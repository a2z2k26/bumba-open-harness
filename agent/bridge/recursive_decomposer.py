"""Recursive WorkOrder decomposer (Sprint 07.02 + 07.03).

Concept-only port of TinyAGI/fractals (MIT, paraphrased — no verbatim
code). Implements the ``Decomposer`` Protocol shipped in 07.01 with a
real recursive ``classify(atomic|composite) → decompose → recurse`` loop.

Sprint 07.03 adds ``execute_tree`` — walks a decomposed tree and runs
each leaf through a ``WorktreeExecutor`` in its own isolated git
worktree. Strategy on each ``Decomposition`` governs how children are
scheduled relative to each other (SEQUENTIAL / PARALLEL_FANOUT / RACE).

The decomposer is **purely advisory** at this sprint: ``decompose_recursive``
returns a new ``WorkOrder`` with its ``decomposition`` field populated.
The caller (07.03 dispatcher wiring) decides whether to execute the tree.

Key properties:

- ``classify`` is heuristic-only (no LLM): atomic if the intent is short,
  contains no list-y task language, and implies a single tool. Composite
  otherwise. This keeps cost predictable and cycle-detection cheap.
- ``decompose`` is LLM-backed via an injected callable so tests can run
  fully offline. Cost is capped per call (default $0.02).
- ``decompose_recursive`` enforces ``max_depth`` (default 3) — at the
  bottom of the recursion every WO is forced atomic regardless of the
  classifier's verdict, with a logger.warning so cycles are visible.
- Idempotent: passing a WO that already carries a ``Decomposition`` is
  returned unchanged (no re-classification, no LLM call).
- Empty/whitespace intents short-circuit to atomic before any LLM call.

Reuses the existing ``workorder_decomposition_enabled`` feature flag
from 07.01 — no new flag.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from bridge.decomposer import Classification
from bridge.work_order import (
    BatchStrategy,
    Decomposition,
    WorkOrder,
)

if TYPE_CHECKING:
    from bridge.claude_runner import ClaudeResult
    from bridge.executors.worktree import WorktreeExecutor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Heuristic constants
# ---------------------------------------------------------------------------

# WorkOrders whose intent is shorter than this are very likely to be a
# single tool call. Keep this conservative — false-atomics waste a depth
# level at most; false-composites waste a Haiku call.
_ATOMIC_INTENT_CHAR_LIMIT = 200

# Phrases that signal multi-step task language. The presence of any of
# these in the intent flips the verdict to composite.
_LIST_LIKE_PATTERNS: tuple[str, ...] = (
    r"\band\s+then\b",
    r"\bfirst\b.*\bthen\b",
    r"\bsecond\b",
    r"\bthird\b",
    r"\bfourth\b",
    r"\bfifth\b",
    r"\bstep\s+\d+\b",
    r"\bafter\s+that\b",
    r"\bfollowed\s+by\b",
)

# Cost cap per ``decompose`` call. Haiku at typical decomposer prompt
# sizes runs ~$0.001-0.005, so $0.02 leaves comfortable headroom while
# guarding against runaway prompt sizes.
_DEFAULT_COST_CAP_USD = 0.02

# Default recursion depth. Three levels lets a top-level WO fan out
# into branches and leaves; deeper trees burn cost without helping
# planning quality in our experience.
_DEFAULT_MAX_DEPTH = 3


# ---------------------------------------------------------------------------
# LLM callable Protocol — kept tight so tests can inject fakes.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecomposeCallResult:
    """Result of one LLM-backed ``decompose`` call.

    ``children_intents`` is the list of sub-intents the LLM produced.
    ``cost_usd`` lets the caller enforce a per-call cap and roll up
    cost into the parent WO's budget.
    """

    children_intents: tuple[str, ...]
    strategy: BatchStrategy
    cost_usd: float = 0.0


class DecomposeCallable(Protocol):
    """Injected LLM call surface. Implementations must be idempotent on retry."""

    def __call__(self, wo: WorkOrder) -> DecomposeCallResult: ...


# ---------------------------------------------------------------------------
# RecursiveDecomposer
# ---------------------------------------------------------------------------


class RecursiveDecomposer:
    """Heuristic classifier + LLM-backed decomposer with depth/cost guards.

    Implements the ``Decomposer`` Protocol from 07.01 plus the recursive
    driver ``decompose_recursive``. Constructor accepts an injected
    ``DecomposeCallable`` so unit tests can run without any real LLM.
    """

    def __init__(
        self,
        *,
        decompose_call: DecomposeCallable | None = None,
        cost_cap_usd: float = _DEFAULT_COST_CAP_USD,
        max_depth: int = _DEFAULT_MAX_DEPTH,
    ) -> None:
        self._decompose_call = decompose_call
        self._cost_cap_usd = cost_cap_usd
        self._max_depth = max_depth

    # ------------------------------------------------------------------
    # Decomposer Protocol surface
    # ------------------------------------------------------------------

    def classify(self, wo: WorkOrder) -> Classification:
        """Heuristic-only classification — no LLM call.

        Returns ``"atomic"`` when the intent is short, single-tool, and
        free of list-y task language. Returns ``"composite"`` otherwise.
        Empty/whitespace intents are atomic by definition (nothing to
        decompose).
        """
        intent = (wo.intent or "").strip()
        if not intent:
            return "atomic"

        if len(intent) >= _ATOMIC_INTENT_CHAR_LIMIT:
            return "composite"

        lowered = intent.lower()
        for pattern in _LIST_LIKE_PATTERNS:
            if re.search(pattern, lowered):
                return "composite"

        # Multiple top-level conjunctions in a short intent also signal
        # multi-step work ("write the parser and run the linter and...").
        # Two or more " and " hits is a strong tell.
        if lowered.count(" and ") >= 2:
            return "composite"

        return "atomic"

    def decompose(self, wo: WorkOrder) -> Decomposition:
        """LLM-backed split of a composite WO into sub-WOs.

        The injected ``DecomposeCallable`` returns sub-intents and a
        strategy hint. Children are constructed as fresh ``WorkOrder``
        instances inheriting ``skill`` and ``project`` from the parent
        and pointing back via ``parent_id``.

        Raises ``RuntimeError`` if no callable was injected (the
        decomposer is configured for classification-only use) or if the
        call exceeds ``cost_cap_usd``.
        """
        if self._decompose_call is None:
            raise RuntimeError(
                "RecursiveDecomposer.decompose called without an injected "
                "DecomposeCallable. Construct with decompose_call=... or "
                "use classify-only mode."
            )

        result = self._decompose_call(wo)

        if result.cost_usd > self._cost_cap_usd:
            raise RuntimeError(
                f"decompose cost ${result.cost_usd:.4f} exceeds cap "
                f"${self._cost_cap_usd:.4f} for WO {wo.id}; aborting "
                "to avoid runaway recursion."
            )

        # Defensive: cap fan-out to a sane upper bound so a hallucinated
        # 50-child split can't blow up the tree. The spec calls for
        # 2-5; we accept up to 8 (07.02 spec's max_children) and trim.
        intents = tuple(i.strip() for i in result.children_intents if i and i.strip())
        if not intents:
            # No usable children — collapse to atomic. This is a
            # degenerate but valid outcome (LLM gave up).
            return Decomposition(strategy=result.strategy, children=(), atomic=True)

        intents = intents[:8]
        children = tuple(
            WorkOrder.create(
                intent=intent,
                skill=wo.skill,
                project=wo.project,
                parent_id=wo.id,
            )
            for intent in intents
        )

        return Decomposition(
            strategy=result.strategy,
            children=children,
            atomic=False,
        )

    # ------------------------------------------------------------------
    # Recursive driver
    # ------------------------------------------------------------------

    def decompose_recursive(
        self,
        wo: WorkOrder,
        *,
        max_depth: int | None = None,
        _depth: int = 0,
    ) -> WorkOrder:
        """Run ``classify → decompose → recurse`` until every leaf is atomic.

        Returns a new WorkOrder with the ``decomposition`` field
        populated for composite nodes (or marked atomic for leaves).
        Original ``wo`` is never mutated.

        ``max_depth`` overrides the constructor default for this call.
        Hitting the depth cap forces classification to atomic and logs
        a warning — this is the cycle-protection backstop.

        Idempotent: if ``wo`` already carries a ``decomposition`` the
        original is returned unchanged (no re-classification, no LLM
        call). Callers wanting to re-decompose must clear the field
        first via ``wo.with_decomposition(None)``.
        """
        if wo.decomposition is not None:
            return wo

        depth_cap = self._max_depth if max_depth is None else max_depth

        # Depth cap — force atomic regardless of classifier verdict.
        # This is the backstop against pathological cycles or
        # unbounded LLM fan-out.
        if _depth >= depth_cap:
            if self.classify(wo) == "composite":
                logger.warning(
                    "decompose_recursive hit max_depth=%s for WO %s; "
                    "forcing atomic to prevent runaway recursion.",
                    depth_cap,
                    wo.id,
                )
            return wo.with_decomposition(
                Decomposition(strategy=BatchStrategy.SEQUENTIAL, atomic=True)
            )

        verdict = self.classify(wo)
        if verdict == "atomic":
            return wo.with_decomposition(
                Decomposition(strategy=BatchStrategy.SEQUENTIAL, atomic=True)
            )

        # Composite — decompose then recurse on each child.
        plan = self.decompose(wo)
        if plan.atomic or not plan.children:
            # Decomposer collapsed to atomic (e.g. LLM gave up).
            return wo.with_decomposition(plan)

        recursed_children = tuple(
            self.decompose_recursive(child, max_depth=depth_cap, _depth=_depth + 1)
            for child in plan.children
        )

        return wo.with_decomposition(
            Decomposition(
                strategy=plan.strategy,
                children=recursed_children,
                atomic=False,
            )
        )


# ---------------------------------------------------------------------------
# Convenience constructor — no LLM, classification-only mode.
# ---------------------------------------------------------------------------


def make_classification_only_decomposer() -> RecursiveDecomposer:
    """Return a RecursiveDecomposer that can classify but not decompose.

    Useful for callers that only need the heuristic verdict (e.g.
    metrics, dispatcher hints) without paying for any LLM call.
    Calling ``decompose`` on the returned instance raises.
    """
    return RecursiveDecomposer(decompose_call=None)


# ---------------------------------------------------------------------------
# Sprint 07.03 — tree execution via WorktreeExecutor
# ---------------------------------------------------------------------------


def _is_leaf(wo: WorkOrder) -> bool:
    """A leaf is any WO that has no further children to expand.

    A WO with ``decomposition is None`` (never classified) is also a
    leaf for the executor's purposes — the caller is asking us to run
    it directly. Marked-atomic decompositions are leaves. Composite
    decompositions with empty ``children`` collapse to leaves too.
    """
    if wo.decomposition is None:
        return True
    if wo.decomposition.atomic:
        return True
    return not wo.decomposition.children


async def _execute_leaf(
    wo: WorkOrder,
    executor: "WorktreeExecutor",
) -> "ClaudeResult":
    """Run a single leaf through the executor; trap exceptions into a ClaudeResult.

    The executor's existing try/finally guarantees worktree cleanup even
    on failure; we additionally trap any propagated exception into a
    synthetic error result so siblings can keep running (per spec DoD:
    *"one leaf failing doesn't abort siblings"*).
    """
    from bridge.claude_runner import ClaudeResult

    try:
        return await executor.execute(wo)
    except asyncio.CancelledError:
        # Honour cancellation (used by RACE to cancel siblings).
        raise
    except Exception as exc:  # noqa: BLE001 — partial-success semantics
        logger.warning(
            "execute_tree: leaf %s raised %s; recording as error result.",
            wo.id[:8],
            type(exc).__name__,
        )
        return ClaudeResult(
            is_error=True,
            error_type="leaf_exception",
            stderr_output=f"{type(exc).__name__}: {exc}",
        )


async def _run_children(
    children: tuple[WorkOrder, ...],
    strategy: BatchStrategy,
    executor: "WorktreeExecutor",
) -> dict[str, "ClaudeResult"]:
    """Schedule child execution per the given strategy and merge the results."""
    results: dict[str, ClaudeResult] = {}

    if not children:
        return results

    if strategy == BatchStrategy.PARALLEL_FANOUT:
        # All children run concurrently; gather all results regardless
        # of individual outcome (partial success preserved).
        coros = [execute_tree(c, strategy=strategy, executor=executor) for c in children]
        gathered = await asyncio.gather(*coros, return_exceptions=False)
        for sub in gathered:
            results.update(sub)
        return results

    if strategy == BatchStrategy.RACE:
        # Race: first non-error result wins; cancel siblings.
        tasks: list[asyncio.Task[dict[str, ClaudeResult]]] = [
            asyncio.create_task(execute_tree(c, strategy=strategy, executor=executor))
            for c in children
        ]
        winner: dict[str, ClaudeResult] | None = None
        try:
            pending = set(tasks)
            while pending and winner is None:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for d in done:
                    sub = d.result()
                    if sub and any(not r.is_error for r in sub.values()):
                        winner = sub
                        break
                    # All errors in this branch — keep waiting; if no
                    # branch wins, fall through and aggregate failures.
                    results.update(sub)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            # Drain cancellations so we don't leak warnings.
            for t in tasks:
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

        if winner is not None:
            # Winner takes precedence; discard partial-error results.
            return winner
        return results

    # SEQUENTIAL (and traversal strategies — DEPTH_FIRST / BREADTH_FIRST /
    # LAYER_SEQUENTIAL — all run children in declared order at this layer;
    # finer traversal control is roadmap-only per spec scope boundary).
    for child in children:
        sub = await execute_tree(child, strategy=strategy, executor=executor)
        results.update(sub)
    return results


async def execute_tree(
    tree: WorkOrder,
    strategy: BatchStrategy,
    executor: "WorktreeExecutor",
) -> dict[str, "ClaudeResult"]:
    """Execute a decomposed WorkOrder tree, one isolated worktree per leaf.

    Sprint 07.03 — wires the decomposer (07.02) to the WorktreeExecutor.
    Each leaf is run via ``executor.execute(leaf)``, which creates a
    dedicated git worktree, runs the subagent inside it, and cleans up
    via try/finally regardless of outcome.

    Behavior:

    - Leaf WO (``decomposition is None`` or ``atomic`` or no children) →
      single ``executor.execute`` call. Result keyed by ``wo.id`` in the
      returned dict.
    - Composite WO → schedule children per the **node's own**
      ``Decomposition.strategy`` (PARALLEL_FANOUT / RACE / SEQUENTIAL).
      The ``strategy`` parameter on this function controls only the
      **root** node — once we descend into a child, that child's own
      decomposition strategy applies.
    - Failures: a leaf raising an exception is captured as a synthetic
      ``ClaudeResult(is_error=True, error_type="leaf_exception")`` —
      siblings keep running (partial success preserved).
    - Cleanup: delegated entirely to ``executor.execute``'s existing
      try/finally; this function adds none of its own worktree state.

    Returns a ``dict[str, ClaudeResult]`` keyed by leaf WorkOrder id.
    Internal nodes do not appear in the dict — synthesis is concat-only
    per spec ("sophisticated synthesis deferred").
    """
    if _is_leaf(tree):
        result = await _execute_leaf(tree, executor)
        return {tree.id: result}

    # Composite node — descend.
    assert tree.decomposition is not None  # _is_leaf guarantees this
    # The node's own strategy governs how its children are scheduled.
    # The argument-level ``strategy`` was already used at the parent
    # call site; here we honour the per-node value.
    node_strategy = tree.decomposition.strategy
    return await _run_children(
        tree.decomposition.children,
        strategy=node_strategy,
        executor=executor,
    )


# ---------------------------------------------------------------------------
# Sprint D1.6 -- Haiku adapter + prompt/response helpers
# ---------------------------------------------------------------------------

_COMPLEXITY_CHARS_PER_UNIT = 70


def heuristic_complexity_score(wo: WorkOrder) -> int:
    """Return a 1-10 complexity score derived from the WO intent length."""
    import math
    intent = (wo.intent or "").strip()
    if not intent:
        return 1
    raw = math.ceil(len(intent) / _COMPLEXITY_CHARS_PER_UNIT)
    return max(1, min(10, raw))


def _build_decomposition_prompt(wo: WorkOrder) -> str:
    """Assemble the Haiku decomposition prompt for wo."""
    complexity = getattr(wo, "complexity_score", None) or heuristic_complexity_score(wo)
    lines = [
        "SYSTEM:",
        "You are a WorkOrder decomposer. Given a single WorkOrder, return a JSON",
        "array of 2-5 child WorkOrder specs that, when executed in parallel and",
        "synthesized, produce the same outcome as executing the parent directly.",
        "",
        "Each child spec has the shape:",
        '{',
        '  "title": "<<one-line title>>",',
        '  "description": "<<3-5 sentence description>>",',
        '  "estimated_complexity": <integer 1-10>,',
        '  "depends_on": ["<<title of other child or null>>"]',
        '}',
        "",
        "Constraints:",
        "- Total estimated complexity across children <= parent complexity",
        "- Children are independent unless depends_on says otherwise",
        "- Children are bounded scope (no child has complexity >= parent complexity)",
        "- If the parent is not safely decomposable, return [] and a brief reason",
        "",
        "Respond with ONLY a JSON array (no prose, no markdown fences).",
        "",
        "USER:",
        "Parent WorkOrder:",
        f"  Title: {wo.intent[:120]}",
        f"  Description: {wo.intent}",
        f"  Complexity: {complexity}",
        "",
        "Decompose.",
    ]
    return "\n".join(lines)


def _parse_decomposition_response(
    text: str,
    parent_complexity: int,
) -> "tuple[list[str], BatchStrategy]":
    """Parse the LLM JSON response into a list of child intents."""
    import json as _json

    text = text.strip()
    if not text:
        return [], BatchStrategy.SEQUENTIAL

    if text.startswith("```"):
        parts = text.splitlines()
        text = "\n".join(parts[1:-1]) if len(parts) > 2 else ""

    try:
        data = _json.loads(text)
    except _json.JSONDecodeError:
        logger.warning("_parse_decomposition_response: invalid JSON from LLM: %s", text[:200])
        return [], BatchStrategy.SEQUENTIAL

    if not isinstance(data, list):
        logger.warning("_parse_decomposition_response: expected JSON array, got %s", type(data).__name__)
        return [], BatchStrategy.SEQUENTIAL

    intents: list[str] = []
    total_complexity = 0

    for item in data:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue
        est = int(item.get("estimated_complexity", 1) or 1)
        if est >= parent_complexity:
            logger.warning(
                "_parse_decomposition_response: child complexity %d >= parent %d; rejecting for child '%s'",
                est, parent_complexity, title,
            )
            return [], BatchStrategy.SEQUENTIAL
        total_complexity += est
        intents.append(title)

    if intents and total_complexity > parent_complexity:
        logger.warning(
            "_parse_decomposition_response: total %d > parent %d; rejecting",
            total_complexity, parent_complexity,
        )
        return [], BatchStrategy.SEQUENTIAL

    return intents, BatchStrategy.PARALLEL_FANOUT


def make_haiku_decomposer(claude_runner: object) -> "DecomposeCallable":
    """Build a DecomposeCallable that invokes Haiku via the bridge's ClaudeRunner.

    Sprint D1.6 -- wired into the dispatcher when
    workorder_decomposition_enabled = true.
    """
    import asyncio as _asyncio

    def _call(wo: WorkOrder) -> DecomposeCallResult:
        prompt = _build_decomposition_prompt(wo)
        parent_complexity = (
            getattr(wo, "complexity_score", None) or heuristic_complexity_score(wo)
        )

        async def _run() -> object:
            return await claude_runner.invoke_haiku_for_decomposition(prompt)  # type: ignore[attr-defined]

        try:
            try:
                loop = _asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                future = _asyncio.run_coroutine_threadsafe(_run(), loop)
                result = future.result(timeout=30)
            else:
                result = _asyncio.run(_run())
        except Exception as exc:
            logger.warning("make_haiku_decomposer: invoke failed (%s); no-split", exc)
            return DecomposeCallResult(children_intents=(), strategy=BatchStrategy.SEQUENTIAL, cost_usd=0.0)

        cost = float(getattr(result, "cost_usd", 0.0) or 0.0)
        children, strategy = _parse_decomposition_response(
            str(getattr(result, "response_text", "") or ""),
            parent_complexity,
        )
        return DecomposeCallResult(children_intents=tuple(children), strategy=strategy, cost_usd=cost)

    return _call


__all__ = [
    "DecomposeCallResult",
    "DecomposeCallable",
    "RecursiveDecomposer",
    "execute_tree",
    "make_classification_only_decomposer",
    "make_haiku_decomposer",
    "heuristic_complexity_score",
    "_build_decomposition_prompt",
    "_parse_decomposition_response",
]
