"""Tests for the /board command migration to DepartmentRegistry (sprint E443.1).

Issue #544: _cmd_board must route through DepartmentRegistry.route("board", ...)
when Zone 4 is wired, and fall back to the legacy AgentRouter path when it is not.

Sprint 04.06 (issue #1007): adds subcommand dispatch (status, anonymize,
cross-vendor, cap, help). Tests for the new surface live in
``TestCmdBoardSubcommands`` below.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch


from bridge.commands import CommandHandler
from teams._types import TeamResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_handler() -> CommandHandler:
    """Return a CommandHandler with the minimal real dependencies mocked out.

    Sprint 04.09: a fake BridgeApp shim is wired via set_app() so _cmd_board's
    new BridgeDeps.from_app(self._app, ...) call does not AttributeError. The
    shim populates the exact attributes from_app reads on the live app.
    """
    db = MagicMock()
    db.fetchall = AsyncMock(return_value=[])
    queue = MagicMock()
    queue.get_queue_status = AsyncMock(return_value={"counts": {"pending": 0}, "pending": []})
    session_mgr = MagicMock()
    session_mgr.get_session_stats = AsyncMock(return_value={
        "active_session": {"session_id": None}
    })
    handler = CommandHandler(db=db, queue=queue, session_manager=session_mgr)
    handler.set_app(_make_fake_app())
    return handler


def _make_fake_app(*, data_dir: str | None = None) -> MagicMock:
    """Return a minimal duck-typed BridgeApp stand-in for BridgeDeps.from_app.

    The factory reads:
    - app.config.operator.chat_id (or app._config.operator_discord_id)
    - app.config.data_dir (for sessions_dir)
    - app.memory, app.knowledge_search, app.cost_tracker, app.event_bus,
      app.trust_manager
    """
    app = MagicMock()
    app.config.operator.chat_id = "operator-chat"
    app.config.data_dir = data_dir  # None keeps sessions_dir disabled by default.
    app.memory = MagicMock()
    app.knowledge_search = MagicMock()
    app.cost_tracker = MagicMock()
    app.event_bus = MagicMock()
    app.trust_manager = MagicMock()
    return app


def _make_team_result(
    *,
    success: bool = True,
    manager_output: str = "Board recommendation: proceed.",
    error: str | None = None,
    duration: float = 1.5,
) -> TeamResult:
    return TeamResult(
        department="board",
        manager_output=manager_output,
        success=success,
        error=error,
        duration_seconds=duration,
    )


# ---------------------------------------------------------------------------
# Tests: Zone 4 path
# ---------------------------------------------------------------------------


class TestCmdBoardZ4Path:
    """_cmd_board routes through DepartmentRegistry when departments are wired."""

    def test_no_args_returns_usage(self) -> None:
        """Sprint 04.06: no-arg /board now returns the subcommand help block.

        Help text contains the literal ``Usage:`` line plus the four
        subcommand names — strictly richer than the prior bare usage hint.
        """
        handler = _make_handler()
        result = asyncio.run(handler._cmd_board("chat-1", ""))
        assert "Usage:" in result
        assert "/board" in result

    def test_uses_department_registry_when_wired(self) -> None:
        """When _departments is set, route("board", ...) is called."""
        handler = _make_handler()

        mock_registry = MagicMock()
        mock_registry.route = AsyncMock(return_value=_make_team_result())
        handler.set_departments(mock_registry)

        result = asyncio.run(handler._cmd_board("chat-1", "Should we expand to Europe?"))

        mock_registry.route.assert_called_once()
        call_args = mock_registry.route.call_args
        assert call_args[0][0] == "board"
        assert "Europe" in call_args[0][1]

    def test_z4_success_returns_formatted_output(self) -> None:
        """Successful Z4 result is formatted with department header and duration."""
        handler = _make_handler()

        mock_registry = MagicMock()
        mock_registry.route = AsyncMock(
            return_value=_make_team_result(
                manager_output="Expand to Europe: YES.", duration=2.3
            )
        )
        handler.set_departments(mock_registry)

        result = asyncio.run(handler._cmd_board("chat-1", "Europe expansion?"))

        assert "Board" in result
        assert "2.3" in result
        assert "Expand to Europe" in result

    def test_z4_success_links_session_output(self, tmp_path) -> None:
        """Successful board runs tell the operator where the transcript lives."""
        handler = _make_handler()
        handler.set_app(_make_fake_app(data_dir=str(tmp_path)))

        mock_registry = MagicMock()
        mock_registry.route = AsyncMock(
            return_value=_make_team_result(
                manager_output="Expand to Europe: YES.", duration=2.3
            )
        )
        handler.set_departments(mock_registry)

        result = asyncio.run(handler._cmd_board("chat-1", "Europe expansion?"))

        assert "Session transcript" in result
        assert (
            str(
                tmp_path
                / "z4-sessions"
                / "chat-1"
                / "board"
                / "conversation.jsonl"
            )
            in result
        )
        assert "/api/z4/sessions/chat-1/departments/board/conversation" in result

    def test_z4_failure_returns_error_message(self) -> None:
        """When Z4 route fails, the error is surfaced clearly."""
        handler = _make_handler()

        mock_registry = MagicMock()
        mock_registry.route = AsyncMock(
            return_value=_make_team_result(
                success=False,
                manager_output="",
                error="circuit OPEN",
            )
        )
        handler.set_departments(mock_registry)

        result = asyncio.run(handler._cmd_board("chat-1", "Europe expansion?"))

        assert "FAILED" in result
        assert "circuit OPEN" in result

    def test_z4_exception_falls_back_to_legacy(self) -> None:
        """If DepartmentRegistry.route raises, fall back to AgentRouter."""
        handler = _make_handler()

        mock_registry = MagicMock()
        mock_registry.route = AsyncMock(side_effect=RuntimeError("z4 down"))
        handler.set_departments(mock_registry)

        mock_agent_router = MagicMock()
        mock_agent_router.get_board_prompt = MagicMock(return_value="LEGACY_PROMPT")
        handler._agent_router = mock_agent_router

        result = asyncio.run(handler._cmd_board("chat-1", "Europe expansion?"))

        assert result == "LEGACY_PROMPT"


# ---------------------------------------------------------------------------
# Tests: Legacy fallback path
# ---------------------------------------------------------------------------


class TestCmdBoardLegacyPath:
    """When _departments is None, /board uses the legacy AgentRouter."""

    def test_legacy_path_when_no_departments(self) -> None:
        """With no DepartmentRegistry, the legacy AgentRouter is used."""
        handler = _make_handler()
        assert handler._departments is None

        mock_router = MagicMock()
        mock_router.get_board_prompt = MagicMock(return_value="LEGACY_BOARD_PROMPT")
        handler._agent_router = mock_router

        result = asyncio.run(handler._cmd_board("chat-1", "Is this a good idea?"))

        assert result == "LEGACY_BOARD_PROMPT"
        mock_router.get_board_prompt.assert_called_once_with("Is this a good idea?")

    def test_legacy_path_instantiates_agent_router_if_none(self) -> None:
        """If _agent_router is also None, one is created on demand."""
        handler = _make_handler()
        assert handler._departments is None
        assert handler._agent_router is None

        # AgentRouter is imported locally inside _cmd_board so patch the module it comes from
        with patch("bridge.agent_router.AgentRouter") as MockAgentRouter:
            mock_instance = MagicMock()
            mock_instance.get_board_prompt.return_value = "AUTO_CREATED_PROMPT"
            MockAgentRouter.return_value = mock_instance

            result = asyncio.run(handler._cmd_board("chat-1", "Is this a good idea?"))

        MockAgentRouter.assert_called_once()
        assert result == "AUTO_CREATED_PROMPT"


# ---------------------------------------------------------------------------
# Sprint 04.06 — /board subcommand dispatch (issue #1007)
# ---------------------------------------------------------------------------


@dataclass
class _FakeBoardConfig:
    """Mutable stand-in for BridgeConfig with just the Board v2 flags.

    BridgeConfig is ``frozen=True`` in production; ``object.__setattr__`` is
    how _cmd_board flips flags at runtime. This fake mirrors the attribute
    surface so the same code path works under test.
    """

    board_v2_enabled: bool = False
    board_cross_vendor_enabled: bool = False
    feature_cost_caps_enabled: bool = False


@dataclass
class _FakeBoardApp:
    """Minimal app stub exposing ``config`` for the subcommand handlers."""

    config: _FakeBoardConfig = field(default_factory=_FakeBoardConfig)


class _FakeCostTracker:
    """In-memory CostTracker shim — only the API _cmd_board touches.

    Exposes ``_feature_caps`` (read by /board status) and
    ``register_feature_cap`` (called by /board cap), matching the real
    bridge.cost_tracker.CostTracker contract from Sprint 04.04.
    """

    def __init__(self) -> None:
        self._feature_caps: dict[str, float] = {}

    def register_feature_cap(self, feature: str, daily_cap_usd: float) -> None:
        if not feature:
            raise ValueError("feature must be a non-empty string")
        if daily_cap_usd < 0:
            raise ValueError("daily_cap_usd must be >= 0")
        self._feature_caps[feature] = float(daily_cap_usd)


def _make_subcommand_handler() -> tuple[CommandHandler, _FakeBoardApp, _FakeCostTracker]:
    """Build a handler wired with a real (mutable) config + cost tracker."""
    db = MagicMock()
    db.fetchall = AsyncMock(return_value=[])
    queue = MagicMock()
    queue.get_queue_status = AsyncMock(
        return_value={"counts": {"pending": 0}, "pending": []}
    )
    session_mgr = MagicMock()
    session_mgr.get_session_stats = AsyncMock(
        return_value={"active_session": {"session_id": None}}
    )
    handler = CommandHandler(db=db, queue=queue, session_manager=session_mgr)

    app = _FakeBoardApp()
    handler.set_app(app)

    tracker = _FakeCostTracker()
    handler.set_cost_tracker(tracker)
    return handler, app, tracker


class TestCmdBoardSubcommands:
    """/board <subcommand> dispatch added in Sprint 04.06 (issue #1007)."""

    # -- Regression guard: legacy free-form path must stay byte-equivalent --

    def test_freeform_question_still_routes_to_legacy(self) -> None:
        """A bare /board <question> with no subcommand still convokes the board."""
        handler, _app, _tracker = _make_subcommand_handler()
        mock_router = MagicMock()
        mock_router.get_board_prompt = MagicMock(return_value="LEGACY_PROMPT")
        handler._agent_router = mock_router

        result = asyncio.run(handler._cmd_board("chat-1", "Is this a good idea?"))

        assert result == "LEGACY_PROMPT"
        mock_router.get_board_prompt.assert_called_once_with("Is this a good idea?")

    def test_no_args_returns_help_not_legacy(self) -> None:
        """Bare /board (no args) returns help — does not invoke the legacy router."""
        handler, _app, _tracker = _make_subcommand_handler()
        mock_router = MagicMock()
        mock_router.get_board_prompt = MagicMock(return_value="LEGACY_PROMPT")
        handler._agent_router = mock_router

        result = asyncio.run(handler._cmd_board("chat-1", ""))

        mock_router.get_board_prompt.assert_not_called()
        assert "Usage" in result
        assert "anonymize" in result and "cross-vendor" in result
        assert "cap" in result and "status" in result

    def test_legacy_keyword_passes_through_to_router(self) -> None:
        """``/board legacy <question>`` strips the keyword and calls the router."""
        handler, _app, _tracker = _make_subcommand_handler()
        mock_router = MagicMock()
        mock_router.get_board_prompt = MagicMock(return_value="LEGACY_PROMPT")
        handler._agent_router = mock_router

        result = asyncio.run(handler._cmd_board("chat-1", "legacy Should we ship?"))

        mock_router.get_board_prompt.assert_called_once_with("Should we ship?")
        assert result == "LEGACY_PROMPT"

    # -- /board status --

    def test_status_renders_flag_state_and_no_caps(self) -> None:
        handler, _app, _tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "status"))
        assert "board_v2_enabled" in result
        assert "board_cross_vendor_enabled" in result
        assert "feature_cost_caps_enabled" in result
        assert "OFF" in result  # all flags default to False
        assert "(none)" in result

    def test_status_lists_registered_caps(self) -> None:
        handler, _app, tracker = _make_subcommand_handler()
        tracker.register_feature_cap("board", 2.50)
        tracker.register_feature_cap("ops", 0.75)
        result = asyncio.run(handler._cmd_board("chat-1", "status"))
        assert "board: $2.50/day" in result
        assert "ops: $0.75/day" in result

    # -- /board anonymize on|off --

    def test_anonymize_on_flips_board_v2_enabled(self) -> None:
        handler, app, _tracker = _make_subcommand_handler()
        assert app.config.board_v2_enabled is False
        result = asyncio.run(handler._cmd_board("chat-1", "anonymize on"))
        assert app.config.board_v2_enabled is True
        assert "ON" in result

    def test_anonymize_off_flips_board_v2_enabled_back(self) -> None:
        handler, app, _tracker = _make_subcommand_handler()
        object.__setattr__(app.config, "board_v2_enabled", True)
        result = asyncio.run(handler._cmd_board("chat-1", "anonymize off"))
        assert app.config.board_v2_enabled is False
        assert "OFF" in result

    def test_anonymize_invalid_arg_returns_usage(self) -> None:
        handler, _app, _tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "anonymize maybe"))
        assert "Usage" in result and "on|off" in result

    # -- /board cross-vendor on|off --

    def test_cross_vendor_on_flips_flag(self) -> None:
        handler, app, _tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "cross-vendor on"))
        assert app.config.board_cross_vendor_enabled is True
        assert "ON" in result

    def test_cross_vendor_off_flips_flag(self) -> None:
        handler, app, _tracker = _make_subcommand_handler()
        object.__setattr__(app.config, "board_cross_vendor_enabled", True)
        result = asyncio.run(handler._cmd_board("chat-1", "cross-vendor off"))
        assert app.config.board_cross_vendor_enabled is False
        assert "OFF" in result

    def test_cross_vendor_underscore_alias_works(self) -> None:
        """``cross_vendor`` underscore variant is accepted alongside hyphen."""
        handler, app, _tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "cross_vendor on"))
        assert app.config.board_cross_vendor_enabled is True
        assert "ON" in result

    # -- /board cap <feature> <usd> --

    def test_cap_registers_new_feature(self) -> None:
        handler, _app, tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "cap board 2.50"))
        assert tracker._feature_caps == {"board": 2.50}
        assert "board" in result and "2.50" in result

    def test_cap_updates_existing_feature(self) -> None:
        handler, _app, tracker = _make_subcommand_handler()
        tracker.register_feature_cap("board", 1.00)
        asyncio.run(handler._cmd_board("chat-1", "cap board 5.25"))
        assert tracker._feature_caps == {"board": 5.25}

    def test_cap_then_status_shows_new_value(self) -> None:
        handler, _app, _tracker = _make_subcommand_handler()
        asyncio.run(handler._cmd_board("chat-1", "cap board 2.50"))
        status = asyncio.run(handler._cmd_board("chat-1", "status"))
        assert "board: $2.50/day" in status

    def test_cap_invalid_usd_returns_friendly_error(self) -> None:
        handler, _app, tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "cap board notanumber"))
        assert "Invalid USD" in result
        assert tracker._feature_caps == {}

    def test_cap_negative_usd_rejected(self) -> None:
        handler, _app, tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "cap board -1.00"))
        assert ">= 0" in result
        assert tracker._feature_caps == {}

    def test_cap_missing_args_returns_usage(self) -> None:
        handler, _app, _tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "cap board"))
        assert "Usage" in result and "<feature>" in result

    # -- /board help + unknown subcommand --

    def test_help_includes_all_four_subcommands(self) -> None:
        handler, _app, _tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "help"))
        for token in ("status", "anonymize", "cross-vendor", "cap"):
            assert token in result

    def test_unknown_subcommand_falls_through_to_legacy(self) -> None:
        """Unknown first-token routes to the legacy free-form path.

        This keeps backwards compatibility — questions like "What is the
        board's view on X?" don't accidentally get swallowed as a bad
        subcommand. ``help`` is the only way to surface the new help text.
        """
        handler, _app, _tracker = _make_subcommand_handler()
        mock_router = MagicMock()
        mock_router.get_board_prompt = MagicMock(return_value="LEGACY")
        handler._agent_router = mock_router

        result = asyncio.run(handler._cmd_board("chat-1", "what is the plan"))

        mock_router.get_board_prompt.assert_called_once_with("what is the plan")
        assert result == "LEGACY"

    # -- Sprint E.03 (#2010): operational-disclaimer regression --

    def test_board_toggle_response_includes_operational_disclaimer(self) -> None:
        """Every toggle response surfaces the restart-disclaimer text.

        Sprint E.03 (Option A): toggles are deliberately in-process. The
        ``/board cross-vendor on`` response (and every sibling toggle) must
        include "Effective until next daemon restart" so the operator knows
        to re-issue after deploys. Regression guard against silently
        dropping the disclaimer.
        """
        handler, _app, _tracker = _make_subcommand_handler()
        result = asyncio.run(handler._cmd_board("chat-1", "cross-vendor on"))
        assert "Effective until next daemon restart" in result


