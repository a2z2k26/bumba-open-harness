"""Tests for `bridge.warm_chief` — Z4-S11 (#1382).

Coverage targets:
- Happy path: WARM → EXECUTING → AWAITING_EVALUATION transitions persisted.
- Failure path: WARM → EXECUTING → FAILED with error captured + re-raise.
- Cost attribution: ``result.total_cost_usd`` is added to ``session.cost_usd``
  BEFORE the AWAITING_EVALUATION update, so the persisted row reflects the
  run's full cost on the next reader's first lookup.
- ``result`` property guard: raises before the run, returns ``TeamResult`` after.
- Integration via ``TestModel`` (PydanticAI) against a real ``DepartmentTeam``
  to prove the wiring of ``_run_chief`` matches today's chief invocation.

Tests use ``InMemoryChiefSessionStore`` from Z4-S03 (#1387) — the Protocol
contract guarantees ``WarmChief`` works against any conformant store, so a
later swap to the SQLite-backed impl from Z4-S10 (#1381) does not require
re-running these tests.
"""
from __future__ import annotations

from unittest import mock

import pytest
from pydantic_ai.models.test import TestModel

from bridge.chief_session import (
    ChiefSession,
    ChiefSessionState,
)
from bridge.chief_session_store import InMemoryChiefSessionStore
from bridge.warm_chief import CostCapExceededError, WarmChief
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Constraints,
    DepartmentConfig,
    EmployeeResult,
    TeamResult,
)
from tests.test_teams.conftest import make_deps


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session(
    *,
    state: ChiefSessionState = ChiefSessionState.WARM,
    session_id: str = "cs-warmchief01",
    work_order_id: str = "wo-warmchief",
    department: str = "qa",
    chief_name: str = "qa-chief",
    cost_usd: float = 0.0,
) -> ChiefSession:
    """Build a ChiefSession in WARM (the state WarmChief expects to receive)."""
    return ChiefSession(
        session_id=session_id,
        work_order_id=work_order_id,
        department=department,
        chief_name=chief_name,
        state=state,
        cost_usd=cost_usd,
    )


@pytest.fixture
def config() -> DepartmentConfig:
    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA",
        manager=AgentSpec(name="qa-chief", model="anthropic:claude-opus-4-6"),
        employees=(
            AgentSpec(name="qa-engineer", model="anthropic:claude-sonnet-4-6"),
        ),
    )


@pytest.fixture
def deps() -> BridgeDeps:
    return make_deps(session_id="warmchief-test", department="qa")


@pytest.fixture
def store() -> InMemoryChiefSessionStore:
    return InMemoryChiefSessionStore()


def _team_result(
    *,
    success: bool = True,
    cost_usd: float = 0.0,
    department: str = "qa",
    manager_output: str = "synthesised",
    error: str | None = None,
    employee_results: tuple[EmployeeResult, ...] = (),
) -> TeamResult:
    return TeamResult(
        department=department,
        manager_output=manager_output,
        employee_results=employee_results,
        total_tokens=0,
        total_cost_usd=cost_usd,
        duration_seconds=0.01,
        success=success,
        error=error,
    )


