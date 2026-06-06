"""Tests for RecursiveDecomposer (Sprint 07.02).

Concept-only port of TinyAGI/fractals (MIT). These tests cover the
heuristic classifier, the LLM-injected decomposer, and the recursive
driver — all offline. No real LLM calls.
"""

from __future__ import annotations

import logging

import pytest

from bridge.decomposer import Decomposer
from bridge.recursive_decomposer import (
    DecomposeCallResult,
    RecursiveDecomposer,
    make_classification_only_decomposer,
)
from bridge.work_order import BatchStrategy, Decomposition, WorkOrder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wo(intent: str) -> WorkOrder:
    return WorkOrder.create(intent=intent, skill="x", project="p")


# ---------------------------------------------------------------------------
# classify() — heuristic-only, no LLM
# ---------------------------------------------------------------------------


def test_classify_short_single_tool_intent_is_atomic() -> None:
    """Short, single-tool task language → atomic."""
    dec = RecursiveDecomposer()
    wo = _make_wo("read the README")
    assert dec.classify(wo) == "atomic"


def test_classify_empty_intent_is_atomic_no_llm_call() -> None:
    """Empty/whitespace WO short-circuits before any LLM call."""

    def _boom(_wo: WorkOrder) -> DecomposeCallResult:
        raise AssertionError("decompose must not be called for empty intents")

    dec = RecursiveDecomposer(decompose_call=_boom)
    assert dec.classify(_make_wo("")) == "atomic"
    assert dec.classify(_make_wo("    \n  \t ")) == "atomic"


def test_classify_long_intent_is_composite() -> None:
    """Intents over the char-limit are presumed multi-step."""
    dec = RecursiveDecomposer()
    long_text = "do something " * 50  # > 200 chars
    assert dec.classify(_make_wo(long_text)) == "composite"


@pytest.mark.parametrize(
    "intent",
    [
        "First write the parser, then run the linter",
        "Write the test and then implement and then deploy",
        "Step 1 build, step 2 test, step 3 ship",
        "Build the API followed by the migration",
        "Set up auth, after that wire the routes",
    ],
)
def test_classify_list_like_intents_are_composite(intent: str) -> None:
    """Sequential task language flips to composite."""
    dec = RecursiveDecomposer()
    assert dec.classify(_make_wo(intent)) == "composite"


def test_classify_multiple_ands_in_short_intent_is_composite() -> None:
    """Two or more ' and ' hits in a short intent signal multi-step."""
    dec = RecursiveDecomposer()
    intent = "lint and test and deploy"
    assert dec.classify(_make_wo(intent)) == "composite"


# ---------------------------------------------------------------------------
# decompose() — LLM-injected
# ---------------------------------------------------------------------------


def test_decompose_returns_decomposition_with_children() -> None:
    """Injected callable's intents become child WorkOrders."""

    def fake(_wo: WorkOrder) -> DecomposeCallResult:
        return DecomposeCallResult(
            children_intents=("scrape", "parse"),
            strategy=BatchStrategy.PARALLEL_FANOUT,
            cost_usd=0.001,
        )

    dec = RecursiveDecomposer(decompose_call=fake)
    parent = _make_wo("scrape and parse data")
    plan = dec.decompose(parent)

    assert isinstance(plan, Decomposition)
    assert plan.strategy == BatchStrategy.PARALLEL_FANOUT
    assert plan.atomic is False
    assert len(plan.children) == 2
    assert {c.intent for c in plan.children} == {"scrape", "parse"}
    # Children inherit skill/project + point back to parent.
    for child in plan.children:
        assert child.skill == "x"
        assert child.project == "p"
        assert child.parent_id == parent.id


def test_decompose_without_callable_raises() -> None:
    """Classification-only decomposer can't decompose."""
    dec = make_classification_only_decomposer()
    with pytest.raises(RuntimeError, match="without an injected"):
        dec.decompose(_make_wo("anything"))


def test_decompose_cost_cap_enforced() -> None:
    """Cost over cap raises RuntimeError before children are constructed."""

    def expensive(_wo: WorkOrder) -> DecomposeCallResult:
        return DecomposeCallResult(
            children_intents=("a", "b"),
            strategy=BatchStrategy.SEQUENTIAL,
            cost_usd=0.10,  # 5x default cap
        )

    dec = RecursiveDecomposer(decompose_call=expensive, cost_cap_usd=0.02)
    with pytest.raises(RuntimeError, match="exceeds cap"):
        dec.decompose(_make_wo("compound task"))


def test_decompose_caps_fanout_at_eight_children() -> None:
    """Hallucinated 50-child split is trimmed to 8."""

    def too_many(_wo: WorkOrder) -> DecomposeCallResult:
        return DecomposeCallResult(
            children_intents=tuple(f"child-{i}" for i in range(50)),
            strategy=BatchStrategy.PARALLEL_FANOUT,
        )

    dec = RecursiveDecomposer(decompose_call=too_many)
    plan = dec.decompose(_make_wo("big composite task"))
    assert len(plan.children) == 8


