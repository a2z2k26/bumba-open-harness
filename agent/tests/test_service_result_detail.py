"""Tests for /services detail view and narration field (Z2-S2.4)."""
from __future__ import annotations

import json
from pathlib import Path


from bridge.services.result import (
    SERVICE_NARRATIONS,
    SERVICE_SCHEDULES,
    ServiceResult,
    format_completion_line,
    render_service_detail,
    render_services_table,
    write_last_run,
)


# ---------------------------------------------------------------------------
# ServiceResult — narration field backward compatibility
# ---------------------------------------------------------------------------

class TestServiceResultNarration:
    def test_narration_defaults_to_none(self):
        r = ServiceResult(service="briefing", ok=True, work_items=0, duration_ms=100, cost_usd=0.0)
        assert r.narration is None

    def test_narration_can_be_set(self):
        r = ServiceResult(
            service="briefing",
            ok=True,
            work_items=3,
            duration_ms=200,
            cost_usd=0.01,
            narration="Noticed 3 goals drifting — queued in tomorrow's brief.",
        )
        assert r.narration == "Noticed 3 goals drifting — queued in tomorrow's brief."

    def test_narration_persisted_in_last_run_json(self, tmp_path):
        r = ServiceResult(
            service="briefing",
            ok=True,
            work_items=1,
            duration_ms=150,
            cost_usd=0.0,
            narration="Test narration.",
        )
        write_last_run(tmp_path, r)
        data = json.loads((tmp_path / "last_run.json").read_text())
        assert data["briefing"]["narration"] == "Test narration."

    def test_narration_null_when_not_set(self, tmp_path):
        r = ServiceResult(service="email", ok=True, work_items=0, duration_ms=50, cost_usd=0.0)
        write_last_run(tmp_path, r)
        data = json.loads((tmp_path / "last_run.json").read_text())
        assert data["email"]["narration"] is None

    def test_completion_line_unaffected_by_narration(self):
        r1 = ServiceResult(service="s", ok=True, work_items=1, duration_ms=100, cost_usd=0.0)
        r2 = ServiceResult(service="s", ok=True, work_items=1, duration_ms=100, cost_usd=0.0, narration="X")
        assert format_completion_line(r1) == format_completion_line(r2)


# ---------------------------------------------------------------------------
# SERVICE_NARRATIONS — static registry
# ---------------------------------------------------------------------------

class TestServiceNarrations:
    def test_all_known_services_have_narration(self):
        known = {"briefing", "checkin", "email", "calendar", "knowledge_review",
                 "retro", "weekly_review", "job_search", "job_search_execute"}
        for name in known:
            assert name in SERVICE_NARRATIONS, f"Missing narration for: {name}"
            assert len(SERVICE_NARRATIONS[name]) > 10

    def test_all_known_services_have_schedule(self):
        for name in SERVICE_NARRATIONS:
            assert name in SERVICE_SCHEDULES, f"Missing schedule for: {name}"

    def test_narrations_are_non_empty_strings(self):
        for name, narration in SERVICE_NARRATIONS.items():
            assert isinstance(narration, str)
            assert len(narration) > 0


# ---------------------------------------------------------------------------
# render_service_detail
# ---------------------------------------------------------------------------

def _write_run(state_dir: Path, name: str, **kwargs) -> None:
    """Helper to write a fake last_run.json entry."""
    path = state_dir / "last_run.json"
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    entry = {
        "ok": kwargs.get("ok", True),
        "work_items": kwargs.get("work_items", 0),
        "duration_ms": kwargs.get("duration_ms", 100),
        "cost_usd": kwargs.get("cost_usd", 0.0),
        "artifacts": kwargs.get("artifacts", []),
        "anomalies": kwargs.get("anomalies", []),
        "skip_reason": kwargs.get("skip_reason", None),
        "narration": kwargs.get("narration", None),
        "completed_at": kwargs.get("completed_at", "2026-04-17T08:05:00+00:00"),
        "completion_line": kwargs.get("completion_line", f"[SERVICE][OK {name}]"),
    }
    data[name] = entry
    state_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


