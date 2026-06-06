"""Agent executor Protocol — kept for future dual-mode use.

Sprint 04.04 (2026-04-30 delete-it path) removed the
``PydanticAIExecutor`` and ``ClaudeCodeExecutor`` implementations along
with the ``select_executor()`` resolver. The Protocol and the
``ExecutionResult`` dataclass remain so future work can re-introduce
dual-mode execution without re-deriving the contract.

**Why this was removed**: Phase 5 + #1072/#1075 standardised every Z4
chief and specialist on OpenRouter via pydantic-ai. The
``ClaudeCodeExecutor`` would have spawned a ``claude -p`` subprocess
per specialist, which authenticates against Anthropic via
``claude_oauth_token`` — a path the operator deliberately reserved for
the Tier 1 Main Agent only. Routing specialists through ``claude -p``
would violate the no-Anthropic-in-Z4 contract documented in
``docs/zone4/model-assignments.md``.

The dual-mode infrastructure had **zero production callers** before
removal — it was scaffolding for an architectural option the operator
ultimately did not take. See round3-runtime-wiring.md A10 (CONFIRMED)
for the audit that surfaced the dead code.

If dual-mode execution returns (e.g. a future on-device specialist),
the Protocol below is the seam to extend.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from teams._types import AgentSpec, BridgeDeps


@dataclass(frozen=True)
class ExecutionResult:
    """Uniform return shape for any future executor implementation."""

    success: bool
    output: str = ""
    error: Optional[str] = None
    tokens_used: int = 0
    duration_seconds: float = 0.0


class AgentExecutor(Protocol):
    """Protocol kept for future dual-mode execution.

    Implementations should wrap a single specialist invocation (one
    pydantic-ai agent run, one subprocess call, one remote MCP call,
    etc.) and return an ``ExecutionResult``.
    """

    async def execute(
        self,
        agent_spec: AgentSpec,
        task: str,
        deps: BridgeDeps,
        agent_instance: Any = None,
    ) -> ExecutionResult: ...
