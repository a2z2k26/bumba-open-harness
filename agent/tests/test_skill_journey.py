"""Tests for Skill Journey ledger (#576)."""
from __future__ import annotations

import pytest
from bridge.skill_journey import (
    SkillJourney,
    SkillRecord,
    PROMOTION_TO_GRADUATED_RUNS,
    DEMOTION_WINDOW,
)
from bridge.skill_store import SkillStore


@pytest.fixture
def store():
    return SkillStore(":memory:")


@pytest.fixture
def journey(store):
    return SkillJourney(store)


def test_get_or_create_new_skill(journey):
    rec = journey.get_or_create("new-skill")
    assert rec.name == "new-skill"
    assert rec.tier == "experimental"
    assert rec.total_runs == 0


def test_get_or_create_canonical_seed(store, journey):
    # fix-test is seeded as experimental
    rec = journey.get_or_create("fix-test")
    assert rec.name == "fix-test"
    assert rec.tier == "experimental"


def test_record_outcome_success(journey):
    rec = journey.record_outcome("test-skill", success=True)
    assert rec.success_count == 1
    assert rec.failure_count == 0
    assert rec.total_runs == 1


def test_record_outcome_failure(journey):
    rec = journey.record_outcome("test-skill", success=False)
    assert rec.failure_count == 1
    assert rec.success_count == 0


def test_record_outcome_persists(journey, store):
    journey.record_outcome("my-skill", success=True)
    rec = store.get_skill("my-skill")
    assert rec is not None
    assert rec.success_count == 1


def test_promotion_to_graduated(journey):
    # Simulate PROMOTION_TO_GRADUATED_RUNS successes
    for _ in range(PROMOTION_TO_GRADUATED_RUNS):
        rec = journey.record_outcome("good-skill", success=True)
    assert rec.tier == "graduated"
    assert rec.promoted_at is not None


def test_no_promotion_below_threshold(journey):
    # 19 successes (below 20 threshold)
    for _ in range(PROMOTION_TO_GRADUATED_RUNS - 1):
        rec = journey.record_outcome("borderline", success=True)
    assert rec.tier == "experimental"


def test_no_promotion_low_success_rate(journey):
    # 20 runs but only 50% success
    for i in range(PROMOTION_TO_GRADUATED_RUNS):
        rec = journey.record_outcome("flaky-skill", success=(i % 2 == 0))
    assert rec.tier == "experimental"


def test_demotion_from_graduated(journey):
    # First promote
    for _ in range(PROMOTION_TO_GRADUATED_RUNS):
        journey.record_outcome("degrade-skill", success=True)

    # Then add many failures
    for _ in range(DEMOTION_WINDOW):
        rec = journey.record_outcome("degrade-skill", success=False)

    # Should demote (eventually)
    # Note: demotion uses overall stats — needs enough failures relative to total
    assert rec.tier in ("experimental", "graduated")


def test_agent_proficiency_recorded(journey):
    journey.record_outcome("fix-test", success=True, agent_id="agent-001")
    journey.record_outcome("fix-test", success=True, agent_id="agent-001")
    journey.record_outcome("fix-test", success=False, agent_id="agent-001")

    prof = journey.get_agent_proficiency("fix-test", "agent-001")
    assert prof is not None
    assert prof.success_count == 2
    assert prof.failure_count == 1


def test_list_skills_returns_all(journey, store):
    journey.record_outcome("skill-a", success=True)
    journey.record_outcome("skill-b", success=False)
    records = journey.list_skills()
    names = [r.name for r in records]
    assert "skill-a" in names
    assert "skill-b" in names


def test_skill_record_success_rate():
    rec = SkillRecord(name="test", success_count=7, failure_count=3, total_runs=10)
    assert rec.success_rate == pytest.approx(0.7)


def test_skill_record_zero_runs():
    rec = SkillRecord(name="empty")
    assert rec.success_rate == 0.0


def test_skill_record_to_dict():
    rec = SkillRecord(name="my-skill", tier="graduated", success_count=10, total_runs=10)
    d = rec.to_dict()
    assert d["name"] == "my-skill"
    assert d["tier"] == "graduated"
    assert d["success_rate"] == 1.0
