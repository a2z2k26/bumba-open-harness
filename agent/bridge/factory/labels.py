"""GitHub-label state machine for the Dark Factory pipeline.

Sprint 14.01 — Plan 14 Phase 1.

Concept-only port of coleam00/dark-factory-experiment (no LICENSE — no source
copy). Bumba's WorkOrder dispatcher already uses SQLite via
`bridge.work_order_store.WorkOrderStore`. This module provides a parallel,
GitHub-label-based view of state that:

  - Is visible in the GitHub UI (humans can see the queue)
  - Survives total local-process crash (state is on github.com)
  - Costs nothing (free state store on a free plan)
  - Single-active invariant: at most ONE `factory:*` state label per issue

This module COMPLEMENTS, not replaces, the SQLite path. Use SQLite for the
dispatcher; use labels for the factory pipeline's cross-process coordination.

Operator action after merge:

    cd agent && python3 -c "from bridge.factory.labels import \
        ensure_labels_exist; print(ensure_labels_exist('your-org/bumba-open-harness'))"

Run once. The PR helper does not run this for you — labels are a
non-reversible side effect on the live repo.
"""
from __future__ import annotations

import enum
import json
import logging
import subprocess
from typing import Final

from bridge.dispatch_metrics import increment_module_counter

logger = logging.getLogger(__name__)


# ── State enum ──────────────────────────────────────────────────────────


class FactoryState(enum.Enum):
    """The factory state machine.

    Each value is the literal GitHub label name (`factory:*`). The label IS
    the state — there is no parallel storage. Multiple `factory:*` labels on
    the same issue is a state-machine invariant violation; `get_state`
    raises `LabelStateError` in that case.

    The `OPT_IN` marker (`factory:opt-in`) is NOT a state — it gates whether
    the factory touches an issue at all. It is intentionally excluded from
    `get_state`'s return values.
    """

    UNTRIAGED = "factory:untriaged"
    ACCEPTED = "factory:accepted"
    REJECTED = "factory:rejected"
    RATE_LIMITED = "factory:rate-limited"
    IN_PROGRESS = "factory:in-progress"
    NEEDS_REVIEW = "factory:needs-review"
    APPROVED_PENDING_MERGE = "factory:approved-pending-merge"
    REJECTED_FINAL = "factory:rejected-final"
    NEEDS_HUMAN = "factory:needs-human"
    FIX_ATTEMPT_1 = "factory:fix-attempt-1"
    FIX_ATTEMPT_2 = "factory:fix-attempt-2"


# Marker label that flags an issue as factory-managed. Not a state.
FACTORY_OPT_IN_LABEL: Final[str] = "factory:opt-in"


# All labels the factory creates / uses. Order is stable for ensure_labels_exist.
FACTORY_LABELS: Final[tuple[str, ...]] = (
    FACTORY_OPT_IN_LABEL,
    FactoryState.UNTRIAGED.value,
    FactoryState.ACCEPTED.value,
    FactoryState.REJECTED.value,
    FactoryState.RATE_LIMITED.value,
    FactoryState.IN_PROGRESS.value,
    FactoryState.NEEDS_REVIEW.value,
    FactoryState.APPROVED_PENDING_MERGE.value,
    FactoryState.REJECTED_FINAL.value,
    FactoryState.NEEDS_HUMAN.value,
    FactoryState.FIX_ATTEMPT_1.value,
    FactoryState.FIX_ATTEMPT_2.value,
)


# Label color/description per group. Colors are 6-digit hex (no `#`).
# The factory pipeline doesn't depend on colors — they're operator UX only.
_LABEL_METADATA: Final[dict[str, tuple[str, str]]] = {
    FACTORY_OPT_IN_LABEL: ("0e8a16", "Factory opt-in marker — gates whether the factory touches this issue"),
    "factory:untriaged": ("ededed", "Factory state: awaiting triage decision"),
    "factory:accepted": ("c2e0c6", "Factory state: triaged and accepted into the pipeline"),
    "factory:rejected": ("e99695", "Factory state: triaged and rejected (recoverable)"),
    "factory:rate-limited": ("fbca04", "Factory state: deferred, rate limit hit"),
    "factory:in-progress": ("1d76db", "Factory state: agent is working"),
    "factory:needs-review": ("0052cc", "Factory state: PR open, awaiting review"),
    "factory:approved-pending-merge": ("0e8a16", "Factory state: review approved, queued to merge"),
    "factory:rejected-final": ("b60205", "Factory state: rejected after fix attempts (terminal)"),
    "factory:needs-human": ("d93f0b", "Factory state: escalated to operator (terminal-pending)"),
    "factory:fix-attempt-1": ("fbca04", "Factory state: first fix attempt in progress"),
    "factory:fix-attempt-2": ("d93f0b", "Factory state: second (final) fix attempt in progress"),
}


# Reverse lookup from label string back to FactoryState (only states, not opt-in).
_LABEL_TO_STATE: Final[dict[str, FactoryState]] = {s.value: s for s in FactoryState}


# ── Errors ──────────────────────────────────────────────────────────────


class LabelStateError(RuntimeError):
    """Raised when the label state-machine invariant is violated.

    Currently the only invariant: at most one `factory:*` state label per
    issue (the opt-in marker doesn't count). If a caller observes more than
    one, the orchestrator must NOT pick a winner — it must surface the
    conflict to the operator.
    """


# ── gh helpers ──────────────────────────────────────────────────────────


