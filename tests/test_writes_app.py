"""Offline snapshot tests for App/UAC operation builders."""

from __future__ import annotations

import google.oauth2.credentials as oauth_creds
import pytest
from google.ads.googleads.client import GoogleAdsClient

from google_ads_mcp.tools.writes_app import build_app_campaign_op


@pytest.fixture
def client(monkeypatch) -> GoogleAdsClient:
    monkeypatch.setattr(
        oauth_creds.Credentials, "refresh", lambda self, request: setattr(self, "token", "t")
    )
    return GoogleAdsClient.load_from_dict(
        {
            "developer_token": "DUMMY", "client_id": "DUMMY",
            "client_secret": "DUMMY", "refresh_token": "DUMMY", "use_proto_plus": True,
        },
        version="v23",
    )


def test_app_campaign_is_paused_app_subtype(client):
    op, goal = build_app_campaign_op(
        client, cid="1234567890", name="UAC Test", app_id="com.example.app",
        app_store="GOOGLE_APP_STORE", budget_id="1", bidding_goal="INSTALLS_TARGET_CPI",
        target_value=3.0,
    )
    c = op.create
    assert c.status == client.enums.CampaignStatusEnum.PAUSED
    assert c.advertising_channel_type == client.enums.AdvertisingChannelTypeEnum.MULTI_CHANNEL
    assert c.advertising_channel_sub_type == client.enums.AdvertisingChannelSubTypeEnum.APP_CAMPAIGN
    assert c.app_campaign_setting.app_id == "com.example.app"
    assert c.app_campaign_setting.app_store == client.enums.AppCampaignAppStoreEnum.GOOGLE_APP_STORE
    assert c.target_cpa.target_cpa_micros == 3_000_000
    assert goal == "OPTIMIZE_INSTALLS_TARGET_INSTALL_COST"


def test_app_campaign_installs_without_target_uses_maximize(client):
    op, goal = build_app_campaign_op(
        client, cid="1234567890", name="UAC", app_id="com.x", app_store="GOOGLE_APP_STORE",
        budget_id="1", bidding_goal="INSTALLS", target_value=None,
    )
    assert goal == "OPTIMIZE_INSTALLS_WITHOUT_TARGET_INSTALL_COST"


def test_app_campaign_roas_requires_value(client):
    with pytest.raises(ValueError):
        build_app_campaign_op(
            client, cid="1", name="x", app_id="com.x", app_store="GOOGLE_APP_STORE",
            budget_id="1", bidding_goal="ROAS", target_value=None,
        )


def test_app_campaign_bad_store(client):
    with pytest.raises(KeyError):
        build_app_campaign_op(
            client, cid="1", name="x", app_id="com.x", app_store="NOPE_STORE",
            budget_id="1", bidding_goal="INSTALLS", target_value=None,
        )
