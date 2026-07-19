"""Replacement copy bank for UAC text assets.

The actual copy lives in `config.json` → `creative_bank` (gitignored); the repo
ships neutral placeholders in `config.example.json`. When a HEADLINE or
DESCRIPTION underperforms on events, the report suggests an unused alternative
from here. Keep headlines <= 30 chars and descriptions <= 90 (App-ad limits).
"""

from __future__ import annotations

import unicodedata

from analysis_config import get


def _bank() -> dict:
    return get("creative_bank", {}) or {}


def headlines() -> list[str]:
    return _bank().get("headlines", [])


def descriptions() -> list[str]:
    return _bank().get("descriptions", [])


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn").strip()


def suggest(field_type: str, used: set[str], taken: set[str]) -> str | None:
    """Return an alternative not already in use (`used`) nor already suggested
    this run (`taken`), or None if the bank is exhausted."""
    pool = headlines() if field_type == "HEADLINE" else descriptions()
    for cand in pool:
        if _norm(cand) not in used and _norm(cand) not in taken:
            taken.add(_norm(cand))
            return cand
    return None
