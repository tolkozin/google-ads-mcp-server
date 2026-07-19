# Google Ads MCP

An [MCP](https://modelcontextprotocol.io) server that lets an LLM agent operate
Google Ads — both **Search** and **App/UAC** campaigns. It exposes read tools
(GAQL) always, and guarded write tools behind a mutation flag.

> **Status:** Phase 1 — reads only (`list_accessible_customers`, `search`,
> `describe_resource`). Writes (budgets, campaigns, ad groups, keywords, ads,
> UAC) land in later phases behind `ADS_MCP_ENABLE_MUTATIONS`.

Design principles: every change will be reversible, confirmable, account- and
budget-scoped. Reads are always safe.

## Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- A Google Ads **developer token**, an OAuth2 client, and a **refresh token**.
- Google Ads API version is **pinned to v23** in `src/google_ads_mcp/config.py`.

## Install

```bash
uv sync --extra dev
```

## Getting credentials

You need five values in a `google-ads.yaml` file (copy from
`google-ads.yaml.example`).

1. **developer_token** — Google Ads UI → Tools → API Center. Basic Access is
   enough (15k operations/day).
2. **OAuth client** (`client_id`, `client_secret`) — Google Cloud Console →
   *APIs & Services → Credentials → Create OAuth client ID → Desktop app*.
   Enable the *Google Ads API* for the project first.
3. **refresh_token** — generate once with the OAuth consent flow for scope
   `https://www.googleapis.com/auth/adwords`. The official google-ads-python repo
   ships `generate_user_credentials.py` for exactly this; run it with your
   client id/secret and paste the resulting refresh token.
4. **login_customer_id** — your manager (MCC) account id without dashes. Omit if
   you authenticate directly against a single account.

Then:

```bash
cp google-ads.yaml.example google-ads.yaml   # fill in real values (gitignored)
cp .env.example .env                          # set GOOGLE_ADS_CREDENTIALS to its path
export GOOGLE_ADS_CREDENTIALS="$PWD/google-ads.yaml"
```

> Secrets are never committed. `google-ads.yaml`, `.env`, and `*.audit.jsonl`
> are gitignored.

## Run

```bash
# stdio (default — what Claude Desktop uses)
uv run google-ads-mcp

# or HTTP (future Cloud Run hosting)
ADS_MCP_HTTP=true uv run google-ads-mcp
```

## Connect to Claude Desktop

Edit Claude Desktop's config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add an entry (use absolute paths):

```json
{
  "mcpServers": {
    "google-ads": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/Google Ads MCP",
        "run",
        "google-ads-mcp"
      ],
      "env": {
        "GOOGLE_ADS_CREDENTIALS": "/absolute/path/to/Google Ads MCP/google-ads.yaml"
      }
    }
  }
}
```

If `uv` isn't on Claude Desktop's PATH, use its absolute path (`which uv`).
Restart Claude Desktop. The three read tools appear under the 🔌 connector menu.

### First check

Ask Claude: *"List my accessible Google Ads customers"*, then
*"Run this GAQL on account <id>: SELECT campaign.id, campaign.name,
campaign.status FROM campaign LIMIT 10"*.

## Tools (Phase 1)

| Tool | Description |
|------|-------------|
| `list_accessible_customers()` | Customer ids the auth user can access. |
| `search(customer_id, gaql, page_size=1000)` | Execute a GAQL query. |
| `describe_resource(resource)` | Discover selectable/filterable fields for GAQL. |

All return a unified envelope: `{status, dry_run, resource_name, diff, message, data}`.

## Safety flags (parsed now, enforced from Phase 2)

| Env var | Default | Purpose |
|---------|---------|---------|
| `ADS_MCP_ENABLE_MUTATIONS` | `false` | Master switch for all write tools. |
| `GOOGLE_ADS_ALLOWED_CUSTOMER_IDS` | *(empty)* | CSV allowlist of customer ids. |
| `GOOGLE_ADS_MAX_DAILY_BUDGET_USD` | `100` | Budget/bid ceiling without `override`. |
| `GOOGLE_ADS_DEFAULT_VALIDATE_ONLY` | `true` | Mutations dry-run by default. |
| `GOOGLE_ADS_AUDIT_LOG` | `./google-ads.audit.jsonl` | Applied-change log. |

## Security model

- **Secrets never enter git.** `google-ads.yaml`, `.env`, and `*.audit.jsonl` are
  gitignored. The repo ships only `*.example` files with placeholders. Account
  ids and app ids in tests are fake.
- **Writes are off by default** (`ADS_MCP_ENABLE_MUTATIONS=false`).
- **Allowlist** — mutations are refused for any account outside
  `GOOGLE_ADS_ALLOWED_CUSTOMER_IDS`. Reads are unaffected.
- **Budget cap** — a budget/bid above `GOOGLE_ADS_MAX_DAILY_BUDGET_USD` is
  refused unless the call passes `override=true`.
- **Two-key apply** — a real change needs BOTH `validate_only=false` AND
  `confirm=true`. Otherwise the tool returns the diff (validate_only) or a
  preview, applying nothing.
- **New campaigns/ad groups/ads are created PAUSED** — nothing serves until you
  deliberately enable it.
- **Audit log** — every applied change (and every failure during apply) is
  appended to the JSONL audit log; dry-runs are not logged as applied.
- **Atomic batches** — multi-operation tools (`manage_keywords`,
  `manage_negative_keywords`) are all-or-nothing by design (no `partial_failure`),
  so a batch never half-applies.

If a credential is ever exposed, rotate it: developer token in the Ads API
Center, OAuth client secret in Google Cloud Console → Credentials.

## Tests

```bash
uv run pytest          # offline tests (no network); live calls need real creds
```

## Roadmap

1. ✅ Skeleton + reads.
2. ✅ Safety layer (validate_only wrapper, allowlist, budget guard, confirm, audit, error mapping) — see `safety.py`, `audit.py`, `tests/test_guardrails.py`.
3. ✅ Search writes (budget → campaign → ad group → keywords/negatives → RSA → statuses) — `writes_common.py`, `writes_search.py`. New campaigns/ad groups/ads are created PAUSED; live validate_only verified.
4. ✅ UAC writes (app campaign, app assets, target updates) — `writes_app.py`. App campaigns created PAUSED; create_app_campaign structurally validated against the live API. Real apply + manage_app_assets verify on the final account (where the app is provisioned).
5. ✅ Hardening + packaging (green pytest suite, security model documented, secret scan, optional HTTP transport for Cloud Run).
