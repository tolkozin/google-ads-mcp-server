"""Append-only JSONL audit log of mutation attempts.

Every real (applied) change is recorded. Dry-runs are recorded too, flagged
`dry_run: true`, so the log is a complete history of what the agent tried.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log_change(
    audit_log_path: Path,
    *,
    customer_id: str,
    tool: str,
    args: dict[str, Any],
    resource_name: str | None,
    result: dict[str, Any],
    dry_run: bool,
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "customer_id": customer_id,
        "tool": tool,
        "args": args,
        "resource_name": resource_name,
        "result": result,
        "dry_run": dry_run,
    }
    path = Path(audit_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
