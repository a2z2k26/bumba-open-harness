"""Factory orchestrator service — runs the Dark Factory loop on a 4h cadence.

Sprint 14.10 — Plan 14 Phase 5.

Composes triage → implement → quality → validate → synthesize → route. Per-target
locking ensures no two ticks operate on the same issue concurrently. A single
global lock prevents two scheduler instances from racing.

Concept-only port of coleam00/dark-factory-experiment (no LICENSE — no source
copy). The pipeline so far:

  - 14.04 (PR #1116) — `bridge.factory.labels` GitHub-label state machine
  - 14.05 (PR #1117 + #1123) — triage + implement workflows
  - 14.06 (PR #1131) — quality gates (PR size + protected files + new-dep)
  - 14.07 (PR #1134) — validate workflow (4 holdout reviewers)
  - 14.03 (PR #1135) — holdout primitives + validate.py refactor
  - 14.08 (PR #1136) — 7-rule synthesizer

This sprint wires them all together as a scheduled service. Each tick picks
``factory:accepted`` issues, runs implement → quality → validate → synthesize,
then routes the outcome to the right next state. Per-issue locks bound the
blast radius — one slow run cannot block sibling issues; one stuck issue
cannot block the entire loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bridge.factory.channels import (
    CHANNEL_CLOSE_LABEL_PREFIX,
    ChannelInfo,
    ChannelLabelError,
    is_channel_close_ready,
    make_channel_close_issue_body,
    parse_channel_from_labels,
)
from bridge.factory.fix_loop import (
    DEFAULT_COST_CAP_PER_ATTEMPT_USD as FIX_LOOP_DEFAULT_COST_CAP_PER_ATTEMPT_USD,
    DEFAULT_COST_CAP_TOTAL_USD as FIX_LOOP_DEFAULT_COST_CAP_TOTAL_USD,
    DEFAULT_MAX_ATTEMPTS as FIX_LOOP_DEFAULT_MAX_ATTEMPTS,
    FixLoopResult,
    run_fix_loop,
)
from bridge.factory.implement import implement_issue
from bridge.factory.labels import FactoryState, transition_state
from bridge.factory.seven_rule_synthesizer import (
    FactorySynthesisOutcome,
    SynthesisDecision,
    SynthesisInput,
    outcome_to_factory_state,
    synthesize,
)
from bridge.factory.validate import ValidateResult, validate_pr
from bridge.halt import HaltPolicy
from bridge.services.base import ServiceBase
from bridge.services.result import ServiceResult

logger = logging.getLogger(__name__)


def _build_runtime_halt_policy(data_dir: Path) -> HaltPolicy:
    """Build a HaltPolicy bound to ``<data_dir>/halt.flag`` (audit-2026-05-16.C.05).

    Mirrors the pattern in ``job_search/_pipeline.py::_build_halt_policy``.
    The factory orchestrator runs as a LaunchDaemon subprocess via
    ``python -m bridge.services.runner factory_orchestrator``; that
    context does NOT boot the full bridge stack (no ``SecurityManager``,
    no ``Database``), so :func:`bridge.config.build_default_halt_policy`
    is overkill. Instead, read the same on-disk halt flag the daemon
    side reads — both surfaces converge on the file ``/halt`` writes.

    The factory's existing ``factory-paused.flag`` is a separate
    operator-pause concept (factory-specific). The global halt flag
    introduced here is the cross-surface kill switch. Both are honoured.
    """
    halt_path = Path(data_dir) / "halt.flag"

    def _is_halted() -> bool:
        return halt_path.exists()

    def _halt_reason() -> str | None:
        if not halt_path.exists():
            return None
        try:
            return halt_path.read_text().strip() or "halted"
        except OSError:
            return "halted"

    return HaltPolicy(is_halted=_is_halted, halt_reason=_halt_reason)


# ── Helpers ──────────────────────────────────────────────────────────────


def _load_mailbox_settings() -> tuple[bool, int, int]:
    """Load factory mailbox settings from config.

    Returns (enabled, poll_interval_seconds, decision_timeout_seconds).
    Fails open (all defaults) so the orchestrator never crashes on config errors.
    """
    try:
        from bridge.config import load_config

        cfg = load_config()
        return (
            bool(getattr(cfg, "factory_mailbox_enabled", False)),
            int(getattr(cfg, "factory_mailbox_poll_interval_seconds", 2)),
            int(getattr(cfg, "factory_mailbox_decision_timeout_seconds", 3600)),
        )
    except Exception:
        return (False, 2, 3600)


# ── Constants ────────────────────────────────────────────────────────────


DEFAULT_REPO = "your-org/bumba-open-harness"

# Global lock — guards an entire tick. Mirrors consolidation_lock.py's
# mtime-as-timestamp pattern; STALE_THRESHOLD lets a crashed scheduler get
# reclaimed by the next tick.
GLOBAL_LOCK_FILENAME = "factory-orchestrator.lock"
GLOBAL_LOCK_STALE_S = 600  # 10 min

# Per-target lock — one per issue. Stale threshold is longer because the
# implement pipeline can run for a while. The orchestrator never blocks
# waiting on a contended lock — a contended issue is just skipped this tick.
PER_TARGET_LOCK_DIRNAME = "factory-locks"
PER_TARGET_LOCK_STALE_S = 1800  # 30 min

# Cost discipline (per spec / sprint description):
#   - per-issue cap: $2.00
#   - per-tick cap:  $5.00 (finishes current issue then halts further starts)
DEFAULT_COST_CAP_PER_ISSUE_USD = 2.00
DEFAULT_COST_CAP_PER_TICK_USD = 5.00

# Bound on issues considered per tick, irrespective of cost. The orchestrator
# is a 4h cron — plenty of next-tick capacity. Also prevents `gh issue list`
# from returning thousands of rows on day one.
MAX_ISSUES_PER_TICK = 20

# Awaiting-review label — a stand-in name. The shipping label wins is
# `factory:needs-review` (the implement workflow already moves the issue
# there on success). The spec calls for ``factory:awaiting-review`` for
# READY_FOR_OPERATOR / READY_WITH_NOTES. We use the existing
# ``factory:needs-review`` so we don't drift the state machine; the
# in-flight issue may already carry that label after implement_issue. The
# transition is therefore best-effort.
AWAITING_REVIEW_STATE = FactoryState.NEEDS_REVIEW
NEEDS_FIX_STATE = FactoryState.FIX_ATTEMPT_1
NEEDS_HUMAN_STATE = FactoryState.NEEDS_HUMAN


# ── Result dataclasses ───────────────────────────────────────────────────


@dataclass(frozen=True)
class IssueProcessResult:
    """Result of processing one issue this tick."""

    issue_number: int
    starting_state: str  # FactoryState string at start of tick
    final_state: str  # FactoryState string after tick (state we routed to)
    synthesis_outcome: str | None  # FactorySynthesisOutcome.value, or None
    cost_usd: float
    duration_seconds: float
    error: str | None = None  # set when the per-target loop broke


@dataclass(frozen=True)
class TickResult:
    """Aggregate result of one orchestrator tick."""

    issues_processed: tuple[IssueProcessResult, ...] = ()
    skipped_count: int = 0  # issues we couldn't acquire a per-target lock on
    error: str | None = None
    duration_seconds: float = 0.0
    total_cost_usd: float = 0.0


# ── Lock helpers (file-based, mtime-as-timestamp) ────────────────────────


def _is_process_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` is currently alive.

    ``os.kill(pid, 0)`` is the canonical Unix probe — it raises
    ``ProcessLookupError`` for dead pids and ``PermissionError`` for live
    ones we don't own. We treat the perm-error as alive (someone else owns
    it; we shouldn't reclaim).
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _try_acquire_lock(path: Path, *, stale_s: int) -> bool:
    """Try to acquire ``path`` as our PID lock.

    Returns True iff we now hold the lock. False otherwise (someone else
    holds it and is alive). Stale locks (older than ``stale_s`` AND held
    by a dead pid) are reclaimed in-place.

    Race notes: write-then-read to detect the rare two-writer race. Not
    bulletproof — POSIX file locks would be — but the orchestrator runs
    every 4h, so the window is small and contention is rare.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            stat = path.stat()
            age_s = time.time() - stat.st_mtime
            holder_text = path.read_text().strip()
            holder_pid = int(holder_text) if holder_text.isdigit() else 0
        except (OSError, ValueError):
            holder_pid = 0
            age_s = 0.0

        if age_s < stale_s and holder_pid and _is_process_alive(holder_pid):
            return False
        # Else: stale — fall through to overwrite below.

    try:
        path.write_text(str(os.getpid()))
    except OSError as e:
        logger.warning("factory_orchestrator: lock write failed for %s: %s", path, e)
        return False

    # Race resolution — re-read to confirm we won.
    try:
        written_pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return False
    return written_pid == os.getpid()


