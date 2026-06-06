"""Tests for WorkflowRegistry + /workflows command (sprint F-W.5)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from bridge.workflow_registry import WorkflowRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workflow_dir(tmp_path: Path) -> Path:
    """Return a temp directory with two workflow YAML files."""
    (tmp_path / "wf-a.yaml").write_text(
        textwrap.dedent(
            """\
            name: wf-a
            trigger: explicit
            budget:
              max_cost_usd: 1.0
            steps:
              - name: step1
                department: ops
                intent: "Do ops stuff"
                outputs: [result]
            """
        )
    )
    (tmp_path / "wf-b.yaml").write_text(
        textwrap.dedent(
            """\
            name: wf-b
            trigger: schedule
            schedule: "cron:0 8 * * 1"
            steps:
              - name: gather
                department: strategy
                intent: "Gather weekly signals"
                outputs: [signals]
              - name: decide
                department: board
                intent: "Decide from {signals}"
                inputs: [signals]
                outputs: [decision]
            """
        )
    )
    return tmp_path


@pytest.fixture()
def registry(workflow_dir: Path) -> WorkflowRegistry:
    return WorkflowRegistry(config_dir=workflow_dir)


# ---------------------------------------------------------------------------
# Load / names
# ---------------------------------------------------------------------------


class TestLoading:
    def test_loads_all_yamls(self, registry: WorkflowRegistry) -> None:
        assert set(registry.names()) == {"wf-a", "wf-b"}

    def test_ignores_invalid_yaml(self, workflow_dir: Path) -> None:
        (workflow_dir / "bad.yaml").write_text("name: bad\ntrigger: schedule\nsteps: []\n")
        reg = WorkflowRegistry(config_dir=workflow_dir)
        # bad.yaml fails validation (schedule trigger requires schedule field)
        assert "bad" not in reg.names()

    def test_empty_dir(self, tmp_path: Path) -> None:
        reg = WorkflowRegistry(config_dir=tmp_path)
        assert reg.names() == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        reg = WorkflowRegistry(config_dir=tmp_path / "does-not-exist")
        assert reg.names() == []

    def test_reload_picks_up_new_file(
        self, workflow_dir: Path, registry: WorkflowRegistry
    ) -> None:
        (workflow_dir / "wf-c.yaml").write_text(
            textwrap.dedent(
                """\
                name: wf-c
                trigger: explicit
                steps:
                  - name: s
                    department: qa
                    intent: "QA check"
                """
            )
        )
        count = registry.reload()
        assert count == 3
        assert "wf-c" in registry.names()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_existing(self, registry: WorkflowRegistry) -> None:
        cfg = registry.get("wf-a")
        assert cfg is not None
        assert cfg.name == "wf-a"

    def test_get_missing(self, registry: WorkflowRegistry) -> None:
        assert registry.get("does-not-exist") is None


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    def test_list_returns_all(self, registry: WorkflowRegistry) -> None:
        entries = registry.list()
        names = {e["name"] for e in entries}
        assert names == {"wf-a", "wf-b"}

    def test_list_has_expected_keys(self, registry: WorkflowRegistry) -> None:
        entry = next(e for e in registry.list() if e["name"] == "wf-a")
        assert "trigger" in entry
        assert "steps" in entry
        assert "budget_usd" in entry
        assert "last_run" in entry

    def test_list_step_count(self, registry: WorkflowRegistry) -> None:
        entry = next(e for e in registry.list() if e["name"] == "wf-b")
        assert entry["steps"] == 2

    def test_last_run_none_without_store(self, registry: WorkflowRegistry) -> None:
        for entry in registry.list():
            assert entry["last_run"] is None

    def test_last_run_populated_with_store(self, workflow_dir: Path) -> None:
        mock_run = MagicMock()
        mock_run.id = "run-abc"
        mock_run.status = "completed"
        mock_run.created_at = "2026-04-18T08:00:00"
        mock_run.cost_usd = 0.5

        mock_store = MagicMock()
        mock_store.list_runs_for_workflow = MagicMock(return_value=[mock_run])

        reg = WorkflowRegistry(config_dir=workflow_dir, store=mock_store)
        entries = reg.list()
        for entry in entries:
            assert entry["last_run"] is not None
            assert entry["last_run"]["id"] == "run-abc"


# ---------------------------------------------------------------------------
# trigger / cancel
# ---------------------------------------------------------------------------


class TestTrigger:
    def test_trigger_without_engine_returns_none(
        self, registry: WorkflowRegistry
    ) -> None:
        result = registry.trigger("wf-a")
        assert result is None

    def test_trigger_missing_workflow_raises(
        self, registry: WorkflowRegistry
    ) -> None:
        with pytest.raises(KeyError):
            registry.trigger("no-such-workflow")

    def test_trigger_with_engine(self, registry: WorkflowRegistry) -> None:
        mock_engine = MagicMock()
        mock_engine.start = MagicMock(return_value="run-xyz")
        run_id = registry.trigger("wf-a", {"key": "val"}, engine=mock_engine)
        assert run_id == "run-xyz"
        mock_engine.start.assert_called_once()


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_without_engine_returns_false(
        self, registry: WorkflowRegistry
    ) -> None:
        assert await registry.cancel("run-123") is False

    @pytest.mark.asyncio
    async def test_cancel_with_engine(self, registry: WorkflowRegistry) -> None:
        # C.06 (#2061): engine.cancel is now an async coroutine.
        mock_engine = MagicMock()

        async def _cancel(run_id: str) -> bool:
            return True

        mock_engine.cancel = _cancel
        result = await registry.cancel("run-abc", engine=mock_engine)
        assert result is True


# ---------------------------------------------------------------------------
# format helpers
# ---------------------------------------------------------------------------


class TestFormatList:
    def test_format_list_contains_workflow_names(
        self, registry: WorkflowRegistry
    ) -> None:
        text = registry.format_list()
        assert "wf-a" in text
        assert "wf-b" in text

    def test_format_list_empty(self, tmp_path: Path) -> None:
        reg = WorkflowRegistry(config_dir=tmp_path)
        assert reg.format_list() == "No workflows loaded."


class TestFormatDetail:
    def test_detail_existing(self, registry: WorkflowRegistry) -> None:
        text = registry.format_detail("wf-b")
        assert "wf-b" in text
        assert "schedule" in text.lower()
        assert "gather" in text
        assert "decide" in text

    def test_detail_missing(self, registry: WorkflowRegistry) -> None:
        text = registry.format_detail("ghost")
        assert "not found" in text.lower()
