"""Gmail API interface functions for reading and sending email.

Uses the Google Workspace CLI (gws) for all Gmail operations.
Falls back gracefully if gws is not available.
"""

from __future__ import annotations

import base64
import json
import logging
import shutil
import subprocess
from email.mime.text import MIMEText
from typing import TypedDict

log = logging.getLogger(__name__)

GWS_BINARY = "/opt/homebrew/bin/gws"
GWS_TIMEOUT = 30


class EmailMessage(TypedDict, total=False):
    id: str
    from_addr: str
    to: str
    subject: str
    snippet: str
    date: str
    labels: list[str]
    body: str


def _find_gws() -> str:
    """Find the gws binary."""
    if shutil.which("gws"):
        return shutil.which("gws")
    from pathlib import Path
    if Path(GWS_BINARY).is_file():
        return GWS_BINARY
    raise FileNotFoundError("gws CLI not found — install with: npm install -g @googleworkspace/cli")


def _run_gws(args: list[str], input_data: str | None = None) -> dict | list | None:
    """Run a gws command and return parsed JSON output."""
    try:
        binary = _find_gws()
    except FileNotFoundError as e:
        log.error(str(e))
        return None

    cmd = [binary] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=GWS_TIMEOUT,
            input=input_data,
            cwd="/tmp",  # Node.js crashes if cwd is inaccessible (LaunchDaemon context)
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()[:300] if result.stderr else ""
            log.error("gws command failed: %s — %s", " ".join(args[:3]), stderr)
            return None

        stdout = result.stdout.strip()
        if not stdout:
            return None

        return json.loads(stdout)

    except subprocess.TimeoutExpired:
        log.error("gws command timed out: %s", " ".join(args[:3]))
        return None
    except json.JSONDecodeError:
        log.error("gws returned invalid JSON: %s", result.stdout[:200] if result.stdout else "empty")
        return None
    except Exception as e:
        log.error("gws command error: %s", e)
        return None


def get_unread_count(account: str = "agent") -> int:
    """Get count of unread messages in inbox."""
    data = _run_gws([
        "gmail", "users", "labels", "get",
        "--params", json.dumps({"userId": "me", "id": "INBOX"}),
    ])
    if not data or not isinstance(data, dict):
        return 0
    return data.get("messagesUnread", 0)


def get_unread_messages(
    account: str = "agent",
    limit: int = 10,
    label: str = "INBOX",
) -> list[EmailMessage]:
    """Get unread messages from specified label."""
    data = _run_gws([
        "gmail", "users", "messages", "list",
        "--params", json.dumps({
            "userId": "me",
            "labelIds": [label],
            "q": "is:unread",
            "maxResults": limit,
        }),
    ])
    if not data or not isinstance(data, dict):
        return []

    messages = data.get("messages", [])
    output: list[EmailMessage] = []

    for msg_ref in messages:
        msg_id = msg_ref.get("id", "")
        if not msg_id:
            continue

        detail = _run_gws([
            "gmail", "users", "messages", "get",
            "--params", json.dumps({
                "userId": "me",
                "id": msg_id,
                "format": "metadata",
                "metadataHeaders": ["From", "Subject", "Date"],
            }),
        ])
        if not detail or not isinstance(detail, dict):
            continue

        headers = {
            h["name"]: h["value"]
            for h in detail.get("payload", {}).get("headers", [])
        }
        output.append(EmailMessage(
            id=detail.get("id", msg_id),
            from_addr=headers.get("From", ""),
            subject=headers.get("Subject", "(no subject)"),
            snippet=detail.get("snippet", ""),
            date=headers.get("Date", ""),
            labels=detail.get("labelIds", []),
        ))

    return output


def get_message_detail(account: str, msg_id: str) -> EmailMessage | None:
    """Get full message detail including body."""
    data = _run_gws([
        "gmail", "users", "messages", "get",
        "--params", json.dumps({
            "userId": "me",
            "id": msg_id,
            "format": "full",
        }),
    ])
    if not data or not isinstance(data, dict):
        return None

    headers = {
        h["name"]: h["value"]
        for h in data.get("payload", {}).get("headers", [])
    }

    # Extract body
    body = ""
    payload = data.get("payload", {})
    if payload.get("body", {}).get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    elif payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break

    return EmailMessage(
        id=data.get("id", msg_id),
        from_addr=headers.get("From", ""),
        to=headers.get("To", ""),
        subject=headers.get("Subject", "(no subject)"),
        snippet=data.get("snippet", ""),
        date=headers.get("Date", ""),
        labels=data.get("labelIds", []),
        body=body,
    )


def send_email(
    to: str,
    subject: str,
    body: str,
    from_account: str = "agent",
) -> bool:
    """Send an email using gws CLI."""
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    data = _run_gws([
        "gmail", "users", "messages", "send",
        "--params", json.dumps({"userId": "me"}),
        "--json", json.dumps({"raw": raw}),
    ])

    if data and isinstance(data, dict) and data.get("id"):
        log.info("Email sent to %s: %s", to, subject)
        return True

    log.error("Failed to send email to %s", to)
    return False


def mark_read(account: str, msg_id: str) -> bool:
    """Mark a message as read."""
    data = _run_gws([
        "gmail", "users", "messages", "modify",
        "--params", json.dumps({"userId": "me", "id": msg_id}),
        "--json", json.dumps({"removeLabelIds": ["UNREAD"]}),
    ])
    return data is not None
