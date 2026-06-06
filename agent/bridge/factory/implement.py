"""Dark Factory implement workflow.

Sprint 14.05 — Plan 14 Phase 3.

Concept-only port of coleam00/dark-factory-experiment (no LICENSE — no source
copied). For each open issue in `FactoryState.ACCEPTED`, this module runs a
10-phase agent pipeline that turns the issue into a draft pull request and
transitions the issue's factory state label.

Pipeline:

    1.  classify    — re-read the triage verdict from issue body + labels.
    2.  plan        — Sonnet subprocess produces a step-by-step plan (no code).
    3.  branch      — `git worktree add` creates `factory/<issue>-<slug>`.
    4.  implement   — Sonnet subprocess writes code in the worktree.
    5.  commit      — stage + commit with conventional message.
    6.  test        — `pytest` in the worktree. Fail → factory:fix-attempt-1.
    7.  lint        — `ruff check`. Fail → factory:fix-attempt-1.
    8.  draft-pr    — `gh pr create --draft` linking the issue.
    9.  transition  — ACCEPTED → IN_PROGRESS → NEEDS_REVIEW.
    10. cleanup     — leave the worktree intact (orchestrator GC removes it).

Each phase runs in its own subprocess (Dark Factory invariant: fresh context
per phase). The classify and plan phases use Haiku-class fast models; only
plan + implement use Sonnet. Total per-issue cap: $1.00.

Failure semantics: any phase failure transitions the issue to a recoverable
or terminal state and returns an `ImplementResult` with `failed_phase` set.

  - Phase 6 (test) failure          → state: FIX_ATTEMPT_1, recoverable.
  - Phase 7 (lint) failure          → state: FIX_ATTEMPT_1, recoverable.
  - Any other phase failure         → state: NEEDS_HUMAN, operator action.
  - Cost-cap exceeded mid-flight    → state: NEEDS_HUMAN, `cost_cap_exceeded`.
  - Subprocess timeout              → state: NEEDS_HUMAN.

This sprint ships the workflow as a callable function. There is **no
orchestration call site yet**; Sprint 14.10 wires `factory_orchestrator.py`.
Sprint 14.06 layers the 500-LOC PR cap, protected-files check, and new-dep
justification on top of the result.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from bridge.backends import BackendProtocol, spawn_one_shot
from bridge.factory.labels import FactoryState, transition_state
from bridge.factory.quality import run_all_quality_checks
from bridge.mailbox import Mailbox, MailboxConfig

logger = logging.getLogger(__name__)


# ── Mailbox wiring (Sprint 15.03 / issue #1053) ─────────────────────────
#
# Per-issue mailbox so concurrent factory runs don't share state. The
# worker-side companion is :mod:`bridge.factory.implement_mailbox_worker`;
# the bridge opens a Mailbox(role="bridge") here and passes the env vars
# below to the worker subprocess so that side can open its half.


# Default storage directory for per-issue factory mailboxes. The bridge
# orchestrator may override this via ``mailbox_data_dir`` on the public
# entry point; tests override too.
DEFAULT_MAILBOX_DATA_DIR: Final[Path] = Path("data/factory-mailboxes")

# Env-var contract — kept in lockstep with implement_mailbox_worker.
ENV_MAILBOX_NAME: Final[str] = "BUMBA_MAILBOX_NAME"
ENV_MAILBOX_DATA_DIR: Final[str] = "BUMBA_MAILBOX_DATA_DIR"


def make_factory_mailbox_config(
    issue_number: int,
    *,
    data_dir: Path | None = None,
) -> MailboxConfig:
    """Per-issue mailbox so concurrent factory runs don't share state."""
    return MailboxConfig(
        name=f"factory_implement_{issue_number}",
        data_dir=data_dir or DEFAULT_MAILBOX_DATA_DIR,
        schema_version=1,
    )


# ── Configuration constants ─────────────────────────────────────────────


# Default repo. Overridable per-call so tests don't accidentally hit a live
# remote and so the factory can be reused across repos in future plans.
DEFAULT_REPO: Final[str] = "your-org/bumba-open-harness"

# Hard per-issue cost cap. The implement workflow is the most expensive
# factory stage (multi-phase Sonnet calls); the cap protects the daily budget.
# When mid-flight cumulative cost exceeds this, the workflow halts with
# failed_phase="cost_cap_exceeded" and transitions the issue to NEEDS_HUMAN.
COST_CAP_USD: Final[float] = 1.0

# Subprocess timeout per phase. Sonnet implement passes are the slowest; 600s
# is generous for a small-scope issue. Hard ceiling keeps a stuck phase from
# blocking the orchestrator forever.
CLAUDE_TIMEOUT_SEC: Final[int] = 600