def _release_lock(path: Path) -> None:
    """Release ``path`` if it currently belongs to us. Best-effort."""
    if not path.exists():
        return
    try:
        held = path.read_text().strip()
        if held == str(os.getpid()):
            path.unlink(missing_ok=True)
    except OSError:
        # Not ours to delete, or already gone — either way, leave it alone.
        pass


# ── GitHub helpers (via `gh` CLI subprocess) ─────────────────────────────


def _run_gh(args: list[str]) -> tuple[int, str, str]:
    """Run a `gh` subcommand. Returns (rc, stdout, stderr)."""
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _gh_list_accepted(repo: str, limit: int = MAX_ISSUES_PER_TICK) -> list[dict]:
    """Return open issues with ``factory:accepted`` (most recent first).

    Fetches number + title + body + labels so the orchestrator can hand
    the body to ``validate_pr`` later without an extra round-trip per
    issue, and so Sprint 15.04 channels-as-branches routing can read the
    labels without a second ``gh`` call.
    """
    rc, stdout, stderr = _run_gh(
        [
            "issue", "list",
            "--repo", repo,
            "--state", "open",
            "--label", FactoryState.ACCEPTED.value,
            "--limit", str(limit),
            "--json", "number,title,body,labels",
        ]
    )
    if rc != 0:
        raise RuntimeError(
            f"`gh issue list --label {FactoryState.ACCEPTED.value}` failed "
            f"(exit {rc}): {stderr.strip()[:300]}"
        )
    try:
        payload = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Could not parse `gh issue list` JSON: {e}") from e
    return payload if isinstance(payload, list) else []


def _gh_issue_comment(issue_number: int, body: str, repo: str) -> None:
    """Comment on an issue. Best-effort — failures log, never raise."""
    rc, _stdout, stderr = _run_gh(
        ["issue", "comment", str(issue_number), "--repo", repo, "--body", body]
    )
    if rc != 0:
        logger.warning(
            "factory_orchestrator: comment on #%s failed (exit %s): %s",
            issue_number, rc, stderr.strip()[:200],
        )


def _gh_pr_ready_for_review(pr_number: int, repo: str) -> None:
    """Mark a draft PR ready for review. Best-effort."""
    rc, _stdout, stderr = _run_gh(
        ["pr", "ready", str(pr_number), "--repo", repo]
    )
    if rc != 0:
        logger.warning(
            "factory_orchestrator: pr ready #%s failed (exit %s): %s",
            pr_number, rc, stderr.strip()[:200],
        )


def _gh_pr_diff(pr_number: int, repo: str) -> str:
    """Return the unified diff of a PR (empty string on failure)."""
    rc, stdout, stderr = _run_gh(
        ["pr", "diff", str(pr_number), "--repo", repo]
    )
    if rc != 0:
        logger.warning(
            "factory_orchestrator: pr diff #%s failed (exit %s): %s",
            pr_number, rc, stderr.strip()[:200],
        )
        return ""
    return stdout


# ── Channels-as-branches helpers (Sprint 15.04) ─────────────────────────


def _extract_label_names(raw_labels: Any) -> list[str]:
    """Return a flat list of label-name strings from a `gh ... --json labels` blob.

    ``gh`` returns labels as a list of dicts with ``name`` keys. Tests
    sometimes hand in raw strings; tolerate both shapes.
    """
    out: list[str] = []
    if not isinstance(raw_labels, list):
        return out
    for item in raw_labels:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                out.append(name)
    return out


def _gh_branch_exists(branch: str, repo: str) -> bool:
    """Return True iff ``branch`` exists on the remote repo.

    Probes via ``gh api repos/{repo}/branches/{branch}``. A 404 means
    "create me"; any other failure falls through to False with a warning
    so the orchestrator still attempts creation (idempotent on the gh
    side — duplicate-create errors surface as creation-failure logs).
    """
    rc, _stdout, stderr = _run_gh(
        ["api", f"repos/{repo}/branches/{branch}", "--silent"]
    )
    if rc == 0:
        return True
    # gh prints a "Not Found" body to stderr for 404s; any other error
    # also lands here. Conservative: assume non-zero == absent.
    if "Not Found" not in stderr and stderr.strip():
        logger.debug(
            "factory_orchestrator: gh api branches probe for %s returned "
            "non-zero exit (%s) without 'Not Found': %s",
            branch, rc, stderr.strip()[:200],
        )
    return False


def _gh_create_branch_from_main(branch: str, repo: str) -> bool:
    """Create ``branch`` from ``origin/main`` on the remote.

    Best-effort: returns True on success, False on failure (logged).
    Implemented via ``gh api`` POST to the git-refs endpoint, which lets
    us create remote branches without a local working tree.
    """
    # Resolve main's tip SHA.
    rc, stdout, stderr = _run_gh(
        ["api", f"repos/{repo}/git/refs/heads/main"]
    )
    if rc != 0:
        logger.warning(
            "factory_orchestrator: could not resolve main's SHA on %s "
            "(exit %s): %s",
            repo, rc, stderr.strip()[:200],
        )
        return False
    try:
        payload = json.loads(stdout) if stdout.strip() else {}
        sha = (payload.get("object") or {}).get("sha")
    except json.JSONDecodeError:
        sha = None
    if not isinstance(sha, str) or not sha:
        logger.warning(
            "factory_orchestrator: main SHA missing from gh api response "
            "for %s",
            repo,
        )
        return False

    rc, _stdout, stderr = _run_gh(
        [
            "api",
            "--method", "POST",
            f"repos/{repo}/git/refs",
            "-f", f"ref=refs/heads/{branch}",
            "-f", f"sha={sha}",
        ]
    )
    if rc != 0:
        logger.warning(
            "factory_orchestrator: create branch %s on %s failed "
            "(exit %s): %s",
            branch, repo, rc, stderr.strip()[:200],
        )
        return False
    return True


