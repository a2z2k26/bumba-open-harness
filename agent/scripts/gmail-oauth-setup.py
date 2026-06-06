#!/usr/bin/env python3
"""Gmail OAuth setup — run once per account from admin terminal.

Usage:
    python gmail-oauth-setup.py --account agent --credentials client_secret.json
    python gmail-oauth-setup.py --account personal --credentials client_secret.json
    python gmail-oauth-setup.py --account workspace --credentials client_secret.json

Prerequisites:
    1. Create Google Cloud project at console.cloud.google.com
    2. Enable Gmail API + Google Calendar API
    3. Create OAuth 2.0 client ID (Desktop application)
    4. Download client_secret.json
    5. pip install google-auth-oauthlib google-api-python-client
"""

import argparse
import json
import sys
from pathlib import Path

CREDENTIALS_PATH = Path("/opt/bumba-harness/data/.gmail-credentials.json")

SCOPES_FULL = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
]
SCOPES_READONLY = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def setup_account(client_secrets_path: str, account: str) -> bool:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib not installed")
        print("Run: pip install google-auth-oauthlib google-api-python-client")
        return False

    if not Path(client_secrets_path).exists():
        print(f"ERROR: Client secrets file not found: {client_secrets_path}")
        return False

    scopes = SCOPES_FULL if account == "agent" else SCOPES_READONLY
    print(f"\nSetting up '{account}' account with scopes:")
    for s in scopes:
        print(f"  - {s}")
    print("\nA browser window will open for authorization...")

    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, scopes)
    creds = flow.run_local_server(port=0)

    # Load existing or create new
    creds_data = {}
    if CREDENTIALS_PATH.exists():
        try:
            creds_data = json.loads(CREDENTIALS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    creds_data[account] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
    }

    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(creds_data, indent=2))
    CREDENTIALS_PATH.chmod(0o600)

    print(f"\nCredentials saved for '{account}' at {CREDENTIALS_PATH}")
    print(f"Accounts configured: {', '.join(creds_data.keys())}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Gmail OAuth setup for Bumba agent")
    parser.add_argument(
        "--account",
        choices=["agent", "personal", "workspace"],
        required=True,
        help="Account to configure",
    )
    parser.add_argument(
        "--credentials",
        required=True,
        help="Path to client_secret.json from Google Cloud Console",
    )
    args = parser.parse_args()

    print("=" * 50)
    print(f"  Gmail OAuth Setup — {args.account} account")
    print("=" * 50)

    if setup_account(args.credentials, args.account):
        print("\nDone. The agent can now access this account.")
        if args.account == "agent":
            print("\nNext: Set up 'personal' or 'workspace' accounts if needed:")
            print(f"  python {sys.argv[0]} --account personal --credentials {args.credentials}")
    else:
        print("\nSetup failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