def test_decompose_empty_intents_collapses_to_atomic() -> None:
    """LLM gave up — return an atomic Decomposition with no children."""

    def empty(_wo: WorkOrder) -> DecomposeCallResult:
        return DecomposeCallResult(
            children_intents=("", "   "),  # all whitespace
            strategy=BatchStrategy.SEQUENTIAL,
        )

    dec = RecursiveDecomposer(decompose_call=empty)
    plan = dec.decompose(_make_wo("ambiguous task"))
    assert plan.atomic is True
    assert plan.children == ()


# ---------------------------------------------------------------------------
# decompose_recursive() — full driver
# ---------------------------------------------------------------------------


def test_decompose_recursive_atomic_wo_returns_atomic_leaf() -> None:
    """Atomic root yields a leaf-marked Decomposition."""
    dec = RecursiveDecomposer()
    wo = _make_wo("read README")
    result = dec.decompose_recursive(wo)
    assert result.decomposition is not None
    assert result.decomposition.atomic is True
    assert result.decomposition.children == ()
    # Original is unchanged (immutable).
    assert wo.decomposition is None


def test_decompose_recursive_two_child_split_recurses() -> None:
    """Composite root splits; each child is then classified atomic."""

    def fake(_wo: WorkOrder) -> DecomposeCallResult:
        return DecomposeCallResult(
            children_intents=("scrape", "parse"),
            strategy=BatchStrategy.PARALLEL_FANOUT,
            cost_usd=0.001,
        )

    dec = RecursiveDecomposer(decompose_call=fake)
    root = _make_wo("First scrape, then parse and then store")
    result = dec.decompose_recursive(root)

    assert result.decomposition is not None
    assert result.decomposition.strategy == BatchStrategy.PARALLEL_FANOUT
    assert len(result.decomposition.children) == 2
    # Each child got its own Decomposition tagged atomic (short intents).
    for child in result.decomposition.children:
        assert child.decomposition is not None
        assert child.decomposition.atomic is True


