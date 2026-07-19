"""MCP server entry point.

Transport defaults to stdio (for Claude Desktop). Set ADS_MCP_HTTP=true to run
the streamable-HTTP transport instead (for future Cloud Run hosting).

Read tools are always registered. Write tools are registered in later phases and
gated behind `Settings.enable_mutations`.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from .config import API_VERSION, get_settings
from .tools import reads

mcp = FastMCP("google-ads-mcp")


# --- Read tools (always available) ------------------------------------------

@mcp.tool()
def list_accessible_customers() -> dict:
    """List Google Ads customer ids the authenticated user can access."""
    return reads.list_accessible_customers()


@mcp.tool()
def search(
    customer_id: str,
    gaql: str,
    page_size: int = 1000,
    login_customer_id: str | None = None,
) -> dict:
    """Run a GAQL query against one account and return the matching rows.

    Args:
        customer_id: Account id (dashes are stripped automatically).
        gaql: A Google Ads Query Language statement containing a SELECT clause.
        page_size: Max rows to return (default 1000).
        login_customer_id: Optional manager/login id for accounts not under the
            manager in google-ads.yaml. For a direct-access account, pass its own
            id here.
    """
    return reads.search(customer_id, gaql, page_size, login_customer_id)


@mcp.tool()
def describe_resource(resource: str) -> dict:
    """Discover selectable/filterable fields of a resource to help build GAQL.

    Args:
        resource: A resource/metric/segment prefix, e.g. 'campaign', 'ad_group',
            'metrics', 'segments'.
    """
    return reads.describe_resource(resource)


def _register_mutations() -> None:
    """Register write tools — only called when ADS_MCP_ENABLE_MUTATIONS=true."""
    from .tools import writes_app, writes_common, writes_search

    writes_common.register(mcp)  # budgets, campaign status, bidding
    writes_search.register(mcp)  # search campaign, ad group, keywords, RSA, ad status
    writes_app.register(mcp)  # app campaign, app assets, app target updates


def main() -> None:
    settings = get_settings()
    if settings.enable_mutations:
        _register_mutations()

    if os.getenv("ADS_MCP_HTTP", "false").lower() == "true":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
