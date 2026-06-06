"""MS5.10 — Serial Webhook Event Delivery with Backpressure.

Guarantees in-order delivery of events to multiple webhooks with automatic
retry on 5xx errors, backpressure when queue is full, and comprehensive
metrics tracking.

Design:
- Single delivery loop processes queue FIFO (no concurrency)
- Enqueue returns False if queue is full (backpressure signal)
- Retries only on 5xx (not 4xx), configurable max retries
- All deliveries serialized (one event to all webhooks, then next event)
- Async-only, no threads
- HMAC-SHA256 signing of outbound payloads when webhook_secret is configured
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    httpx = None

log = logging.getLogger(__name__)


@dataclass
class Webhook:
    """Registered webhook endpoint."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    url: str = ""
    name: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    active: bool = True
    failure_count: int = 0
    last_failure: str | None = None


@dataclass
class Event:
    """Event to be delivered."""

    event_type: str = ""
    payload: dict = field(default_factory=dict)
    source: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: str | None = None


@dataclass
class DeliveryAttempt:
    """Record of a single delivery attempt."""

    event_id: str = ""
    webhook_id: str = ""
    webhook_url: str = ""
    status_code: int | None = None
    error: str | None = None
    duration_ms: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    retry_count: int = 0


SIGNATURE_HEADER = "X-Bumba-Signature-SHA256"


def sign_payload(secret: str, body_bytes: bytes) -> str:
    """Return HMAC-SHA256 hex digest of *body_bytes* using *secret*.

    Receivers verify by recomputing the digest and comparing to the
    ``X-Bumba-Signature-SHA256`` header value (constant-time comparison).
    """
    return hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


