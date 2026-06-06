"""Shared test helpers for the teams test suite."""

from __future__ import annotations

from typing import Iterable
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from teams._agent_cache import GLOBAL_AGENT_CACHE
from teams._types import BridgeDeps


# ---------------------------------------------------------------------------
# Sprint zone4-warmth.A.02 (#2291) — global agent cache isolation
#
# ``build_manager_agent`` consults ``GLOBAL_AGENT_CACHE`` when no explicit
# ``agent_cache`` is passed. Existing tests build fresh ``DepartmentConfig``
# objects per test and re-call ``build_manager_agent`` — without this fixture
# the second test for a given ``(team_name, chief_name)`` would receive the
# previous test's cached chief (closures bound to the previous test's
# employees / collector). Wiping the cache before every test in this suite
# restores the historical "fresh chief per test" contract while keeping the
# production cache path intact.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_global_agent_cache():
    """Invalidate ``GLOBAL_AGENT_CACHE`` before each test in the teams suite."""
    GLOBAL_AGENT_CACHE.invalidate_all()
    yield
    GLOBAL_AGENT_CACHE.invalidate_all()


def make_deps(
    session_id: str = "test-session",
    department: str = "qa",
    operator_id: str = "op-test",
    memory_store=None,
    event_bus=None,
    trust_manager=None,
    cost_tracker=None,
    knowledge_search=None,
    cost_limit_usd: float = 2.0,
    workflow: str = "",
) -> BridgeDeps:
    """Construct a BridgeDeps with all required fields for use in tests.

    Pass explicit values for any field you want to test; the rest default
    to lightweight mocks so construction always succeeds.
    """
    if memory_store is None:
        memory_store = AsyncMock()
        memory_store.get = AsyncMock(return_value=None)
        memory_store.set = AsyncMock(return_value=None)
    if event_bus is None:
        event_bus = MagicMock()
    if trust_manager is None:
        trust_manager = MagicMock()
    if cost_tracker is None:
        cost_tracker = MagicMock()
    if knowledge_search is None:
        knowledge_search = AsyncMock(return_value=[])

    return BridgeDeps(
        session_id=session_id,
        department=department,
        operator_id=operator_id,
        memory_store=memory_store,
        event_bus=event_bus,
        trust_manager=trust_manager,
        cost_tracker=cost_tracker,
        knowledge_search=knowledge_search,
        cost_limit_usd=cost_limit_usd,
        workflow=workflow,
    )


@pytest.fixture
def bridge_deps() -> BridgeDeps:
    """Default BridgeDeps fixture with all fields wired to mocks."""
    return make_deps()


# ---------------------------------------------------------------------------
# Sprint 19 (Phase 5A) — chief delegation test helpers
#
# The unified ``delegate(specialist, task, ...)`` tool replaced the
# per-specialist ``delegate_to_<name>(task)`` tools. ``TestModel.call_tools``
# is name-only — it can't pin the ``specialist`` argument the chief's LLM
# would normally choose. ``FunctionModel`` lets us emit a precise
# ToolCallPart, then return the final ``TeamOutput`` synthesis on the second
# round once the tool has run.
# ---------------------------------------------------------------------------


def make_chief_delegating_model(
    delegations: Iterable[tuple[str, str]],
    *,
    final_answer: str = "synthesised",
) -> FunctionModel:
    """Build a FunctionModel that drives a chief through specific delegations.

    The chief's LLM would normally pick a specialist via ``list_specialists()``
    + reasoning. In tests we want determinism: this helper returns a model that
    fires every (specialist_name, task) pair in ``delegations`` on the first
    call, then on the second call (after pydantic-ai feeds tool results back)
    returns a final ``TeamOutput`` synthesis.

    Args:
        delegations: Sequence of ``(specialist_name, task)`` tuples — one
            ``ToolCallPart(tool_name="delegate", args={...})`` is emitted per
            tuple, in order.
        final_answer: The ``answer`` field of the synthesised ``TeamOutput``.
    """
    deleg_pairs = tuple(delegations)
    call_count = {"n": 0}

    async def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        call_count["n"] += 1
        if call_count["n"] == 1 and deleg_pairs:
            parts = [
                ToolCallPart(
                    tool_name="delegate",
                    args={"specialist": specialist, "task": task},
                )
                for specialist, task in deleg_pairs
            ]
            return ModelResponse(parts=parts)
        # Final synthesis turn — emit the structured TeamOutput via the
        # final_result tool that pydantic-ai injects when output_type is set.
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={
                        "answer": final_answer,
                        "specialist_outputs": [],
                    },
                )
            ]
        )

    return FunctionModel(_fn, model_name="chief-delegating-test")


def make_chief_direct_answer_model(answer: str = "direct answer") -> FunctionModel:
    """Build a FunctionModel that returns a direct TeamOutput with no delegation."""

    async def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={"answer": answer, "specialist_outputs": []},
                )
            ]
        )

    return FunctionModel(_fn, model_name="chief-direct-test")


def make_specialist_text_model(text: str) -> FunctionModel:
    """Build a FunctionModel for a specialist that returns a plain text answer."""

    async def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content=text)])

    return FunctionModel(_fn, model_name="specialist-text-test")
