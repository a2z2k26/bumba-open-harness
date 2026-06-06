"""Tests for Zone 4 workflow YAML schema and validator (sprint F-W.1)."""

from __future__ import annotations

import textwrap

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from config.workflows._schema import (  # noqa: E402
    ActionStep,
    DepartmentStep,
    GateStep,
    WorkflowBudget,
    WorkflowConfig,
    load_workflow_config,
)


# ---------------------------------------------------------------------------
# WorkflowBudget
# ---------------------------------------------------------------------------


class TestWorkflowBudget:
    def test_defaults(self) -> None:
        b = WorkflowBudget()
        assert b.max_cost_usd == 5.0
        assert b.max_duration_seconds == 600

    def test_custom_values(self) -> None:
        b = WorkflowBudget(max_cost_usd=2.0, max_duration_seconds=300)
        assert b.max_cost_usd == 2.0

    def test_zero_cost_invalid(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WorkflowBudget(max_cost_usd=0)


# ---------------------------------------------------------------------------
# DepartmentStep
# ---------------------------------------------------------------------------


class TestDepartmentStep:
    def test_minimal(self) -> None:
        s = DepartmentStep(name="s1", department="strategy", intent="Do X")
        assert s.name == "s1"
        assert s.department == "strategy"
        assert s.inputs == []
        assert s.outputs == []
        assert s.parallel_with is None

    def test_invalid_department(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DepartmentStep(name="s1", department="unknown", intent="X")  # type: ignore[arg-type]

    def test_on_failure_list(self) -> None:
        s = DepartmentStep(
            name="synthesize",
            department="board",
            intent="Synthesize",
            on_failure=["cleanup"],
        )
        assert s.on_failure == ["cleanup"]


# ---------------------------------------------------------------------------
# GateStep
# ---------------------------------------------------------------------------


class TestGateStep:
    def test_basic(self) -> None:
        g = GateStep(name="approve", gate="operator", message="OK?")
        assert g.timeout_seconds == 3600
        assert g.condition is None

    def test_with_condition(self) -> None:
        g = GateStep(
            name="borderline",
            gate="operator",
            message="Borderline: {decision}",
            condition="{confidence} < 0.7",
        )
        assert g.condition == "{confidence} < 0.7"


# ---------------------------------------------------------------------------
# ActionStep
# ---------------------------------------------------------------------------


class TestActionStep:
    def test_discord_action(self) -> None:
        a = ActionStep(
            name="post",
            action="publish_discord",
            channel="operator",
            message="{digest}",
        )
        assert a.action == "publish_discord"

    def test_github_comment_action(self) -> None:
        a = ActionStep(
            name="comment",
            action="publish_github_comment",
            target="pr",
            message="{decision}",
        )
        assert a.action == "publish_github_comment"

    def test_invalid_action(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ActionStep(name="bad", action="send_email", message="hi")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# WorkflowConfig
# ---------------------------------------------------------------------------


class TestWorkflowConfig:
    def test_explicit_trigger(self) -> None:
        cfg = WorkflowConfig(
            name="test-wf",
            trigger="explicit",
            steps=[
                DepartmentStep(name="s1", department="ops", intent="Check health"),
            ],
        )
        assert cfg.name == "test-wf"
        assert cfg.trigger == "explicit"

    def test_schedule_requires_schedule_field(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="schedule"):
            WorkflowConfig(name="wf", trigger="schedule", steps=[])

    def test_schedule_cron_prefix_required(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WorkflowConfig(
                name="wf",
                trigger="schedule",
                schedule="0 8 * * 1",  # missing cron: prefix
                steps=[],
            )

    def test_valid_schedule(self) -> None:
        cfg = WorkflowConfig(
            name="wf",
            trigger="schedule",
            schedule="cron:0 8 * * 1",
            steps=[],
        )
        assert cfg.schedule == "cron:0 8 * * 1"

    def test_webhook_requires_webhook_field(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="webhook"):
            WorkflowConfig(name="wf", trigger="webhook", steps=[])

    def test_duplicate_step_names(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Duplicate"):
            WorkflowConfig(
                name="wf",
                trigger="explicit",
                steps=[
                    DepartmentStep(name="step-a", department="ops", intent="X"),
                    DepartmentStep(name="step-a", department="qa", intent="Y"),
                ],
            )

    def test_invalid_parallel_with_ref(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="parallel_with"):
            WorkflowConfig(
                name="wf",
                trigger="explicit",
                steps=[
                    DepartmentStep(
                        name="step-a",
                        department="ops",
                        intent="X",
                        parallel_with="nonexistent",
                    ),
                ],
            )


# ---------------------------------------------------------------------------
# load_workflow_config — round-trip through YAML
# ---------------------------------------------------------------------------


class TestLoadWorkflowConfig:
    MINIMAL_YAML = textwrap.dedent(
        """\
        name: my-workflow
        trigger: explicit
        steps:
          - name: gather
            department: strategy
            intent: "Gather signals"
            outputs: [signals]
        """
    )

    def test_load_minimal(self) -> None:
        cfg = load_workflow_config(self.MINIMAL_YAML)
        assert cfg.name == "my-workflow"
        assert len(cfg.steps) == 1
        step = cfg.steps[0]
        assert isinstance(step, DepartmentStep)
        assert step.outputs == ["signals"]

    def test_load_gate_step(self) -> None:
        yaml_text = textwrap.dedent(
            """\
            name: approval-wf
            trigger: explicit
            steps:
              - name: approve
                gate: operator
                message: "OK?"
                timeout_seconds: 1800
            """
        )
        cfg = load_workflow_config(yaml_text)
        gate = cfg.steps[0]
        assert isinstance(gate, GateStep)
        assert gate.timeout_seconds == 1800

    def test_load_action_step(self) -> None:
        yaml_text = textwrap.dedent(
            """\
            name: post-wf
            trigger: explicit
            steps:
              - name: post
                action: publish_discord
                channel: operator
                message: "{result}"
            """
        )
        cfg = load_workflow_config(yaml_text)
        action = cfg.steps[0]
        assert isinstance(action, ActionStep)
        assert action.channel == "operator"

    def test_load_example_yaml(self) -> None:
        """The shipped example.yaml must pass validation."""
        from pathlib import Path

        example = (
            Path(__file__).parent.parent / "config" / "workflows" / "example.yaml"
        )
        cfg = load_workflow_config(example.read_text())
        assert cfg.name == "example-workflow"
        assert len(cfg.steps) >= 3

    def test_schema_error_propagates(self) -> None:
        from pydantic import ValidationError

        bad_yaml = textwrap.dedent(
            """\
            name: bad
            trigger: schedule
            steps: []
            """
        )
        with pytest.raises(ValidationError):
            load_workflow_config(bad_yaml)
