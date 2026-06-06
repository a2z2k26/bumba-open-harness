"""
peer_ranking.py — extracted from bridge/deliberation.py (Sprint D1.8)

Peer-ranking helpers for the Strategy Board deliberation system.

Provides:
- Immutable data models: DeliberationConstraints, BoardMemberResponse,
  DeliberationRound, DeliberationState
- Anonymization helpers (Sprint 04.01 concept-only port):
  assign_anonymous_labels, anonymize_responses, deanonymize
- Strict FINAL RANKING parse contract (Sprint 04.02 concept-only port):
  FinalRanking, RankingParseError, parse_final_ranking
- Memo formatter: format_board_memo

These were previously in bridge/deliberation.py alongside the full
DeliberationArchiver and orchestration machinery. D1.8 extracts the
~250 LOC of helpers that are reusable outside the deliberation loop so
the remainder of the original module (and bridge/delegation.py) can be
deleted.

Sprint 04.01 and 04.02 are concept-only ports (no llm-council source
copied; that repo has no license). See original deliberation.py docstring
for design rationale.
"""
from __future__ import annotations

import random
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Literal, Sequence


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeliberationConstraints:
    """Guard rails for a deliberation session."""
    max_rounds: int = 5
    min_rounds: int = 1
    max_duration_minutes: float = 60.0
    max_cost_usd: float = 5.0


@dataclass(frozen=True)
class BoardMemberResponse:
    """A single board member's response in a deliberation round."""
    member_name: str
    round_number: int
    stance: str                  # SUPPORT | OPPOSE | CONDITIONAL | ABSTAIN
    reasoning: str
    key_concern: str = ""
    recommended_action: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "member_name": self.member_name,
            "round_number": self.round_number,
            "stance": self.stance,
            "reasoning": self.reasoning,
            "key_concern": self.key_concern,
            "recommended_action": self.recommended_action,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BoardMemberResponse":
        return cls(**data)


