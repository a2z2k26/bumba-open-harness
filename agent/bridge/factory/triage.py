"""Dark Factory triage workflow.

Sprint 14.04 — Plan 14 Phase 2.

Concept-only port of coleam00/dark-factory-experiment (no LICENSE — no source
copied). Two-step triage:

  1. Read open issues with both `factory:opt-in` and `factory:untriaged`
     labels via `gh issue list --json`.
  2. For each issue (capped at `max_issues`), spawn a Claude subprocess
     (Sonnet, no tools, structured JSON output) to classify it. Apply the
     resulting state via `transition_state` from `bridge.factory.labels` and
     leave a rationale comment via `gh issue comment`.

The triage is **pure classification** — it does not generate code. Sprint
14.05 owns the implement workflow.

Verdicts (`FactoryState`):
  - ACCEPTED       — clearly in scope, ready for the implement workflow
  - REJECTED       — out of scope, ill-formed, or fails policy gates
  - RATE_LIMITED   — overflow above `max_issues` per run; retried next run
  - NEEDS_HUMAN    — Claude couldn't produce parseable JSON, or non-zero exit

Cost cap: $0.05 per `classify_issue` call. The cap is informational — when a
single call exceeds it, the verdict still ships but a warning is logged. The
orchestrator (Sprint 14.10) is responsible for hard-stopping a run that drains
the daily factory budget.

This sprint ships the workflow as a callable function. There is **no
orchestration call site yet**; Sprint 14.10 wires `factory_orchestrator.py`.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Literal

from bridge.backends import BackendProtocol, spawn_one_shot
from bridge.factory.labels import (
    FACTORY_OPT_IN_LABEL,
    FactoryState,
    transition_state,
)

logger = logging.getLogger(__name__)


# ── Configuration constants ─────────────────────────────────────────────


# Default repo. Overridable per-call so tests don't accidentally hit a live
# remote and to allow the factory to be reused across repos in future plans.
DEFAULT_REPO: Final[str] = "your-org/bumba-open-harness"

# Per-classify-call cost cap. When exceeded, the verdict is still applied but
# a warning is logged. The hard daily cap lives upstream in the orchestrator.
COST_CAP_USD: Final[float] = 0.05

# Subprocess timeout — Claude classification has no tool calls, so a 120s
# ceiling is generous. We don't want this to be the long-poll on a stuck run.
CLAUDE_TIMEOUT_SEC: Final[int] = 120

# Default Claude binary path. Set BUMBA_CLAUDE_BIN when the CLI is not on PATH.
CLAUDE_BIN: Final[Path] = Path(os.environ.get("BUMBA_CLAUDE_BIN", "claude"))

Complexity = Literal["small", "medium", "large", "out-of-scope"]


# Maps the structured state-string the prompt asks Claude to return back to
# the FactoryState enum. Anything else falls through to NEEDS_HUMAN.
_STATE_NAME_TO_ENUM: Final[dict[str, FactoryState]] = {
    "accepted": FactoryState.ACCEPTED,
    "rejected": FactoryState.REJECTED,
    "rate-limited": FactoryState.RATE_LIMITED,
    "needs-human": FactoryState.NEEDS_HUMAN,
}


# ── Verdict dataclass ───────────────────────────────────────────────────


@dataclass(frozen=True)
class TriageVerdict:
    """Frozen record of one triage decision.

    Immutable so the orchestrator can fan out verdicts safely; one workflow
    run produces an append-only list.
    """

    issue_number: int
    state: FactoryState
    category: str
    complexity: Complexity
    reasoning: str
    cost_usd: float
    evaluated_at: datetime


# ── Prompt template ─────────────────────────────────────────────────────


_TRIAGE_PROMPT_TEMPLATE: Final[str] = """\
You are the triage stage of a self-managing GitHub issue factory. Classify
ONE GitHub issue and return a single JSON object — nothing else, no prose,
no code fences.

Allowed states (pick exactly one):
  - "accepted"     — in scope, ready for an implementation pass
  - "rejected"     — out of scope, ill-formed, duplicate, or fails policy
  - "rate-limited" — valid but should be deferred; we are over capacity
  - "needs-human"  — ambiguous; operator must decide

Allowed categories: "bug-fix", "feature", "refactor", "docs", "test", "infra"
Allowed complexity: "small", "medium", "large", "out-of-scope"

Issue #{issue_number}
Title: {title}

Body:
{body}

Existing labels: {labels}

Return JSON with EXACTLY these keys:
  {{
    "state": "accepted" | "rejected" | "rate-limited" | "needs-human",
    "category": "bug-fix" | "feature" | "refactor" | "docs" | "test" | "infra",
    "complexity": "small" | "medium" | "large" | "out-of-scope",
    "reasoning": "<= 500 chars explaining why"
  }}
