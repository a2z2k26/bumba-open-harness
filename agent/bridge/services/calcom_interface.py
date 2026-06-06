"""Cal.com REST API interface for booking management.

Multi-account contract (Sprint 02.11):
    Bumba talks to multiple Cal.com accounts (e.g. ``personal`` and
    ``business``). Account API keys live in ``/opt/bumba-harness/data/.secrets``
    under entries of the form ``calcom_api_key_<label>=<key>``::

        calcom_api_key_personal=cal_live_xxxx
        calcom_api_key_business=cal_live_yyyy

    Public functions (``get_upcoming_bookings``, ``get_booking_detail``,
    ``get_availability``, ``validate_api_key``) accept an optional
    ``account: str | None`` argument that selects which key to use. When
    ``account`` is ``None`` the first label in alphabetical order is picked
    and a WARNING is logged — callers should be explicit.

    ``list_all_accounts()`` returns the sorted list of configured labels.

Backward compatibility:
    A legacy single-key entry ``calcom_api_key=<key>`` (no suffix) is
    accepted and surfaced as account ``"default"`` with a one-shot
    DeprecationWarning. Operators should rename it to
    ``calcom_api_key_personal=`` (or whichever label fits).
"""

from __future__ import annotations

import json
import logging
import re
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict
from urllib.request import Request, urlopen
from urllib.error import URLError

log = logging.getLogger(__name__)

CALCOM_BASE = "https://api.cal.com/v1"
SECRETS_PATH = Path("/opt/bumba-harness/data/.secrets")

# Match ``calcom_api_key_<label>=<value>`` where label is lowercase letters
# and underscores. The legacy bare ``calcom_api_key=<value>`` is matched
# separately (see _get_api_keys).
_KEY_RE = re.compile(r"^calcom_api_key_([a-z_]+)=(.+)$")
_LEGACY_KEY_RE = re.compile(r"^calcom_api_key=(.+)$")

# Emit the legacy DeprecationWarning at most once per process to keep the
# bridge logs quiet on hot paths. The flag is module-level so it persists
# across invocations.
_legacy_warned: bool = False


class Booking(TypedDict, total=False):
    id: int
    title: str
    start: str
    end: str
    attendee_name: str
    attendee_email: str
    status: str
    meeting_url: str


def _get_api_keys() -> dict[str, str]:
    """Read all Cal.com API keys from ``.secrets`` keyed by account label.

    Returns:
        Mapping of ``label -> api_key``. Empty dict if the file is missing
        or has no Cal.com entries.

    Backward compatibility:
        If only the legacy ``calcom_api_key=<value>`` entry exists (no
        ``calcom_api_key_<label>=`` entries), returns ``{"default": value}``
        and emits a DeprecationWarning nudging the operator to rename.
    """
    global _legacy_warned

    if not SECRETS_PATH.exists():
        return {}

    keys: dict[str, str] = {}
    legacy_value: str | None = None

    for raw in SECRETS_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = _KEY_RE.match(line)
        if m:
            label, value = m.group(1), m.group(2).strip()
            if value:
                keys[label] = value
            continue

        m_legacy = _LEGACY_KEY_RE.match(line)
        if m_legacy:
            legacy_value = m_legacy.group(1).strip() or None

    if keys:
        return keys

    if legacy_value:
        if not _legacy_warned:
            warnings.warn(
                "calcom_api_key=<value> in .secrets is deprecated; rename to "
                "calcom_api_key_<label>=<value> (e.g. calcom_api_key_personal=)",
                DeprecationWarning,
                stacklevel=2,
            )
            _legacy_warned = True
        return {"default": legacy_value}

    return {}


def list_all_accounts() -> list[str]:
    """Return sorted account labels configured in ``.secrets``."""
    return sorted(_get_api_keys().keys())


