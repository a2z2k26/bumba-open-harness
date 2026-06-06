"""S04 — DEPARTMENT MCP filter contract tests (#566)."""
from __future__ import annotations

import json
import os
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from bridge.executors.department import DepartmentExecutor
from bridge.work_order import Environment, WorkOrder, WorkOrderStatus


def _wo_for(dept: str) -> WorkOrder:
    from dataclasses import replace
    wo = (
        WorkOrder.create(intent="x", skill="review-pr", project="p")
        .with_environment(Environment.DEPARTMENT, "t")
        .transition(WorkOrderStatus.ASSIGNED)
    )
    return replace(wo, department_target=dept)


# ---------------------------------------------------------------------------
# AC-1: BridgeDeps has mcp_allowed_servers field
# ---------------------------------------------------------------------------

def test_bridge_deps_mcp_allowed_servers_is_tuple():
    """AC-1: BridgeDeps.mcp_allowed_servers exists as tuple with default ()."""
    from teams._types import BridgeDeps
    d = BridgeDeps(
        session_id="s",
        department="eng",
        operator_id="op",
        memory_store=None,
        event_bus=None,
        trust_manager=None,
        cost_tracker=None,
        knowledge_search=None,
        mcp_allowed_servers=("github",),
    )
    assert d.mcp_allowed_servers == ("github",)


def test_bridge_deps_mcp_allowed_servers_default_is_empty():
    """AC-1: Default mcp_allowed_servers is ()."""
    from teams._types import BridgeDeps
    d = BridgeDeps(
        session_id="s",
        department="eng",
        operator_id="op",
        memory_store=None,
        event_bus=None,
        trust_manager=None,
        cost_tracker=None,
        knowledge_search=None,
    )
    assert d.mcp_allowed_servers == ()


def test_bridge_deps_is_frozen():
    """BridgeDeps is frozen — mutation raises."""
    from teams._types import BridgeDeps
    d = BridgeDeps(
        session_id="s",
        department="eng",
        operator_id="op",
        memory_store=None,
        event_bus=None,
        trust_manager=None,
        cost_tracker=None,
        knowledge_search=None,
        mcp_allowed_servers=("github",),
    )
    with pytest.raises((AttributeError, TypeError)):
        d.mcp_allowed_servers = ("x",)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC-2: DepartmentExecutor passes mcp_subset from YAML config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_department_executor_passes_mcp_subset():
    """AC-2: DepartmentExecutor passes mcp_subset from YAML to BridgeDeps."""
    registry = MagicMock()
    registry.department_names = MagicMock(return_value=["eng"])
    registry.get_cost_limit = MagicMock(return_value=2.0)
    captured: dict = {}

    async def fake_route(dept, intent, deps):
        captured["deps"] = deps
        return MagicMock(success=True, manager_output="ok", total_cost_usd=0.01, error=None)

    registry.route = fake_route

    executor = DepartmentExecutor(department_registry=registry, app=None, event_bus=None)

    # Sprint P2.4: _load_dept_mcp_subset now returns (servers, mode).
    with patch.object(
        DepartmentExecutor,
        "_load_dept_mcp_subset",
        return_value=(("github", "notion"), "permissive"),
    ):
        await executor.execute(_wo_for("eng"))

    assert captured["deps"].mcp_allowed_servers == ("github", "notion")


@pytest.mark.asyncio
async def test_department_executor_passes_empty_tuple_when_no_yaml():
    """When no mcp_servers in YAML, mcp_allowed_servers is () (permissive fallback)."""
    registry = MagicMock()
    registry.department_names = MagicMock(return_value=["eng"])
    registry.get_cost_limit = MagicMock(return_value=2.0)
    captured: dict = {}

    async def fake_route(dept, intent, deps):
        captured["deps"] = deps
        return MagicMock(success=True, manager_output="ok", total_cost_usd=0.01, error=None)

    registry.route = fake_route

    executor = DepartmentExecutor(department_registry=registry, app=None, event_bus=None)

    # Sprint P2.4: _load_dept_mcp_subset now returns (servers, mode).
    with patch.object(
        DepartmentExecutor,
        "_load_dept_mcp_subset",
        return_value=((), "permissive"),
    ):
        await executor.execute(_wo_for("eng"))

    assert captured["deps"].mcp_allowed_servers == ()


