from __future__ import annotations

import io
from dataclasses import replace

import pandas as pd
import streamlit as st

from certificate import build_certificate
from certificate_pdf import render_certificate_pdf
from cleaning import CleaningOptions, preview_duplicate_rows
from findings import Finding, collect_findings
from fuzzy import MAX_UNIQUE, FuzzyGroup
from handoff import build_handoff_zip
from io_files import neutralize_formula_cells
from profiles import CleaningProfile, PROFILES, get_profile
from quality import QualityReport, build_quality_report
from recipe import recipe_line
from ui import (
    EXCEL_REPORT_AUTOMATOR_URL,
    bento_tiles,
    finding_cards,
    handoff_card,
    note_cards,
    quality_score_bento,
    recipe_banner,
    section_header,
)

PREVIEW_ROWS = 200


def show_frame(df: pd.DataFrame) -> None:
    st.dataframe(df.head(PREVIEW_ROWS), use_container_width=True)
    if len(df) > PREVIEW_ROWS:
        st.caption(f"Showing first {PREVIEW_ROWS:,} of {len(df):,} rows.")


def _score_caption(score: int) -> str:
    if score >= 85:
        return "Solid — only polish remaining."
    if score >= 70:
        return "Usable, but a few issues will bite you later."
    if score >= 50:
        return "Messy — cleaning will save you real time."
    return "High risk — do not analyze this as-is."


def render_quality_report(df: pd.DataFrame, report: QualityReport, fuzzy_scan) -> list[Finding]:
    section_header(
        "02  ·  Diagnosis",
        "Data quality report",
        "The score is a headline. The findings below are why it is that number.",
    )
    findings = collect_findings(df, report, fuzzy_scan)
    high = sum(1 for f in findings if f.severity == "high")
    caption = _score_caption(report.score)
    if findings:
        caption = f"{caption} {len(findings)} finding(s), {high} high."
    quality_score_bento(
        report.score,
        caption,
        report.completeness,
        report.uniqueness,
        report.consistency,
        report.exact_duplicate_rows,
    )
    finding_cards(findings)

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
    st.caption("Column-by-column diagnosis")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    return findings


def render_fuzzy_scan(scan) -> list[FuzzyGroup]:
    section_header(
        "03  ·  Near-matches",
        "Fuzzy duplicates",
        "Pick a keeper per group. Uncheck a group or skip a column to leave those spellings alone.",
    )
    if scan.skipped_columns:
        st.warning(
            "These columns were not scanned — too many unique values for a full pass. "
            f"Scan anyway uses the {MAX_UNIQUE:,} most common values, not every spelling."
        )
        prefix = str(st.session_state.get("file_key", ""))
        for col in scan.skipped_columns:
            n = scan.skipped_unique_counts.get(col, 0)
            st.checkbox(
                f"Scan “{col}” anyway ({n:,} unique values)",
                value=False,
                key=f"fuzzy_force_{prefix}_{col}",
                help=f"Scans the {MAX_UNIQUE:,} most common values in this column (not every unique).",
            )
    if scan.sampled_columns:
        bits = [
            f"{col} ({n:,} unique, scanned top {MAX_UNIQUE:,})"
            for col, n in scan.sampled_columns.items()
        ]
        st.caption("Sampled for speed: " + "; ".join(bits))
    if not scan.scanned_columns:
        st.info("No text columns were small enough to scan.")
        st.session_state["fuzzy_selected"] = []
        return []
    if not scan.groups:
        st.success("No near-duplicate groups found in the scanned text columns.")
        st.session_state["fuzzy_selected"] = []
        return []

    st.warning(f"Found {len(scan.groups)} near-duplicate group(s) to review.")
    prefix = str(st.session_state.get("file_key", ""))
    selected: list[FuzzyGroup] = []
    by_column: dict[str, list] = {}
    for group in scan.groups:
        by_column.setdefault(group.column, []).append(group)

    for column, groups in by_column.items():
        skip_col = st.checkbox(
            f"Skip column “{column}”",
            value=False,
            key=f"fuzzy_skipcol_{prefix}_{column}",
            help="Leave every spelling in this column unchanged.",
        )
        if skip_col:
            continue
        for group in groups:
            why = ", ".join(group.reasons) if group.reasons else "similar text"
            with st.expander(
                f"{column}: {len(group.variants)} spellings · {why} → keep “{group.suggested}”"
            ):
                include = st.checkbox(
                    "Merge this group",
                    value=True,
                    key=f"fuzzy_inc_{prefix}_{group.group_id}",
                )
                preview = pd.DataFrame(
                    {
                        "value": group.variants,
                        "rows": [group.counts[v] for v in group.variants],
                    }
                )
                st.dataframe(preview, use_container_width=True, hide_index=True)
                st.caption(f"Why: {why}.")
                default_idx = group.variants.index(group.suggested) if group.suggested in group.variants else 0
                keeper = st.radio(
                    "Keep this spelling",
                    group.variants,
                    index=default_idx,
                    key=f"fuzzy_keep_{prefix}_{group.group_id}",
                )
                if include:
                    chosen = FuzzyGroup(
                        column=group.column,
                        variants=group.variants,
                        counts=group.counts,
                        suggested=keeper,
                        reasons=group.reasons,
                        similarity=group.similarity,
                        group_id=group.group_id,
                    )
                    selected.append(chosen)
    st.session_state["fuzzy_selected"] = selected
    st.caption(f"{len(selected)} group(s) will merge if you include Collapse near-duplicates in the plan.")
    return selected