# ---------------------------------------------------------------------------
# Tests: Board Phase 2 WS4 (#2391) — run persistence + /board-history
# ---------------------------------------------------------------------------


def _make_handler_with_data_dir(data_dir: str) -> CommandHandler:
    """CommandHandler whose fake app exposes a real ``_config.data_dir``.

    The board-run store reads ``app._config.data_dir`` (not ``app.config``),
    so set it explicitly to a real path for persistence tests.
    """
    handler = _make_handler()
    app = _make_fake_app(data_dir=data_dir)
    app._config.data_dir = data_dir
    handler.set_app(app)
    return handler


class TestBoardRunPersistence:
    def test_successful_board_run_is_persisted(self, tmp_path) -> None:
        handler = _make_handler_with_data_dir(str(tmp_path))
        registry = MagicMock()
        registry.route = AsyncMock(return_value=_make_team_result(
            manager_output="Proceed with Phase 2.", duration=12.5,
        ))
        handler.set_departments(registry)

        asyncio.run(handler._cmd_board("chat-7", "Ship the dashboard?"))

        from bridge.board_run_store import BoardRunStore
        store = BoardRunStore(str(tmp_path))
        runs = store.list_recent()
        assert len(runs) == 1
        assert runs[0].synthesis == "Proceed with Phase 2."
        assert runs[0].session_id == "chat-7"

    def test_board_history_lists_recent_runs(self, tmp_path) -> None:
        handler = _make_handler_with_data_dir(str(tmp_path))
        registry = MagicMock()
        registry.route = AsyncMock(return_value=_make_team_result(
            manager_output="Recommendation A.",
        ))
        handler.set_departments(registry)
        asyncio.run(handler._cmd_board("chat-1", "Question one?"))

        out = asyncio.run(handler._cmd_board_history("chat-1", ""))
        assert "Recent board runs" in out
        assert "board-" in out
        assert "Question one?" in out

    def test_board_history_empty(self, tmp_path) -> None:
        handler = _make_handler_with_data_dir(str(tmp_path))
        out = asyncio.run(handler._cmd_board_history("chat-1", ""))
        assert "No board runs recorded yet." in out

    def test_persistence_skipped_on_non_path_data_dir(self) -> None:
        # Default fake app's _config.data_dir is a MagicMock -> the store
        # accessor returns None (no junk directory written) and the reply
        # still stands.
        import os

        handler = _make_handler()
        registry = MagicMock()
        registry.route = AsyncMock(return_value=_make_team_result(
            manager_output="Still answers.",
        ))
        handler.set_departments(registry)
        assert handler._board_run_store() is None
        result = asyncio.run(handler._cmd_board("chat-1", "Anything?"))
        assert "Still answers." in result
        # No stray MagicMock-named directory leaked into the tree.
        assert not os.path.exists("MagicMock")
