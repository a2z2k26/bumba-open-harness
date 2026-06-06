"""Tests for structured plan state."""
from __future__ import annotations

import pytest
from bridge.plan_state import PlanStep, PlanState


class TestPlanStep:
    def test_defaults_to_pending(self):
        step = PlanStep(id="s1", title="Write tests")
        assert step.status == "pending"

    def test_frozen(self):
        step = PlanStep(id="s1", title="Write tests")
        with pytest.raises(AttributeError):
            step.status = "completed"  # type: ignore[misc]

    def test_dependencies_stored_as_tuple(self):
        step = PlanStep(id="s2", title="Implement", dependencies=["s1"])
        assert isinstance(step.dependencies, tuple)
        assert step.dependencies == ("s1",)

    def test_no_dependencies_by_default(self):
        step = PlanStep(id="s1", title="First step")
        assert step.dependencies == ()

    def test_checkpoint_defaults_none(self):
        step = PlanStep(id="s1", title="First step")
        assert step.checkpoint is None


class TestPlanState:
    def test_create_plan(self):
        plan = PlanState.create(
            title="Implement verification",
            project="bumba-open-harness",
            steps=[
                PlanStep(id="s1", title="Write tests"),
                PlanStep(id="s2", title="Implement module", dependencies=("s1",)),
                PlanStep(id="s3", title="Wire integration", dependencies=("s2",)),
            ],
        )
        assert plan.plan_id != ""
        assert len(plan.steps) == 3
        assert plan.current_step_id is None

    def test_plan_is_frozen(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        with pytest.raises(AttributeError):
            plan.title = "Changed"  # type: ignore[misc]

    def test_advance_step_returns_new_state(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[
                PlanStep(id="s1", title="Step 1"),
                PlanStep(id="s2", title="Step 2", dependencies=("s1",)),
            ],
        )
        updated = plan.advance("s1", "completed", checkpoint="Tests written and passing")
        assert updated is not plan  # New instance
        assert updated.get_step("s1").status == "completed"
        assert updated.get_step("s1").checkpoint == "Tests written and passing"

    def test_advance_does_not_mutate_original(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        plan.advance("s1", "completed")
        assert plan.get_step("s1").status == "pending"

    def test_advance_in_progress_sets_started_at(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        updated = plan.advance("s1", "in_progress")
        assert updated.get_step("s1").started_at is not None

    def test_advance_completed_sets_completed_at(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        updated = plan.advance("s1", "completed")
        assert updated.get_step("s1").completed_at is not None

    def test_advance_invalid_status_raises(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        with pytest.raises(ValueError, match="Invalid step status"):
            plan.advance("s1", "flying")

    def test_advance_unknown_step_raises(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        with pytest.raises(KeyError):
            plan.advance("s999", "completed")

    def test_next_actionable_respects_dependencies(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[
                PlanStep(id="s1", title="Step 1"),
                PlanStep(id="s2", title="Step 2", dependencies=("s1",)),
            ],
        )
        # s1 has no dependencies, so it's next
        next_step = plan.next_actionable()
        assert next_step is not None
        assert next_step.id == "s1"

        # After completing s1, s2 becomes next
        updated = plan.advance("s1", "completed")
        next_step = updated.next_actionable()
        assert next_step is not None
        assert next_step.id == "s2"

    def test_all_completed_returns_none_for_next(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        updated = plan.advance("s1", "completed")
        assert updated.next_actionable() is None

    def test_next_actionable_skips_blocked(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[
                PlanStep(id="s1", title="Step 1"),
                PlanStep(id="s2", title="Step 2"),
            ],
        )
        updated = plan.advance("s1", "blocked")
        # s1 is blocked (not pending), s2 is pending with no deps
        next_step = updated.next_actionable()
        assert next_step is not None
        assert next_step.id == "s2"

    def test_serialization_roundtrip(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[
                PlanStep(id="s1", title="Step 1"),
                PlanStep(id="s2", title="Step 2", dependencies=("s1",)),
            ],
        )
        data = plan.to_dict()
        restored = PlanState.from_dict(data)
        assert restored.plan_id == plan.plan_id
        assert len(restored.steps) == len(plan.steps)
        assert restored.steps[1].dependencies == ("s1",)

    def test_serialization_preserves_checkpoint(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        updated = plan.advance("s1", "completed", checkpoint="Done and verified")
        data = updated.to_dict()
        restored = PlanState.from_dict(data)
        assert restored.get_step("s1").checkpoint == "Done and verified"

    def test_save_and_load(self, tmp_path):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        plan.save(str(tmp_path))
        loaded = PlanState.load(plan.plan_id, str(tmp_path))
        assert loaded is not None
        assert loaded.plan_id == plan.plan_id

    def test_load_missing_returns_none(self, tmp_path):
        result = PlanState.load("nonexistent-id", str(tmp_path))
        assert result is None

    def test_get_step_raises_for_unknown(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[PlanStep(id="s1", title="Step 1")],
        )
        with pytest.raises(KeyError):
            plan.get_step("unknown")

    def test_multi_dependency_step(self):
        plan = PlanState.create(
            title="Test plan",
            project="test",
            steps=[
                PlanStep(id="s1", title="Step 1"),
                PlanStep(id="s2", title="Step 2"),
                PlanStep(id="s3", title="Step 3", dependencies=("s1", "s2")),
            ],
        )
        # s3 requires both s1 and s2
        next_step = plan.next_actionable()
        assert next_step.id in ("s1", "s2")

        # Complete s1 — s3 still blocked by s2
        updated = plan.advance("s1", "completed")
        next_step = updated.next_actionable()
        assert next_step.id == "s2"

        # Complete s2 — s3 now unblocked
        updated = updated.advance("s2", "completed")
        next_step = updated.next_actionable()
        assert next_step is not None
        assert next_step.id == "s3"