def render_profile_picker() -> CleaningProfile:
    profile_id = st.radio(
        "Starting plan",
        [p.id for p in PROFILES],
        format_func=lambda i: get_profile(i).label,
        horizontal=True,
        key="cleaning_profile",
        help="A profile seeds the checkboxes. Skip any step you do not want.",
    )
    profile = get_profile(profile_id)
    st.caption(profile.summary)
    return profile


def render_recipe_editor(recipe, profile: CleaningProfile) -> tuple[list[str], bool]:
    """Let the user accept, skip, or tweak the proposed plan. Does not apply yet."""
    token = f"{st.session_state.get('file_key')}:{profile.id}"
    if st.session_state.get("_profile_token") != token:
        st.session_state["_profile_token"] = token
        wanted = {s.fix_key for s in recipe if s.default_include}
        for step in recipe:
            st.session_state[f"recipe_{step.fix_key}"] = step.fix_key in wanted
        st.session_state["recipe_dayfirst"] = bool(profile.dayfirst)

    included: list[str] = []
    for step in recipe:
        cols = st.columns([0.12, 0.88])
        with cols[0]:
            on = st.checkbox(
                step.label,
                value=step.default_include,
                key=f"recipe_{step.fix_key}",
                label_visibility="collapsed",
            )
        with cols[1]:
            status = "in plan" if on else "skipped"
            st.markdown(
                f"**{step.label}** · {step.highest_severity} · {status}  \n"
                f"{step.summary}"
            )
        if on:
            included.append(step.fix_key)
    recipe_banner(recipe_line(recipe, included))
    dayfirst = False
    if "fix_dates" in included:
        dayfirst = st.checkbox(
            "Dates are day-first (DD/MM/YYYY)",
            help="Turn this on for most non-US date formats.",
            key="recipe_dayfirst",
        )
    return included, dayfirst


def collect_cleaning_options(df: pd.DataFrame, has_fuzzy: bool) -> CleaningOptions:
    with st.expander("Advanced operations — full toolkit"):
        st.caption("Use this for fills, row drops, casing, and renames that are not in the plan.")
        return _collect_cleaning_options_body(df, has_fuzzy)


def _collect_cleaning_options_body(df: pd.DataFrame, has_fuzzy: bool) -> CleaningOptions:
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
    options.trim_whitespace = st.checkbox("Trim whitespace on text columns")
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
    st.caption("What will change — a dry look. Nothing is applied yet.")
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
        st.write("Near-duplicates will be collapsed to the suggested values shown above.")
    if options.missing_strategy == "drop_rows":
        st.write(
            f"Rows with any missing value that would be removed: **{int(df.isna().any(axis=1).sum()):,}**"
        )


def _receipt_reports(original: pd.DataFrame, cleaned: pd.DataFrame) -> tuple[QualityReport, QualityReport]:
    sig = (id(original), id(cleaned))
    if st.session_state.get("_receipt_sig") != sig:
        st.session_state["_receipt"] = (
            build_quality_report(original),
            build_quality_report(cleaned),
        )
        st.session_state["_receipt_sig"] = sig
    return st.session_state["_receipt"]


