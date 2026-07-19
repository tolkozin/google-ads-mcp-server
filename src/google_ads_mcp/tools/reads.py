"""Read-only tools: always available, no mutation gating.

These are pure functions returning the unified dict envelope so they can be unit
tested without an MCP transport. `server.py` wraps them as MCP tools.
"""

from __future__ import annotations

import re
from typing import Any

from google.ads.googleads.errors import GoogleAdsException
from google.protobuf.json_format import MessageToDict

from ..client import get_client, get_service
from ..errors import format_google_ads_exception
from ..schemas import error, ok
from ..util import normalize_customer_id

_ID_RE = re.compile(r"customers/(\d+)")


def list_accessible_customers() -> dict[str, Any]:
    """List the customer ids the authenticated user can access.

    Returns ids (no dashes) parsed from the resource names. These are the values
    to pass as `customer_id` to other tools.
    """
    try:
        service = get_service("CustomerService")
        response = service.list_accessible_customers()
        customers = []
        for resource_name in response.resource_names:
            m = _ID_RE.search(resource_name)
            customers.append(
                {
                    "customer_id": m.group(1) if m else resource_name,
                    "resource_name": resource_name,
                }
            )
        return ok(
            message=f"{len(customers)} accessible customer(s).",
            data={"customers": customers},
        )
    except GoogleAdsException as exc:
        return error(format_google_ads_exception(exc))


def search(
    customer_id: str,
    gaql: str,
    page_size: int = 1000,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Run a GAQL query against one account and return the rows.

    Args:
        customer_id: Account to query (dashes stripped).
        gaql: A GAQL statement with a SELECT clause.
        page_size: Max rows to return.
        login_customer_id: Optional manager/login id to use in the request
            header. Needed for accounts NOT under the manager in google-ads.yaml
            (pass the account's own id for direct-access accounts).

    Example:
        search("1234567890",
               "SELECT campaign.id, campaign.name, campaign.status "
               "FROM campaign WHERE campaign.status != 'REMOVED' LIMIT 50")
    """
    cid = normalize_customer_id(customer_id)
    if not cid:
        return error("customer_id is empty or invalid.")
    if not gaql or "select" not in gaql.lower():
        return error("gaql must be a valid GAQL query containing a SELECT clause.")

    try:
        service = get_service("GoogleAdsService", login_customer_id=login_customer_id)
        stream = service.search_stream(customer_id=cid, query=gaql)
        rows: list[dict[str, Any]] = []
        for batch in stream:
            for row in batch.results:
                rows.append(
                    MessageToDict(row._pb, preserving_proto_field_name=True)
                )
                if len(rows) >= page_size:
                    break
            if len(rows) >= page_size:
                break
        return ok(
            message=f"{len(rows)} row(s) returned.",
            data={"rows": rows, "truncated": len(rows) >= page_size},
        )
    except GoogleAdsException as exc:
        return error(format_google_ads_exception(exc))


def describe_resource(resource: str) -> dict[str, Any]:
    """Discover selectable/filterable fields of a resource, metric, or segment.

    Helps build GAQL. Pass a resource name like 'campaign', 'ad_group',
    'keyword_view', or a prefix like 'metrics' / 'segments'.

    Example: describe_resource("campaign")
    """
    prefix = (resource or "").strip().rstrip(".")
    if not prefix:
        return error("resource is required, e.g. 'campaign' or 'metrics'.")

    query = (
        "SELECT name, category, data_type, selectable, filterable, sortable, "
        "is_repeated WHERE name LIKE '{}.%' ORDER BY name"
    ).format(prefix)

    try:
        service = get_client().get_service("GoogleAdsFieldService")
        response = service.search_google_ads_fields(query=query)
        fields = []
        for f in response:
            fields.append(
                {
                    "name": f.name,
                    "category": str(f.category),
                    "data_type": str(f.data_type),
                    "selectable": f.selectable,
                    "filterable": f.filterable,
                    "sortable": f.sortable,
                    "is_repeated": f.is_repeated,
                }
            )
        if not fields:
            return ok(
                message=f"No fields found for prefix '{prefix}'. "
                "Try a bare resource name like 'campaign' or 'ad_group'.",
                data={"fields": []},
            )
        return ok(
            message=f"{len(fields)} field(s) under '{prefix}'.",
            data={"fields": fields},
        )
    except GoogleAdsException as exc:
        return error(format_google_ads_exception(exc))
