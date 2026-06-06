"""Tests for bridge.app and bridge.__main__ (S84)."""

from __future__ import annotations

from dataclasses import replace
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.message_queue import QueuedMessage


@pytest_asyncio.fixture
async def wired_app(tmp_path, sample_config_toml, mock_keyring):
    """Create a BridgeApp with initialized components (no Discord/Claude)."""
    app = BridgeApp(config_path=str(sample_config_toml))

    # Initialize components without starting Discord
    await app._initialize()
    yield app

    # Cleanup — Sprint R2.3 (#1895): close the sync-sqlite stores
    # BridgeApp owns. Tests that exercise stop() do this via the
    # shutdown path; tests that don't reach stop() still must release
    # the connections explicitly or each test leaks a handful of
    # ``ResourceWarning: unclosed database`` entries on GC.
    for _store in (app._embedding_engine, app._workorder_store, app._peer_registry):
        if _store is not None and hasattr(_store, "close"):
            try:
                _store.close()
            except Exception:  # noqa: BLE001
                pass
    if app._db:
        await app._db.close()


class TestAppInitialize:
    """S77: BridgeApp skeleton and initialization."""

    @pytest.mark.asyncio
    async def test_initialize_delegates_to_startup_builder(
        self, monkeypatch, sample_config_toml
    ):
        from bridge import app_init

        app = BridgeApp(config_path=str(sample_config_toml))
        captured = {}

        async def fake_run(self):
            captured["app"] = self._app

        monkeypatch.setattr(app_init.BridgeAppInit, "run", fake_run)

        await app._initialize()

        assert captured["app"] is app

    @pytest.mark.asyncio
    async def test_initialize_creates_components(self, wired_app):
        assert wired_app._config is not None
        assert wired_app._db is not None
        assert wired_app._queue is not None
        assert wired_app._memory is not None
        assert wired_app._session_mgr is not None
        assert wired_app._security is not None
        assert wired_app._claude is not None
        assert wired_app._discord is not None
        assert wired_app._commands is not None

    @pytest.mark.asyncio
    async def test_initialize_sets_callbacks(self, wired_app):
        assert wired_app._discord._message_callback is not None
        assert wired_app._discord._command_callback is not None

    @pytest.mark.asyncio
    async def test_initialize_creates_voice_components(self, wired_app):
        assert wired_app._config.voice_enabled is False
        assert wired_app._voice is None
        assert wired_app._tts is None
        assert wired_app._audio_pipeline is None

    @pytest.mark.asyncio
    async def test_initialize_wires_voice_manager(self, wired_app):
        assert wired_app._discord._voice_manager is wired_app._voice



class TestAppStartup:
    """S78: Startup sequence."""

    @pytest.mark.asyncio
    async def test_startup_writes_pid(self, wired_app):
        assert wired_app._pid_path is not None
        wired_app._pid_path.write_text(str(os.getpid()))
        assert wired_app._pid_path.exists()
        assert wired_app._pid_path.read_text() == str(os.getpid())

    @pytest.mark.asyncio
    async def test_halt_flag_detected_on_startup(self, wired_app):
        # Set halt flag
        wired_app._security.set_halt("test_halt")

        # Re-check as startup would
        halt_reason = wired_app._security.check_halt_flag()
        assert halt_reason == "test_halt"


