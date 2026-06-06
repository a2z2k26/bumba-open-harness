"""Smoke tests for agent/config/system-prompt.md.

Sprint 4.12 — Phase 4B (Dialogue-First Communication Architecture).

The system prompt is a Tier C file (operator-only modifications). These
tests are a drift-detection tripwire: they confirm the prompt file is
present, well-formed, versioned, and contains the Sprint 4.12
dialogue-first doctrine that the 4.8/4.9/4.10/4.11 structural gates
depend on to behave consistently with the agent's understanding.

These are file-level smoke tests, not subprocess tests. We do not spawn
``claude -p`` here because (a) it's slow, (b) it requires live auth,
and (c) the acceptance criterion from the sprint spec is "a fresh
subprocess loads the new prompt," which is equivalent to "the file is
valid and on disk at the expected path." If the bridge can read the
file, Claude Code can load it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Path resolution from agent/tests/<f>.py:
#   parent (agent/tests) → parent (agent/) → config/system-prompt.md
# This file was migrated from root /tests/ in Sprint 00.04 — at the old
# location parent.parent was repo root, so /agent/config was correct.
# Now that it lives in agent/tests/, parent.parent is already agent/,
# so the leading "agent" segment must be dropped.
PROMPT_PATH = Path(__file__).resolve().parent.parent / "config" / "system-prompt.md"


@pytest.fixture(scope="module")
def prompt_text() -> str:
    assert PROMPT_PATH.exists(), f"system-prompt.md missing at {PROMPT_PATH}"
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert text, "system-prompt.md is empty"
    return text


# ---------------------------------------------------------------------------
# Existence + basic shape
# ---------------------------------------------------------------------------


def test_prompt_file_exists(prompt_text: str):
    assert len(prompt_text) > 500  # sanity: not truncated to nothing


def test_prompt_has_version_marker(prompt_text: str):
    """The version comment at the top is load-bearing for drift detection."""
    assert "<!-- system-prompt version:" in prompt_text
    # Sprint 0.2 (audit-followup) is the most recent edit. The marker is
    # bumped on every Tier C change so drift detection can compare against
    # the expected latest sprint.
    assert "sprint-0.2" in prompt_text


def test_prompt_still_has_zone_architecture_section(prompt_text: str):
    """Regression guard: we added a new section but must not have
    displaced the existing Zone Architecture / Master Functions
    structure.
    """
    assert "## Zone Architecture" in prompt_text
    assert "## 15 Master Functions" in prompt_text
    assert "## Self-Improvement Tiers" in prompt_text
    assert "## Dialogue-First Doctrine" in prompt_text
    assert "## Numerical Claims" in prompt_text
    assert "## Operational Defaults" in prompt_text
    assert "## Non-Negotiables" in prompt_text


# ---------------------------------------------------------------------------
# Sprint 4.12 — Dialogue-First Doctrine section
# ---------------------------------------------------------------------------


def test_prompt_contains_dialogue_first_doctrine_section(prompt_text: str):
    assert "## Dialogue-First Doctrine" in prompt_text


def test_prompt_contains_priority_hierarchy(prompt_text: str):
    assert "### Priority hierarchy" in prompt_text
    # Core principles must be present
    assert "Operator dialogue is your highest priority" in prompt_text
    assert "Work is always interruptible" in prompt_text
    assert "Natural-language conversation is your default mode" in prompt_text
    assert "False claims of success are the worst possible failure mode" in prompt_text
    assert "Silence is suspicious" in prompt_text


def test_prompt_describes_three_output_channels(prompt_text: str):
    assert "### Output channels" in prompt_text
    assert "**dialogue**" in prompt_text
    assert "**milestone**" in prompt_text
    assert "**trace**" in prompt_text
    # Tool-call narration rule is a load-bearing anti-pattern to document
    assert "Do not narrate your own tool calls in dialogue" in prompt_text


def test_prompt_documents_ack_marker_contract(prompt_text: str):
    assert "### Acknowledging operator messages" in prompt_text
    assert "[ACK:msg_id]" in prompt_text
    # The gate reference is important — the agent should know the contract
    # is machine-checkable, not soft politeness.
    assert "tool-call gate" in prompt_text or "Sprint 4.10" in prompt_text


def test_prompt_documents_three_severity_levels(prompt_text: str):
    assert "### Severity levels" in prompt_text
    assert "INFO" in prompt_text
    assert "QUESTION" in prompt_text
    assert "HALT" in prompt_text
    # HALT must be explicit that ack alone doesn't resume
    halt_section = prompt_text.split("**HALT**")[1].split("###")[0]
    assert "Only the operator can resume" in halt_section
    assert "does not restart work" in halt_section


def test_prompt_has_why_this_exists_rationale(prompt_text: str):
    """The 'why' paragraph explains the doctrine so the agent applies it
    in edge cases the structural gates don't cover.
    """
    assert "### Why this doctrine exists" in prompt_text
    assert "Sprint 4.12" in prompt_text
    # Links back to the enabling sprints
    assert "4.8" in prompt_text
    assert "4.11" in prompt_text


# ---------------------------------------------------------------------------
# Redundancy cleanup — Sprint 4.12 consolidated duplicate bullets
# ---------------------------------------------------------------------------


def test_operator_priority_is_not_duplicated_between_sections(prompt_text: str):
    """Regression guard: the old bullet 'Operator messages always take
    priority' under Response discipline has been removed because the
    Dialogue-First Doctrine supersedes it. Having both would be
    confusing and drift-prone.
    """
    # The doctrine's canonical phrasing remains
    assert "Operator dialogue is your highest priority" in prompt_text
    # The legacy duplicate in Response discipline should be gone
    assert "**Operator messages always take priority.**" not in prompt_text
    assert "**Answer first, act second.**" not in prompt_text


def test_response_discipline_points_to_doctrine(prompt_text: str):
    """The Response discipline block should explicitly note that priority
    now lives in the doctrine section, not duplicate it.
    """
    # Find the Response discipline subsection
    assert "Response discipline:" in prompt_text
    disc_start = prompt_text.index("Response discipline:")
    disc_block = prompt_text[disc_start : disc_start + 500]
    assert "Dialogue-First Doctrine" in disc_block


# ---------------------------------------------------------------------------
# No broken references — anchors, paths, and names used in the doctrine
# ---------------------------------------------------------------------------


def test_doctrine_references_match_existing_sprint_ids(prompt_text: str):
    """The doctrine cites 4.8, 4.9, 4.10, 4.11. Regression guard for
    accidental typos like '4.08' or missing references.
    """
    assert "Sprint 4.8" in prompt_text or "4.8 " in prompt_text
    assert "Sprint 4.9" in prompt_text or "4.9 " in prompt_text
    assert "Sprint 4.10" in prompt_text or "4.10 " in prompt_text
    assert "Sprint 4.11" in prompt_text or "4.11 " in prompt_text


# ---------------------------------------------------------------------------
# Sprint 0.2 — Numerical Claims section
# ---------------------------------------------------------------------------


def test_prompt_contains_numerical_claims_section(prompt_text: str):
    """Sprint 0.2 added a soft guardrail for numerical claims. The section
    must exist as a top-level header so the model parses it as a peer of
    the Dialogue-First Doctrine, not as a subsection.
    """
    assert "## Numerical Claims" in prompt_text


def test_prompt_documents_numerical_claims_rules(prompt_text: str):
    """All four hard rules from Sprint 0.2 Step 7A must be present in
    the section. Each one is the load-bearing claim of the section.
    """
    assert "### Rules" in prompt_text
    # Rule 1 — grounding requirement
    assert "Never give a precise integer from memory or session context" in prompt_text
    # Rule 2 — qualifier preservation
    assert "Approximate qualifiers" in prompt_text
    assert "part of the claim" in prompt_text
    # Rule 3 — fresh measurement wins
    assert "fresh measurement always wins" in prompt_text
    # Rule 4 — re-measure when operator action depends
    assert "re-measure first" in prompt_text


def test_prompt_has_numerical_claims_examples(prompt_text: str):
    """Examples are not optional decoration — they're the calibration
    signal for the model. Specifically, the 259-files example is
    present because that's the case the section was written about.
    """
    assert "### Examples" in prompt_text
    # The 259 example must be present (the originating incident)
    assert "259 missing files" in prompt_text or "~259" in prompt_text


def test_prompt_has_numerical_claims_why_rationale(prompt_text: str):
    """The 'why' paragraph anchors the rule in a specific past failure
    so the model can recognize the same pattern in new situations.
    """
    assert "### Why this section exists" in prompt_text
    assert "Sprint 0.2" in prompt_text
    # The actual count being ~37 vs the claimed ~259 is the corrective fact
    assert "37" in prompt_text