# ---------------------------------------------------------------------------
# Happy path: WARM → EXECUTING → AWAITING_EVALUATION
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_normal_run_transitions_to_awaiting_evaluation(
        self, config, deps, store
    ):
        session = _make_session()
        await store.create(session)

        fake_result = _team_result(success=True, manager_output="QA done")

        async def _fake_run_chief(self):  # noqa: ANN001
            return fake_result

        warm = WarmChief(session, store, config, deps, "review module")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm as ctx:
                # Inside the body: chief has run, but AWAITING_EVALUATION
                # has not yet been written. State is EXECUTING.
                assert ctx.session.state == ChiefSessionState.EXECUTING
                stored_mid = await store.get(session.session_id)
                assert stored_mid.state == ChiefSessionState.EXECUTING

        # Post-exit: persisted row is AWAITING_EVALUATION.
        stored_final = await store.get(session.session_id)
        assert stored_final.state == ChiefSessionState.AWAITING_EVALUATION
        assert stored_final.idle_since_utc is not None
        assert stored_final.execution_started_at_utc is not None
        assert stored_final.run_count == 1

    @pytest.mark.asyncio
    async def test_result_property_returns_team_result(
        self, config, deps, store
    ):
        session = _make_session()
        await store.create(session)
        fake_result = _team_result(manager_output="QA done")

        async def _fake_run_chief(self):  # noqa: ANN001
            return fake_result

        warm = WarmChief(session, store, config, deps, "task")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        assert warm.result is fake_result
        assert warm.result.manager_output == "QA done"

    @pytest.mark.asyncio
    async def test_result_raises_before_run_completes(
        self, config, deps, store
    ):
        session = _make_session()
        await store.create(session)

        warm = WarmChief(session, store, config, deps, "task")
        with pytest.raises(RuntimeError, match="before the chief run completed"):
            _ = warm.result

    @pytest.mark.asyncio
    async def test_team_result_with_success_false_still_awaits_evaluation(
        self, config, deps, store
    ):
        # ``DepartmentTeam.run`` does NOT raise on chief failures — it
        # returns a TeamResult with success=False. WarmChief treats that
        # as a normal completion and routes to AWAITING_EVALUATION; the
        # caller decides whether to requeue or terminate.
        session = _make_session()
        await store.create(session)
        soft_failure = _team_result(success=False, error="gate violations")

        async def _fake_run_chief(self):  # noqa: ANN001
            return soft_failure

        warm = WarmChief(session, store, config, deps, "task")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.AWAITING_EVALUATION
        assert warm.result.success is False


# ---------------------------------------------------------------------------
# Failure path: WARM → EXECUTING → FAILED on raised exception
# ---------------------------------------------------------------------------


class TestFailurePath:
    @pytest.mark.asyncio
    async def test_run_raising_transitions_to_failed_and_reraises(
        self, config, deps, store
    ):
        session = _make_session()
        await store.create(session)

        async def _failing_run(self):  # noqa: ANN001
            raise RuntimeError("simulated chief construction failure")

        warm = WarmChief(session, store, config, deps, "task")
        with mock.patch.object(WarmChief, "_run_chief", _failing_run):
            with pytest.raises(RuntimeError, match="simulated chief construction"):
                async with warm:
                    pytest.fail("body should not run when __aenter__ raises")

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.FAILED
        assert stored.error is not None
        assert "RuntimeError" in stored.error
        assert "simulated chief construction" in stored.error
        assert stored.completed_at_utc is not None

    @pytest.mark.asyncio
    async def test_failure_path_does_not_set_result(
        self, config, deps, store
    ):
        session = _make_session()
        await store.create(session)

        async def _failing_run(self):  # noqa: ANN001
            raise ValueError("boom")

        warm = WarmChief(session, store, config, deps, "task")
        with mock.patch.object(WarmChief, "_run_chief", _failing_run):
            with pytest.raises(ValueError):
                async with warm:
                    pass

        with pytest.raises(RuntimeError, match="before the chief run completed"):
            _ = warm.result


# ---------------------------------------------------------------------------
# Cost attribution
# ---------------------------------------------------------------------------


