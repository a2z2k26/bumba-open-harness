"""Tests for E4.5 — allowed_tools / allowed_mcp_servers enforcement.

Covers:
  - Backward compat: all existing team YAMLs load without the new fields
  - Team-level allowed_tools narrows every employee
  - Per-employee allowed_mcp_servers overrides team-level
  - Empty allowlists = no narrowing (regression guard)
  - Factory applies allowlist before tool registration
"""
from __future__ import annotations

from pathlib import Path

import pytest

from teams._config import InvalidConfigError, load_department_config
from teams._types import DepartmentConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEAMS_DIR = Path(__file__).resolve().parents[3] / "agent" / "config" / "teams"

EXISTING_TEAM_YAMLS = sorted(TEAMS_DIR.glob("*.yaml"))


def _make_minimal_yaml(
    *,
    team_allowed_tools: list[str] | None = None,
    worker_allowed_mcp: list[str] | None = None,
) -> str:
    """Build a minimal team YAML with optional allowlist fields."""
    tools_block = "    common: []\n    department: []\n    per_employee: {}\n"
    if team_allowed_tools is not None:
        tools_block += f"    allowed_tools: {team_allowed_tools!r}\n"

    worker_block = "    - name: w1\n      role: worker\n"
    if worker_allowed_mcp is not None:
        worker_block += f"      allowed_mcp_servers: {worker_allowed_mcp!r}\n"

    return f"""\
team:
  name: test-dept
  zone: 4
  chief:
    name: test-chief
  workers:
{worker_block}
  tools:
{tools_block}
mcp_servers: []
"""


def _load_from_text(yaml_text: str, tmp_path: Path) -> DepartmentConfig:
    p = tmp_path / "test.yaml"
    p.write_text(yaml_text)
    return load_department_config(p)


# ---------------------------------------------------------------------------
# Backward compatibility: existing YAMLs load without the new fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("yaml_path", EXISTING_TEAM_YAMLS, ids=[p.name for p in EXISTING_TEAM_YAMLS])
def test_existing_team_yamls_load_without_allowed_tools(yaml_path: Path):
    """All existing team YAMLs must load cleanly — no ValidationError."""
    config = load_department_config(yaml_path)
    assert config.name  # sanity: non-empty name


@pytest.mark.parametrize("yaml_path", EXISTING_TEAM_YAMLS, ids=[p.name for p in EXISTING_TEAM_YAMLS])
def test_existing_team_yamls_have_empty_allowed_tools(yaml_path: Path):
    """Existing YAMLs omit allowed_tools, so DepartmentConfig.allowed_tools == ()."""
    config = load_department_config(yaml_path)
    assert config.allowed_tools == ()


@pytest.mark.parametrize("yaml_path", EXISTING_TEAM_YAMLS, ids=[p.name for p in EXISTING_TEAM_YAMLS])
def test_existing_agents_have_empty_allowed_mcp_servers(yaml_path: Path):
    """Existing YAMLs omit per-employee allowed_mcp_servers, so all agents get ()."""
    config = load_department_config(yaml_path)
    for spec in (config.manager,) + config.employees:
        assert spec.allowed_mcp_servers == ()


# ---------------------------------------------------------------------------
# Schema field loading
# ---------------------------------------------------------------------------


def test_team_level_allowed_tools_loads(tmp_path: Path):
    config = _load_from_text(
        _make_minimal_yaml(team_allowed_tools=["search_knowledge", "read_file"]),
        tmp_path,
    )
    assert config.allowed_tools == ("search_knowledge", "read_file")


def test_per_employee_allowed_mcp_servers_loads(tmp_path: Path):
    config = _load_from_text(
        _make_minimal_yaml(worker_allowed_mcp=["github", "brave-search"]),
        tmp_path,
    )
    worker = config.employees[0]
    assert worker.allowed_mcp_servers == ("github", "brave-search")


def test_empty_allowed_tools_loads(tmp_path: Path):
    config = _load_from_text(_make_minimal_yaml(team_allowed_tools=[]), tmp_path)
    assert config.allowed_tools == ()


