"""Tests for agent.bridge.operator_inbox.

Sprint 4.9 — Phase 4B (Dialogue-First Communication Architecture).
Sprint 4.11 — Severity classifier with operator override prefixes.

The operator inbox treats messages from the operator as first-class
interrupts. The harness injects pending messages at the top of every
turn context so the agent cannot avoid seeing them. These tests cover
the inbox state machine, banner formatting, turn-context injection,
and (Sprint 4.11) the content-based severity classifier.
"""
from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from bridge.operator_inbox import (
    MessageSeverity,
    OperatorInbox,
    OperatorMessage,
    build_turn_context_with_inbox,
    classify_severity,
    format_interrupt_banner,
)


# ---------------------------------------------------------------------------
# MessageSeverity enum
# ---------------------------------------------------------------------------


def test_message_severity_has_three_levels():
    assert {s.value for s in MessageSeverity} == {"info", "question", "halt"}


def test_message_severity_values_are_lowercase_strings():
    assert MessageSeverity.INFO.value == "info"
    assert MessageSeverity.QUESTION.value == "question"
    assert MessageSeverity.HALT.value == "halt"


# ---------------------------------------------------------------------------
# OperatorMessage dataclass
# ---------------------------------------------------------------------------


def _make_msg(
    *,
    msg_id: str = "msg_1",
    content: str = "hello",
    severity: MessageSeverity = MessageSeverity.INFO,
    received_at: datetime | None = None,
    acknowledged_at: datetime | None = None,
) -> OperatorMessage:
    return OperatorMessage(
        id=msg_id,
        content=content,
        severity=severity,
        received_at=received_at or datetime.now(timezone.utc),
        acknowledged_at=acknowledged_at,
    )


def test_operator_message_is_frozen():
    msg = _make_msg()
    with pytest.raises(FrozenInstanceError):
        msg.content = "mutated"  # type: ignore[misc]


def test_operator_message_is_pending_when_unacked():
    msg = _make_msg()
    assert msg.is_pending is True


def test_operator_message_is_not_pending_when_acked():
    acked_at = datetime.now(timezone.utc)
    msg = _make_msg(acknowledged_at=acked_at)
    assert msg.is_pending is False


