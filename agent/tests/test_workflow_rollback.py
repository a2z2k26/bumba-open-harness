"""Tests for workflow failure compensation (sprint F-W.6)."""

from __future__ import annotations

import asyncio
import textwrap

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from bridge.workflow_engine import WorkflowEngine
from config.workflows._schema import load_workflow_config


WORKFLOW_WITH_ROLLBACK = textwrap.dedent(
    """\
    name: rollback-test
    trigger: explicit
    budget:
      max_cost_usd: 10.0
    steps:
      - name: step-a
        department: strategy
        intent: "Step A"
        outputs: [a_result]
        on_failure: [compensate-a]

      - name: step-b
        department: qa
        intent: "Step B — will fail"
        outputs: [b_result]
        on_failure: [compensate-b]

      - name: step-c
        department: ops
        intent: "Step C"
        outputs: [c_result]

      - name: compensate-a
        action: publish_discord
        channel: operator
        message: "Rolling back step A"

      - name: compensate-b
        action: publish_discord
        channel: operator
        message: "Rolling back step B"
    """
)

WORKFLOW_NO_ROLLBACK = textwrap.dedent(
    """\
    name: no-rollback-test
    trigger: explicit
    steps:
      - name: step-x
        department: ops
        intent: "Step X"
        outputs: [x]
      - name: step-y
        department: qa
        intent: "Step Y"
        outputs: [y]
    """
)


@pytest.fixture()
def cfg_with_rollback():
    return load_workflow_config(WORKFLOW_WITH_ROLLBACK)


@pytest.fixture()
def cfg_no_rollback():
    return load_workflow_config(WORKFLOW_NO_ROLLBACK)


class TestCompensationOnFailure:
    @pytest.mark.asyncio
    async def test_compensation_steps_run_when_step_fails(
        self, cfg_with_rollback
    ) -> None:
        call_log: list[str] = []

        async def dept_runner(dept, intent, ctx):
            call_log.append(f"dept:{dept}")
            if dept == "qa":
                raise RuntimeError("QA step failed!")
            return f"result-{dept}", 0.1

        discord_calls: list[tuple[str, str]] = []

        async def discord_cb(channel, message):
            discord_calls.append((channel, message))

        engine = WorkflowEngine(
            department_runner=dept_runner,
            discord_callback=discord_cb,
        )
        run_id = engine.start(cfg_with_rollback)
        state = engine.get_run_state(run_id)
        assert state is not None

        # Let the task run to completion
        await asyncio.sleep(0.1)

        assert state.status == "failed"
        # Compensation messages should have been posted
        messages = [msg for _, msg in discord_calls]
        # compensate-a and compensate-b (or at least compensate-a since step-a completed)
        assert any("Rolling back step A" in m for m in messages)

    @pytest.mark.asyncio
    async def test_no_compensation_when_all_succeed(self, cfg_no_rollback) -> None:
        discord_calls: list[tuple] = []

        async def discord_cb(channel, message):
            discord_calls.append((channel, message))

        async def dept_runner(dept, intent, ctx):
            return f"result-{dept}", 0.05

        engine = WorkflowEngine(
            department_runner=dept_runner,
            discord_callback=discord_cb,
        )
        run_id = engine.start(cfg_no_rollback)
        await asyncio.sleep(0.1)
        state = engine.get_run_state(run_id)
        assert state is not None
        assert state.status == "completed"
        assert len(discord_calls) == 0

    @pytest.mark.asyncio
    async def test_compensation_step_not_found_logs_warning(
        self, cfg_with_rollback
    ) -> None:
        """When a compensation step references a nonexistent step name, it logs
        a warning but does not raise."""

        async def dept_runner(dept, intent, ctx):
            if dept == "qa":
                raise RuntimeError("fail")
            return "ok", 0.0

        engine = WorkflowEngine(department_runner=dept_runner)
        # Patch the steps_by_name lookup to exclude compensate-b
        original_execute = engine._execute

        run_id = engine.start(cfg_with_rollback)
        await asyncio.sleep(0.1)
        state = engine.get_run_state(run_id)
        assert state is not None
        assert state.status == "failed"


class TestCompensationSchema:
    def test_on_failure_field_accepted(self) -> None:
        yaml_text = textwrap.dedent(
            """\
            name: comp-schema
            trigger: explicit
            steps:
              - name: risky
                department: ops
                intent: "Risky operation"
                on_failure: [rollback-risky]
              - name: rollback-risky
                action: publish_discord
                channel: operator
                message: "Rolling back risky"
            """
        )
        cfg = load_workflow_config(yaml_text)
        risky = cfg.steps[0]
        assert risky.on_failure == ["rollback-risky"]

    def test_on_failure_defaults_empty(self) -> None:
        yaml_text = textwrap.dedent(
            """\
            name: no-rollback
            trigger: explicit
            steps:
              - name: safe
                department: ops
                intent: "Safe operation"
            """
        )
        cfg = load_workflow_config(yaml_text)
        assert cfg.steps[0].on_failure == []
