"""Defense-in-depth push guard for the experiment loop (Sprint ref-audit-02-11).

Spec: docs/specs/2026-04-25-reference-audit/spec-02-11-ship-combumbaagent-experimentplist-runs-as-bumba-user.md
Issue: #986

The experiment loop runs as ``bumba-agent`` (restricted user) per operator
decision 2026-05-01. The primary push gate is the GitHub fine-grained PAT
issued for the ``bumba-agent`` user — its scope only allows writes to a
narrow set of branch namespaces. This module is the **secondary** gate: a
config-time accident catch that refuses to push branches outside the
allowed namespaces *before* the network call, so we never test the PAT's
deny rules in production.

Allowed namespaces:
- ``autoresearch/iter-`` — append-only audit trail (Sprint 02.04, #978).
- ``experiment-finalize/`` — grouped finalize branches (Sprint 02.08, #983).
- ``experiment/`` — per-iteration branches the loop creates while exploring.

Forbidden by construction: ``main``, ``feat/*``, ``release/*``, anything else.
"""

from __future__ import annotations

# Allowed branch-name prefixes for experiment-loop pushes. Frozen tuple so
# callers cannot mutate the policy by accident. Adding a new prefix is a
# code change reviewed in PR; this is not operator-tunable at runtime.
ALLOWED_PUSH_NAMESPACES: tuple[str, ...] = (
    "autoresearch/iter-",
    "experiment-finalize/",
    "experiment/",
)


def assert_pushable_branch(branch_name: str) -> None:
    """Raise ``PermissionError`` if ``branch_name`` is outside allowed namespaces.

    The GitHub PAT scope is the primary deny gate; this is a defense-in-depth
    check for config-time accidents (e.g. a refactor that builds the wrong
    ref from a template). The error message names the allowed prefixes so
    the operator can diagnose without grepping the source.

    Empty / whitespace-only branch names also raise — there is no legitimate
    case for pushing an empty ref.
    """
    if not branch_name or not branch_name.strip():
        raise PermissionError(
            f"Refusing to push to {branch_name!r}: empty branch name. "
            f"Allowed prefixes: {ALLOWED_PUSH_NAMESPACES}"
        )
    if not any(branch_name.startswith(p) for p in ALLOWED_PUSH_NAMESPACES):
        raise PermissionError(
            f"Refusing to push to {branch_name!r}: not in allowed namespaces. "
            f"Allowed prefixes: {ALLOWED_PUSH_NAMESPACES}"
        )
