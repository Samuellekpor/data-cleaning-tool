from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from cleaning import CleaningOptions, apply_cleaning, options_from_fix_keys, preview_duplicate_rows
from findings import collect_findings
from fuzzy import scan_fuzzy_duplicates
from io_files import FileReadError, merge_frames, read_uploaded_file
from quality import QualityReport, build_quality_report
from ui import (
    bento_tiles,
    finding_cards,
    hero,
    inject_theme,
    note_cards,
    quality_score_bento,
    section_header,
    sidebar_chrome,
)

st.set_page_config(
    page_title="Data Cleaning Tool",
    layout="wide",
    # Open on desktop; collapse on narrow viewports so Protocol does not cover the hero.
    initial_sidebar_state="auto",
)

inject_theme()

with st.sidebar:
    sidebar_chrome()

hero()


def _score_caption(score: int) -> str:
    if score >= 85:
        return "Solid — only polish remaining."
    if score >= 70:
        return "Usable, but a few issues will bite you later."
    if score >= 50:
        return "Messy — cleaning will save you real time."
    return "High risk — do not analyze this as-is."


def render_quality_report(df: pd.DataFrame, report: QualityReport, fuzzy_scan) -> None:
    section_header(
        "02  ·  Diagnosis",
        "Data quality report",
        "The score is a headline. The findings below are why it is that number.",
    )
    findings = collect_findings(df, report, fuzzy_scan)
    high = sum(1 for f in findings if f.severity == "high")
    caption = _score_caption(report.score)
    if findings:
        caption = f"{caption} {len(findings)} finding(s), {high} high."
    quality_score_bento(
        report.score,
        caption,
        report.completeness,
        report.uniqueness,
        report.consistency,
        report.exact_duplicate_rows,
    )
    finding_cards(findings)

    rows = []
    for col in report.columns:
        rows.append(
            {
                "column": col.name,
                "looks like": col.inferred_role or "—",
                "missing %": col.missing_pct,
                "missing count": col.missing_count,
                "empty / placeholder values": col.empty_string_count,
                "date formats seen": ", ".join(col.date_formats) or "—",
                "invalid emails": col.invalid_email_count,
                "invalid phones": col.invalid_phone_count,
            }
        )
    st.caption("Column-by-column diagnosis")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    return findings


def render_fuzzy_scan(scan) -> None:
    section_header(
        "03  ·  Near-matches",
        "Fuzzy duplicates",
        "Exact copies are already in the score. This finds extra spaces, casing, and near-typos.",
    )
    if scan.skipped_columns:
        st.info(
            "Fuzzy matching was skipped for performance on columns with more "
            "than 5,000 unique values: "
            + ", ".join(scan.skipped_columns)
        )
    if not scan.scanned_columns:
        st.info("No text columns were small enough to scan.")
        return scan
    if not scan.groups:
        st.success("No near-duplicate groups found in the scanned text columns.")
        return scan

    st.warning(f"Found {len(scan.groups)} near-duplicate group(s) to review.")
    for group in scan.groups:
        with st.expander(
            f"{group.column}: {len(group.variants)} spellings → keep “{group.suggested}”"
        ):
            preview = pd.DataFrame(
                {
                    "value": group.variants,
                    "rows": [group.counts[v] for v in group.variants],
                    "suggested keep": [v == group.suggested for v in group.variants],
                }
            )
            st.dataframe(preview, use_container_width=True, hide_index=True)
            st.caption("Tick “Collapse near-duplicates” in advanced cleaning to apply the suggested values.")
    return scan


def _commit_clean(original: pd.DataFrame, cleaned: pd.DataFrame, log) -> None:
    st.session_state["working"] = cleaned
    st.session_state["cleaned"] = cleaned
    st.session_state["original"] = original
    st.session_state["log"] = log
    steps = list(st.session_state.get("applied_steps") or [])
    steps.extend(log.steps)
    st.session_state["applied_steps"] = steps


