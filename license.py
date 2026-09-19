"""Gumroad license gate. The rest of the app does not run until this passes."""

from __future__ import annotations

import requests
import streamlit as st

# ---- Per-app config (change these two blocks only) ----
APP_NAME = "Data Cleaning Tool"
BUY_URL = "https://app.gumroad.com/products/PASTE_SINGLE_PRODUCT_ID"

# This app accepts a key from EITHER its own single product ($19)
# OR the "Complete Toolkit" bundle ($29) that unlocks both tools.
ALLOWED_PRODUCT_IDS = [
    "PASTE_SINGLE_PRODUCT_ID",  # this app's own $19 product
    "PASTE_BUNDLE_PRODUCT_ID",  # the $29 "Complete Toolkit" bundle
]
# --------------------------------------------------------------


def verify_license(key: str) -> dict:
    """Try the key against every allowed product id. Return the first success."""
    for pid in ALLOWED_PRODUCT_IDS:
        try:
            resp = requests.post(
                "https://api.gumroad.com/v2/licenses/verify",
                data={
                    "product_id": pid,
                    "license_key": key.strip(),
                    "increment_uses_count": "false",
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("success"):
                return data
        except (requests.RequestException, ValueError):
            continue
    return {"success": False}


def license_gate() -> bool:
    if st.session_state.get("licensed"):
        return True

    st.title(f"🔑 Unlock {APP_NAME}")
    st.write(f"{APP_NAME} — $19 · Complete Toolkit (both tools) — $29")
    st.link_button("Buy a license →", BUY_URL)

    key = st.text_input("License key", placeholder="XXXX-XXXX-XXXX-XXXX")

    if st.button("Verify", type="primary"):
        if not key.strip():
            st.warning("Please paste your license key.")
            return False
        data = verify_license(key)
        if data.get("success"):
            purchase = data.get("purchase", {})
            if purchase.get("refunded") or purchase.get("chargebacked"):
                st.error("This license has been refunded or chargebacked.")
                return False
            st.session_state["licensed"] = True
            st.session_state["license_key"] = key.strip()
            st.rerun()
        else:
            st.error("Invalid license key. Check your Gumroad receipt.")
    return False
