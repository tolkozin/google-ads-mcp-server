"""Smoke tests that do NOT hit the network.

They verify input validation guards and that the server registers its tools.
Live GAQL calls are exercised separately once real credentials exist.
"""

from google_ads_mcp.tools import reads
from google_ads_mcp.util import normalize_customer_id


def test_normalize_customer_id_strips_dashes():
    assert normalize_customer_id("123-456-7890") == "1234567890"
    assert normalize_customer_id("  987 654 3210 ") == "9876543210"


def test_search_rejects_empty_customer_id():
    resp = reads.search("", "SELECT campaign.id FROM campaign")
    assert resp["status"] == "error"


def test_search_rejects_non_gaql():
    resp = reads.search("1234567890", "not a query")
    assert resp["status"] == "error"


def test_describe_resource_requires_input():
    resp = reads.describe_resource("")
    assert resp["status"] == "error"


def test_server_registers_read_tools():
    import asyncio

    from google_ads_mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert {"list_accessible_customers", "search", "describe_resource"} <= names
