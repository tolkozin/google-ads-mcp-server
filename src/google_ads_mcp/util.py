"""Small shared helpers."""

from __future__ import annotations

import re


def normalize_customer_id(customer_id: str) -> str:
    """Strip dashes/whitespace so '123-456-7890' -> '1234567890'."""
    return re.sub(r"\D", "", customer_id or "")
