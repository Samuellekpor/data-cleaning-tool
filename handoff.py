"""Package the cleaned table plus certificate for Excel Report Automator."""

from __future__ import annotations

import zipfile
from io import BytesIO

HOWTO_BRIEF = """How to brief this cleaned table

1. Open Excel Report Automator (use the button in the Data Cleaning Tool, or run that app locally).
2. Upload cleaned_data.xlsx from this folder — that is the spreadsheet, not the PDF.
3. Keep cleaning_certificate.pdf with the briefing if someone needs a paper trail.

The Automator reads CSV and Excel tables only. Do not upload the PDF as the data file.
"""


def build_handoff_zip(*, excel_bytes: bytes, pdf_bytes: bytes) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("cleaned_data.xlsx", excel_bytes)
        archive.writestr("cleaning_certificate.pdf", pdf_bytes)
        archive.writestr("HOW_TO_BRIEF.txt", HOWTO_BRIEF)
    return buffer.getvalue()
