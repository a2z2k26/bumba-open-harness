"""Parse structured tags from Claude's response text.

Tags:
    [REMEMBER: fact]
    [FORGET: partial match]
    [GOAL: description | DEADLINE: date]
    [DONE: partial match]
    [CANCEL: partial match]
    [INVOKE: agent | question]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from bridge.dispatch_metrics import increment_module_counter


class TagType(Enum):
    REMEMBER = "remember"
    FORGET = "forget"
    GOAL = "goal"
    DONE = "done"
    CANCEL = "cancel"
    INVOKE = "invoke"


@dataclass
class ParsedTag:
    """A single parsed tag from response text."""

    tag_type: TagType
    value: str
    deadline: str | None = None  # Only for GOAL tags
    agent: str | None = None  # Only for INVOKE tags
    raw: str = ""  # The full matched tag text


# Pattern matches [TAG_NAME: content] with optional nested fields
_TAG_PATTERN = re.compile(
    r"\[("
    r"REMEMBER|FORGET|GOAL|DONE|CANCEL|INVOKE"
    r"):\s*"
    r"(.*?)"
    r"\]",
    re.IGNORECASE | re.DOTALL,
)

# claude-mem-style `<private>` redaction tag (concept-only port from claude-mem,
# AGPL-3.0; paraphrased: an inline tag-bracketed span the user can wrap around
# content that must NOT be persisted to long-term memory). The capture pipeline
# strips matched spans before the content reaches `classify_intent`,
# `compute_importance`, or `format_context_for_claude`.
#
# Inside-out matcher: this pattern only matches a `<private>...</private>`
# span whose body contains NO further `<private>` opening tag. Combined with
# an iterative loop (see `strip_private_spans`), this excises the innermost
# spans first, then the next layer, until no spans remain. The reason for
# inside-out matching is that a naive non-greedy pattern paired with a nested
# inner span would close on the inner `</private>` and leave the outer
# closing tag as orphan literal — see `test_nested_spans`.
#
# Match is case-insensitive and multi-line. The body excludes `<private`
# (case-insensitive) so we never wrap an inner span; the closer tolerates
# trailing whitespace before `>`.
_PRIVATE_INNERMOST_SPAN = re.compile(
    r"<private\b[^>]*>"
    r"(?:(?!<private\b).)*?"
    r"</private\s*>",
    re.IGNORECASE | re.DOTALL,
)
# Defensive: a malformed `<private>` open tag with no matching close should
# never accidentally erase the entire trailing buffer. The matcher requires
# a closing tag, so unmatched opens remain untouched. This is the documented
# behaviour — surface, don't paper over.

# Cap the redaction pass count so a pathological input cannot cause an
# unbounded loop. Each pass MUST strictly reduce the input or break out;
# in practice 8 passes is far beyond any realistic nesting depth.
_MAX_REDACTION_PASSES = 8

# Day name mapping for parse_natural_deadline
_DAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def parse_tags(text: str) -> list[ParsedTag]:
    increment_module_counter("tag_parser.parse_tags", tier=0)
    """Extract all structured tags from text.

    Returns a list of ParsedTag objects in order of appearance.
    """
    tags: list[ParsedTag] = []

    for match in _TAG_PATTERN.finditer(text):
        tag_name = match.group(1).upper()
        content = match.group(2).strip()
        raw = match.group(0)

        tag_type = TagType[tag_name]
        tag = ParsedTag(tag_type=tag_type, value=content, raw=raw)

        if tag_type == TagType.GOAL:
            # Parse optional DEADLINE field: [GOAL: desc | DEADLINE: date]
            if "|" in content:
                parts = content.split("|", 1)
                tag.value = parts[0].strip()
                deadline_part = parts[1].strip()
                # Remove "DEADLINE:" prefix if present
                deadline_match = re.match(r"(?i)DEADLINE:\s*(.*)", deadline_part)
                if deadline_match:
                    tag.deadline = deadline_match.group(1).strip()
                else:
                    tag.deadline = deadline_part
            else:
                tag.value = content

        elif tag_type == TagType.INVOKE:
            # Parse agent and question: [INVOKE: agent | question]
            if "|" in content:
                parts = content.split("|", 1)
                tag.agent = parts[0].strip()
                tag.value = parts[1].strip()
            else:
                tag.agent = content
                tag.value = ""

        tags.append(tag)

    return tags


def strip_tags(text: str) -> str:
    """Remove all structured tags from text and clean up whitespace."""
    result = _TAG_PATTERN.sub("", text)
    # Collapse multiple blank lines into at most two
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def strip_private_spans(text: str) -> str:
    """Remove ``<private>...</private>`` spans (and their content) from text.

    Concept-only port of the claude-mem `<private>` redaction tag (AGPL-3.0;
    paraphrased — see ``_PRIVATE_SPAN_PATTERN`` above). Pure function with no
    side effects: returns a new string. Safe to call on any input.

    Behaviour:

    - Case-insensitive: ``<PRIVATE>``, ``<Private>``, and ``<private>`` are
      all recognised.
    - Multi-line: the redacted span may straddle newlines.
    - Non-greedy: multiple non-overlapping spans are each excised individually.
    - Nested spans: a fixed number of redaction passes runs so the outer span
      removes the entire nested block (defensive — operators may write
      ``<private>outer <private>inner</private> tail</private>`` even though
      the canonical use is flat).
    - Malformed (open without close): unmatched opens are left untouched
      because the matcher requires a closing tag. This is intentional so an
      accidentally-typed ``<private>`` does NOT silently swallow the rest of
      the message.
    - Inputs with no spans round-trip char-for-char (no whitespace
      collapsing, no normalisation).

    Args:
        text: The raw input that may contain redaction spans.

    Returns:
        The input with all matched spans removed. Identical to the input when
        no span is present.
    """
    if not text or "<" not in text:
        # Fast path: no angle bracket means no possible match.
        return text

    result = text
    for _ in range(_MAX_REDACTION_PASSES):
        new_result = _PRIVATE_INNERMOST_SPAN.sub("", result)
        if new_result == result:
            break
        result = new_result
    return result


def parse_natural_deadline(text: str) -> datetime | None:
    """Parse a natural language deadline into a datetime.

    Supports:
        - "tomorrow"
        - "today"
        - "next Monday", "next Friday", etc.
        - "in N days", "in N hours", "in N weeks"
        - ISO format: "2024-03-15", "2024-03-15T14:00"
        - Informal: "Monday", "Friday" (next occurrence)
    """
    if not text:
        return None

    text = text.strip().lower()
    now = datetime.now()

    # "today"
    if text == "today":
        return now.replace(hour=23, minute=59, second=0, microsecond=0)

    # "tomorrow"
    if text == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)

    # "in N days/hours/weeks/minutes"
    relative = re.match(r"in\s+(\d+)\s+(day|hour|week|minute|month)s?", text)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        if unit == "day":
            return now + timedelta(days=amount)
        elif unit == "hour":
            return now + timedelta(hours=amount)
        elif unit == "week":
            return now + timedelta(weeks=amount)
        elif unit == "minute":
            return now + timedelta(minutes=amount)
        elif unit == "month":
            return now + timedelta(days=amount * 30)

    # "next Monday", "next Friday", etc.
    next_day = re.match(r"next\s+(\w+)", text)
    if next_day:
        day_name = next_day.group(1).lower()
        if day_name in _DAY_NAMES:
            target = _DAY_NAMES[day_name]
            days_ahead = target - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (now + timedelta(days=days_ahead)).replace(
                hour=23, minute=59, second=0, microsecond=0
            )

    # Bare day name: "Monday", "Friday" (next occurrence)
    if text in _DAY_NAMES:
        target = _DAY_NAMES[text]
        days_ahead = target - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return (now + timedelta(days=days_ahead)).replace(
            hour=23, minute=59, second=0, microsecond=0
        )

    # ISO format: "2024-03-15" or "2024-03-15T14:00"
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None
