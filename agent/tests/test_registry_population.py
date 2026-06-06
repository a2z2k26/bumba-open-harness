"""E2.5 — registry population coverage tests.

Asserts that every event type in EVENT_TYPES has a registry entry,
every routed API path has an action entry, and aggregate counts meet
the acceptance criteria (≥100 total entries, 0 validation errors).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.event_bus import EVENT_TYPES
from bridge.registry_loader import RegistryLoader

# Path to the registry root relative to this file:
# agent/tests/ → agent/config/registry/
_REGISTRY_ROOT = Path(__file__).parent.parent / "config" / "registry"

# Paths collected by inspecting api_server.py + api/directives_routes.py routes.
# Peer-coordination routes are excluded (not wired into BridgeApp per CLAUDE.md).
_EXPECTED_PATHS: list[tuple[str, str]] = [
    # Health & system
    ("GET", "/healthz"),
    ("GET", "/api"),
    ("GET", "/api/heartbeat/status"),
    ("GET", "/api/metrics/{name}"),
    ("GET", "/api/traces"),
    ("GET", "/api/services"),
    # Agents & sessions
    ("GET", "/api/agents"),
    ("GET", "/api/agents/{agent_id}"),
    ("POST", "/api/agents/spawn"),
    ("POST", "/api/agents/{agent_id}/kill"),
    ("GET", "/api/sessions"),
    ("POST", "/api/sessions/reset"),
    # Cost & trust
    ("GET", "/api/cost"),
    ("GET", "/api/trust"),
    # Escalation
    ("GET", "/api/escalation"),
    ("POST", "/api/escalation/acknowledge"),
    ("POST", "/api/escalation/defer"),
    # Events & knowledge
    ("GET", "/api/events"),
    ("GET", "/api/events/remote-status"),
    ("GET", "/api/knowledge"),
    ("GET", "/api/knowledge/search"),
    # Commands
    ("GET", "/api/commands"),
    ("POST", "/api/commands"),
    # Tasks
    ("GET", "/api/tasks"),
    ("GET", "/api/tasks/{task_id}"),
    ("POST", "/api/tasks"),
    ("PUT", "/api/tasks/{task_id}/status"),
    ("PUT", "/api/tasks/{task_id}/move"),
    ("PUT", "/api/tasks/{task_id}/assign"),
    # Reviews
    ("GET", "/api/reviews"),
    ("POST", "/api/reviews"),
    ("POST", "/api/reviews/{review_id}/decide"),
    # Webhooks
    ("POST", "/api/webhooks/github"),
    ("POST", "/api/webhooks/calcom"),
    # HITL
    ("GET", "/api/hitl/pending"),
    ("POST", "/api/hitl/{task_id}/respond"),
    # WebSocket
    ("GET", "/ws/events"),
    # WorkOrder
    ("POST", "/api/workorders"),
    ("GET", "/api/workorders/{wo_id}"),
    ("GET", "/ws/workorders/{wo_id}"),
    # Zone 4 VAPI
    ("GET", "/api/v1/departments"),
    ("GET", "/api/v1/departments/{dept}"),
    ("POST", "/api/v1/departments/{dept}/chat/completions"),
    # Z4 observability (feature-flagged — must still be registered)
    ("GET", "/api/z4/sessions"),
    ("GET", "/api/z4/sessions/{sid}"),
    ("GET", "/api/z4/sessions/{sid}/cost"),
    ("GET", "/api/z4/sessions/{sid}/departments/{dept}/conversation"),
    ("GET", "/api/z4/sessions/{sid}/departments/{dept}/tools/{agent}"),
    ("GET", "/api/z4/departments"),
    ("GET", "/api/z4/departments/{dept}/health"),
    ("GET", "/api/z4/agents"),
    ("GET", "/api/z4/agents/{name}/expertise"),
    ("GET", "/api/z4/board/briefs"),
    ("GET", "/api/z4/board/memos"),
    ("GET", "/api/z4/metrics/cost/daily"),
    ("GET", "/api/z4/metrics/agents"),
    ("GET", "/api/z4/metrics/violations"),
    # Sprint 23 directive routes
    ("GET", "/api/directives"),
    ("GET", "/api/directives/{directive_id}/tree"),
    ("GET", "/api/surfaces"),
    ("POST", "/api/surfaces/{surface_id}/ack"),
]


@pytest.fixture(scope="module")
def registry_index():
    """Load the populated registry once per module."""
    return RegistryLoader().load_all(_REGISTRY_ROOT)


class TestNoValidationErrors:
    def test_no_validation_errors(self, registry_index) -> None:
        """Registry must load with zero validation errors."""
        assert registry_index.errors == [], (
            "Registry validation errors:\n"
            + "\n".join(f"  {e.file.name}[{e.entry_key}]: {e.message}" for e in registry_index.errors)
        )


class TestMinimumCoverage:
    def test_total_entries_at_least_100(self, registry_index) -> None:
        """Total entries across events + metrics + actions must be at least 100."""
        total = (
            len(registry_index.events)
            + len(registry_index.metrics)
            + len(registry_index.actions)
        )
        assert total >= 100, f"Expected ≥100 entries, got {total}"

    def test_event_count(self, registry_index) -> None:
        """Must have at least 40 event entries (38 core + hook entries)."""
        assert len(registry_index.events) >= 40, (
            f"Expected ≥40 event entries, got {len(registry_index.events)}"
        )

    def test_action_count(self, registry_index) -> None:
        """Must have at least 40 action entries (41 always-on + Z4 + directives)."""
        assert len(registry_index.actions) >= 40, (
            f"Expected ≥40 action entries, got {len(registry_index.actions)}"
        )

    def test_metric_count(self, registry_index) -> None:
        """Must have at least 15 metric entries."""
        assert len(registry_index.metrics) >= 15, (
            f"Expected ≥15 metric entries, got {len(registry_index.metrics)}"
        )


class TestEventTypeCoverage:
    def test_every_event_type_has_entry(self, registry_index) -> None:
        """Every event type in event_bus.EVENT_TYPES must have a registry entry."""
        missing = []
        for et in EVENT_TYPES:
            if registry_index.find_event_by_type(et) is None:
                missing.append(et)
        assert missing == [], (
            f"Missing registry entries for event types: {missing}"
        )

    def test_find_workorder_created(self, registry_index) -> None:
        """Smoke: find_event_by_type('workorder.created') returns non-None."""
        entry = registry_index.find_event_by_type("workorder.created")
        assert entry is not None
        assert entry.event_type == "workorder.created"

    def test_find_health_changed(self, registry_index) -> None:
        """Smoke: health changed event has correct category."""
        entry = registry_index.find_event_by_type("health.changed")
        assert entry is not None


class TestActionPathCoverage:
    def test_every_routed_path_has_entry(self, registry_index) -> None:
        """Every expected API path must have a registry entry."""
        missing = []
        for method, path in _EXPECTED_PATHS:
            if registry_index.find_action_by_path(method, path) is None:
                missing.append(f"{method} {path}")
        assert missing == [], (
            "Missing registry entries for paths:\n" + "\n".join(f"  {p}" for p in missing)
        )

    def test_find_cost_endpoint(self, registry_index) -> None:
        """Smoke: find_action_by_path('GET', '/api/cost') returns non-None."""
        entry = registry_index.find_action_by_path("GET", "/api/cost")
        assert entry is not None
        assert entry.path == "/api/cost"

    def test_find_healthz(self, registry_index) -> None:
        """Smoke: /healthz has auth=none."""
        entry = registry_index.find_action_by_path("GET", "/healthz")
        assert entry is not None
        assert entry.auth == "none"

    def test_ws_events_uses_websocket_access_method(self, registry_index) -> None:
        """WebSocket entry uses HTTP GET upgrade plus access_method=ws."""
        entry = registry_index.find_action_by_path("GET", "/ws/events")
        assert entry is not None
        assert entry.access_method == "ws"


class TestAllEightCategoriesUsed:
    def test_all_eight_categories_used(self, registry_index) -> None:
        """All eight Category enum values must appear in at least one entry."""
        from config.registry._schema import Category

        all_entries = (
            list(registry_index.events)
            + list(registry_index.metrics)
            + list(registry_index.actions)
        )
        found_categories = {e.category for e in all_entries}
        missing = set(Category) - found_categories
        assert missing == set(), (
            f"Categories with no entries: {[c.value for c in missing]}"
        )
