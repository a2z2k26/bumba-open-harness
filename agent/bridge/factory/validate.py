"""Dark Factory validate workflow — 4 holdout reviewers.

Sprint 14.07 — Plan 14 Phase 4. Sprint 14.03 refactor: per-reviewer
dispatch now delegates to :mod:`bridge.factory.holdout` so the
empty-tools contract lives in one place. The public surface here
(``ReviewerKind``, ``ReviewerResult``, ``ValidateResult``,
``validate_pr``, ``route_validate_outcome``, ``run_validate_for_pr``)
is unchanged — only the internals moved.

Concept-only port of coleam00/dark-factory-experiment (no LICENSE — no
source copy). After Sprint 14.05's ``implement.py`` opens a draft PR and
Sprint 14.06's quality gates pass, this module dispatches **four** parallel
holdout reviewers — each in its own context with no shared state:

    1. behavioral   — does the diff match the issue body's stated ask?
    2. security     — secret leaks, injection, dangerous deps, missing
                      input validation, exposed PII?
    3. code_quality — readability, naming, dead code, missing error
                      handling, deeply nested logic, oversize functions?
    4. test_quality — do new tests cover new code paths? Any gameable
                      tests (``assert True``)? Broken assertions?

Each reviewer is a Claude Haiku subprocess (cost-discipline tier). All four
run in parallel via ``asyncio.gather``. Outputs are aggregated:

  - any reviewer ``block``        → aggregate ``block``
    (caller transitions PR to ``factory:needs-human``)
  - else any ``advise``           → aggregate ``advise``
  - else                          → aggregate ``pass``
    (caller transitions PR to ``factory:awaiting-review``)

Total cost cap: $0.50 per validate run. The pre-call estimate uses
``len(diff_text) // 4`` characters * 4 reviewers as a token-equivalent
upper bound; if the estimate exceeds the cap, the workflow logs a warning
and runs only the two highest-priority reviewers (behavioral + security)
to stay under budget.

Reviewer outputs are STRUCTURED:

    VERDICT: pass|advise|block
    SUMMARY: <one-line explanation>
    FINDINGS:
    - <bullet 1>
    - <bullet 2>

Defensive parsing — malformed output yields ``verdict=advise`` with a
parse-error finding, never a hard failure. The validate gate must remain
fail-soft so a broken reviewer never silently blocks PR progress.

This sprint ships the workflow as a callable function. The wiring into
the factory loop (post-implement seam, comment + label transition) lives
in :func:`route_validate_outcome` and :func:`run_validate_for_pr`. Sprint
14.10 still owns the orchestrator scheduler.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Final, Literal

from bridge.dispatch_metrics import increment_module_counter
from bridge.factory.holdout import (
    HoldoutInput,
    HoldoutResult,
    run_holdout_batch,
)
from bridge.factory.implement import _gh_issue_comment
from bridge.factory.labels import FactoryState, transition_state

logger = logging.getLogger(__name__)


# ── Reviewer kinds + verdict type ────────────────────────────────────────


class ReviewerKind(str, Enum):
    """The four holdout reviewer roles.

    Each kind has a strictly-scoped system prompt. A reviewer that comments
    outside its lane (e.g. behavioral commenting on style) is treated as
    correct in form but silently noisy — the lane scoping in
    :data:`REVIEWER_PROMPTS` is a soft guarantee, not a hard parser check.
    """

    BEHAVIORAL = "behavioral"
    SECURITY = "security"
    CODE_QUALITY = "code_quality"
    TEST_QUALITY = "test_quality"


# Reviewer verdict. ``pass`` = no concerns, ``advise`` = soft issue worth a
# look but not blocking, ``block`` = must not merge as-is.
ReviewVerdict = Literal["pass", "advise", "block"]

_VALID_VERDICTS: Final[frozenset[str]] = frozenset({"pass", "advise", "block"})


# ── Reviewer + aggregate result dataclasses ──────────────────────────────


@dataclass(frozen=True)
class ReviewerResult:
    """One holdout reviewer's verdict on the draft PR.

    Frozen so the aggregator cannot accidentally mutate sibling results.
    """

    kind: ReviewerKind
    verdict: ReviewVerdict
    summary: str
    findings: tuple[str, ...]
    cost_usd: float
    latency_ms: int


@dataclass(frozen=True)
class ValidateResult:
    """Aggregate of all reviewers + the routing decision.

    ``aggregate_verdict`` and ``block_reasons`` are derived from
    ``reviewer_results`` via :func:`aggregate_verdicts`. They are stored on
    the result so callers don't have to re-derive in two places (label
    transition + GitHub comment body).
    """

    reviewer_results: tuple[ReviewerResult, ...]
    aggregate_verdict: ReviewVerdict
    block_reasons: tuple[str, ...]
    total_cost_usd: float


# ── Cost cap + parsing constants ─────────────────────────────────────────


# Hard per-validate cost cap. Reviewers run in parallel so wall-clock is
# bounded by the slowest, but cumulative cost is bounded by this. When the
# pre-call estimate exceeds the cap, the workflow degrades to two reviewers.
COST_CAP_USD: Final[float] = 0.50

# Approximate Haiku $/character for the diff-driven estimate. Haiku 4.5 is
# ~$0.80/MTok input; ~4 chars/token gives ~$0.20/Mchar. We use a slightly
# pessimistic constant so the cap engages before the real charge does.
_HAIKU_USD_PER_CHAR: Final[float] = 2.5e-7

# When the pre-call estimate trips the cap, run only these two reviewers.
# Behavioral + security are the two whose findings we *cannot* recover from
# a later operator review pass; code/test quality are signal-only.
_DEGRADED_KINDS: Final[tuple[ReviewerKind, ReviewerKind]] = (
    ReviewerKind.BEHAVIORAL,
    ReviewerKind.SECURITY,
)


# ── Reviewer prompts (lane-scoped, refuse to drift) ──────────────────────


REVIEWER_PROMPTS: dict[ReviewerKind, str] = {
    ReviewerKind.BEHAVIORAL: (
        "You are the BEHAVIORAL reviewer of a draft pull request. Your only "
        "job is to judge whether the diff implements what the issue body "
        "asks for — nothing more.\n\n"
        "Read the issue body and the diff. Decide:\n"
        "  - pass: the diff plainly resolves the issue's stated ask.\n"
        "  - advise: the diff is partially aligned but misses a stated case.\n"
        "  - block: the diff does not solve the issue's stated problem at all.\n\n"
        "Do NOT comment on code style, security, or test quality. Other "
        "reviewers cover those — staying out of their lane is part of your "
        "job.\n\n"
        "Output EXACTLY this format and nothing else:\n"
        "VERDICT: pass|advise|block\n"
        "SUMMARY: <one-line explanation>\n"
        "FINDINGS:\n"
        "- <specific issue, or 'none' if pass>\n"
    ),
    ReviewerKind.SECURITY: (
        "You are the SECURITY reviewer of a draft pull request. Your only "
        "job is to surface security regressions in the diff.\n\n"
        "Look for: hardcoded secrets, SQL injection, command injection, "
        "dangerous new dependencies, missing input validation at trust "
        "boundaries, exposed PII, weakened authentication or authorization, "
        "rate-limit bypass, governance edits.\n\n"
        "  - pass: no security regressions.\n"
        "  - advise: a soft finding worth a second look but not blocking.\n"
        "  - block: a clear security regression that must not merge.\n\n"
        "Do NOT comment on behavior, code style, or test coverage. Other "
        "reviewers cover those.\n\n"
        "Output EXACTLY this format and nothing else:\n"
        "VERDICT: pass|advise|block\n"
        "SUMMARY: <one-line explanation>\n"
        "FINDINGS:\n"
        "- <specific issue, or 'none' if pass>\n"
    ),
    ReviewerKind.CODE_QUALITY: (
        "You are the CODE-QUALITY reviewer of a draft pull request. Your "
        "only job is to flag readability and maintainability concerns.\n\n"
        "Look for (signal-only, not strict): deeply nested logic, ambiguous "
        "names, dead code, missing error handling, lines longer than 120 "
        "characters, functions longer than 50 lines, obvious bugs.\n\n"
        "  - pass: clean enough to ship.\n"
        "  - advise: stylistic concerns worth a polish pass but not "
        "blocking.\n"
        "  - block: an obvious bug or unmaintainable construct.\n\n"
        "Do NOT comment on behavior, security, or test quality. Other "
        "reviewers cover those.\n\n"
        "Output EXACTLY this format and nothing else:\n"
        "VERDICT: pass|advise|block\n"
        "SUMMARY: <one-line explanation>\n"
        "FINDINGS:\n"
        "- <specific issue, or 'none' if pass>\n"
    ),
    ReviewerKind.TEST_QUALITY: (
        "You are the TEST-QUALITY reviewer of a draft pull request. Your "
        "only job is to judge whether the new tests meaningfully cover the "
        "new code paths.\n\n"
        "Look for: missing tests for new functions, gameable tests "
        "(``assert True``, tautological asserts), tests that don't actually "
        "exercise the new code path, broken assertions, mocked-everything "
        "tests that prove nothing.\n\n"
        "  - pass: tests exercise new behavior meaningfully.\n"
        "  - advise: coverage exists but is thin or has weak assertions.\n"
        "  - block: new code is untested or tests are fundamentally "
        "gameable.\n\n"
        "Do NOT comment on behavior, security, or code style. Other "
        "reviewers cover those.\n\n"
        "Output EXACTLY this format and nothing else:\n"
        "VERDICT: pass|advise|block\n"
        "SUMMARY: <one-line explanation>\n"
        "FINDINGS:\n"
        "- <specific issue, or 'none' if pass>\n"
    ),
}


# ── Reviewer output parsing ──────────────────────────────────────────────


_VERDICT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*VERDICT\s*:\s*(pass|advise|block)\s*$",
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


def _parse_reviewer_output(raw: str) -> tuple[ReviewVerdict, str, tuple[str, ...]]:
    """Parse a reviewer's structured output.

    Returns ``(verdict, summary, findings)``. Defensive: any failure to
    locate VERDICT or SUMMARY yields ``("advise", "reviewer output
    malformed", (parse-error message,))`` so the validate gate stays
    fail-soft. We never let a broken reviewer block a PR.
    """
    if not raw or not raw.strip():
        return (
            "advise",
            "reviewer output malformed",
            ("parse error: empty reviewer output",),
        )

    verdict_match = _VERDICT_RE.search(raw)
    summary_match = _SUMMARY_RE.search(raw)
    if verdict_match is None or summary_match is None:
        missing = []
        if verdict_match is None:
            missing.append("VERDICT")
        if summary_match is None:
            missing.append("SUMMARY")
        return (
            "advise",
            "reviewer output malformed",
            (f"parse error: missing required field(s): {', '.join(missing)}",),
        )

    verdict_str = verdict_match.group(1).strip().lower()
    if verdict_str not in _VALID_VERDICTS:  # pragma: no cover — regex constrains
        return (
            "advise",
            "reviewer output malformed",
            (f"parse error: unrecognized verdict {verdict_str!r}",),
        )

    summary = summary_match.group(1).strip() or "(no summary)"

    findings_section_start = raw.upper().find("FINDINGS")
    if findings_section_start == -1:
        findings: tuple[str, ...] = ()
    else:
        tail = raw[findings_section_start:]
        # Drop the FINDINGS header line itself; re-parse the bullets.
        bullets = tuple(
            m.group(1).strip()
            for m in _FINDING_LINE_RE.finditer(tail)
            if m.group(1).strip().lower() not in {"none", "n/a", "-"}
        )
        findings = bullets

    return verdict_str, summary, findings  # type: ignore[return-value]


# ── Aggregation ──────────────────────────────────────────────────────────


def aggregate_verdicts(
    results: tuple[ReviewerResult, ...],
) -> tuple[ReviewVerdict, tuple[str, ...]]:
    """Compute aggregate verdict + block_reasons from per-reviewer results.

    Rules:
      - any ``block`` → aggregate ``block``;
        ``block_reasons`` = one ``"<kind>: <summary>"`` entry per blocking
        reviewer (preserves the input order so the GitHub comment lists
        them deterministically).
      - else any ``advise`` → ``advise``; ``block_reasons`` is empty.
      - else (all ``pass``, including the empty-results edge case) →
        ``pass``; ``block_reasons`` is empty.
    """
    blockers = tuple(r for r in results if r.verdict == "block")
    if blockers:
        return "block", tuple(f"{r.kind.value}: {r.summary}" for r in blockers)

    if any(r.verdict == "advise" for r in results):
        return "advise", ()

    return "pass", ()


# ── Reviewer dispatch ────────────────────────────────────────────────────


# A runner is anything that takes (prompt, model) and returns either
# (response_text, cost_usd, latency_ms) directly or an awaitable thereof.
# The async signature is the production path (Claude subprocess). The sync
# path is offered so tests can pass a plain callable.
RunnerCallable = Callable[
    ...,
    "Awaitable[tuple[str, float, int]] | tuple[str, float, int]",
]


_REVIEWER_USER_TEMPLATE: Final[str] = (
    "Issue body:\n{issue_body}\n\n"
    "Pull request URL: {pr_url}\n\n"
    "Diff:\n```\n{diff_text}\n```\n"
)


async def run_reviewer(
    kind: ReviewerKind,
    *,
    issue_body: str,
    pr_url: str,
    diff_text: str,
    runner: RunnerCallable,
) -> ReviewerResult:
    """Run one holdout reviewer.

    The reviewer sees only: the system prompt for its kind, the issue
    body, the PR URL, the diff. It does NOT see other reviewers' prompts,
    sessions, or verdicts — that's the holdout invariant.

    The runner callable handles the actual Claude subprocess (or test
    fake). It receives the full prompt and the model hint ``"haiku"``;
    it returns ``(response_text, cost_usd, latency_ms)`` either
    synchronously or as an awaitable. The runner — not us — is responsible
    for OAuth, timeouts, and cost tracking.

    Defensive: any runner exception is caught and converted into an
    ``advise`` verdict with a finding describing the failure. Validate is
    a fail-soft gate.
    """
    system_prompt = REVIEWER_PROMPTS[kind]
    user_prompt = _REVIEWER_USER_TEMPLATE.format(
        issue_body=issue_body or "(no issue body)",
        pr_url=pr_url or "(no PR url)",
        diff_text=diff_text or "(empty diff)",
    )
    full_prompt = f"{system_prompt}\n---\n{user_prompt}"

    started = time.monotonic()
    try:
        result = runner(full_prompt, model="haiku")
        if asyncio.iscoroutine(result):
            response, cost_usd, latency_ms = await result
        else:
            response, cost_usd, latency_ms = result  # type: ignore[misc]
    except Exception as e:  # noqa: BLE001 — fail-soft on any runner error
        latency_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "validate.run_reviewer: %s reviewer raised %s — degrading to advise",
            kind.value, e,
        )
        return ReviewerResult(
            kind=kind,
            verdict="advise",
            summary="reviewer subprocess failed",
            findings=(f"runner error: {type(e).__name__}: {e}",),
            cost_usd=0.0,
            latency_ms=latency_ms,
        )

    verdict, summary, findings = _parse_reviewer_output(response)
    return ReviewerResult(
        kind=kind,
        verdict=verdict,
        summary=summary,
        findings=findings,
        cost_usd=float(cost_usd),
        latency_ms=int(latency_ms),
    )


def _estimate_total_cost(diff_text: str, n_reviewers: int) -> float:
    """Pre-call estimate of total reviewer cost, in USD.

    ``len(diff_text) // 4`` chars-per-token-equivalent * n_reviewers *
    Haiku $/char. The estimate is an upper bound — real cost is usually
    lower because Haiku output is short.
    """
    return float(len(diff_text)) * _HAIKU_USD_PER_CHAR * n_reviewers


def _build_reviewer_prompt(
    kind: ReviewerKind,
    *,
    issue_body: str,
    pr_url: str,
    diff_text: str,
) -> str:
    """Build the full system+user prompt for one reviewer kind.

    Extracted so :func:`validate_pr` can hand individual prompts to the
    holdout primitive (which is prompt-agnostic) and so :func:`run_reviewer`
    keeps its existing inline path for direct callers.
    """
    system_prompt = REVIEWER_PROMPTS[kind]
    user_prompt = _REVIEWER_USER_TEMPLATE.format(
        issue_body=issue_body or "(no issue body)",
        pr_url=pr_url or "(no PR url)",
        diff_text=diff_text or "(empty diff)",
    )
    return f"{system_prompt}\n---\n{user_prompt}"


# Per-reviewer cost cap used when dispatching through the holdout
# primitive. Four reviewers × $0.125 = the documented $0.50 total cap.
# The total budget is enforced upstream via :func:`_estimate_total_cost`
# (degrades to two reviewers when the estimate trips the cap); this
# per-input cap is the defensive backstop on the primitive side so a
# single runaway reviewer cannot blow the budget single-handed.
_PER_REVIEWER_COST_CAP_USD: Final[float] = COST_CAP_USD / float(len(ReviewerKind))


def _holdout_to_reviewer_result(
    kind: ReviewerKind, hr: HoldoutResult,
) -> ReviewerResult:
    """Convert the primitive's :class:`HoldoutResult` back to the
    validate-public :class:`ReviewerResult` shape.

    ``parse_error`` from the primitive becomes a finding so callers
    inspecting ``ReviewerResult.findings`` see the failure mode without
    needing the primitive's enriched envelope.
    """
    findings = hr.findings
    if hr.parse_error and not any(
        hr.parse_error in f for f in findings
    ):
        findings = findings + (f"holdout: {hr.parse_error}",)
    return ReviewerResult(
        kind=kind,
        verdict=hr.verdict.value,  # type: ignore[arg-type]
        summary=hr.summary,
        findings=findings,
        cost_usd=hr.cost_usd,
        latency_ms=hr.latency_ms,
    )


async def validate_pr(
    *,
    issue_body: str,
    pr_url: str,
    diff_text: str,
    runner: RunnerCallable,
) -> ValidateResult:
    """Run all four reviewers in parallel; aggregate; return ValidateResult.

    Cost discipline:
      - Pre-call estimate uses :func:`_estimate_total_cost` against four
        reviewers. If the estimate exceeds :data:`COST_CAP_USD`, the
        workflow degrades to behavioral + security only (skipping code +
        test quality) and logs a warning.
      - Real cost is summed from the reviewer results. The cap engages
        BEFORE the call, never partway through — once dispatched, every
        reviewer runs to completion.
      - Each reviewer also carries a per-input
        :data:`_PER_REVIEWER_COST_CAP_USD` (= total cap / n_reviewers)
        enforced by :func:`bridge.factory.holdout.run_holdout`. A
        breached per-reviewer cap surfaces as ``ADVISE`` with a
        ``holdout: cost_cap_exceeded`` finding rather than aborting
        siblings.

    Edge case: if ``runner`` is somehow passed but no reviewers fire (e.g.
    a future override sets the kind list to empty), the function returns
    ``ValidateResult(reviewer_results=(), aggregate_verdict="pass",
    block_reasons=(), total_cost_usd=0.0)`` — empty input is treated as
    no-blockers-found per the aggregator's rules.

    Sprint 14.03 refactor: dispatches via
    :func:`bridge.factory.holdout.run_holdout_batch`. The legacy
    validate-style runner ``(prompt, model) -> (text, cost, latency)``
    is adapted to the holdout-style runner ``(prompt) -> (text, cost,
    latency)`` inline so existing callers and tests are unchanged.
    """
    estimate = _estimate_total_cost(diff_text, n_reviewers=len(ReviewerKind))
    if estimate > COST_CAP_USD:
        logger.warning(
            "validate_pr: estimated cost $%.4f exceeds cap $%.2f — "
            "degrading to behavioral + security only",
            estimate, COST_CAP_USD,
        )
        kinds_to_run: tuple[ReviewerKind, ...] = _DEGRADED_KINDS
    else:
        kinds_to_run = tuple(ReviewerKind)

    if not kinds_to_run:
        increment_module_counter(
            "factory.validate.validate_pr",
            tier=2,
            cost_usd=0.0,
        )
        return ValidateResult(
            reviewer_results=(),
            aggregate_verdict="pass",
            block_reasons=(),
            total_cost_usd=0.0,
        )

    # Adapt the validate-style runner (takes prompt + model kwarg) to the
    # holdout-style runner (takes prompt only). The model hint stays
    # "haiku" for cost discipline. Sync runners are still tolerated:
    # asyncio.iscoroutine on the result short-circuits the await.
    async def _holdout_runner(prompt: str) -> tuple[str, float, int]:
        result = runner(prompt, model="haiku")
        if asyncio.iscoroutine(result):
            response, cost_usd, latency_ms = await result
        else:
            response, cost_usd, latency_ms = result  # type: ignore[misc]
        return response, float(cost_usd), int(latency_ms)

    inputs = tuple(
        HoldoutInput(
            kind=kind.value,
            prompt=_build_reviewer_prompt(
                kind,
                issue_body=issue_body,
                pr_url=pr_url,
                diff_text=diff_text,
            ),
            cost_cap_usd=_PER_REVIEWER_COST_CAP_USD,
        )
        for kind in kinds_to_run
    )
    holdout_results = await run_holdout_batch(inputs, runner=_holdout_runner)

    # Re-attach the original ReviewerKind enum (the primitive returns
    # the string label only) and normalize the parse_error surface.
    results: tuple[ReviewerResult, ...] = tuple(
        _holdout_to_reviewer_result(kind, hr)
        for kind, hr in zip(kinds_to_run, holdout_results)
    )

    aggregate_verdict, block_reasons = aggregate_verdicts(results)
    total_cost = sum(r.cost_usd for r in results)

    # Determinism Spectrum (Sprint #1115): constrained-LLM batch, Tier 2.
    increment_module_counter(
        "factory.validate.validate_pr",
        tier=2,
        cost_usd=total_cost,
    )

    return ValidateResult(
        reviewer_results=results,
        aggregate_verdict=aggregate_verdict,
        block_reasons=block_reasons,
        total_cost_usd=total_cost,
    )


# ── Factory-loop wiring ──────────────────────────────────────────────────


def _build_review_comment(result: ValidateResult) -> str:
    """Render a Markdown comment summarizing all reviewers' verdicts.

    Posted on the issue when validate finishes. The comment is the audit
    trail — operators reading the issue see exactly which reviewer said
    what before the label transition happened.
    """
    lines = [
        "**Factory validate** — 4-reviewer holdout gate",
        "",
        f"Aggregate verdict: `{result.aggregate_verdict}` "
        f"(spent ${result.total_cost_usd:.4f}).",
        "",
    ]
    for r in result.reviewer_results:
        lines.append(f"### {r.kind.value} → `{r.verdict}`")
        lines.append(r.summary)
        if r.findings:
            lines.append("")
            for f in r.findings:
                lines.append(f"- {f}")
        lines.append("")
    if result.block_reasons:
        lines.append("**Blocking reasons:**")
        for reason in result.block_reasons:
            lines.append(f"- {reason}")
        lines.append("")
    lines.append("---")
    lines.append("_concept-only-no-license — Dark Factory_")
    return "\n".join(lines)


# Sprint 14 hasn't yet added an AWAITING_REVIEW state, so we re-use the
# existing NEEDS_REVIEW slot for the pass / advise outcome. The label IS
# the state — reusing NEEDS_REVIEW means the operator review queue is
# untouched. Sprint 14.08 (synthesizer) is where AWAITING_REVIEW will
# eventually land if it's needed.
_PASS_TARGET_STATE: Final[FactoryState] = FactoryState.NEEDS_REVIEW
_BLOCK_TARGET_STATE: Final[FactoryState] = FactoryState.NEEDS_HUMAN


def route_validate_outcome(
    *,
    issue_number: int,
    result: ValidateResult,
    repo: str,
) -> FactoryState:
    """Apply the validate outcome to the GitHub label state machine.

    On ``block``: post a comment listing all reviewer summaries and the
    block reasons, then transition the issue to ``factory:needs-human``.

    On ``pass`` / ``advise``: post the same comment (operators still want
    to see the reviewer audit trail) and transition to
    ``factory:needs-review`` (PR is awaiting operator review).

    Returns the target state actually applied. Best-effort: a transition
    failure logs but doesn't raise — the comment is still posted so the
    operator sees the verdict regardless.
    """
    target = (
        _BLOCK_TARGET_STATE
        if result.aggregate_verdict == "block"
        else _PASS_TARGET_STATE
    )

    body = _build_review_comment(result)
    _gh_issue_comment(issue_number, body, repo=repo)

    transitioned = False
    for prior in (FactoryState.IN_PROGRESS, FactoryState.NEEDS_REVIEW):
        try:
            if transition_state(issue_number, prior, target):
                transitioned = True
                break
        except Exception as e:  # pragma: no cover — gh errors logged, not fatal
            logger.warning(
                "validate: transition_state %s→%s failed on #%s: %s",
                prior.value, target.value, issue_number, e,
            )
    if not transitioned:
        logger.warning(
            "validate: could not transition #%s to %s (already moved?)",
            issue_number, target.value,
        )
    return target


async def run_validate_for_pr(
    *,
    issue_number: int,
    issue_body: str,
    pr_url: str,
    diff_text: str,
    runner: RunnerCallable,
    repo: str,
    config_enabled: bool = True,
) -> ValidateResult | None:
    """Top-level seam called from the factory loop after implement opens
    a draft PR.

    When ``config_enabled`` is False (the default for
    ``BridgeConfig.factory_validate_enabled``), the workflow short-circuits
    and returns ``None`` without dispatching reviewers. The orchestrator
    (Sprint 14.10) is responsible for the flag-flip discipline — this
    function is the inert call site until then.
    """
    if not config_enabled:
        logger.debug(
            "run_validate_for_pr: feature flag OFF — skipping reviewers for #%s",
            issue_number,
        )
        return None

    result = await validate_pr(
        issue_body=issue_body,
        pr_url=pr_url,
        diff_text=diff_text,
        runner=runner,
    )
    route_validate_outcome(
        issue_number=issue_number,
        result=result,
        repo=repo,
    )
    return result
