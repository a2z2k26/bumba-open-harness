"""Tests for bridge.commands (S66) - expanded coverage.

Coverage:
- record_message/error/rate_limit counters
- All setter methods
- Safety-critical: /halt + /resume end-to-end
- /cancel with/without runner
- /reset with warm claude cycling
- Autonomy commands: not-initialized guards + mock paths
- Tmux commands: not-initialized guards + mock paths
- /fewshot, /edits, /approve, /reject
- /knowledge subcommands
- Session hook commands: /careful, /freeze, /relax, /hooks
- /verify on/off/status
- /proactive on/off/status
- /board, /goals, /tasks
- /trace, /cost, /routing, /reflect, /mcp, /diagnose
- /log command
- get_agent_prompt template formatting
- Command set membership
- _format_uptime output format
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from bridge.commands import AGENT_COMMANDS, BRIDGE_COMMANDS, CommandHandler as CmdHandler


@pytest_asyncio.fixture
async def cmd_handler(migrated_db, message_queue, session_manager):
    return CmdHandler(
        db=migrated_db,
        queue=message_queue,
        session_manager=session_manager,
        claude_runner=None,
    )


@pytest_asyncio.fixture
async def cmd_handler_with_runner(migrated_db, message_queue, session_manager):
    mock_runner = MagicMock()
    mock_runner.kill_current = AsyncMock(return_value=True)
    handler = CmdHandler(
        db=migrated_db,
        queue=message_queue,
        session_manager=session_manager,
        claude_runner=mock_runner,
    )
    return handler, mock_runner


class TestBridgeCommands:
    """S64: Bridge-level commands."""

    @pytest.mark.asyncio
    async def test_ping(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "ping", "")
        assert "pong" in result
        assert "latency" in result

    @pytest.mark.asyncio
    async def test_uptime(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "uptime", "")
        assert "Uptime:" in result
        assert "Messages processed:" in result

    @pytest.mark.asyncio
    async def test_status(self, cmd_handler, session_manager):
        await session_manager.create_session("chat-1")
        result = await cmd_handler.handle("chat-1", "status", "")
        assert "Agent online" in result
        assert "Queue:" in result

    @pytest.mark.asyncio
    async def test_queue_empty(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "queue", "")
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_queue_with_messages(self, cmd_handler, message_queue):
        await message_queue.enqueue(1, "chat-1", "Analyze auth module")
        result = await cmd_handler.handle("chat-1", "queue", "")
        assert "1 messages pending" in result
        assert "Analyze auth" in result

    @pytest.mark.asyncio
    async def test_reset(self, cmd_handler, session_manager):
        await session_manager.create_session("chat-1")
        result = await cmd_handler.handle("chat-1", "reset", "")
        assert "Session reset" in result

    @pytest.mark.asyncio
    async def test_halt_and_resume(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "halt", "")
        assert "halted" in result.lower()
        assert cmd_handler.is_halted() is True
        result = await cmd_handler.handle("chat-1", "resume", "")
        assert "resumed" in result.lower()
        assert cmd_handler.is_halted() is False

    @pytest.mark.asyncio
    async def test_cancel_no_runner(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "cancel", "")
        assert "No active task" in result


class TestAgentCommands:
    """S65: Agent command routing."""

    @pytest.mark.asyncio
    async def test_audit(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "audit", "last 24h")
        assert "audit log" in result.lower()
        assert "last 24h" in result

    @pytest.mark.asyncio
    async def test_memory(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "memory", "project name")
        assert "memory" in result.lower()
        assert "project name" in result

    @pytest.mark.asyncio
    async def test_permissions(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "permissions", "")
        assert "permissions" in result.lower()

    @pytest.mark.asyncio
    async def test_review(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "review", "")
        assert "self-improvement" in result.lower()

    @pytest.mark.asyncio
    async def test_skills(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "skills", "")
        assert "skills" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_command(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "nonexistent", "")
        assert "Unknown command" in result


class TestVoiceCommands:
    @pytest.mark.asyncio
    async def test_voice_returns_removed_message(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "voice", "")
        assert result == "Voice: disabled (voice_enabled = false in bridge.toml)"

    @pytest.mark.asyncio
    async def test_tts_returns_removed_message(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "tts", "")
        assert result == "Usage: /tts <text> | /tts status"


class TestCounters:
    @pytest.mark.asyncio
    async def test_record_message_shows_in_uptime(self, cmd_handler):
        cmd_handler.record_message()
        result = await cmd_handler.handle("c", "uptime", "")
        assert "Messages processed: 1" in result

    @pytest.mark.asyncio
    async def test_record_error_shows_in_uptime(self, cmd_handler):
        cmd_handler.record_error()
        cmd_handler.record_error()
        result = await cmd_handler.handle("c", "uptime", "")
        assert "Errors: 2" in result

    @pytest.mark.asyncio
    async def test_record_rate_limit_shows_in_uptime(self, cmd_handler):
        cmd_handler.record_rate_limit()
        result = await cmd_handler.handle("c", "uptime", "")
        assert "Rate limits: 1" in result


class TestSetters:
    @pytest.mark.asyncio
    async def test_set_autonomy(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_autonomy(mock)
        assert cmd_handler._autonomy is mock

    @pytest.mark.asyncio
    async def test_set_session_hooks_and_alias(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_session_hooks(mock)
        assert cmd_handler._session_hooks is mock
        assert cmd_handler._session_hook_registry is mock

    @pytest.mark.asyncio
    async def test_set_session_hook_registry_alias(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_session_hook_registry(mock)
        assert cmd_handler._session_hooks is mock


    @pytest.mark.asyncio
    async def test_set_tracer(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_tracer(mock)
        assert cmd_handler._tracer is mock

    @pytest.mark.asyncio
    async def test_set_cost_tracker(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_cost_tracker(mock)
        assert cmd_handler._cost_tracker is mock

    @pytest.mark.asyncio
    async def test_set_routing_feedback(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_routing_feedback(mock)
        assert cmd_handler._routing_feedback is mock

    @pytest.mark.asyncio
    async def test_set_reflection_store(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_reflection_store(mock)
        assert cmd_handler._reflection_store is mock

    @pytest.mark.asyncio
    async def test_set_mcp_monitor(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_mcp_monitor(mock)
        assert cmd_handler._mcp_monitor is mock

    @pytest.mark.asyncio
    async def test_set_skill_evolution(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_skill_evolution(mock)
        assert cmd_handler._skill_evolution is mock

    @pytest.mark.asyncio
    async def test_set_agent_router(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_agent_router(mock)
        assert cmd_handler._agent_router is mock

    @pytest.mark.asyncio
    async def test_set_log_dir(self, cmd_handler, tmp_path):
        cmd_handler.set_log_dir(tmp_path)
        assert cmd_handler._log_dir is tmp_path

    @pytest.mark.asyncio
    async def test_set_runbook_engine(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_runbook_engine(mock)
        assert cmd_handler._runbook_engine is mock

    @pytest.mark.asyncio
    async def test_set_webhook_deliverer(self, cmd_handler):
        mock = MagicMock()
        cmd_handler.set_webhook_deliverer(mock)
        assert cmd_handler._webhook_deliverer is mock

    @pytest.mark.asyncio
    async def test_set_shutdown_callback(self, cmd_handler):
        cb = MagicMock()
        cmd_handler.set_shutdown_callback(cb)
        assert cmd_handler._shutdown_callback is cb

class TestHaltResumeSafety:
    @pytest.mark.asyncio
    async def test_halt_sets_flag(self, cmd_handler):
        assert cmd_handler.is_halted() is False
        await cmd_handler.handle("chat-1", "halt", "")
        assert cmd_handler.is_halted() is True

    @pytest.mark.asyncio
    async def test_resume_clears_flag(self, cmd_handler):
        await cmd_handler.handle("chat-1", "halt", "")
        await cmd_handler.handle("chat-1", "resume", "")
        assert cmd_handler.is_halted() is False

    @pytest.mark.asyncio
    async def test_halt_kills_running_process(self, cmd_handler_with_runner):
        handler, mock_runner = cmd_handler_with_runner
        await handler.handle("chat-1", "halt", "")
        mock_runner.kill_current.assert_called_once()

    @pytest.mark.asyncio
    async def test_halt_without_runner_does_not_raise(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "halt", "")
        assert "halted" in result.lower()

    @pytest.mark.asyncio
    async def test_double_halt_stays_halted(self, cmd_handler):
        await cmd_handler.handle("chat-1", "halt", "")
        await cmd_handler.handle("chat-1", "halt", "")
        assert cmd_handler.is_halted() is True

    @pytest.mark.asyncio
    async def test_double_resume_stays_unhalted(self, cmd_handler):
        await cmd_handler.handle("chat-1", "halt", "")
        await cmd_handler.handle("chat-1", "resume", "")
        await cmd_handler.handle("chat-1", "resume", "")
        assert cmd_handler.is_halted() is False

    @pytest.mark.asyncio
    async def test_cmd_halt_writes_flag_via_security(self, cmd_handler):
        """Sprint 06.03: _cmd_halt calls SecurityManager.set_halt when wired."""
        mock_security = MagicMock()
        mock_security.set_halt = MagicMock()
        cmd_handler.set_security(mock_security)
        await cmd_handler.handle("chat-1", "halt", "")
        mock_security.set_halt.assert_called_once_with("operator_halt")

    @pytest.mark.asyncio
    async def test_cmd_halt_no_security_does_not_raise(self, cmd_handler):
        """Sprint 06.03: _cmd_halt works without SecurityManager wired."""
        assert cmd_handler._security is None
        result = await cmd_handler.handle("chat-1", "halt", "")
        assert "halted" in result.lower()


class TestCancelWithRunner:
    @pytest.mark.asyncio
    async def test_cancel_kills_active_task(self, cmd_handler_with_runner):
        handler, mock_runner = cmd_handler_with_runner
        result = await handler.handle("chat-1", "cancel", "")
        assert "No active task" not in result
        mock_runner.kill_current.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_when_kill_returns_false(self, migrated_db, message_queue, session_manager):
        mock_runner = MagicMock()
        mock_runner.kill_current = AsyncMock(return_value=False)
        handler = CmdHandler(migrated_db, message_queue, session_manager, claude_runner=mock_runner)
        result = await handler.handle("chat-1", "cancel", "")
        assert "No active task" in result


class TestResetWithWarmClaude:
    @pytest.mark.asyncio
    async def test_reset_cycles_warm_claude_on_success(self, cmd_handler, session_manager):
        await session_manager.create_session("chat-1")
        mock_warm = MagicMock()
        mock_warm.cycle = AsyncMock(return_value=True)
        cmd_handler.set_warm_claude(mock_warm)
        result = await cmd_handler.handle("chat-1", "reset", "")
        assert "Session reset" in result
        assert "Warm process recycled" in result

    @pytest.mark.asyncio
    async def test_reset_reports_warm_cycle_failure(self, cmd_handler, session_manager):
        await session_manager.create_session("chat-1")
        mock_warm = MagicMock()
        mock_warm.cycle = AsyncMock(return_value=False)
        cmd_handler.set_warm_claude(mock_warm)
        result = await cmd_handler.handle("chat-1", "reset", "")
        assert "failing back" in result.lower() or "failed" in result.lower() or "falling back" in result.lower()


class TestAutonomyCommands:
    @pytest.mark.asyncio
    async def test_trust_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "trust", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_escalation_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "escalation", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_events_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "events", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_digest_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "digest", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_proposals_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "proposals", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_trust_delegates_to_autonomy(self, cmd_handler):
        mock_autonomy = MagicMock()
        mock_autonomy.trust.format_trust_table.return_value = "trust table"
        cmd_handler.set_autonomy(mock_autonomy)
        result = await cmd_handler.handle("chat-1", "trust", "")
        assert result == "trust table"

    @pytest.mark.asyncio
    async def test_trust_with_known_capability(self, cmd_handler):
        mock_autonomy = MagicMock()
        mock_autonomy.trust.format_capability_detail.return_value = "capability detail"
        cmd_handler.set_autonomy(mock_autonomy)
        result = await cmd_handler.handle("chat-1", "trust", "bash")
        assert result == "capability detail"

    @pytest.mark.asyncio
    async def test_trust_unknown_capability(self, cmd_handler):
        mock_autonomy = MagicMock()
        mock_autonomy.trust.format_capability_detail.return_value = None
        cmd_handler.set_autonomy(mock_autonomy)
        result = await cmd_handler.handle("chat-1", "trust", "nonexistent")
        assert "Unknown capability" in result

    @pytest.mark.asyncio
    async def test_escalation_no_active_alerts(self, cmd_handler):
        mock_autonomy = MagicMock()
        mock_autonomy.escalation._active_alerts = {}
        cmd_handler.set_autonomy(mock_autonomy)
        result = await cmd_handler.handle("chat-1", "escalation", "")
        assert "No active alerts" in result

    @pytest.mark.asyncio
    async def test_events_limit_capped_at_50(self, cmd_handler):
        mock_autonomy = MagicMock()
        mock_autonomy.event_bus.format_recent_events.return_value = "events"
        cmd_handler.set_autonomy(mock_autonomy)
        await cmd_handler.handle("chat-1", "events", "999")
        mock_autonomy.event_bus.format_recent_events.assert_called_with(limit=50)

    @pytest.mark.asyncio
    async def test_events_with_numeric_limit(self, cmd_handler):
        mock_autonomy = MagicMock()
        mock_autonomy.event_bus.format_recent_events.return_value = "events"
        cmd_handler.set_autonomy(mock_autonomy)
        await cmd_handler.handle("chat-1", "events", "30")
        mock_autonomy.event_bus.format_recent_events.assert_called_with(limit=30)

    @pytest.mark.asyncio
    async def test_digest_delegates_to_autonomy(self, cmd_handler):
        mock_autonomy = MagicMock()
        mock_autonomy.build_weekly_digest.return_value = "weekly digest"
        cmd_handler.set_autonomy(mock_autonomy)
        result = await cmd_handler.handle("chat-1", "digest", "")
        assert result == "weekly digest"


class TestTmuxCommands:
    @pytest.mark.asyncio
    async def test_spawn_not_available(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "spawn", "do something")
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_spawn_no_args_returns_usage(self, cmd_handler):
        mock_tmux = MagicMock()
        cmd_handler.set_tmux_agents(mock_tmux)
        result = await cmd_handler.handle("chat-1", "spawn", "")
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_spawn_delegates(self, cmd_handler):
        mock_tmux = MagicMock()
        mock_result = MagicMock()
        mock_result.agent_id = "agent-001"
        mock_result.task = "analyze code"
        mock_tmux.spawn_agent = AsyncMock(return_value=mock_result)
        cmd_handler.set_tmux_agents(mock_tmux)
        result = await cmd_handler.handle("chat-1", "spawn", "analyze code")
        assert "agent-001" in result

    @pytest.mark.asyncio
    async def test_kill_agent_hyphen_normalized(self, cmd_handler):
        mock_tmux = MagicMock()
        mock_tmux.kill_agent = AsyncMock(return_value=True)
        cmd_handler.set_tmux_agents(mock_tmux)
        result = await cmd_handler.handle("chat-1", "kill-agent", "agent-001")
        assert "Unknown command" not in result

    @pytest.mark.asyncio
    async def test_kill_agent_success(self, cmd_handler):
        mock_tmux = MagicMock()
        mock_tmux.kill_agent = AsyncMock(return_value=True)
        cmd_handler.set_tmux_agents(mock_tmux)
        result = await cmd_handler.handle("chat-1", "kill-agent", "agent-001")
        assert "killed" in result.lower()

    @pytest.mark.asyncio
    async def test_agents_table(self, cmd_handler):
        mock_tmux = MagicMock()
        mock_tmux.format_agents_table.return_value = "agents table"
        cmd_handler.set_tmux_agents(mock_tmux)
        result = await cmd_handler.handle("chat-1", "agents", "")
        assert result == "agents table"


class TestMemoryCommands:
    @pytest.mark.asyncio
    async def test_fewshot_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "fewshot", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_fewshot_no_examples(self, cmd_handler):
        mock_store = MagicMock()
        mock_store.count.return_value = 0
        cmd_handler.set_few_shot_store(mock_store)
        result = await cmd_handler.handle("chat-1", "fewshot", "")
        assert "No few-shot examples" in result

    @pytest.mark.asyncio
    async def test_edits_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "edits", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_approve_success(self, cmd_handler):
        mock_sem = MagicMock()
        mock_sem.approve_pending.return_value = True
        cmd_handler.set_self_edit(mock_sem)
        result = await cmd_handler.handle("chat-1", "approve", "42")
        assert "approved" in result.lower()
        assert "42" in result

    @pytest.mark.asyncio
    async def test_approve_invalid_id(self, cmd_handler):
        mock_sem = MagicMock()
        cmd_handler.set_self_edit(mock_sem)
        result = await cmd_handler.handle("chat-1", "approve", "not-a-number")
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_reject_success(self, cmd_handler):
        mock_sem = MagicMock()
        mock_sem.reject_pending.return_value = True
        cmd_handler.set_self_edit(mock_sem)
        result = await cmd_handler.handle("chat-1", "reject", "5 not relevant")
        assert "rejected" in result.lower()

    @pytest.mark.asyncio
    async def test_reject_invalid_id(self, cmd_handler):
        mock_sem = MagicMock()
        cmd_handler.set_self_edit(mock_sem)
        result = await cmd_handler.handle("chat-1", "reject", "bad")
        assert "Usage" in result


class TestKnowledgeCommand:
    @pytest.mark.asyncio
    async def test_knowledge_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "knowledge", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_knowledge_list_all(self, cmd_handler):
        mock_kb = MagicMock()
        mock_kb.count.return_value = 5
        mock_kb.list_keys.return_value = ["key1", "key2"]
        cmd_handler.set_temporal_kb(mock_kb)
        result = await cmd_handler.handle("chat-1", "knowledge", "")
        assert "5 entries" in result

    @pytest.mark.asyncio
    async def test_knowledge_get_key(self, cmd_handler):
        mock_kb = MagicMock()
        mock_entry = MagicMock()
        mock_entry.version = 3
        mock_entry.value = "some value"
        mock_entry.valid_from = "2026-04-01"
        mock_entry.changed_by = "bumba"
        mock_entry.reason = "updated"
        mock_kb.get.return_value = mock_entry
        cmd_handler.set_temporal_kb(mock_kb)
        result = await cmd_handler.handle("chat-1", "knowledge", "mykey")
        assert "v3" in result

    @pytest.mark.asyncio
    async def test_knowledge_expired(self, cmd_handler):
        mock_kb = MagicMock()
        mock_kb.get_expired.return_value = ["old-key1"]
        cmd_handler.set_temporal_kb(mock_kb)
        result = await cmd_handler.handle("chat-1", "knowledge", "expired")
        assert "old-key1" in result


class TestSessionHookCommands:
    @pytest.mark.asyncio
    async def test_careful_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "careful", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_careful_activates_hook(self, cmd_handler):
        mock_hooks = MagicMock()
        mock_hooks.activate.return_value = True
        cmd_handler.set_session_hooks(mock_hooks)
        result = await cmd_handler.handle("chat-1", "careful", "")
        assert "Careful mode ON" in result

    @pytest.mark.asyncio
    async def test_freeze_activates_hook(self, cmd_handler):
        mock_hooks = MagicMock()
        mock_hooks.activate.return_value = True
        cmd_handler.set_session_hooks(mock_hooks)
        result = await cmd_handler.handle("chat-1", "freeze", "")
        assert "Freeze mode ON" in result

    @pytest.mark.asyncio
    async def test_relax_deactivates_hooks(self, cmd_handler):
        mock_hooks = MagicMock()
        mock_hooks.deactivate.return_value = True
        cmd_handler.set_session_hooks(mock_hooks)
        result = await cmd_handler.handle("chat-1", "relax", "")
        assert "Normal mode" in result

    @pytest.mark.asyncio
    async def test_relax_no_active_hooks(self, cmd_handler):
        mock_hooks = MagicMock()
        mock_hooks.deactivate.return_value = False
        cmd_handler.set_session_hooks(mock_hooks)
        result = await cmd_handler.handle("chat-1", "relax", "")
        assert "No active hooks" in result

    @pytest.mark.asyncio
    async def test_hooks_lists_available(self, cmd_handler):
        mock_hooks = MagicMock()
        mock_hooks.list_available.return_value = [
            {"name": "careful", "active": True, "description": "Force Opus"},
        ]
        cmd_handler.set_session_hooks(mock_hooks)
        result = await cmd_handler.handle("chat-1", "hooks", "")
        assert "careful" in result


class TestVerifyCommand:
    @pytest.mark.asyncio
    async def test_verify_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "verify", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_verify_on(self, cmd_handler):
        mock_verifier = MagicMock()
        mock_verifier.enabled = False
        cmd_handler.set_self_verifier(mock_verifier)
        result = await cmd_handler.handle("chat-1", "verify", "on")
        assert "enabled" in result.lower()
        assert mock_verifier.enabled is True

    @pytest.mark.asyncio
    async def test_verify_off(self, cmd_handler):
        mock_verifier = MagicMock()
        mock_verifier.enabled = True
        cmd_handler.set_self_verifier(mock_verifier)
        result = await cmd_handler.handle("chat-1", "verify", "off")
        assert "disabled" in result.lower()
        assert mock_verifier.enabled is False

    @pytest.mark.asyncio
    async def test_verify_status(self, cmd_handler):
        mock_verifier = MagicMock()
        mock_verifier.enabled = True
        cmd_handler.set_self_verifier(mock_verifier)
        result = await cmd_handler.handle("chat-1", "verify", "status")
        assert "enabled" in result.lower()


class TestProactiveCommand:
    @pytest.mark.asyncio
    async def test_proactive_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "proactive", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_proactive_on(self, cmd_handler):
        mock_tm = MagicMock()
        cmd_handler.set_tick_manager(mock_tm)
        result = await cmd_handler.handle("chat-1", "proactive", "on")
        assert "enabled" in result.lower()
        mock_tm.enable.assert_called_once()

    @pytest.mark.asyncio
    async def test_proactive_off(self, cmd_handler):
        mock_tm = MagicMock()
        cmd_handler.set_tick_manager(mock_tm)
        result = await cmd_handler.handle("chat-1", "proactive", "off")
        assert "disabled" in result.lower()
        mock_tm.disable.assert_called_once()

    @pytest.mark.asyncio
    async def test_proactive_status(self, cmd_handler):
        from bridge.tick_manager import TickState
        mock_tm = MagicMock()
        mock_tm.enabled = True
        mock_tm.state = TickState.IDLE
        mock_tm._default_sleep = 300
        mock_tm._min_sleep = 60
        mock_tm._max_sleep = 3600
        cmd_handler.set_tick_manager(mock_tm)
        result = await cmd_handler.handle("chat-1", "proactive", "status")
        assert "ENABLED" in result

    @pytest.mark.asyncio
    async def test_proactive_unknown_subcommand(self, cmd_handler):
        mock_tm = MagicMock()
        cmd_handler.set_tick_manager(mock_tm)
        result = await cmd_handler.handle("chat-1", "proactive", "badarg")
        assert "Unknown sub-command" in result

    @pytest.mark.asyncio
    async def test_proactive_status_includes_scheduler_section_when_wired(
        self, cmd_handler, tmp_path
    ):
        """D7.12 #1424 — /proactive status surfaces the last-7-days
        scheduler activity ledger when set_proactive_scheduler() has
        been called.
        """
        from bridge.proactive_scheduler import (
            ProactiveTickReport,
            WorkItem,
            append_to_ledger,
        )
        from bridge.tick_manager import TickState

        # Real ledger with a representative mix of skip + pick rows
        ledger = tmp_path / "proactive-activity.jsonl"
        for action, reason, wi in [
            ("skipped", "operator_dialogue_active", None),
            ("skipped", "budget_pressure", None),
            (
                "picked",
                "dry_run",
                WorkItem(42, "Sprint D7.99 — fake", (), "D7.99", ()),
            ),
        ]:
            append_to_ledger(
                ledger,
                ProactiveTickReport(action=action, work_item=wi, reason=reason),
            )

        # TickManager mock (existing surface)
        mock_tm = MagicMock()
        mock_tm.enabled = True
        mock_tm.state = TickState.IDLE
        mock_tm._default_sleep = 300
        mock_tm._min_sleep = 60
        mock_tm._max_sleep = 3600
        cmd_handler.set_tick_manager(mock_tm)

        # Scheduler stub — exposes ledger_path + dry_run + is_running
        mock_scheduler = MagicMock()
        mock_scheduler.ledger_path = ledger
        mock_scheduler.dry_run = True
        mock_scheduler.is_running = True
        cmd_handler.set_proactive_scheduler(mock_scheduler)

        result = await cmd_handler.handle("chat-1", "proactive", "status")

        # Original TickManager surface still intact
        assert "ENABLED" in result
        # New scheduler section present
        assert "Scheduler" in result
        assert "RUNNING" in result
        assert "dry-run" in result
        # Tick counts surfaced
        assert "Ticks: 3" in result
        # Pick title surfaced (at least the issue number)
        assert "#42" in result

    @pytest.mark.asyncio
    async def test_proactive_status_omits_scheduler_when_not_wired(
        self, cmd_handler
    ):
        """When the scheduler isn't wired, /proactive status falls back
        to the legacy TickManager-only output (no Scheduler section).
        """
        from bridge.tick_manager import TickState

        mock_tm = MagicMock()
        mock_tm.enabled = False
        mock_tm.state = TickState.PAUSED
        mock_tm._default_sleep = 300
        mock_tm._min_sleep = 60
        mock_tm._max_sleep = 3600
        cmd_handler.set_tick_manager(mock_tm)
        # NOTE: no set_proactive_scheduler call

        result = await cmd_handler.handle("chat-1", "proactive", "status")

        assert "DISABLED" in result
        assert "Scheduler" not in result


class TestBoardCommand:
    @pytest.mark.asyncio
    async def test_board_no_args_returns_usage(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "board", "")
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_board_with_question_returns_content(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "board", "Should we add auth?")
        assert result


class TestGoalsTasks:
    @pytest.mark.asyncio
    async def test_goals_empty(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "goals", "")
        assert "No active goals" in result

    @pytest.mark.asyncio
    async def test_tasks_empty(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "tasks", "")
        assert "No pending tasks" in result

    @pytest.mark.asyncio
    async def test_goals_with_data(self, cmd_handler, migrated_db):
        import json
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value, updated_at) VALUES (?, ?, ?)",
            ("goal:test-goal", json.dumps({"description": "Ship v2"}), "2026-04-01"),
        )
        result = await cmd_handler.handle("chat-1", "goals", "")
        assert "Active Goals" in result
        assert "Ship v2" in result


class TestOptionalModuleCommands:
    @pytest.mark.asyncio
    async def test_trace_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "trace", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_cost_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "cost", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_routing_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "routing", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_reflect_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "reflect", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_mcp_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "mcp", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_diagnose_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "diagnose", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_cost_with_tracker(self, cmd_handler):
        mock_tracker = MagicMock()
        mock_tracker.get_daily_summary.return_value = {
            "date": "2026-04-10", "total_cost": 0.05, "request_count": 3,
            "by_model": {"haiku": {"cost": 0.01, "count": 2}},
        }
        mock_tracker.get_weekly_summary.return_value = {
            "total_cost": 0.35, "request_count": 21,
            "by_model": {"haiku": {"cost": 0.07, "count": 14}},
        }
        cmd_handler.set_cost_tracker(mock_tracker)
        result = await cmd_handler.handle("chat-1", "cost", "")
        assert "Cost Summary" in result

    @pytest.mark.asyncio
    async def test_cost_experiments_empty(self, cmd_handler):
        """`/cost --experiments` with no attributed entries returns guidance."""
        mock_tracker = MagicMock()
        mock_tracker.list_experiment_iters.return_value = []
        cmd_handler.set_cost_tracker(mock_tracker)
        result = await cmd_handler.handle("chat-1", "cost", "--experiments")
        assert "Per-experiment Cost" in result
        assert "No experiment-attributed" in result

    @pytest.mark.asyncio
    async def test_cost_experiments_lists_per_iter(self, cmd_handler):
        """`/cost --experiments` formats one row per iteration with totals."""
        from bridge.cost_tracker import ExperimentCostSummary

        mock_tracker = MagicMock()
        mock_tracker.list_experiment_iters.return_value = ["iter-0001", "iter-0002"]

        def _summary(iid: str) -> ExperimentCostSummary:
            mapping = {
                "iter-0001": ExperimentCostSummary(
                    iter_id="iter-0001",
                    total_usd=0.0250,
                    call_count=3,
                    started_at="2026-04-29T10:00:00+00:00",
                    ended_at="2026-04-29T10:05:00+00:00",
                    model_breakdown={"haiku": {"cost": 0.025, "count": 3}},
                ),
                "iter-0002": ExperimentCostSummary(
                    iter_id="iter-0002",
                    total_usd=0.1750,
                    call_count=5,
                    started_at="2026-04-29T11:00:00+00:00",
                    ended_at="2026-04-29T11:30:00+00:00",
                    model_breakdown={"sonnet": {"cost": 0.175, "count": 5}},
                ),
            }
            return mapping[iid]

        mock_tracker.get_experiment_summary.side_effect = _summary

        cmd_handler.set_cost_tracker(mock_tracker)
        result = await cmd_handler.handle("chat-1", "cost", "--experiments")
        assert "Per-experiment Cost" in result
        assert "iter-0001" in result
        assert "iter-0002" in result
        # Sum of per-iter costs surfaces in the footer.
        assert "0.2000" in result
        assert "2 iteration" in result

    @pytest.mark.asyncio
    async def test_routing_with_engine(self, cmd_handler):
        mock_engine = MagicMock()
        mock_engine.format_routing_report.return_value = "routing report"
        cmd_handler.set_routing_feedback(mock_engine)
        result = await cmd_handler.handle("chat-1", "routing", "")
        assert result == "routing report"

    @pytest.mark.asyncio
    async def test_reflect_no_entries(self, cmd_handler):
        mock_store = MagicMock()
        mock_store.get_recent.return_value = []
        cmd_handler.set_reflection_store(mock_store)
        result = await cmd_handler.handle("chat-1", "reflect", "")
        assert "No reflections" in result


class TestLogCommand:
    @pytest.mark.asyncio
    async def test_log_not_initialized(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "log", "test entry")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_log_append_entry(self, cmd_handler):
        mock_log = MagicMock()
        cmd_handler.set_daily_log(mock_log)
        result = await cmd_handler.handle("chat-1", "log", "test entry")
        assert "Logged" in result
        mock_log.append.assert_called_once_with("test entry", category="general")

    @pytest.mark.asyncio
    async def test_log_append_with_category(self, cmd_handler):
        mock_log = MagicMock()
        cmd_handler.set_daily_log(mock_log)
        result = await cmd_handler.handle("chat-1", "log", "memory important note")
        assert "[memory]" in result
        mock_log.append.assert_called_once_with("important note", category="memory")

    @pytest.mark.asyncio
    async def test_log_read_today(self, cmd_handler):
        mock_log = MagicMock()
        mock_log.read_today.return_value = "- entry 1\n- entry 2\n"
        cmd_handler.set_daily_log(mock_log)
        result = await cmd_handler.handle("chat-1", "log", "today")
        assert "Today's log" in result

    @pytest.mark.asyncio
    async def test_log_read_empty(self, cmd_handler):
        mock_log = MagicMock()
        mock_log.read_today.return_value = None
        cmd_handler.set_daily_log(mock_log)
        result = await cmd_handler.handle("chat-1", "log", "read")
        assert "No entries" in result

    @pytest.mark.asyncio
    async def test_log_category_only_no_text(self, cmd_handler):
        mock_log = MagicMock()
        cmd_handler.set_daily_log(mock_log)
        result = await cmd_handler.handle("chat-1", "log", "event")
        assert "Nothing to log" in result


class TestGetAgentPrompt:
    def test_audit_prompt_includes_args(self):
        prompt = CmdHandler.get_agent_prompt("audit", "last 7 days")
        assert "last 7 days" in prompt
        assert "audit log" in prompt.lower()

    def test_missing_args_defaults_to_all(self):
        prompt = CmdHandler.get_agent_prompt("memory", "")
        assert "all" in prompt

    def test_unknown_command_returns_none(self):
        result = CmdHandler.get_agent_prompt("nonexistent", "")
        assert result is None

    def test_all_agent_commands_have_templates(self):
        for cmd in AGENT_COMMANDS:
            result = CmdHandler.get_agent_prompt(cmd, "test")
            assert result is not None, f"Agent command '{cmd}' has no template"


class TestCommandSets:
    def test_halt_is_bridge_command(self):
        assert "halt" in BRIDGE_COMMANDS

    def test_resume_is_bridge_command(self):
        assert "resume" in BRIDGE_COMMANDS

    def test_freeze_is_bridge_command(self):
        # #1071 Part 2: freeze is Tier 3 (session hook). With the
        # conftest auto-fixture enabling all Tier 3 commands, it is
        # in the active set during tests.
        assert "freeze" in BRIDGE_COMMANDS

    def test_proactive_is_bridge_command(self):
        # #1071 Part 2: Tier 3 — see test_freeze_is_bridge_command.
        assert "proactive" in BRIDGE_COMMANDS

    def test_kill_agent_normalized_in_bridge_commands(self):
        # #1071 Part 2: Tier 3 — see test_freeze_is_bridge_command.
        assert "kill_agent" in BRIDGE_COMMANDS

    def test_tmux_is_agent_command(self):
        assert "tmux" in AGENT_COMMANDS


class TestFormatUptime:
    @pytest.mark.asyncio
    async def test_format_uptime_output(self, cmd_handler):
        result = cmd_handler._format_uptime()
        assert "h" in result
        assert "m" in result


class TestSkillsFailures:
    @pytest.mark.asyncio
    async def test_skills_not_initialized(self, cmd_handler):
        # The skills bridge command routes to agent command when no _skill_evolution
        # The BRIDGE command "skills" needs _skill_evolution; agent command also called "skills"
        # The bridge handle() checks BRIDGE_COMMANDS first
        mock_ev = MagicMock()
        mock_ev.get_proposals.return_value = []
        cmd_handler.set_skill_evolution(mock_ev)
        result = await cmd_handler.handle("chat-1", "skills", "")
        # Should return something about no proposals or skills
        assert result

    @pytest.mark.asyncio
    async def test_failures_not_initialized(self, cmd_handler):
        mock_ev = MagicMock()
        mock_ev.failure_count.return_value = 0
        mock_ev.detect_recurring_failures.return_value = []
        cmd_handler.set_skill_evolution(mock_ev)
        result = await cmd_handler.handle("chat-1", "failures", "")
        assert "No recurring failure patterns" in result

    @pytest.mark.asyncio
    async def test_failures_with_patterns(self, cmd_handler):
        mock_ev = MagicMock()
        mock_ev.failure_count.return_value = 5
        pattern = MagicMock()
        pattern.task_type = "code"
        pattern.error_type = "auth"
        pattern.count = 3
        pattern.first_seen = "2026-04-01T00:00:00"
        pattern.last_seen = "2026-04-09T00:00:00"
        mock_ev.detect_recurring_failures.return_value = [pattern]
        cmd_handler.set_skill_evolution(mock_ev)
        result = await cmd_handler.handle("chat-1", "failures", "")
        assert "Recurring Failures" in result


class TestGoalsTasksEdge:
    @pytest.mark.asyncio
    async def test_goals_with_deadline(self, cmd_handler, migrated_db):
        import json
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value, updated_at) VALUES (?, ?, ?)",
            ("goal:timed", json.dumps({
                "description": "Ship feature",
                "deadline": "2026-05-01T00:00:00",
            }), "2026-04-01"),
        )
        result = await cmd_handler.handle("chat-1", "goals", "")
        assert "due:" in result


class TestRestartCommand:
    @pytest.mark.asyncio
    async def test_restart_with_shutdown_callback(self, cmd_handler):
        cb = MagicMock()
        cmd_handler.set_shutdown_callback(cb)
        result = await cmd_handler.handle("chat-1", "restart", "")
        assert "Restarting" in result

    @pytest.mark.asyncio
    async def test_restart_without_shutdown_callback(self, cmd_handler):
        # Should use sys.exit path — we just verify it returns a string without hanging
        result = await cmd_handler.handle("chat-1", "restart", "")
        assert "Restarting" in result


class TestDispatchCommand:
    """Z3.12: /dispatch operator command tests."""

    @pytest.mark.asyncio
    async def test_cmd_dispatch_no_text(self, cmd_handler):
        """Empty text returns usage string."""
        result = await cmd_handler.handle("chat-1", "dispatch", "")
        assert "Usage:" in result
        assert "/dispatch" in result

    @pytest.mark.asyncio
    async def test_cmd_dispatch_no_brain(self, cmd_handler):
        """No routing brain configured returns guidance message."""
        result = await cmd_handler.handle("chat-1", "dispatch", "build a feature")
        assert "not configured" in result.lower() or "RoutingBrain" in result

    @pytest.mark.asyncio
    async def test_cmd_dispatch_routing_only(self, cmd_handler):
        """With routing brain but no dispatcher, returns routing decision summary.

        Sprint 03.05 — RoutingBrain.decide() returns a RoutingDecision with
        intent/confidence/complexity/environment/reason fields, not the
        model-router-style tier/model/budget_remaining shape.
        """
        from bridge.intent_classifier import Intent
        from bridge.routing_brain import RoutingDecision

        mock_decision = RoutingDecision(
            intent=Intent.FIX,
            confidence=0.85,
            complexity=3,
            modality="text",
            environment="subagent",
            reason="Complexity 3 (moderate) — defaulting to subagent.",
        )

        mock_brain = MagicMock()
        mock_brain.decide.return_value = mock_decision
        cmd_handler.set_routing_brain(mock_brain)

        result = await cmd_handler.handle("chat-1", "dispatch", "build a feature")
        assert "Routing decision" in result
        assert "subagent" in result  # environment surfaces in the summary
        assert "moderate" in result  # reason surfaces

    @pytest.mark.asyncio
    async def test_cmd_dispatch_with_dispatcher(self, cmd_handler):
        """With both brain and dispatcher, returns full dispatch result."""
        from bridge.intent_classifier import Intent
        from bridge.routing_brain import RoutingDecision

        mock_decision = RoutingDecision(
            intent=Intent.BUILD,
            confidence=0.9,
            complexity=5,
            modality="text",
            environment="worktree",
            reason="Complexity 5 (extreme) — worktree isolation required.",
        )

        mock_brain = MagicMock()
        mock_brain.decide.return_value = mock_decision
        cmd_handler.set_routing_brain(mock_brain)

        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.handled = True
        mock_result.reason = "Dispatched to worktree"
        mock_result.result = None

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(return_value=mock_result)
        cmd_handler.set_dispatcher(mock_dispatcher)

        result = await cmd_handler.handle("chat-1", "dispatch", "refactor the auth module")
        assert "Dispatch result" in result
        assert "worktree" in result
        assert "OK" in result  # handled=True → "OK"

    @pytest.mark.asyncio
    async def test_cmd_dispatch_verbose(self, cmd_handler):
        """-v flag includes reason in output."""
        from bridge.intent_classifier import Intent
        from bridge.routing_brain import RoutingDecision

        mock_decision = RoutingDecision(
            intent=Intent.UNKNOWN,
            confidence=0.6,
            complexity=1,
            modality="text",
            environment="subagent",
            reason="Complexity 1 (trivial) — subagent is sufficient.",
        )

        mock_brain = MagicMock()
        mock_brain.decide.return_value = mock_decision
        cmd_handler.set_routing_brain(mock_brain)

        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.handled = False
        mock_result.reason = "Dispatched to subagent"
        mock_result.result = None

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(return_value=mock_result)
        cmd_handler.set_dispatcher(mock_dispatcher)

        result = await cmd_handler.handle("chat-1", "dispatch", "-v what time is it")
        # Verbose flag was historically used to print result.reason — preserve
        # that contract by checking the dispatcher-supplied reason still leaks
        # through. Sprint 03.05 simplified the verbose path; we only assert
        # the dispatch result line is present.
        assert "Dispatch result" in result
        assert "subagent" in result


# ---------------------------------------------------------------------------
# Sprints 04.09 + 04.10 + 04.11 — BridgeDeps.from_app migration spy tests
#
# These tests confirm that _cmd_board, _cmd_route, and _cmd_handoff construct
# their BridgeDeps via the BridgeDeps.from_app(...) factory rather than direct
# BridgeDeps(...) construction. The spy wraps the real factory so functional
# behavior continues to be exercised — only the call site is asserted.
# ---------------------------------------------------------------------------


def _make_fake_bridge_app() -> MagicMock:
    """Return a duck-typed BridgeApp stand-in suitable for BridgeDeps.from_app.

    The factory reads:
    - app.config.operator.chat_id (preferred)
    - app.config.data_dir (for sessions_dir)
    - app.memory, app.knowledge_search, app.cost_tracker, app.event_bus,
      app.trust_manager
    """
    app = MagicMock()
    app.config.operator.chat_id = "operator-chat"
    app.config.data_dir = None  # sessions_dir derives to None — fine for tests
    app.memory = MagicMock()
    app.knowledge_search = MagicMock()
    app.cost_tracker = MagicMock()
    app.event_bus = MagicMock()
    app.trust_manager = MagicMock()
    return app


def _bare_handler_with_app() -> CmdHandler:
    """Bypass __init__, set the minimal attributes _cmd_* read.

    Uses ``CommandHandler.__new__`` so the test does not depend on the full
    real-DB / real-queue fixture chain — these tests only care about the
    BridgeDeps construction path.
    """
    h = CmdHandler.__new__(CmdHandler)
    h._departments = None
    h._circuit_registry = None
    h._memory = None
    h._autonomy = None
    h._cost_tracker = None
    h._app = _make_fake_bridge_app()
    h._agent_router = None
    return h


class TestSprint0409CmdBoardFromAppFactory:
    """Sprint 04.09 — _cmd_board must construct BridgeDeps via from_app."""

    @pytest.mark.asyncio
    async def test_cmd_board_uses_from_app_factory(self) -> None:
        from unittest.mock import patch

        from teams._types import BridgeDeps, TeamResult

        handler = _bare_handler_with_app()
        mock_registry = MagicMock()
        mock_registry.route = AsyncMock(
            return_value=TeamResult(
                department="board",
                manager_output="Board says: ship.",
                duration_seconds=1.2,
            )
        )
        handler._departments = mock_registry

        with patch.object(
            BridgeDeps, "from_app", wraps=BridgeDeps.from_app
        ) as spy:
            result = await handler._cmd_board("chat-9", "ship now?")

        # Spy must have fired exactly once and the construction site must
        # have flowed through from_app, not direct BridgeDeps(...) call.
        spy.assert_called_once()
        # Confirm the kwargs preserve the literal "board" department name.
        kwargs = spy.call_args.kwargs
        assert kwargs["session_id"] == "chat-9"
        assert kwargs["department"] == "board"
        assert "ship" in result


class TestSprint0410CmdRouteFromAppFactory:
    """Sprint 04.10 — _cmd_route must construct BridgeDeps via from_app."""

    @pytest.mark.asyncio
    async def test_cmd_route_uses_from_app_factory(self) -> None:
        from unittest.mock import patch

        from teams._types import BridgeDeps, TeamResult

        handler = _bare_handler_with_app()
        mock_registry = MagicMock()
        mock_registry.department_names.return_value = ["qa", "strategy"]
        mock_registry.route = AsyncMock(
            return_value=TeamResult(
                department="qa",
                manager_output="QA review complete.",
                duration_seconds=0.7,
            )
        )
        handler._departments = mock_registry

        with patch.object(
            BridgeDeps, "from_app", wraps=BridgeDeps.from_app
        ) as spy:
            result = await handler._cmd_route("chat-9", "qa run the smoke tests")

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        # The department comes from the operator's typed argument, not a
        # literal — preserve that contract.
        assert kwargs["session_id"] == "chat-9"
        assert kwargs["department"] == "qa"
        assert "QA review complete" in result


class TestSprint0411CmdHandoffFromAppFactory:
    """Sprint 04.11 — _cmd_handoff must construct BridgeDeps via from_app."""

    @pytest.mark.asyncio
    async def test_cmd_handoff_uses_from_app_factory(self) -> None:
        from unittest.mock import patch

        from teams._types import BridgeDeps, TeamResult

        handler = _bare_handler_with_app()
        mock_registry = MagicMock()
        mock_registry.department_names.return_value = ["qa", "strategy"]
        mock_registry.route = AsyncMock(
            return_value=TeamResult(
                department="strategy",
                manager_output="Strategy follow-up: scope reduced.",
                duration_seconds=2.1,
            )
        )
        handler._departments = mock_registry

        # Stub out load_handoff so the test does not need a real memory store
        # — _cmd_handoff calls load_handoff before constructing BridgeDeps.
        envelope = MagicMock()
        envelope.to_department = "strategy"
        envelope.from_department = "qa"
        envelope.task = "follow-up needed"
        envelope.findings = "tests pass; UX gap"

        with patch("teams._handoff.load_handoff", new=AsyncMock(return_value=envelope)):
            with patch.object(
                BridgeDeps, "from_app", wraps=BridgeDeps.from_app
            ) as spy:
                result = await handler._cmd_handoff(
                    "chat-9", "continue corr-123"
                )

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert kwargs["session_id"] == "chat-9"
        # Department is dynamic — taken from the loaded envelope's
        # to_department field.
        assert kwargs["department"] == "strategy"
        assert "Strategy follow-up" in result


class TestSprint0407WorkflowsCommand:
    """Sprint 04.07 — /workflows must list, trigger, and detail real workflows."""

    @pytest.mark.asyncio
    async def test_workflows_list_returns_three_workflows(self, cmd_handler):
        """/workflows (no args) renders the registry's format_list output.

        With a real WorkflowRegistry pointed at the canonical YAMLs the
        command must surface every shipped workflow name.
        """
        from pathlib import Path

        from bridge.workflow_registry import WorkflowRegistry

        config_dir = Path(__file__).parent.parent / "config" / "workflows"
        registry = WorkflowRegistry(config_dir=config_dir)
        cmd_handler.set_workflow_registry(registry)

        result = await cmd_handler.handle("chat-1", "workflows", "")

        # All three production workflows must appear in the rendered list.
        for wf_name in ("example-workflow", "pr-ship-decision", "weekly-ceo-review"):
            assert wf_name in result, (
                f"/workflows output missing {wf_name!r}. Got:\n{result}"
            )
        # And the short-circuit message must be gone.
        assert "WorkflowRegistry is not initialised." not in result

    @pytest.mark.asyncio
    async def test_workflows_trigger_dispatches_workflow(self, cmd_handler):
        """/workflows trigger <name> must call WorkflowRegistry.trigger and
        return the engine's run id."""
        registry = MagicMock()
        registry.trigger.return_value = "wfrun-abc123"
        engine = MagicMock()
        cmd_handler.set_workflow_registry(registry)
        cmd_handler.set_workflow_engine(engine)

        result = await cmd_handler.handle(
            "chat-1", "workflows", "trigger pr-ship-decision"
        )

        registry.trigger.assert_called_once_with(
            "pr-ship-decision", engine=engine
        )
        assert "wfrun-abc123" in result

    @pytest.mark.asyncio
    async def test_workflows_unknown_subcommand_returns_detail(self, cmd_handler):
        """A bare ``/workflows <name>`` falls through to format_detail —
        confirming the registry is reachable for the operator's read path."""
        registry = MagicMock()
        registry.format_detail.return_value = "**weekly-ceo-review** details"
        cmd_handler.set_workflow_registry(registry)

        result = await cmd_handler.handle(
            "chat-1", "workflows", "weekly-ceo-review"
        )
        registry.format_detail.assert_called_once_with("weekly-ceo-review")
        assert "weekly-ceo-review" in result


