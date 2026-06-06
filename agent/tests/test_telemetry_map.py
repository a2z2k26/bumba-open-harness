"""Tests for ``scripts/check_telemetry_map.py``.

Sprint R7.3 acceptance: at least two high-risk operations have direct
tests. The first lives in ``tests/test_chief_dispatcher_readiness.py``
(R1.4) for the dispatch event lineage. This file covers the second:
parser correctness + the doc/registry agreement check itself.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_telemetry_map import (
    CheckResult,
    check,
    main,
    parse_map_events,
    parse_registry_events,
    render_text,
)


# ---------------------------------------------------------------------------
# parse_map_events
# ---------------------------------------------------------------------------


class TestParseMapEvents:
    def test_extracts_events_from_event_rows(self):
        text = "\n".join([
            "## Map",
            "",
            "### 1. Dispatch (happy path)",
            "",
            "| Surface | Identifier | Source |",
            "|---|---|---|",
            "| Event | `chief_dispatcher.routed` | `bridge.chief_dispatcher` |",
            "| Event | `chief_session.created` | `bridge.chief_dispatcher` |",
            "",
            "## See also",
        ])
        events = parse_map_events(text)
        assert events == {"chief_dispatcher.routed", "chief_session.created"}

    def test_ignores_non_event_rows(self):
        """Metric / Log / Side effect rows must NOT be sampled."""
        text = "\n".join([
            "## Map",
            "",
            "| Event | `chief_dispatcher.routed` | src |",
            "| Metric | `chief_session.cost.usd` | src |",
            "| Log | `INFO chief_dispatcher.routed wo=%s` | src |",
            "| Side effect | `data/halt.flag` exists | src |",
            "",
            "## See also",
        ])
        events = parse_map_events(text)
        # Only the Event row's identifier counts.
        assert events == {"chief_dispatcher.routed"}

    def test_ignores_map_coverage_gaps_section(self):
        """The deferred-gaps section sits at sibling H2 and must be excluded."""
        text = "\n".join([
            "## Map",
            "",
            "| Event | `chief_dispatcher.routed` | src |",
            "",
            "## Map coverage gaps (deferred)",
            "",
            "| Event | `webhook.auth.failed` | not yet emitted |",
            "",
            "## See also",
        ])
        events = parse_map_events(text)
        assert events == {"chief_dispatcher.routed"}
        assert "webhook.auth.failed" not in events

    def test_ignores_module_paths_and_file_paths(self):
        text = "\n".join([
            "## Map",
            "",
            "| Event | `bridge.chief_dispatcher` | not an event |",
            "| Event | `agent/config/something.yaml` | not an event |",
            "| Event | `chief_session.timed_out` | real event |",
            "",
            "## See also",
        ])
        events = parse_map_events(text)
        assert events == {"chief_session.timed_out"}

    def test_returns_empty_when_no_map_section(self):
        text = "# nothing useful\n\n| Event | `whatever.x` | y |\n"
        assert parse_map_events(text) == set()


# ---------------------------------------------------------------------------
# parse_registry_events
# ---------------------------------------------------------------------------


class TestParseRegistryEvents:
    def test_collects_event_types_from_yaml(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "a.yaml").write_text(
            "entry_one:\n"
            "  kind: event\n"
            "  event_type: foo.bar\n"
            "entry_two:\n"
            "  kind: event\n"
            "  event_type: foo.baz\n"
        )
        (events_dir / "b.yaml").write_text(
            "entry_three:\n"
            "  kind: event\n"
            "  event_type: qux.quux\n"
        )
        events = parse_registry_events(events_dir)
        assert events == {"foo.bar", "foo.baz", "qux.quux"}

    def test_ignores_non_event_entries(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "a.yaml").write_text(
            "entry_with_no_event_type:\n"
            "  kind: event\n"
            "  description: missing event_type\n"
            "entry_with_event_type:\n"
            "  kind: event\n"
            "  event_type: real.event\n"
        )
        events = parse_registry_events(events_dir)
        assert events == {"real.event"}

    def test_raises_when_dir_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_registry_events(tmp_path / "absent")


# ---------------------------------------------------------------------------
# check + integration with the live registry
# ---------------------------------------------------------------------------


class TestCheck:
    def test_clean_when_map_subset_of_registry(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "a.yaml").write_text(
            "x:\n"
            "  event_type: chief_dispatcher.routed\n"
            "y:\n"
            "  event_type: chief_session.created\n"
            "z:\n"
            "  event_type: chief_session.state_changed\n"
        )
        text = "\n".join([
            "## Map",
            "| Event | `chief_dispatcher.routed` | src |",
            "| Event | `chief_session.created` | src |",
            "## See also",
        ])
        result = check(text, events_dir)
        assert result.ok is True
        assert result.missing_from_registry == []
        assert "chief_session.state_changed" in result.missing_from_map

    def test_fails_when_map_names_unknown_event(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "a.yaml").write_text(
            "x:\n  event_type: chief_dispatcher.routed\n"
        )
        text = "\n".join([
            "## Map",
            "| Event | `chief_dispatcher.routed` | src |",
            "| Event | `chief_dispatcher.invented_event` | src |",
            "## See also",
        ])
        result = check(text, events_dir)
        assert result.ok is False
        assert "chief_dispatcher.invented_event" in result.missing_from_registry


# ---------------------------------------------------------------------------
# Live-tree integration: the real map and the real registry must agree.
# This is the high-risk-path direct test the R7.3 spec requires.
# ---------------------------------------------------------------------------


class TestLiveAgreement:
    """Run check() against the actual repo tree.

    If this test fails, either the map cited an event that's not in the
    registry, or the parser broke. Either way the operator needs to see
    it before merge.
    """

    def test_telemetry_map_agrees_with_registry(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        map_path = repo_root / "docs" / "observability" / "telemetry-map.md"
        events_dir = repo_root / "agent" / "config" / "registry" / "events"
        assert map_path.is_file(), f"map not found at {map_path}"
        assert events_dir.is_dir(), f"events dir not found at {events_dir}"

        result = check(map_path.read_text(encoding="utf-8"), events_dir)
        assert result.missing_from_registry == [], (
            "telemetry map names events that have no registry entry: "
            f"{result.missing_from_registry}"
        )
        # The live map should cover at least the dispatch/session lineage
        # — proves the parser found something, not zero.
        assert len(result.map_events) >= 5


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------


class TestMainExitCodes:
    def test_exit_zero_on_clean_check(self, tmp_path, capsys):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "a.yaml").write_text(
            "x:\n  event_type: chief_dispatcher.routed\n"
        )
        map_path = tmp_path / "map.md"
        map_path.write_text(
            "## Map\n| Event | `chief_dispatcher.routed` | src |\n## See also\n"
        )
        rc = main([
            "--map", str(map_path),
            "--events-dir", str(events_dir),
        ])
        assert rc == 0

    def test_exit_one_when_map_names_unknown_event(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "a.yaml").write_text(
            "x:\n  event_type: chief_dispatcher.routed\n"
        )
        map_path = tmp_path / "map.md"
        map_path.write_text(
            "## Map\n| Event | `chief_dispatcher.invented` | src |\n## See also\n"
        )
        rc = main([
            "--map", str(map_path),
            "--events-dir", str(events_dir),
        ])
        assert rc == 1

    def test_exit_two_when_map_missing(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        rc = main([
            "--map", str(tmp_path / "absent.md"),
            "--events-dir", str(events_dir),
        ])
        assert rc == 2

    def test_strict_bidirectional_fails_when_registry_richer(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "a.yaml").write_text(
            "x:\n  event_type: chief_dispatcher.routed\n"
            "y:\n  event_type: chief_session.created\n"
        )
        map_path = tmp_path / "map.md"
        map_path.write_text(
            "## Map\n| Event | `chief_dispatcher.routed` | src |\n## See also\n"
        )
        rc = main([
            "--map", str(map_path),
            "--events-dir", str(events_dir),
            "--strict-bidirectional",
        ])
        assert rc == 1


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


class TestRenderText:
    def test_text_lists_missing_events(self):
        result = CheckResult(
            map_events={"a.b"},
            registry_events={"c.d"},
            missing_from_registry=["a.b"],
            missing_from_map=["c.d"],
        )
        text = render_text(result, strict_bidirectional=False)
        assert "MISSING FROM REGISTRY" in text
        assert "a.b" in text
        # Without --strict, missing_from_map section is suppressed.
        assert "MISSING FROM MAP" not in text

    def test_text_lists_both_directions_when_strict(self):
        result = CheckResult(
            map_events={"a.b"},
            registry_events={"c.d"},
            missing_from_registry=["a.b"],
            missing_from_map=["c.d"],
        )
        text = render_text(result, strict_bidirectional=True)
        assert "MISSING FROM REGISTRY" in text
        assert "MISSING FROM MAP" in text
        assert "c.d" in text