def render_finding_actions(working: pd.DataFrame, original: pd.DataFrame, findings) -> None:
    actionable = [f for f in findings if f.fix_key]
    if not actionable:
        return
    st.caption("Apply a recommended fix. The working table and score refresh immediately.")
    seen: set[str] = set()
    keys: list[str] = []
    for finding in actionable:
        if finding.fix_key in seen:
            continue
        seen.add(finding.fix_key)
        keys.append(finding.fix_key)
        if st.button(finding.recommended_fix, key=f"fix_{finding.fix_key}"):
            cleaned, log = apply_cleaning(working, options_from_fix_keys([finding.fix_key]))
            _commit_clean(original, cleaned, log)
            st.rerun()
    if st.button("Apply all recommended fixes", type="primary"):
        cleaned, log = apply_cleaning(working, options_from_fix_keys(keys))
        _commit_clean(original, cleaned, log)
        st.rerun()


def collect_cleaning_options(df: pd.DataFrame, has_fuzzy: bool) -> CleaningOptions:
    with st.expander("Advanced operations — full toolkit"):
        st.caption("Use this when a finding has no one-click fix, or you want extra control.")
        return _collect_cleaning_options_body(df, has_fuzzy)


def _collect_cleaning_options_body(df: pd.DataFrame, has_fuzzy: bool) -> CleaningOptions:
    options = CleaningOptions()

    st.subheader("Duplicates")
    options.drop_exact_duplicates = st.checkbox(
        "Remove exact duplicate rows",
        help="Keeps the first copy of each duplicated row.",
    )
    if options.drop_exact_duplicates:
        options.duplicate_subset = st.multiselect(
            "Compare duplicates using these columns only (optional)",
            list(df.columns),
            help="Leave empty to compare entire rows.",
        ) or None
    options.collapse_fuzzy = st.checkbox(
        "Collapse near-duplicates to the suggested spelling",
        disabled=not has_fuzzy,
        help="Uses the fuzzy groups shown above.",
    )

    st.subheader("Text, dates, and numbers")
    options.trim_whitespace = st.checkbox("Trim whitespace on text columns")
    options.fix_dates = st.checkbox("Fix date-like columns (parse to datetime)")
    if options.fix_dates:
        options.dayfirst = st.checkbox(
            "Dates are day-first (DD/MM/YYYY)",
            help="Turn this on for most non-US date formats.",
        )
    options.casing = st.selectbox(
        "Standardize text casing",
        ["none", "title", "lower", "upper"],
        format_func=lambda x: {
            "none": "Leave casing as-is",
            "title": "Title Case",
            "lower": "lowercase",
            "upper": "UPPERCASE",
        }[x],
    )
    options.fix_emails = st.checkbox("Validate / fix emails (trim + lowercase)")
    options.normalize_phones = st.checkbox("Normalize phone numbers")
    if options.normalize_phones:
        options.phone_format = st.radio(
            "Phone format",
            ["digits", "dashed"],
            format_func=lambda x: "Digits only" if x == "digits" else "###-###-####",
            horizontal=True,
        )
    options.strip_currency = st.checkbox(
        "Strip currency symbols and commas from numbers ($1,234 → 1234)"
    )

    st.subheader("Missing values")
    options.missing_strategy = st.selectbox(
        "How to handle missing values",
        ["leave", "drop_rows", "drop_columns", "fill"],
        format_func=lambda x: {
            "leave": "Leave missing values",
            "drop_rows": "Remove rows that have any missing value",
            "drop_columns": "Remove columns that are mostly missing",
            "fill": "Fill missing values",
        }[x],
    )
    if options.missing_strategy == "drop_columns":
        options.missing_threshold_pct = st.slider(
            "Drop column if missing % is at least",
            min_value=10,
            max_value=100,
            value=100,
        )
    if options.missing_strategy == "fill":
        options.numeric_fill = st.selectbox(
            "Numeric columns",
            ["none", "mean", "median"],
            format_func=lambda x: {
                "none": "Do not auto-fill numbers",
                "mean": "Fill with mean",
                "median": "Fill with median",
            }[x],
        )
        options.fill_value = st.text_input(
            "Fill other columns with this value (optional)",
            placeholder="e.g. Unknown",
        )

    st.subheader("Columns and empty cells")
    options.rename_style = st.selectbox(
        "Rename columns",
        ["none", "snake", "lower"],
        format_func=lambda x: {
            "none": "Keep names",
            "snake": "lowercase with underscores",
            "lower": "lowercase (keep spaces)",
        }[x],
    )
    with st.expander("Manual column renames"):
        manual = {}
        for col in df.columns:
            new = st.text_input(f"{col}", value=str(col), key=f"rename_{col}")
            if new.strip() and new.strip() != str(col):
                manual[col] = new.strip()
        options.manual_renames = manual
    options.drop_empty_columns = st.checkbox("Remove completely empty columns")
    options.drop_empty_rows = st.checkbox("Remove completely empty rows")
    return options