def _ensure_integration_branch(channel: ChannelInfo, repo: str) -> None:
    """Idempotently ensure the channel's integration branch exists on `repo`.

    No-op if the branch is already present. Logs warnings on creation
    failure but never raises — the orchestrator falls back to ``main``
    via the implement pipeline's ``base_branch`` default if the integration
    branch can't be created (the per-issue lock + best-effort idiom across
    this module).
    """
    branch = channel.integration_branch
    if _gh_branch_exists(branch, repo):
        return
    created = _gh_create_branch_from_main(branch, repo)
    if created:
        logger.info(
            "factory_orchestrator: created integration branch %s on %s",
            branch, repo,
        )


def _gh_list_open_issues_with_labels(repo: str) -> dict[int, list[str]]:
    """Return ``{issue_number: [label_name, ...]}`` for every open issue.

    Used by :func:`is_channel_close_ready` to decide whether all of a
    channel's children are closed. Capped at 200 issues to bound the gh
    call. On failure returns an empty dict + warning — the orchestrator
    treats "couldn't list" as "don't auto-file the close issue this tick"
    rather than guessing.
    """
    rc, stdout, stderr = _run_gh(
        [
            "issue", "list",
            "--repo", repo,
            "--state", "open",
            "--limit", "200",
            "--json", "number,labels",
        ]
    )
    if rc != 0:
        logger.warning(
            "factory_orchestrator: open-issue list for channel-close check "
            "failed (exit %s): %s",
            rc, stderr.strip()[:200],
        )
        return {}
    try:
        payload = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError:
        return {}
    out: dict[int, list[str]] = {}
    if not isinstance(payload, list):
        return out
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        number = entry.get("number")
        if not isinstance(number, int):
            continue
        out[number] = _extract_label_names(entry.get("labels"))
    return out


def _gh_create_channel_close_issue(
    *,
    channel: ChannelInfo,
    closed_issue_numbers: list[int],
    repo: str,
    branch_prefix: str = "factory/channel",
) -> int | None:
    """File the channel-close issue. Returns the new issue number or None."""
    title, body = make_channel_close_issue_body(
        channel.name,
        closed_issue_numbers=closed_issue_numbers,
        branch_prefix=branch_prefix,
    )
    close_label = f"{CHANNEL_CLOSE_LABEL_PREFIX}{channel.name}"
    rc, stdout, stderr = _run_gh(
        [
            "issue", "create",
            "--repo", repo,
            "--title", title,
            "--body", body,
            "--label", close_label,
        ]
    )
    if rc != 0:
        logger.warning(
            "factory_orchestrator: create channel-close issue for %s on %s "
            "failed (exit %s): %s",
            channel.name, repo, rc, stderr.strip()[:200],
        )
        return None
    # gh prints the new issue URL on stdout; parse the trailing /<number>.
    text = stdout.strip()
    if "/" in text:
        try:
            return int(text.rsplit("/", 1)[-1])
        except ValueError:
            return None
    return None


def _gh_fast_forward_integration_to_main(
    channel: ChannelInfo, repo: str,
) -> bool:
    """Fast-forward ``main`` to the channel's integration branch on ``repo``.

    Operator-gated entry point — invoked by ``_process_issue`` only when
    the channel-close issue itself has reached a clean route plan (i.e.
    operator approved). Best-effort + logged; returns True on success.
    """
    branch = channel.integration_branch
    rc, stdout, stderr = _run_gh(
        ["api", f"repos/{repo}/git/refs/heads/{branch}"]
    )
    if rc != 0:
        logger.warning(
            "factory_orchestrator: fast-forward — could not resolve %s "
            "(exit %s): %s",
            branch, rc, stderr.strip()[:200],
        )
        return False
    try:
        payload = json.loads(stdout) if stdout.strip() else {}
        sha = (payload.get("object") or {}).get("sha")
    except json.JSONDecodeError:
        sha = None
    if not isinstance(sha, str) or not sha:
        return False

    rc, _stdout, stderr = _run_gh(
        [
            "api",
            "--method", "PATCH",
            f"repos/{repo}/git/refs/heads/main",
            "-f", f"sha={sha}",
            "-F", "force=false",
        ]
    )
    if rc != 0:
        logger.warning(
            "factory_orchestrator: fast-forward main → %s failed "
            "(exit %s): %s",
            branch, rc, stderr.strip()[:200],
        )
        return False
    logger.info(
        "factory_orchestrator: fast-forwarded main to %s on %s",
        branch, repo,
    )
    return True


# ── Outcome routing (pure) ───────────────────────────────────────────────


@dataclass(frozen=True)
class _RoutePlan:
    """How a synthesizer outcome should be applied to GitHub.

    Pure description of the side effect — produced by ``_route_outcome`` and
    applied by ``_process_issue``. Keeping the description pure makes the
    routing logic testable in isolation.
    """

    target_state: FactoryState
    comment_body: str
    mark_pr_ready: bool


def _build_outcome_comment(
    *,
    outcome: FactorySynthesisOutcome,
    explanation: str,
    block_reasons: tuple[str, ...],
    advise_reasons: tuple[str, ...],
) -> str:
    """Render a Markdown comment summarizing the synthesizer decision."""
    lines = [
        f"**Factory orchestrator** — outcome `{outcome.value}`",
        "",
        explanation,
        "",
    ]
    if block_reasons:
        lines.append("**Blocking reasons:**")
        for reason in block_reasons:
            lines.append(f"- {reason}")
        lines.append("")
    if advise_reasons:
        lines.append("**Advisory notes:**")
        for reason in advise_reasons:
            lines.append(f"- {reason}")
        lines.append("")
    lines.append("---")
    lines.append("_concept-only-no-license — Dark Factory_")
    return "\n".join(lines)


