"""Named cleaning profiles: a starting plan for a kind of table."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CleaningProfile:
    id: str
    label: str
    summary: str
    fix_keys: tuple[str, ...] | None
    dayfirst: bool = False


# fix_keys is None → keep whatever the findings recipe already proposed.
PROFILES: tuple[CleaningProfile, ...] = (
    CleaningProfile(
        id="findings",
        label="From findings",
        summary="Use the diagnosis. Skip anything you do not want.",
        fix_keys=None,
    ),
    CleaningProfile(
        id="crm",
        label="CRM contacts",
        summary="Trim, emails, phones, near-duplicates, exact copies.",
        fix_keys=(
            "trim_whitespace",
            "collapse_fuzzy",
            "fix_emails",
            "normalize_phones",
            "drop_exact_duplicates",
        ),
    ),
    CleaningProfile(
        id="transactions",
        label="Transactions",
        summary="Trim, currency, day-first dates, exact copies.",
        fix_keys=(
            "trim_whitespace",
            "strip_currency",
            "fix_dates",
            "drop_exact_duplicates",
        ),
        dayfirst=True,
    ),
    CleaningProfile(
        id="survey",
        label="Survey",
        summary="Trim, empty columns, exact copies. Missing answers stay.",
        fix_keys=(
            "trim_whitespace",
            "drop_empty_columns",
            "drop_exact_duplicates",
        ),
    ),
)

PROFILE_BY_ID = {p.id: p for p in PROFILES}


def get_profile(profile_id: str) -> CleaningProfile:
    return PROFILE_BY_ID.get(profile_id, PROFILES[0])
