"""Shared response shape for every tool.

The unified envelope `{status, dry_run, resource_name, diff, message}` keeps the
LLM's parsing predictable across reads and (later) mutates.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResponse(BaseModel):
    status: Literal["ok", "error", "rejected"] = "ok"
    dry_run: bool = False
    resource_name: str | None = None
    diff: dict[str, Any] | None = None
    message: str = ""
    data: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


def ok(message: str = "", **kwargs: Any) -> dict[str, Any]:
    return ToolResponse(status="ok", message=message, **kwargs).to_dict()


def error(message: str, **kwargs: Any) -> dict[str, Any]:
    return ToolResponse(status="error", message=message, **kwargs).to_dict()


def rejected(message: str, **kwargs: Any) -> dict[str, Any]:
    """A guardrail blocked the operation (not an API failure)."""
    return ToolResponse(status="rejected", message=message, **kwargs).to_dict()
