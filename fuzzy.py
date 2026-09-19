"""Near-duplicate detection for text columns using difflib (stdlib only)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

DEFAULT_THRESHOLD = 0.85
MAX_UNIQUE = 5000
MAX_BLOCK = 400


@dataclass
class FuzzyGroup:
    column: str
    variants: list[str]
    counts: dict[str, int]
    suggested: str
    reasons: list[str] = field(default_factory=list)
    similarity: float = 1.0
    group_id: str = ""


@dataclass
class FuzzyScan:
    groups: list[FuzzyGroup] = field(default_factory=list)
    skipped_columns: list[str] = field(default_factory=list)
    skipped_unique_counts: dict[str, int] = field(default_factory=dict)
    sampled_columns: dict[str, int] = field(default_factory=dict)
    truncated_blocks: dict[str, int] = field(default_factory=dict)
    scanned_columns: list[str] = field(default_factory=list)


def _is_text_column(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
        return False
    sample = series.dropna().head(50)
    if sample.empty:
        return False
    as_str = sample.astype(str)
    # Mostly numeric strings → skip (IDs, phones handled elsewhere).
    numericish = pd.to_numeric(as_str.str.replace(r"[,\s]", "", regex=True), errors="coerce")
    if numericish.notna().mean() > 0.8:
        return False
    return True


def _normalize(value: str) -> str:
    return " ".join(str(value).strip().split()).casefold()


def _similar(a: str, b: str, threshold: float) -> bool:
    if not a or not b:
        return False
    # Cheap length gate before SequenceMatcher.
    la, lb = len(a), len(b)
    if min(la, lb) / max(la, lb) < 0.6:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def explain_match(variants: list[str]) -> tuple[float, list[str]]:
    """Why these values were grouped: casing, spacing, and/or similarity %."""
    reasons: list[str] = []
    if any(v != v.strip() or "  " in v for v in variants):
        reasons.append("spacing")
    stripped = [v.strip() for v in variants]
    folded = {s.casefold() for s in stripped}
    if len(set(stripped)) > len(folded):
        reasons.append("casing")
    norms = [_normalize(v) for v in variants]
    distinct = list(dict.fromkeys(norms))
    if len(distinct) <= 1:
        similarity = 1.0
        if not reasons:
            reasons.append("identical after trim")
        return similarity, reasons
    ratios = [
        SequenceMatcher(None, a, b).ratio()
        for i, a in enumerate(distinct)
        for b in distinct[i + 1 :]
    ]
    similarity = min(ratios) if ratios else 1.0
    reasons.append(f"{int(round(similarity * 100))}% similar")
    return similarity, reasons


def _group_id(column: str, variants: list[str]) -> str:
    blob = column + "\0" + "\0".join(sorted(variants))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _cluster(uniques: list[str], threshold: float) -> tuple[list[list[str]], int]:
    """Union-find on normalized similarity; keep original spellings in each cluster."""
    by_norm: dict[str, list[str]] = defaultdict(list)
    for val in uniques:
        by_norm[_normalize(val)].append(val)
    norms = list(by_norm.keys())
    parent = {n: n for n in norms}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Block by first character to avoid O(n²) on large unique sets.
    blocks: dict[str, list[str]] = defaultdict(list)
    for n in norms:
        key = n[:2] if n else ""
        blocks[key].append(n)

    truncated = 0
    for members in blocks.values():
        if len(members) > MAX_BLOCK:
            truncated += len(members) - MAX_BLOCK
            members = members[:MAX_BLOCK]
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if _similar(a, b, threshold):
                    union(a, b)

    clusters: dict[str, list[str]] = defaultdict(list)
    for n in norms:
        clusters[find(n)].extend(by_norm[n])
    return [vals for vals in clusters.values() if len(vals) > 1], truncated


def scan_fuzzy_duplicates(
    df: pd.DataFrame,
    threshold: float = DEFAULT_THRESHOLD,
    max_unique: int = MAX_UNIQUE,
    force_columns: set[str] | None = None,
) -> FuzzyScan:
    scan = FuzzyScan()
    force_columns = force_columns or set()
    for col in df.columns:
        series = df[col]
        if not _is_text_column(series):
            continue
        values = series.dropna().astype(str)
        values = values[values.str.strip().ne("")]
        uniques = values.unique().tolist()
        col_name = str(col)
        if len(uniques) > max_unique and col_name not in force_columns:
            scan.skipped_columns.append(col_name)
            scan.skipped_unique_counts[col_name] = len(uniques)
            continue
        counts = values.value_counts().to_dict()
        if len(uniques) > max_unique and col_name in force_columns:
            uniques = list(values.value_counts().head(max_unique).index)
            scan.sampled_columns[col_name] = len(counts)
        scan.scanned_columns.append(col_name)
        clusters, leftover = _cluster(uniques, threshold)
        if leftover:
            scan.truncated_blocks[col_name] = leftover
        for variants in clusters:
            def _rank(v: str) -> tuple:
                stripped = v.strip()
                return (
                    counts.get(v, 0),
                    stripped[:1].isupper() and not stripped.isupper(),
                    stripped == v,
                    len(stripped),
                )

            suggested = max(variants, key=_rank)
            similarity, reasons = explain_match(variants)
            scan.groups.append(
                FuzzyGroup(
                    column=col_name,
                    variants=sorted(variants, key=lambda v: (-counts.get(v, 0), v)),
                    counts={v: int(counts.get(v, 0)) for v in variants},
                    suggested=suggested,
                    reasons=reasons,
                    similarity=similarity,
                    group_id=_group_id(col_name, variants),
                )
            )
    return scan
