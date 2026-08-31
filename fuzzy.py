"""Near-duplicate detection for text columns using difflib (stdlib only)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

DEFAULT_THRESHOLD = 0.85
MAX_UNIQUE = 5000


@dataclass
class FuzzyGroup:
    column: str
    variants: list[str]
    counts: dict[str, int]
    suggested: str


@dataclass
class FuzzyScan:
    groups: list[FuzzyGroup] = field(default_factory=list)
    skipped_columns: list[str] = field(default_factory=list)
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


def _cluster(uniques: list[str], threshold: float) -> list[list[str]]:
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

    for members in blocks.values():
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if _similar(a, b, threshold):
                    union(a, b)

    clusters: dict[str, list[str]] = defaultdict(list)
    for n in norms:
        clusters[find(n)].extend(by_norm[n])
    return [vals for vals in clusters.values() if len(vals) > 1]


def scan_fuzzy_duplicates(
    df: pd.DataFrame,
    threshold: float = DEFAULT_THRESHOLD,
    max_unique: int = MAX_UNIQUE,
) -> FuzzyScan:
    scan = FuzzyScan()
    for col in df.columns:
        series = df[col]
        if not _is_text_column(series):
            continue
        values = series.dropna().astype(str)
        values = values[values.str.strip().ne("")]
        uniques = values.unique().tolist()
        if len(uniques) > max_unique:
            scan.skipped_columns.append(str(col))
            continue
        scan.scanned_columns.append(str(col))
        counts = values.value_counts().to_dict()
        for variants in _cluster(uniques, threshold):
            def _rank(v: str) -> tuple:
                stripped = v.strip()
                return (
                    counts.get(v, 0),
                    stripped[:1].isupper() and not stripped.isupper(),
                    stripped == v,
                    len(stripped),
                )

            suggested = max(variants, key=_rank)
            scan.groups.append(
                FuzzyGroup(
                    column=str(col),
                    variants=sorted(variants, key=lambda v: (-counts.get(v, 0), v)),
                    counts={v: int(counts.get(v, 0)) for v in variants},
                    suggested=suggested,
                )
            )
    return scan
