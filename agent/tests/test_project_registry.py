"""Tests for bridge.project_registry — project CRUD, track switching, context injection."""

from __future__ import annotations


import pytest

from bridge.project_registry import (
    MAX_DESCRIPTION_LEN,
    MAX_LIST_ITEMS,
    MAX_PROJECTS,
    MAX_SUMMARY_LEN,
    VALID_STATUSES,
    ProjectRegistry,
    validate_project,
)


@pytest.fixture
def registry(tmp_path):
    """Create a ProjectRegistry with temp data directory."""
    return ProjectRegistry(data_dir=tmp_path)


# ── Schema Validation ──

class TestValidation:
    def test_valid_project(self):
        assert validate_project({"project": "test", "status": "active"}) == []

    def test_missing_name(self):
        errors = validate_project({"status": "active"})
        assert any("project" in e for e in errors)

    def test_invalid_status(self):
        errors = validate_project({"project": "test", "status": "invalid"})
        assert any("status" in e for e in errors)

    def test_description_too_long(self):
        errors = validate_project({
            "project": "test",
            "description": "x" * (MAX_DESCRIPTION_LEN + 1),
        })
        assert any("description" in e for e in errors)

    def test_summary_too_long(self):
        errors = validate_project({
            "project": "test",
            "where_we_left_off": "x" * (MAX_SUMMARY_LEN + 1),
        })
        assert any("where_we_left_off" in e for e in errors)

    def test_list_too_many_items(self):
        errors = validate_project({
            "project": "test",
            "next_steps": ["step"] * (MAX_LIST_ITEMS + 1),
        })
        assert any("next_steps" in e for e in errors)

    def test_list_field_not_list(self):
        errors = validate_project({"project": "test", "stack": "not-a-list"})
        assert any("stack" in e for e in errors)

    def test_all_valid_statuses(self):
        for status in VALID_STATUSES:
            assert validate_project({"project": "t", "status": status}) == []


# ── CRUD Operations ──

class TestCRUD:
    def test_register(self, registry):
        p = registry.register("my-project", {"description": "A test project"})
        assert p["project"] == "my-project"
        assert p["description"] == "A test project"
        assert p["status"] == "active"
        assert p["last_worked"] != ""

    def test_register_duplicate(self, registry):
        registry.register("dup")
        with pytest.raises(ValueError, match="already exists"):
            registry.register("dup")

    def test_register_validation_fails(self, registry):
        with pytest.raises(ValueError, match="Validation failed"):
            registry.register("bad", {"status": "invalid"})

    def test_get_existing(self, registry):
        registry.register("test")
        p = registry.get("test")
        assert p is not None
        assert p["project"] == "test"

    def test_get_nonexistent(self, registry):
        assert registry.get("nope") is None

    def test_update(self, registry):
        registry.register("upd")
        updated = registry.update("upd", {"description": "Updated!"})
        assert updated["description"] == "Updated!"

    def test_update_nonexistent(self, registry):
        with pytest.raises(ValueError, match="not found"):
            registry.update("nope", {"description": "x"})

    def test_update_validation(self, registry):
        registry.register("val")
        with pytest.raises(ValueError, match="Validation failed"):
            registry.update("val", {"status": "bad"})

    def test_update_cannot_change_name(self, registry):
        registry.register("original")
        updated = registry.update("original", {"project": "renamed"})
        assert updated["project"] == "original"

    def test_list_all_empty(self, registry):
        assert registry.list_all() == []

    def test_list_all_sorted(self, registry):
        registry.register("first", {"description": "a"})
        registry.register("second", {"description": "b"})
        projects = registry.list_all()
        assert len(projects) == 2
        # Most recently registered (second) should be first
        assert projects[0]["project"] == "second"

    def test_set_status(self, registry):
        registry.register("s")
        registry.set_status("s", "suspended")
        p = registry.get("s")
        assert p["status"] == "suspended"

    def test_set_invalid_status(self, registry):
        registry.register("s")
        with pytest.raises(ValueError, match="Status must be"):
            registry.set_status("s", "nope")

    def test_delete(self, registry):
        registry.register("del")
        assert registry.delete("del") is True
        assert registry.get("del") is None

    def test_delete_nonexistent(self, registry):
        assert registry.delete("nope") is False

    def test_max_projects(self, registry):
        for i in range(MAX_PROJECTS):
            registry.register(f"p-{i}")
        with pytest.raises(ValueError, match="Maximum"):
            registry.register("one-too-many")


# ── Track Switching ──