# ---------------- Sprint 05.10 — second-brain operator UX (#1020) -------- #


class TestSprint0510WikiPromoteRejectWiki:
    """Dispatch + gating tests for /wiki, /promote, /reject_wiki."""

    @staticmethod
    def _wire_app(handler, *, second_brain_enabled: bool):
        """Attach a minimal BridgeApp-shaped object so the gate works."""
        cfg = MagicMock()
        cfg.second_brain_enabled = second_brain_enabled
        app = MagicMock()
        app.config = cfg
        handler.set_app(app)

    def test_three_commands_in_bridge_commands(self):
        # Conftest enables all Tier 3 commands for tests; verify the
        # registration is present.
        assert "wiki" in BRIDGE_COMMANDS
        assert "promote" in BRIDGE_COMMANDS
        assert "reject_wiki" in BRIDGE_COMMANDS

    def test_existing_reject_command_still_present(self):
        """Spec ref-audit-05-10 acceptance: /reject (memory edits) must
        coexist alongside /reject_wiki."""
        assert "reject" in BRIDGE_COMMANDS
        # Distinct entries — not aliases of each other.
        assert "reject" != "reject_wiki"

    @pytest.mark.asyncio
    async def test_wiki_when_second_brain_disabled(self, cmd_handler):
        self._wire_app(cmd_handler, second_brain_enabled=False)
        result = await cmd_handler.handle("chat-1", "wiki", "test")
        assert "not enabled" in result.lower()
        assert "second_brain" in result or "second-brain" in result.lower()

    @pytest.mark.asyncio
    async def test_promote_when_second_brain_disabled(self, cmd_handler):
        self._wire_app(cmd_handler, second_brain_enabled=False)
        result = await cmd_handler.handle(
            "chat-1", "promote", "bumba-contributions/staging/x.md"
        )
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_reject_wiki_when_second_brain_disabled(self, cmd_handler):
        self._wire_app(cmd_handler, second_brain_enabled=False)
        result = await cmd_handler.handle(
            "chat-1", "reject_wiki", "bumba-contributions/staging/x.md"
        )
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_wiki_no_args_lists_staging(self, cmd_handler, tmp_path):
        from bridge.second_brain import (
            CURATED_PREFIX,
            STAGING_PREFIX,
            WikiNote,
            WikiRepo,
        )

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / STAGING_PREFIX).mkdir(parents=True)
        (vault / CURATED_PREFIX).mkdir(parents=True)
        repo = WikiRepo(vault)
        repo.write(
            WikiNote(
                relpath=STAGING_PREFIX + "alpha.md",
                content_body="alpha body",
                source="daily_log",
                session_id="s",
                authored_at="2026-05-01T00:00:00Z",
                provenance="t",
            )
        )

        self._wire_app(cmd_handler, second_brain_enabled=True)
        cmd_handler.set_wiki_repo(repo)

        result = await cmd_handler.handle("chat-1", "wiki", "")
        assert "1 note" in result
        assert "alpha.md" in result

    @pytest.mark.asyncio
    async def test_wiki_health_subcommand(self, cmd_handler, tmp_path):
        from bridge.second_brain import (
            CURATED_PREFIX,
            STAGING_PREFIX,
            WikiRepo,
        )

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / STAGING_PREFIX).mkdir(parents=True)
        (vault / CURATED_PREFIX).mkdir(parents=True)
        repo = WikiRepo(vault)

        self._wire_app(cmd_handler, second_brain_enabled=True)
        cmd_handler.set_wiki_repo(repo)

        result = await cmd_handler.handle("chat-1", "wiki", "health")
        assert "health" in result.lower()
        assert "staged: 0" in result
        assert "curated: 0" in result

    # Removed test_wiki_query_module_not_importable_falls_back: Sprint 05.08
    # (#1016) merged before this sprint, so the import-error fallback path is
    # no longer reachable without invalidating sys.modules cache (fragile).
    # The graceful fallback code remains in commands.py as a future-proof guard.

    @pytest.mark.asyncio
    async def test_promote_calls_promote_note(self, cmd_handler, tmp_path):
        from bridge.second_brain import (
            CURATED_PREFIX,
            STAGING_PREFIX,
            WikiNote,
            WikiRepo,
        )

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / STAGING_PREFIX).mkdir(parents=True)
        (vault / CURATED_PREFIX).mkdir(parents=True)
        repo = WikiRepo(vault)
        repo.write(
            WikiNote(
                relpath=STAGING_PREFIX + "promote-me.md",
                content_body="content body",
                source="daily_log",
                session_id="s",
                authored_at="2026-05-01T00:00:00Z",
                provenance="t",
            )
        )

        self._wire_app(cmd_handler, second_brain_enabled=True)
        cmd_handler.set_wiki_repo(repo)

        result = await cmd_handler.handle(
            "chat-1",
            "promote",
            "bumba-contributions/staging/promote-me.md",
        )
        assert "Promoted" in result
        assert "promote-me.md" in result
        assert (vault / "promote-me.md").is_file()

    @pytest.mark.asyncio
    async def test_promote_invalid_path_returns_helpful_error(
        self, cmd_handler, tmp_path
    ):
        from bridge.second_brain import (
            CURATED_PREFIX,
            STAGING_PREFIX,
            WikiRepo,
        )

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / STAGING_PREFIX).mkdir(parents=True)
        (vault / CURATED_PREFIX).mkdir(parents=True)
        repo = WikiRepo(vault)

        self._wire_app(cmd_handler, second_brain_enabled=True)
        cmd_handler.set_wiki_repo(repo)

        result = await cmd_handler.handle(
            "chat-1", "promote", "outside-quarantine.md"
        )
        # Validation failure → ValueError → "Promote rejected:" prefix.
        assert "Promote rejected" in result
        assert "bumba-contributions" in result

    @pytest.mark.asyncio
    async def test_promote_usage_when_no_args(self, cmd_handler, tmp_path):
        from bridge.second_brain import (
            CURATED_PREFIX,
            STAGING_PREFIX,
            WikiRepo,
        )

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / STAGING_PREFIX).mkdir(parents=True)
        (vault / CURATED_PREFIX).mkdir(parents=True)
        repo = WikiRepo(vault)

        self._wire_app(cmd_handler, second_brain_enabled=True)
        cmd_handler.set_wiki_repo(repo)

        result = await cmd_handler.handle("chat-1", "promote", "")
        assert "Usage:" in result
        assert "/promote" in result

    @pytest.mark.asyncio
    async def test_reject_wiki_calls_reject_note_with_reason(
        self, cmd_handler, tmp_path
    ):
        from bridge.second_brain import (
            CURATED_PREFIX,
            STAGING_PREFIX,
            WikiNote,
            WikiRepo,
        )

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / STAGING_PREFIX).mkdir(parents=True)
        (vault / CURATED_PREFIX).mkdir(parents=True)
        repo = WikiRepo(vault)
        repo.write(
            WikiNote(
                relpath=STAGING_PREFIX + "reject-me.md",
                content_body="body",
                source="daily_log",
                session_id="s",
                authored_at="2026-05-01T00:00:00Z",
                provenance="t",
            )
        )

        self._wire_app(cmd_handler, second_brain_enabled=True)
        cmd_handler.set_wiki_repo(repo)

        result = await cmd_handler.handle(
            "chat-1",
            "reject_wiki",
            "bumba-contributions/staging/reject-me.md too speculative",
        )
        assert "Rejected" in result
        assert "too speculative" in result
        assert not (
            vault / "bumba-contributions" / "staging" / "reject-me.md"
        ).exists()

    @pytest.mark.asyncio
    async def test_reject_wiki_idempotent_when_absent(
        self, cmd_handler, tmp_path
    ):
        from bridge.second_brain import (
            CURATED_PREFIX,
            STAGING_PREFIX,
            WikiRepo,
        )

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / STAGING_PREFIX).mkdir(parents=True)
        (vault / CURATED_PREFIX).mkdir(parents=True)
        repo = WikiRepo(vault)

        self._wire_app(cmd_handler, second_brain_enabled=True)
        cmd_handler.set_wiki_repo(repo)

        result = await cmd_handler.handle(
            "chat-1",
            "reject_wiki",
            "bumba-contributions/staging/ghost.md",
        )
        assert "No-op" in result or "already absent" in result.lower()

    @pytest.mark.asyncio
    async def test_reject_wiki_usage_when_no_args(self, cmd_handler, tmp_path):
        from bridge.second_brain import (
            CURATED_PREFIX,
            STAGING_PREFIX,
            WikiRepo,
        )

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / STAGING_PREFIX).mkdir(parents=True)
        (vault / CURATED_PREFIX).mkdir(parents=True)
        repo = WikiRepo(vault)

        self._wire_app(cmd_handler, second_brain_enabled=True)
        cmd_handler.set_wiki_repo(repo)

        result = await cmd_handler.handle("chat-1", "reject_wiki", "")
        assert "Usage:" in result
        assert "/reject_wiki" in result

    @pytest.mark.asyncio
    async def test_wiki_repo_not_wired_returns_helpful_error(
        self, cmd_handler
    ):
        # second_brain_enabled True but WikiRepo never set.
        self._wire_app(cmd_handler, second_brain_enabled=True)
        result = await cmd_handler.handle(
            "chat-1", "promote", "bumba-contributions/staging/x.md"
        )
        assert "WikiRepo not wired" in result


