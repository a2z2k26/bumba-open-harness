"""Tests for agent.bridge.tool_trace_reader.

Sprint 4.14 — Phase 4B (Dialogue-First Communication Architecture).

The reader is the backend for the operator-invoked tool-trace firehose
command. It reads the JSONL trace log written by Sprint 4.8's
DiskLogDestination and returns a human-readable summary suitable for
posting back to the dialogue channel. Fully pure — no session-state
coupling, no command-handler coupling, no I/O except reading the log.
"""
from __future__ import annotations

import json
from pathlib import Path


from bridge.tool_trace_reader import (
    DEFAULT_TRACE_COUNT,
    TraceEntry,
    format_trace_entries_for_dialogue,
    parse_trace_count_argument,
    read_recent_trace_entries,
)


# ---------------------------------------------------------------------------
# Helpers — build a synthetic trace log that matches OutputChunk.to_dict()
# ---------------------------------------------------------------------------


def _chunk_dict(
    type_: str,
    content: str,
    session_id: str = "session_abc",
    metadata: dict | None = None,
) -> dict:
    return {
        "type": type_,
        "content": content,
        "session_id": session_id,
        "metadata": metadata or {},
    }


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry))
            f.write("\n")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_trace_count_is_twenty():
    """The spec calls for default N=20 when the operator doesn't pass one."""
    assert DEFAULT_TRACE_COUNT == 20


# ---------------------------------------------------------------------------
# parse_trace_count_argument
# ---------------------------------------------------------------------------


def test_parse_trace_count_empty_returns_default():
    assert parse_trace_count_argument("") == DEFAULT_TRACE_COUNT


def test_parse_trace_count_whitespace_returns_default():
    assert parse_trace_count_argument("   ") == DEFAULT_TRACE_COUNT


def test_parse_trace_count_valid_integer():
    assert parse_trace_count_argument("5") == 5
    assert parse_trace_count_argument("100") == 100


def test_parse_trace_count_with_surrounding_whitespace():
    assert parse_trace_count_argument("  42 ") == 42


def test_parse_trace_count_rejects_negative():
    """Negative counts make no sense and should fall back to default."""
    assert parse_trace_count_argument("-5") == DEFAULT_TRACE_COUNT


def test_parse_trace_count_rejects_zero():
    """Zero is a degenerate case — the operator probably meant 'default'."""
    assert parse_trace_count_argument("0") == DEFAULT_TRACE_COUNT


def test_parse_trace_count_rejects_non_integer():
    assert parse_trace_count_argument("abc") == DEFAULT_TRACE_COUNT
    assert parse_trace_count_argument("1.5") == DEFAULT_TRACE_COUNT


def test_parse_trace_count_caps_at_maximum():
    """Defensive guard — a giant N would post a huge Discord message."""
    result = parse_trace_count_argument("1000000")
    assert result <= 500  # generous cap; actual value tested implicitly


# ---------------------------------------------------------------------------
# read_recent_trace_entries — file-level behavior
# ---------------------------------------------------------------------------


def test_read_missing_file_returns_empty_list(tmp_path: Path):
    """A missing trace log means 'no trace data yet' — not an error.

    This is the common case before the Phase 4B wiring sprint lands:
    the log file won't exist until the output router is active in the
    live subprocess lifecycle.
    """
    result = read_recent_trace_entries(tmp_path / "missing.jsonl", n=10)
    assert result == []


