import streamlit as st
import pandas as pd

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


def render_fuzzy_scan(df: pd.DataFrame) -> None:
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
        return
    if not scan.groups:
        st.success("No near-duplicate groups found in the scanned text columns.")
        return

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
            st.caption("Apply cleaning later to collapse these to the suggested value.")


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
selected = names[0] if len(names) == 1 else st.selectbox("Preview file", names)
df = frames[selected]

st.subheader(f"Preview — {selected}")
st.caption(f"{len(df):,} rows × {len(df.columns):,} columns")
st.dataframe(df, use_container_width=True)

render_quality_report(build_quality_report(df))
render_fuzzy_scan(df)
