"""Runtime configuration loaded from environment / .env.

Phase 1 only reads the credentials path and the pinned API version. The safety
flags are parsed here too so Phase 2 can enforce them without re-plumbing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Pin the Google Ads API version. Google ships monthly releases; without a pin
# the client would drift and break. Bump this deliberately.
API_VERSION = "v23"


def _csv_set(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    credentials_path: Path
    enable_mutations: bool
    allowed_customer_ids: frozenset[str] = field(default_factory=frozenset)
    max_daily_budget_usd: float = 100.0
    default_validate_only: bool = True
    audit_log_path: Path = Path("./google-ads.audit.jsonl")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()  # no-op if there is no .env file

        cred = os.getenv("GOOGLE_ADS_CREDENTIALS")
        credentials_path = Path(cred).expanduser() if cred else Path.home() / "google-ads.yaml"

        return cls(
            credentials_path=credentials_path,
            enable_mutations=os.getenv("ADS_MCP_ENABLE_MUTATIONS", "false").lower() == "true",
            allowed_customer_ids=_csv_set(os.getenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS")),
            max_daily_budget_usd=float(os.getenv("GOOGLE_ADS_MAX_DAILY_BUDGET_USD", "100")),
            default_validate_only=os.getenv("GOOGLE_ADS_DEFAULT_VALIDATE_ONLY", "true").lower()
            != "false",
            audit_log_path=Path(os.getenv("GOOGLE_ADS_AUDIT_LOG", "./google-ads.audit.jsonl")),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Cached singleton so every tool sees the same configuration."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
