"""Save and reload a cleaning recipe between files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from recipe import STEP_ORDER

RECIPE_VERSION = 1


def recipe_payload(profile_id: str, fix_keys: list[str], dayfirst: bool) -> dict[str, Any]:
    keys = [k for k in STEP_ORDER if k in set(fix_keys)]
    return {
        "version": RECIPE_VERSION,
        "profile": profile_id,
        "fix_keys": keys,
        "dayfirst": bool(dayfirst),
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def recipe_to_json(profile_id: str, fix_keys: list[str], dayfirst: bool) -> str:
    return json.dumps(recipe_payload(profile_id, fix_keys, dayfirst), indent=2) + "\n"


def recipe_from_json(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or "fix_keys" not in data:
        raise ValueError("This file is not a cleaning recipe.")
    allowed = set(STEP_ORDER)
    keys = [k for k in data.get("fix_keys") or [] if k in allowed]
    if not keys:
        raise ValueError("This recipe has no recognised cleaning steps.")
    profile = data.get("profile") or "findings"
    if not isinstance(profile, str):
        profile = "findings"
    return {
        "profile": profile,
        "fix_keys": keys,
        "dayfirst": bool(data.get("dayfirst")),
    }
