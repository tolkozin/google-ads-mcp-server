"""Credential / account resolution that works both locally and on Streamlit Cloud.

Order of preference:
  1. Streamlit secrets  — [google_ads] section and [ads] account  (cloud)
  2. google-ads.yaml + ADS_ANALYSIS_ACCOUNT env / .env            (local, cron)

Nothing here raises at import time, so modules can be imported safely even when
credentials are absent; failures surface when a client is actually requested.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_YAML_KEYS = ("developer_token", "client_id", "client_secret", "refresh_token")


def _secrets():
    """Streamlit secrets if available, else None (never raises)."""
    try:
        import streamlit as st
        return st.secrets
    except Exception:
        return None


def get_account() -> str:
    """Customer id to analyze."""
    sec = _secrets()
    if sec is not None:
        try:
            if "ads" in sec and "account" in sec["ads"]:
                return str(sec["ads"]["account"])
        except Exception:
            pass
    return os.getenv("ADS_ANALYSIS_ACCOUNT", "")


def load_credentials() -> dict:
    """google-ads client config dict, from Streamlit secrets or google-ads.yaml."""
    sec = _secrets()
    if sec is not None:
        try:
            if "google_ads" in sec:
                g = sec["google_ads"]
                if all(k in g for k in _YAML_KEYS):
                    cfg = {k: str(g[k]) for k in _YAML_KEYS}
                    if g.get("login_customer_id"):
                        cfg["login_customer_id"] = str(g["login_customer_id"])
                    cfg["use_proto_plus"] = True
                    return cfg
        except Exception:
            pass
    path = Path(os.getenv("GOOGLE_ADS_CREDENTIALS", str(Path(__file__).parent / "google-ads.yaml")))
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise RuntimeError(
        "No Google Ads credentials found. On Streamlit Cloud add a [google_ads] "
        "section to the app secrets; locally provide google-ads.yaml "
        "(see google-ads.yaml.example)."
    )
