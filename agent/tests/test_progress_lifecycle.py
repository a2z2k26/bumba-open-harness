"""Tests for issue #13: Progress artifacts lifecycle integration."""

from __future__ import annotations

import pytest

from bridge.project_registry import ProjectRegistry


# ── ProjectRegistry.record_session_start ──

@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(data_dir=tmp_path)


class TestRecordSessionStart:
    def test_creates_progress_file(self, registry, tmp_path):
        registry.create_new("alpha")
        registry.record_session_start("alpha", "sess-abc")
        path = registry._progress_path("alpha")
        assert path.exists()

    def test_session_start_entry_has_timestamp(self, registry):
        registry.create_new("alpha")
        progress = registry.record_session_start("alpha", "sess-abc")
        assert len(progress["sessions"]) == 1
        entry = progress["sessions"][0]
        assert "timestamp" in entry
        assert len(entry["timestamp"]) > 0

    def test_session_start_entry_has_session_id(self, registry):
        registry.create_new("alpha")
        progress = registry.record_session_start("alpha", "sess-abc123")
        entry = progress["sessions"][0]
        assert entry.get("session_id") == "sess-abc123"

    def test_session_start_summary_is_placeholder(self, registry):
        registry.create_new("alpha")
        progress = registry.record_session_start("alpha", "sess-1")
        entry = progress["sessions"][0]
        assert entry["summary"] == "Session started."

    def test_multiple_starts_accumulate(self, registry):
        registry.create_new("alpha")
        registry.record_session_start("alpha", "sess-1")
        registry.record_session_start("alpha", "sess-2")
        progress = registry.get_progress("alpha")
        assert len(progress["sessions"]) == 2

    def test_capped_at_20(self, registry):
        registry.create_new("alpha")
        for i in range(25):
            registry.record_session_start("alpha", f"sess-{i}")
        progress = registry.get_progress("alpha")
        assert len(progress["sessions"]) == 20

    def test_persists_to_disk(self, registry):
        registry.create_new("alpha")
        registry.record_session_start("alpha", "sess-x")
        # Re-read from disk by creating a new registry instance
        registry2 = ProjectRegistry(data_dir=registry.data_dir)
        progress = registry2.get_progress("alpha")
        assert len(progress["sessions"]) == 1
        assert progress["sessions"][0]["session_id"] == "sess-x"


# ── record_session integration ──

class TestRecordSessionIntegration:
    def test_record_session_after_start(self, registry):
        """Start then record — should have 2 entries."""
        registry.create_new("alpha")
        registry.record_session_start("alpha", "sess-1")
        progress = registry.record_session(
            "alpha",
            summary="Implemented feature X",
            feature="feature-x",
        )
        assert len(progress["sessions"]) == 2
        assert progress["current_feature"] == "feature-x"

    def test_record_session_caps_summary(self, registry):
        registry.create_new("alpha")
        long_summary = "x" * 600
        progress = registry.record_session("alpha", summary=long_summary)
        entry = progress["sessions"][-1]
        assert len(entry["summary"]) <= 500  # capped at 500 in record_session

    def test_record_session_with_blockers(self, registry):
        registry.create_new("alpha")
        progress = registry.record_session(
            "alpha",
            summary="hit a wall",
            blockers=["OAuth token expired"],
        )
        assert "OAuth token expired" in progress["blockers"]

    def test_record_session_on_expiry(self, registry):
        registry.create_new("alpha")
        progress = registry.record_session(
            "alpha",
            summary="Session expired after 30 min idle.",
        )
        assert "Session expired" in progress["sessions"][-1]["summary"]

    def test_progress_path_is_per_project(self, registry):
        """Different projects have separate progress files."""
        registry.create_new("project-a")
        registry.create_new("project-b")
        registry.record_session_start("project-a", "sess-a1")
        registry.record_session_start("project-b", "sess-b1")
        pa = registry.get_progress("project-a")
        pb = registry.get_progress("project-b")
        assert len(pa["sessions"]) == 1
        assert len(pb["sessions"]) == 1
        assert pa["sessions"][0]["session_id"] == "sess-a1"
        assert pb["sessions"][0]["session_id"] == "sess-b1"
