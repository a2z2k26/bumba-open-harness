"""Cal.com webhook handler (Z2-S4.1).

Receives inbound webhook POST requests from Cal.com, verifies optional
HMAC-SHA256 signatures, deduplicates by eventId, and publishes typed
events to the EventBus.

Supported trigger events:
  BOOKING_CREATED   → calcom.booking.created
  BOOKING_CANCELLED → calcom.booking.cancelled
  BOOKING_RESCHEDULED → calcom.booking.rescheduled
  <anything else>   → calcom.booking.unknown  (logged + published for observability)

Deduplication:
  Cal.com may deliver the same webhook more than once. We deduplicate by
  the ``payload.uid`` field (Cal.com booking UID) within the same event
  type. The seen-set is per-process; a restart resets it — acceptable for
  this use case since EventBus dedup by correlation_id handles cross-restart
  cases in downstream consumers.

Signature verification (REQUIRED post audit-2026-05-16.B.05 / #2054 / HI-6):
  Every request must carry a valid ``X-Cal-Signature-256`` header
  (HMAC-SHA256 hex of the raw body keyed on ``calcom_webhook_secret``
  from ``.secrets``). Missing secret, missing header, and bad signature
  all return 401 and are NOT published. The route-level gate in
  ``bridge/api/routes_webhooks.py`` additionally returns 503 when
  ``calcom_webhook_enabled`` is False, and ``BridgeConfig.validate()``
  refuses to boot with the flag on and the secret empty.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)

# Mapping from Cal.com triggerEvent → our event bus event type
_TRIGGER_MAP: dict[str, str] = {
    "BOOKING_CREATED": "calcom.booking.created",
    "BOOKING_CANCELLED": "calcom.booking.cancelled",
    "BOOKING_RESCHEDULED": "calcom.booking.rescheduled",
}

_SECRETS_PATH = Path("/opt/bumba-harness/data/.secrets")

# Warn once if the webhook secret is absent
_warned_no_secret = False

# Per-process deduplication: (event_type, booking_uid) → timestamp
_seen: dict[tuple[str, str], str] = {}


def _read_secret() -> str | None:
    """Read calcom_webhook_secret from .secrets."""
    if not _SECRETS_PATH.exists():
        return None
    for line in _SECRETS_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("calcom_webhook_secret="):
            return line.split("=", 1)[1].strip()
    return None


def _verify_signature(body: bytes, header_sig: str, secret: str) -> bool:
    """Return True if HMAC-SHA256(body, secret) matches header_sig."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # Cal.com sends the signature as plain hex (no "sha256=" prefix)
    return hmac.compare_digest(expected, header_sig.strip())


