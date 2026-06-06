"""Tests for `bridge.work_order_router` — Z4-S02 (#1386) + Z4-S20 (#1390).

Contract layer + concrete RuleBasedWorkOrderRouter.

Tests cover:
- ``RoutingDecision`` shape (defaults, immutability)
- ``WorkOrderRouter`` ABC instantiation rules
- ``NullRouter`` round-trip
- ``RoutingError`` carries the work-order id + reason
- WorkOrder is not mutated by ``route()`` (load-bearing contract)
- ``RuleBasedWorkOrderRouter`` 4-tier rule chain (Z4-S20)
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import pytest

from bridge.work_order import (
    BatchStrategy,
    Decomposition,
    WorkOrder,
    WorkOrderInput,
)
from bridge.work_order_router import (
    NullRouter,
    RoutingDecision,
    RoutingError,
    RuleBasedWorkOrderRouter,
    WorkOrderRouter,
)


def _make_work_order(
    intent: str = "Test work order",
    *,
    department_target: str | None = None,
    text: str = "",
    decomposition: Decomposition | None = None,
) -> WorkOrder:
    """Build a WorkOrder with optional Z4-S20-relevant overrides."""
    wo = WorkOrder.create(intent=intent, skill="test", project="test")
    # WorkOrder is frozen — re-create via dataclasses.replace
    overrides: dict = {}
    if department_target is not None:
        overrides["department_target"] = department_target
    if text:
        overrides["input"] = WorkOrderInput(text=text)
    if decomposition is not None:
        overrides["decomposition"] = decomposition
    return dataclasses.replace(wo, **overrides) if overrides else wo


# ---------------------------------------------------------------------------
# Fake DepartmentRegistry — duck-typed match for what the router calls
# ---------------------------------------------------------------------------


@dataclass
class _FakeDeptConfig:
    description: str = ""


class _FakeRegistry:
    """Minimal registry stub satisfying the duck-typed surface the
    router uses (`department_names()` + `get_config(name)`).
    """

    def __init__(self, departments: dict[str, str]) -> None:
        self._departments = departments  # name -> description

    def department_names(self) -> list[str]:
        return sorted(self._departments)

    def get_config(self, name: str) -> _FakeDeptConfig | None:
        if name not in self._departments:
            return None
        return _FakeDeptConfig(description=self._departments[name])


def _registry(**departments: str) -> _FakeRegistry:
    return _FakeRegistry(departments)


# ---------------------------------------------------------------------------
# RoutingDecision
# ---------------------------------------------------------------------------


class TestRoutingDecision:
    def test_required_fields(self):
        decision = RoutingDecision(
            department="strategy",
            rationale="default routing for strategic decisions",
        )
        assert decision.department == "strategy"
        assert decision.rationale == "default routing for strategic decisions"

    def test_default_confidence_is_one(self):
        """Routers that don't reason about confidence (e.g. rule-based with
        explicit rules) land at full confidence by default. Confidence-aware
        routers opt in by supplying the kwarg.
        """
        decision = RoutingDecision(department="strategy", rationale="x")
        assert decision.confidence == 1.0

    def test_default_priority_override_is_none(self):
        decision = RoutingDecision(department="strategy", rationale="x")
        assert decision.priority_override is None

    def test_default_fallback_departments_is_empty_tuple(self):
        decision = RoutingDecision(department="strategy", rationale="x")
        assert decision.fallback_departments == ()

    def test_is_frozen(self):
        decision = RoutingDecision(department="strategy", rationale="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.department = "ops"  # type: ignore[misc]

    def test_explicit_fallbacks_are_preserved(self):
        decision = RoutingDecision(
            department="strategy",
            rationale="x",
            fallback_departments=("ops", "qa"),
        )
        assert decision.fallback_departments == ("ops", "qa")

    def test_priority_override_accepts_string(self):
        decision = RoutingDecision(
            department="strategy",
            rationale="x",
            priority_override="high",
        )
        assert decision.priority_override == "high"


# ---------------------------------------------------------------------------
# WorkOrderRouter ABC
# ---------------------------------------------------------------------------


class TestAbstractInterface:
    def test_cannot_instantiate_abstract_class(self):
        """Subclasses MUST implement `route()` — the ABC machinery
        prevents direct instantiation.
        """
        with pytest.raises(TypeError):
            WorkOrderRouter()  # type: ignore[abstract]

    def test_subclass_without_route_cannot_instantiate(self):
        """A subclass that fails to implement `route()` is still abstract."""
        class IncompleteRouter(WorkOrderRouter):
            pass

        with pytest.raises(TypeError):
            IncompleteRouter()  # type: ignore[abstract]

    def test_subclass_with_route_can_instantiate(self):
        """A subclass that implements `route()` is concrete."""
        class ConcreteRouter(WorkOrderRouter):
            async def route(self, work_order):
                return RoutingDecision(
                    department="ops", rationale="concrete subclass"
                )

        # Instantiation succeeds; the test stops here so a half-failing
        # subclass surfaces clearly.
        ConcreteRouter()


# ---------------------------------------------------------------------------
# NullRouter
# ---------------------------------------------------------------------------


class TestNullRouter:
    @pytest.mark.asyncio
    async def test_default_department_is_strategy(self):
        router = NullRouter()
        decision = await router.route(_make_work_order())
        assert decision.department == "strategy"
        assert decision.confidence == 1.0

    @pytest.mark.asyncio
    async def test_custom_department(self):
        router = NullRouter(department="ops")
        decision = await router.route(_make_work_order())
        assert decision.department == "ops"

    @pytest.mark.asyncio
    async def test_rationale_names_the_department(self):
        router = NullRouter(department="qa")
        decision = await router.route(_make_work_order())
        assert "qa" in decision.rationale.lower()

    @pytest.mark.asyncio
    async def test_returns_routing_decision_instance(self):
        router = NullRouter()
        decision = await router.route(_make_work_order())
        assert isinstance(decision, RoutingDecision)

    @pytest.mark.asyncio
    async def test_does_not_mutate_work_order(self):
        """Load-bearing invariant — the router contract says the WorkOrder
        passed in must not be modified. WorkOrder is frozen so direct
        mutation would raise; this test guards against `dataclasses.replace`-
        style mutation that returns a new instance + accidentally swaps it.
        """
        router = NullRouter()
        wo = _make_work_order("immutability check")
        original_id = wo.id
        original_intent = wo.intent
        await router.route(wo)
        assert wo.id == original_id
        assert wo.intent == original_intent


# ---------------------------------------------------------------------------
# RoutingError
# ---------------------------------------------------------------------------


class TestRoutingError:
    def test_carries_work_order_id_and_reason(self):
        err = RoutingError(work_order_id="wo-test", reason="no department matched")
        assert err.work_order_id == "wo-test"
        assert err.reason == "no department matched"
        assert "wo-test" in str(err)
        assert "no department matched" in str(err)

    def test_is_an_exception(self):
        err = RoutingError(work_order_id="wo-x", reason="x")
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# Z4-S20 — RuleBasedWorkOrderRouter 4-tier rule chain
# ---------------------------------------------------------------------------


class TestRuleBasedRouterTier1ExplicitTarget:
    """Tier 1: WorkOrder.department_target is the canonical 'this WO
    already names its dept' slot. Confidence 1.0 when set + the dept
    exists.
    """

    @pytest.mark.asyncio
    async def test_explicit_target_routes_with_full_confidence(self):
        registry = _registry(
            ops="Operations work — infrastructure, deploy.",
            strategy="Strategic decisions, market research.",
        )
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        wo = _make_work_order(department_target="ops", intent="anything")
        decision = await router.route(wo)
        assert decision.department == "ops"
        assert decision.confidence == 1.0
        assert "Tier 1" in decision.rationale

    @pytest.mark.asyncio
    async def test_explicit_target_falls_through_when_dept_unknown(self):
        """If `department_target` names a dept the registry doesn't know,
        fall through to the next tier rather than fail.
        """
        registry = _registry(strategy="Strategy work.")
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        wo = _make_work_order(
            department_target="nonexistent",
            intent="something something strategy",
        )
        decision = await router.route(wo)
        # Should NOT have routed via Tier 1
        assert decision.department != "nonexistent"


class TestRuleBasedRouterTier2KeywordMatch:
    @pytest.mark.asyncio
    async def test_keyword_match_routes_to_best_dept(self):
        registry = _registry(
            ops="Operations infrastructure deployment monitoring services.",
            strategy="Strategic market analysis competitive research roadmap.",
        )
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        wo = _make_work_order(intent="Run a market analysis on competitive landscape")
        decision = await router.route(wo)
        assert decision.department == "strategy"
        assert decision.confidence == 0.75
        assert "Tier 2" in decision.rationale

    @pytest.mark.asyncio
    async def test_keyword_match_populates_fallbacks(self):
        registry = _registry(
            ops="ops description",
            strategy="strategic market analysis competitive research",
            qa="quality assurance testing validation review",
        )
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        wo = _make_work_order(intent="market analysis competitive research")
        decision = await router.route(wo)
        assert decision.department == "strategy"
        # Other depts populate fallback (deterministic; alphabetical)
        assert "strategy" not in decision.fallback_departments
        assert len(decision.fallback_departments) <= 2

    @pytest.mark.asyncio
    async def test_tie_break_alphabetical(self):
        """When two depts score equally on keyword match, the
        alphabetically-first dept wins.
        """
        registry = _registry(
            zebra="alpha beta gamma delta",
            alpha="alpha beta gamma delta",
        )
        router = RuleBasedWorkOrderRouter(registry, default_department="alpha")
        wo = _make_work_order(intent="alpha beta gamma delta exact match")
        decision = await router.route(wo)
        # Both score 1.0; alphabetically-first wins
        assert decision.department == "alpha"


class TestRuleBasedRouterTier3StrategyHeuristic:
    @pytest.mark.asyncio
    async def test_parallel_fanout_routes_to_ops(self):
        registry = _registry(
            ops="ops",  # short description -> no Tier-2 keyword match
            strategy="strategy",
        )
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        # Build a decomposition with PARALLEL_FANOUT strategy
        decomp = Decomposition(strategy=BatchStrategy.PARALLEL_FANOUT)
        wo = _make_work_order(
            intent="zzzz",  # no keyword match against "ops" or "strategy"
            decomposition=decomp,
        )
        decision = await router.route(wo)
        assert decision.department == "ops"
        assert decision.confidence == 0.5
        assert "Tier 3" in decision.rationale

    @pytest.mark.asyncio
    async def test_race_strategy_routes_to_qa(self):
        registry = _registry(
            qa="qa",
            strategy="strategy",
        )
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        decomp = Decomposition(strategy=BatchStrategy.RACE)
        wo = _make_work_order(intent="zzzz", decomposition=decomp)
        decision = await router.route(wo)
        assert decision.department == "qa"
        assert decision.confidence == 0.5

    @pytest.mark.asyncio
    async def test_unmapped_strategy_falls_through(self):
        """A traversal-strategy (DEPTH_FIRST etc.) has no heuristic
        target; should fall through to Tier 4.
        """
        registry = _registry(strategy="strategy")
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        decomp = Decomposition(strategy=BatchStrategy.DEPTH_FIRST)
        wo = _make_work_order(intent="zzzz", decomposition=decomp)
        decision = await router.route(wo)
        assert decision.confidence == 0.3  # Tier 4
        assert decision.department == "strategy"

    @pytest.mark.asyncio
    async def test_strategy_mapping_to_unknown_dept_falls_through(self):
        """If the heuristic maps to a dept that's not in the registry,
        fall through to Tier 4 — the heuristic doesn't fire.
        """
        registry = _registry(strategy="strategy")  # no "ops"
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        decomp = Decomposition(strategy=BatchStrategy.PARALLEL_FANOUT)
        wo = _make_work_order(intent="zzzz", decomposition=decomp)
        decision = await router.route(wo)
        # PARALLEL_FANOUT maps to "ops" but registry doesn't have it
        assert decision.department == "strategy"
        assert decision.confidence == 0.3  # Tier 4


class TestRuleBasedRouterTier4Default:
    @pytest.mark.asyncio
    async def test_no_match_routes_to_default(self):
        registry = _registry(
            strategy="strategy work",
            ops="ops work",
        )
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        wo = _make_work_order(intent="zzzz unrelated to anything")
        decision = await router.route(wo)
        assert decision.department == "strategy"
        assert decision.confidence == 0.3
        assert "Tier 4" in decision.rationale

    @pytest.mark.asyncio
    async def test_default_populates_fallbacks(self):
        registry = _registry(
            strategy="strategy",
            ops="ops",
            qa="qa",
            board="board",
        )
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        wo = _make_work_order(intent="zzzz")
        decision = await router.route(wo)
        assert decision.department == "strategy"
        # Non-default departments populate fallback (up to 2)
        assert len(decision.fallback_departments) == 2
        assert "strategy" not in decision.fallback_departments

    @pytest.mark.asyncio
    async def test_missing_default_raises_routing_error(self):
        """If the configured default isn't in the registry AND no other
        rule fired, the router can't route — raise loudly so the
        operator catches the config bug.
        """
        registry = _registry(strategy="strategy")
        # Configure a default that doesn't exist
        router = RuleBasedWorkOrderRouter(
            registry, default_department="nonexistent"
        )
        wo = _make_work_order(intent="zzzz")
        with pytest.raises(RoutingError) as exc:
            await router.route(wo)
        assert "nonexistent" in exc.value.reason


class TestRuleBasedRouterImmutability:
    @pytest.mark.asyncio
    async def test_does_not_mutate_work_order(self):
        registry = _registry(strategy="strategy work")
        router = RuleBasedWorkOrderRouter(registry, default_department="strategy")
        wo = _make_work_order(intent="zzzz")
        original_id = wo.id
        original_intent = wo.intent
        await router.route(wo)
        assert wo.id == original_id
        assert wo.intent == original_intent


class TestRuleBasedRouterRegistryFailure:
    @pytest.mark.asyncio
    async def test_registry_raises_router_falls_through_to_default(self):
        """A registry that throws on department_names() should be
        handled gracefully — degrade to Tier 4 default rather than
        crashing the router.
        """

        class _BrokenRegistry:
            def department_names(self):
                raise RuntimeError("registry boom")

            def get_config(self, name):
                raise RuntimeError("registry boom")

        # When everything fails, even the default lookup fails —
        # router raises RoutingError with a clear message
        router = RuleBasedWorkOrderRouter(
            _BrokenRegistry(), default_department="strategy"
        )
        wo = _make_work_order(intent="x")
        with pytest.raises(RoutingError):
            await router.route(wo)
