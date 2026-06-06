"""MS5.9 — Event-Driven + Time Hybrid Architecture.

Publish/subscribe event system with time-based fallback. Events are
persisted to daily JSONL files, correlated via correlation_id, and
monitored for missed events.

Event types: message.received, message.processed, deploy.started,
deploy.completed, deploy.failed, failure.detected, failure.recovered,
failure.escalated, schedule.triggered, health.changed, trust.changed,
guardrail.triggered
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# All known event types
EVENT_TYPES = (
    "message.received",
    "message.processed",
    "deploy.started",
    "deploy.completed",
    "deploy.failed",
    "failure.detected",
    "failure.recovered",
    "failure.escalated",
    "schedule.triggered",
    "health.changed",
    "trust.changed",
    "guardrail.triggered",
    # WorkOrder lifecycle events (Zone 3)
    "workorder.created",
    "workorder.assigned",
    "workorder.dispatched",
    "workorder.executing",
    "workorder.verifying",
    "workorder.completed",
    "workorder.complete",
    "workorder.failed",
    # Agent progress (Zone 3)
    "agent.progress",
    # Pipeline events (Zone 3)
    "pipeline.stage_advanced",
    "pipeline.stage_rejected",
    "pipeline.gate_failed",
    # Crash black box (Sprint E.3)
    "crash.recorded",
    # Department lifecycle events (Z4.4.2)
    "department.task.started",
    "department.task.completed",
    "department.task.failed",
    "department.delegation.started",
    # Phase 5 protocol events (Sprint 23)
    "directive.issued",
    "directive.status_changed",
    "task.status_changed",
    "surface.written",
    "surface.acknowledged",
    # Claude Code CLI lifecycle hook events (Sprint E2.3, issue #1240)
    "hook.session_start",
    "hook.session_end",
    "hook.user_prompt_submit",
    "hook.pre_tool_use",
    "hook.post_tool_use",
    "hook.stop",
    "hook.subagent_stop",
    "hook.notification",
    "hook.pre_compact",
    "hook.post_compact",
    "hook.pre_model_invoke",
    "hook.post_model_invoke",
    "hook.error",
    # Z4 chief-session lifecycle events (Z4-S01 #1385, cataloged in
    # config/registry/events/chief-session.yaml; emitters in S30/S32/S40)
    "chief_session.created",
    "chief_session.state_changed",
    "chief_session.cost_updated",
    "chief_session.timed_out",
    # Z4 chief-dispatcher events (Z4-S04 #1389, cataloged in
    # config/registry/events/chief-dispatcher.yaml; emitter in chief_dispatcher.py)
    "chief_dispatcher.routed",
    "chief_dispatcher.rejected",
    "chief_dispatcher.requeued",
    # Z4-S64 (#1408) — per-department circuit breaker transitions.
    # Cataloged in config/registry/events/chief-dispatcher.yaml.
    "chief_dispatcher.circuit_open",
    "chief_dispatcher.circuit_closed",
)

# Department lifecycle event type constants (Z4.4.2)
DEPARTMENT_TASK_STARTED = "department.task.started"
DEPARTMENT_TASK_COMPLETED = "department.task.completed"
DEPARTMENT_TASK_FAILED = "department.task.failed"
DEPARTMENT_DELEGATION_STARTED = "department.delegation.started"

# Phase 5 protocol event type constants (Sprint 23)
DIRECTIVE_ISSUED = "directive.issued"
DIRECTIVE_STATUS_CHANGED = "directive.status_changed"
TASK_STATUS_CHANGED = "task.status_changed"
SURFACE_WRITTEN = "surface.written"
SURFACE_ACKNOWLEDGED = "surface.acknowledged"

# Claude Code CLI lifecycle hook event type constants (Sprint E2.3, issue #1240)
HOOK_SESSION_START = "hook.session_start"
HOOK_SESSION_END = "hook.session_end"
HOOK_USER_PROMPT_SUBMIT = "hook.user_prompt_submit"
HOOK_PRE_TOOL_USE = "hook.pre_tool_use"
HOOK_POST_TOOL_USE = "hook.post_tool_use"
HOOK_STOP = "hook.stop"
HOOK_SUBAGENT_STOP = "hook.subagent_stop"
HOOK_NOTIFICATION = "hook.notification"
HOOK_PRE_COMPACT = "hook.pre_compact"
HOOK_POST_COMPACT = "hook.post_compact"
HOOK_PRE_MODEL_INVOKE = "hook.pre_model_invoke"
HOOK_POST_MODEL_INVOKE = "hook.post_model_invoke"
HOOK_ERROR = "hook.error"


@dataclass
class Event:
    event_type: str = ""
    payload: dict = field(default_factory=dict)
    source: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: str | None = None
    is_replay: bool = False


@dataclass
class Subscription:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    event_type: str = ""
    callback: Callable | None = None
    filter_fn: Callable | None = None  # optional filter
    expected_interval: float | None = None  # seconds; if set, fallback monitor tracks it
    last_triggered: float = 0.0


@dataclass
class CorrelationChain:
    correlation_id: str = ""
    event_ids: list[str] = field(default_factory=list)
    status: str = "in_progress"  # in_progress | completed | failed | timeout
    started_at: str = ""
    updated_at: str = ""


class EventBus:
    """Thread-safe publish/subscribe event bus with persistence and correlation."""

    _default_instance: "EventBus | None" = None

    @classmethod
    def get_instance(cls) -> "EventBus":
        """Return the module-level default instance (created on first call)."""
        if cls._default_instance is None:
            cls._default_instance = cls()
        return cls._default_instance

    def __init__(self, data_dir: Path | None = None):
        self._lock = threading.Lock()
        self._data_dir = data_dir  # if None, no persistence
        self._subscriptions: dict[str, list[Subscription]] = {}  # event_type -> [Subscription]
        self._all_subscriptions: dict[str, Subscription] = {}  # sub_id -> Subscription
        self._correlations: dict[str, CorrelationChain] = {}
        self._handler_errors: list[dict] = []
        self._event_count = 0
        self._recent_events: list[Event] = []  # bounded ring for format_recent_events
        # Sprint 07.07 — peer-target routing. When set, payloads with a
        # ``peer_target`` field route through this bridge before the
        # local publish completes. Stays None when peer coordination is
        # disabled, in which case publish() behaves exactly as it did
        # pre-07.07. See bridge/remote_events.py for the bridge contract.
        self._remote_event_bridge: object | None = None
        self._peer_coordination_enabled: bool = False

    def set_remote_event_bridge(
        self,
        bridge: object | None,
        peer_coordination_enabled: bool = True,
    ) -> None:
        """Wire a ``RemoteEventBridge`` for peer-target routing.

        Sprint 07.07 — invoked from ``BridgeApp._wire`` via the
        WIRING_MANIFEST when ``config.peer_coordination_enabled`` is
        True. The flag is captured here so subsequent ``publish`` calls
        can short-circuit cheaply when peer routing is off (which is
        the production default until cross-machine coordination ships).
        """
        self._remote_event_bridge = bridge
        self._peer_coordination_enabled = bool(peer_coordination_enabled)

    def publish(
        self,
        event_type: str,
        payload: dict | None = None,
        source: str = "",
        correlation_id: str | None = None,
    ) -> Event:
        """Publish an event and invoke all matching handlers.

        Sprint 07.07 — when ``payload`` carries a ``peer_target`` field
        and the wire-time ``RemoteEventBridge`` is present, the event
        is also forwarded to that peer through the bridge. Forwarding
        is best-effort: failures are logged but never block the local
        publish, which always runs (events.jsonl + subscribers fire
        regardless of peer-routing outcome).
        """
        event = Event(
            event_type=event_type,
            payload=payload or {},
            source=source,
            correlation_id=correlation_id,
        )
        # Sprint 07.07 — peer-target routing. Detect a ``peer_target`` in
        # the payload (the cleanest signal: it travels with the event
        # the same way ``correlation_id`` does, no API surface change at
        # call sites). If both the bridge is wired and the
        # peer_coordination flag is on, forward through the bridge
        # before the local dispatch — failures inside the bridge never
        # interrupt the always-on local publish.
        peer_target: str | None = None
        if isinstance(event.payload, dict):
            raw_target = event.payload.get("peer_target")
            if isinstance(raw_target, str) and raw_target:
                peer_target = raw_target
        if (
            peer_target
            and self._remote_event_bridge is not None
            and self._peer_coordination_enabled
        ):
            try:
                self._remote_event_bridge.publish_remote(  # type: ignore[attr-defined]
                    event_type, event.payload, peer_target
                )
            except Exception:
                log.exception(
                    "remote publish failed; event still persisted locally "
                    "(event_type=%s peer_target=%s)",
                    event_type,
                    peer_target,
                )
        self._persist_event(event)
        self._update_correlation(event)
        self._dispatch(event)
        with self._lock:
            self._event_count += 1
            self._recent_events.append(event)
            # Keep only last 100 events in memory
            if len(self._recent_events) > 100:
                self._recent_events = self._recent_events[-100:]
        return event

    def subscribe(
        self,
        event_type: str,
        callback: Callable,
        filter_fn: Callable | None = None,
        expected_interval: float | None = None,
    ) -> str:
        """Register a handler. Returns subscription ID."""
        sub = Subscription(
            event_type=event_type,
            callback=callback,
            filter_fn=filter_fn,
            expected_interval=expected_interval,
        )
        with self._lock:
            self._subscriptions.setdefault(event_type, []).append(sub)
            self._all_subscriptions[sub.id] = sub
        return sub.id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a handler. Returns True if found and removed."""
        with self._lock:
            sub = self._all_subscriptions.pop(subscription_id, None)
            if sub is None:
                return False
            subs = self._subscriptions.get(sub.event_type, [])
            self._subscriptions[sub.event_type] = [
                s for s in subs if s.id != subscription_id
            ]
            return True

    def replay(
        self,
        event_type: str | None = None,
        since_timestamp: str | None = None,
    ) -> list[Event]:
        """Replay events from persisted files. Returns list of replayed events."""
        if not self._data_dir:
            return []

        events_dir = self._data_dir / "events"
        if not events_dir.exists():
            return []

        replayed: list[Event] = []
        for jsonl_path in sorted(events_dir.glob("*.jsonl")):
            for line in jsonl_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Filter by event_type if specified
                if event_type and data.get("event_type") != event_type:
                    continue

                # Filter by since_timestamp if specified
                if since_timestamp and data.get("timestamp", "") < since_timestamp:
                    continue

                event = Event(
                    event_type=data.get("event_type", ""),
                    payload=data.get("payload", {}),
                    source=data.get("source", ""),
                    event_id=data.get("event_id", ""),
                    timestamp=data.get("timestamp", ""),
                    correlation_id=data.get("correlation_id"),
                    is_replay=True,
                )
                replayed.append(event)

        return replayed

    def get_subscription(self, sub_id: str) -> Subscription | None:
        """Get a subscription by ID."""
        with self._lock:
            return self._all_subscriptions.get(sub_id)

    def list_subscriptions(self) -> list[Subscription]:
        """List all active subscriptions."""
        with self._lock:
            return list(self._all_subscriptions.values())

    # ------------------------------------------------------------------
    # Correlation tracking
    # ------------------------------------------------------------------

    def start_chain(self, correlation_id: str | None = None) -> str:
        """Start a new correlation chain. Returns correlation_id."""
        cid = correlation_id or uuid.uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()
        chain = CorrelationChain(
            correlation_id=cid,
            started_at=now,
            updated_at=now,
        )
        with self._lock:
            self._correlations[cid] = chain
        return cid

    def complete_chain(self, correlation_id: str) -> bool:
        """Mark a chain as completed. Returns True if chain existed."""
        with self._lock:
            chain = self._correlations.get(correlation_id)
            if chain is None:
                return False
            chain.status = "completed"
            chain.updated_at = datetime.now(timezone.utc).isoformat()
            return True

    def fail_chain(self, correlation_id: str) -> bool:
        """Mark a chain as failed. Returns True if chain existed."""
        with self._lock:
            chain = self._correlations.get(correlation_id)
            if chain is None:
                return False
            chain.status = "failed"
            chain.updated_at = datetime.now(timezone.utc).isoformat()
            return True

    def get_chain(self, correlation_id: str) -> CorrelationChain | None:
        """Get a correlation chain by ID."""
        with self._lock:
            return self._correlations.get(correlation_id)

    def get_active_chains(self) -> list[CorrelationChain]:
        """Return all chains with status 'in_progress'."""
        with self._lock:
            return [c for c in self._correlations.values() if c.status == "in_progress"]

    # ------------------------------------------------------------------
    # Fallback monitoring
    # ------------------------------------------------------------------

    def check_fallbacks(self) -> list[str]:
        """Check all subscriptions with expected_interval.

        For each subscription where (now - last_triggered) > expected_interval,
        fire the callback with a synthetic fallback event and return the sub ID.

        Returns list of triggered subscription IDs.
        """
        now = time.monotonic()
        triggered_ids: list[str] = []

        with self._lock:
            candidates = [
                s for s in self._all_subscriptions.values()
                if s.expected_interval is not None and s.last_triggered > 0
            ]

        for sub in candidates:
            elapsed = now - sub.last_triggered
            if elapsed > sub.expected_interval:
                fallback_event = Event(
                    event_type=sub.event_type,
                    payload={"fallback": True, "elapsed_seconds": elapsed},
                    source="fallback_monitor",
                )
                try:
                    sub.callback(fallback_event)
                    sub.last_triggered = now
                except Exception as exc:
                    with self._lock:
                        self._handler_errors.append({
                            "subscription_id": sub.id,
                            "event_id": fallback_event.event_id,
                            "error": str(exc),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    log.warning("Fallback handler error for sub %s: %s", sub.id, exc)
                triggered_ids.append(sub.id)

        return triggered_ids

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_event_count(self) -> int:
        """Return total number of published events."""
        return self._event_count

    def get_handler_errors(self) -> list[dict]:
        """Return list of handler error records."""
        with self._lock:
            return list(self._handler_errors)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_event(self, event: Event) -> None:
        """Append event to daily JSONL file."""
        if not self._data_dir:
            return
        events_dir = self._data_dir / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filepath = events_dir / f"{date_str}.jsonl"
        record = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "payload": event.payload,
            "source": event.source,
            "timestamp": event.timestamp,
            "correlation_id": event.correlation_id,
        }
        with self._lock:
            with open(filepath, "a") as f:
                f.write(json.dumps(record) + "\n")

    def _dispatch(self, event: Event) -> None:
        """Call all matching handlers. Errors in one handler don't affect others."""
        with self._lock:
            subs = list(self._subscriptions.get(event.event_type, []))
        for sub in subs:
            if sub.filter_fn and not sub.filter_fn(event):
                continue
            try:
                sub.callback(event)
                sub.last_triggered = time.monotonic()
            except Exception as exc:
                with self._lock:
                    self._handler_errors.append({
                        "subscription_id": sub.id,
                        "event_id": event.event_id,
                        "error": str(exc),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                log.warning("Handler error for sub %s: %s", sub.id, exc)

    def _update_correlation(self, event: Event) -> None:
        """Link event to correlation chain if correlation_id present."""
        if not event.correlation_id:
            return
        with self._lock:
            chain = self._correlations.get(event.correlation_id)
            if chain is not None:
                chain.event_ids.append(event.event_id)
                chain.updated_at = datetime.now(timezone.utc).isoformat()

    def record_crash(
        self,
        error: Exception,
        context: dict | None = None,
    ) -> None:
        """Record a structured crash event as the last entry before exit.

        This is the black box — it captures:
        - Exception type and message
        - Traceback summary (first 500 chars)
        - Active correlation chains
        - Provided context (session duration, token usage, etc.)
        - Total event count this session

        Safe to call in error handlers — catches all internal exceptions.
        """
        import traceback as tb_module

        try:
            tb_text = "".join(tb_module.format_exception(type(error), error, error.__traceback__))
            # Truncate traceback to avoid massive payloads
            if len(tb_text) > 500:
                tb_text = tb_text[:500] + "... (truncated)"

            active = self.get_active_chains()
            chain_ids = [c.correlation_id for c in active]

            payload = {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "traceback_summary": tb_text,
                "active_chains": chain_ids,
                "total_events_this_session": self._event_count,
                **(context or {}),
            }

            self.publish(
                event_type="crash.recorded",
                payload=payload,
                source="crash_black_box",
            )

            log.warning(
                "Crash black box recorded: %s: %s (%d active chains)",
                type(error).__name__, error, len(chain_ids),
            )
        except Exception as inner:
            # Never let crash recording itself crash the process
            log.error("Failed to record crash black box: %s", inner)

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_recent_events(self, limit: int = 20) -> str:
        """Format recent events as markdown."""
        with self._lock:
            events = self._recent_events[-limit:]

        if not events:
            return "No recent events."

        lines = ["## Recent Events", ""]
        for evt in reversed(events):
            ts = evt.timestamp
            if "T" in ts:
                ts = ts.split("T")[1][:8]  # HH:MM:SS
            corr = f" [chain:{evt.correlation_id[:8]}]" if evt.correlation_id else ""
            payload_summary = ""
            if evt.payload:
                keys = list(evt.payload.keys())[:3]
                payload_summary = " " + ", ".join(f"{k}={evt.payload[k]}" for k in keys)
            lines.append(f"- `{ts}` **{evt.event_type}**{corr}{payload_summary}")

        return "\n".join(lines)

    def format_chain(self, correlation_id: str) -> str | None:
        """Format a correlation chain as markdown."""
        with self._lock:
            chain = self._correlations.get(correlation_id)
        if chain is None:
            return None

        lines = [
            f"## Chain: {chain.correlation_id}",
            f"- **Status**: {chain.status}",
            f"- **Started**: {chain.started_at}",
            f"- **Updated**: {chain.updated_at}",
            f"- **Events**: {len(chain.event_ids)}",
        ]
        for eid in chain.event_ids:
            lines.append(f"  - `{eid}`")

        return "\n".join(lines)
