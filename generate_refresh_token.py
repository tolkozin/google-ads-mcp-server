"""One-off helper: obtain a Google Ads API refresh token via OAuth.

Run it in YOUR terminal (it opens a browser and starts a local callback server):

    cd "/Users/tolkozin/Google Ads MCP"
    ~/.local/bin/uv run python generate_refresh_token.py \
        --client_id YOUR_CLIENT_ID \
        --client_secret YOUR_CLIENT_SECRET

Sign in with the Google account that has access to the Ads account, approve the
consent screen, and the refresh token is printed at the end. Paste it into
google-ads.yaml as `refresh_token`.
"""

import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main(client_id: str, client_secret: str) -> None:
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    # Opens browser, runs a temporary loopback server to catch the redirect.
    flow.run_local_server(
        port=0,
        prompt="consent",          # force a refresh_token to be issued
        access_type="offline",
        authorization_prompt_message="Opening browser for Google sign-in...",
        success_message="Done — you can close this tab and return to the terminal.",
    )
    creds = flow.credentials
    print("\n" + "=" * 60)
    print("REFRESH TOKEN (copy into google-ads.yaml -> refresh_token):")
    print(creds.refresh_token)
    print("=" * 60)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--client_id", required=True)
    p.add_argument("--client_secret", required=True)
    args = p.parse_args()
    main(args.client_id, args.client_secret)
