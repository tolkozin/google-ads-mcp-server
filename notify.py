"""Delivery for the daily report: Telegram push + Google Sheet append.

No heavy deps — plain HTTPS via urllib. Secrets live in a gitignored
`automation_secrets.json` next to this file:

    {
      "telegram_token":   "123456:ABC-...",     # from @BotFather
      "telegram_chat_id": "123456789",           # your chat id
      "sheet_webhook_url": "https://script.google.com/macros/s/AKf.../exec"
    }

Anything missing is simply skipped (best-effort; never raises to the caller).

CLI helpers:
    python notify.py --find-chat-id   # print chat ids that messaged your bot
    python notify.py --test           # send a test message + test sheet row
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS = Path(__file__).parent / "automation_secrets.json"


def load_secrets() -> dict:
    if SECRETS.exists():
        try:
            return json.loads(SECRETS.read_text())
        except Exception:
            return {}
    return {}


def _post(url: str, data: bytes, headers: dict, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def send_telegram(text: str, secrets: dict | None = None) -> bool:
    s = secrets or load_secrets()
    token, chat = s.get("telegram_token"), s.get("telegram_chat_id")
    if not token or not chat:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat, "text": text,
        "parse_mode": "Markdown", "disable_web_page_preview": "true",
    }).encode()
    try:
        code, _ = _post(url, payload, {"Content-Type": "application/x-www-form-urlencoded"})
        return code == 200
    except Exception as e:
        print(f"[notify] telegram failed: {e}", file=sys.stderr)
        return False


def append_sheet(row: list, secrets: dict | None = None) -> bool:
    """POST a row to a Google Apps Script web-app webhook that appends to a sheet."""
    s = secrets or load_secrets()
    url = s.get("sheet_webhook_url")
    if not url:
        return False
    try:
        code, _ = _post(url, json.dumps({"row": row}).encode(),
                        {"Content-Type": "application/json"})
        return code in (200, 302)
    except Exception as e:
        print(f"[notify] sheet append failed: {e}", file=sys.stderr)
        return False


def _find_chat_id() -> None:
    s = load_secrets()
    token = s.get("telegram_token")
    if not token:
        print("Set telegram_token in automation_secrets.json first."); return
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20) as r:
        data = json.loads(r.read())
    seen = {}
    for upd in data.get("result", []):
        ch = (upd.get("message") or {}).get("chat") or {}
        if ch.get("id"):
            seen[ch["id"]] = ch.get("username") or ch.get("first_name") or "?"
    if not seen:
        print("No messages yet. Send any message to your bot, then re-run."); return
    print("Chat ids that messaged your bot (put one in telegram_chat_id):")
    for cid, who in seen.items():
        print(f"  {cid}  ({who})")


if __name__ == "__main__":
    if "--find-chat-id" in sys.argv:
        _find_chat_id()
    elif "--test" in sys.argv:
        ok_t = send_telegram("*Test* — Google Ads daily automation is wired up ✅")
        ok_s = append_sheet(["TEST", "row", "from notify.py"])
        print(f"telegram sent: {ok_t} | sheet appended: {ok_s}")
    else:
        print(__doc__)
