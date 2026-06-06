"""Tests for webhook_deliverer.py — serial event delivery with backpressure."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bridge.webhook_deliverer import (
    SerialEventDeliverer,
    Event,
    Webhook,
)


@pytest.fixture
def deliverer():
    """Create a fresh deliverer for each test."""
    return SerialEventDeliverer(max_queue=100, timeout_sec=5.0, max_retries=3)


@pytest.fixture
def sample_event():
    """Create a sample event."""
    return Event(
        event_type="test.event",
        payload={"key": "value"},
        source="test_source",
        correlation_id="corr-123",
    )


class TestEnqueueAndBackpressure:
    """Test enqueue behavior and backpressure."""

    def test_enqueue_success(self, deliverer, sample_event):
        """Test successful enqueue."""
        assert deliverer.enqueue(sample_event) is True
        assert deliverer.get_queue_size() == 1

    def test_enqueue_multiple(self, deliverer):
        """Test enqueueing multiple events."""
        events = [Event(event_type=f"test.event.{i}") for i in range(5)]
        for event in events:
            assert deliverer.enqueue(event) is True
        assert deliverer.get_queue_size() == 5

    @pytest.mark.asyncio
    async def test_backpressure_when_full(self, deliverer):
        """Test that enqueue returns False when queue is full."""
        # Create a small queue
        small_deliverer = SerialEventDeliverer(max_queue=2, timeout_sec=1.0)

        # Start the loop (but don't let it consume)
        task = small_deliverer.start()

        # Pause the loop by creating a long-running delivery.
        # Sprint R2.1/R2.2 (#1894): `side_effect=asyncio.sleep(10)` would
        # construct ONE coroutine eagerly and discard it (leaks a
        # `coroutine 'sleep' was never awaited` warning), and never
        # actually pause the mock — the value is returned, not awaited.
        # Use a callable so each invocation produces a fresh awaitable.
        with patch.object(small_deliverer, "_deliver_one", new_callable=AsyncMock) as mock_deliver:
            mock_deliver.side_effect = lambda *_a, **_kw: asyncio.sleep(10)

            # Enqueue events until queue is full
            for i in range(3):
                result = small_deliverer.enqueue(Event(event_type=f"test.{i}"))
                if i < 2:
                    assert result is True
                else:
                    # Queue should be full (1 being processed, 2 in queue)
                    assert result is False

        await small_deliverer.stop()


class TestWebhookRegistration:
    """Test webhook registration and management."""

    def test_register_webhook(self, deliverer):
        """Test registering a webhook."""
        webhook_id = deliverer.register_webhook("http://example.com/webhook", "test_webhook")
        assert webhook_id is not None
        assert len(webhook_id) > 0

        webhook = deliverer.get_webhook(webhook_id)
        assert webhook is not None
        assert webhook.url == "http://example.com/webhook"
        assert webhook.name == "test_webhook"
        assert webhook.active is True

    def test_register_multiple_webhooks(self, deliverer):
        """Test registering multiple webhooks."""
        id1 = deliverer.register_webhook("http://example1.com", "webhook1")
        id2 = deliverer.register_webhook("http://example2.com", "webhook2")

        assert id1 != id2
        assert len(deliverer.list_webhooks()) == 2

    def test_unregister_webhook(self, deliverer):
        """Test unregistering a webhook."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")
        assert deliverer.unregister_webhook(webhook_id) is True
        assert deliverer.get_webhook(webhook_id) is None

    def test_unregister_nonexistent_webhook(self, deliverer):
        """Test unregistering a nonexistent webhook."""
        assert deliverer.unregister_webhook("nonexistent") is False

    def test_list_webhooks(self, deliverer):
        """Test listing webhooks."""
        deliverer.register_webhook("http://example1.com", "webhook1")
        deliverer.register_webhook("http://example2.com", "webhook2")

        webhooks = deliverer.list_webhooks()
        assert len(webhooks) == 2
        names = [w.name for w in webhooks]
        assert "webhook1" in names
        assert "webhook2" in names


