"""Dark Factory holdout primitive — generalized empty-tools reviewer.

Sprint 14.03 — Plan 14 Phase 4. Concept-only port of the Dark Factory
holdout idea (no LICENSE — no source copy).

This module extracts the per-reviewer primitive that Sprint 14.07 shipped
inline in :mod:`bridge.factory.validate` so future holdout consumers
(``factory loop`` Sprint 14.10, ``_holdout_validator.py`` from Plan 02.14
when it lands, etc.) can share a single, audited surface.

# The empty-tools contract — read this before wiring a new consumer

A holdout reviewer is the **adversary** of the implementer subprocess.
It must not see the implementer's plans, sibling reviewers' verdicts,
session continuity, the file system, MCP servers, bash, web, or any
tool that could rewrite the prompt it judges. The reviewer reads the
prompt, emits a structured verdict, exits.

This primitive **does not call ``claude -p`` directly**. It delegates
to a caller-supplied :data:`HoldoutRunner`. The runner contract:

  - It MUST invoke claude with empty tools — for the bridge's
    ``claude_runner.ClaudeRunner`` that means appending
    ``--allowedTools=""`` to the argv. See
    :func:`make_empty_tools_runner` for a reference adapter.
  - It MUST be single-pass — no ``--resume``, no session continuity.
  - It MUST enforce the per-invocation timeout (``input.timeout_s``)
    and translate timeouts into ``asyncio.TimeoutError`` (or any
    exception — :func:`run_holdout` is fail-soft).
  - It MUST return ``(response_text, cost_usd, latency_ms)``.

Tests verify the contract by inspecting what the runner was called
with; the primitive itself is tool-agnostic so it can be unit-tested
without spawning anything.

# Cost discipline

Each :class:`HoldoutInput` carries its own ``cost_cap_usd``. When a
runner reports a cost above the cap, :func:`run_holdout` does NOT
abort the call (the spend already happened) — it converts the result
into ``ADVISE`` with ``parse_error="cost_cap_exceeded"`` so callers see
the breach in the verdict and can react. The cap is therefore
defensive: it bounds individual-invocation reporting, and consumers
budget total cost via :func:`run_holdout_batch` (sum of per-input
caps).

# Fail-soft

Holdout is a gate; a broken reviewer must not block PR progress. Every
exception path (runner raises, parse fails, cost cap trips) returns
``HoldoutResult(verdict=ADVISE, parse_error=...)``. Callers that need
strict propagation should layer their own checks on top of
``parse_error``.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Final, Optional

from bridge.dispatch_metrics import increment_module_counter

logger = logging.getLogger(__name__)


# ── Verdict enum ────────────────────────────────────────────────────────


class HoldoutVerdict(str, Enum):
    """Three-valued holdout outcome.

    ``PASS`` — no concerns.
    ``ADVISE`` — soft signal worth a look but not blocking.
    ``BLOCK`` — must not merge as-is.
    """

    PASS = "pass"
    ADVISE = "advise"
    BLOCK = "block"


_VALID_VERDICT_STRINGS: Final[frozenset[str]] = frozenset(
    {v.value for v in HoldoutVerdict}
)


# ── Input + result envelopes ────────────────────────────────────────────


@dataclass(frozen=True)
class HoldoutInput:
    """Inputs to a single holdout invocation.

    ``kind`` is a free-form label the consumer attaches (e.g.
    ``"behavioral"`` / ``"security"`` / ``"experiment_iteration"``) so
    batch results can be matched to inputs without positional
    dependence. The primitive does not interpret it.
    """

    kind: str
    prompt: str
    cost_cap_usd: float = 0.20
    timeout_s: int = 60


@dataclass(frozen=True)
class HoldoutResult:
    """Structured result from one holdout invocation.

    ``parse_error`` is set when:
      - the reviewer output could not be parsed,
      - the runner raised before producing output,
      - the runner-reported cost exceeded ``input.cost_cap_usd``.

    In all three cases the verdict is :data:`HoldoutVerdict.ADVISE` so
    the gate stays fail-soft. Strict consumers can branch on
    ``parse_error is not None``.
    """

    kind: str
    verdict: HoldoutVerdict
    summary: str
    findings: tuple[str, ...]
    cost_usd: float
    latency_ms: int
    raw_response: str
    parse_error: Optional[str] = None


# ── Runner protocol ──────────────────────────────────────────────────────


# A HoldoutRunner is an awaitable that takes a prompt and returns
# ``(response_text, cost_usd, latency_ms)``. The runner is responsible
# for everything tool-related — the primitive only inspects the
# returned tuple.
HoldoutRunner = Callable[[str], Awaitable[tuple[str, float, int]]]


# ── Verdict parsing ──────────────────────────────────────────────────────


_VERDICT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*VERDICT\s*:\s*(pass|advise|block)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FINDING_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*[-*]\s+(.+?)\s*$",
    re.MULTILINE,
)


def parse_verdict(
    raw: str,
) -> tuple[HoldoutVerdict, str, tuple[str, ...], Optional[str]]:
    """Parse a structured reviewer response.

    Expected shape::

        VERDICT: pass|advise|block
        <summary line — anything until the FINDINGS section or end>
        FINDINGS:
        - <bullet 1>
        - <bullet 2>

    The summary line is the first non-empty line after ``VERDICT``.
    Findings are bullets after the optional ``FINDINGS`` header (or
    after the verdict line if no header is present); ``none`` / ``n/a``
    bullets are dropped.

    Returns ``(verdict, summary, findings, parse_error)``. On any
    parse problem returns ``(ADVISE, "<diagnostic>", (), error_message)``
    so callers stay fail-soft. Empty input → ``ADVISE`` with a
    "empty reviewer output" parse error.
    """
    if not raw or not raw.strip():
        return (
            HoldoutVerdict.ADVISE,
            "reviewer output malformed",
            (),
            "parse error: empty reviewer output",
        )

    verdict_match = _VERDICT_RE.search(raw)
    if verdict_match is None:
        return (
            HoldoutVerdict.ADVISE,
            "reviewer output malformed",
            (),
            "parse error: missing VERDICT line",
        )

    verdict_str = verdict_match.group(1).strip().lower()
    if verdict_str not in _VALID_VERDICT_STRINGS:  # pragma: no cover — regex constrains
        return (
            HoldoutVerdict.ADVISE,
            "reviewer output malformed",
            (),
            f"parse error: unrecognized verdict {verdict_str!r}",
        )
    verdict = HoldoutVerdict(verdict_str)

    # Summary: first non-empty line after the verdict line, stopping at
    # FINDINGS header. Look at the slice of ``raw`` after the verdict
    # match end so we don't accidentally pick the verdict line itself.
    after_verdict = raw[verdict_match.end():]
    findings_pos = after_verdict.upper().find("FINDINGS")
    summary_region = (
        after_verdict[:findings_pos] if findings_pos != -1 else after_verdict
    )
    summary_lines = [
        line.strip()
        for line in summary_region.splitlines()
        if line.strip()
    ]
    # Drop any bullet-style summary lines (those belong to findings if
    # the FINDINGS header was omitted).
    summary_candidates = [
        ln for ln in summary_lines if not _FINDING_LINE_RE.match(ln)
    ]
    summary = summary_candidates[0] if summary_candidates else "(no summary)"

    # Findings: bullets after the FINDINGS header, or after the summary
    # if no header. Drop "none" / "n/a" placeholders.
    if findings_pos != -1:
        findings_region = after_verdict[findings_pos:]
    else:
        findings_region = after_verdict
    findings = tuple(
        m.group(1).strip()
        for m in _FINDING_LINE_RE.finditer(findings_region)
        if m.group(1).strip().lower() not in {"none", "n/a", "-"}
    )

    return verdict, summary, findings, None


# ── Single-invocation entry point ────────────────────────────────────────


async def run_holdout(
    inputs: HoldoutInput,
    *,
    runner: HoldoutRunner,
    model: str = "haiku",
) -> HoldoutResult:
    """Run one holdout invocation through the supplied runner.

    The primitive does not invoke claude itself; the runner does. The
    runner MUST enforce the empty-tools contract described in the
    module docstring (see :func:`make_empty_tools_runner` for a
    reference adapter that does so for the bridge's ``ClaudeRunner``).

    Defensive: any runner exception (including
    :class:`asyncio.TimeoutError`) becomes an ``ADVISE`` result with
    ``parse_error`` describing the failure. A runner that reports
    ``cost_usd`` above ``inputs.cost_cap_usd`` gets the same
    treatment, with ``parse_error="cost_cap_exceeded"``.
    """
    started = time.monotonic()
    try:
        response, cost_usd, latency_ms = await runner(inputs.prompt)
    except asyncio.TimeoutError as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "holdout.run_holdout: %s reviewer timed out after %dms",
            inputs.kind, elapsed_ms,
        )
        increment_module_counter(
            "factory.holdout.run_holdout",
            tier=2,
            parse_error=True,
        )
        return HoldoutResult(
            kind=inputs.kind,
            verdict=HoldoutVerdict.ADVISE,
            summary="reviewer subprocess timed out",
            findings=(f"timeout: {e}" if str(e) else "timeout: no message",),
            cost_usd=0.0,
            latency_ms=elapsed_ms,
            raw_response="",
            parse_error=f"asyncio.TimeoutError: {e}",
        )
    except Exception as e:  # noqa: BLE001 — fail-soft on any runner error
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "holdout.run_holdout: %s reviewer raised %s — degrading to advise",
            inputs.kind, e,
        )
        increment_module_counter(
            "factory.holdout.run_holdout",
            tier=2,
            parse_error=True,
        )
        return HoldoutResult(
            kind=inputs.kind,
            verdict=HoldoutVerdict.ADVISE,
            summary="reviewer subprocess failed",
            findings=(f"runner error: {type(e).__name__}: {e}",),
            cost_usd=0.0,
            latency_ms=elapsed_ms,
            raw_response="",
            parse_error=f"{type(e).__name__}: {e}",
        )

    cost_usd = float(cost_usd)
    latency_ms = int(latency_ms)

    # Cost cap check happens AFTER the call — the spend already
    # happened. Surfacing it via parse_error lets the caller see the
    # breach without losing the verdict text.
    if cost_usd > inputs.cost_cap_usd:
        logger.warning(
            "holdout.run_holdout: %s reviewer cost $%.4f exceeded cap $%.4f",
            inputs.kind, cost_usd, inputs.cost_cap_usd,
        )
        increment_module_counter(
            "factory.holdout.run_holdout",
            tier=2,
            cost_usd=cost_usd,
            parse_error=True,
        )
        return HoldoutResult(
            kind=inputs.kind,
            verdict=HoldoutVerdict.ADVISE,
            summary="reviewer exceeded per-invocation cost cap",
            findings=(
                f"cost ${cost_usd:.4f} exceeded cap ${inputs.cost_cap_usd:.4f}",
            ),
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            raw_response=response,
            parse_error="cost_cap_exceeded",
        )

    verdict, summary, findings, parse_error = parse_verdict(response)
    # Determinism Spectrum (Sprint #1115): constrained-LLM holdout, Tier 2.
    increment_module_counter(
        "factory.holdout.run_holdout",
        tier=2,
        cost_usd=cost_usd,
        parse_error=bool(parse_error),
    )
    return HoldoutResult(
        kind=inputs.kind,
        verdict=verdict,
        summary=summary,
        findings=findings,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        raw_response=response,
        parse_error=parse_error,
    )


# ── Batch entry point ────────────────────────────────────────────────────


async def run_holdout_batch(
    inputs: tuple[HoldoutInput, ...],
    *,
    runner: HoldoutRunner,
    model: str = "haiku",
) -> tuple[HoldoutResult, ...]:
    """Run multiple holdouts concurrently via :func:`asyncio.gather`.

    Result tuple is in input order; the ``kind`` field on each result
    matches the ``kind`` on the corresponding input so consumers can
    rebuild the mapping defensively.

    The total cost cap is the sum of per-input ``cost_cap_usd`` —
    enforcement is per-input (see :func:`run_holdout`); a single
    breached invocation does not abort the others.
    """
    if not inputs:
        return ()

    # Determinism Spectrum (Sprint #1115): batch dispatch, Tier 2 — record
    # one batch invocation here; per-call counters fire inside run_holdout.
    increment_module_counter("factory.holdout.run_holdout_batch", tier=2)
    coros = [run_holdout(i, runner=runner, model=model) for i in inputs]
    results = await asyncio.gather(*coros)
    return tuple(results)


# ── Reference empty-tools adapter ────────────────────────────────────────


def make_empty_tools_runner(
    claude_runner: object,
    *,
    timeout_s: int = 60,
) -> HoldoutRunner:
    """Wrap a bridge ``ClaudeRunner`` into a :data:`HoldoutRunner`.

    This is the reference adapter — production callers that want to
    speak to a real ``claude -p`` subprocess use this so the
    empty-tools contract is enforced in one place.

    The wrapped runner:
      - calls ``claude_runner.invoke(prompt, ...)`` with
        ``allowed_tools=""`` (empty tool whitelist) — duck-typed: we
        pass the kwarg unconditionally; if the underlying runner
        ignores it, the contract is broken and tests will catch it,
      - enforces ``timeout_s`` via :func:`asyncio.wait_for`,
      - returns ``(response_text, cost_usd, latency_ms)``.

    ``claude_runner`` is intentionally typed ``object`` so this module
    has no hard dependency on ``bridge.claude_runner`` — the holdout
    primitive must remain independently testable.

    Note: the bridge's existing ``ClaudeRunner.invoke`` does not yet
    accept an ``allowed_tools`` kwarg directly (see
    ``claude_runner.py`` ``_build_command``); a future micro-PR will
    plumb the kwarg through. Until then, callers should pass a runner
    whose ``invoke`` honors the empty-tools contract — typically a
    test fake that records the kwarg, or a thin wrapper that injects
    ``--allowedTools=""`` into the argv.
    """

    async def _runner(prompt: str) -> tuple[str, float, int]:
        started = time.monotonic()
        # Duck-typed call. The kwarg is passed so a future-aware runner
        # can act on it; an older runner that doesn't recognise it will
        # raise TypeError, which run_holdout catches and converts to
        # ADVISE — failing loud rather than silently running with tools.
        try:
            invoke = claude_runner.invoke  # type: ignore[attr-defined]
        except AttributeError as e:
            raise RuntimeError(
                "make_empty_tools_runner: claude_runner missing invoke()"
            ) from e

        result = await asyncio.wait_for(
            invoke(prompt, allowed_tools=""),
            timeout=timeout_s,
        )

        # Two return shapes are tolerated:
        #   - tuple (response, cost, latency)
        #   - object with .text / .cost_usd / .latency_ms attributes
        if isinstance(result, tuple) and len(result) == 3:
            response_text, cost_usd, latency_ms = result
            return str(response_text), float(cost_usd), int(latency_ms)

        elapsed_ms = int((time.monotonic() - started) * 1000)
        response_text = getattr(result, "text", "") or getattr(
            result, "response", ""
        ) or ""
        cost_usd = float(getattr(result, "cost_usd", 0.0))
        latency_ms = int(getattr(result, "latency_ms", elapsed_ms))
        return str(response_text), cost_usd, latency_ms

    return _runner
