"""Integration tests for Weekly CEO Review workflow (sprint G-CR.2).

Marked @pytest.mark.live — not run in CI by default.
Run with: pytest -m live tests/test_weekly_ceo_review_integration.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from bridge.workflow_engine import WorkflowEngine
from bridge.workflow_registry import WorkflowRegistry
from config.workflows._schema import load_workflow_config


YAML_PATH = (
    Path(__file__).parent.parent / "config" / "workflows" / "weekly-ceo-review.yaml"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg():
    return load_workflow_config(YAML_PATH.read_text())


@pytest.fixture()
def workflow_dir(tmp_path: Path) -> Path:
    """Copy weekly-ceo-review.yaml into a temp dir for registry tests."""
    (tmp_path / "weekly-ceo-review.yaml").write_text(YAML_PATH.read_text())
    return tmp_path


@pytest.fixture()
def registry(workflow_dir: Path) -> WorkflowRegistry:
    return WorkflowRegistry(config_dir=workflow_dir)


# ---------------------------------------------------------------------------
# Unit-level integration (stub department runner)
# ---------------------------------------------------------------------------


class TestWeeklyCEOReviewIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_stub_runner(self, cfg) -> None:
        """Workflow runs end-to-end with stub departments and posts to Discord."""
        discord_posts: list[tuple[str, str]] = []

        async def dept_runner(dept: str, intent: str, ctx: dict) -> tuple[str, float]:
            if dept == "strategy":
                return "Competitive signals: stable.", 0.1
            if dept == "ops":
                return "All services healthy. 0 incidents.", 0.1
            if dept == "board":
                return "## What's Working\nAll green.\n## What's Next\nQ2 planning.\n## Risks\nNone.", 0.5
            return f"[stub {dept}]", 0.05

        async def discord_cb(channel: str, message: str) -> None:
            discord_posts.append((channel, message))

        engine = WorkflowEngine(
            department_runner=dept_runner,
            discord_callback=discord_cb,
        )

        run_id = engine.start(cfg)
        # Allow the background task to complete
        await asyncio.sleep(0.2)

        state = engine.get_run_state(run_id)
        assert state is not None
        assert state.status == "completed"
        assert state.cost_usd == pytest.approx(0.7)

        # Digest should have been published to Discord
        assert discord_posts, "Expected at least one Discord post"
        channels = [ch for ch, _ in discord_posts]
        assert "operator" in channels

    @pytest.mark.asyncio
    async def test_digest_output_in_context(self, cfg) -> None:
        """After workflow, 'digest' key should be in context."""
        async def dept_runner(dept, intent, ctx):
            return f"[{dept} result]", 0.1

        engine = WorkflowEngine(department_runner=dept_runner)
        run_id = engine.start(cfg)
        await asyncio.sleep(0.2)

        state = engine.get_run_state(run_id)
        assert state is not None
        assert "digest" in state.context

    @pytest.mark.asyncio
    async def test_parallel_steps_both_run(self, cfg) -> None:
        """Strategy and ops steps must both execute."""
        departments_called: list[str] = []

        async def dept_runner(dept, intent, ctx):
            departments_called.append(dept)
            return f"[{dept}]", 0.1

        engine = WorkflowEngine(department_runner=dept_runner)
        run_id = engine.start(cfg)
        await asyncio.sleep(0.2)

        assert "strategy" in departments_called
        assert "ops" in departments_called

    def test_registry_includes_workflow(self, registry: WorkflowRegistry) -> None:
        """WorkflowRegistry should load weekly-ceo-review."""
        assert "weekly-ceo-review" in registry.names()

    def test_registry_trigger_returns_run_id(self, registry: WorkflowRegistry) -> None:
        """Triggering via registry returns a run_id string."""
        mock_engine = MagicMock()
        mock_engine.start = MagicMock(return_value="run-abc-123")

        run_id = registry.trigger("weekly-ceo-review", engine=mock_engine)
        assert run_id == "run-abc-123"


@pytest.mark.live
class TestWeeklyCEOReviewLive:
    """Live integration tests — require real department infrastructure."""

    def test_live_placeholder(self) -> None:
        """Placeholder: live CEO review requires wired Z4 departments."""
        pytest.skip("Live test: requires wired Z4 department runner")
