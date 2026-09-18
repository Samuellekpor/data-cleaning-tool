"""Reviewable cleaning operations and a structured change log."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fuzzy import FuzzyGroup, scan_fuzzy_duplicates
from quality import detect_date_formats, infer_role

CURRENCY_RE = re.compile(r"[\$€£¥₹,\s]")


@dataclass
class CleaningOptions:
    drop_exact_duplicates: bool = False
    duplicate_subset: list[str] | None = None
    trim_whitespace: bool = False
    fix_dates: bool = False
    dayfirst: bool = False
    casing: str = "none"  # none | title | lower | upper
    fix_emails: bool = False
    normalize_phones: bool = False
    phone_format: str = "digits"  # digits | dashed
    strip_currency: bool = False
    missing_strategy: str = "leave"  # leave | drop_rows | drop_columns | fill
    fill_value: str = ""
    numeric_fill: str = "none"  # none | mean | median
    missing_threshold_pct: float = 100.0
    rename_style: str = "none"  # none | snake | lower
    manual_renames: dict[str, str] = field(default_factory=dict)
    drop_empty_rows: bool = False
    drop_empty_columns: bool = False
    collapse_fuzzy: bool = False
    fuzzy_groups: list[FuzzyGroup] | None = None


@dataclass
class ChangeLog:
    rows_before: int = 0
    cols_before: int = 0
    rows_after: int = 0
    cols_after: int = 0
    duplicates_dropped: int = 0
    empty_rows_removed: int = 0
    empty_cols_removed: int = 0
    missing_filled: int = 0
    columns_renamed: dict[str, str] = field(default_factory=dict)
    dates_parsed: list[str] = field(default_factory=list)
    standardized: list[str] = field(default_factory=list)
    fuzzy_collapsed: int = 0
    steps: list[str] = field(default_factory=list)

    def as_rows(self) -> list[dict[str, Any]]:
        return [
            {"item": "Rows before", "value": self.rows_before},
            {"item": "Rows after", "value": self.rows_after},
            {"item": "Columns before", "value": self.cols_before},
            {"item": "Columns after", "value": self.cols_after},
            {"item": "Duplicate rows removed", "value": self.duplicates_dropped},
            {"item": "Empty rows removed", "value": self.empty_rows_removed},
            {"item": "Empty columns removed", "value": self.empty_cols_removed},
            {"item": "Empty cells filled", "value": self.missing_filled},
            {"item": "Similar spellings merged", "value": self.fuzzy_collapsed},
            {
                "item": "Columns renamed",
                "value": ", ".join(f"{a} → {b}" for a, b in self.columns_renamed.items())
                or "—",
            },
            {
                "item": "Date columns fixed",
                "value": ", ".join(self.dates_parsed) or "—",
            },
            {
                "item": "Standardized",
                "value": ", ".join(self.standardized) or "—",
            },
        ]

    def as_text(self) -> str:
        lines = ["Data Cleaning Tool — cleaning summary", ""]
        for row in self.as_rows():
            lines.append(f"{row['item']}: {row['value']}")
        lines.append("")
        lines.append("Steps")
        for step in self.steps:
            lines.append(f"- {step}")
        return "\n".join(lines) + "\n"


def _text_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c])
    ]


def _snake(name: str) -> str:
    text = re.sub(r"[^\w\s]", "", str(name), flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text.strip())
    return text.lower()


def preview_duplicate_rows(df: pd.DataFrame, subset: list[str] | None) -> pd.DataFrame:
    if df.empty:
        return df
    cols = subset or list(df.columns)
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return df.iloc[0:0]
    return df[df.duplicated(subset=cols, keep="first")].copy()


def options_from_fix_keys(
    keys: list[str],
    *,
    dayfirst: bool = False,
    fuzzy_groups: list | None = None,
) -> CleaningOptions:
    """Turn finding fix keys into a single CleaningOptions payload."""
    opts = CleaningOptions()
    for key in keys:
        if key == "drop_exact_duplicates":
            opts.drop_exact_duplicates = True
        elif key == "collapse_fuzzy":
            opts.collapse_fuzzy = True
        elif key == "fix_dates":
            opts.fix_dates = True
        elif key == "fix_emails":
            opts.fix_emails = True
        elif key == "normalize_phones":
            opts.normalize_phones = True
        elif key == "drop_empty_columns":
            opts.drop_empty_columns = True
        elif key == "trim_whitespace":
            opts.trim_whitespace = True
        elif key == "strip_currency":
            opts.strip_currency = True
    opts.dayfirst = dayfirst
    if fuzzy_groups is not None:
        opts.fuzzy_groups = list(fuzzy_groups)
    return opts


def apply_cleaning(
    df: pd.DataFrame, options: CleaningOptions
) -> tuple[pd.DataFrame, ChangeLog]:
    out = df.copy()
    log = ChangeLog(rows_before=len(df), cols_before=len(df.columns))

    if options.trim_whitespace:
        for col in _text_columns(out):
            out[col] = out[col].map(
                lambda v: v.strip() if isinstance(v, str) else v
            )
        log.steps.append("Trimmed extra spaces on text columns.")
        log.standardized.append("whitespace")

    if options.collapse_fuzzy:
        groups = (
            options.fuzzy_groups
            if options.fuzzy_groups is not None
            else scan_fuzzy_duplicates(out).groups
        )
        collapsed = 0
        merged_groups = 0
        for group in groups:
            mapping = {v: group.suggested for v in group.variants if v != group.suggested}
            if mapping:
                matched = out[group.column].isin(mapping.keys())
                collapsed += int(matched.sum())
                merged_groups += 1
                out[group.column] = out[group.column].replace(mapping)
        log.fuzzy_collapsed = collapsed
        if collapsed:
            log.steps.append(
                f"Merged {collapsed} similar-spelling value(s) across {merged_groups} group(s)."
            )
        elif not groups:
            log.steps.append("Similar-spelling merge skipped — no groups were selected.")

    if options.casing != "none":
        fn = {"title": str.title, "lower": str.lower, "upper": str.upper}[options.casing]
        for col in _text_columns(out):
            if infer_role(col, out[col]) in {"email", "id"}:
                continue
            out[col] = out[col].map(lambda v, f=fn: f(v) if isinstance(v, str) else v)
        log.steps.append(f"Applied {options.casing} casing to text columns (skipped emails/IDs).")
        log.standardized.append(f"casing:{options.casing}")

    if options.fix_emails:
        for col in out.columns:
            if infer_role(col, out[col]) != "email" and "email" not in str(col).lower():
                continue
            out[col] = out[col].map(_clean_email)
            log.standardized.append(f"email:{col}")
        log.steps.append("Lowercased and trimmed values in email-like columns.")

    if options.normalize_phones:
        for col in out.columns:
            role = infer_role(col, out[col])
            if role != "phone" and "phone" not in str(col).lower() and "mobile" not in str(col).lower():
                continue
            out[col] = out[col].map(
                lambda v: _clean_phone(v, options.phone_format)
            )
            log.standardized.append(f"phone:{col}")
        log.steps.append("Standardized phone numbers (punctuation removed).")

    if options.strip_currency:
        for col in out.columns:
            converted = _strip_currency_series(out[col])
            if converted is not None:
                out[col] = converted
                log.standardized.append(f"currency:{col}")
        if any(s.startswith("currency:") for s in log.standardized):
            log.steps.append("Turned currency text into numbers (symbols and commas removed).")

    if options.fix_dates:
        for col in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[col]):
                continue
            formats = detect_date_formats(out[col])
            role = infer_role(col, out[col])
            if not formats and role != "date" and "date" not in str(col).lower():
                continue
            parsed = pd.to_datetime(out[col], errors="coerce", dayfirst=options.dayfirst)
            if parsed.notna().sum() >= max(1, int(0.5 * out[col].notna().sum())):
                out[col] = parsed
                log.dates_parsed.append(str(col))
        if log.dates_parsed:
            log.steps.append(
                "Fixed date-like columns"
                + (" (day-first)." if options.dayfirst else ".")
            )

    if options.drop_empty_columns:
        before = list(out.columns)
        out = out.dropna(axis=1, how="all")
        removed = [c for c in before if c not in out.columns]
        log.empty_cols_removed = len(removed)
        if removed:
            log.steps.append("Removed empty columns: " + ", ".join(map(str, removed)))

    if options.drop_empty_rows:
        before_n = len(out)
        out = out.dropna(how="all")
        log.empty_rows_removed = before_n - len(out)
        if log.empty_rows_removed:
            log.steps.append(f"Removed {log.empty_rows_removed} completely empty row(s).")

    if options.missing_strategy == "drop_rows":
        before_n = len(out)
        out = out.dropna(how="any")
        dropped = before_n - len(out)
        log.steps.append(f"Removed {dropped} row(s) that still had empty cells.")
    elif options.missing_strategy == "drop_columns":
        drop = [
            c
            for c in out.columns
            if (100.0 * out[c].isna().sum() / max(len(out), 1))
            >= options.missing_threshold_pct
        ]
        if drop:
            out = out.drop(columns=drop)
            log.steps.append(
                "Removed columns that were mostly empty "
                f"({options.missing_threshold_pct:.0f}%+ empty): " + ", ".join(map(str, drop))
            )
    elif options.missing_strategy == "fill":
        filled = 0
        for col in out.columns:
            na = out[col].isna()
            if not na.any():
                continue
            if options.numeric_fill in {"mean", "median"} and pd.api.types.is_numeric_dtype(out[col]):
                stat = out[col].mean() if options.numeric_fill == "mean" else out[col].median()
                filled += int(na.sum())
                out[col] = out[col].fillna(stat)
            elif options.fill_value != "" and not pd.api.types.is_datetime64_any_dtype(out[col]):
                filled += int(na.sum())
                out[col] = out[col].fillna(options.fill_value)
        log.missing_filled = filled
        if filled:
            log.steps.append(f"Filled {filled} empty cell(s).")

    if options.drop_exact_duplicates:
        before_n = len(out)
        subset = options.duplicate_subset or None
        if subset:
            subset = [c for c in subset if c in out.columns] or None
        out = out.drop_duplicates(subset=subset, keep="first")
        log.duplicates_dropped = before_n - len(out)
        log.steps.append(
            f"Removed {log.duplicates_dropped} duplicate row(s)"
            + (f" (matched on: {', '.join(subset)})." if subset else ".")
        )

    rename_map: dict[str, str] = {}
    if options.rename_style == "snake":
        rename_map = {c: _snake(str(c)) for c in out.columns}
    elif options.rename_style == "lower":
        rename_map = {c: str(c).strip().lower() for c in out.columns}
    for src, dest in options.manual_renames.items():
        dest = dest.strip()
        if src in out.columns and dest and dest != src:
            rename_map[src] = dest
    rename_map = {a: b for a, b in rename_map.items() if a != b}
    if rename_map:
        # avoid collisions
        used = set()
        safe = {}
        for old, new in rename_map.items():
            candidate = new
            i = 2
            while candidate in used or (candidate in out.columns and candidate != old):
                candidate = f"{new}_{i}"
                i += 1
            used.add(candidate)
            safe[old] = candidate
        out = out.rename(columns=safe)
        log.columns_renamed = safe
        log.steps.append("Renamed columns: " + ", ".join(f"{a} → {b}" for a, b in safe.items()))

    log.rows_after = len(out)
    log.cols_after = len(out.columns)
    if not log.steps:
        log.steps.append("No cleaning steps were selected.")
    return out, log


def _clean_email(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip().lower()
    return text


def _clean_phone(value: Any, fmt: str) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return value
    if fmt == "dashed" and len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    if fmt == "dashed" and len(digits) == 11:
        return f"{digits[0]}-{digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    return digits


def _strip_currency_series(series: pd.Series) -> pd.Series | None:
    if pd.api.types.is_numeric_dtype(series):
        return None
    sample = series.dropna().astype(str).head(80)
    if sample.empty:
        return None
    looks = sample.str.contains(r"[\$€£¥₹]|,", regex=True).mean()
    if looks < 0.3:
        return None
    cleaned = series.map(
        lambda v: CURRENCY_RE.sub("", v) if isinstance(v, str) else v
    )
    numeric = pd.to_numeric(cleaned, errors="coerce")
    if numeric.notna().sum() >= max(1, int(0.5 * series.notna().sum())):
        return numeric
    return None
