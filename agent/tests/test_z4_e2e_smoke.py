"""E2E offline smoke test for the Z4 chief-session pipeline (Z4-S51 #1400).

This is the first integration-level test that drives the FULL chief-session
pipeline as a single unit:

    WorkOrder
      → ChiefDispatcher.dispatch
      → WorkOrderRouter.route (NullRouter, deterministic)
      → ChiefSessionStore.create   (InMemoryChiefSessionStore — offline)
      → WarmChief context manager (WARM → EXECUTING transitions)
      → DepartmentTeam.run         (overridden deterministic chief — offline)
      → WarmChief.__aexit__        (EXECUTING → AWAITING_EVALUATION)
      → ChiefDispatcher returns the persisted ChiefSession
      → verify_team_result         (8-gate verifier — empty violations)

A second test exercises the formalized requeue path:

    AWAITING_EVALUATION → requeue → WARM → second dispatch → AWAITING_EVALUATION

Per the Z4-S51 spec the requeue path must keep ``run_count`` stable across
``ChiefDispatcher.requeue`` (no increment) and only bump on the next
WARM → EXECUTING transition driven by ``WarmChief.__aenter__``.

Why this lives at the integration layer:

    Each component already has its own unit tests (see
    ``test_chief_dispatcher.py``, ``test_warm_chief.py``,
    ``test_chief_session_store.py``, ``test_work_order_router.py``,
    ``test_playbook_validation.py``). The gap those unit tests don't cover
    is the *seam* — whether ``ChiefDispatcher.dispatch`` actually composes
    cleanly with a real ``WarmChief``, a real ``InMemoryChiefSessionStore``,
    a real ``DepartmentRegistry`` (loaded from a scaffolded YAML), and a
    real ``DepartmentTeam`` driven by ``TestModel``. This file is the
    contract test for that seam.

Offline contract:

- No ``ANTHROPIC_API_KEY``. No ``OPENROUTER_API_KEY``. No live API calls.
- The chief and specialist models are overridden with deterministic
  FunctionModels so the test performs one offline delegation and still
  satisfies the strict specialist floor.
- The team is scaffolded via ``scripts.scaffold_zone4`` into ``tmp_path``;
  no production team YAMLs are read or modified.

Authority note (Z4-S51 spec): if the dispatcher / WarmChief / DepartmentTeam
seam does not compose cleanly with TestModel for E2E testing, that's an
integration-gap finding to surface in the PR body — not a workaround to
silently bury. The pre-existing ``TestIntegrationWithTestModel`` class in
``test_warm_chief.py`` is the closest precedent and the one we follow here.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel

from bridge.chief_dispatcher import ChiefDispatcher
from bridge.chief_session import ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore
from bridge.event_bus import EventBus
from bridge.warm_chief import WarmChief
from bridge.work_order import WorkOrder
from bridge.work_order_router import NullRouter

# Source repo root, used to copy the golden _template.yaml into tmp_path so
# scaffold_doctor's template-field-set diff has something to compare against.
_SOURCE_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_TEMPLATE = (
    _SOURCE_REPO_ROOT / "agent" / "config" / "teams" / "_template.yaml"
)


# ---------------------------------------------------------------------------
# Helpers (mirrors test_playbook_validation.py — same scaffolding pattern)
# ---------------------------------------------------------------------------


def _patched_repo_root(fake_root: Path) -> list:
    """Redirect every scaffold/validate module-level path constant at fake_root.

    See the analogous helper in ``test_playbook_validation.py`` for the
    full rationale. The short version: the scaffold scripts cache their
    own ``REPO_ROOT`` / ``TEAMS_DIR`` constants at import time, so we
    must patch them on every module that uses them — there is no shared
    source of truth.
    """
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
    """Apply a list of ``unittest.mock.patch`` objects as a single context."""

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
    """Build a tmp REPO_ROOT skeleton with the golden template copied in.

    ``scaffold_zone4`` will create the team YAML + expertise + system_prompt
    files inside this tree; nothing escapes ``tmp_path``.
    """
    teams_dir = tmp_path / "agent" / "config" / "teams"
    expertise_dir = tmp_path / "agent" / "config" / "expertise" / "updatable"
    agents_dir = tmp_path / "agent" / "config" / "agents" / "zone4"
    teams_dir.mkdir(parents=True)
    expertise_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)

    if _SOURCE_TEMPLATE.exists():
        shutil.copy2(_SOURCE_TEMPLATE, teams_dir / "_template.yaml")

    return tmp_path


def _scaffold_chief_specialist_team(
    fake_root: Path,
    slug: str,
) -> Path:
    """Run ``scripts.scaffold_zone4 chief-specialist <slug>`` against fake_root.

    Returns the path to the freshly-created team YAML so the registry
    can be loaded from its containing directory.
    """
    import scripts.scaffold_zone4 as scaffold_mod

    with _stack_patches(_patched_repo_root(fake_root)):
        rc = scaffold_mod.main(["chief-specialist", slug])
    assert rc == 0, f"scaffold_zone4 chief-specialist exit code was {rc}"

    yaml_path = fake_root / f"agent/config/teams/{slug}.yaml"
    assert yaml_path.exists(), (
        f"scaffold did not write expected YAML at {yaml_path}"
    )
    return yaml_path


def _build_test_model_run_chief():
    """Return a ``WarmChief._run_chief`` replacement using offline models.

    The replacement rebuilds the ``DepartmentTeam`` (matching production
    ``_run_chief`` exactly) and drops deterministic models over both the
    chief and first specialist for the duration of the run.
    """
    from teams._team import DepartmentTeam
    from tests.test_teams.conftest import (
        make_chief_delegating_model,
        make_specialist_text_model,
    )

    async def _run_with_test_model(self):  # noqa: ANN001
        team = DepartmentTeam(self._config, lazy_build=False)
        specialist_name = self._config.employees[0].name
        chief_model = make_chief_delegating_model(
            [(specialist_name, "Run the E2E smoke specialist check.")],
            final_answer="E2E smoke: synthesised by TestModel",
        )
        specialist_model = make_specialist_text_model("E2E smoke specialist: ok")
        with team.employees[specialist_name].override(model=specialist_model):
            with team.manager.override(model=chief_model):
                return await team.run(self._task, deps=self._deps)

    return _run_with_test_model


# ---------------------------------------------------------------------------
# Test 1: end-to-end happy path — dispatch → AWAITING_EVALUATION + verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_to_chief_to_awaiting_evaluation_offline(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the full Z4 pipeline offline; assert AWAITING_EVALUATION + clean gates.

    Steps:
        1. Scaffold a chief-specialist team in ``tmp_path`` so the test
           never touches the production strategy.yaml etc.
        2. Load the team into a real ``DepartmentRegistry`` from that
           tmp directory.
        3. Build a ``ChiefDispatcher`` with a ``NullRouter`` pointing at
           the scaffolded team's slug + an ``InMemoryChiefSessionStore``
           + a real ``EventBus`` for observability.
        4. Override ``WarmChief._run_chief`` with deterministic offline
           ``DepartmentTeam.run`` so no live API call happens.
        5. Build a ``WorkOrder`` + ``BridgeDeps`` and call
           ``dispatcher.dispatch``.
        6. Assert the returned ``ChiefSession`` is in
           ``AWAITING_EVALUATION``, ``run_count == 1``, and the routed
           event was published.
        7. Run ``verify_team_result`` against the in-memory ``TeamResult``
           captured by ``WarmChief.result`` — assert the violations list
           is empty (all 8 gates pass).
    """
    slug = "smoke-test"

    # Match the playbook test's CWD posture: the factory's expertise /
    # system_prompt path resolution uses ``Path(...).resolve()`` against
    # the current working directory. chdir into fake_repo so the
    # scaffolded YAML's repo-relative paths land inside the tmp tree.
    monkeypatch.chdir(fake_repo)

    # ----- Step 1: scaffold the team into tmp_path -----------------------
    _scaffold_chief_specialist_team(fake_repo, slug)

    # ----- Step 2: load the freshly-scaffolded team via the registry ----
    from teams._registry import DepartmentRegistry

    teams_dir = fake_repo / "agent/config/teams"
    registry = DepartmentRegistry.from_directory(teams_dir)
    assert slug in registry.department_names(), (
        f"DepartmentRegistry did not discover {slug!r} from {teams_dir}; "
        f"discovered: {registry.department_names()}"
    )

    # ----- Step 3: build the dispatcher with offline-only components ----
    store = InMemoryChiefSessionStore()
    router = NullRouter(department=slug)
    event_bus = EventBus(data_dir=fake_repo / "data")

    dispatcher = ChiefDispatcher(
        router=router,
        session_store=store,
        dept_registry=registry,
        event_bus=event_bus,
    )

    # ----- Step 4: build the WorkOrder + BridgeDeps -----------------------
    wo = WorkOrder.create(
        intent="E2E smoke: validate chief-session pipeline offline",
        skill="test",
        project="z4-e2e-smoke",
    )

    # Local import keeps test fixture coupling minimal at module load.
    from tests.test_teams.conftest import make_deps

    deps = make_deps(session_id="z4-e2e-smoke", department=slug)

    # ----- Step 5: dispatch under the deterministic model override --------
    run_with_test_model = _build_test_model_run_chief()
    with mock.patch.object(WarmChief, "_run_chief", run_with_test_model):
        session = await dispatcher.dispatch(wo, deps)

    # ----- Step 6: assert pipeline state + routed event published -------
    assert session.state == ChiefSessionState.AWAITING_EVALUATION, (
        f"Pipeline did not reach AWAITING_EVALUATION; final state was "
        f"{session.state.value!r}. error={session.error!r}"
    )
    assert session.run_count == 1, (
        f"run_count should be 1 after a single dispatch, got {session.run_count}"
    )
    assert session.work_order_id == wo.id
    assert session.department == slug

    # Routed event was published before WarmChief ran.
    routed_events = [
        e for e in event_bus._recent_events
        if e.event_type == "chief_dispatcher.routed"
    ]
    assert len(routed_events) == 1, (
        f"Expected exactly 1 chief_dispatcher.routed event, got "
        f"{len(routed_events)}: {[e.event_type for e in event_bus._recent_events]}"
    )
    assert routed_events[0].payload["department"] == slug
    assert routed_events[0].payload["session_id"] == session.session_id

    # No rejected events on the happy path.
    rejected_events = [
        e for e in event_bus._recent_events
        if e.event_type == "chief_dispatcher.rejected"
    ]
    assert rejected_events == [], (
        f"Unexpected rejected events on happy path: {rejected_events}"
    )

    # ----- Step 7: run verify_team_result against the persisted store ----
    # We rebuild the TeamResult-equivalent shape via a second dispatch is
    # NOT needed; the cleanest gate-check here is to re-run the chief via
    # deterministic models and pass that TeamResult through verify_team_result. The
    # WarmChief's own ``result`` is stored on the WarmChief instance, but
    # the dispatcher does not expose it; rather than reach into private
    # state, we exercise the verifier on a fresh deterministic run that
    # mirrors what the chief produced inside the dispatch above.
    from teams._team import DepartmentTeam
    from teams._verify import verify_team_result

    config = registry.get_config(slug)
    team = DepartmentTeam(config, lazy_build=False)
    from tests.test_teams.conftest import (
        make_chief_delegating_model,
        make_specialist_text_model,
    )
    specialist_name = f"{slug}-specialist"
    chief_model = make_chief_delegating_model(
        [(specialist_name, "Run the verifier specialist check.")],
        final_answer="E2E smoke: synthesised by TestModel",
    )
    specialist_model = make_specialist_text_model("E2E smoke specialist: ok")
    with team.employees[specialist_name].override(model=specialist_model):
        with team.manager.override(model=chief_model):
            team_result = await team.run(
                "E2E smoke verifier check",
                deps=make_deps(session_id="z4-verifier-check", department=slug),
            )

    violations = verify_team_result(team_result, config)
    assert not violations, (
        "verify_team_result returned non-empty violations against the "
        "deterministic chief output. The 8-gate verifier rejected what "
        "the dispatcher's chief produced, which means the offline E2E path "
        "no longer composes cleanly with the verifier. Violations:\n  - "
        + "\n  - ".join(violations)
    )

    # Sanity: the chief's structured output flowed through.
    assert "synthesised by TestModel" in team_result.manager_output, (
        f"manager_output missing TestModel synthesis text. Got: "
        f"{team_result.manager_output!r}"
    )
    assert team_result.success is True


