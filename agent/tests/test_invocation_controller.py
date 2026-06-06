"""Tests for InvocationController (Sprint P1.1, audit finding C1).

The controller is the shared in-flight signal that both ClaudeRunner
(one-shot) and WarmClaudeProcess (warm) tick into. App-level interrupt
detection consults it via ``active()`` so a warm-path invocation is no
longer invisible to the operator-interrupt path.
"""

from __future__ import annotations

import asyncio

import pytest

from bridge.invocation_controller import (
    InvocationController,
    InvocationSnapshot,
)


@pytest.mark.asyncio
async def test_initial_state_is_idle():
    c = InvocationController()
    assert await c.active() is None


@pytest.mark.asyncio
async def test_start_records_snapshot():
    c = InvocationController()
    snap = await c.start(path="one_shot", session_id="s1", chat_id="c1")
    assert isinstance(snap, InvocationSnapshot)
    assert snap.path == "one_shot"
    assert snap.session_id == "s1"
    assert snap.chat_id == "c1"
    assert snap.invocation_id.startswith("inv_")

    active = await c.active()
    assert active is not None
    assert active.invocation_id == snap.invocation_id


@pytest.mark.asyncio
async def test_finish_clears_snapshot():
    c = InvocationController()
    snap = await c.start(path="warm")
    assert await c.active() is not None
    await c.finish(snap.invocation_id)
    assert await c.active() is None


@pytest.mark.asyncio
async def test_finish_with_stale_id_is_noop():
    c = InvocationController()
    snap = await c.start(path="warm")
    # Wrong id — must NOT clear the active snapshot
    await c.finish("inv_fake_999")
    active = await c.active()
    assert active is not None
    assert active.invocation_id == snap.invocation_id


@pytest.mark.asyncio
async def test_track_context_manager_pairs_start_and_finish():
    c = InvocationController()
    assert await c.active() is None
    async with c.track(path="warm", session_id="s2") as snap:
        assert snap.path == "warm"
        assert snap.session_id == "s2"
        active = await c.active()
        assert active is not None
        assert active.invocation_id == snap.invocation_id
    # After exit
    assert await c.active() is None


@pytest.mark.asyncio
async def test_track_clears_snapshot_even_on_exception():
    c = InvocationController()
    with pytest.raises(RuntimeError):
        async with c.track(path="one_shot"):
            raise RuntimeError("simulated invocation failure")
    assert await c.active() is None


@pytest.mark.asyncio
async def test_invocation_ids_are_unique_per_start():
    c = InvocationController()
    s1 = await c.start(path="warm")
    await c.finish(s1.invocation_id)
    s2 = await c.start(path="warm")
    assert s1.invocation_id != s2.invocation_id


@pytest.mark.asyncio
async def test_path_literal_accepted():
    c = InvocationController()
    # Both Literal values must work without error
    s_warm = await c.start(path="warm")
    await c.finish(s_warm.invocation_id)
    s_one = await c.start(path="one_shot")
    assert s_one.path == "one_shot"


@pytest.mark.asyncio
async def test_concurrent_starts_do_not_corrupt_state():
    """The controller serializes via an asyncio.Lock; concurrent starts
    must each produce a distinct snapshot and not corrupt the singleton
    active slot.
    """
    c = InvocationController()

    async def _start_and_get_id():
        snap = await c.start(path="warm")
        return snap.invocation_id

    ids = await asyncio.gather(*[_start_and_get_id() for _ in range(5)])
    # All ids unique
    assert len(set(ids)) == 5
    # Active slot holds *some* snapshot (last writer wins is fine)
    active = await c.active()
    assert active is not None
    assert active.invocation_id in ids


@pytest.mark.asyncio
async def test_audit_c1_repro_warm_path_visible_to_active_check():
    """Regression test for the C1 finding: pre-P1.1, an app-level check
    of ``ClaudeRunner._lock.locked()`` was the only in-flight signal.
    A warm invocation was invisible to that check.

    With the InvocationController, BOTH paths are tracked via the same
    controller, so ``await controller.active()`` returns truthy for
    either path. This test simulates the warm-path entry point.
    """
    c = InvocationController()
    # Simulate WarmClaudeProcess.send_message entering its tracked block
    async with c.track(path="warm", session_id="warm-sess"):
        snap = await c.active()
        assert snap is not None, (
            "P1.1 regression: warm-path invocation is invisible to active() — "
            "operator interrupt detection would silently miss it."
        )
        assert snap.path == "warm"
        assert snap.session_id == "warm-sess"
