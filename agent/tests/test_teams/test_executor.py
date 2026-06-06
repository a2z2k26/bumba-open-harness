"""Tests for teams._executor.

Sprint 04.04 (2026-04-30 delete-it path) removed the
``PydanticAIExecutor`` and ``ClaudeCodeExecutor`` implementations and
the ``select_executor()`` resolver. The Protocol and ``ExecutionResult``
dataclass remain so future dual-mode work has a stable contract to
extend. These tests pin that contract.
"""
from __future__ import annotations

import pytest

from teams._executor import AgentExecutor, ExecutionResult


class TestExecutionResult:
    """ExecutionResult is the uniform return shape any future executor
    implementation should produce."""

    def test_success_minimal(self) -> None:
        r = ExecutionResult(success=True, output="done")
        assert r.success is True
        assert r.output == "done"
        assert r.error is None
        assert r.tokens_used == 0
        assert r.duration_seconds == 0.0

    def test_failure_with_error(self) -> None:
        r = ExecutionResult(success=False, output="", error="timeout")
        assert r.success is False
        assert r.error == "timeout"

    def test_full_payload(self) -> None:
        r = ExecutionResult(
            success=True,
            output="x",
            error=None,
            tokens_used=42,
            duration_seconds=1.5,
        )
        assert r.tokens_used == 42
        assert r.duration_seconds == 1.5

    def test_frozen(self) -> None:
        r = ExecutionResult(success=True)
        with pytest.raises(Exception):
            r.success = False  # type: ignore[misc]


class TestAgentExecutorProtocol:
    """The Protocol is structural — any class implementing the right
    method signature satisfies it. The dropped implementations did so;
    so should any future ones."""

    def test_protocol_runtime_check_via_attribute(self) -> None:
        # Protocols in typing.Protocol aren't runtime-checkable by default.
        # We confirm the Protocol exists, has the right method name, and
        # that subclasses-by-structure satisfy it via `hasattr`.
        assert hasattr(AgentExecutor, "execute")

    def test_concrete_implementation_satisfies_protocol_structurally(self) -> None:
        # Define a minimal compliant class — proves the Protocol contract
        # is implementable without re-importing the deleted classes.
        from typing import Any

        from teams._types import AgentSpec, BridgeDeps

        class _NoopExecutor:
            async def execute(
                self,
                agent_spec: AgentSpec,
                task: str,
                deps: BridgeDeps,
                agent_instance: Any = None,
            ) -> ExecutionResult:
                return ExecutionResult(success=True, output="noop")

        executor: AgentExecutor = _NoopExecutor()  # structural typing
        assert hasattr(executor, "execute")


class TestDeletedSymbolsAreGone:
    """Hard contract: the deleted dual-mode classes must NOT come back
    silently. Any reintroduction needs operator approval and a
    no-Anthropic-in-Z4-violation review (see
    docs/zone4/model-assignments.md)."""

    def test_pydantic_ai_executor_not_exported(self) -> None:
        import teams._executor as mod
        assert not hasattr(mod, "PydanticAIExecutor")

    def test_claude_code_executor_not_exported(self) -> None:
        import teams._executor as mod
        assert not hasattr(mod, "ClaudeCodeExecutor")

    def test_select_executor_not_exported(self) -> None:
        import teams._executor as mod
        assert not hasattr(mod, "select_executor")
