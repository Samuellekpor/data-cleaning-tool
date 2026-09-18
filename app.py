from __future__ import annotations

import pandas as pd
import streamlit as st

from cleaning import apply_cleaning, compose_rename_map, options_from_fix_keys
from fuzzy import scan_fuzzy_duplicates
from io_files import FileReadError, fingerprint_bytes, merge_frames, read_uploaded_file, unique_upload_name
from profiles import PROFILE_BY_ID
from quality import build_quality_report
from recipe import STEP_ORDER, build_recipe, recipe_line
from recipe_io import recipe_from_json, recipe_payload, recipe_to_json
from ui import hero, inject_theme, section_header, sidebar_chrome
from views import (
    show_frame,
    collect_cleaning_options,
    render_before_after,
    render_export,
    render_fuzzy_scan,
    render_pre_apply_preview,
    render_profile_picker,
    render_quality_report,
    render_recipe_editor,
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


def _commit_clean(
    original: pd.DataFrame,
    cleaned: pd.DataFrame,
    log,
    *,
    replace_steps: bool,
) -> None:
    st.session_state["working"] = cleaned
    st.session_state["cleaned"] = cleaned
    st.session_state["original"] = original
    st.session_state["log"] = log
    if replace_steps:
        st.session_state["applied_steps"] = list(log.steps)
        st.session_state["has_advanced"] = False
    else:
        steps = list(st.session_state.get("applied_steps") or [])
        steps.extend(log.steps)
        st.session_state["applied_steps"] = steps
        st.session_state["has_advanced"] = True
    latest = dict(log.columns_renamed or {})
    if replace_steps:
        st.session_state["rename_map"] = latest
    else:
        st.session_state["rename_map"] = compose_rename_map(
            st.session_state.get("rename_map") or {},
            latest,
        )
    st.session_state["_data_gen"] = int(st.session_state.get("_data_gen") or 0) + 1


def apply_saved_recipe(saved: dict) -> None:
    profile_id = saved.get("profile") if saved.get("profile") in PROFILE_BY_ID else "findings"
    st.session_state["cleaning_profile"] = profile_id
    st.session_state["_profile_token"] = f"{st.session_state.get('file_key')}:{profile_id}"
    wanted = set(saved.get("fix_keys") or [])
    for key in STEP_ORDER:
        st.session_state[f"recipe_{key}"] = key in wanted
    st.session_state["recipe_dayfirst"] = bool(saved.get("dayfirst"))



section_header(
    "01  ·  Upload",
    "Add your spreadsheet",
    "CSV or Excel. Several files can be stacked if they are the same kind of table.",
)

uploads = st.file_uploader(
    "Choose files",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    help="Accepted formats: .xlsx, .xls, .csv",
    label_visibility="collapsed",
)

if not uploads:
    st.info("Drop a spreadsheet to begin. We score it before anything is cleaned.")
    st.stop()

frames: dict[str, pd.DataFrame] = {}
fingerprints: dict[str, str] = {}
errors: list[str] = []

for uploaded in uploads:
    try:
        label = unique_upload_name(uploaded.name, set(frames))
        fingerprints[label] = fingerprint_bytes(uploaded.getvalue())
        frames[label] = read_uploaded_file(uploaded)
    except FileReadError as exc:
        errors.append(str(exc))

for message in errors:
    st.error(message)

if not frames:
    st.warning("Nothing readable yet. Fix the errors above, or try another file.")
    st.stop()

names = list(frames.keys())
merge = False
if len(frames) > 1:
    merge = st.checkbox(
        "Combine files into one table",
        help="Use this when each file is the same kind of table, stacked as extra rows.",
    )
    header_sets = [tuple(map(str, f.columns)) for f in frames.values()]
    if merge and len(set(header_sets)) > 1:
        st.warning(
            "Column names differ between files. Matching names line up; "
            "a blank is left where a file is missing a column."
        )
        with st.expander("Headers in each file"):
            for name, cols in zip(frames.keys(), header_sets):
                st.write(f"**{name}:** {', '.join(cols)}")

if merge:
    df, _headers_differ = merge_frames(frames)
    selected = "(merged)"
    content_fp = fingerprint_bytes("|".join(fingerprints[n] for n in names).encode())
else:
    selected = names[0] if len(names) == 1 else st.selectbox("File to inspect", names)
    df = frames[selected]
    content_fp = fingerprints[selected]
file_key = f"{selected}:{len(df)}:{tuple(map(str, df.columns))}:{content_fp}"
if st.session_state.get("file_key") != file_key:
    st.session_state["file_key"] = file_key
    st.session_state["source"] = df.copy()
    st.session_state["working"] = df.copy()
    st.session_state["applied_steps"] = []
    st.session_state["has_advanced"] = False
    st.session_state["_data_gen"] = 0
    st.session_state["rename_map"] = {}
    st.session_state.pop("cleaned", None)
    st.session_state.pop("log", None)
    st.session_state.pop("original", None)
    st.session_state.pop("fuzzy_selected", None)
    st.session_state.pop("fuzzy_skipped_last", None)
    st.session_state.pop("_diag_sig", None)
    st.session_state.pop("_fuzzy_scan", None)
    st.session_state.pop("_quality", None)
    st.session_state.pop("_export_sig", None)
    st.session_state.pop("_export", None)
    st.session_state.pop("_receipt_sig", None)
    st.session_state.pop("_receipt", None)
    st.session_state.pop("_recipe_upload_digest", None)
    if st.session_state.get("saved_recipe"):
        st.session_state["_offer_last_recipe"] = True

source = st.session_state.get("source", df)
working = st.session_state.get("working", df)

section_header(
    "Table",
    selected,
    f"{len(working):,} rows × {len(working.columns):,} columns. This is the current working copy.",
)
show_frame(working)

prefix = str(st.session_state.get("file_key", ""))
force_columns = {
    col
    for col in (st.session_state.get("fuzzy_skipped_last") or [])
    if st.session_state.get(f"fuzzy_force_{prefix}_{col}")
}
diag_sig = (prefix, int(st.session_state.get("_data_gen") or 0), frozenset(force_columns))
if st.session_state.get("_diag_sig") != diag_sig:
    st.session_state["_fuzzy_scan"] = scan_fuzzy_duplicates(
        working, force_columns=force_columns
    )
    st.session_state["_quality"] = build_quality_report(working)
    st.session_state["_diag_sig"] = diag_sig
fuzzy_scan = st.session_state["_fuzzy_scan"]
st.session_state["fuzzy_skipped_last"] = list(fuzzy_scan.skipped_columns)
findings = render_quality_report(working, st.session_state["_quality"], fuzzy_scan)
fuzzy_selected = render_fuzzy_scan(fuzzy_scan)
has_fuzzy = bool(fuzzy_selected)

section_header(
    "04  ·  Plan",
    "Choose what to fix",
    "Start from the findings or a named profile. Turn off any step you do not want, then apply.",
)
profile = render_profile_picker()
recipe = build_recipe(findings, force_keys=profile.fix_keys)
saved = st.session_state.get("saved_recipe")
if st.session_state.get("_offer_last_recipe") and saved:
    last_line = recipe_line(recipe, saved.get("fix_keys") or [])
    offer_l, offer_r = st.columns([0.72, 0.28])
    with offer_l:
        st.info(f"Last plan, from the previous file: {last_line}")
    with offer_r:
        if st.button("Use last plan", use_container_width=True):
            apply_saved_recipe(saved)
            st.session_state["_offer_last_recipe"] = False
            st.rerun()
included_keys, recipe_dayfirst = render_recipe_editor(recipe, profile)

save_l, save_r = st.columns(2)
with save_l:
    st.download_button(
        "Save this plan  ↗",
        data=recipe_to_json(profile.id, included_keys, recipe_dayfirst),
        file_name="cleaning_recipe.json",
        mime="application/json",
        disabled=not included_keys,
        use_container_width=True,
        help="Open this JSON on next month’s file to tick the same steps.",
    )
with save_r:
    recipe_upload = st.file_uploader(
        "Or load a saved plan (JSON)",
        type=["json"],
        key="recipe_json_upload",
    )
    load_plan = st.button(
        "Load plan",
        disabled=recipe_upload is None,
        use_container_width=True,
    )
if recipe_upload is not None and load_plan:
    raw = recipe_upload.getvalue()
    digest = fingerprint_bytes(raw)
    if st.session_state.get("_recipe_upload_digest") == digest:
        st.info("That plan is already loaded.")
    else:
        try:
            loaded = recipe_from_json(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(f"Could not read that plan file. {exc}")
        else:
            apply_saved_recipe(loaded)
            st.session_state["saved_recipe"] = loaded
            st.session_state["_recipe_upload_digest"] = digest
            st.rerun()

if st.session_state.get("has_advanced"):
    st.warning(
        "Apply this plan starts from the original file. "
        "Advanced changes on the working copy will be discarded."
    )
if st.button("Apply this plan", type="primary", disabled=not included_keys):
    plan = options_from_fix_keys(
        included_keys,
        dayfirst=recipe_dayfirst,
        fuzzy_groups=st.session_state.get("fuzzy_selected"),
    )
    cleaned, log = apply_cleaning(source, plan)
    _commit_clean(source, cleaned, log, replace_steps=True)
    st.session_state["saved_recipe"] = recipe_payload(
        profile.id, included_keys, recipe_dayfirst
    )
    st.session_state["_offer_last_recipe"] = False
    st.success("Plan applied from the original file. Check the score change below.")
    st.rerun()

options = collect_cleaning_options(working, has_fuzzy)
render_pre_apply_preview(working, options)

if st.button("Apply advanced tools"):
    if options.collapse_fuzzy and options.fuzzy_groups is None:
        options.fuzzy_groups = st.session_state.get("fuzzy_selected")
    cleaned, log = apply_cleaning(working, options)
    _commit_clean(source, cleaned, log, replace_steps=False)
    st.success("Advanced tools applied. Check before and after below.")
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
