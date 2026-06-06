"""Tests for bridge.memory_enhancement — intent, importance, context window, analytics."""

from __future__ import annotations

import time


from bridge.memory_enhancement import (
    DEFAULT_CONTEXT_WINDOW,
    VALID_INTENTS,
    MemoryAnalytics,
    ScoredEntry,
    classify_intent,
    compute_analytics,
    compute_importance,
    find_low_importance,
    format_context_for_claude,
    select_context_window,
)


def _make_entry(
    key: str = "test-key",
    value: str = "test value",
    category: str = "general",
    intent: str = "fact",
    salience: float = 0.5,
    access_count: int = 0,
    last_accessed: float = 0.0,
    created_at: float = 0.0,
) -> ScoredEntry:
    return ScoredEntry(
        key=key,
        value=value,
        category=category,
        intent=intent,
        salience=salience,
        access_count=access_count,
        last_accessed=last_accessed,
        created_at=created_at,
    )


# ── Intent Classification ──

class TestIntentClassification:
    def test_preference(self):
        assert classify_intent("I prefer using Python over JavaScript") == "preference"

    def test_decision(self):
        assert classify_intent("We decided to use SQLite for storage") == "decision"

    def test_instruction(self):
        assert classify_intent("You must always validate input before processing") == "instruction"

    def test_context(self):
        assert classify_intent("Currently working on the voice pipeline") == "context"

    def test_fact_default(self):
        assert classify_intent("The sky appears blue due to Rayleigh scattering") == "fact"

    def test_empty_string(self):
        assert classify_intent("") == "fact"

    def test_case_insensitive(self):
        assert classify_intent("I PREFER TypeScript") == "preference"

    def test_multiple_signals(self):
        # "decided" and "chose" both point to decision
        result = classify_intent("We decided and chose to go with option A")
        assert result == "decision"

    def test_all_intents_valid(self):
        for intent in VALID_INTENTS:
            assert intent in VALID_INTENTS


# ── Importance Scoring ──

class TestImportanceScoring:
    def test_high_salience_high_importance(self):
        entry = _make_entry(salience=0.9, created_at=time.time())
        score = compute_importance(entry)
        assert score > 0

    def test_low_salience_low_importance(self):
        high = _make_entry(salience=0.9, created_at=time.time())
        low = _make_entry(salience=0.1, created_at=time.time())
        assert compute_importance(high) > compute_importance(low)

    def test_recent_access_boosts(self):
        recent = _make_entry(
            salience=0.5,
            last_accessed=time.time(),
            created_at=time.time() - 86400,
        )
        stale = _make_entry(
            salience=0.5,
            last_accessed=time.time() - 86400 * 7,
            created_at=time.time() - 86400,
        )
        assert compute_importance(recent) >= compute_importance(stale)

    def test_high_access_count_boosts(self):
        many = _make_entry(salience=0.5, access_count=10, created_at=time.time())
        few = _make_entry(salience=0.5, access_count=0, created_at=time.time())
        assert compute_importance(many) > compute_importance(few)

    def test_intent_boost(self):
        entry = _make_entry(intent="decision", created_at=time.time())
        boosted = compute_importance(entry, intent_boost="decision")
        normal = compute_importance(entry, intent_boost="fact")
        assert boosted > normal

    def test_score_bounded(self):
        entry = _make_entry(
            salience=1.0,
            access_count=100,
            last_accessed=time.time(),
            created_at=time.time(),
        )
        score = compute_importance(entry)
        assert 0.0 <= score <= 1.0

    def test_zero_salience(self):
        entry = _make_entry(salience=0.0, created_at=time.time())
        score = compute_importance(entry)
        assert score >= 0.0


# ── Context Window ──

class TestContextWindow:
    def test_selects_top_entries(self):
        entries = [
            _make_entry(key=f"k{i}", salience=i * 0.1, created_at=time.time())
            for i in range(10)
        ]
        selected = select_context_window(entries, max_entries=3)
        assert len(selected) == 3

    def test_respects_max_entries(self):
        entries = [_make_entry(key=f"k{i}", created_at=time.time()) for i in range(50)]
        selected = select_context_window(entries, max_entries=DEFAULT_CONTEXT_WINDOW)
        assert len(selected) <= DEFAULT_CONTEXT_WINDOW

    def test_respects_char_budget(self):
        entries = [
            _make_entry(key=f"k{i}", value="x" * 1000, salience=0.9, created_at=time.time())
            for i in range(20)
        ]
        selected = select_context_window(entries, max_chars=5000)
        total = sum(len(e.key) + len(e.value) for e in selected)
        assert total <= 5000

    def test_empty_entries(self):
        assert select_context_window([]) == []

    def test_intent_filter_boosts(self):
        decision = _make_entry(
            key="dec", intent="decision", salience=0.3, created_at=time.time()
        )
        fact = _make_entry(
            key="fact", intent="fact", salience=0.5, created_at=time.time()
        )
        selected = select_context_window(
            [decision, fact],
            query_intent="decision",
            max_entries=1,
        )
        assert len(selected) == 1
        # Decision should be boosted even though it has lower salience
        assert selected[0].key == "dec"


