"""Branch protection verification for agent-touched repos.

Sprint 4.1 — Phase 4A (Agent Harness Hardening).

Checks whether the default branch of a given repo has GitHub-side branch
protection enabled with the standard ruleset. If protection is absent or
degraded, returns a clear operator-facing reason. The harness's pre-work
hook calls `verify_branch_protection()` before allowing sprint-mode work
to begin on any repo.

Billing caveat:
    GitHub branch protection on private repos requires a paid plan
    (GitHub Pro, Team, or Enterprise). Free-tier accounts can only
    apply protection to public repos. For private repos on the free
    tier, this module returns a DEGRADED result — the harness will log
    a warning to the dialogue channel and allow operation, but GitHub-
    side guarantees are absent. See:
        memory/project_branch_protection_standard.md
        memory/project_agent_repo_inventory.md

Integration:
    - pre-work hook calls verify_branch_protection(repo) before sprint-mode
    - a DEGRADED result logs a warning via the dialogue channel
    - an ERROR result aborts sprint-mode work with a clear operator message
    - a STRICT_OK result allows work to proceed silently
"""
from __future__ import annotations

import asyncio
import enum
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ProtectionStatus(enum.Enum):
    """Result of a branch protection check."""

    STRICT_OK = "strict_ok"
    """GitHub-side protection is enabled with the standard ruleset."""

    DEGRADED_PAID_FEATURE = "degraded_paid_feature"
    """Repo is private on a free-tier account; GitHub refuses protection
    API calls with HTTP 403. Harness allows operation with a warning."""

    DEGRADED_UNPROTECTED = "degraded_unprotected"
    """Repo is protectable (public or paid) but protection is not enabled.
    Harness allows operation with a warning. Operator should enable."""

    ERROR_MISSING_RULES = "error_missing_rules"
    """Protection is enabled but is missing required rules from the
    standard ruleset. Harness refuses to proceed."""

    ERROR_NOT_FOUND = "error_not_found"
    """Repo or branch does not exist, or `gh` is not authenticated.
    Harness refuses to proceed."""

    ERROR_UNKNOWN = "error_unknown"
    """Unexpected failure querying the GitHub API. Harness refuses
    to proceed."""


@dataclass(frozen=True)
class ProtectionResult:
    """Structured result of a branch protection check.

    Attributes:
        repo: The repo slug (e.g., "your-org/bumba-open-harness").
        branch: The default branch name checked.
        status: One of the ProtectionStatus values.
        ok: True if the harness should allow work (strict or degraded).
        degraded: True if protection is weaker than the standard ruleset.
        reason: Human-readable explanation for dialogue-channel output.
    """

    repo: str
    branch: str
    status: ProtectionStatus
    ok: bool
    degraded: bool
    reason: str


