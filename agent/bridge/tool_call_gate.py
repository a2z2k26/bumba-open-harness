"""Tool-call gate — acknowledgment enforcement for operator messages.

D7.5 finding F-2: paired with operator_inbox.py — the seam where operator
messages should preempt in-flight tool calls. Activation tracked in D7.9
(#1421). Today this gate fires only at turn boundaries; D7.9 wires it
into claude_runner so it fires before every tool-call dispatch.

Sprint 4.10 — Phase 4B (Dialogue-First Communication Architecture).

Sprint 4.9 makes operator messages SEEN on every turn by prepending a
banner to the context. This module makes them ACTED ON: before the
harness hands control back to the model for another work-tool-call
turn, it calls ``evaluate_gate()`` to decide whether the agent has
satisfied the acknowledgment contract. If pending operator messages
exist and the agent's most recent dialogue did not ack them, the gate
returns a ``BLOCK_*`` decision and the harness re-prompts the agent
with a structured block message instead of allowing another work
turn.

Architectural note — why this is a pre-turn gate, not a mid-call
interceptor:

    The Sprint 4.10 spec describes a ``pre_tool_call_gate`` that raises
    ``ToolCallBlocked`` from inside the tool-dispatch path. That is not
    achievable with the current Bumba bridge architecture: the bridge
    spawns ``claude -p`` as a subprocess and streams JSON events from
    it. Tool calls happen *inside* that subprocess; by the time the
    bridge sees a ``tool_use`` event in the stream, the tool has
    already been invoked. There is no harness-owned hook the bridge
    can intercept mid-call without rewriting how Claude Code executes
    tools.

    The correct place to enforce the contract is at turn boundaries.
    Between turns, the bridge owns full control — it decides what
    context to hand back to the model and can refuse to start a new
    work turn until the agent has emitted ``[ACK:msg_id]`` markers
    for each pending message. That is what this module implements:
    a pure function over (inbox, dialogue_text) that the bridge
    consults before building the next turn's context.

    This is functionally equivalent to the spec's intent — "the
    bumba-agent cannot physically issue a tool call while an operator
    message is pending" — because the agent has to pass through the
    bridge's turn-boundary logic before any tool call. The gate is the
    same wall, moved up one layer so it lives where the bridge can
    actually enforce it.

Integration surface (this sprint ships the module only; wiring into
``claude_runner.py`` is a follow-up, same pattern as Sprints 4.8 and
4.9):

    1. After the agent produces assistant text for a turn, call
       ``parse_acks_from_dialogue(text, inbox)`` to mark acked
       messages in the inbox.
    2. Before starting the next turn, call ``evaluate_gate(inbox)``.
       If the decision is ``ALLOW``, proceed normally. Otherwise,
       build the next turn context from the block message (instead
       of the normal base context) and re-prompt the agent.
    3. The banner from Sprint 4.9's
       ``build_turn_context_with_inbox`` is still used on ``ALLOW``
       turns to keep the message visible until the agent volunteers
       a dialogue response addressing it.

Severity precedence: HALT > QUESTION > INFO. If any HALT message is
pending, the decision is always ``BLOCK_HALT`` regardless of what
other severities are present. HALT additionally signals that ack
alone is not enough — the operator must issue an explicit resume
command before work continues.
"""
from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass

