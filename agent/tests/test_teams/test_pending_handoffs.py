"""Tests for pending_handoffs discovery (sprint B-S.2)."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time

from teams._handoff import HandoffEnvelope, list_pending_handoffs, store_handoff
from teams.tools._common import pending_handoffs
from tests.test_teams.conftest import make_deps


def _make_memory_store() -> tuple[AsyncMock, dict[str, str]]:
    """Build a dict-backed async memory store with list_prefix support."""
    store: dict[str, str] = {}

    mock = AsyncMock()
    mock.set.side_effect = lambda k, v: store.__setitem__(k, v)
    mock.get.side_effect = lambda k: store.get(k)

    async def _list_prefix(prefix: str) -> list[str]:
        return [k for k in store if k.startswith(prefix)]

    mock.list_prefix = _list_prefix
    return mock, store


@pytest.mark.asyncio
async def test_list_pending_filters_by_department() -> None:
    """Only envelopes addressed to the target department should be returned."""
    memory_mock, _ = _make_memory_store()

    env_ops_1 = HandoffEnvelope(from_department="strategy", to_department="ops", task="alert")
    env_ops_2 = HandoffEnvelope(from_department="qa", to_department="ops", task="fix")
    env_design = HandoffEnvelope(from_department="strategy", to_department="design", task="redesign")

    await store_handoff(env_ops_1, memory_mock)
    await store_handoff(env_ops_2, memory_mock)
    await store_handoff(env_design, memory_mock)

    pending = await list_pending_handoffs(memory_mock, "ops")

    assert len(pending) == 2
    departments = {p.from_department for p in pending}
    assert departments == {"strategy", "qa"}


@pytest.mark.asyncio
async def test_list_pending_excludes_expired() -> None:
    """Expired envelopes must be filtered out."""
    memory_mock, _ = _make_memory_store()

    with freeze_time("2026-05-12 12:00:00") as frozen:
        fresh = HandoffEnvelope(from_department="qa", to_department="ops", task="fresh", ttl_hours=1.0)
        expired = HandoffEnvelope(from_department="strategy", to_department="ops", task="old", ttl_hours=0.0001)

        await store_handoff(fresh, memory_mock)
        await store_handoff(expired, memory_mock)

        frozen.tick(timedelta(seconds=1))  # let the 0.0001h envelope expire (~0.36s)

        pending = await list_pending_handoffs(memory_mock, "ops")

        assert len(pending) == 1
        assert pending[0].from_department == "qa"


@pytest.mark.asyncio
async def test_list_pending_empty_when_no_envelopes() -> None:
    memory_mock, _ = _make_memory_store()
    pending = await list_pending_handoffs(memory_mock, "ops")
    assert pending == []


@pytest.mark.asyncio
async def test_list_pending_returns_empty_for_none_store() -> None:
    pending = await list_pending_handoffs(None, "ops")
    assert pending == []


@pytest.mark.asyncio
async def test_list_pending_graceful_on_missing_list_prefix() -> None:
    """Stores without list_prefix support should return empty list, not raise."""
    memory_mock = AsyncMock()
    del memory_mock.list_prefix  # remove the attribute entirely
    pending = await list_pending_handoffs(memory_mock, "ops")
    assert pending == []


@pytest.mark.asyncio
async def test_pending_handoffs_tool_returns_formatted_string() -> None:
    """The pending_handoffs tool function must return a human-readable summary."""
    memory_mock, _ = _make_memory_store()

    env = HandoffEnvelope(from_department="qa", to_department="ops", task="check logs")
    await store_handoff(env, memory_mock)

    deps = make_deps(memory_store=memory_mock, department="ops")
    ctx = MagicMock()
    ctx.deps = deps

    result = await pending_handoffs(ctx, "ops")

    assert "ops" in result
    assert "qa" in result
    assert "check logs" in result


@pytest.mark.asyncio
async def test_pending_handoffs_tool_returns_no_pending_when_empty() -> None:
    memory_mock, _ = _make_memory_store()

    deps = make_deps(memory_store=memory_mock, department="ops")
    ctx = MagicMock()
    ctx.deps = deps

    result = await pending_handoffs(ctx, "ops")

    assert "no pending" in result.lower()


def test_pending_handoffs_registered_in_tool_registry() -> None:
    """pending_handoffs must be in TOOL_CALLABLES and COMMON_TOOL_NAMES."""
    from teams._tool_registry import COMMON_TOOL_NAMES, TOOL_CALLABLES

    assert "pending_handoffs" in TOOL_CALLABLES
    assert TOOL_CALLABLES["pending_handoffs"] is not None
    assert "pending_handoffs" in COMMON_TOOL_NAMES