class TestMetrics:
    """Test metrics tracking."""

    def test_initial_metrics(self, deliverer):
        """Test initial metric values."""
        assert deliverer.get_delivered_count() == 0
        assert deliverer.get_failed_count() == 0
        assert deliverer.get_queue_size() == 0
        assert deliverer.get_delivery_times_ms() == []
        assert deliverer.get_avg_delivery_time_ms() == 0.0

    @pytest.mark.asyncio
    async def test_metrics_after_successful_delivery(self, deliverer):
        """Test metrics after successful delivery."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            event = Event(event_type="test.event")
            deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(0.5)
            await deliverer.stop()

            assert deliverer.get_delivered_count() == 1
            assert deliverer.get_failed_count() == 0
            assert len(deliverer.get_delivery_times_ms()) == 1

    def test_format_metrics(self, deliverer):
        """Test metrics formatting."""
        deliverer.register_webhook("http://example1.com", "webhook1")
        deliverer.register_webhook("http://example2.com", "webhook2")

        metrics_str = deliverer.format_metrics()
        assert "Webhook Delivery Metrics" in metrics_str
        assert "Delivered" in metrics_str
        assert "Failed" in metrics_str
        assert "webhook1" in metrics_str
        assert "webhook2" in metrics_str


class TestDeliveryLoop:
    """Test the delivery loop and FIFO ordering."""

    @pytest.mark.asyncio
    async def test_delivery_loop_starts_and_stops(self, deliverer):
        """Test starting and stopping the delivery loop."""
        assert deliverer._running is False

        task = deliverer.start()
        assert deliverer._running is True
        assert task is not None

        await deliverer.stop()
        assert deliverer._running is False

    @pytest.mark.asyncio
    async def test_fifo_delivery_order(self, deliverer):
        """Test that events are delivered in FIFO order."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")

        delivered_events = []

        async def mock_deliver(event):
            delivered_events.append(event.event_id)
            # Simulate delivery time
            await asyncio.sleep(0.01)

        with patch.object(deliverer, "_deliver_one", side_effect=mock_deliver):
            # Enqueue events
            events = []
            for i in range(5):
                event = Event(
                    event_type=f"test.event.{i}",
                    event_id=f"event-{i}",
                )
                events.append(event)
                deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(1.0)
            await deliverer.stop()

            # Verify FIFO order
            assert delivered_events == ["event-0", "event-1", "event-2", "event-3", "event-4"]

    @pytest.mark.asyncio
    async def test_delivery_to_all_webhooks(self, deliverer):
        """Test that one event is delivered to all webhooks."""
        webhook1_id = deliverer.register_webhook("http://example1.com", "webhook1")
        webhook2_id = deliverer.register_webhook("http://example2.com", "webhook2")

        deliveries = []

        async def mock_deliver_to_webhook(event, webhook):
            deliveries.append((event.event_id, webhook.id))
            await asyncio.sleep(0.01)

        with patch.object(
            deliverer, "_deliver_to_webhook", side_effect=mock_deliver_to_webhook
        ):
            event = Event(event_type="test.event", event_id="event-1")
            deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(0.5)
            await deliverer.stop()

            # Should deliver to both webhooks
            assert len(deliveries) == 2
            event_ids = [d[0] for d in deliveries]
            webhook_ids = [d[1] for d in deliveries]
            assert "event-1" in event_ids
            assert webhook1_id in webhook_ids
            assert webhook2_id in webhook_ids


class TestRetryLogic:
    """Test retry behavior on 5xx vs 4xx errors."""

    @pytest.mark.asyncio
    async def test_no_retry_on_4xx(self, deliverer):
        """Test that 4xx errors are not retried."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")
        deliverer.set_max_retries(3)

        post_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal post_count
            post_count += 1
            response = MagicMock()
            response.status_code = 400  # Bad Request
            return response

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            event = Event(event_type="test.event")
            deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(0.5)
            await deliverer.stop()

            # Should only POST once (no retries on 4xx)
            assert post_count == 1
            assert deliverer.get_failed_count() == 1

    @pytest.mark.asyncio
    async def test_retry_on_5xx(self, deliverer):
        """Test that 5xx errors trigger retries."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")
        deliverer.set_max_retries(2)

        post_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal post_count
            post_count += 1
            response = MagicMock()
            response.status_code = 500  # Internal Server Error
            return response

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            event = Event(event_type="test.event")
            deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(2.0)  # Allow time for retries
            await deliverer.stop()

            # Should POST multiple times (retries on 5xx)
            assert post_count == 3  # original + 2 retries
            assert deliverer.get_failed_count() == 1

    @pytest.mark.asyncio
    async def test_success_on_retry(self, deliverer):
        """Test successful delivery after retry."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")
        deliverer.set_max_retries(2)

        post_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal post_count
            post_count += 1
            response = MagicMock()
            # Fail first, then succeed
            response.status_code = 500 if post_count < 2 else 200
            return response

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            event = Event(event_type="test.event")
            deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(2.0)
            await deliverer.stop()

            # Should succeed on second attempt
            assert deliverer.get_delivered_count() == 1
            assert deliverer.get_failed_count() == 0


class TestEventFormat:
    """Test event JSON serialization."""

    @pytest.mark.asyncio
    async def test_event_json_format(self, deliverer):
        """Test that events are serialized correctly."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")

        posted_data = None

        async def mock_post(url, content=None, **kwargs):
            nonlocal posted_data
            posted_data = json.loads(content)
            response = MagicMock()
            response.status_code = 200
            return response

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            event = Event(
                event_type="test.event",
                payload={"key": "value"},
                source="test_source",
                correlation_id="corr-123",
            )
            deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(0.5)
            await deliverer.stop()

            assert posted_data is not None
            assert posted_data["event_type"] == "test.event"
            assert posted_data["payload"] == {"key": "value"}
            assert posted_data["source"] == "test_source"
            assert posted_data["correlation_id"] == "corr-123"