def test_decompose_recursive_halts_at_max_depth(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LLM that always splits is forced atomic at max_depth."""

    def always_split(wo: WorkOrder) -> DecomposeCallResult:
        # Always returns a 2-child composite to force runaway recursion.
        return DecomposeCallResult(
            children_intents=(
                f"first then second of {wo.intent}",
                f"step 1 of {wo.intent}",
            ),
            strategy=BatchStrategy.SEQUENTIAL,
            cost_usd=0.0005,
        )

    dec = RecursiveDecomposer(decompose_call=always_split)
    root = _make_wo("First do A then do B")  # composite by classifier

    with caplog.at_level(logging.WARNING, logger="bridge.recursive_decomposer"):
        result = dec.decompose_recursive(root, max_depth=2)

    # Walk the tree; deepest nodes must be atomic.
    def deepest_atomic(wo: WorkOrder, depth: int = 0) -> tuple[int, bool]:
        decomp = wo.decomposition
        assert decomp is not None
        if decomp.atomic or not decomp.children:
            return depth, decomp.atomic
        max_depth = depth
        all_atomic = True
        for child in decomp.children:
            d, atomic = deepest_atomic(child, depth + 1)
            max_depth = max(max_depth, d)
            all_atomic = all_atomic and atomic
        return max_depth, all_atomic

    deepest, all_leaves_atomic = deepest_atomic(result)
    assert deepest == 2  # capped
    assert all_leaves_atomic is True
    # At least one warning was logged when forcing atomic at the cap.
    assert any(
        "max_depth" in record.getMessage() for record in caplog.records
    )


def test_decompose_recursive_idempotent_on_already_decomposed_wo() -> None:
    """A WO that already carries a Decomposition is returned unchanged."""

    call_count = {"n": 0}

    def fake(_wo: WorkOrder) -> DecomposeCallResult:
        call_count["n"] += 1
        return DecomposeCallResult(
            children_intents=("a",),
            strategy=BatchStrategy.SEQUENTIAL,
            cost_usd=0.001,
        )

    dec = RecursiveDecomposer(decompose_call=fake)
    pre = _make_wo("first then second").with_decomposition(
        Decomposition(strategy=BatchStrategy.RACE, atomic=True)
    )
    result = dec.decompose_recursive(pre)
    assert result is pre  # exact identity — no rebuild
    assert call_count["n"] == 0


def test_decompose_recursive_empty_intent_no_llm_call() -> None:
    """Whitespace WO returns atomic without invoking the LLM."""

    def _boom(_wo: WorkOrder) -> DecomposeCallResult:
        raise AssertionError("decompose must not be called for empty intents")

    dec = RecursiveDecomposer(decompose_call=_boom)
    result = dec.decompose_recursive(_make_wo("   "))
    assert result.decomposition is not None
    assert result.decomposition.atomic is True


def test_decompose_recursive_respects_cost_cap() -> None:
    """Per-call cost cap propagates: an over-cap call aborts the whole tree."""

    def expensive(_wo: WorkOrder) -> DecomposeCallResult:
        return DecomposeCallResult(
            children_intents=("a", "b"),
            strategy=BatchStrategy.SEQUENTIAL,
            cost_usd=0.50,
        )

    dec = RecursiveDecomposer(decompose_call=expensive, cost_cap_usd=0.02)
    with pytest.raises(RuntimeError, match="exceeds cap"):
        dec.decompose_recursive(_make_wo("First do A then do B"))


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_recursive_decomposer_satisfies_decomposer_protocol() -> None:
    """RecursiveDecomposer ducks-types as the 07.01 Decomposer Protocol."""
    dec: Decomposer = RecursiveDecomposer()
    assert isinstance(dec, Decomposer)


# ---------------------------------------------------------------------------
# Sprint D1.6 -- prompt assembly, response parser, haiku adapter, complexity
# ---------------------------------------------------------------------------


from bridge.recursive_decomposer import (
    _build_decomposition_prompt,
    _parse_decomposition_response,
    heuristic_complexity_score,
    make_haiku_decomposer,
)


def test_prompt_assembly_includes_parent_fields() -> None:
    wo = _make_wo("Build the parser and run the linter and then deploy")
    prompt = _build_decomposition_prompt(wo)
    assert wo.intent in prompt
    assert "Complexity:" in prompt
    assert "Decompose." in prompt
    assert "JSON" in prompt


def test_response_parser_rejects_complexity_violation() -> None:
    import json
    payload = json.dumps([{"title": "child", "estimated_complexity": 5}])
    intents, strategy = _parse_decomposition_response(payload, parent_complexity=5)
    assert intents == []
    assert strategy == BatchStrategy.SEQUENTIAL


def test_response_parser_rejects_total_exceeding_parent() -> None:
    import json
    payload = json.dumps([{"title": "a", "estimated_complexity": 4}, {"title": "b", "estimated_complexity": 4}])
    intents, strategy = _parse_decomposition_response(payload, parent_complexity=7)
    assert intents == []
    assert strategy == BatchStrategy.SEQUENTIAL


def test_response_parser_falls_back_on_invalid_json() -> None:
    intents, strategy = _parse_decomposition_response("{not valid json", parent_complexity=7)
    assert intents == []
    assert strategy == BatchStrategy.SEQUENTIAL


def test_response_parser_valid_decomposition_returns_intents() -> None:
    import json
    payload = json.dumps([{"title": "scrape data", "estimated_complexity": 3}, {"title": "parse output", "estimated_complexity": 3}])
    intents, strategy = _parse_decomposition_response(payload, parent_complexity=7)
    assert intents == ["scrape data", "parse output"]
    assert strategy == BatchStrategy.PARALLEL_FANOUT


def test_response_parser_falls_back_on_empty_response() -> None:
    intents, strategy = _parse_decomposition_response("", parent_complexity=7)
    assert intents == []
    assert strategy == BatchStrategy.SEQUENTIAL


def test_heuristic_complexity_score_short_intent() -> None:
    wo = _make_wo("read the README")
    assert heuristic_complexity_score(wo) == 1


def test_heuristic_complexity_score_medium_intent() -> None:
    wo = _make_wo("x" * 350)
    assert heuristic_complexity_score(wo) == 5


def test_heuristic_complexity_score_caps_at_10() -> None:
    wo = _make_wo("x" * 9999)
    assert heuristic_complexity_score(wo) == 10


def test_heuristic_complexity_score_empty_intent() -> None:
    wo = _make_wo("")
    assert heuristic_complexity_score(wo) == 1


def test_make_haiku_decomposer_returns_callable() -> None:
    from bridge.recursive_decomposer import DecomposeCallResult
    import json
    children_payload = json.dumps([
        {"title": "step A", "estimated_complexity": 2},
        {"title": "step B", "estimated_complexity": 2},
    ])
    class FakeRunner:
        async def invoke_haiku_for_decomposition(self, prompt):
            class Result:
                response_text = children_payload
                cost_usd = 0.001
            return Result()
    decompose_fn = make_haiku_decomposer(FakeRunner())
    wo = _make_wo("x" * 350)
    result = decompose_fn(wo)
    assert isinstance(result, DecomposeCallResult)
    assert len(result.children_intents) == 2
    assert result.cost_usd == 0.001


def test_make_haiku_decomposer_falls_back_on_invoke_error() -> None:
    from bridge.recursive_decomposer import DecomposeCallResult
    class FailRunner:
        async def invoke_haiku_for_decomposition(self, prompt):
            raise RuntimeError("network error")
    decompose_fn = make_haiku_decomposer(FailRunner())
    wo = _make_wo("Build and test and deploy")
    result = decompose_fn(wo)
    assert isinstance(result, DecomposeCallResult)
    assert result.children_intents == ()
    assert result.cost_usd == 0.0
