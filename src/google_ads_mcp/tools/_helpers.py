"""Shared helpers for building Google Ads mutate operations.

Operation builders are kept as pure functions (client in, operation out) so they
can be snapshot-tested offline — `client.get_type(...)` builds protos without any
network call.
"""

from __future__ import annotations

from google.api_core import protobuf_helpers


def mutate(client, service, *, request_type: str, method: str, customer_id: str,
           operations, validate_only: bool):
    """Build a Mutate*Request (validate_only lives on the request, not the call)
    and invoke the service method."""
    req = client.get_type(request_type)
    req.customer_id = customer_id
    req.operations.extend(operations)
    req.validate_only = validate_only
    return getattr(service, method)(request=req)


def usd_to_micros(amount: float) -> int:
    """Account-currency units -> micros. (Fields are named *_usd for clarity, but
    micros are always in the account's currency.)"""
    return int(round(float(amount) * 1_000_000))


def micros_to_units(micros: int) -> float:
    return int(micros) / 1_000_000


def set_update_mask(client, operation) -> None:
    """Populate operation.update_mask from the fields set on operation.update."""
    client.copy_from(
        operation.update_mask,
        protobuf_helpers.field_mask(None, operation.update._pb),
    )


def apply_bidding(client, campaign, strategy: str, target_value: float | None) -> str:
    """Set a standard (campaign-level) bidding strategy on a campaign proto.
    Returns the top-level oneof field name (for the update mask when updating —
    an empty oneof message like manual_cpc won't be auto-detected otherwise)."""
    s = strategy.upper()
    if s == "MANUAL_CPC":
        # Set a leaf (enhanced_cpc_enabled) — masking the bare message errors.
        campaign.manual_cpc.enhanced_cpc_enabled = False
        return "manual_cpc.enhanced_cpc_enabled"
    if s == "MAXIMIZE_CONVERSIONS":
        campaign.maximize_conversions.target_cpa_micros = usd_to_micros(target_value) if target_value else 0
        return "maximize_conversions.target_cpa_micros"
    if s == "MAXIMIZE_CONVERSION_VALUE":
        campaign.maximize_conversion_value.target_roas = float(target_value) if target_value else 0.0
        return "maximize_conversion_value.target_roas"
    if s == "TARGET_CPA":
        if not target_value:
            raise ValueError("TARGET_CPA requires target_value (target CPA in account currency).")
        campaign.target_cpa.target_cpa_micros = usd_to_micros(target_value)
        return "target_cpa.target_cpa_micros"
    if s == "TARGET_ROAS":
        if not target_value:
            raise ValueError("TARGET_ROAS requires target_value (e.g. 3.5 for 350% ROAS).")
        campaign.target_roas.target_roas = float(target_value)
        return "target_roas.target_roas"
    if s == "TARGET_SPEND":
        campaign.target_spend.cpc_bid_ceiling_micros = usd_to_micros(target_value) if target_value else 0
        return "target_spend.cpc_bid_ceiling_micros"
    raise ValueError(
        f"Unsupported bidding strategy '{strategy}'. Use one of: MANUAL_CPC, "
        "MAXIMIZE_CONVERSIONS, MAXIMIZE_CONVERSION_VALUE, TARGET_CPA, TARGET_ROAS, TARGET_SPEND."
    )
