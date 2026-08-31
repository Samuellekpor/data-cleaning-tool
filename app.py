from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from cleaning import CleaningOptions, apply_cleaning, preview_duplicate_rows
from fuzzy import scan_fuzzy_duplicates
from io_files import FileReadError, merge_frames, read_uploaded_file
from quality import QualityReport, build_quality_report

st.set_page_config(page_title="Data Cleaning Tool", layout="wide")

st.sidebar.header("Also useful")
st.sidebar.markdown(
    "📊 Need a polished report from your cleaned data? Use the "
    "[Excel Report Automator](https://github.com/placeholder/excel-report-automator) →"
)
st.sidebar.caption("How to use this tool")
st.sidebar.markdown(
    """
    1. Upload CSV or Excel (one file or several).
    2. Read the **quality score** and column diagnosis first.
    3. Review fuzzy near-duplicate groups.
    4. Tick cleaning steps and check the preview.
    5. Apply, compare before/after, then download.
    """
)

st.title("Data Cleaning Tool")
st.markdown(
    """
    Upload messy spreadsheets and this app **inspects them like a data-quality
    auditor**. It finds missing values, duplicates, inconsistent dates, and
    suspicious ID/email/phone columns — then gives you a score and
    reviewable fixes.

    You see the diagnosis **before** anything is changed, so you learn what
    is wrong just by uploading.
    """
)


def _score_caption(score: int) -> str:
    if score >= 85:
        return "Solid — only polish remaining."
    if score >= 70:
        return "Usable, but a few issues will bite you later."
    if score >= 50:
        return "Messy — cleaning will save you real time."
    return "High risk — do not analyze this as-is."


def render_quality_report(report: QualityReport) -> None:
    st.header("2. Data quality report")
    st.caption("This is the diagnosis from the raw file. Nothing has been cleaned yet.")

    st.metric(
        "Your data quality score",
        f"{report.score}/100",
        help="Weighted: completeness 40%, uniqueness 30%, consistency 30%.",
    )
    st.progress(report.score / 100.0)
    st.caption(_score_caption(report.score))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Completeness", f"{report.completeness:.0f}/100")
    c2.metric("Uniqueness", f"{report.uniqueness:.0f}/100")
    c3.metric("Consistency", f"{report.consistency:.0f}/100")
    c4.metric("Exact duplicate rows", f"{report.exact_duplicate_rows:,}")

    for note in report.notes:
        st.markdown(f"- {note}")

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
    st.subheader("Column-by-column diagnosis")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_fuzzy_scan(df: pd.DataFrame):
    st.header("3. Fuzzy near-duplicates")
    st.caption(
        "Exact duplicates are already in the score above. This looks for "
        "**almost** the same text — extra spaces, casing, or a typo — so you "
        "can pick one spelling to keep."
    )
    scan = scan_fuzzy_duplicates(df)
    if scan.skipped_columns:
        st.info(
            "Fuzzy matching was skipped for performance on columns with more "
            "than 5,000 unique values: "
            + ", ".join(scan.skipped_columns)
        )
    if not scan.scanned_columns:
        st.write("No text columns were small enough to scan.")
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
            st.caption("Tick “Collapse near-duplicates” below to apply the suggested values.")
    return scan


def collect_cleaning_options(df: pd.DataFrame, has_fuzzy: bool) -> CleaningOptions:
    st.header("4. Cleaning operations")
    st.caption("Tick what you want, then apply. Nothing changes until you click the button.")

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
    options.trim_whitespace = st.checkbox("Trim whitespace on text columns", value=True)
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
    st.subheader("What will change (preview)")
    st.caption("This is a dry look at the current file — nothing is applied yet.")
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
        st.write("Near-duplicates will be collapsed to the suggested values shown in section 3.")
    if options.missing_strategy == "drop_rows":
        st.write(
            f"Rows with any missing value that would be removed: **{int(df.isna().any(axis=1).sum()):,}**"
        )


def render_before_after(original: pd.DataFrame, cleaned: pd.DataFrame, log) -> None:
    st.header("5. Before vs after")
    after_report = build_quality_report(cleaned)
    b1, b2, b3 = st.columns(3)
    b1.metric("Rows", f"{log.rows_after:,}", delta=log.rows_after - log.rows_before)
    b2.metric("Columns", f"{log.cols_after:,}", delta=log.cols_after - log.cols_before)
    b3.metric("Quality score after", f"{after_report.score}/100")

    st.subheader("Change summary")
    st.dataframe(pd.DataFrame(log.as_rows()), use_container_width=True, hide_index=True)
    for step in log.steps:
        st.markdown(f"- {step}")

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
    st.header("6. Export")
    st.caption("Download the cleaned table and a short proof of what changed.")
    csv_data = cleaned.to_csv(index=False).encode("utf-8")
    excel_data = _excel_bytes(cleaned)
    summary_text = log.as_text()
    summary_csv = pd.DataFrame(log.as_rows()).to_csv(index=False).encode("utf-8")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "Download CSV",
            data=csv_data,
            file_name="cleaned_data.csv",
            mime="text/csv",
        )
    with c2:
        st.download_button(
            "Download Excel",
            data=excel_data,
            file_name="cleaned_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with c3:
        st.download_button(
            "Download cleaning summary (txt)",
            data=summary_text,
            file_name="cleaning_summary.txt",
            mime="text/plain",
        )
    st.download_button(
        "Download cleaning summary (CSV)",
        data=summary_csv,
        file_name="cleaning_summary.csv",
        mime="text/csv",
    )


st.header("1. Upload your data")
st.caption("CSV or Excel. You can add more than one file.")

uploads = st.file_uploader(
    "Choose files",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    help="Accepted formats: .xlsx, .xls, .csv",
)

if not uploads:
    st.info("Drop a file above to get started.")
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
    st.subheader("Merge files")
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
    st.session_state.pop("cleaned", None)
    st.session_state.pop("log", None)
    st.session_state.pop("original", None)

st.subheader(f"Preview — {selected}")
st.caption(f"{len(df):,} rows × {len(df.columns):,} columns")
st.dataframe(df, use_container_width=True)

render_quality_report(build_quality_report(df))
fuzzy_scan = render_fuzzy_scan(df)
has_fuzzy = bool(fuzzy_scan and fuzzy_scan.groups)

options = collect_cleaning_options(df, has_fuzzy)
render_pre_apply_preview(df, options)

if st.button("Apply cleaning", type="primary"):
    cleaned, log = apply_cleaning(df, options)
    st.session_state["cleaned"] = cleaned
    st.session_state["log"] = log
    st.session_state["original"] = df
    st.success("Cleaning applied. Review the before/after below.")

cleaned = st.session_state.get("cleaned")
log = st.session_state.get("log")
original = st.session_state.get("original")
if cleaned is not None and log is not None and original is not None:
    render_before_after(original, cleaned, log)
    render_export(cleaned, log)
