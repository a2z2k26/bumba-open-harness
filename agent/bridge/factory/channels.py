"""Channels-as-branches helpers for the Dark Factory pipeline.

Sprint 15.04 — Plan 15 (NanoClaw v2 pattern adoption, channels variant
applied to the factory orchestrator).

Concept-only port of the channels-as-branches pattern (Dark Factory /
NanoClaw v2 lineage). No source copy. Bumba's Plan 14 factory currently
runs one issue → one PR → one merge into main. For larger features that
warrant per-slice review, this module describes the *labels* the
orchestrator reads to route a child issue to a per-channel integration
branch instead of main. Pure functions only — git side effects live in
the orchestrator.

Label vocabulary
----------------

  ``factory:channel:<name>`` — child issue belongs to a channel; the
      orchestrator branches off the channel's integration branch instead
      of ``main`` and merges the child's PR back into integration.

  ``factory:channel-close:<name>`` — auto-filed by the orchestrator when
      every other ``factory:channel:<name>`` issue is closed. The
      close issue's acceptance triggers an integration → main fast-forward
      and is operator-gated (label transitions still go through the same
      `factory:accepted` → `factory:needs-review` flow as any other PR).

The two prefixes are siblings, not states — a single issue may carry
either prefix but never both for the same channel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final


CHANNEL_LABEL_PREFIX: Final[str] = "factory:channel:"
CHANNEL_CLOSE_LABEL_PREFIX: Final[str] = "factory:channel-close:"


# ── Data ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChannelInfo:
    """Channel state derived from issue labels.

    Frozen — instances flow through the orchestrator unchanged. Built by
    :func:`parse_channel_from_labels`; consumers should not construct
    ``ChannelInfo`` directly so the integration-branch invariant is
    centralized.
    """

    name: str
    """The ``X`` in ``factory:channel:X`` (or ``factory:channel-close:X``)."""

    integration_branch: str
    """Computed branch ref — e.g. ``factory/channel/<name>/integration``.

    The ref always uses the ``factory/channel/`` prefix so the existing
    git-worktree-gc service can keep treating ``factory/`` branches as
    factory-owned for cleanup purposes.
    """

    is_close_issue: bool
    """True iff the issue carries ``factory:channel-close:<name>``.

    Close issues drive the integration → main fast-forward; channel-member
    issues drive child PRs that target the integration branch.
    """


# ── Errors ──────────────────────────────────────────────────────────────


class ChannelLabelError(ValueError):
    """Raised when a single issue carries multiple channel markers.

    The orchestrator MUST refuse to pick a winner — operator reconciliation
    is required. Mirrors :class:`bridge.factory.labels.LabelStateError`'s
    "surface conflict, never guess" stance.
    """


# ── Pure helpers ────────────────────────────────────────────────────────


def integration_branch_name(
    channel_name: str,
    *,
    prefix: str = "factory/channel",
) -> str:
    """Compute the integration branch ref name for ``channel_name``.

    Returns ``<prefix>/<name>/integration``. ``channel_name`` is
    expected to be kebab-case (the ``/add-extension`` skill enforces this
    operator-side); we do not normalize here so a stray uppercase or space
    surfaces as a real branch-creation error rather than being silently
    rewritten.
    """
    return f"{prefix}/{channel_name}/integration"


def parse_channel_from_labels(
    labels: list[str],
    *,
    branch_prefix: str = "factory/channel",
) -> ChannelInfo | None:
    """Return :class:`ChannelInfo` if ``labels`` contains a channel marker.

    Pure function. Returns ``None`` when no channel marker is present.

    Raises:
        ChannelLabelError: If two or more *distinct* channel markers are
            present (whether channel-member or channel-close, whether the
            same channel mixed across the two prefixes, or two different
            channels). The orchestrator surfaces this and refuses to act.

    Notes:
        - A single issue carrying ``factory:channel:foo`` AND
          ``factory:channel-close:foo`` is also a violation — close issues
          are filed by the orchestrator on a fresh issue, never on an
          existing channel member.
        - Duplicate occurrences of the same exact label are a no-op (GitHub
          deduplicates labels, but we tolerate the input shape regardless).
    """
    member_names: list[str] = []
    close_names: list[str] = []

    for raw in labels:
        if not isinstance(raw, str):
            continue
        if raw.startswith(CHANNEL_CLOSE_LABEL_PREFIX):
            name = raw[len(CHANNEL_CLOSE_LABEL_PREFIX):]
            if name and name not in close_names:
                close_names.append(name)
        elif raw.startswith(CHANNEL_LABEL_PREFIX):
            name = raw[len(CHANNEL_LABEL_PREFIX):]
            if name and name not in member_names:
                member_names.append(name)

    distinct_count = len(member_names) + len(close_names)
    if distinct_count == 0:
        return None
    if distinct_count > 1:
        offending = sorted(
            [f"{CHANNEL_LABEL_PREFIX}{n}" for n in member_names]
            + [f"{CHANNEL_CLOSE_LABEL_PREFIX}{n}" for n in close_names]
        )
        raise ChannelLabelError(
            "Issue carries multiple channel markers — orchestrator refuses "
            f"to pick a winner: {offending}. Operator must reconcile."
        )

    if close_names:
        name = close_names[0]
        return ChannelInfo(
            name=name,
            integration_branch=integration_branch_name(name, prefix=branch_prefix),
            is_close_issue=True,
        )

    name = member_names[0]
    return ChannelInfo(
        name=name,
        integration_branch=integration_branch_name(name, prefix=branch_prefix),
        is_close_issue=False,
    )


def is_channel_close_ready(
    channel_name: str,
    *,
    open_issue_labels_by_number: dict[int, list[str]],
) -> bool:
    """Return True iff no open issues carry ``factory:channel:<name>``.

    Channel-close issues themselves are excluded from the check — their
    presence does not block close-readiness (the orchestrator may have
    already filed a close issue). Used by the orchestrator on a successful
    child-PR merge to decide whether to file the channel-close issue.

    Args:
        channel_name: The ``X`` in ``factory:channel:X``.
        open_issue_labels_by_number: Map of issue number → labels for
            *currently open* issues. Caller fetches via ``gh issue list
            --state open --json number,labels``.

    Returns:
        True when zero open channel-member issues remain. False otherwise.
    """
    member_label = f"{CHANNEL_LABEL_PREFIX}{channel_name}"
    close_label = f"{CHANNEL_CLOSE_LABEL_PREFIX}{channel_name}"
    for labels in open_issue_labels_by_number.values():
        if not isinstance(labels, list):
            continue
        # Skip close issues for this channel — they don't block close.
        if close_label in labels:
            continue
        if member_label in labels:
            return False
    return True


def make_channel_close_issue_body(
    channel_name: str,
    *,
    closed_issue_numbers: list[int],
    branch_prefix: str = "factory/channel",
) -> tuple[str, str]:
    """Build the ``(title, body)`` for the auto-filed channel-close issue.

    Title: ``"Close channel: <name>"``.

    Body enumerates the closed children, the integration branch ref, and
    the operator-gated acceptance criterion (fast-forward integration →
    main). The Markdown body is paste-ready for ``gh issue create
    --body-file -``.
    """
    title = f"Close channel: {channel_name}"
    integration = integration_branch_name(channel_name, prefix=branch_prefix)
    children_lines = (
        "\n".join(f"- #{n}" for n in closed_issue_numbers)
        if closed_issue_numbers
        else "- (no children — empty channel; investigate before merging)"
    )
    body = f"""\
# Close channel: `{channel_name}`

The Dark Factory orchestrator filed this issue automatically because every
`factory:channel:{channel_name}` child issue is closed. This issue tracks
the final integration → main merge.

## Children merged into integration

{children_lines}

## Integration branch

`{integration}`

## Acceptance criterion (operator-gated)

- [ ] Operator reviews the integration diff: `gh pr create --base main \
--head {integration}` (or local `git diff main...{integration}`)
- [ ] All children's PRs are merged into integration (not main)
- [ ] CI green on the integration branch
- [ ] Operator approves the channel-close PR; orchestrator fast-forwards
  integration → main on accept

## Labels

- `factory:accepted` (added on operator review)
- `factory:channel-close:{channel_name}` (added by orchestrator)

---

_Concept-only port — Dark Factory channels-as-branches (no LICENSE)._
"""
    return title, body


__all__ = [
    "CHANNEL_LABEL_PREFIX",
    "CHANNEL_CLOSE_LABEL_PREFIX",
    "ChannelInfo",
    "ChannelLabelError",
    "integration_branch_name",
    "is_channel_close_ready",
    "make_channel_close_issue_body",
    "parse_channel_from_labels",
]
