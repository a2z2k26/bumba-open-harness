"""Tests for weekly-ceo-review workflow YAML definition (sprint G-CR.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from config.workflows._schema import ActionStep, DepartmentStep, load_workflow_config


YAML_PATH = (
    Path(__file__).parent.parent / "config" / "workflows" / "weekly-ceo-review.yaml"
)


@pytest.fixture()
def cfg():
    return load_workflow_config(YAML_PATH.read_text())


class TestWeeklyCEOReviewYAML:
    def test_file_exists(self) -> None:
        assert YAML_PATH.exists(), "weekly-ceo-review.yaml must exist"

    def test_name(self, cfg) -> None:
        assert cfg.name == "weekly-ceo-review"

    def test_trigger_schedule(self, cfg) -> None:
        assert cfg.trigger == "schedule"

    def test_schedule_monday_08(self, cfg) -> None:
        # Must be a cron: expression targeting Monday at 08:00 UTC
        assert cfg.schedule is not None
        assert cfg.schedule.startswith("cron:")
        cron_expr = cfg.schedule.removeprefix("cron:")
        parts = cron_expr.strip().split()
        assert len(parts) == 5
        minute, hour, _dom, _month, weekday = parts
        assert hour == "8"
        assert weekday == "1"  # Monday

    def test_budget_cap(self, cfg) -> None:
        assert cfg.budget.max_cost_usd == 3.0

    def test_has_strategy_step(self, cfg) -> None:
        strategy_steps = [
            s for s in cfg.steps
            if isinstance(s, DepartmentStep) and s.department == "strategy"
        ]
        assert strategy_steps, "Must have a strategy department step"

    def test_has_ops_step(self, cfg) -> None:
        ops_steps = [
            s for s in cfg.steps
            if isinstance(s, DepartmentStep) and s.department == "ops"
        ]
        assert ops_steps, "Must have an ops department step"

    def test_has_board_synthesis_step(self, cfg) -> None:
        board_steps = [
            s for s in cfg.steps
            if isinstance(s, DepartmentStep) and s.department == "board"
        ]
        assert board_steps, "Must have a board synthesis step"
        board = board_steps[0]
        assert "strategy_signals" in board.inputs or "signals" in (board.inputs or []) or len(board.inputs) >= 1

    def test_parallel_ops_and_strategy(self, cfg) -> None:
        """Ops and strategy steps should run in parallel."""
        dept_steps = [s for s in cfg.steps if isinstance(s, DepartmentStep)]
        parallel_refs = {s.parallel_with for s in dept_steps if s.parallel_with}
        # At least one parallel reference should exist
        assert parallel_refs, "Some steps should run in parallel"

    def test_has_discord_publish_step(self, cfg) -> None:
        action_steps = [
            s for s in cfg.steps
            if isinstance(s, ActionStep) and s.action == "publish_discord"
        ]
        assert action_steps, "Must have a publish_discord action step"

    def test_board_step_takes_inputs(self, cfg) -> None:
        board_steps = [
            s for s in cfg.steps
            if isinstance(s, DepartmentStep) and s.department == "board"
        ]
        board = board_steps[0]
        assert len(board.inputs) >= 2, "Board step must take at least 2 inputs"

    def test_schema_validates(self) -> None:
        """Round-trip: load and validate without errors."""
        cfg = load_workflow_config(YAML_PATH.read_text())
        assert cfg is not None


class TestWeeklyCEOReviewService:
    def test_service_triggers_workflow(self) -> None:
        from unittest.mock import MagicMock
        from bridge.services.weekly_ceo_review import WeeklyCEOReviewService
        import asyncio

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=object())
        mock_registry.trigger = MagicMock(return_value="run-test-123")
        mock_engine = MagicMock()

        svc = WeeklyCEOReviewService(
            data_dir="/tmp",
            workflow_registry=mock_registry,
            workflow_engine=mock_engine,
        )
        result = asyncio.run(svc.run())
        assert result.ok is True
        assert "run-test-123" in (result.narration or "")

    def test_service_returns_failure_when_workflow_not_found(self) -> None:
        from unittest.mock import MagicMock
        from bridge.services.weekly_ceo_review import WeeklyCEOReviewService
        import asyncio

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=None)  # Workflow not found
        mock_engine = MagicMock()

        svc = WeeklyCEOReviewService(
            data_dir="/tmp",
            workflow_registry=mock_registry,
            workflow_engine=mock_engine,
        )
        result = asyncio.run(svc.run())
        assert result.ok is False

    def test_service_returns_failure_when_no_engine(self) -> None:
        from bridge.services.weekly_ceo_review import WeeklyCEOReviewService
        import asyncio

        svc = WeeklyCEOReviewService(data_dir="/tmp")
        result = asyncio.run(svc.run())
        assert result.ok is False