def _resolve_account(account: str | None, keys: dict[str, str]) -> str | None:
    """Pick the account label to use for a request.

    Returns ``None`` when no keys are configured. When ``account`` is
    explicitly named but missing, raises ``KeyError`` so callers fail
    loudly instead of silently falling back to a different account.
    """
    if not keys:
        return None

    if account is not None:
        if account not in keys:
            raise KeyError(
                f"Cal.com account {account!r} not configured in .secrets "
                f"(known accounts: {sorted(keys.keys())})"
            )
        return account

    # No account specified — pick the alphabetically-first one and warn.
    chosen = sorted(keys.keys())[0]
    if len(keys) > 1:
        log.warning(
            "calcom_interface: account unspecified, defaulting to %r "
            "(configured: %s) — call with explicit account= to silence this",
            chosen, sorted(keys.keys()),
        )
    return chosen


def _api_get(
    endpoint: str,
    params: dict | None = None,
    *,
    account: str | None = None,
) -> dict | None:
    """Make a GET request to Cal.com API for the resolved account."""
    keys = _get_api_keys()
    label = _resolve_account(account, keys)
    if label is None:
        log.error("Cal.com API key not found in .secrets")
        return None

    api_key = keys[label]

    url = f"{CALCOM_BASE}/{endpoint}?apiKey={api_key}"
    if params:
        from urllib.parse import urlencode
        url += "&" + urlencode(params)

    try:
        req = Request(url, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except URLError as e:
        log.error("Cal.com API error (account=%s): %s", label, e)
        return None
    except json.JSONDecodeError as e:
        log.error("Cal.com API JSON error (account=%s): %s", label, e)
        return None


def _parse_booking(raw: dict) -> Booking:
    """Parse a Cal.com booking response into our typed dict."""
    attendees = raw.get("attendees", [{}])
    first_attendee = attendees[0] if attendees else {}

    return Booking(
        id=raw.get("id", 0),
        title=raw.get("title", "(no title)"),
        start=raw.get("startTime", ""),
        end=raw.get("endTime", ""),
        attendee_name=first_attendee.get("name", ""),
        attendee_email=first_attendee.get("email", ""),
        status=raw.get("status", ""),
        meeting_url=raw.get("metadata", {}).get("videoCallUrl", ""),
    )


def get_upcoming_bookings(
    days: int = 7,
    *,
    account: str | None = None,
) -> list[Booking]:
    """Get upcoming bookings within the next N days for *account*."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    data = _api_get(
        "bookings",
        {
            "dateFrom": now.strftime("%Y-%m-%d"),
            "dateTo": end.strftime("%Y-%m-%d"),
        },
        account=account,
    )

    if not data or "bookings" not in data:
        return []

    bookings = [_parse_booking(b) for b in data["bookings"]]
    # Filter to upcoming only (API may return past bookings too)
    return [b for b in bookings if b.get("start", "") >= now.isoformat()]


def get_booking_detail(
    booking_id: int,
    *,
    account: str | None = None,
) -> Booking | None:
    """Get details for a specific booking from *account*."""
    data = _api_get(f"bookings/{booking_id}", account=account)
    if not data or "booking" not in data:
        return None
    return _parse_booking(data["booking"])


def validate_api_key(*, account: str | None = None) -> bool:
    """Validate the Cal.com API key for *account* via a test request."""
    keys = _get_api_keys()
    if not keys:
        log.warning("Cal.com API key not configured in .secrets")
        return False

    try:
        label = _resolve_account(account, keys)
    except KeyError as exc:
        log.warning("Cal.com validate_api_key: %s", exc)
        return False

    if label is None:
        return False

    result = _api_get("bookings", {"limit": "1"}, account=label)
    if result is None:
        log.warning("Cal.com API key validation failed (account=%s)", label)
        return False

    log.info("Cal.com API key validated successfully (account=%s)", label)
    return True


def get_availability(
    date_from: str,
    date_to: str,
    *,
    account: str | None = None,
) -> list[dict]:
    """Get availability slots for a date range for *account*.

    Args:
        date_from: YYYY-MM-DD
        date_to: YYYY-MM-DD
        account: Optional Cal.com account label.

    Returns:
        List of availability slots
    """
    data = _api_get(
        "availability",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
        },
        account=account,
    )

    if not data:
        return []

    return data.get("availability", [])
