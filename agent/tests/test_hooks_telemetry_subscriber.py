"""Tests for E2.3 — HooksTelemetrySubscriber and hook.* EVENT_TYPES.

Sprint E2.3, issue #1240.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bridge.event_bus import (
    EVENT_TYPES,
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
from bridge.hooks_telemetry_subscriber import HooksTelemetrySubscriber, _EVENT_MAP


# All 13 expected hook.* event types.
EXPECTED_HOOK_TYPES = {
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
}


class TestEventBusHookTypes:
    """Verify the hook.* event types are registered in EVENT_TYPES."""

    def test_all_13_hook_types_in_event_types(self):
        registered = set(EVENT_TYPES)
        missing = EXPECTED_HOOK_TYPES - registered
        assert not missing, f"Missing hook.* event types in EVENT_TYPES: {missing}"

    def test_hook_type_constants_match_event_types(self):
        assert HOOK_SESSION_START in EVENT_TYPES
        assert HOOK_SESSION_END in EVENT_TYPES
        assert HOOK_USER_PROMPT_SUBMIT in EVENT_TYPES
        assert HOOK_PRE_TOOL_USE in EVENT_TYPES
        assert HOOK_POST_TOOL_USE in EVENT_TYPES
        assert HOOK_STOP in EVENT_TYPES
        assert HOOK_SUBAGENT_STOP in EVENT_TYPES
        assert HOOK_NOTIFICATION in EVENT_TYPES
        assert HOOK_PRE_COMPACT in EVENT_TYPES
        assert HOOK_POST_COMPACT in EVENT_TYPES
        assert HOOK_PRE_MODEL_INVOKE in EVENT_TYPES
        assert HOOK_POST_MODEL_INVOKE in EVENT_TYPES
        assert HOOK_ERROR in EVENT_TYPES

    def test_event_map_covers_all_13_lifecycle_points(self):
        cli_names = {
            "SessionStart", "SessionEnd", "UserPromptSubmit",
            "PreToolUse", "PostToolUse", "Stop", "SubagentStop",
            "Notification", "PreCompact", "PostCompact",
            "PreModelInvoke", "PostModelInvoke", "Error",
        }
        assert set(_EVENT_MAP.keys()) == cli_names

    def test_event_map_values_are_valid_event_types(self):
        registered = set(EVENT_TYPES)
        for cli_name, event_type in _EVENT_MAP.items():
            assert event_type in registered, (
                f"_EVENT_MAP[{cli_name!r}] = {event_type!r} not in EVENT_TYPES"
            )


class TestHooksTelemetrySubscriber:
    """Unit tests for the JSONL tail-and-publish loop."""

    def _make_subscriber(
        self,
        sink: Path,
        offset_file: Path,
    ) -> tuple[HooksTelemetrySubscriber, list]:
        bus = EventBus()
        published: list = []
        # EventBus has no wildcard subscribe — register once per hook type.
        for event_type in _EVENT_MAP.values():
            bus.subscribe(event_type, lambda e: published.append(e))
        subscriber = HooksTelemetrySubscriber(
            bus=bus,
            sink=sink,
            offset_file=offset_file,
            poll_interval_s=0.01,
        )
        return subscriber, published

    def _write_lines(self, sink: Path, lines: list[dict]) -> None:
        with sink.open("a") as f:
            for obj in lines:
                f.write(json.dumps(obj) + "\n")

    @pytest.mark.asyncio
    async def test_publishes_one_event_per_jsonl_line(self, tmp_path):
        sink = tmp_path / "telemetry.jsonl"
        offset_file = tmp_path / "offset"
        subscriber, published = self._make_subscriber(sink, offset_file)

        self._write_lines(sink, [
            {"ts": "2026-05-03T00:00:01Z", "event": "SessionStart", "session_id": "s1", "payload": {}},
            {"ts": "2026-05-03T00:00:02Z", "event": "PreToolUse", "session_id": "s1", "payload": {"tool": "Bash"}},
        ])

        await subscriber.start()
        await asyncio.sleep(0.05)
        await subscriber.stop()

        event_types = [e.event_type for e in published]
        assert "hook.session_start" in event_types
        assert "hook.pre_tool_use" in event_types

    @pytest.mark.asyncio
    async def test_offset_persists_across_restart(self, tmp_path):
        sink = tmp_path / "telemetry.jsonl"
        offset_file = tmp_path / "offset"
        subscriber, published = self._make_subscriber(sink, offset_file)

        self._write_lines(sink, [
            {"ts": "T1", "event": "Stop", "session_id": "s1", "payload": {}},
        ])

        await subscriber.start()
        await asyncio.sleep(0.05)
        await subscriber.stop()

        assert len(published) == 1

        # Second subscriber starts from saved offset; must not re-publish.
        subscriber2, published2 = self._make_subscriber(sink, offset_file)
        await subscriber2.start()
        await asyncio.sleep(0.05)
        await subscriber2.stop()

        assert len(published2) == 0

    @pytest.mark.asyncio
    async def test_sink_truncation_resets_offset(self, tmp_path):
        sink = tmp_path / "telemetry.jsonl"
        offset_file = tmp_path / "offset"

        # Write and consume first batch (2 lines so saved offset > new content).
        self._write_lines(sink, [
            {"ts": "T1", "event": "Stop", "session_id": "s1", "payload": {}},
            {"ts": "T1b", "event": "Stop", "session_id": "s1", "payload": {}},
        ])
        sub1, pub1 = self._make_subscriber(sink, offset_file)
        await sub1.start()
        await asyncio.sleep(0.05)
        await sub1.stop()
        assert len(pub1) == 2

        # Simulate truncation/rotation: clear the sink.
        sink.write_text("")
        self._write_lines(sink, [
            {"ts": "T2", "event": "SessionStart", "session_id": "s2", "payload": {}},
        ])

        sub2, pub2 = self._make_subscriber(sink, offset_file)
        await sub2.start()
        await asyncio.sleep(0.05)
        await sub2.stop()

        event_types = [e.event_type for e in pub2]
        assert "hook.session_start" in event_types

    @pytest.mark.asyncio
    async def test_unknown_event_name_silently_dropped(self, tmp_path):
        sink = tmp_path / "telemetry.jsonl"
        offset_file = tmp_path / "offset"
        subscriber, published = self._make_subscriber(sink, offset_file)

        self._write_lines(sink, [
            {"ts": "T1", "event": "Garbage", "session_id": "s1", "payload": {}},
            {"ts": "T2", "event": "SessionStart", "session_id": "s1", "payload": {}},
        ])

        await subscriber.start()
        await asyncio.sleep(0.05)
        await subscriber.stop()

        event_types = [e.event_type for e in published]
        assert "hook.session_start" in event_types
        # Garbage should not appear in any form.
        assert all("garbage" not in t.lower() for t in event_types)
        assert len(event_types) == 1  # only the valid line published

    @pytest.mark.asyncio
    async def test_invalid_json_line_silently_skipped(self, tmp_path):
        sink = tmp_path / "telemetry.jsonl"
        offset_file = tmp_path / "offset"
        subscriber, published = self._make_subscriber(sink, offset_file)

        with sink.open("w") as f:
            f.write("{invalid json}\n")
            f.write(json.dumps({"ts": "T", "event": "Stop", "session_id": "s", "payload": {}}) + "\n")

        await subscriber.start()
        await asyncio.sleep(0.05)
        await subscriber.stop()

        assert len(published) == 1
        assert published[0].event_type == "hook.stop"

    @pytest.mark.asyncio
    async def test_nonexistent_sink_does_not_error(self, tmp_path):
        sink = tmp_path / "nonexistent.jsonl"
        offset_file = tmp_path / "offset"
        subscriber, published = self._make_subscriber(sink, offset_file)

        await subscriber.start()
        await asyncio.sleep(0.05)
        await subscriber.stop()

        assert published == []

    @pytest.mark.asyncio
    async def test_payload_forwarded_to_event(self, tmp_path):
        sink = tmp_path / "telemetry.jsonl"
        offset_file = tmp_path / "offset"
        subscriber, published = self._make_subscriber(sink, offset_file)

        self._write_lines(sink, [
            {"ts": "T", "event": "PreToolUse", "session_id": "sid1", "payload": {"tool": "Edit"}},
        ])

        await subscriber.start()
        await asyncio.sleep(0.05)
        await subscriber.stop()

        assert len(published) == 1
        assert published[0].payload["tool"] == "Edit"
        assert published[0].payload["session_id"] == "sid1"
        assert published[0].source == "hooks_telemetry_subscriber"
