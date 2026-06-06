"""Tests for bridge.memory_wal — Sprint 03.06.

Covers the spec acceptance checklist:
- enqueue writes one valid JSON line, durable
- drain calls applier per entry, removes drained, retains failures
- replay/recover after simulated crash recovers all unapplied operations
- concurrent enqueue from two coroutines doesn't interleave bytes
- memory_wal_enabled=False short-circuits to no-op
- corrupt WAL line is skipped (warning) not crash
- idempotency: drain twice → no duplicates
- size warning at 10 MB
- consolidation lock held → drain is a no-op (force=True bypasses)
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bridge.consolidation_lock import ConsolidationLock
from bridge.memory_wal import (
    WAL_WARN_BYTES,
    DrainResult,
    MemoryWAL,
    WALEntry,
    _compute_write_id,
)


@pytest.fixture
def wal_path(tmp_path: Path) -> Path:
    return tmp_path / "memory_wal.jsonl"


@pytest.fixture
def live_other_pid() -> int:
    """Return a live PID that is not the pytest process itself."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    try:
        yield proc.pid
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# -------- Schema / pure-function helpers --------


def test_compute_write_id_is_deterministic() -> None:
    a = _compute_write_id({"k": "v"}, "knowledge", "2026-04-29T00:00:00Z")
    b = _compute_write_id({"k": "v"}, "knowledge", "2026-04-29T00:00:00Z")
    assert a == b
    # Different store → different id
    c = _compute_write_id({"k": "v"}, "different", "2026-04-29T00:00:00Z")
    assert a != c


def test_walentry_round_trip() -> None:
    entry = WALEntry(
        ts="2026-04-29T00:00:00Z",
        write_id="abc",
        target_store="knowledge",
        payload_hash="def",
        payload={"key": "x", "value": "y"},
    )
    line = entry.to_json_line()
    parsed = json.loads(line)
    rebuilt = WALEntry.from_dict(parsed)
    assert rebuilt == entry


# -------- enabled=False short-circuit --------


@pytest.mark.asyncio
async def test_disabled_enqueue_is_noop(wal_path: Path) -> None:
    wal = MemoryWAL(wal_path, enabled=False)
    result = await wal.enqueue("knowledge", {"key": "k", "value": "v"})
    assert result is None
    assert not wal_path.exists()


@pytest.mark.asyncio
async def test_disabled_drain_returns_empty(wal_path: Path) -> None:
    wal = MemoryWAL(wal_path, enabled=False)

    async def applier(_op):
        raise AssertionError("applier should not be called when disabled")

    result = await wal.drain(applier)
    assert result.drained == 0
    assert result.retained == 0


# -------- enqueue --------


@pytest.mark.asyncio
async def test_enqueue_writes_one_valid_json_line(wal_path: Path) -> None:
    wal = MemoryWAL(wal_path, enabled=True)
    entry = await wal.enqueue("knowledge", {"key": "k1", "value": "v1"})
    assert entry is not None
    raw = wal_path.read_text(encoding="utf-8")
    lines = [l for l in raw.splitlines() if l]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["target_store"] == "knowledge"
    assert parsed["payload"]["key"] == "k1"
    assert parsed["status"] == "pending"
    assert parsed["write_id"] == entry.write_id


@pytest.mark.asyncio
async def test_enqueue_appends_multiple(wal_path: Path) -> None:
    wal = MemoryWAL(wal_path, enabled=True)
    for i in range(3):
        await wal.enqueue("knowledge", {"key": f"k{i}", "value": "v"})
    lines = [l for l in wal_path.read_text().splitlines() if l]
    assert len(lines) == 3


# -------- drain --------