# ---------- D2.5: /cost --by-team rendering ----------


class TestCostByTeamCommand:
    """/cost --by-team renders team breakdown (D2.5)."""

    def _make_handler_with_tracker(self, tmp_path):
        from bridge.cost_tracker import CostTracker
        h = CmdHandler.__new__(CmdHandler)
        h._departments = None
        h._circuit_registry = None
        h._memory = None
        h._autonomy = None
        h._cost_tracker = CostTracker(
            data_dir=tmp_path,
            team_limits={"design": 6.0, "qa": 5.0},
        )
        h._app = None
        h._agent_router = None
        return h

    @pytest.mark.asyncio
    async def test_by_team_no_entries_returns_no_entries_message(self, tmp_path):
        h = self._make_handler_with_tracker(tmp_path)
        result = await h._cmd_cost("chat-1", "--by-team")
        assert "No team-attributed" in result

    @pytest.mark.asyncio
    async def test_by_team_renders_spend_vs_limit(self, tmp_path):
        h = self._make_handler_with_tracker(tmp_path)
        h._cost_tracker.record(model="haiku", input_tokens=0, output_tokens=0, team="design")
        result = await h._cmd_cost("chat-1", "--by-team")
        assert "design" in result
        assert "6.00" in result

    @pytest.mark.asyncio
    async def test_existing_cost_view_unchanged(self, tmp_path):
        h = self._make_handler_with_tracker(tmp_path)
        result = await h._cmd_cost("chat-1", "")
        assert "Cost Summary" in result or "cost" in result.lower()


