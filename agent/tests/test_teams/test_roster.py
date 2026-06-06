"""Tests for the Sprint 19 (Phase 5A) chief rostering layer.

Covers:
- ``roster_from_department_config()`` preserves YAML order and copies fields
- ``Roster.get()`` / ``Roster.names()`` accessors
- ``_format_roster_block()`` deterministic markdown rendering
- ``_inject_roster_into_prompt()`` placeholder vs append-with-warning paths
- ``list_specialists()`` tool returns specs in YAML order
- ``delegate()`` tool rejects unknown specialist names with ValueError
- ``delegate()`` tool populates the EmployeeResult collector
- Sprint P3.6 — every production chief prompt under
  ``agent/config/agents/zone4/`` contains the literal ``{{ROSTER}}``
  placeholder (for chiefs of delegate-mode teams).
"""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from pydantic_ai import ModelRetry

from teams._factory import (
    ROSTER_PLACEHOLDER,
    _format_roster_block,
    _inject_roster_into_prompt,
    build_employee_agents,
    build_manager_agent,
    roster_from_department_config,
)
from teams._types import (
    AgentSpec,
    Constraints,
    DepartmentConfig,
    EmployeeResult,
    Roster,
    SpecialistSpec,
)
from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_deps,
    make_specialist_text_model,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _three_specialist_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="dept-x",
        zone=4,
        description="",
        manager=AgentSpec(
            name="x-chief",
            model="anthropic:claude-opus-4-6",
            role="Orchestrates dept-x",
        ),
        employees=(
            AgentSpec(
                name="alpha",
                model="anthropic:claude-sonnet-4-6",
                role="Alpha role",
                expertise_summary="Alpha expertise",
                when_to_call="Call alpha for alpha work",
                deny_write_paths=("agent/alpha/",),
            ),
            AgentSpec(
                name="beta",
                model="anthropic:claude-sonnet-4-6",
                role="Beta role",
                # when_to_call left empty — must fall back to role
            ),
            AgentSpec(
                name="gamma",
                model="anthropic:claude-sonnet-4-6",
                role="",  # role also empty — must fall back to name
            ),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


# ---------------------------------------------------------------------------
# roster_from_department_config()
# ---------------------------------------------------------------------------


class TestRosterFromConfig:
    def test_preserves_yaml_order(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        assert roster.names() == ("alpha", "beta", "gamma")

    def test_chief_name_and_department(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        assert roster.department == "dept-x"
        assert roster.chief_name == "x-chief"

    def test_when_to_call_populated_from_field(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        alpha = roster.get("alpha")
        assert alpha is not None
        assert alpha.when_to_call == "Call alpha for alpha work"

    def test_when_to_call_falls_back_to_role(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        beta = roster.get("beta")
        assert beta is not None
        assert beta.when_to_call == "Beta role"

    def test_when_to_call_falls_back_to_name(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        gamma = roster.get("gamma")
        assert gamma is not None
        assert gamma.when_to_call == "gamma"

    def test_expertise_summary_falls_back_to_role(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        beta = roster.get("beta")
        assert beta is not None
        assert beta.expertise_summary == "Beta role"

    def test_domain_write_paths_copied(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        alpha = roster.get("alpha")
        assert alpha is not None
        assert alpha.domain_write_paths == ("agent/alpha/",)

    def test_get_returns_none_for_unknown(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        assert roster.get("nope") is None

    def test_roster_is_frozen(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        with pytest.raises(Exception):
            roster.department = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _format_roster_block + _inject_roster_into_prompt
# ---------------------------------------------------------------------------


class TestFormatRosterBlock:
    def test_block_lists_every_specialist(self) -> None:
        config = _three_specialist_config()
        block = _format_roster_block(roster_from_department_config(config))
        assert "**alpha**" in block
        assert "**beta**" in block
        assert "**gamma**" in block

    def test_block_includes_when_to_call(self) -> None:
        config = _three_specialist_config()
        block = _format_roster_block(roster_from_department_config(config))
        assert "Call alpha for alpha work" in block

    def test_block_pluralisation(self) -> None:
        config = _three_specialist_config()
        block = _format_roster_block(roster_from_department_config(config))
        assert "3 specialists" in block

    def test_empty_roster_renders_placeholder(self) -> None:
        roster = Roster(
            department="empty",
            chief_name="empty-chief",
            specialists=(),
        )
        block = _format_roster_block(roster)
        assert "no specialists configured" in block

    def test_strict_floor_requires_delegation_in_doctrine(self) -> None:
        config = _three_specialist_config()
        block = _format_roster_block(
            roster_from_department_config(config),
            expected_min_specialists=2,
        )
        assert "MUST delegate to at least 2 specialists" in block
        assert "Do not answer directly" in block
        assert "If no specialist fits, answer directly" not in block


class TestInjectRosterIntoPrompt:
    def test_substitutes_placeholder(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        prompt = f"You are the chief.\n\n{ROSTER_PLACEHOLDER}\n\nGo."
        out = _inject_roster_into_prompt(prompt, roster)
        assert ROSTER_PLACEHOLDER not in out
        assert "**alpha**" in out
        assert out.startswith("You are the chief.")
        assert out.endswith("Go.")

    def test_appends_when_placeholder_missing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        prompt = "You are the chief. Go."
        with caplog.at_level(logging.WARNING, logger="teams._factory"):
            out = _inject_roster_into_prompt(prompt, roster)
        assert "roster.placeholder_missing" in caplog.text
        assert "You are the chief. Go." in out
        assert "**alpha**" in out  # roster appended

    def test_empty_prompt_still_gets_block_with_no_separator(self) -> None:
        config = _three_specialist_config()
        roster = roster_from_department_config(config)
        out = _inject_roster_into_prompt("", roster)
        assert "**alpha**" in out
        # Empty leading prompt → no leading "---" separator
        assert not out.lstrip().startswith("---")


# ---------------------------------------------------------------------------
# list_specialists() tool
# ---------------------------------------------------------------------------


class TestListSpecialistsTool:
    def test_tool_is_registered(self) -> None:
        config = _three_specialist_config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        assert "list_specialists" in manager._function_toolset.tools

    def test_delegate_tool_is_registered(self) -> None:
        config = _three_specialist_config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        assert "delegate" in manager._function_toolset.tools

    def test_per_specialist_tools_are_removed(self) -> None:
        """The old delegate_to_<name> tools must no longer be registered."""
        config = _three_specialist_config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        names = list(manager._function_toolset.tools.keys())
        assert not any(n.startswith("delegate_to_") for n in names)

    def test_manager_prompt_includes_strict_floor_doctrine(self) -> None:
        config = replace(
            _three_specialist_config(),
            constraints=Constraints(
                cost_limit_usd=1.0,
                timeout_seconds=60,
                expected_min_specialists=2,
            ),
        )
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)

        prompt = manager._system_prompts[0]
        assert "MUST delegate to at least 2 specialists" in prompt
        assert "If no specialist fits, answer directly" not in prompt


# ---------------------------------------------------------------------------
# delegate() validation + collector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_populates_collector_with_correct_specialist_name() -> None:
    """delegate(specialist=alpha, ...) must record EmployeeResult.employee_name='alpha'."""
    config = _three_specialist_config()
    collector: list[EmployeeResult] = []
    deps = make_deps(department="dept-x")

    employees = build_employee_agents(config)
    manager = build_manager_agent(
        config, employees, employee_results_collector=collector
    )

    emp_model = make_specialist_text_model("alpha did the work")
    mgr_model = make_chief_delegating_model(
        [("alpha", "do alpha work")], final_answer="ok"
    )

    with employees["alpha"].override(model=emp_model):
        with manager.override(model=mgr_model):
            await manager.run("task", deps=deps)

    assert len(collector) == 1
    assert collector[0].employee_name == "alpha"
    assert collector[0].success is True


@pytest.mark.asyncio
async def test_delegate_records_failure_when_specialist_raises() -> None:
    """If the specialist agent raises, delegate() must record success=False."""
    config = _three_specialist_config()
    collector: list[EmployeeResult] = []
    deps = make_deps(department="dept-x")

    employees = build_employee_agents(config)
    manager = build_manager_agent(
        config, employees, employee_results_collector=collector
    )

    # Build a specialist model that raises inside its function
    from pydantic_ai.models.function import AgentInfo, FunctionModel
    from pydantic_ai.messages import ModelMessage, ModelResponse

    async def _boom(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise RuntimeError("specialist exploded")

    emp_model = FunctionModel(_boom, model_name="boom")
    mgr_model = make_chief_delegating_model(
        [("alpha", "do something")], final_answer="recovered"
    )

    with employees["alpha"].override(model=emp_model):
        with manager.override(model=mgr_model):
            await manager.run("task", deps=deps)

    assert len(collector) == 1
    assert collector[0].employee_name == "alpha"
    assert collector[0].success is False
    assert collector[0].error is not None
    assert "specialist exploded" in collector[0].error


# ---------------------------------------------------------------------------
# SpecialistSpec frozen-ness
# ---------------------------------------------------------------------------


def test_specialist_spec_is_frozen() -> None:
    spec = SpecialistSpec(
        name="x",
        role="r",
        expertise_summary="e",
        when_to_call="w",
        domain_write_paths=(),
    )
    with pytest.raises(Exception):
        spec.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# delegate() rejects unknown specialist (acceptance-criterion test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_raises_value_error_on_unknown_specialist() -> None:
    """The delegate() tool MUST raise ValueError for an unknown specialist.

    This is the spec's load-bearing safety property: pydantic-ai surfaces
    ValueError back to the chief's LLM as a tool-validation error so the
    LLM retries with a valid name. The test invokes the registered tool
    callable directly to assert the raise reaches us.
    """
    config = _three_specialist_config()
    employees = build_employee_agents(config)
    manager = build_manager_agent(config, employees)

    delegate_tool = manager._function_toolset.tools["delegate"]
    # pydantic-ai stores the underlying callable on .function
    fn = delegate_tool.function

    # Build a minimal RunContext-shaped object — the unified delegate()
    # implementation only reads ctx.deps and ctx.usage, both of which are
    # touched after the roster check; the ValueError fires before either.
    class _FakeCtx:
        deps = make_deps(department="dept-x")
        usage = None

    with pytest.raises(ValueError) as excinfo:
        await fn(_FakeCtx(), specialist="not-a-real-specialist", task="x")

    assert "not-a-real-specialist" in str(excinfo.value)
    # Available list must be surfaced so the LLM can retry with a valid name
    assert "alpha" in str(excinfo.value)


@pytest.mark.asyncio
async def test_delegate_raises_model_retry_for_schema_placeholder_specialist() -> None:
    """Schema placeholders like 'string' should get a targeted retry prompt."""
    config = _three_specialist_config()
    employees = build_employee_agents(config)
    manager = build_manager_agent(config, employees)

    delegate_tool = manager._function_toolset.tools["delegate"]
    fn = delegate_tool.function

    class _FakeCtx:
        deps = make_deps(department="dept-x")
        usage = None

    with pytest.raises(ModelRetry) as excinfo:
        await fn(_FakeCtx(), specialist="string", task="x")

    message = str(excinfo.value)
    assert "schema placeholder" in message
    assert "alpha" in message
    assert "beta" in message


# ---------------------------------------------------------------------------
# Sprint P3.6 — production-chief prompt invariant
# ---------------------------------------------------------------------------
#
# Spec: every production chief prompt under agent/config/agents/zone4/
# must contain the literal {{ROSTER}} placeholder so the runtime injection
# in `_inject_roster_into_prompt` substitutes the roster block at the
# right spot (rather than falling back to the degraded "append at end
# with a warning" path).
#
# A "production chief" is the chief of a delegate-mode team — a team
# YAML with workers > 0. Single-director teams (workers: [], e.g.
# outreach.yaml) are exempt because the chief has no specialists to
# delegate to and the roster block would render as "no specialists
# configured".


REPO_ROOT = Path(__file__).resolve().parents[3]
TEAMS_DIR = REPO_ROOT / "agent" / "config" / "teams"


def _resolve_prompt_path(rel: str) -> Path:
    """Resolve a YAML system_prompt path to the canonical on-disk file.

    Mirrors `scripts.validate_team_yaml._resolve_chief_prompt_path` —
    YAMLs that declare `config/...` are read by the runtime against
    its `agent/` CWD, so the canonical file lives under
    `<repo>/agent/<rel>`. Prefer that location over the repo-root
    shadow.
    """
    if rel.startswith("agent/"):
        return REPO_ROOT / rel
    canonical = REPO_ROOT / "agent" / rel
    if canonical.exists():
        return canonical
    return REPO_ROOT / rel


def _delegate_mode_chief_prompts() -> list[tuple[str, Path]]:
    """Collect (team_name, chief-prompt path) pairs for every delegate-mode
    production team in `agent/config/teams/`.

    Skips:
    - `_template.yaml` (not a real team; not discovered by the registry)
    - Single-director teams (workers: []) — no roster injection happens
    """
    out: list[tuple[str, Path]] = []
    for yaml_path in sorted(TEAMS_DIR.glob("*.yaml")):
        if yaml_path.name.startswith("_"):
            continue
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        team = (raw or {}).get("team", {}) or {}
        workers = team.get("workers", []) or []
        if not workers:
            continue
        chief = team.get("chief", {}) or {}
        sp = chief.get("system_prompt", "") or ""
        if not sp:
            continue
        out.append((team.get("name", yaml_path.stem), _resolve_prompt_path(sp)))
    return out


@pytest.mark.parametrize(
    "team_name,prompt_path",
    _delegate_mode_chief_prompts(),
    ids=[p[0] for p in _delegate_mode_chief_prompts()],
)
def test_production_chief_prompt_contains_roster_placeholder(
    team_name: str, prompt_path: Path
) -> None:
    """Every production chief prompt under `agent/config/agents/zone4/`
    must contain the literal ``{{ROSTER}}`` placeholder.

    The runtime falls back to appending the roster at end-of-prompt with
    a logged warning if the placeholder is missing — observable as a
    one-line WARN in the bridge log on every chief run. Production teams
    must use the placeholder so the roster lands in the author's intended
    spot, not appended after unrelated trailing content.
    """
    assert prompt_path.exists(), (
        f"chief prompt for team {team_name!r} not found at {prompt_path}"
    )
    body = prompt_path.read_text(encoding="utf-8")
    assert ROSTER_PLACEHOLDER in body, (
        f"chief prompt for team {team_name!r} at {prompt_path} is missing "
        f"the literal {ROSTER_PLACEHOLDER!r} placeholder. Add it where the "
        f"team-roster injection should land (typically replacing a hand-"
        f"maintained '## Your Team' section)."
    )