def test_operator_message_age_seconds_is_nonnegative():
    msg = _make_msg(received_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    assert msg.age_seconds >= 5.0
    assert msg.age_seconds < 60.0  # sanity bound


# ---------------------------------------------------------------------------
# OperatorInbox — receive / pending / acknowledge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbox_starts_empty():
    inbox = OperatorInbox(session_id="s1")
    assert await inbox.pending() == []


@pytest.mark.asyncio
async def test_inbox_receive_returns_the_stored_message():
    inbox = OperatorInbox(session_id="s1")
    msg = await inbox.receive("what's the status?", MessageSeverity.QUESTION)
    assert msg.content == "what's the status?"
    assert msg.severity == MessageSeverity.QUESTION
    assert msg.is_pending is True
    assert msg.id.startswith("msg_")
    assert msg.received_at.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_inbox_pending_lists_unacked_messages_in_receive_order():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    m2 = await inbox.receive("second", MessageSeverity.QUESTION)
    pending = await inbox.pending()
    assert [m.id for m in pending] == [m1.id, m2.id]


@pytest.mark.asyncio
async def test_inbox_acknowledge_removes_from_pending():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    await inbox.acknowledge(m1.id)
    assert await inbox.pending() == []


@pytest.mark.asyncio
async def test_inbox_acknowledge_only_affects_targeted_message():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    m2 = await inbox.receive("second", MessageSeverity.QUESTION)
    await inbox.acknowledge(m1.id)
    pending = await inbox.pending()
    assert [m.id for m in pending] == [m2.id]


@pytest.mark.asyncio
async def test_inbox_acknowledge_unknown_id_is_silent_no_op():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    # The spec says acknowledging an unknown id should silently ignore
    # rather than raise, so callers (Discord bot, command dispatch) don't
    # need to wrap the call in try/except for a benign race.
    await inbox.acknowledge("msg_does_not_exist")
    pending = await inbox.pending()
    assert [m.id for m in pending] == [m1.id]


@pytest.mark.asyncio
async def test_inbox_acknowledge_already_acked_is_silent_no_op():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    await inbox.acknowledge(m1.id)
    # Second ack must not raise and must not resurrect the message
    await inbox.acknowledge(m1.id)
    assert await inbox.pending() == []


@pytest.mark.asyncio
async def test_inbox_acknowledge_records_acknowledged_at():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    await inbox.acknowledge(m1.id)
    # All stored messages (including acked ones) should be queryable to
    # see the full history; the ack timestamp should be set.
    all_msgs = await inbox.all_messages()
    assert len(all_msgs) == 1
    assert all_msgs[0].acknowledged_at is not None
    assert all_msgs[0].acknowledged_at.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_inbox_receive_generates_unique_ids():
    inbox = OperatorInbox(session_id="s1")
    ids = set()
    for i in range(10):
        msg = await inbox.receive(f"msg-{i}", MessageSeverity.INFO)
        ids.add(msg.id)
    assert len(ids) == 10


@pytest.mark.asyncio
async def test_inbox_concurrent_receives_are_serialized():
    """Two receives racing should both land in the inbox without collision."""
    inbox = OperatorInbox(session_id="s1")

    async def send(content: str) -> OperatorMessage:
        return await inbox.receive(content, MessageSeverity.INFO)

    results = await asyncio.gather(*[send(f"concurrent-{i}") for i in range(20)])
    assert len({m.id for m in results}) == 20
    pending = await inbox.pending()
    assert len(pending) == 20


@pytest.mark.asyncio
async def test_inbox_session_id_is_preserved():
    inbox = OperatorInbox(session_id="session-42")
    assert inbox.session_id == "session-42"


@pytest.mark.asyncio
async def test_inbox_concurrent_acknowledge_is_idempotent():
    """Two tasks racing to acknowledge the same id must both succeed silently."""
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("racy", MessageSeverity.QUESTION)

    results = await asyncio.gather(
        inbox.acknowledge(m1.id),
        inbox.acknowledge(m1.id),
        inbox.acknowledge(m1.id),
        return_exceptions=True,
    )
    # None of the three should have raised.
    assert all(r is None for r in results)
    assert await inbox.pending() == []


@pytest.mark.asyncio
async def test_inbox_double_ack_preserves_first_timestamp():
    """Double-ack must not overwrite the first acknowledged_at value.

    This is a load-bearing audit invariant: the first ack is when the
    agent genuinely saw the message. A later no-op ack must not rewrite
    that timestamp — otherwise the audit log lies about when the agent
    responded.
    """
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("audit me", MessageSeverity.INFO)
    await inbox.acknowledge(m1.id)

    first_ack_ts = (await inbox.all_messages())[0].acknowledged_at
    assert first_ack_ts is not None

    # Wait long enough that any accidental overwrite would produce a
    # measurably different timestamp.
    await asyncio.sleep(0.01)
    await inbox.acknowledge(m1.id)

    second_ack_ts = (await inbox.all_messages())[0].acknowledged_at
    assert second_ack_ts == first_ack_ts


@pytest.mark.asyncio
async def test_all_messages_returns_interleaved_history_in_arrival_order():
    """all_messages() must preserve arrival order even after interleaved ops."""
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("first", MessageSeverity.INFO)
    m2 = await inbox.receive("second", MessageSeverity.QUESTION)
    await inbox.acknowledge(m1.id)
    m3 = await inbox.receive("third", MessageSeverity.HALT)
    await inbox.acknowledge(m2.id)
    m4 = await inbox.receive("fourth", MessageSeverity.INFO)

    history = await inbox.all_messages()
    assert [m.id for m in history] == [m1.id, m2.id, m3.id, m4.id]
    # Acked and pending status should reflect the ops, not the order.
    assert history[0].acknowledged_at is not None  # m1 acked
    assert history[1].acknowledged_at is not None  # m2 acked
    assert history[2].acknowledged_at is None      # m3 pending
    assert history[3].acknowledged_at is None      # m4 pending


# ---------------------------------------------------------------------------
# format_interrupt_banner — formatting rules
# ---------------------------------------------------------------------------


def _fixed_msg(
    msg_id: str,
    content: str,
    severity: MessageSeverity,
    age_seconds: int = 10,
) -> OperatorMessage:
    received = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return OperatorMessage(
        id=msg_id,
        content=content,
        severity=severity,
        received_at=received,
    )


def test_format_banner_empty_returns_empty_string():
    # An empty list should not produce a banner — callers rely on this
    # to decide whether to prepend anything at all.
    assert format_interrupt_banner([]) == ""


def test_format_banner_single_info_message_includes_core_fields():
    msg = _fixed_msg("msg_100", "status check", MessageSeverity.INFO)
    banner = format_interrupt_banner([msg])
    assert "OPERATOR MESSAGE" in banner
    assert "[INFO]" in banner
    assert "msg_100" in banner
    assert "status check" in banner


def test_format_banner_single_question_message():
    msg = _fixed_msg("msg_q1", "are you sure?", MessageSeverity.QUESTION)
    banner = format_interrupt_banner([msg])
    assert "[QUESTION]" in banner
    assert "are you sure?" in banner


def test_format_banner_single_halt_message():
    msg = _fixed_msg("msg_h1", "STOP NOW", MessageSeverity.HALT)
    banner = format_interrupt_banner([msg])
    assert "[HALT]" in banner
    assert "STOP NOW" in banner


def test_format_banner_with_multiple_messages_includes_all():
    msgs = [
        _fixed_msg("msg_1", "first", MessageSeverity.INFO),
        _fixed_msg("msg_2", "second", MessageSeverity.QUESTION),
        _fixed_msg("msg_3", "third", MessageSeverity.HALT),
    ]
    banner = format_interrupt_banner(msgs)
    for mid, content in [("msg_1", "first"), ("msg_2", "second"), ("msg_3", "third")]:
        assert mid in banner
        assert content in banner
    assert "[INFO]" in banner
    assert "[QUESTION]" in banner
    assert "[HALT]" in banner


def test_format_banner_includes_age_in_seconds():
    # Use a large age so ±1s drift between dataclass construction and
    # banner formatting cannot cross a digit boundary on a slow CI box.
    msg = _fixed_msg("msg_1", "test", MessageSeverity.INFO, age_seconds=1000)
    banner = format_interrupt_banner([msg])
    # The age in the banner should be within 2 seconds of 1000.
    assert any(str(n) in banner for n in (998, 999, 1000, 1001, 1002))


def test_format_banner_includes_acknowledgment_instructions():
    msg = _fixed_msg("msg_1", "test", MessageSeverity.INFO)
    banner = format_interrupt_banner([msg])
    # The banner must instruct the agent on how to acknowledge — this is
    # the contract with Sprint 4.10's tool-call gate.
    assert "[ACK:" in banner
    assert "msg_id" in banner.lower() or "msg_1" in banner


def test_format_banner_mentions_dialogue_channel():
    msg = _fixed_msg("msg_1", "test", MessageSeverity.INFO)
    banner = format_interrupt_banner([msg])
    # The banner must steer the agent to respond in dialogue rather than
    # absorb the message into its work loop silently.
    assert "dialogue" in banner.lower()


def test_format_banner_explains_each_severity_behavior():
    """The banner should tell the agent how to handle each severity level."""
    msgs = [
        _fixed_msg("msg_1", "info msg", MessageSeverity.INFO),
    ]
    banner = format_interrupt_banner(msgs)
    lower = banner.lower()
    # All three severity behaviors must be documented in the banner so the
    # agent knows what to do regardless of which severity it receives.
    assert "halt" in lower
    assert "question" in lower
    assert "info" in lower


# ---------------------------------------------------------------------------
# build_turn_context_with_inbox — context injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_turn_context_with_empty_inbox_returns_base_unchanged():
    inbox = OperatorInbox(session_id="s1")
    base = "user asked: what time is it?"
    result = await build_turn_context_with_inbox(inbox, base)
    assert result == base


@pytest.mark.asyncio
async def test_build_turn_context_prepends_banner_when_pending():
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("important", MessageSeverity.QUESTION)
    base = "BASE_CONTEXT_SENTINEL"
    result = await build_turn_context_with_inbox(inbox, base)
    assert base in result
    # Banner must be AT THE TOP of the context — before the base.
    banner_index = result.find("OPERATOR MESSAGE")
    base_index = result.find(base)
    assert banner_index != -1
    assert banner_index < base_index


@pytest.mark.asyncio
async def test_build_turn_context_includes_all_pending_messages():
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("first", MessageSeverity.INFO)
    await inbox.receive("second", MessageSeverity.QUESTION)
    result = await build_turn_context_with_inbox(inbox, "base")
    assert "first" in result
    assert "second" in result


@pytest.mark.asyncio
async def test_build_turn_context_excludes_acked_messages():
    inbox = OperatorInbox(session_id="s1")
    m1 = await inbox.receive("acked", MessageSeverity.INFO)
    await inbox.receive("pending", MessageSeverity.INFO)
    await inbox.acknowledge(m1.id)
    result = await build_turn_context_with_inbox(inbox, "base")
    # Acked message should not leak into the banner
    assert "acked" not in result
    assert "pending" in result


@pytest.mark.asyncio
async def test_build_turn_context_separator_between_banner_and_base():
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("test", MessageSeverity.INFO)
    result = await build_turn_context_with_inbox(inbox, "base")
    # The banner and the base context must be visually separated so the
    # agent can't misread the banner as part of its task context.
    assert "---" in result


# ---------------------------------------------------------------------------
# Severity routing — explicit test for each severity end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "severity,tag",
    [
        (MessageSeverity.INFO, "[INFO]"),
        (MessageSeverity.QUESTION, "[QUESTION]"),
        (MessageSeverity.HALT, "[HALT]"),
    ],
)
async def test_receive_then_format_carries_severity_through(severity, tag):
    inbox = OperatorInbox(session_id="s1")
    await inbox.receive("content", severity)
    pending = await inbox.pending()
    banner = format_interrupt_banner(pending)
    assert tag in banner


