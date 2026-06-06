"""Operator-mediated handoff protocol — data types + composer + listener + fire path.

Sprint 1.01 (#2138) shipped data-only types ``HandoffDraft`` + ``HandoffPacket``.
Sprint 1.02 (#2139) added the sender-side composer: ``save_conversation_gist``,
``compose_handoff``, ``format_draft_for_operator``.
Sprint 1.03 (#2140) added the receiver-side parser + consumer:
``HANDOFF_REGEX``, ``HandoffPlan``, ``parse_handoff_message``, ``consume_handoff``.
Sprint 1.04 (#2141) ships the fire path + close-resolved promotion:
``fire_handoff``, ``mark_handoff_resolved``.

Design notes
------------
- ``HandoffDraft`` is what a harness composes locally. The operator
  reviews a draft before it is "fired".
- ``HandoffPacket`` is the durable, sent record. It points at an
  external artifact (gist or promoted repo path) so the receiving
  harness can reconstruct the full handoff without trusting a Discord
  message body that may be truncated or reformatted.
- Both types are frozen dataclasses. Immutability is load-bearing:
  drafts must not mutate between operator review and fire, and packets
  must not mutate after being persisted.
- ``response_protocol`` is fixed at ``"operator-only"``. The receiving
  harness replies to the operator, never to the sender. This is a
  structural property of the protocol, not an operator-tunable setting.

See ``docs/plans/2026-05-16-issue-1112-master/`` for the surrounding
design when those plan docs land.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# ``review`` requires operator confirmation before ``fire_handoff``.
# ``auto`` is reserved for the trust-escalation work and is not used by
# the Phase 1 composer.
TrustLevel = Literal["review", "auto"]


@dataclass(frozen=True)
class HandoffDraft:
    """A composed-but-not-yet-fired handoff.

    The operator reviews the rendered form of this draft before the
    composer calls ``fire_handoff``. All slots are required because the
    template is meant to force structured thinking on the sender; an
    empty ``boundaries`` field, for example, would silently invite the
    receiving harness to over-reach.
    """

    from_harness: str
    to_harness: str
    topic: str
    context_summary: str
    work_done: str
    ask: str
    boundaries: str
    references: tuple[str, ...]
    # Structural; not negotiable. Documented as a field so that the
    # protocol itself is self-describing when a draft is rendered.
    response_protocol: Literal["operator-only"] = "operator-only"
    trust_level: TrustLevel = "review"


@dataclass(frozen=True)
class HandoffPacket:
    """A fired handoff.

    The ``artifact_url`` points at the durable copy of the full
    handoff (gist or promoted repo path). The remaining fields are the
    minimum needed to route the notification on the receiving side and
    to surface the handoff to the operator on the sending side.
    """

    from_harness: str
    to_harness: str
    artifact_url: str
    one_line_summary: str
    fired_at: str  # ISO-8601 UTC timestamp


# ---------------------------------------------------------------------------
# Sprint 1.02 (#2139) — sender-side composer
# ---------------------------------------------------------------------------


def _slugify_topic(topic: str, max_len: int = 40) -> str:
    """Conservative filename-safe slug for a free-form topic string.

    Keeps alphanumerics; collapses everything else to a single ``-``. We
    do not trust the topic — it comes from the operator's typed line and
    can contain shell metacharacters or path separators that would be
    awkward inside a gist filename. The slug is the topic, not a hash —
    the operator should still be able to recognise the gist in their
    GitHub UI.
    """
    out = []
    last_was_dash = False
    for ch in topic:
        if ch.isalnum():
            out.append(ch)
            last_was_dash = False
        else:
            if not last_was_dash:
                out.append("-")
                last_was_dash = True
    slug = "".join(out).strip("-")
    return slug[:max_len]


def save_conversation_gist(
    conversation: str,
    from_harness: str,
    to_harness: str,
    topic: str,
) -> str:
    """Create a gist with the conversation transcript; return the gist URL.

    Implementation uses ``gh gist create`` so authentication is the local
    ``gh`` CLI's responsibility (no GitHub API client, no token in this
    module). ``check=True`` means a failed CLI invocation surfaces as a
    ``CalledProcessError`` for the caller — the composer command catches
    it and renders a friendly message.
    """
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    filename = (
        f"bumba-handoff-{from_harness}-to-{to_harness}-"
        f"{iso}-{_slugify_topic(topic)}.md"
    )
    proc = subprocess.run(
        ["gh", "gist", "create", "--filename", filename, "-"],
        input=conversation,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def compose_handoff(
    conversation_ctx: str,
    from_harness: str,
    to_harness: str,
    topic: str,
) -> HandoffDraft:
    """Synthesize a ``HandoffDraft`` from the current conversation context.

    Phase 1 implementation is intentionally **non-LLM**: it packages the
    conversation + slot scaffolding into a well-formed draft so downstream
    review/fire wiring (Sprint 1.04) has a stable shape to consume. The
    operator can iterate the draft via ``edit`` before firing once the
    receiver-side lands (Sprint 1.03). Sub-Claude synthesis is the long
    pole and is deferred per the issue body — the test-friendly seam
    here is the function signature returning ``HandoffDraft``.

    The composer is deliberate about populating every required slot with a
    non-empty string so the ``HandoffDraft`` frozen-dataclass invariants
    hold (every slot in the template is required, by design — see
    ``agent/config/handoff-template.md``).
    """
    # Keep the context summary bounded so a long Discord transcript does
    # not blow up the rendered draft. The full transcript still lives in
    # the gist; this field is meant to be a hint, not a copy.
    summary_cap = 600
    ctx = (conversation_ctx or "").strip()
    if not ctx:
        context_summary = (
            "No prior conversation captured for this chat — operator "
            "should edit before firing."
        )
    elif len(ctx) <= summary_cap:
        context_summary = ctx
    else:
        context_summary = ctx[:summary_cap].rstrip() + " …"

    # Phase 1 placeholder slots — the operator is expected to refine via
    # ``edit`` once that subcommand lands. These strings are short and
    # marked as drafts so reviewers immediately notice them.
    work_done = (
        "[draft] The sending harness should restate concrete work already "
        "done — file paths, PR numbers, decisions. Edit before firing."
    )
    ask = (
        f"[draft] {topic} — restate the ask in imperative voice. "
        "Edit before firing."
    )
    boundaries = (
        "[draft] Surgical changes only. Receiving harness should not "
        "refactor unrelated modules. Edit to tighten this further."
    )
    references: tuple[str, ...] = ()

    return HandoffDraft(
        from_harness=from_harness,
        to_harness=to_harness,
        topic=topic,
        context_summary=context_summary,
        work_done=work_done,
        ask=ask,
        boundaries=boundaries,
        references=references,
        # ``response_protocol`` is structural and not negotiable; the
        # dataclass default suffices but we pass it explicitly for
        # documentation in the call site.
        response_protocol="operator-only",
        trust_level="review",
    )


def format_draft_for_operator(draft: HandoffDraft, gist_url: str) -> str:
    """Render a ``HandoffDraft`` as a Discord-friendly markdown block.

    Pure function: no I/O, no mutation, deterministic on its inputs. The
    bottom of the block tells the operator the three verbs they can reply
    with — those are wired by the fire path in Sprint 1.04.
    """
    references_block = (
        "\n".join(f"- {r}" for r in draft.references)
        if draft.references
        else "_(none yet — edit the draft to add references)_"
    )
    return (
        f"**Handoff draft → {draft.to_harness}** (topic: {draft.topic})\n"
        f"Gist: {gist_url}\n\n"
        f"**Context summary**\n{draft.context_summary}\n\n"
        f"**Work done**\n{draft.work_done}\n\n"
        f"**Ask**\n{draft.ask}\n\n"
        f"**Boundaries**\n{draft.boundaries}\n\n"
        f"**References**\n{references_block}\n\n"
        f"**Response protocol**: {draft.response_protocol}\n"
        f"**Trust level**: {draft.trust_level}\n\n"
        f"Reply `go` to fire, `edit` to revise, `abort` to cancel."
    )


# ---------------------------------------------------------------------------
# Sprint 1112.1.03 (#2140) — receiver-side parsing + consumption.
#
# These additions live in this module so the data model and its accompanying
# pure parse/consume functions stay co-located. The Discord listener wires
# them in via ``_route_peer_handoff`` (see ``bridge.discord_bot``); the
# protocol-level invariants (target-harness gate, frozen plan dataclass,
# subprocess-based gist fetch) are tested here.
# ---------------------------------------------------------------------------


# Line shape:
#   [handoff to:<harness-id>] <url> <summary>
#
# Harness IDs use the same `[a-z0-9-]+` shape that ``BridgeConfig.harness_id``
# implies (the default `local-1` matches; uppercase or underscore is
# deliberately rejected so a misconfigured peer can't smuggle in mismatched
# IDs).
HANDOFF_REGEX = re.compile(
    r"^\[handoff to:(?P<to>[a-z0-9-]+)\] (?P<url>https?://\S+) (?P<summary>.+)$"
)


@dataclass(frozen=True)
class HandoffPlan:
    """Receiver-side execution plan, drafted from a consumed packet.

    The plan is presented to the operator for review; the receiving harness
    does NOT execute it autonomously. ``proposed_steps`` is a tuple of
    imperative strings — placeholder content (``("operator-review-required",)``)
    is acceptable here because the sub-Claude wiring that fills in real
    steps lands in a subsequent sprint. The contract is: non-empty tuple
    of strings.
    """

    from_harness: str
    to_harness: str
    artifact_url: str
    summary: str
    proposed_steps: tuple[str, ...]


def parse_handoff_message(content: str, my_harness: str) -> HandoffPacket | None:
    """Return a :class:`HandoffPacket` if ``content`` is a handoff addressed
    to ``my_harness``, else ``None``.

    This is the routing gate: any peer-bot message that does not parse, or
    that parses but targets a different harness, is silently rejected. The
    caller (the Discord listener) treats ``None`` as "not a handoff, fall
    through to the normal rejection path".

    Fields not present in the line (``from_harness``, ``fired_at``) are
    left empty; the listener fills them from the Discord message metadata
    before persisting.
    """
    m = HANDOFF_REGEX.match(content)
    if m is None:
        return None
    if m.group("to") != my_harness:
        return None
    return HandoffPacket(
        from_harness="",  # filled by listener from message.author
        to_harness=m.group("to"),
        artifact_url=m.group("url"),
        one_line_summary=m.group("summary"),
        fired_at="",  # filled by listener from message.created_at
    )


def consume_handoff(packet: HandoffPacket) -> HandoffPlan:
    """Fetch the gist body and return a :class:`HandoffPlan` for operator review.

    The sub-Claude wiring that turns the gist into a concrete execution plan
    is deferred (it lands in the implementing PR's second commit and a
    subsequent sprint). The contract this function pins now:

    1. ``gh gist view <id>`` is invoked with the id extracted from
       ``packet.artifact_url``.
    2. A ``HandoffPlan`` is returned whose ``proposed_steps`` is a non-empty
       tuple. ``("operator-review-required",)`` is the placeholder.

    The receiver does NOT auto-execute the plan; the operator is the gate.
    """
    gist_id = packet.artifact_url.rstrip("/").rsplit("/", 1)[-1]
    subprocess.run(
        ["gh", "gist", "view", gist_id],
        capture_output=True,
        text=True,
        check=False,
    )
    return HandoffPlan(
        from_harness=packet.from_harness,
        to_harness=packet.to_harness,
        artifact_url=packet.artifact_url,
        summary=packet.one_line_summary,
        proposed_steps=("operator-review-required",),
    )


# ---------------------------------------------------------------------------
# Sprint 1.04 (#2141) — fire path + close-resolved promotion
# ---------------------------------------------------------------------------


async def fire_handoff(
    draft: HandoffDraft,
    gist_url: str,
    target_channel_id: int,
    discord_client,
) -> HandoffPacket:
    """Post the structured handoff trigger to the peer-allowlisted Discord channel.

    Returns a :class:`HandoffPacket` recording what was sent, when, and where.
    The packet is the operator-facing record the sender can use to track the
    handoff lifecycle until ``mark_handoff_resolved`` migrates the gist to a
    promoted repo path.

    The structured line shape matches what ``parse_handoff_message`` expects
    on the receiver side: ``[handoff to:<target>] <gist-url> <summary>``.

    ``target_channel_id`` is the peer-allowlisted Discord channel where the
    receiver harness is listening. The caller is responsible for resolving
    the channel id — typically from operator config or per-peer channel map.

    The ``discord_client`` is the live discord.py client whose ``get_channel``
    method returns a sendable channel. Pure-function unit tests should pass
    a mock supporting ``get_channel(id).send(content)``.
    """
    summary_line = draft.topic  # one-line summary; operator-edited via /handoff edit
    content = f"[handoff to:{draft.to_harness}] {gist_url} {summary_line}"
    channel = discord_client.get_channel(target_channel_id)
    await channel.send(content)
    return HandoffPacket(
        from_harness=draft.from_harness,
        to_harness=draft.to_harness,
        artifact_url=gist_url,
        one_line_summary=summary_line,
        fired_at=datetime.now(timezone.utc).isoformat(),
    )


def mark_handoff_resolved(
    packet: HandoffPacket,
    topic_slug: str,
    repo_root: Path,
) -> str:
    """Migrate a gist's content to ``handoffs/promoted/<date>-<topic>.md``.

    Returns the relative path of the promoted file (relative to ``repo_root``).

    The promotion captures the gist's content + a provenance header naming the
    sending + receiving harnesses + the original gist url + the fired-at
    timestamp. This is the close-resolved step in the handoff lifecycle: a
    handoff that produced an actionable outcome gets a durable copy in the
    repo for future reference; one that didn't stays ephemeral in gist form.

    Operator-triggered via ``/handoff-resolve <gist-id>`` per the runbook;
    never automatic.
    """
    gist_id = packet.artifact_url.rstrip("/").rsplit("/", 1)[-1]
    proc = subprocess.run(
        ["gh", "gist", "view", gist_id],
        capture_output=True,
        text=True,
        check=True,
    )
    content = proc.stdout
    date = packet.fired_at[:10] if packet.fired_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    safe_slug = _slugify_topic(topic_slug)
    dest = (
        repo_root
        / "handoffs"
        / "promoted"
        / f"{date}-{packet.from_harness}-to-{packet.to_harness}-{safe_slug}.md"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"<!-- promoted from gist {packet.artifact_url} -->\n"
        f"<!-- {packet.from_harness} → {packet.to_harness} {packet.fired_at} -->\n\n"
    )
    dest.write_text(header + content)
    return str(dest.relative_to(repo_root))


__all__ = [
    "HANDOFF_REGEX",
    "HandoffDraft",
    "HandoffPacket",
    "HandoffPlan",
    "TrustLevel",
    "compose_handoff",
    "consume_handoff",
    "fire_handoff",
    "format_draft_for_operator",
    "mark_handoff_resolved",
    "parse_handoff_message",
    "save_conversation_gist",
]