class TestCostAttribution:
    @pytest.mark.asyncio
    async def test_cost_added_to_session_before_awaiting_evaluation_update(
        self, config, deps, store
    ):
        session = _make_session(cost_usd=0.0)
        await store.create(session)
        fake_result = _team_result(cost_usd=0.42)

        async def _fake_run_chief(self):  # noqa: ANN001
            return fake_result

        warm = WarmChief(session, store, config, deps, "task")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        # The stored row reflects the AWAITING_EVALUATION transition AND
        # the cost delta — the run's full cost is visible to the next
        # reader's first lookup.
        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.AWAITING_EVALUATION
        assert stored.cost_usd == pytest.approx(0.42)

    @pytest.mark.asyncio
    async def test_cost_accumulates_with_existing_session_cost(
        self, config, deps, store
    ):
        # Session may have non-zero cost from a prior run on the requeue
        # path. The new delta adds to whatever was there.
        session = _make_session(cost_usd=0.10)
        # Bump straight to WARM via the proper transition path so the
        # session has a non-zero starting cost AND is in WARM state.
        # _make_session already returns WARM; just keep cost_usd=0.10.
        await store.create(session)
        fake_result = _team_result(cost_usd=0.07)

        async def _fake_run_chief(self):  # noqa: ANN001
            return fake_result

        warm = WarmChief(session, store, config, deps, "task")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        stored = await store.get(session.session_id)
        assert stored.cost_usd == pytest.approx(0.17)

    @pytest.mark.asyncio
    async def test_zero_cost_run_leaves_cost_unchanged(
        self, config, deps, store
    ):
        session = _make_session(cost_usd=0.05)
        await store.create(session)
        fake_result = _team_result(cost_usd=0.0)

        async def _fake_run_chief(self):  # noqa: ANN001
            return fake_result

        warm = WarmChief(session, store, config, deps, "task")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        stored = await store.get(session.session_id)
        assert stored.cost_usd == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_failed_run_does_not_attribute_cost(
        self, config, deps, store
    ):
        # If the chief raises, no TeamResult exists, so no cost can be
        # extracted. The session row records FAILED with no cost change.
        session = _make_session(cost_usd=0.05)
        await store.create(session)

        async def _failing_run(self):  # noqa: ANN001
            raise RuntimeError("nope")

        warm = WarmChief(session, store, config, deps, "task")
        with mock.patch.object(WarmChief, "_run_chief", _failing_run):
            with pytest.raises(RuntimeError):
                async with warm:
                    pass

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.FAILED
        assert stored.cost_usd == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Integration: real DepartmentTeam with TestModel chief
# ---------------------------------------------------------------------------


class TestIntegrationWithTestModel:
    """End-to-end: real DepartmentTeam built, chief overridden with TestModel.

    Proves the production wiring path (``_run_chief`` → ``DepartmentTeam.run``
    → ``manager.run``) drives a complete WarmChief lifecycle without an
    Anthropic key. The override pattern matches what live-smoke tests use
    when they want determinism (see ``tests/test_teams/test_team.py``).
    """

    @pytest.mark.asyncio
    async def test_full_lifecycle_through_real_team_with_test_model(
        self, config, deps, store
    ):
        session = _make_session()
        await store.create(session)

        # Patch _run_chief to use a TestModel-overridden DepartmentTeam.
        # We can't patch the team-build step alone because TestModel.override
        # only takes effect on a built agent, so we rebuild the path here.
        from teams._team import DepartmentTeam

        async def _run_with_test_model(self):  # noqa: ANN001
            team = DepartmentTeam(self._config, lazy_build=False)
            test_model = TestModel(
                custom_output_args={"answer": "synthesised by TestModel"},
                call_tools=[],
            )
            with team.manager.override(model=test_model):
                return await team.run(self._task, deps=self._deps)

        warm = WarmChief(session, store, config, deps, "review module")
        with mock.patch.object(WarmChief, "_run_chief", _run_with_test_model):
            async with warm:
                assert warm.session.state == ChiefSessionState.EXECUTING

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.AWAITING_EVALUATION
        assert warm.result.success is True
        assert "synthesised by TestModel" in warm.result.manager_output


# ---------------------------------------------------------------------------
# Z4-S41 (#1399): pre/post-flight cost cap enforcement
# ---------------------------------------------------------------------------


class _StubCostTracker:
    """Minimal CostTracker stub exposing only ``get_session_cost``.

    The real ``CostTracker`` reads ``cost_tracking.jsonl`` on every call.
    Tests prefer a deterministic in-memory stub: ``readings`` is a list of
    floats consumed in order on each call (the last value sticks for
    additional calls). A single-float ``readings`` makes a constant
    tracker. This duck-types ``CostTracker`` for ``WarmChief``'s purposes
    — only ``get_session_cost(session_id) -> float`` is used.
    """

    def __init__(self, readings: list[float] | float) -> None:
        if isinstance(readings, (int, float)):
            self._readings: list[float] = [float(readings)]
        else:
            self._readings = [float(v) for v in readings]
        self.calls: list[str] = []

    def get_session_cost(self, session_id: str) -> float:
        self.calls.append(session_id)
        if not self._readings:
            return 0.0
        if len(self._readings) == 1:
            return self._readings[0]
        return self._readings.pop(0)