# ===========================================================================
# Sprint 4.11 — classify_severity + receive_classified
# ===========================================================================


# ---------------------------------------------------------------------------
# Default severity — QUESTION
# ---------------------------------------------------------------------------


def test_classify_default_is_question():
    # The safest default: force engagement when we don't know better.
    # Post-#2207 Part B, the default-QUESTION example needs to land on
    # either an explicit "?" or an imperative verb (otherwise short
    # non-imperative messages get classified INFO).
    assert classify_severity("can you confirm the deploy?") == MessageSeverity.QUESTION


def test_classify_empty_string_is_question():
    assert classify_severity("") == MessageSeverity.QUESTION


def test_classify_whitespace_only_is_question():
    assert classify_severity("   \n\t  ") == MessageSeverity.QUESTION


def test_classify_plain_sentence_is_question():
    assert classify_severity("what's the status of the pipeline?") == MessageSeverity.QUESTION


# ---------------------------------------------------------------------------
# HALT triggers — exact match or word-bounded prefix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "halt",
        "stop",
        "pause",
        "cease",
        "/halt",
        "!halt",
    ],
)
def test_classify_halt_triggers_exact_match(text):
    assert classify_severity(text) == MessageSeverity.HALT


@pytest.mark.parametrize(
    "text",
    [
        "halt the work",
        "stop what you're doing",
        "pause for a moment",
        "/halt now please",
        "!halt immediately",
    ],
)
def test_classify_halt_triggers_word_bounded_prefix(text):
    assert classify_severity(text) == MessageSeverity.HALT


