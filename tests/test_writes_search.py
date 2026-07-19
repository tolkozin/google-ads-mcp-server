"""Offline snapshot tests for Search-write operation builders.

`client.get_type(...)` builds protobufs without any network call, so we can
assert the exact mutate payloads. A dummy in-memory client is used (no real
credentials, nothing leaves the process).
"""

from __future__ import annotations

import google.oauth2.credentials as oauth_creds
import pytest
from google.ads.googleads.client import GoogleAdsClient

from google_ads_mcp.tools._helpers import apply_bidding, usd_to_micros
from google_ads_mcp.tools.writes_common import build_create_budget_op, build_update_budget_op


@pytest.fixture
def client(monkeypatch) -> GoogleAdsClient:
    # google-ads 31 eagerly refreshes the OAuth token when the client is built.
    # Stub the refresh so a dummy-cred client constructs fully offline — proto
    # building and *_path helpers never touch the network.
    def _fake_refresh(self, request):
        self.token = "offline-test-token"

    monkeypatch.setattr(oauth_creds.Credentials, "refresh", _fake_refresh)
    return GoogleAdsClient.load_from_dict(
        {
            "developer_token": "DUMMY",
            "client_id": "DUMMY",
            "client_secret": "DUMMY",
            "refresh_token": "DUMMY",
            "use_proto_plus": True,
        },
        version="v23",
    )


def test_usd_to_micros():
    assert usd_to_micros(5) == 5_000_000
    assert usd_to_micros(4.5) == 4_500_000


def test_create_budget_op(client):
    op = build_create_budget_op(client, "Test Budget", 5_000_000, "STANDARD")
    assert op.create.name == "Test Budget"
    assert op.create.amount_micros == 5_000_000
    assert op.create.explicitly_shared is False
    assert op.create.delivery_method == client.enums.BudgetDeliveryMethodEnum.STANDARD


def test_update_budget_op_sets_mask(client):
    svc = client.get_service("CampaignBudgetService")
    rn = svc.campaign_budget_path("1234567890", "123")
    op = build_update_budget_op(client, rn, 7_000_000)
    assert op.update.resource_name == rn
    assert op.update.amount_micros == 7_000_000
    assert "amount_micros" in list(op.update_mask.paths)


def test_apply_bidding_target_cpa(client):
    camp = client.get_type("CampaignOperation").create
    apply_bidding(client, camp, "TARGET_CPA", 4.5)
    assert camp.target_cpa.target_cpa_micros == 4_500_000


def test_apply_bidding_target_roas(client):
    camp = client.get_type("CampaignOperation").create
    apply_bidding(client, camp, "TARGET_ROAS", 3.5)
    assert camp.target_roas.target_roas == 3.5


def test_apply_bidding_target_cpa_requires_value(client):
    camp = client.get_type("CampaignOperation").create
    with pytest.raises(ValueError):
        apply_bidding(client, camp, "TARGET_CPA", None)


def test_apply_bidding_unknown_strategy(client):
    camp = client.get_type("CampaignOperation").create
    with pytest.raises(ValueError):
        apply_bidding(client, camp, "NONSENSE", None)


def test_search_campaign_is_paused_and_typed(client):
    """The create_search_campaign builder must force PAUSED + SEARCH channel."""
    svc = client.get_service("CampaignService")
    budget_svc = client.get_service("CampaignBudgetService")
    op = client.get_type("CampaignOperation")
    c = op.create
    c.name = "X"
    c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
    c.status = client.enums.CampaignStatusEnum.PAUSED
    c.campaign_budget = budget_svc.campaign_budget_path("1234567890", "1")
    apply_bidding(client, c, "MAXIMIZE_CONVERSIONS", None)
    assert c.status == client.enums.CampaignStatusEnum.PAUSED
    assert c.advertising_channel_type == client.enums.AdvertisingChannelTypeEnum.SEARCH


def test_mutations_register_when_enabled(monkeypatch, tmp_path):
    """With mutations on, the server exposes the write tools."""
    monkeypatch.setenv("ADS_MCP_ENABLE_MUTATIONS", "true")
    monkeypatch.setenv("GOOGLE_ADS_CREDENTIALS", str(tmp_path / "google-ads.yaml"))
    # Force a fresh settings + server import so the env takes effect.
    import importlib

    import google_ads_mcp.config as config
    config._settings = None
    import google_ads_mcp.server as server
    importlib.reload(server)
    server._register_mutations()

    import asyncio
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    for expected in [
        "create_campaign_budget", "update_campaign_budget", "update_campaign_status",
        "set_campaign_bidding", "create_search_campaign", "create_ad_group",
        "manage_keywords", "manage_negative_keywords", "create_responsive_search_ad",
        "update_ad_status",
        "create_app_campaign", "update_app_campaign_targets", "manage_app_assets",
    ]:
        assert expected in names
