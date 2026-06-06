"""Load test for the Z4 chief-session pipeline (Z4-S62 #1406).

Stress the ``ChiefDispatcher`` with 10 concurrent ``WorkOrder`` dispatches
fanning out across 3 scaffolded departments. Asserts the invariants the
operator wants confirmed before flipping ``chief_dispatcher_enabled=true``
in production:

1. **No session-row leaks.** Every dispatch produces exactly one
   ``ChiefSession``; the in-memory store ends with ``len(_sessions) ==
   10`` and every session reaches a non-EXECUTING terminal state
   (AWAITING_EVALUATION on the happy path; FAILED is also acceptable).
2. **No session-id collisions.** All 10 returned ``session_id`` values
   are unique. (The dispatcher allocates via ``new_chief_session_id()``
   on every call; any UUID collision under concurrency is a bug worth
   surfacing.)
3. **Event publishing is lossless.** Exactly 10
   ``chief_dispatcher.routed`` events fire — one per successful dispatch
   — and zero ``chief_dispatcher.rejected`` events fire on the happy
   path.
4. **Cost attribution stays clean.** The 10 ``cost_usd`` values are
   addressable per session_id (no aliasing).
5. **Wall-clock bound.** Total wall-clock for 10 concurrent dispatches
   under TestModel is well under 15s — the offline pipeline has no real
   model latency to amortize.

Routing posture (mix of Tier 1 + Tier 2 per the spec):

- 6 work orders set ``department_target`` explicitly
  (``WorkOrder.with_department``) — Tier 1 confidence 1.0.
- 4 work orders carry intent strings whose tokens overlap with one
  scaffolded department's description but no others — Tier 2 keyword
  match at confidence 0.75.

We rewrite each scaffolded YAML's ``team.description`` post-scaffold so
the keyword-router has discriminative tokens to work with. Without that
rewrite, all three scaffolded teams share the generic
``"<Name> Department."`` description, which would push every Tier-2
candidate to the same low-score-tied bucket and degrade routing to
Tier-4 default-fallback for everyone — defeating the point of asking
the router to fan out.

Offline contract (mirrors ``test_z4_e2e_smoke.py``):

- No ``ANTHROPIC_API_KEY`` / ``OPENROUTER_API_KEY`` reads.
- ``WarmChief._run_chief`` is patched to run ``DepartmentTeam.run`` under
  ``make_chief_delegating_model`` + ``make_specialist_text_model``
  overrides — driving a deterministic offline delegation that satisfies
  the post-#1645 strict-floor Gate 8 (``expected_min_specialists=1``).
- All teams scaffolded into ``tmp_path``; production team YAMLs are
  never touched.

Authority note (Z4-S62 spec): if the load test surfaces real concurrency
bugs — session-id collision, event drops, semaphore violations,
``InvalidTransitionError`` from a reaper race, etc. — the test's job is
to FAIL loudly. The fix lives in a follow-up sprint, not here.
"""
from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import pytest
import yaml

from bridge.chief_dispatcher import ChiefDispatcher
from bridge.chief_session import ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore
from bridge.event_bus import EventBus
from bridge.warm_chief import WarmChief
from bridge.work_order import WorkOrder
from bridge.work_order_router import RuleBasedWorkOrderRouter

# Source repo root, used to copy the golden _template.yaml into tmp_path so
# the scaffold's downstream validators have something to compare against.
_SOURCE_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_TEMPLATE = (
    _SOURCE_REPO_ROOT / "agent" / "config" / "teams" / "_template.yaml"
)


# ---------------------------------------------------------------------------
# Scaffold helpers (mirrors test_z4_e2e_smoke.py — same patching pattern)
# ---------------------------------------------------------------------------