def test_classify_halt_is_case_insensitive():
    assert classify_severity("HALT") == MessageSeverity.HALT
    assert classify_severity("Stop") == MessageSeverity.HALT
    assert classify_severity("PAUSE now") == MessageSeverity.HALT


def test_classify_halt_tolerates_leading_whitespace():
    assert classify_severity("   halt") == MessageSeverity.HALT
    assert classify_severity("\n\tstop") == MessageSeverity.HALT


def test_classify_halt_does_NOT_match_substring():
    """Regression guard: 'halting' must not trigger HALT.

    The classifier uses whole-word matching for the bare triggers so
    that legitimate messages like 'halting the old pipeline is tricky'
    don't get misclassified as a halt command.
    """
    assert classify_severity("halting the old pipeline is tricky") != MessageSeverity.HALT
    assert classify_severity("stopgap measure needed") != MessageSeverity.HALT
    assert classify_severity("pausescreen.png is missing") != MessageSeverity.HALT
    assert classify_severity("ceasefire negotiations") != MessageSeverity.HALT


def test_classify_halt_triggers_after_leading_text():
    """Regression guard (Sprint 4.11 code review): HALT must be detected
    even when it's not the first token. Discord and terminal users
    routinely send messages like 'please halt now' or 'hey team, stop'.
    """
    assert classify_severity("please halt the pipeline") == MessageSeverity.HALT
    assert classify_severity("hey team, stop what you're doing") == MessageSeverity.HALT
    assert classify_severity("I need you to cease immediately") == MessageSeverity.HALT
    assert classify_severity("can you pause for a sec") == MessageSeverity.HALT