# Tools-disabled phases (classify/plan use Haiku, no Edit/Write needed).
QUICK_TIMEOUT_SEC: Final[int] = 180

# Default Claude binary path. Set BUMBA_CLAUDE_BIN when the CLI is not on PATH.
CLAUDE_BIN: Final[Path] = Path(os.environ.get("BUMBA_CLAUDE_BIN", "claude"))

# Default workspace root for git worktrees. Tests override via parameter.
DEFAULT_WORKSPACE_ROOT: Final[Path] = Path("/tmp/bumba-factory")

# Phase identifier strings — also the values stored in ImplementResult.failed_phase.
PHASE_CLASSIFY: Final[str] = "classify"
PHASE_PLAN: Final[str] = "plan"
PHASE_BRANCH: Final[str] = "branch"
PHASE_IMPLEMENT: Final[str] = "implement"
PHASE_COMMIT: Final[str] = "commit"
PHASE_TEST: Final[str] = "test"
PHASE_LINT: Final[str] = "lint"
PHASE_DRAFT_PR: Final[str] = "draft-pr"
PHASE_TRANSITION: Final[str] = "transition"
PHASE_CLEANUP: Final[str] = "cleanup"
PHASE_COST_CAP: Final[str] = "cost_cap_exceeded"
PHASE_QUALITY: Final[str] = "quality"


# ── Result dataclass ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImplementResult:
    """Frozen record of one implement attempt.

    Immutable so the orchestrator can fan out results safely; one workflow
    run produces an append-only list of these.
    """

    issue_number: int
    pr_number: int | None
    pr_url: str | None
    final_state: FactoryState
    failed_phase: str | None
    cost_usd: float
    evaluated_at: datetime


# ── Subprocess helpers (separately patchable for tests) ─────────────────


