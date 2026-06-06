"""Operator inbox + interrupt injection for dialogue-first communication.

D7.5 finding F-2: highest-leverage friction item in the audit. This module
is module-complete but the wiring into claude_runner is still dormant —
operator messages don't yet preempt in-progress tool calls. See sprint D7.9
(#1421) for the activation work.

Sprint 4.9 — Phase 4B (Dialogue-First Communication Architecture).
Sprint 4.11 — Adds content-based severity classifier + override prefixes.
Sprint E3.3 — Redirect and confirm wiring for orientation update triggers.

Operator messages are the highest-priority interrupt in the system.
When the agent is deep in a work loop, soft instructions like "respond
to the operator first" get routed around — the work loop is the same
loop as the communication loop, so the agent has nothing structural
forcing it to check for new operator input before each turn.

This module builds the inbox. Messages from Discord, the terminal, or
any other operator channel land in an `OperatorInbox`. Before every
model turn, the harness calls `build_turn_context_with_inbox()` which
prepends a banner at the TOP of the context window. The agent cannot
avoid seeing pending messages — they are in its immediate attention
field on every turn until acknowledged.

This sprint ships the inbox state machine and the banner formatter.
Sprint 4.10 builds the tool-call gate that refuses to execute tool
calls until the agent has emitted an `[ACK:msg_id]` marker for each
pending message. 4.9 makes pending messages visible; 4.10 makes them
enforceable.

Design principles:
    1. The inbox is the single source of truth. Do not cache "last
       pending" state elsewhere.
    2. Acknowledgment is idempotent: acking an unknown or already-acked
       ID is a silent no-op, so callers racing the agent don't need
       defensive try/except.
    3. The banner contains its own instructions. The agent should be
       able to handle a pending message on first contact without any
       out-of-band system prompt changes. This keeps the module
       composable with whatever downstream system prompt evolution
       happens in Sprint 4.12.
    4. All timestamps are timezone-aware UTC. No naive datetimes leak
       into the inbox state.
"""
from __future__ import annotations

import asyncio
import enum
import itertools
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# E3.3 — lazy import to avoid circular; called only from receive() path.
def _orientation_hooks(content: str) -> None:
    """Fire E3.3 orientation update hooks based on message content."""
    try:
        from bridge.orientation import (
            is_redirect_message,
            promote_pending_focus_if_confirmed,
            update_on_operator_redirect,
        )
        if is_redirect_message(content):
            update_on_operator_redirect(content)
        else:
            promote_pending_focus_if_confirmed(content)
    except Exception as exc:
        logger.warning("operator_inbox: orientation hook failed: %s", exc)


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


class MessageSeverity(enum.Enum):
    """Operator message severity.

    - INFO: acknowledgment required, work may continue after ack.
    - QUESTION: acknowledgment required, work pauses until operator
      answers `continue` (or similar) in a follow-up message.
    - HALT: work terminates cleanly; the agent must stop and wait.

    Sprint 4.10's tool-call gate reads this enum to decide whether to
    block only the next tool call (INFO, QUESTION) or all tool calls
    until an explicit resume (HALT).
    """

    INFO = "info"
    QUESTION = "question"
    HALT = "halt"


# ---------------------------------------------------------------------------
# Operator message
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OperatorMessage:
    """An immutable record of a single operator message.

    Attributes:
        id: Unique identifier. Format: ``msg_<ms_timestamp>_<seq>``.
            The timestamp segment is a debugging aid only — it is
            wall-clock wall-time and can go backwards across NTP syncs,
            so **IDs are NOT sortable**. The per-inbox sequence counter
            is the authoritative uniqueness guarantee. Arrival order
            comes from list position in ``OperatorInbox.pending()`` /
            ``all_messages()``, never from string-sorting IDs.
        content: The raw text the operator sent.
        severity: How the harness should treat this message.
        received_at: UTC timestamp when the inbox received the message.
        acknowledged_at: UTC timestamp when the agent acked the message,
            or ``None`` if still pending.
    """

    id: str
    content: str
    severity: MessageSeverity
    received_at: datetime
    acknowledged_at: datetime | None = None

    @property
    def is_pending(self) -> bool:
        return self.acknowledged_at is None

    @property
    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.received_at).total_seconds()


# ---------------------------------------------------------------------------
# Inbox store
# ---------------------------------------------------------------------------


