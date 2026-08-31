# Data Cleaning Tool

A Streamlit **data-quality inspector**. Upload messy spreadsheets and it diagnoses problems you may not have noticed, scores overall quality, applies reviewable cleaning steps, then exports the result plus a change log.

## What it does

- Accepts CSV and Excel (`.csv`, `.xlsx`, `.xls`), including **multiple files you can merge**
- Diagnoses missing values, exact duplicates, inconsistent dates, empty placeholders, and likely ID / email / phone columns
- Shows a **0–100 data quality score** (completeness 40%, uniqueness 30%, consistency 30%) *before* you change anything
- Finds **fuzzy near-duplicates** in text (stdlib `difflib`, skipped on columns with > 5,000 unique values)
- Cleaning you can review: duplicates, whitespace, dates, casing, emails, phones, currency, missing values, renames, empty rows/columns
- Before/after view and a downloadable cleaning summary

## How to run

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

## Requirements

- Python 3.9+
- See `requirements.txt` (streamlit, pandas, openpyxl, xlrd)