def test_classify_halt_triggers_in_multiline_messages():
    """Regression guard (Sprint 4.11 code review): HALT triggers on any
    line of a multi-line message. The word-token scan must cross line
    boundaries so operators who type 'ok<newline>stop' aren't silently
    misclassified as QUESTION.
    """
    assert classify_severity("ok\nstop") == MessageSeverity.HALT
    assert classify_severity("line1\nline2\ncease") == MessageSeverity.HALT
    assert classify_severity("Hey team\nhalt\nnow") == MessageSeverity.HALT


def test_classify_multiline_with_no_halt_word_is_still_question():
    """Negative regression: multi-line messages without a HALT trigger
    still classify as QUESTION when they're substantive (post-#2207
    Part B: use length > 80 to land on the QUESTION fallback).
    """
    long_multiline = (
        "line one is a substantive thought\n"
        "line two continues the substantive thought\n"
        "line three wraps up the substantive thought"
    )
    assert len(long_multiline) > 80
    assert classify_severity(long_multiline) == MessageSeverity.QUESTION


def test_classify_halt_bang_prefix_does_not_need_word_boundary():
    """`!halt` and `/halt` are unambiguous — they can be followed by
    anything and still trigger HALT, because no English word starts
    with `!halt` or `/halt`.
    """
    assert classify_severity("!haltdontwait") == MessageSeverity.HALT
    assert classify_severity("/haltASAP") == MessageSeverity.HALT


# ---------------------------------------------------------------------------
# INFO prefixes — explicit opt-in only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "!info the build is green",
        "(info) deploy finished",
        "fyi: build is green",
        "fyi the build is green",
    ],
)
def test_classify_info_prefixes(text):
    assert classify_severity(text) == MessageSeverity.INFO