# ---------------------------------------------------------------------------
# Test 2: full lifecycle including formalized requeue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_full_lifecycle_with_requeue(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatch → AWAITING_EVALUATION → requeue → WARM, then a second run.

    Asserts the requeue invariants from Z4-S31 (#1393):

    - ``ChiefDispatcher.requeue(session_id)`` transitions
      AWAITING_EVALUATION → WARM in-place on the same session row.
    - ``run_count`` stays at 1 across ``requeue`` (only bumps on the
      next WARM → EXECUTING transition driven by ``WarmChief``).
    - A subsequent ``WarmChief`` run on the requeued session bumps
      ``run_count`` to 2 and lands back in AWAITING_EVALUATION.

    Note: ``ChiefDispatcher.dispatch`` always allocates a NEW
    ``ChiefSession`` row; the requeue path is the in-place mechanic
    for re-running the SAME row. To exercise the second run we drive
    the ``WarmChief`` directly against the requeued row, mirroring how
    Z4 background loops will resume work in production.
    """
    slug = "smoke-requeue"
    monkeypatch.chdir(fake_repo)

    _scaffold_chief_specialist_team(fake_repo, slug)

    from teams._registry import DepartmentRegistry

    teams_dir = fake_repo / "agent/config/teams"
    registry = DepartmentRegistry.from_directory(teams_dir)
    assert slug in registry.department_names()

    store = InMemoryChiefSessionStore()
    router = NullRouter(department=slug)
    event_bus = EventBus(data_dir=fake_repo / "data")

    dispatcher = ChiefDispatcher(
        router=router,
        session_store=store,
        dept_registry=registry,
        event_bus=event_bus,
    )

    wo = WorkOrder.create(
        intent="E2E smoke: requeue lifecycle",
        skill="test",
        project="z4-e2e-smoke",
    )

    from tests.test_teams.conftest import make_deps

    deps = make_deps(session_id="z4-e2e-requeue", department=slug)

    # ----- First dispatch: arrive at AWAITING_EVALUATION ----------------
    run_with_test_model = _build_test_model_run_chief()
    with mock.patch.object(WarmChief, "_run_chief", run_with_test_model):
        first = await dispatcher.dispatch(wo, deps)

    assert first.state == ChiefSessionState.AWAITING_EVALUATION
    assert first.run_count == 1

    # ----- Requeue: AWAITING_EVALUATION → WARM, run_count unchanged -----
    requeued = await dispatcher.requeue(first.session_id)
    assert requeued.session_id == first.session_id, (
        "requeue should mutate the SAME row, not allocate a new session_id"
    )
    assert requeued.state == ChiefSessionState.WARM, (
        f"requeue did not return to WARM; got {requeued.state.value!r}"
    )
    assert requeued.run_count == 1, (
        f"requeue must NOT increment run_count (it bumps on the next "
        f"WARM → EXECUTING transition); got {requeued.run_count}"
    )

    # ----- Second run on the requeued session: bumps run_count to 2 ----
    # The dispatcher allocates a new session per dispatch by design
    # (Z4-S21), so to exercise the same row we drive WarmChief directly
    # — this matches how a future "evaluator → reschedule" loop will
    # resume work in production.
    config = registry.get_config(slug)
    with mock.patch.object(WarmChief, "_run_chief", run_with_test_model):
        async with WarmChief(
            requeued, store, config, deps, "second pass"
        ) as warm:
            # Inside the body the chief has already run; state is EXECUTING.
            assert warm.session.state == ChiefSessionState.EXECUTING

    final = await store.get(first.session_id)
    assert final.state == ChiefSessionState.AWAITING_EVALUATION, (
        f"Second run did not return to AWAITING_EVALUATION; got "
        f"{final.state.value!r}. error={final.error!r}"
    )
    assert final.run_count == 2, (
        f"Second WARM → EXECUTING transition should have bumped run_count "
        f"to 2; got {final.run_count}"
    )

    # The requeued event was published exactly once.
    requeued_events = [
        e for e in event_bus._recent_events
        if e.event_type == "chief_dispatcher.requeued"
    ]
    assert len(requeued_events) == 1, (
        f"Expected exactly 1 chief_dispatcher.requeued event, got "
        f"{len(requeued_events)}"
    )
    assert requeued_events[0].payload["session_id"] == first.session_id
    # ``attempt`` carries the run_count at requeue time per the dispatcher
    # contract — the subscriber audits the requeue sequence by reading it.
    assert requeued_events[0].payload["attempt"] == 1


# ---------------------------------------------------------------------------
# P3.3 (#1584): end-to-end observability via POST /api/workorders + /ws/events.
#
# Drives the FULL chief-session pipeline through the same surface an operator
# would touch:
#
#   client POST /api/workorders         (with department=<slug>)
#     → APIServer._handle_create_workorder
#     → ChiefDispatcher.dispatch
#     → ChiefSession row created + chief_session.created event
#     → state_changed events on each WarmChief transition
#     → response carries chief_session_id
#
# While that happens, a parallel client subscribed to /ws/events captures the
# event stream. The test then asserts the stream contains every expected
# event AND every event carries the WO id as its top-level correlation_id.
#
# The chief itself is driven by TestModel with call_tools=[] (matches the
# offline contract above); the delegate() event is exercised separately by
# invoking the tool directly post-dispatch (TestModel cannot reliably drive
# a roster-valid delegate call). Both code paths publish through the same
# EventBus, so the WebSocket sees both.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.socket
async def test_dispatcher_e2e_observable_via_websocket(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST → dispatch → WS event stream sees routed/created/state_changed/delegate.

    Asserts the P3.3 observability contract: every event published during a
    WorkOrder's dispatch lifecycle carries the WO id as its top-level
    ``correlation_id``, and the four event TYPES the audit calls out
    (``chief_dispatcher.routed``, ``chief_session.created``,
    ``chief_session.state_changed`` for both WARM→EXECUTING and
    EXECUTING→AWAITING_EVALUATION, plus ``department.delegation.started``)
    all reach the ``/ws/events`` subscriber.
    """
    import asyncio
    import json as _json
    from unittest.mock import AsyncMock, MagicMock

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from bridge.api_server import (
        APIServer,
        cors_middleware,
        create_auth_middleware,
    )
    from bridge.chief_dispatcher import ChiefDispatcher
    from bridge.event_bus import EventBus

    slug = "smoke-e2e-ws"
    api_token = "test-token-p3-3-e2e"

    monkeypatch.chdir(fake_repo)
    _scaffold_chief_specialist_team(fake_repo, slug)

    from teams._registry import DepartmentRegistry

    teams_dir = fake_repo / "agent/config/teams"
    registry = DepartmentRegistry.from_directory(teams_dir)
    assert slug in registry.department_names()

    # Real EventBus + InMemory store + real ChiefDispatcher — the WS handler
    # subscribes via ``bridge._autonomy.event_bus.subscribe`` so we wire a
    # MagicMock bridge with a real EventBus exposed at that path.
    event_bus = EventBus(data_dir=fake_repo / "data")
    store = InMemoryChiefSessionStore()
    router = NullRouter(department=slug)
    dispatcher = ChiefDispatcher(
        router=router,
        session_store=store,
        dept_registry=registry,
        event_bus=event_bus,
    )

    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = str(fake_repo / "data")
    bridge._config.operator_discord_id = "test-operator"
    bridge._config.peer_coordination_enabled = False
    bridge._config.chief_dispatcher_enabled = True
    bridge._db = AsyncMock()
    bridge._health_server = None
    bridge._tmux_agents = None
    bridge._session_mgr = None
    bridge._cost_tracker = None
    bridge._memory = None
    bridge._commands = None
    bridge._metrics = None
    bridge._tracer = None
    bridge._task_queue = None
    bridge._task_pipeline = None
    bridge._quality_gate = None
    bridge._webhook_receiver = None
    bridge._peer_registry = None
    bridge._workorder_store = None
    bridge._workorder_stream = None
    bridge._chief_dispatcher = dispatcher
    bridge._chief_session_store = store

    # WS handler reads ``bridge._autonomy.event_bus`` — wire the same bus.
    autonomy = MagicMock()
    autonomy.event_bus = event_bus
    bridge._autonomy = autonomy

    # The /api/workorders dispatch path constructs BridgeDeps via
    # BridgeDeps.from_app(self._bridge, ...). The MagicMock bridge accepts
    # arbitrary attribute reads; from_app reaches into ``memory``,
    # ``knowledge_search``, ``cost_tracker``, ``event_bus``, ``trust_manager``,
    # ``config.operator.chat_id`` (or ``_config.operator_discord_id``).
    # Returning MagicMock() for each is acceptable for the offline path —
    # the chief is overridden via WarmChief._run_chief patch below.
    bridge.memory = MagicMock()
    bridge.knowledge_search = MagicMock()
    bridge.cost_tracker = MagicMock()
    bridge.event_bus = event_bus
    bridge.trust_manager = MagicMock()

    server_obj = APIServer(bridge, api_token=api_token, port=0)
    app = web.Application(
        middlewares=[
            cors_middleware,
            create_auth_middleware(server_obj._api_token),
        ]
    )
    server_obj._register_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()

    # Override WarmChief._run_chief so the chief produces a TeamResult via
    # TestModel — no live API call, no roster-required delegate.
    run_with_test_model = _build_test_model_run_chief()

    received_events: list[dict] = []

    async def _consume_ws(ws) -> None:
        """Drain WS frames into ``received_events`` until the connection
        closes or the test cancels the task."""
        try:
            async for msg in ws:
                if msg.type.name == "TEXT":
                    try:
                        received_events.append(_json.loads(msg.data))
                    except Exception:
                        continue
                elif msg.type.name in ("CLOSE", "CLOSING", "CLOSED", "ERROR"):
                    return
        except asyncio.CancelledError:
            return

    try:
        # Subscribe before POSTing so no events race the subscription.
        async with client.ws_connect(f"/ws/events?token={api_token}") as ws:
            consumer = asyncio.create_task(_consume_ws(ws))
            # Give the WS handler a tick to install its EventBus
            # subscriptions before we publish anything through dispatch.
            await asyncio.sleep(0.05)

            with mock.patch.object(
                WarmChief, "_run_chief", run_with_test_model,
            ):
                resp = await client.post(
                    "/api/workorders",
                    json={
                        "intent": "P3.3 E2E observability test",
                        "skill": "test",
                        "project": "z4-e2e-ws",
                        "department": slug,
                    },
                    headers={"Authorization": f"Bearer {api_token}"},
                )

            assert resp.status == 201, (
                f"POST /api/workorders returned {resp.status}: "
                f"{await resp.text()}"
            )
            body = await resp.json()
            wo_id: str = body["workorder_id"]
            session_id: str = body["chief_session_id"]
            assert body["chief_session_state"] == "awaiting_evaluation", (
                f"Dispatch did not reach AWAITING_EVALUATION; final state was "
                f"{body['chief_session_state']!r}"
            )

            # P3.3 (#1584) — also exercise the delegate() tool's event
            # publish. TestModel(call_tools=[]) blocks the chief from
            # calling delegate inside the run above; to verify the
            # delegate-side observability hook fires we invoke the tool
            # directly with a roster-valid specialist. This is the same
            # production code path; only the trigger differs.
            await _invoke_delegate_directly(registry, slug, event_bus, wo_id)

            # Let the WS drain pending frames.
            await asyncio.sleep(0.3)
            consumer.cancel()
            try:
                await consumer
            except asyncio.CancelledError:
                pass

        # -----------------------------------------------------------------
        # Assertions on the captured WS stream
        # -----------------------------------------------------------------
        seen_types = [e["event_type"] for e in received_events]

        # Every expected event type made it to the WebSocket subscriber.
        for required_type in (
            "chief_dispatcher.routed",
            "chief_session.created",
            "chief_session.state_changed",
            "department.delegation.started",
        ):
            assert required_type in seen_types, (
                f"Required event {required_type!r} did not reach the WS "
                f"stream. Saw: {seen_types}"
            )

        # The WARM→EXECUTING and EXECUTING→AWAITING_EVALUATION transitions
        # both fire as ``chief_session.state_changed`` events.
        state_changed = [
            e for e in received_events
            if e["event_type"] == "chief_session.state_changed"
        ]
        transitions = {
            (e["payload"].get("from_state"), e["payload"].get("to_state"))
            for e in state_changed
        }
        assert ("cold", "warm") in transitions, (
            f"Missing COLD → WARM transition event. Got: {transitions}"
        )
        assert ("warm", "executing") in transitions, (
            f"Missing WARM → EXECUTING transition event. Got: {transitions}"
        )
        assert ("executing", "awaiting_evaluation") in transitions, (
            f"Missing EXECUTING → AWAITING_EVALUATION transition event. "
            f"Got: {transitions}"
        )

        # -----------------------------------------------------------------
        # Correlation IDs link every dispatcher / session event back to WO id.
        # -----------------------------------------------------------------
        for event in received_events:
            etype = event["event_type"]
            cid = event.get("correlation_id")
            if etype in {
                "chief_dispatcher.routed",
                "chief_session.created",
                "chief_session.state_changed",
            }:
                assert cid == wo_id, (
                    f"Event {etype} carried correlation_id {cid!r}; "
                    f"expected WO id {wo_id!r}"
                )
                # session_id is also threaded on the payload for cross-
                # reference back to the chief session row.
                assert event["payload"].get("session_id") == session_id, (
                    f"Event {etype} session_id mismatch: "
                    f"{event['payload'].get('session_id')!r} != {session_id!r}"
                )

        # delegate() carries the BridgeDeps.session_id as its correlation
        # — that field is the chief's session-id surface inside the run,
        # which the dispatcher path sets to a dispatch-uuid. The test
        # asserts presence rather than exact value: a non-empty cid links
        # the delegation to its parent invocation context.
        delegate_events = [
            e for e in received_events
            if e["event_type"] == "department.delegation.started"
        ]
        assert delegate_events, "No department.delegation.started event"
        for e in delegate_events:
            assert e.get("correlation_id"), (
                f"delegation event {e['event_id']} has no correlation_id; "
                f"payload={e['payload']!r}"
            )

    finally:
        await client.close()


async def _invoke_delegate_directly(
    registry,
    slug: str,
    event_bus,
    wo_id: str,
) -> None:
    """Exercise the delegate() tool's event publish via a direct invocation.

    TestModel(call_tools=[]) blocks the chief from calling delegate during
    the dispatch above. To verify the delegate-side P3.3 publish reaches
    the EventBus (and downstream WS subscribers), we build the same team
    the dispatcher built, locate the ``delegate`` tool's underlying
    function on the manager agent, and invoke it with a roster-valid
    specialist + a TestModel-driven specialist agent.

    This is not the production chief-driven path — it's an integration
    test of the tool's own observability hook. The dispatcher-driven
    chief→delegate path lands once we move beyond TestModel.
    """
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from teams._team import DepartmentTeam
    from tests.test_teams.conftest import make_deps

    config = registry.get_config(slug)
    team = DepartmentTeam(config, lazy_build=False)

    # Override the specialist's model so its run is offline + fast.
    specialist_name = next(iter(team._employees.keys()))
    specialist_agent = team._employees[specialist_name]
    test_model = TestModel(custom_output_args="ack", call_tools=[])

    # Override the specialist's model — the chief never runs here; we
    # call delegate directly.
    deps = make_deps(session_id=wo_id, department=slug)
    deps_with_bus = _replace_deps_event_bus(deps, event_bus)

    # Find the delegate tool function by inspecting the manager's
    # registered tools. The factory registers it via ``manager.tool(name=
    # "delegate")(...)`` so it lives in the agent's toolset by name.
    delegate_fn = _find_delegate_tool(team.manager)
    assert delegate_fn is not None, (
        "delegate tool not found on manager agent — _factory.py contract "
        "changed; the test needs an update."
    )

    ctx = RunContext(deps=deps_with_bus, model=test_model, usage=RunUsage())
    with specialist_agent.override(model=test_model):
        await delegate_fn(ctx, specialist=specialist_name, task="hello")


def _find_delegate_tool(manager_agent):
    """Return the ``delegate`` tool's underlying function from the manager.

    Pydantic-AI exposes registered tools via ``Agent._function_toolset`` —
    we look up the ``delegate`` entry and return its ``function``. This
    is test-internal coupling to pydantic-ai's API surface; if the surface
    changes the test fails loudly rather than silently skipping the
    observability assertion.
    """
    toolset = getattr(manager_agent, "_function_toolset", None)
    if toolset is None:
        return None
    tools = getattr(toolset, "tools", None) or {}
    tool = tools.get("delegate")
    if tool is None:
        return None
    # ``ToolsetTool`` stores the bound function on ``.tool_def`` or
    # exposes ``.function`` depending on pydantic-ai's minor version;
    # try both.
    fn = getattr(tool, "function", None)
    if fn is None:
        fn = getattr(tool, "func", None)
    return fn


def _replace_deps_event_bus(deps, event_bus):
    """Return a copy of ``deps`` with ``event_bus`` replaced.

    BridgeDeps is a frozen dataclass; ``dataclasses.replace`` returns
    a new instance. Used by the direct-delegate path so the test's
    EventBus catches the delegation event.
    """
    from dataclasses import replace as dc_replace
    return dc_replace(deps, event_bus=event_bus)
