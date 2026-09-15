from __future__ import annotations

import io
from dataclasses import replace

import pandas as pd
import streamlit as st

from certificate import build_certificate
from certificate_pdf import render_certificate_pdf
from cleaning import CleaningOptions, apply_cleaning, options_from_fix_keys, preview_duplicate_rows
from findings import collect_findings
from fuzzy import MAX_UNIQUE, FuzzyGroup, scan_fuzzy_duplicates
from handoff import build_handoff_zip
from io_files import (
    FileReadError,
    fingerprint_bytes,
    merge_frames,
    neutralize_formula_cells,
    read_uploaded_file,
)
from profiles import CleaningProfile, PROFILES, PROFILE_BY_ID, get_profile
from quality import QualityReport, build_quality_report
from recipe import STEP_ORDER, build_recipe, recipe_line
from recipe_io import recipe_from_json, recipe_payload, recipe_to_json
from ui import (
    EXCEL_REPORT_AUTOMATOR_URL,
    bento_tiles,
    finding_cards,
    handoff_card,
    hero,
    inject_theme,
    note_cards,
    quality_score_bento,
    recipe_banner,
    section_header,
    sidebar_chrome,
)

st.set_page_config(
    page_title="Data Cleaning Tool",
    layout="wide",
    # Open on desktop; collapse on narrow viewports so Protocol does not cover the hero.
    initial_sidebar_state="auto",
)

inject_theme()

with st.sidebar:
    sidebar_chrome()

hero()


def _score_caption(score: int) -> str:
    if score >= 85:
        return "Solid — only polish remaining."
    if score >= 70:
        return "Usable, but a few issues will bite you later."
    if score >= 50:
        return "Messy — cleaning will save you real time."
    return "High risk — do not analyze this as-is."


def render_quality_report(df: pd.DataFrame, report: QualityReport, fuzzy_scan) -> None:
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


def _commit_clean(original: pd.DataFrame, cleaned: pd.DataFrame, log) -> None:
    st.session_state["working"] = cleaned
    st.session_state["cleaned"] = cleaned
    st.session_state["original"] = original
    st.session_state["log"] = log
    steps = list(st.session_state.get("applied_steps") or [])
    steps.extend(log.steps)
    st.session_state["applied_steps"] = steps


def apply_saved_recipe(saved: dict) -> None:
    profile_id = saved.get("profile") if saved.get("profile") in PROFILE_BY_ID else "findings"
    st.session_state["cleaning_profile"] = profile_id
    st.session_state["_profile_token"] = f"{st.session_state.get('file_key')}:{profile_id}"
    wanted = set(saved.get("fix_keys") or [])
    for key in STEP_ORDER:
        st.session_state[f"recipe_{key}"] = key in wanted
    st.session_state["recipe_dayfirst"] = bool(saved.get("dayfirst"))


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


