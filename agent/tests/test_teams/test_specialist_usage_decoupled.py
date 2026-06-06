"""Regression test for fix/z4-decouple-specialist-runusage (2026-05-19).

Background
----------
``agent/teams/_factory.py`` previously invoked the specialist's Agent via::

    result = await agent.run(full_task, deps=child_deps, usage=ctx.usage)

Passing ``usage=ctx.usage`` makes the specialist share the chief's
``RunUsage`` object. Every specialist invocation's input tokens then
accumulate against the chief's ``input_tokens_limit`` budget (resolved from
``Constraints.request_token_limit`` via ``_team._resolve_usage_limits``).
With ``expected_min_specialists: 6+`` plus multi-round deliberation the
cumulative input quickly exceeds 100K and trips ``UsageLimitExceeded`` on
the chief's NEXT request — even when the chief's own context is well
within bounds.

The fix drops ``usage=ctx.usage`` so each specialist runs on its own
fresh ``RunUsage``. The chief's input-token cap then governs only chief
context, as intended.

See ``docs/architecture/2026-05-19-z4-board-token-budget-diagnostic-correction.md``
for the full diagnostic.

What this test guards
---------------------
This test pins the contract: the delegate-tool's specialist invocation must
NOT thread ``usage=ctx.usage`` through to the specialist's ``agent.run``.
It does so by wrapping the specialist Agent's ``run`` method with a spy that
captures the kwargs the delegate tool passes in.
"""
from __future__ import annotations

import pytest

from teams._factory import build_employee_agents, build_manager_agent
from teams._types import AgentSpec, Constraints, DepartmentConfig, EmployeeResult
from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_deps,
    make_specialist_text_model,
)


