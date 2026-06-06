"""Regression coverage for oversized team context payloads."""

from __future__ import annotations

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

from teams._factory import (
    DELEGATION_TASK_MAX_CHARS,
    build_employee_agents,
    build_manager_agent,
)
from teams._types import AgentSpec, BridgeDeps, Constraints, DepartmentConfig
from tests.test_teams.conftest import make_chief_delegating_model, make_deps


class FakeCtx:
    def __init__(self, deps: BridgeDeps) -> None:
        self.deps = deps


def _single_specialist_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="context-cap-test",
        zone=4,
        description="",
        manager=AgentSpec(
            name="cap-chief",
            model="anthropic:claude-opus-4-6",
            role="chief",
        ),
        employees=(
            AgentSpec(
                name="cap-specialist",
                model="anthropic:claude-sonnet-4-6",
                role="specialist",
            ),
        ),
        constraints=Constraints(cost_limit_usd=10.0, timeout_seconds=60),
    )


@pytest.mark.asyncio
async def test_ops_tail_log_caps_large_log_output(monkeypatch) -> None:
    from teams.tools import _ops

    async def fake_run_subprocess(*args, **kwargs):
        return ("x" * (_ops.OPS_TOOL_OUTPUT_MAX_CHARS * 3), 0)

    monkeypatch.setattr(_ops.Path, "exists", lambda self: True)
    monkeypatch.setattr(_ops, "_run_subprocess", fake_run_subprocess)

    result = await _ops.tail_log(FakeCtx(make_deps(department="ops")), "bridge")

    assert len(result) <= _ops.OPS_TOOL_OUTPUT_MAX_CHARS
    assert "[...truncated" in result


@pytest.mark.asyncio
async def test_delegate_caps_oversized_specialist_task_payload() -> None:
    config = _single_specialist_config()
    employees = build_employee_agents(config)
    manager = build_manager_agent(config, employees, employee_results_collector=[])
    oversized_task = "start-" + ("x" * (DELEGATION_TASK_MAX_CHARS * 3)) + "-end"
    captured: dict[str, str] = {}

    async def capture_specialist_input(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> ModelResponse:
        captured["messages"] = repr(messages)
        return ModelResponse(parts=[TextPart(content="specialist ok")])

    specialist_model = FunctionModel(
        capture_specialist_input,
        model_name="capture-specialist-input",
    )
    manager_model = make_chief_delegating_model(
        [("cap-specialist", oversized_task)],
        final_answer="done",
    )

    with employees["cap-specialist"].override(model=specialist_model):
        with manager.override(model=manager_model):
            await manager.run(
                "delegate a large payload",
                deps=make_deps(department="context-cap-test"),
            )

    specialist_context = captured["messages"]
    assert len(specialist_context) < DELEGATION_TASK_MAX_CHARS + 10_000
    assert "start-" in specialist_context
    assert "-end" in specialist_context
    assert "[...delegation task truncated" in specialist_context
