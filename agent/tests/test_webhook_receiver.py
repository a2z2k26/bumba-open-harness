"""Tests for bridge.webhook_receiver — GitHub webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest

from bridge.webhook_receiver import WebhookReceiver

WEBHOOK_SECRET = "test-secret-key-do-not-use"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """Produce a valid ``sha256=<hex>`` signature for *body*."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _make_receiver(
    *,
    pipeline: MagicMock | None = MagicMock(),
    event_bus: MagicMock | None = MagicMock(),
) -> WebhookReceiver:
    return WebhookReceiver(
        webhook_secret=WEBHOOK_SECRET,
        task_pipeline=pipeline,
        event_bus=event_bus,
    )


# ------------------------------------------------------------------
# Signature verification
# ------------------------------------------------------------------

class TestVerifySignature:
    def test_valid_signature(self):
        receiver = _make_receiver()
        body = b'{"action": "opened"}'
        sig = _sign(body)
        assert receiver.verify_signature(body, sig) is True

    def test_valid_signature_without_prefix(self):
        receiver = _make_receiver()
        body = b'{"action": "opened"}'
        raw_digest = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert receiver.verify_signature(body, raw_digest) is True

    def test_invalid_signature(self):
        receiver = _make_receiver()
        body = b'{"action": "opened"}'
        assert receiver.verify_signature(body, "sha256=badhex") is False

    def test_tampered_body(self):
        receiver = _make_receiver()
        body = b'{"action": "opened"}'
        sig = _sign(body)
        tampered = b'{"action": "closed"}'
        assert receiver.verify_signature(tampered, sig) is False


# ------------------------------------------------------------------
# handle_webhook — signature gate
# ------------------------------------------------------------------

class TestHandleWebhookSignature:
    @pytest.mark.asyncio
    async def test_invalid_signature_returns_error(self):
        receiver = _make_receiver()
        body = b'{"zen": "hello"}'
        result = await receiver.handle_webhook(body, "sha256=wrong", "ping")
        assert result["error"] == "invalid_signature"
        assert result["status"] == 401


# ------------------------------------------------------------------
# Ping
# ------------------------------------------------------------------

class TestPingEvent:
    @pytest.mark.asyncio
    async def test_ping_returns_pong(self):
        receiver = _make_receiver()
        body = json.dumps({"zen": "Keep it logically awesome."}).encode()
        sig = _sign(body)
        result = await receiver.handle_webhook(body, sig, "ping")
        assert result == {"pong": True}


# ------------------------------------------------------------------
# Pull Request
# ------------------------------------------------------------------

class TestPullRequestEvent:
    @pytest.mark.asyncio
    async def test_opened_creates_task(self):
        pipeline = MagicMock()
        receiver = _make_receiver(pipeline=pipeline)
        payload = {
            "action": "opened",
            "pull_request": {"number": 42, "title": "Add widget"},
        }
        body = json.dumps(payload).encode()
        sig = _sign(body)

        result = await receiver.handle_webhook(body, sig, "pull_request")

        assert result["received"] is True
        assert result["action"] == "opened"
        pipeline.create_task.assert_called_once()
        call_kwargs = pipeline.create_task.call_args.kwargs
        assert call_kwargs["title"] == "Review PR #42: Add widget"
        assert call_kwargs["priority"] == "high"

    @pytest.mark.asyncio
    async def test_closed_does_not_create_task(self):
        pipeline = MagicMock()
        receiver = _make_receiver(pipeline=pipeline)
        payload = {
            "action": "closed",
            "pull_request": {"number": 42, "title": "Add widget"},
        }
        body = json.dumps(payload).encode()
        sig = _sign(body)

        result = await receiver.handle_webhook(body, sig, "pull_request")

        assert result["received"] is True
        pipeline.create_task.assert_not_called()


# ------------------------------------------------------------------
# Issues
# ------------------------------------------------------------------

class TestIssuesEvent:
    @pytest.mark.asyncio
    async def test_opened_with_bug_label_creates_task(self):
        pipeline = MagicMock()
        receiver = _make_receiver(pipeline=pipeline)
        payload = {
            "action": "opened",
            "issue": {
                "number": 99,
                "title": "Login broken",
                "labels": [{"name": "bug"}, {"name": "urgent"}],
            },
        }
        body = json.dumps(payload).encode()
        sig = _sign(body)

        result = await receiver.handle_webhook(body, sig, "issues")

        assert result["received"] is True
        pipeline.create_task.assert_called_once()
        call_kwargs = pipeline.create_task.call_args.kwargs
        assert call_kwargs["title"] == "Fix bug: Login broken"
        assert call_kwargs["assigned_to"] == "engineering"

    @pytest.mark.asyncio
    async def test_opened_without_bug_label_skips_task(self):
        pipeline = MagicMock()
        receiver = _make_receiver(pipeline=pipeline)
        payload = {
            "action": "opened",
            "issue": {
                "number": 100,
                "title": "Feature request",
                "labels": [{"name": "enhancement"}],
            },
        }
        body = json.dumps(payload).encode()
        sig = _sign(body)

        await receiver.handle_webhook(body, sig, "issues")
        pipeline.create_task.assert_not_called()


