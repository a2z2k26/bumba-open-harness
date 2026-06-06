"""HooksTelemetrySubscriber — tail ~/data/hooks-telemetry.jsonl and publish to EventBus.

Sprint E2.3, issue #1240.

Tails the JSONL sink written by the E2.1 lifecycle hook scripts
(~/.claude/hooks/<Event>/01-emit.sh) and translates each line into a
typed ``hook.*`` EventBus event. Uses byte-offset bookkeeping so restarts
do not re-publish history. Poll interval: 250ms.

Architecture decision (E2.3):
  - Hooks = capture (filesystem boundary, fire-and-forget from CLI subprocess)
  - EventBus = pub-sub for cross-module reactions (this subscriber bridges them)
  - OTEL spans = in-process trace correlation (separate pipeline)
  - REST/WebSocket = operator-facing action + live-event firehose
  See docs/architecture/adr/2026-05-03-control-plane-layering.md for the full
  four-surface doctrine.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from bridge.event_bus import (
    EventBus,
    HOOK_SESSION_START,
    HOOK_SESSION_END,
    HOOK_USER_PROMPT_SUBMIT,
    HOOK_PRE_TOOL_USE,
    HOOK_POST_TOOL_USE,
    HOOK_STOP,
    HOOK_SUBAGENT_STOP,
    HOOK_NOTIFICATION,
    HOOK_PRE_COMPACT,
    HOOK_POST_COMPACT,
    HOOK_PRE_MODEL_INVOKE,
    HOOK_POST_MODEL_INVOKE,
    HOOK_ERROR,
)

log = logging.getLogger(__name__)

DEFAULT_SINK = Path.home() / "data" / "hooks-telemetry.jsonl"
DEFAULT_OFFSET_FILE = Path.home() / "data" / "hooks-telemetry.offset"
POLL_INTERVAL_S: float = 0.25

# Map JSONL ``event`` field → EventBus ``hook.*`` event type (E2.3).
# Keys match the lifecycle point names in agent/config/hooks/<Event>/
_EVENT_MAP: dict[str, str] = {
    "SessionStart": HOOK_SESSION_START,
    "SessionEnd": HOOK_SESSION_END,
    "UserPromptSubmit": HOOK_USER_PROMPT_SUBMIT,
    "PreToolUse": HOOK_PRE_TOOL_USE,
    "PostToolUse": HOOK_POST_TOOL_USE,
    "Stop": HOOK_STOP,
    "SubagentStop": HOOK_SUBAGENT_STOP,
    "Notification": HOOK_NOTIFICATION,
    "PreCompact": HOOK_PRE_COMPACT,
    "PostCompact": HOOK_POST_COMPACT,
    "PreModelInvoke": HOOK_PRE_MODEL_INVOKE,
    "PostModelInvoke": HOOK_POST_MODEL_INVOKE,
    "Error": HOOK_ERROR,
}


class HooksTelemetrySubscriber:
    """Async tail-and-publish loop for the hooks JSONL telemetry sink.

    Usage::

        subscriber = HooksTelemetrySubscriber(bus=EventBus.get_instance())
        await subscriber.start()
        # ... later, on shutdown:
        await subscriber.stop()

    The subscriber polls ``sink`` every ``POLL_INTERVAL_S`` seconds. New lines
    are parsed as JSONL, mapped to ``hook.*`` EventBus event types, and
    published. The byte offset is persisted in ``offset_file`` so restarts do
    not re-publish history.

    Robustness:
      - Sink truncation or rotation is detected (size < saved offset) and
        offset is reset to 0.
      - ``json.JSONDecodeError`` on individual lines is logged and skipped —
        a corrupt line never blocks the subscriber.
      - Unknown event names in the JSONL are silently dropped (forward-compat).
      - Any exception in the tail loop is logged and the loop resumes after
        ``POLL_INTERVAL_S`` seconds.
    """

    def __init__(
        self,
        *,
        bus: EventBus,
        sink: Path = DEFAULT_SINK,
        offset_file: Path = DEFAULT_OFFSET_FILE,
        poll_interval_s: float = POLL_INTERVAL_S,
    ) -> None:
        self._bus = bus
        self._sink = sink
        self._offset_file = offset_file
        self._poll_interval_s = poll_interval_s
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background polling task."""
        if self._task is not None and not self._task.done():
            return  # Already running.
        self._task = asyncio.create_task(self._run(), name="hooks_telemetry_subscriber")
        log.info("HooksTelemetrySubscriber started (sink=%s)", self._sink)

    async def stop(self) -> None:
        """Cancel the background polling task and wait for it to exit."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        log.info("HooksTelemetrySubscriber stopped")

    async def _run(self) -> None:
        offset = self._load_offset()
        while True:
            try:
                offset = await self._tail_once(offset)
            except Exception as exc:  # noqa: BLE001 — keep subscriber alive
                log.warning("HooksTelemetrySubscriber: tail error: %s", exc)
            await asyncio.sleep(self._poll_interval_s)

    async def _tail_once(self, offset: int) -> int:
        """Read new bytes from the sink and publish any new lines. Returns new offset."""
        if not self._sink.exists():
            return offset
        try:
            size = self._sink.stat().st_size
        except OSError:
            return offset
        if size < offset:
            # Sink was truncated or rotated.
            log.debug("HooksTelemetrySubscriber: sink rotated, resetting offset")
            offset = 0
        if size == offset:
            return offset  # No new data.
        with self._sink.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read()
        new_offset = offset + len(chunk)
        for raw in chunk.splitlines():
            self._publish_line(raw)
        self._save_offset(new_offset)
        return new_offset

    def _publish_line(self, raw: bytes) -> None:
        """Parse one JSONL line and publish the corresponding EventBus event."""
        try:
            obj: dict[str, Any] = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            log.debug("HooksTelemetrySubscriber: skipping invalid JSONL line")
            return
        cli_event = obj.get("event", "")
        event_type = _EVENT_MAP.get(cli_event)
        if event_type is None:
            return  # Unknown lifecycle point — forward-compat no-op.
        payload: dict[str, Any] = {
            "ts": obj.get("ts", ""),
            "session_id": obj.get("session_id", ""),
        }
        payload.update(obj.get("payload") or {})
        self._bus.publish(
            event_type=event_type,
            payload=payload,
            source="hooks_telemetry_subscriber",
        )

    def _load_offset(self) -> int:
        """Read the persisted byte offset. Returns 0 on any read/parse error."""
        try:
            text = self._offset_file.read_text().strip()
            return max(0, int(text))
        except (FileNotFoundError, ValueError, OSError):
            return 0

    def _save_offset(self, offset: int) -> None:
        """Persist the byte offset to disk. Silently ignores write errors."""
        try:
            self._offset_file.parent.mkdir(parents=True, exist_ok=True)
            self._offset_file.write_text(str(offset))
        except OSError:
            pass
