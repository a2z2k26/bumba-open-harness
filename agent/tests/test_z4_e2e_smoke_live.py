"""LIVE E2E smoke test for the Z4 chief-session pipeline (Z4-S52 #1402).

The live counterpart to ``tests/test_z4_e2e_smoke.py`` (Z4-S51 #1400).
Same shape, same fixtures, same assertions — except:

- NO ``TestModel`` override. The chief runs against a real model per the
  production strategy team YAML (currently OpenRouter ``gpt-5.5`` chief +
  ``gpt-4o-mini`` specialists).
- ``@pytest.mark.live`` decorator. Default ``pytest`` invocation skips it;
  only ``pytest -m live`` (or ``make live-smoke``) runs it.
- A real ``CostTracker`` is wired into ``BridgeDeps`` so the per-run cost
  is observable; the test asserts ``session.cost_usd > 0`` (real cost was
  charged) and ``< cap`` (within budget).

Skip mechanics:

- Skipped when ``ANTHROPIC_API_KEY`` is not set, mirroring the existing
  ``tests/test_teams/test_live_smoke.py`` pattern. (Even when the chief
  routes through OpenRouter, the existing live-smoke harness uses the
  same env-var gate so the operator has one switch to flip.)
- ``LIVE_COST_CAP`` env override is honored (default $0.75) so the
  operator can raise the cap without editing the test.

Cost target:

- Per-run target ≤ $0.50, hard cap $0.75 (slightly above to absorb
  worst-case spend before the assertion fires). The intent is a single
  one-sentence summary so the chief produces minimal output.

When to run:

- Before the production flag flip (Z4-S63 #1407).
- After any change to the strategy department YAML, chief expertise, or
  the WarmChief / ChiefDispatcher seam.
- On demand via ``make live-smoke`` after exporting ``ANTHROPIC_API_KEY``.

Authority note (Z4-S52 spec): per the spec the test exercises the full
chief-session pipeline against the real Anthropic API with a tight intent
and a firm cost cap. The pre-existing ``test_live_smoke.py`` is the
precedent for the env-var gate, the cost-cap assertion, and the verifier
check; this file is the dispatcher-level peer.
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from bridge.chief_dispatcher import ChiefDispatcher
from bridge.chief_session import ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore
from bridge.event_bus import EventBus
from bridge.work_order import WorkOrder
from bridge.work_order_router import NullRouter

# Source repo agent root; used to load the production strategy.yaml.
_AGENT_ROOT = Path(__file__).resolve().parent.parent
_STRATEGY_YAML = _AGENT_ROOT / "config" / "teams" / "strategy.yaml"

# Default per-run cost cap. Overridable via ``LIVE_COST_CAP`` env var to
# stay consistent with the existing live-smoke harness.
_DEFAULT_COST_CAP_USD = 0.75


def _live_cost_cap_usd() -> float:
    """Per-run cost cap. Honors ``LIVE_COST_CAP`` env override."""
    return float(os.environ.get("LIVE_COST_CAP", str(_DEFAULT_COST_CAP_USD)))


@pytest.mark.live
@pytest.mark.asyncio
async def test_e2e_dispatcher_to_chief_live(tmp_path: Path) -> None:
    """Drive the full Z4 pipeline against the real API; assert AWAITING_EVALUATION + bounded cost.

    Steps:
        1. Skip if ``ANTHROPIC_API_KEY`` is not set (matches existing
           live-smoke pattern; the operator flips one env var to enable
           the entire live test surface).
        2. Load the production ``strategy`` department YAML via
           ``DepartmentRegistry.from_directory`` so the test exercises
           the same registry path production uses.
        3. Override the department's ``constraints.cost_limit_usd`` with
           a tight cap (default $0.75) so even a worst-case run stays
           bounded. The original config object is never mutated —
           ``dataclasses.replace`` returns a new copy per the
           immutable-update convention.
        4. Build a ``ChiefDispatcher`` against an in-memory session store
           + a ``NullRouter("strategy")`` + a real ``EventBus``.
        5. Build a ``WorkOrder`` with a tight intent (one-sentence
           summary) so the chief produces minimal output.
        6. Build ``BridgeDeps`` with a real ``CostTracker`` rooted at
           ``tmp_path`` so the test sees real cost ledger entries.
        7. Call ``await dispatcher.dispatch(work_order, deps)`` — this
           runs the real chief against the real model.
        8. Assert ``session.state == AWAITING_EVALUATION``,
           ``cost_usd > 0`` (real cost charged), ``cost_usd < cap``
           (within budget), and the WarmChief's captured TeamResult
           passes ``verify_team_result`` (empty violations).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — skipping live E2E test")

    # Local imports keep the offline test surface unaffected when
    # collection sweeps this file but the live key is absent.
    from bridge.cost_tracker import CostTracker
    from teams._registry import DepartmentRegistry
    from teams._verify import verify_team_result
    from tests.test_teams.conftest import make_deps

    cost_cap = _live_cost_cap_usd()

    # ----- Step 2: load the production strategy team via the registry --
    teams_dir = _STRATEGY_YAML.parent
    assert _STRATEGY_YAML.exists(), (
        f"Production strategy.yaml not found at {_STRATEGY_YAML}; "
        f"the live test relies on the real department YAML and cannot "
        f"run without it."
    )
    registry = DepartmentRegistry.from_directory(teams_dir)
    assert "strategy" in registry.department_names(), (
        f"DepartmentRegistry did not discover 'strategy' from {teams_dir}; "
        f"discovered: {registry.department_names()}"
    )

    # ----- Step 3: tighten the cost cap on a copy of the config -------
    # The strategy YAML ships with cost_limit_usd=1.50 — fine for
    # production but too loose for a live test. Build an immutable copy
    # of the config with constraints.cost_limit_usd lowered to our cap.
    original_config = registry.get_config("strategy")
    tight_constraints = dataclasses.replace(
        original_config.constraints,
        cost_limit_usd=cost_cap,
    )
    tight_config = dataclasses.replace(
        original_config,
        constraints=tight_constraints,
    )

    # Splice the tightened config back into the registry. The registry
    # exposes ``get_config`` — we patch the underlying mapping so the
    # dispatcher reads our tightened copy without touching the global
    # config files.
    registry._configs["strategy"] = tight_config  # type: ignore[attr-defined]

    # ----- Step 4: build the dispatcher with live-friendly components --
    store = InMemoryChiefSessionStore()
    router = NullRouter(department="strategy")
    event_bus = EventBus(data_dir=tmp_path / "data")

    dispatcher = ChiefDispatcher(
        router=router,
        session_store=store,
        dept_registry=registry,
        event_bus=event_bus,
    )

    # ----- Step 5: build a tight WorkOrder ------------------------------
    wo = WorkOrder.create(
        intent=(
            "Summarize the Z4 chief-session architecture in one sentence."
        ),
        skill="strategy",
        project="z4-e2e-smoke-live",
    )

    # ----- Step 6: BridgeDeps with a real CostTracker ------------------
    cost_tracker = CostTracker(data_dir=tmp_path / "cost")
    deps = make_deps(
        session_id="z4-e2e-smoke-live",
        department="strategy",
        cost_tracker=cost_tracker,
        cost_limit_usd=cost_cap,
    )

    # ----- Step 7: dispatch (this hits the real API) -------------------
    session = await dispatcher.dispatch(wo, deps)

    # ----- Step 8: assert pipeline state + bounded cost ----------------
    assert session.state == ChiefSessionState.AWAITING_EVALUATION, (
        f"Live pipeline did not reach AWAITING_EVALUATION; final state "
        f"was {session.state.value!r}. error={session.error!r}"
    )
    assert session.run_count == 1, (
        f"run_count should be 1 after a single dispatch, got "
        f"{session.run_count}"
    )
    assert session.work_order_id == wo.id
    assert session.department == "strategy"

    # Real cost was charged. WarmChief.__aexit__ adds the run's
    # ``total_cost_usd`` to the session row before transitioning to
    # AWAITING_EVALUATION, so a successful live run MUST have a positive
    # ``cost_usd``. A zero here means either the model returned without
    # billing (unexpected) or the cost-attribution path is broken.
    assert session.cost_usd > 0, (
        f"Live run completed but session.cost_usd is {session.cost_usd}; "
        f"expected a positive cost since the real model was invoked."
    )
    assert session.cost_usd < cost_cap, (
        f"Live run cost ${session.cost_usd:.4f} exceeds the per-run cap "
        f"${cost_cap:.2f}. Either the run produced more output than the "
        f"intent warrants, or the cap is too tight. Override via "
        f"LIVE_COST_CAP=<usd> if the latter."
    )

    # Routed event was published before WarmChief ran.
    routed_events = [
        e for e in event_bus._recent_events
        if e.event_type == "chief_dispatcher.routed"
    ]
    assert len(routed_events) == 1, (
        f"Expected exactly 1 chief_dispatcher.routed event, got "
        f"{len(routed_events)}"
    )
    assert routed_events[0].payload["department"] == "strategy"
    assert routed_events[0].payload["session_id"] == session.session_id

    # ----- Verifier check: re-run a fresh team to capture a TeamResult --
    # The dispatcher does not expose the WarmChief.result on the returned
    # ChiefSession (same shape as the offline test's verifier check). To
    # exercise verify_team_result on representative live output we run a
    # second team against the tight config — this is the dispatcher-level
    # peer of the offline test's verifier-check pattern. Cost on the
    # second run is also bounded by the same cap.
    from teams._team import DepartmentTeam

    team = DepartmentTeam(tight_config, lazy_build=False)
    team_result = await team.run(
        "Reply with one sentence: confirm receipt.",
        deps=make_deps(
            session_id="z4-verifier-check-live",
            department="strategy",
            cost_tracker=cost_tracker,
            cost_limit_usd=cost_cap,
        ),
    )

    # The TeamResult has non-empty manager_output (real model produced
    # text) and passes all 8 verifier gates against the tightened config.
    assert team_result.manager_output, (
        "Live team_result.manager_output was empty; the real chief "
        "should have produced at least one sentence of output."
    )
    assert team_result.success is True, (
        f"Live team_result.success was False; error={team_result.error!r}"
    )

    violations = verify_team_result(team_result, tight_config)
    assert not violations, (
        "verify_team_result returned non-empty violations against the "
        "live chief output. The 8-gate verifier rejected what the chief "
        "produced. Violations:\n  - " + "\n  - ".join(violations)
    )

    # Verifier-check spend is bounded by the same cap.
    assert team_result.total_cost_usd < cost_cap, (
        f"Verifier-check team run cost ${team_result.total_cost_usd:.4f} "
        f"exceeds the per-run cap ${cost_cap:.2f}."
    )