def _extract_booking(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Cal.com webhook payload into our canonical booking dict."""
    attendees = payload.get("attendees", [{}])
    first = attendees[0] if attendees else {}
    organizer = payload.get("organizer", {})

    return {
        "uid": payload.get("uid", ""),
        "title": payload.get("title", "(no title)"),
        "start_time": payload.get("startTime", ""),
        "end_time": payload.get("endTime", ""),
        "attendee_name": first.get("name", ""),
        "attendee_email": first.get("email", ""),
        "organizer_name": organizer.get("name", ""),
        "organizer_email": organizer.get("email", ""),
        "meeting_url": payload.get("metadata", {}).get("videoCallUrl", ""),
        "location": payload.get("location", ""),
        "description": (payload.get("description") or "")[:500],
        "status": payload.get("status", ""),
    }


# Sprint 02.11: Cal.com webhook payloads do NOT include a stable account/team
# field across plans — both ``payload.team`` and ``payload.organization`` are
# absent on personal-tier accounts. The most reliable signal is the organizer
# email domain (organizer = the Cal.com account holder, NOT the attendee).
#
# Organizer email is preferred over attendee email because the attendee is
# whoever booked the slot (any third party), whereas the organizer is always
# the Cal.com account whose API key we need.
_ACCOUNT_DOMAIN_MAP: dict[str, str] = {
    "example-operator.com": "personal",
    "business.ai": "business",
}


def _infer_account(payload: dict[str, Any], booking: dict[str, Any]) -> str:
    """Infer the Cal.com account label for a webhook event.

    Priority:
        1. Explicit ``payload.account`` / ``payload.team`` if Cal.com ever
           starts sending one (forward-compat — no harm if absent).
        2. Organizer email domain match in ``_ACCOUNT_DOMAIN_MAP``.
        3. Fallback: ``"default"`` with a WARNING log.

    Returns:
        The inferred account label (lowercase, matches the
        ``calcom_api_key_<label>`` suffix in .secrets).
    """
    # 1. Explicit field (future-proofing).
    for key in ("account", "team", "organization"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        if isinstance(value, dict):
            slug = value.get("slug") or value.get("name")
            if isinstance(slug, str) and slug.strip():
                return slug.strip().lower()

    # 2. Organizer email domain.
    organizer_email = (booking.get("organizer_email") or "").lower()
    if "@" in organizer_email:
        domain = organizer_email.rsplit("@", 1)[1]
        mapped = _ACCOUNT_DOMAIN_MAP.get(domain)
        if mapped:
            return mapped

    # 3. Fallback.
    log.warning(
        "calcom_webhook.account_inference_fallback organizer_email=%r — "
        "using 'default'. Add the domain to _ACCOUNT_DOMAIN_MAP if it's "
        "a real Bumba Cal.com account.",
        organizer_email,
    )
    return "default"


class CalcomWebhookHandler:
    """Processes inbound Cal.com webhook POST bodies.

    Instantiated once and held on the BridgeApp / APIServer.  Thread-safe
    for the ``handle`` method — dedup set is written under no lock because
    aiohttp runs on a single event-loop thread.
    """

    def __init__(self, event_bus: Any | None = None) -> None:
        """
        Args:
            event_bus: An EventBus instance.  If None, events are logged
                but not published (useful in tests).
        """
        self._event_bus = event_bus

    # ------------------------------------------------------------------
    # Core handler
    # ------------------------------------------------------------------

    async def handle(self, request: web.Request) -> web.Response:
        """aiohttp request handler for POST /api/webhooks/calcom."""
        global _warned_no_secret

        body = await request.read()

        # ----- Signature verification (REQUIRED, audit-2026-05-16.B.05 #2054) -----
        # Pre-B.05 behaviour: missing secret -> accept-unsigned with one-time
        # warning (fail-open). Post-B.05: missing secret -> 401 reject. The
        # boot validator in BridgeConfig.validate() refuses to start with
        # calcom_webhook_enabled=true and an empty secret, so this branch
        # only fires when the operator hasn't configured the secret at all
        # AND the route still reached us (e.g. the config gate in
        # routes_webhooks.py was bypassed by a test fixture).
        secret = _read_secret()
        if not secret:
            if not _warned_no_secret:
                log.warning(
                    "calcom_webhook.no_secret configured — rejecting unsigned "
                    "webhook (set calcom_webhook_secret in .secrets to enable "
                    "verified delivery). Sprint audit-2026-05-16.B.05 "
                    "(#2054, HI-6)."
                )
                _warned_no_secret = True
            return web.Response(status=401, text="webhook secret not configured")

        sig_header = request.headers.get("X-Cal-Signature-256", "")
        if not sig_header:
            log.warning("calcom_webhook.no_signature_header — rejecting (secret configured, signature required)")
            return web.Response(status=401, text="Missing signature")
        if not _verify_signature(body, sig_header, secret):
            log.warning("calcom_webhook.bad_signature — rejecting request")
            return web.Response(status=401, text="Invalid signature")

        # ----- Parse body -----
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("calcom_webhook.invalid_json: %s", exc)
            return web.Response(status=400, text="Invalid JSON")

        trigger = data.get("triggerEvent", "")
        payload = data.get("payload", data)  # some cal.com versions use top-level

        event_type = _TRIGGER_MAP.get(trigger, "calcom.booking.unknown")
        if event_type == "calcom.booking.unknown":
            log.info("calcom_webhook.unknown_trigger triggerEvent=%r", trigger)

        # ----- Deduplication -----
        booking = _extract_booking(payload)
        uid = booking.get("uid", "")
        dedup_key = (event_type, uid)
        if uid and dedup_key in _seen:
            log.debug(
                "calcom_webhook.duplicate_skipped event_type=%s uid=%s",
                event_type, uid,
            )
            return web.Response(status=200, text="duplicate")

        if uid:
            _seen[dedup_key] = datetime.now(timezone.utc).isoformat()
            # Limit memory growth — prune oldest 50 when > 500 entries
            if len(_seen) > 500:
                oldest_keys = list(_seen.keys())[:50]
                for k in oldest_keys:
                    _seen.pop(k, None)

        # ----- Account inference (Sprint 02.11) -----
        # Tag the event with the Cal.com account so downstream consumers
        # (meeting_prebrief, etc.) hit the correct API key.
        account = _infer_account(payload, booking)

        # ----- Publish to EventBus -----
        event_payload = {
            "trigger": trigger,
            "account": account,
            "booking": booking,
            "raw_uid": uid,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }

        if self._event_bus is not None:
            try:
                self._event_bus.publish(
                    event_type,
                    payload=event_payload,
                    source="calcom_webhook",
                    correlation_id=uid or None,
                )
                log.info(
                    "calcom_webhook.published event_type=%s account=%s uid=%s title=%r",
                    event_type, account, uid, booking.get("title", ""),
                )
            except Exception as exc:  # noqa: BLE001
                log.error("calcom_webhook.publish_failed: %s", exc)
        else:
            log.debug(
                "calcom_webhook.no_event_bus — event_type=%s account=%s uid=%s",
                event_type, account, uid,
            )

        return web.Response(status=200, text="ok")

    # ------------------------------------------------------------------
    # Test helper
    # ------------------------------------------------------------------

    @staticmethod
    def clear_dedup_cache() -> None:
        """Clear the per-process dedup set (test helper)."""
        _seen.clear()