def _patched_repo_root(fake_root: Path) -> list:
    """Redirect the scaffold module's REPO_ROOT/TEAMS_DIR at fake_root."""
    import scripts.scaffold_zone4 as scaffold_mod
    import scripts.validate_team_yaml as validate_mod

    teams_dir = fake_root / "agent" / "config" / "teams"
    template_path = teams_dir / "_template.yaml"

    return [
        patch.object(scaffold_mod, "REPO_ROOT", fake_root),
        patch.object(scaffold_mod, "TEAMS_DIR", teams_dir),
        patch.object(validate_mod, "REPO_ROOT", fake_root),
        patch.object(validate_mod, "TEAMS_DIR", teams_dir),
        patch.object(validate_mod, "TEMPLATE_PATH", template_path),
    ]


class _stack_patches:
    """Apply a list of ``unittest.mock.patch`` objects as one context."""

    def __init__(self, patches: list) -> None:
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for p in reversed(self._patches):
            p.stop()
        return False


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """Build a tmp REPO_ROOT skeleton with the golden template copied in."""
    teams_dir = tmp_path / "agent" / "config" / "teams"
    expertise_dir = tmp_path / "agent" / "config" / "expertise" / "updatable"
    agents_dir = tmp_path / "agent" / "config" / "agents" / "zone4"
    teams_dir.mkdir(parents=True)
    expertise_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)

    if _SOURCE_TEMPLATE.exists():
        shutil.copy2(_SOURCE_TEMPLATE, teams_dir / "_template.yaml")

    return tmp_path


def _scaffold_chief_specialist_team(fake_root: Path, slug: str) -> Path:
    """Run ``scripts.scaffold_zone4 chief-specialist <slug>`` against fake_root."""
    import scripts.scaffold_zone4 as scaffold_mod

    with _stack_patches(_patched_repo_root(fake_root)):
        rc = scaffold_mod.main(["chief-specialist", slug])
    assert rc == 0, f"scaffold_zone4 chief-specialist exit code was {rc}"

    yaml_path = fake_root / f"agent/config/teams/{slug}.yaml"
    assert yaml_path.exists(), f"scaffold did not write {yaml_path}"
    return yaml_path


def _rewrite_description(yaml_path: Path, new_description: str) -> None:
    """Overwrite ``team.description`` so the Tier-2 keyword router has signal.

    The default scaffold writes ``"<Name> Department."`` for every team —
    too generic to differentiate when three teams coexist. We inject
    distinctive keyword sets so the router's ``_match_keywords`` produces
    one unambiguous winner per intent string.
    """
    with yaml_path.open() as fh:
        data = yaml.safe_load(fh)
    data["team"]["description"] = new_description
    with yaml_path.open("w") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def _build_test_model_run_chief():
    """Return a ``WarmChief._run_chief`` replacement using offline models.

    Same pattern as ``test_z4_e2e_smoke.py::_build_test_model_run_chief``;
    duplicated here so this load test stays self-contained and an unrelated
    edit to the smoke-test helper can't silently change load-test
    semantics.

    P3.6 strict-floor migration (#1693): each ``_run_with_test_model`` call
    builds its OWN ``chief_model`` so the closure-local ``call_count`` in
    ``make_chief_delegating_model`` doesn't collapse across the 10
    concurrent dispatches. See ``agent/CLAUDE.md`` Delegation-floor
    convention and the ``test_qa_concurrent_invocations_respect_semaphore``
    precedent for the per-coroutine fresh-model pattern.
    """
    from teams._team import DepartmentTeam
    from tests.test_teams.conftest import (
        make_chief_delegating_model,
        make_specialist_text_model,
    )

    async def _run_with_test_model(self):  # noqa: ANN001
        team = DepartmentTeam(self._config, lazy_build=False)
        specialist_name = self._config.employees[0].name
        # Fresh chief_model per coroutine — call_count is closure-local.
        chief_model = make_chief_delegating_model(
            [(specialist_name, "Run the Z4-S62 load test specialist check.")],
            final_answer="Z4-S62 load test: synthesised by TestModel",
        )
        specialist_model = make_specialist_text_model(
            "Z4-S62 load test specialist: ok"
        )
        with team.employees[specialist_name].override(model=specialist_model):
            with team.manager.override(model=chief_model):
                return await team.run(self._task, deps=self._deps)

    return _run_with_test_model


# ---------------------------------------------------------------------------
# The load test
# ---------------------------------------------------------------------------


