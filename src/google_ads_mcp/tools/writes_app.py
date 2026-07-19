"""App/UAC write tools: create_app_campaign, update_app_campaign_targets,
manage_app_assets. Routed through `safety.run_mutation`.

UAC reality (per the brief): Google's algorithm controls delivery. There are no
asset_groups (that's Performance Max) — assets attach to the App ad. App
campaigns are created PAUSED here. `app_id` is the public store id
(e.g. 'com.example.app'); it does not need to be "in" the account for
the API to validate the campaign.
"""

from __future__ import annotations

from typing import Any

from ..client import get_client
from ..config import get_settings
from ..safety import run_mutation
from ..util import normalize_customer_id
from ._helpers import mutate, set_update_mask, usd_to_micros


def _goal_and_bidding(client, campaign, bidding_goal: str, target_value: float | None) -> str:
    """Map a friendly goal to the AppCampaignSetting goal type + campaign bidding.

    bidding_goal: INSTALLS | INSTALLS_TARGET_CPI | IN_APP_ACTIONS | ROAS.
    Returns the goal-type enum name (for the diff).
    """
    g = bidding_goal.upper()
    setting = campaign.app_campaign_setting
    goal_enum = client.enums.AppCampaignBiddingStrategyGoalTypeEnum
    if g in ("INSTALLS", "INSTALLS_TARGET_CPI"):
        if target_value:
            setting.bidding_strategy_goal_type = goal_enum.OPTIMIZE_INSTALLS_TARGET_INSTALL_COST
            campaign.target_cpa.target_cpa_micros = usd_to_micros(target_value)
            return "OPTIMIZE_INSTALLS_TARGET_INSTALL_COST"
        setting.bidding_strategy_goal_type = goal_enum.OPTIMIZE_INSTALLS_WITHOUT_TARGET_INSTALL_COST
        campaign.maximize_conversions = client.get_type("MaximizeConversions")
        return "OPTIMIZE_INSTALLS_WITHOUT_TARGET_INSTALL_COST"
    if g == "IN_APP_ACTIONS":
        if not target_value:
            raise ValueError("IN_APP_ACTIONS requires target_value (target CPA).")
        setting.bidding_strategy_goal_type = (
            goal_enum.OPTIMIZE_IN_APP_CONVERSIONS_TARGET_CONVERSION_COST
        )
        campaign.target_cpa.target_cpa_micros = usd_to_micros(target_value)
        return "OPTIMIZE_IN_APP_CONVERSIONS_TARGET_CONVERSION_COST"
    if g == "ROAS":
        if not target_value:
            raise ValueError("ROAS requires target_value (e.g. 3.5).")
        setting.bidding_strategy_goal_type = goal_enum.OPTIMIZE_RETURN_ON_ADVERTISING_SPEND
        campaign.target_roas.target_roas = float(target_value)
        return "OPTIMIZE_RETURN_ON_ADVERTISING_SPEND"
    raise ValueError(
        f"Unsupported bidding_goal '{bidding_goal}'. Use INSTALLS, INSTALLS_TARGET_CPI, "
        "IN_APP_ACTIONS, or ROAS."
    )


def build_app_campaign_op(
    client, *, cid, name, app_id, app_store, budget_id, bidding_goal, target_value
) -> tuple:
    """Build the App campaign create operation. Returns (op, goal_type_name)."""
    budget_svc = client.get_service("CampaignBudgetService")
    op = client.get_type("CampaignOperation")
    c = op.create
    c.name = name
    c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.MULTI_CHANNEL
    c.advertising_channel_sub_type = client.enums.AdvertisingChannelSubTypeEnum.APP_CAMPAIGN
    c.status = client.enums.CampaignStatusEnum.PAUSED  # safety: never auto-serve
    c.campaign_budget = budget_svc.campaign_budget_path(cid, budget_id)
    c.app_campaign_setting.app_id = app_id
    c.app_campaign_setting.app_store = client.enums.AppCampaignAppStoreEnum[app_store.upper()]
    goal_name = _goal_and_bidding(client, c, bidding_goal, target_value)
    return op, goal_name


def _criteria_ops(client, cid, campaign_rn, geo_target_constant_ids, language_constant_ids):
    ops = []
    for geo in geo_target_constant_ids or []:
        op = client.get_type("CampaignCriterionOperation")
        op.create.campaign = campaign_rn
        op.create.location.geo_target_constant = f"geoTargetConstants/{geo}"
        ops.append(op)
    for lang in language_constant_ids or []:
        op = client.get_type("CampaignCriterionOperation")
        op.create.campaign = campaign_rn
        op.create.language.language_constant = f"languageConstants/{lang}"
        ops.append(op)
    return ops


