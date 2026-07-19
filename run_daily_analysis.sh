#!/bin/bash
# Wrapper for the daily Google Ads analysis (invoked by launchd at 10:00).
# Read-only: writes reports/YYYY-MM-DD.md, applies no changes.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
export GOOGLE_ADS_CREDENTIALS="$PWD/google-ads.yaml"
# Account id and any overrides live in gitignored .env
set -a; [ -f .env ] && . ./.env; set +a
mkdir -p reports logs
# Run and tee a log; macOS notification on finish (best-effort).
if uv run python daily_analysis.py >> "logs/daily.log" 2>&1; then
  # Auto-open today's two dashboards (Search + UAC) in the default browser.
  for page in search uac; do
    f="reports/$(date +%Y-%m-%d)-$page.html"
    [ -f "$f" ] && open "$f" 2>/dev/null || true
  done
  osascript -e 'display notification "Search + UAC dashboards opened" with title "Google Ads daily analysis"' 2>/dev/null || true
else
  osascript -e 'display notification "Analysis FAILED — see logs/daily.log" with title "Google Ads daily analysis"' 2>/dev/null || true
fi
