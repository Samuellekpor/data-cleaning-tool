# Data Cleaning Tool

A Streamlit **data-quality inspector**. Upload messy CSV or Excel, see what is wrong, choose a plan, then export a cleaned table plus a certificate you can send with the file.

It is the step before a briefing, not a silent pandas script. Companion product: [Excel Report Automator](https://github.com/Samuellekpor/excel-report-automator).

## What it does

- Accepts `.csv`, `.xlsx`, and `.xls` (several files can be stacked into one table)
- Flags empty cells, duplicate rows, mixed date formats, placeholders, and likely ID / email / phone columns
- Shows a **0–100 quality score** before anything is cleaned — completeness 40%, uniqueness 30%, consistency 30%
- Lists **findings** with severity, column, samples, and a suggested fix
- Finds **similar spellings** in text (`difflib`). Columns with more than 5,000 unique values are skipped unless you turn on Also scan (then the 5,000 most common values are scanned)
- Lets you **choose a plan**: skip any step, then apply from the original file in one pass
- Named starting plans: **From findings**, **CRM contacts**, **Transactions**, **Survey**
- Save the current plan as JSON and reload it, or reuse the last plan on the next file
- Result: score before → after, change log, before/after tables
- Export: cleaned CSV/Excel, certificate PDF, text/CSV summaries, and a briefing pack for the Automator. CSV/Excel prefix a quote on cells that look like spreadsheet formulas (`=`, `+`, `-`, `@`).
- Advanced toolkit (casing, fills, row drops, renames) stays behind an expander

The pandas operations never run until you apply the plan or apply Advanced.

## How to run

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

## Workflow

1. **Upload** — drop files. Combine only when the tables are the same kind.
2. **Score** — read the findings. Nothing has been cleaned yet.
3. **Similar spellings** — pick a keeper per group, or skip a group / column.
4. **Plan** — start from findings or a named profile, skip steps, optionally save or load a plan JSON, then Apply this plan.
5. **Result** — score before → after and the change log.
6. **Files** — download the table, the certificate, and (if you want a briefing) the Automator pack.

## Requirements

- Python 3.9+
- `requirements.txt`: streamlit, pandas, openpyxl, xlrd, fpdf2

## Layout

| File | Role |
| --- | --- |
| `app.py` | Streamlit wiring |
| `views.py` | Score, plan, result, and export UI |
| `ui.py` | OLED / copper chrome |
| `quality.py` | Score and column diagnosis |
| `findings.py` | Reviewable issue list |
| `fuzzy.py` | Near-duplicate scan |
| `recipe.py` / `profiles.py` / `recipe_io.py` | Plan, named profiles, JSON recipes |
| `cleaning.py` | Reviewable operations and change log |
| `certificate.py` / `certificate_pdf.py` | Proof of what changed |
| `handoff.py` | Zip for Excel Report Automator |
| `io_files.py` | CSV / Excel load and merge |

## Not in this branch

Column contracts (fail the score if a field breaks a rule), a messy sample in the empty state, and a hard “preview before any row drop” gate on Apply this plan are not shipped yet.