def create_app_campaign(
    customer_id: str,
    name: str,
    app_id: str,
    budget_id: str,
    app_store: str = "GOOGLE_APP_STORE",
    bidding_goal: str = "INSTALLS",
    target_value: float | None = None,
    geo_target_constant_ids: list[str] | None = None,
    language_constant_ids: list[str] | None = None,
    validate_only: bool | None = None,
    confirm: bool = False,
    override: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create an App/UAC campaign (always PAUSED) for an existing budget.

    app_id: store id, e.g. 'com.example.app' (Android) or the numeric iOS id.
    app_store: GOOGLE_APP_STORE | APPLE_APP_STORE.
    bidding_goal: INSTALLS | INSTALLS_TARGET_CPI | IN_APP_ACTIONS | ROAS.
    target_value: target CPI/CPA (account currency) or tROAS (e.g. 3.5).
    geo_target_constant_ids / language_constant_ids: applied after creation
        (real apply only; not part of the validate_only campaign check).
    """
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    diff = {
        "action": "create_app_campaign", "name": name, "app_id": app_id,
        "app_store": app_store.upper(), "budget_id": budget_id,
        "bidding_goal": bidding_goal.upper(), "target_value": target_value,
        "status": "PAUSED", "geo": geo_target_constant_ids, "languages": language_constant_ids,
    }
    budget_guard = target_value if bidding_goal.upper() in (
        "INSTALLS_TARGET_CPI", "IN_APP_ACTIONS"
    ) else None

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("CampaignService")
        op, _goal = build_app_campaign_op(
            client, cid=cid, name=name, app_id=app_id, app_store=app_store,
            budget_id=budget_id, bidding_goal=bidding_goal, target_value=target_value,
        )
        resp = mutate(client, svc, request_type="MutateCampaignsRequest",
                      method="mutate_campaigns", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        if validate_only:
            return None
        campaign_rn = resp.results[0].resource_name
        crit_ops = _criteria_ops(
            client, cid, campaign_rn, geo_target_constant_ids, language_constant_ids
        )
        if crit_ops:
            crit_svc = client.get_service("CampaignCriterionService")
            mutate(client, crit_svc, request_type="MutateCampaignCriteriaRequest",
                   method="mutate_campaign_criteria", customer_id=cid,
                   operations=crit_ops, validate_only=False)
        return campaign_rn

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="create_app_campaign",
        args=diff, diff=diff, execute=execute, validate_only=validate_only,
        confirm=confirm, override=override, budget_usd=budget_guard,
    )


def update_app_campaign_targets(
    customer_id: str,
    campaign_id: str,
    target_cpa: float | None = None,
    target_roas: float | None = None,
    budget_id: str | None = None,
    budget_amount_usd: float | None = None,
    validate_only: bool | None = None,
    confirm: bool = False,
    override: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Update an App campaign's target CPA/ROAS and/or its daily budget."""
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    diff = {
        "action": "update_app_campaign_targets", "campaign_id": campaign_id,
        "target_cpa": target_cpa, "target_roas": target_roas,
        "budget_id": budget_id, "budget_amount_usd": budget_amount_usd,
    }
    budget_guard = max(x for x in [target_cpa, budget_amount_usd, 0] if x is not None) or None

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        camp_svc = client.get_service("CampaignService")
        if target_cpa is not None or target_roas is not None:
            op = client.get_type("CampaignOperation")
            op.update.resource_name = camp_svc.campaign_path(cid, campaign_id)
            if target_cpa is not None:
                op.update.target_cpa.target_cpa_micros = usd_to_micros(target_cpa)
            if target_roas is not None:
                op.update.target_roas.target_roas = float(target_roas)
            set_update_mask(client, op)
            mutate(client, camp_svc, request_type="MutateCampaignsRequest",
                   method="mutate_campaigns", customer_id=cid,
                   operations=[op], validate_only=validate_only)
        rn = camp_svc.campaign_path(cid, campaign_id)
        if budget_id and budget_amount_usd is not None:
            budget_svc = client.get_service("CampaignBudgetService")
            bop = client.get_type("CampaignBudgetOperation")
            bop.update.resource_name = budget_svc.campaign_budget_path(cid, budget_id)
            bop.update.amount_micros = usd_to_micros(budget_amount_usd)
            set_update_mask(client, bop)
            mutate(client, budget_svc, request_type="MutateCampaignBudgetsRequest",
                   method="mutate_campaign_budgets", customer_id=cid,
                   operations=[bop], validate_only=validate_only)
        return None if validate_only else rn

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="update_app_campaign_targets",
        args=diff, diff=diff, execute=execute, validate_only=validate_only,
        confirm=confirm, override=override, budget_usd=budget_guard,
    )


