"""Guardrail + confirm/validate_only tests — fully mocked, no network."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.ads.googleads.errors import GoogleAdsException

from google_ads_mcp.config import Settings
from google_ads_mcp.safety import run_mutation

ALLOWED = "1111111111"
BLOCKED = "2222222222"


def make_settings(tmp_path: Path, **over) -> Settings:
    base = dict(
        credentials_path=Path("/nonexistent/google-ads.yaml"),
        enable_mutations=True,
        allowed_customer_ids=frozenset({ALLOWED}),
        max_daily_budget_usd=50.0,
        default_validate_only=True,
        audit_log_path=tmp_path / "audit.jsonl",
    )
    base.update(over)
    return Settings(**base)


def call(settings, execute, **over):
    kwargs = dict(
        settings=settings,
        customer_id=ALLOWED,
        tool="dummy_tool",
        args={"x": 1},
        diff={"before": 1, "after": 2},
        execute=execute,
    )
    kwargs.update(over)
    return run_mutation(**kwargs)


def test_writes_disabled_is_rejected(tmp_path):
    execute = MagicMock()
    resp = call(make_settings(tmp_path, enable_mutations=False), execute)
    assert resp["status"] == "rejected"
    execute.assert_not_called()


def test_allowlist_blocks_other_account(tmp_path):
    execute = MagicMock()
    resp = call(make_settings(tmp_path), execute, customer_id=BLOCKED)
    assert resp["status"] == "rejected"
    assert BLOCKED in resp["message"]
    execute.assert_not_called()


def test_empty_allowlist_allows_any(tmp_path):
    execute = MagicMock(return_value=None)
    settings = make_settings(tmp_path, allowed_customer_ids=frozenset())
    resp = call(settings, execute, customer_id=BLOCKED, validate_only=True)
    assert resp["status"] == "ok"
    execute.assert_called_once_with(validate_only=True)


def test_budget_over_cap_rejected_without_override(tmp_path):
    execute = MagicMock()
    resp = call(make_settings(tmp_path), execute, budget_usd=200.0)
    assert resp["status"] == "rejected"
    execute.assert_not_called()


def test_budget_over_cap_allowed_with_override(tmp_path):
    execute = MagicMock(return_value=None)
    resp = call(make_settings(tmp_path), execute, budget_usd=200.0, override=True, validate_only=True)
    assert resp["status"] == "ok"
    assert resp["dry_run"] is True


def test_validate_only_does_not_apply(tmp_path):
    execute = MagicMock(return_value=None)
    resp = call(make_settings(tmp_path), execute, validate_only=True)
    assert resp["status"] == "ok"
    assert resp["dry_run"] is True
    execute.assert_called_once_with(validate_only=True)
    assert not (tmp_path / "audit.jsonl").exists()  # dry-run is not audited as applied


def test_apply_without_confirm_only_previews(tmp_path):
    execute = MagicMock(return_value="customers/1111111111/campaignBudgets/1")
    resp = call(make_settings(tmp_path), execute, validate_only=False, confirm=False)
    assert resp["status"] == "ok"
    assert resp["dry_run"] is True
    execute.assert_not_called()  # nothing applied without confirm


def test_apply_with_confirm_executes_and_audits(tmp_path):
    rn = "customers/1111111111/campaignBudgets/1"
    execute = MagicMock(return_value=rn)
    resp = call(make_settings(tmp_path), execute, validate_only=False, confirm=True)
    assert resp["status"] == "ok"
    assert resp["dry_run"] is False
    assert resp["resource_name"] == rn
    execute.assert_called_once_with(validate_only=False)

    log = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
    assert len(log) == 1
    rec = json.loads(log[0])
    assert rec["customer_id"] == ALLOWED
    assert rec["resource_name"] == rn
    assert rec["dry_run"] is False
    assert rec["result"]["status"] == "ok"


def _fake_google_ads_exception() -> GoogleAdsException:
    failure = SimpleNamespace(
        errors=[SimpleNamespace(message="Budget too low", error_code="X", location=None)]
    )
    return GoogleAdsException(error=None, call=None, failure=failure, request_id="req-123")


def test_apply_error_is_mapped_and_audited(tmp_path):
    execute = MagicMock(side_effect=_fake_google_ads_exception())
    resp = call(make_settings(tmp_path), execute, validate_only=False, confirm=True)
    assert resp["status"] == "error"
    assert "Budget too low" in resp["message"]

    rec = json.loads((tmp_path / "audit.jsonl").read_text().strip())
    assert rec["result"]["status"] == "error"
    assert rec["resource_name"] is None
