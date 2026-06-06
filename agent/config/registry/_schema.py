"""Pydantic schema for agent/config/registry/ entries — events, metrics, actions.

Per Plan E Obj 5 + E-O6: registry is the contract the frontend builds against.
Loader at agent/bridge/registry_loader.py validates these at startup.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Category(str, Enum):
    """The eight registry categories per Plan E line 86."""

    HEALTH_STATUS = "Health & Status"
    WORK_PROGRESS = "Work & Progress"
    ACTIONABLE_HITL = "Actionable/HITL"
    COST_RESOURCES = "Cost & Resources"
    MEMORY = "Memory"
    AGENTS = "Agents"
    SERVICES = "Services"
    JOBS = "Jobs"


class _BaseEntry(BaseModel):
    """Shared fields per Plan E Obj 5: 'name, category, schema, access method, source module'."""

    name: str = Field(min_length=1, max_length=120)
    category: Category
    description: str = Field(default="", max_length=400)
    source_module: str = Field(
        min_length=1,
        description="Bridge module that owns this entry (e.g. 'bridge.cost_tracker')",
    )
    schema_ref: str = Field(
        default="",
        description=(
            "Pointer to the data shape — JSONSchema $id, dataclass name, "
            "or in-line description"
        ),
    )


class EventEntry(_BaseEntry):
    kind: Literal["event"] = "event"
    event_type: str = Field(
        description="The string published via EventBus.publish(Event(event_type=...))"
    )
    access_method: Literal["push:event_bus", "ws:/ws/events"] = "push:event_bus"


class MetricEntry(_BaseEntry):
    kind: Literal["metric"] = "metric"
    metric_name: str
    access_method: Literal[
        "pull:/api/metrics/{name}", "pull:/healthz"
    ] = "pull:/api/metrics/{name}"


class ActionEntry(_BaseEntry):
    kind: Literal["action"] = "action"
    method: Literal["GET", "POST", "PUT", "DELETE", "WS"]
    path: str = Field(description="HTTP/WS path, e.g. '/api/cost' or '/ws/events'")
    auth: Literal["bearer", "none"] = "bearer"
    access_method: Literal["rest", "ws"] = "rest"

    @field_validator("path")
    @classmethod
    def _path_starts_with_slash(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("path must start with '/'")
        return v