def manage_app_assets(
    customer_id: str,
    ad_group_id: str,
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
    youtube_video_ids: list[str] | None = None,
    image_asset_resource_names: list[str] | None = None,
    validate_only: bool | None = None,
    confirm: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Set the assets on an App campaign's App ad (full-replace of the given lists).

    App campaigns have no asset_groups; assets live on the single App ad inside
    the ad group. Pass the ad_group_id of the App campaign. Provided lists REPLACE
    the corresponding asset type on the ad.

    - headlines / descriptions: text (inline AdTextAsset).
    - youtube_video_ids: YouTube video ids (linked as YouTubeVideoAsset).
    - image_asset_resource_names: pre-existing ImageAsset resource names to link.
      (Uploading new image/HTML5 bytes is handled separately via AssetService.)

    NOTE: verified pending a real App campaign on the final account.
    """
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    diff = {
        "action": "manage_app_assets", "ad_group_id": ad_group_id,
        "headlines": headlines, "descriptions": descriptions,
        "youtube_video_ids": youtube_video_ids,
        "image_asset_resource_names": image_asset_resource_names,
    }

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        # The App ad is the single AdGroupAd in the ad group; find it.
        ga = client.get_service("GoogleAdsService")
        query = (
            "SELECT ad_group_ad.ad.resource_name FROM ad_group_ad "
            f"WHERE ad_group.id = {int(ad_group_id)} LIMIT 1"
        )
        ad_rn = None
        for batch in ga.search_stream(customer_id=cid, query=query):
            for row in batch.results:
                ad_rn = row.ad_group_ad.ad.resource_name
        if not ad_rn:
            raise ValueError(f"No App ad found in ad group {ad_group_id}.")

        ad_svc = client.get_service("AdService")
        op = client.get_type("AdOperation")
        op.update.resource_name = ad_rn
        app_ad = op.update.app_ad
        for h in headlines or []:
            asset = client.get_type("AdTextAsset")
            asset.text = h
            app_ad.headlines.append(asset)
        for d in descriptions or []:
            asset = client.get_type("AdTextAsset")
            asset.text = d
            app_ad.descriptions.append(asset)
        for vid in youtube_video_ids or []:
            ad_asset = client.get_type("AdVideoAsset")
            # A YouTube video asset must already exist or be created via AssetService;
            # here we reference by the conventional asset path is not possible from a
            # bare video id, so we create the asset inline through AssetService.
            asset_rn = _ensure_youtube_asset(client, cid, vid, validate_only)
            ad_asset.asset = asset_rn
            app_ad.youtube_videos.append(ad_asset)
        for img_rn in image_asset_resource_names or []:
            ad_asset = client.get_type("AdImageAsset")
            ad_asset.asset = img_rn
            app_ad.images.append(ad_asset)

        mask_fields = []
        if headlines:
            mask_fields.append("app_ad.headlines")
        if descriptions:
            mask_fields.append("app_ad.descriptions")
        if youtube_video_ids:
            mask_fields.append("app_ad.youtube_videos")
        if image_asset_resource_names:
            mask_fields.append("app_ad.images")
        if not mask_fields:
            raise ValueError("Nothing to update: provide at least one asset list.")
        op.update_mask.paths.extend(mask_fields)

        resp = mutate(client, ad_svc, request_type="MutateAdsRequest",
                      method="mutate_ads", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="manage_app_assets",
        args=diff, diff=diff, execute=execute, validate_only=validate_only, confirm=confirm,
    )


def _ensure_youtube_asset(client, cid, video_id, validate_only) -> str:
    """Create a YouTubeVideoAsset and return its resource name."""
    asset_svc = client.get_service("AssetService")
    op = client.get_type("AssetOperation")
    op.create.youtube_video_asset.youtube_video_id = video_id
    resp = mutate(client, asset_svc, request_type="MutateAssetsRequest",
                  method="mutate_assets", customer_id=cid,
                  operations=[op], validate_only=validate_only)
    if validate_only:
        return f"customers/{cid}/assets/0"  # placeholder; not applied
    return resp.results[0].resource_name


def register(mcp) -> None:
    mcp.tool()(create_app_campaign)
    mcp.tool()(update_app_campaign_targets)
    mcp.tool()(manage_app_assets)
