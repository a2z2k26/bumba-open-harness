"""Holdout validator subprocess for the experiment loop (Sprint 02.14, issue #989).

Spec: ``docs/specs/2026-04-25-reference-audit/spec-02-14-add-holdout-validator-subprocess-judges-diff-vs-program-from.md``

The experiment loop already runs pytest + ruff + mypy gates after each
iteration (see ``experiment_loop.validate_experiment`` and
``experiment_quality_gates.run_quality_gates`` shipped in PR #1142). What
those gates can't tell us is whether a green diff is a *meaningful*
improvement. The holdout validator slots in after the quality gates pass:
a fresh-context Claude subprocess with empty tool list reads the
proposal, the diff, and the program SHA from ``origin/main``, then emits
a structured verdict — improvement / noise / regression / unsure.

This module reuses the bridge-side holdout primitive
(``bridge.factory.holdout``) for the runner contract, parsing
machinery, and fail-soft posture, but stays an independent script-level
module so the experiment loop has zero coupling to the factory's PR-
review pipeline. The verdict shape here is experiment-loop specific
(four-valued) rather than the factory's three-valued PASS/ADVISE/BLOCK,
so we keep our own ``HoldoutValidatorVerdict`` enum and parser.

# Empty-tools contract

The validator subprocess MUST run with no MCP tools, no bash, no file
system access. That contract is enforced by the caller-supplied runner
(see ``factory.holdout.make_empty_tools_runner`` for the reference
adapter that wires ``allowed_tools=""`` into ``ClaudeRunner.invoke``).
``run_validator`` does not invoke claude itself; it inspects what the
runner returned.

# Cost discipline

Each ``ValidatorInput`` carries its own ``cost_cap_usd`` (default
$0.30). When the runner reports a cost above the cap, we surface it as
``parse_error="cost_cap_exceeded"`` with the verdict pinned to
``UNSURE`` so the caller sees the breach without silent loss. The cap
is defensive — the spend already happened by the time we see the
report — but it gives the iteration a structured signal to discard the
verdict rather than let it influence the merge decision.

# Fail-soft

Validator failure must NEVER block iteration progress. Every exception
path (runner raises, parse fails, cost cap trips, subprocess for the
SHA lookup fails) returns ``UNSURE`` with a populated ``parse_error``.
``experiment_loop`` wraps the call in its own try/except as a belt-and-
suspenders measure.
"""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Final, Optional

try:
    # Sprint #1115 determinism counters — best-effort, the validator
    # script also runs standalone where ``bridge`` may not be importable.
    from bridge.dispatch_metrics import increment_module_counter as _z4_count
except Exception:  # pragma: no cover — standalone script execution
    def _z4_count(*_a, **_kw):  # type: ignore[no-redef]
        return None

logger = logging.getLogger(__name__)


# ── Verdict enum ────────────────────────────────────────────────────────


class HoldoutValidatorVerdict(str, Enum):
    """Four-valued verdict from a holdout validator invocation.

    ``IMPROVEMENT`` — diff is a genuine improvement; proceed to merge.
    ``NOISE`` — diff is harmless but doesn't move the needle; discard.
    ``REGRESSION`` — diff hides a regression behind green tests; discard.
    ``UNSURE`` — model couldn't decide, OR the validator failed open.
    """

    IMPROVEMENT = "improvement"
    NOISE = "noise"
    REGRESSION = "regression"
    UNSURE = "unsure"


_VALID_VERDICT_STRINGS: Final[frozenset[str]] = frozenset(
    {v.value for v in HoldoutValidatorVerdict}
)


# ── Input + result envelopes ────────────────────────────────────────────


@dataclass(frozen=True)
class ValidatorInput:
    """Inputs to one validator invocation.

    Frozen so callers cannot mutate after construction — the validator
    runs against a stable snapshot of the iteration state.
    """

    iter_id: str
    issue_body: str
    diff_text: str
    program_origin_sha: str
    cost_cap_usd: float = 0.30
    timeout_s: int = 90


@dataclass(frozen=True)
class ValidatorResult:
    """Structured result from one validator invocation.

    ``parse_error`` is set when:
      - the model output could not be parsed,
      - the runner raised before producing output,
      - the runner-reported cost exceeded ``input.cost_cap_usd``.

    In all three cases the verdict is :data:`HoldoutValidatorVerdict.UNSURE`
    so the experiment loop stays fail-soft. Strict consumers can branch
    on ``parse_error is not None``.
    """

    iter_id: str
    verdict: HoldoutValidatorVerdict
    summary: str
    findings: tuple[str, ...]
    cost_usd: float
    latency_ms: int
    raw_response: str
    parse_error: Optional[str] = None