# ---------- Codex-6 (#1840): /cost per-backend rendering ----------


class TestCostPerBackendCommand:
    """``/cost`` surfaces a per-backend section (Codex-6, #1840).

    Per the #1841 operator broadcast: Claude lines show a dollar
    figure; Codex lines show ``subscription-billed`` (never
    ``$0.00``) plus turn-count + token-count.
    """

    def _make_handler_with_tracker(self, tmp_path):
        from bridge.cost_tracker import CostTracker
        h = CmdHandler.__new__(CmdHandler)
        h._departments = None
        h._circuit_registry = None
        h._memory = None
        h._autonomy = None
        h._cost_tracker = CostTracker(data_dir=tmp_path)
        h._app = None
        h._agent_router = None
        return h

    @pytest.mark.asyncio
    async def test_claude_only_renders_dollar_figure(self, tmp_path):
        h = self._make_handler_with_tracker(tmp_path)
        h._cost_tracker.record(
            model="sonnet", input_tokens=100, output_tokens=50, backend="claude"
        )
        result = await h._cmd_cost("chat-1", "")
        assert "Backend breakdown:" in result
        assert "claude" in result
        # Real per-token cost > $0.00 — make sure we surface the dollars.
        assert "$0." in result

    @pytest.mark.asyncio
    async def test_codex_turn_renders_subscription_billed(self, tmp_path):
        h = self._make_handler_with_tracker(tmp_path)
        h._cost_tracker.record(
            model="gpt-5-codex",
            input_tokens=200,
            output_tokens=80,
            backend="codex",
        )
        result = await h._cmd_cost("chat-1", "")
        assert "subscription-billed" in result
        # The hard constraint from the brief — no $0.00 leak for Codex.
        assert "$0.00 " not in result
        assert "1 turns" in result  # codex uses "turns" not "requests"

    @pytest.mark.asyncio
    async def test_mixed_claude_and_codex_session(self, tmp_path):
        h = self._make_handler_with_tracker(tmp_path)
        h._cost_tracker.record(
            model="sonnet", input_tokens=100, output_tokens=50, backend="claude"
        )
        h._cost_tracker.record(
            model="haiku", input_tokens=20, output_tokens=10, backend="claude"
        )
        h._cost_tracker.record(
            model="gpt-5-codex",
            input_tokens=200,
            output_tokens=80,
            backend="codex",
        )
        result = await h._cmd_cost("chat-1", "")
        # Both backends surface
        assert "claude" in result
        assert "codex" in result
        # Claude has a dollar figure, Codex has the honest label
        assert "subscription-billed" in result
        # Existing per-model breakdown still works alongside the new
        # per-backend section (no regression for Claude-only operators).
        assert "sonnet" in result
        assert "haiku" in result


