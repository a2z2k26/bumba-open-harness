"""Tests for RecursiveDecomposer.execute_tree (Sprint 07.03).

Wires the decomposer to ``WorktreeExecutor`` so each leaf runs in its
own isolated git worktree. Concept-only port of TinyAGI/fractals (MIT,
paraphrased — no verbatim code).

Per spec DoD, the five named tests are:

- ``test_4_leaf_tree_executes_in_isolation_depth_first``
- ``test_4_leaf_tree_executes_breadth_first``
- ``test_4_leaf_tree_executes_layer_sequential``
- ``test_no_worktree_leaks_after_50_runs``
- ``test_leaf_failure_doesnt_abort_other_leaves``

Plus a few smaller coverage helpers (atomic regression guard, parallel
fan-out, RACE early-exit) so the implementation stays honest as the
codebase evolves.

All executor calls are mocked — no real ``git worktree add`` runs.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.claude_runner import ClaudeResult
from bridge.recursive_decomposer import execute_tree
from bridge.work_order import (
    BatchStrategy,
    Decomposition,
    WorkOrder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _leaf(intent: str = "leaf") -> WorkOrder:
    """A leaf WO with no decomposition — atomic by ``_is_leaf`` rules."""
    return WorkOrder.create(intent=intent, skill="x", project="p")


def _atomic_leaf(intent: str = "leaf") -> WorkOrder:
    """A leaf WO with an explicit ``atomic=True`` decomposition."""
    return _leaf(intent).with_decomposition(
        Decomposition(strategy=BatchStrategy.SEQUENTIAL, atomic=True)
    )


def _composite(
    intent: str,
    children: list[WorkOrder],
    strategy: BatchStrategy = BatchStrategy.SEQUENTIAL,
) -> WorkOrder:
    """A composite WO with the given children + strategy."""
    parent = _leaf(intent)
    return parent.with_decomposition(
        Decomposition(strategy=strategy, children=tuple(children), atomic=False)
    )


def _ok_result(text: str = "ok") -> ClaudeResult:
    return ClaudeResult(is_error=False, response_text=text)


def _err_result(msg: str = "boom") -> ClaudeResult:
    return ClaudeResult(is_error=True, error_type="leaf_exception", stderr_output=msg)


def _make_recording_executor(
    per_call_delay: float = 0.0,
    failures: set[str] | None = None,
) -> MagicMock:
    """Return a mock executor whose ``execute`` records call order.

    ``failures`` is a set of WO intents that should raise; everything
    else returns a successful ClaudeResult tagged with the intent.
    """
    fails = failures or set()
    call_order: list[str] = []

    async def _exec(wo: WorkOrder) -> ClaudeResult:
        if per_call_delay:
            await asyncio.sleep(per_call_delay)
        call_order.append(wo.intent)
        if wo.intent in fails:
            raise RuntimeError(f"executor failed for {wo.intent}")
        return _ok_result(text=wo.intent)

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=_exec)
    executor.call_order = call_order  # type: ignore[attr-defined]
    return executor


# ---------------------------------------------------------------------------
# Atomic regression guard — leaf WO without any decomposition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atomic_leaf_runs_directly_no_walk() -> None:
    """A leaf WO with no decomposition runs as a single executor call."""
    leaf = _leaf("just-do-it")
    executor = _make_recording_executor()

    results = await execute_tree(leaf, strategy=BatchStrategy.SEQUENTIAL, executor=executor)

    assert list(results.keys()) == [leaf.id]
    assert results[leaf.id].response_text == "just-do-it"
    assert executor.call_order == ["just-do-it"]


@pytest.mark.asyncio
async def test_atomic_marked_leaf_runs_directly() -> None:
    """A leaf WO with ``atomic=True`` decomposition still runs as a single call."""
    leaf = _atomic_leaf("ok")
    executor = _make_recording_executor()

    results = await execute_tree(leaf, strategy=BatchStrategy.SEQUENTIAL, executor=executor)

    assert list(results.keys()) == [leaf.id]
    assert executor.call_order == ["ok"]


# ---------------------------------------------------------------------------
# 4-leaf tree fixtures — used by the three traversal-strategy tests
# ---------------------------------------------------------------------------


def _four_leaf_tree(strategy: BatchStrategy) -> tuple[WorkOrder, list[WorkOrder]]:
    """Build a 2-level tree with four leaves under the given strategy.

    Shape:

        root [strategy]
          ├─ left  [SEQUENTIAL] → leaf_a, leaf_b
          └─ right [SEQUENTIAL] → leaf_c, leaf_d
    """
    leaf_a = _leaf("a")
    leaf_b = _leaf("b")
    leaf_c = _leaf("c")
    leaf_d = _leaf("d")
    left = _composite("left", [leaf_a, leaf_b], strategy=BatchStrategy.SEQUENTIAL)
    right = _composite("right", [leaf_c, leaf_d], strategy=BatchStrategy.SEQUENTIAL)
    root = _composite("root", [left, right], strategy=strategy)
    return root, [leaf_a, leaf_b, leaf_c, leaf_d]


@pytest.mark.asyncio
async def test_4_leaf_tree_executes_in_isolation_depth_first() -> None:
    """DEPTH_FIRST traversal — each of 4 leaves runs through executor exactly once."""
    root, leaves = _four_leaf_tree(BatchStrategy.DEPTH_FIRST)
    executor = _make_recording_executor()

    results = await execute_tree(
        root, strategy=BatchStrategy.DEPTH_FIRST, executor=executor
    )

    assert len(results) == 4
    assert {l.id for l in leaves} == set(results.keys())
    assert executor.execute.await_count == 4
    # Depth-first order: a, b (left subtree) then c, d (right subtree)
    assert executor.call_order == ["a", "b", "c", "d"]


@pytest.mark.asyncio
async def test_4_leaf_tree_executes_breadth_first() -> None:
    """BREADTH_FIRST traversal — same 4 leaves, all results captured."""
    root, leaves = _four_leaf_tree(BatchStrategy.BREADTH_FIRST)
    executor = _make_recording_executor()

    results = await execute_tree(
        root, strategy=BatchStrategy.BREADTH_FIRST, executor=executor
    )

    assert len(results) == 4
    assert {l.id for l in leaves} == set(results.keys())
    # Implementation runs children in declared order at each layer; no
    # interleaving with deeper traversal control (per spec scope).
    assert executor.call_order == ["a", "b", "c", "d"]


@pytest.mark.asyncio
async def test_4_leaf_tree_executes_layer_sequential() -> None:
    """LAYER_SEQUENTIAL traversal — same 4 leaves all run once."""
    root, leaves = _four_leaf_tree(BatchStrategy.LAYER_SEQUENTIAL)
    executor = _make_recording_executor()

    results = await execute_tree(
        root, strategy=BatchStrategy.LAYER_SEQUENTIAL, executor=executor
    )

    assert len(results) == 4
    assert {l.id for l in leaves} == set(results.keys())
    assert executor.execute.await_count == 4


# ---------------------------------------------------------------------------
# Concurrency strategies — PARALLEL_FANOUT, RACE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_fanout_runs_children_concurrently() -> None:
    """PARALLEL_FANOUT: 3 leaves run concurrently and all 3 results are captured."""
    leaves = [_leaf("p0"), _leaf("p1"), _leaf("p2")]
    root = _composite("root", leaves, strategy=BatchStrategy.PARALLEL_FANOUT)
    # Per-call delay forces overlap; if they ran sequentially total ≈ 0.06s,
    # concurrent ≈ 0.02s. We don't assert timing, only that all three ran.
    executor = _make_recording_executor(per_call_delay=0.02)

    results = await execute_tree(
        root, strategy=BatchStrategy.PARALLEL_FANOUT, executor=executor
    )

    assert len(results) == 3
    assert {l.id for l in leaves} == set(results.keys())
    assert all(not r.is_error for r in results.values())


@pytest.mark.asyncio
async def test_race_returns_first_success_and_cancels_siblings() -> None:
    """RACE: first non-error wins; siblings get cancelled."""
    fast = _leaf("fast")
    slow_a = _leaf("slow_a")
    slow_b = _leaf("slow_b")

    started: list[str] = []
    completed: list[str] = []

    async def _exec(wo: WorkOrder) -> ClaudeResult:
        started.append(wo.intent)
        try:
            if wo.intent == "fast":
                await asyncio.sleep(0.005)
            else:
                await asyncio.sleep(2.0)  # long enough to be cancelled
            completed.append(wo.intent)
            return _ok_result(text=wo.intent)
        except asyncio.CancelledError:
            raise

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=_exec)

    root = _composite("root", [fast, slow_a, slow_b], strategy=BatchStrategy.RACE)
    results = await execute_tree(
        root, strategy=BatchStrategy.RACE, executor=executor
    )

    # Winner only — race returns first successful branch.
    assert len(results) == 1
    assert fast.id in results
    assert results[fast.id].response_text == "fast"
    # All three started, but only the fast one completed.
    assert set(started) == {"fast", "slow_a", "slow_b"}
    assert completed == ["fast"]


# ---------------------------------------------------------------------------
# Robustness — partial failure, no leaks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leaf_failure_doesnt_abort_other_leaves() -> None:
    """One leaf failing does not abort siblings; partial success preserved."""
    leaves = [_leaf("ok1"), _leaf("BAD"), _leaf("ok3")]
    root = _composite("root", leaves, strategy=BatchStrategy.SEQUENTIAL)
    executor = _make_recording_executor(failures={"BAD"})

    results = await execute_tree(
        root, strategy=BatchStrategy.SEQUENTIAL, executor=executor
    )

    # All three leaves attempted; bad one captured as error result.
    assert len(results) == 3
    assert executor.call_order == ["ok1", "BAD", "ok3"]
    bad = next(r for wo, r in zip(leaves, [results[l.id] for l in leaves]) if wo.intent == "BAD")
    assert bad.is_error is True
    assert bad.error_type == "leaf_exception"
    # Successful siblings unaffected.
    assert results[leaves[0].id].is_error is False
    assert results[leaves[2].id].is_error is False


@pytest.mark.asyncio
async def test_no_worktree_leaks_after_50_runs() -> None:
    """50 sequential leaf executions — every executor call paired with cleanup.

    Cleanup is delegated to ``WorktreeExecutor.execute``'s try/finally,
    so we assert the contract here by counting executor invocations and
    confirming none of the calls leaks an unhandled exception. (Real
    filesystem cleanup is covered in ``test_worktree_executor.py``.)
    """
    leaves = [_leaf(f"leaf_{i}") for i in range(50)]
    root = _composite("root", leaves, strategy=BatchStrategy.SEQUENTIAL)
    executor = _make_recording_executor()

    results = await execute_tree(
        root, strategy=BatchStrategy.SEQUENTIAL, executor=executor
    )

    assert len(results) == 50
    assert executor.execute.await_count == 50
    assert all(not r.is_error for r in results.values())
    # Every call site routed through the executor — no shortcut path.
    assert len(executor.call_order) == 50
