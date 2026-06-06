"""Tests for ``build_employee_agents`` cache-aware behavior (Sprint A.03 #2292).

A.02 wired the chief (``build_manager_agent``) through ``AgentCache``. This
sprint extends the same pattern to the specialist layer: each specialist
Agent is cached under ``(team_name, specialist_name)`` so repeat
``build_employee_agents`` calls for the same config return the SAME Agent
instances.

The load-bearing risk in this refactor is the late-binding-closure trap.
Python loop variables are captured by reference, so a naive

    for spec in employees:
        def _build():
            return Agent(model=_resolve_model(spec), ...)

…produces closures that all see the LAST iteration's ``spec``. The fix
is two-layered:

1. The wrapper binds ``spec`` via default-arg: ``def _build(s=spec):``
   The default arg evaluates at function-definition time, snapshotting
   the current spec.
2. The body of the closure is a one-line trampoline to
   ``_build_employee_agent_uncached(s, ...)`` — a module-level function
   whose ``spec`` is a plain parameter, where closure capture is
   structurally impossible.

Test #4 (``test_late_binding_closure_each_specialist_has_correct_model``)
is the regression guard.
"""

from __future__ import annotations

from teams._agent_cache import AgentCache
from teams._factory import build_employee_agents, build_manager_agent
from teams._types import AgentSpec, DepartmentConfig


def _make_config(
    name: str,
    *,
    chief_name: str | None = None,
    employees: tuple[AgentSpec, ...] | None = None,
    per_employee_tools: dict[str, tuple[str, ...]] | None = None,
) -> DepartmentConfig:
    """Build a minimal DepartmentConfig for cache tests.

    Defaults to two specialists. Override ``employees`` to test
    distinct-model wiring (the late-binding regression test) or
    ``per_employee_tools`` to test per-specialist tool isolation.
    """
    if employees is None:
        employees = (
            AgentSpec(
                name=f"{name}-worker-a",
                model="anthropic:claude-sonnet-4-6",
                role="First specialist",
            ),
            AgentSpec(
                name=f"{name}-worker-b",
                model="anthropic:claude-sonnet-4-6",
                role="Second specialist",
            ),
        )
    return DepartmentConfig(
        name=name,
        zone=4,
        description=f"{name} department for cache tests",
        manager=AgentSpec(
            name=chief_name or f"{name}-chief",
            model="anthropic:claude-opus-4-6",
            role=f"Orchestrates {name} work",
        ),
        employees=employees,
        per_employee_tools=per_employee_tools or {},
    )


def test_two_calls_same_team_return_same_specialist_dict_by_value():
    """Each specialist's Agent instance is the same across two calls.

    The dict identity differs (we return a fresh dict) but each value
    (the specialist Agent) is the cached instance.
    """
    cache = AgentCache()
    config = _make_config("board")

    d1 = build_employee_agents(config, agent_cache=cache)
    d2 = build_employee_agents(config, agent_cache=cache)

    assert set(d1.keys()) == set(d2.keys())
    for name in d1:
        assert d1[name] is d2[name], (
            f"Specialist {name!r} not the same Agent instance across two "
            f"build_employee_agents calls — cache miss?"
        )


def test_distinct_specialists_within_team_are_distinct_agents():
    """The cache key includes specialist name; distinct specialists in the
    same team get distinct Agent instances.
    """
    cache = AgentCache()
    config = _make_config("board")

    d = build_employee_agents(config, agent_cache=cache)

    agents = list(d.values())
    assert len(agents) >= 2
    # All Agent instances are distinct objects (different memory ids).
    assert len({id(a) for a in agents}) == len(agents)


def test_specialists_across_teams_with_disjoint_names_are_independent():
    """Different teams' specialist sets populate the cache independently.

    Synthetic test — board/design specialists have disjoint name prefixes
    so no real collision exists. The intent is to confirm cache keys are
    team-namespaced.
    """
    cache = AgentCache()

    board_dict = build_employee_agents(_make_config("board"), agent_cache=cache)
    design_dict = build_employee_agents(_make_config("design"), agent_cache=cache)

    assert set(board_dict.keys()).isdisjoint(set(design_dict.keys()))
    # Both populated the cache: 2 specialists per team × 2 teams = 4 entries.
    assert cache.stats().size == 4


