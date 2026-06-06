"""Lightweight message classifier for the conversational fast path.

Sprint D-R4 (#1934), epic: dispatcher-re-envision.

Classifies an inbound operator message into one of four ``MessageType``
buckets so the pipeline can route quickly:

- ``ZONE4_EXPLICIT``      → existing dispatcher branch (D-R2 gate)
- ``TASK``                → warm process + task-framing preamble
- ``INFORMATION_REQUEST`` → warm process directly
- ``CONVERSATIONAL``      → warm process directly

Pure regex + heuristic, no I/O, no model calls. Target < 5ms per call.
Results are cached via ``lru_cache(maxsize=512)`` so a repeated message
is free.

This module is the **primary routing decision** post-D-R4. D-R2's
intent-classifier gate becomes a secondary guard *inside* the
``ZONE4_EXPLICIT`` branch; for all other types the gate is skipped
entirely (and so is the intent classifier call).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache


class MessageType(Enum):
    """Coarse routing class for an inbound message."""

    CONVERSATIONAL = "conversational"
    INFORMATION_REQUEST = "information_request"
    TASK = "task"
    ZONE4_EXPLICIT = "zone4_explicit"


@dataclass(frozen=True)
class MessageClassification:
    """Result of classifying a message.

    Attributes:
        message_type: The coarse routing class.
        confidence: 0.0-1.0 score for the classification.
        matched_signal: Human-readable string identifying which rule
            fired (used for logging + debugging).
        elapsed_ms: Wall-clock time spent in ``classify()`` for this
            message. Useful for the < 5ms performance assertion in tests.
    """

    message_type: MessageType
    confidence: float
    matched_signal: str
    elapsed_ms: float


# --- Pattern tables --------------------------------------------------------

# Explicit Zone 4 prefixes — operator-typed slash commands or @-mentions that
# unambiguously target a chief or department. Highest precedence; any prefix
# match short-circuits to ZONE4_EXPLICIT regardless of message body.
_ZONE4_PREFIXES: tuple[str, ...] = (
    "/board",
    "/route",
    "/z4_tasks",
    "/departments",
    "/handoff",
    "@engineering",
    "@qa",
    "@ops",
    "@strategy",
    "@design",
)

# Conversational openers — short greetings, acks, affirmations.
_CONVERSATIONAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^\s*(hi+|hey+|hello+|sup|yo)\s*[!.,?]*\s*$",
        r"^\s*(ok|okay|got it|thanks|thank you|ty|thx|lgtm|ack(?:nowledged?)?)\s*[!.,?]*\s*$",
        r"^\s*(yes|no|yep|nope|sure|sounds good|cool|great|perfect|agreed)\s*[!.,?]*\s*$",
        r"^\s*how are you\??\s*$",
        r"^\s*(continue|go ahead|proceed|carry on)\s*[!.,?]*\s*$",
    )
)

# Task verbs — implementation/build requests. Match anywhere in the string
# rather than at the start; "please fix the auth bug" should still classify
# as TASK.
_TASK_VERB_RE: re.Pattern[str] = re.compile(
    r"\b(build|create|implement|write|fix|refactor|add|remove|update|deploy|"
    r"generate|make|set up|configure|migrate|test|debug|optimize|rename|delete|"
    r"move|copy|extract|split|merge|wire|enable|disable|install|upgrade)\b",
    re.IGNORECASE,
)

# Information request — interrogatives at the start.
_INFO_REQUEST_RE: re.Pattern[str] = re.compile(
    r"^\s*(what|how|why|when|where|who|can you|could you|is there|are there|"
    r"tell me|show me|explain|describe|list|find|check|verify|what'?s|"
    r"how do(?:es)?)\b",
    re.IGNORECASE,
)


# --- Public API ------------------------------------------------------------


@lru_cache(maxsize=512)
def classify(message: str) -> MessageClassification:
    """Classify an inbound message into a ``MessageType``.

    Decision order (first match wins):
    1. Zone 4 explicit prefix → ``ZONE4_EXPLICIT``
    2. Conversational opener pattern → ``CONVERSATIONAL``
    3. Task verb anywhere in message → ``TASK``
    4. Information-request interrogative at start → ``INFORMATION_REQUEST``
    5. Fallback → ``INFORMATION_REQUEST`` (low confidence)

    Results are memoized per-message via ``lru_cache`` so identical input
    returns the same instance — the test suite asserts identity to
    confirm the cache is wired.
    """
    t0 = time.perf_counter()
    stripped = message.strip()
    lower = stripped.lower()

    for prefix in _ZONE4_PREFIXES:
        if lower.startswith(prefix):
            return MessageClassification(
                message_type=MessageType.ZONE4_EXPLICIT,
                confidence=0.99,
                matched_signal=f"zone4_prefix:{prefix}",
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            )

    for pattern in _CONVERSATIONAL_PATTERNS:
        if pattern.match(stripped):
            return MessageClassification(
                message_type=MessageType.CONVERSATIONAL,
                confidence=0.95,
                matched_signal="conversational_re",
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            )

    task_match = _TASK_VERB_RE.search(stripped)
    if task_match:
        return MessageClassification(
            message_type=MessageType.TASK,
            confidence=0.80,
            matched_signal=f"task_verb:{task_match.group().lower()}",
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )

    if _INFO_REQUEST_RE.match(stripped):
        return MessageClassification(
            message_type=MessageType.INFORMATION_REQUEST,
            confidence=0.75,
            matched_signal="info_request_re",
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )

    return MessageClassification(
        message_type=MessageType.INFORMATION_REQUEST,
        confidence=0.50,
        matched_signal="default_fallback",
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
    )
