"""Sprint audit-2026-05-16.B.05 (#2054, HI-6) — Cal.com webhook fail-closed tests.

Covers:
  - BridgeConfig.validate() raises ConfigError when calcom_webhook_enabled=True
    and calcom_webhook_secret is empty (fail-closed boot).
  - The disabled+no-secret and enabled+secret combinations validate clean.
  - CalcomWebhookHandler.handle returns 401 when the secret is absent,
    instead of accepting unsigned webhooks (pre-B.05 behaviour was 200).
  - CalcomWebhookHandler.handle returns 401 when the secret is present but
    no X-Cal-Signature-256 header is supplied (regression coverage).

The test_calcom_multi_account.py module covers a different surface
(account-inference + multi-key parsing).
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest

from bridge import calcom_webhook as webhook
from bridge.calcom_webhook import CalcomWebhookHandler
from bridge.config import BridgeConfig, ConfigError


# ---------------------------------------------------------------------------
# Config-level fail-closed validator tests
# ---------------------------------------------------------------------------


def _minimal_valid_config(**overrides: Any) -> BridgeConfig:
    """Build a BridgeConfig with the bare minimum needed for validate() to
    only fail on the invariant under test.

    We bypass _validate() (single-field range checks) and call
    .validate() directly — the cross-field invariants under test live
    on the dataclass method per the comment at config.py:937-941
    ('several pre-existing tests invoke _validate(config) directly').
    """
    base = BridgeConfig()
    return dataclasses.replace(base, **overrides)


def test_config_enabled_without_secret_raises_config_error():
    """B.05 invariant — calcom_webhook_enabled=True + empty secret fails boot."""
    config = _minimal_valid_config(
        calcom_webhook_enabled=True,
        calcom_webhook_secret="",
    )
    with pytest.raises(ConfigError) as excinfo:
        config.validate()
    msg = str(excinfo.value)
    assert "calcom_webhook_secret" in msg
    assert "calcom_webhook_enabled" in msg


def test_config_enabled_with_whitespace_only_secret_raises_config_error():
    """A whitespace-only secret is treated as empty (.strip() guard)."""
    config = _minimal_valid_config(
        calcom_webhook_enabled=True,
        calcom_webhook_secret="   \t\n  ",
    )
    with pytest.raises(ConfigError, match="calcom_webhook_secret"):
        config.validate()


def test_config_disabled_without_secret_passes():
    """Default posture — flag off, no secret — must validate clean."""
    config = _minimal_valid_config(
        calcom_webhook_enabled=False,
        calcom_webhook_secret="",
    )
    config.validate()  # must not raise


def test_config_enabled_with_secret_passes():
    """Operator opt-in path — flag on, secret present — must validate clean."""
    config = _minimal_valid_config(
        calcom_webhook_enabled=True,
        calcom_webhook_secret="s3cret-shared-with-cal-com",
    )
    config.validate()  # must not raise


# ---------------------------------------------------------------------------
# Handler-level 401 tests
# ---------------------------------------------------------------------------


class _MockRequest:
    """Minimal stand-in for aiohttp.web.Request.

    The handler only touches ``await request.read()`` and
    ``request.headers.get(...)``; we supply those two surfaces and nothing
    else so the test doesn't need an aiohttp TestServer.
    """

    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    async def read(self) -> bytes:
        return self._body


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_warned_flag():
    """Reset the module-level one-time warning flag so each test starts fresh."""
    webhook._warned_no_secret = False
    yield
    webhook._warned_no_secret = False


def test_handler_rejects_when_no_secret(monkeypatch):
    """B.05 — no secret configured -> 401 (pre-B.05 was 200 with warning)."""
    monkeypatch.setattr(webhook, "_read_secret", lambda: None)

    handler = CalcomWebhookHandler(event_bus=None)
    request = _MockRequest(body=b'{"triggerEvent": "BOOKING_CREATED", "payload": {}}')

    response = _run(handler.handle(request))

    assert response.status == 401
    # Body explains the misconfiguration without leaking secret material.
    assert b"webhook secret not configured" in response.body


def test_handler_rejects_unsigned_request_when_secret_present(monkeypatch):
    """Regression — secret configured + no signature header -> 401."""
    monkeypatch.setattr(webhook, "_read_secret", lambda: "test-secret")

    handler = CalcomWebhookHandler(event_bus=None)
    request = _MockRequest(
        body=b'{"triggerEvent": "BOOKING_CREATED", "payload": {}}',
        headers={},  # explicitly no X-Cal-Signature-256
    )

    response = _run(handler.handle(request))

    assert response.status == 401
    assert b"Missing signature" in response.body


def test_handler_rejects_bad_signature_when_secret_present(monkeypatch):
    """Regression — secret configured + wrong signature -> 401."""
    monkeypatch.setattr(webhook, "_read_secret", lambda: "test-secret")

    handler = CalcomWebhookHandler(event_bus=None)
    request = _MockRequest(
        body=b'{"triggerEvent": "BOOKING_CREATED", "payload": {}}',
        headers={"X-Cal-Signature-256": "deadbeef" * 8},
    )

    response = _run(handler.handle(request))

    assert response.status == 401
    assert b"Invalid signature" in response.body
