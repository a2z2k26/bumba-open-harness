"""Pydantic schema for Zone 4 Layer 2 workflow YAML definitions.

A workflow is a sequence (or partial-DAG) of Zone 4 department invocations,
primitive actions, and operator gates.  The YAML is validated at load time so
typos fail fast rather than at runtime.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class WorkflowBudget(BaseModel):
    """Aggregate cost and duration cap for an entire workflow run."""

    max_cost_usd: float = Field(
        default=5.0,
        gt=0,
        description="Maximum total cost across all steps (USD).",
    )
    max_duration_seconds: int = Field(
        default=600,
        gt=0,
        description="Wall-clock timeout for the entire workflow (seconds).",
    )


# ---------------------------------------------------------------------------
# Step variants
# ---------------------------------------------------------------------------


class DepartmentStep(BaseModel):
    """A step that invokes a Zone 4 department."""

    name: str
    department: Literal["strategy", "ops", "board", "qa", "design", "job_search"]
    intent: str = Field(description="Natural-language task for the department.")
    inputs: list[str] = Field(
        default_factory=list,
        description="Keys from the shared workflow context to inject.",
    )
    outputs: list[str] = Field(
        default_factory=list,
        description="Keys this step writes into the shared workflow context.",
    )
    parallel_with: str | None = Field(
        default=None,
        description="Name of another step that can run concurrently with this one.",
    )
    cost_limit_usd: float | None = Field(
        default=None,
        description="Per-step cost cap (USD). Defaults to None = no per-step limit.",
    )
    on_failure: list[str] = Field(
        default_factory=list,
        description="Names of compensating steps to run in reverse order on failure.",
    )
    # type discriminator
    type: Literal["department"] = "department"


class GateStep(BaseModel):
    """An operator-approval gate that pauses workflow execution."""

    name: str
    gate: Literal["operator"]
    timeout_seconds: int = Field(
        default=3600,
        gt=0,
        description="Seconds to wait for operator response before timing out.",
    )
    message: str = Field(
        description="Message template shown to operator (may reference {context_key} placeholders).",
    )
    condition: str | None = Field(
        default=None,
        description="Optional Python-like expression; gate is skipped when condition evaluates to False. "
        'Example: "{confidence} < 0.7"',
    )
    on_failure: list[str] = Field(
        default_factory=list,
        description="Names of compensating steps to run if the gate times out or is rejected.",
    )
    type: Literal["gate"] = "gate"


class ActionStep(BaseModel):
    """A built-in primitive action (Discord post, GitHub comment, etc.)."""

    name: str
    action: Literal["publish_discord", "publish_github_comment"]
    channel: str | None = None
    target: str | None = None
    message: str = Field(
        description="Message template (may reference {context_key} placeholders).",
    )
    on_failure: list[str] = Field(
        default_factory=list,
        description="Names of compensating steps to run if this action fails.",
    )
    type: Literal["action"] = "action"


# Union discriminated by presence of keys rather than a Literal field so
# plain YAML that lacks a 'type' key is still handled correctly.
WorkflowStep = DepartmentStep | GateStep | ActionStep


# ---------------------------------------------------------------------------
# Top-level workflow
# ---------------------------------------------------------------------------


class WorkflowConfig(BaseModel):
    """Top-level workflow definition loaded from YAML."""

    name: str = Field(description="Unique workflow identifier (kebab-case).")
    trigger: Literal["explicit", "schedule", "webhook"] = Field(
        description="How this workflow is initiated.",
    )
    schedule: str | None = Field(
        default=None,
        description='Cron expression prefixed with "cron:" when trigger=schedule.',
    )
    webhook: str | None = Field(
        default=None,
        description='Webhook event name, e.g. "github.pull_request.opened", when trigger=webhook.',
    )
    budget: WorkflowBudget = Field(default_factory=WorkflowBudget)
    steps: list[Any] = Field(
        default_factory=list,
        description="Ordered list of workflow steps.",
    )

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("cron:"):
            raise ValueError("schedule must start with 'cron:' — e.g. 'cron:0 8 * * 1'")
        return v

    @model_validator(mode="after")
    def validate_trigger_fields(self) -> "WorkflowConfig":
        if self.trigger == "schedule" and not self.schedule:
            raise ValueError("trigger=schedule requires a 'schedule' field")
        if self.trigger == "webhook" and not self.webhook:
            raise ValueError("trigger=webhook requires a 'webhook' field")
        return self

    @model_validator(mode="after")
    def validate_step_names_unique(self) -> "WorkflowConfig":
        names = [s.get("name") if isinstance(s, dict) else s.name for s in self.steps]
        seen: set[str] = set()
        for n in names:
            if n in seen:
                raise ValueError(f"Duplicate step name: '{n}'")
            seen.add(n)
        return self

    @model_validator(mode="after")
    def validate_parallel_refs(self) -> "WorkflowConfig":
        """Every parallel_with reference must point to an existing step name."""
        step_names = {
            s.get("name") if isinstance(s, dict) else s.name
            for s in self.steps
        }
        for step in self.steps:
            if isinstance(step, dict):
                ref = step.get("parallel_with")
            else:
                ref = getattr(step, "parallel_with", None)
            if ref and ref not in step_names:
                raise ValueError(
                    f"parallel_with='{ref}' references unknown step"
                )
        return self


# ---------------------------------------------------------------------------
# Loader helper
# ---------------------------------------------------------------------------


def load_workflow_config(yaml_text: str) -> WorkflowConfig:
    """Parse and validate a workflow YAML string.

    Steps are parsed into typed objects via the WorkflowStep discriminated
    union.  Raises ``pydantic.ValidationError`` on schema violations.
    """
    try:
        import yaml  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("PyYAML is required to load workflow configs") from exc

    raw: dict[str, Any] = yaml.safe_load(yaml_text)

    # Parse steps into typed objects
    typed_steps: list[WorkflowStep] = []
    for raw_step in raw.get("steps", []):
        typed_steps.append(_parse_step(raw_step))
    raw["steps"] = typed_steps

    return WorkflowConfig.model_validate(raw)


def _parse_step(raw: dict[str, Any]) -> WorkflowStep:
    """Infer step type and return a typed step model."""
    if "department" in raw:
        return DepartmentStep.model_validate(raw)
    if "gate" in raw:
        return GateStep.model_validate(raw)
    if "action" in raw:
        return ActionStep.model_validate(raw)
    # Default: attempt DepartmentStep — will raise a clear ValidationError
    return DepartmentStep.model_validate(raw)