# ---------------------------------------------------------------------------
# AC-3: _prepare_filtered_mcp writes a 0600 JSON with only allowed servers
# ---------------------------------------------------------------------------

def test_registry_creates_filtered_mcp_file_when_subset_nonempty(tmp_path, monkeypatch):
    """AC-3: _prepare_filtered_mcp writes a filtered JSON file with mode 0600."""
    master = {
        "mcpServers": {
            "github": {"command": "a"},
            "cloudflare": {"command": "b"},
            "notion": {"command": "c"},
        }
    }
    fake_master = tmp_path / ".mcp.json"
    fake_master.write_text(json.dumps(master))

    import teams._registry as reg

    # Monkeypatch the master path detection inside _prepare_filtered_mcp
    original_path_class = pathlib.Path

    def patched_path(p):
        if str(p).endswith(".mcp.json"):
            return fake_master
        return original_path_class(p)

    monkeypatch.setattr(reg, "_get_master_mcp_path", lambda: fake_master)

    from teams._types import BridgeDeps
    deps = BridgeDeps(
        session_id="s",
        department="eng",
        operator_id="op",
        memory_store=None,
        event_bus=None,
        trust_manager=None,
        cost_tracker=None,
        knowledge_search=None,
        mcp_allowed_servers=("github", "notion"),
    )
    path = reg._prepare_filtered_mcp(deps)
    assert path is not None

    filtered = json.loads(pathlib.Path(path).read_text())
    assert set(filtered["mcpServers"].keys()) == {"github", "notion"}
    assert "cloudflare" not in filtered["mcpServers"]

    file_mode = os.stat(path).st_mode & 0o777
    assert file_mode == 0o600, f"Expected 0600, got {oct(file_mode)}"

    reg._cleanup_filtered_mcp(path)
    assert not pathlib.Path(path).exists()


# ---------------------------------------------------------------------------
# AC-4: _prepare_filtered_mcp returns None when subset is empty
# ---------------------------------------------------------------------------

def test_registry_returns_none_when_subset_empty():
    """AC-4: Empty mcp_allowed_servers → no filter (permissive fallback, returns None)."""
    import teams._registry as reg
    from teams._types import BridgeDeps
    deps = BridgeDeps(
        session_id="s",
        department="eng",
        operator_id="op",
        memory_store=None,
        event_bus=None,
        trust_manager=None,
        cost_tracker=None,
        knowledge_search=None,
    )
    assert reg._prepare_filtered_mcp(deps) is None


# ---------------------------------------------------------------------------
# AC-3/AC-4: _cleanup_filtered_mcp is idempotent
# ---------------------------------------------------------------------------

def test_cleanup_filtered_mcp_is_idempotent(tmp_path):
    """_cleanup_filtered_mcp does not raise if the file was already deleted."""
    import teams._registry as reg
    path = tmp_path / "nonexistent.json"
    assert not path.exists()
    reg._cleanup_filtered_mcp(str(path))  # should not raise
    # Idempotency contract: the missing-file path completed and the
    # filesystem state is unchanged.
    assert not path.exists()
    # And a second call on the still-missing path is also a no-op.
    reg._cleanup_filtered_mcp(str(path))
    assert not path.exists()


# ---------------------------------------------------------------------------
# DepartmentExecutor._load_dept_mcp_subset
# ---------------------------------------------------------------------------

def test_load_dept_mcp_subset_reads_yaml(tmp_path):
    """_load_dept_mcp_subset reads legacy top-level mcp_servers from YAML.

    P2.4: legacy top-level `mcp_servers` is still honored — return value
    is now a (servers, mode) tuple. Legacy callers always run under
    `permissive` mode.
    """
    teams_yaml_dir = tmp_path / "teams"
    teams_yaml_dir.mkdir()
    (teams_yaml_dir / "eng.yaml").write_text("mcp_servers:\n  - github\n  - notion\n")

    executor = DepartmentExecutor(department_registry=MagicMock(), app=None, event_bus=None)
    with patch.object(
        type(executor), "_teams_config_dir",
        new_callable=lambda: property(lambda self: teams_yaml_dir),
    ):
        servers, mode = executor._load_dept_mcp_subset("eng")
    assert set(servers) == {"github", "notion"}
    assert mode == "permissive"