def test_allowed_tools_extra_field_rejected(tmp_path: Path):
    """_ToolsSchema extra:forbid still rejects unknown fields."""
    bad = _make_minimal_yaml().replace(
        "    common: []", "    common: []\n    unknown_field: true"
    )
    with pytest.raises(InvalidConfigError):
        _load_from_text(bad, tmp_path)


# ---------------------------------------------------------------------------
# Factory effective-allowlist resolution
# ---------------------------------------------------------------------------


def _effective_allowlist_result(
    all_tools: tuple[str, ...],
    team_allowed: tuple[str, ...],
    spec_allowed: tuple[str, ...],
) -> tuple[str, ...]:
    """Replicate the factory's E4.5 filtering logic for unit testing."""
    effective = spec_allowed or team_allowed
    if effective:
        return tuple(t for t in all_tools if t in effective)
    return all_tools


class TestEffectiveAllowlist:
    def test_empty_everywhere_returns_all(self):
        all_tools = ("read_file", "search_knowledge", "github")
        result = _effective_allowlist_result(all_tools, (), ())
        assert result == all_tools

    def test_team_level_narrows_all_tools(self):
        all_tools = ("read_file", "search_knowledge", "github")
        result = _effective_allowlist_result(all_tools, ("read_file",), ())
        assert result == ("read_file",)

    def test_per_employee_overrides_team_level(self):
        all_tools = ("read_file", "search_knowledge", "github")
        # Team says only read_file; employee says github is fine
        result = _effective_allowlist_result(all_tools, ("read_file",), ("github",))
        assert result == ("github",)

    def test_per_employee_empty_inherits_team_level(self):
        all_tools = ("read_file", "search_knowledge", "github")
        result = _effective_allowlist_result(all_tools, ("read_file", "github"), ())
        assert result == ("read_file", "github")

    def test_allowlist_with_no_overlap_returns_empty(self):
        """Tool not in allowlist is completely filtered out."""
        all_tools = ("read_file", "github")
        result = _effective_allowlist_result(all_tools, ("brave-search",), ())
        assert result == ()

    def test_preserves_order_of_all_tools(self):
        all_tools = ("c", "a", "b")
        result = _effective_allowlist_result(all_tools, ("a", "b", "c"), ())
        assert result == ("c", "a", "b")  # order from all_tools preserved


# ---------------------------------------------------------------------------
# DepartmentConfig.allowed_tools is an immutable tuple
# ---------------------------------------------------------------------------


def test_allowed_tools_is_tuple(tmp_path: Path):
    config = _load_from_text(
        _make_minimal_yaml(team_allowed_tools=["x", "y"]), tmp_path
    )
    assert isinstance(config.allowed_tools, tuple)


def test_allowed_mcp_servers_is_tuple(tmp_path: Path):
    config = _load_from_text(
        _make_minimal_yaml(worker_allowed_mcp=["github"]), tmp_path
    )
    assert isinstance(config.employees[0].allowed_mcp_servers, tuple)


# ---------------------------------------------------------------------------
# Sprint P2.4 — split: `mcp.allowed_servers` (server-level) vs.
# `tools.allowed_tools` (tool-name level), plus `tools.denied_tools` blocklist
# ---------------------------------------------------------------------------