def render_pre_apply_preview(df: pd.DataFrame, options: CleaningOptions) -> None:
    st.caption("What will change — a dry look. Nothing is applied yet.")
    if options.drop_exact_duplicates:
        dupes = preview_duplicate_rows(df, options.duplicate_subset)
        st.write(f"Exact duplicate rows that would be dropped: **{len(dupes):,}**")
        if not dupes.empty:
            st.dataframe(dupes.head(50), use_container_width=True)
            if len(dupes) > 50:
                st.caption(f"Showing first 50 of {len(dupes):,}.")
    if options.drop_empty_columns:
        empty_cols = [c for c in df.columns if df[c].isna().all()]
        st.write(
            "Empty columns that would be removed: "
            + (", ".join(map(str, empty_cols)) if empty_cols else "none")
        )
    if options.drop_empty_rows:
        empty_rows = int(df.isna().all(axis=1).sum())
        st.write(f"Completely empty rows that would be removed: **{empty_rows:,}**")
    if options.collapse_fuzzy:
        st.write("Near-duplicates will be collapsed to the suggested values shown above.")
    if options.missing_strategy == "drop_rows":
        st.write(
            f"Rows with any missing value that would be removed: **{int(df.isna().any(axis=1).sum()):,}**"
        )


def render_before_after(original: pd.DataFrame, cleaned: pd.DataFrame, log) -> None:
    section_header(
        "05  ·  Receipt",
        "Before vs after",
        "Proof of what changed — then download the cleaned table.",
    )
    after_report = build_quality_report(cleaned)
    bento_tiles(
        [
            ("era-tile-lg", "Rows", f"{log.rows_after:,}", f"Was {log.rows_before:,}"),
            ("era-tile", "Columns", f"{log.cols_after:,}", f"Was {log.cols_before:,}"),
            ("era-tile", "Score after", f"{after_report.score}/100", "Quality on the cleaned table"),
        ]
    )
    st.caption("Change summary")
    st.dataframe(pd.DataFrame(log.as_rows()), use_container_width=True, hide_index=True)
    note_cards(log.steps)

    before_tab, after_tab = st.tabs(["Before", "After"])
    with before_tab:
        st.caption(f"{len(original):,} rows × {len(original.columns):,} columns")
        st.dataframe(original, use_container_width=True)
    with after_tab:
        st.caption(f"{len(cleaned):,} rows × {len(cleaned.columns):,} columns")
        st.dataframe(cleaned, use_container_width=True)


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="cleaned")
    return buffer.getvalue()