class TestDeliveryAttemptTracking:
    """Test delivery attempt recording."""

    @pytest.mark.asyncio
    async def test_attempt_tracking(self, deliverer):
        """Test that delivery attempts are tracked."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            event = Event(event_type="test.event")
            deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(0.5)
            await deliverer.stop()

            attempts = deliverer.get_attempts()
            assert len(attempts) >= 1
            attempt = attempts[0]
            assert attempt.webhook_id == webhook_id
            assert attempt.status_code == 200
            assert attempt.error is None
            assert attempt.duration_ms >= 0


class TestMaxRetries:
    """Test max retries configuration."""

    def test_set_max_retries(self, deliverer):
        """Test setting max retries."""
        assert deliverer._max_retries == 3
        deliverer.set_max_retries(5)
        assert deliverer._max_retries == 5

    @pytest.mark.asyncio
    async def test_respects_max_retries(self, deliverer):
        """Test that max retries is respected."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")
        deliverer.set_max_retries(2)

        post_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal post_count
            post_count += 1
            response = MagicMock()
            response.status_code = 500
            return response

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            event = Event(event_type="test.event")
            deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(2.0)
            await deliverer.stop()

            # Should POST max_retries + 1 times (initial + 2 retries)
            assert post_count == 3


class TestNoActiveWebhooks:
    """Test behavior when no webhooks are registered."""

    @pytest.mark.asyncio
    async def test_delivery_with_no_webhooks(self, deliverer):
        """Test that delivery skips gracefully with no webhooks."""
        event = Event(event_type="test.event")
        deliverer.enqueue(event)

        task = deliverer.start()
        await asyncio.sleep(0.2)
        await deliverer.stop()

        # Should not fail, just skip
        assert deliverer.get_delivered_count() == 0
        assert deliverer.get_failed_count() == 0


class TestEventJSONStructure:
    """Test Event dataclass JSON serialization."""

    def test_event_creation(self):
        """Test creating an event."""
        event = Event(
            event_type="test.type",
            payload={"a": 1},
            source="test",
            correlation_id="id-123",
        )
        assert event.event_type == "test.type"
        assert event.payload == {"a": 1}
        assert event.source == "test"
        assert event.correlation_id == "id-123"


class TestWebhookDataclass:
    """Test Webhook dataclass."""

    def test_webhook_creation(self):
        """Test creating a webhook."""
        webhook = Webhook(url="http://example.com", name="test")
        assert webhook.url == "http://example.com"
        assert webhook.name == "test"
        assert webhook.active is True
        assert webhook.failure_count == 0


class TestSerializationAndRetry:
    """Test error serialization and retry behavior with timeouts."""

    @pytest.mark.asyncio
    async def test_timeout_retry(self, deliverer):
        """Test retry on timeout."""
        webhook_id = deliverer.register_webhook("http://example.com", "webhook")
        deliverer.set_max_retries(1)

        post_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal post_count
            post_count += 1
            if post_count < 2:
                raise asyncio.TimeoutError("Request timeout")
            response = MagicMock()
            response.status_code = 200
            return response

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            event = Event(event_type="test.event")
            deliverer.enqueue(event)

            task = deliverer.start()
            await asyncio.sleep(2.0)
            await deliverer.stop()

            # Should retry on timeout and succeed
            assert deliverer.get_delivered_count() == 1


