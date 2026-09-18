"""Defensible findings behind the 0–100 quality score."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from fuzzy import FuzzyScan
from quality import EMAIL_RE, QualityReport

_PLACEHOLDERS = {"", "nan", "NaN", "None", "NULL", "null"}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Finding:
    id: str
    severity: str  # high | medium | low
    pillar: str  # completeness | uniqueness | consistency
    title: str
    detail: str
    column: str | None = None
    count: int = 0
    samples: list[str] = field(default_factory=list)
    recommended_fix: str = ""
    fix_key: str | None = None


def _sample_strings(values: pd.Series, limit: int = 5) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for val in values:
        text = str(val).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text[:80])
        if len(out) >= limit:
            break
    return out


def _severity_for_share(count: int, n_rows: int, high: float = 0.1, medium: float = 0.02) -> str:
    if n_rows <= 0 or count <= 0:
        return "low"
    share = count / n_rows
    if share >= high:
        return "high"
    if share >= medium:
        return "medium"
    return "low"


def collect_findings(
    df: pd.DataFrame,
    report: QualityReport,
    fuzzy_scan: FuzzyScan | None = None,
) -> list[Finding]:
    """Turn the quality report into a reviewable list of issues."""
    findings: list[Finding] = []
    n_rows = report.n_rows

    if report.exact_duplicate_rows:
        dupes = df[df.duplicated(keep="first")]
        findings.append(
            Finding(
                id="exact-duplicates",
                severity=_severity_for_share(report.exact_duplicate_rows, n_rows, high=0.05, medium=0.01),
                pillar="uniqueness",
                title=f"{report.exact_duplicate_rows:,} duplicate row{'s' if report.exact_duplicate_rows != 1 else ''}",
                detail="The same row appears more than once. That can inflate counts later.",
                count=report.exact_duplicate_rows,
                samples=_sample_strings(dupes.astype(str).agg(" · ".join, axis=1), 3),
                recommended_fix="Keep the first copy of each duplicate row",
                fix_key="drop_exact_duplicates",
            )
        )

    for col in report.columns:
        series = df[col.name]
        if col.missing_pct == 100:
            findings.append(
                Finding(
                    id=f"empty-column:{col.name}",
                    severity="high",
                    pillar="completeness",
                    title=f"Column “{col.name}” is completely empty",
                    detail="This column has no values. Removing it will not lose any rows.",
                    column=col.name,
                    count=col.missing_count,
                    recommended_fix="Remove empty columns",
                    fix_key="drop_empty_columns",
                )
            )
        elif col.missing_count:
            findings.append(
                Finding(
                    id=f"missing:{col.name}",
                    severity=_severity_for_share(col.missing_count, n_rows, high=0.4, medium=0.1),
                    pillar="completeness",
                    title=f"{col.missing_pct:.1f}% empty in “{col.name}”",
                    detail=f"{col.missing_count:,} empty cell{'s' if col.missing_count != 1 else ''}. Filling or dropping is a choice — preview first.",
                    column=col.name,
                    count=col.missing_count,
                    recommended_fix="Open Advanced to fill empty cells or drop rows",
                    fix_key=None,
                )
            )
        if col.empty_string_count:
            as_str = series.astype(str)
            mask = (~series.isna()) & as_str.str.strip().isin(_PLACEHOLDERS)
            findings.append(
                Finding(
                    id=f"placeholders:{col.name}",
                    severity="low",
                    pillar="completeness",
                    title=f"{col.empty_string_count:,} placeholder{'s' if col.empty_string_count != 1 else ''} in “{col.name}”",
                    detail="Words like NULL, NaN, or blank text instead of a truly empty cell.",
                    column=col.name,
                    count=col.empty_string_count,
                    samples=_sample_strings(series[mask], 5),
                    recommended_fix="Trim extra spaces (placeholders often become empty)",
                    fix_key="trim_whitespace",
                )
            )
        if len(col.date_formats) > 1:
            findings.append(
                Finding(
                    id=f"dates:{col.name}",
                    severity="medium",
                    pillar="consistency",
                    title=f"{len(col.date_formats)} date formats in “{col.name}”",
                    detail="Mixed formats: " + ", ".join(col.date_formats) + ".",
                    column=col.name,
                    count=len(col.date_formats),
                    samples=col.date_formats,
                    recommended_fix="Turn this column into real dates",
                    fix_key="fix_dates",
                )
            )
        if col.invalid_email_count:
            values = series.dropna().astype(str).str.strip()
            bad = values[~values.map(lambda v: bool(EMAIL_RE.match(v)))]
            findings.append(
                Finding(
                    id=f"email:{col.name}",
                    severity=_severity_for_share(col.invalid_email_count, n_rows, high=0.1, medium=0.02),
                    pillar="consistency",
                    title=f"{col.invalid_email_count:,} invalid email(s) in “{col.name}”",
                    detail="These do not look like name@domain. Trim and lowercase often fixes the easy ones.",
                    column=col.name,
                    count=col.invalid_email_count,
                    samples=_sample_strings(bad, 5),
                    recommended_fix="Trim and lowercase email columns",
                    fix_key="fix_emails",
                )
            )
        if col.invalid_phone_count:
            values = series.dropna().astype(str)
            digits = values.map(lambda v: re.sub(r"\D", "", v))
            bad = values[(digits.str.len() < 7) | (digits.str.len() > 15)]
            findings.append(
                Finding(
                    id=f"phone:{col.name}",
                    severity=_severity_for_share(col.invalid_phone_count, n_rows, high=0.1, medium=0.02),
                    pillar="consistency",
                    title=f"{col.invalid_phone_count:,} invalid phone(s) in “{col.name}”",
                    detail="After removing punctuation, these have fewer than 7 or more than 15 digits.",
                    column=col.name,
                    count=col.invalid_phone_count,
                    samples=_sample_strings(bad, 5),
                    recommended_fix="Standardize phones to digits",
                    fix_key="normalize_phones",
                )
            )

        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            padded = series.dropna().astype(str)
            padded = padded[padded.str.strip() != padded]
            if len(padded):
                findings.append(
                    Finding(
                        id=f"whitespace:{col.name}",
                        severity="low",
                        pillar="consistency",
                        title=f"Extra spaces in “{col.name}”",
                        detail=f"{len(padded):,} value{'s' if len(padded) != 1 else ''} would change if trimmed — a common false duplicate.",
                        column=col.name,
                        count=int(len(padded)),
                        samples=_sample_strings(padded.map(lambda v: repr(v)), 4),
                        recommended_fix="Trim extra spaces on text",
                        fix_key="trim_whitespace",
                    )
                )
            sample = series.dropna().astype(str).head(80)
            if not sample.empty and sample.str.contains(r"[\$€£¥₹]|,\d{3}", regex=True).mean() >= 0.3:
                findings.append(
                    Finding(
                        id=f"currency:{col.name}",
                        severity="low",
                        pillar="consistency",
                        title=f"“{col.name}” looks like currency text",
                        detail="Symbols or thousands separators will block sums and averages.",
                        column=col.name,
                        count=int(sample.str.contains(r"[\$€£¥₹]", regex=True).sum()),
                        samples=_sample_strings(sample, 4),
                        recommended_fix="Turn currency text into numbers",
                        fix_key="strip_currency",
                    )
                )

    if fuzzy_scan and fuzzy_scan.groups:
        skip_fuzzy = {
            c.name
            for c in report.columns
            if c.inferred_role in {"email", "phone", "date", "id"}
        }
        by_col: dict[str, int] = {}
        samples_by_col: dict[str, list[str]] = {}
        for group in fuzzy_scan.groups:
            if group.column in skip_fuzzy:
                continue
            by_col[group.column] = by_col.get(group.column, 0) + 1
            shown = " / ".join(group.variants[:3])
            samples_by_col.setdefault(group.column, []).append(shown)
        for column, n_groups in by_col.items():
            findings.append(
                Finding(
                    id=f"fuzzy:{column}",
                    severity="medium",
                    pillar="uniqueness",
                    title=f"{n_groups:,} similar-spelling group{'s' if n_groups != 1 else ''} in “{column}”",
                    detail="Same person or label written more than one way (case, spaces, small typos).",
                    column=column,
                    count=n_groups,
                    samples=samples_by_col.get(column, [])[:4],
                    recommended_fix="Merge similar spellings to the spelling you keep",
                    fix_key="collapse_fuzzy",
                )
            )

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), -f.count, f.title))
    return findings