def render_export(cleaned: pd.DataFrame, log) -> None:
    section_header(
        "06  ·  Deliverable",
        "Export",
        "The cleaned table, plus a small change log you can keep as proof.",
    )
    csv_data = cleaned.to_csv(index=False).encode("utf-8")
    excel_data = _excel_bytes(cleaned)
    summary_text = log.as_text()
    summary_csv = pd.DataFrame(log.as_rows()).to_csv(index=False).encode("utf-8")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "Download CSV  ↗",
            data=csv_data,
            file_name="cleaned_data.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "Download Excel  ↗",
            data=excel_data,
            file_name="cleaned_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with c3:
        st.download_button(
            "Summary (txt)  ↗",
            data=summary_text,
            file_name="cleaning_summary.txt",
            mime="text/plain",
            use_container_width=True,
        )
    st.download_button(
        "Summary (CSV)  ↗",
        data=summary_csv,
        file_name="cleaning_summary.csv",
        mime="text/csv",
        use_container_width=True,
    )


section_header(
    "01  ·  Intake",
    "Upload your data",
    "CSV or Excel. Several files can be stacked into one table.",
)

uploads = st.file_uploader(
    "Choose files",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    help="Accepted formats: .xlsx, .xls, .csv",
    label_visibility="collapsed",
)

if not uploads:
    st.info("Start by dropping a spreadsheet. The quality score appears before anything is cleaned.")
    st.stop()

frames: dict[str, pd.DataFrame] = {}
errors: list[str] = []

for uploaded in uploads:
    try:
        frames[uploaded.name] = read_uploaded_file(uploaded)
    except FileReadError as exc:
        errors.append(str(exc))

for message in errors:
    st.error(message)

if not frames:
    st.warning("No readable files yet. Fix the errors above or try another file.")
    st.stop()

names = list(frames.keys())
merge = False
if len(frames) > 1:
    merge = st.checkbox(
        "Merge files (stack rows into one table)",
        help="Use this when each file is the same kind of table.",
    )
    header_sets = [tuple(map(str, f.columns)) for f in frames.values()]
    if merge and len(set(header_sets)) > 1:
        st.warning(
            "Column headers differ between files. The merge will line up "
            "matching names and leave blanks where a file is missing a column."
        )
        with st.expander("Headers in each file"):
            for name, cols in zip(frames.keys(), header_sets):
                st.write(f"**{name}:** {', '.join(cols)}")

if merge:
    df, _headers_differ = merge_frames(frames)
    selected = "(merged)"
else:
    selected = names[0] if len(names) == 1 else st.selectbox("Working file", names)
    df = frames[selected]
file_key = f"{selected}:{len(df)}:{tuple(df.columns)}"
if st.session_state.get("file_key") != file_key:
    st.session_state["file_key"] = file_key
    st.session_state["source"] = df.copy()
    st.session_state["working"] = df.copy()
    st.session_state["applied_steps"] = []
    st.session_state.pop("cleaned", None)
    st.session_state.pop("log", None)
    st.session_state.pop("original", None)

source = st.session_state.get("source", df)
working = st.session_state.get("working", df)

section_header(
    "Receipt",
    f"Preview — {selected}",
    f"{len(working):,} rows × {len(working.columns):,} columns in the working table.",
)
st.dataframe(working, use_container_width=True)

fuzzy_scan = scan_fuzzy_duplicates(working)
findings = render_quality_report(working, build_quality_report(working), fuzzy_scan)
render_fuzzy_scan(fuzzy_scan)
has_fuzzy = bool(fuzzy_scan.groups)

section_header(
    "04  ·  Operations",
    "Fix what the score found",
    "Recommended fixes first. The full toolkit stays in Advanced.",
)
render_finding_actions(working, source, findings)
options = collect_cleaning_options(working, has_fuzzy)
render_pre_apply_preview(working, options)

if st.button("Apply cleaning", type="primary"):
    cleaned, log = apply_cleaning(working, options)
    _commit_clean(source, cleaned, log)
    st.success("Cleaning applied. Review the before/after below.")
    st.rerun()

cleaned = st.session_state.get("cleaned")
log = st.session_state.get("log")
original = st.session_state.get("original")
if cleaned is not None and log is not None and original is not None:
    render_before_after(original, cleaned, log)
    render_export(cleaned, log)
