"""Turn findings into an ordered, reviewable cleaning recipe."""

from __future__ import annotations

from dataclasses import dataclass, field

from findings import Finding, SEVERITY_ORDER

# Matches the order apply_cleaning actually runs.
STEP_ORDER = (
    "trim_whitespace",
    "collapse_fuzzy",
    "fix_emails",
    "normalize_phones",
    "strip_currency",
    "fix_dates",
    "drop_empty_columns",
    "drop_exact_duplicates",
)

STEP_LABELS = {
    "trim_whitespace": "Trim extra spaces",
    "collapse_fuzzy": "Merge similar spellings",
    "fix_emails": "Clean emails",
    "normalize_phones": "Standardize phones",
    "strip_currency": "Turn currency into numbers",
    "fix_dates": "Fix mixed dates",
    "drop_empty_columns": "Remove empty columns",
    "drop_exact_duplicates": "Remove duplicate rows",
}


@dataclass
class RecipeStep:
    fix_key: str
    label: str
    summary: str
    finding_ids: list[str]
    columns: list[str] = field(default_factory=list)
    default_include: bool = True
    highest_severity: str = "low"


def _include_by_default(severity: str) -> bool:
    # High/medium always on. Trim stays on even when it is a low finding —
    # it is cheap and often unlocks the rest of the plan.
    return severity in {"high", "medium"}


def build_recipe(
    findings: list[Finding],
    *,
    force_keys: tuple[str, ...] | list[str] | None = None,
) -> list[RecipeStep]:
    """One step per fix_key, ordered like the cleaner, not like the finding list."""
    buckets: dict[str, list[Finding]] = {key: [] for key in STEP_ORDER}
    for finding in findings:
        if finding.fix_key in buckets:
            buckets[finding.fix_key].append(finding)

    forced = set(force_keys) if force_keys is not None else None
    steps: list[RecipeStep] = []
    for key in STEP_ORDER:
        group = buckets[key]
        if not group and (forced is None or key not in forced):
            continue
        if group:
            highest = min(group, key=lambda f: SEVERITY_ORDER.get(f.severity, 9)).severity
            columns = sorted({f.column for f in group if f.column})
            titles = [f.title for f in group[:3]]
            if len(group) > 3:
                titles.append(f"+{len(group) - 3} more")
            summary = " · ".join(titles)
            default = _include_by_default(highest) or key == "trim_whitespace"
        else:
            highest = "low"
            columns = []
            summary = "This profile always includes this step, even if we did not flag it."
            default = True
        if forced is not None:
            default = key in forced
        steps.append(
            RecipeStep(
                fix_key=key,
                label=STEP_LABELS[key],
                summary=summary,
                finding_ids=[f.id for f in group],
                columns=columns,
                default_include=default,
                highest_severity=highest,
            )
        )
    return steps


def recipe_line(steps: list[RecipeStep], included_keys: list[str] | None = None) -> str:
    """Human-readable plan, e.g. Trim extra spaces → Fix mixed dates → Remove duplicate rows."""
    chosen = set(included_keys) if included_keys is not None else {
        s.fix_key for s in steps if s.default_include
    }
    labels = [s.label for s in steps if s.fix_key in chosen]
    return " → ".join(labels) if labels else "No steps selected"