def render_before_after(original: pd.DataFrame, cleaned: pd.DataFrame, log) -> None:
    section_header(
        "05  ·  Receipt",
        "Before vs after",
        "The same score, before the plan and after. This is the screenshot to send.",
    )
    before, after = _receipt_reports(original, cleaned)
    delta = after.score - before.score
    sign = f"+{delta}" if delta > 0 else str(delta)
    quality_score_bento(
        before.score,
        f"{_score_caption(after.score)} Change {sign} points.",
        before.completeness,
        before.uniqueness,
        before.consistency,
        before.exact_duplicate_rows,
        after_score=after.score,
        after_completeness=after.completeness,
        after_uniqueness=after.uniqueness,
        after_consistency=after.consistency,
        after_duplicates=after.exact_duplicate_rows,
    )
    bento_tiles(
        [
            ("era-tile-lg", "Rows", f"{log.rows_after:,}", f"Was {log.rows_before:,}"),
            ("era-tile-lg", "Columns", f"{log.cols_after:,}", f"Was {log.cols_before:,}"),
        ]
    )
    st.caption("Change summary")
    st.dataframe(pd.DataFrame(log.as_rows()), use_container_width=True, hide_index=True)
    note_cards(log.steps)

    before_tab, after_tab = st.tabs(["Before", "After"])
    with before_tab:
        st.caption(f"{len(original):,} rows × {len(original.columns):,} columns")
        show_frame(original)
    with after_tab:
        st.caption(f"{len(cleaned):,} rows × {len(cleaned.columns):,} columns")
        show_frame(cleaned)


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="cleaned")
    return buffer.getvalue()


def render_export(
    cleaned: pd.DataFrame,
    log,
    original: pd.DataFrame,
    source_name: str,
    remaining_findings: int = 0,
) -> None:
    section_header(
        "06  ·  Deliverable",
        "Export",
        "The cleaned table, plus a certificate: score, every rule, and a sample of what changed.",
    )
    before, after = _receipt_reports(original, cleaned)
    steps = tuple(st.session_state.get("applied_steps") or [])
    export_sig = (id(cleaned), id(original), remaining_findings, steps, source_name)
    if st.session_state.get("_export_sig") != export_sig:
        cert_log = replace(
            log,
            rows_before=len(original),
            rows_after=len(cleaned),
            cols_before=len(original.columns),
            cols_after=len(cleaned.columns),
            steps=list(steps or log.steps),
        )
        cert = build_certificate(
            source_name=source_name,
            original=original,
            cleaned=cleaned,
            before=before,
            after=after,
            log=cert_log,
            remaining_findings=remaining_findings,
        )
        safe = neutralize_formula_cells(cleaned)
        excel_data = _excel_bytes(safe)
        pdf_data = render_certificate_pdf(cert)
        st.session_state["_export"] = {
            "cert": cert,
            "csv": safe.to_csv(index=False).encode("utf-8"),
            "excel": excel_data,
            "pdf": pdf_data,
            "summary_text": cert.as_text(),
            "summary_csv": pd.DataFrame(log.as_rows()).to_csv(index=False).encode("utf-8"),
            "pack": build_handoff_zip(excel_bytes=excel_data, pdf_bytes=pdf_data),
        }
        st.session_state["_export_sig"] = export_sig
    bundle = st.session_state["_export"]
    cert = bundle["cert"]
    csv_data = bundle["csv"]
    excel_data = bundle["excel"]
    pdf_data = bundle["pdf"]
    summary_text = bundle["summary_text"]
    summary_csv = bundle["summary_csv"]
    pack = bundle["pack"]
    st.caption(
        f"Certificate · score {cert.score_before} → {cert.score_after} · "
        f"{cert.dropped_total:,} dropped row(s) · {cert.changed_total:,} changed cell(s)"
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.download_button(
            "Certificate (PDF)  ↗",
            data=pdf_data,
            file_name="cleaning_certificate.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "Download CSV  ↗",
            data=csv_data,
            file_name="cleaned_data.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c3:
        st.download_button(
            "Download Excel  ↗",
            data=excel_data,
            file_name="cleaned_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with c4:
        st.download_button(
            "Summary (txt)  ↗",
            data=summary_text,
            file_name="cleaning_summary.txt",
            mime="text/plain",
            use_container_width=True,
        )
    st.download_button(
        "Summary (CSV)  ↗",
        data=summary_csv,
        file_name="cleaning_summary.csv",
        mime="text/csv",
        use_container_width=True,
    )
    handoff_card(EXCEL_REPORT_AUTOMATOR_URL)
    st.download_button(
        "Handoff pack (Excel + certificate)  ↗",
        data=pack,
        file_name="handoff_for_automator.zip",
        mime="application/zip",
        use_container_width=True,
        help="Upload cleaned_data.xlsx from this zip into Excel Report Automator.",
    )