def _make_minimal_yaml_p24(
    *,
    team_allowed_tools: list[str] | None = None,
    team_denied_tools: list[str] | None = None,
    mcp_mode: str | None = None,
    mcp_allowed_servers: list[str] | None = None,
) -> str:
    """Build a minimal team YAML exercising the P2.4 schema split.

    The minimal-yaml builder above only knows about `tools.allowed_tools`
    and per-worker `allowed_mcp_servers`. P2.4 also introduces the
    structured `mcp:` block and the `tools.denied_tools` field — this
    builder lets the new tests construct YAMLs that exercise each surface.
    """
    tools_block = "    common: []\n    department: []\n    per_employee: {}\n"
    if team_allowed_tools is not None:
        tools_block += f"    allowed_tools: {team_allowed_tools!r}\n"
    if team_denied_tools is not None:
        tools_block += f"    denied_tools: {team_denied_tools!r}\n"

    mcp_block = ""
    if mcp_mode is not None or mcp_allowed_servers is not None:
        mode = mcp_mode if mcp_mode is not None else "permissive"
        servers = mcp_allowed_servers if mcp_allowed_servers is not None else []
        mcp_block = f"  mcp:\n    mode: {mode}\n    allowed_servers: {servers!r}\n"

    return f"""\
team:
  name: test-dept
  zone: 4
  chief:
    name: test-chief
  workers:
    - name: w1
      role: worker
  tools:
{tools_block}{mcp_block}mcp_servers: []
"""


class TestMCPServerAllowlist:
    """`team.mcp.allowed_servers` plus `team.mcp.mode` (P2.4)."""

    def test_default_mode_is_permissive(self, tmp_path: Path):
        """Backward compat: omitting `mcp:` defaults to permissive + empty."""
        config = _load_from_text(_make_minimal_yaml_p24(), tmp_path)
        assert config.mcp_mode == "permissive"
        assert config.mcp_allowed_servers == ()

    def test_mcp_block_loads(self, tmp_path: Path):
        config = _load_from_text(
            _make_minimal_yaml_p24(
                mcp_mode="deny_by_default",
                mcp_allowed_servers=["github", "notion"],
            ),
            tmp_path,
        )
        assert config.mcp_mode == "deny_by_default"
        assert config.mcp_allowed_servers == ("github", "notion")

    def test_mcp_allowed_servers_is_tuple(self, tmp_path: Path):
        config = _load_from_text(
            _make_minimal_yaml_p24(mcp_allowed_servers=["github"]),
            tmp_path,
        )
        assert isinstance(config.mcp_allowed_servers, tuple)

    def test_invalid_mcp_mode_rejected(self, tmp_path: Path):
        """Mode outside ALLOWED_MCP_MODES surfaces InvalidConfigError."""
        bad = _make_minimal_yaml_p24(mcp_mode="wide_open")
        with pytest.raises(InvalidConfigError):
            _load_from_text(bad, tmp_path)

    def test_mcp_extra_field_rejected(self, tmp_path: Path):
        """`extra=forbid` rejects unknown keys under `mcp:`."""
        bad = _make_minimal_yaml_p24(mcp_mode="permissive").replace(
            "    mode: permissive\n",
            "    mode: permissive\n    rogue_field: true\n",
        )
        with pytest.raises(InvalidConfigError):
            _load_from_text(bad, tmp_path)

    def test_empty_allowed_servers_under_deny_by_default(self, tmp_path: Path):
        """Empty list + deny_by_default is explicit: no MCP servers at all."""
        config = _load_from_text(
            _make_minimal_yaml_p24(
                mcp_mode="deny_by_default",
                mcp_allowed_servers=[],
            ),
            tmp_path,
        )
        assert config.mcp_mode == "deny_by_default"
        assert config.mcp_allowed_servers == ()


class TestDeniedToolsBlocklist:
    """`tools.denied_tools` removes after `allowed_tools` filtering (P2.4)."""

    def test_denied_tools_loads(self, tmp_path: Path):
        config = _load_from_text(
            _make_minimal_yaml_p24(team_denied_tools=["dangerous_tool"]),
            tmp_path,
        )
        assert config.denied_tools == ("dangerous_tool",)

    def test_denied_tools_default_empty(self, tmp_path: Path):
        """Backward compat: omitting `denied_tools` defaults to empty."""
        config = _load_from_text(_make_minimal_yaml_p24(), tmp_path)
        assert config.denied_tools == ()

    def test_denied_tools_is_tuple(self, tmp_path: Path):
        config = _load_from_text(
            _make_minimal_yaml_p24(team_denied_tools=["x"]),
            tmp_path,
        )
        assert isinstance(config.denied_tools, tuple)