# ── Runner protocol ──────────────────────────────────────────────────────


# A runner takes a prompt and returns ``(response_text, cost_usd, latency_ms)``.
# The runner is responsible for everything subprocess-related and MUST
# enforce the empty-tools contract; the validator only inspects what it
# returns. See ``bridge.factory.holdout.make_empty_tools_runner`` for the
# reference adapter — production callers reuse it directly.
ValidatorRunner = Callable[[str], Awaitable[tuple[str, float, int]]]


# ── Prompt template ─────────────────────────────────────────────────────


PROMPT_TEMPLATE = """\
You are reviewing a proposed code change from an autonomous experiment loop.
The loop's job is to make small improvements to the codebase without breaking things.
Your job: classify whether this diff is a genuine improvement, harmless-but-noise,
a hidden regression, or you're unsure.

# Context
- Origin/main SHA at validation time: {program_origin_sha}
- Iteration ID: {iter_id}

# The proposal (what the loop set out to do)
{issue_body}

# The diff
{diff_text}

# Output format (strict)
VERDICT: improvement|noise|regression|unsure
SUMMARY: <one sentence>
FINDINGS:
- <specific observation 1>
- <specific observation 2>
"""


def build_prompt(inputs: ValidatorInput) -> str:
    """Render the strict-format prompt for ``inputs``.

    Pulled out as a free function so tests can assert on prompt shape
    without touching the runner.
    """
    return PROMPT_TEMPLATE.format(
        program_origin_sha=inputs.program_origin_sha,
        iter_id=inputs.iter_id,
        issue_body=inputs.issue_body,
        diff_text=inputs.diff_text,
    )


# ── Verdict parsing ──────────────────────────────────────────────────────


_VERDICT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*VERDICT\s*:\s*(improvement|noise|regression|unsure)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SUMMARY_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*SUMMARY\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FINDING_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*[-*]\s+(.+?)\s*$",
    re.MULTILINE,
)


def parse_validator_output(
    raw: str,
) -> tuple[HoldoutValidatorVerdict, str, tuple[str, ...], Optional[str]]:
    """Parse a structured validator response.

    Expected shape::

        VERDICT: improvement|noise|regression|unsure
        SUMMARY: <one sentence>
        FINDINGS:
        - <observation 1>
        - <observation 2>

    Returns ``(verdict, summary, findings, parse_error)``. On any parse
    problem returns ``(UNSURE, "<diagnostic>", (), error_message)`` so
    callers stay fail-soft. Empty input → ``UNSURE`` with a
    "empty validator output" parse error.
    """
    if not raw or not raw.strip():
        return (
            HoldoutValidatorVerdict.UNSURE,
            "validator output malformed",
            (),
            "parse error: empty validator output",
        )

    verdict_match = _VERDICT_RE.search(raw)
    if verdict_match is None:
        return (
            HoldoutValidatorVerdict.UNSURE,
            "validator output malformed",
            (),
            "parse error: missing VERDICT line",
        )

    verdict_str = verdict_match.group(1).strip().lower()
    if verdict_str not in _VALID_VERDICT_STRINGS:  # pragma: no cover — regex constrains
        return (
            HoldoutValidatorVerdict.UNSURE,
            "validator output malformed",
            (),
            f"parse error: unrecognized verdict {verdict_str!r}",
        )
    verdict = HoldoutValidatorVerdict(verdict_str)

    # Summary: prefer an explicit ``SUMMARY:`` line, fall back to the
    # first non-empty non-bullet line after the verdict.
    summary_match = _SUMMARY_RE.search(raw)
    if summary_match is not None:
        summary = summary_match.group(1).strip()
    else:
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
        summary_candidates = [
            ln for ln in summary_lines
            if not _FINDING_LINE_RE.match(ln)
            and not ln.upper().startswith("SUMMARY")
        ]
        summary = summary_candidates[0] if summary_candidates else "(no summary)"

    # Findings: bullets after the FINDINGS header. Drop "none" / "n/a".
    findings_pos = raw.upper().find("FINDINGS")
    findings_region = raw[findings_pos:] if findings_pos != -1 else raw
    findings = tuple(
        m.group(1).strip()
        for m in _FINDING_LINE_RE.finditer(findings_region)
        if m.group(1).strip().lower() not in {"none", "n/a", "-"}
    )

    return verdict, summary, findings, None