def _route_outcome(
    outcome: FactorySynthesisOutcome,
    *,
    explanation: str,
    block_reasons: tuple[str, ...],
    advise_reasons: tuple[str, ...],
) -> _RoutePlan:
    """Translate ``FactorySynthesisOutcome`` → ``_RoutePlan``.

    Pure (no side effects). The orchestrator applies the plan separately so
    failures in one side effect don't poison the others.

    Routing table:
      READY_FOR_OPERATOR / READY_WITH_NOTES → mark PR ready, label
        ``factory:needs-review`` (awaiting-review proxy until the spec
        adds a dedicated state).
      NEEDS_FIX → label ``factory:fix-attempt-1`` + comment explaining
        what to fix. Sprint 14.09 (auto-fix loop) will pick the issue up;
        until 14.09 ships, the operator handles it.
      NEEDS_HUMAN / ABANDON / ESCALATE_COST → label ``factory:needs-human``
        + comment with reasons.
      RETRY_REVIEWERS → keep state at ``factory:in-progress`` (the
        orchestrator owns the second invocation; routing here is a no-op).
    """
    body = _build_outcome_comment(
        outcome=outcome,
        explanation=explanation,
        block_reasons=block_reasons,
        advise_reasons=advise_reasons,
    )
    if outcome in (
        FactorySynthesisOutcome.READY_FOR_OPERATOR,
        FactorySynthesisOutcome.READY_WITH_NOTES,
    ):
        return _RoutePlan(
            target_state=AWAITING_REVIEW_STATE,
            comment_body=body,
            mark_pr_ready=True,
        )
    if outcome == FactorySynthesisOutcome.NEEDS_FIX:
        return _RoutePlan(
            target_state=NEEDS_FIX_STATE,
            comment_body=body,
            mark_pr_ready=False,
        )
    if outcome == FactorySynthesisOutcome.RETRY_REVIEWERS:
        # The orchestrator handles retry inline; the state stays IN_PROGRESS.
        return _RoutePlan(
            target_state=FactoryState.IN_PROGRESS,
            comment_body=body,
            mark_pr_ready=False,
        )
    # Default — abandon, escalate-cost, or needs-human all land at NEEDS_HUMAN.
    return _RoutePlan(
        target_state=outcome_to_factory_state(outcome),
        comment_body=body,
        mark_pr_ready=False,
    )


# ── Type aliases for injected dependencies ───────────────────────────────


# Implement runner signature: (issue_number, repo) -> ImplementResult-like.
# We type as ``Any`` to keep the orchestrator decoupled from the
# ImplementResult dataclass — only the duck-typed attributes (pr_number,
# pr_url, final_state, cost_usd, failed_phase) are read.
ImplementRunner = Callable[..., Any]

# Validate runner signature: (issue_body, pr_url, diff_text) -> coroutine
# returning a ValidateResult. Defaults to a thin wrapper over
# ``bridge.factory.validate.validate_pr`` that supplies a no-op runner.
ValidateRunner = Callable[..., Awaitable[ValidateResult]]

# Synthesizer signature mirrors ``synthesize``.
Synthesizer = Callable[..., Any]

# Fix-runner — Sprint 14.09 fix-loop adapter. Receives (issue_body,
# current_diff, block_reasons) and returns (new_diff, cost_usd, latency_ms).
# Default constructed lazily inside :meth:`_run_fix_loop` so the
# orchestrator can stay decoupled from ClaudeRunner at construction time
# (tests inject AsyncMock; production wires :func:`make_fix_runner` against
# the live runner).
FixRunner = Callable[..., Awaitable[tuple[str, float, int]]]

# Notifier — invoked once per tick with a human-readable summary string.
# Optional; service base ``deliver_message`` is the canonical channel.
Notifier = Callable[[str], None]


# ── Orchestrator class ───────────────────────────────────────────────────