# ------------------------------------------------------------------
# Check Run
# ------------------------------------------------------------------

class TestCheckRunEvent:
    @pytest.mark.asyncio
    async def test_failure_creates_critical_task(self):
        pipeline = MagicMock()
        receiver = _make_receiver(pipeline=pipeline)
        payload = {
            "check_run": {
                "name": "test-suite",
                "conclusion": "failure",
            },
        }
        body = json.dumps(payload).encode()
        sig = _sign(body)

        result = await receiver.handle_webhook(body, sig, "check_run")

        assert result["received"] is True
        assert result["conclusion"] == "failure"
        pipeline.create_task.assert_called_once()
        call_kwargs = pipeline.create_task.call_args.kwargs
        assert call_kwargs["title"] == "Fix failing tests: test-suite"
        assert call_kwargs["priority"] == "critical"

    @pytest.mark.asyncio
    async def test_success_does_not_create_task(self):
        pipeline = MagicMock()
        receiver = _make_receiver(pipeline=pipeline)
        payload = {
            "check_run": {
                "name": "test-suite",
                "conclusion": "success",
            },
        }
        body = json.dumps(payload).encode()
        sig = _sign(body)

        await receiver.handle_webhook(body, sig, "check_run")
        pipeline.create_task.assert_not_called()


# ------------------------------------------------------------------
# Push
# ------------------------------------------------------------------

class TestPushEvent:
    @pytest.mark.asyncio
    async def test_push_does_not_create_task(self):
        pipeline = MagicMock()
        receiver = _make_receiver(pipeline=pipeline)
        payload = {
            "ref": "refs/heads/main",
            "commits": [{"id": "abc123", "message": "fix typo"}],
        }
        body = json.dumps(payload).encode()
        sig = _sign(body)

        result = await receiver.handle_webhook(body, sig, "push")

        assert result["received"] is True
        assert result["ref"] == "refs/heads/main"
        pipeline.create_task.assert_not_called()


# ------------------------------------------------------------------
# Unknown event type
# ------------------------------------------------------------------

class TestUnknownEvent:
    @pytest.mark.asyncio
    async def test_unknown_event_returns_received(self):
        receiver = _make_receiver()
        payload = {"some": "data"}
        body = json.dumps(payload).encode()
        sig = _sign(body)

        result = await receiver.handle_webhook(body, sig, "star")

        assert result == {"received": True, "event_type": "star"}


# ------------------------------------------------------------------
# No pipeline / no event bus
# ------------------------------------------------------------------

class TestOptionalDependencies:
    @pytest.mark.asyncio
    async def test_no_pipeline_skips_task_creation(self):
        receiver = _make_receiver(pipeline=None)
        payload = {
            "action": "opened",
            "pull_request": {"number": 1, "title": "Test"},
        }
        body = json.dumps(payload).encode()
        sig = _sign(body)

        result = await receiver.handle_webhook(body, sig, "pull_request")

        # Should succeed without error -- no task creation attempted.
        assert result["received"] is True
        assert result["action"] == "opened"

    @pytest.mark.asyncio
    async def test_no_event_bus_skips_publish(self):
        receiver = _make_receiver(event_bus=None)
        payload = {"zen": "Responsive is better than fast."}
        body = json.dumps(payload).encode()
        sig = _sign(body)

        # Should not raise even though event_bus is None.
        result = await receiver.handle_webhook(body, sig, "ping")
        assert result == {"pong": True}


# ------------------------------------------------------------------
# EventBus integration
# ------------------------------------------------------------------

class TestEventBusPublishing:
    @pytest.mark.asyncio
    async def test_event_published_on_success(self):
        event_bus = MagicMock()
        receiver = _make_receiver(event_bus=event_bus)
        payload = {"zen": "Anything added dilutes everything else."}
        body = json.dumps(payload).encode()
        sig = _sign(body)

        await receiver.handle_webhook(body, sig, "ping")

        event_bus.publish.assert_called_once()
        call_kwargs = event_bus.publish.call_args.kwargs
        assert call_kwargs["event_type"] == "webhook.github.ping"
        assert call_kwargs["source"] == "webhook_receiver"

    @pytest.mark.asyncio
    async def test_event_bus_error_swallowed(self):
        event_bus = MagicMock()
        event_bus.publish.side_effect = ValueError("unknown event type")
        receiver = _make_receiver(event_bus=event_bus)
        payload = {"zen": "test"}
        body = json.dumps(payload).encode()
        sig = _sign(body)

        # Should not raise despite EventBus error.
        result = await receiver.handle_webhook(body, sig, "ping")
        assert result == {"pong": True}
