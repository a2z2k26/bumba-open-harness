"""Tests for bridge.tag_parser."""

from __future__ import annotations

from datetime import datetime, timedelta

from bridge.tag_parser import (
    TagType,
    parse_natural_deadline,
    parse_tags,
    strip_private_spans,
    strip_tags,
)


class TestParseTags:
    """Tag extraction from text."""

    def test_parse_remember_tag(self):
        text = "Sure! [REMEMBER: User prefers dark mode] I'll keep that in mind."
        tags = parse_tags(text)
        assert len(tags) == 1
        assert tags[0].tag_type == TagType.REMEMBER
        assert tags[0].value == "User prefers dark mode"

    def test_parse_forget_tag(self):
        text = "[FORGET: dark mode] Removed that preference."
        tags = parse_tags(text)
        assert len(tags) == 1
        assert tags[0].tag_type == TagType.FORGET
        assert tags[0].value == "dark mode"

    def test_parse_goal_without_deadline(self):
        text = "[GOAL: Finish the quarterly report] I'll track that for you."
        tags = parse_tags(text)
        assert len(tags) == 1
        assert tags[0].tag_type == TagType.GOAL
        assert tags[0].value == "Finish the quarterly report"
        assert tags[0].deadline is None

    def test_parse_goal_with_deadline(self):
        text = "[GOAL: Finish the report | DEADLINE: next Friday] Got it!"
        tags = parse_tags(text)
        assert len(tags) == 1
        assert tags[0].tag_type == TagType.GOAL
        assert tags[0].value == "Finish the report"
        assert tags[0].deadline == "next Friday"

    def test_parse_done_tag(self):
        text = "[DONE: quarterly report] Great job completing that!"
        tags = parse_tags(text)
        assert len(tags) == 1
        assert tags[0].tag_type == TagType.DONE
        assert tags[0].value == "quarterly report"

    def test_parse_cancel_tag(self):
        text = "[CANCEL: old project] Removed from your goals."
        tags = parse_tags(text)
        assert len(tags) == 1
        assert tags[0].tag_type == TagType.CANCEL
        assert tags[0].value == "old project"

    def test_parse_invoke_tag(self):
        text = "[INVOKE: strategist | What's the best approach for scaling?]"
        tags = parse_tags(text)
        assert len(tags) == 1
        assert tags[0].tag_type == TagType.INVOKE
        assert tags[0].agent == "strategist"
        assert tags[0].value == "What's the best approach for scaling?"

    def test_parse_invoke_no_question(self):
        text = "[INVOKE: analyst]"
        tags = parse_tags(text)
        assert len(tags) == 1
        assert tags[0].tag_type == TagType.INVOKE
        assert tags[0].agent == "analyst"
        assert tags[0].value == ""

    def test_parse_multiple_tags(self):
        text = (
            "[REMEMBER: User's name is the operator] "
            "[GOAL: Deploy v2 | DEADLINE: tomorrow] "
            "I've noted your name and set up that goal."
        )
        tags = parse_tags(text)
        assert len(tags) == 2
        assert tags[0].tag_type == TagType.REMEMBER
        assert tags[1].tag_type == TagType.GOAL
        assert tags[1].deadline == "tomorrow"

    def test_parse_no_tags(self):
        text = "Just a normal response with no special tags."
        tags = parse_tags(text)
        assert len(tags) == 0

    def test_parse_case_insensitive(self):
        text = "[remember: something important] [Goal: do a thing]"
        tags = parse_tags(text)
        assert len(tags) == 2
        assert tags[0].tag_type == TagType.REMEMBER
        assert tags[1].tag_type == TagType.GOAL

    def test_tag_preserves_raw(self):
        text = "Hello [REMEMBER: test fact] world"
        tags = parse_tags(text)
        assert tags[0].raw == "[REMEMBER: test fact]"


class TestStripTags:
    """Tag removal from text."""

    def test_strip_single_tag(self):
        text = "Hello [REMEMBER: test] world"
        assert strip_tags(text) == "Hello  world"

    def test_strip_multiple_tags(self):
        text = "[REMEMBER: a] Response text [GOAL: b | DEADLINE: tomorrow]"
        result = strip_tags(text)
        assert "REMEMBER" not in result
        assert "GOAL" not in result
        assert "Response text" in result

    def test_strip_tags_only(self):
        text = "[REMEMBER: fact]"
        assert strip_tags(text) == ""

    def test_strip_collapses_blank_lines(self):
        text = "Before\n\n\n[REMEMBER: fact]\n\n\nAfter"
        result = strip_tags(text)
        assert "\n\n\n" not in result


