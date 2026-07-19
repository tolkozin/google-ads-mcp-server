"""Write tools shared by Search and App/UAC campaigns: budgets, campaign status,
campaign bidding. All routed through `safety.run_mutation` (allowlist, budget cap,
validate_only dry-run, confirm-to-apply, audit)."""

from __future__ import annotations

from typing import Any

from ..client import get_client
from ..config import get_settings
from ..safety import run_mutation
from ..util import normalize_customer_id
from ._helpers import apply_bidding, mutate, set_update_mask, usd_to_micros

# --- builders (pure, offline-testable) --------------------------------------

def build_create_budget_op(client, name: str, micros: int, delivery: str):
    op = client.get_type("CampaignBudgetOperation")
    b = op.create
    b.name = name
    b.amount_micros = micros
    b.delivery_method = client.enums.BudgetDeliveryMethodEnum[delivery.upper()]
    b.explicitly_shared = False
    return op


def build_update_budget_op(client, resource_name: str, micros: int):
    op = client.get_type("CampaignBudgetOperation")
    op.update.resource_name = resource_name
    op.update.amount_micros = micros
    set_update_mask(client, op)
    return op


# --- tools -------------------------------------------------------------------

def create_campaign_budget(
    customer_id: str,
    name: str,
    amount_usd: float,
    delivery: str = "STANDARD",
    validate_only: bool | None = None,
    confirm: bool = False,
    override: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a shared-pool daily campaign budget.

    amount_usd is the average DAILY budget in the account currency. Guardrails:
    above the cap needs override=true; nothing is applied without confirm=true.
    """
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    micros = usd_to_micros(amount_usd)
    diff = {
        "action": "create_campaign_budget",
        "name": name,
        "daily_amount": amount_usd,
        "amount_micros": micros,
        "delivery": delivery.upper(),
    }

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("CampaignBudgetService")
        op = build_create_budget_op(client, name, micros, delivery)
        resp = mutate(client, svc, request_type="MutateCampaignBudgetsRequest",
                      method="mutate_campaign_budgets", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="create_campaign_budget",
        args=diff, diff=diff, execute=execute, validate_only=validate_only,
        confirm=confirm, override=override, budget_usd=amount_usd,
    )


def update_campaign_budget(
    customer_id: str,
    budget_id: str,
    amount_usd: float,
    validate_only: bool | None = None,
    confirm: bool = False,
    override: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Change the daily amount of an existing campaign budget."""
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    micros = usd_to_micros(amount_usd)
    diff = {
        "action": "update_campaign_budget",
        "budget_id": budget_id,
        "new_daily_amount": amount_usd,
        "amount_micros": micros,
    }

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("CampaignBudgetService")
        rn = svc.campaign_budget_path(cid, budget_id)
        op = build_update_budget_op(client, rn, micros)
        resp = mutate(client, svc, request_type="MutateCampaignBudgetsRequest",
                      method="mutate_campaign_budgets", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="update_campaign_budget",
        args=diff, diff=diff, execute=execute, validate_only=validate_only,
        confirm=confirm, override=override, budget_usd=amount_usd,
    )


def update_campaign_status(
    customer_id: str,
    campaign_id: str,
    status: str,
    validate_only: bool | None = None,
    confirm: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Set a campaign's status: ENABLED | PAUSED | REMOVED."""
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    status_u = status.upper()
    diff = {"action": "update_campaign_status", "campaign_id": campaign_id, "status": status_u}

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("CampaignService")
        op = client.get_type("CampaignOperation")
        op.update.resource_name = svc.campaign_path(cid, campaign_id)
        op.update.status = client.enums.CampaignStatusEnum[status_u]
        set_update_mask(client, op)
        resp = mutate(client, svc, request_type="MutateCampaignsRequest",
                      method="mutate_campaigns", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="update_campaign_status",
        args=diff, diff=diff, execute=execute, validate_only=validate_only, confirm=confirm,
    )


def set_campaign_bidding(
    customer_id: str,
    campaign_id: str,
    strategy: str,
    target_value: float | None = None,
    validate_only: bool | None = None,
    confirm: bool = False,
    override: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Set a campaign's standard bidding strategy.

    strategy: MAXIMIZE_CONVERSIONS | MAXIMIZE_CONVERSION_VALUE | TARGET_CPA |
    TARGET_ROAS | TARGET_SPEND | MANUAL_CPC. target_value is the tCPA (account
    currency) or tROAS (e.g. 3.5) where applicable.
    """
    settings = get_settings()
    cid = normalize_customer_id(customer_id)
    diff = {
        "action": "set_campaign_bidding", "campaign_id": campaign_id,
        "strategy": strategy.upper(), "target_value": target_value,
    }
    # A tCPA target counts as a "bid" for the budget cap.
    budget_guard = target_value if strategy.upper() == "TARGET_CPA" else None

    def execute(validate_only: bool):
        client = get_client(login_customer_id)
        svc = client.get_service("CampaignService")
        op = client.get_type("CampaignOperation")
        op.update.resource_name = svc.campaign_path(cid, campaign_id)
        field = apply_bidding(client, op.update, strategy, target_value)
        op.update_mask.paths.append(field)  # explicit: empty oneof msgs evade auto-mask
        resp = mutate(client, svc, request_type="MutateCampaignsRequest",
                      method="mutate_campaigns", customer_id=cid,
                      operations=[op], validate_only=validate_only)
        return None if validate_only else resp.results[0].resource_name

    return run_mutation(
        settings=settings, customer_id=customer_id, tool="set_campaign_bidding",
        args=diff, diff=diff, execute=execute, validate_only=validate_only,
        confirm=confirm, override=override, budget_usd=budget_guard,
    )


def register(mcp) -> None:
    mcp.tool()(create_campaign_budget)
    mcp.tool()(update_campaign_budget)
    mcp.tool()(update_campaign_status)
    mcp.tool()(set_campaign_bidding)