def _two_specialist_config() -> DepartmentConfig:
    """Minimal department config with two specialists for delegation tests."""
    return DepartmentConfig(
        name="test-dept-usage",
        zone=4,
        description="",
        manager=AgentSpec(
            name="chief", model="anthropic:claude-opus-4-6", role="chief"
        ),
        employees=(
            AgentSpec(
                name="specialist-a",
                model="anthropic:claude-sonnet-4-6",
                role="a",
            ),
            AgentSpec(
                name="specialist-b",
                model="anthropic:claude-sonnet-4-6",
                role="b",
            ),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


@pytest.mark.asyncio
async def test_specialist_run_does_not_receive_chief_usage_kwarg() -> None:
    """The delegate tool must call specialist.run() WITHOUT ``usage=ctx.usage``.

    Before the fix the delegate-tool body threaded the chief's
    ``ctx.usage`` (a ``RunUsage``) into every specialist invocation, causing
    cumulative-budget failures. After the fix, the kwarg is omitted so each
    specialist gets a fresh per-call ``RunUsage`` from pydantic-ai.
    """
    config = _two_specialist_config()
    collector: list[EmployeeResult] = []
    deps = make_deps(department="test-dept-usage")

    employees = build_employee_agents(config)
    manager = build_manager_agent(
        config, employees, employee_results_collector=collector
    )

    # Spy on each specialist Agent's ``run`` method. Wrap rather than
    # replace so the real pydantic-ai code path still executes — we just
    # snapshot the kwargs the delegate-tool body passes in.
    captured_kwargs: list[dict[str, object]] = []

    def _wrap(agent_obj):
        original_run = agent_obj.run

        async def _spy(*args, **kwargs):
            # Strip the user-prompt positional arg from the snapshot; only
            # the kwargs matter for this contract check.
            captured_kwargs.append(dict(kwargs))
            return await original_run(*args, **kwargs)

        agent_obj.run = _spy  # type: ignore[method-assign]
        return agent_obj

    for name in ("specialist-a", "specialist-b"):
        _wrap(employees[name])

    emp_model = make_specialist_text_model("specialist output")
    mgr_model = make_chief_delegating_model(
        [
            ("specialist-a", "do part A"),
            ("specialist-b", "do part B"),
        ],
        final_answer="synthesised",
    )

    with employees["specialist-a"].override(model=emp_model):
        with employees["specialist-b"].override(model=emp_model):
            with manager.override(model=mgr_model):
                await manager.run("multi-specialist task", deps=deps)

    # Both specialists must have been invoked exactly once.
    assert len(captured_kwargs) == 2, (
        f"expected 2 specialist invocations, got {len(captured_kwargs)}: "
        f"{captured_kwargs}"
    )

    # CONTRACT: neither specialist invocation may carry a ``usage`` kwarg.
    # If a future refactor re-introduces ``usage=ctx.usage`` (or any other
    # shared RunUsage), this assertion fires.
    for i, kw in enumerate(captured_kwargs):
        assert "usage" not in kw, (
            f"specialist invocation {i} received usage kwarg "
            f"(keys={list(kw)}); this re-couples specialist tokens to the "
            f"chief's RunUsage budget — see "
            f"docs/architecture/2026-05-19-z4-board-token-budget-diagnostic-correction.md"
        )

    # And the specialists DID run — collector populated proves the
    # delegation path actually executed (rather than short-circuiting).
    assert len(collector) == 2, (
        f"expected 2 EmployeeResult entries, got {len(collector)}"
    )
    assert {er.employee_name for er in collector} == {"specialist-a", "specialist-b"}
    assert all(er.success is True for er in collector)


@pytest.mark.asyncio
async def test_chief_usage_excludes_specialist_input_tokens() -> None:
    """The chief's reported usage must not include specialist input tokens.

    Complement to the kwarg-shape contract test above: this exercises the
    end-to-end accounting. We make the specialist's stub response include
    a deliberately large input-token charge; if specialist usage were still
    sharing the chief's RunUsage, the chief's ``result.usage().input_tokens``
    would reflect it.
    """
    config = _two_specialist_config()
    collector: list[EmployeeResult] = []
    deps = make_deps(department="test-dept-usage")

    employees = build_employee_agents(config)
    manager = build_manager_agent(
        config, employees, employee_results_collector=collector
    )

    emp_model = make_specialist_text_model("specialist output")
    mgr_model = make_chief_delegating_model(
        [("specialist-a", "do the task")],
        final_answer="synthesised",
    )

    with employees["specialist-a"].override(model=emp_model):
        with manager.override(model=mgr_model):
            result = await manager.run("delegation task", deps=deps)

    # Chief's RunUsage must reflect only the chief's own model requests.
    # With ``FunctionModel`` + ``_estimate_usage`` the chief sees two
    # rounds (initial + post-tool synthesis); the specialist's tokens are
    # tracked in a *separate* RunUsage and surfaced only via
    # ``EmployeeResult.tokens_used``. We don't pin an exact number — that
    # would couple the test to pydantic-ai's internal estimator — but we
    # assert the collector + chief usage are independent accounts.
    chief_usage = result.usage()
    assert chief_usage is not None, "chief result must report a RunUsage"

    # The specialist contributed at least one tool-call exchange which
    # produces a non-zero token count; if it had leaked into the chief's
    # usage, ``chief_usage.requests`` would be inflated by the specialist's
    # request count. The exact assertion: chief.requests equals the number
    # of chief-model rounds we drove via ``make_chief_delegating_model``
    # (2: initial delegate call + final synthesis), with no third request
    # bleed from the specialist.
    assert chief_usage.requests == 2, (
        f"chief should have made exactly 2 model requests; got "
        f"{chief_usage.requests}. A higher number indicates specialist "
        f"requests are leaking into the chief's RunUsage."
    )

    # Specialist ran and reported tokens via the collector — the parallel
    # bookkeeping path is intact.
    assert len(collector) == 1
    assert collector[0].employee_name == "specialist-a"
    assert collector[0].tokens_used > 0, (
        "specialist tokens_used must still be reported (via result.usage() "
        "in the delegate tool), even though they no longer accumulate "
        "against the chief's RunUsage."
    )
