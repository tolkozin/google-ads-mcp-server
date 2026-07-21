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
  # Reports are markdown history + a Telegram push; the interactive view is the
  # Streamlit dashboard (run separately). No browser tabs are opened here.
  osascript -e 'display notification "Daily report ready (reports/ + Telegram)" with title "Google Ads daily analysis"' 2>/dev/null || true
else
  osascript -e 'display notification "Analysis FAILED — see logs/daily.log" with title "Google Ads daily analysis"' 2>/dev/null || true
fi
