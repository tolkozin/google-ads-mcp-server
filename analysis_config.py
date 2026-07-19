"""Account-specific analysis config.

Layered, last wins:
  1. config.example.json  — neutral placeholders shipped with the repo
  2. config.json          — real values, gitignored (local / cron)
  3. Streamlit secrets    — a [config] section, for cloud deployments where
                            config.json cannot exist

Without layer 2 or 3 the app still runs, but on placeholder vocabulary — which is
why cloud deployments must supply [config] in secrets (otherwise creative
suggestions come back in the wrong language).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


def _from_secrets() -> dict:
    try:
        import streamlit as st
        if "config" in st.secrets:
            return {k: (list(v) if isinstance(v, (list, tuple)) else
                        dict(v) if hasattr(v, "keys") else v)
                    for k, v in st.secrets["config"].items()}
    except Exception:
        pass
    return {}


@lru_cache(maxsize=1)
def cfg() -> dict:
    merged = json.loads((_DIR / "config.example.json").read_text(encoding="utf-8"))
    local = _DIR / "config.json"
    if local.exists():
        merged.update(json.loads(local.read_text(encoding="utf-8")))
    merged.update(_from_secrets())
    return merged


def get(key: str, default=None):
    return cfg().get(key, default)