class FactoryOrchestrator(ServiceBase):
    """Scheduled service. Drives the Dark Factory loop.

    One tick per LaunchDaemon firing (every 4h). Each tick:

      1. Acquires the global lock (idempotent — stale → reclaim).
      2. Lists ``factory:accepted`` issues via ``gh``.
      3. For each issue (serial; cost cap finishes current then halts):
         - Per-target lock acquire (skip on contention).
         - implement_issue → ImplementResult.
         - validate_pr → ValidateResult.
         - synthesize → SynthesisDecision.
         - On RETRY_REVIEWERS: re-validate once, re-synthesize.
         - Apply route plan: comment, transition state, optionally pr ready.
         - Per-target lock release.
      4. Release global lock; notify operator with summary.
    """

    def __init__(
        self,
        *,
        data_dir: str | Path,
        chat_id: str = "",
        repo: str = DEFAULT_REPO,
        cost_cap_per_tick_usd: float = DEFAULT_COST_CAP_PER_TICK_USD,
        cost_cap_per_issue_usd: float = DEFAULT_COST_CAP_PER_ISSUE_USD,
        config_enabled: bool = False,
        implement_runner: ImplementRunner | None = None,
        validate_runner: ValidateRunner | None = None,
        synthesizer: Synthesizer | None = None,
        notifier: Notifier | None = None,
        global_lock_path: Path | None = None,
        per_target_lock_dir: Path | None = None,
        event_callback: Callable[[str, dict], None] | None = None,
        # Sprint 14.09 — fix-loop wiring. Defaults preserve the legacy
        # behaviour (no fix loop, route NEEDS_FIX straight to
        # ``factory:fix-attempt-1`` for operator action).
        fix_loop_enabled: bool = False,
        fix_runner: FixRunner | None = None,
        fix_loop_max_attempts: int = FIX_LOOP_DEFAULT_MAX_ATTEMPTS,
        fix_loop_cost_cap_per_attempt_usd: float = (
            FIX_LOOP_DEFAULT_COST_CAP_PER_ATTEMPT_USD
        ),
        fix_loop_cost_cap_total_usd: float = (
            FIX_LOOP_DEFAULT_COST_CAP_TOTAL_USD
        ),
        # Sprint 15.04 — channels-as-branches gating. When False (default)
        # the orchestrator ignores ``factory:channel:*`` labels and every
        # issue runs against ``main`` (legacy behaviour). When True,
        # channel-attached issues route to the per-channel integration
        # branch and channel-close auto-filing kicks in.
        channels_enabled: bool = False,
        integration_branch_prefix: str = "factory/channel",
        # audit-2026-05-16.C.05 — shared HaltPolicy contract. When None
        # (default) the orchestrator skips the global halt check and
        # only honours its own ``factory-paused.flag``. When wired, the
        # global halt blocks new ticks and cancels new per-issue starts
        # within a tick (in-flight `_process_issue` finishes cleanly).
        halt_policy: HaltPolicy | None = None,
    ) -> None:
        super().__init__(data_dir=data_dir, event_callback=event_callback)
        self._chat_id = chat_id
        self._repo = repo
        self._cost_cap_per_tick = cost_cap_per_tick_usd
        self._cost_cap_per_issue = cost_cap_per_issue_usd
        self._config_enabled = config_enabled
        self._implement = implement_runner or implement_issue
        self._validate = validate_runner or self._default_validate_runner
        self._synthesize = synthesizer or synthesize
        self._notifier = notifier
        self._global_lock_path = (
            global_lock_path
            if global_lock_path is not None
            else self.data_dir / GLOBAL_LOCK_FILENAME
        )
        self._per_target_lock_dir = (
            per_target_lock_dir
            if per_target_lock_dir is not None
            else self.data_dir / PER_TARGET_LOCK_DIRNAME
        )
        # Sprint 15.04 — channels-as-branches gating snapshot.
        self._channels_enabled = channels_enabled
        self._integration_branch_prefix = integration_branch_prefix
        # Sprint 14.09 — fix-loop config snapshot.
        self._fix_loop_enabled = fix_loop_enabled
        self._fix_runner = fix_runner
        self._fix_loop_max_attempts = fix_loop_max_attempts
        self._fix_loop_cost_cap_per_attempt = fix_loop_cost_cap_per_attempt_usd
        self._fix_loop_cost_cap_total = fix_loop_cost_cap_total_usd
        # audit-2026-05-16.C.05 — shared halt-policy handle (may be None;
        # when None the global halt check is skipped entirely so the
        # legacy pause-flag-only behaviour is preserved).
        self._halt_policy = halt_policy

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def run(self) -> ServiceResult:
        """Service entry — invoked by ``bridge.services.runner``.

        Honors ``factory_orchestrator_enabled``. Returns a ``ServiceResult``
        normalized for the runner pipeline. The flag is read from the live
        ``BridgeConfig`` if the constructor did not pre-set it (the runner
        does not thread feature flags into constructors today; loading lazy
        here keeps this service shippable without a runner change).
        """
        start = time.monotonic()
        enabled = self._config_enabled
        if not enabled:
            try:
                from bridge.config import load_config
                cfg = load_config()
                enabled = bool(
                    getattr(cfg, "factory_orchestrator_enabled", False)
                )
            except Exception:  # pragma: no cover — defensive only
                enabled = False
        if not enabled:
            return ServiceResult(
                service="factory_orchestrator",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                cost_usd=0.0,
                skip_reason="feature flag OFF",
            )

        tick = await self.tick()
        duration_ms = int((time.monotonic() - start) * 1000)
        narration = (
            f"factory: processed {len(tick.issues_processed)} issues, "
            f"skipped {tick.skipped_count}, cost ${tick.total_cost_usd:.4f}"
        )
        return ServiceResult(
            service="factory_orchestrator",
            ok=tick.error is None,
            work_items=len(tick.issues_processed),
            duration_ms=duration_ms,
            cost_usd=tick.total_cost_usd,
            anomalies=(("locked",) if tick.error == "locked" else ()),
            narration=narration,
        )

    async def tick(self) -> TickResult:
        """One orchestrator tick.

        Acquires global lock, lists ``factory:accepted`` issues, processes
        each in turn, releases lock. Idempotent — re-tick is safe (any issue
        whose per-target lock is still held will be skipped).

        Sprint 14.11 — honors the operator pause flag. If
        ``data/factory-paused.flag`` exists (resolved relative to
        ``data_dir``), the tick exits immediately with
        ``error="paused"`` after a single info log. No GitHub state is
        touched. The shadow harness checks the same flag.

        audit-2026-05-16.C.05 — honors the shared global halt flag.
        When a ``HaltPolicy`` is wired and reports blocked, the tick
        exits immediately with ``error="halted"`` BEFORE the pause-flag
        check. New per-issue dispatches are also gated via
        ``check_continue("factory")`` inside the loop so an operator
        ``/halt`` mid-tick stops further starts (the in-flight issue
        finishes cleanly).
        """
        tick_start = time.monotonic()

        # audit-2026-05-16.C.05 — global halt check fires first so an
        # operator `/halt` overrides every other tick-skip condition
        # (lock contention, pause flag, listing errors). The pause flag
        # remains as a factory-specific operator surface; halt is the
        # cross-surface kill switch.
        if self._halt_policy is not None:
            start_decision = self._halt_policy.check_start("factory")
            if start_decision.blocked:
                logger.info(
                    "factory_orchestrator: halt-policy blocked start — %s",
                    start_decision.reason,
                )
                return TickResult(
                    issues_processed=(),
                    skipped_count=0,
                    error="halted",
                    duration_seconds=time.monotonic() - tick_start,
                )

        # Pause-flag check — must run before lock acquisition so a paused
        # tick is also a no-op for lock contention.
        from bridge.factory.operator_commands import is_paused as _is_paused

        pause_flag_path = self.data_dir / "factory-paused.flag"
        if _is_paused(pause_flag_path):
            logger.info(
                "factory_orchestrator: pause flag present — skipping tick"
            )
            return TickResult(
                issues_processed=(),
                skipped_count=0,
                error="paused",
                duration_seconds=time.monotonic() - tick_start,
            )

        if not _try_acquire_lock(
            self._global_lock_path, stale_s=GLOBAL_LOCK_STALE_S
        ):
            logger.info(
                "factory_orchestrator: global lock contended — skipping tick"
            )
            return TickResult(
                issues_processed=(),
                skipped_count=0,
                error="locked",
                duration_seconds=time.monotonic() - tick_start,
            )

        results: list[IssueProcessResult] = []
        skipped = 0
        total_cost = 0.0

        try:
            try:
                issues = _gh_list_accepted(self._repo)
            except Exception as e:
                logger.exception(
                    "factory_orchestrator: list accepted failed: %s", e
                )
                return TickResult(
                    issues_processed=(),
                    skipped_count=0,
                    error=str(e)[:300],
                    duration_seconds=time.monotonic() - tick_start,
                )

            for issue in issues:
                if total_cost >= self._cost_cap_per_tick:
                    logger.info(
                        "factory_orchestrator: per-tick cost cap $%.2f reached "
                        "(spent $%.4f) — halting further starts",
                        self._cost_cap_per_tick, total_cost,
                    )
                    break

                # audit-2026-05-16.C.05 — re-check halt before each new
                # per-issue start. An operator `/halt` mid-tick stops
                # further dispatches; the issue already in-flight (if
                # any) finishes cleanly below before this branch fires.
                if self._halt_policy is not None:
                    cont_decision = self._halt_policy.check_continue("factory")
                    if cont_decision.blocked:
                        logger.info(
                            "factory_orchestrator: halt-policy blocked "
                            "continue — %s",
                            cont_decision.reason,
                        )
                        break

                issue_number = int(issue.get("number", 0) or 0)
                if not issue_number:
                    continue
                issue_body = str(issue.get("body") or "")
                issue_labels = _extract_label_names(issue.get("labels"))

                # Per-target lock — non-blocking. Contention → skip.
                lock_path = (
                    self._per_target_lock_dir / f"issue-{issue_number}.lock"
                )
                if not _try_acquire_lock(
                    lock_path, stale_s=PER_TARGET_LOCK_STALE_S
                ):
                    logger.info(
                        "factory_orchestrator: per-target lock for #%s "
                        "contended — skipping this tick",
                        issue_number,
                    )
                    skipped += 1
                    continue

                try:
                    result = await self._process_issue(
                        issue_number=issue_number,
                        issue_body=issue_body,
                        issue_labels=issue_labels,
                    )
                    results.append(result)
                    total_cost += result.cost_usd
                finally:
                    _release_lock(lock_path)

        finally:
            _release_lock(self._global_lock_path)

        duration_s = time.monotonic() - tick_start
        tick_result = TickResult(
            issues_processed=tuple(results),
            skipped_count=skipped,
            error=None,
            duration_seconds=duration_s,
            total_cost_usd=total_cost,
        )

        # Notify with summary.
        summary = (
            f"Factory tick — processed {len(results)} issue(s), "
            f"skipped {skipped}, cost ${total_cost:.4f}, "
            f"duration {duration_s:.1f}s"
        )
        if self._notifier is not None:
            try:
                self._notifier(summary)
            except Exception:
                logger.debug(
                    "factory_orchestrator: notifier raised", exc_info=True
                )

        return tick_result

    # ------------------------------------------------------------------
    # Per-issue pipeline
    # ------------------------------------------------------------------

    async def _process_issue(
        self,
        *,
        issue_number: int,
        issue_body: str,
        issue_labels: list[str] | None = None,
    ) -> IssueProcessResult:
        """Process one issue end-to-end.

        Returns an ``IssueProcessResult`` describing the final routed state.
        Never raises; failures land in ``error`` and route to NEEDS_HUMAN.

        Sprint 15.04 — when ``channels_enabled`` is True and the issue
        carries ``factory:channel:<name>``, the implement pipeline targets
        the channel's integration branch instead of ``main``. Channel-close
        issues (``factory:channel-close:<name>``) instead trigger a
        fast-forward of integration → main and skip the implement pipeline
        entirely.
        """
        per_issue_start = time.monotonic()
        cumulative_cost = 0.0
        starting_state = FactoryState.ACCEPTED.value

        # Sprint 15.04 — resolve channel info from labels (when enabled).
        # Multiple-channel labels surface as a clean error route to
        # NEEDS_HUMAN so the operator can reconcile.
        channel: ChannelInfo | None = None
        if self._channels_enabled and issue_labels:
            try:
                channel = parse_channel_from_labels(
                    list(issue_labels),
                    branch_prefix=self._integration_branch_prefix,
                )
            except ChannelLabelError as e:
                logger.warning(
                    "factory_orchestrator: #%s has multiple channel labels: %s",
                    issue_number, e,
                )
                return IssueProcessResult(
                    issue_number=issue_number,
                    starting_state=starting_state,
                    final_state=NEEDS_HUMAN_STATE.value,
                    synthesis_outcome=None,
                    cost_usd=cumulative_cost,
                    duration_seconds=time.monotonic() - per_issue_start,
                    error=str(e)[:300],
                )

        # Sprint 15.04 — channel-close issues are a separate path: skip
        # implement, fast-forward integration → main, and route to
        # NEEDS_REVIEW for operator visibility.
        if channel is not None and channel.is_close_issue:
            success = _gh_fast_forward_integration_to_main(
                channel, repo=self._repo,
            )
            comment = (
                f"**Factory orchestrator** — channel close `{channel.name}`\n\n"
                f"Fast-forward `main` → `{channel.integration_branch}` "
                f"{'succeeded' if success else 'FAILED — operator action required'}.\n\n"
                "---\n_concept-only-no-license — Dark Factory_"
            )
            _gh_issue_comment(issue_number, comment, repo=self._repo)
            target_state = (
                FactoryState.NEEDS_REVIEW if success else NEEDS_HUMAN_STATE
            )
            for prior in (
                FactoryState.ACCEPTED,
                FactoryState.IN_PROGRESS,
                FactoryState.NEEDS_REVIEW,
            ):
                try:
                    if transition_state(issue_number, prior, target_state):
                        break
                except Exception as e:  # pragma: no cover — best-effort
                    logger.warning(
                        "factory_orchestrator: channel-close transition "
                        "#%s %s→%s raised: %s",
                        issue_number, prior.value, target_state.value, e,
                    )
            return IssueProcessResult(
                issue_number=issue_number,
                starting_state=starting_state,
                final_state=target_state.value,
                synthesis_outcome=None,
                cost_usd=cumulative_cost,
                duration_seconds=time.monotonic() - per_issue_start,
                error=None if success else "fast-forward failed",
            )

        # Sprint 15.04 — for channel-member issues, ensure the integration
        # branch exists before implement runs. Determine the base branch
        # passed to the implement runner so the worktree branches off
        # integration (not main).
        base_branch = "main"
        if channel is not None:
            _ensure_integration_branch(channel, repo=self._repo)
            base_branch = channel.integration_branch

        # Phase 1 — implement.
        try:
            impl_kwargs: dict[str, Any] = {"repo": self._repo}
            if channel is not None:
                impl_kwargs["base_branch"] = base_branch
            # Sprint D1.2 — wire factory_mailbox_enabled so the per-issue
            # mailbox primitive activates when the flag is on.
            mailbox_enabled, _poll, _decision_to = _load_mailbox_settings()
            if mailbox_enabled:
                impl_kwargs["mailbox_enabled"] = True
                impl_kwargs["mailbox_data_dir"] = (
                    self.data_dir / "factory-mailboxes"
                )
            impl_result = self._implement(
                issue_number,
                **impl_kwargs,
            )
            # Awaitable support — primarily for tests using AsyncMock.
            if asyncio.iscoroutine(impl_result):
                impl_result = await impl_result
        except Exception as e:
            logger.exception(
                "factory_orchestrator: implement_issue raised on #%s: %s",
                issue_number, e,
            )
            return IssueProcessResult(
                issue_number=issue_number,
                starting_state=starting_state,
                final_state=NEEDS_HUMAN_STATE.value,
                synthesis_outcome=None,
                cost_usd=cumulative_cost,
                duration_seconds=time.monotonic() - per_issue_start,
                error=str(e)[:300],
            )

        impl_cost = float(getattr(impl_result, "cost_usd", 0.0) or 0.0)
        cumulative_cost += impl_cost
        impl_failed_phase = getattr(impl_result, "failed_phase", None)
        impl_final_state = getattr(impl_result, "final_state", None)
        pr_number = getattr(impl_result, "pr_number", None)
        pr_url = getattr(impl_result, "pr_url", None) or ""

        # If implement already terminated (failure routed itself), respect it.
        if impl_failed_phase or pr_number is None:
            final_state_str = (
                impl_final_state.value
                if isinstance(impl_final_state, FactoryState)
                else NEEDS_HUMAN_STATE.value
            )
            return IssueProcessResult(
                issue_number=issue_number,
                starting_state=starting_state,
                final_state=final_state_str,
                synthesis_outcome=None,
                cost_usd=cumulative_cost,
                duration_seconds=time.monotonic() - per_issue_start,
                error=(
                    f"implement failed at {impl_failed_phase}"
                    if impl_failed_phase
                    else None
                ),
            )

        # Phase 2 — validate (4 holdout reviewers).
        try:
            diff_text = _gh_pr_diff(int(pr_number), self._repo)
            validate_result = await self._validate(
                issue_body=issue_body,
                pr_url=pr_url,
                diff_text=diff_text,
            )
        except Exception as e:
            logger.exception(
                "factory_orchestrator: validate raised on #%s: %s",
                issue_number, e,
            )
            return IssueProcessResult(
                issue_number=issue_number,
                starting_state=starting_state,
                final_state=NEEDS_HUMAN_STATE.value,
                synthesis_outcome=None,
                cost_usd=cumulative_cost,
                duration_seconds=time.monotonic() - per_issue_start,
                error=str(e)[:300],
            )

        cumulative_cost += float(
            getattr(validate_result, "total_cost_usd", 0.0) or 0.0
        )

        # Phase 3 — synthesize.
        decision = self._synthesize(
            SynthesisInput(
                validate_result=validate_result,
                total_cost_usd=cumulative_cost,
                retry_count=0,
            ),
            cost_cap_usd=self._cost_cap_per_issue,
        )

        # Phase 3a — RETRY_REVIEWERS handling. One retry, then re-synthesize.
        if decision.outcome == FactorySynthesisOutcome.RETRY_REVIEWERS:
            prior_signature = tuple(
                sorted(
                    reason.strip().lower()
                    for reason in (
                        getattr(validate_result, "block_reasons", ()) or ()
                    )
                )
            )
            try:
                validate_result = await self._validate(
                    issue_body=issue_body,
                    pr_url=pr_url,
                    diff_text=diff_text,
                )
            except Exception as e:
                logger.exception(
                    "factory_orchestrator: validate retry raised on #%s: %s",
                    issue_number, e,
                )
                return IssueProcessResult(
                    issue_number=issue_number,
                    starting_state=starting_state,
                    final_state=NEEDS_HUMAN_STATE.value,
                    synthesis_outcome=decision.outcome.value,
                    cost_usd=cumulative_cost,
                    duration_seconds=time.monotonic() - per_issue_start,
                    error=str(e)[:300],
                )
            cumulative_cost += float(
                getattr(validate_result, "total_cost_usd", 0.0) or 0.0
            )
            decision = self._synthesize(
                SynthesisInput(
                    validate_result=validate_result,
                    total_cost_usd=cumulative_cost,
                    retry_count=1,
                    prior_block_signature=prior_signature,
                ),
                cost_cap_usd=self._cost_cap_per_issue,
            )

        # Phase 3b — fresh-context fix loop (Sprint 14.09). Triggered only
        # when the synthesizer returned NEEDS_FIX AND the operator opted
        # in via ``factory_fix_loop_enabled``. The loop spawns up to N
        # fresh Claude subprocesses (no --resume) to address the block
        # reasons, re-validates, re-synthesizes after each attempt, and
        # escalates if attempts exhaust without resolution. The loop's
        # ``final_outcome`` then drives Phase 4 routing instead of the
        # original NEEDS_FIX decision.
        if (
            decision.outcome == FactorySynthesisOutcome.NEEDS_FIX
            and self._fix_loop_enabled
        ):
            try:
                fix_result = await self._run_fix_loop(
                    initial_decision=decision,
                    issue_body=issue_body,
                    pr_url=pr_url,
                    initial_diff=diff_text,
                )
            except Exception as e:  # pragma: no cover — fail-soft logging
                logger.exception(
                    "factory_orchestrator: fix loop raised on #%s: %s — "
                    "falling back to original NEEDS_FIX routing",
                    issue_number, e,
                )
            else:
                cumulative_cost += float(fix_result.total_cost_usd or 0.0)
                # Replace the decision with one carrying the loop's verdict
                # so Phase 4 routes to the post-loop state. ``rule_fired``
                # is preserved for telemetry; explanation gets a suffix.
                decision = SynthesisDecision(
                    outcome=fix_result.final_outcome,
                    rule_fired=decision.rule_fired,
                    explanation=(
                        f"{decision.explanation} | fix loop: "
                        f"{len(fix_result.attempts)} attempt(s), "
                        f"escalated={fix_result.escalated_to_human}"
                    ),
                    block_reasons=decision.block_reasons,
                    advise_reasons=decision.advise_reasons,
                    fixable_blocks=decision.fixable_blocks,
                    nonfixable_blocks=decision.nonfixable_blocks,
                )

        # Phase 4 — apply route plan.
        plan = _route_outcome(
            decision.outcome,
            explanation=decision.explanation,
            block_reasons=decision.block_reasons,
            advise_reasons=decision.advise_reasons,
        )

        # Comment first (audit trail), then state transition, then PR ready.
        _gh_issue_comment(issue_number, plan.comment_body, repo=self._repo)

        # Best-effort transition. Implement already moved to NEEDS_REVIEW
        # on success — most outcomes' targets equal that, so the transition
        # is a no-op. RETRY_REVIEWERS keeps it where it is.
        for prior in (
            FactoryState.NEEDS_REVIEW,
            FactoryState.IN_PROGRESS,
            FactoryState.ACCEPTED,
        ):
            try:
                if transition_state(issue_number, prior, plan.target_state):
                    break
            except Exception as e:  # pragma: no cover — best-effort logging
                logger.warning(
                    "factory_orchestrator: transition #%s %s→%s raised: %s",
                    issue_number, prior.value, plan.target_state.value, e,
                )

        if plan.mark_pr_ready and pr_number is not None:
            _gh_pr_ready_for_review(int(pr_number), repo=self._repo)

        # Sprint 15.04 — channel-close auto-filing. After a successful
        # READY_* outcome on a channel-member issue, check whether this
        # issue's closure (or imminent closure on operator approval)
        # would leave the channel with zero open members; if so, file
        # the channel-close issue. Best-effort: failures log + continue.
        if (
            channel is not None
            and not channel.is_close_issue
            and plan.target_state == AWAITING_REVIEW_STATE
        ):
            self._maybe_file_channel_close(
                channel=channel,
                triggering_issue_number=issue_number,
            )

        return IssueProcessResult(
            issue_number=issue_number,
            starting_state=starting_state,
            final_state=plan.target_state.value,
            synthesis_outcome=decision.outcome.value,
            cost_usd=cumulative_cost,
            duration_seconds=time.monotonic() - per_issue_start,
            error=None,
        )

    def _maybe_file_channel_close(
        self,
        *,
        channel: ChannelInfo,
        triggering_issue_number: int,
    ) -> None:
        """File the channel-close issue if no other open members remain.

        Best-effort, never raises. Excludes the triggering issue from the
        "still open" count because by the time the orchestrator reaches
        this hook the issue has been routed to ``factory:needs-review``
        (still open from GitHub's POV but functionally done from the
        channel's POV — operator merge will close it). Subsequent ticks
        will recompute and either file the close issue then or skip
        because it's already filed.
        """
        try:
            open_labels = _gh_list_open_issues_with_labels(self._repo)
            # Drop the triggering issue from consideration so we file the
            # close issue on the *last* member's review-ready transition.
            open_labels.pop(triggering_issue_number, None)
            if not is_channel_close_ready(
                channel.name,
                open_issue_labels_by_number=open_labels,
            ):
                return
            # Avoid duplicates: scan for an existing close issue for
            # this channel and abort if present.
            close_label = (
                f"{CHANNEL_CLOSE_LABEL_PREFIX}{channel.name}"
            )
            for labels in open_labels.values():
                if close_label in labels:
                    return
            # Best-effort: walk closed_issue_numbers from prior members.
            closed_members = self._collect_channel_member_numbers(
                channel.name,
            )
            new_number = _gh_create_channel_close_issue(
                channel=channel,
                closed_issue_numbers=closed_members,
                repo=self._repo,
                branch_prefix=self._integration_branch_prefix,
            )
            if new_number is not None:
                logger.info(
                    "factory_orchestrator: filed channel-close issue #%s "
                    "for channel %s",
                    new_number, channel.name,
                )
        except Exception as e:  # pragma: no cover — defensive logging
            logger.warning(
                "factory_orchestrator: channel-close auto-file for %s "
                "raised: %s",
                channel.name, e,
            )

    def _collect_channel_member_numbers(self, channel_name: str) -> list[int]:
        """Return closed-issue numbers carrying ``factory:channel:<name>``.

        Used to enumerate children in the channel-close issue body. Best-
        effort: a gh failure returns an empty list rather than raising.
        """
        member_label = f"factory:channel:{channel_name}"
        rc, stdout, _stderr = _run_gh(
            [
                "issue", "list",
                "--repo", self._repo,
                "--state", "closed",
                "--label", member_label,
                "--limit", "200",
                "--json", "number",
            ]
        )
        if rc != 0:
            return []
        try:
            payload = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        out: list[int] = []
        for entry in payload:
            if isinstance(entry, dict):
                num = entry.get("number")
                if isinstance(num, int):
                    out.append(num)
        return sorted(out)

    # ------------------------------------------------------------------
    # Fix loop dispatch (Sprint 14.09)
    # ------------------------------------------------------------------

    async def _run_fix_loop(
        self,
        *,
        initial_decision: SynthesisDecision,
        issue_body: str,
        pr_url: str,
        initial_diff: str,
    ) -> FixLoopResult:
        """Dispatch the fresh-context fix loop.

        The loop is gated by ``self._fix_loop_enabled``; the call site in
        ``_process_issue`` already checks that, but the gate here is a
        defensive backstop so a future caller can't accidentally run the
        loop with the flag off. ``fix_runner`` is required when the loop
        is enabled — if no runner is wired, the loop is a no-op (returns
        the initial NEEDS_FIX decision unchanged) and logs a warning.
        """
        if self._fix_runner is None:
            logger.warning(
                "factory_orchestrator: fix loop enabled but no fix_runner "
                "wired — skipping loop, routing to FIX_ATTEMPT_1 as before"
            )
            return FixLoopResult(
                attempts=(),
                final_outcome=initial_decision.outcome,
                final_state=outcome_to_factory_state(initial_decision.outcome),
                total_cost_usd=0.0,
                escalated_to_human=False,
            )

        # Adapt the orchestrator's stored validate runner (kwargs-only) to
        # the fix-loop's positional contract. Sync runners are tolerated
        # for tests via ``asyncio.iscoroutine``.
        async def _validate_adapter(
            issue_body_in: str, pr_url_in: str, diff_text_in: str,
        ) -> Any:
            result = self._validate(
                issue_body=issue_body_in,
                pr_url=pr_url_in,
                diff_text=diff_text_in,
            )
            if asyncio.iscoroutine(result):
                return await result
            return result

        return await run_fix_loop(
            initial_decision=initial_decision,
            issue_body=issue_body,
            pr_url=pr_url,
            initial_diff=initial_diff,
            fix_runner=self._fix_runner,
            validate_runner=_validate_adapter,
            max_attempts=self._fix_loop_max_attempts,
            cost_cap_per_attempt_usd=self._fix_loop_cost_cap_per_attempt,
            cost_cap_total_usd=self._fix_loop_cost_cap_total,
        )

    # ------------------------------------------------------------------
    # Default validate runner — wraps ``validate_pr`` with a no-op runner.
    # ------------------------------------------------------------------

    async def _default_validate_runner(
        self,
        *,
        issue_body: str,
        pr_url: str,
        diff_text: str,
    ) -> ValidateResult:
        """Default validate path — uses ``bridge.factory.validate.validate_pr``.

        The reviewer subprocess runner is *not* wired here on purpose. The
        caller injects a real Haiku-backed runner via the ``validate_runner``
        kwarg in production; for the orchestrator's own default we delegate
        to a stub that always parse-errors so the tick degrades gracefully
        rather than burning cost without an injected runner.
        """

        async def _stub_runner(
            prompt: str, *, model: str = "haiku"
        ) -> tuple[str, float, int]:
            # Deliberately incomplete output — _parse_reviewer_output will
            # treat this as a parse error. Synthesizer Rule 5 retries once,
            # then Rule 6 abandons. Net effect: orchestrator escalates to
            # NEEDS_HUMAN without burning real budget.
            return ("", 0.0, 0)

        return await validate_pr(
            issue_body=issue_body,
            pr_url=pr_url,
            diff_text=diff_text,
            runner=_stub_runner,
        )


