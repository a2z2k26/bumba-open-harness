"""Zone 4 teams package — Pydantic AI department orchestration.

Bridge-independent: this package must not import from bridge.app or bridge.discord_bot.
Teams consume bridge infrastructure via BridgeDeps dataclass injection.

## Quick start

    from teams import DepartmentRegistry, BridgeDeps
    from unittest.mock import AsyncMock, MagicMock

    # Build registry from YAML configs
    registry = DepartmentRegistry.from_directory("agent/config/teams")

    # Route a task to a department (all fields required)
    deps = BridgeDeps(
        session_id="s1",
        department="qa",
        operator_id="",
        memory_store=MagicMock(),
        event_bus=MagicMock(),
        trust_manager=MagicMock(),
        cost_tracker=MagicMock(),
        knowledge_search=AsyncMock(return_value=[]),
    )
    result = await registry.route("qa", "review auth module", deps)

    if result.success:
        print(result.manager_output)
    else:
        print(f"Failed: {result.error}")
"""

from teams._agent_cache import GLOBAL_AGENT_CACHE, AgentCache, CacheStats
from teams._executor import (
    AgentExecutor,
    ExecutionResult,
)
from teams._factory import build_employee_agents, build_manager_agent
from teams._handoff import HandoffEnvelope, list_pending_handoffs, load_handoff, store_handoff
from teams._verify import verify_team_result
from teams._registry import DepartmentRegistry
from teams._namespace import NamespaceGuard, NamespaceViolationError, get_guard
from teams._circuit import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
    get_registry,
)
from teams._semaphore import DepartmentSemaphore
from teams._team import DepartmentTeam
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Budget,
    Constraints,
    DepartmentConfig,
    EmployeeResult,
    TeamOutput,
    TeamResult,
    ToolSpec,
    VAPIReceptionist,
)

__all__ = [
    # Types
    "AgentSpec",
    "BridgeDeps",
    "Budget",
    "Constraints",
    "DepartmentConfig",
    "EmployeeResult",
    "TeamOutput",
    "TeamResult",
    "ToolSpec",
    "VAPIReceptionist",
    # Factory
    "build_employee_agents",
    "build_manager_agent",
    # Runtime
    "DepartmentTeam",
    "DepartmentRegistry",
    "DepartmentSemaphore",
    # Circuit breakers
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitOpenError",
    "CircuitState",
    "get_registry",
    # Namespace enforcement
    "NamespaceGuard",
    "NamespaceViolationError",
    "get_guard",
    # Executor (base protocol + result only; concrete executors are in teams._executor)
    "AgentExecutor",
    "ExecutionResult",
    # Handoff
    "HandoffEnvelope",
    "store_handoff",
    "load_handoff",
    "list_pending_handoffs",
    # Verification
    "verify_team_result",
    # Agent cache (Phase 1 #2290 — infrastructure only, unused by production paths)
    "AgentCache",
    "CacheStats",
    "GLOBAL_AGENT_CACHE",
]
