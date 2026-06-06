"""Tests for bridge.memory_writes — D2.3 MemoryWriteReceipt + emit + tail.

Sprint D2.3 (#1188): uniform write-receipt log for all silent memory stores.
"""
from __future__ import annotations

import json
import stat



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_receipt(**kwargs):
    from bridge.memory_writes import MemoryWriteReceipt
    defaults = dict(
        subsystem="knowledge",
        op="insert",
        key="test:key",
        payload_bytes=42,
        actor="agent",
        notes="",
    )
    defaults.update(kwargs)
    return MemoryWriteReceipt.now(**defaults)


# ---------------------------------------------------------------------------
# MemoryWriteReceipt.now — construction
# ---------------------------------------------------------------------------

class TestMemoryWriteReceipt:
    def test_now_sets_timestamp_utc(self):
        from bridge.memory_writes import MemoryWriteReceipt
        r = MemoryWriteReceipt.now(subsystem="knowledge", op="insert",
                                   key="k", payload_bytes=10)
        assert r.timestamp.endswith("+00:00"), f"expected UTC, got {r.timestamp}"

    def test_key_truncated_at_120(self):
        from bridge.memory_writes import MemoryWriteReceipt
        long_key = "x" * 200
        r = MemoryWriteReceipt.now(subsystem="knowledge", op="insert",
                                   key=long_key, payload_bytes=0)
        assert len(r.key) == 120

    def test_notes_truncated_at_200(self):
        from bridge.memory_writes import MemoryWriteReceipt
        r = MemoryWriteReceipt.now(subsystem="knowledge", op="insert",
                                   key="k", payload_bytes=0,
                                   notes="n" * 300)
        assert len(r.notes) == 200

    def test_bytes_coerced_to_int(self):
        from bridge.memory_writes import MemoryWriteReceipt
        r = MemoryWriteReceipt.now(subsystem="knowledge", op="insert",
                                   key="k", payload_bytes=3.7)
        assert isinstance(r.bytes, int)


# ---------------------------------------------------------------------------
# emit — append behaviour
# ---------------------------------------------------------------------------

class TestEmit:
    def test_emit_writes_single_terminated_jsonl_line(self, tmp_path):
        from bridge.memory_writes import emit
        path = tmp_path / "writes.jsonl"
        r = _make_receipt()
        emit(r, path=path)
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["subsystem"] == "knowledge"
        assert parsed["op"] == "insert"

    def test_emit_multiple_appends_multiple_lines(self, tmp_path):
        from bridge.memory_writes import emit
        path = tmp_path / "writes.jsonl"
        for i in range(3):
            emit(_make_receipt(key=f"k{i}"), path=path)
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_emit_creates_parent_dirs(self, tmp_path):
        from bridge.memory_writes import emit
        path = tmp_path / "sub" / "dir" / "writes.jsonl"
        emit(_make_receipt(), path=path)
        assert path.exists()

    def test_emit_failsoft_never_raises(self, tmp_path):
        """emit() on an unwritable path must not propagate exceptions."""
        from bridge.memory_writes import emit
        path = tmp_path / "ro.jsonl"
        path.write_text("")
        path.chmod(stat.S_IREAD)  # read-only
        try:
            emit(_make_receipt(), path=path)  # must not raise
        finally:
            path.chmod(stat.S_IREAD | stat.S_IWRITE)  # restore for cleanup

    def test_emit_line_is_valid_json(self, tmp_path):
        from bridge.memory_writes import emit
        path = tmp_path / "writes.jsonl"
        emit(_make_receipt(notes="hello world"), path=path)
        d = json.loads(path.read_text().strip())
        assert "timestamp" in d
        assert "bytes" in d


# ---------------------------------------------------------------------------
# tail — read behaviour
# ---------------------------------------------------------------------------

class TestTail:
    def test_tail_empty_file_returns_empty(self, tmp_path):
        from bridge.memory_writes import tail
        path = tmp_path / "nope.jsonl"
        assert tail(20, path=path) == []

    def test_tail_returns_newest_first(self, tmp_path):
        from bridge.memory_writes import emit, tail
        path = tmp_path / "writes.jsonl"
        for i in range(5):
            emit(_make_receipt(key=f"k{i}"), path=path)
        result = tail(5, path=path)
        assert [r.key for r in result] == [f"k{4-i}" for i in range(5)]

    def test_tail_respects_n(self, tmp_path):
        from bridge.memory_writes import emit, tail
        path = tmp_path / "writes.jsonl"
        for i in range(10):
            emit(_make_receipt(key=f"k{i}"), path=path)
        result = tail(3, path=path)
        assert len(result) == 3

    def test_tail_subsystem_filter(self, tmp_path):
        from bridge.memory_writes import emit, tail
        path = tmp_path / "writes.jsonl"
        emit(_make_receipt(subsystem="knowledge"), path=path)
        emit(_make_receipt(subsystem="conversation"), path=path)
        emit(_make_receipt(subsystem="knowledge"), path=path)
        result = tail(20, subsystem="knowledge", path=path)
        assert len(result) == 2
        assert all(r.subsystem == "knowledge" for r in result)

    def test_tail_ignores_malformed_lines(self, tmp_path):
        from bridge.memory_writes import emit, tail
        path = tmp_path / "writes.jsonl"
        path.write_text("not-json\n")
        emit(_make_receipt(), path=path)
        result = tail(20, path=path)
        assert len(result) == 1  # bad line skipped


# ---------------------------------------------------------------------------
# Round-trip: emit then tail
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_roundtrip_preserves_fields(self, tmp_path):
        from bridge.memory_writes import emit, tail
        path = tmp_path / "writes.jsonl"
        r = _make_receipt(subsystem="memory_file", op="update",
                          key="MEMORY.md", payload_bytes=1024,
                          actor="agent", notes="test note")
        emit(r, path=path)
        result = tail(1, path=path)
        assert len(result) == 1
        got = result[0]
        assert got.subsystem == "memory_file"
        assert got.op == "update"
        assert got.key == "MEMORY.md"
        assert got.bytes == 1024
        assert got.actor == "agent"
        assert got.notes == "test note"