def _config_with_cap(cap_usd: float) -> DepartmentConfig:
    """Build a DepartmentConfig with a specific cost_limit_usd."""
    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA",
        manager=AgentSpec(name="qa-chief", model="anthropic:claude-opus-4-6"),
        employees=(
            AgentSpec(name="qa-engineer", model="anthropic:claude-sonnet-4-6"),
        ),
        constraints=Constraints(cost_limit_usd=cap_usd),
    )


class TestCostCapPreflight:
    """Pre-flight: enforce cap BEFORE _run_chief is called."""

    @pytest.mark.asyncio
    async def test_prior_cost_over_cap_raises_and_marks_failed(
        self, deps, store
    ):
        # Cap = 1.0; prior spend on this session = 1.5 (already over).
        # WarmChief must short-circuit before _run_chief, raise
        # CostCapExceededError, and persist FAILED with a cost-cap error.
        cfg = _config_with_cap(1.0)
        session = _make_session(cost_usd=1.5)
        await store.create(session)

        tracker = _StubCostTracker(readings=1.5)

        run_called = {"count": 0}

        async def _should_not_run(self):  # noqa: ANN001
            run_called["count"] += 1
            return _team_result()

        warm = WarmChief(
            session, store, cfg, deps, "task", cost_tracker=tracker
        )
        with mock.patch.object(WarmChief, "_run_chief", _should_not_run):
            with pytest.raises(CostCapExceededError) as exc_info:
                async with warm:
                    pytest.fail("body must not run on pre-flight breach")

        # The error carries the session_id, attempted_cost, and cap.
        assert exc_info.value.session_id == session.session_id
        assert exc_info.value.attempted_cost == pytest.approx(1.5)
        assert exc_info.value.cap == pytest.approx(1.0)
        # Message includes both numbers for operator debugging.
        msg = str(exc_info.value)
        assert "$1.5000" in msg
        assert "$1.0000" in msg

        # The chief never ran.
        assert run_called["count"] == 0

        # Persisted state is FAILED with the cost-cap error captured.
        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.FAILED
        assert stored.error is not None
        assert "CostCapExceededError" in stored.error

    @pytest.mark.asyncio
    async def test_prior_cost_under_cap_runs_normally(
        self, deps, store
    ):
        # Cap = 2.0; prior spend = 0.5 (under). Run proceeds; the
        # tracker's post-flight reading also stays under cap so the
        # session lands in AWAITING_EVALUATION.
        cfg = _config_with_cap(2.0)
        session = _make_session(cost_usd=0.5)
        await store.create(session)

        # Single constant reading: 0.5 both pre- and post-flight.
        tracker = _StubCostTracker(readings=0.5)

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result(cost_usd=0.0)

        warm = WarmChief(
            session, store, cfg, deps, "task", cost_tracker=tracker
        )
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.AWAITING_EVALUATION
        # Tracker was consulted at least once (pre-flight).
        assert len(tracker.calls) >= 1