class TestAppShutdown:
    """S81: Graceful shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_removes_pid(self, wired_app):
        assert wired_app._pid_path is not None
        wired_app._pid_path.write_text("12345")

        # Mock discord to avoid real network calls
        wired_app._discord = MagicMock()
        wired_app._discord.send_message = AsyncMock()
        wired_app._discord.stop = AsyncMock()

        wired_app._claude = MagicMock()
        wired_app._claude.kill_current = AsyncMock(return_value=False)

        await wired_app.stop()

        assert not wired_app._pid_path.exists()

    @pytest.mark.asyncio
    async def test_shutdown_kills_claude(self, wired_app):
        wired_app._discord = MagicMock()
        wired_app._discord.send_message = AsyncMock()
        wired_app._discord.stop = AsyncMock()

        wired_app._claude = MagicMock()
        wired_app._claude.kill_current = AsyncMock(return_value=True)

        await wired_app.stop()
        wired_app._claude.kill_current.assert_called_once()


class TestCommandRouting:
    """S82: Command integration."""

    @pytest.mark.asyncio
    async def test_bridge_command_routes(self, wired_app):
        wired_app._security.log_event = AsyncMock()

        result = await wired_app._handle_command("chat-1", "ping", "")
        assert result is not None
        assert "pong" in result

    @pytest.mark.asyncio
    async def test_agent_command_enqueues(self, wired_app):
        wired_app._security.log_event = AsyncMock()

        result = await wired_app._handle_command("chat-1", "audit", "last 24h")
        assert result is not None
        assert "queued" in result.lower()

        # Verify it was enqueued
        status = await wired_app._queue.get_queue_status()
        assert status["counts"].get("pending", 0) >= 1

    @pytest.mark.asyncio
    async def test_unknown_command(self, wired_app):
        wired_app._security.log_event = AsyncMock()

        result = await wired_app._handle_command("chat-1", "nonexistent", "")
        assert "Unknown command" in result

    @pytest.mark.asyncio
    async def test_halt_command_sets_halt(self, wired_app):
        wired_app._security.log_event = AsyncMock()

        await wired_app._handle_command("chat-1", "halt", "")
        assert wired_app._halted is True

    @pytest.mark.asyncio
    async def test_resume_command_clears_halt(self, wired_app):
        wired_app._security.log_event = AsyncMock()

        await wired_app._handle_command("chat-1", "halt", "")
        assert wired_app._halted is True

        await wired_app._handle_command("chat-1", "resume", "")
        assert wired_app._halted is False


class TestNewMessage:
    """S82: New message handling."""

    @pytest.mark.asyncio
    async def test_new_message_enqueues(self, wired_app):
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()

        await wired_app._handle_new_message("chat-1", "Hello!", 100)

        status = await wired_app._queue.get_queue_status()
        assert status["counts"].get("pending", 0) >= 1

    @pytest.mark.asyncio
    async def test_new_message_sends_no_ack_for_first_position(self, wired_app):
        # Post-D-R1 (#1917) the warm path replies in 1-2s, so a
        # "Starting now." ACK for the immediate-handle case races the
        # actual response and is pure noise. Only the queued cases (active
        # turn, position > 1) get an ACK now.
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()

        await wired_app._handle_new_message("chat-1", "Hello!", 100)

        wired_app._discord.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_new_message_ack_reflects_active_turn(self, wired_app):
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()

        snap = await wired_app._invocation_controller.start(
            path="one_shot", session_id="test"
        )
        try:
            await wired_app._handle_new_message("chat-1", "Interrupt", 101)
        finally:
            await wired_app._invocation_controller.finish(snap.invocation_id)

        wired_app._discord.send_message.assert_awaited_once_with(
            "chat-1",
            "Received. Queued behind the active turn.",
            reply_to=101,
        )

    @pytest.mark.asyncio
    async def test_halted_rejects_messages(self, wired_app):
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()
        wired_app._halted = True

        await wired_app._handle_new_message("chat-1", "Hello!", 100)

        # Should have sent "halted" message, not enqueued
        wired_app._discord.send_message.assert_called()
        call_args = wired_app._discord.send_message.call_args
        assert "halted" in call_args[0][1].lower()

    @pytest.mark.asyncio
    async def test_response_latency_watchdog_sends_processing_notice(
        self, wired_app, monkeypatch
    ):
        wired_app._discord.send_message = AsyncMock()
        wired_app._config = replace(
            wired_app._config,
            discord_first_response_sla_seconds=1,
            discord_progress_interval_seconds=0,
        )

        async def fast_sleep(_seconds):
            return None

        monkeypatch.setattr("bridge.app.asyncio.sleep", fast_sleep)
        msg = QueuedMessage(
            id=1,
            platform_message_id=102,
            chat_id="chat-1",
            text="long task",
            received_at="2026-05-13T00:00:00Z",
            status="processing",
            attempt_count=0,
        )

        await wired_app._response_latency_watchdog(msg)

        wired_app._discord.send_message.assert_awaited_once_with(
            "chat-1",
            "Still working on this. No final answer yet.",
            reply_to=102,
        )


class TestOperatorInboxWiring:
    """D7.9 #1421 (slice 2) — BridgeApp instantiates and wires the operator
    inbox so the slice-1 mid-stream interrupt can fire.
    """

    @pytest.mark.asyncio
    async def test_initialize_wires_inbox_to_runner(self, wired_app):
        """After _initialize, the runner's _operator_inbox is set to the
        same OperatorInbox instance the app exposes via _operator_inbox.
        """
        from bridge.operator_inbox import OperatorInbox

        assert wired_app._operator_inbox is not None
        assert isinstance(wired_app._operator_inbox, OperatorInbox)
        assert wired_app._claude._operator_inbox is wired_app._operator_inbox

    @pytest.mark.asyncio
    async def test_idle_message_skips_inbox(self, wired_app):
        """When no invocation is in flight, _handle_new_message must NOT
        feed the inbox — otherwise the next-spawn gate would block the
        message we're about to dequeue and process.
        """
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()

        # Lock is NOT held (no invocation running)
        assert not wired_app._claude._lock.locked()

        await wired_app._handle_new_message("chat-1", "Hello!", 100)

        pending = await wired_app._operator_inbox.pending()
        assert pending == [], (
            f"inbox should be empty after idle-state receive; got {pending}"
        )

    @pytest.mark.asyncio
    async def test_in_flight_message_feeds_inbox(self, wired_app):
        """When an invocation is in flight, the message lands in the inbox
        so the slice-1 mid-stream check picks it up.

        P1.1: the in-flight signal now consults the InvocationController
        (which both one-shot and warm paths feed) rather than the
        one-shot runner's lock directly. Test simulates in-flight state
        by starting the controller.
        """
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()

        # P1.1 — simulate an in-flight invocation via the controller.
        snap = await wired_app._invocation_controller.start(
            path="one_shot", session_id="test"
        )
        try:
            await wired_app._handle_new_message(
                "chat-1", "the operator here — please pause", 100
            )
        finally:
            await wired_app._invocation_controller.finish(snap.invocation_id)

        pending = await wired_app._operator_inbox.pending()
        assert len(pending) == 1
        assert pending[0].content == "the operator here — please pause"

    @pytest.mark.asyncio
    async def test_warm_path_in_flight_message_feeds_inbox(self, wired_app):
        """P1.1 (audit C1) regression guard.

        Pre-P1.1, the in-flight check looked at
        ``self._claude._lock.locked()`` — the one-shot runner's lock.
        Warm-path invocations were invisible to this check, so an
        operator message arriving while WarmClaudeProcess.send_message
        was in flight would silently bypass the inbox-receive call and
        the operator interrupt would be lost.

        With the InvocationController, BOTH paths feed the same signal.
        This test simulates the warm-path scenario: track an invocation
        with path="warm" and verify the inbox still receives.
        """
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()

        snap = await wired_app._invocation_controller.start(
            path="warm", session_id="warm-test"
        )
        try:
            await wired_app._handle_new_message(
                "chat-1", "halt — warm path interrupt test", 200
            )
        finally:
            await wired_app._invocation_controller.finish(snap.invocation_id)

        pending = await wired_app._operator_inbox.pending()
        assert len(pending) == 1, (
            "P1.1 regression: warm-path in-flight invocation must trigger "
            "inbox receive — but didn't."
        )
        assert pending[0].content == "halt — warm path interrupt test"

    @pytest.mark.asyncio
    async def test_message_always_enqueued_regardless_of_inbox_path(
        self, wired_app
    ):
        """The inbox is for *interrupt signaling*, not message delivery.
        Whether the inbox receives or not, the message MUST always land
        in the queue so the bridge processes it on the next dequeue.
        """
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()

        # In-flight branch: lock held, inbox should receive AND queue should grow
        await wired_app._claude._lock.acquire()
        try:
            await wired_app._handle_new_message("chat-1", "while-busy", 100)
        finally:
            wired_app._claude._lock.release()

        status = await wired_app._queue.get_queue_status()
        # The exact message ended up in the queue
        assert status["counts"].get("pending", 0) >= 1

    @pytest.mark.asyncio
    async def test_block_message_delivery_auto_acks_inbox(
        self, wired_app, mock_claude_result
    ):
        """When _process_single_message delivers a TOOL CALL BLOCKED
        response, the inbox is auto-acked so the next dequeue isn't
        re-blocked. The agent does NOT need to emit [ACK:msg_id] in
        this slice — the bridge handles the contract.
        """
        from bridge.operator_inbox import MessageSeverity

        # Pre-load the inbox with a pending message (simulating what
        # the slice-1 mid-stream interrupt would have left behind).
        await wired_app._operator_inbox.receive(
            "the operator sent this mid-flight",
            MessageSeverity.QUESTION,
        )
        pending_before = await wired_app._operator_inbox.pending()
        assert len(pending_before) == 1

        # The slice-1 runner returns a result whose response_text starts
        # with "TOOL CALL BLOCKED". Mock the invoke chain to mimic that.
        result = mock_claude_result(
            response_text=(
                "TOOL CALL BLOCKED — OPERATOR QUESTION PENDING\n\n"
                "1 QUESTION message(s) from the operator are pending..."
            ),
            is_error=False,
        )
        wired_app._discord._start_typing = MagicMock()
        wired_app._discord._stop_typing = MagicMock()
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()
        wired_app._security.check_anomalies = AsyncMock(return_value=[])
        wired_app._claude.invoke = AsyncMock(return_value=result)

        msg = QueuedMessage(
            id=1, platform_message_id=100, chat_id="chat-1",
            text="prior message", received_at="2025-01-01T00:00:00",
            status="processing", attempt_count=1,
        )

        await wired_app._process_single_message(msg)

        # Discord saw the BLOCK message — that's the within-5s ack that
        # acceptance criterion #1 calls for.
        wired_app._discord.send_message.assert_called()
        # Inbox is now empty — the next dequeue won't re-block.
        pending_after = await wired_app._operator_inbox.pending()
        assert pending_after == [], (
            f"inbox should be empty after BLOCK delivery; got {pending_after}"
        )

    @pytest.mark.asyncio
    async def test_normal_response_does_not_ack_inbox(
        self, wired_app, mock_claude_result
    ):
        """A regular (non-BLOCK) response must NOT touch the inbox — only
        BLOCK messages trigger auto-ACK.
        """
        from bridge.operator_inbox import MessageSeverity

        await wired_app._operator_inbox.receive("background msg", MessageSeverity.INFO)

        result = mock_claude_result(response_text="Here's your answer.")
        wired_app._discord._start_typing = MagicMock()
        wired_app._discord._stop_typing = MagicMock()
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()
        wired_app._security.check_anomalies = AsyncMock(return_value=[])
        wired_app._claude.invoke = AsyncMock(return_value=result)

        msg = QueuedMessage(
            id=1, platform_message_id=100, chat_id="chat-1",
            text="some prompt", received_at="2025-01-01T00:00:00",
            status="processing", attempt_count=1,
        )

        await wired_app._process_single_message(msg)

        # Inbox is untouched — the auto-ACK is BLOCK-message-conditional.
        pending = await wired_app._operator_inbox.pending()
        assert len(pending) == 1, (
            f"non-BLOCK response should not auto-ACK; got {pending}"
        )


class TestChiefDispatcherWiring:
    """Z4-S22 #1395 — `chief_dispatcher_enabled` flag gates the dispatcher
    trio (store + router + dispatcher) at startup. Default off; existing
    bridge startup unaffected.
    """

    @pytest.mark.asyncio
    async def test_default_flag_off_leaves_stack_unwired(self, wired_app):
        """With the default config (flag=False), all three attributes
        remain None. The api_server reads `_chief_session_store` via
        getattr and stays in 503-on-the-/api/chief_sessions path.
        """
        assert wired_app._config.chief_dispatcher_enabled is False
        assert wired_app._chief_session_store is None
        assert wired_app._chief_router is None
        assert wired_app._chief_dispatcher is None

    @pytest.mark.asyncio
    async def test_flag_on_instantiates_full_stack(
        self, tmp_path, sample_config_toml, mock_keyring
    ):
        """When the flag is True, _initialize() creates SQLiteChiefSessionStore
        + RuleBasedWorkOrderRouter + ChiefDispatcher. The instances are
        live and wired to each other.
        """
        # Patch the TOML file to enable the dispatcher
        toml_text = sample_config_toml.read_text()
        toml_text += "\n[chief_dispatcher]\nenabled = true\n"
        sample_config_toml.write_text(toml_text)

        from bridge.app import BridgeApp
        from bridge.chief_session_store import SQLiteChiefSessionStore
        from bridge.work_order_router import RuleBasedWorkOrderRouter
        from bridge.chief_dispatcher import ChiefDispatcher

        app = BridgeApp(config_path=str(sample_config_toml))
        try:
            await app._initialize()
            assert app._config.chief_dispatcher_enabled is True
            assert isinstance(app._chief_session_store, SQLiteChiefSessionStore)
            assert isinstance(app._chief_router, RuleBasedWorkOrderRouter)
            assert isinstance(app._chief_dispatcher, ChiefDispatcher)
            # Sanity-check: dispatcher's deps are wired to the same instances
            assert app._chief_dispatcher._store is app._chief_session_store
            assert app._chief_dispatcher._router is app._chief_router
        finally:
            if app._db:
                await app._db.close()

    @pytest.mark.asyncio
    async def test_idle_timeout_default_is_4_hours(self, wired_app):
        """The default idle-timeout for the Z4 reaper is 14400s (4h).

        Was 1800s (30 min) up through Phase 3 of zone4-warmth; extended
        to 4 hours in D.01 (#2299) to match the warm-reuse intent. Per-
        team overrides in YAML can shorten this for high-churn departments
        (Ops/JobSearch at 10 min).
        """
        assert wired_app._config.chief_dispatcher_idle_timeout_seconds == 14400.0

    @pytest.mark.asyncio
    async def test_default_department_is_strategy(self, wired_app):
        """Default fallback dept is 'strategy' — matches RuleBasedWorkOrderRouter
        Tier-4 default. Pinned so a config-load test catches drift.
        """
        assert wired_app._config.chief_dispatcher_default_department == "strategy"


class TestChiefSessionShutdownSweep:
    """Z4-S32 #1394 — `_shutdown_all_chief_sessions` sweeps active rows
    on `BridgeApp.stop()` so no session is orphaned in a non-SHUTDOWN
    state when the bridge exits.
    """

    @pytest.mark.asyncio
    async def test_no_op_when_dispatcher_not_wired(self, wired_app):
        """Default config (flag off) → helper is a no-op (returns
        without raising). Default `_chief_session_store` and
        `_chief_dispatcher` are None.
        """
        # Should not raise
        await wired_app._shutdown_all_chief_sessions()
        # And should not have touched anything
        assert wired_app._chief_session_store is None
        assert wired_app._chief_dispatcher is None

    @pytest.mark.asyncio
    async def test_sweeps_all_non_shutdown_states(self, wired_app):
        """Stub the store + dispatcher with mocks. The helper must
        call `list_by_state` for every non-SHUTDOWN state and
        `shutdown_session` for every returned row.
        """
        from unittest.mock import AsyncMock, MagicMock
        from bridge.chief_session import ChiefSession, ChiefSessionState

        # Build three sessions in different states
        s1 = ChiefSession(
            session_id="cs-aaaa", work_order_id="wo-1",
            department="strategy", chief_name="strategy-chief",
            state=ChiefSessionState.EXECUTING,
        )
        s2 = ChiefSession(
            session_id="cs-bbbb", work_order_id="wo-2",
            department="ops", chief_name="ops-chief",
            state=ChiefSessionState.AWAITING_EVALUATION,
        )
        s3 = ChiefSession(
            session_id="cs-cccc", work_order_id="wo-3",
            department="qa", chief_name="qa-chief",
            state=ChiefSessionState.COLD,
        )

        # Mock store: list_by_state returns the right session per state,
        # empty list for everything else
        store = MagicMock()
        async def fake_list(state):
            if state == ChiefSessionState.EXECUTING:
                return [s1]
            if state == ChiefSessionState.AWAITING_EVALUATION:
                return [s2]
            if state == ChiefSessionState.COLD:
                return [s3]
            return []
        store.list_by_state = fake_list

        # Mock dispatcher: shutdown_session is called for each session
        dispatcher = MagicMock()
        dispatcher.shutdown_session = AsyncMock()

        wired_app._chief_session_store = store
        wired_app._chief_dispatcher = dispatcher

        await wired_app._shutdown_all_chief_sessions()

        # All three sessions should have been shut down
        assert dispatcher.shutdown_session.await_count == 3
        called_ids = {
            call.args[0]
            for call in dispatcher.shutdown_session.await_args_list
        }
        assert called_ids == {"cs-aaaa", "cs-bbbb", "cs-cccc"}
        # Reason is "bridge exit"
        for call in dispatcher.shutdown_session.await_args_list:
            assert call.args[1] == "bridge exit"

    @pytest.mark.asyncio
    async def test_shutdown_idempotent_on_already_shutdown_sessions(
        self, wired_app
    ):
        """Already-SHUTDOWN sessions are filtered out by the
        active_states list (SHUTDOWN is not in it). The helper must
        never try to call `shutdown_session` on a row that's already
        terminal.
        """
        from unittest.mock import AsyncMock, MagicMock

        store = MagicMock()
        async def fake_list(state):
            return []  # nothing in any active state
        store.list_by_state = fake_list

        dispatcher = MagicMock()
        dispatcher.shutdown_session = AsyncMock()

        wired_app._chief_session_store = store
        wired_app._chief_dispatcher = dispatcher

        await wired_app._shutdown_all_chief_sessions()

        # Nothing to shut down → dispatcher never called
        dispatcher.shutdown_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_one_session_failure_does_not_stop_loop(self, wired_app):
        """If `shutdown_session` raises on one session, the helper logs
        a warning and continues to the next. Best-effort per row.
        """
        from unittest.mock import AsyncMock, MagicMock
        from bridge.chief_session import ChiefSession, ChiefSessionState

        s1 = ChiefSession(
            session_id="cs-fail", work_order_id="wo-1",
            department="strategy", chief_name="x",
            state=ChiefSessionState.EXECUTING,
        )
        s2 = ChiefSession(
            session_id="cs-ok", work_order_id="wo-2",
            department="strategy", chief_name="x",
            state=ChiefSessionState.EXECUTING,
        )

        store = MagicMock()
        async def fake_list(state):
            return [s1, s2] if state == ChiefSessionState.EXECUTING else []
        store.list_by_state = fake_list

        dispatcher = MagicMock()

        # First call raises, second succeeds
        async def fake_shutdown(sid, reason):
            if sid == "cs-fail":
                raise RuntimeError("network down")
        dispatcher.shutdown_session = AsyncMock(side_effect=fake_shutdown)

        wired_app._chief_session_store = store
        wired_app._chief_dispatcher = dispatcher

        # Should not raise — best-effort per row
        await wired_app._shutdown_all_chief_sessions()

        # Both sessions were attempted (the failure didn't abort the loop)
        assert dispatcher.shutdown_session.await_count == 2

    @pytest.mark.asyncio
    async def test_list_by_state_failure_does_not_stop_other_states(
        self, wired_app
    ):
        """If `list_by_state(EXECUTING)` raises, we log + continue to
        the other states. The store's lookup is best-effort per state.
        """
        from unittest.mock import AsyncMock, MagicMock
        from bridge.chief_session import ChiefSession, ChiefSessionState

        s_cold = ChiefSession(
            session_id="cs-cold", work_order_id="wo-1",
            department="strategy", chief_name="x",
            state=ChiefSessionState.COLD,
        )

        store = MagicMock()
        async def fake_list(state):
            if state == ChiefSessionState.EXECUTING:
                raise RuntimeError("store boom")
            if state == ChiefSessionState.COLD:
                return [s_cold]
            return []
        store.list_by_state = fake_list

        dispatcher = MagicMock()
        dispatcher.shutdown_session = AsyncMock()

        wired_app._chief_session_store = store
        wired_app._chief_dispatcher = dispatcher

        await wired_app._shutdown_all_chief_sessions()

        # The COLD session was still shut down despite the EXECUTING error
        assert dispatcher.shutdown_session.await_count == 1
        assert dispatcher.shutdown_session.await_args.args[0] == "cs-cold"


class TestMessageProcessing:
    """S79-S80: Message processing and error handling."""

    @pytest.mark.asyncio
    async def test_process_single_message_happy_path(self, wired_app, mock_claude_result):
        result = mock_claude_result(response_text="Hello from Claude!")

        wired_app._discord._start_typing = MagicMock()
        wired_app._discord._stop_typing = MagicMock()
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()
        wired_app._security.check_anomalies = AsyncMock(return_value=[])

        # Mock claude invoke
        wired_app._claude.invoke = AsyncMock(return_value=result)

        # Create a queued message
        msg = QueuedMessage(
            id=1, platform_message_id=100, chat_id="chat-1",
            text="What is 2+2?", received_at="2025-01-01T00:00:00",
            status="processing", attempt_count=1,
        )

        await wired_app._process_single_message(msg)

        # Claude was invoked
        wired_app._claude.invoke.assert_called_once()

        # Response was sent
        wired_app._discord.send_message.assert_called()

        # Typing stopped
        wired_app._discord._stop_typing.assert_called_with("chat-1")

    @pytest.mark.asyncio
    async def test_process_message_auth_error_halts(self, wired_app, mock_claude_result):
        result = mock_claude_result(
            is_error=True, error_type="auth",
            stderr_output="auth token expired",
        )

        wired_app._discord._start_typing = MagicMock()
        wired_app._discord._stop_typing = MagicMock()
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()
        wired_app._security.check_anomalies = AsyncMock(return_value=[])
        wired_app._claude.invoke = AsyncMock(return_value=result)

        msg = QueuedMessage(
            id=1, platform_message_id=100, chat_id="chat-1",
            text="test", received_at="2025-01-01T00:00:00",
            status="processing", attempt_count=1,
        )

        await wired_app._process_single_message(msg)
        assert wired_app._halted is True

    @pytest.mark.asyncio
    async def test_process_message_rate_limit_retries(self, wired_app, mock_claude_result):
        result = mock_claude_result(
            is_error=True, error_type="rate_limit",
        )

        wired_app._discord._start_typing = MagicMock()
        wired_app._discord._stop_typing = MagicMock()
        wired_app._discord.send_message = AsyncMock()
        wired_app._security.log_event = AsyncMock()
        wired_app._security.check_anomalies = AsyncMock(return_value=[])
        wired_app._claude.invoke = AsyncMock(return_value=result)
        # Set shutdown event immediately to avoid the backoff wait
        wired_app._shutdown_event.set()

        msg = QueuedMessage(
            id=1, platform_message_id=100, chat_id="chat-1",
            text="test", received_at="2025-01-01T00:00:00",
            status="processing", attempt_count=1,
        )

        # Enqueue the message first so retry can find it
        await wired_app._queue.enqueue(100, "chat-1", "test")

        await wired_app._process_single_message(msg)

        # Message should be retried (set back to pending)
        # The rate_limit notification was sent
        wired_app._discord.send_message.assert_called()


class TestMainEntry:
    """S83: __main__.py entry point."""

    def test_parse_args_defaults(self):
        from bridge.__main__ import parse_args
        args = parse_args([])
        assert args.config is None
        assert args.log_level == "INFO"

    def test_parse_args_custom(self):
        from bridge.__main__ import parse_args
        args = parse_args(["--config", "/tmp/test.toml", "--log-level", "DEBUG"])
        assert args.config == "/tmp/test.toml"
        assert args.log_level == "DEBUG"

    def test_setup_logging(self, tmp_path):
        from bridge.__main__ import setup_logging
        import logging

        setup_logging("DEBUG", str(tmp_path))

        log_file = tmp_path / "bridge.log"
        assert log_file.exists()

        # Cleanup handlers to avoid interfering with other tests + close any
        # open file streams (S6.2, #2352): handlers attached by setup_logging
        # own a FileHandler whose stream stays open until close() is called.
        root = logging.getLogger()
        for h in root.handlers[:]:
            try:
                h.close()
            except Exception:
                pass
            root.removeHandler(h)


class TestDispatcherBranch:
    """Z3.10: Dispatcher feature-flag wiring in _invoke_claude.

    Post-D-R2 (#1932): messages must classify into ``ZONE4_INTENTS`` with
    confidence >= ``DISPATCHER_MIN_CONFIDENCE`` to enter the dispatcher
    branch. The fixture message below uses ``/board`` which classifies as
    ``BOARD_QUERY`` with confidence 1.0 — the canonical "Zone 4 chief"
    shape these tests are written to exercise. Pre-D-R2 the fixture was
    ``"Do something interesting"`` which classified as UNKNOWN and would
    no longer pass the gate.
    """

    def _make_msg(self):
        return QueuedMessage(
            id=1,
            platform_message_id=100,
            chat_id="chat-1",
            text="/board debate the architecture",
            received_at="2025-01-01T00:00:00",
            status="processing",
            attempt_count=1,
        )

    def _setup_discord(self, app):
        app._discord._start_typing = MagicMock()
        app._discord._stop_typing = MagicMock()
        app._discord.send_message = AsyncMock()
        app._security.log_event = AsyncMock()
        app._security.check_anomalies = AsyncMock(return_value=[])

    @pytest.mark.asyncio
    async def test_dispatcher_flag_off_bypasses_dispatcher(self, wired_app, mock_claude_result):
        """When dispatcher_enabled=False the Dispatcher.dispatch is never called."""
        from unittest.mock import AsyncMock as _AsyncMock
        from bridge.dispatcher import Dispatcher, DispatchResult

        result = mock_claude_result(response_text="Direct response")
        self._setup_discord(wired_app)
        wired_app._claude.invoke = AsyncMock(return_value=result)

        # Ensure flag is off (it is by default, but be explicit)
        import dataclasses
        wired_app._config = dataclasses.replace(wired_app._config, dispatcher_enabled=False)

        mock_dispatcher = MagicMock(spec=Dispatcher)
        mock_dispatcher.dispatch = _AsyncMock(
            return_value=DispatchResult(valid=True, handled=True, result=result, reason="should not be called")
        )
        wired_app._dispatcher = mock_dispatcher

        msg = self._make_msg()
        await wired_app._process_single_message(msg)

        # Dispatcher must NOT have been called when flag is off
        mock_dispatcher.dispatch.assert_not_called()
        # But Claude was invoked directly
        wired_app._claude.invoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatcher_flag_on_handled_true_returns_result(self, wired_app, mock_claude_result):
        """When dispatcher_enabled=True and handled=True, the dispatcher result is used."""
        import dataclasses
        from bridge.dispatcher import Dispatcher, DispatchResult

        dispatcher_result = mock_claude_result(response_text="Handled by dispatcher")
        self._setup_discord(wired_app)

        # Flag on
        wired_app._config = dataclasses.replace(wired_app._config, dispatcher_enabled=True)

        mock_dispatcher = MagicMock(spec=Dispatcher)
        mock_dispatcher.dispatch = AsyncMock(
            return_value=DispatchResult(
                valid=True,
                handled=True,
                result=dispatcher_result,
                reason="subagent completed",
            )
        )
        wired_app._dispatcher = mock_dispatcher

        # Direct claude.invoke should NOT be called when dispatcher handles it
        wired_app._claude.invoke = AsyncMock(return_value=mock_claude_result(response_text="Should not appear"))

        msg = self._make_msg()
        await wired_app._process_single_message(msg)

        # Dispatcher was called
        mock_dispatcher.dispatch.assert_called_once()
        # Claude direct invoke was NOT called (dispatcher handled it)
        wired_app._claude.invoke.assert_not_called()
        # Response was delivered (send_message called with dispatcher result text)
        wired_app._discord.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_dispatcher_flag_on_handled_false_falls_through(self, wired_app, mock_claude_result):
        """When dispatcher_enabled=True but handled=False, direct Claude invoke still runs."""
        import dataclasses
        from bridge.dispatcher import Dispatcher, DispatchResult

        direct_result = mock_claude_result(response_text="Direct fallthrough response")
        self._setup_discord(wired_app)

        # Flag on
        wired_app._config = dataclasses.replace(wired_app._config, dispatcher_enabled=True)

        mock_dispatcher = MagicMock(spec=Dispatcher)
        mock_dispatcher.dispatch = AsyncMock(
            return_value=DispatchResult(
                valid=True,
                handled=False,  # Dispatcher chose not to handle — fallthrough required
                result=None,
                reason="No runner configured — caller must fall through",
            )
        )
        wired_app._dispatcher = mock_dispatcher

        wired_app._claude.invoke = AsyncMock(return_value=direct_result)

        msg = self._make_msg()
        await wired_app._process_single_message(msg)

        # Dispatcher was called
        mock_dispatcher.dispatch.assert_called_once()
        # Fallthrough invariant: direct Claude invoke DID run
        wired_app._claude.invoke.assert_called_once()
        # And the response was delivered
        wired_app._discord.send_message.assert_called()


# ---------------------------------------------------------------------------
# Sprint 04.01 — Board skill via _INTENT_SKILL_MAP end-to-end.
# ---------------------------------------------------------------------------


def test_intent_skill_map_produces_board_skill() -> None:
    """``Intent.BOARD_QUERY`` must look up to skill string ``"board-query"``.

    Pre-fix: _INTENT_SKILL_MAP had no entry for board_query, so the dispatcher
    fell through to the default ``"chat"`` skill — which classifies as
    readonly/SUBAGENT and never reaches the Zone 4 Board department.

    Post-fix: ``Intent.BOARD_QUERY.value`` ("board_query") maps to
    ``"board-query"``, which then hits ``_SKILL_CLASS_RULES`` "board" prefix
    and routes to ``Environment.DEPARTMENT`` via EnvironmentSelector.
    """
    from bridge.app import _INTENT_SKILL_MAP, _intent_to_skill
    from bridge.command_router import Intent

    # Direct map lookup — the keystone of the sprint.
    assert _INTENT_SKILL_MAP["board_query"] == "board-query"

    # The resolver helper that the dispatcher branch calls must produce the
    # same answer when given Intent.BOARD_QUERY.value.
    assert _intent_to_skill(Intent.BOARD_QUERY.value) == "board-query"

    # Sanity: unknown intents still fall back to "chat" (the default).
    assert _intent_to_skill("not_a_real_intent") == "chat"


# ---------------------------------------------------------------------------
# Sprint 04.02 — broaden _INTENT_SKILL_MAP to QA / Ops / Strategy / Design.
# Mirrors test_intent_skill_map_produces_board_skill above for the four
# remaining departments. Each new intent must look up to a skill string that
# (a) starts with the dept prefix in EnvironmentSelector._SKILL_CLASS_RULES
# and (b) cannot drift away from Intent.<NAME>.value.
# ---------------------------------------------------------------------------


def test_intent_skill_map_produces_qa_review_skill() -> None:
    """``Intent.QA_REVIEW`` must look up to skill string ``"qa-review"``.

    The "qa-review" skill string passes _SKILL_CLASS_RULES "qa-" prefix
    → Environment.DEPARTMENT, then _derive_department returns "qa".
    """
    from bridge.app import _INTENT_SKILL_MAP, _intent_to_skill
    from bridge.command_router import Intent

    assert _INTENT_SKILL_MAP["qa_review"] == "qa-review"
    assert _intent_to_skill(Intent.QA_REVIEW.value) == "qa-review"


def test_intent_skill_map_produces_ops_diagnose_skill() -> None:
    """``Intent.OPS_DIAGNOSE`` must look up to skill string ``"ops-diagnose"``."""
    from bridge.app import _INTENT_SKILL_MAP, _intent_to_skill
    from bridge.command_router import Intent

    assert _INTENT_SKILL_MAP["ops_diagnose"] == "ops-diagnose"
    assert _intent_to_skill(Intent.OPS_DIAGNOSE.value) == "ops-diagnose"


def test_intent_skill_map_produces_strategy_analyze_skill() -> None:
    """``Intent.STRATEGY_ANALYZE`` must look up to skill string ``"strategy-analyze"``.

    Note: "strategy-analyze" contains the substring "analyze" (a readonly
    rule) but the "strategy" department prefix appears earlier in
    _SKILL_CLASS_RULES, so first-match-wins keeps it as "department".
    """
    from bridge.app import _INTENT_SKILL_MAP, _intent_to_skill
    from bridge.command_router import Intent

    assert _INTENT_SKILL_MAP["strategy_analyze"] == "strategy-analyze"
    assert _intent_to_skill(Intent.STRATEGY_ANALYZE.value) == "strategy-analyze"


def test_intent_skill_map_produces_design_review_skill() -> None:
    """``Intent.DESIGN_REVIEW`` must look up to skill string ``"design-review"``.

    Same first-match-wins guarantee as strategy: "design-review" contains
    "review" (a readonly rule) but "design" appears earlier so the skill
    classifies as department.
    """
    from bridge.app import _INTENT_SKILL_MAP, _intent_to_skill
    from bridge.command_router import Intent

    assert _INTENT_SKILL_MAP["design_review"] == "design-review"
    assert _intent_to_skill(Intent.DESIGN_REVIEW.value) == "design-review"


# ---------- D1.10: feature_cost_caps_enabled + board_v2_enabled wiring ----------


class TestCostTrackerConfigWiring:
    """BridgeApp must thread feature_cost_caps_enabled and board_v2_enabled
    from BridgeConfig into CostTracker at construction time (D1.10 #1182)."""

    @pytest.mark.asyncio
    async def test_default_flags_disabled(self, wired_app):
        # Default config has no [cost] section → both flags False.
        assert wired_app._cost_tracker._feature_caps_enabled is False

    @pytest.mark.asyncio
    async def test_feature_caps_enabled_flag_threaded(
        self, tmp_path, tmp_dirs, mock_keyring
    ):
        toml_path = tmp_path / "bridge_caps.toml"
        toml_path.write_text(
            f"""
[bridge]
data_dir = "{tmp_dirs['data_dir']}"
log_dir = "{tmp_dirs['log_dir']}"
[claude]
working_dir = "{tmp_dirs['working_dir']}"
[cost]
feature_caps_enabled = true
"""
        )
        app = BridgeApp(config_path=str(toml_path))
        await app._initialize()
        try:
            assert app._cost_tracker._feature_caps_enabled is True
        finally:
            if app._db:
                await app._db.close()
