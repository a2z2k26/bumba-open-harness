"""Report-only runtime checks for Zone 4 capability manifests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from bridge.capability_manifest import (
    CapabilityGrant,
    CapabilityManifest,
    compare_capabilities,
)
from teams import _factory
from teams._agent_cache import AgentCache
from teams._config import load_department_config_from_string
from teams._factory import build_employee_agents, build_manager_agent
from teams._team import DepartmentTeam
from teams._types import AgentSpec, DepartmentConfig, TeamOutput
from tests.test_teams.conftest import make_deps


@dataclass(frozen=True)
class _RunResult:
    output: TeamOutput

    def usage(self) -> None:
        return None


def _manifest_path(root: Path, department: str, body: str) -> Path:
    path = root / f"{department}.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _config() -> DepartmentConfig:
    return DepartmentConfig(
        name="strategy",
        zone=4,
        description="Strategy department for report-only checks",
        manager=AgentSpec(
            name="strategy-product-chief",
            model="anthropic:claude-opus-4-6",
            skills=("mental-model", "active-listener"),
        ),
        employees=(
            AgentSpec(
                name="strategy-market-researcher",
                model="anthropic:claude-sonnet-4-6",
                skills=("mental-model", "exploratory-research"),
            ),
        ),
        common_tools=("read_file",),
        department_tools=("analyze_competitor",),
        mcp_mode="deny_by_default",
        mcp_allowed_servers=("notion",),
        capability_manifest_enforced=True,
    )


def test_department_config_loader_preserves_yaml_skills() -> None:
    config = load_department_config_from_string(
        """
team:
  name: strategy
  zone: 4
  chief:
    name: strategy-product-chief
    skills:
      - mental-model
      - active-listener
  workers:
    - name: strategy-market-researcher
      skills:
        - market-research
""",
        source="capability-skill-test.yaml",
    )

    assert config.manager.skills == ("mental-model", "active-listener")
    assert config.employees[0].skills == ("market-research",)


def test_compare_capabilities_reports_extra_and_missing_runtime_access() -> None:
    manifest = CapabilityManifest(
        department="strategy",
        mode="report_only",
        defaults=CapabilityGrant(tools=("read_file",), skills=("mental-model",)),
        chief={},
        specialists={},
        path=Path("strategy.yaml"),
    )

    report = compare_capabilities(
        department="strategy",
        agent_name="strategy-market-researcher",
        role="specialist",
        actual_tools=("read_file", "analyze_competitor"),
        actual_skills=("exploratory-research",),
        actual_mcp_servers=("notion",),
        manifest=manifest,
    )

    assert report.department == "strategy"
    assert report.agent == "strategy-market-researcher"
    assert report.role == "specialist"
    assert report.mode == "report_only"
    assert report.extra_tools == ("analyze_competitor",)
    assert report.missing_tools == ()
    assert report.extra_skills == ("exploratory-research",)
    assert report.missing_skills == ("mental-model",)
    assert report.extra_mcp_servers == ("notion",)
    assert report.has_violation is True
    assert (
        ("capability.strategy-market-researcher.extra_tools", "analyze_competitor")
        in report.telemetry_fields()
    )


def test_report_only_violation_does_not_block_employee_agent_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _manifest_path(
        tmp_path,
        "strategy",
        """
department: strategy
mode: report_only
defaults:
  tools:
    - read_file
  skills:
    - mental-model
  mcp_servers: []
chief:
  strategy-product-chief: {}
specialists:
  strategy-market-researcher: {}
""",
    )
    monkeypatch.setattr(_factory, "_CAPABILITY_MANIFEST_ROOT", tmp_path)

    with caplog.at_level(logging.INFO, logger="teams._factory"):
        employees = build_employee_agents(_config(), agent_cache=AgentCache())

    agent = employees["strategy-market-researcher"]
    report = agent._bumba_capability_report

    assert report.mode == "report_only"
    assert "analyze_competitor" in report.extra_tools
    assert "exploratory-research" in report.extra_skills
    assert report.extra_mcp_servers == ("notion",)
    assert "capability.report_only_violation" in caplog.text
    assert "strategy-market-researcher" in caplog.text


def test_report_only_manager_build_exposes_capability_telemetry_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _manifest_path(
        tmp_path,
        "strategy",
        """
department: strategy
mode: report_only
defaults:
  tools:
    - read_file
  skills: []
  mcp_servers: []
chief:
  strategy-product-chief:
    skills:
      - mental-model
specialists:
  strategy-market-researcher:
    skills:
      - mental-model
""",
    )
    monkeypatch.setattr(_factory, "_CAPABILITY_MANIFEST_ROOT", tmp_path)
    config = _config()
    cache = AgentCache()
    employees = build_employee_agents(config, agent_cache=cache)

    with caplog.at_level(logging.INFO, logger="teams._factory"):
        manager = build_manager_agent(
            config,
            employees,
            agent_cache=cache,
        )

    report = manager._bumba_capability_report
    telemetry = dict(manager._bumba_capability_telemetry)

    assert report.agent == "strategy-product-chief"
    assert "active-listener" in report.extra_skills
    assert "capability.strategy-product-chief.extra_skills" in telemetry
    assert "active-listener" in telemetry["capability.strategy-product-chief.extra_skills"]
    assert "capability.report_only_violation" in caplog.text


@pytest.mark.asyncio
async def test_report_only_fields_are_included_in_run_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _manifest_path(
        tmp_path,
        "strategy",
        """
department: strategy
mode: report_only
defaults:
  tools:
    - read_file
  skills: []
  mcp_servers: []
chief:
  strategy-product-chief:
    skills:
      - mental-model
specialists:
  strategy-market-researcher:
    skills:
      - mental-model
""",
    )
    monkeypatch.setattr(_factory, "_CAPABILITY_MANIFEST_ROOT", tmp_path)
    team = DepartmentTeam(config=_config(), lazy_build=False)
    deps = make_deps(session_id="s1", department="strategy")

    with patch.object(
        team.manager,
        "run",
        new=AsyncMock(return_value=_RunResult(output=TeamOutput(answer="done"))),
    ):
        result = await team.run("size the market", deps=deps)

    assert result.telemetry is not None
    telemetry = dict(result.telemetry.extra)
    assert "capability.strategy-product-chief.extra_skills" in telemetry
    assert "active-listener" in telemetry["capability.strategy-product-chief.extra_skills"]