# Keyword-disjoint descriptions: each department's vocabulary is unique
# enough that a 4+ char-word intersection picks one winner. We avoid
# common stems ("department", "load", "test") that would produce ties.
_DEPT_DESCRIPTIONS: dict[str, str] = {
    "loadalpha": (
        "Strategic planning roadmap product analysis market positioning."
    ),
    "loadbeta": (
        "Engineering implementation backend frontend deployment release."
    ),
    "loadgamma": (
        "Quality verification regression coverage testing assurance."
    ),
}

# Tier-2 intents that map deterministically to one department each via
# the unique tokens in ``_DEPT_DESCRIPTIONS`` above.
_TIER2_INTENTS: list[tuple[str, str]] = [
    ("loadalpha", "Run a strategic planning roadmap analysis."),
    ("loadbeta", "Engineering implementation deployment for backend release."),
    ("loadgamma", "Quality regression coverage and verification testing."),
    ("loadalpha", "Strategic market positioning product analysis."),
]


@pytest.mark.asyncio
async def test_dispatcher_handles_10_concurrent_workorders_across_3_departments(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """10 concurrent dispatches fan out across 3 departments — no corruption.

    Steps:
        1. Scaffold 3 chief-specialist teams in tmp_path. Rewrite each
           ``team.description`` with a keyword-disjoint vocabulary.
        2. Load all three into a real ``DepartmentRegistry``.
        3. Build a ``ChiefDispatcher`` with a real
           ``RuleBasedWorkOrderRouter`` (so routing logic actually runs),
           an ``InMemoryChiefSessionStore``, and a real ``EventBus``.
        4. Build 10 ``WorkOrder``s — 6 explicit (Tier 1) + 4 keyword
           (Tier 2) covering all 3 departments.
        5. Patch ``WarmChief._run_chief`` with a delegating-model-driven
           DepartmentTeam.run so no live API calls happen and Gate 8's
           strict-floor (``expected_min_specialists=1``) is satisfied.
        6. Fire all 10 via ``asyncio.gather`` and time the wall-clock.
        7. Assert every concurrency invariant the spec calls out.
    """
    monkeypatch.chdir(fake_repo)

    # ----- Step 1: scaffold + rewrite descriptions ----------------------
    slugs = list(_DEPT_DESCRIPTIONS.keys())
    for slug in slugs:
        yaml_path = _scaffold_chief_specialist_team(fake_repo, slug)
        _rewrite_description(yaml_path, _DEPT_DESCRIPTIONS[slug])

    # ----- Step 2: load via the real registry ----------------------------
    from teams._registry import DepartmentRegistry

    teams_dir = fake_repo / "agent/config/teams"
    registry = DepartmentRegistry.from_directory(teams_dir)
    discovered = set(registry.department_names())
    for slug in slugs:
        assert slug in discovered, (
            f"DepartmentRegistry did not discover {slug!r}; "
            f"discovered: {sorted(discovered)}"
        )

    # ----- Step 3: build the dispatcher with offline-only components ----
    store = InMemoryChiefSessionStore()
    router = RuleBasedWorkOrderRouter(
        registry=registry,
        default_department=slugs[0],  # loadalpha as Tier-4 fallback
    )
    event_bus = EventBus(data_dir=fake_repo / "data")
    dispatcher = ChiefDispatcher(
        router=router,
        session_store=store,
        dept_registry=registry,
        event_bus=event_bus,
    )

    # ----- Step 4: build 10 WorkOrders, mixing Tier 1 + Tier 2 ----------
    # 6 Tier-1 (explicit ``department_target``): 2 per department.
    tier1_assignments: list[str] = (
        [slugs[0]] * 2 + [slugs[1]] * 2 + [slugs[2]] * 2
    )
    work_orders: list[WorkOrder] = []
    for i, dept in enumerate(tier1_assignments):
        wo = WorkOrder.create(
            intent=f"Z4-S62 load test Tier-1 #{i} explicit -> {dept}",
            skill="test",
            project="z4-load",
        ).with_department(dept)
        work_orders.append(wo)

    # 4 Tier-2 (keyword routing) — pull from _TIER2_INTENTS.
    expected_tier2_targets: list[str] = []
    for dept, intent in _TIER2_INTENTS:
        wo = WorkOrder.create(
            intent=intent,
            skill="test",
            project="z4-load",
        )
        work_orders.append(wo)
        expected_tier2_targets.append(dept)

    assert len(work_orders) == 10

    # ----- Step 5: build deps shared across the fan-out -----------------
    from tests.test_teams.conftest import make_deps

    # Each dispatch gets its own BridgeDeps so the session_id fields
    # don't alias inside the chief's run context. Department field is
    # set to a sentinel — the dispatcher's call into WarmChief doesn't
    # use deps.department for routing (that already happened upstream).
    deps_list = [
        make_deps(session_id=f"z4-load-{i}", department="z4-load")
        for i in range(10)
    ]

    # ----- Step 6: fire all 10 concurrently under TestModel override ----
    run_with_test_model = _build_test_model_run_chief()
    started = time.monotonic()
    with mock.patch.object(WarmChief, "_run_chief", run_with_test_model):
        results = await asyncio.gather(
            *[
                dispatcher.dispatch(wo, deps_list[i])
                for i, wo in enumerate(work_orders)
            ],
            return_exceptions=True,
        )
    elapsed = time.monotonic() - started

    # ----- Step 7: invariants ------------------------------------------

    # 7a — wall clock bound. Generous (15s) — TestModel is fast; if we
    # blow this, the dispatcher has a real concurrency / lock-contention
    # issue worth surfacing.
    assert elapsed < 15.0, (
        f"10 concurrent TestModel dispatches took {elapsed:.2f}s "
        f"(> 15s budget). Investigate dispatcher concurrency."
    )

    # 7b — no exceptions surfaced from gather. Any exception here is a
    # concurrency bug (the dispatcher catches WarmChief failures and
    # returns a FAILED ChiefSession instead of raising).
    exceptions = [r for r in results if isinstance(r, Exception)]
    assert not exceptions, (
        "asyncio.gather surfaced exceptions from concurrent dispatch. "
        "The dispatcher contract says executor failures land on FAILED "
        "rows, not raised exceptions. Investigate:\n  "
        + "\n  ".join(repr(e) for e in exceptions)
    )
    sessions = [r for r in results if not isinstance(r, Exception)]
    assert len(sessions) == 10

    # 7c — every session in a non-EXECUTING terminal state. The happy
    # path lands at AWAITING_EVALUATION; FAILED / TIMED_OUT / SHUTDOWN
    # are also acceptable terminal states (the test would still expose
    # any session stuck mid-run as a bug).
    terminal_ok = {
        ChiefSessionState.AWAITING_EVALUATION,
        ChiefSessionState.FAILED,
        ChiefSessionState.TIMED_OUT,
        ChiefSessionState.SHUTDOWN,
    }
    stuck = [s for s in sessions if s.state not in terminal_ok]
    assert not stuck, (
        "Sessions stuck in non-terminal state after concurrent dispatch:\n  "
        + "\n  ".join(
            f"{s.session_id} state={s.state.value}" for s in stuck
        )
    )

    # 7d — happy path expectation: with the delegating chief model + a
    # stubbed first specialist, the chief produces a clean structured
    # output every time and Gate 8 passes, so all 10 SHOULD reach
    # AWAITING_EVALUATION. Failures here are concurrency bugs to
    # surface, not an excuse to weaken the assertion.
    awaiting = [
        s for s in sessions if s.state == ChiefSessionState.AWAITING_EVALUATION
    ]
    failed = [s for s in sessions if s.state == ChiefSessionState.FAILED]
    assert len(awaiting) == 10, (
        f"Expected all 10 to reach AWAITING_EVALUATION under TestModel; "
        f"got {len(awaiting)} AWAITING_EVALUATION + "
        f"{len(failed)} FAILED + "
        f"{len(sessions) - len(awaiting) - len(failed)} other.\n"
        + "  FAILED errors:\n    "
        + "\n    ".join(f"{s.session_id}: {s.error!r}" for s in failed)
    )

    # 7e — session_id uniqueness. UUID collision under concurrency would
    # be a real (if unlikely) bug worth exposing.
    session_ids = [s.session_id for s in sessions]
    assert len(set(session_ids)) == 10, (
        f"Session-id collision detected. Got {len(set(session_ids))} "
        f"unique ids out of 10 dispatches: {session_ids}"
    )

    # 7f — store contains exactly 10 rows; no leaks, no overcounting.
    assert len(store._sessions) == 10, (
        f"InMemoryChiefSessionStore holds {len(store._sessions)} rows; "
        f"expected 10 (one per dispatch). Possible session leak."
    )

    # 7g — exactly 10 chief_dispatcher.routed events.
    routed_events = [
        e for e in event_bus._recent_events
        if e.event_type == "chief_dispatcher.routed"
    ]
    assert len(routed_events) == 10, (
        f"Expected exactly 10 chief_dispatcher.routed events; got "
        f"{len(routed_events)}. EventBus may be dropping events under "
        f"concurrency."
    )

    # 7h — every routed event's session_id matches a real session row.
    routed_session_ids = {e.payload["session_id"] for e in routed_events}
    assert routed_session_ids == set(session_ids), (
        "chief_dispatcher.routed event session_ids do not match the "
        "returned ChiefSession ids. Possible event/session aliasing.\n"
        f"  in events:    {sorted(routed_session_ids)}\n"
        f"  in sessions:  {sorted(session_ids)}"
    )

    # 7i — no rejected events on the happy path.
    rejected_events = [
        e for e in event_bus._recent_events
        if e.event_type == "chief_dispatcher.rejected"
    ]
    assert rejected_events == [], (
        f"Unexpected chief_dispatcher.rejected events on happy-path "
        f"load test: {[e.payload for e in rejected_events]}"
    )

    # 7j — every department actually got at least one dispatch (the
    # router fanned out, didn't collapse to a single team).
    departments_hit = {s.department for s in sessions}
    assert departments_hit == set(slugs), (
        f"Routing did not fan out across all 3 departments. "
        f"Hit: {sorted(departments_hit)}; expected: {sorted(slugs)}"
    )

    # 7k — Tier-1 work orders landed on their explicit department_target.
    # The first 6 work orders carry explicit targets; sessions are
    # returned in dispatch-call order by asyncio.gather, so the first 6
    # results correspond to the first 6 work orders.
    for i, expected_dept in enumerate(tier1_assignments):
        assert sessions[i].department == expected_dept, (
            f"Tier-1 wo[{i}] expected department={expected_dept!r}, "
            f"got {sessions[i].department!r}. Routing did not honor "
            f"explicit department_target under concurrency."
        )

    # 7l — Tier-2 work orders landed on their keyword-derived target.
    for offset, expected_dept in enumerate(expected_tier2_targets):
        idx = 6 + offset
        assert sessions[idx].department == expected_dept, (
            f"Tier-2 wo[{idx}] intent={work_orders[idx].intent!r}: "
            f"expected keyword-route to {expected_dept!r}, got "
            f"{sessions[idx].department!r}. Tier-2 keyword router may be "
            f"non-deterministic under concurrency."
        )

    # 7m — cost_usd is addressable per session (no aliasing). The
    # chief-session contract says cost is mutated via increment_cost ->
    # store.update; with TestModel + call_tools=[] no real cost is
    # accrued, so every session lands at the default 0.0. The point of
    # this assertion is shape — that store.get(sid).cost_usd is a real
    # per-session attribute, not aliased across sessions.
    cost_by_id = {sid: (await store.get(sid)).cost_usd for sid in session_ids}
    assert len(cost_by_id) == 10
    for sid, cost in cost_by_id.items():
        assert cost == 0.0, (
            f"Session {sid} has non-zero cost_usd={cost} under "
            f"TestModel; expected 0.0 (no real model calls). Possible "
            f"cross-session cost aliasing."
        )
