"""Map GoogleAdsException into compact, human-readable text.

Used by every tool so the LLM gets "field / reason / how to fix" instead of a
raw protobuf dump.
"""

from __future__ import annotations

from google.ads.googleads.errors import GoogleAdsException


def format_google_ads_exception(exc: GoogleAdsException) -> str:
    lines: list[str] = []
    request_id = getattr(exc, "request_id", None)
    failure = getattr(exc, "failure", None)
    errors = getattr(failure, "errors", []) if failure is not None else []

    for err in errors:
        # error_code is a oneof; stringify whichever sub-code is set.
        code = getattr(err, "error_code", None)
        code_str = str(code).strip() if code is not None else "UNKNOWN"
        message = getattr(err, "message", "") or ""
        field_path = ""
        location = getattr(err, "location", None)
        if location is not None:
            parts = [
                fp.field_name
                for fp in getattr(location, "field_path_elements", [])
                if getattr(fp, "field_name", None)
            ]
            field_path = " > ".join(parts)

        piece = f"- {message}"
        if field_path:
            piece += f"  [field: {field_path}]"
        if code_str and code_str != "UNKNOWN":
            piece += f"  ({code_str})"
        lines.append(piece)

    if not lines:
        lines.append(f"- {exc}")

    header = "Google Ads API rejected the request:"
    footer = f"(request_id: {request_id})" if request_id else ""
    return "\n".join([header, *lines, footer]).strip()
