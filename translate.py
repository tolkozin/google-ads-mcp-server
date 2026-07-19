"""ES->EN translation for report tables — best-effort, cached, never raises.

Uses deep-translator (Google Translate, no API key). If the network/endpoint is
unavailable, to_en() returns "" so the report still renders.
"""

from __future__ import annotations

from functools import lru_cache

try:
    from deep_translator import GoogleTranslator
    _T = GoogleTranslator(source="es", target="en")
except Exception:  # library missing or init failure
    _T = None


@lru_cache(maxsize=4000)
def to_en(text: str) -> str:
    if not _T or not text:
        return ""
    try:
        return _T.translate(text) or ""
    except Exception:
        return ""