"""


# ── gh helpers (separately patchable for tests) ─────────────────────────


def _run_subprocess(args: list[str], *, input_text: str | None = None,
                     timeout: int | None = None) -> tuple[int, str, str]:
    """Run a command synchronously. Returns (returncode, stdout, stderr).

    Isolated for clean test patching. Synchronous because triage is a batch
    job — there's nothing to interleave.
    """
    proc = subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _gh_issue_view(issue_number: int, repo: str) -> dict:
    """Fetch issue title, body, labels via `gh issue view`.

    Raises:
        RuntimeError: gh failed or returned malformed JSON.
    """
    rc, stdout, stderr = _run_subprocess(
        [
            "gh", "issue", "view", str(issue_number),
            "--repo", repo,
            "--json", "title,body,labels",
        ]
    )
    if rc != 0:
        raise RuntimeError(
            f"`gh issue view {issue_number}` failed (exit {rc}): "
            f"{stderr.strip()[:300]}"
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Could not parse `gh issue view {issue_number}` JSON: {e}"
        ) from e


def _gh_issue_list_untriaged(repo: str, limit: int) -> list[int]:
    """List open issue numbers with both `factory:opt-in` AND `factory:untriaged`.

    `gh issue list` ANDs labels passed via repeated `--label` flags.
    """
    rc, stdout, stderr = _run_subprocess(
        [
            "gh", "issue", "list",
            "--repo", repo,
            "--state", "open",
            "--label", FACTORY_OPT_IN_LABEL,
            "--label", FactoryState.UNTRIAGED.value,
            "--limit", str(limit),
            "--json", "number",
        ]
    )
    if rc != 0:
        raise RuntimeError(
            f"`gh issue list` failed (exit {rc}): {stderr.strip()[:300]}"
        )
    try:
        payload = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Could not parse `gh issue list` JSON: {e}") from e

    return [int(entry["number"]) for entry in payload if "number" in entry]


def _gh_issue_comment(issue_number: int, body: str, repo: str) -> None:
    """Post a comment on an issue.

    Best-effort: comment failure logs a warning but does NOT roll back the
    state transition. The state label IS the durable record; the comment
    is operator-facing audit context.
    """
    rc, _stdout, stderr = _run_subprocess(
        [
            "gh", "issue", "comment", str(issue_number),
            "--repo", repo,
            "--body", body,
        ]
    )
    if rc != 0:
        logger.warning(
            "triage: failed to comment on #%s (exit %s): %s",
            issue_number, rc, stderr.strip()[:300],
        )


def _gh_issue_add_label(issue_number: int, label: str, repo: str) -> None:
    """Add a label without removing anything.

    Used for rate-limit overflow — we don't transition out of UNTRIAGED on
    overflow, we just decorate so the next run can defer them.
    """
    rc, _stdout, stderr = _run_subprocess(
        [
            "gh", "issue", "edit", str(issue_number),
            "--repo", repo,
            "--add-label", label,
        ]
    )
    if rc != 0:
        logger.warning(
            "triage: failed to add label %s on #%s (exit %s): %s",
            label, issue_number, rc, stderr.strip()[:300],
        )


# ── Claude subprocess invocation ────────────────────────────────────────


def _load_oauth_token() -> str | None:
    """Read the Claude OAuth token from the runtime secrets file.

    Mirrors `scripts/experiment_loop.py` so the factory uses the same auth
    path the bridge daemon does. Returns None if absent — caller still tries
    invoking `claude -p`, which will fail loudly via non-zero exit.
    """
    secrets_path = Path("/opt/bumba-harness/data/.secrets")
    if not secrets_path.exists():
        return None
    try:
        for line in secrets_path.read_text().splitlines():
            if line.startswith("claude_oauth_token="):
                return line.split("=", 1)[1].strip()
    except OSError as e:
        logger.warning("triage: could not read .secrets: %s", e)
    return None


def _invoke_claude(
    prompt: str, *, backend: BackendProtocol | None = None
) -> tuple[int, str, str]:
    """Spawn a no-tools, structured-output one-shot classification call.

    Returns (returncode, stdout, stderr). Raises subprocess.TimeoutExpired
    on timeout — the caller treats that as a NEEDS_HUMAN verdict.

    P4.02 decoupling: ``backend`` is an OPTIONAL seam. When None (default),
    the byte-identical legacy argv is used — ``--output-format text``,
    ``--max-turns 0`` — because the classifier parses plain-text stdout as
    JSON, which the stream-json shape of ``backend.build_command`` would
    break. When a backend IS supplied, the call routes through
    ``spawn_one_shot`` so a future BackendRegistry wire-in can swap the CLI
    without touching this site. ``spawn_one_shot`` (P4.01) is intentionally
    off the hot path today; it is the seam's destination, not dead code.
    """
    oauth_token = _load_oauth_token()

    if backend is not None:
        extra_env: dict[str, str] = {}
        if oauth_token:
            extra_env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
        result = spawn_one_shot(
            backend,
            prompt=prompt,
            timeout=CLAUDE_TIMEOUT_SEC,
            permission_mode="default",
            extra_env=extra_env or None,
        )
        return result.returncode, result.stdout, result.stderr

    # Default path — faithful legacy one-shot argv (unchanged behaviour).
    env = os.environ.copy()
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token

    return _run_subprocess(
        [
            str(CLAUDE_BIN), "-p",
            "--output-format", "text",
            "--max-turns", "0",
            "--setting-sources", "user",
        ],
        input_text=prompt,
        timeout=CLAUDE_TIMEOUT_SEC,
    )


# ── Classification ──────────────────────────────────────────────────────


def _parse_claude_response(stdout: str) -> dict | None:
    """Extract the JSON object from Claude's response.

    Accepts:
      - Pure JSON
      - JSON wrapped in ```json ... ``` fences
      - JSON preceded by short prose

    Returns None on any parse failure — caller defaults to NEEDS_HUMAN.
    """
    text = stdout.strip()
    # Strip code fences if present
    if "```" in text:
        # Find the first JSON-looking block between fences
        parts = text.split("```")
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("json"):
                stripped = stripped[len("json"):].strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                text = stripped
                break
    # Last-ditch: find the first { ... } substring
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start:end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def classify_issue(
    issue_number: int,
    *,
    repo: str = DEFAULT_REPO,
) -> TriageVerdict:
    """Classify a single GitHub issue into a TriageVerdict.

    Reads the issue via `gh`, spawns a Claude subprocess, parses the JSON
    response. Defaults to NEEDS_HUMAN on any parse / subprocess failure.

    Cost cap is informational: a verdict whose cost exceeds COST_CAP_USD
    still ships, but a WARNING is logged so the operator can audit.

    Args:
        issue_number: GitHub issue number on `repo`.
        repo: owner/name slug. Defaults to your-org/bumba-open-harness.

    Returns:
        A frozen TriageVerdict. NEEDS_HUMAN on subprocess or parse failure.
    """
    issue_payload = _gh_issue_view(issue_number, repo=repo)
    title = issue_payload.get("title", "")
    body = issue_payload.get("body", "") or ""
    labels = [
        label.get("name", "")
        for label in (issue_payload.get("labels") or [])
    ]

    prompt = _TRIAGE_PROMPT_TEMPLATE.format(
        issue_number=issue_number,
        title=title,
        body=body[:8000],  # bound the body — long issues otherwise blow context
        labels=", ".join(labels) if labels else "(none)",
    )

    cost_usd = 0.0
    try:
        rc, stdout, stderr = _invoke_claude(prompt)
    except subprocess.TimeoutExpired:
        logger.warning(
            "triage: claude timeout on #%s — defaulting to needs-human",
            issue_number,
        )
        return TriageVerdict(
            issue_number=issue_number,
            state=FactoryState.NEEDS_HUMAN,
            category="unknown",
            complexity="out-of-scope",
            reasoning="Claude subprocess timed out during classification.",
            cost_usd=cost_usd,
            evaluated_at=datetime.now(timezone.utc),
        )

    if rc != 0:
        logger.warning(
            "triage: claude exit %s on #%s — defaulting to needs-human: %s",
            rc, issue_number, stderr.strip()[:300],
        )
        return TriageVerdict(
            issue_number=issue_number,
            state=FactoryState.NEEDS_HUMAN,
            category="unknown",
            complexity="out-of-scope",
            reasoning=f"Claude subprocess exit {rc}: {stderr.strip()[:200]}",
            cost_usd=cost_usd,
            evaluated_at=datetime.now(timezone.utc),
        )

    parsed = _parse_claude_response(stdout)
    if parsed is None:
        logger.warning(
            "triage: malformed JSON on #%s — defaulting to needs-human",
            issue_number,
        )
        return TriageVerdict(
            issue_number=issue_number,
            state=FactoryState.NEEDS_HUMAN,
            category="unknown",
            complexity="out-of-scope",
            reasoning="Claude response was not parseable JSON.",
            cost_usd=cost_usd,
            evaluated_at=datetime.now(timezone.utc),
        )

    # Cost is optional — Claude doesn't put it in `text` mode, but tests inject
    # a number through a separate path. We accept both keys for robustness.
    cost_usd = float(parsed.get("cost_usd", parsed.get("cost", 0.0)) or 0.0)
    if cost_usd > COST_CAP_USD:
        logger.warning(
            "triage: #%s cost $%.4f exceeded cap $%.4f — verdict still applied",
            issue_number, cost_usd, COST_CAP_USD,
        )

    state_str = str(parsed.get("state", "")).lower()
    state = _STATE_NAME_TO_ENUM.get(state_str, FactoryState.NEEDS_HUMAN)

    category = str(parsed.get("category", "unknown"))[:50]
    complexity_raw = str(parsed.get("complexity", "out-of-scope"))
    complexity: Complexity = (
        complexity_raw  # type: ignore[assignment]
        if complexity_raw in ("small", "medium", "large", "out-of-scope")
        else "out-of-scope"
    )
    reasoning = str(parsed.get("reasoning", ""))[:500]

    return TriageVerdict(
        issue_number=issue_number,
        state=state,
        category=category,
        complexity=complexity,
        reasoning=reasoning,
        cost_usd=cost_usd,
        evaluated_at=datetime.now(timezone.utc),
    )


# ── Workflow ────────────────────────────────────────────────────────────


def _format_comment(verdict: TriageVerdict) -> str:
    """Produce the operator-facing audit comment body for a verdict."""
    return (
        f"**Factory triage** → `{verdict.state.value}`\n\n"
        f"- category: `{verdict.category}`\n"
        f"- complexity: `{verdict.complexity}`\n"
        f"- cost: ${verdict.cost_usd:.4f}\n"
        f"- evaluated: {verdict.evaluated_at.isoformat()}\n\n"
        f"_Reasoning_: {verdict.reasoning}"
    )


def triage_workflow(
    *,
    repo: str = DEFAULT_REPO,
    max_issues: int = 5,
    config_enabled: bool = True,
) -> list[TriageVerdict]:
    """Run one triage pass over the `factory:opt-in + factory:untriaged` queue.

    Up to `max_issues` issues are classified by `classify_issue`. For each, we:
      1. Call `transition_state(num, UNTRIAGED, verdict.state)`.
      2. Comment the rationale via `gh issue comment`.

    Issues that overflow the rate limit (`max_issues`) keep their UNTRIAGED
    label and additionally get the `factory:rate-limited` label so the next
    run can prioritize differently. They are NOT classified this pass.

    The `config_enabled` parameter is the feature-flag wire-through. When
    False, this function is a no-op returning `[]` — the orchestrator
    (Sprint 14.10) reads `BridgeConfig.factory_triage_enabled` and forwards
    it here.

    Args:
        repo: owner/name. Defaults to your-org/bumba-open-harness.
        max_issues: hard cap on classifications per run. Default 5.
        config_enabled: feature-flag wire-through. Default True for direct
            callers; the orchestrator passes the BridgeConfig flag.

    Returns:
        The list of TriageVerdict objects produced this pass (length <= max_issues).
        Empty list when the flag is OFF or no issues match.
    """
    if not config_enabled:
        logger.debug("triage_workflow: feature flag OFF — returning []")
        return []

    # Pull a generous overhang so we can rate-limit-label everything beyond
    # max_issues that exists today. 200 is the gh default cap.
    candidates = _gh_issue_list_untriaged(repo=repo, limit=200)
    if not candidates:
        logger.info("triage_workflow: no factory:opt-in + factory:untriaged issues found")
        return []

    to_classify = candidates[:max_issues]
    overflow = candidates[max_issues:]

    if overflow:
        logger.info(
            "triage_workflow: %d issues over rate limit — labeling factory:rate-limited",
            len(overflow),
        )
        for issue_number in overflow:
            _gh_issue_add_label(
                issue_number,
                FactoryState.RATE_LIMITED.value,
                repo=repo,
            )

    verdicts: list[TriageVerdict] = []
    for issue_number in to_classify:
        try:
            verdict = classify_issue(issue_number, repo=repo)
        except RuntimeError as e:
            logger.warning(
                "triage_workflow: classify_issue failed on #%s: %s",
                issue_number, e,
            )
            continue

        # Apply state transition. transition_state's optimistic check handles
        # the case where another factory process already moved the label.
        try:
            transitioned = transition_state(
                issue_number,
                FactoryState.UNTRIAGED,
                verdict.state,
            )
            if not transitioned:
                logger.info(
                    "triage_workflow: optimistic check failed on #%s — skipping comment",
                    issue_number,
                )
        except Exception as e:  # pragma: no cover — gh/state errors logged, not fatal
            logger.warning(
                "triage_workflow: transition_state failed on #%s: %s",
                issue_number, e,
            )
            transitioned = False

        if transitioned:
            _gh_issue_comment(issue_number, _format_comment(verdict), repo=repo)

        verdicts.append(verdict)

    return verdicts