def test_read_empty_file_returns_empty_list(tmp_path: Path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    assert read_recent_trace_entries(path, n=10) == []


def test_read_returns_last_n_entries_in_chronological_order(tmp_path: Path):
    """If the log has 10 entries and N=3, the reader returns the last
    three in the same order they were written (oldest-of-three first).
    """
    path = tmp_path / "session_abc.jsonl"
    _write_jsonl(
        path,
        [
            _chunk_dict("tool_start", f"entry {i}", metadata={"seq": i})
            for i in range(10)
        ],
    )
    result = read_recent_trace_entries(path, n=3)
    assert len(result) == 3
    assert [e.content for e in result] == ["entry 7", "entry 8", "entry 9"]


def test_read_n_greater_than_file_length_returns_all(tmp_path: Path):
    path = tmp_path / "session_abc.jsonl"
    _write_jsonl(path, [_chunk_dict("tool_start", f"entry {i}") for i in range(3)])
    result = read_recent_trace_entries(path, n=100)
    assert len(result) == 3


def test_read_skips_malformed_jsonl_lines(tmp_path: Path):
    """Malformed lines (half-written, corrupted) must not crash the
    reader. Skip with a debug log; return whatever valid entries exist.
    """
    path = tmp_path / "corrupted.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(_chunk_dict("tool_start", "first")) + "\n")
        f.write("this is not json\n")
        f.write(json.dumps(_chunk_dict("tool_start", "third")) + "\n")
        f.write("{incomplete\n")
        f.write(json.dumps(_chunk_dict("tool_start", "fifth")) + "\n")

    result = read_recent_trace_entries(path, n=10)
    assert [e.content for e in result] == ["first", "third", "fifth"]


def test_read_skips_non_dict_json_lines(tmp_path: Path):
    """A JSON line that parses to a list or a bare value, not a dict,
    must be skipped. The reader expects chunk dicts.
    """
    path = tmp_path / "weird.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(_chunk_dict("tool_start", "valid")) + "\n")
        f.write(json.dumps([1, 2, 3]) + "\n")
        f.write(json.dumps("just a string") + "\n")
        f.write(json.dumps({"type": "tool_result", "content": "also valid"}) + "\n")

    result = read_recent_trace_entries(path, n=10)
    assert len(result) == 2
    assert result[0].content == "valid"
    assert result[1].content == "also valid"


# ---------------------------------------------------------------------------
# TraceEntry — parsed structure
# ---------------------------------------------------------------------------


def test_trace_entry_parses_tool_start(tmp_path: Path):
    path = tmp_path / "t.jsonl"
    _write_jsonl(
        path,
        [
            _chunk_dict(
                "tool_start",
                "editing file X",
                metadata={"tool_name": "Edit", "tool_args": {"file": "X"}},
            )
        ],
    )
    [entry] = read_recent_trace_entries(path, n=10)
    assert isinstance(entry, TraceEntry)
    assert entry.type == "tool_start"
    assert entry.tool_name == "Edit"


def test_trace_entry_parses_tool_result_with_duration(tmp_path: Path):
    path = tmp_path / "t.jsonl"
    _write_jsonl(
        path,
        [
            _chunk_dict(
                "tool_result",
                "ok",
                metadata={
                    "tool_name": "Bash",
                    "duration_ms": 1234,
                    "exit_code": 0,
                },
            )
        ],
    )
    [entry] = read_recent_trace_entries(path, n=10)
    assert entry.type == "tool_result"
    assert entry.tool_name == "Bash"
    assert entry.duration_ms == 1234
    assert entry.exit_code == 0


def test_trace_entry_parses_tool_error(tmp_path: Path):
    path = tmp_path / "t.jsonl"
    _write_jsonl(
        path,
        [
            _chunk_dict(
                "tool_error",
                "command failed",
                metadata={"tool_name": "Bash", "exit_code": 1},
            )
        ],
    )
    [entry] = read_recent_trace_entries(path, n=10)
    assert entry.type == "tool_error"
    assert entry.exit_code == 1


def test_trace_entry_missing_metadata_fields_uses_none(tmp_path: Path):
    """If the chunk has no tool_name / duration / exit_code, the parsed
    entry reflects that with None rather than raising KeyError.
    """
    path = tmp_path / "t.jsonl"
    _write_jsonl(path, [_chunk_dict("tool_start", "bare")])
    [entry] = read_recent_trace_entries(path, n=10)
    assert entry.tool_name is None
    assert entry.duration_ms is None
    assert entry.exit_code is None


# ---------------------------------------------------------------------------
# format_trace_entries_for_dialogue — human-readable output
# ---------------------------------------------------------------------------


def test_format_empty_list_returns_informative_message():
    result = format_trace_entries_for_dialogue([])
    assert "no" in result.lower() or "empty" in result.lower()
    # Must not be raw JSON or an empty string
    assert result.strip()
    assert not result.startswith("[")


def test_format_single_tool_result_is_human_readable():
    entries = [
        TraceEntry(
            type="tool_result",
            content="ok",
            tool_name="Bash",
            duration_ms=1234,
            exit_code=0,
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    # Human cues, not raw JSON
    assert "Bash" in output
    assert "1234" in output or "1.2" in output or "1.23" in output
    assert "{" not in output  # no JSON blobs


def test_format_tool_error_is_visually_distinct():
    """Errors should be easy to spot in the firehose output."""
    entries = [
        TraceEntry(
            type="tool_error",
            content="command failed",
            tool_name="Bash",
            exit_code=1,
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    # Some visual indicator of error (emoji, "ERROR", "FAIL", etc.)
    lower = output.lower()
    assert any(marker in lower for marker in ("error", "fail", "✗", "x"))


def test_format_collapses_long_tool_arg_blobs():
    """Tool arg blobs can be huge (file contents, full bash scripts).
    The formatter must collapse them so the output is scannable.
    """
    huge_content = "x" * 5000
    entries = [
        TraceEntry(
            type="tool_start",
            content=huge_content,
            tool_name="Write",
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    # The huge blob must not appear in full
    assert huge_content not in output
    # But the tool name must still be visible
    assert "Write" in output


def test_format_multiple_entries_each_on_own_line():
    entries = [
        TraceEntry(type="tool_start", content="a", tool_name="Read"),
        TraceEntry(type="tool_result", content="b", tool_name="Read", duration_ms=50),
        TraceEntry(type="tool_start", content="c", tool_name="Edit"),
    ]
    output = format_trace_entries_for_dialogue(entries)
    # Three entries → three lines (or more; some formats add headers)
    assert output.count("\n") >= 2
    assert "Read" in output
    assert "Edit" in output


def test_format_includes_event_type_indicator():
    """The formatter should visually distinguish tool_start from
    tool_result from tool_error so the operator can see the flow.
    """
    entries = [
        TraceEntry(type="tool_start", content="a", tool_name="Read"),
        TraceEntry(type="tool_result", content="b", tool_name="Read"),
    ]
    output = format_trace_entries_for_dialogue(entries)
    # Two distinct visual markers
    lines = [line for line in output.split("\n") if "Read" in line]
    assert len(lines) == 2
    # The two lines should not be identical
    assert lines[0] != lines[1]


# ---------------------------------------------------------------------------
# Sprint 4.14 code review HIGH #1 — OSError on read
# ---------------------------------------------------------------------------


def test_read_handles_os_error_returns_empty_list(tmp_path: Path, monkeypatch):
    """A permission denied / I/O error on open must return [] not raise."""
    path = tmp_path / "locked.jsonl"
    path.write_text(json.dumps(_chunk_dict("tool_start", "x")) + "\n")

    original_open = Path.open

    def raise_on_open(self, *args, **kwargs):
        if self == path:
            raise PermissionError("simulated permission denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", raise_on_open)
    result = read_recent_trace_entries(path, n=10)
    assert result == []


# ---------------------------------------------------------------------------
# Sprint 4.14 code review — edge-case parsing
# ---------------------------------------------------------------------------


def test_read_handles_non_dict_metadata_field(tmp_path: Path):
    """A chunk whose metadata field is a list or string instead of a
    dict should not crash the reader — metadata fields fall back to
    None.
    """
    path = tmp_path / "weird_meta.jsonl"
    with path.open("w", encoding="utf-8") as f:
        # metadata as a list
        f.write(
            json.dumps(
                {"type": "tool_start", "content": "a", "metadata": [1, 2, 3]}
            )
            + "\n"
        )
        # metadata as a string
        f.write(
            json.dumps(
                {"type": "tool_start", "content": "b", "metadata": "oops"}
            )
            + "\n"
        )
        # metadata missing entirely
        f.write(json.dumps({"type": "tool_start", "content": "c"}) + "\n")

    result = read_recent_trace_entries(path, n=10)
    assert len(result) == 3
    for entry in result:
        assert entry.tool_name is None
        assert entry.duration_ms is None
        assert entry.exit_code is None


def test_read_handles_non_string_type_field(tmp_path: Path):
    """A chunk whose type field is not a string (e.g. number, null)
    should still parse — the reader coerces via str().
    """
    path = tmp_path / "weird_type.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"type": 42, "content": "a"}) + "\n")
        f.write(json.dumps({"type": None, "content": "b"}) + "\n")
    result = read_recent_trace_entries(path, n=10)
    assert len(result) == 2
    assert result[0].type == "42"
    assert result[1].type == "None"


# ---------------------------------------------------------------------------
# Sprint 4.14 code review HIGH #2 — secret leak prevention
# ---------------------------------------------------------------------------


def test_format_tool_start_shows_size_not_content():
    """tool_start content (which can be full bash scripts, file writes,
    or env exports) must NEVER appear in the dialogue channel — only
    the tool name and arg size. This is a load-bearing defense against
    re-surfacing the exact risk Sprint 4.8 mitigated by sending trace
    output to disk only.
    """
    secret_bash = "export STRIPE_API_KEY=sk_live_very_secret_token"
    entries = [
        TraceEntry(
            type="tool_start",
            content=secret_bash,
            tool_name="Bash",
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    # The secret must not appear in any form
    assert "sk_live" not in output
    assert "STRIPE" not in output
    assert secret_bash not in output
    # But the tool name and size hint must still be visible
    assert "Bash" in output
    assert str(len(secret_bash)) in output  # size shown
    assert "chars" in output


def test_format_tool_start_with_empty_content_has_no_size():
    entries = [TraceEntry(type="tool_start", content="", tool_name="Read")]
    output = format_trace_entries_for_dialogue(entries)
    assert "Read" in output
    assert "0 chars" not in output  # empty content → omit size entirely


def test_format_redacts_sk_live_in_tool_result_content():
    entries = [
        TraceEntry(
            type="tool_result",
            content="got response: sk_live_abcdef123456 ok",
            tool_name="Bash",
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    assert "sk_live_abcdef123456" not in output
    assert "[REDACTED]" in output


def test_format_redacts_bearer_token_in_tool_result():
    entries = [
        TraceEntry(
            type="tool_result",
            content="Bearer eyJhbGciOi_a_long_jwt_here",
            tool_name="WebFetch",
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    assert "eyJhbGciOi" not in output
    assert "[REDACTED]" in output


def test_format_redacts_password_assignment():
    entries = [
        TraceEntry(
            type="tool_result",
            content="password=hunter2 was used",
            tool_name="Bash",
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    assert "hunter2" not in output
    assert "[REDACTED]" in output


def test_format_redacts_ghp_github_token():
    entries = [
        TraceEntry(
            type="tool_result",
            content="token: ghp_ABCDEF1234567890",
            tool_name="Bash",
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    assert "ghp_ABCDEF" not in output


def test_format_redacts_aws_access_key_id():
    entries = [
        TraceEntry(
            type="tool_result",
            content="AKIAIOSFODNN7EXAMPLE credentials",
            tool_name="Bash",
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    assert "AKIAIOSFODNN7EXAMPLE" not in output


def test_format_tool_result_preserves_non_secret_content():
    """Regression guard: the redactor must not eat legitimate output.
    Ordinary tool results should pass through unchanged.
    """
    entries = [
        TraceEntry(
            type="tool_result",
            content="Read 42 files in 128ms",
            tool_name="Glob",
        ),
    ]
    output = format_trace_entries_for_dialogue(entries)
    assert "42 files" in output
    assert "128ms" in output
    assert "[REDACTED]" not in output


# ---------------------------------------------------------------------------
# Sprint 4.14 code review — memory discipline
# ---------------------------------------------------------------------------


def test_read_bounded_memory_on_large_file(tmp_path: Path):
    """Regression guard (Sprint 4.14 code review HIGH #1): the reader
    must not slurp the entire file into memory. Write a file with
    many entries and ask for the last 5; the result must have 5
    entries and the reader should not have loaded all 10000 into a
    single list.

    We can't easily measure memory directly in a unit test, but we
    can at least verify the correctness of the bounded read (the
    result is 5 entries, in the right order) which is the observable
    behavior the deque-based implementation enables.
    """
    path = tmp_path / "huge.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for i in range(10000):
            f.write(json.dumps(_chunk_dict("tool_start", f"entry {i}")) + "\n")

    result = read_recent_trace_entries(path, n=5)
    assert len(result) == 5
    # The deque preserves order, so the last 5 should be entries 9995-9999
    assert [e.content for e in result] == [f"entry {i}" for i in range(9995, 10000)]
