"""Google Ads API client factory.

Builds cached `GoogleAdsClient`s from `google-ads.yaml`, with the API version
pinned via `config.API_VERSION`. A per-call `login_customer_id` override lets the
server reach accounts that are NOT under the manager id baked into the yaml
(direct-access accounts), without rewriting the credentials file.
"""

from __future__ import annotations

from functools import lru_cache

from google.ads.googleads.client import GoogleAdsClient

from .config import API_VERSION, get_settings
from .util import normalize_customer_id


@lru_cache(maxsize=None)
def get_client(login_customer_id: str | None = None) -> GoogleAdsClient:
    settings = get_settings()
    path = settings.credentials_path
    if not path.exists():
        raise FileNotFoundError(
            f"google-ads.yaml not found at {path}. "
            "Set GOOGLE_ADS_CREDENTIALS to its absolute path "
            "(see google-ads.yaml.example)."
        )
    client = GoogleAdsClient.load_from_storage(path=str(path), version=API_VERSION)
    if login_customer_id:
        # Override the manager/login header for direct-access accounts.
        client.login_customer_id = normalize_customer_id(login_customer_id)
    return client


def get_service(name: str, login_customer_id: str | None = None):
    """Return a versioned service handle, e.g. get_service('GoogleAdsService')."""
    return get_client(login_customer_id).get_service(name, version=API_VERSION)