# ── Single-invocation entry point ────────────────────────────────────────


async def run_validator(
    inputs: ValidatorInput,
    *,
    runner: ValidatorRunner,
    model: str = "haiku",
) -> ValidatorResult:
    """Run one validator invocation through the supplied runner.

    The validator does not invoke claude itself; the runner does. The
    runner MUST enforce the empty-tools contract — production callers
    use ``bridge.factory.holdout.make_empty_tools_runner`` to wrap a
    ``ClaudeRunner`` with ``allowed_tools=""``.

    Defensive: any runner exception (including
    :class:`asyncio.TimeoutError`) becomes an ``UNSURE`` result with
    ``parse_error`` describing the failure. A runner that reports
    ``cost_usd`` above ``inputs.cost_cap_usd`` gets the same treatment,
    with ``parse_error="cost_cap_exceeded"``.
    """
    prompt = build_prompt(inputs)
    started = time.monotonic()
    try:
        response, cost_usd, latency_ms = await runner(prompt)
    except asyncio.TimeoutError as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "experiment holdout validator: iter %s timed out after %dms",
            inputs.iter_id, elapsed_ms,
        )
        return ValidatorResult(
            iter_id=inputs.iter_id,
            verdict=HoldoutValidatorVerdict.UNSURE,
            summary="validator subprocess timed out",
            findings=(f"timeout: {e}" if str(e) else "timeout: no message",),
            cost_usd=0.0,
            latency_ms=elapsed_ms,
            raw_response="",
            parse_error=f"asyncio.TimeoutError: {e}",
        )
    except Exception as e:  # noqa: BLE001 — fail-soft on any runner error
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "experiment holdout validator: iter %s runner raised %s",
            inputs.iter_id, e,
        )
        return ValidatorResult(
            iter_id=inputs.iter_id,
            verdict=HoldoutValidatorVerdict.UNSURE,
            summary="validator subprocess failed",
            findings=(f"runner error: {type(e).__name__}: {e}",),
            cost_usd=0.0,
            latency_ms=elapsed_ms,
            raw_response="",
            parse_error=f"{type(e).__name__}: {e}",
        )

    cost_usd = float(cost_usd)
    latency_ms = int(latency_ms)

    if cost_usd > inputs.cost_cap_usd:
        logger.warning(
            "experiment holdout validator: iter %s cost $%.4f exceeded cap $%.4f",
            inputs.iter_id, cost_usd, inputs.cost_cap_usd,
        )
        return ValidatorResult(
            iter_id=inputs.iter_id,
            verdict=HoldoutValidatorVerdict.UNSURE,
            summary="validator exceeded per-invocation cost cap",
            findings=(
                f"cost ${cost_usd:.4f} exceeded cap ${inputs.cost_cap_usd:.4f}",
            ),
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            raw_response=response,
            parse_error="cost_cap_exceeded",
        )

    verdict, summary, findings, parse_error = parse_validator_output(response)
    # Determinism Spectrum (Sprint #1115): constrained-LLM, Tier 2.
    _z4_count(
        "experiment_holdout_validator.run_validator",
        tier=2,
        cost_usd=cost_usd,
        parse_error=bool(parse_error),
    )
    return ValidatorResult(
        iter_id=inputs.iter_id,
        verdict=verdict,
        summary=summary,
        findings=findings,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        raw_response=response,
        parse_error=parse_error,
    )


# ── Origin/main SHA lookup ───────────────────────────────────────────────


def get_origin_main_sha(*, cwd: Optional[str] = None) -> str:
    """Return the SHA of ``origin/main`` for cross-referencing verdicts.

    Used by the experiment loop to stamp each verdict with the version
    of the program contract that was authoritative at validation time.
    Returns ``"unknown"`` on any subprocess failure — the loop already
    treats verdicts as advisory, so a missing SHA never blocks merge.

    ``cwd`` is the git repo to query; defaults to the current working
    directory which (under the experiment loop) is the source repo root.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("get_origin_main_sha: %s — returning 'unknown'", e)
        return "unknown"
    except Exception as e:  # noqa: BLE001 — fail-soft, validator is advisory
        logger.warning("get_origin_main_sha: %s — returning 'unknown'", e)
        return "unknown"

    if proc.returncode != 0:
        logger.warning(
            "get_origin_main_sha: git exit %d, stderr=%s",
            proc.returncode, proc.stderr.strip()[:200],
        )
        return "unknown"

    sha = proc.stdout.strip()
    return sha if sha else "unknown"