def _run_gh(args: list[str]) -> tuple[int, str, str]:
    """Run a `gh` command synchronously. Returns (returncode, stdout, stderr).

    Isolated for clean test patching. Synchronous because label transitions
    are infrequent and the factory loop polls — no need for asyncio here.
    """
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ── Read state ──────────────────────────────────────────────────────────


def get_state(issue_or_pr_number: int) -> FactoryState | None:
    """Return the factory state for an issue or PR.

    Reads labels via `gh issue view --json labels`. (`gh` resolves both
    issues and PRs by number against the repo `gh` is configured for.)

    Returns:
        - The single `FactoryState` if exactly one `factory:*` state label is present
        - `None` if no `factory:*` state label is present (opt-in alone counts as none)

    Raises:
        LabelStateError: If two or more `factory:*` state labels are present.
        RuntimeError: If `gh` fails or returns malformed JSON.
    """
    rc, stdout, stderr = _run_gh(
        ["issue", "view", str(issue_or_pr_number), "--json", "labels"]
    )
    if rc != 0:
        raise RuntimeError(
            f"`gh issue view {issue_or_pr_number}` failed (exit {rc}): "
            f"{stderr.strip()[:300]}"
        )

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Could not parse `gh issue view {issue_or_pr_number}` JSON: {e}"
        ) from e

    raw_labels = payload.get("labels") or []
    label_names = [label.get("name", "") for label in raw_labels]

    states = [_LABEL_TO_STATE[name] for name in label_names if name in _LABEL_TO_STATE]

    if len(states) > 1:
        offending = sorted(s.value for s in states)
        raise LabelStateError(
            f"Issue/PR #{issue_or_pr_number} has multiple factory state labels: "
            f"{offending}. The state machine permits at most one. "
            f"Operator must reconcile manually."
        )

    return states[0] if states else None


# ── Transition state ────────────────────────────────────────────────────


def transition_state(
    issue_or_pr_number: int,
    from_state: FactoryState | None,
    to_state: FactoryState,
) -> bool:
    """Atomically transition an issue/PR from `from_state` to `to_state`.

    Optimistic concurrency: if the current state does not match `from_state`,
    return False without changing anything. The caller is responsible for
    re-reading state and retrying or escalating.

    The transition is performed by a single `gh issue edit --add-label X
    --remove-label Y` call. `gh` itself is not transactional, but the
    add+remove in one CLI invocation is the closest atomic unit available
    short of GraphQL mutations.

    Args:
        issue_or_pr_number: Issue or PR number on the configured repo.
        from_state: Expected current state (or None if no factory state yet).
        to_state: Target state.

    Returns:
        True if the transition succeeded.
        False if the optimistic check failed (current state != from_state).

    Raises:
        RuntimeError: If `gh` fails for reasons other than concurrency.
        LabelStateError: If the issue currently has multiple state labels.
    """
    # Determinism Spectrum (Sprint #1115): table-driven state machine, Tier 1.
    increment_module_counter("factory.labels.transition_state", tier=1)
    current = get_state(issue_or_pr_number)
    if current != from_state:
        logger.info(
            "transition_state: optimistic check failed for #%s "
            "(expected from=%s, observed=%s, target=%s) — no change",
            issue_or_pr_number,
            from_state.value if from_state else None,
            current.value if current else None,
            to_state.value,
        )
        return False

    args = ["issue", "edit", str(issue_or_pr_number), "--add-label", to_state.value]
    if from_state is not None:
        args.extend(["--remove-label", from_state.value])

    rc, _stdout, stderr = _run_gh(args)
    if rc != 0:
        raise RuntimeError(
            f"`gh issue edit {issue_or_pr_number}` failed transitioning "
            f"{from_state.value if from_state else '<none>'} → {to_state.value} "
            f"(exit {rc}): {stderr.strip()[:300]}"
        )
    return True


# ── Label provisioning ──────────────────────────────────────────────────


def ensure_labels_exist(repo: str = "your-org/bumba-open-harness") -> int:
    """Idempotently create every factory label on the given repo.

    Returns the number of labels newly created (0 if all already existed).

    Implementation: query existing labels once with `gh label list --limit 200
    --json name`, then for each missing label call `gh label create`. We do
    NOT rely on `gh label create`'s exit code to detect existence, because
    its error format has shifted across versions; querying first is robust.

    Raises:
        RuntimeError: If `gh label list` or `gh label create` fail.
    """
    rc, stdout, stderr = _run_gh(
        ["label", "list", "--repo", repo, "--limit", "200", "--json", "name"]
    )
    if rc != 0:
        raise RuntimeError(
            f"`gh label list --repo {repo}` failed (exit {rc}): "
            f"{stderr.strip()[:300]}"
        )

    try:
        existing_payload = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Could not parse `gh label list --repo {repo}` JSON: {e}"
        ) from e

    existing_names = {entry.get("name", "") for entry in existing_payload}

    created = 0
    for label in FACTORY_LABELS:
        if label in existing_names:
            continue
        color, description = _LABEL_METADATA[label]
        rc, _out, err = _run_gh(
            [
                "label",
                "create",
                label,
                "--repo",
                repo,
                "--color",
                color,
                "--description",
                description,
            ]
        )
        if rc != 0:
            raise RuntimeError(
                f"`gh label create {label} --repo {repo}` failed "
                f"(exit {rc}): {err.strip()[:300]}"
            )
        created += 1
        logger.info("ensure_labels_exist: created %s on %s", label, repo)

    return created