def test_load_dept_mcp_subset_returns_empty_for_missing_file():
    """_load_dept_mcp_subset returns ((), "permissive") if no YAML."""
    executor = DepartmentExecutor(department_registry=MagicMock(), app=None, event_bus=None)
    servers, mode = executor._load_dept_mcp_subset("nonexistent-department-xyz")
    assert servers == ()
    assert mode == "permissive"


# ---------------------------------------------------------------------------
# Sprint P2.4 — structured `team.mcp` block (preferred over legacy top-level)
# ---------------------------------------------------------------------------


def test_load_dept_mcp_subset_prefers_structured_block(tmp_path):
    """P2.4: when `team.mcp.allowed_servers` is set, the legacy top-level
    `mcp_servers` is ignored. The structured `mode` is returned alongside.
    """
    teams_yaml_dir = tmp_path / "teams"
    teams_yaml_dir.mkdir()
    yaml_text = """\
team:
  name: eng
  zone: 4
  mcp:
    mode: deny_by_default
    allowed_servers: [github, notion]
  chief:
    name: c
  workers: []
mcp_servers: [should-be-ignored]
"""
    (teams_yaml_dir / "eng.yaml").write_text(yaml_text)

    executor = DepartmentExecutor(department_registry=MagicMock(), app=None, event_bus=None)
    with patch.object(
        type(executor), "_teams_config_dir",
        new_callable=lambda: property(lambda self: teams_yaml_dir),
    ):
        servers, mode = executor._load_dept_mcp_subset("eng")
    assert set(servers) == {"github", "notion"}
    assert mode == "deny_by_default"


def test_load_dept_mcp_subset_falls_back_to_top_level_when_no_structured(tmp_path):
    """P2.4: backward compat — unmigrated YAMLs with only top-level
    `mcp_servers` continue to work; mode defaults to permissive.
    """
    teams_yaml_dir = tmp_path / "teams"
    teams_yaml_dir.mkdir()
    (teams_yaml_dir / "eng.yaml").write_text("mcp_servers: [github]\n")

    executor = DepartmentExecutor(department_registry=MagicMock(), app=None, event_bus=None)
    with patch.object(
        type(executor), "_teams_config_dir",
        new_callable=lambda: property(lambda self: teams_yaml_dir),
    ):
        servers, mode = executor._load_dept_mcp_subset("eng")
    assert servers == ("github",)
    assert mode == "permissive"


def test_prepare_filtered_mcp_deny_by_default_empty_emits_empty_config(tmp_path, monkeypatch):
    """P2.4: deny_by_default + empty allowed_servers → writes `{}` filtered config.

    This is the explicit "no MCP servers at all" path the audit called
    for. Distinct from permissive-empty which returns None (inherit
    bridge default).
    """
    master = {"mcpServers": {"github": {"command": "g"}}}
    fake_master = tmp_path / ".mcp.json"
    fake_master.write_text(json.dumps(master))

    import teams._registry as reg
    monkeypatch.setattr(reg, "_get_master_mcp_path", lambda: fake_master)

    from teams._types import BridgeDeps
    deps = BridgeDeps(
        session_id="s",
        department="eng",
        operator_id="op",
        memory_store=None,
        event_bus=None,
        trust_manager=None,
        cost_tracker=None,
        knowledge_search=None,
        mcp_allowed_servers=(),
        mcp_mode="deny_by_default",
    )
    path = reg._prepare_filtered_mcp(deps)
    assert path is not None, "deny_by_default + empty must emit a file, not None"

    filtered = json.loads(pathlib.Path(path).read_text())
    # Empty allowlist + deny_by_default → no servers in the filtered config.
    assert filtered.get("mcpServers", {}) == {} or "mcpServers" not in filtered

    reg._cleanup_filtered_mcp(path)


def test_prepare_filtered_mcp_permissive_empty_still_returns_none():
    """P2.4 regression guard: permissive + empty preserves old behaviour."""
    import teams._registry as reg
    from teams._types import BridgeDeps
    deps = BridgeDeps(
        session_id="s",
        department="eng",
        operator_id="op",
        memory_store=None,
        event_bus=None,
        trust_manager=None,
        cost_tracker=None,
        knowledge_search=None,
        mcp_allowed_servers=(),
        mcp_mode="permissive",
    )
    assert reg._prepare_filtered_mcp(deps) is None
