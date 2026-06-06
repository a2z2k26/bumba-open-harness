"""Tests for agent/bridge/registry_loader.py and agent/config/registry/_schema.py.

Sprint E2.4 — schema + loader contract.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from config.registry._schema import (
    ActionEntry,
    Category,
    EventEntry,
    MetricEntry,
)
from bridge.registry_loader import RegistryIndex, RegistryLoader


# ---------------------------------------------------------------------------
# Schema unit tests
# ---------------------------------------------------------------------------


class TestEventEntry:
    def test_requires_event_type(self) -> None:
        with pytest.raises(Exception):  # pydantic ValidationError
            EventEntry(
                name="X",
                category=Category.HEALTH_STATUS,
                source_module="bridge.foo",
            )

    def test_accepts_canonical_example(self) -> None:
        e = EventEntry(
            name="Session Started",
            category=Category.AGENTS,
            source_module="bridge.session_manager",
            event_type="session.started",
        )
        assert e.event_type == "session.started"
        assert e.kind == "event"
        assert e.access_method == "push:event_bus"

    def test_access_method_ws(self) -> None:
        e = EventEntry(
            name="X",
            category=Category.HEALTH_STATUS,
            source_module="bridge.foo",
            event_type="foo",
            access_method="ws:/ws/events",
        )
        assert e.access_method == "ws:/ws/events"

    def test_invalid_access_method_rejected(self) -> None:
        with pytest.raises(Exception):
            EventEntry(
                name="X",
                category=Category.HEALTH_STATUS,
                source_module="bridge.foo",
                event_type="foo",
                access_method="invalid",  # type: ignore[arg-type]
            )


class TestMetricEntry:
    def test_requires_metric_name(self) -> None:
        with pytest.raises(Exception):
            MetricEntry(
                name="X",
                category=Category.HEALTH_STATUS,
                source_module="bridge.metrics",
            )

    def test_accepts_canonical_example(self) -> None:
        m = MetricEntry(
            name="Request Count",
            category=Category.HEALTH_STATUS,
            source_module="bridge.metrics",
            metric_name="request_count",
        )
        assert m.metric_name == "request_count"
        assert m.kind == "metric"


class TestActionEntry:
    def test_path_must_start_with_slash(self) -> None:
        with pytest.raises(Exception):
            ActionEntry(
                name="X",
                category=Category.COST_RESOURCES,
                source_module="bridge.api_server",
                method="GET",
                path="api/cost",  # missing leading slash
            )

    def test_accepts_canonical_example(self) -> None:
        a = ActionEntry(
            name="Get Cost",
            category=Category.COST_RESOURCES,
            source_module="bridge.api_server",
            method="GET",
            path="/api/cost",
        )
        assert a.path == "/api/cost"
        assert a.method == "GET"
        assert a.kind == "action"
        assert a.auth == "bearer"

    def test_invalid_method_rejected(self) -> None:
        with pytest.raises(Exception):
            ActionEntry(
                name="X",
                category=Category.HEALTH_STATUS,
                source_module="bridge.api_server",
                method="PATCH",  # type: ignore[arg-type]
                path="/api/x",
            )

    def test_ws_action(self) -> None:
        a = ActionEntry(
            name="WS Events",
            category=Category.HEALTH_STATUS,
            source_module="bridge.api_server",
            method="WS",
            path="/ws/events",
            auth="none",
            access_method="ws",
        )
        assert a.access_method == "ws"


class TestCategory:
    def test_all_eight_values(self) -> None:
        expected = {
            "Health & Status",
            "Work & Progress",
            "Actionable/HITL",
            "Cost & Resources",
            "Memory",
            "Agents",
            "Services",
            "Jobs",
        }
        actual = {c.value for c in Category}
        assert actual == expected

    def test_category_from_string(self) -> None:
        c = Category("Cost & Resources")
        assert c == Category.COST_RESOURCES


# ---------------------------------------------------------------------------
# Loader unit tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry_root(tmp_path: Path) -> Path:
    """Create a minimal registry root with three subdirectories."""
    (tmp_path / "events").mkdir()
    (tmp_path / "metrics").mkdir()
    (tmp_path / "actions").mkdir()
    return tmp_path


class TestLoaderEmptyRoot:
    def test_returns_empty_index_on_missing_dirs(self, tmp_path: Path) -> None:
        index = RegistryLoader().load_all(tmp_path / "nonexistent")
        assert index.events == []
        assert index.metrics == []
        assert index.actions == []
        assert index.errors == []

    def test_empty_dirs_yield_empty_index(self, registry_root: Path) -> None:
        index = RegistryLoader().load_all(registry_root)
        assert index.events == []
        assert index.metrics == []
        assert index.actions == []
        assert index.errors == []


class TestLoaderValidEntry:
    def test_valid_event_entry_indexed(self, registry_root: Path) -> None:
        (registry_root / "events" / "test.yaml").write_text(
            textwrap.dedent("""\
                session_started:
                  kind: event
                  name: Session Started
                  category: "Agents"
                  source_module: bridge.session_manager
                  event_type: session.started
            """)
        )
        index = RegistryLoader().load_all(registry_root)
        assert len(index.events) == 1
        assert index.events[0].event_type == "session.started"
        assert index.errors == []

    def test_valid_metric_entry_indexed(self, registry_root: Path) -> None:
        (registry_root / "metrics" / "test.yaml").write_text(
            textwrap.dedent("""\
                request_count:
                  kind: metric
                  name: Request Count
                  category: "Health & Status"
                  source_module: bridge.metrics
                  metric_name: request_count
            """)
        )
        index = RegistryLoader().load_all(registry_root)
        assert len(index.metrics) == 1
        assert index.metrics[0].metric_name == "request_count"
        assert index.errors == []

    def test_valid_action_entry_indexed(self, registry_root: Path) -> None:
        (registry_root / "actions" / "test.yaml").write_text(
            textwrap.dedent("""\
                api_cost:
                  kind: action
                  name: Get Cost
                  category: "Cost & Resources"
                  source_module: bridge.api_server
                  method: GET
                  path: /api/cost
            """)
        )
        index = RegistryLoader().load_all(registry_root)
        assert len(index.actions) == 1
        assert index.actions[0].path == "/api/cost"
        assert index.errors == []


class TestLoaderInvalidEntry:
    def test_invalid_entry_recorded_not_raised(self, registry_root: Path) -> None:
        (registry_root / "events" / "bad.yaml").write_text(
            textwrap.dedent("""\
                broken_event:
                  name: Missing Required Fields
                  category: "Agents"
                  source_module: bridge.foo
                  # event_type is missing — required field
            """)
        )
        # Must not raise
        index = RegistryLoader().load_all(registry_root)
        assert len(index.errors) == 1
        assert index.errors[0].entry_key == "broken_event"
        assert index.events == []

    def test_yaml_parse_error_recorded_not_raised(self, registry_root: Path) -> None:
        (registry_root / "events" / "malformed.yaml").write_text(
            "key: [unclosed bracket\n"
        )
        # Must not raise
        index = RegistryLoader().load_all(registry_root)
        assert len(index.errors) == 1
        assert index.errors[0].entry_key == "<file>"

    def test_mixed_valid_and_invalid(self, registry_root: Path) -> None:
        (registry_root / "events" / "mixed.yaml").write_text(
            textwrap.dedent("""\
                good_event:
                  kind: event
                  name: Good
                  category: "Agents"
                  source_module: bridge.session_manager
                  event_type: good.event

                bad_event:
                  name: Bad (missing event_type)
                  category: "Agents"
                  source_module: bridge.foo
            """)
        )
        index = RegistryLoader().load_all(registry_root)
        assert len(index.events) == 1
        assert len(index.errors) == 1
        assert index.events[0].event_type == "good.event"


# ---------------------------------------------------------------------------
# Find-* API tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def populated_index(registry_root: Path) -> RegistryIndex:
    (registry_root / "events" / "e.yaml").write_text(
        textwrap.dedent("""\
            cost_summary:
              kind: event
              name: Cost Summary
              category: "Cost & Resources"
              source_module: bridge.cost_tracker
              event_type: cost.daily_summary
        """)
    )
    (registry_root / "metrics" / "m.yaml").write_text(
        textwrap.dedent("""\
            req_count:
              kind: metric
              name: Request Count
              category: "Health & Status"
              source_module: bridge.metrics
              metric_name: request_count
        """)
    )
    (registry_root / "actions" / "a.yaml").write_text(
        textwrap.dedent("""\
            api_cost:
              kind: action
              name: Get Cost
              category: "Cost & Resources"
              source_module: bridge.api_server
              method: GET
              path: /api/cost
        """)
    )
    return RegistryLoader().load_all(registry_root)


class TestFindAPIs:
    def test_find_event_by_type_returns_match(
        self, populated_index: RegistryIndex
    ) -> None:
        result = populated_index.find_event_by_type("cost.daily_summary")
        assert result is not None
        assert result.name == "Cost Summary"

    def test_find_event_by_type_returns_none_on_miss(
        self, populated_index: RegistryIndex
    ) -> None:
        assert populated_index.find_event_by_type("nonexistent") is None

    def test_find_metric_by_name_returns_match(
        self, populated_index: RegistryIndex
    ) -> None:
        result = populated_index.find_metric_by_name("request_count")
        assert result is not None
        assert result.name == "Request Count"

    def test_find_metric_by_name_returns_none_on_miss(
        self, populated_index: RegistryIndex
    ) -> None:
        assert populated_index.find_metric_by_name("nonexistent") is None

    def test_find_action_by_path_returns_match(
        self, populated_index: RegistryIndex
    ) -> None:
        result = populated_index.find_action_by_path("GET", "/api/cost")
        assert result is not None
        assert result.name == "Get Cost"

    def test_find_action_by_path_returns_none_on_wrong_method(
        self, populated_index: RegistryIndex
    ) -> None:
        assert populated_index.find_action_by_path("POST", "/api/cost") is None

    def test_find_action_by_path_returns_none_on_wrong_path(
        self, populated_index: RegistryIndex
    ) -> None:
        assert populated_index.find_action_by_path("GET", "/api/other") is None


# ---------------------------------------------------------------------------
# Sample fixtures smoke test
# ---------------------------------------------------------------------------


class TestSampleFixtures:
    """Verify that the checked-in sample YAML fixtures load without errors."""

    def test_sample_fixtures_load_cleanly(self) -> None:
        # Locate agent/config/registry relative to this test file
        tests_dir = Path(__file__).parent
        registry_root = tests_dir.parent / "config" / "registry"
        if not registry_root.exists():
            pytest.skip("Registry root not found at expected path")

        index = RegistryLoader().load_all(registry_root)
        # Sample fixtures provide at least one entry per kind
        assert len(index.events) >= 1, "Expected at least 1 event from sample fixtures"
        assert len(index.metrics) >= 1, "Expected at least 1 metric from sample fixtures"
        assert len(index.actions) >= 1, "Expected at least 1 action from sample fixtures"
        assert index.errors == [], f"Unexpected errors: {index.errors}"
