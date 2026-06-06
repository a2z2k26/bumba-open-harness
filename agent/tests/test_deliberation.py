"""Tests for bridge.deliberation — Sprints 04.01 + 04.02.

Concept-only port (llm-council has no license; no source copied). These tests
cover:

* Sprint 04.01 — `assign_anonymous_labels`, `anonymize_responses`,
  `deanonymize`, and the flag-aware `format_board_memo` rendering.
* Sprint 04.02 — the strict ``FINAL RANKING:`` parse contract
  (`parse_final_ranking`, `FinalRanking`, `RankingParseError`).
"""
from __future__ import annotations

import pytest

from bridge.peer_ranking import (
    BoardMemberResponse,
    DeliberationRound,
    DeliberationState,
    FinalRanking,
    RankingParseError,
    _label_for_index,
    anonymize_responses,
    assign_anonymous_labels,
    deanonymize,
    format_board_memo,
    parse_final_ranking,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _resp(name: str, stance: str = "SUPPORT", reasoning: str = "ok") -> BoardMemberResponse:
    return BoardMemberResponse(
        member_name=name,
        round_number=1,
        stance=stance,
        reasoning=reasoning,
        key_concern="",
        recommended_action="",
        timestamp="2026-04-29T00:00:00+00:00",
    )


def _state_with(responses: tuple[BoardMemberResponse, ...]) -> DeliberationState:
    rnd = DeliberationRound(
        round_number=1,
        question="Should we ship?",
        responses=responses,
        synthesis="",
        resolved=False,
    )
    return DeliberationState(
        session_id="sess-fixed-001",
        topic="Ship decision",
        framing="",
        rounds=(rnd,),
        decision="",
        status="open",
        created_at="2026-04-29T00:00:00+00:00",
    )


# ── Label encoding ────────────────────────────────────────────────────────────


class TestLabelForIndex:
    def test_first_26_are_single_letters(self):
        assert _label_for_index(0) == "A"
        assert _label_for_index(1) == "B"
        assert _label_for_index(25) == "Z"

    def test_wraps_to_double_letters(self):
        assert _label_for_index(26) == "AA"
        assert _label_for_index(27) == "AB"

    def test_negative_index_rejected(self):
        with pytest.raises(ValueError):
            _label_for_index(-1)


# ── assign_anonymous_labels ───────────────────────────────────────────────────


class TestAssignAnonymousLabels:
    def test_deterministic_for_same_seed(self):
        responses = (_resp("Alice"), _resp("Bob"), _resp("Carol"))
        m1 = assign_anonymous_labels(responses, seed=42)
        m2 = assign_anonymous_labels(responses, seed=42)
        assert m1 == m2

    def test_input_order_does_not_change_mapping(self):
        forward = (_resp("Alice"), _resp("Bob"), _resp("Carol"))
        reversed_in = (_resp("Carol"), _resp("Bob"), _resp("Alice"))
        assert assign_anonymous_labels(forward, seed=7) == assign_anonymous_labels(
            reversed_in, seed=7
        )

    def test_different_seeds_yield_different_mappings(self):
        # Three members and a hash-style shuffle: at least one of these seeds
        # must produce a different mapping than seed=1. Sample several to
        # avoid relying on a single implementation detail.
        responses = (_resp("Alice"), _resp("Bob"), _resp("Carol"))
        base = assign_anonymous_labels(responses, seed=1)
        differing = [
            assign_anonymous_labels(responses, seed=s)
            for s in (2, 3, 4, 5, 6, 7, 8, 9, 10)
        ]
        assert any(m != base for m in differing), (
            "expected at least one seed in 2..10 to produce a distinct mapping"
        )

    def test_labels_are_unique_and_complete(self):
        responses = tuple(_resp(n) for n in ("M1", "M2", "M3", "M4", "M5"))
        mapping = assign_anonymous_labels(responses, seed=12345)
        assert set(mapping.keys()) == {"M1", "M2", "M3", "M4", "M5"}
        assert set(mapping.values()) == {"A", "B", "C", "D", "E"}

    def test_two_member_board(self):
        responses = (_resp("X"), _resp("Y"))
        mapping = assign_anonymous_labels(responses, seed=1)
        assert set(mapping.values()) == {"A", "B"}

    def test_duplicate_member_collapses(self):
        # Same member showing up twice in one round is one identity.
        responses = (_resp("Solo"), _resp("Solo"))
        mapping = assign_anonymous_labels(responses, seed=1)
        assert mapping == {"Solo": "A"}


# ── anonymize_responses + deanonymize ─────────────────────────────────────────


class TestAnonymizeResponses:
    def test_responses_get_label_in_member_name(self):
        responses = (_resp("Alice"), _resp("Bob"))
        anonymized, label_to_name = anonymize_responses(responses, seed=99)
        # Every output member_name is a label (A, B, …), not a real identity.
        anon_names = {r.member_name for r in anonymized}
        assert anon_names <= {"A", "B"}
        assert anon_names.isdisjoint({"Alice", "Bob"})
        # Mapping inverts cleanly.
        assert set(label_to_name.values()) == {"Alice", "Bob"}

    def test_does_not_mutate_input(self):
        responses = (_resp("Alice"), _resp("Bob"))
        snapshot = tuple((r.member_name, r.stance, r.reasoning) for r in responses)
        _ = anonymize_responses(responses, seed=99)
        after = tuple((r.member_name, r.stance, r.reasoning) for r in responses)
        assert snapshot == after

    def test_round_trip_via_deanonymize(self):
        responses = (_resp("Alice"), _resp("Bob"), _resp("Carol"))
        anonymized, mapping = anonymize_responses(responses, seed=777)
        # Pretend a peer-ranker returned the labels in some order.
        ranking_labels = [r.member_name for r in anonymized]
        identity_ranking = deanonymize(ranking_labels, mapping)
        assert sorted(identity_ranking) == sorted(["Alice", "Bob", "Carol"])

    def test_deanonymize_passes_through_unknown_labels(self):
        # Defensive: a malformed ranker output cannot silently drop members.
        out = deanonymize(["A", "ZZZ"], {"A": "Alice"})
        assert out == ["Alice", "ZZZ"]

    def test_preserves_non_identity_fields(self):
        responses = (
            BoardMemberResponse(
                member_name="Alice",
                round_number=2,
                stance="OPPOSE",
                reasoning="risk too high",
                key_concern="data loss",
                recommended_action="abort",
            ),
        )
        anonymized, mapping = anonymize_responses(responses, seed=1)
        a = anonymized[0]
        assert a.member_name == "A"
        assert a.round_number == 2
        assert a.stance == "OPPOSE"
        assert a.reasoning == "risk too high"
        assert a.key_concern == "data loss"
        assert a.recommended_action == "abort"
        assert mapping == {"A": "Alice"}


# ── format_board_memo flag wiring ─────────────────────────────────────────────


class TestFormatBoardMemoFlag:
    def test_flag_off_default_unchanged(self):
        """anonymize=False (default) reproduces the existing memo verbatim."""
        responses = (_resp("Alice", "SUPPORT", "ok by me"), _resp("Bob", "OPPOSE", "no"))
        state = _state_with(responses)
        memo = format_board_memo(state)
        assert "Alice" in memo
        assert "Bob" in memo
        # No raw labels leaked into the default memo.
        assert "[SUPPORT]" in memo
        # Default path does not contain a label-only stance line.
        assert "**A** [SUPPORT]" not in memo
        assert "**B** [OPPOSE]" not in memo

    def test_flag_on_replaces_member_names_with_labels(self):
        responses = (_resp("Alice", "SUPPORT", "ok"), _resp("Bob", "OPPOSE", "no"))
        state = _state_with(responses)
        memo = format_board_memo(state, anonymize=True, seed=42)
        assert "Alice" not in memo
        assert "Bob" not in memo
        # Both labels A and B are present.
        assert "**A**" in memo
        assert "**B**" in memo

    def test_flag_on_is_deterministic_with_seed(self):
        responses = (_resp("Alice", "SUPPORT", "ok"), _resp("Bob", "OPPOSE", "no"))
        state = _state_with(responses)
        m1 = format_board_memo(state, anonymize=True, seed=42)
        m2 = format_board_memo(state, anonymize=True, seed=42)
        assert m1 == m2

    def test_flag_on_with_default_seed_is_session_stable(self):
        """Same session_id → same anonymized memo across calls (no explicit seed)."""
        responses = (_resp("Alice", "SUPPORT", "ok"), _resp("Bob", "OPPOSE", "no"))
        state = _state_with(responses)
        m1 = format_board_memo(state, anonymize=True)
        m2 = format_board_memo(state, anonymize=True)
        assert m1 == m2

    def test_flag_on_anonymizes_tensions_and_actions(self):
        a = BoardMemberResponse(
            member_name="Alice",
            round_number=1,
            stance="OPPOSE",
            reasoning="risk",
            key_concern="data loss",
            recommended_action="hold",
        )
        b = BoardMemberResponse(
            member_name="Bob",
            round_number=1,
            stance="SUPPORT",
            reasoning="ok",
            key_concern="",
            recommended_action="ship",
        )
        state = _state_with((a, b))
        memo = format_board_memo(state, anonymize=True, seed=11)
        # Identity strings nowhere in the memo.
        assert "Alice" not in memo
        assert "Bob" not in memo
        # Tensions section still labels concerns by anonymous tag.
        assert "data loss" in memo
        # Next-Actions section still references the action; identity is masked.
        assert "ship" in memo
        assert "hold" in memo


# ── BridgeConfig flag ─────────────────────────────────────────────────────────


class TestBoardV2FeatureFlag:
    def test_flag_default_off_on_bridgeconfig(self):
        from bridge.config import BridgeConfig

        cfg = BridgeConfig()
        assert hasattr(cfg, "board_v2_enabled")
        assert cfg.board_v2_enabled is False

    def test_flag_toml_mapping_present(self):
        from bridge.config import _TOML_MAP

        assert _TOML_MAP["board.v2_enabled"] == "board_v2_enabled"


# ── parse_final_ranking (Sprint 04.02) ────────────────────────────────────────


class TestParseFinalRankingHappyPath:
    """Happy paths: each accepted format returns a FinalRanking with the
    correct ordered labels."""

    def test_comma_separated(self):
        text = "Some reasoning here.\nFINAL RANKING: A, B, C\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B", "C")

    def test_newline_separated(self):
        text = "Reasoning.\nFINAL RANKING:\nA\nB\nC\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B", "C")

    def test_numbered_list(self):
        text = "Reasoning.\nFINAL RANKING:\n1. A\n2. B\n3. C\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B", "C")

    def test_numbered_list_with_paren_marker(self):
        text = "FINAL RANKING:\n1) A\n2) B\n3) C\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B", "C")

    def test_bullet_list(self):
        text = "FINAL RANKING:\n- A\n- B\n- C\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B", "C")

    def test_real_member_names(self):
        # When the anonymization flag is OFF, valid_labels are real names.
        text = "FINAL RANKING:\n1. Alice\n2. Bob\n3. Carol\n"
        result = parse_final_ranking(text, valid_labels=["Alice", "Bob", "Carol"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("Alice", "Bob", "Carol")

    def test_raw_text_preserved(self):
        text = "FINAL RANKING:\n1. A\n2. B\n"
        result = parse_final_ranking(text, valid_labels=["A", "B"])
        assert isinstance(result, FinalRanking)
        # raw_text is everything after the sentinel (used for audit).
        assert "1. A" in result.raw_text
        assert "2. B" in result.raw_text


class TestParseFinalRankingLastWins:
    def test_last_occurrence_wins_when_multiple_sentinels(self):
        text = (
            "First attempt:\n"
            "FINAL RANKING: X, Y\n"
            "Wait, that was wrong. Let me redo.\n"
            "FINAL RANKING: A, B, C\n"
        )
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        # If the parser took the FIRST occurrence, X/Y would not be in
        # valid_labels and we'd get unknown_label. The LAST-wins rule is
        # what makes this succeed.
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B", "C")


class TestParseFinalRankingErrors:
    def test_missing_token(self):
        text = "I think A is best, then B, then C.\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, RankingParseError)
        assert result.reason == "missing_token"
        assert result.raw_text == text

    def test_inline_mention_is_not_a_sentinel(self):
        # The literal phrase mid-sentence must NOT count as the sentinel —
        # the regex requires it on its own line.
        text = "I will now produce my FINAL RANKING: it is A first.\n"
        result = parse_final_ranking(text, valid_labels=["A", "B"])
        assert isinstance(result, RankingParseError)
        assert result.reason == "missing_token"

    def test_empty_list_after_token(self):
        text = "Reasoning.\nFINAL RANKING:\n\n\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, RankingParseError)
        assert result.reason == "empty_list"

    def test_unknown_label(self):
        text = "FINAL RANKING:\nA\nB\nQ\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, RankingParseError)
        assert result.reason == "unknown_label"
        # Spec wants the offending label visible in detail for re-prompting.
        assert "Q" in result.detail

    def test_duplicate_label(self):
        text = "FINAL RANKING:\nA\nB\nA\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, RankingParseError)
        assert result.reason == "duplicate_label"
        assert "A" in result.detail


class TestParseFinalRankingWhitespace:
    def test_extra_spaces_around_labels(self):
        text = "FINAL RANKING:    A ,   B ,  C   \n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B", "C")

    def test_mixed_indent_in_numbered_list(self):
        text = "FINAL RANKING:\n  1. A\n    2. B\n3.   C\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B", "C")

    def test_trailing_whitespace_lines_dropped(self):
        text = "FINAL RANKING:\nA\nB\nC\n\n   \n\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B", "C")

    def test_partial_list_accepted_if_in_valid_set(self):
        # Two-of-three is not a parse error — the spec validates against
        # ``valid_labels``, not "must equal valid_labels". Caller decides
        # whether a short list is semantically acceptable.
        text = "FINAL RANKING:\nA\nB\n"
        result = parse_final_ranking(text, valid_labels=["A", "B", "C"])
        assert isinstance(result, FinalRanking)
        assert result.ordered_labels == ("A", "B")
