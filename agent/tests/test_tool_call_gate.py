"""Tests for agent.bridge.tool_call_gate.

Sprint 4.10 — Phase 4B (Dialogue-First Communication Architecture).

The gate sits between model turns. Given the inbox state and the
assistant's most recent dialogue output, the gate decides whether
the harness is allowed to hand control back to the model for another
work-tool-call turn or must re-prompt the agent with a blocking
banner until pending operator messages are acknowledged.

The gate is a pure function over (pending_messages, dialogue_text).
The tests exercise:

- ACK marker parsing from free-form assistant text
- Idempotent acknowledgment against the inbox
- Gate decision logic across severity combinations
- Severity precedence (HALT > QUESTION > INFO)
- Block-message content the agent sees when blocked
"""
from __future__ import annotations

import pytest

from bridge.operator_inbox import (
    MessageSeverity,
    OperatorInbox,
)
from bridge.tool_call_gate import (
    ACK_PATTERN,
    GateDecision,
    GateResult,
    evaluate_gate,
    parse_acks_from_dialogue,
)


# ---------------------------------------------------------------------------
# ACK_PATTERN — regex shape
# ---------------------------------------------------------------------------


def test_ack_pattern_matches_standard_marker():
    assert ACK_PATTERN.search("[ACK:msg_123_4]") is not None


def test_ack_pattern_captures_msg_id():
    m = ACK_PATTERN.search("acknowledging [ACK:msg_999_1] now")
    assert m is not None
    assert m.group(1) == "msg_999_1"


def test_ack_pattern_finds_multiple_in_one_string():
    text = "Got it [ACK:msg_1_1] and also [ACK:msg_2_2] handled."
    ids = [m.group(1) for m in ACK_PATTERN.finditer(text)]
    assert ids == ["msg_1_1", "msg_2_2"]


def test_ack_pattern_rejects_wrong_prefix():
    assert ACK_PATTERN.search("[ack:msg_1_1]") is None  # lowercase ack
    assert ACK_PATTERN.search("[ACKmsg_1_1]") is None   # missing colon
    assert ACK_PATTERN.search("ACK:msg_1_1") is None    # missing brackets


def test_ack_pattern_rejects_non_msg_id_payload():
    assert ACK_PATTERN.search("[ACK:foo_bar]") is None
    assert ACK_PATTERN.search("[ACK:1234]") is None
    assert ACK_PATTERN.search("[ACK:]") is None


# ---------------------------------------------------------------------------
# parse_acks_from_dialogue — integration with inbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_acks_acknowledges_matching_messages():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    m2 = await inbox.receive("second", MessageSeverity.QUESTION)

    text = f"Noted [ACK:{m1.id}] and answering [ACK:{m2.id}]: yes."
    acked = await parse_acks_from_dialogue(text, inbox)

    assert set(acked) == {m1.id, m2.id}
    assert await inbox.pending() == []


@pytest.mark.asyncio
async def test_parse_acks_with_no_markers_returns_empty():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    acked = await parse_acks_from_dialogue("just a plain reply", inbox)
    assert acked == []
    # Pending message should still be pending
    assert [m.id for m in await inbox.pending()] == [m1.id]


@pytest.mark.asyncio
async def test_parse_acks_silently_ignores_unknown_ids():
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("real", MessageSeverity.INFO)
    # Fabricated id that doesn't exist in the inbox
    text = "[ACK:msg_9999999_42]"
    acked = await parse_acks_from_dialogue(text, inbox)
    # parse_acks should return only ids that successfully acked, not
    # ids it tried to ack. Unknown ids are silently dropped by the
    # inbox idempotency contract, and parse_acks should mirror that.
    assert acked == []


@pytest.mark.asyncio
async def test_parse_acks_handles_already_acked_ids_silently():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    await inbox.acknowledge(m1.id)

    acked = await parse_acks_from_dialogue(f"[ACK:{m1.id}]", inbox)
    # Message was already acked — no error, no change.
    assert acked == []
    assert await inbox.pending() == []


@pytest.mark.asyncio
async def test_parse_acks_partial_match_acks_only_real_ones():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    text = f"[ACK:{m1.id}] and [ACK:msg_fake_1]"
    acked = await parse_acks_from_dialogue(text, inbox)
    assert acked == [m1.id]