# ── Module entry point ───────────────────────────────────────────────────


def main() -> None:
    """Entry point invoked by ``python -m bridge.services.runner factory_orchestrator``.

    Wires the orchestrator against the live BridgeConfig, runtime data dir,
    and operator chat id — same lookup the runner uses for every other
    service. The runner imports the class via SERVICE_MAP; this function
    exists so an operator can also smoke-test the service standalone via
    ``python -m bridge.services.factory_orchestrator``.
    """
    import logging
    from bridge.config import load_config

    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    # audit-2026-05-16.C.05 — build the subprocess-side halt policy from
    # the on-disk halt flag (no SecurityManager in this context).
    halt_policy = _build_runtime_halt_policy(Path(cfg.data_dir))
    orchestrator = FactoryOrchestrator(
        data_dir=cfg.data_dir,
        config_enabled=getattr(cfg, "factory_orchestrator_enabled", False),
        halt_policy=halt_policy,
        # Sprint 15.04 — channels-as-branches gating.
        channels_enabled=getattr(cfg, "factory_channels_enabled", False),
        integration_branch_prefix=getattr(
            cfg, "factory_channels_integration_branch_prefix", "factory/channel"
        ),
        # Sprint 14.09 — fix loop wiring. Fix runner stays None here
        # because main() doesn't have a ClaudeRunner handy; the bridge
        # boot path constructs ClaudeRunner separately and can pass
        # ``make_fix_runner(claude_runner)`` when wiring this service.
        fix_loop_enabled=getattr(cfg, "factory_fix_loop_enabled", False),
        fix_loop_max_attempts=getattr(
            cfg, "factory_fix_loop_max_attempts",
            FIX_LOOP_DEFAULT_MAX_ATTEMPTS,
        ),
        fix_loop_cost_cap_per_attempt_usd=getattr(
            cfg, "factory_fix_loop_cost_cap_per_attempt_usd",
            FIX_LOOP_DEFAULT_COST_CAP_PER_ATTEMPT_USD,
        ),
        fix_loop_cost_cap_total_usd=getattr(
            cfg, "factory_fix_loop_cost_cap_total_usd",
            FIX_LOOP_DEFAULT_COST_CAP_TOTAL_USD,
        ),
    )
    asyncio.run(orchestrator.run())


__all__ = [
    "AWAITING_REVIEW_STATE",
    "DEFAULT_COST_CAP_PER_ISSUE_USD",
    "DEFAULT_COST_CAP_PER_TICK_USD",
    "FactoryOrchestrator",
    "GLOBAL_LOCK_FILENAME",
    "GLOBAL_LOCK_STALE_S",
    "IssueProcessResult",
    "MAX_ISSUES_PER_TICK",
    "NEEDS_FIX_STATE",
    "NEEDS_HUMAN_STATE",
    "PER_TARGET_LOCK_DIRNAME",
    "PER_TARGET_LOCK_STALE_S",
    "TickResult",
    "main",
]


if __name__ == "__main__":
    main()