def test_classify_info_is_case_insensitive():
    assert classify_severity("!INFO heads up") == MessageSeverity.INFO
    assert classify_severity("FYI: heads up") == MessageSeverity.INFO
    assert classify_severity("(Info) heads up") == MessageSeverity.INFO


def test_classify_info_without_prefix_is_question():
    # 'info' on its own is not enough — must be a recognized prefix.
    # Post-#2207 Part B: use "?" to land on QUESTION fallback so the
    # short-non-imperative heuristic doesn't intercept.
    assert classify_severity("info about the build?") == MessageSeverity.QUESTION


def test_classify_info_does_not_match_substring():
    """'information' must not trigger INFO. (post-#2207: ? forces QUESTION)"""
    assert classify_severity("information about the build?") == MessageSeverity.QUESTION


# ---------------------------------------------------------------------------
# QUESTION explicit prefixes — redundant but supported per spec
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "!q are you sure?",
        "(q) why did that happen?",
    ],
)
def test_classify_question_explicit_prefixes(text):
    assert classify_severity(text) == MessageSeverity.QUESTION


# ---------------------------------------------------------------------------
# Severity precedence in the classifier — HALT wins over INFO prefix
# ---------------------------------------------------------------------------


def test_classify_halt_trigger_beats_info_prefix_if_both_present():
    """If the operator says 'halt fyi:', HALT wins — stopping is safer."""
    assert classify_severity("halt fyi: stop the loop") == MessageSeverity.HALT


# ---------------------------------------------------------------------------
# receive_classified — integration with the inbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receive_classified_assigns_question_by_default():
    inbox = OperatorInbox(session_id="s1")
    msg = await inbox.receive_classified("hello, are you there?")
    assert msg.severity == MessageSeverity.QUESTION


@pytest.mark.asyncio
async def test_receive_classified_detects_halt():
    inbox = OperatorInbox(session_id="s1")
    msg = await inbox.receive_classified("stop the pipeline now")
    assert msg.severity == MessageSeverity.HALT


@pytest.mark.asyncio
async def test_receive_classified_detects_info():
    inbox = OperatorInbox(session_id="s1")
    msg = await inbox.receive_classified("fyi: build is green")
    assert msg.severity == MessageSeverity.INFO


@pytest.mark.asyncio
async def test_receive_classified_stores_original_content_not_stripped_prefix():
    """The stored content must be the full original text so the agent
    sees exactly what the operator typed, including the prefix.
    """
    inbox = OperatorInbox(session_id="s1")
    msg = await inbox.receive_classified("fyi: build is green")
    assert msg.content == "fyi: build is green"


@pytest.mark.asyncio
async def test_receive_classified_goes_through_normal_inbox_state():
    """receive_classified messages should be pending like any other."""
    inbox = OperatorInbox(session_id="s1")
    msg = await inbox.receive_classified("stop")
    pending = await inbox.pending()
    assert [m.id for m in pending] == [msg.id]
    assert pending[0].severity == MessageSeverity.HALT


