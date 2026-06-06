"""Gmail API authentication for email digest service.

Supports multiple accounts:
- Agent's own Gmail (full access: read + send)
- Operator's personal/workspace accounts (read-only via delegation)

Credentials stored in data/.gmail-credentials.json (bumba-agent owned, 600 perms).
Refresh token stored in .secrets alongside Claude OAuth token.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Scopes per account type
SCOPES_FULL = ["https://www.googleapis.com/auth/gmail.modify"]
SCOPES_READONLY = ["https://www.googleapis.com/auth/gmail.readonly"]
SCOPES_CALENDAR = ["https://www.googleapis.com/auth/calendar.readonly"]
ALL_SCOPES = SCOPES_FULL + SCOPES_READONLY + SCOPES_CALENDAR

CREDENTIALS_PATH = Path("/opt/bumba-harness/data/.gmail-credentials.json")
SECRETS_PATH = Path("/opt/bumba-harness/data/.secrets")


def _load_secrets() -> dict[str, str]:
    """Load key=value pairs from .secrets file."""
    secrets = {}
    if SECRETS_PATH.exists():
        for line in SECRETS_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                secrets[key.strip()] = value.strip()
    return secrets


def get_gmail_credentials(account: str = "agent"):
    """Get Google API credentials for the specified account.

    Args:
        account: 'agent' (own account, full access),
                 'personal' (operator personal, read-only),
                 'workspace' (operator workspace, read-only)

    Returns:
        google.oauth2.credentials.Credentials or None
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        log.error("google-auth not installed: pip install google-auth google-auth-oauthlib")
        return None

    if not CREDENTIALS_PATH.exists():
        log.error("Gmail credentials file not found: %s", CREDENTIALS_PATH)
        return None

    try:
        creds_data = json.loads(CREDENTIALS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to read credentials: %s", e)
        return None

    account_creds = creds_data.get(account)
    if not account_creds:
        log.error("No credentials for account '%s'", account)
        return None

    scopes = SCOPES_FULL if account == "agent" else SCOPES_READONLY

    creds = Credentials(
        token=account_creds.get("token"),
        refresh_token=account_creds.get("refresh_token"),
        token_uri=account_creds.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=account_creds.get("client_id"),
        client_secret=account_creds.get("client_secret"),
        scopes=scopes,
    )

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Update stored token
            account_creds["token"] = creds.token
            creds_data[account] = account_creds
            CREDENTIALS_PATH.write_text(json.dumps(creds_data, indent=2))
            log.info("Refreshed Gmail token for account '%s'", account)
        except Exception as e:
            log.error("Failed to refresh Gmail token for '%s': %s", account, e)
            return None

    return creds


def initial_auth_flow(client_secrets_path: str, account: str = "agent") -> bool:
    """Run the initial OAuth2 flow for a new account (interactive).

    This should be run once per account from a terminal with browser access.
    Not for use in the LaunchDaemon context.

    Args:
        client_secrets_path: Path to client_secrets.json from Google Cloud Console
        account: Account key to store credentials under

    Returns:
        True if auth succeeded
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        log.error("google-auth-oauthlib not installed")
        return False

    scopes = SCOPES_FULL + SCOPES_CALENDAR if account == "agent" else SCOPES_READONLY + SCOPES_CALENDAR

    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, scopes)
    creds = flow.run_local_server(port=0)

    # Load existing or create new credentials file
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

    CREDENTIALS_PATH.write_text(json.dumps(creds_data, indent=2))
    CREDENTIALS_PATH.chmod(0o600)
    log.info("Gmail credentials saved for account '%s'", account)
    return True