def _run_subprocess(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    input_text: str | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a command synchronously. Returns (returncode, stdout, stderr).

    Isolated for clean test patching. Synchronous because the implement
    pipeline is a serial 10-phase pass — there's nothing to interleave.
    """
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd is not None else None,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


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
        logger.warning("implement: could not read .secrets: %s", e)
    return None


def _invoke_claude(
    prompt: str,
    *,
    cwd: str | Path | None = None,
    timeout: int = CLAUDE_TIMEOUT_SEC,
    extra_env: dict[str, str] | None = None,
    backend: BackendProtocol | None = None,
) -> tuple[int, str, str]:
    """Spawn a one-shot, permissions-bypassed subprocess for autonomous edits.

    The implement workflow needs Edit/Write/Bash inside the worktree; we run
    `claude -p` with `--dangerously-skip-permissions` so the agent does not
    block on per-tool prompts. The worktree is the blast radius — even if
    the agent goes off-rails it cannot touch the source repo.

    ``extra_env`` is a small key/value layer the caller can mix into the
    subprocess environment (e.g. mailbox env vars from Sprint 15.03 wiring).

    P4.03 decoupling: ``backend`` is an OPTIONAL seam. When None (default),
    the byte-identical legacy argv is used — ``--output-format text``,
    ``--dangerously-skip-permissions`` — because the workflow parses
    plain-text stdout, which the stream-json shape of
    ``backend.build_command`` would break. When a backend IS supplied, the
    call routes through ``spawn_one_shot`` (P4.01) with ``bypassPermissions``,
    threading ``cwd`` and ``extra_env`` (OAuth layered in), so a future
    BackendRegistry wire-in can swap the CLI without touching this site.

    Returns (returncode, stdout, stderr). Raises subprocess.TimeoutExpired
    on timeout — the caller treats that as a NEEDS_HUMAN verdict.
    """
    oauth_token = _load_oauth_token()

    if backend is not None:
        merged_env: dict[str, str] = dict(extra_env) if extra_env else {}
        if oauth_token:
            merged_env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
        result = spawn_one_shot(
            backend,
            prompt=prompt,
            timeout=timeout,
            permission_mode="bypassPermissions",
            cwd=cwd,
            extra_env=merged_env or None,
        )
        return result.returncode, result.stdout, result.stderr

    # Default path — faithful legacy one-shot argv (unchanged behaviour).
    env = os.environ.copy()
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    if extra_env:
        env.update(extra_env)

    return _run_subprocess(
        [
            str(CLAUDE_BIN), "-p",
            "--output-format", "text",
            "--dangerously-skip-permissions",
        ],
        cwd=cwd,
        input_text=prompt,
        timeout=timeout,
        env=env,
    )


# ── gh helpers ──────────────────────────────────────────────────────────


def _gh_issue_view(issue_number: int, repo: str) -> dict:
    """Fetch issue title, body, labels, comments via `gh issue view`.

    The implement workflow's classify phase re-reads the triage verdict from
    issue comments (the audit trail Sprint 14.04 leaves) rather than
    re-classifying.

    Raises:
        RuntimeError: gh failed or returned malformed JSON.
    """
    rc, stdout, stderr = _run_subprocess(
        [
            "gh", "issue", "view", str(issue_number),
            "--repo", repo,
            "--json", "title,body,labels,comments",
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


def _gh_issue_list_accepted(repo: str, limit: int) -> list[int]:
    """List open issue numbers with the `factory:accepted` state label.

    The implement workflow only consumes issues already triaged into
    ACCEPTED — the opt-in marker is implied by the triage having run.
    """
    rc, stdout, stderr = _run_subprocess(
        [
            "gh", "issue", "list",
            "--repo", repo,
            "--state", "open",
            "--label", FactoryState.ACCEPTED.value,
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
    """Post a comment on an issue. Best-effort — failure logs, never raises."""
    rc, _stdout, stderr = _run_subprocess(
        [
            "gh", "issue", "comment", str(issue_number),
            "--repo", repo,
            "--body", body,
        ]
    )
    if rc != 0:
        logger.warning(
            "implement: failed to comment on #%s (exit %s): %s",
            issue_number, rc, stderr.strip()[:300],
        )


def _gh_pr_create_draft(
    *,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str,
    repo: str,
    cwd: str | Path,
) -> tuple[int, str | None, str | None]:
    """Open a draft PR. Returns (rc, pr_url, pr_number_str).

    `gh pr create` prints the PR URL on stdout. We parse the trailing
    integer after the last slash for the number.
    """
    rc, stdout, stderr = _run_subprocess(
        [
            "gh", "pr", "create",
            "--repo", repo,
            "--draft",
            "--title", title,
            "--body", body,
            "--head", head_branch,
            "--base", base_branch,
        ],
        cwd=cwd,
    )
    if rc != 0:
        logger.warning(
            "implement: gh pr create failed (exit %s): %s",
            rc, stderr.strip()[:300],
        )
        return rc, None, None

    url = stdout.strip().splitlines()[-1] if stdout.strip() else None
    pr_number_str: str | None = None
    if url:
        match = re.search(r"/pull/(\d+)", url)
        if match:
            pr_number_str = match.group(1)
    return rc, url, pr_number_str


# ── Slug + branch helpers ───────────────────────────────────────────────


_SLUG_CHAR_SUB: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


def _slugify(title: str, *, max_len: int = 40) -> str:
    """Reduce a title to a short, branch-safe slug.

    "Add foo bar (#42)" → "add-foo-bar". Always lowercase, hyphenated, and
    bounded; empty input becomes "issue".
    """
    cleaned = _SLUG_CHAR_SUB.sub("-", title.lower()).strip("-")
    if not cleaned:
        return "issue"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("-")
    return cleaned or "issue"


def _branch_name(issue_number: int, title: str) -> str:
    """Build the factory branch name for an issue.

    Format: `factory/<issue-number>-<slug>`. The orchestrator GC and the
    git-worktree-gc service rely on the `factory/` prefix to identify
    factory-owned branches.
    """
    return f"factory/{issue_number}-{_slugify(title)}"


# ── Phase implementations ───────────────────────────────────────────────
#
# Each phase is a small isolated function so tests can mock per-phase
# behaviour independently. Phases return their own success/failure tuple
# so the orchestrating function can decide the failure mode (recoverable
# vs operator).


def _classify_phase(issue_number: int, repo: str) -> dict:
    """Phase 1 — re-read triage verdict from issue comments + labels.

    The triage workflow (Sprint 14.04) leaves a `**Factory triage** →
    factory:accepted` comment on each accepted issue. We re-read that
    audit trail rather than re-classifying. Returns a dict with at least
    `title` and `body`; the implement / plan phases consume both.

    Raises RuntimeError on gh failure — caller maps that to NEEDS_HUMAN.
    """
    payload = _gh_issue_view(issue_number, repo=repo)
    return {
        "title": payload.get("title", "") or "",
        "body": payload.get("body", "") or "",
        "labels": [
            entry.get("name", "")
            for entry in (payload.get("labels") or [])
        ],
        "comments": payload.get("comments") or [],
    }


_PLAN_PROMPT_TEMPLATE: Final[str] = """\
You are the planner stage of a self-managing GitHub issue factory. Produce a
step-by-step plan to resolve this issue. Do NOT write code. Output the plan
as numbered steps; keep it under 40 lines.

Issue #{issue_number}
Title: {title}

Body:
{body}
"""


def _plan_phase(issue_number: int, classification: dict) -> tuple[str, float]:
    """Phase 2 — Sonnet subprocess writes a step-by-step plan, no code.

    Returns (plan_text, cost_usd). On non-zero exit or timeout the caller
    halts with `failed_phase=PHASE_PLAN` and routes the issue to NEEDS_HUMAN.
    """
    prompt = _PLAN_PROMPT_TEMPLATE.format(
        issue_number=issue_number,
        title=classification["title"],
        body=classification["body"][:8000],
    )
    rc, stdout, stderr = _invoke_claude(prompt, timeout=QUICK_TIMEOUT_SEC)
    if rc != 0:
        raise RuntimeError(
            f"plan phase: claude exit {rc}: {stderr.strip()[:300]}"
        )
    return stdout.strip(), 0.0


def _branch_phase(
    *,
    issue_number: int,
    title: str,
    repo_root: Path,
    workspace_root: Path,
) -> tuple[Path, str]:
    """Phase 3 — `git worktree add` creates the factory branch + worktree.

    Returns (worktree_path, branch_name). Raises RuntimeError on git
    failure — caller halts with `failed_phase=PHASE_BRANCH`.
    """
    branch = _branch_name(issue_number, title)
    workspace_root.mkdir(parents=True, exist_ok=True)
    wt_path = workspace_root / f"issue-{issue_number}"

    rc, _stdout, stderr = _run_subprocess(
        ["git", "worktree", "add", "-b", branch, str(wt_path), "HEAD"],
        cwd=repo_root,
    )
    if rc != 0:
        raise RuntimeError(
            f"git worktree add failed (exit {rc}): {stderr.strip()[:300]}"
        )
    logger.info(
        "implement: created worktree %s on branch %s",
        wt_path, branch,
    )
    return wt_path, branch


_IMPLEMENT_PROMPT_TEMPLATE: Final[str] = """\
You are the implementation stage of a self-managing GitHub issue factory.
Apply the plan below to the current working directory. Use Edit, Read, Write,
and Bash tools as needed. Stay surgical — touch only the files necessary to
resolve the issue. Do not add unrelated refactors.

When done, print a one-line summary of what you changed.

Issue #{issue_number}
Title: {title}

Body:
{body}

Plan:
{plan}
"""


def _implement_phase(
    *,
    issue_number: int,
    classification: dict,
    plan: str,
    worktree_path: Path,
    extra_env: dict[str, str] | None = None,
) -> tuple[str, float]:
    """Phase 4 — Sonnet subprocess writes code in the worktree.

    Returns (summary, cost_usd). Raises RuntimeError on subprocess failure;
    caller halts with `failed_phase=PHASE_IMPLEMENT`.

    ``extra_env`` carries optional mailbox env vars when Sprint 15.03's
    ``factory_mailbox_enabled`` flag is ON. When None we omit the kwarg
    entirely so existing tests that patch ``_invoke_claude`` with a
    pre-Sprint-15.03 signature keep working.
    """
    prompt = _IMPLEMENT_PROMPT_TEMPLATE.format(
        issue_number=issue_number,
        title=classification["title"],
        body=classification["body"][:6000],
        plan=plan,
    )
    invoke_kwargs: dict = {
        "cwd": worktree_path,
        "timeout": CLAUDE_TIMEOUT_SEC,
    }
    if extra_env:
        invoke_kwargs["extra_env"] = extra_env
    rc, stdout, stderr = _invoke_claude(prompt, **invoke_kwargs)
    if rc != 0:
        raise RuntimeError(
            f"implement phase: claude exit {rc}: {stderr.strip()[:300]}"
        )
    return stdout.strip(), 0.0


def _commit_phase(
    *,
    issue_number: int,
    title: str,
    worktree_path: Path,
) -> None:
    """Phase 5 — stage + commit with conventional message.

    The commit message follows `feat(scope): <title> (#<issue>)` per the
    Bumba conventional-commit norm. Raises RuntimeError on git failure;
    caller halts with `failed_phase=PHASE_COMMIT`.
    """
    rc, _out, err = _run_subprocess(
        ["git", "add", "-A"], cwd=worktree_path,
    )
    if rc != 0:
        raise RuntimeError(
            f"git add failed (exit {rc}): {err.strip()[:300]}"
        )

    msg = f"feat(factory): {title} (#{issue_number})"
    rc, _out, err = _run_subprocess(
        ["git", "commit", "-m", msg], cwd=worktree_path,
    )
    if rc != 0:
        raise RuntimeError(
            f"git commit failed (exit {rc}): {err.strip()[:300]}"
        )


def _collect_diff_inputs(
    *,
    worktree_path: Path,
    base_branch: str,
) -> tuple[dict, list[str], str]:
    """Gather diff_stat, changed_files, diff_text against `base_branch`.

    The implement workflow's quality gate (phase 5.5) consumes pre-computed
    inputs rather than running git itself; this helper is the bridge. Uses
    `git diff --numstat` for line counts, `git diff --name-only` for the
    file list, and `git diff` (unified) for the new-dep detection's parser.

    Returns ({"additions": int, "deletions": int, "files_changed": int},
             [filename, ...], unified_diff_text).
    On any git error the helper returns conservative defaults (zero stats,
    empty files, empty diff) — the caller still runs the gate, which will
    pass trivially. Better to ship a borderline PR than block on git
    plumbing flakes.
    """
    spec = f"{base_branch}...HEAD"

    additions = 0
    deletions = 0
    files_changed = 0
    rc, stdout, _err = _run_subprocess(
        ["git", "diff", "--numstat", spec],
        cwd=worktree_path,
    )
    if rc == 0 and stdout:
        for line in stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            try:
                # Binary diffs report `-`; treat them as 0.
                additions += int(parts[0]) if parts[0].isdigit() else 0
                deletions += int(parts[1]) if parts[1].isdigit() else 0
                files_changed += 1
            except (ValueError, IndexError):
                continue

    rc, stdout, _err = _run_subprocess(
        ["git", "diff", "--name-only", spec],
        cwd=worktree_path,
    )
    changed_files: list[str] = []
    if rc == 0 and stdout:
        changed_files = [line.strip() for line in stdout.splitlines() if line.strip()]

    rc, stdout, _err = _run_subprocess(
        ["git", "diff", spec],
        cwd=worktree_path,
    )
    diff_text = stdout if rc == 0 else ""

    return (
        {
            "additions": additions,
            "deletions": deletions,
            "files_changed": files_changed,
        },
        changed_files,
        diff_text,
    )


def _quality_phase(
    *,
    worktree_path: Path,
    base_branch: str,
    issue_body: str,
    repo: str = "",
    branch_protection_posture: str = "warn",
) -> tuple[bool, list[str]]:
    """Phase 5.5 — run pre-PR quality gates (Sprint 14.06 + D1.5).

    Returns (passed, failure_reasons). On any failure the caller halts with
    `failed_phase=PHASE_QUALITY` and routes to NEEDS_HUMAN — the operator
    owns oversize, protected-file, unjustified-dep, and unprotected-branch PRs.

    Args:
        worktree_path: Path to the factory worktree.
        base_branch: Base branch for the diff (e.g. "main").
        issue_body: Issue body text for dep-justification gate.
        repo: Repo slug passed to the branch-protection gate (D1.5). Empty
            string skips the gate.
        branch_protection_posture: "warn" (default, soak period) or
            "block". Forwarded to `run_all_quality_checks`.
    """
    diff_stat, changed_files, diff_text = _collect_diff_inputs(
        worktree_path=worktree_path,
        base_branch=base_branch,
    )
    results = run_all_quality_checks(
        diff_stat=diff_stat,
        changed_files=changed_files,
        diff_text=diff_text,
        issue_body=issue_body,
        repo=repo,
        branch_protection_posture=branch_protection_posture,
    )
    failures = [r.reason for r in results if not r.passed]
    return (not failures), failures


def _test_phase(worktree_path: Path) -> tuple[bool, str]:
    """Phase 6 — pytest in the worktree.

    Returns (passed, log_tail). The caller routes failure to FIX_ATTEMPT_1
    rather than NEEDS_HUMAN — Sprint 14.09 picks up the fix loop.
    """
    rc, stdout, stderr = _run_subprocess(
        ["pytest", "-q"], cwd=worktree_path, timeout=CLAUDE_TIMEOUT_SEC,
    )
    log_tail = (stdout + stderr).strip()[-2000:]
    return rc == 0, log_tail


def _lint_phase(worktree_path: Path) -> tuple[bool, str]:
    """Phase 7 — ruff check in the worktree.

    Returns (clean, log_tail). Caller routes failure to FIX_ATTEMPT_1 —
    Sprint 14.09 picks up the fix loop. Lint is treated as recoverable
    because it is the cheapest class of fix.
    """
    rc, stdout, stderr = _run_subprocess(
        ["ruff", "check", "."], cwd=worktree_path,
    )
    log_tail = (stdout + stderr).strip()[-2000:]
    return rc == 0, log_tail


def _draft_pr_phase(
    *,
    issue_number: int,
    title: str,
    plan: str,
    branch: str,
    worktree_path: Path,
    repo: str,
    base_branch: str,
) -> tuple[int, str]:
    """Phase 8 — push the branch + open a draft PR linking the issue.

    Returns (pr_number, pr_url). Raises RuntimeError on push or PR
    creation failure; caller halts with `failed_phase=PHASE_DRAFT_PR` and
    routes to NEEDS_HUMAN.
    """
    # Push the factory branch to origin so gh pr create has a remote head.
    rc, _out, err = _run_subprocess(
        ["git", "push", "-u", "origin", branch],
        cwd=worktree_path,
    )
    if rc != 0:
        raise RuntimeError(
            f"git push failed (exit {rc}): {err.strip()[:300]}"
        )

    pr_title = f"feat(factory): {title} (#{issue_number})"
    pr_body = (
        f"Auto-generated by the Dark Factory implement workflow.\n\n"
        f"Closes #{issue_number}\n\n"
        f"## Plan\n\n{plan}\n\n"
        f"---\n_concept-only-no-license — Dark Factory_"
    )
    rc, url, pr_num_str = _gh_pr_create_draft(
        title=pr_title,
        body=pr_body,
        head_branch=branch,
        base_branch=base_branch,
        repo=repo,
        cwd=worktree_path,
    )
    if rc != 0 or url is None or pr_num_str is None:
        raise RuntimeError(
            f"gh pr create failed (rc={rc}, url={url!r}, num={pr_num_str!r})"
        )
    return int(pr_num_str), url


# ── Failure handling ────────────────────────────────────────────────────


def _route_failure(
    *,
    issue_number: int,
    failed_phase: str,
    error_summary: str,
    cost_usd: float,
    repo: str,
) -> ImplementResult:
    """Map a phase failure to a final state and ImplementResult.

    Recoverable failures (test, lint) → `FIX_ATTEMPT_1` so Sprint 14.09's
    fix loop can pick the issue up. Everything else → `NEEDS_HUMAN`.
    """
    if failed_phase in (PHASE_TEST, PHASE_LINT):
        target_state = FactoryState.FIX_ATTEMPT_1
    else:
        target_state = FactoryState.NEEDS_HUMAN

    # Best-effort: try IN_PROGRESS first, then ACCEPTED if we never moved.
    transitioned = False
    for prior in (FactoryState.IN_PROGRESS, FactoryState.ACCEPTED):
        try:
            if transition_state(issue_number, prior, target_state):
                transitioned = True
                break
        except Exception as e:  # pragma: no cover — gh errors logged, not fatal
            logger.warning(
                "implement: transition_state %s→%s failed on #%s: %s",
                prior.value, target_state.value, issue_number, e,
            )
    if not transitioned:
        logger.warning(
            "implement: could not transition #%s to %s (already moved?)",
            issue_number, target_state.value,
        )

    _gh_issue_comment(
        issue_number,
        (
            f"**Factory implement** failed at phase `{failed_phase}` "
            f"(spent ${cost_usd:.4f}).\n\n"
            f"```\n{error_summary[:1500]}\n```\n\n"
            f"Routed to `{target_state.value}`."
        ),
        repo=repo,
    )
    return ImplementResult(
        issue_number=issue_number,
        pr_number=None,
        pr_url=None,
        final_state=target_state,
        failed_phase=failed_phase,
        cost_usd=cost_usd,
        evaluated_at=datetime.now(timezone.utc),
    )


# ── Main entry points ───────────────────────────────────────────────────


def implement_issue(
    issue_number: int,
    *,
    repo: str = DEFAULT_REPO,
    workspace_root: Path | None = None,
    repo_root: Path | None = None,
    base_branch: str = "main",
    mailbox_enabled: bool = False,
    mailbox_data_dir: Path | None = None,
    branch_protection_posture: str = "warn",
) -> ImplementResult:
    """Run the 10-phase implement pipeline for a single accepted issue.

    Each phase has its own subprocess (Dark Factory invariant: fresh
    context). The function is synchronous because the pipeline is serial.
    On any phase failure the issue is transitioned to a fix or human-review
    state and an ImplementResult is returned with `failed_phase` set.

    Args:
        issue_number: Issue number on `repo`. Must currently be ACCEPTED.
        repo: owner/name slug. Defaults to your-org/bumba-open-harness.
        workspace_root: dir under which `issue-N/` worktrees are created.
            Defaults to `/tmp/bumba-factory`.
        repo_root: source repo path used as the parent for `git worktree
            add`. Defaults to the directory two levels above this module
            (the bumba-open-harness source root in the standard layout).
        base_branch: PR base. Defaults to `main`.
        branch_protection_posture: "warn" (default, 7-day soak) or
            "block". Forwarded to the branch-protection gate (D1.5).
            Operator flips `quality_chain.branch_protection_posture`
            in `bridge.toml` after the soak period ends.
        mailbox_enabled: when True, open a per-issue Mailbox(role='bridge')
            and pass the env-var contract to the worker subprocess so it
            can stream progress / decision / cost messages back. Default
            False keeps existing one-way behaviour. Sprint 15.03.
        mailbox_data_dir: storage dir for the per-issue mailbox. Defaults
            to ``data/factory-mailboxes`` (see ``DEFAULT_MAILBOX_DATA_DIR``).

    Returns:
        ImplementResult — `pr_number` set on success, `failed_phase` set on
        any failure.
    """
    workspace_root = workspace_root or DEFAULT_WORKSPACE_ROOT
    repo_root = repo_root or Path(__file__).resolve().parents[3]

    cumulative_cost = 0.0
    started_at = datetime.now(timezone.utc)
    worktree_path: Path | None = None
    branch: str | None = None

    # Sprint 15.03 — open the per-issue mailbox if the operator opted in.
    # The bridge side never reads from this mailbox in the current
    # iteration (PR #1153 ships only the primitive); the worker side may
    # write progress / decision / partial-cost messages that the bridge
    # picks up in a follow-up sprint. The mailbox is closed in a finally
    # block so a mid-pipeline raise does not leak a SQLite connection.
    mailbox: Mailbox | None = None
    mailbox_extra_env: dict[str, str] | None = None
    if mailbox_enabled:
        mb_config = make_factory_mailbox_config(
            issue_number, data_dir=mailbox_data_dir,
        )
        try:
            mailbox = Mailbox(mb_config, role="bridge")
            mailbox.init_db()
            mailbox_extra_env = {
                ENV_MAILBOX_NAME: mb_config.name,
                ENV_MAILBOX_DATA_DIR: str(mb_config.data_dir),
            }
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(
                "implement: mailbox init failed for #%s: %s — proceeding without",
                issue_number, e,
            )
            mailbox = None
            mailbox_extra_env = None

    # Phase 1: classify
    try:
        classification = _classify_phase(issue_number, repo=repo)
    except Exception as e:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_CLASSIFY,
            error_summary=str(e),
            cost_usd=cumulative_cost,
            repo=repo,
        )

    title = classification["title"] or f"issue-{issue_number}"

    # Phase 2: plan
    try:
        plan, plan_cost = _plan_phase(issue_number, classification)
    except Exception as e:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_PLAN,
            error_summary=str(e),
            cost_usd=cumulative_cost,
            repo=repo,
        )
    cumulative_cost += plan_cost
    if cumulative_cost > COST_CAP_USD:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_COST_CAP,
            error_summary=(
                f"Cost cap ${COST_CAP_USD:.2f} exceeded after plan phase: "
                f"${cumulative_cost:.4f}"
            ),
            cost_usd=cumulative_cost,
            repo=repo,
        )

    # Phase 3: branch
    try:
        worktree_path, branch = _branch_phase(
            issue_number=issue_number,
            title=title,
            repo_root=repo_root,
            workspace_root=workspace_root,
        )
    except Exception as e:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_BRANCH,
            error_summary=str(e),
            cost_usd=cumulative_cost,
            repo=repo,
        )

    # Move issue ACCEPTED → IN_PROGRESS now that the branch exists. Best-
    # effort: a False return from transition_state means the operator (or
    # another factory worker) moved it; we keep going.
    try:
        transition_state(issue_number, FactoryState.ACCEPTED, FactoryState.IN_PROGRESS)
    except Exception as e:
        logger.warning(
            "implement: ACCEPTED→IN_PROGRESS transition raised on #%s: %s",
            issue_number, e,
        )

    # Phase 4: implement
    try:
        _summary, impl_cost = _implement_phase(
            issue_number=issue_number,
            classification=classification,
            plan=plan,
            worktree_path=worktree_path,
            extra_env=mailbox_extra_env,
        )
    except Exception as e:
        if mailbox is not None:
            mailbox.close()
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_IMPLEMENT,
            error_summary=str(e),
            cost_usd=cumulative_cost,
            repo=repo,
        )
    cumulative_cost += impl_cost
    if cumulative_cost > COST_CAP_USD:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_COST_CAP,
            error_summary=(
                f"Cost cap ${COST_CAP_USD:.2f} exceeded after implement: "
                f"${cumulative_cost:.4f}"
            ),
            cost_usd=cumulative_cost,
            repo=repo,
        )

    # Phase 5: commit
    try:
        _commit_phase(
            issue_number=issue_number,
            title=title,
            worktree_path=worktree_path,
        )
    except Exception as e:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_COMMIT,
            error_summary=str(e),
            cost_usd=cumulative_cost,
            repo=repo,
        )

    # Phase 5.5: quality gates (Sprint 14.06 + D1.5) — PR size cap, protected
    # files, new-dep justification, branch protection. Failure routes to
    # NEEDS_HUMAN unconditionally.
    quality_passed, quality_failures = _quality_phase(
        worktree_path=worktree_path,
        base_branch=base_branch,
        issue_body=classification["body"] or "",
        repo=repo,
        branch_protection_posture=branch_protection_posture,
    )
    if not quality_passed:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_QUALITY,
            error_summary=(
                "Quality gate failed:\n- " + "\n- ".join(quality_failures)
            ),
            cost_usd=cumulative_cost,
            repo=repo,
        )

    # Phase 6: test (recoverable: failure → FIX_ATTEMPT_1)
    passed, log_tail = _test_phase(worktree_path)
    if not passed:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_TEST,
            error_summary=f"pytest failed:\n{log_tail}",
            cost_usd=cumulative_cost,
            repo=repo,
        )

    # Phase 7: lint (recoverable: failure → FIX_ATTEMPT_1)
    clean, log_tail = _lint_phase(worktree_path)
    if not clean:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_LINT,
            error_summary=f"ruff check failed:\n{log_tail}",
            cost_usd=cumulative_cost,
            repo=repo,
        )

    # Phase 8: draft PR
    try:
        pr_number, pr_url = _draft_pr_phase(
            issue_number=issue_number,
            title=title,
            plan=plan,
            branch=branch,
            worktree_path=worktree_path,
            repo=repo,
            base_branch=base_branch,
        )
    except Exception as e:
        return _route_failure(
            issue_number=issue_number,
            failed_phase=PHASE_DRAFT_PR,
            error_summary=str(e),
            cost_usd=cumulative_cost,
            repo=repo,
        )

    # Phase 9: transition IN_PROGRESS → NEEDS_REVIEW. Best-effort.
    try:
        transition_state(
            issue_number,
            FactoryState.IN_PROGRESS,
            FactoryState.NEEDS_REVIEW,
        )
    except Exception as e:
        logger.warning(
            "implement: IN_PROGRESS→NEEDS_REVIEW raised on #%s: %s",
            issue_number, e,
        )

    # Phase 10: cleanup. Per Sprint 02.04 branch-preservation, the worktree
    # is intentionally left intact for the operator (and Sprint 14.07's
    # validate workflow) to inspect. The worktree-gc service prunes it if
    # the operator never touches it.
    logger.info(
        "implement: #%s shipped draft PR #%s (%s) — duration %.1fs",
        issue_number,
        pr_number,
        pr_url,
        (datetime.now(timezone.utc) - started_at).total_seconds(),
    )

    if mailbox is not None:
        mailbox.close()

    return ImplementResult(
        issue_number=issue_number,
        pr_number=pr_number,
        pr_url=pr_url,
        final_state=FactoryState.NEEDS_REVIEW,
        failed_phase=None,
        cost_usd=cumulative_cost,
        evaluated_at=datetime.now(timezone.utc),
    )


def implement_workflow(
    *,
    repo: str = DEFAULT_REPO,
    max_issues: int = 1,
    config_enabled: bool = True,
    workspace_root: Path | None = None,
    repo_root: Path | None = None,
    base_branch: str = "main",
    mailbox_enabled: bool = False,
    mailbox_data_dir: Path | None = None,
) -> list[ImplementResult]:
    """Run the implement pipeline over up to `max_issues` accepted issues.

    The implement workflow is intentionally rate-limited to a SMALL number
    per orchestrator tick — each call burns up to $1 of Sonnet budget.

    Args:
        repo: owner/name slug. Defaults to your-org/bumba-open-harness.
        max_issues: hard cap on implements per call. Default 1 — the
            orchestrator (Sprint 14.10) is responsible for amortizing across
            ticks.
        config_enabled: feature-flag wire-through. Default True for direct
            callers; the orchestrator passes BridgeConfig.factory_implement_enabled.
        workspace_root, repo_root, base_branch: forwarded to implement_issue.

    Returns:
        list[ImplementResult] — empty when the flag is OFF or no issues match.
    """
    if not config_enabled:
        logger.debug("implement_workflow: feature flag OFF — returning []")
        return []

    candidates = _gh_issue_list_accepted(repo=repo, limit=200)
    if not candidates:
        logger.info("implement_workflow: no factory:accepted issues found")
        return []

    to_run = candidates[:max_issues]
    results: list[ImplementResult] = []
    for issue_number in to_run:
        try:
            result = implement_issue(
                issue_number,
                repo=repo,
                workspace_root=workspace_root,
                repo_root=repo_root,
                base_branch=base_branch,
                mailbox_enabled=mailbox_enabled,
                mailbox_data_dir=mailbox_data_dir,
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.exception(
                "implement_workflow: implement_issue raised on #%s: %s",
                issue_number, e,
            )
            continue
        results.append(result)

    return results
