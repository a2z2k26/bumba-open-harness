"""Dark Factory fresh-context fix loop — max 2 attempts then escalate.

Sprint 14.09 — Plan 14 Phase 5.

Concept-only port of coleam00/dark-factory-experiment (no LICENSE — no
source copy). After Sprint 14.08's
:mod:`bridge.factory.seven_rule_synthesizer` (renamed from
``bridge.factory.synthesizer`` in Sprint P8.3 / audit M-6, #1749)
returns ``NEEDS_FIX``, the factory loop (Sprint 14.10's
:mod:`bridge.services.factory_orchestrator`) routes the issue to
``factory:fix-attempt-1``. This module owns what happens next:

  1. Read the block reasons off the prior :class:`SynthesisDecision`
  2. Spawn a **fresh** Claude subprocess (no ``--resume``, no shared
     session, no inherited tool history) with the original issue body,
     the current PR diff, and the specific block reasons
  3. The subprocess produces a focused patch addressing only those blocks
  4. Re-validate + re-synthesize on the new diff
  5. If still ``NEEDS_FIX`` → attempt 2 (``factory:fix-attempt-2``)
  6. If still ``NEEDS_FIX`` after attempt 2 → escalate to
     ``factory:needs-human``
  7. If ``RETRY_REVIEWERS`` or ``NEEDS_HUMAN`` at any point → respect
     that outcome; do not loop further

"Fresh context" — the load-bearing invariant of the fix loop — means each
attempt begins from a clean slate: no inherited session id, no tool-call
history, no prior reasoning. The point is to prevent the agent from
doubling down on a wrong approach. :func:`make_fix_runner` wires this
explicitly: it never passes ``--resume``, never threads a session id, and
asks for sonnet (not haiku) because one focused fix needs reasoning, not
just throughput.

Cost discipline matches the rest of the factory:

  - Per-attempt cost cap (default $1.50): if the fix subprocess exceeds
    its budget, the attempt is logged with ``error`` set and the next
    attempt still runs. One blown attempt does not kill the loop.
  - Total cost cap (default $3.00): if the cumulative cost of all
    attempts exceeds the cap mid-loop, the loop stops and escalates.
    This preserves the synthesizer's Rule 7 cost-kill-switch discipline
    one layer up.

The loop is deterministic given fixed inputs: same issue body, same
diff, same runners → same final outcome. No I/O outside the runner
callables.

Naming
------

The module is :mod:`bridge.factory.fix_loop` to match the existing
``bridge.factory.{synthesizer,validate,implement,quality,...}`` layout.
Public names are :class:`FixAttemptResult`, :class:`FixLoopResult`,
:func:`run_fix_loop`, :func:`make_fix_runner` — short, unambiguous, and
greppable.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Final, Optional

from bridge.dispatch_metrics import increment_module_counter
from bridge.factory.labels import FactoryState
from bridge.factory.seven_rule_synthesizer import (
    FactorySynthesisOutcome,
    SynthesisDecision,
    SynthesisInput,
    outcome_to_factory_state,
    synthesize,
)

logger = logging.getLogger(__name__)


# ── Defaults (mirrors BridgeConfig fields) ───────────────────────────────


# Two attempts per spec ("max 2 attempts, then escalate"). Hardcoded as a
# defensive ceiling — the orchestrator passes the configured value, but if
# a future caller forgets, we still cap at 2.
DEFAULT_MAX_ATTEMPTS: Final[int] = 2

# Per-attempt cost cap. Sized so two attempts comfortably fit under the
# total cap with headroom. A breached per-attempt cap fails *that* attempt
# (FixAttemptResult.error set) without killing the loop — the second
# attempt still runs.
DEFAULT_COST_CAP_PER_ATTEMPT_USD: Final[float] = 1.50

# Total cost cap across all attempts within a single fix-loop invocation.
# When the cumulative cost crosses this mid-loop, the loop stops and
# escalates so cost discipline is preserved layer by layer.
DEFAULT_COST_CAP_TOTAL_USD: Final[float] = 3.00


# ── Result dataclasses ───────────────────────────────────────────────────


@dataclass(frozen=True)
class FixAttemptResult:
    """One fix attempt's outcome.

    Frozen so the loop cannot accidentally mutate a recorded attempt
    while reasoning about a sibling. ``error`` is populated when the
    fix subprocess crashed, timed out, or breached the per-attempt
    cost cap; in that case ``final_outcome`` falls back to the
    ``initial_outcome`` (i.e. the attempt did not change anything).
    """

    attempt_number: int  # 1 or 2
    initial_outcome: FactorySynthesisOutcome  # what triggered this attempt (NEEDS_FIX)
    final_outcome: FactorySynthesisOutcome  # synth verdict on the attempt's new diff
    final_state: FactoryState  # the FactoryState the attempt ends in
    block_reasons_addressed: tuple[str, ...]  # blocks the attempt was given to fix
    block_reasons_remaining: tuple[str, ...]  # blocks synth still complains about
    cost_usd: float
    duration_seconds: float
    error: Optional[str] = None  # set on subprocess crash / timeout / cap breach


@dataclass(frozen=True)
class FixLoopResult:
    """Aggregate result of running 0, 1, or 2 fix attempts.

    ``attempts == ()`` is the no-op case: the initial decision wasn't
    ``NEEDS_FIX`` so the loop had nothing to do. ``escalated_to_human``
    is True iff every available attempt exhausted itself while still
    blocking — operator must intervene.
    """

    attempts: tuple[FixAttemptResult, ...]  # 0, 1, or 2 entries
    final_outcome: FactorySynthesisOutcome
    final_state: FactoryState
    total_cost_usd: float
    escalated_to_human: bool


# ── Runner protocols ─────────────────────────────────────────────────────


# Fix-runner contract:
#     fix_runner(issue_body, current_diff, block_reasons)
#         -> Awaitable[(new_diff_text, cost_usd, latency_ms)]
#
# Implementations spawn a fresh Claude subprocess. The contract is
# intentionally narrow — only the three inputs the prompt actually
# consumes. ``make_fix_runner`` is the reference adapter.
FixRunner = Callable[
    [str, str, tuple[str, ...]],
    Awaitable[tuple[str, float, int]],
]


# Validate-runner contract — wraps :func:`bridge.factory.validate.validate_pr`.
# Typed loosely with ``Any`` for the return because we only read duck-typed
# attributes (``block_reasons``, ``total_cost_usd``, ``aggregate_verdict``)
# off the result; importing :class:`ValidateResult` here would tie this
# module to validate.py's optional deps for no benefit.
ValidateRunner = Callable[
    [str, str, str],
    Awaitable[Any],
]


# ── Prompt template (paraphrased; concept-only) ─────────────────────────


PROMPT_TEMPLATE: Final[str] = (
    "You are receiving a code change that has been validated by 4 reviewers.\n"
    "Some reviewers blocked the change. Your job is to address ONLY the blocking\n"
    "reasons listed below. Do not make any other changes.\n"
    "\n"
    "# Original issue\n"
    "{issue_body}\n"
    "\n"
    "# Current diff\n"
    "{current_diff}\n"
    "\n"
    "# Block reasons to address\n"
    "{block_reasons_formatted}\n"
    "\n"
    "Output: a unified-diff patch that addresses the blocks. No explanation.\n"
)


def _format_block_reasons(block_reasons: tuple[str, ...]) -> str:
    """Render block reasons as a bulleted list for the fix prompt.

    Empty tuple yields "(no specific block reasons recorded)" — the prompt
    never has a blank section. Each reason gets a leading ``- `` so the
    fixer sees them as a clearly-delimited list.
    """
    if not block_reasons:
        return "(no specific block reasons recorded)"
    return "\n".join(f"- {reason}" for reason in block_reasons)


# ── Helpers ──────────────────────────────────────────────────────────────


def _normalize_block_signature(block_reasons: tuple[str, ...]) -> tuple[str, ...]:
    """Lowercase + strip + sort block reasons for the synthesizer's
    ``prior_block_signature`` field.

    Mirrors :func:`bridge.factory.seven_rule_synthesizer._normalize_block_signature`
    — duplicated here rather than imported because the synth helper is
    underscore-prefixed (private). Keeping the duplication explicit is
    cheaper than promoting the helper to public surface for one caller.
    """
    return tuple(sorted(reason.strip().lower() for reason in block_reasons))


def _attempt_to_state(attempt_number: int) -> FactoryState:
    """Map an attempt number to its target ``factory:fix-attempt-N`` state.

    Hardcoded for 1 and 2 — beyond that, the loop has already escalated.
    Defensive: any other value lands at FIX_ATTEMPT_2 (the more pessimistic
    of the two) so a misuse never silently routes to a wrong state.
    """
    if attempt_number <= 1:
        return FactoryState.FIX_ATTEMPT_1
    return FactoryState.FIX_ATTEMPT_2


# ── The loop ─────────────────────────────────────────────────────────────


async def run_fix_loop(
    *,
    initial_decision: SynthesisDecision,
    issue_body: str,
    pr_url: str,
    initial_diff: str,
    fix_runner: FixRunner,
    validate_runner: ValidateRunner,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    cost_cap_per_attempt_usd: float = DEFAULT_COST_CAP_PER_ATTEMPT_USD,
    cost_cap_total_usd: float = DEFAULT_COST_CAP_TOTAL_USD,
) -> FixLoopResult:
    """Run up to ``max_attempts`` auto-fix iterations.

    Behaviour:

      - If ``initial_decision.outcome != NEEDS_FIX`` → return
        immediately with ``attempts=()``. The initial outcome and its
        state pass through unchanged.
      - On each attempt: invoke ``fix_runner`` with the block reasons,
        capture the new diff and cost, run ``validate_runner`` on the
        new diff, build a :class:`SynthesisInput` with
        ``prior_block_signature`` populated from the prior block list,
        call :func:`synthesize`, and check the outcome.
      - If the outcome ≠ ``NEEDS_FIX`` after any attempt → stop and
        return that outcome's state.
      - If ``max_attempts`` exhausted while still ``NEEDS_FIX`` →
        escalate (``final_state=NEEDS_HUMAN``,
        ``escalated_to_human=True``).
      - Per-attempt cost cap: if exceeded, that attempt's
        :class:`FixAttemptResult` carries ``error`` and the next attempt
        still runs.
      - Total cost cap: if cumulative exceeds the cap, stop the loop
        and escalate so the cost-kill-switch discipline is preserved.
      - On ``RETRY_REVIEWERS`` or ``NEEDS_HUMAN`` mid-loop: respect that
        outcome; do not loop further. The orchestrator owns those paths.

    Args:
        initial_decision: The synthesizer decision that triggered the
            fix loop (must be ``NEEDS_FIX`` for any work to happen).
        issue_body: Original issue body — handed to the fix runner so
            the fresh subprocess sees the spec without inheriting any
            prior session.
        pr_url: PR URL — passed through to the validate runner.
        initial_diff: PR diff at the start of the loop — the first fix
            attempt's input. Subsequent attempts replace it with the
            previous attempt's output.
        fix_runner: Async callable that spawns a fresh Claude subprocess
            (no ``--resume``) and returns the new diff text + cost +
            latency.
        validate_runner: Async callable that re-runs the 4-holdout
            validate workflow against the new diff and returns a
            :class:`bridge.factory.validate.ValidateResult`.
        max_attempts: Hard ceiling on attempts (default 2 per spec).
        cost_cap_per_attempt_usd: Per-attempt cost cap; breach fails
            that attempt only.
        cost_cap_total_usd: Total cost cap; breach stops + escalates.
    """
    result = await _run_fix_loop_impl(
        initial_decision=initial_decision,
        issue_body=issue_body,
        pr_url=pr_url,
        initial_diff=initial_diff,
        fix_runner=fix_runner,
        validate_runner=validate_runner,
        max_attempts=max_attempts,
        cost_cap_per_attempt_usd=cost_cap_per_attempt_usd,
        cost_cap_total_usd=cost_cap_total_usd,
    )
    # Determinism Spectrum (Sprint #1115): judged-LLM with retry, Tier 3.
    increment_module_counter(
        "factory.fix_loop.run_fix_loop",
        tier=3,
        cost_usd=float(getattr(result, "total_cost_usd", 0.0) or 0.0),
        escalation=bool(getattr(result, "escalated_to_human", False)),
    )
    return result


async def _run_fix_loop_impl(
    *,
    initial_decision: SynthesisDecision,
    issue_body: str,
    pr_url: str,
    initial_diff: str,
    fix_runner: FixRunner,
    validate_runner: ValidateRunner,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    cost_cap_per_attempt_usd: float = DEFAULT_COST_CAP_PER_ATTEMPT_USD,
    cost_cap_total_usd: float = DEFAULT_COST_CAP_TOTAL_USD,
) -> FixLoopResult:
    """Internal fix-loop body — extracted so the public ``run_fix_loop``
    can record a single Tier 3 invocation regardless of which exit path
    fires (per Sprint #1115 determinism counters).
    """
    # ── Short-circuit: not a fix-eligible decision ────────────────────
    if initial_decision.outcome != FactorySynthesisOutcome.NEEDS_FIX:
        return FixLoopResult(
            attempts=(),
            final_outcome=initial_decision.outcome,
            final_state=outcome_to_factory_state(initial_decision.outcome),
            total_cost_usd=0.0,
            escalated_to_human=False,
        )

    attempts: list[FixAttemptResult] = []
    cumulative_cost = 0.0
    current_diff = initial_diff
    current_blocks = initial_decision.block_reasons
    current_outcome = initial_decision.outcome  # NEEDS_FIX entering the loop

    # Bound max_attempts defensively — never run more than the absolute
    # ceiling. A caller passing 99 still caps at DEFAULT_MAX_ATTEMPTS so the
    # loop can't be tricked into burning cost.
    bounded_max = max(1, min(int(max_attempts), DEFAULT_MAX_ATTEMPTS))

    for attempt_number in range(1, bounded_max + 1):
        attempt_started = time.monotonic()
        block_reasons_addressed = current_blocks

        # ── Pre-attempt: total-cost gate ──────────────────────────────
        # Checked BEFORE spawning the fix subprocess so a runaway loop
        # cannot escape the cap by being mid-attempt when it crosses it.
        if cumulative_cost > cost_cap_total_usd:
            logger.warning(
                "fix_loop: total cost $%.4f exceeded cap $%.2f before "
                "attempt %d — escalating",
                cumulative_cost, cost_cap_total_usd, attempt_number,
            )
            return FixLoopResult(
                attempts=tuple(attempts),
                final_outcome=FactorySynthesisOutcome.ESCALATE_COST,
                final_state=outcome_to_factory_state(
                    FactorySynthesisOutcome.ESCALATE_COST
                ),
                total_cost_usd=cumulative_cost,
                escalated_to_human=True,
            )

        # ── Run the fix subprocess (fresh context) ────────────────────
        new_diff = current_diff
        attempt_error: Optional[str] = None
        try:
            fix_result = await fix_runner(
                issue_body, current_diff, block_reasons_addressed,
            )
            new_diff_candidate, fix_cost_usd, _fix_latency_ms = fix_result
        except Exception as e:  # noqa: BLE001 — fail-soft per attempt
            logger.warning(
                "fix_loop: attempt %d fix runner raised %s — recording error, "
                "continuing to next attempt",
                attempt_number, e,
            )
            attempts.append(
                FixAttemptResult(
                    attempt_number=attempt_number,
                    initial_outcome=current_outcome,
                    final_outcome=current_outcome,  # nothing changed
                    final_state=_attempt_to_state(attempt_number),
                    block_reasons_addressed=block_reasons_addressed,
                    block_reasons_remaining=block_reasons_addressed,
                    cost_usd=0.0,
                    duration_seconds=time.monotonic() - attempt_started,
                    error=f"fix_runner: {type(e).__name__}: {e}",
                )
            )
            continue

        fix_cost_f = float(fix_cost_usd or 0.0)

        # ── Per-attempt cost cap ──────────────────────────────────────
        if fix_cost_f > cost_cap_per_attempt_usd:
            attempt_error = (
                f"per-attempt cost cap exceeded: "
                f"${fix_cost_f:.4f} > ${cost_cap_per_attempt_usd:.2f}"
            )
            logger.warning(
                "fix_loop: attempt %d %s — failing this attempt; "
                "next attempt will still run",
                attempt_number, attempt_error,
            )
            cumulative_cost += fix_cost_f
            attempts.append(
                FixAttemptResult(
                    attempt_number=attempt_number,
                    initial_outcome=current_outcome,
                    final_outcome=current_outcome,
                    final_state=_attempt_to_state(attempt_number),
                    block_reasons_addressed=block_reasons_addressed,
                    block_reasons_remaining=block_reasons_addressed,
                    cost_usd=fix_cost_f,
                    duration_seconds=time.monotonic() - attempt_started,
                    error=attempt_error,
                )
            )
            continue

        cumulative_cost += fix_cost_f
        new_diff = new_diff_candidate or current_diff

        # ── Mid-attempt: total-cost gate after the fix subprocess ─────
        # Catches the case where one attempt's cost lands us past the cap
        # but isn't itself a per-attempt breach. Stop + escalate.
        if cumulative_cost > cost_cap_total_usd:
            logger.warning(
                "fix_loop: total cost $%.4f exceeded cap $%.2f after "
                "attempt %d's fix subprocess — escalating",
                cumulative_cost, cost_cap_total_usd, attempt_number,
            )
            attempts.append(
                FixAttemptResult(
                    attempt_number=attempt_number,
                    initial_outcome=current_outcome,
                    final_outcome=FactorySynthesisOutcome.ESCALATE_COST,
                    final_state=outcome_to_factory_state(
                        FactorySynthesisOutcome.ESCALATE_COST
                    ),
                    block_reasons_addressed=block_reasons_addressed,
                    block_reasons_remaining=block_reasons_addressed,
                    cost_usd=fix_cost_f,
                    duration_seconds=time.monotonic() - attempt_started,
                    error="total cost cap exceeded mid-loop",
                )
            )
            return FixLoopResult(
                attempts=tuple(attempts),
                final_outcome=FactorySynthesisOutcome.ESCALATE_COST,
                final_state=outcome_to_factory_state(
                    FactorySynthesisOutcome.ESCALATE_COST
                ),
                total_cost_usd=cumulative_cost,
                escalated_to_human=True,
            )

        # ── Re-validate the new diff (fresh context — fresh runner) ──
        try:
            validate_result = await validate_runner(
                issue_body, pr_url, new_diff,
            )
        except Exception as e:  # noqa: BLE001 — fail-soft per attempt
            logger.warning(
                "fix_loop: attempt %d validate runner raised %s — "
                "recording error, continuing",
                attempt_number, e,
            )
            attempts.append(
                FixAttemptResult(
                    attempt_number=attempt_number,
                    initial_outcome=current_outcome,
                    final_outcome=current_outcome,
                    final_state=_attempt_to_state(attempt_number),
                    block_reasons_addressed=block_reasons_addressed,
                    block_reasons_remaining=block_reasons_addressed,
                    cost_usd=fix_cost_f,
                    duration_seconds=time.monotonic() - attempt_started,
                    error=f"validate_runner: {type(e).__name__}: {e}",
                )
            )
            continue

        validate_cost = float(
            getattr(validate_result, "total_cost_usd", 0.0) or 0.0
        )
        cumulative_cost += validate_cost

        # ── Re-synthesize ─────────────────────────────────────────────
        # ``prior_block_signature`` carries the *previous* block set so
        # synth Rule 6 can detect "same blocks reproduced" → ABANDON.
        # Without this thread-through, a stuck fix could loop forever
        # under the synth's own discipline.
        prior_signature = _normalize_block_signature(current_blocks)
        new_decision = synthesize(
            SynthesisInput(
                validate_result=validate_result,
                total_cost_usd=cumulative_cost,
                retry_count=attempt_number,
                prior_block_signature=prior_signature,
            ),
        )

        new_blocks = new_decision.block_reasons
        new_outcome = new_decision.outcome

        # Record this attempt before deciding whether to loop.
        attempts.append(
            FixAttemptResult(
                attempt_number=attempt_number,
                initial_outcome=current_outcome,
                final_outcome=new_outcome,
                final_state=outcome_to_factory_state(new_outcome),
                block_reasons_addressed=block_reasons_addressed,
                block_reasons_remaining=new_blocks,
                cost_usd=fix_cost_f + validate_cost,
                duration_seconds=time.monotonic() - attempt_started,
                error=None,
            )
        )

        # ── Outcome-driven exit conditions ────────────────────────────
        if new_outcome != FactorySynthesisOutcome.NEEDS_FIX:
            # The attempt resolved (or escalated to a non-fix path).
            # Respect the synth's verdict — do not loop further.
            return FixLoopResult(
                attempts=tuple(attempts),
                final_outcome=new_outcome,
                final_state=outcome_to_factory_state(new_outcome),
                total_cost_usd=cumulative_cost,
                escalated_to_human=False,
            )

        # Still NEEDS_FIX → next attempt (if any). Roll forward state.
        current_diff = new_diff
        current_blocks = new_blocks
        current_outcome = new_outcome

    # ── Loop exhausted while still NEEDS_FIX → escalate ──────────────
    logger.info(
        "fix_loop: %d attempts exhausted while still NEEDS_FIX — "
        "escalating to operator",
        bounded_max,
    )
    return FixLoopResult(
        attempts=tuple(attempts),
        final_outcome=FactorySynthesisOutcome.NEEDS_HUMAN,
        final_state=FactoryState.NEEDS_HUMAN,
        total_cost_usd=cumulative_cost,
        escalated_to_human=True,
    )


# ── Reference fix-runner adapter (fresh-context invariant) ──────────────


def make_fix_runner(
    claude_runner: object,
    *,
    model: str = "sonnet",
    timeout_s: int = 300,
) -> FixRunner:
    """Build a :data:`FixRunner` that wraps ``claude_runner.invoke``.

    Critical invariant: this adapter NEVER passes ``--resume`` and NEVER
    threads a ``session_id``. Each call is a fresh Claude subprocess with
    no inherited session, no tool-call history, no prior reasoning. That
    is the load-bearing guarantee of the fix loop — it prevents the agent
    from doubling down on a wrong approach across attempts.

    The model defaults to ``sonnet`` (not haiku): one focused fix
    addressing specific block reasons needs reasoning, not throughput.
    The validate workflow uses haiku for cost discipline; the fix
    workflow can afford sonnet because it runs at most twice per issue.

    Args:
        claude_runner: A :class:`bridge.claude_runner.ClaudeRunner`
            instance — duck-typed via ``invoke()``.
        model: Model hint passed to ``claude_runner.invoke``. Default
            ``"sonnet"`` per discipline above; override to ``"haiku"``
            in cost-stressed environments.
        timeout_s: Wall-clock timeout per fix attempt. The fix prompt
            is bounded; 5 min is plenty for sonnet to produce a focused
            patch. Breach → :class:`asyncio.TimeoutError` propagates to
            :func:`run_fix_loop`'s per-attempt error path.
    """

    async def _runner(
        issue_body: str,
        current_diff: str,
        block_reasons: tuple[str, ...],
    ) -> tuple[str, float, int]:
        prompt = PROMPT_TEMPLATE.format(
            issue_body=issue_body or "(no issue body)",
            current_diff=current_diff or "(empty diff)",
            block_reasons_formatted=_format_block_reasons(block_reasons),
        )
        started = time.monotonic()
        # Fresh context — session_id explicitly None. Never resume.
        invoke = getattr(claude_runner, "invoke", None)
        if invoke is None:
            raise RuntimeError(
                "fix_loop: claude_runner has no `invoke` method — "
                "cannot dispatch fix subprocess"
            )
        try:
            result = await asyncio.wait_for(
                invoke(prompt, session_id=None, model=model),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError as e:
            raise RuntimeError(
                f"fix_loop: subprocess timed out after {timeout_s}s"
            ) from e
        latency_ms = int((time.monotonic() - started) * 1000)
        new_diff = str(getattr(result, "response_text", "") or "")
        cost_usd = float(getattr(result, "cost_usd", 0.0) or 0.0)
        return new_diff, cost_usd, latency_ms

    return _runner


__all__ = [
    "DEFAULT_COST_CAP_PER_ATTEMPT_USD",
    "DEFAULT_COST_CAP_TOTAL_USD",
    "DEFAULT_MAX_ATTEMPTS",
    "FixAttemptResult",
    "FixLoopResult",
    "FixRunner",
    "PROMPT_TEMPLATE",
    "ValidateRunner",
    "make_fix_runner",
    "run_fix_loop",
]