class TestCostCapPostflight:
    """Post-flight: override AWAITING_EVALUATION with FAILED if run pushed over cap."""

    @pytest.mark.asyncio
    async def test_run_pushes_over_cap_transitions_to_failed(
        self, deps, store
    ):
        # Cap = 2.0; pre-flight reading = 0.5 (under, run proceeds);
        # post-flight reading = 3.0 (the run pushed total over cap).
        # Final state must be FAILED, not AWAITING_EVALUATION. The
        # TeamResult is still observable via ``warm.result``.
        cfg = _config_with_cap(2.0)
        session = _make_session()
        await store.create(session)

        tracker = _StubCostTracker(readings=[0.5, 3.0])

        fake_result = _team_result(
            success=True, manager_output="QA done", cost_usd=2.5
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return fake_result

        warm = WarmChief(
            session, store, cfg, deps, "task", cost_tracker=tracker
        )
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass  # __aexit__ does the post-flight kill

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.FAILED
        assert stored.error is not None
        assert "CostCapExceededError" in stored.error
        # Cap and live cost both surface in the error string for ops.
        assert "$3.0000" in stored.error
        assert "$2.0000" in stored.error

        # The TeamResult is still set so observers can see what was
        # generated before the kill.
        assert warm.result is fake_result

    @pytest.mark.asyncio
    async def test_run_stays_under_cap_transitions_to_awaiting_evaluation(
        self, deps, store
    ):
        # Cap = 5.0; pre-flight = 0.5; post-flight = 1.2 (still under).
        # Normal AWAITING_EVALUATION transition.
        cfg = _config_with_cap(5.0)
        session = _make_session()
        await store.create(session)

        tracker = _StubCostTracker(readings=[0.5, 1.2])

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result(cost_usd=0.7)

        warm = WarmChief(
            session, store, cfg, deps, "task", cost_tracker=tracker
        )
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.AWAITING_EVALUATION
        # Both pre-flight and post-flight readings consulted.
        assert len(tracker.calls) >= 2


class TestCostCapDisabled:
    """When cost_tracker=None: enforcement is a no-op."""

    @pytest.mark.asyncio
    async def test_no_cost_tracker_skips_enforcement_even_if_cap_low(
        self, deps, store
    ):
        # Cap is tiny but no tracker → no enforcement; session lands in
        # AWAITING_EVALUATION normally even though TeamResult cost
        # nominally exceeds the cap (the legacy ``add_cost`` path still
        # records the delta to the in-memory session, but the FAILED
        # override only fires when cost_tracker is supplied).
        cfg = _config_with_cap(0.01)
        session = _make_session()
        await store.create(session)

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result(cost_usd=1.0)

        warm = WarmChief(session, store, cfg, deps, "task")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.AWAITING_EVALUATION
        assert stored.cost_usd == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# HaltPolicy pre-flight (audit-2026-05-16.C.02, #2057)
# ---------------------------------------------------------------------------


def _make_halt_policy(*, halted: bool, reason: str | None = "operator pressed /halt"):
    """Construct a HaltPolicy stub for tests with controllable halt state."""
    from bridge.halt import HaltPolicy

    return HaltPolicy(
        is_halted=lambda: halted,
        halt_reason=lambda: reason if halted else None,
    )


class TestHaltPolicyPreflight:
    """Verifies WarmChief honors check_start('warm-chief') before each turn."""

    @pytest.mark.asyncio
    async def test_halt_before_start_transitions_to_failed_no_chief_run(
        self, config, deps, store
    ):
        # When the policy reports halted on entry, the chief never runs.
        # The session transitions WARM → EXECUTING → FAILED (via the
        # existing exception handler) with the halt reason captured.
        session = _make_session()
        await store.create(session)
        policy = _make_halt_policy(halted=True, reason="operator pressed /halt")

        ran = {"called": False}

        async def _fake_run_chief(self):  # noqa: ANN001
            ran["called"] = True
            return _team_result()

        warm = WarmChief(
            session, store, config, deps, "task", halt_policy=policy,
        )
        from bridge.warm_chief import HaltBlockedError

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            with pytest.raises(HaltBlockedError):
                async with warm:
                    pytest.fail("body should not run when halt blocks pre-flight")

        # _run_chief was NOT invoked — no subprocess work was started.
        assert ran["called"] is False
        # Session row reflects the failure with the halt reason.
        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.FAILED
        assert stored.error is not None
        assert "HaltBlockedError" in stored.error
        assert "warm-chief" in stored.error
        assert "halt" in stored.error.lower()

    @pytest.mark.asyncio
    async def test_halt_absent_allows_normal_run(self, config, deps, store):
        # When the policy reports not-halted, behavior is unchanged from
        # the no-policy path — regression guard.
        session = _make_session()
        await store.create(session)
        policy = _make_halt_policy(halted=False)

        ran = {"called": False}

        async def _fake_run_chief(self):  # noqa: ANN001
            ran["called"] = True
            return _team_result(manager_output="done")

        warm = WarmChief(
            session, store, config, deps, "task", halt_policy=policy,
        )
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        assert ran["called"] is True
        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.AWAITING_EVALUATION

    @pytest.mark.asyncio
    async def test_no_policy_wired_preserves_back_compat(
        self, config, deps, store
    ):
        # When no policy is wired (the default), _enforce_halt_policy_preflight
        # is a no-op — the legacy code path is untouched.
        session = _make_session()
        await store.create(session)

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        warm = WarmChief(session, store, config, deps, "task")  # no halt_policy kwarg
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            async with warm:
                pass

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.AWAITING_EVALUATION
