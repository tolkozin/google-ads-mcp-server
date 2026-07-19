"""Search-campaign write tools: campaign, ad group, keywords, negatives, RSA, ad
status. All routed through `safety.run_mutation`.

Safety stance: new campaigns are created PAUSED. New ad groups/ads default to
PAUSED too, so nothing serves until you deliberately enable it via
update_campaign_status / update_ad_status.
"""

from __future__ import annotations

from typing import Any

from ..client import get_client
from ..config import get_settings
from ..safety import run_mutation
from ..util import normalize_customer_id
from ._helpers import apply_bidding, mutate, set_update_mask, usd_to_micros


def create_search_campaign(
    customer_id: str,
    name: str,
    budget_id: str,
    bidding_strategy: str = "MAXIMIZE_CONVERSIONS",
    target_value: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    target_search_network: bool = True,
    target_content_network: bool = False,
    validate_only: bool | None = None,
    confirm: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a SEARCH campaign (always PAUSED) using an existing budget.

    Dates are 'YYYY-MM-DD' (or 'YYYYMMDD'). bidding_strategy is applied as a
    standard strategy; see set_campaign_bidding for the allowed values.
    """
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    diff = {
        "action": "create_search_campaign", "name": name, "budget_id": budget_id,
        "bidding_strategy": bidding_strategy.upper(), "target_value": target_value,
        "status": "PAUSED", "start_date": start_date, "end_date": end_date,
        "target_search_network": target_search_network,
        "target_content_network": target_content_network,
    }

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("CampaignService")
        budget_svc = client.get_service("CampaignBudgetService")
        op = client.get_type("CampaignOperation")
        c = op.create
        c.name = name
        c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
        c.status = client.enums.CampaignStatusEnum.PAUSED  # safety: never auto-serve
        c.campaign_budget = budget_svc.campaign_budget_path(cid, budget_id)
        c.network_settings.target_google_search = True
        c.network_settings.target_search_network = target_search_network
        c.network_settings.target_content_network = target_content_network
        c.network_settings.target_partner_search_network = False
        apply_bidding(client, c, bidding_strategy, target_value)
        if start_date:
            c.start_date = start_date.replace("-", "")
        if end_date:
            c.end_date = end_date.replace("-", "")
        resp = mutate(client, svc, request_type="MutateCampaignsRequest",
                      method="mutate_campaigns", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="create_search_campaign",
        args=diff, diff=diff, execute=execute, validate_only=validate_only,
        confirm=confirm, budget_usd=target_value if bidding_strategy.upper() == "TARGET_CPA" else None,
    )


def create_ad_group(
    customer_id: str,
    campaign_id: str,
    name: str,
    default_cpc_bid_usd: float | None = None,
    status: str = "PAUSED",
    validate_only: bool | None = None,
    confirm: bool = False,
    override: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a standard Search ad group under a campaign (PAUSED by default)."""
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    diff = {
        "action": "create_ad_group", "campaign_id": campaign_id, "name": name,
        "default_cpc_bid": default_cpc_bid_usd, "status": status.upper(),
    }

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("AdGroupService")
        camp_svc = client.get_service("CampaignService")
        op = client.get_type("AdGroupOperation")
        g = op.create
        g.name = name
        g.campaign = camp_svc.campaign_path(cid, campaign_id)
        g.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
        g.status = client.enums.AdGroupStatusEnum[status.upper()]
        if default_cpc_bid_usd is not None:
            g.cpc_bid_micros = usd_to_micros(default_cpc_bid_usd)
        resp = mutate(client, svc, request_type="MutateAdGroupsRequest",
                      method="mutate_ad_groups", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="create_ad_group",
        args=diff, diff=diff, execute=execute, validate_only=validate_only,
        confirm=confirm, override=override, budget_usd=default_cpc_bid_usd,
    )


def manage_keywords(
    customer_id: str,
    ad_group_id: str,
    add: list[dict] | None = None,
    remove: list[str] | None = None,
    validate_only: bool | None = None,
    confirm: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Add and/or remove keywords in one ad group.

    add: list of {"text": str, "match_type": "EXACT"|"PHRASE"|"BROAD"}.
    remove: list of criterion_id strings to remove.
    """
    add = add or []
    remove = remove or []
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    diff = {
        "action": "manage_keywords", "ad_group_id": ad_group_id,
        "add": add, "remove": remove,
    }

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("AdGroupCriterionService")
        ag_svc = client.get_service("AdGroupService")
        ag_path = ag_svc.ad_group_path(cid, ad_group_id)
        ops = []
        for kw in add:
            op = client.get_type("AdGroupCriterionOperation")
            c = op.create
            c.ad_group = ag_path
            c.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
            c.keyword.text = kw["text"]
            c.keyword.match_type = client.enums.KeywordMatchTypeEnum[kw["match_type"].upper()]
            ops.append(op)
        for crit_id in remove:
            op = client.get_type("AdGroupCriterionOperation")
            op.remove = svc.ad_group_criterion_path(cid, ad_group_id, crit_id)
            ops.append(op)
        if not ops:
            raise ValueError("Nothing to do: provide at least one keyword to add or remove.")
        resp = mutate(client, svc, request_type="MutateAdGroupCriteriaRequest",
                      method="mutate_ad_group_criteria", customer_id=cid,
                      operations=ops, validate_only=validate_only)
        if validate_only:
            return None
        return f"{len(resp.results)} criteria mutated; first={resp.results[0].resource_name}"

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="manage_keywords",
        args=diff, diff=diff, execute=execute, validate_only=validate_only, confirm=confirm,
    )


def manage_negative_keywords(
    customer_id: str,
    scope: str,
    add: list[dict] | None = None,
    remove: list[str] | None = None,
    ad_group_id: str | None = None,
    campaign_id: str | None = None,
    validate_only: bool | None = None,
    confirm: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Add/remove negative keywords at AD_GROUP or CAMPAIGN scope.

    add: list of {"text": str, "match_type": ...}. remove: list of criterion_ids.
    (SHARED_SET scope is not implemented yet.)
    """
    scope_u = scope.upper()
    add = add or []
    remove = remove or []
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    diff = {
        "action": "manage_negative_keywords", "scope": scope_u,
        "ad_group_id": ad_group_id, "campaign_id": campaign_id,
        "add": add, "remove": remove,
    }

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        if scope_u == "AD_GROUP":
            if not ad_group_id:
                raise ValueError("ad_group_id is required for AD_GROUP scope.")
            svc = client.get_service("AdGroupCriterionService")
            ag_path = client.get_service("AdGroupService").ad_group_path(cid, ad_group_id)
            ops = []
            for kw in add:
                op = client.get_type("AdGroupCriterionOperation")
                c = op.create
                c.ad_group = ag_path
                c.negative = True
                c.keyword.text = kw["text"]
                c.keyword.match_type = client.enums.KeywordMatchTypeEnum[kw["match_type"].upper()]
                ops.append(op)
            for crit_id in remove:
                op = client.get_type("AdGroupCriterionOperation")
                op.remove = svc.ad_group_criterion_path(cid, ad_group_id, crit_id)
                ops.append(op)
            if not ops:
                raise ValueError("Nothing to do.")
            resp = mutate(client, svc, request_type="MutateAdGroupCriteriaRequest",
                          method="mutate_ad_group_criteria", customer_id=cid,
                          operations=ops, validate_only=validate_only)
        elif scope_u == "CAMPAIGN":
            if not campaign_id:
                raise ValueError("campaign_id is required for CAMPAIGN scope.")
            svc = client.get_service("CampaignCriterionService")
            camp_path = client.get_service("CampaignService").campaign_path(cid, campaign_id)
            ops = []
            for kw in add:
                op = client.get_type("CampaignCriterionOperation")
                c = op.create
                c.campaign = camp_path
                c.negative = True
                c.keyword.text = kw["text"]
                c.keyword.match_type = client.enums.KeywordMatchTypeEnum[kw["match_type"].upper()]
                ops.append(op)
            for crit_id in remove:
                op = client.get_type("CampaignCriterionOperation")
                op.remove = svc.campaign_criterion_path(cid, campaign_id, crit_id)
                ops.append(op)
            if not ops:
                raise ValueError("Nothing to do.")
            resp = mutate(client, svc, request_type="MutateCampaignCriteriaRequest",
                          method="mutate_campaign_criteria", customer_id=cid,
                          operations=ops, validate_only=validate_only)
        else:
            raise ValueError(
                f"Unsupported scope '{scope}'. Use AD_GROUP or CAMPAIGN "
                "(SHARED_SET not implemented yet)."
            )
        if validate_only:
            return None
        return f"{len(resp.results)} negative(s) mutated; first={resp.results[0].resource_name}"

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="manage_negative_keywords",
        args=diff, diff=diff, execute=execute, validate_only=validate_only, confirm=confirm,
    )


def create_responsive_search_ad(
    customer_id: str,
    ad_group_id: str,
    headlines: list[str],
    descriptions: list[str],
    final_urls: list[str],
    path1: str | None = None,
    path2: str | None = None,
    status: str = "PAUSED",
    validate_only: bool | None = None,
    confirm: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a Responsive Search Ad (PAUSED by default).

    Requires 3-15 headlines and 2-4 descriptions (Google Ads limits).
    """
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    if not (3 <= len(headlines) <= 15):
        return {"status": "rejected", "message": "RSA needs 3-15 headlines.", "dry_run": True}
    if not (2 <= len(descriptions) <= 4):
        return {"status": "rejected", "message": "RSA needs 2-4 descriptions.", "dry_run": True}
    diff = {
        "action": "create_responsive_search_ad", "ad_group_id": ad_group_id,
        "headlines": headlines, "descriptions": descriptions, "final_urls": final_urls,
        "path1": path1, "path2": path2, "status": status.upper(),
    }

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("AdGroupAdService")
        ag_path = client.get_service("AdGroupService").ad_group_path(cid, ad_group_id)
        op = client.get_type("AdGroupAdOperation")
        aga = op.create
        aga.ad_group = ag_path
        aga.status = client.enums.AdGroupAdStatusEnum[status.upper()]
        aga.ad.final_urls.extend(final_urls)
        rsa = aga.ad.responsive_search_ad
        for h in headlines:
            asset = client.get_type("AdTextAsset")
            asset.text = h
            rsa.headlines.append(asset)
        for d in descriptions:
            asset = client.get_type("AdTextAsset")
            asset.text = d
            rsa.descriptions.append(asset)
        if path1:
            rsa.path1 = path1
        if path2:
            rsa.path2 = path2
        resp = mutate(client, svc, request_type="MutateAdGroupAdsRequest",
                      method="mutate_ad_group_ads", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="create_responsive_search_ad",
        args=diff, diff=diff, execute=execute, validate_only=validate_only, confirm=confirm,
    )


def update_ad_status(
    customer_id: str,
    ad_group_id: str,
    ad_id: str,
    status: str,
    validate_only: bool | None = None,
    confirm: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Set an ad's status within its ad group: ENABLED | PAUSED | REMOVED."""
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    status_u = status.upper()
    diff = {
        "action": "update_ad_status", "ad_group_id": ad_group_id,
        "ad_id": ad_id, "status": status_u,
    }

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("AdGroupAdService")
        op = client.get_type("AdGroupAdOperation")
        op.update.resource_name = svc.ad_group_ad_path(cid, ad_group_id, ad_id)
        op.update.status = client.enums.AdGroupAdStatusEnum[status_u]
        set_update_mask(client, op)
        resp = mutate(client, svc, request_type="MutateAdGroupAdsRequest",
                      method="mutate_ad_group_ads", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="update_ad_status",
        args=diff, diff=diff, execute=execute, validate_only=validate_only, confirm=confirm,
    )


def set_keyword_status(
    customer_id: str,
    ad_group_id: str,
    criterion_ids: list[str],
    status: str,
    validate_only: bool | None = None,
    confirm: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Pause / enable / remove keywords by criterion id (ad_group_criterion status).

    status: ENABLED | PAUSED | REMOVED. Pausing keeps the keyword and its history
    (unlike remove), so it's the reversible way to stop a keyword.
    """
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    status_u = status.upper()
    diff = {"action": "set_keyword_status", "ad_group_id": ad_group_id,
            "criterion_ids": criterion_ids, "status": status_u}

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("AdGroupCriterionService")
        ops = []
        for crit in criterion_ids:
            op = client.get_type("AdGroupCriterionOperation")
            op.update.resource_name = svc.ad_group_criterion_path(cid, ad_group_id, crit)
            op.update.status = client.enums.AdGroupCriterionStatusEnum[status_u]
            set_update_mask(client, op)
            ops.append(op)
        resp = mutate(client, svc, request_type="MutateAdGroupCriteriaRequest",
                      method="mutate_ad_group_criteria", customer_id=cid,
                      operations=ops, validate_only=validate_only)
        return None if validate_only else f"{len(resp.results)} keyword(s) -> {status_u}"

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="set_keyword_status",
        args=diff, diff=diff, execute=execute, validate_only=validate_only, confirm=confirm,
    )


def set_ad_group_bid(
    customer_id: str,
    ad_group_id: str,
    cpc_bid_usd: float,
    validate_only: bool | None = None,
    confirm: bool = False,
    override: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Set an ad group's default max CPC bid (only effective under Manual/eCPC)."""
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    micros = usd_to_micros(cpc_bid_usd)
    diff = {"action": "set_ad_group_bid", "ad_group_id": ad_group_id, "cpc_bid_usd": cpc_bid_usd}

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("AdGroupService")
        op = client.get_type("AdGroupOperation")
        op.update.resource_name = svc.ad_group_path(cid, ad_group_id)
        op.update.cpc_bid_micros = micros
        set_update_mask(client, op)
        resp = mutate(client, svc, request_type="MutateAdGroupsRequest",
                      method="mutate_ad_groups", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="set_ad_group_bid",
        args=diff, diff=diff, execute=execute, validate_only=validate_only,
        confirm=confirm, override=override, budget_usd=cpc_bid_usd,
    )


def register(mcp) -> None:
    mcp.tool()(create_search_campaign)
    mcp.tool()(create_ad_group)
    mcp.tool()(manage_keywords)
    mcp.tool()(manage_negative_keywords)
    mcp.tool()(create_responsive_search_ad)
    mcp.tool()(update_ad_status)
    mcp.tool()(set_keyword_status)
    mcp.tool()(set_ad_group_bid)
