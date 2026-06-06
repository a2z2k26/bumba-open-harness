"""Dark Factory pre-PR quality gates.

Sprint 14.06 — Plan 14 Phase 3.

Concept-only port of coleam00/dark-factory-experiment (no LICENSE — no source
copy). Layered on top of Sprint 14.05's implement workflow, this module adds
three guards that run after the diff is staged but before a draft PR is
opened:

  1. **500-LOC PR cap** — additions + deletions across the diff. Oversized
     PRs are too risky for autonomous review; route to the operator.
  2. **Protected-files check** — touching any file in
     `bridge.tier_manager.IMMUTABLE_FILES` or any `.plist` exits the
     factory's blast radius. Hands off to the operator.
  3. **New-dep justification gate** — `pyproject.toml` adds dependencies
     without a `new-dep-justified:` block in the issue body? Route to the
     operator.
  4. **Branch protection gate** (D1.5) — verify the target repo's default
     branch is protected before opening a PR. Posture is configurable:
     ``"warn"`` allows the PR but emits an EventBus event and a log warning
     (default for the first 7 days post-deploy); ``"block"`` fails the gate
     hard. Operator flips ``quality_chain.branch_protection_posture`` in
     ``bridge.toml`` after the soak period.

Each check returns a ``QualityCheckResult``. The caller (Sprint 14.06's
implement.py wiring) decides whether to short-circuit on first failure or
collect all results. ``run_all_quality_checks`` returns the full list so
operators see every reason at once.

The module is INTENTIONALLY pure for gates 1-3: the checks consume
pre-computed inputs (diff stats, changed files, diff text, issue body)
rather than running git/gh themselves. Gate 4 must call the GitHub API
via ``verify_branch_protection``; it does so through a synchronous
``asyncio.run()`` wrapper so the overall quality-phase API stays
synchronous (the implement pipeline is fully serial).
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Literal

from bridge.dispatch_metrics import increment_module_counter
from bridge.tier_manager import IMMUTABLE_FILES

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────


# Hard cap on diff size (additions + deletions). 500 LOC is the Dark Factory
# canonical threshold — large enough to ship most surgical changes, small
# enough that a human reviewer can absorb the diff in one sitting.
PR_SIZE_CAP: int = 500


# Magic phrase that operator (or triage) drops into an issue body to authorize
# a new dependency. Anything after the colon is treated as the justification
# rationale; the gate doesn't grade it, only requires its presence.
NEW_DEP_MAGIC_PHRASE: str = "new-dep-justified:"


# Failure category labels — discriminate four guard types in telemetry.
QualityCategory = Literal["pr_size", "protected_files", "new_deps", "branch_protection", ""]


# ── Result dataclass ────────────────────────────────────────────────────


@dataclass(frozen=True)
class QualityCheckResult:
    """Outcome of a single quality gate.

    `category` discriminates which guard ran. When `passed=True`, both
    `reason` and `category` are empty strings — the caller treats the
    truthiness of `passed` as the only authoritative signal.
    """

    passed: bool
    reason: str
    category: QualityCategory


_PASSED_PR_SIZE: QualityCheckResult = QualityCheckResult(
    passed=True, reason="", category="pr_size"
)
_PASSED_PROTECTED: QualityCheckResult = QualityCheckResult(
    passed=True, reason="", category="protected_files"
)
_PASSED_NEW_DEPS: QualityCheckResult = QualityCheckResult(
    passed=True, reason="", category="new_deps"
)
_PASSED_BRANCH_PROTECTION: QualityCheckResult = QualityCheckResult(
    passed=True, reason="", category="branch_protection"
)


# ── Check 1: PR size cap ────────────────────────────────────────────────


def check_pr_size(diff_stat: dict) -> QualityCheckResult:
    """Fail if (additions + deletions) > PR_SIZE_CAP.

    `diff_stat` is the lightweight {"additions": int, "deletions": int,
    "files_changed": int} shape produced by the implement workflow's diff
    summarizer. We only consume `additions` + `deletions`; missing keys
    default to 0 so the caller can pass a partial dict during early phases.
    """
    additions = int(diff_stat.get("additions", 0) or 0)
    deletions = int(diff_stat.get("deletions", 0) or 0)
    total = additions + deletions

    if total > PR_SIZE_CAP:
        return QualityCheckResult(
            passed=False,
            reason=(
                f"PR size {total} lines (additions={additions}, "
                f"deletions={deletions}) exceeds {PR_SIZE_CAP}-line cap"
            ),
            category="pr_size",
        )
    return _PASSED_PR_SIZE


# ── Check 2: Protected files ────────────────────────────────────────────


def _is_plist(path: str) -> bool:
    """True if the path ends in `.plist` (LaunchDaemon plist convention)."""
    return path.lower().endswith(".plist")


def _matches_immutable(path: str) -> str | None:
    """Return the IMMUTABLE_FILES entry that `path` matches, else None.

    `IMMUTABLE_FILES` stores bare filenames (`security.py`, etc.). A change
    triggers the gate when any segment of `path` equals one of those names,
    OR when the path's suffix matches. Substring fallback covers exotic
    layouts (e.g. nested copies). The match is intentionally generous —
    false positives route to the operator, which is the safe direction.
    """
    if not path:
        return None

    # Path-suffix / segment match (canonical). Splits on both POSIX and
    # Windows separators so the gate handles diff output from any host.
    segments = path.replace("\\", "/").split("/")
    last_segment = segments[-1] if segments else ""

    if last_segment in IMMUTABLE_FILES:
        return last_segment
    for segment in segments:
        if segment in IMMUTABLE_FILES:
            return segment

    # Substring fallback — covers `.../bridge/security.py.bak` etc. Cheap
    # given IMMUTABLE_FILES has <10 entries.
    for immutable in IMMUTABLE_FILES:
        if immutable in path:
            return immutable

    # Hooks dir (per CLAUDE.md "Forbidden files: ... hooks/"). The bare
    # constant doesn't include the directory, so we add the conventional
    # path test here. Two segment variants cover repo-relative + absolute.
    for segment in segments:
        if segment == "hooks":
            # Only flag if the diff actually touches a file UNDER hooks/,
            # not a sibling named "hooks.py".
            idx = segments.index("hooks")
            if idx < len(segments) - 1:  # something follows the hooks dir
                return "hooks/"

    return None


def check_protected_files(changed_files: list[str]) -> QualityCheckResult:
    """Fail if any changed file matches IMMUTABLE_FILES or ends in `.plist`.

    Reuses `bridge.tier_manager.IMMUTABLE_FILES` directly per Sprint 14.06's
    contract: this gate consumes the existing protected-set, never extends
    it. `.plist` is the one exception — LaunchDaemon plists are protected
    at the plist_manager layer too, and a factory edit to one is always an
    operator concern.
    """
    for changed in changed_files:
        if not changed:
            continue
        if _is_plist(changed):
            return QualityCheckResult(
                passed=False,
                reason=f"Protected file touched: {changed} (.plist files are operator-only)",
                category="protected_files",
            )
        match = _matches_immutable(changed)
        if match is not None:
            return QualityCheckResult(
                passed=False,
                reason=(
                    f"Protected file touched: {changed} "
                    f"(matches IMMUTABLE_FILES entry `{match}`)"
                ),
                category="protected_files",
            )
    return _PASSED_PROTECTED


# ── Check 3: New-dep justification ──────────────────────────────────────


# Match a `+` diff line that adds a dependency string. Heuristic: TOML
# `pyproject.toml` lists deps either as
#   - `+    "requests>=2.0",` (PEP 621 array form)
#   - `+requests = "*"` (Poetry table form)
# We capture either. Comment-only and blank `+` lines are excluded.
_DEP_NAME_RE: re.Pattern[str] = re.compile(
    r"""^\+              # '+' diff marker
        (?:\s*)          # optional indent
        (?:
            "([A-Za-z0-9_.\-]+)              # PEP 621: "name" possibly followed by version specifier
            |
            ([A-Za-z0-9_.\-]+)\s*=           # Poetry: name = "..."
        )
    """,
    re.VERBOSE,
)


def _extract_added_deps(diff_text: str) -> list[str]:
    """Parse a unified-diff snippet for dep adds inside `pyproject.toml` sections.

    Returns the list of dependency *names* (not version specifiers). Only
    `+` lines are inspected, and only those falling within a dep-bearing
    region: PEP 621 `[project] dependencies = [...]`, PEP 621
    `[project.optional-dependencies]` tables, or Poetry-style
    `[tool.poetry.dependencies]` / `[tool.poetry.dev-dependencies]`.

    The parser tracks two pieces of state per line: which TOML section
    we're in, and whether we're inside an array assignment (`name = [`)
    that is itself a dep array. Both `[project]` (with `dependencies = [`)
    and `[project.optional-dependencies.X]` (with `X = [`) are handled.
    """
    if not diff_text:
        return []

    in_pyproject = False
    section_is_project = False
    section_is_dep_table = False  # poetry-style table where every key is a dep
    in_dep_array = False  # currently inside `dependencies = [ ... ]` (or similar)
    found: list[str] = []

    # Keys that, when assigned an array under [project], are dep arrays.
    project_dep_array_keys = ("dependencies",)

    for raw_line in diff_text.splitlines():
        # Track which file the diff is currently describing.
        if raw_line.startswith("+++ ") or raw_line.startswith("--- "):
            in_pyproject = "pyproject.toml" in raw_line
            section_is_project = False
            section_is_dep_table = False
            in_dep_array = False
            continue
        if not in_pyproject:
            continue

        # Strip the diff marker for content inspection but remember it.
        marker = raw_line[:1] if raw_line else ""
        content = raw_line[1:] if marker in ("+", "-", " ") else raw_line
        stripped = content.strip()

        # Section header line (any context line — applies regardless of marker).
        if stripped.startswith("["):
            header = stripped
            section_is_project = header.startswith("[project]")
            section_is_dep_table = (
                header.startswith("[project.optional-dependencies")
                or header.startswith("[tool.poetry.dependencies")
                or header.startswith("[tool.poetry.dev-dependencies")
            )
            in_dep_array = False
            continue

        # Detect entering a `dependencies = [` block under [project].
        if section_is_project and "=" in stripped:
            # Look at the LHS key.
            lhs = stripped.split("=", 1)[0].strip()
            if lhs in project_dep_array_keys and stripped.rstrip().endswith("["):
                in_dep_array = True
                continue
            # `optional-dependencies = { ... }` is a sub-table opener; treat
            # entering it as a dep region too.
            if lhs == "optional-dependencies" and "{" in stripped:
                in_dep_array = True
                continue

        # Detect entering an array under an optional-dependencies table:
        # `[project.optional-dependencies]` then `dev = [` -> the values are deps.
        if section_is_dep_table and "=" in stripped and stripped.rstrip().endswith("["):
            in_dep_array = True
            continue

        # Closing bracket exits the array.
        if in_dep_array and stripped.startswith("]"):
            in_dep_array = False
            continue

        # Only `+` lines count as additions.
        if marker != "+":
            continue
        if raw_line.startswith("+++"):
            continue

        # Decide whether this added line is a dep entry.
        in_dep_region = in_dep_array or section_is_dep_table

        if not in_dep_region:
            continue

        match = _DEP_NAME_RE.match(raw_line)
        if match is None:
            continue
        name = match.group(1) or match.group(2) or ""
        # Skip TOML keys that aren't dep names (e.g. `python = ">=3.11"`).
        if name and name.lower() not in {"python", "name", "version", "description", "requires-python"}:
            found.append(name)

    return found


def check_new_deps(diff_text: str, issue_body: str) -> QualityCheckResult:
    """Fail if `pyproject.toml` adds new deps without `new-dep-justified:` in body.

    Justification format is intentionally simple: the operator (or triage
    pass) drops the literal phrase `new-dep-justified:` followed by free
    text. The gate doesn't grade the rationale — its presence is the
    contract. If the diff doesn't touch `pyproject.toml` at all, this
    passes regardless of the body content.
    """
    added_deps = _extract_added_deps(diff_text)
    if not added_deps:
        return _PASSED_NEW_DEPS

    body_lower = (issue_body or "").lower()
    if NEW_DEP_MAGIC_PHRASE in body_lower:
        return _PASSED_NEW_DEPS

    deps_str = ", ".join(added_deps)
    return QualityCheckResult(
        passed=False,
        reason=(
            f"New dependency added without justification: {deps_str}. "
            f"Issue body must contain `{NEW_DEP_MAGIC_PHRASE} <reason>`."
        ),
        category="new_deps",
    )


# ── Check 4: Branch protection gate (D1.5) ─────────────────────────────


def check_branch_protection(
    repo: str,
    posture: str = "warn",
) -> QualityCheckResult:
    """Verify the target repo's default branch is protected before opening a PR.

    Calls ``verify_branch_protection(repo)`` from ``bridge.branch_protection``
    via a synchronous asyncio wrapper (the factory quality phase is serial).

    Posture semantics:
      - ``"warn"``  (default, first-7-days soak): always returns
        ``passed=True``; on degraded/error, emits an EventBus event
        ``security.branch_protection.failed`` and logs a WARNING. The PR
        creation is allowed so the 17/20 unprotected repos do not block all
        factory output during the soak period.
      - ``"block"``: returns ``passed=False`` on any non-STRICT_OK result.
        Operator flips ``quality_chain.branch_protection_posture`` in
        ``bridge.toml`` after the soak period ends.

    Args:
        repo: Repo slug, e.g. ``"your-org/bumba-open-harness"``. Empty string skips
            the check (returns passed) so callers can opt out without
            touching the gate logic.
        posture: ``"warn"`` or ``"block"``.

    Returns:
        QualityCheckResult — ``passed=True`` in warn posture regardless of
        protection state; ``passed=False`` in block posture on any failure.
    """
    if not repo:
        return _PASSED_BRANCH_PROTECTION

    # Import here to avoid a circular-import at module load time (branch_protection
    # → event_bus → ... → factory chains are long; deferring keeps startup clean).
    from bridge.branch_protection import ProtectionStatus, verify_branch_protection
    from bridge.event_bus import EventBus

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(verify_branch_protection(repo))
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "branch_protection gate: unexpected error for %s — %s", repo, exc
        )
        if posture == "block":
            return QualityCheckResult(
                passed=False,
                reason=f"Branch protection check errored for {repo}: {exc}",
                category="branch_protection",
            )
        return _PASSED_BRANCH_PROTECTION
    finally:
        loop.close()

    if result.status == ProtectionStatus.STRICT_OK:
        return _PASSED_BRANCH_PROTECTION

    # Emit observability event regardless of posture so the operator can
    # track degraded repos even during the warn-and-allow soak period.
    try:
        EventBus.get_instance().publish(
            "security.branch_protection.failed",
            {
                "repo": repo,
                "status": result.status.value,
                "reason": result.reason,
                "posture": posture,
            },
        )
    except Exception as exc:  # pragma: no cover — event bus must not block gate
        logger.debug("branch_protection gate: EventBus publish failed: %s", exc)

    if posture == "block":
        return QualityCheckResult(
            passed=False,
            reason=f"Branch protection check FAILED for {repo}: {result.reason}",
            category="branch_protection",
        )

    # warn posture — allow but log so the operator can track degraded repos.
    logger.warning(
        "branch_protection: degraded for %s — %s (posture=warn, PR allowed)",
        repo,
        result.reason,
    )
    return _PASSED_BRANCH_PROTECTION


# ── Aggregate runner ────────────────────────────────────────────────────


def run_all_quality_checks(
    diff_stat: dict,
    changed_files: list[str],
    diff_text: str,
    issue_body: str,
    *,
    repo: str = "",
    branch_protection_posture: str = "warn",
) -> list[QualityCheckResult]:
    """Run all four gates, return the full list (no short-circuiting).

    Caller decides whether one failure is enough to halt — but we always
    surface every result so operator-routed comments name every offense
    at once. Order is stable: pr_size, protected_files, new_deps,
    branch_protection.

    Args:
        diff_stat: ``{"additions": int, "deletions": int, "files_changed": int}``.
        changed_files: List of file paths touched by the diff.
        diff_text: Raw unified-diff text (used for dep scanning).
        issue_body: Issue body text (used for dep justification check).
        repo: Repo slug for the branch-protection gate (D1.5). Empty string
            skips the gate. Defaults to ``""`` so callers that were wired
            before D1.5 continue working without a code change.
        branch_protection_posture: ``"warn"`` or ``"block"``. Passed through
            to ``check_branch_protection``. Defaults to ``"warn"`` (soak
            period default per D1.5 spec).
    """
    # Determinism Spectrum (Sprint #1115): table-driven gate, Tier 1.
    increment_module_counter("factory.quality.run_all_quality_checks", tier=1)
    return [
        check_pr_size(diff_stat),
        check_protected_files(changed_files),
        check_new_deps(diff_text, issue_body),
        check_branch_protection(repo, posture=branch_protection_posture),
    ]