@pytest.mark.asyncio
async def test_parse_acks_duplicate_markers_ack_once():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    text = f"[ACK:{m1.id}] [ACK:{m1.id}] [ACK:{m1.id}]"
    acked = await parse_acks_from_dialogue(text, inbox)
    # The first ack succeeds; subsequent ones are silent no-ops.
    assert acked == [m1.id]
    assert await inbox.pending() == []


# ---------------------------------------------------------------------------
# evaluate_gate — decision logic (pure function over pending list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_allows_when_inbox_empty():
    inbox = OperatorInbox(session_id="s1")
    result = await evaluate_gate(inbox)
    assert isinstance(result, GateResult)
    assert result.decision == GateDecision.ALLOW
    assert result.block_message == ""


@pytest.mark.asyncio
async def test_gate_allows_on_pending_info_only():
    # INFO never blocks. The message lands in the inbox so the banner
    # surfaces it, but tool calls flow per the operator-inbox doctrine
    # ("If severity is INFO, acknowledge and continue work if appropriate").
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("fyi", MessageSeverity.INFO)
    result = await evaluate_gate(inbox)
    assert result.decision == GateDecision.ALLOW
    assert result.block_message == ""


@pytest.mark.asyncio
async def test_gate_blocks_on_pending_question():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("are you sure?", MessageSeverity.QUESTION)
    result = await evaluate_gate(inbox)
    assert result.decision == GateDecision.BLOCK_QUESTION
    assert m1.id in result.block_message
    assert "QUESTION" in result.block_message


@pytest.mark.asyncio
async def test_gate_blocks_on_pending_halt():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("STOP", MessageSeverity.HALT)
    result = await evaluate_gate(inbox)
    assert result.decision == GateDecision.BLOCK_HALT
    assert m1.id in result.block_message
    assert "HALT" in result.block_message


# ---------------------------------------------------------------------------
# Severity precedence — HALT > QUESTION > INFO
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_halt_overrides_info_and_question():
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("info msg", MessageSeverity.INFO)
    await inbox.receive("question msg", MessageSeverity.QUESTION)
    await inbox.receive("STOP", MessageSeverity.HALT)
    result = await evaluate_gate(inbox)
    assert result.decision == GateDecision.BLOCK_HALT


@pytest.mark.asyncio
async def test_gate_question_overrides_info_when_no_halt():
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("info msg", MessageSeverity.INFO)
    await inbox.receive("are you sure?", MessageSeverity.QUESTION)
    result = await evaluate_gate(inbox)
    assert result.decision == GateDecision.BLOCK_QUESTION


@pytest.mark.asyncio
async def test_gate_allows_multiple_info_with_no_higher_severity():
    # Multiple stacked INFO messages still do not block. The headline
    # smoke-test regression — operator sending 4× "hi" in a row should
    # never trip the gate.
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("info 1", MessageSeverity.INFO)
    await inbox.receive("info 2", MessageSeverity.INFO)
    await inbox.receive("info 3", MessageSeverity.INFO)
    await inbox.receive("info 4", MessageSeverity.INFO)
    result = await evaluate_gate(inbox)
    assert result.decision == GateDecision.ALLOW


# ---------------------------------------------------------------------------
# Post-ack state transitions — the full round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_allows_after_single_ack_clears_inbox():
    # Use a QUESTION because INFO never blocks; the round-trip
    # we're proving here is: block → ack → allow.
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("are you sure?", MessageSeverity.QUESTION)

    # First gate check: blocked
    before = await evaluate_gate(inbox)
    assert before.decision == GateDecision.BLOCK_QUESTION

    # Agent responds with an ACK marker
    await parse_acks_from_dialogue(f"Acknowledged [ACK:{m1.id}]", inbox)

    # Second gate check: allowed
    after = await evaluate_gate(inbox)
    assert after.decision == GateDecision.ALLOW


@pytest.mark.asyncio
async def test_gate_still_blocks_after_partial_ack():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    m2 = await inbox.receive("second", MessageSeverity.QUESTION)

    # Agent only acks m1
    await parse_acks_from_dialogue(f"[ACK:{m1.id}]", inbox)

    # Gate must still block because m2 remains pending
    result = await evaluate_gate(inbox)
    assert result.decision == GateDecision.BLOCK_QUESTION
    assert m2.id in result.block_message
    assert m1.id not in result.block_message


