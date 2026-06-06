"""Tests for bridge.message_classifier (Sprint D-R4, #1934).

Covers the four MessageType classes, performance budget, cache identity,
and decision-order edge cases.
"""
from __future__ import annotations

import pytest

from bridge.message_classifier import (
    MessageClassification,
    MessageType,
    classify,
)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_message_classification_is_frozen() -> None:
    """Result dataclass must be immutable so cached values can't be mutated."""
    mc = classify("hi")
    with pytest.raises(Exception):
        mc.message_type = MessageType.TASK  # type: ignore[misc]


def test_classify_returns_message_classification() -> None:
    """Public API returns a MessageClassification instance."""
    assert isinstance(classify("hi"), MessageClassification)


# ---------------------------------------------------------------------------
# CONVERSATIONAL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("greeting", [
    "hi", "hii", "hey", "heyyy", "hello", "sup", "yo",
    "ok", "okay", "got it", "thanks", "thank you", "ty", "thx",
    "lgtm", "ack", "acknowledged",
    "yes", "no", "yep", "nope", "sure", "sounds good", "cool", "great",
    "perfect", "agreed",
    "how are you", "how are you?",
    "continue", "go ahead", "proceed", "carry on",
])
def test_conversational_openers_classify_as_conversational(greeting: str) -> None:
    mc = classify(greeting)
    assert mc.message_type == MessageType.CONVERSATIONAL, (
        f"{greeting!r} expected CONVERSATIONAL, got {mc.message_type}"
    )
    assert mc.confidence >= 0.90


def test_conversational_handles_trailing_punctuation() -> None:
    """Casual punctuation should still classify as conversational."""
    for variant in ("hi!", "ok.", "thanks!!", "got it..."):
        mc = classify(variant)
        assert mc.message_type == MessageType.CONVERSATIONAL


# ---------------------------------------------------------------------------
# TASK
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task_msg,expected_verb", [
    ("build a login page", "build"),
    ("fix the auth bug", "fix"),
    ("please refactor the dispatcher", "refactor"),
    ("can you implement the new feature?", "implement"),
    ("deploy to production", "deploy"),
    ("write a test for this", "write"),
    ("rename the variable", "rename"),
    ("optimize the query", "optimize"),
])
def test_task_verbs_classify_as_task(task_msg: str, expected_verb: str) -> None:
    mc = classify(task_msg)
    assert mc.message_type == MessageType.TASK, (
        f"{task_msg!r} expected TASK, got {mc.message_type}"
    )
    assert expected_verb in mc.matched_signal


# ---------------------------------------------------------------------------
# INFORMATION_REQUEST
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("info_msg", [
    "what is the current session count?",
    "how does the warm process work?",
    "why did the dispatcher fail?",
    "when does the cron fire?",
    "where is the config file?",
    "who owns this module?",
    "can you tell me the queue depth",
    "tell me about the recent failures",
    "show me the cost report",
    "explain how routing works",
    "list the open PRs",
    # Note: messages combining an interrogative + an action verb
    # ("what's the latest deploy?" / "how do you build X?") classify
    # as TASK because the task-verb pattern fires before the
    # info-request pattern. This is the intended decision order; the
    # classifier prefers actionable framing when verbs are present.
])
def test_information_requests_classify_as_information_request(info_msg: str) -> None:
    mc = classify(info_msg)
    assert mc.message_type == MessageType.INFORMATION_REQUEST, (
        f"{info_msg!r} expected INFORMATION_REQUEST, got {mc.message_type}"
    )


# ---------------------------------------------------------------------------
# ZONE4_EXPLICIT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("z4_msg,expected_prefix", [
    ("/board debate the architecture", "/board"),
    ("/route to engineering", "/route"),
    ("/z4_tasks status", "/z4_tasks"),
    ("/departments list", "/departments"),
    ("/handoff to qa", "/handoff"),
    ("@engineering fix the auth bug", "@engineering"),
    ("@qa review the auth flow", "@qa"),
    ("@ops diagnose the outage", "@ops"),
    ("@strategy analyze the q3 plan", "@strategy"),
    ("@design review the new modal", "@design"),
])
def test_zone4_prefixes_classify_as_zone4_explicit(
    z4_msg: str, expected_prefix: str
) -> None:
    mc = classify(z4_msg)
    assert mc.message_type == MessageType.ZONE4_EXPLICIT, (
        f"{z4_msg!r} expected ZONE4_EXPLICIT, got {mc.message_type}"
    )
    assert mc.matched_signal == f"zone4_prefix:{expected_prefix}"
    assert mc.confidence >= 0.95


def test_zone4_prefix_takes_precedence_over_task_verb() -> None:
    """A message starting with /board that also contains 'fix' should
    classify as ZONE4_EXPLICIT — prefix wins."""
    mc = classify("/board fix the architectural drift")
    assert mc.message_type == MessageType.ZONE4_EXPLICIT


def test_zone4_prefix_case_insensitive() -> None:
    """The prefix match should be case-insensitive."""
    mc = classify("/BOARD discuss the roadmap")
    assert mc.message_type == MessageType.ZONE4_EXPLICIT


# ---------------------------------------------------------------------------
# Decision-order edge cases
# ---------------------------------------------------------------------------


def test_default_fallback_returns_information_request_low_confidence() -> None:
    """Text that matches nothing should fall to INFO_REQUEST with conf 0.5."""
    mc = classify("xyzzy plover")
    assert mc.message_type == MessageType.INFORMATION_REQUEST
    assert mc.matched_signal == "default_fallback"
    assert mc.confidence == 0.50


def test_conversational_takes_precedence_over_info_request() -> None:
    """'how are you?' starts with 'how' but should classify CONVERSATIONAL,
    not INFO_REQUEST — conversational regex is checked first."""
    mc = classify("how are you?")
    assert mc.message_type == MessageType.CONVERSATIONAL


# ---------------------------------------------------------------------------
# Cache identity (lru_cache wired)
# ---------------------------------------------------------------------------


def test_classify_cache_returns_identical_object() -> None:
    """Two calls with the same input must return the same instance — proves
    @lru_cache(maxsize=512) is in place. Otherwise repeated message
    classifications would re-pay the regex cost on every turn."""
    a = classify("hi")
    b = classify("hi")
    assert a is b, "classify() must be cached — same input should return same instance"


# ---------------------------------------------------------------------------
# Performance budget (< 5ms)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("msg", [
    "hi",
    "fix the auth bug",
    "what is the current session count?",
    "/board debate the architecture",
    "xyzzy plover",  # fallback path
])
def test_classify_under_5ms(msg: str) -> None:
    """Every code path must complete in < 5ms wall clock.

    Note: the first call to classify() per process JIT-compiles the
    regexes; we use a warm-up call to amortize that out of the budget.
    """
    classify(msg + " warmup")
    mc = classify(msg)
    assert mc.elapsed_ms < 5.0, (
        f"classify({msg!r}) took {mc.elapsed_ms:.3f}ms (budget 5ms)"
    )
