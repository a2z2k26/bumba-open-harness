"""Tests for Dojo ranking — trust_score per-skill proficiency (#580)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from bridge.trust_score import TrustScoreEngine
from bridge.skill_store import SkillStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> TrustScoreEngine:
    """Create a TrustScoreEngine pre-wired with an in-memory SkillStore."""
    engine = TrustScoreEngine()
    engine.set_skill_store(SkillStore(":memory:"))
    return engine


# ---------------------------------------------------------------------------
# get_skill_proficiency
# ---------------------------------------------------------------------------

def test_get_skill_proficiency_default_unseen():
    engine = _make_engine()
    score = engine.get_skill_proficiency("agent-001", "fix-test")
    assert score == pytest.approx(0.5)


def test_get_skill_proficiency_after_record():
    engine = _make_engine()
    engine.record_skill_outcome("agent-001", "fix-test", success=True)
    engine.record_skill_outcome("agent-001", "fix-test", success=True)
    engine.record_skill_outcome("agent-001", "fix-test", success=False)
    score = engine.get_skill_proficiency("agent-001", "fix-test")
    # 2 successes, 1 failure -> 2/3 ≈ 0.667
    assert score == pytest.approx(2 / 3, abs=0.01)


def test_get_skill_proficiency_zero_score_after_failures():
    engine = _make_engine()
    for _ in range(5):
        engine.record_skill_outcome("agent-bad", "ship-feature", success=False)
    score = engine.get_skill_proficiency("agent-bad", "ship-feature")
    assert score == pytest.approx(0.0)


def test_get_skill_proficiency_perfect_score():
    engine = _make_engine()
    for _ in range(10):
        engine.record_skill_outcome("agent-great", "review-pr", success=True)
    score = engine.get_skill_proficiency("agent-great", "review-pr")
    assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# record_skill_outcome
# ---------------------------------------------------------------------------

def test_record_skill_outcome_increments_counts():
    engine = _make_engine()
    engine.record_skill_outcome("ag-1", "fix-test", success=True)
    engine.record_skill_outcome("ag-1", "fix-test", success=True)
    engine.record_skill_outcome("ag-1", "fix-test", success=False)
    score = engine.get_skill_proficiency("ag-1", "fix-test")
    assert 0.6 < score < 0.7


def test_record_skill_outcome_multiple_agents_isolated():
    engine = _make_engine()
    engine.record_skill_outcome("agent-a", "fix-test", success=True)
    engine.record_skill_outcome("agent-b", "fix-test", success=False)

    score_a = engine.get_skill_proficiency("agent-a", "fix-test")
    score_b = engine.get_skill_proficiency("agent-b", "fix-test")
    assert score_a > score_b


def test_record_skill_outcome_multiple_skills_isolated():
    engine = _make_engine()
    engine.record_skill_outcome("agent-x", "fix-test", success=True)
    engine.record_skill_outcome("agent-x", "deploy", success=False)

    ft = engine.get_skill_proficiency("agent-x", "fix-test")
    dep = engine.get_skill_proficiency("agent-x", "deploy")
    assert ft > dep


# ---------------------------------------------------------------------------
# set_skill_store delegation
# ---------------------------------------------------------------------------

def test_set_skill_store_delegates_get():
    engine = _make_engine()
    mock_store = MagicMock()
    mock_store.get_agent_proficiency.return_value = MagicMock(
        success_count=8,
        failure_count=2,
        success_rate=0.8,
    )
    engine.set_skill_store(mock_store)
    score = engine.get_skill_proficiency("agent-1", "fix-test")
    assert score == pytest.approx(0.8)
    mock_store.get_agent_proficiency.assert_called_once_with("fix-test", "agent-1")


def test_set_skill_store_delegates_record():
    engine = _make_engine()
    mock_store = MagicMock()
    mock_store.get_agent_proficiency.return_value = None
    engine.set_skill_store(mock_store)
    engine.record_skill_outcome("agent-1", "fix-test", success=True)
    mock_store.upsert_agent_proficiency.assert_called_once()


def test_set_skill_store_null_proficiency_returns_default():
    engine = _make_engine()
    mock_store = MagicMock()
    mock_store.get_agent_proficiency.return_value = None
    engine.set_skill_store(mock_store)
    score = engine.get_skill_proficiency("agent-unknown", "unknown-skill")
    assert score == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Integration with SkillJourney (S15 + S11 combined)
# ---------------------------------------------------------------------------

def test_trust_engine_and_skill_journey_record_together():
    from bridge.skill_journey import SkillJourney
    from bridge.skill_store import SkillStore

    store = SkillStore(":memory:")
    journey = SkillJourney(store)
    engine = _make_engine()

    # Wire them together
    journey.set_trust_manager(engine)

    # Record some outcomes through the journey
    journey.record_outcome("fix-test", success=True, agent_id="agent-001")
    journey.record_outcome("fix-test", success=True, agent_id="agent-001")
    journey.record_outcome("fix-test", success=False, agent_id="agent-001")

    prof = journey.get_agent_proficiency("fix-test", "agent-001")
    assert prof is not None
    assert prof.success_count == 2
    assert prof.failure_count == 1


def test_dojo_floor_gating_logic():
    """Simulate the dispatcher checking skill floor against agent proficiency."""
    engine = _make_engine()

    # An agent with no history gets 0.5 default
    score = engine.get_skill_proficiency("new-agent", "fix-test")
    floor = 0.0
    assert score >= floor  # Default 0.5 passes a 0.0 floor

    # A strict floor
    strict_floor = 0.8
    assert score < strict_floor  # 0.5 does NOT pass 0.8 floor


def test_proficiency_persists_across_records():
    engine = _make_engine()
    for i in range(10):
        engine.record_skill_outcome("ag", "skill", success=(i < 7))  # 7/10

    score = engine.get_skill_proficiency("ag", "skill")
    assert score == pytest.approx(0.7, abs=0.05)