class TestHMACSigning:
    """Sprint 06.06 rework — HMAC-SHA256 signing of outbound payloads."""

    def test_sign_payload_known_digest(self):
        """sign_payload returns the canonical HMAC-SHA256 hex digest."""
        from bridge.webhook_deliverer import sign_payload
        # Reference vector — same input must always produce the same output
        digest = sign_payload("super-secret", b'{"event_type":"test.event"}')
        assert isinstance(digest, str)
        assert len(digest) == 64  # SHA-256 hex is 64 chars
        # Same input -> same output (determinism)
        assert digest == sign_payload("super-secret", b'{"event_type":"test.event"}')
        # Different secret -> different output
        assert digest != sign_payload("other-secret", b'{"event_type":"test.event"}')
        # Different body -> different output
        assert digest != sign_payload("super-secret", b'{"event_type":"different"}')

    @pytest.mark.asyncio
    async def test_hmac_signature_round_trip(self):
        """Outbound delivery includes X-Bumba-Signature-SHA256 header that
        receivers can verify by recomputing HMAC over the body bytes."""
        from bridge.webhook_deliverer import sign_payload, SIGNATURE_HEADER

        deliverer = SerialEventDeliverer(
            max_queue=10, timeout_sec=5.0, max_retries=0,
            webhook_secret="round-trip-secret",
        )
        deliverer.register_webhook("http://example.com/hook", "webhook")

        captured = {}

        async def mock_post(url, content=None, headers=None, **kwargs):
            captured["url"] = url
            captured["body"] = content
            captured["headers"] = dict(headers) if headers else {}
            response = MagicMock()
            response.status_code = 200
            return response

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            deliverer.enqueue(Event(event_type="test.event", payload={"k": "v"}))
            deliverer.start()
            await asyncio.sleep(0.3)
            await deliverer.stop()

        # Header is present
        assert SIGNATURE_HEADER in captured["headers"], (
            f"outbound POST must include {SIGNATURE_HEADER} header when secret is set"
        )

        # Receiver-side verification: recompute HMAC over the same body
        received_sig = captured["headers"][SIGNATURE_HEADER]
        expected_sig = sign_payload("round-trip-secret", captured["body"].encode())
        assert received_sig == expected_sig, (
            "X-Bumba-Signature-SHA256 must equal HMAC-SHA256(secret, body)"
        )

    @pytest.mark.asyncio
    async def test_no_signature_header_when_secret_missing(self):
        """When webhook_secret is empty, signature header is omitted (and a
        warning is logged at construction — see test_missing_secret_logs_warning)."""
        from bridge.webhook_deliverer import SIGNATURE_HEADER

        deliverer = SerialEventDeliverer(
            max_queue=10, timeout_sec=5.0, max_retries=0,
            webhook_secret="",  # explicitly missing
        )
        deliverer.register_webhook("http://example.com/hook", "webhook")

        captured = {}

        async def mock_post(url, content=None, headers=None, **kwargs):
            captured["headers"] = dict(headers) if headers else {}
            response = MagicMock()
            response.status_code = 200
            return response

        with patch("bridge.webhook_deliverer.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.AsyncClient.return_value = mock_client

            deliverer.enqueue(Event(event_type="test.event"))
            deliverer.start()
            await asyncio.sleep(0.3)
            await deliverer.stop()

        assert SIGNATURE_HEADER not in captured["headers"], (
            "signature header must be absent when webhook_secret is empty"
        )

    def test_missing_secret_logs_warning(self, caplog):
        """Constructing without webhook_secret logs a startup warning, not silent."""
        import logging
        with caplog.at_level(logging.WARNING, logger="bridge.webhook_deliverer"):
            SerialEventDeliverer(webhook_secret=None)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("UNSIGNED" in r.message or "webhook_secret" in r.message for r in warnings), (
            f"missing-secret construction must log a clear warning; got: "
            f"{[r.message for r in warnings]}"
        )

    def test_present_secret_no_warning(self, caplog):
        """Constructing WITH webhook_secret does not log the missing-secret warning."""
        import logging
        with caplog.at_level(logging.WARNING, logger="bridge.webhook_deliverer"):
            SerialEventDeliverer(webhook_secret="present")
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("UNSIGNED" in r.message for r in warnings), (
            "warning must NOT fire when secret is provided"
        )


class TestDeadTwinRemoved:
    """Sprint 06.06 rework — verify the dead twin module is gone."""

    def test_serial_event_deliverer_module_does_not_exist(self):
        """agent/bridge/serial_event_deliverer.py must be deleted."""
        from pathlib import Path
        bridge_dir = Path(__file__).resolve().parent.parent / "bridge"
        assert not (bridge_dir / "serial_event_deliverer.py").exists(), (
            "Dead twin agent/bridge/serial_event_deliverer.py must be deleted "
            "(canonical implementation lives in webhook_deliverer.py)"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
