"""Sprint 02.11 — Cal.com multi-account interface tests.

Exercises the refactored ``calcom_interface`` so that all
``calcom_api_key_<label>=`` entries in ``.secrets`` are routed correctly,
plus the legacy single-key backward-compat shim and the webhook
account-inference logic.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services import calcom_interface as ci
from bridge import calcom_webhook as webhook

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer


@pytest.fixture(autouse=True)
def _reset_legacy_warned():
    """Reset the module-level legacy-warning flag so each test starts fresh."""
    ci._legacy_warned = False
    yield
    ci._legacy_warned = False


def _write_secrets(tmp_path: Path, contents: str) -> Path:
    secrets = tmp_path / ".secrets"
    secrets.write_text(contents)
    return secrets


# ---------------------------------------------------------------------------
# Test 1 — multi-account parsing
# ---------------------------------------------------------------------------

def test_get_api_keys_parses_multi_account(tmp_path, monkeypatch):
    """``_get_api_keys`` returns every ``calcom_api_key_<label>=`` entry."""
    secrets = _write_secrets(
        tmp_path,
        "discord_token=abc\n"
        "calcom_api_key_personal=k1\n"
        "calcom_api_key_business=k2\n"
        "notion_api_token=ntn_xyz\n",
    )
    monkeypatch.setattr(ci, "SECRETS_PATH", secrets)

    keys = ci._get_api_keys()
    assert keys == {"personal": "k1", "business": "k2"}


# ---------------------------------------------------------------------------
# Test 2 — _api_get routes to the named account
# ---------------------------------------------------------------------------

def test_api_get_routes_to_named_account(tmp_path, monkeypatch):
    """``_api_get(..., account=<label>)`` uses that label's API key in the URL."""
    secrets = _write_secrets(
        tmp_path,
        "calcom_api_key_personal=k1\n"
        "calcom_api_key_business=k2\n",
    )
    monkeypatch.setattr(ci, "SECRETS_PATH", secrets)

    captured: dict[str, str] = {}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"bookings": []}'

    def _fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        return _FakeResp()

    with patch.object(ci, "urlopen", _fake_urlopen):
        ci._api_get("bookings", account="business")
    assert "apiKey=k2" in captured["url"]
    assert "apiKey=k1" not in captured["url"]

    captured.clear()
    with patch.object(ci, "urlopen", _fake_urlopen):
        ci._api_get("bookings", account="personal")
    assert "apiKey=k1" in captured["url"]
    assert "apiKey=k2" not in captured["url"]


# ---------------------------------------------------------------------------
# Test 3 — legacy single-key backward compatibility + DeprecationWarning
# ---------------------------------------------------------------------------

def test_legacy_single_key_returns_default_with_warning(tmp_path, monkeypatch):
    """A bare ``calcom_api_key=`` falls back to ``{'default': value}`` and warns."""
    secrets = _write_secrets(
        tmp_path,
        "discord_token=abc\n"
        "calcom_api_key=legacy-key-xyz\n",
    )
    monkeypatch.setattr(ci, "SECRETS_PATH", secrets)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        keys = ci._get_api_keys()

    assert keys == {"default": "legacy-key-xyz"}
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == 1
    assert "calcom_api_key_<label>" in str(deprecations[0].message)


def test_legacy_warning_is_emitted_only_once(tmp_path, monkeypatch):
    """The deprecation warning is one-shot per process, not per call."""
    secrets = _write_secrets(
        tmp_path,
        "calcom_api_key=legacy-key-xyz\n",
    )
    monkeypatch.setattr(ci, "SECRETS_PATH", secrets)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ci._get_api_keys()
        ci._get_api_keys()
        ci._get_api_keys()

    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == 1


# ---------------------------------------------------------------------------
# Test 4 — list_all_accounts() returns sorted labels
# ---------------------------------------------------------------------------

def test_list_all_accounts_returns_sorted_labels(tmp_path, monkeypatch):
    """``list_all_accounts`` is alphabetically sorted for deterministic output."""
    secrets = _write_secrets(
        tmp_path,
        "calcom_api_key_zeta=zk\n"
        "calcom_api_key_business=ak\n"
        "calcom_api_key_personal=pk\n",
    )
    monkeypatch.setattr(ci, "SECRETS_PATH", secrets)

    assert ci.list_all_accounts() == ["business", "personal", "zeta"]


def test_list_all_accounts_empty_when_secrets_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "SECRETS_PATH", tmp_path / "nonexistent")
    assert ci.list_all_accounts() == []


# ---------------------------------------------------------------------------
# Test 5 — explicit account that doesn't exist raises (no silent fallback)
# ---------------------------------------------------------------------------

def test_api_get_unknown_account_raises_keyerror(tmp_path, monkeypatch):
    """``_api_get(account='business')`` when only 'personal' exists must raise."""
    secrets = _write_secrets(
        tmp_path,
        "calcom_api_key_personal=k1\n",
    )
    monkeypatch.setattr(ci, "SECRETS_PATH", secrets)

    with pytest.raises(KeyError) as exc_info:
        ci._api_get("bookings", account="business")

    assert "business" in str(exc_info.value)
    assert "personal" in str(exc_info.value)


