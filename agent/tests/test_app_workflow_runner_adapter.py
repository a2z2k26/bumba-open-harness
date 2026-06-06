"""Sprint 04.07 — unit tests for the BridgeApp workflow runner adapter.

Sprint 04.06 wired ``WorkflowEngine`` with ``department_runner=None`` because
``DepartmentRegistry.route`` returns a ``TeamResult`` while
``WorkflowEngine`` awaits ``(department, intent, context) -> (str, float)``.

Sprint 04.07 owns ``BridgeApp._workflow_department_runner`` — the adapter
that bridges those two shapes. These tests prove:

1. The adapter delegates to ``DepartmentRegistry.route`` with the right
   arguments and a synthesised ``BridgeDeps``.
2. The adapter coerces the returned ``TeamResult`` into ``(str, float)``
   via ``manager_output`` + ``total_cost_usd``.
3. The adapter degrades gracefully when ``DepartmentRegistry`` is missing
   or ``BridgeDeps.from_app`` raises — both branches return a typed sentinel
   tuple of shape ``(str, float)`` so ``WorkflowEngine`` never crashes on
   the runner edge.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_with_stub_registry(monkeypatch, route_return):
    """Construct a minimal BridgeApp-shaped object with stubbed dependencies.

    We don't rely on the full ``BridgeApp.__init__`` because that pulls in
    the entire bridge boot graph. Instead we build a thin namespace that
    exposes exactly the attributes ``_workflow_department_runner`` reads:
    ``_departments``, ``memory``, ``knowledge_search``, ``cost_tracker``,
    ``event_bus``, ``trust_manager``, plus the ``config.operator.chat_id``
    / ``config.data_dir`` chain consumed by ``BridgeDeps.from_app``.
    """
    from bridge.app import BridgeApp

    # Pretend DepartmentRegistry.route returns the configured TeamResult.
    fake_registry = MagicMock()
    fake_registry.department_names.return_value = ["strategy", "ops", "qa", "board", "design"]
    fake_registry.get_cost_limit.return_value = 1.5
    fake_registry.route = AsyncMock(return_value=route_return)

    # Build a minimal namespace BridgeDeps.from_app + the adapter consume.
    app = BridgeApp.__new__(BridgeApp)
    app._departments = fake_registry  # type: ignore[attr-defined]

    # BridgeDeps.from_app reads these directly off the app object.
    app._memory = None  # type: ignore[attr-defined]
    app._cost_tracker = MagicMock()  # type: ignore[attr-defined]
    app._autonomy = None  # type: ignore[attr-defined]
    app._trust_manager = MagicMock()  # type: ignore[attr-defined]

    # config.operator.chat_id chain
    fake_config = MagicMock()
    fake_config.operator.chat_id = "operator-1"
    fake_config.data_dir = "/tmp/sprint-0407-test"
    app.config = fake_config  # type: ignore[attr-defined]

    return app, fake_registry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAdapterDelegatesToRoute:
    """The adapter must call DepartmentRegistry.route with the right args."""

    @pytest.mark.asyncio
    async def test_adapter_calls_registry_route(self, monkeypatch):
        from teams._types import TeamResult

        team_result = TeamResult(
            department="strategy",
            manager_output="signals: …",
            total_cost_usd=0.42,
            success=True,
        )
        app, fake_registry = _make_app_with_stub_registry(monkeypatch, team_result)

        result = await app._workflow_department_runner(
            "strategy", "Gather weekly signals", {"week": "W17"}
        )

        # Delegation: route called once, with the right department + intent.
        assert fake_registry.route.await_count == 1
        call_args = fake_registry.route.await_args
        assert call_args.args[0] == "strategy"
        assert call_args.args[1] == "Gather weekly signals"
        # The third positional is BridgeDeps — verified by the from_app
        # contract; we only assert it carried the right department.
        deps = call_args.args[2]
        assert deps.department == "strategy"
        assert deps.session_id == "workflow:strategy"

        # Adapter return shape (str, float).
        assert result == ("signals: …", 0.42)

    @pytest.mark.asyncio
    async def test_adapter_threads_workflow_name_from_context(self, monkeypatch):
        """WS3.2 (#2570) — the engine injects ``_workflow_name`` into the
        per-step context; the shim threads it onto deps.workflow so the
        team_run cost row recorded by route() carries the workflow tag."""
        from teams._types import TeamResult

        team_result = TeamResult(
            department="strategy",
            manager_output="ok",
            total_cost_usd=0.10,
            success=True,
        )
        app, fake_registry = _make_app_with_stub_registry(monkeypatch, team_result)

        await app._workflow_department_runner(
            "strategy", "Gather", {"_workflow_name": "weekly-signals"}
        )

        deps = fake_registry.route.await_args.args[2]
        assert deps.workflow == "weekly-signals"

    @pytest.mark.asyncio
    async def test_adapter_workflow_defaults_empty_without_context(self, monkeypatch):
        """No ``_workflow_name`` in context → deps.workflow stays empty, so the
        team_run row lands in the un-attributed bucket."""
        from teams._types import TeamResult

        team_result = TeamResult(
            department="strategy",
            manager_output="ok",
            total_cost_usd=0.10,
            success=True,
        )
        app, fake_registry = _make_app_with_stub_registry(monkeypatch, team_result)

        await app._workflow_department_runner("strategy", "Gather", {})

        deps = fake_registry.route.await_args.args[2]
        assert deps.workflow == ""


class TestAdapterAdaptsTeamResultToTuple:
    """The adapter must coerce TeamResult into (str, float)."""

    @pytest.mark.asyncio
    async def test_team_result_coerced_to_str_float(self, monkeypatch):
        from teams._types import TeamResult

        team_result = TeamResult(
            department="ops",
            manager_output="ops up",
            total_cost_usd=1.234567,
            success=True,
        )
        app, _ = _make_app_with_stub_registry(monkeypatch, team_result)

        result = await app._workflow_department_runner("ops", "Status?", {})

        assert isinstance(result, tuple)
        assert len(result) == 2
        result_text, cost = result
        assert isinstance(result_text, str)
        assert isinstance(cost, float)
        assert result_text == "ops up"
        assert cost == pytest.approx(1.234567)

    @pytest.mark.asyncio
    async def test_adapter_handles_empty_manager_output(self, monkeypatch):
        from teams._types import TeamResult

        team_result = TeamResult(
            department="qa",
            manager_output="",
            total_cost_usd=0.0,
            success=False,
            error="boom",
        )
        app, _ = _make_app_with_stub_registry(monkeypatch, team_result)

        result_text, cost = await app._workflow_department_runner("qa", "Check", {})
        assert result_text == ""
        assert cost == 0.0


class TestAdapterDegradesGracefully:
    """Missing infrastructure must yield a typed sentinel, not a crash."""

    @pytest.mark.asyncio
    async def test_no_department_registry_returns_sentinel(self):
        from bridge.app import BridgeApp

        app = BridgeApp.__new__(BridgeApp)
        app._departments = None  # type: ignore[attr-defined]

        result_text, cost = await app._workflow_department_runner(
            "strategy", "irrelevant", {}
        )
        assert result_text == "[department-registry-unavailable]"
        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_route_exception_is_caught(self, monkeypatch):
        from bridge.app import BridgeApp

        fake_registry = MagicMock()
        fake_registry.department_names.return_value = ["ops"]
        fake_registry.get_cost_limit.return_value = 1.0
        fake_registry.route = AsyncMock(side_effect=RuntimeError("boom"))

        app = BridgeApp.__new__(BridgeApp)
        app._departments = fake_registry  # type: ignore[attr-defined]
        app._memory = None  # type: ignore[attr-defined]
        app._cost_tracker = MagicMock()  # type: ignore[attr-defined]
        app._autonomy = None  # type: ignore[attr-defined]
        app._trust_manager = MagicMock()  # type: ignore[attr-defined]
        fake_config = MagicMock()
        fake_config.operator.chat_id = "operator-1"
        fake_config.data_dir = "/tmp/sprint-0407-test"
        app.config = fake_config  # type: ignore[attr-defined]

        result_text, cost = await app._workflow_department_runner(
            "ops", "intent", {}
        )
        assert result_text.startswith("[route-failed:")
        assert cost == 0.0