from bridge.operator_inbox import (
    MessageSeverity,
    OperatorInbox,
    OperatorMessage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ACK marker parsing
# ---------------------------------------------------------------------------


# Matches the machine-readable acknowledgment marker the agent emits in
# its dialogue channel. Format: ``[ACK:msg_<timestamp>_<seq>]``. The
# ``msg_id`` is the exact value produced by OperatorInbox.receive(),
# which is ``msg_`` + digits + ``_`` + digits. We keep the pattern
# tight so stray strings like ``[ACK:foo]`` are ignored rather than
# silently dispatched to the inbox where they'd be no-ops anyway —
# catching them here lets us log a warning if the agent starts emitting
# malformed markers.
ACK_PATTERN = re.compile(r"\[ACK:(msg_\d+_\d+)\]")


async def parse_acks_from_dialogue(
    text: str,
    inbox: OperatorInbox,
) -> list[str]:
    """Scan ``text`` for ACK markers and acknowledge matching inbox entries.

    Returns the list of message IDs that were successfully acked as a
    result of this call (i.e. the message was pending before the call
    and is now acked). IDs in the text that don't correspond to a
    pending message — whether unknown or already-acked — are silently
    dropped from the return value, matching the inbox idempotency
    contract from Sprint 4.9.

    Duplicate markers for the same ID in a single ``text`` produce at
    most one successful ack: the first marker acks the message, and
    subsequent markers hit the already-acked path and return nothing.
    """
    if not text:
        return []

    # Collect the set of pending IDs BEFORE any acks so we can tell
    # which markers produced a real state transition.
    pending_before = {m.id for m in await inbox.pending()}
    if not pending_before:
        # No-op fast path: the inbox is empty, nothing to ack.
        for match in ACK_PATTERN.finditer(text):
            logger.debug(
                "tool_call_gate: ack marker %s dropped (inbox empty)",
                match.group(1),
            )
        return []

    acked: list[str] = []
    already_seen: set[str] = set()
    for match in ACK_PATTERN.finditer(text):
        msg_id = match.group(1)
        if msg_id in already_seen:
            # Duplicate marker in the same dialogue; first one already
            # handled, skip silently.
            continue
        already_seen.add(msg_id)

        if msg_id not in pending_before:
            # Unknown or already-acked before this call.
            logger.debug(
                "tool_call_gate: ack marker %s dropped (not pending)",
                msg_id,
            )
            continue

        await inbox.acknowledge(msg_id)
        acked.append(msg_id)

    if acked:
        logger.info(
            "tool_call_gate: parsed %d ack(s) from dialogue: %s",
            len(acked),
            ", ".join(acked),
        )
    return acked


# ---------------------------------------------------------------------------
# Gate decision
# ---------------------------------------------------------------------------


class GateDecision(enum.Enum):
    """What the harness is allowed to do on the next turn.

    - ``ALLOW``: no pending operator messages; hand control back to
      the model as usual.
    - ``BLOCK_INFO``: reserved; not currently emitted. INFO messages
      populate the operator banner for context but never block tool
      calls (per the operator-inbox doctrine — "If severity is INFO,
      acknowledge and continue work if appropriate"). The enum value
      remains for downstream consumers that pattern-match on it; the
      formatter helper ``_format_info_block`` is kept for the same
      reason.
    - ``BLOCK_QUESTION``: at least one QUESTION message is pending;
      the harness must re-prompt AND pause the work loop until the
      operator confirms continuation.
    - ``BLOCK_HALT``: at least one HALT message is pending; the
      harness must re-prompt AND refuse to start any further tool
      calls until the operator issues an explicit resume command.
      Acking a HALT alone is NOT sufficient to unblock — this is the
      strongest state.
    """

    ALLOW = "allow"
    BLOCK_INFO = "block_info"
    BLOCK_QUESTION = "block_question"
    BLOCK_HALT = "block_halt"


@dataclass(frozen=True)
class GateResult:
    """Result of a gate evaluation.

    Attributes:
        decision: What the harness is permitted to do next.
        block_message: The text the harness should re-prompt the agent
            with when the decision is not ``ALLOW``. Empty string on
            ``ALLOW``.
    """

    decision: GateDecision
    block_message: str


# ---------------------------------------------------------------------------
# Gate evaluation — pure function over inbox state
# ---------------------------------------------------------------------------


async def evaluate_gate(
    inbox: OperatorInbox,
    *,
    min_pending: int = 1,
) -> GateResult:
    """Decide whether the harness may start another tool-call turn.

    Severity precedence is HALT > QUESTION > INFO. The highest
    severity among pending messages determines the decision. The
    block message lists all pending IDs (not just the highest-severity
    ones) so the agent sees the full state it needs to address.

    ``min_pending`` is the number of pending QUESTION messages required
    to trigger BLOCK_QUESTION. Default 1 preserves single-question
    blocking; ``min_pending=2`` lets a lone question through and only
    blocks once a second accumulates. INFO never blocks regardless of
    threshold — per the operator-inbox doctrine ("If severity is INFO,
    acknowledge and continue work if appropriate"), INFO messages
    populate the banner for context but tool calls continue. HALT is
    always immediate regardless of threshold.
    """
    pending = await inbox.pending()
    if not pending:
        return GateResult(decision=GateDecision.ALLOW, block_message="")

    # #2207 Part C — defensive: never let the gate block on a force-pause
    # banner the bridge itself emitted. The banner is meant to alert the
    # operator, not to require the agent to acknowledge its own self-talk.
    # Today no code path re-ingests the banner into the inbox, but if a
    # future path does (e.g. Discord webhook fan-back), this guard prevents
    # the loop the issue describes from forming. Filter banner-marker
    # messages out of the gate's pending view; they still surface in
    # `inbox.pending()` for other consumers.
    pending = [m for m in pending if not _is_force_pause_banner(m)]
    if not pending:
        return GateResult(decision=GateDecision.ALLOW, block_message="")

    halt_msgs = [m for m in pending if m.severity == MessageSeverity.HALT]
    question_msgs = [m for m in pending if m.severity == MessageSeverity.QUESTION]

    if halt_msgs:
        return GateResult(
            decision=GateDecision.BLOCK_HALT,
            block_message=_format_halt_block(pending, halt_msgs),
        )

    # INFO never blocks. Threshold only gates QUESTION accumulation.
    if len(question_msgs) < max(1, min_pending):
        return GateResult(decision=GateDecision.ALLOW, block_message="")

    return GateResult(
        decision=GateDecision.BLOCK_QUESTION,
        block_message=_format_question_block(pending, question_msgs),
    )


# ---------------------------------------------------------------------------
# #2207 Part C — force-pause banner detection
# ---------------------------------------------------------------------------


_FORCE_PAUSE_MARKER: str = "[FORCE-PAUSE]"


def _is_force_pause_banner(msg: OperatorMessage) -> bool:
    """True iff a pending message looks like a bridge-emitted force-pause banner.

    The DiscordForcePauseAlerter posts messages tagged `[FORCE-PAUSE]` to the
    operator channel. If those messages ever get re-ingested as pending
    inbox content (Discord webhook fan-back, replay, etc.), this filter
    keeps the gate from looping on them.
    """
    return msg.content.startswith(_FORCE_PAUSE_MARKER)


# ---------------------------------------------------------------------------
# Block-message formatters
# ---------------------------------------------------------------------------


def _format_pending_list(pending: list[OperatorMessage]) -> str:
    """Render a pending-message list the agent can see inside a block message."""
    lines: list[str] = []
    for msg in pending:
        lines.append(
            f"  - [{msg.severity.value.upper()}] {msg.id}: {msg.content}"
        )
    return "\n".join(lines)


def _format_halt_block(
    pending: list[OperatorMessage],
    halt_msgs: list[OperatorMessage],
) -> str:
    return (
        "TOOL CALL BLOCKED — HALT PENDING\n\n"
        f"{len(halt_msgs)} HALT message(s) from the operator are pending. "
        "Cease all work immediately. Do not issue any tool calls. Wait for "
        "the operator to explicitly resume work with a `continue` or "
        "`resume` command.\n\n"
        "Pending operator messages:\n"
        f"{_format_pending_list(pending)}\n\n"
        "Acknowledge in your dialogue channel with [ACK:msg_id] for each "
        "message, then stop and wait. Acking a HALT does not resume work — "
        "only the operator can."
    )


def _format_question_block(
    pending: list[OperatorMessage],
    question_msgs: list[OperatorMessage],
) -> str:
    return (
        "TOOL CALL BLOCKED — OPERATOR QUESTION PENDING\n\n"
        f"{len(question_msgs)} QUESTION message(s) from the operator are "
        "pending. You cannot issue tool calls until you respond in the "
        "dialogue channel and include [ACK:msg_id] for each pending "
        "message.\n\n"
        "Pending operator messages:\n"
        f"{_format_pending_list(pending)}\n\n"
        "Respond to the question(s) directly in your dialogue output and "
        "include [ACK:msg_id] for each pending message. After acking, pause "
        "work until the operator says `continue`."
    )


def _format_info_block(info_msgs: list[OperatorMessage]) -> str:
    return (
        "TOOL CALL BLOCKED — OPERATOR INFO PENDING\n\n"
        f"{len(info_msgs)} INFO message(s) from the operator are pending. "
        "Acknowledge them in your dialogue channel before your next tool "
        "call.\n\n"
        "Pending operator messages:\n"
        f"{_format_pending_list(info_msgs)}\n\n"
        "Include [ACK:msg_id] in your dialogue response for each pending "
        "message. After acknowledgment you may continue work."
    )
