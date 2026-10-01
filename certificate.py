"""Cleaning certificate: score delta, applied rules, and sample diffs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from cleaning import ChangeLog
from quality import QualityReport

DROPPED_SAMPLE = 8
CHANGED_SAMPLE = 12
CELL_PREVIEW = 80


def _cell(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value)
    if len(text) > CELL_PREVIEW:
        return text[: CELL_PREVIEW - 1] + "…"
    return text


@dataclass
class CellChange:
    row: str
    column: str
    before: str
    after: str


@dataclass
class CleaningCertificate:
    source_name: str
    generated_at: str
    score_before: int
    score_after: int
    completeness_before: float
    completeness_after: float
    uniqueness_before: float
    uniqueness_after: float
    consistency_before: float
    consistency_after: float
    rows_before: int
    rows_after: int
    cols_before: int
    cols_after: int
    rules: list[str]
    log_rows: list[dict[str, Any]]
    dropped_total: int
    dropped_sample: list[dict[str, str]]
    dropped_columns: list[str]
    changed_total: int
    changed_sample: list[CellChange]
    remaining_findings: int = 0

    @property
    def score_delta(self) -> int:
        return int(self.score_after) - int(self.score_before)

    def as_text(self) -> str:
        delta = self.score_delta
        sign = f"+{delta}" if delta > 0 else str(delta)
        lines = [
            "Data Cleaning Tool — cleaning certificate",
            f"Source: {self.source_name}",
            f"Generated: {self.generated_at}",
            "",
            f"Score: {self.score_before} → {self.score_after} ({sign})",
            f"Completeness: {self.completeness_before:.0f} → {self.completeness_after:.0f}",
            f"Uniqueness: {self.uniqueness_before:.0f} → {self.uniqueness_after:.0f}",
            f"Consistency: {self.consistency_before:.0f} → {self.consistency_after:.0f}",
            f"Rows: {self.rows_before} → {self.rows_after}",
            f"Columns: {self.cols_before} → {self.cols_after}",
            "",
            "Rules applied",
        ]
        for step in self.rules:
            lines.append(f"- {step}")
        lines.append("")
        lines.append(f"Rows removed: {self.dropped_total}")
        if self.dropped_sample:
            lines.append("Sample of removed rows:")
            for rec in self.dropped_sample:
                bits = [f"{k}={v}" for k, v in rec.items() if k != "_row"]
                lines.append(f"  row {rec.get('_row', '?')}: " + "; ".join(bits[:6]))
        lines.append("")
        lines.append(f"Changed cells: {self.changed_total}")
        if self.changed_sample:
            lines.append("Sample of changed cells:")
            for item in self.changed_sample:
                lines.append(
                    f"  row {item.row} / {item.column}: {item.before!r} → {item.after!r}"
                )
        if self.remaining_findings:
            lines.append("")
            lines.append(
                f"Issues still flagged on the cleaned table: {self.remaining_findings}"
            )
        return "\n".join(lines) + "\n"


def dropped_row_sample(
    original: pd.DataFrame,
    cleaned: pd.DataFrame,
    n: int = DROPPED_SAMPLE,
) -> tuple[int, list[dict[str, str]], list[str]]:
    lost_idx = original.index.difference(cleaned.index)
    total = int(len(lost_idx))
    columns = [str(c) for c in original.columns]
    sample: list[dict[str, str]] = []
    if total == 0:
        return 0, sample, columns
    slice_df = original.loc[lost_idx].head(n)
    for idx, row in slice_df.iterrows():
        rec = {"_row": str(idx)}
        for col in original.columns:
            rec[str(col)] = _cell(row[col])
        sample.append(rec)
    return total, sample, columns


def changed_cell_sample(
    original: pd.DataFrame,
    cleaned: pd.DataFrame,
    n: int = CHANGED_SAMPLE,
    rename_map: dict[str, str] | None = None,
) -> tuple[int, list[CellChange]]:
    """Compare original vs cleaned. Renamed columns are aligned by the old name."""
    right = cleaned
    if rename_map:
        reverse = {new: old for old, new in rename_map.items() if new in cleaned.columns}
        if reverse:
            right = cleaned.rename(columns=reverse)
    common_idx = original.index.intersection(right.index)
    common_cols = [c for c in original.columns if c in right.columns]
    if len(common_idx) == 0 or not common_cols:
        return 0, []
    left = original.loc[common_idx, common_cols].apply(lambda col: col.map(_cell))
    right_text = right.loc[common_idx, common_cols].apply(lambda col: col.map(_cell))
    mask = left.ne(right_text)
    total = int(mask.to_numpy().sum())
    if total == 0:
        return 0, []
    hits = mask.stack()
    hits = hits[hits]
    sample: list[CellChange] = []
    for (idx, col) in hits.head(n).index:
        shown = str(col)
        if rename_map and col in rename_map:
            shown = f"{col} → {rename_map[col]}"
        sample.append(
            CellChange(
                row=str(idx),
                column=shown,
                before=str(left.at[idx, col]),
                after=str(right_text.at[idx, col]),
            )
        )
    return total, sample


def build_certificate(
    *,
    source_name: str,
    original: pd.DataFrame,
    cleaned: pd.DataFrame,
    before: QualityReport,
    after: QualityReport,
    log: ChangeLog,
    remaining_findings: int = 0,
) -> CleaningCertificate:
    dropped_total, dropped_sample, dropped_columns = dropped_row_sample(
        original, cleaned
    )
    changed_total, changed_sample = changed_cell_sample(
        original, cleaned, rename_map=log.columns_renamed
    )
    return CleaningCertificate(
        source_name=source_name or "uploaded table",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        score_before=before.score,
        score_after=after.score,
        completeness_before=before.completeness,
        completeness_after=after.completeness,
        uniqueness_before=before.uniqueness,
        uniqueness_after=after.uniqueness,
        consistency_before=before.consistency,
        consistency_after=after.consistency,
        rows_before=log.rows_before,
        rows_after=log.rows_after,
        cols_before=log.cols_before,
        cols_after=log.cols_after,
        rules=list(log.steps),
        log_rows=log.as_rows(),
        dropped_total=dropped_total,
        dropped_sample=dropped_sample,
        dropped_columns=dropped_columns,
        changed_total=changed_total,
        changed_sample=changed_sample,
        remaining_findings=remaining_findings,
    )