class SerialEventDeliverer:
    """Delivers events to webhooks in strict order with backpressure.

    HMAC-SHA256 signing: when constructed with a non-empty ``webhook_secret``,
    every outbound POST carries an ``X-Bumba-Signature-SHA256`` header whose
    value is the HMAC of the request body. When the secret is empty or None,
    a warning is logged at startup and signing is skipped (downstream cannot
    verify origin in that mode).
    """

    def __init__(
        self,
        max_queue: int = 1000,
        timeout_sec: float = 30.0,
        max_retries: int = 3,
        webhook_secret: str | None = None,
    ):
        """Initialize the deliverer.

        Args:
            max_queue: Maximum queue size before backpressure (enqueue returns False)
            timeout_sec: HTTP timeout for each POST request
            max_retries: Max retries on 5xx errors (default 3)
            webhook_secret: HMAC-SHA256 secret for outbound payload signing.
                When empty or None, signing is skipped and a warning is logged.
        """
        self._max_queue = max_queue
        self._timeout_sec = timeout_sec
        self._max_retries = max_retries
        self._webhook_secret = webhook_secret or ""

        if not self._webhook_secret:
            log.warning(
                "SerialEventDeliverer constructed without webhook_secret — "
                "outbound payloads will be UNSIGNED. Downstream receivers "
                "cannot verify origin. Set [api] webhook_secret in bridge.toml "
                "or webhook_secret in .secrets to enable HMAC-SHA256 signing."
            )

        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue)
        self._webhooks: dict[str, Webhook] = {}  # id -> Webhook
        self._loop_task: asyncio.Task | None = None
        self._running = False

        # Metrics
        self._delivered_count = 0
        self._failed_count = 0
        self._delivery_times: list[int] = []
        self._attempts: list[DeliveryAttempt] = []

    def enqueue(self, event: Event) -> bool:
        """Add event to delivery queue.

        Returns False if queue is full (backpressure).
        """
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            log.warning(f"Webhook queue full — backpressure triggered (size={self._queue.qsize()})")
            return False

    def register_webhook(self, url: str, name: str) -> str:
        """Register a webhook URL. Returns webhook ID."""
        webhook = Webhook(url=url, name=name)
        self._webhooks[webhook.id] = webhook
        log.info(f"Registered webhook {webhook.id}: {name} ({url})")
        return webhook.id

    def unregister_webhook(self, webhook_id: str) -> bool:
        """Remove a webhook. Returns True if found."""
        if webhook_id in self._webhooks:
            del self._webhooks[webhook_id]
            log.info(f"Unregistered webhook {webhook_id}")
            return True
        return False

    def set_max_retries(self, n: int) -> None:
        """Set maximum retries for 5xx errors."""
        self._max_retries = n
        log.debug(f"Set max_retries to {n}")

    def start(self) -> asyncio.Task:
        """Start the delivery loop in background. Returns the task."""
        if self._running:
            log.warning("SerialEventDeliverer already running")
            return self._loop_task or asyncio.Task(asyncio.sleep(0))

        self._running = True
        self._loop_task = asyncio.create_task(self._delivery_loop())
        log.info("SerialEventDeliverer started")
        return self._loop_task

    async def stop(self) -> None:
        """Stop the delivery loop and wait for in-flight deliveries."""
        if not self._running:
            return

        self._running = False
        log.info("Stopping SerialEventDeliverer...")

        if self._loop_task:
            try:
                await asyncio.wait_for(self._loop_task, timeout=10.0)
            except asyncio.TimeoutError:
                log.warning("Delivery loop did not stop within 10s, cancelling")
                self._loop_task.cancel()
                try:
                    await self._loop_task
                except asyncio.CancelledError:
                    pass

        log.info("SerialEventDeliverer stopped")

    async def _delivery_loop(self) -> None:
        """Main loop: pop events from queue, deliver to all webhooks in sequence."""
        log.debug("Delivery loop started")

        while self._running:
            try:
                # Wait for next event (with timeout to allow clean shutdown)
                try:
                    event = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    # No event available, loop again
                    continue

                # Deliver to all registered webhooks
                await self._deliver_one(event)

            except asyncio.CancelledError:
                log.debug("Delivery loop cancelled")
                break
            except Exception as exc:
                log.error(f"Delivery loop error: {exc}", exc_info=True)

        log.debug("Delivery loop ended")

    async def _deliver_one(self, event: Event) -> None:
        """Deliver a single event to all webhooks sequentially.

        This method is where actual delivery happens. For each webhook:
        1. POST event JSON
        2. If 5xx, retry up to max_retries times
        3. If 4xx, fail immediately (no retry)
        4. Track delivery attempt and duration
        """
        if not self._webhooks:
            log.debug(f"No webhooks registered — skipping delivery of event {event.event_id}")
            return

        active_webhooks = [w for w in self._webhooks.values() if w.active]
        if not active_webhooks:
            log.warning("All webhooks are inactive")
            return

        log.debug(f"Delivering event {event.event_id} ({event.event_type}) to {len(active_webhooks)} webhooks")

        for webhook in active_webhooks:
            await self._deliver_to_webhook(event, webhook)

    async def _deliver_to_webhook(self, event: Event, webhook: Webhook) -> None:
        """Deliver event to a single webhook with retry logic."""
        event_json = json.dumps({
            "event_id": event.event_id,
            "event_type": event.event_type,
            "payload": event.payload,
            "source": event.source,
            "timestamp": event.timestamp,
            "correlation_id": event.correlation_id,
        })
        body_bytes = event_json.encode()

        # Build outbound headers, optionally including the HMAC signature.
        headers = {"Content-Type": "application/json"}
        if self._webhook_secret:
            headers[SIGNATURE_HEADER] = sign_payload(self._webhook_secret, body_bytes)

        for attempt_num in range(self._max_retries + 1):
            start_time = time.time()
            status_code = None
            error = None

            try:
                if httpx is None:
                    raise RuntimeError("httpx not installed — cannot deliver webhooks")

                async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                    response = await client.post(
                        webhook.url,
                        content=event_json,
                        headers=headers,
                    )
                    status_code = response.status_code

                duration_ms = int((time.time() - start_time) * 1000)

                # Log attempt
                attempt = DeliveryAttempt(
                    event_id=event.event_id,
                    webhook_id=webhook.id,
                    webhook_url=webhook.url,
                    status_code=status_code,
                    error=None,
                    duration_ms=duration_ms,
                    retry_count=attempt_num,
                )
                self._attempts.append(attempt)
                self._delivery_times.append(duration_ms)

                if 200 <= status_code < 300:
                    # Success
                    self._delivered_count += 1
                    log.debug(
                        f"Delivered event {event.event_id} to {webhook.name} "
                        f"(webhook_id={webhook.id}, status={status_code}, ms={duration_ms})"
                    )
                    return

                elif 400 <= status_code < 500:
                    # 4xx: fail immediately, no retry
                    self._failed_count += 1
                    webhook.failure_count += 1
                    webhook.last_failure = datetime.now(timezone.utc).isoformat()
                    log.warning(
                        f"Webhook {webhook.name} returned {status_code} (no retry for 4xx): {webhook.url}"
                    )
                    return

                elif status_code >= 500:
                    # 5xx: might retry
                    if attempt_num < self._max_retries:
                        # Backoff: exponential with small delay
                        delay = min(2 ** attempt_num, 10)  # max 10s
                        log.warning(
                            f"Event {event.event_id} delivery to {webhook.name} failed with {status_code}, "
                            f"retrying in {delay}s (attempt {attempt_num + 1}/{self._max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        # Max retries exceeded
                        self._failed_count += 1
                        webhook.failure_count += 1
                        webhook.last_failure = datetime.now(timezone.utc).isoformat()
                        log.error(
                            f"Event {event.event_id} delivery to {webhook.name} failed after {self._max_retries} retries (final status={status_code})"
                        )
                        return

            except asyncio.TimeoutError:
                error = "timeout"
                if attempt_num < self._max_retries:
                    delay = min(2 ** attempt_num, 10)
                    log.warning(
                        f"Event {event.event_id} delivery to {webhook.name} timed out, "
                        f"retrying in {delay}s (attempt {attempt_num + 1}/{self._max_retries})"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    self._failed_count += 1
                    webhook.failure_count += 1
                    webhook.last_failure = datetime.now(timezone.utc).isoformat()
                    log.error(f"Event {event.event_id} delivery to {webhook.name} timed out after {self._max_retries} retries")
                    return

            except Exception as exc:
                error = str(exc)
                duration_ms = int((time.time() - start_time) * 1000)

                # Log attempt
                attempt = DeliveryAttempt(
                    event_id=event.event_id,
                    webhook_id=webhook.id,
                    webhook_url=webhook.url,
                    status_code=None,
                    error=error,
                    duration_ms=duration_ms,
                    retry_count=attempt_num,
                )
                self._attempts.append(attempt)

                if attempt_num < self._max_retries:
                    delay = min(2 ** attempt_num, 10)
                    log.warning(
                        f"Event {event.event_id} delivery to {webhook.name} failed ({error}), "
                        f"retrying in {delay}s (attempt {attempt_num + 1}/{self._max_retries})"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    self._failed_count += 1
                    webhook.failure_count += 1
                    webhook.last_failure = datetime.now(timezone.utc).isoformat()
                    log.error(f"Event {event.event_id} delivery to {webhook.name} failed with error: {error}")
                    return

    # -- Metrics --

    def get_delivered_count(self) -> int:
        """Return number of successfully delivered events."""
        return self._delivered_count

    def get_failed_count(self) -> int:
        """Return number of failed event deliveries."""
        return self._failed_count

    def get_queue_size(self) -> int:
        """Return current queue size."""
        return self._queue.qsize()

    def get_delivery_times_ms(self) -> list[int]:
        """Return list of delivery times in milliseconds."""
        return list(self._delivery_times)

    def get_avg_delivery_time_ms(self) -> float:
        """Return average delivery time, or 0 if no deliveries yet."""
        if not self._delivery_times:
            return 0.0
        return sum(self._delivery_times) / len(self._delivery_times)

    def get_attempts(self) -> list[DeliveryAttempt]:
        """Return list of all delivery attempts."""
        return list(self._attempts)

    def list_webhooks(self) -> list[Webhook]:
        """Return list of all registered webhooks."""
        return list(self._webhooks.values())

    def get_webhook(self, webhook_id: str) -> Webhook | None:
        """Get a webhook by ID."""
        return self._webhooks.get(webhook_id)

    def format_metrics(self) -> str:
        """Format metrics as markdown."""
        lines = [
            "## Webhook Delivery Metrics",
            f"- **Delivered**: {self._delivered_count}",
            f"- **Failed**: {self._failed_count}",
            f"- **Queue Size**: {self._queue.qsize()}/{self._max_queue}",
            f"- **Avg Delivery Time**: {self.get_avg_delivery_time_ms():.1f}ms",
            f"- **Registered Webhooks**: {len(self._webhooks)}",
            f"- **Active Webhooks**: {sum(1 for w in self._webhooks.values() if w.active)}",
        ]

        if self._webhooks:
            lines.append("")
            lines.append("### Webhooks")
            for webhook in self._webhooks.values():
                status = "active" if webhook.active else "inactive"
                lines.append(
                    f"- `{webhook.id}` **{webhook.name}** ({status}) — "
                    f"failures={webhook.failure_count}"
                )

        return "\n".join(lines)