class OperatorInbox:
    """Async-safe store of operator messages for a single session.

    The inbox is owned per-session. Messages are stored in arrival order
    and never removed — acknowledgment mutates the timestamp only, so
    the inbox also doubles as a history log that the harness can surface
    in ``/status`` or a future audit command.

    Concurrency is handled by a single asyncio.Lock. All mutating
    operations (receive, acknowledge) take the lock; read operations
    (pending, all_messages) also take the lock to return a stable
    snapshot rather than a view of mid-mutation state.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._messages: list[OperatorMessage] = []
        self._lock = asyncio.Lock()
        # Monotonic per-inbox sequence to guarantee unique IDs even when
        # two messages arrive within the same millisecond AND across
        # wall-clock jumps (NTP sync, DST, manual clock change). The
        # sequence is the authoritative uniqueness bit — the embedded
        # timestamp is a human-readable debugging aid, not a sort key.
        # Callers that need arrival order MUST use list position from
        # ``pending()`` / ``all_messages()``, not string-sort on ID.
        self._seq = itertools.count(1)

    async def receive(
        self,
        content: str,
        severity: MessageSeverity,
    ) -> OperatorMessage:
        """Store a new operator message and return the stored record."""
        async with self._lock:
            msg_id = f"msg_{int(time.time() * 1000)}_{next(self._seq)}"
            msg = OperatorMessage(
                id=msg_id,
                content=content,
                severity=severity,
                received_at=datetime.now(timezone.utc),
            )
            self._messages.append(msg)
            logger.info(
                "operator_inbox: received %s severity=%s session=%s",
                msg.id,
                severity.value,
                self.session_id,
            )

        # E3.3 — orientation hooks run outside the lock (file I/O, no re-entrancy).
        _orientation_hooks(content)
        return msg

    async def pending(self) -> list[OperatorMessage]:
        """Return a snapshot list of unacknowledged messages in arrival order."""
        async with self._lock:
            return [m for m in self._messages if m.is_pending]

    async def acknowledge(self, msg_id: str) -> None:
        """Mark a pending message as acknowledged.

        Silently ignores unknown IDs and already-acked messages so
        callers don't need to wrap the call in try/except for benign
        races (e.g. the agent acking a message the operator already
        withdrew via another command).
        """
        async with self._lock:
            for i, msg in enumerate(self._messages):
                if msg.id == msg_id and msg.is_pending:
                    self._messages[i] = replace(
                        msg,
                        acknowledged_at=datetime.now(timezone.utc),
                    )
                    logger.info(
                        "operator_inbox: acknowledged %s session=%s",
                        msg_id,
                        self.session_id,
                    )
                    return
            logger.debug(
                "operator_inbox: acknowledge no-op for %s session=%s",
                msg_id,
                self.session_id,
            )

    async def all_messages(self) -> list[OperatorMessage]:
        """Return a snapshot of every message (pending and acked) in arrival order."""
        async with self._lock:
            return list(self._messages)

    async def receive_classified(self, content: str) -> OperatorMessage:
        """Receive a message with severity auto-classified from ``content``.

        Convenience wrapper around ``receive()`` for callers that don't
        pre-classify (e.g. the Discord bot, terminal input). The original
        content is stored verbatim — the classifier only reads it, never
        rewrites it, so the agent sees exactly what the operator typed.

        See ``classify_severity()`` for the classification rules and the
        full list of operator-facing override prefixes.
        """
        severity = classify_severity(content)
        return await self.receive(content, severity)


# ---------------------------------------------------------------------------
# Banner formatter
# ---------------------------------------------------------------------------


_BANNER_HEADER = "WARNING: OPERATOR MESSAGE(S) — unacknowledged"

_BANNER_FOOTER = (
    "YOU MUST ADDRESS THESE MESSAGES IN YOUR DIALOGUE CHANNEL BEFORE ISSUING "
    "ANY TOOL CALL.\n"
    "Include the marker [ACK:msg_id] in your response to acknowledge each "
    "message.\n"
    "If severity is HALT, cease work immediately and wait for the operator.\n"
    "If severity is QUESTION, answer and pause work until the operator says "
    "`continue`.\n"
    "If severity is INFO, acknowledge and continue work if appropriate."
)


def format_interrupt_banner(pending: list[OperatorMessage]) -> str:
    """Build the structured banner that injects into the top of the turn context.

    Returns an empty string when ``pending`` is empty so callers can use the
    return value directly to decide whether to prepend anything at all.
    """
    if not pending:
        return ""

    lines: list[str] = [_BANNER_HEADER, ""]
    for msg in pending:
        age = int(msg.age_seconds)
        lines.append(
            f"[{msg.severity.value.upper()}] msg_id: {msg.id}  (received {age}s ago)"
        )
        lines.append(f"> {msg.content}")
        lines.append("")
    lines.append(_BANNER_FOOTER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Turn-context injection helper
# ---------------------------------------------------------------------------


_CONTEXT_SEPARATOR = "\n\n---\n\n"


async def build_turn_context_with_inbox(
    inbox: OperatorInbox,
    base_context: str,
) -> str:
    """Return ``base_context`` with the inbox banner prepended if non-empty.

    This is the per-turn entry point the subprocess runner (claude_runner.py)
    will call from Sprint 4.8's wiring follow-up. It is intentionally a free
    function rather than a method on ``OperatorInbox`` so that it can be
    composed into existing context-assembly pipelines without a circular
    dependency between the inbox and the runner.
    """
    pending = await inbox.pending()
    banner = format_interrupt_banner(pending)
    if not banner:
        return base_context
    return f"{banner}{_CONTEXT_SEPARATOR}{base_context}"


# ---------------------------------------------------------------------------
# Sprint 4.11 — Severity classifier with operator override prefixes
# ---------------------------------------------------------------------------
#
# Operator-facing prefix syntax. Keep this block documented and exported
# so ``/help``-style commands can render the active rules without having
# to duplicate the list.
#
# HALT (work terminates, operator must resume):
#   - Whole-word bare triggers: ``halt``, ``stop``, ``pause``, ``cease``
#     (must be the entire message or followed by whitespace — substring
#     matches like ``halting`` or ``stopgap`` do NOT count)
#   - Unambiguous prefixes: ``/halt``, ``!halt`` (any following character
#     is allowed, including none)
#
# INFO (acknowledgment required, work may continue):
#   - ``!info ...``
#   - ``(info) ...``
#   - ``fyi: ...``
#   - ``fyi ...`` (with trailing space — ``fyi`` alone is ambiguous)
#
# QUESTION explicit (same as default, but documented for operator clarity):
#   - ``!q ...``
#   - ``(q) ...``
#
# Default when no trigger matches: QUESTION (safest — forces the agent
# to engage before continuing work).
#
# Classification precedence (highest severity wins): HALT > INFO > QUESTION.
# HALT is checked first because an operator who types ``halt fyi: stop the
# loop`` clearly wants work to stop, not to be logged as FYI.


# Whole-word HALT triggers. When ``classify_severity`` sees one of these,
# the message is HALT if it's either the entire (stripped, lowercased)
# text or if it's followed by whitespace — never if it's a substring of
# a larger word. This prevents ``halting the old pipeline is tricky``
# from being misclassified as a halt command.
_HALT_WORD_TRIGGERS: frozenset[str] = frozenset(
    {"halt", "stop", "pause", "cease"}
)

# Unambiguous HALT prefixes. These are treated as HALT regardless of what
# follows, because no English word starts with ``!halt`` or ``/halt``.
_HALT_PREFIX_TRIGGERS: tuple[str, ...] = ("!halt", "/halt")

# INFO prefixes. Each must be a proper prefix (optionally followed by
# content), and are checked in the order listed — the first match wins.
_INFO_PREFIXES: tuple[str, ...] = ("!info", "(info)", "fyi:", "fyi ")

# Whole-message conversational openers that should never trigger the
# QUESTION default. The operator typing "hi" five times in a row should
# not stack five BLOCK_QUESTION gate fires — these are dialogue, not
# requests for action. Matched against the entire stripped+lowercased
# message (no substring matching), so "hi there" still defaults to
# QUESTION but a bare "hi" maps to INFO. INFO still surfaces in the
# banner and audit history; it just emits the weakest gate decision.
#
# Issue #1557 extends the original PR #1534 set with Plan W's verbal-yes
# tokens (sure/yes/no/yep/nope/great/perfect/continue/go ahead/proceed/
# acknowledged). All eleven candidates are classified as INFO because:
#   1. They are conversational-acknowledgment tokens used in passing reply,
#      not operator directives carrying new work.
#   2. PR #1617 (merged 2026-05-11) made INFO never block tool calls, so
#      even if the operator types "proceed" mid-invocation it lands as
#      INFO + populates the banner — it does not gate.
#   3. The orientation confirm-pipeline (`is_confirm_message`) already
#      treats "yes" as a confirmation signal that must land as INFO for
#      the E3.3 promote-pending-focus path to fire.
_CONVERSATIONAL_OPENERS: frozenset[str] = frozenset(
    {
        # Original set (PR #1534)
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "ok",
        "okay",
        "k",
        "thanks",
        "thank you",
        "ty",
        "thx",
        "cool",
        "nice",
        "gotcha",
        "got it",
        "sounds good",
        "lgtm",
        "ack",
        "noted",
        # Issue #1557 extension (Plan W verbal-yes tokens)
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
    }
)


def classify_severity(content: str) -> MessageSeverity:
    """Assign a severity to an operator message based on content.

    Deterministic, side-effect-free, no I/O. Safe to call from any
    thread or coroutine without coordination.

    **Severity only (#1537).** This function classifies *how urgently the
    agent must respond* (HALT/INFO/QUESTION). It is intentionally orthogonal
    to *what the operator wants done* — that's intent classification, which
    lives in ``bridge.intent_classifier.classify``. The two surfaces share
    no regex patterns and must not be merged: severity triggers (``halt``,
    ``stop``, ``!info``, ``fyi:``, conversational openers) are disjoint
    from intent patterns (``build``, ``analyze``, ``fix``, ...).

    See the module-level constants and the docstring above them for
    the full rule set. In one line: HALT triggers win, then INFO
    prefixes, then QUESTION as the default.
    """
    text = content.strip().lower()
    if not text:
        return MessageSeverity.QUESTION

    # HALT — check unambiguous prefixes first
    for prefix in _HALT_PREFIX_TRIGGERS:
        if text.startswith(prefix):
            return MessageSeverity.HALT

    # HALT — whole-word bare triggers anywhere in the message.
    # We scan every whitespace-separated token (not just the first) so
    # multi-line messages and messages with leading pleasantries like
    # "please halt the pipeline" or "ok\nstop" still trigger HALT. The
    # substring safety guarantee is preserved because ``split()`` yields
    # whole tokens — ``"halting" in _HALT_WORD_TRIGGERS`` is False.
    #
    # The trade-off: a message like "stop the halting bug" will now
    # classify as HALT because the token ``stop`` is present. This is
    # deliberate — when a HALT-like word appears in operator text, the
    # safest reading is "pause work and confirm," not "assume context."
    # The false-positive cost (work briefly pauses, operator resumes)
    # is far smaller than the false-negative cost (work continues
    # through an emergency the operator was trying to halt).
    if any(tok in _HALT_WORD_TRIGGERS for tok in text.split()):
        return MessageSeverity.HALT

    # INFO prefixes
    for prefix in _INFO_PREFIXES:
        if text.startswith(prefix):
            return MessageSeverity.INFO

    # Conversational openers — whole-message match only.
    if text in _CONVERSATIONAL_OPENERS:
        return MessageSeverity.INFO

    # #2207 Part B — exploratory short-message heuristic.
    #
    # Conversational sessions often produce short partial thoughts that
    # don't match the opener whitelist but also aren't directives:
    # "I find that Anthropic...", "not sleeping quite yet", "interesting".
    # Pre-#2207 these fell through to QUESTION and could stack BLOCK_QUESTION
    # gate fires once 2+ accumulated.
    #
    # Heuristic: messages that are short (≤ 80 chars), contain no `?`, and
    # don't start with a recognised imperative verb are likely exploratory
    # — classify INFO. Real directives ("fix the bug", "build the thing",
    # "run the tests") still hit the imperative-prefix check and fall
    # through to QUESTION. Long messages and explicit questions also fall
    # through unchanged.
    if (
        len(text) <= 80
        and "?" not in text
        and not _starts_with_imperative_verb(text)
    ):
        return MessageSeverity.INFO

    # Default: QUESTION (safest — forces engagement)
    return MessageSeverity.QUESTION


# #2207 Part B — verbs that indicate the operator wants action. Kept narrow
# on purpose: the heuristic is for the "short partial thought" failure mode,
# not a general intent classifier (that lives in bridge.intent_classifier).
# When in doubt, fall through to QUESTION.
_IMPERATIVE_VERBS: frozenset[str] = frozenset(
    {
        "add",
        "analyze",
        "build",
        "check",
        "create",
        "debug",
        "delete",
        "deploy",
        "diagnose",
        "fix",
        "implement",
        "install",
        "investigate",
        "make",
        "merge",
        "migrate",
        "open",
        "rebuild",
        "refactor",
        "remove",
        "rename",
        "restart",
        "run",
        "ship",
        "show",
        "test",
        "update",
        "verify",
        "write",
    }
)


def _starts_with_imperative_verb(text: str) -> bool:
    """True iff the message's first token is a recognised imperative verb (#2207)."""
    first = text.split(maxsplit=1)
    if not first:
        return False
    return first[0] in _IMPERATIVE_VERBS
