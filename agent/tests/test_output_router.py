"""Tests for agent.bridge.output_router.

Sprint 4.8 — Phase 4B (Dialogue-First Communication Architecture).
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bridge.output_router import (
    AUTONOMOUS_ROUTING,
    SUPERVISED_ROUTING,
    DiscordDestination,
    DiskLogDestination,
    OutputChannel,
    OutputChunk,
    OutputDestinationName,
    OutputRouter,
    RoutingTable,
    TerminalDestination,
    classify_chunk,
    routing_for_mode,
)


# ---------------------------------------------------------------------------
# Classifier — tool-lifecycle events always route to TRACE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chunk_type", ["tool_start", "tool_result", "tool_error"])
def test_tool_lifecycle_events_are_classified_as_trace(chunk_type):
    chunk = OutputChunk(type=chunk_type, content="editing file X")
    assert classify_chunk(chunk) == OutputChannel.TRACE


def test_tool_event_with_milestone_looking_content_still_trace():
    # Tool events must not be reclassified by content; trace wins
    chunk = OutputChunk(type="tool_result", content="# Finished sprint 08-03")
    assert classify_chunk(chunk) == OutputChannel.TRACE


# ---------------------------------------------------------------------------
# Classifier — assistant text falls into DIALOGUE or MILESTONE
# ---------------------------------------------------------------------------


def test_plain_assistant_text_is_dialogue():
    chunk = OutputChunk(
        type="assistant_text",
        content="Here's how that function works: it takes a list and returns the sum.",
    )
    assert classify_chunk(chunk) == OutputChannel.DIALOGUE


def test_question_is_dialogue():
    chunk = OutputChunk(
        type="assistant_text",
        content="Which option would you prefer — A or B?",
    )
    assert classify_chunk(chunk) == OutputChannel.DIALOGUE


def test_explicit_milestone_tag_is_milestone():
    chunk = OutputChunk(
        type="assistant_text",
        content="[MILESTONE] Finished writing the router module.",
    )
    assert classify_chunk(chunk) == OutputChannel.MILESTONE


def test_finished_heading_is_milestone():
    chunk = OutputChunk(
        type="assistant_text",
        content="## Finished Sprint 4.1\n\nProtection enabled on 3 repos.",
    )
    assert classify_chunk(chunk) == OutputChannel.MILESTONE


def test_sprint_complete_bold_is_milestone():
    chunk = OutputChunk(
        type="assistant_text",
        content="**Sprint 4.1 complete** — code shipped.",
    )
    assert classify_chunk(chunk) == OutputChannel.MILESTONE


def test_pr_opened_phrase_is_milestone():
    chunk = OutputChunk(
        type="assistant_text",
        content="All done. PR #232 opened for review.",
    )
    assert classify_chunk(chunk) == OutputChannel.MILESTONE


def test_checkmark_sprint_is_milestone():
    chunk = OutputChunk(
        type="assistant_text",
        content="✅ Sprint 4.8 done. Moving on.",
    )
    assert classify_chunk(chunk) == OutputChannel.MILESTONE


def test_case_insensitive_milestone_detection():
    chunk = OutputChunk(
        type="assistant_text",
        content="# finished THE work",
    )
    assert classify_chunk(chunk) == OutputChannel.MILESTONE


def test_empty_assistant_text_is_dialogue():
    # Empty content with no markers — default to dialogue (safest)
    chunk = OutputChunk(type="assistant_text", content="")
    assert classify_chunk(chunk) == OutputChannel.DIALOGUE


def test_unknown_chunk_type_defaults_to_dialogue():
    # Safest default — never silently hide output
    chunk = OutputChunk(type="weird_new_type", content="surprise")
    assert classify_chunk(chunk) == OutputChannel.DIALOGUE


def test_multiline_dialogue_with_milestone_in_middle_is_milestone():
    content = "I did a bunch of things.\n\n## Finished all tasks\n\nMore detail follows."
    chunk = OutputChunk(type="assistant_text", content=content)
    assert classify_chunk(chunk) == OutputChannel.MILESTONE


# ---------------------------------------------------------------------------
# Routing tables
# ---------------------------------------------------------------------------


def test_autonomous_routing_sends_trace_only_to_disk():
    dests = AUTONOMOUS_ROUTING.destinations_for(OutputChannel.TRACE)
    assert dests == (OutputDestinationName.DISK_LOG,)
    assert OutputDestinationName.TERMINAL not in dests
    assert OutputDestinationName.DISCORD not in dests


def test_autonomous_routing_sends_dialogue_to_both_operator_channels():
    dests = AUTONOMOUS_ROUTING.destinations_for(OutputChannel.DIALOGUE)
    assert OutputDestinationName.TERMINAL in dests
    assert OutputDestinationName.DISCORD in dests


def test_autonomous_routing_sends_milestone_to_both_operator_channels():
    dests = AUTONOMOUS_ROUTING.destinations_for(OutputChannel.MILESTONE)
    assert OutputDestinationName.TERMINAL in dests
    assert OutputDestinationName.DISCORD in dests


def test_supervised_routing_sends_trace_to_terminal():
    dests = SUPERVISED_ROUTING.destinations_for(OutputChannel.TRACE)
    assert dests == (OutputDestinationName.TERMINAL,)


def test_routing_for_mode_autonomous():
    assert routing_for_mode("autonomous") is AUTONOMOUS_ROUTING


def test_routing_for_mode_supervised():
    assert routing_for_mode("supervised") is SUPERVISED_ROUTING


def test_routing_for_mode_unknown_falls_back_to_autonomous():
    # Unknown mode must fall back to the safer option (autonomous)
    # so we never accidentally leak trace to operator channels.
    assert routing_for_mode("chaotic") is AUTONOMOUS_ROUTING
    assert routing_for_mode("") is AUTONOMOUS_ROUTING


# ---------------------------------------------------------------------------
# Destinations — terminal
# ---------------------------------------------------------------------------


def test_terminal_destination_writes_content_to_stream():
    buf = io.StringIO()
    dest = TerminalDestination(stream=buf)
    chunk = OutputChunk(type="assistant_text", content="hello operator")
    dest.write(chunk)
    assert "hello operator" in buf.getvalue()


def test_terminal_destination_appends_newline_if_missing():
    buf = io.StringIO()
    dest = TerminalDestination(stream=buf)
    dest.write(OutputChunk(type="assistant_text", content="no trailing newline"))
    assert buf.getvalue().endswith("\n")


def test_terminal_destination_does_not_double_newline():
    buf = io.StringIO()
    dest = TerminalDestination(stream=buf)
    dest.write(OutputChunk(type="assistant_text", content="has newline\n"))
    assert buf.getvalue() == "has newline\n"


# ---------------------------------------------------------------------------
# Destinations — discord
# ---------------------------------------------------------------------------


def test_discord_destination_calls_sink_when_configured():
    sink = MagicMock()
    dest = DiscordDestination(sink=sink)
    chunk = OutputChunk(type="assistant_text", content="send me")
    dest.write(chunk)
    sink.assert_called_once_with(chunk)


def test_discord_destination_buffers_when_no_sink():
    dest = DiscordDestination()
    chunk = OutputChunk(type="assistant_text", content="pending")
    dest.write(chunk)
    assert len(dest.buffered_chunks) == 1
    assert dest.buffered_chunks[0] is chunk


def test_discord_destination_swallows_sink_exceptions():
    def failing_sink(chunk):
        raise RuntimeError("discord down")

    dest = DiscordDestination(sink=failing_sink)
    # Must not raise
    dest.write(OutputChunk(type="assistant_text", content="will fail silently"))


# ---------------------------------------------------------------------------
# Destinations — disk log
# ---------------------------------------------------------------------------


def test_disk_log_destination_writes_jsonl(tmp_path: Path):
    dest = DiskLogDestination(root=tmp_path)
    chunk = OutputChunk(
        type="tool_result",
        content="edit completed",
        session_id="sess_abc",
        metadata={"tool": "Edit", "file": "x.py"},
    )
    dest.write(chunk)

    expected_path = tmp_path / "sess_abc.jsonl"
    assert expected_path.exists()
    line = expected_path.read_text().strip()
    parsed = json.loads(line)
    assert parsed["type"] == "tool_result"
    assert parsed["content"] == "edit completed"
    assert parsed["session_id"] == "sess_abc"
    assert parsed["metadata"]["tool"] == "Edit"


def test_disk_log_destination_appends_multiple_chunks(tmp_path: Path):
    dest = DiskLogDestination(root=tmp_path)
    for i in range(3):
        dest.write(
            OutputChunk(type="tool_start", content=f"step {i}", session_id="sess_multi")
        )

    path = tmp_path / "sess_multi.jsonl"
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 3
    assert all("step" in line for line in lines)


def test_disk_log_destination_handles_path_traversal_attempts(tmp_path: Path):
    dest = DiskLogDestination(root=tmp_path)
    # Pathological session_id — must be sanitized
    chunk = OutputChunk(
        type="tool_start",
        content="sneaky",
        session_id="../../etc/passwd",
    )
    dest.write(chunk)

    # The file should be inside tmp_path, not anywhere outside
    written_files = list(tmp_path.rglob("*.jsonl"))
    assert len(written_files) == 1
    assert str(written_files[0]).startswith(str(tmp_path))


def test_disk_log_destination_defaults_session_id_to_no_session(tmp_path: Path):
    dest = DiskLogDestination(root=tmp_path)
    dest.write(OutputChunk(type="tool_start", content="anon"))
    assert (tmp_path / "no_session.jsonl").exists()


# ---------------------------------------------------------------------------
# Router end-to-end
# ---------------------------------------------------------------------------


def _build_router(routing: RoutingTable, disk_root: Path) -> tuple[OutputRouter, dict]:
    terminal_buf = io.StringIO()
    discord_sink = MagicMock()
    destinations = {
        OutputDestinationName.TERMINAL: TerminalDestination(stream=terminal_buf),
        OutputDestinationName.DISCORD: DiscordDestination(sink=discord_sink),
        OutputDestinationName.DISK_LOG: DiskLogDestination(root=disk_root),
    }
    router = OutputRouter(routing=routing, destinations=destinations)
    return router, {
        "terminal": terminal_buf,
        "discord": discord_sink,
        "disk_root": disk_root,
    }


def test_router_in_autonomous_mode_hides_trace_from_operator_channels(tmp_path: Path):
    router, probes = _build_router(AUTONOMOUS_ROUTING, tmp_path)

    trace_chunk = OutputChunk(
        type="tool_start",
        content="invoking grep",
        session_id="autonomous_test",
        metadata={"tool": "Grep"},
    )
    channel = router.dispatch(trace_chunk)
    assert channel == OutputChannel.TRACE

    # Terminal buffer must NOT contain the trace content
    assert "invoking grep" not in probes["terminal"].getvalue()
    # Discord sink must NOT have been called
    probes["discord"].assert_not_called()
    # Disk log MUST contain it
    log_path = tmp_path / "autonomous_test.jsonl"
    assert log_path.exists()
    assert "invoking grep" in log_path.read_text()


def test_router_in_autonomous_mode_routes_dialogue_to_both_operator_channels(tmp_path: Path):
    router, probes = _build_router(AUTONOMOUS_ROUTING, tmp_path)

    dialogue_chunk = OutputChunk(
        type="assistant_text",
        content="How can I help?",
        session_id="autonomous_test",
    )
    channel = router.dispatch(dialogue_chunk)
    assert channel == OutputChannel.DIALOGUE
    assert "How can I help?" in probes["terminal"].getvalue()
    assert probes["discord"].call_count == 1
    # Disk log must NOT have the dialogue (dialogue doesn't route to disk)
    assert not (tmp_path / "autonomous_test.jsonl").exists()


def test_router_in_autonomous_mode_routes_milestone_to_both_operator_channels(tmp_path: Path):
    router, probes = _build_router(AUTONOMOUS_ROUTING, tmp_path)
    milestone_chunk = OutputChunk(
        type="assistant_text",
        content="[MILESTONE] Sprint 4.8 shipped.",
        session_id="ms_test",
    )
    channel = router.dispatch(milestone_chunk)
    assert channel == OutputChannel.MILESTONE
    assert "MILESTONE" in probes["terminal"].getvalue()
    assert probes["discord"].call_count == 1


def test_router_in_supervised_mode_shows_trace_in_terminal(tmp_path: Path):
    router, probes = _build_router(SUPERVISED_ROUTING, tmp_path)
    trace_chunk = OutputChunk(
        type="tool_result",
        content="subprocess exited 0",
        session_id="sup_test",
    )
    router.dispatch(trace_chunk)
    assert "subprocess exited 0" in probes["terminal"].getvalue()
    # Disk log should NOT be written in supervised mode for trace
    assert not (tmp_path / "sup_test.jsonl").exists()


def test_router_tracks_dispatch_count(tmp_path: Path):
    router, _ = _build_router(AUTONOMOUS_ROUTING, tmp_path)
    for i in range(5):
        router.dispatch(
            OutputChunk(type="assistant_text", content=f"msg {i}", session_id="count")
        )
    assert router.dispatch_count == 5


def test_router_skips_missing_destinations_gracefully(tmp_path: Path):
    # Router with only TERMINAL registered, but routing table also mentions DISCORD
    terminal_stream = io.StringIO()
    router = OutputRouter(
        routing=AUTONOMOUS_ROUTING,
        destinations={OutputDestinationName.TERMINAL: TerminalDestination(stream=terminal_stream)},
    )
    # This should not raise, just log a warning and skip the missing Discord dest
    router.dispatch(OutputChunk(type="assistant_text", content="hi", session_id="s"))
    # The registered destination still received the chunk (the missing
    # one was skipped, not the whole dispatch).
    assert "hi" in terminal_stream.getvalue()
    assert router.dispatch_count == 1


def test_router_register_destination_attaches_after_construction(tmp_path: Path):
    router = OutputRouter(
        routing=AUTONOMOUS_ROUTING,
        destinations={OutputDestinationName.TERMINAL: TerminalDestination(stream=io.StringIO())},
    )
    discord_sink = MagicMock()
    router.register_destination(
        OutputDestinationName.DISCORD,
        DiscordDestination(sink=discord_sink),
    )
    router.dispatch(OutputChunk(type="assistant_text", content="after attach", session_id="s"))
    assert discord_sink.called
