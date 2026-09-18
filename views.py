from __future__ import annotations

import io
from dataclasses import replace

import pandas as pd
import streamlit as st

from certificate import build_certificate
from certificate_pdf import render_certificate_pdf
from cleaning import CleaningOptions, preview_duplicate_rows
from findings import Finding, collect_findings
from fuzzy import MAX_BLOCK, MAX_UNIQUE, FuzzyGroup
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
        return "In good shape — mostly polish."
    if score >= 70:
        return "Usable, with a few issues worth fixing."
    if score >= 50:
        return "Messy. Cleaning will save real time."
    return "High risk. Do not analyze this as-is."


def render_quality_report(df: pd.DataFrame, report: QualityReport, fuzzy_scan) -> list[Finding]:
    section_header(
        "02  ·  Score",
        "What we found",
        "The score is the headline. The cards below explain it.",
    )
    findings = collect_findings(df, report, fuzzy_scan)
    high = sum(1 for f in findings if f.severity == "high")
    caption = _score_caption(report.score)
    if findings:
        caption = f"{caption} {len(findings)} issue{'s' if len(findings) != 1 else ''}"
        if high:
            caption += f", {high} serious."
        else:
            caption += "."
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
                "likely type": col.inferred_role or "—",
                "empty %": col.missing_pct,
                "empty cells": col.missing_count,
                "placeholder text": col.empty_string_count,
                "date formats": ", ".join(col.date_formats) or "—",
                "invalid emails": col.invalid_email_count,
                "invalid phones": col.invalid_phone_count,
            }
        )
    st.caption("Every column, in one table")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    return findings