@pytest.mark.asyncio
async def test_gate_halt_blocks_even_after_info_and_question_acked():
    """HALT must remain blocking even if all other severities are cleared."""
    inbox = OperatorInbox(session_id="s1")
    m_info = await inbox.receive("fyi", MessageSeverity.INFO)
    m_q = await inbox.receive("?", MessageSeverity.QUESTION)
    m_halt = await inbox.receive("STOP", MessageSeverity.HALT)

    await parse_acks_from_dialogue(f"[ACK:{m_info.id}] [ACK:{m_q.id}]", inbox)

    result = await evaluate_gate(inbox)
    assert result.decision == GateDecision.BLOCK_HALT
    assert m_halt.id in result.block_message


# ---------------------------------------------------------------------------
# Block message content — what the agent actually sees
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_block_message_lists_all_unacked_message_ids():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.QUESTION)
    m2 = await inbox.receive("second", MessageSeverity.QUESTION)
    result = await evaluate_gate(inbox)
    assert m1.id in result.block_message
    assert m2.id in result.block_message


@pytest.mark.asyncio
async def test_block_message_instructs_agent_to_use_ack_marker():
    # Use a QUESTION so the gate actually emits a block message —
    # INFO-only no longer blocks.
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("first", MessageSeverity.QUESTION)
    result = await evaluate_gate(inbox)
    # The agent must be told how to unblock itself.
    assert "[ACK:" in result.block_message


@pytest.mark.asyncio
async def test_block_message_mentions_dialogue_channel():
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("first", MessageSeverity.QUESTION)
    result = await evaluate_gate(inbox)
    assert "dialogue" in result.block_message.lower()


@pytest.mark.asyncio
async def test_block_message_for_halt_explains_resume_protocol():
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("STOP", MessageSeverity.HALT)
    result = await evaluate_gate(inbox)
    # HALT must explicitly tell the agent it is waiting for operator
    # input, not just for an ACK — acking a HALT alone does not resume
    # work in this design.
    lower = result.block_message.lower()
    assert "halt" in lower
    assert "operator" in lower or "resume" in lower or "continue" in lower


# ---------------------------------------------------------------------------
# GateDecision enum — sanity
# ---------------------------------------------------------------------------


def test_gate_decision_has_four_values():
    assert {d.name for d in GateDecision} == {
        "ALLOW",
        "BLOCK_INFO",
        "BLOCK_QUESTION",
        "BLOCK_HALT",
    }


def test_gate_decision_allow_is_only_passing_state():
    # Any non-ALLOW decision means the harness must NOT hand control
    # back to the agent for a tool-call turn without first re-prompting
    # with the block message.
    non_allow = [d for d in GateDecision if d != GateDecision.ALLOW]
    assert len(non_allow) == 3


# ---------------------------------------------------------------------------
# min_pending threshold — fix/dialogue-gate-conversational-whitelist
# ---------------------------------------------------------------------------
#
# Operator-tunable backstop. min_pending=1 (default) preserves the original
# single-message-blocks behavior. min_pending=2+ means a lone non-HALT
# message no longer halts work; the banner still shows the message but
# tool calls flow through. HALT is always immediate regardless of threshold.


@pytest.mark.asyncio
async def test_gate_threshold_allows_single_question_when_min_pending_is_two():
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("are you sure?", MessageSeverity.QUESTION)
    result = await evaluate_gate(inbox, min_pending=2)
    assert result.decision == GateDecision.ALLOW
    assert result.block_message == ""


@pytest.mark.asyncio
async def test_gate_info_allows_at_any_threshold():
    # INFO never blocks — confirmed at min_pending=1 (default), 2,
    # and 99. The threshold only gates QUESTION accumulation.
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("fyi 1", MessageSeverity.INFO)
    await inbox.receive("fyi 2", MessageSeverity.INFO)
    await inbox.receive("fyi 3", MessageSeverity.INFO)
    for threshold in (1, 2, 99):
        result = await evaluate_gate(inbox, min_pending=threshold)
        assert result.decision == GateDecision.ALLOW, (
            f"INFO must never block (threshold={threshold})"
        )


