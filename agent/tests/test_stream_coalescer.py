"""Tests for StreamCoalescer — 100ms delta buffering for Discord delivery."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from bridge.stream_coalescer import StreamCoalescer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_coalescer(callback=None):
    """Return a StreamCoalescer with an AsyncMock flush callback."""
    if callback is None:
        callback = AsyncMock()
    return StreamCoalescer(on_flush=callback), callback


# ---------------------------------------------------------------------------
# 1. push(delta) — accumulates full_text
# ---------------------------------------------------------------------------

def test_push_accumulates_full_text():
    coalescer, _ = make_coalescer()
    coalescer.push("hello")
    assert coalescer._full_text == "hello"


# ---------------------------------------------------------------------------
# 2. multiple push() — full_text is concatenation of all deltas
# ---------------------------------------------------------------------------

def test_push_multiple_concatenates():
    coalescer, _ = make_coalescer()
    coalescer.push("foo")
    coalescer.push(" bar")
    coalescer.push(" baz")
    assert coalescer._full_text == "foo bar baz"


# ---------------------------------------------------------------------------
# 3. flush() — calls on_flush callback with full_text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_calls_callback_with_full_text():
    coalescer, cb = make_coalescer()
    coalescer.push("hello world")
    await coalescer.flush()
    cb.assert_awaited_once_with("hello world")


# ---------------------------------------------------------------------------
# 4. flush() on empty buffer — no callback call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_empty_buffer_no_callback():
    coalescer, cb = make_coalescer()
    await coalescer.flush()
    cb.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. flush() — clears buffer after flushing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_clears_buffer():
    coalescer, _ = make_coalescer()
    coalescer.push("data")
    await coalescer.flush()
    assert coalescer._buffer == []


# ---------------------------------------------------------------------------
# 6. FLUSH_INTERVAL_MS == 100
# ---------------------------------------------------------------------------

def test_flush_interval_ms():
    assert StreamCoalescer.FLUSH_INTERVAL_MS == 100


# ---------------------------------------------------------------------------
# 7. reset() — clears full_text, buffer, cancels pending timer
# ---------------------------------------------------------------------------

def test_reset_clears_state():
    coalescer, _ = make_coalescer()
    coalescer.push("something")
    coalescer.reset()
    assert coalescer._full_text == ""
    assert coalescer._buffer == []
    assert coalescer._timer is None
    assert coalescer._finalized is False


# ---------------------------------------------------------------------------
# 8. flush callback receives full accumulated text (not just last delta)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_callback_receives_full_text_not_last_delta():
    coalescer, cb = make_coalescer()
    coalescer.push("part1 ")
    coalescer.push("part2 ")
    coalescer.push("part3")
    await coalescer.flush()
    # Callback must receive the fully accumulated string, not just "part3"
    cb.assert_awaited_once_with("part1 part2 part3")


# ---------------------------------------------------------------------------
# 9. Multiple push() before flush — callback called once with complete text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_pushes_single_callback_call():
    coalescer, cb = make_coalescer()
    for word in ["a", "b", "c", "d", "e"]:
        coalescer.push(word)
    await coalescer.flush()
    assert cb.await_count == 1
    cb.assert_awaited_once_with("abcde")


# ---------------------------------------------------------------------------
# 10. _schedule_flush sets timer (not None after push in running loop)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schedule_flush_sets_timer():
    coalescer, _ = make_coalescer()
    coalescer.push("delta")
    # In a running loop, _schedule_flush should have set a timer handle
    assert coalescer._timer is not None
    # Clean up
    coalescer.reset()


# ---------------------------------------------------------------------------
# 11. finalize() — forces immediate flush, marks finalized
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finalize_forces_flush():
    coalescer, cb = make_coalescer()
    coalescer.push("stream ")
    coalescer.push("complete")
    await coalescer.finalize()
    cb.assert_awaited_once_with("stream complete")
    assert coalescer._finalized is True


# ---------------------------------------------------------------------------
# 12. finalize() on empty buffer — no callback called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finalize_empty_buffer_no_callback():
    coalescer, cb = make_coalescer()
    await coalescer.finalize()
    cb.assert_not_awaited()
    assert coalescer._finalized is True


# ---------------------------------------------------------------------------
# Additional: push() after finalize() is ignored
# ---------------------------------------------------------------------------

def test_push_after_finalize_ignored():
    coalescer, _ = make_coalescer()
    coalescer._finalized = True
    coalescer.push("ignored")
    assert coalescer._full_text == ""
    assert coalescer._buffer == []


# ---------------------------------------------------------------------------
# Additional: finalize() cancels scheduled timer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finalize_cancels_timer():
    coalescer, _ = make_coalescer()
    coalescer.push("data")
    # Timer should be set
    assert coalescer._timer is not None
    await coalescer.finalize()
    # Timer should be cancelled/cleared after finalize
    assert coalescer._timer is None


# ---------------------------------------------------------------------------
# Additional: reset() after finalize() clears finalized flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_after_finalize_clears_flag():
    coalescer, _ = make_coalescer()
    coalescer.push("x")
    await coalescer.finalize()
    assert coalescer._finalized is True
    coalescer.reset()
    assert coalescer._finalized is False


# ---------------------------------------------------------------------------
# Additional: flush() after flush() on same buffer — second flush does nothing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_double_flush_second_is_noop():
    coalescer, cb = make_coalescer()
    coalescer.push("text")
    await coalescer.flush()
    await coalescer.flush()
    # Only one callback call — second flush sees empty buffer
    assert cb.await_count == 1


# ---------------------------------------------------------------------------
# Additional: timer fires and flushes via asyncio loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timer_fires_and_flushes():
    """Timer scheduled by _schedule_flush eventually fires and calls flush."""
    cb = AsyncMock()
    coalescer = StreamCoalescer(on_flush=cb)
    coalescer.push("timed flush")
    # Timer set — wait slightly longer than FLUSH_INTERVAL_MS
    await asyncio.sleep(0.15)
    cb.assert_awaited_once_with("timed flush")
    coalescer.reset()