def render_fuzzy_scan(scan) -> list[FuzzyGroup]:
    section_header(
        "03  ·  Similar names",
        "Similar spellings",
        "Same person or label, written more than one way. Keep one spelling, or skip a group.",
    )
    if scan.skipped_columns:
        st.warning(
            "These columns have too many unique values for a full scan. "
            f"If you turn one on, we only check the {MAX_UNIQUE:,} most common spellings."
        )
        prefix = str(st.session_state.get("file_key", ""))
        for col in scan.skipped_columns:
            n = scan.skipped_unique_counts.get(col, 0)
            st.checkbox(
                f"Also scan “{col}” ({n:,} unique values)",
                value=False,
                key=f"fuzzy_force_{prefix}_{col}",
                help=f"Only the {MAX_UNIQUE:,} most common values in this column. Rare spellings are skipped.",
            )
    if scan.sampled_columns:
        bits = [
            f"{col} ({n:,} unique, scanned top {MAX_UNIQUE:,})"
            for col, n in scan.sampled_columns.items()
        ]
        st.caption("Checked the most common values only: " + "; ".join(bits))
    if scan.truncated_blocks:
        bits = [
            f"{col} ({n:,} similar-looking values not compared)"
            for col, n in scan.truncated_blocks.items()
        ]
        st.caption(
            f"Some two-letter groups were larger than {MAX_BLOCK:,}. "
            "Those extra spellings were skipped: " + "; ".join(bits)
        )
    if not scan.scanned_columns:
        st.info("No text columns were small enough to scan for similar spellings.")
        st.session_state["fuzzy_selected"] = []
        return []
    if not scan.groups:
        st.success("No similar-spelling groups in the columns we scanned.")
        st.session_state["fuzzy_selected"] = []
        return []

    st.info(f"{len(scan.groups)} similar-spelling group{'s' if len(scan.groups) != 1 else ''} to review.")
    prefix = str(st.session_state.get("file_key", ""))
    selected: list[FuzzyGroup] = []
    by_column: dict[str, list] = {}
    for group in scan.groups:
        by_column.setdefault(group.column, []).append(group)

    for column, groups in by_column.items():
        skip_col = st.checkbox(
            f"Leave “{column}” unchanged",
            value=False,
            key=f"fuzzy_skipcol_{prefix}_{column}",
            help="Do not merge any spellings in this column.",
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
    st.caption(
        f"{len(selected)} group{'s' if len(selected) != 1 else ''} will merge "
        "if Merge similar spellings is in the plan."
    )
    return selected

def render_profile_picker() -> CleaningProfile:
    profile_id = st.radio(
        "Start from",
        [p.id for p in PROFILES],
        format_func=lambda i: get_profile(i).label,
        horizontal=True,
        key="cleaning_profile",
        help="This ticks the steps. You can still turn any of them off.",
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
            status = "on" if on else "off"
            weight = {"high": "serious", "medium": "worth fixing", "low": "optional"}.get(
                step.highest_severity, step.highest_severity
            )
            st.markdown(
                f"**{step.label}** · {weight} · {status}  \n"
                f"{step.summary}"
            )
        if on:
            included.append(step.fix_key)
    recipe_banner(recipe_line(recipe, included))
    dayfirst = False
    if "fix_dates" in included:
        dayfirst = st.checkbox(
            "Dates are day-first (31/12/2024, not 12/31/2024)",
            help="Turn this on outside the US.",
            key="recipe_dayfirst",
        )
    return included, dayfirst


def collect_cleaning_options(df: pd.DataFrame, has_fuzzy: bool) -> CleaningOptions:
    with st.expander("Advanced — extra tools"):
        st.caption("Fills, dropping rows, casing, and renaming live here. They are not in the plan above.")
        return _collect_cleaning_options_body(df, has_fuzzy)


def _collect_cleaning_options_body(df: pd.DataFrame, has_fuzzy: bool) -> CleaningOptions:
    options = CleaningOptions()
    prefix = str(st.session_state.get("file_key", ""))

    st.subheader("Duplicates")
    options.drop_exact_duplicates = st.checkbox(
        "Remove duplicate rows",
        help="Keeps the first copy of each identical row.",
        key=f"adv_{prefix}_drop_exact_duplicates",
    )
    if options.drop_exact_duplicates:
        options.duplicate_subset = st.multiselect(
            "Only treat rows as duplicates if these columns match (optional)",
            list(df.columns),
            help="Leave empty to compare the whole row.",
            key=f"adv_{prefix}_duplicate_subset",
        ) or None
    options.collapse_fuzzy = st.checkbox(
        "Merge similar spellings to the spelling you kept above",
        disabled=not has_fuzzy,
        help="Uses the groups you reviewed under Similar spellings.",
        key=f"adv_{prefix}_collapse_fuzzy",
    )

    st.subheader("Text, dates, and numbers")
    options.trim_whitespace = st.checkbox(
        "Trim extra spaces on text",
        key=f"adv_{prefix}_trim_whitespace",
    )
    options.fix_dates = st.checkbox(
        "Turn date-like text into real dates",
        key=f"adv_{prefix}_fix_dates",
    )
    if options.fix_dates:
        options.dayfirst = st.checkbox(
            "Dates are day-first (31/12/2024, not 12/31/2024)",
            help="Turn this on outside the US.",
            key=f"adv_{prefix}_dayfirst",
        )
    options.casing = st.selectbox(
        "Text casing",
        ["none", "title", "lower", "upper"],
        format_func=lambda x: {
            "none": "Leave as-is",
            "title": "Title Case",
            "lower": "lowercase",
            "upper": "UPPERCASE",
        }[x],
        key=f"adv_{prefix}_casing",
    )
    options.fix_emails = st.checkbox(
        "Clean emails (trim and lowercase)",
        key=f"adv_{prefix}_fix_emails",
    )
    options.normalize_phones = st.checkbox(
        "Standardize phone numbers",
        key=f"adv_{prefix}_normalize_phones",
    )
    if options.normalize_phones:
        options.phone_format = st.radio(
            "Phone format",
            ["digits", "dashed"],
            format_func=lambda x: "Digits only" if x == "digits" else "###-###-####",
            horizontal=True,
            key=f"adv_{prefix}_phone_format",
        )
    options.strip_currency = st.checkbox(
        "Turn currency text into numbers ($1,234 → 1234)",
        key=f"adv_{prefix}_strip_currency",
    )

    st.subheader("Missing values")
    options.missing_strategy = st.selectbox(
        "Empty cells",
        ["leave", "drop_rows", "drop_columns", "fill"],
        format_func=lambda x: {
            "leave": "Leave them",
            "drop_rows": "Remove any row with an empty cell",
            "drop_columns": "Remove columns that are mostly empty",
            "fill": "Fill empty cells",
        }[x],
        key=f"adv_{prefix}_missing_strategy",
    )
    if options.missing_strategy == "drop_columns":
        options.missing_threshold_pct = st.slider(
            "Drop column if empty % is at least",
            min_value=10,
            max_value=100,
            value=100,
            key=f"adv_{prefix}_missing_threshold",
        )
    if options.missing_strategy == "fill":
        options.numeric_fill = st.selectbox(
            "Numbers",
            ["none", "mean", "median"],
            format_func=lambda x: {
                "none": "Do not fill numbers automatically",
                "mean": "Fill with the average",
                "median": "Fill with the median",
            }[x],
            key=f"adv_{prefix}_numeric_fill",
        )
        options.fill_value = st.text_input(
            "Fill other columns with (optional)",
            placeholder="e.g. Unknown",
            key=f"adv_{prefix}_fill_value",
        )

    st.subheader("Column names and blank rows")
    options.rename_style = st.selectbox(
        "Rename columns",
        ["none", "snake", "lower"],
        format_func=lambda x: {
            "none": "Keep names",
            "snake": "lowercase_with_underscores",
            "lower": "lowercase (keep spaces)",
        }[x],
        key=f"adv_{prefix}_rename_style",
    )
    with st.expander("Manual column renames"):
        manual = {}
        for col in df.columns:
            new = st.text_input(
                f"{col}",
                value=str(col),
                key=f"rename_{prefix}_{col}",
            )
            if new.strip() and new.strip() != str(col):
                manual[col] = new.strip()
        options.manual_renames = manual
    options.drop_empty_columns = st.checkbox(
        "Remove completely empty columns",
        key=f"adv_{prefix}_drop_empty_columns",
    )
    options.drop_empty_rows = st.checkbox(
        "Remove completely empty rows",
        key=f"adv_{prefix}_drop_empty_rows",
    )
    return options


def render_pre_apply_preview(df: pd.DataFrame, options: CleaningOptions) -> None:
    st.caption("Preview only. Nothing is applied until you click below.")
    if options.drop_exact_duplicates:
        dupes = preview_duplicate_rows(df, options.duplicate_subset)
        st.write(f"Duplicate rows that would be removed: **{len(dupes):,}**")
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
        st.write("Similar spellings will be merged to the values you kept above.")
    if options.missing_strategy == "drop_rows":
        st.write(
            f"Rows with any empty cell that would be removed: **{int(df.isna().any(axis=1).sum()):,}**"
        )


def _receipt_reports(original: pd.DataFrame, cleaned: pd.DataFrame) -> tuple[QualityReport, QualityReport]:
    sig = int(st.session_state.get("_data_gen") or 0)
    if st.session_state.get("_receipt_sig") != sig:
        st.session_state["_receipt"] = (
            build_quality_report(original),
            build_quality_report(cleaned),
        )
        st.session_state["_receipt_sig"] = sig
    return st.session_state["_receipt"]


def _journey_log(original: pd.DataFrame, cleaned: pd.DataFrame, log):
    """One log for Result + certificate: original → current, all applied steps."""
    steps = list(st.session_state.get("applied_steps") or log.steps)
    return replace(
        log,
        rows_before=len(original),
        rows_after=len(cleaned),
        cols_before=len(original.columns),
        cols_after=len(cleaned.columns),
        steps=steps,
    )


def render_before_after(original: pd.DataFrame, cleaned: pd.DataFrame, log) -> None:
    section_header(
        "05  ·  Result",
        "Before and after",
        "The score before the plan, then after. This is the screenshot to send.",
    )
    before, after = _receipt_reports(original, cleaned)
    log = _journey_log(original, cleaned, log)
    delta = after.score - before.score
    sign = f"+{delta}" if delta > 0 else str(delta)
    quality_score_bento(
        before.score,
        f"{_score_caption(after.score)} {sign} points.",
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
    st.caption("What we did")
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
        "06  ·  Files",
        "Download",
        "The clean table, plus a certificate: the score, every step, and a sample of what changed.",
    )
    before, after = _receipt_reports(original, cleaned)
    cert_log = _journey_log(original, cleaned, log)
    steps = tuple(cert_log.steps)
    export_sig = (
        int(st.session_state.get("_data_gen") or 0),
        remaining_findings,
        steps,
        source_name,
    )
    if st.session_state.get("_export_sig") != export_sig:
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
            "summary_csv": pd.DataFrame(cert_log.as_rows()).to_csv(index=False).encode("utf-8"),
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
        f"Score {cert.score_before} → {cert.score_after} · "
        f"{cert.dropped_total:,} row{'s' if cert.dropped_total != 1 else ''} removed · "
        f"{cert.changed_total:,} cell{'s' if cert.changed_total != 1 else ''} changed"
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.download_button(
            "Certificate PDF  ↗",
            data=pdf_data,
            file_name="cleaning_certificate.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "Clean CSV  ↗",
            data=csv_data,
            file_name="cleaned_data.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c3:
        st.download_button(
            "Clean Excel  ↗",
            data=excel_data,
            file_name="cleaned_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with c4:
        st.download_button(
            "Change log  ↗",
            data=summary_text,
            file_name="cleaning_summary.txt",
            mime="text/plain",
            use_container_width=True,
        )
    st.download_button(
        "Change log (CSV)  ↗",
        data=summary_csv,
        file_name="cleaning_summary.csv",
        mime="text/csv",
        use_container_width=True,
    )
    handoff_card(EXCEL_REPORT_AUTOMATOR_URL)
    st.download_button(
        "Briefing pack  ↗",
        data=pack,
        file_name="handoff_for_automator.zip",
        mime="application/zip",
        use_container_width=True,
        help="Contains cleaned_data.xlsx and the certificate. Upload the Excel file in Excel Report Automator.",
    )

