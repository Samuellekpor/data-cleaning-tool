"""Diagnose data-quality issues and compute a 0–100 score."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
# Phones: digits plus typical separators, not ISO-looking dates (YYYY-MM-DD).
PHONE_RE = re.compile(
    r"^(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{2,4}\)?[\s.\-]?)?\d{3,4}[\s.\-]?\d{3,4}$"
)
ID_NAME_RE = re.compile(r"(^|_)(id|uuid|guid|pk|sku)(_|$)|(^id$)|_id$", re.I)

# Distinct date *patterns* we can spot in string data (not pandas dtypes).
DATE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("YYYY-MM-DD", re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")),
    ("DD/MM/YYYY or MM/DD/YYYY", re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")),
    ("DD-MM-YYYY or MM-DD-YYYY", re.compile(r"^\d{1,2}-\d{1,2}-\d{2,4}$")),
    ("YYYY/MM/DD", re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")),
    ("DD.MM.YYYY", re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")),
    ("Month DD, YYYY", re.compile(r"^[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}$")),
    ("DD-Mon-YYYY", re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{2,4}$")),
    ("ISO datetime", re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")),
]


@dataclass
class ColumnDiagnosis:
    name: str
    missing_count: int
    missing_pct: float
    empty_string_count: int
    inferred_role: str | None  # id | email | phone | date | None
    date_formats: list[str] = field(default_factory=list)
    invalid_email_count: int = 0
    invalid_phone_count: int = 0


@dataclass
class QualityReport:
    n_rows: int
    n_cols: int
    exact_duplicate_rows: int
    overall_missing_pct: float
    completeness: float
    uniqueness: float
    consistency: float
    score: int
    columns: list[ColumnDiagnosis]
    notes: list[str]


def _non_null_strings(series: pd.Series) -> pd.Series:
    s = series.dropna().astype(str).str.strip()
    return s[s.ne("") & s.str.lower().ne("nan") & s.str.lower().ne("none")]


def infer_role(name: str, series: pd.Series) -> str | None:
    values = _non_null_strings(series)
    if values.empty:
        if ID_NAME_RE.search(str(name)):
            return "id"
        return None

    sample = values.head(200)
    email_hits = sample.map(lambda v: bool(EMAIL_RE.match(v))).mean()
    date_hits = sample.map(lambda v: _match_date_formats(v) is not None).mean()
    phone_hits = sample.map(
        lambda v: bool(PHONE_RE.match(v)) and _match_date_formats(v) is None
    ).mean()

    if email_hits >= 0.6:
        return "email"
    if date_hits >= 0.6:
        return "date"
    if phone_hits >= 0.6:
        return "phone"
    if ID_NAME_RE.search(str(name)):
        return "id"

    nunique = values.nunique()
    numeric = pd.to_numeric(values, errors="coerce")
    numeric_ratio = numeric.notna().mean()
    if nunique == len(values) and numeric_ratio > 0.9 and len(values) >= 10:
        return "id"
    return None


def _match_date_formats(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    for label, pattern in DATE_PATTERNS:
        if pattern.match(text):
            return label
    return None


def detect_date_formats(series: pd.Series) -> list[str]:
    values = _non_null_strings(series)
    if values.empty:
        return []
    found: dict[str, int] = {}
    for val in values.head(2000):
        label = _match_date_formats(val)
        if label:
            found[label] = found.get(label, 0) + 1
    return [k for k, _ in sorted(found.items(), key=lambda kv: -kv[1])]


def diagnose_column(name: str, series: pd.Series) -> ColumnDiagnosis:
    n = len(series)
    missing = int(series.isna().sum())
    as_str = series.astype(str)
    empty_mask = (~series.isna()) & as_str.str.strip().isin(
        ["", "nan", "NaN", "None", "NULL", "null"]
    )
    empty = int(empty_mask.sum())
    role = infer_role(name, series)
    formats = detect_date_formats(series) if role in {"date", None} else []
    # If mixed date formats showed up, treat as date even without role.
    if len(formats) >= 2:
        role = role or "date"

    invalid_email = 0
    invalid_phone = 0
    values = _non_null_strings(series)
    if role == "email" and not values.empty:
        invalid_email = int((~values.map(lambda v: bool(EMAIL_RE.match(v)))).sum())
    if role == "phone" and not values.empty:
        digits = values.map(lambda v: re.sub(r"\D", "", v))
        invalid_phone = int(((digits.str.len() < 7) | (digits.str.len() > 15)).sum())

    return ColumnDiagnosis(
        name=str(name),
        missing_count=missing,
        missing_pct=round(100.0 * missing / n, 2) if n else 0.0,
        empty_string_count=empty,
        inferred_role=role,
        date_formats=formats,
        invalid_email_count=invalid_email,
        invalid_phone_count=invalid_phone,
    )


def _consistency_score(columns: list[ColumnDiagnosis], n_rows: int) -> float:
    """100 = consistent formats; penalties for mixed dates and invalid emails/phones."""
    if not columns or n_rows == 0:
        return 100.0
    penalties = 0.0
    checked = 0
    for col in columns:
        if col.date_formats:
            checked += 1
            if len(col.date_formats) > 1:
                penalties += min(40.0, 15.0 * (len(col.date_formats) - 1))
        if col.inferred_role == "email":
            checked += 1
            if col.invalid_email_count:
                penalties += min(40.0, 100.0 * col.invalid_email_count / max(n_rows, 1))
        if col.inferred_role == "phone":
            checked += 1
            if col.invalid_phone_count:
                penalties += min(40.0, 100.0 * col.invalid_phone_count / max(n_rows, 1))
    if checked == 0:
        # No format-sensitive columns: treat as fully consistent.
        return 100.0
    avg_penalty = penalties / checked
    return max(0.0, 100.0 - avg_penalty)


def build_quality_report(df: pd.DataFrame) -> QualityReport:
    n_rows, n_cols = df.shape
    columns = [diagnose_column(col, df[col]) for col in df.columns]
    exact_dups = int(df.duplicated().sum()) if n_rows else 0
    total_cells = n_rows * n_cols if n_cols else 0
    missing_cells = int(df.isna().sum().sum()) if total_cells else 0
    overall_missing_pct = (100.0 * missing_cells / total_cells) if total_cells else 0.0

    completeness = max(0.0, 100.0 - overall_missing_pct)
    uniqueness = (
        100.0 * (1.0 - exact_dups / n_rows) if n_rows else 100.0
    )
    consistency = _consistency_score(columns, n_rows)
    score = int(round(0.40 * completeness + 0.30 * uniqueness + 0.30 * consistency))

    notes: list[str] = []
    mixed_dates = [c.name for c in columns if len(c.date_formats) > 1]
    if mixed_dates:
        notes.append(
            "Mixed date formats in: " + ", ".join(mixed_dates)
        )
    role_cols = [c for c in columns if c.inferred_role]
    if role_cols:
        parts = [
            f"{c.name} looks like a {c.inferred_role}"
            for c in role_cols
        ]
        notes.append("; ".join(parts) + ".")
    empty_cols = [c.name for c in columns if c.missing_pct == 100]
    if empty_cols:
        notes.append("Completely empty columns: " + ", ".join(empty_cols) + ".")
    if exact_dups:
        notes.append(f"{exact_dups:,} exact duplicate row(s) found.")
    if not notes:
        notes.append("No obvious structural issues jumped out — still review the score breakdown.")

    return QualityReport(
        n_rows=n_rows,
        n_cols=n_cols,
        exact_duplicate_rows=exact_dups,
        overall_missing_pct=round(overall_missing_pct, 2),
        completeness=round(completeness, 1),
        uniqueness=round(uniqueness, 1),
        consistency=round(consistency, 1),
        score=max(0, min(100, score)),
        columns=columns,
        notes=notes,
    )
