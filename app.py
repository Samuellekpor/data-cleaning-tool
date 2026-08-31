import streamlit as st
import pandas as pd

from cleaning import CleaningOptions, apply_cleaning
from fuzzy import scan_fuzzy_duplicates
from io_files import FileReadError, read_uploaded_file
from quality import QualityReport, build_quality_report

st.set_page_config(page_title="Data Cleaning Tool", layout="wide")

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
selected = names[0] if len(names) == 1 else st.selectbox("Working file", names)
df = frames[selected]

st.subheader(f"Preview — {selected}")
st.caption(f"{len(df):,} rows × {len(df.columns):,} columns")
st.dataframe(df, use_container_width=True)

render_quality_report(build_quality_report(df))
fuzzy_scan = render_fuzzy_scan(df)
has_fuzzy = bool(fuzzy_scan and fuzzy_scan.groups)

options = collect_cleaning_options(df, has_fuzzy)

if st.button("Apply cleaning", type="primary"):
    cleaned, log = apply_cleaning(df, options)
    st.session_state["cleaned"] = cleaned
    st.session_state["log"] = log
    st.success("Cleaning applied. Scroll down to review the result.")

cleaned = st.session_state.get("cleaned")
if cleaned is not None:
    st.subheader("Cleaned data")
    st.dataframe(cleaned, use_container_width=True)
    log = st.session_state.get("log")
    if log:
        st.write("Steps:")
        for step in log.steps:
            st.markdown(f"- {step}")
