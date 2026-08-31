# Data Cleaning Tool

A Streamlit data-quality inspector. Upload messy spreadsheets and it **diagnoses problems you may not have noticed**, scores overall quality, then applies reviewable cleaning steps — not just a pile of pandas buttons.

## What it does

- Accepts CSV and Excel files (including multiple files you can merge)
- Diagnoses missing values, duplicates, date/format issues, and likely ID/email/phone columns
- Shows a **0–100 data quality score** before you change anything
- Finds **fuzzy near-duplicates** in text columns
- Lets you apply cleaning with a before/after review and a change log
- Exports cleaned data plus a cleaning summary

## How to run

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).