def test_late_binding_closure_each_specialist_has_correct_model():
    """REGRESSION: the closure-late-binding bug would assign every
    specialist the LAST spec's model. This test pins each specialist's
    underlying Agent ``model`` to the string declared on ITS spec.

    Three distinct model strings across three specialists. If the
    late-binding bug were present, all three Agents would carry the
    third (``glm-5.1``) model.
    """
    cache = AgentCache()
    employees = (
        AgentSpec(
            name="security-auditor",
            model="anthropic:claude-opus-4-6",
            role="Security review",
        ),
        AgentSpec(
            name="qa-engineer",
            model="anthropic:claude-sonnet-4-6",
            role="Test design and execution",
        ),
        AgentSpec(
            name="accessibility-tester",
            model="anthropic:claude-haiku-4-6",
            role="WCAG compliance",
        ),
    )
    config = _make_config("qa", employees=employees)

    d = build_employee_agents(config, agent_cache=cache)

    # Each specialist's Agent.model must reflect its OWN spec's model
    # string, not the loop's last iteration value.
    assert "opus" in str(d["security-auditor"].model).lower()
    assert "sonnet" in str(d["qa-engineer"].model).lower()
    assert "haiku" in str(d["accessibility-tester"].model).lower()


def test_invalidate_team_evicts_all_specialists_plus_chief():
    """A team-level ``invalidate`` clears BOTH the chief (cached by A.02)
    and every specialist (cached by A.03).
    """
    cache = AgentCache()
    config = _make_config("ops")

    workers = build_employee_agents(config, agent_cache=cache)
    chief = build_manager_agent(config, workers, agent_cache=cache)

    # 2 specialists + 1 chief = 3 cached entries for team "ops".
    n_before = cache.stats().size
    assert n_before == 3

    evicted = cache.invalidate("ops")
    assert evicted == n_before
    assert cache.stats().size == 0


def test_cross_vendor_filter_runs_before_cache_lookup():
    """Filtered-out specialists are NOT constructed and NOT cached.

    Only the ``board`` department triggers the filter; with
    ``cross_vendor_enabled=False`` every ``adapter="openrouter"`` worker is
    omitted from the returned dict AND the cache.
    """
    cache = AgentCache()
    employees = (
        AgentSpec(
            name="board-claude-member",
            model="anthropic:claude-opus-4-6",
            role="Claude-routed",
            adapter="claude",
        ),
        AgentSpec(
            name="board-openrouter-member",
            model="openrouter:anthropic/claude-opus-4-6",
            role="OpenRouter-routed",
            adapter="openrouter",
        ),
    )
    config = _make_config("board", employees=employees)

    d = build_employee_agents(
        config, cross_vendor_enabled=False, agent_cache=cache
    )

    # Only the claude-adapter worker is in the dict.
    assert set(d.keys()) == {"board-claude-member"}
    # And only that worker is in the cache — the filtered-out spec never
    # reached ``get_or_build``.
    assert cache.stats().size == 1


def test_per_employee_tools_still_apply_to_cached_agent():
    """REGRESSION: per-employee tool registration must still attach the
    right tools to the right specialist after the cache rewire.

    Two specialists; one of them has a per-employee tool entry. Each
    cached Agent's tool set must reflect ITS spec's per-employee entry,
    not the other's.
    """
    cache = AgentCache()
    employees = (
        AgentSpec(
            name="design-accessibility-specialist",
            model="anthropic:claude-sonnet-4-6",
            role="WCAG specialist",
        ),
        AgentSpec(
            name="design-visual-designer",
            model="anthropic:claude-sonnet-4-6",
            role="Visual design specialist",
        ),
    )
    # ``check_wcag_contrast`` is registered in teams/_tool_registry.py.
    per_employee_tools = {
        "design-accessibility-specialist": ("check_wcag_contrast",),
    }
    config = _make_config(
        "design", employees=employees, per_employee_tools=per_employee_tools
    )

    d = build_employee_agents(config, agent_cache=cache)

    a11y_tools = set(d["design-accessibility-specialist"]._function_toolset.tools.keys())
    visual_tools = set(d["design-visual-designer"]._function_toolset.tools.keys())

    # The per-employee tool is attached to the right specialist.
    assert "check_wcag_contrast" in a11y_tools
    # And NOT to the other one.
    assert "check_wcag_contrast" not in visual_tools
