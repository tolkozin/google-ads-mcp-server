"""Account-specific analysis config.

Real values live in `config.json` (gitignored). `config.example.json` ships with
neutral placeholders so the repo contains no client data. Anything missing from
config.json falls back to the example.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def cfg() -> dict:
    example = json.loads((_DIR / "config.example.json").read_text(encoding="utf-8"))
    local = _DIR / "config.json"
    if local.exists():
        example.update(json.loads(local.read_text(encoding="utf-8")))
    return example


def get(key: str, default=None):
    return cfg().get(key, default)
