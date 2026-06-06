"""Lean readiness route contracts for Zone 4 departments."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_teams.conftest import make_deps
from teams import BridgeDeps, DepartmentRegistry
from teams._types import TeamResult


_TEAMS_DIR = Path(__file__).parent.parent.parent / "config" / "teams"


class ExplodingSemaphore:
    def acquire(self, department: str):  # noqa: ANN201
        raise AssertionError("readiness must not acquire the department semaphore")


@pytest.fixture
def registry() -> DepartmentRegistry:
    return DepartmentRegistry.from_directory(_TEAMS_DIR)


@pytest.fixture
def deps() -> BridgeDeps:
    return make_deps(session_id="readiness-test", department="strategy")


def _registry_with_exploding_semaphore() -> DepartmentRegistry:
    base = DepartmentRegistry.from_directory(_TEAMS_DIR)
    configs = {name: base.get_config(name) for name in base.department_names()}
    return DepartmentRegistry(configs=configs, semaphore=ExplodingSemaphore())


@pytest.mark.asyncio
async def test_readiness_prompt_bypasses_team_run_and_semaphore(
    deps: BridgeDeps,
) -> None:
    registry = _registry_with_exploding_semaphore()

    result = await registry.route("strategy", "ready to work?", deps)

    assert result.success is True
    assert result.department == "strategy"
    assert result.duration_seconds == 0.0
    assert "Deterministic readiness status" in result.manager_output
    assert "Strategy department is online" in result.manager_output
    assert "Chief: strategy-product-chief" in result.manager_output
    assert "Specialists on roster: 7" in result.manager_output
    assert "Delegation floor: 1" in result.manager_output
    assert "Warm idle: 14400s" in result.manager_output
    assert "Model families:" in result.manager_output
    # #2566 hybrid fleet: chief on anthropic-oauth, specialists on codex-exec
    # (strategy keeps one openai canary). OpenRouter is dead — readiness no
    # longer emits it.
    assert "anthropic-oauth" in result.manager_output
    assert "codex-exec" in result.manager_output
    assert "Known surface blockers: none for readiness" in result.manager_output


@pytest.mark.asyncio
async def test_non_readiness_prompt_still_runs_department_team(
    registry: DepartmentRegistry,
    deps: BridgeDeps,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    team = registry.get_team("strategy")

    async def fake_run(task: str, **kwargs: object) -> TeamResult:
        calls.append(task)
        return TeamResult(
            department="strategy",
            manager_output="substantive route",
            success=True,
        )

    monkeypatch.setattr(team, "run", fake_run)

    result = await registry.route("strategy", "ready to work on pricing?", deps)

    assert result.success is True
    assert result.manager_output == "substantive route"
    assert calls == ["ready to work on pricing?"]

