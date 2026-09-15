"""Printable PDF for a cleaning certificate."""

from __future__ import annotations

from io import BytesIO

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from certificate import CleaningCertificate

INK = (32, 28, 24)
MUTED = (112, 102, 92)
COPPER = (196, 146, 58)
RULE = (228, 216, 198)
PAPER = (252, 248, 242)


def _txt(value: object) -> str:
    text = "" if value is None else str(value)
    replacements = {
        "→": "->",
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
        "·": "-",
        "×": "x",
    }
    for src, dest in replacements.items():
        text = text.replace(src, dest)
    return text.encode("latin-1", "replace").decode("latin-1")


class _CertificatePDF(FPDF):
    def header(self) -> None:
        self.set_fill_color(*PAPER)
        self.rect(0, 0, self.w, self.h, "F")
        self.set_draw_color(*COPPER)
        self.set_line_width(1.1)
        self.line(18, 12, self.w - 18, 12)
        self.set_xy(18, 15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, "DATA CLEANING TOOL  /  CLEANING CERTIFICATE")
        self.ln(8)

    def footer(self) -> None:
        self.set_y(-18)
        self.set_draw_color(*RULE)
        self.set_line_width(0.3)
        self.line(18, self.get_y(), self.w - 18, self.get_y())
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(
            0,
            8,
            _txt(
                f"Page {self.page_no()}  /  Proof of applied rules, not a legal attestation"
            ),
        )


def _heading(pdf: FPDF, title: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(0, 8, _txt(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*COPPER)
    pdf.set_line_width(0.35)
    pdf.line(18, pdf.get_y(), 52, pdf.get_y())
    pdf.ln(4)


def _metric_row(pdf: FPDF, items: list[tuple[str, str]]) -> None:
    col_w = (pdf.w - 36) / max(len(items), 1)
    y = pdf.get_y()
    for i, (label, value) in enumerate(items):
        x = 18 + i * col_w
        pdf.set_xy(x, y)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.cell(col_w - 4, 5, _txt(label).upper())
        pdf.set_xy(x, y + 5)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(*INK)
        pdf.cell(col_w - 4, 9, _txt(value))
    pdf.set_y(y + 16)


def render_certificate_pdf(cert: CleaningCertificate) -> bytes:
    delta = cert.score_delta
    sign = f"+{delta}" if delta >= 0 else str(delta)
    pdf = _CertificatePDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*INK)
    pdf.cell(0, 12, "Cleaning certificate", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        0,
        5,
        _txt(f"{cert.source_name}  /  generated {cert.generated_at}"),
    )
    pdf.ln(4)

    _metric_row(
        pdf,
        [
            ("Score before", str(cert.score_before)),
            ("Score after", str(cert.score_after)),
            ("Change", sign),
        ],
    )
    _metric_row(
        pdf,
        [
            ("Rows in / out", f"{cert.rows_before} -> {cert.rows_after}"),
            ("Columns in / out", f"{cert.cols_before} -> {cert.cols_after}"),
            (
                "Completeness",
                f"{cert.completeness_before:.0f} -> {cert.completeness_after:.0f}",
            ),
        ],
    )
    _metric_row(
        pdf,
        [
            (
                "Uniqueness",
                f"{cert.uniqueness_before:.0f} -> {cert.uniqueness_after:.0f}",
            ),
            (
                "Consistency",
                f"{cert.consistency_before:.0f} -> {cert.consistency_after:.0f}",
            ),
            ("Dropped rows", str(cert.dropped_total)),
        ],
    )

    _heading(pdf, "Rules applied")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*INK)
    if not cert.rules:
        pdf.multi_cell(0, 6, "No cleaning steps were recorded.")
    else:
        for i, step in enumerate(cert.rules, start=1):
            pdf.multi_cell(0, 6, _txt(f"{i:02d}.  {step}"))
            pdf.ln(1)

    _heading(pdf, "Sample of dropped rows")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*INK)
    if cert.dropped_total == 0:
        pdf.multi_cell(0, 6, "No rows were removed.")
    else:
        pdf.multi_cell(
            0,
            6,
            _txt(
                f"{cert.dropped_total} row(s) left the table. Showing up to "
                f"{len(cert.dropped_sample)}."
            ),
        )
        pdf.ln(1)
        preview_cols = [c for c in cert.dropped_columns[:4]]
        pdf.set_font("Helvetica", "", 8)
        for rec in cert.dropped_sample:
            bits = [f"{col}={rec.get(col, '')}" for col in preview_cols]
            pdf.multi_cell(
                0, 5, _txt(f"row {rec.get('_row', '?')}  /  " + "  |  ".join(bits))
            )
            pdf.ln(0.5)

    _heading(pdf, "Sample of changed cells")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*INK)
    if cert.changed_total == 0:
        pdf.multi_cell(0, 6, "No remaining cells changed value.")
    else:
        pdf.multi_cell(
            0,
            6,
            _txt(
                f"{cert.changed_total} cell(s) changed. Showing up to "
                f"{len(cert.changed_sample)}."
            ),
        )
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 8)
        for item in cert.changed_sample:
            pdf.multi_cell(
                0,
                5,
                _txt(
                    f"row {item.row} / {item.column}:  {item.before or '(empty)'}  ->  "
                    f"{item.after or '(empty)'}"
                ),
            )
            pdf.ln(0.5)

    if cert.remaining_findings:
        _heading(pdf, "Still open")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*INK)
        pdf.multi_cell(
            0,
            6,
            _txt(
                f"{cert.remaining_findings} finding(s) still appear on the cleaned table."
            ),
        )

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()
