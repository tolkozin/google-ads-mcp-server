"""Guardrails + the confirm/validate_only orchestration for every mutate tool.

Phase 3/4 tools never talk to the API directly. They build a `diff` describing
the change and an `execute(validate_only) -> resource_name` callable, then hand
both to `run_mutation`, which enforces — in order:

1. writes must be enabled (ADS_MCP_ENABLE_MUTATIONS=true);
2. customer_id must be in the allowlist;
3. budget/bid must be within the cap (unless override=true);
4. dry-run (validate_only) calls the API with native validate_only and applies
   nothing;
5. a real apply requires BOTH validate_only=false AND confirm=true — otherwise
   the tool only returns the diff for review;
6. every real apply (and its failures) is written to the audit log.
"""

from __future__ import annotations

from typing import Any, Callable

from google.ads.googleads.errors import GoogleAdsException

from . import audit
from .config import Settings
from .errors import format_google_ads_exception
from .schemas import error, ok, rejected
from .util import normalize_customer_id


class GuardRejection(Exception):
    """A guardrail blocked the operation before any API call."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def ensure_writes_enabled(settings: Settings) -> None:
    if not settings.enable_mutations:
        raise GuardRejection(
            "Write tools are disabled. Set ADS_MCP_ENABLE_MUTATIONS=true to enable them."
        )


def ensure_allowed(customer_id: str, settings: Settings) -> str:
    cid = normalize_customer_id(customer_id)
    if not cid:
        raise GuardRejection("customer_id is empty or invalid.")
    if settings.allowed_customer_ids and cid not in settings.allowed_customer_ids:
        allowed = ", ".join(sorted(settings.allowed_customer_ids))
        raise GuardRejection(
            f"customer_id {cid} is not in the allowlist [{allowed}]. "
            "Refusing to operate outside allowed accounts."
        )
    return cid


def ensure_budget_within_cap(
    amount_usd: float | None, settings: Settings, override: bool
) -> None:
    if amount_usd is None:
        return
    if amount_usd > settings.max_daily_budget_usd and not override:
        raise GuardRejection(
            f"Requested amount {amount_usd} USD exceeds the cap "
            f"{settings.max_daily_budget_usd} USD. Pass override=true to exceed it deliberately."
        )


def run_mutation(
    *,
    settings: Settings,
    customer_id: str,
    tool: str,
    args: dict[str, Any],
    diff: dict[str, Any],
    execute: Callable[..., str | None],
    validate_only: bool | None = None,
    confirm: bool = False,
    override: bool = False,
    budget_usd: float | None = None,
) -> dict[str, Any]:
    """Run a guarded mutation. See module docstring for the enforced order.

    `execute` is called as `execute(validate_only=...)` and must perform the API
    mutate, returning the new/affected resource_name (or None for validate-only).
    """
    # 1-3: guardrails (no API call yet).
    try:
        ensure_writes_enabled(settings)
        cid = ensure_allowed(customer_id, settings)
        ensure_budget_within_cap(budget_usd, settings, override)
    except GuardRejection as g:
        return rejected(g.message, diff=diff)

    if validate_only is None:
        validate_only = settings.default_validate_only

    # 4: dry-run — native validate_only, applies nothing.
    if validate_only:
        try:
            execute(validate_only=True)
        except GoogleAdsException as exc:
            return error(format_google_ads_exception(exc), dry_run=True, diff=diff)
        return ok(
            message=(
                "Dry-run OK (validate_only=true): the API accepted this change but "
                "nothing was applied. Re-call with validate_only=false AND confirm=true to apply."
            ),
            dry_run=True,
            diff=diff,
        )

    # 5: real apply needs explicit confirm.
    if not confirm:
        return ok(
            message=(
                "Confirmation required. Review the diff; to actually apply, re-call with "
                "validate_only=false AND confirm=true."
            ),
            dry_run=True,
            diff=diff,
        )

    # 6: apply for real + audit.
    try:
        resource_name = execute(validate_only=False)
    except GoogleAdsException as exc:
        msg = format_google_ads_exception(exc)
        audit.log_change(
            settings.audit_log_path,
            customer_id=cid,
            tool=tool,
            args=args,
            resource_name=None,
            result={"status": "error", "message": msg},
            dry_run=False,
        )
        return error(msg, diff=diff)

    audit.log_change(
        settings.audit_log_path,
        customer_id=cid,
        tool=tool,
        args=args,
        resource_name=resource_name,
        result={"status": "ok"},
        dry_run=False,
    )
    return ok(
        message="Applied.",
        dry_run=False,
        resource_name=resource_name,
        diff=diff,
    )
