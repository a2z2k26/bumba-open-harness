"""Tests for /careful, /freeze, /relax commands using set_session_hook_registry API (#19)."""

from __future__ import annotations

import pytest
import pytest_asyncio

from bridge.hooks import SessionHookRegistry
from bridge.commands import CommandHandler


@pytest_asyncio.fixture
async def cmd_handler_with_registry(migrated_db, message_queue, session_manager):
    handler = CommandHandler(
        db=migrated_db,
        queue=message_queue,
        session_manager=session_manager,
        claude_runner=None,
    )
    reg = SessionHookRegistry()
    reg.register("careful", "Force Opus model + extra thoroughness")
    reg.register("freeze", "Read-only mode — block file modifications")
    handler.set_session_hook_registry(reg)
    return handler


class TestCarefulCommand:
    @pytest.mark.asyncio
    async def test_careful_activates(self, cmd_handler_with_registry):
        result = await cmd_handler_with_registry.handle("chat-1", "careful", "")
        assert "Careful mode ON" in result

    @pytest.mark.asyncio
    async def test_careful_mentions_opus(self, cmd_handler_with_registry):
        result = await cmd_handler_with_registry.handle("chat-1", "careful", "")
        assert "Opus" in result

    @pytest.mark.asyncio
    async def test_careful_sets_hook_active(self, cmd_handler_with_registry):
        await cmd_handler_with_registry.handle("chat-1", "careful", "")
        assert cmd_handler_with_registry._session_hook_registry.is_active("careful")


class TestFreezeCommand:
    @pytest.mark.asyncio
    async def test_freeze_activates(self, cmd_handler_with_registry):
        result = await cmd_handler_with_registry.handle("chat-1", "freeze", "")
        assert "Freeze mode ON" in result

    @pytest.mark.asyncio
    async def test_freeze_mentions_readonly(self, cmd_handler_with_registry):
        result = await cmd_handler_with_registry.handle("chat-1", "freeze", "")
        assert "Read-only" in result

    @pytest.mark.asyncio
    async def test_freeze_sets_hook_active(self, cmd_handler_with_registry):
        await cmd_handler_with_registry.handle("chat-1", "freeze", "")
        assert cmd_handler_with_registry._session_hook_registry.is_active("freeze")


class TestRelaxCommand:
    @pytest.mark.asyncio
    async def test_relax_returns_normal_mode(self, cmd_handler_with_registry):
        await cmd_handler_with_registry.handle("chat-1", "careful", "")
        result = await cmd_handler_with_registry.handle("chat-1", "relax", "")
        assert "Normal mode" in result

    @pytest.mark.asyncio
    async def test_relax_deactivates_careful(self, cmd_handler_with_registry):
        await cmd_handler_with_registry.handle("chat-1", "careful", "")
        await cmd_handler_with_registry.handle("chat-1", "relax", "")
        assert not cmd_handler_with_registry._session_hook_registry.is_active("careful")

    @pytest.mark.asyncio
    async def test_relax_deactivates_freeze(self, cmd_handler_with_registry):
        await cmd_handler_with_registry.handle("chat-1", "freeze", "")
        await cmd_handler_with_registry.handle("chat-1", "relax", "")
        assert not cmd_handler_with_registry._session_hook_registry.is_active("freeze")


class TestRegistryNotInitialized:
    @pytest.mark.asyncio
    async def test_careful_not_initialized(self, migrated_db, message_queue, session_manager):
        handler = CommandHandler(
            db=migrated_db,
            queue=message_queue,
            session_manager=session_manager,
        )
        result = await handler.handle("chat-1", "careful", "")
        assert "not initialized" in result

    @pytest.mark.asyncio
    async def test_freeze_not_initialized(self, migrated_db, message_queue, session_manager):
        handler = CommandHandler(
            db=migrated_db,
            queue=message_queue,
            session_manager=session_manager,
        )
        result = await handler.handle("chat-1", "freeze", "")
        assert "not initialized" in result

    @pytest.mark.asyncio
    async def test_relax_not_initialized(self, migrated_db, message_queue, session_manager):
        handler = CommandHandler(
            db=migrated_db,
            queue=message_queue,
            session_manager=session_manager,
        )
        result = await handler.handle("chat-1", "relax", "")
        assert "not initialized" in result


class TestSetSessionHookRegistryAlias:
    @pytest.mark.asyncio
    async def test_set_session_hook_registry_wires_session_hooks(
        self, migrated_db, message_queue, session_manager
    ):
        """set_session_hook_registry must also populate _session_hooks."""
        handler = CommandHandler(
            db=migrated_db,
            queue=message_queue,
            session_manager=session_manager,
        )
        reg = SessionHookRegistry()
        reg.register("careful", "Force Opus")
        handler.set_session_hook_registry(reg)
        # Both attributes should point to the same registry
        assert handler._session_hook_registry is reg
        assert handler._session_hooks is reg

    @pytest.mark.asyncio
    async def test_set_session_hooks_also_wires_registry_attr(
        self, migrated_db, message_queue, session_manager
    ):
        """set_session_hooks must also populate _session_hook_registry."""
        handler = CommandHandler(
            db=migrated_db,
            queue=message_queue,
            session_manager=session_manager,
        )
        reg = SessionHookRegistry()
        reg.register("careful", "Force Opus")
        handler.set_session_hooks(reg)
        assert handler._session_hook_registry is reg
        assert handler._session_hooks is reg