# ---------------------------------------------------------------------------
# E3.3 — redirect + confirm integration via OperatorInbox.receive()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redirect_then_confirm_promotes_focus(tmp_path, monkeypatch):
    """Full E3.3 round-trip: redirect message stages, confirm promotes."""
    import bridge.orientation as ori_mod
    orientation_path = tmp_path / "orientation.json"
    from bridge.orientation import Orientation, update_on_operator_redirect, promote_pending_focus_if_confirmed

    Orientation(current_focus="original focus").write(orientation_path)

    # Patch the trigger functions to write to our tmp path
    monkeypatch.setattr(
        ori_mod, "update_on_operator_redirect",
        lambda content, path=orientation_path: ori_mod.update_on_operator_redirect.__wrapped__(content, orientation_path)
        if hasattr(ori_mod.update_on_operator_redirect, "__wrapped__")
        else _patched_update_on_redirect(content, orientation_path),
    )

    # Simpler approach: patch _orientation_hooks in operator_inbox directly
    redirected: list[str] = []
    confirmed: list[str] = []

    def fake_hooks(content: str) -> None:
        from bridge.orientation import is_redirect_message, is_confirm_message
        if is_redirect_message(content):
            redirected.append(content)
            update_on_operator_redirect(content, orientation_path)
        elif is_confirm_message(content):
            confirmed.append(content)
            promote_pending_focus_if_confirmed(content, orientation_path)

    import bridge.operator_inbox as inbox_mod
    monkeypatch.setattr(inbox_mod, "_orientation_hooks", fake_hooks)

    inbox = OperatorInbox(session_id="e33-test")

    # Step 1: redirect message stages a pending change
    await inbox.receive("redirect: focus on E4 templates", MessageSeverity.INFO)
    loaded = Orientation.load(orientation_path)
    assert loaded.pending_focus_change == "focus on E4 templates"
    assert loaded.current_focus == "original focus"

    # Step 2: confirm message promotes it
    await inbox.receive("yes", MessageSeverity.INFO)
    promoted = Orientation.load(orientation_path)
    assert promoted.current_focus == "focus on E4 templates"
    assert promoted.pending_focus_change is None


@pytest.mark.asyncio
async def test_non_redirect_message_does_not_stage(tmp_path, monkeypatch):
    """Ordinary messages must not touch the orientation file."""
    import bridge.operator_inbox as inbox_mod
    orientation_path = tmp_path / "orientation.json"
    from bridge.orientation import (
        Orientation,
        is_redirect_message,
        is_confirm_message,
        update_on_operator_redirect,
        promote_pending_focus_if_confirmed,
    )

    Orientation(current_focus="stays").write(orientation_path)

    def fake_hooks(content: str) -> None:
        if is_redirect_message(content):
            update_on_operator_redirect(content, orientation_path)
        elif is_confirm_message(content):
            promote_pending_focus_if_confirmed(content, orientation_path)

    monkeypatch.setattr(inbox_mod, "_orientation_hooks", fake_hooks)

    inbox = OperatorInbox(session_id="e33-neg")
    await inbox.receive("just a normal message", MessageSeverity.INFO)
    loaded = Orientation.load(orientation_path)
    assert loaded.pending_focus_change is None
    assert loaded.current_focus == "stays"


# ===========================================================================
# Conversational-opener whitelist — fix/dialogue-gate-conversational-whitelist
# ===========================================================================
#
# Operator sending "hi" five times stacked five BLOCK_QUESTION gate fires
# in production (2026-05-10). Whole-message conversational openers now map
# to INFO so they emit the weakest gate decision instead of QUESTION.


@pytest.mark.parametrize(
    "text",
    [
        "hi",
        "hello",
        "hey",
        "yo",
        "ok",
        "okay",
        "thanks",
        "thank you",
        "ty",
        "thx",
        "ack",
        "noted",
        "lgtm",
        "gotcha",
        "got it",
        "sounds good",
    ],
)
def test_classify_conversational_openers_are_info(text):
    assert classify_severity(text) == MessageSeverity.INFO


# Issue #1557 — Plan W verbal-yes extension. These are the eleven tokens
# added to the conversational-opener whitelist on top of the PR #1534
# baseline. All classify as INFO so a bare verbal-yes from the operator
# does not stack a BLOCK_QUESTION gate fire. Post-PR #1617, INFO never
# blocks tool calls — these surface in the banner without gating work.
@pytest.mark.parametrize(
    "text",
    [
        "sure",
        "yes",
        "no",
        "yep",
        "nope",
        "great",
        "perfect",
        "continue",
        "go ahead",
        "proceed",
        "acknowledged",
    ],
)
def test_classify_verbal_yes_extension_are_info(text):
    assert classify_severity(text) == MessageSeverity.INFO


