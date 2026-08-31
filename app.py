import streamlit as st

from io_files import FileReadError, read_uploaded_file

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

frames: dict[str, object] = {}
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