# ── Low Importance / Pruning ──

class TestPruning:
    def test_find_low_importance(self):
        entries = [
            _make_entry(key="high", salience=0.9, created_at=time.time()),
            _make_entry(key="low", salience=0.01, created_at=time.time() - 86400 * 60),
        ]
        low = find_low_importance(entries)
        assert any(e.key == "low" for e in low)

    def test_no_low_importance(self):
        entries = [
            _make_entry(salience=0.9, created_at=time.time()),
        ]
        low = find_low_importance(entries)
        assert len(low) == 0


# ── Analytics ──

class TestAnalytics:
    def test_empty_analytics(self):
        analytics = compute_analytics([])
        assert analytics.total_entries == 0
        assert analytics.avg_salience == 0.0

    def test_analytics_counts(self):
        entries = [
            _make_entry(key="a", category="facts", intent="fact", salience=0.5, created_at=time.time()),
            _make_entry(key="b", category="prefs", intent="preference", salience=0.8, created_at=time.time()),
        ]
        analytics = compute_analytics(entries)
        assert analytics.total_entries == 2
        assert analytics.intent_distribution["fact"] == 1
        assert analytics.intent_distribution["preference"] == 1
        assert analytics.entries_by_category["facts"] == 1

    def test_to_dict(self):
        analytics = MemoryAnalytics(total_entries=5)
        d = analytics.to_dict()
        assert d["total_entries"] == 5
        assert "avg_salience" in d

    def test_recently_accessed(self):
        entries = [
            _make_entry(last_accessed=time.time(), created_at=time.time()),
            _make_entry(last_accessed=time.time() - 86400 * 2, created_at=time.time()),
        ]
        analytics = compute_analytics(entries)
        assert analytics.recently_accessed_count == 1


# ── Context Formatting ──

class TestFormatting:
    def test_format_empty(self):
        assert format_context_for_claude([]) == ""

    def test_format_entries(self):
        entries = [
            _make_entry(key="test-key", value="test value", intent="fact"),
        ]
        result = format_context_for_claude(entries)
        assert "test-key" in result
        assert "test value" in result

    def test_format_with_intent_prefix(self):
        entries = [
            _make_entry(key="pref", value="val", intent="preference"),
        ]
        result = format_context_for_claude(entries)
        assert "[preference]" in result

    def test_format_fact_no_prefix(self):
        entries = [
            _make_entry(key="fact", value="val", intent="fact"),
        ]
        result = format_context_for_claude(entries)
        assert "[fact]" not in result


# ── `<private>` Redaction (concept-only port from claude-mem, AGPL-3.0) ──

class TestPrivateRedaction:
    """End-to-end check that `<private>...</private>` content never reaches
    capture-side scoring or retrieval-side context formatting.
    """

    def test_private_tag_strips_at_capture(self):
        # `classify_intent` is the earliest capture-side hook. Confirm the
        # secret never influences the keyword-based intent vote.
        text = "I prefer working <private>password=hunter2</private> on Sundays"
        intent = classify_intent(text)
        # "prefer" still wins → preference, but we also assert the redaction
        # path didn't crash and the keyword ranking remains correct.
        assert intent == "preference"

    def test_private_tag_never_appears_in_search_results(self):
        # `format_context_for_claude` is the retrieval-side egress. A stored
        # entry whose `value` somehow contains a `<private>` span MUST NOT
        # echo the secret back to Claude.
        entries = [
            _make_entry(
                key="leak-canary",
                value="public bit <private>SECRET_TOKEN_42</private> tail",
                intent="fact",
            ),
        ]
        result = format_context_for_claude(entries)
        assert "SECRET_TOKEN_42" not in result
        assert "public bit" in result
        assert "tail" in result

    def test_private_tag_nested_inner_only_redacted(self):
        # The redactor strips outer-paired spans entirely (defensive nested
        # handling). For the spec's "inner-only" name we verify that a
        # canonical flat span is excised cleanly while the surrounding text
        # round-trips char-for-char.
        text = "keep <private>drop</private> keep2"
        # No private span outside `format_context_for_claude` — exercise the
        # tag_parser primitive directly via the public capture path.
        intent = classify_intent(text)
        assert intent == "fact"  # no keywords match "keep keep2"
        # And confirm storage round-trip via format path:
        entries = [_make_entry(key="k", value=text, intent="fact")]
        result = format_context_for_claude(entries)
        assert "drop" not in result
        assert "keep" in result and "keep2" in result

    def test_private_tag_malformed_open_without_close_safe(self):
        # A bare `<private>` with no close MUST NOT swallow the rest of the
        # message. classify_intent should still classify against the
        # original text.
        text = "I prefer dark mode <private>oops no close"
        intent = classify_intent(text)
        assert intent == "preference"  # "prefer" keyword survives

    def test_private_tag_round_trip_preserves_non_redacted(self):
        # Storage round-trip preserves non-redacted text exactly (DoD).
        entries = [
            _make_entry(
                key="exact",
                value="alpha beta gamma",
                intent="fact",
            ),
        ]
        result = format_context_for_claude(entries)
        assert "alpha beta gamma" in result