@dataclass(frozen=True)
class DeliberationRound:
    """All responses from one round of deliberation."""
    round_number: int
    question: str
    responses: tuple[BoardMemberResponse, ...] = ()
    synthesis: str = ""          # CEO's synthesis after collecting all responses
    resolved: bool = False       # CEO determined consensus reached

    @property
    def stance_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.responses:
            counts[r.stance] = counts.get(r.stance, 0) + 1
        return counts

    @property
    def has_consensus(self) -> bool:
        """True if all members share the same stance."""
        stances = {r.stance for r in self.responses if r.stance != "ABSTAIN"}
        return len(stances) <= 1 and bool(stances)

    def to_dict(self) -> dict:
        return {
            "round_number": self.round_number,
            "question": self.question,
            "responses": [r.to_dict() for r in self.responses],
            "synthesis": self.synthesis,
            "resolved": self.resolved,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeliberationRound":
        responses = tuple(
            BoardMemberResponse.from_dict(r) for r in data.get("responses", [])
        )
        return cls(
            round_number=data["round_number"],
            question=data["question"],
            responses=responses,
            synthesis=data.get("synthesis", ""),
            resolved=data.get("resolved", False),
        )


@dataclass(frozen=True)
class DeliberationState:
    """Full state of a deliberation session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    topic: str = ""
    framing: str = ""            # CEO's initial framing of the question
    rounds: tuple[DeliberationRound, ...] = ()
    constraints: DeliberationConstraints = field(
        default_factory=DeliberationConstraints
    )
    decision: str = ""           # Final decision after deliberation closes
    status: str = "open"         # open | closed | timeout | budget_exceeded
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    closed_at: str = ""
    total_cost_usd: float = 0.0
    thinking_modality: str = ""  # Active modality (Sprint 18)

    @property
    def current_round_number(self) -> int:
        return len(self.rounds)

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def can_close(self) -> bool:
        """Minimum rounds met and last round is resolved or max rounds hit."""
        if self.current_round_number < self.constraints.min_rounds:
            return False
        if self.rounds and self.rounds[-1].resolved:
            return True
        return self.current_round_number >= self.constraints.max_rounds

    @property
    def budget_exceeded(self) -> bool:
        return self.total_cost_usd >= self.constraints.max_cost_usd

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "topic": self.topic,
            "framing": self.framing,
            "rounds": [r.to_dict() for r in self.rounds],
            "constraints": {
                "max_rounds": self.constraints.max_rounds,
                "min_rounds": self.constraints.min_rounds,
                "max_duration_minutes": self.constraints.max_duration_minutes,
                "max_cost_usd": self.constraints.max_cost_usd,
            },
            "decision": self.decision,
            "status": self.status,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
            "total_cost_usd": self.total_cost_usd,
            "thinking_modality": self.thinking_modality,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeliberationState":
        rounds = tuple(
            DeliberationRound.from_dict(r) for r in data.get("rounds", [])
        )
        constraints_data = data.get("constraints", {})
        constraints = DeliberationConstraints(**constraints_data) if constraints_data else DeliberationConstraints()
        return cls(
            session_id=data.get("session_id", str(uuid.uuid4())[:12]),
            topic=data.get("topic", ""),
            framing=data.get("framing", ""),
            rounds=rounds,
            constraints=constraints,
            decision=data.get("decision", ""),
            status=data.get("status", "open"),
            created_at=data.get("created_at", ""),
            closed_at=data.get("closed_at", ""),
            total_cost_usd=data.get("total_cost_usd", 0.0),
            thinking_modality=data.get("thinking_modality", ""),
        )


# ── Anonymization (Sprint 04.01) ──────────────────────────────────────────────
#
# Concept-only port (no llm-council source copied; that repo has no license).
# When the Board enters a peer-ranking round, each member's response is
# presented to peers under an anonymous label ("A", "B", "C", …) instead of
# the producing agent's name. This removes identity bias from peer ranking.
# The CEO synthesis round, and audit logs, still receive identity-keyed data.
#
# Properties enforced by the helpers below:
#   * Deterministic: same (responses, seed) → same mapping. No mutation of the
#     input tuple — frozen dataclasses are rebuilt with ``dataclasses.replace``.
#   * Per-round freshness: seed-driven shuffle keeps two distinct deliberations
#     (or two rounds with different seeds) from ever sharing a mapping.
#   * Round-trip safety: ``deanonymize`` inverts the label-keyed ranking back
#     to identity-keyed output for the synthesizer.
#   * Flag-OFF preservation: the existing ``format_board_memo`` output is
#     byte-for-byte identical when ``anonymize=False`` (the default).


def _label_for_index(idx: int) -> str:
    """Return the anonymous label for the i-th member (0 → 'A', 1 → 'B', …).

    Wraps to 'AA', 'AB', … for boards with >26 members; in practice the Board
    is bounded at ~7 members but the encoding is unbounded.
    """
    if idx < 0:
        raise ValueError(f"label index must be >= 0, got {idx}")
    letters = []
    n = idx
    while True:
        letters.append(chr(ord("A") + (n % 26)))
        n = n // 26 - 1
        if n < 0:
            break
    return "".join(reversed(letters))


def assign_anonymous_labels(
    responses: Sequence[BoardMemberResponse],
    seed: int,
) -> dict[str, str]:
    """Return a deterministic ``{member_name: label}`` mapping for one round.

    The mapping is a per-round veil: callers MUST NOT persist or reuse it
    across rounds. Determinism comes from sorting member names before applying
    the seeded shuffle, so the same ``(responses, seed)`` always produces the
    same mapping regardless of input order.

    Members with duplicate ``member_name`` collapse to a single entry — the
    Board treats one identity as one voice, even if a member somehow appears
    in two rows of a single round.
    """
    # Sort first so input order doesn't change the mapping (determinism).
    unique_names = sorted({r.member_name for r in responses})
    rng = random.Random(seed)
    shuffled = list(unique_names)
    rng.shuffle(shuffled)
    return {name: _label_for_index(idx) for idx, name in enumerate(shuffled)}


def anonymize_responses(
    responses: tuple[BoardMemberResponse, ...],
    seed: int,
) -> tuple[tuple[BoardMemberResponse, ...], dict[str, str]]:
    """Return ``(anonymized_responses, label_to_name)`` for a peer-ranking round.

    The anonymized responses replace ``member_name`` with the assigned label.
    Frozen-ness is preserved via ``dataclasses.replace``; the original tuple
    is never mutated.

    The returned mapping is keyed ``label → real_member_name`` so the
    synthesizer can de-anonymize a ranking like ``["A", "C", "B"]``.
    """
    name_to_label = assign_anonymous_labels(responses, seed)
    label_to_name = {label: name for name, label in name_to_label.items()}
    anonymized = tuple(
        replace(r, member_name=name_to_label[r.member_name]) for r in responses
    )
    return anonymized, label_to_name


def deanonymize(ranking: list[str], mapping: dict[str, str]) -> list[str]:
    """Convert a label-keyed ranking back to identity-keyed names.

    ``mapping`` is the ``label_to_name`` dict produced by
    :func:`anonymize_responses`. Unknown labels are passed through unchanged
    so a malformed ranker output cannot silently drop members.
    """
    return [mapping.get(label, label) for label in ranking]


# ── FINAL RANKING parse contract (Sprint 04.02) ───────────────────────────────
#
# Concept-only port (no llm-council source copied; that repo has no license).
# After the Board peer-ranks each other's responses, the consolidating model
# emits its ranking after a literal ``FINAL RANKING:`` sentinel. The text
# before the sentinel is reasoning; only the list after it is the actual
# ranking. ``parse_final_ranking`` enforces a strict contract:
#
#   * The sentinel must appear on its own line (regex: ``^\s*FINAL\s+RANKING\s*:\s*$``).
#   * If the sentinel appears more than once, the LAST occurrence wins — earlier
#     mentions are treated as reasoning ("e.g. I now produce my FINAL RANKING:").
#   * The list after the sentinel may be comma-separated, newline-separated, or
#     a numbered list (``1. A\n2. B\n3. C``). Whitespace and trailing/leading
#     numbering markers are stripped per token.
#   * The parsed labels must be a subset of ``valid_labels`` (no unknown labels)
#     and must not repeat (no duplicates).
#
# Failures return a structured ``RankingParseError`` rather than raising —
# the caller decides whether to re-prompt, fall back to legacy parsing, or
# escalate. This keeps the parser side-effect-free and easy to test.

# Sentinel regex: literal "FINAL RANKING:" anchored to start-of-line.
#
# The user-facing rule is "on its own line OR with surrounding whitespace" —
# we accept both ``FINAL RANKING:\nA\nB\nC`` (own line) and
# ``FINAL RANKING: A, B, C`` (same line as the list). The colon is required.
# Anchoring with ``^`` (multiline) plus the leading-whitespace allowance keeps
# inline prose mentions like ``"I will produce my FINAL RANKING:"`` from
# tripping the sentinel — those are mid-line, not start-of-line.
#
# ``re.IGNORECASE`` is intentionally NOT applied — the spec is case-sensitive
# so prose mentions like "final ranking" never count.
_FINAL_RANKING_SENTINEL = re.compile(r"(?m)^\s*FINAL\s+RANKING\s*:")

# Per-token leading numbering markers to strip: ``1.``, ``1)``, ``1:``, or
# bullets like ``- A`` / ``* A``. The token *value* is whatever remains after
# the marker is removed.
_LEADING_MARKER = re.compile(r"^\s*(?:\d+\s*[.\):]|[-*•])\s*")


@dataclass(frozen=True)
class FinalRanking:
    """A successfully parsed ``FINAL RANKING:`` block.

    ``ordered_labels`` is the rank order extracted from the post-sentinel list.
    ``raw_text`` is the text that followed the sentinel (preserved verbatim
    for audit / debugging — callers should not parse it again).
    """
    ordered_labels: tuple[str, ...]
    raw_text: str


@dataclass(frozen=True)
class RankingParseError:
    """Structured parse failure. Returned (not raised) by ``parse_final_ranking``.

    ``reason`` is a stable enum the caller can branch on without string
    matching. ``detail`` carries human-readable context (e.g. the offending
    label for ``unknown_label``). ``raw_text`` is the input ``text`` so the
    caller can log or attach it to a re-prompt.
    """
    reason: Literal["missing_token", "empty_list", "unknown_label", "duplicate_label"]
    detail: str
    raw_text: str


def parse_final_ranking(
    text: str,
    valid_labels: Sequence[str],
) -> FinalRanking | RankingParseError:
    """Parse a model output and extract the rank order after ``FINAL RANKING:``.

    Returns:
        ``FinalRanking`` on success, ``RankingParseError`` on any failure.
        Never raises — the caller decides between retry and fallback.

    Args:
        text: Full model output to parse.
        valid_labels: The label set this ranking must draw from (anonymous
            ``A``/``B``/``C`` labels per Sprint 04.01, or real member names if
            the anonymization flag is OFF). Order does not matter.

    Behavior:
        * Finds the LAST occurrence of ``FINAL RANKING:`` (case-sensitive,
          on its own line) — earlier mentions are treated as reasoning.
        * Splits the post-sentinel text on commas and newlines.
        * Strips leading numbering markers (``1.``, ``1)``, ``-``, ``*``) and
          surrounding whitespace from each token.
        * Drops empty tokens after stripping.
        * Validates: non-empty, all labels in ``valid_labels``, no duplicates.
    """
    valid_set = frozenset(valid_labels)

    # Find the LAST sentinel occurrence. ``finditer`` is O(n); cheaper than
    # split-on-pattern for typical outputs (<<10kB).
    matches = list(_FINAL_RANKING_SENTINEL.finditer(text))
    if not matches:
        return RankingParseError(
            reason="missing_token",
            detail="literal 'FINAL RANKING:' sentinel not found on its own line",
            raw_text=text,
        )

    last = matches[-1]
    post = text[last.end():]

    # Tokenize: split on newlines and commas (either delimiter; both are
    # idiomatic in model outputs). Empty fragments after the split are
    # dropped, so trailing newlines / a single trailing comma are tolerated.
    raw_tokens = re.split(r"[,\n]", post)
    cleaned: list[str] = []
    for raw in raw_tokens:
        token = _LEADING_MARKER.sub("", raw).strip()
        if not token:
            continue
        cleaned.append(token)

    if not cleaned:
        return RankingParseError(
            reason="empty_list",
            detail="no labels found after 'FINAL RANKING:' sentinel",
            raw_text=text,
        )

    seen: set[str] = set()
    for token in cleaned:
        if token not in valid_set:
            return RankingParseError(
                reason="unknown_label",
                detail=f"label {token!r} not in valid set {sorted(valid_set)!r}",
                raw_text=text,
            )
        if token in seen:
            return RankingParseError(
                reason="duplicate_label",
                detail=f"label {token!r} appears more than once",
                raw_text=text,
            )
        seen.add(token)

    return FinalRanking(
        ordered_labels=tuple(cleaned),
        raw_text=post,
    )


# ── Memo format ───────────────────────────────────────────────────────────────

def format_board_memo(state: DeliberationState, *, anonymize: bool = False, seed: int | None = None) -> str:
    """
    Format a completed deliberation as a board memo.

    Structure: Decision, board stances, thinking modality, resolved/unresolved
    tensions, recommendations, next actions.

    When ``anonymize=True`` (Sprint 04.01, gated by ``board_v2_enabled``), the
    last round's member names are replaced with stable per-call labels
    ("A", "B", "C", …) so the memo can be circulated for peer ranking without
    leaking identities. ``seed`` controls the label assignment; if omitted,
    the seed is derived from ``state.session_id`` so the mapping is stable
    across re-renders of the same deliberation but differs between sessions.

    Default ``anonymize=False`` preserves the existing memo output byte-for-byte
    so flag-OFF callers see no change.
    """
    # Build a label-substitution view of the last round's responses if the
    # caller asked for anonymization. The state itself is never mutated.
    anon_mapping: dict[str, str] = {}
    if anonymize and state.rounds and state.rounds[-1].responses:
        if seed is None:
            # Stable per-deliberation default seed when none is supplied.
            seed = abs(hash(state.session_id)) % (2**31)
        last = state.rounds[-1]
        _, label_to_name = anonymize_responses(last.responses, seed)
        anon_mapping = {real: label for label, real in label_to_name.items()}

    def _display_name(member_name: str) -> str:
        return anon_mapping.get(member_name, member_name) if anon_mapping else member_name

    lines = [
        "# Board Deliberation Memo",
        f"**Topic:** {state.topic}",
        f"**Session:** {state.session_id}",
        f"**Status:** {state.status.upper()}",
        f"**Rounds:** {state.current_round_number}",
        f"**Cost:** ${state.total_cost_usd:.4f}",
        "",
    ]

    if state.thinking_modality:
        lines += [f"**Thinking Modality:** {state.thinking_modality}", ""]

    lines += ["## Decision", state.decision or "_Pending_", ""]

    # Board stances from last round
    if state.rounds:
        last_round = state.rounds[-1]
        lines += ["## Board Stances"]
        for response in last_round.responses:
            lines.append(
                f"- **{_display_name(response.member_name)}** [{response.stance}]: {response.reasoning[:200]}"
            )
        lines.append("")

        # Tensions
        stances = {r.stance for r in last_round.responses if r.stance != "ABSTAIN"}
        if len(stances) > 1:
            lines += ["## Unresolved Tensions"]
            opposing = [r for r in last_round.responses if r.stance in ("OPPOSE", "CONDITIONAL")]
            for r in opposing:
                if r.key_concern:
                    lines.append(f"- {_display_name(r.member_name)}: {r.key_concern}")
            lines.append("")
        else:
            lines += ["## Tensions", "_Consensus reached — no unresolved tensions._", ""]

    # Synthesis from each round
    lines += ["## Round Syntheses"]
    for rnd in state.rounds:
        if rnd.synthesis:
            lines.append(f"**Round {rnd.round_number}:** {rnd.synthesis}")
    lines.append("")

    lines += ["## Next Actions"]
    if state.rounds:
        for response in state.rounds[-1].responses:
            if response.recommended_action:
                lines.append(f"- [{_display_name(response.member_name)}] {response.recommended_action}")
    if not any(r.recommended_action for r in (state.rounds[-1].responses if state.rounds else [])):
        lines.append("_No specific actions recommended._")

    return "\n".join(lines)
