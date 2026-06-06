"""Append-only audit-branch trail for the experiment loop (Sprint 02.04).

Spec: docs/specs/2026-04-25-reference-audit/spec-02-04-implement-autoresearchiter-nnnn-branch-per-run-audit-trail.md
Issue: #978

Every experiment-loop iteration creates a permanent branch at
``autoresearch/iter-{NNNN}`` holding the iteration's commits, *regardless*
of keep / discard / crash. Branches are never deleted by this module;
the operator listing is read-only. Optionally pushed to ``origin``
(operator-tunable; default OFF because pushing 1000+ branches/year is a
storage decision the operator must opt into).

Design notes:
- Pure-function module: every git-touching call goes through a tiny
  ``git`` callable (``_default_git`` in production, mock in tests). No
  global state, no implicit cwd.
- Idempotent branch creation: re-creating an existing branch with the
  same SHA is a no-op (no exception). This keeps retries cheap and the
  iteration loop unbroken if the branch was already created in a prior
  partial run.
- Push failure NEVER raises: the ``AuditBranchResult`` carries
  ``push_error`` so the caller can log it without a try/except wall.
- ``annotate_branch_with_outcome`` records the outcome as a git note on
  the branch's HEAD commit. Notes (under ``refs/notes/audit-outcome``)
  are namespaced so they don't collide with operator-authored notes.
- ``list_audit_branches`` cross-references ``experiments.jsonl`` (the
  Sprint 02.03 dual-write file) to attach outcome / fitness / cost
  metadata to each summary. Missing metadata degrades to ``None`` rather
  than failing — the JSONL might be ahead-of or behind-the branch list
  during cleanup or restore.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# Sprint ref-audit-02-11 / issue #986 — defense-in-depth branch-name guard
# refuses to push outside the allowed namespaces *before* the network call.
# The GitHub PAT scope is the primary gate; this catches config-time
# accidents so we never test the PAT's deny rules in production.
from scripts.experiment_loop_push_guard import assert_pushable_branch

# ── Constants ──────────────────────────────────────────────────

BRANCH_PREFIX = "autoresearch/iter-"

# Namespace used for the outcome git-note ref. Keeping a dedicated ref
# avoids collisions with default ``refs/notes/commits`` notes the operator
# may have added by hand.
NOTES_REF = "refs/notes/audit-outcome"

# Pattern for parsing iter id from branch name. We accept both the
# zero-padded ``int`` form ("0042") and arbitrary string ids ("abc-123")
# because the loop uses ``uuid.uuid4().hex[:12]`` for ``iter_id`` today
# but specs sometimes refer to integer ids.
_BRANCH_ITER_RE = re.compile(rf"^{re.escape(BRANCH_PREFIX)}(.+)$")


# ── Types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditBranchResult:
    """Result of one branch-creation invocation.

    Frozen — callers MUST treat instances as immutable. ``push_error`` is
    populated only when ``pushed`` is False AND the operator opted into
    pushing; a default ``push_to_origin=False`` invocation leaves both
    ``pushed=False`` and ``push_error=None``.
    """

    branch_name: str
    commit_sha: str
    pushed: bool
    push_error: str | None = None


@dataclass(frozen=True)
class BranchSummary:
    """One audit branch's metadata for operator listings.

    ``outcome`` / ``fitness_value`` / ``cost_usd`` come from the
    ``experiments.jsonl`` row whose ``iter_id`` matches; left ``None``
    when the JSONL has no matching row (typical for branches created
    before metadata was persisted, or for branches in a test fixture).
    """

    branch_name: str
    iter_id: str
    commit_sha: str
    commit_subject: str
    authored_at_iso: str
    outcome: str | None
    fitness_value: float | None
    cost_usd: float | None


# Type alias for the subprocess wrapper. Callers (tests) pass a callable
# that mimics ``subprocess.run`` enough for our needs; production uses
# ``_default_git`` which simply forwards to ``subprocess.run``.
GitCallable = Callable[..., subprocess.CompletedProcess[str]]


# ── Helpers ────────────────────────────────────────────────────


def _default_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Default git invocation. Captures stdout/stderr; never raises on non-zero.

    The caller checks ``returncode`` so we can construct precise
    ``AuditBranchResult`` records (e.g. distinguishing "branch already
    exists" from "git not found").
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def make_branch_name(iter_id: int | str) -> str:
    """Return the canonical ``autoresearch/iter-...`` branch name.

    For ``int`` ids, zero-pad to 4 digits — preserves chronological
    sort in ``git branch | grep autoresearch/`` output for the first
    9999 iterations. For ``str`` ids (e.g. uuid hex prefixes), use as-is.
    """
    if isinstance(iter_id, int):
        return f"{BRANCH_PREFIX}{iter_id:04d}"
    return f"{BRANCH_PREFIX}{iter_id}"


def parse_iter_id(branch_name: str) -> str | None:
    """Return the iter portion of an ``autoresearch/iter-X`` name; ``None`` otherwise.

    The returned string is the *raw* iter id — for ``int`` branches this
    is the zero-padded form ("0042"), not ``42``. Callers that need a
    numeric form parse with ``int(s)`` themselves.
    """
    match = _BRANCH_ITER_RE.match(branch_name)
    if not match:
        return None
    return match.group(1)


# ── Branch creation ────────────────────────────────────────────


def create_audit_branch(
    *,
    iter_id: int | str,
    head_sha: str,
    repo_root: Path,
    push_to_origin: bool = False,
    git: GitCallable | None = None,
) -> AuditBranchResult:
    """Create ``autoresearch/iter-{iter_id}`` at ``head_sha``; optionally push.

    Idempotent: if the branch already exists at ``head_sha``, this is a
    no-op (returns a successful result). If the branch exists at a
    *different* SHA, the existing branch is preserved untouched —
    audit-branches are append-only — and a result with ``push_error``
    explaining the divergence is returned (with ``pushed=False``).

    Push failure NEVER raises. The result carries the captured stderr in
    ``push_error`` and ``pushed=False`` so the caller can log without a
    try/except. Branch-creation failure DOES raise — the caller's
    iteration is the source of truth for what "broken" means here.
    """
    git_run = git if git is not None else _default_git
    branch_name = make_branch_name(iter_id)

    # Resolve any pre-existing branch SHA. ``rev-parse --verify`` is the
    # cheap, no-side-effect lookup; non-zero exit means the ref does
    # not exist (the happy path for the first call).
    rev_parse = git_run(
        ["rev-parse", "--verify", branch_name],
        cwd=repo_root,
    )
    existing_sha = rev_parse.stdout.strip() if rev_parse.returncode == 0 else None

    if existing_sha is None:
        # Create the branch at head_sha. ``git branch <name> <sha>`` is
        # safe: it errors if the branch already exists, but we already
        # short-circuited that above.
        create = git_run(
            ["branch", branch_name, head_sha],
            cwd=repo_root,
        )
        if create.returncode != 0:
            raise RuntimeError(
                f"git branch {branch_name} {head_sha} failed: "
                f"{(create.stderr or create.stdout).strip()}"
            )
    elif existing_sha != head_sha:
        # Pre-existing branch points elsewhere. Preserve it (append-only
        # is the contract); surface the divergence so the caller can log.
        return AuditBranchResult(
            branch_name=branch_name,
            commit_sha=existing_sha,
            pushed=False,
            push_error=(
                f"branch {branch_name} already exists at {existing_sha[:12]} "
                f"(requested {head_sha[:12]}); preserving existing"
            ),
        )
    # else: existing_sha == head_sha → idempotent no-op, fall through.

    if not push_to_origin:
        return AuditBranchResult(
            branch_name=branch_name,
            commit_sha=head_sha,
            pushed=False,
            push_error=None,
        )

    # Defense-in-depth: refuse to push outside the allowed namespaces before
    # the network call. branch_name comes from make_branch_name(iter_id) which
    # always prepends BRANCH_PREFIX, so this should never trip in normal
    # operation — it's a config-time accident catch (issue #986).
    assert_pushable_branch(branch_name)

    push = git_run(
        ["push", "origin", branch_name],
        cwd=repo_root,
    )
    if push.returncode != 0:
        return AuditBranchResult(
            branch_name=branch_name,
            commit_sha=head_sha,
            pushed=False,
            push_error=(push.stderr or push.stdout).strip()[:500],
        )
    return AuditBranchResult(
        branch_name=branch_name,
        commit_sha=head_sha,
        pushed=True,
        push_error=None,
    )


# ── Outcome annotation ─────────────────────────────────────────


def annotate_branch_with_outcome(
    branch_name: str,
    *,
    outcome: Literal["keep", "discard", "crash"],
    repo_root: Path,
    git: GitCallable | None = None,
) -> bool:
    """Write a git note at ``NOTES_REF`` recording the iteration outcome.

    Idempotent — re-annotating with the same outcome is a no-op; with a
    different outcome the new value REPLACES the old (``--force``). We
    use a dedicated ref (``refs/notes/audit-outcome``) so the operator's
    default ``refs/notes/commits`` namespace stays untouched.

    Returns True on success; False on any git error. Never raises — a
    note-write failure must NEVER block the iteration's keep/discard
    branch in the caller.
    """
    git_run = git if git is not None else _default_git

    # Resolve the branch's HEAD SHA. Note targets are commits; the ref
    # itself can't be annotated.
    rev_parse = git_run(
        ["rev-parse", "--verify", branch_name],
        cwd=repo_root,
    )
    if rev_parse.returncode != 0:
        return False
    sha = rev_parse.stdout.strip()
    if not sha:
        return False

    # ``--force`` makes the call idempotent / re-annotate-friendly.
    add = git_run(
        [
            "notes",
            f"--ref={NOTES_REF}",
            "add",
            "--force",
            "-m",
            outcome,
            sha,
        ],
        cwd=repo_root,
    )
    return add.returncode == 0


def read_branch_outcome(
    branch_name: str,
    *,
    repo_root: Path,
    git: GitCallable | None = None,
) -> str | None:
    """Read the git-note outcome for ``branch_name``. Returns ``None`` if absent."""
    git_run = git if git is not None else _default_git
    show = git_run(
        ["notes", f"--ref={NOTES_REF}", "show", branch_name],
        cwd=repo_root,
    )
    if show.returncode != 0:
        return None
    note = show.stdout.strip()
    return note or None


# ── Listing ────────────────────────────────────────────────────


def _load_jsonl_index(jsonl_path: Path | None) -> dict[str, dict[str, Any]]:
    """Load ``experiments.jsonl`` into ``{iter_id_str: row}`` for cross-ref.

    ``iter_id`` in the JSONL is the SQLite row id (``int``); we coerce
    to ``str`` so callers can match either int- or uuid-prefix branches.
    Missing file → empty index. Malformed lines are skipped silently.
    """
    if jsonl_path is None or not jsonl_path.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    try:
        for line in jsonl_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            iter_id = row.get("iter_id")
            if iter_id is None:
                continue
            # Match both raw ("42") and zero-padded ("0042") forms so the
            # branch name's iter portion can find its row regardless of
            # which side did the formatting.
            key_raw = str(iter_id)
            index[key_raw] = row
            if isinstance(iter_id, int):
                index[f"{iter_id:04d}"] = row
    except OSError:
        return {}
    return index


def _list_branch_names(
    repo_root: Path,
    git: GitCallable,
) -> list[str]:
    """Return all ``autoresearch/iter-*`` branch names, sorted."""
    result = git(
        ["for-each-ref", "--format=%(refname:short)", f"refs/heads/{BRANCH_PREFIX}*"],
        cwd=repo_root,
    )
    if result.returncode != 0:
        return []
    names = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    return sorted(names)


def _commit_meta(
    sha_or_ref: str,
    repo_root: Path,
    git: GitCallable,
) -> tuple[str, str, str]:
    """Return ``(commit_sha, subject, authored_at_iso)`` for a ref. Best-effort."""
    log = git(
        [
            "log",
            "-1",
            "--format=%H%x1f%s%x1f%aI",
            sha_or_ref,
        ],
        cwd=repo_root,
    )
    if log.returncode != 0:
        return ("", "", "")
    parts = log.stdout.strip().split("\x1f")
    if len(parts) != 3:
        return ("", "", "")
    return (parts[0], parts[1], parts[2])


def list_audit_branches(
    *,
    repo_root: Path,
    jsonl_path: Path | None = None,
    git: GitCallable | None = None,
) -> tuple[BranchSummary, ...]:
    """Walk ``autoresearch/iter-*`` branches and build summaries.

    Cross-references ``experiments.jsonl`` (the Sprint 02.03 dual-write
    file) when ``jsonl_path`` is supplied. Missing JSONL or missing rows
    leave outcome / fitness / cost as ``None`` — branches without a JSONL
    counterpart are still surfaced so the operator can spot orphans.

    Returns an immutable tuple — callers must NOT mutate the result.
    """
    git_run = git if git is not None else _default_git
    branches = _list_branch_names(repo_root, git_run)
    index = _load_jsonl_index(jsonl_path)

    summaries: list[BranchSummary] = []
    for name in branches:
        iter_id = parse_iter_id(name) or ""
        commit_sha, subject, authored_at = _commit_meta(name, repo_root, git_run)
        row = index.get(iter_id) or index.get(iter_id.lstrip("0") or "0")
        outcome = (row or {}).get("status") if row else None
        # The JSONL can carry "fitness_delta" or a "fitness_snapshot" subkey.
        fitness_value: float | None = None
        if row is not None:
            raw_fitness = row.get("fitness_delta")
            if raw_fitness is None:
                snap = row.get("fitness_snapshot")
                if isinstance(snap, dict):
                    raw_fitness = snap.get("after_value")
            if raw_fitness is not None:
                try:
                    fitness_value = float(raw_fitness)
                except (TypeError, ValueError):
                    fitness_value = None
        cost_raw = (row or {}).get("cost_usd") if row else None
        cost_usd: float | None = None
        if cost_raw is not None:
            try:
                cost_usd = float(cost_raw)
            except (TypeError, ValueError):
                cost_usd = None

        summaries.append(
            BranchSummary(
                branch_name=name,
                iter_id=iter_id,
                commit_sha=commit_sha,
                commit_subject=subject,
                authored_at_iso=authored_at,
                outcome=outcome,
                fitness_value=fitness_value,
                cost_usd=cost_usd,
            )
        )
    return tuple(summaries)