@pytest.mark.asyncio
async def test_drain_applies_each_and_removes_drained(wal_path: Path) -> None:
    wal = MemoryWAL(wal_path, enabled=True)
    await wal.enqueue("knowledge", {"key": "k1", "value": "v1"})
    await wal.enqueue("knowledge", {"key": "k2", "value": "v2"})

    seen: list[dict] = []

    async def applier(op):
        seen.append(op)
        return True

    result = await wal.drain(applier)
    assert isinstance(result, DrainResult)
    assert result.drained == 2
    assert result.retained == 0
    assert len(seen) == 2
    # File shrinks to zero bytes (still exists)
    assert wal_path.read_text() == ""


@pytest.mark.asyncio
async def test_drain_keeps_failed_entries(wal_path: Path) -> None:
    wal = MemoryWAL(wal_path, enabled=True)
    await wal.enqueue("knowledge", {"key": "ok", "value": "v"})
    await wal.enqueue("knowledge", {"key": "fail", "value": "v"})

    async def applier(op):
        return op["payload"]["key"] == "ok"

    result = await wal.drain(applier)
    assert result.drained == 1
    assert result.retained == 1
    survivors = [l for l in wal_path.read_text().splitlines() if l]
    assert len(survivors) == 1
    assert json.loads(survivors[0])["payload"]["key"] == "fail"


@pytest.mark.asyncio
async def test_drain_idempotent_under_double_call(wal_path: Path) -> None:
    """Spec: drain twice → no duplicates."""
    wal = MemoryWAL(wal_path, enabled=True)
    await wal.enqueue("knowledge", {"key": "k", "value": "v"})

    applied: list[str] = []

    async def applier(op):
        applied.append(op["write_id"])
        return True

    r1 = await wal.drain(applier)
    r2 = await wal.drain(applier)
    assert r1.drained == 1
    assert r2.drained == 0
    assert len(applied) == 1


# -------- recover / replay --------


@pytest.mark.asyncio
async def test_replay_pending_recovers_after_simulated_crash(
    wal_path: Path,
) -> None:
    # Simulate a crashed prior session: the WAL file exists with one
    # un-drained entry. Construct a fresh MemoryWAL (different process
    # instance) and call recover.
    crashed = MemoryWAL(wal_path, enabled=True)
    await crashed.enqueue("knowledge", {"key": "kept", "value": "v"})
    # Drop reference — no drain ever fired (crash).
    del crashed

    fresh = MemoryWAL(wal_path, enabled=True)

    recovered: list[dict] = []

    async def applier(op):
        recovered.append(op)
        return True

    result = await fresh.recover(applier)
    assert result.drained == 1
    assert recovered[0]["payload"]["key"] == "kept"
    assert wal_path.read_text() == ""


@pytest.mark.asyncio
async def test_replay_pending_alias_works(wal_path: Path) -> None:
    """`replay_pending` is an alias for recover (spec naming)."""
    wal = MemoryWAL(wal_path, enabled=True)
    await wal.enqueue("knowledge", {"key": "x", "value": "v"})

    async def applier(op):
        return True

    result = await wal.replay_pending(applier)
    assert result.drained == 1


# -------- concurrent appends --------


@pytest.mark.asyncio
async def test_concurrent_appends_dont_interleave(wal_path: Path) -> None:
    wal = MemoryWAL(wal_path, enabled=True)

    async def writer(prefix: str, n: int) -> None:
        for i in range(n):
            await wal.enqueue(
                "knowledge",
                {"key": f"{prefix}-{i}", "value": "x" * 50},
            )

    await asyncio.gather(
        writer("a", 25),
        writer("b", 25),
    )

    lines = [l for l in wal_path.read_text().splitlines() if l]
    assert len(lines) == 50
    # Every line is parseable JSON — no torn writes.
    for line in lines:
        parsed = json.loads(line)
        assert parsed["target_store"] == "knowledge"
        assert "payload" in parsed


# -------- corrupt lines --------


