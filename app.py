import streamlit as st

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