# ---------------------------------------------------------------------------
# Sprint P2.4 — factory enforcement: tool-name allowlist + blocklist composition
# ---------------------------------------------------------------------------


def _factory_filter_with_blocklist(
    all_tools: tuple[str, ...],
    team_allowed: tuple[str, ...],
    spec_allowed: tuple[str, ...],
    denied: tuple[str, ...],
) -> tuple[str, ...]:
    """Replicate the P2.4 factory tool-filtering logic for unit testing.

    Mirrors `teams._factory.build_employee_agents` line 466-489: applies
    the effective tool-name allowlist first (per-employee wins over team),
    then removes any name in `denied_tools` so denied wins over allowed.
    """
    effective = spec_allowed or team_allowed
    if effective:
        all_tools = tuple(t for t in all_tools if t in effective)
    if denied:
        denied_set = frozenset(denied)
        all_tools = tuple(t for t in all_tools if t not in denied_set)
    return all_tools


class TestDeniedWinsOverAllowed:
    """A tool in `denied_tools` cannot be registered even if otherwise allowed."""

    def test_denied_removes_explicitly_allowed_tool(self):
        all_tools = ("read_file", "exec_shell", "search_knowledge")
        result = _factory_filter_with_blocklist(
            all_tools,
            team_allowed=("read_file", "exec_shell", "search_knowledge"),
            spec_allowed=(),
            denied=("exec_shell",),
        )
        assert result == ("read_file", "search_knowledge")

    def test_denied_with_empty_allowlist_still_removes(self):
        """No allowlist (permissive) but a denylist — denied still filtered."""
        all_tools = ("read_file", "exec_shell", "search_knowledge")
        result = _factory_filter_with_blocklist(
            all_tools,
            team_allowed=(),
            spec_allowed=(),
            denied=("exec_shell",),
        )
        assert result == ("read_file", "search_knowledge")

    def test_denied_overrides_per_employee_allowlist(self):
        """Per-employee allowlist that includes the denied tool — denied wins."""
        all_tools = ("read_file", "exec_shell")
        result = _factory_filter_with_blocklist(
            all_tools,
            team_allowed=(),
            spec_allowed=("read_file", "exec_shell"),
            denied=("exec_shell",),
        )
        assert result == ("read_file",)

    def test_empty_denied_is_noop(self):
        all_tools = ("read_file", "exec_shell")
        result = _factory_filter_with_blocklist(
            all_tools,
            team_allowed=(),
            spec_allowed=(),
            denied=(),
        )
        assert result == all_tools

    def test_denied_tool_not_in_all_tools_is_silent(self):
        """Denylist entries that aren't currently registered have no effect."""
        all_tools = ("read_file",)
        result = _factory_filter_with_blocklist(
            all_tools,
            team_allowed=(),
            spec_allowed=(),
            denied=("nonexistent_tool",),
        )
        assert result == all_tools


# ---------------------------------------------------------------------------
# Sprint P2.4 — production YAML migration smoke check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "yaml_path",
    EXISTING_TEAM_YAMLS,
    ids=[p.name for p in EXISTING_TEAM_YAMLS],
)
def test_production_yaml_carries_explicit_mcp_block(yaml_path: Path):
    """Every production team YAML declares an explicit `mcp:` block (P2.4).

    The schema accepts omission (defaults to permissive + empty), but the
    P2.4 migration explicitly declares the block on every production team
    so security review can see at a glance whether a team is in permissive
    or deny_by_default mode without consulting the schema default.
    """
    import yaml as _yaml

    raw = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    team = raw.get("team", {}) if raw else {}
    # _template.yaml is also a "team" YAML by glob; treat it the same — it
    # ships the structured block as the documented golden path.
    assert "mcp" in team, (
        f"{yaml_path.name}: missing `team.mcp:` block (P2.4 migration)"
    )
    assert "mode" in team["mcp"]
    assert "allowed_servers" in team["mcp"]