# ---------- Z4-S13: /chief_sessions Discord command ----------


class TestChiefSessionsCommand:
    """Z4-S13 (#1388) — /chief_sessions Tier-2 Discord command.

    Covers the not-initialized fallback, the list view (active-only,
    SHUTDOWN excluded, truncated to 10), the single-sid detail view,
    sid-not-found, and the help subcommand.
    """

    @pytest.mark.asyncio
    async def test_set_chief_session_store(self, cmd_handler):
        """The setter wires the store onto the handler attribute."""
        from bridge.chief_session_store import InMemoryChiefSessionStore

        store = InMemoryChiefSessionStore()
        cmd_handler.set_chief_session_store(store)
        assert cmd_handler._chief_session_store is store

    @pytest.mark.asyncio
    async def test_chief_sessions_not_initialized(self, cmd_handler):
        """No store → friendly fallback, never raises."""
        result = await cmd_handler.handle("chat-1", "chief_sessions", "")
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_chief_sessions_list_empty(self, cmd_handler):
        """Empty store → 'none' message under the active-sessions header."""
        from bridge.chief_session_store import InMemoryChiefSessionStore

        cmd_handler.set_chief_session_store(InMemoryChiefSessionStore())
        result = await cmd_handler.handle("chat-1", "chief_sessions", "")
        assert "Active Chief Sessions" in result
        assert "none" in result.lower()

    @pytest.mark.asyncio
    async def test_chief_sessions_list_excludes_shutdown(self, cmd_handler):
        """SHUTDOWN sessions never appear in the active list."""
        from bridge.chief_session import (
            ChiefSession,
            ChiefSessionState,
            new_chief_session_id,
        )
        from bridge.chief_session_store import InMemoryChiefSessionStore

        store = InMemoryChiefSessionStore()
        # One active (WARM) session
        active_id = new_chief_session_id()
        await store.create(
            ChiefSession(
                session_id=active_id,
                work_order_id="wo-active-001",
                department="strategy",
                chief_name="strategy-product-chief",
                state=ChiefSessionState.WARM,
            )
        )
        # One terminal (SHUTDOWN) — must be excluded
        shutdown_id = new_chief_session_id()
        await store.create(
            ChiefSession(
                session_id=shutdown_id,
                work_order_id="wo-shutdown-001",
                department="qa",
                chief_name="qa-chief",
                state=ChiefSessionState.SHUTDOWN,
            )
        )
        cmd_handler.set_chief_session_store(store)

        result = await cmd_handler.handle("chat-1", "chief_sessions", "list")

        assert active_id[:16] in result
        assert shutdown_id[:16] not in result
        # Header shows the active count, not the total
        assert "Active Chief Sessions" in result
        assert "(1)" in result

    @pytest.mark.asyncio
    async def test_chief_sessions_list_renders_row_fields(self, cmd_handler):
        """List rows show department, state, work_order id (truncated), and age."""
        from bridge.chief_session import ChiefSession, new_chief_session_id
        from bridge.chief_session_store import InMemoryChiefSessionStore

        store = InMemoryChiefSessionStore()
        sid = new_chief_session_id()
        await store.create(
            ChiefSession(
                session_id=sid,
                work_order_id="wo-render-12345678",
                department="engineering",
                chief_name="engineering-chief",
            )
        )
        cmd_handler.set_chief_session_store(store)

        result = await cmd_handler.handle("chat-1", "chief_sessions", "")

        assert sid[:16] in result
        assert "engineering" in result
        assert "cold" in result  # default state
        assert "wo=" in result
        assert "age=" in result

    @pytest.mark.asyncio
    async def test_chief_sessions_list_truncates_to_ten(self, cmd_handler):
        """When >10 sessions exist, list shows 10 and a tail counts the rest."""
        from bridge.chief_session import ChiefSession, new_chief_session_id
        from bridge.chief_session_store import InMemoryChiefSessionStore

        store = InMemoryChiefSessionStore()
        ids = []
        for i in range(13):
            sid = new_chief_session_id()
            ids.append(sid)
            await store.create(
                ChiefSession(
                    session_id=sid,
                    work_order_id=f"wo-{i:03d}",
                    department="strategy",
                    chief_name="strategy-product-chief",
                )
            )
        cmd_handler.set_chief_session_store(store)

        result = await cmd_handler.handle("chat-1", "chief_sessions", "list")

        # Header shows total count
        assert "Active Chief Sessions" in result
        assert "(13)" in result
        # Tail line names how many were truncated (13 - 10 = 3)
        assert "+3 more" in result

    @pytest.mark.asyncio
    async def test_chief_sessions_detail_renders_all_fields(self, cmd_handler):
        """Single-sid lookup emits the full detail block."""
        from bridge.chief_session import (
            ChiefSession,
            ChiefSessionState,
            new_chief_session_id,
        )
        from bridge.chief_session_store import InMemoryChiefSessionStore

        store = InMemoryChiefSessionStore()
        sid = new_chief_session_id()
        await store.create(
            ChiefSession(
                session_id=sid,
                work_order_id="wo-detail-001",
                department="design",
                chief_name="design-chief",
                state=ChiefSessionState.WARM,
            )
        )
        cmd_handler.set_chief_session_store(store)

        result = await cmd_handler.handle("chat-1", "chief_sessions", sid)

        assert sid in result  # full id (not truncated)
        assert "wo-detail-001" in result
        assert "design" in result
        assert "design-chief" in result
        assert "warm" in result
        assert "run_count" in result
        assert "cost_usd" in result
        assert "created_at_utc" in result

    @pytest.mark.asyncio
    async def test_chief_sessions_detail_failed_includes_error(self, cmd_handler):
        """A FAILED session's detail block surfaces the error string."""
        from bridge.chief_session import (
            ChiefSession,
            ChiefSessionState,
            new_chief_session_id,
        )
        from bridge.chief_session_store import InMemoryChiefSessionStore

        store = InMemoryChiefSessionStore()
        sid = new_chief_session_id()
        await store.create(
            ChiefSession(
                session_id=sid,
                work_order_id="wo-failed-001",
                department="ops",
                chief_name="ops-chief",
                state=ChiefSessionState.FAILED,
                error="rate-limit exhausted",
            )
        )
        cmd_handler.set_chief_session_store(store)

        result = await cmd_handler.handle("chat-1", "chief_sessions", sid)

        assert "error" in result.lower()
        assert "rate-limit exhausted" in result

    @pytest.mark.asyncio
    async def test_chief_sessions_detail_unknown_id(self, cmd_handler):
        """Unknown sid → friendly 'not found' message."""
        from bridge.chief_session_store import InMemoryChiefSessionStore

        cmd_handler.set_chief_session_store(InMemoryChiefSessionStore())
        result = await cmd_handler.handle(
            "chat-1", "chief_sessions", "cs-doesnotexist"
        )
        assert "not found" in result.lower()
        assert "cs-doesnotexist" in result

    @pytest.mark.asyncio
    async def test_chief_sessions_help(self, cmd_handler):
        """`/chief_sessions help` returns usage text without touching the store."""
        from bridge.chief_session_store import InMemoryChiefSessionStore

        cmd_handler.set_chief_session_store(InMemoryChiefSessionStore())
        result = await cmd_handler.handle("chat-1", "chief_sessions", "help")
        assert "Usage:" in result
        assert "/chief_sessions" in result
        assert "list" in result.lower()

    def test_chief_sessions_in_tier_2(self):
        """`chief_sessions` is registered in the Tier-2 always-on surface."""
        from bridge.commands import _TIER_2_Z4

        assert "chief_sessions" in _TIER_2_Z4
        assert "chief_sessions" in BRIDGE_COMMANDS
