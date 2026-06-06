"""Governance-fetch helper — read rules from origin/main, never the PR.

Sprint 14.02 of the 2026-04-25 reference-audit bundle. Concept-only port of the
Dark Factory "governance-as-constitution with poison immunity" pattern
(NO LICENSE — `concept-only-no-license`).

## Why poison immunity matters

Factory validators read governance documents (CLAUDE.md, RULES.md, OPERATOR.md,
agent/CLAUDE.md, …) to judge whether a PR meets the project's standards. If a
validator reads governance from the PR's own working tree, the PR can weaken
its own rulebook to pass review — the rulebook becomes self-modifying poison.

Dark Factory's fix: validators **always** fetch governance from `origin/main`,
never from the PR's working tree. This module ships that fetch helper. It is
the only sanctioned way for factory validators to obtain governance content.

## Boundaries

This sprint ships the helper only. The validators that consume it (Sprint 14.07
holdout reviewers) come later. Until then this module is dormant — importable
and tested, but unused at runtime. No feature flag is required because the
module is a library, not a behavior.

## Critical guard

Every fetch path calls ``git fetch origin main`` before reading so that
``origin/main`` is current. The fetch is best-effort: if it fails (e.g., the
runtime is offline), we log a warning and continue with whatever the local
``origin/main`` already has. We never fall back to the working tree.
"""
from __future__ import annotations

import logging
import subprocess  # noqa: S404 — external git invocations are required for the design
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# Default governance file list. Superset of `tier_manager.IMMUTABLE_FILES`
# kept in sync via the spec's acceptance check (test asserts the relationship).
# Files that don't exist on the ref are skipped with a warning, so adding
# entries here that haven't been promoted to main yet is safe.
DEFAULT_GOVERNANCE_FILES: tuple[str, ...] = (
    "CLAUDE.md",
    "RULES.md",
    "OPERATOR.md",
    "agent/CLAUDE.md",
)


@dataclass(frozen=True)
class GovernanceSnapshot:
    """Immutable snapshot of governance state at a point in time.

    Attributes:
        files: Mapping of governance path → file content as fetched from ``ref``.
            Files missing on ``ref`` are absent from this mapping (not blank).
        ref_sha: The full commit SHA that ``ref`` resolved to at fetch time.
            Validators record this so verdicts can pin the exact governance
            version they were judged against.
        fetched_at: UTC timestamp of when the snapshot was taken. Useful for
            cache-staleness checks in long-running validators.
    """

    files: dict[str, str] = field(default_factory=dict)
    ref_sha: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _refresh_origin(ref: str) -> None:
    """Best-effort ``git fetch`` so ``ref`` is current before we read it.

    Failure is non-fatal: when the runtime is offline (or the remote is
    unreachable for any reason) we log a warning and rely on whatever the
    local ``origin/main`` already has. We never fall back to the working tree.
    """
    # Parse "origin/main" → ("origin", "main"). If the caller passes a SHA or a
    # local ref, we skip the fetch entirely (no remote to refresh from).
    if "/" not in ref:
        return
    remote, _, branch = ref.partition("/")
    try:
        subprocess.run(  # noqa: S603 — args are constants/validated tokens
            ["git", "fetch", remote, branch],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        # Fail-open: log and continue. Validators that need a guaranteed-fresh
        # ref must check `ref_sha` against the upstream out-of-band.
        logger.warning(
            "git fetch %s %s failed (continuing with stale local ref): %s",
            remote,
            branch,
            exc,
        )


def fetch_governance(
    *,
    files: Sequence[str] = DEFAULT_GOVERNANCE_FILES,
    ref: str = "origin/main",
) -> dict[str, str]:
    """Fetch governance files from a git ref via ``git show <ref>:<file>``.

    Always refreshes ``origin/<branch>`` first (best-effort) so ``ref`` is
    current. Never reads from the working tree. Files that do not exist on
    the ref are skipped with a warning rather than failing the whole fetch
    — this is defensive for governance docs that have been added locally but
    not yet promoted to main.

    Args:
        files: Governance paths to fetch, relative to the repo root.
            Defaults to :data:`DEFAULT_GOVERNANCE_FILES`.
        ref: Git ref to read from. Defaults to ``origin/main`` (the
            poison-immunity contract). Override only for testing or for
            comparing against a different baseline.

    Returns:
        Mapping of ``path → content``. Files missing on the ref are absent
        from the mapping (not represented as empty strings).
    """
    _refresh_origin(ref)

    contents: dict[str, str] = {}
    for path in files:
        spec = f"{ref}:{path}"
        try:
            result = subprocess.run(  # noqa: S603 — args are validated tokens
                ["git", "show", spec],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.CalledProcessError as exc:
            # `git show` returns non-zero when the path doesn't exist on the
            # ref. Skip with a warning — the validator can decide what to
            # make of a missing rulebook entry.
            logger.warning(
                "governance file %s not found on %s (skipping): %s",
                path,
                ref,
                exc.stderr.strip() if exc.stderr else exc,
            )
            continue
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("git show %s failed: %s", spec, exc)
            continue
        contents[path] = result.stdout
    return contents


def get_governance_sha(ref: str = "origin/main") -> str:
    """Return the commit SHA that ``ref`` resolves to.

    Refreshes the remote first (best-effort) so the SHA reflects the latest
    upstream tip. Validators pin this SHA into their verdict records so
    "what governance version judged this PR?" is auditable.

    Args:
        ref: Git ref to resolve. Defaults to ``origin/main``.

    Returns:
        The full 40-character commit SHA. Empty string if resolution fails
        (offline + no local ref) — validators must treat empty as "unknown
        governance" and bail rather than proceed with no constitution.
    """
    _refresh_origin(ref)
    try:
        result = subprocess.run(  # noqa: S603 — args are validated tokens
            ["git", "rev-parse", ref],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("git rev-parse %s failed: %s", ref, exc)
        return ""
    return result.stdout.strip()


def fetch_snapshot(
    *,
    files: Sequence[str] = DEFAULT_GOVERNANCE_FILES,
    ref: str = "origin/main",
) -> GovernanceSnapshot:
    """One-call convenience: combine :func:`fetch_governance` and
    :func:`get_governance_sha` into a single immutable :class:`GovernanceSnapshot`.

    This is what factory validators actually call. The two underlying helpers
    remain public for tests and for callers that need partial information.
    """
    contents = fetch_governance(files=files, ref=ref)
    sha = get_governance_sha(ref=ref)
    return GovernanceSnapshot(
        files=contents,
        ref_sha=sha,
        fetched_at=datetime.now(timezone.utc),
    )
