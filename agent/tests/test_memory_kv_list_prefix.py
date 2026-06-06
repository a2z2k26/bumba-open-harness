"""Tests for MemoryKVAdapter.list_prefix — Sprint 11 / issue #631.

Verifies that:
1. MemoryKVAdapter.list_prefix exists and is callable.
2. list_pending_handoffs works end-to-end via list_prefix.
3. The silent AttributeError swallow in list_pending_handoffs is replaced by
   an explicit warning log.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from bridge.memory import MemoryKVAdapter
from teams._handoff import (
    HandoffEnvelope,
    list_pending_handoffs,
    store_handoff,
)


# ---------------------------------------------------------------------------
# Helper: dict-backed async adapter that mimics MemoryKVAdapter.list_prefix
# ---------------------------------------------------------------------------

def _dict_adapter() -> tuple[AsyncMock, dict[str, str]]:
    """Return an AsyncMock + backing dict with get/set/list_prefix wired."""
    store: dict[str, str] = {}
    mock = AsyncMock()
    mock.set.side_effect = lambda k, v: store.__setitem__(k, v)
    mock.get.side_effect = lambda k: store.get(k)

    async def _list_prefix(prefix: str) -> list[str]:
        return sorted(k for k in store if k.startswith(prefix))

    mock.list_prefix = _list_prefix
    return mock, store


# ---------------------------------------------------------------------------
# 1. MemoryKVAdapter structural test — method must exist
# ---------------------------------------------------------------------------

def test_memory_kv_adapter_has_list_prefix() -> None:
    """MemoryKVAdapter must expose an async list_prefix method."""
    assert hasattr(MemoryKVAdapter, "list_prefix"), (
        "MemoryKVAdapter.list_prefix not found — production list_pending_handoffs "
        "will silently return [] for every call."
    )
    import inspect
    assert inspect.iscoroutinefunction(MemoryKVAdapter.list_prefix), (
        "MemoryKVAdapter.list_prefix must be an async method"
    )


# ---------------------------------------------------------------------------
# 2. MemoryKVAdapter.list_prefix integration test (against real Memory shim)
# ---------------------------------------------------------------------------

class _FakeDB:
    """Minimal in-memory DB shim that MemoryKVAdapter._memory._db expects."""

    def __init__(self) -> None:
        self._rows: list[tuple[str]] = []

    async def fetchall(self, sql: str, params: tuple) -> list[tuple[str, ...]]:
        prefix = params[0].rstrip("%")  # e.g. "handoff:"
        return [r for r in self._rows if r[0].startswith(prefix)]

    async def execute(self, sql: str, params: tuple) -> "_FakeCursor":
        # store_knowledge calls execute for INSERT … WHERE key=?
        # We only care about SELECT, so we just store the row naively.
        if "INSERT" in sql.upper():
            key = params[0]
            # remove old row with same key
            self._rows = [r for r in self._rows if r[0] != key]
            self._rows.append((key,))
        return _FakeCursor()

    async def commit(self) -> None:
        pass

    async def fetchone(self, sql: str, params: tuple) -> tuple | None:
        key = params[0]
        for r in self._rows:
            if r[0] == key:
                return r
        return None


class _FakeCursor:
    lastrowid = 1


class _FakeMemory:
    """Minimal Memory shim for MemoryKVAdapter tests."""

    def __init__(self) -> None:
        self._db = _FakeDB()
        self._store: dict[str, str] = {}

    async def get_knowledge(self, key: str) -> str | None:
        return self._store.get(key)

    async def store_knowledge(self, key: str, value: str, source: str = "") -> None:
        self._store[key] = value
        await self._db.execute(
            "INSERT INTO knowledge (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


@pytest.mark.asyncio
async def test_list_prefix_returns_matching_keys() -> None:
    """list_prefix returns only keys that start with the given prefix."""
    adapter = MemoryKVAdapter(_FakeMemory())  # type: ignore[arg-type]
    await adapter.set("handoff:abc", "data1")
    await adapter.set("handoff:def", "data2")
    await adapter.set("other:xyz", "data3")

    keys = await adapter.list_prefix("handoff:")
    assert "handoff:abc" in keys
    assert "handoff:def" in keys
    assert "other:xyz" not in keys


@pytest.mark.asyncio
async def test_list_prefix_empty_when_no_matches() -> None:
    """list_prefix returns [] when no keys match the prefix."""
    adapter = MemoryKVAdapter(_FakeMemory())  # type: ignore[arg-type]
    await adapter.set("other:xyz", "data")

    keys = await adapter.list_prefix("handoff:")
    assert keys == []


@pytest.mark.asyncio
async def test_list_prefix_empty_store() -> None:
    """list_prefix on an empty store returns []."""
    adapter = MemoryKVAdapter(_FakeMemory())  # type: ignore[arg-type]
    assert await adapter.list_prefix("handoff:") == []


# ---------------------------------------------------------------------------
# 3. list_pending_handoffs end-to-end (mock adapter)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pending_handoffs_filters_by_department() -> None:
    """Only envelopes addressed to the target department are returned."""
    mock, _ = _dict_adapter()

    env_ops = HandoffEnvelope(from_department="strategy", to_department="ops", task="alert")
    env_design = HandoffEnvelope(from_department="qa", to_department="design", task="redesign")

    await store_handoff(env_ops, mock)
    await store_handoff(env_design, mock)

    pending = await list_pending_handoffs(mock, "ops")
    assert len(pending) == 1
    assert pending[0].from_department == "strategy"


@pytest.mark.asyncio
async def test_list_pending_handoffs_returns_empty_for_none_store() -> None:
    """None memory_store should yield empty list, not raise."""
    result = await list_pending_handoffs(None, "ops")
    assert result == []


@pytest.mark.asyncio
async def test_list_pending_handoffs_logs_warning_without_list_prefix(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stores that lack list_prefix must log a warning rather than raising."""
    # Use a plain object that has get/set but no list_prefix, so
    # AttributeError fires naturally when list_pending_handoffs calls it.
    class _NoListPrefix:
        async def get(self, key: str):
            return None
        async def set(self, key: str, value: str) -> None:
            pass

    mock = _NoListPrefix()

    with caplog.at_level(logging.WARNING, logger="teams._handoff"):
        result = await list_pending_handoffs(mock, "ops")

    assert result == []
    assert any("list_prefix" in r.message for r in caplog.records), (
        "Expected a warning log mentioning list_prefix, got: "
        + str([r.message for r in caplog.records])
    )


@pytest.mark.asyncio
async def test_list_pending_handoffs_multiple_recipients() -> None:
    """Multiple envelopes for the same department are all returned."""
    mock, _ = _dict_adapter()

    for i in range(3):
        env = HandoffEnvelope(
            from_department="strategy", to_department="ops", task=f"task-{i}"
        )
        await store_handoff(env, mock)

    pending = await list_pending_handoffs(mock, "ops")
    assert len(pending) == 3