def test_classify_verbal_yes_extension_only_match_whole_message():
    # Multi-word messages built around the new tokens still fall through to
    # QUESTION when they carry explicit intent — verified via "?" or
    # imperative-verb prefix (post-#2207 Part B; short bare verbal-yes
    # phrases now classify INFO via the short-non-imperative heuristic,
    # which is desirable behaviour per the issue).
    assert classify_severity("proceed when ready?") == MessageSeverity.QUESTION
    assert classify_severity("yes but please check the build first") == MessageSeverity.INFO
    assert classify_severity("continue with caution") == MessageSeverity.INFO


def test_classify_verbal_yes_extension_halt_word_still_wins():
    # Regression guard: the HALT word-token scan runs before the
    # conversational-opener check, so a message like "yes, halt" still
    # classifies as HALT — verbal-yes does not shield a HALT trigger.
    assert classify_severity("yes, halt") == MessageSeverity.HALT
    assert classify_severity("proceed but stop after deploy") == MessageSeverity.HALT


@pytest.mark.parametrize(
    "text",
    [
        "Hi",
        "HELLO",
        "  hi  ",
        "Thanks",
        "OK",
    ],
)
def test_classify_conversational_openers_case_and_whitespace_insensitive(text):
    assert classify_severity(text) == MessageSeverity.INFO


def test_classify_conversational_openers_only_match_whole_message():
    # "hi there" is not a whitelisted opener — short and non-imperative, so
    # the #2207 Part B heuristic classifies it INFO. Real conversational
    # questions that include "?" still force engagement.
    assert classify_severity("hi there") == MessageSeverity.INFO
    assert classify_severity("hi there?") == MessageSeverity.QUESTION


def test_classify_halt_still_wins_over_conversational_opener():
    # Regression guard: the HALT word-token scan runs BEFORE the
    # conversational-opener check, so "ok\nstop" still classifies as HALT
    # even though "ok" is whitelisted on its own.
    assert classify_severity("ok\nstop") == MessageSeverity.HALT
    assert classify_severity("thanks, please halt") == MessageSeverity.HALT


# ---------------------------------------------------------------------------
# #2207 Part B — short non-imperative messages classify as INFO.
# Pre-#2207 these fell through to QUESTION and could stack BLOCK_QUESTION
# gate fires once 2+ accumulated. Post-fix they classify INFO and never block.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I find that Anthropic has a strong ecosystem",
        "not sleeping quite yet",
        "interesting",
        "thinking about that",
        "kind of a weird situation",
        "ok so what next",  # was QUESTION pre-#2207
        "hello, can you check the build",  # short greeting + ask without "?"
    ],
)
def test_classify_short_non_imperative_is_info(text):
    """#2207 Part B: short messages without ? or imperative verb → INFO."""
    assert classify_severity(text) == MessageSeverity.INFO


@pytest.mark.parametrize(
    "text",
    [
        "fix the bug",
        "build the thing",
        "run the tests",
        "deploy to staging",
        "update the docs",
        "refactor the module",
        "implement the new endpoint",
    ],
)
def test_classify_short_imperative_is_question(text):
    """#2207 Part B: short imperative directives still classify QUESTION."""
    assert classify_severity(text) == MessageSeverity.QUESTION


def test_classify_question_mark_short_message_is_question():
    """#2207 Part B: explicit "?" forces QUESTION regardless of length."""
    assert classify_severity("what's the status?") == MessageSeverity.QUESTION
    assert classify_severity("ready?") == MessageSeverity.QUESTION


def test_classify_long_message_falls_through_to_question():
    """#2207 Part B: messages over 80 chars fall through to QUESTION default.

    Long messages are more likely to be substantive requests; the short-
    message heuristic doesn't apply.
    """
    long_text = (
        "I think we should consider whether the approach taken in the "
        "second pass is actually correct given the constraints we have"
    )
    assert len(long_text) > 80
    assert classify_severity(long_text) == MessageSeverity.QUESTION
