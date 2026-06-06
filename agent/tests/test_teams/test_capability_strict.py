"""Strict runtime checks for Zone 4 capability manifests."""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.capability_manifest import (
    CapabilityGrant,
    CapabilityManifestError,
    filter_tools_for_manifest,
)
from teams import _factory
from teams._agent_cache import AgentCache
from teams._config import load_department_config
from teams._factory import build_employee_agents, build_manager_agent
from teams._types import AgentSpec, DepartmentConfig


AGENT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOT = AGENT_ROOT / "config" / "capabilities" / "zone4"
TEAMS_ROOT = AGENT_ROOT / "config" / "teams"


def _write_manifest(root: Path, body: str) -> Path:
    path = root / "strategy.yaml"
    path.write_text(body, encoding="utf-8")
    return root


def _config_with_extra_tools() -> DepartmentConfig:
    return DepartmentConfig(
        name="strategy",
        zone=4,
        description="Strategy strict-mode fixture",
        manager=AgentSpec(
            name="strategy-product-chief",
            model="anthropic:claude-opus-4-6",
            skills=("mental-model",),
        ),
        employees=(
            AgentSpec(
                name="strategy-market-researcher",
                model="anthropic:claude-sonnet-4-6",
                skills=("mental-model",),
            ),
        ),
        common_tools=("read_file",),
        department_tools=("analyze_competitor",),
        mcp_mode="deny_by_default",
        capability_manifest_enforced=True,
    )


def test_filter_tools_for_manifest_keeps_report_only_tools() -> None:
    filtered = filter_tools_for_manifest(
        actual_tools=("read_file", "analyze_competitor"),
        grant=CapabilityGrant(tools=("read_file",)),
        mode="report_only",
    )

    assert filtered == ("read_file", "analyze_competitor")


def test_filter_tools_for_manifest_removes_extra_tools_in_strict_mode() -> None:
    filtered = filter_tools_for_manifest(
        actual_tools=("read_file", "analyze_competitor"),
        grant=CapabilityGrant(tools=("read_file",)),
        mode="strict",
    )

    assert filtered == ("read_file",)


def test_strict_manifest_filters_specialist_business_and_lifecycle_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _factory,
        "_CAPABILITY_MANIFEST_ROOT",
        _write_manifest(
            tmp_path,
            """
department: strategy
mode: strict
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
        ),
    )

    employees = build_employee_agents(
        _config_with_extra_tools(),
        agent_cache=AgentCache(),
    )

    tool_names = employees["strategy-market-researcher"]._function_toolset.tools
    report = employees["strategy-market-researcher"]._bumba_capability_report
    assert tuple(tool_names) == ("read_file",)
    assert report.extra_tools == ()
    assert report.missing_tools == ()


def test_strict_manifest_filters_manager_business_and_lifecycle_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _factory,
        "_CAPABILITY_MANIFEST_ROOT",
        _write_manifest(
            tmp_path,
            """
department: strategy
mode: strict
defaults:
  tools:
    - read_file
  skills:
    - mental-model
  mcp_servers: []
chief:
  strategy-product-chief:
    tools:
      - delegate
specialists:
  strategy-market-researcher: {}
""",
        ),
    )
    config = _config_with_extra_tools()
    cache = AgentCache()

    employees = build_employee_agents(config, agent_cache=cache)
    manager = build_manager_agent(config, employees, agent_cache=cache)

    tool_names = manager._function_toolset.tools
    report = manager._bumba_capability_report
    assert tuple(tool_names) == ("delegate", "read_file")
    assert report.extra_tools == ()
    assert report.missing_tools == ()


def test_strict_manifest_missing_required_tool_fails_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _factory,
        "_CAPABILITY_MANIFEST_ROOT",
        _write_manifest(
            tmp_path,
            """
department: strategy
mode: strict
defaults:
  tools:
    - read_file
    - search_market_data
  skills:
    - mental-model
  mcp_servers: []
chief:
  strategy-product-chief: {}
specialists:
  strategy-market-researcher: {}
""",
        ),
    )

    with pytest.raises(CapabilityManifestError, match="missing required tools"):
        build_employee_agents(_config_with_extra_tools(), agent_cache=AgentCache())


def test_strict_manifest_does_not_apply_to_undeclared_synthetic_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _factory,
        "_CAPABILITY_MANIFEST_ROOT",
        _write_manifest(
            tmp_path,
            """
department: strategy
mode: strict
defaults:
  tools:
    - read_file
    - missing_for_real_roster_only
  skills: []
  mcp_servers: []
chief:
  strategy-product-chief: {}
specialists:
  strategy-market-researcher: {}
""",
        ),
    )
    config = DepartmentConfig(
        name="strategy",
        zone=4,
        description="Synthetic strategy fixture",
        manager=AgentSpec(name="synthetic-chief", model="anthropic:claude-opus-4-6"),
        employees=(
            AgentSpec(
                name="synthetic-worker",
                model="anthropic:claude-sonnet-4-6",
            ),
        ),
        common_tools=("read_file",),
        department_tools=("analyze_competitor",),
        capability_manifest_enforced=True,
    )

    employees = build_employee_agents(config, agent_cache=AgentCache())

    tool_names = employees["synthetic-worker"]._function_toolset.tools
    assert "read_file" in tool_names
    assert "analyze_competitor" in tool_names
    assert "surface" in tool_names
    assert "write_artifact" in tool_names
    assert not hasattr(employees["synthetic-worker"], "_bumba_capability_report")


def test_repo_strict_manifest_does_not_apply_to_synthetic_config_by_default() -> None:
    config = DepartmentConfig(
        name="strategy",
        zone=4,
        description="Synthetic strategy fixture with real roster names",
        manager=AgentSpec(
            name="strategy-product-chief",
            model="anthropic:claude-opus-4-6",
        ),
        employees=(
            AgentSpec(
                name="strategy-business-analyst",
                model="anthropic:claude-sonnet-4-6",
            ),
        ),
        common_tools=("read_file",),
    )

    employees = build_employee_agents(config, agent_cache=AgentCache())

    tool_names = employees["strategy-business-analyst"]._function_toolset.tools
    assert "read_file" in tool_names
    assert not hasattr(employees["strategy-business-analyst"], "_bumba_capability_report")


def test_strategy_is_the_only_strict_department_and_builds_without_drift() -> None:
    strict_departments = []
    for path in sorted(MANIFEST_ROOT.glob("*.yaml")):
        manifest = _factory.load_capability_manifest(path)
        if manifest.mode == "strict":
            strict_departments.append(manifest.department)

    assert strict_departments == ["strategy"]

    config = load_department_config(TEAMS_ROOT / "strategy.yaml")
    cache = AgentCache()
    employees = build_employee_agents(config, agent_cache=cache)
    manager = build_manager_agent(config, employees, agent_cache=cache)
    reports = [
        manager._bumba_capability_report,
        *(agent._bumba_capability_report for agent in employees.values()),
    ]

    assert reports
    assert all(not report.has_violation for report in reports)