class TestParseNaturalDeadline:
    """Natural language deadline parsing."""

    def test_tomorrow(self):
        result = parse_natural_deadline("tomorrow")
        assert result is not None
        expected = datetime.now() + timedelta(days=1)
        assert result.date() == expected.date()

    def test_today(self):
        result = parse_natural_deadline("today")
        assert result is not None
        assert result.date() == datetime.now().date()

    def test_in_3_days(self):
        result = parse_natural_deadline("in 3 days")
        assert result is not None
        expected = datetime.now() + timedelta(days=3)
        # Allow 1 second of tolerance
        assert abs((result - expected).total_seconds()) < 2

    def test_in_2_hours(self):
        result = parse_natural_deadline("in 2 hours")
        assert result is not None
        expected = datetime.now() + timedelta(hours=2)
        assert abs((result - expected).total_seconds()) < 2

    def test_in_1_week(self):
        result = parse_natural_deadline("in 1 week")
        assert result is not None
        expected = datetime.now() + timedelta(weeks=1)
        assert abs((result - expected).total_seconds()) < 2

    def test_next_friday(self):
        result = parse_natural_deadline("next Friday")
        assert result is not None
        assert result > datetime.now()
        assert result.weekday() == 4  # Friday

    def test_bare_day_name(self):
        result = parse_natural_deadline("Monday")
        assert result is not None
        assert result > datetime.now()
        assert result.weekday() == 0  # Monday

    def test_iso_date(self):
        result = parse_natural_deadline("2026-06-15")
        assert result is not None
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 15

    def test_iso_datetime(self):
        result = parse_natural_deadline("2026-03-15T14:00")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 0

    def test_empty_string(self):
        assert parse_natural_deadline("") is None

    def test_none(self):
        assert parse_natural_deadline(None) is None

    def test_unparseable(self):
        assert parse_natural_deadline("sometime maybe") is None


class TestStripPrivateSpans:
    """`<private>...</private>` redaction tag — concept-only port (AGPL-3.0)."""

    def test_simple_span(self):
        text = "before <private>secret</private> after"
        assert strip_private_spans(text) == "before  after"

    def test_multiline_span(self):
        text = "line1\n<private>secret\nline\nbreak</private>\nline2"
        result = strip_private_spans(text)
        assert "secret" not in result
        assert "line1" in result
        assert "line2" in result

    def test_case_uppercase(self):
        text = "x <PRIVATE>SECRET</PRIVATE> y"
        assert strip_private_spans(text) == "x  y"

    def test_case_mixed(self):
        text = "x <Private>secret</Private> y"
        assert strip_private_spans(text) == "x  y"

    def test_nested_spans(self):
        # Outer span swallows entire nested block when paired correctly.
        text = "x <private>outer <private>inner</private> tail</private> y"
        result = strip_private_spans(text)
        assert "secret" not in result
        assert "outer" not in result
        assert "inner" not in result
        assert "tail" not in result
        assert result == "x  y"

    def test_no_span_passthrough(self):
        text = "no span here, just regular content"
        assert strip_private_spans(text) == text

    def test_multiple_non_overlapping(self):
        text = "a <private>s1</private> b <private>s2</private> c"
        result = strip_private_spans(text)
        assert "s1" not in result
        assert "s2" not in result
        assert "a" in result and "b" in result and "c" in result

    def test_empty_span(self):
        text = "x <private></private> y"
        assert strip_private_spans(text) == "x  y"

    def test_empty_input(self):
        assert strip_private_spans("") == ""

    def test_malformed_open_without_close_safe(self):
        # An unmatched `<private>` open MUST NOT silently swallow the rest of
        # the buffer — the matcher requires a close tag.
        text = "before <private>oops no close here"
        assert strip_private_spans(text) == text

    def test_private_tag_in_url_treated_as_literal(self):
        # A `<private>` substring that is part of a URL or word should still
        # be redacted because the tag has well-defined semantics regardless
        # of context. The test asserts non-overlapping spans behave as
        # documented (no smart "inside-URL" exception).
        text = "see https://example.com/<private>token</private>/path"
        result = strip_private_spans(text)
        assert "token" not in result
        assert "https://example.com/" in result
        assert "/path" in result

    def test_spanning_code_block(self):
        text = "```\ncode\n<private>secret_key=abc123</private>\nmore code\n```"
        result = strip_private_spans(text)
        assert "secret_key" not in result
        assert "abc123" not in result
        assert "code" in result
        assert "more code" in result

    def test_returns_new_string_not_mutation(self):
        # Strings are immutable in Python, but verify identity differs when
        # changes happen so callers don't rely on identity-equality.
        text = "x <private>s</private> y"
        result = strip_private_spans(text)
        assert result is not text
        assert result == "x  y"