@pytest.mark.asyncio
async def test_corrupt_line_is_skipped(wal_path: Path) -> None:
    wal = MemoryWAL(wal_path, enabled=True)
    await wal.enqueue("knowledge", {"key": "good1", "value": "v"})
    # Inject a corrupt line directly to disk
    with open(wal_path, "a", encoding="utf-8") as f:
        f.write("{not-json,,,\n")
    await wal.enqueue("knowledge", {"key": "good2", "value": "v"})

    seen: list[str] = []

    async def applier(op):
        seen.append(op["payload"]["key"])
        return True

    result = await wal.drain(applier)
    assert result.skipped_corrupt == 1
    assert result.drained == 2
    assert sorted(seen) == ["good1", "good2"]


# -------- size warning --------


@pytest.mark.asyncio
async def test_size_warning_triggers_at_10mb(
    wal_path: Path,
    caplog,
) -> None:
    """Spec test_wal_size_alert_at_10mb."""
    import logging as _logging

    wal = MemoryWAL(wal_path, enabled=True)
    # Pre-stuff the file with 10 MB+1 of placeholder bytes so the next
    # append crosses the threshold.
    wal_path.parent.mkdir(parents=True, exist_ok=True)
    with open(wal_path, "wb") as f:
        f.write(b"x" * (WAL_WARN_BYTES + 1))

    caplog.set_level(_logging.WARNING, logger="bridge.memory_wal")
    await wal.enqueue("knowledge", {"key": "k", "value": "v"})

    triggered = any(
        "drain pressure rising" in rec.message
        or "force-drain" in rec.message
        for rec in caplog.records
    )
    assert triggered, [r.message for r in caplog.records]


# -------- consolidation lock coordination --------


@pytest.mark.asyncio
async def test_drain_skipped_while_consolidation_lock_held(
    tmp_path: Path,
    live_other_pid: int,
) -> None:
    """If consolidation is running, drain returns empty without applying."""
    wal_path = tmp_path / "wal.jsonl"
    lock = ConsolidationLock(tmp_path)

    # Simulate another live process holding the lock by writing a PID that's
    # NOT our own and is currently alive.
    lock_path = tmp_path / ".consolidate-lock"
    lock_path.write_text(str(live_other_pid))

    wal = MemoryWAL(wal_path, enabled=True, consolidation_lock=lock)
    await wal.enqueue("knowledge", {"key": "k", "value": "v"})

    called = False

    async def applier(op):
        nonlocal called
        called = True
        return True

    result = await wal.drain(applier)
    assert result.drained == 0
    assert called is False
    # Surviving line still on disk
    assert "k" in wal_path.read_text()


@pytest.mark.asyncio
async def test_drain_releases_after_consolidation_unlocks(
    tmp_path: Path,
    live_other_pid: int,
) -> None:
    """After consolidation lock is released, the next drain succeeds."""
    wal_path = tmp_path / "wal.jsonl"
    lock = ConsolidationLock(tmp_path)
    lock_path = tmp_path / ".consolidate-lock"
    lock_path.write_text(str(live_other_pid))

    wal = MemoryWAL(wal_path, enabled=True, consolidation_lock=lock)
    await wal.enqueue("knowledge", {"key": "k1", "value": "v"})

    async def applier(op):
        return True

    blocked = await wal.drain(applier)
    assert blocked.drained == 0

    # Release the lock (clear PID body keeps file mtime semantics
    # documented in consolidation_lock.py).
    lock.release()

    unblocked = await wal.drain(applier)
    assert unblocked.drained == 1


@pytest.mark.asyncio
async def test_recover_bypasses_consolidation_lock(
    tmp_path: Path,
) -> None:
    """Startup recovery uses force=True so a stale lock can't block it."""
    wal_path = tmp_path / "wal.jsonl"
    lock = ConsolidationLock(tmp_path)
    lock_path = tmp_path / ".consolidate-lock"
    lock_path.write_text(str(os.getppid()))

    wal = MemoryWAL(wal_path, enabled=True, consolidation_lock=lock)
    await wal.enqueue("knowledge", {"key": "k", "value": "v"})

    async def applier(op):
        return True

    # recover() forces drain regardless of lock state
    result = await wal.recover(applier)
    assert result.drained == 1