async def _run_gh(args: list[str]) -> tuple[int, str, str]:
    """Run a `gh` command. Returns (returncode, stdout, stderr).

    Isolated in its own coroutine so tests can patch it cleanly.
    """
    proc = await asyncio.create_subprocess_exec(
        "gh",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


async def _get_default_branch(repo: str) -> str | None:
    """Return the default branch name for a repo, or None on failure."""
    rc, stdout, _ = await _run_gh(["api", f"repos/{repo}", "--jq", ".default_branch"])
    if rc != 0:
        return None
    name = stdout.strip()
    return name or None


def _standard_ruleset_is_satisfied(protection_json: dict) -> tuple[bool, str]:
    """Verify the protection response matches the standard ruleset.

    Returns (is_satisfied, failure_reason). See
    memory/project_branch_protection_standard.md for the canonical list.
    """
    reviews = protection_json.get("required_pull_request_reviews")
    if not reviews:
        return False, "required_pull_request_reviews is not configured"
    if (reviews.get("required_approving_review_count") or 0) < 1:
        return False, "required_approving_review_count must be >= 1"
    if not reviews.get("dismiss_stale_reviews"):
        return False, "dismiss_stale_reviews must be true"

    if not protection_json.get("required_linear_history", {}).get("enabled"):
        return False, "required_linear_history must be enabled"

    if protection_json.get("allow_force_pushes", {}).get("enabled"):
        return False, "allow_force_pushes must be disabled"

    if protection_json.get("allow_deletions", {}).get("enabled"):
        return False, "allow_deletions must be disabled"

    if not protection_json.get("required_conversation_resolution", {}).get("enabled"):
        return False, "required_conversation_resolution must be enabled"

    return True, ""


async def verify_branch_protection(repo: str) -> ProtectionResult:
    """Verify that a repo's default branch is protected per the standard ruleset.

    Call this from the harness's pre-work hook before allowing any sprint-mode
    task to begin. The result's `ok` field tells the harness whether to proceed;
    the `degraded` flag tells the harness whether to emit a warning; the `reason`
    field is suitable for display in the dialogue channel.

    Args:
        repo: Repo slug (e.g., "your-org/bumba-open-harness").

    Returns:
        ProtectionResult with status, ok/degraded flags, and a reason string.
    """
    # Step 1 — resolve the default branch
    branch = await _get_default_branch(repo)
    if branch is None:
        return ProtectionResult(
            repo=repo,
            branch="<unknown>",
            status=ProtectionStatus.ERROR_NOT_FOUND,
            ok=False,
            degraded=False,
            reason=f"Could not resolve default branch for {repo}. "
            f"Is `gh` authenticated and does the repo exist?",
        )

    # Step 2 — query protection state
    rc, stdout, stderr = await _run_gh(
        ["api", f"repos/{repo}/branches/{branch}/protection"]
    )

    # Step 3 — classify the result
    combined = (stdout + stderr).lower()

    # GitHub returns 403 with "Upgrade to GitHub Pro" for free-tier private repos.
    if "upgrade to github pro" in combined:
        return ProtectionResult(
            repo=repo,
            branch=branch,
            status=ProtectionStatus.DEGRADED_PAID_FEATURE,
            ok=True,
            degraded=True,
            reason=(
                f"{repo}/{branch} is a private repo on a free-tier GitHub account. "
                f"Branch protection requires a paid plan (GitHub Pro, Team, or "
                f"Enterprise). Operating in DEGRADED state — the harness cannot "
                f"guarantee direct-to-main pushes are refused. Consider upgrading "
                f"to GitHub Pro ($4/month) to enable protection."
            ),
        )

    # GitHub returns 404 with "Branch not protected" for protectable-but-unprotected.
    if "branch not protected" in combined:
        return ProtectionResult(
            repo=repo,
            branch=branch,
            status=ProtectionStatus.DEGRADED_UNPROTECTED,
            ok=True,
            degraded=True,
            reason=(
                f"{repo}/{branch} is protectable but has no branch protection "
                f"enabled. Operating in DEGRADED state — run Sprint 4.1 "
                f"enablement to apply the standard ruleset."
            ),
        )

    # Any other non-zero return is unknown failure
    if rc != 0:
        return ProtectionResult(
            repo=repo,
            branch=branch,
            status=ProtectionStatus.ERROR_UNKNOWN,
            ok=False,
            degraded=False,
            reason=f"Unexpected failure querying protection for {repo}/{branch}: "
            f"exit {rc}, stderr: {stderr.strip()[:200]}",
        )

    # Success path — parse the protection JSON
    try:
        protection = json.loads(stdout)
    except json.JSONDecodeError as e:
        return ProtectionResult(
            repo=repo,
            branch=branch,
            status=ProtectionStatus.ERROR_UNKNOWN,
            ok=False,
            degraded=False,
            reason=f"Could not parse protection JSON for {repo}/{branch}: {e}",
        )

    # Verify the standard ruleset is satisfied
    satisfied, failure_reason = _standard_ruleset_is_satisfied(protection)
    if not satisfied:
        return ProtectionResult(
            repo=repo,
            branch=branch,
            status=ProtectionStatus.ERROR_MISSING_RULES,
            ok=False,
            degraded=False,
            reason=(
                f"{repo}/{branch} has branch protection but it is missing "
                f"required rules: {failure_reason}. Harness refuses to proceed. "
                f"See memory/project_branch_protection_standard.md"
            ),
        )

    return ProtectionResult(
        repo=repo,
        branch=branch,
        status=ProtectionStatus.STRICT_OK,
        ok=True,
        degraded=False,
        reason=f"{repo}/{branch} is protected per the standard ruleset.",
    )


# ── CLI entry point (Sprint 06.15b rework) ────────────────────────────

def _cli_main(argv: list[str] | None = None) -> int:
    """Sync CLI entry: ``python -m bridge.branch_protection --repo <name>``.

    Exit codes:
        0   STRICT_OK or DEGRADED_* (proceed; degraded prints a warning)
        1   ERROR_* (refuse; harness must abort)
        2   --strict mode rejects DEGRADED_* (only STRICT_OK passes)
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="bridge.branch_protection",
        description=(
            "Verify GitHub branch protection on a repo's default branch. "
            "Called per-repo by the harness pre-work hook."
        ),
    )
    parser.add_argument(
        "--repo",
        required=True,
        help='Repo slug, e.g. "your-org/bumba-open-harness"',
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit non-zero on DEGRADED_* (paid-feature, unprotected). "
            "Default mode allows degraded with a warning, matching the "
            "harness's normal allow-with-warning posture."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress reason output on success; print on failure only.",
    )

    args = parser.parse_args(argv)

    # Use a dedicated event loop rather than asyncio.run() so the test suite's
    # default loop is not closed when _cli_main is called from a synchronous
    # test (asyncio.run closes the running loop on exit).
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(verify_branch_protection(args.repo))
    finally:
        loop.close()

    if result.status == ProtectionStatus.STRICT_OK:
        if not args.quiet:
            print(f"OK: {result.reason}")
        return 0

    if result.status in (
        ProtectionStatus.DEGRADED_PAID_FEATURE,
        ProtectionStatus.DEGRADED_UNPROTECTED,
    ):
        # Always print degraded warnings to stderr so the harness logs them
        print(f"WARN: {result.reason}", file=sys.stderr)
        return 2 if args.strict else 0

    # ERROR_* — refuse to proceed
    print(f"ERROR: {result.reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_cli_main())