@pytest.mark.asyncio
async def test_gate_threshold_blocks_once_two_messages_stack():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.QUESTION)
    m2 = await inbox.receive("second", MessageSeverity.QUESTION)
    result = await evaluate_gate(inbox, min_pending=2)
    assert result.decision == GateDecision.BLOCK_QUESTION
    assert m1.id in result.block_message
    assert m2.id in result.block_message


@pytest.mark.asyncio
async def test_gate_threshold_does_not_relax_halt():
    # HALT must always block, even when min_pending=99. A single HALT is
    # the operator saying "stop now"; threshold semantics never apply.
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("STOP", MessageSeverity.HALT)
    result = await evaluate_gate(inbox, min_pending=99)
    assert result.decision == GateDecision.BLOCK_HALT
    assert m1.id in result.block_message


@pytest.mark.asyncio
async def test_gate_threshold_default_is_one():
    # Backwards-compat: omitting min_pending behaves exactly as before.
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("anything", MessageSeverity.QUESTION)
    default_result = await evaluate_gate(inbox)
    explicit_result = await evaluate_gate(inbox, min_pending=1)
    assert default_result.decision == explicit_result.decision == GateDecision.BLOCK_QUESTION


@pytest.mark.asyncio
async def test_gate_threshold_zero_and_negative_clamp_to_one():
    # Defensive: a misconfigured 0 or negative threshold must NOT silently
    # disable the gate. Clamp to 1 so a single pending message still blocks.
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("anything", MessageSeverity.QUESTION)
    assert (await evaluate_gate(inbox, min_pending=0)).decision == GateDecision.BLOCK_QUESTION
    assert (await evaluate_gate(inbox, min_pending=-5)).decision == GateDecision.BLOCK_QUESTION


# ---------------------------------------------------------------------------
# #2207 Part C — force-pause banner messages are auto-acked by the gate.
# The banner is bridge self-talk; if any code path ever re-ingests it as
# pending, the gate should not loop on it. Defensive guard.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_ignores_force_pause_banner_message():
    """#2207 Part C: banner-marker messages don't block the gate."""
    inbox = OperatorInbox(session_id="s1")
    # The banner format matches DiscordForcePauseAlerter — the marker is the
    # leading [FORCE-PAUSE] token. INFO severity since INFO never blocks
    # anyway, but the filter runs before the severity check too.
    await inbox.receive(
        "[FORCE-PAUSE] 1 operator message(s) pending for >305s without ack",
        MessageSeverity.INFO,
    )

    result = await evaluate_gate(inbox)

    assert result.decision == GateDecision.ALLOW


@pytest.mark.asyncio
async def test_gate_ignores_banner_even_when_classified_as_question():
    """#2207 Part C: defense-in-depth — banner filter runs before severity check.

    If a future bug causes a banner to be ingested with QUESTION severity
    (or HALT), the gate must still not loop on it. The filter is
    content-based, not severity-based.
    """
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive(
        "[FORCE-PAUSE] stale messages pending",
        MessageSeverity.QUESTION,
    )

    result = await evaluate_gate(inbox)

    assert result.decision == GateDecision.ALLOW


@pytest.mark.asyncio
async def test_gate_blocks_when_banner_and_real_question_both_pending():
    """#2207 Part C: banner filter doesn't mask real pending messages.

    If the inbox holds both a banner (auto-acked) AND a real QUESTION,
    the gate must still block on the real question.
    """
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive(
        "[FORCE-PAUSE] banner self-talk",
        MessageSeverity.INFO,
    )
    await inbox.receive("real operator question?", MessageSeverity.QUESTION)

    result = await evaluate_gate(inbox)

    assert result.decision == GateDecision.BLOCK_QUESTION


@pytest.mark.asyncio
async def test_gate_blocks_on_halt_even_with_banner_pending():
    """#2207 Part C: HALT still wins. Banner is auto-acked; HALT blocks."""
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive(
        "[FORCE-PAUSE] banner self-talk",
        MessageSeverity.INFO,
    )
    await inbox.receive("halt", MessageSeverity.HALT)

    result = await evaluate_gate(inbox)

    assert result.decision == GateDecision.BLOCK_HALT