def render_before_after(original: pd.DataFrame, cleaned: pd.DataFrame, log) -> None:
    section_header(
        "05  ·  Receipt",
        "Before vs after",
        "The same score, before the plan and after. This is the screenshot to send.",
    )
    before = build_quality_report(original)
    after = build_quality_report(cleaned)
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
        st.dataframe(original, use_container_width=True)
    with after_tab:
        st.caption(f"{len(cleaned):,} rows × {len(cleaned.columns):,} columns")
        st.dataframe(cleaned, use_container_width=True)


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
    before = build_quality_report(original)
    after = build_quality_report(cleaned)
    cert_log = replace(
        log,
        rows_before=len(original),
        rows_after=len(cleaned),
        cols_before=len(original.columns),
        cols_after=len(cleaned.columns),
        steps=list(st.session_state.get("applied_steps") or log.steps),
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
    csv_data = neutralize_formula_cells(cleaned).to_csv(index=False).encode("utf-8")
    excel_data = _excel_bytes(neutralize_formula_cells(cleaned))
    pdf_data = render_certificate_pdf(cert)
    summary_text = cert.as_text()
    summary_csv = pd.DataFrame(log.as_rows()).to_csv(index=False).encode("utf-8")
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
    pack = build_handoff_zip(excel_bytes=excel_data, pdf_bytes=pdf_data)
    handoff_card(EXCEL_REPORT_AUTOMATOR_URL)
    st.download_button(
        "Handoff pack (Excel + certificate)  ↗",
        data=pack,
        file_name="handoff_for_automator.zip",
        mime="application/zip",
        use_container_width=True,
        help="Upload cleaned_data.xlsx from this zip into Excel Report Automator.",
    )


section_header(
    "01  ·  Intake",
    "Upload your data",
    "CSV or Excel. Several files can be stacked into one table.",
)

uploads = st.file_uploader(
    "Choose files",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    help="Accepted formats: .xlsx, .xls, .csv",
    label_visibility="collapsed",
)

if not uploads:
    st.info("Start by dropping a spreadsheet. The quality score appears before anything is cleaned.")
    st.stop()

frames: dict[str, pd.DataFrame] = {}
fingerprints: dict[str, str] = {}
errors: list[str] = []

for uploaded in uploads:
    try:
        fingerprints[uploaded.name] = fingerprint_bytes(uploaded.getvalue())
        frames[uploaded.name] = read_uploaded_file(uploaded)
    except FileReadError as exc:
        errors.append(str(exc))

for message in errors:
    st.error(message)

if not frames:
    st.warning("No readable files yet. Fix the errors above or try another file.")
    st.stop()

names = list(frames.keys())
merge = False
if len(frames) > 1:
    merge = st.checkbox(
        "Merge files (stack rows into one table)",
        help="Use this when each file is the same kind of table.",
    )
    header_sets = [tuple(map(str, f.columns)) for f in frames.values()]
    if merge and len(set(header_sets)) > 1:
        st.warning(
            "Column headers differ between files. The merge will line up "
            "matching names and leave blanks where a file is missing a column."
        )
        with st.expander("Headers in each file"):
            for name, cols in zip(frames.keys(), header_sets):
                st.write(f"**{name}:** {', '.join(cols)}")

if merge:
    df, _headers_differ = merge_frames(frames)
    selected = "(merged)"
    content_fp = fingerprint_bytes("|".join(fingerprints[n] for n in names).encode())
else:
    selected = names[0] if len(names) == 1 else st.selectbox("Working file", names)
    df = frames[selected]
    content_fp = fingerprints[selected]
file_key = f"{selected}:{len(df)}:{tuple(map(str, df.columns))}:{content_fp}"
if st.session_state.get("file_key") != file_key:
    st.session_state["file_key"] = file_key
    st.session_state["source"] = df.copy()
    st.session_state["working"] = df.copy()
    st.session_state["applied_steps"] = []
    st.session_state.pop("cleaned", None)
    st.session_state.pop("log", None)
    st.session_state.pop("original", None)
    st.session_state.pop("fuzzy_selected", None)
    st.session_state.pop("fuzzy_skipped_last", None)
    if st.session_state.get("saved_recipe"):
        st.session_state["_offer_last_recipe"] = True

source = st.session_state.get("source", df)
working = st.session_state.get("working", df)

section_header(
    "Receipt",
    f"Preview — {selected}",
    f"{len(working):,} rows × {len(working.columns):,} columns in the working table.",
)
st.dataframe(working, use_container_width=True)

prefix = str(st.session_state.get("file_key", ""))
force_columns = {
    col
    for col in (st.session_state.get("fuzzy_skipped_last") or [])
    if st.session_state.get(f"fuzzy_force_{prefix}_{col}")
}
fuzzy_scan = scan_fuzzy_duplicates(working, force_columns=force_columns)
st.session_state["fuzzy_skipped_last"] = list(fuzzy_scan.skipped_columns)
findings = render_quality_report(working, build_quality_report(working), fuzzy_scan)
fuzzy_selected = render_fuzzy_scan(fuzzy_scan)
has_fuzzy = bool(fuzzy_selected)

section_header(
    "04  ·  Plan",
    "Approve the repair plan",
    "Start from findings or a named profile, skip any step, then apply.",
)
profile = render_profile_picker()
recipe = build_recipe(findings, force_keys=profile.fix_keys)
saved = st.session_state.get("saved_recipe")
if st.session_state.get("_offer_last_recipe") and saved:
    last_line = recipe_line(recipe, saved.get("fix_keys") or [])
    offer_l, offer_r = st.columns([0.72, 0.28])
    with offer_l:
        st.info(f"Last recipe from the previous file: {last_line}")
    with offer_r:
        if st.button("Re-run last recipe", use_container_width=True):
            apply_saved_recipe(saved)
            st.session_state["_offer_last_recipe"] = False
            st.rerun()
included_keys, recipe_dayfirst = render_recipe_editor(recipe, profile)

save_l, save_r = st.columns(2)
with save_l:
    st.download_button(
        "Save this recipe  ↗",
        data=recipe_to_json(profile.id, included_keys, recipe_dayfirst),
        file_name="cleaning_recipe.json",
        mime="application/json",
        disabled=not included_keys,
        use_container_width=True,
        help="Reload this JSON on next month’s file to seed the same plan.",
    )
with save_r:
    recipe_upload = st.file_uploader(
        "Load a saved recipe (JSON)",
        type=["json"],
        key="recipe_json_upload",
    )
if recipe_upload is not None:
    digest = f"{recipe_upload.name}:{recipe_upload.size}"
    if st.session_state.get("_recipe_upload_digest") != digest:
        try:
            loaded = recipe_from_json(recipe_upload.getvalue())
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(f"Could not read that recipe. {exc}")
            st.session_state["_recipe_upload_digest"] = digest
        else:
            apply_saved_recipe(loaded)
            st.session_state["saved_recipe"] = loaded
            st.session_state["_recipe_upload_digest"] = digest
            st.rerun()

if st.button("Accept plan", type="primary", disabled=not included_keys):
    plan = options_from_fix_keys(
        included_keys,
        dayfirst=recipe_dayfirst,
        fuzzy_groups=st.session_state.get("fuzzy_selected"),
    )
    cleaned, log = apply_cleaning(source, plan)
    _commit_clean(source, cleaned, log)
    st.session_state["saved_recipe"] = recipe_payload(
        profile.id, included_keys, recipe_dayfirst
    )
    st.session_state["_offer_last_recipe"] = False
    st.success("Plan applied from the original file. Review the score change below.")
    st.rerun()

options = collect_cleaning_options(working, has_fuzzy)
render_pre_apply_preview(working, options)

if st.button("Apply advanced cleaning"):
    if options.collapse_fuzzy and options.fuzzy_groups is None:
        options.fuzzy_groups = st.session_state.get("fuzzy_selected")
    cleaned, log = apply_cleaning(working, options)
    _commit_clean(source, cleaned, log)
    st.success("Advanced cleaning applied. Review the before/after below.")
    st.rerun()

cleaned = st.session_state.get("cleaned")
log = st.session_state.get("log")
original = st.session_state.get("original")
if cleaned is not None and log is not None and original is not None:
    render_before_after(original, cleaned, log)
    render_export(
        cleaned,
        log,
        original,
        selected,
        remaining_findings=len(findings),
    )