class TestRenderServiceDetail:
    def test_unknown_service_lists_available(self, tmp_path):
        state_dir = tmp_path / "service_state"
        result = render_service_detail(tmp_path, "nonexistent_service_xyz")
        assert "nonexistent_service_xyz" in result
        assert "Available" in result

    def test_known_service_no_data_shows_static_narration(self, tmp_path):
        result = render_service_detail(tmp_path, "briefing")
        assert "briefing" in result
        # Static narration from SERVICE_NARRATIONS should appear
        assert SERVICE_NARRATIONS["briefing"][:20] in result

    def test_known_service_with_run_data_shows_completion_line(self, tmp_path):
        state_dir = tmp_path / "service_state"
        _write_run(state_dir, "briefing", completion_line="[SERVICE][OK briefing work_items=3]")
        result = render_service_detail(tmp_path, "briefing")
        assert "[SERVICE][OK briefing work_items=3]" in result

    def test_known_service_shows_completed_at(self, tmp_path):
        state_dir = tmp_path / "service_state"
        _write_run(state_dir, "email", completed_at="2026-04-17T10:00:00+00:00")
        result = render_service_detail(tmp_path, "email")
        assert "2026-04-17" in result

    def test_custom_narration_overrides_static(self, tmp_path):
        state_dir = tmp_path / "service_state"
        custom = "Handled 5 emails — 1 needs your eyes."
        _write_run(state_dir, "email", narration=custom)
        result = render_service_detail(tmp_path, "email")
        assert custom in result

    def test_anomalies_shown_when_present(self, tmp_path):
        state_dir = tmp_path / "service_state"
        _write_run(state_dir, "email", anomalies=["oauth_401", "empty_payload"])
        result = render_service_detail(tmp_path, "email")
        assert "oauth_401" in result
        assert "empty_payload" in result

    def test_schedule_always_shown(self, tmp_path):
        result = render_service_detail(tmp_path, "briefing")
        assert "08:00" in result  # from SERVICE_SCHEDULES["briefing"]

    def test_narration_truncated_at_1800_chars(self, tmp_path):
        state_dir = tmp_path / "service_state"
        long_narration = "x" * 2000
        _write_run(state_dir, "briefing", narration=long_narration)
        result = render_service_detail(tmp_path, "briefing")
        # Should not contain the full 2000-char string
        assert "x" * 2000 not in result
        assert "…" in result

    def test_service_detail_via_hyphenated_name_resolved(self, tmp_path):
        # "/services job-search" normalises to "job_search"
        # This is handled in the command handler, but we test the function
        # accepts underscore names directly.
        result = render_service_detail(tmp_path, "job_search")
        assert "job_search" in result

    def test_no_data_shows_no_run_data_message(self, tmp_path):
        result = render_service_detail(tmp_path, "briefing")
        assert "No run data" in result

    def test_artifacts_shown_when_present(self, tmp_path):
        state_dir = tmp_path / "service_state"
        _write_run(state_dir, "briefing", artifacts=["data/logs/2026/04/2026-04-17.md"])
        result = render_service_detail(tmp_path, "briefing")
        assert "2026-04-17.md" in result


# ---------------------------------------------------------------------------
# render_services_table — unchanged behaviour check
# ---------------------------------------------------------------------------

class TestRenderServicesTable:
    def test_no_file_returns_help_message(self, tmp_path):
        msg = render_services_table(tmp_path)
        assert "No service runs" in msg

    def test_shows_completion_line(self, tmp_path):
        state_dir = tmp_path / "service_state"
        _write_run(state_dir, "checkin", completion_line="[SERVICE][OK checkin work_items=1]")
        msg = render_services_table(tmp_path)
        assert "checkin" in msg
        assert "[SERVICE][OK checkin" in msg
