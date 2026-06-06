#!/usr/bin/env python3
"""Dry-run diagnostic: can the refresh_token in .secrets still mint an access token?

Runs a single OAuth POST (grant_type=refresh_token) against the Claude Code
OAuth endpoint using the refresh_token currently stored in .secrets. Prints the
result. Does NOT persist anything — but note the POST itself rotates the token
server-side (single-use refresh tokens), so the .secrets refresh_token is dead
after a successful mint until re-synced.

Usage (on the mini, as bumba-agent):
    sudo -u bumba-agent env HOME=/opt/bumba-harness \
        python3 /opt/bumba-harness/agent-flat/agent/scripts/diag_token_mint.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS = Path("/opt/bumba-harness/data/.secrets")
OAUTH_URL = "https://console.anthropic.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


def load_secret(key: str) -> str:
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k == key:
            return v
    return ""


def main() -> None:
    refresh_token = load_secret("claude_oauth_refresh_token")
    print("refresh_token tail:", refresh_token[-12:] if refresh_token else "(EMPTY)")
    if not refresh_token:
        print("MINT SKIPPED — no refresh_token in .secrets")
        return

    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        }
    ).encode()
    req = urllib.request.Request(
        OAUTH_URL,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "claude-code/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
        print(
            "MINT OK — new access tail:",
            body.get("access_token", "")[-12:],
            "| expires_in:",
            body.get("expires_in"),
            "| got new refresh:",
            bool(body.get("refresh_token")),
        )
        print(
            ">>> NOTE: this POST just ROTATED the refresh_token server-side. "
            "The new one is NOT saved here. Re-sync from Keychain before relying "
            "on the bridge again."
        )
    except urllib.error.HTTPError as e:
        print("MINT FAILED HTTP", e.code, "—", e.read().decode()[:300])
    except Exception as e:  # noqa: BLE001
        print("MINT ERROR:", type(e).__name__, e)


if __name__ == "__main__":
    main()
