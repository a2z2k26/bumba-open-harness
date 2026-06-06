"""Integration tests for Sprint 07.13 — StreamCoalescer wired from BridgeApp manifest.

R1 Operability said stream_coalescer was unwired. R2 corrected: the module
IS imported and DiscordBot.set_stream_coalescer exists, but had zero callers.
The setter-attach path was dead, leaving self._stream_coalescer == None and
every Discord delta as a separate edit.

Sprint 07.13 fixes that:

- BridgeApp constructs ``StreamCoalescer(on_flush=...)`` in ``_initialize``.
- A ``WiringEntry`` for ``set_stream_coalescer`` on DiscordBot fires from
  the manifest, attaching the coalescer to the bot.
- ClaudeRunner gains an ``on_text_delta`` callback parameter so the bridge
  can route every assistant text event through ``coalescer.push(...)``
  instead of direct Discord writes.

These tests assert the wiring contract and the coalescer's batching contract
end-to-end. The 100ms timer-driven flush is StreamCoalescer's documented
mechanism; here we drive it manually to keep the tests deterministic.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.stream_coalescer import StreamCoalescer


# ---------------------------------------------------------------------------
# Boot-time wiring contract
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def wired_app(tmp_path, sample_config_toml, mock_keyring):
    """Boot a BridgeApp through ``_initialize`` (no Discord/Claude network IO)."""
    app = BridgeApp(config_path=str(sample_config_toml))
    await app._initialize()
    yield app
    if app._db:
        await app._db.close()


class TestCoalescerWiring:
    """Sprint 07.13: ``set_stream_coalescer`` must fire from the manifest."""

    @pytest.mark.asyncio
    async def test_coalescer_attached_on_bridge_boot(self, wired_app):
        """After ``_initialize``, DiscordBot._stream_coalescer must be a real
        StreamCoalescer instance — not the default ``None`` left over from
        ``DiscordBot.__init__``. This is the regression guard against the
        Pattern B setter-orphan that R1 surfaced."""
        assert wired_app._discord is not None
        assert wired_app._discord._stream_coalescer is not None, (
            "DiscordBot._stream_coalescer is None after _initialize — "
            "the WIRING_MANIFEST entry for set_stream_coalescer did not fire."
        )
        assert isinstance(wired_app._discord._stream_coalescer, StreamCoalescer)

    @pytest.mark.asyncio
    async def test_bridge_owns_coalescer_source_attr(self, wired_app):
        """BridgeApp must keep the coalescer on ``_stream_coalescer`` so the
        WIRING_MANIFEST source resolution (``getattr(app, 'stream_coalescer')``)
        finds it. Plan 07.13 owns construction; future sprints that reach in
        depend on the same attribute name."""
        assert getattr(wired_app, "_stream_coalescer", None) is not None
        # Same instance, both ends of the wire.
        assert wired_app._stream_coalescer is wired_app._discord._stream_coalescer


# ---------------------------------------------------------------------------
# Batching contract — N deltas → ≤ N/5 flush callbacks
# ---------------------------------------------------------------------------


class TestCoalescerBatching:
    """Sprint 07.13: the coalescer's documented goal is ~50 → ~5 edits.

    These tests do not require a real Discord; they pin the batching contract
    against a mock on_flush callback so the regression is caught even if the
    bridge isn't fully booted."""

    @pytest.mark.asyncio
    async def test_fifty_deltas_produce_under_ten_edits(self):
        """Push 50 deltas back-to-back; flush exactly once. Goal: ≤ 10
        callback invocations regardless of timer scheduling — and in this
        deterministic single-flush path, exactly one. Sprint 07.13 documents
        ~50→~5 as the target; we assert the strict ≤10 upper bound here."""
        cb = AsyncMock()
        coalescer = StreamCoalescer(on_flush=cb)

        for i in range(50):
            coalescer.push(f"delta-{i:02d} ")

        # One explicit flush — the coalescer batches everything into a single
        # callback invocation regardless of how many push() calls preceded it.
        await coalescer.flush()

        assert cb.await_count <= 10, (
            f"50 deltas produced {cb.await_count} callback invocations — "
            f"the coalescer is not batching (Sprint 07.13 target: ~5)."
        )
        # Final accumulated text contains every delta.
        last_call_arg = cb.await_args.args[0]
        assert last_call_arg.startswith("delta-00 ")
        assert last_call_arg.endswith("delta-49 ")

    @pytest.mark.asyncio
    async def test_timer_driven_flush_keeps_callback_count_low(self):
        """Validate the 100ms timer-driven path: push 50 deltas with a small
        ``await asyncio.sleep(0)`` yield so the loop can run the timer once.
        Even with timer-driven flushes interleaved, callback count stays ≤10."""
        cb = AsyncMock()
        coalescer = StreamCoalescer(on_flush=cb)

        for i in range(50):
            coalescer.push(f"d{i} ")
        # Let the 100ms timer fire at most a couple of times.
        await asyncio.sleep(0.25)
        await coalescer.finalize()

        assert cb.await_count <= 10, (
            f"Timer-driven path produced {cb.await_count} callbacks — "
            f"batching goal (~5) breached."
        )


# ---------------------------------------------------------------------------
# Tool-call boundary semantics — finalize forces flush
# ---------------------------------------------------------------------------


class TestFlushBoundary:
    """Sprint 07.13: a tool-call boundary (or end-of-stream) must force flush.

    The coalescer exposes ``finalize()`` for this — it cancels any pending
    timer and emits whatever's buffered. In the bridge, ClaudeRunner calls
    ``coalescer.finalize()`` once invoke() returns the final ClaudeResult."""

    @pytest.mark.asyncio
    async def test_flush_on_tool_call_boundary(self):
        """Push a few text deltas, then call finalize() (the tool-call /
        end-of-stream boundary marker). Flush must fire with the accumulated
        text and the coalescer must mark itself finalized."""
        cb = AsyncMock()
        coalescer = StreamCoalescer(on_flush=cb)

        coalescer.push("partial ")
        coalescer.push("text ")
        coalescer.push("before tool call")
        # Finalize is the bridge's tool-call boundary signal.
        await coalescer.finalize()

        cb.assert_awaited_once_with("partial text before tool call")
        assert coalescer._finalized is True
