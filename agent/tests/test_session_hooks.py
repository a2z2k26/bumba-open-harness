"""Tests for SessionHookRegistry (#18) and session hook commands (#19)."""

from __future__ import annotations

import pytest
import pytest_asyncio

from bridge.hooks import SessionHookRegistry
from bridge.commands import CommandHandler
from bridge.model_router import CAREFUL_OPUS_MODEL


# -- Sprint 01.08b: anti-resurrection guard for HookDispatcher --

class TestHookDispatcherRemoved:
    """Sprint 01.08b deleted HookDispatcher after the Mac mini audit
    (docs/audits/2026-04-24-activation-plans/plan-01-hooks-audit.md)
    found zero production hooks targeting the bridge's 6 events. If a
    future contributor re-adds the class to bridge.hooks, this test
    catches the resurrection in CI before the false-advertising pattern
    returns. Direction for that case: the new dispatcher should target
    a dedicated dir (e.g. ~/.claude/bumba-bridge-hooks/), not the shared
    ~/.claude/hooks/ that's owned by Claude Code CLI + Bumba Design Bridge.
    """

    def test_hook_dispatcher_class_does_not_exist(self):
        """Importing HookDispatcher from bridge.hooks must raise ImportError."""
        with pytest.raises(ImportError):
            from bridge.hooks import HookDispatcher  # noqa: F401

    def test_hook_timeout_constant_does_not_exist(self):
        """The HOOK_TIMEOUT constant was part of HookDispatcher infra; gone."""
        with pytest.raises(ImportError):
            from bridge.hooks import HOOK_TIMEOUT  # noqa: F401


# -- SessionHookRegistry unit tests (#18) --

class TestSessionHookRegistry:
    def test_register_and_list(self):
        reg = SessionHookRegistry()
        reg.register("careful", "Force Opus")
        reg.register("freeze", "Read-only")
        available = reg.list_available()
        assert len(available) == 2
        assert available[0]["name"] == "careful"
        assert available[0]["active"] is False

    def test_activate_deactivate(self):
        reg = SessionHookRegistry()
        reg.register("careful", "Force Opus")
        assert reg.activate("careful") is True
        assert reg.is_active("careful") is True
        assert reg.get_active() == ["careful"]
        assert reg.deactivate("careful") is True
        assert reg.is_active("careful") is False

    def test_activate_unregistered_returns_false(self):
        reg = SessionHookRegistry()
        assert reg.activate("nonexistent") is False

    def test_deactivate_inactive_returns_false(self):
        reg = SessionHookRegistry()
        reg.register("careful", "Force Opus")
        assert reg.deactivate("careful") is False

    def test_activate_already_active_returns_true(self):
        reg = SessionHookRegistry()
        reg.register("careful", "Force Opus")
        reg.activate("careful")
        assert reg.activate("careful") is True

    def test_callbacks_fire(self):
        activated = []
        deactivated = []
        reg = SessionHookRegistry()
        reg.register(
            "test",
            "Test hook",
            on_activate=lambda: activated.append(1),
            on_deactivate=lambda: deactivated.append(1),
        )
        reg.activate("test")
        assert len(activated) == 1
        reg.deactivate("test")
        assert len(deactivated) == 1

    def test_reset_deactivates_all(self):
        reg = SessionHookRegistry()
        reg.register("careful", "Force Opus")
        reg.register("freeze", "Read-only")
        reg.activate("careful")
        reg.activate("freeze")
        assert len(reg.get_active()) == 2
        reg.reset()
        assert len(reg.get_active()) == 0

    def test_list_available_shows_active_status(self):
        reg = SessionHookRegistry()
        reg.register("careful", "Force Opus")
        reg.activate("careful")
        available = reg.list_available()
        assert available[0]["active"] is True


# -- Command handler tests (#19) --

@pytest_asyncio.fixture
async def cmd_with_hooks(migrated_db, message_queue, session_manager):
    handler = CommandHandler(
        db=migrated_db,
        queue=message_queue,
        session_manager=session_manager,
        claude_runner=None,
    )
    reg = SessionHookRegistry()
    reg.register("careful", "Force Opus model + extra thoroughness")
    reg.register("freeze", "Read-only mode — block file modifications")
    handler.set_session_hooks(reg)
    return handler


class TestSessionHookCommands:
    @pytest.mark.asyncio
    async def test_careful_activates(self, cmd_with_hooks):
        result = await cmd_with_hooks.handle("chat-1", "careful", "")
        assert "Careful mode ON" in result
        assert cmd_with_hooks._session_hooks.is_active("careful")

    @pytest.mark.asyncio
    async def test_freeze_activates(self, cmd_with_hooks):
        result = await cmd_with_hooks.handle("chat-1", "freeze", "")
        assert "Freeze mode ON" in result
        assert cmd_with_hooks._session_hooks.is_active("freeze")

    @pytest.mark.asyncio
    async def test_relax_deactivates_both(self, cmd_with_hooks):
        await cmd_with_hooks.handle("chat-1", "careful", "")
        await cmd_with_hooks.handle("chat-1", "freeze", "")
        result = await cmd_with_hooks.handle("chat-1", "relax", "")
        assert "Normal mode" in result
        assert "careful" in result
        assert "freeze" in result
        assert not cmd_with_hooks._session_hooks.is_active("careful")
        assert not cmd_with_hooks._session_hooks.is_active("freeze")

    @pytest.mark.asyncio
    async def test_relax_with_nothing_active(self, cmd_with_hooks):
        result = await cmd_with_hooks.handle("chat-1", "relax", "")
        assert "No active hooks" in result

    @pytest.mark.asyncio
    async def test_hooks_lists_all(self, cmd_with_hooks):
        await cmd_with_hooks.handle("chat-1", "careful", "")
        result = await cmd_with_hooks.handle("chat-1", "hooks", "")
        assert "Session Hooks" in result
        assert "[ON]" in result
        assert "[off]" in result

    @pytest.mark.asyncio
    async def test_hooks_not_initialized(self, migrated_db, message_queue, session_manager):
        handler = CommandHandler(
            db=migrated_db,
            queue=message_queue,
            session_manager=session_manager,
        )
        result = await handler.handle("chat-1", "careful", "")
        assert "not initialized" in result


# -- Model override tests (#19) --

class TestCarefulModelOverride:
    """Verify CAREFUL_OPUS_MODEL constant is correct (#19 Tier B decision)."""

    def test_careful_opus_model_id(self):
        """The constant must match the operator-approved model ID."""
        assert CAREFUL_OPUS_MODEL == "claude-opus-4-5-20251001"

    def test_careful_opus_model_is_full_id(self):
        """Must be the full model ID, not a short alias like 'opus'."""
        assert "claude-" in CAREFUL_OPUS_MODEL
        assert CAREFUL_OPUS_MODEL != "opus"
        assert CAREFUL_OPUS_MODEL != "claude-opus"
