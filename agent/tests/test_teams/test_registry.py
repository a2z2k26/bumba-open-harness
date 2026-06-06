"""Tests for teams._registry.DepartmentRegistry."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from teams._registry import DepartmentRegistry
from tests.test_teams.conftest import make_deps


@pytest.fixture
def teams_dir(tmp_path: Path) -> Path:
    d = tmp_path / "teams"
    d.mkdir()
    (d / "qa.yaml").write_text(textwrap.dedent("""\
        team:
          name: qa
          zone: 4
          description: QA
          chief:
            name: qa-chief
            model: anthropic:claude-opus-4-6
          workers:
            - name: qa-engineer
              model: anthropic:claude-sonnet-4-6
    """))
    (d / "design.yaml").write_text(textwrap.dedent("""\
        team:
          name: design
          zone: 4
          description: Design
          chief:
            name: design-chief
            model: anthropic:claude-opus-4-6
          workers: []
    """))
    return d


class TestDepartmentRegistry:
    def test_discovers_configs(self, teams_dir: Path):
        reg = DepartmentRegistry.from_directory(teams_dir)
        assert set(reg.department_names()) == {"qa", "design"}

    def test_lazy_load(self, teams_dir: Path):
        reg = DepartmentRegistry.from_directory(teams_dir)
        assert reg._teams == {}  # nothing built yet

        team = reg.get_team("qa")
        assert team.config.name == "qa"
        assert "qa" in reg._teams

    def test_get_team_unknown_raises(self, teams_dir: Path):
        reg = DepartmentRegistry.from_directory(teams_dir)
        with pytest.raises(KeyError):
            reg.get_team("nonexistent")

    def test_empty_directory(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        reg = DepartmentRegistry.from_directory(empty)
        assert reg.department_names() == []

    def test_missing_directory(self, tmp_path: Path):
        nonexistent = tmp_path / "nonexistent"
        reg = DepartmentRegistry.from_directory(nonexistent)
        assert reg.department_names() == []

    def test_underscore_prefix_files_skipped(self, teams_dir: Path):
        """D7.13 #1425 — `_template.yaml` and other `_*.yaml` files are
        non-runtime scaffolding artifacts; the registry must skip them.
        """
        # Plant a malformed _template.yaml — if discovery were to load it,
        # the missing `team:` block would either raise or register a team
        # named "template". Either outcome would fail this test.
        (teams_dir / "_template.yaml").write_text("not_a_team: {}\n")
        reg = DepartmentRegistry.from_directory(teams_dir)
        assert set(reg.department_names()) == {"qa", "design"}
        assert "template" not in reg.department_names()
        assert "_template" not in reg.department_names()

    @pytest.mark.skip(
        reason=(
            "strict-floor activated 2026-05-12 per #1645 + classification doc "
            "(docs/architecture/2026-05-12-1645-delegation-floor-classification.md, "
            "Class A). Routing-end-to-end via direct-answer retired with the "
            "strict-floor convention; routing dispatch is still covered by "
            "the registry's other unit/integration tests."
        )
    )
    @pytest.mark.asyncio
    async def test_route_runs_department(self, teams_dir: Path):
        from pydantic_ai.models.test import TestModel

        reg = DepartmentRegistry.from_directory(teams_dir)
        deps = make_deps(session_id="s1", department="qa")

        team = reg.get_team("qa")
        test_model = TestModel(custom_output_args={"answer": "QA routed"}, call_tools=[])
        with team.manager.override(model=test_model):
            result = await reg.route("qa", "review module", deps)

        assert result.department == "qa"
        assert result.success is True
        assert "QA routed" in result.manager_output

    @pytest.mark.asyncio
    async def test_route_unknown_department(self, teams_dir: Path):
        reg = DepartmentRegistry.from_directory(teams_dir)
        deps = make_deps(session_id="s1", department="unknown")
        result = await reg.route("nonexistent", "task", deps)
        assert result.success is False
        assert "Unknown department" in (result.error or "")


class TestPerDepartmentSemaphore:
    """Sprint #1972 — per-department semaphore honors YAML concurrency_limit.

    Before #1972, a single global ``DepartmentSemaphore`` was constructed
    in ``__init__`` with the default cap of 2; the YAML
    ``constraints.concurrency_limit`` field was loaded into the dataclass
    but never threaded into the runtime. 5 of 6 production departments
    were running at the wrong cap.
    """

    def test_each_department_gets_semaphore_sized_to_its_yaml_cap(
        self, tmp_path: Path
    ):
        """Departments with different declared caps get different semaphores."""
        d = tmp_path / "teams"
        d.mkdir()
        (d / "low.yaml").write_text(textwrap.dedent("""\
            team:
              name: low
              zone: 4
              description: low-concurrency
              constraints:
                concurrency_limit: 1
              chief:
                name: low-chief
                model: anthropic:claude-opus-4-6
              workers: []
        """))
        (d / "high.yaml").write_text(textwrap.dedent("""\
            team:
              name: high
              zone: 4
              description: high-concurrency
              constraints:
                concurrency_limit: 8
              chief:
                name: high-chief
                model: anthropic:claude-opus-4-6
              workers: []
        """))
        reg = DepartmentRegistry.from_directory(d)
        low_sem = reg._get_semaphore("low")
        high_sem = reg._get_semaphore("high")
        assert low_sem.limit == 1
        assert high_sem.limit == 8
        # Different instances per department (not a shared global).
        assert low_sem is not high_sem

    def test_repeated_get_returns_same_semaphore_instance(
        self, tmp_path: Path
    ):
        """Lazy-create: second lookup returns the cached instance."""
        d = tmp_path / "teams"
        d.mkdir()
        (d / "qa.yaml").write_text(textwrap.dedent("""\
            team:
              name: qa
              zone: 4
              description: QA
              constraints:
                concurrency_limit: 4
              chief:
                name: qa-chief
                model: anthropic:claude-opus-4-6
              workers: []
        """))
        reg = DepartmentRegistry.from_directory(d)
        first = reg._get_semaphore("qa")
        second = reg._get_semaphore("qa")
        assert first is second
        assert first.limit == 4

    def test_explicit_semaphore_override_wins_for_test_injection(
        self, tmp_path: Path
    ):
        """When __init__ receives a semaphore=, every dept uses that instance.

        Preserves the test-injection contract for existing tests that pass
        a custom semaphore (e.g. to drive a specific concurrency scenario).
        """
        from teams._semaphore import DepartmentSemaphore

        d = tmp_path / "teams"
        d.mkdir()
        (d / "qa.yaml").write_text(textwrap.dedent("""\
            team:
              name: qa
              zone: 4
              description: QA
              constraints:
                concurrency_limit: 4
              chief:
                name: qa-chief
                model: anthropic:claude-opus-4-6
              workers: []
        """))
        (d / "design.yaml").write_text(textwrap.dedent("""\
            team:
              name: design
              zone: 4
              description: Design
              constraints:
                concurrency_limit: 1
              chief:
                name: design-chief
                model: anthropic:claude-opus-4-6
              workers: []
        """))
        configs = {}
        from teams._config import load_department_config
        for yaml_file in sorted(d.glob("*.yaml")):
            cfg = load_department_config(yaml_file)
            configs[cfg.name] = cfg

        override = DepartmentSemaphore(limit=99)
        reg = DepartmentRegistry(configs=configs, semaphore=override)

        # Both departments return the override, ignoring their YAML caps.
        assert reg._get_semaphore("qa") is override
        assert reg._get_semaphore("design") is override

    def test_unknown_department_falls_back_to_default_limit(
        self, teams_dir: Path
    ):
        """Defensive: lookups for unknown department names use DEFAULT_LIMIT.

        Real route() path catches unknown departments earlier; this branch
        covers test fixtures that hand-build partial configs.
        """
        from teams._semaphore import DEFAULT_LIMIT

        reg = DepartmentRegistry.from_directory(teams_dir)
        sem = reg._get_semaphore("nonexistent")
        assert sem.limit == DEFAULT_LIMIT
