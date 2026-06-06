"""WorkOrder data model for Zone 3 orchestration.

WorkOrders are the formal contract between the Chief Engineer and
specialist agents. They flow through status transitions, carry
execution environment selection with rationale, and are immutable
(transitions return new instances).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Literal

# S07 — trigger source type
TriggerSource = Literal["discord", "cron", "webhook", "tick", "peer", "dispatcher"]


class WorkOrderStatus(enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"  # terminal — added for orch compat (S01)


class Environment(enum.Enum):
    SUBAGENT = "subagent"
    TMUX = "tmux"
    WORKTREE = "worktree"
    E2B = "e2b"
    DEPARTMENT = "department"


class BatchStrategy(enum.Enum):
    """How sub-WorkOrders of a composite WorkOrder are scheduled.

    Sprint 07.01 — concept-only port of TinyAGI/fractals (MIT). The
    decomposer (07.02) consumes this when expanding a composite
    WorkOrder; the worktree wiring (07.03) honours it at execution.

    The first three values are *concurrency* strategies that govern
    how children execute relative to each other. The latter three are
    *traversal* strategies that govern the order in which a recursive
    decomposer visits the WorkOrder tree. Both shapes are documented
    in the spec — they compose orthogonally.
    """

    # Concurrency — how children execute relative to each other.
    SEQUENTIAL = "sequential"          # children run in declared order
    PARALLEL_FANOUT = "parallel_fanout"  # children run concurrently, results aggregated
    RACE = "race"                      # children run concurrently, first non-empty wins

    # Traversal — order in which the decomposer visits the tree.
    DEPTH_FIRST = "depth_first"
    BREADTH_FIRST = "breadth_first"
    LAYER_SEQUENTIAL = "layer_sequential"


class InvalidTransitionError(Exception):
    """Raised when a WorkOrder status transition is not allowed."""


# Valid state transitions (from → set of allowed targets)
_TRANSITIONS: dict[WorkOrderStatus, set[WorkOrderStatus]] = {
    WorkOrderStatus.PENDING: {WorkOrderStatus.ASSIGNED, WorkOrderStatus.FAILED, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.ASSIGNED: {WorkOrderStatus.EXECUTING, WorkOrderStatus.FAILED, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.EXECUTING: {WorkOrderStatus.VERIFYING, WorkOrderStatus.FAILED, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.VERIFYING: {WorkOrderStatus.COMPLETE, WorkOrderStatus.FAILED,
                                 WorkOrderStatus.EXECUTING},  # reject → rework
    WorkOrderStatus.COMPLETE: set(),    # terminal
    WorkOrderStatus.FAILED: set(),      # terminal
    WorkOrderStatus.CANCELLED: set(),   # terminal
}


@dataclass(frozen=True)
class WorkOrderContext:
    """Task-specific context brief."""
    spec_section: str = ""
    prerequisite_outputs: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()

    def __init__(
        self,
        spec_section: str = "",
        prerequisite_outputs: list[str] | tuple[str, ...] = (),
        constraints: list[str] | tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "spec_section", spec_section)
        object.__setattr__(self, "prerequisite_outputs", tuple(prerequisite_outputs))
        object.__setattr__(self, "constraints", tuple(constraints))


@dataclass(frozen=True)
class WorkOrderInput:
    """Input payload for a WorkOrder."""
    text: str = ""
    structured: dict[str, Any] = field(default_factory=dict)
    files: tuple[str, ...] = ()
    context: WorkOrderContext = field(default_factory=WorkOrderContext)

    def __init__(
        self,
        text: str = "",
        structured: dict[str, Any] | None = None,
        files: list[str] | tuple[str, ...] = (),
        context: WorkOrderContext | None = None,
    ) -> None:
        object.__setattr__(self, "text", text)
        from types import MappingProxyType
        object.__setattr__(self, "structured", MappingProxyType(structured or {}))
        object.__setattr__(self, "files", tuple(files))
        object.__setattr__(self, "context", context or WorkOrderContext())


@dataclass(frozen=True)
class WorkOrderConstraints:
    """Execution constraints."""
    max_token_budget: int = 100_000
    timeout_ms: int = 600_000
    quality_tier: str = "standard"
    # Native Claude Code --permission-mode values: "acceptEdits", "auto",
    # "bypassPermissions", "default", "dontAsk", "plan". Passed verbatim.
    permission_mode: str = "bypassPermissions"


@dataclass(frozen=True)
class WorkOrderAssignment:
    """Agent assignment details."""
    agent_type: str = ""
    agent_id: str = ""
    model: str = ""
    assigned_at: str = ""


@dataclass(frozen=True)
class WorkOrderExecution:
    """Execution tracking."""
    started_at: str = ""
    completed_at: str = ""
    retries: int = 0
    max_retries: int = 3


@dataclass(frozen=True)
class WorkOrderOutput:
    """Output from a completed WorkOrder."""
    result: str = ""
    artifacts: tuple[str, ...] = ()
    token_usage: int = 0
    verification_status: str = ""
    confidence: float = 0.0

    def __init__(
        self,
        result: str = "",
        artifacts: list[str] | tuple[str, ...] = (),
        token_usage: int = 0,
        verification_status: str = "",
        confidence: float = 0.0,
    ) -> None:
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "artifacts", tuple(artifacts))
        object.__setattr__(self, "token_usage", token_usage)
        object.__setattr__(self, "verification_status", verification_status)
        object.__setattr__(self, "confidence", confidence)


@dataclass(frozen=True)
class Decomposition:
    """Sub-WorkOrder fan-out plan for a composite WorkOrder.

    Sprint 07.01 — concept-only port of TinyAGI/fractals (MIT). A
    ``WorkOrder`` is recursively classifiable as **atomic** (executed
    directly) or **composite** (decomposed via this struct into N
    sub-WorkOrders). Each child may itself carry a ``Decomposition``
    — the structure is naturally recursive.

    Frozen and immutable. ``children`` is a tuple of ``WorkOrder`` so
    the whole tree is hashable. ``atomic`` is explicit (vs. inferred
    from ``children`` being empty) so a leaf can declare itself atomic
    without ambiguity.
    """

    strategy: BatchStrategy
    children: tuple["WorkOrder", ...] = ()
    atomic: bool = False

    def __init__(
        self,
        strategy: BatchStrategy,
        children: list["WorkOrder"] | tuple["WorkOrder", ...] = (),
        atomic: bool = False,
    ) -> None:
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "children", tuple(children))
        object.__setattr__(self, "atomic", atomic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "atomic": self.atomic,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Decomposition":
        return cls(
            strategy=BatchStrategy(data["strategy"]),
            children=tuple(WorkOrder.from_dict(c) for c in data.get("children", [])),
            atomic=bool(data.get("atomic", False)),
        )


@dataclass(frozen=True)
class WorkOrder:
    """Immutable WorkOrder — the orchestration contract.

    All mutations return new instances. Original is never modified.
    """
    id: str = ""
    parent_id: str | None = None
    context_id: str = ""
    intent: str = ""
    skill: str = ""
    project: str = ""
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    input: WorkOrderInput = field(default_factory=WorkOrderInput)
    constraints: WorkOrderConstraints = field(default_factory=WorkOrderConstraints)
    environment: Environment | None = None
    environment_rationale: str = ""
    department_target: str | None = None
    output_schema: dict[str, Any] | None = None
    assignment: WorkOrderAssignment = field(default_factory=WorkOrderAssignment)
    execution: WorkOrderExecution = field(default_factory=WorkOrderExecution)
    output: WorkOrderOutput = field(default_factory=WorkOrderOutput)
    dependencies: tuple[str, ...] = ()
    # S07 — correlation + cost primitives
    idempotency_key: str | None = None
    trigger_source: TriggerSource = "dispatcher"
    cost_cap_usd: float | None = None
    retry_of: str | None = None
    attempt_number: int = 1
    # Sprint 07.01 — recursive decomposition contract (TinyAGI/fractals,
    # MIT, concept-only). None = not classified yet (default for legacy
    # rows + existing call sites). 07.02 ships the decomposer that
    # populates this field.
    decomposition: Decomposition | None = None

    @classmethod
    def create(
        cls,
        *,
        intent: str,
        skill: str,
        project: str,
        parent_id: str | None = None,
    ) -> WorkOrder:
        """Create a new WorkOrder with a generated ID."""
        return cls(
            id=str(uuid.uuid4()),
            intent=intent,
            skill=skill,
            project=project,
            parent_id=parent_id,
            context_id=str(uuid.uuid4()),
        )

    @classmethod
    def from_message(
        cls,
        message: str,
        intent: str,
        *,
        skill: str = "",
        project: str = "",
        cost_cap_usd: float = 0.50,
    ) -> WorkOrder:
        """Create a WorkOrder from a classified Zone 4 operator message.

        Sprint D-R2 (#1932). Construct a WorkOrder tagged for the
        operator-message path: ``trigger_source = "discord"``,
        ``cost_cap_usd`` capped (default $0.50), full message text as
        ``input.text``, and the original intent value carried verbatim
        on the ``intent`` field.

        Used by the dispatcher gate in ``invocation_pipeline`` for
        Zone 4 routing, and by D-R4's ZONE4_EXPLICIT branch.
        """
        wo = cls.create(
            intent=intent,
            skill=skill,
            project=project,
        )
        return replace(
            wo,
            input=WorkOrderInput(text=message),
            trigger_source="discord",
            cost_cap_usd=cost_cap_usd,
        )

    def transition(self, to: WorkOrderStatus) -> WorkOrder:
        """Return a new WorkOrder with the given status."""
        allowed = _TRANSITIONS.get(self.status, set())
        if to not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from {self.status.value} to {to.value}"
            )
        return replace(self, status=to)

    def with_environment(self, env: Environment, rationale: str) -> WorkOrder:
        return replace(self, environment=env, environment_rationale=rationale)

    def with_department(self, dept: str) -> WorkOrder:
        """Return a new WorkOrder with ``department_target`` set to ``dept``.

        Sprint 03.04 — sets the target department for a DEPARTMENT-routed
        WorkOrder so ``DepartmentExecutor.execute`` can resolve it through
        the registry. Callers MUST use this whenever ``environment`` is
        ``Environment.DEPARTMENT``; without it the executor raises
        ``ValueError("unknown department: ")`` and the dispatcher falls
        through, silently burning a retry.

        Production callers (3 sites): ``app.py`` dispatcher branch,
        ``api_server.py`` external WorkOrder ingestion, and ``commands.py``
        ``/dispatch`` operator command. Each derives ``dept`` from
        ``environment_selector._derive_department(skill)`` (the single
        source of truth) or accepts an explicit override (api_server).
        """
        return replace(self, department_target=dept)

    def with_input(self, inp: WorkOrderInput) -> WorkOrder:
        return replace(self, input=inp)

    def with_output(self, out: WorkOrderOutput) -> WorkOrder:
        return replace(self, output=out)

    def with_assignment(self, assignment: WorkOrderAssignment) -> WorkOrder:
        return replace(self, assignment=assignment)

    def with_decomposition(self, decomp: Decomposition | None) -> WorkOrder:
        """Return a new WorkOrder with the given decomposition plan.

        Sprint 07.01 — immutable setter for the decomposition field;
        used by the decomposer (07.02) and by tests asserting tree
        construction. Pass ``None`` to mark the WorkOrder as not yet
        classified.
        """
        return replace(self, decomposition=decomp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "context_id": self.context_id,
            "intent": self.intent,
            "skill": self.skill,
            "project": self.project,
            "status": self.status.value,
            "environment": self.environment.value if self.environment else None,
            "environment_rationale": self.environment_rationale,
            "department_target": self.department_target,
            "input": {
                "text": self.input.text,
                "structured": dict(self.input.structured),
                "files": list(self.input.files),
                "context": {
                    "spec_section": self.input.context.spec_section,
                    "prerequisite_outputs": list(self.input.context.prerequisite_outputs),
                    "constraints": list(self.input.context.constraints),
                },
            },
            "constraints": {
                "max_token_budget": self.constraints.max_token_budget,
                "timeout_ms": self.constraints.timeout_ms,
                "quality_tier": self.constraints.quality_tier,
                "permission_mode": self.constraints.permission_mode,
            },
            "output_schema": self.output_schema,
            "assignment": {
                "agent_type": self.assignment.agent_type,
                "agent_id": self.assignment.agent_id,
                "model": self.assignment.model,
                "assigned_at": self.assignment.assigned_at,
            },
            "execution": {
                "started_at": self.execution.started_at,
                "completed_at": self.execution.completed_at,
                "retries": self.execution.retries,
                "max_retries": self.execution.max_retries,
            },
            "output": {
                "result": self.output.result,
                "artifacts": list(self.output.artifacts),
                "token_usage": self.output.token_usage,
                "verification_status": self.output.verification_status,
                "confidence": self.output.confidence,
            },
            "dependencies": list(self.dependencies),
            # S07
            "idempotency_key": self.idempotency_key,
            "trigger_source": self.trigger_source,
            "cost_cap_usd": self.cost_cap_usd,
            "retry_of": self.retry_of,
            "attempt_number": self.attempt_number,
            # Sprint 07.01 — recursive decomposition contract.
            "decomposition": (
                self.decomposition.to_dict() if self.decomposition is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkOrder:
        env_val = data.get("environment")
        inp_data = data.get("input", {})
        ctx_data = inp_data.get("context", {})
        constraints_data = data.get("constraints", {})
        assign_data = data.get("assignment", {})
        exec_data = data.get("execution", {})
        out_data = data.get("output", {})

        return cls(
            id=data.get("id", ""),
            parent_id=data.get("parent_id"),
            context_id=data.get("context_id", ""),
            intent=data.get("intent", ""),
            skill=data.get("skill", ""),
            project=data.get("project", ""),
            status=WorkOrderStatus(data.get("status", "pending")),
            environment=Environment(env_val) if env_val else None,
            environment_rationale=data.get("environment_rationale", ""),
            department_target=data.get("department_target"),
            input=WorkOrderInput(
                text=inp_data.get("text", ""),
                structured=inp_data.get("structured", {}),
                files=inp_data.get("files", []),
                context=WorkOrderContext(
                    spec_section=ctx_data.get("spec_section", ""),
                    prerequisite_outputs=ctx_data.get("prerequisite_outputs", []),
                    constraints=ctx_data.get("constraints", []),
                ),
            ),
            constraints=WorkOrderConstraints(
                max_token_budget=constraints_data.get("max_token_budget", 100_000),
                timeout_ms=constraints_data.get("timeout_ms", 600_000),
                quality_tier=constraints_data.get("quality_tier", "standard"),
                permission_mode=constraints_data.get("permission_mode", "bypassPermissions"),
            ),
            output_schema=data.get("output_schema"),
            assignment=WorkOrderAssignment(
                agent_type=assign_data.get("agent_type", ""),
                agent_id=assign_data.get("agent_id", ""),
                model=assign_data.get("model", ""),
                assigned_at=assign_data.get("assigned_at", ""),
            ),
            execution=WorkOrderExecution(
                started_at=exec_data.get("started_at", ""),
                completed_at=exec_data.get("completed_at", ""),
                retries=exec_data.get("retries", 0),
                max_retries=exec_data.get("max_retries", 3),
            ),
            output=WorkOrderOutput(
                result=out_data.get("result", ""),
                artifacts=out_data.get("artifacts", []),
                token_usage=out_data.get("token_usage", 0),
                verification_status=out_data.get("verification_status", ""),
                confidence=out_data.get("confidence", 0.0),
            ),
            dependencies=tuple(data.get("dependencies", [])),
            # S07
            idempotency_key=data.get("idempotency_key"),
            trigger_source=data.get("trigger_source", "dispatcher"),
            cost_cap_usd=data.get("cost_cap_usd"),
            retry_of=data.get("retry_of"),
            attempt_number=data.get("attempt_number", 1),
            # Sprint 07.01 — None when absent (legacy rows + existing
            # call sites) so backward-compat is preserved.
            decomposition=(
                Decomposition.from_dict(data["decomposition"])
                if data.get("decomposition") is not None
                else None
            ),
        )