def test_resolve_account_default_warns_with_multiple_accounts(
    tmp_path, monkeypatch, caplog,
):
    """When ``account=None`` and multiple accounts exist, log a WARNING."""
    secrets = _write_secrets(
        tmp_path,
        "calcom_api_key_personal=k1\n"
        "calcom_api_key_business=k2\n",
    )
    monkeypatch.setattr(ci, "SECRETS_PATH", secrets)

    keys = ci._get_api_keys()
    with caplog.at_level("WARNING", logger="bridge.services.calcom_interface"):
        chosen = ci._resolve_account(None, keys)

    assert chosen == "business"  # alphabetically first
    assert any(
        "account unspecified" in rec.message for rec in caplog.records
    ), "expected a 'account unspecified' WARNING"


# ---------------------------------------------------------------------------
# Test 6 — webhook account inference
# ---------------------------------------------------------------------------

def test_webhook_infers_account_from_organizer_email_business():
    """Organizer email ``@business.ai`` → ``account = 'business'``."""
    payload = {"uid": "b-1"}
    booking = {
        "uid": "b-1",
        "organizer_email": "hello@business.ai",
        "attendee_email": "guest@example.com",
    }
    assert webhook._infer_account(payload, booking) == "business"


def test_webhook_infers_account_from_organizer_email_personal():
    """Organizer email ``@example-operator.com`` → ``account = 'personal'``."""
    payload = {"uid": "b-2"}
    booking = {
        "uid": "b-2",
        "organizer_email": "hi@example-operator.com",
        "attendee_email": "client@example.com",
    }
    assert webhook._infer_account(payload, booking) == "personal"


def test_webhook_account_inference_unknown_falls_back_to_default(caplog):
    """Unmapped organizer domain → ``'default'`` with a WARNING."""
    payload = {"uid": "b-3"}
    booking = {
        "uid": "b-3",
        "organizer_email": "someone@unknown-domain.example",
    }
    with caplog.at_level("WARNING", logger="bridge.calcom_webhook"):
        result = webhook._infer_account(payload, booking)

    assert result == "default"
    assert any(
        "account_inference_fallback" in rec.message for rec in caplog.records
    )


def test_webhook_account_inference_explicit_field_wins():
    """A future ``payload.account`` field overrides email-domain inference."""
    payload = {"uid": "b-4", "account": "Personal"}
    booking = {
        "uid": "b-4",
        "organizer_email": "hi@business.ai",  # would otherwise map to business
    }
    # Explicit field is normalised to lowercase but otherwise honoured.
    assert webhook._infer_account(payload, booking) == "personal"


def test_webhook_publishes_account_in_event_payload(monkeypatch):
    """The full webhook handle path includes ``account`` in the event payload.

    Updated by audit-2026-05-16.B.05 (#2054, HI-6): the handler now requires
    a signed request, so the test stubs ``_read_secret`` to return a known
    secret and supplies the matching HMAC-SHA256 signature header.
    """
    import asyncio
    import hashlib
    import hmac
    import json
    from aiohttp.test_utils import make_mocked_request

    captured: list[dict] = []

    class _FakeBus:
        def publish(self, event_type, *, payload, source, correlation_id=None):
            captured.append({
                "event_type": event_type,
                "payload": payload,
                "source": source,
            })

    handler = webhook.CalcomWebhookHandler(event_bus=_FakeBus())
    handler.clear_dedup_cache()

    body = json.dumps({
        "triggerEvent": "BOOKING_CREATED",
        "payload": {
            "uid": "b-5",
            "title": "Sync",
            "startTime": "2026-04-25T15:00:00Z",
            "endTime": "2026-04-25T15:30:00Z",
            "attendees": [{"name": "Guest", "email": "guest@example.com"}],
            "organizer": {"name": "the operator", "email": "operator@business.ai"},
        },
    }).encode()

    # B.05 — supply a known secret + matching HMAC-SHA256 signature so the
    # request passes the fail-closed verification path.
    test_secret = "b05-test-secret"
    monkeypatch.setattr(webhook, "_read_secret", lambda: test_secret)
    expected_sig = hmac.new(
        test_secret.encode(), body, hashlib.sha256
    ).hexdigest()

    request = make_mocked_request(
        "POST",
        "/api/webhooks/calcom",
        headers={"X-Cal-Signature-256": expected_sig},
    )

    async def _fake_read():
        return body

    request._payload = None
    request.read = _fake_read  # type: ignore[method-assign]

    asyncio.new_event_loop().run_until_complete(handler.handle(request))

    assert captured, "expected an event publish"
    event = captured[0]
    assert event["event_type"] == "calcom.booking.created"
    assert event["payload"]["account"] == "business"
    assert event["payload"]["raw_uid"] == "b-5"