class TestTrackSwitching:
    def test_no_active_project(self, registry):
        assert registry.get_active_project_name() is None

    def test_switch_to(self, registry):
        registry.register("target")
        registry.switch_to("target")
        assert registry.get_active_project_name() == "target"

    def test_switch_to_nonexistent(self, registry):
        with pytest.raises(ValueError, match="not found"):
            registry.switch_to("nope")

    def test_switch_to_deprecated(self, registry):
        registry.register("dep")
        registry.set_status("dep", "deprecated")
        with pytest.raises(ValueError, match="deprecated"):
            registry.switch_to("dep")

    def test_switch_saves_outgoing(self, registry):
        registry.register("A")
        registry.register("B")
        registry.switch_to("A")
        registry.switch_to("B", save_current={"where_we_left_off": "doing stuff"})
        p = registry.get("A")
        assert p["where_we_left_off"] == "doing stuff"

    def test_switch_unsuspends(self, registry):
        registry.register("susp")
        registry.set_status("susp", "suspended")
        registry.switch_to("susp")
        p = registry.get("susp")
        assert p["status"] == "active"

    def test_switch_to_system(self, registry):
        registry.register("proj")
        registry.switch_to("proj")
        assert registry.get_active_project_name() == "proj"
        registry.switch_to_system()
        assert registry.get_active_project_name() is None

    def test_switch_to_system_saves(self, registry):
        registry.register("proj")
        registry.switch_to("proj")
        registry.switch_to_system(save_current={"where_we_left_off": "paused"})
        p = registry.get("proj")
        assert p["where_we_left_off"] == "paused"

    def test_suspend(self, registry):
        registry.register("s")
        registry.switch_to("s")
        registry.suspend("s", save_state={"where_we_left_off": "saving"})
        p = registry.get("s")
        assert p["status"] == "suspended"
        assert p["where_we_left_off"] == "saving"
        assert registry.get_active_project_name() is None

    def test_create_new_sets_active(self, registry):
        registry.create_new("fresh", stack=["Python"], description="New project")
        assert registry.get_active_project_name() == "fresh"
        p = registry.get("fresh")
        assert p["stack"] == ["Python"]

    def test_create_new_no_active(self, registry):
        registry.create_new("no-active", set_active=False)
        assert registry.get_active_project_name() is None

    def test_delete_clears_active(self, registry):
        registry.register("del")
        registry.switch_to("del")
        registry.delete("del")
        assert registry.get_active_project_name() is None


# ── Context Injection ──

class TestContextInjection:
    def test_no_context_system_track(self, registry):
        assert registry.get_active_project_context() is None

    def test_context_includes_name(self, registry):
        registry.create_new("ctx-test", description="Testing context")
        ctx = registry.get_active_project_context()
        assert ctx is not None
        assert "ctx-test" in ctx
        assert "Testing context" in ctx

    def test_context_includes_stack(self, registry):
        registry.create_new("stack-test", stack=["Python", "SQLite"])
        ctx = registry.get_active_project_context()
        assert "Python" in ctx
        assert "SQLite" in ctx

    def test_context_includes_where_we_left_off(self, registry):
        registry.create_new("wlo-test")
        registry.update("wlo-test", {"where_we_left_off": "Fixing the bug"})
        ctx = registry.get_active_project_context()
        assert "Fixing the bug" in ctx

    def test_context_includes_next_steps(self, registry):
        registry.create_new("ns-test")
        registry.update("ns-test", {"next_steps": ["Step 1", "Step 2"]})
        ctx = registry.get_active_project_context()
        assert "Step 1" in ctx

    def test_context_includes_key_files(self, registry):
        registry.create_new("kf-test")
        registry.update("kf-test", {"key_files": ["bridge/app.py"]})
        ctx = registry.get_active_project_context()
        assert "bridge/app.py" in ctx

    def test_context_limits_decisions(self, registry):
        registry.create_new("dec-test")
        decisions = [f"Decision {i}" for i in range(8)]
        registry.update("dec-test", {"decisions": decisions})
        ctx = registry.get_active_project_context()
        # Only last 5 decisions shown
        assert "Decision 7" in ctx
        assert "Decision 3" in ctx
        assert "Decision 0" not in ctx


# ── Status Table ──

class TestStatusTable:
    def test_empty_table(self, registry):
        table = registry.format_status_table()
        assert "No projects" in table

    def test_table_with_projects(self, registry):
        registry.create_new("alpha", description="Alpha project")
        registry.create_new("beta", description="Beta project")
        table = registry.format_status_table()
        assert "alpha" in table
        assert "beta" in table
        assert "active" in table

    def test_active_marker(self, registry):
        registry.create_new("marked")
        table = registry.format_status_table()
        assert "*" in table  # Active project marker
