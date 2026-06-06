"""Project registry — YAML-based multi-project tracking.

Manages project state for Zone 3 engineering capability.
Supports registration, status tracking, context switching,
and context injection for Claude subprocess.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Schema constraints
MAX_DESCRIPTION_LEN = 500
MAX_SUMMARY_LEN = 1000
MAX_LIST_ITEMS = 10
MAX_PROJECTS = 50
VALID_STATUSES = {"active", "suspended", "deprecated"}

# Required fields with defaults
SCHEMA_DEFAULTS: dict[str, Any] = {
    "project": "",
    "status": "active",
    "stack": [],
    "description": "",
    "last_worked": "",
    "where_we_left_off": "",
    "next_steps": [],
    "key_files": [],
    "decisions": [],
    "sdd_stage": "",
    "sdd_spec": "",
    "sdd_plan": "",
}

# Use YAML if available, fall back to JSON
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def _read_project_file(path: Path) -> dict:
    """Read a project file (YAML or JSON)."""
    text = path.read_text()
    if _HAS_YAML and path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text) or {}
    return json.loads(text)


def _write_project_file(path: Path, data: dict) -> None:
    """Write a project file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if _HAS_YAML and path.suffix in (".yaml", ".yml"):
        content = yaml.dump(data, default_flow_style=False, sort_keys=False)
    else:
        content = json.dumps(data, indent=2) + "\n"

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=path.suffix)
    try:
        os.write(fd, content.encode())
        os.close(fd)
        os.replace(tmp, str(path))
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def validate_project(data: dict) -> list[str]:
    """Validate project data against schema. Returns list of errors."""
    errors: list[str] = []

    if not data.get("project"):
        errors.append("'project' name is required")
    elif not isinstance(data["project"], str):
        errors.append("'project' must be a string")

    status = data.get("status", "active")
    if status not in VALID_STATUSES:
        errors.append(f"'status' must be one of {VALID_STATUSES}, got '{status}'")

    desc = data.get("description", "")
    if len(desc) > MAX_DESCRIPTION_LEN:
        errors.append(f"'description' exceeds {MAX_DESCRIPTION_LEN} chars")

    summary = data.get("where_we_left_off", "")
    if len(summary) > MAX_SUMMARY_LEN:
        errors.append(f"'where_we_left_off' exceeds {MAX_SUMMARY_LEN} chars")

    for list_field in ("stack", "next_steps", "key_files", "decisions"):
        val = data.get(list_field, [])
        if not isinstance(val, list):
            errors.append(f"'{list_field}' must be a list")
        elif len(val) > MAX_LIST_ITEMS:
            errors.append(f"'{list_field}' exceeds {MAX_LIST_ITEMS} items")

    return errors


class ProjectRegistry:
    """YAML-based project registry with CRUD operations."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.projects_dir = self.data_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._active_project_file = self.data_dir / "active_project.json"

    def _project_path(self, name: str) -> Path:
        """Get path for a project file."""
        ext = ".yaml" if _HAS_YAML else ".json"
        safe_name = name.lower().replace(" ", "-").replace("/", "-")
        return self.projects_dir / f"{safe_name}{ext}"

    def register(self, name: str, data: dict | None = None) -> dict:
        """Register a new project. Raises ValueError on validation failure."""
        path = self._project_path(name)
        if path.exists():
            raise ValueError(f"Project '{name}' already exists")

        if len(list(self.projects_dir.iterdir())) >= MAX_PROJECTS:
            raise ValueError(f"Maximum {MAX_PROJECTS} projects reached")

        project = dict(SCHEMA_DEFAULTS)
        project["project"] = name
        if data:
            project.update(data)
            project["project"] = name  # Ensure name not overridden

        project["last_worked"] = datetime.now(timezone.utc).isoformat()

        errors = validate_project(project)
        if errors:
            raise ValueError(f"Validation failed: {'; '.join(errors)}")

        _write_project_file(path, project)
        log.info("Registered project: %s", name)
        return project

    def get(self, name: str) -> dict | None:
        """Get a project by name. Returns None if not found."""
        path = self._project_path(name)
        if not path.exists():
            return None
        try:
            return _read_project_file(path)
        except Exception as e:
            log.error("Failed to read project '%s': %s", name, e)
            return None

    def update(self, name: str, fields: dict) -> dict:
        """Update specific fields of a project. Returns updated project."""
        project = self.get(name)
        if project is None:
            raise ValueError(f"Project '{name}' not found")

        # Prevent changing the project name
        fields.pop("project", None)

        project.update(fields)
        project["last_worked"] = datetime.now(timezone.utc).isoformat()

        errors = validate_project(project)
        if errors:
            raise ValueError(f"Validation failed: {'; '.join(errors)}")

        _write_project_file(self._project_path(name), project)
        log.info("Updated project: %s (fields: %s)", name, list(fields.keys()))
        return project

    def list_all(self) -> list[dict]:
        """List all registered projects, sorted by last_worked descending."""
        projects: list[dict] = []
        for path in self.projects_dir.iterdir():
            if path.suffix in (".yaml", ".yml", ".json"):
                try:
                    projects.append(_read_project_file(path))
                except Exception as e:
                    log.warning("Failed to read %s: %s", path, e)

        projects.sort(
            key=lambda p: p.get("last_worked", ""),
            reverse=True,
        )
        return projects

    def set_status(self, name: str, status: str) -> dict:
        """Set project status (active/suspended/deprecated)."""
        if status not in VALID_STATUSES:
            raise ValueError(f"Status must be one of {VALID_STATUSES}")
        return self.update(name, {"status": status})

    def delete(self, name: str) -> bool:
        """Delete a project. Returns True if deleted."""
        path = self._project_path(name)
        if path.exists():
            path.unlink()
            log.info("Deleted project: %s", name)

            # Clear active project if this was it
            active = self.get_active_project_name()
            if active == name:
                self._write_active(None)

            return True
        return False

    # --- Track Switching ---

    def get_active_project_name(self) -> str | None:
        """Get the name of the currently active project (or None for system track)."""
        if not self._active_project_file.exists():
            return None
        try:
            data = json.loads(self._active_project_file.read_text())
            return data.get("active_project")
        except (json.JSONDecodeError, OSError):
            return None

    def _write_active(self, name: str | None) -> None:
        """Write active project tracker."""
        data = {
            "active_project": name,
            "switched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._active_project_file.parent.mkdir(parents=True, exist_ok=True)
        self._active_project_file.write_text(json.dumps(data, indent=2) + "\n")

    def switch_to(self, name: str, save_current: dict | None = None) -> dict:
        """Switch active project. Optionally save outgoing project state.

        Args:
            name: Target project name.
            save_current: Fields to save on the outgoing project (e.g., where_we_left_off).

        Returns:
            The target project data.
        """
        target = self.get(name)
        if target is None:
            raise ValueError(f"Project '{name}' not found")

        if target.get("status") == "deprecated":
            raise ValueError(f"Cannot switch to deprecated project '{name}'")

        # Save outgoing project state
        current_name = self.get_active_project_name()
        if current_name and save_current:
            try:
                self.update(current_name, save_current)
            except Exception as e:
                log.warning("Failed to save outgoing project '%s': %s", current_name, e)

        # Activate target (unsuspend if needed)
        if target.get("status") == "suspended":
            self.set_status(name, "active")
            target["status"] = "active"

        self._write_active(name)
        self.update(name, {"last_worked": datetime.now(timezone.utc).isoformat()})
        log.info("Switched to project: %s", name)
        return target

    def switch_to_system(self, save_current: dict | None = None) -> None:
        """Switch to system track (no active project)."""
        current_name = self.get_active_project_name()
        if current_name and save_current:
            try:
                self.update(current_name, save_current)
            except Exception as e:
                log.warning("Failed to save outgoing project '%s': %s", current_name, e)

        self._write_active(None)
        log.info("Switched to system track")

    def suspend(self, name: str, save_state: dict | None = None) -> dict:
        """Suspend a project, preserving state."""
        if save_state:
            self.update(name, save_state)
        project = self.set_status(name, "suspended")

        # Clear from active if this was active
        if self.get_active_project_name() == name:
            self._write_active(None)

        log.info("Suspended project: %s", name)
        return project

    def create_new(
        self,
        name: str,
        *,
        stack: list[str] | None = None,
        description: str = "",
        set_active: bool = True,
    ) -> dict:
        """Create a new project and optionally set it as active."""
        data: dict[str, Any] = {}
        if stack:
            data["stack"] = stack
        if description:
            data["description"] = description

        project = self.register(name, data)

        if set_active:
            self._write_active(name)

        return project

    # --- Session Progress Tracking ---

    def _progress_path(self, name: str) -> Path:
        """Path to a project's progress.json file."""
        safe_name = name.lower().replace(" ", "-").replace("/", "-")
        return self.data_dir / "project_progress" / f"{safe_name}-progress.json"

    def get_progress(self, name: str) -> dict:
        """Get structured progress for a project."""
        path = self._progress_path(name)
        if not path.exists():
            return {"sessions": [], "current_feature": None, "blockers": [], "recent_changes": []}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"sessions": [], "current_feature": None, "blockers": [], "recent_changes": []}

    def save_progress(self, name: str, progress: dict) -> None:
        """Save structured progress for a project (atomic write)."""
        path = self._progress_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(progress, indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".json")
        try:
            os.write(fd, content.encode())
            os.close(fd)
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def record_session(
        self,
        name: str,
        *,
        summary: str,
        feature: str | None = None,
        changes: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> dict:
        """Record a session's progress. Returns updated progress."""
        progress = self.get_progress(name)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary[:500],
        }
        if feature:
            entry["feature"] = feature
        if changes:
            entry["changes"] = changes[:10]

        progress["sessions"].append(entry)
        # Keep last 20 sessions
        progress["sessions"] = progress["sessions"][-20:]

        if feature is not None:
            progress["current_feature"] = feature
        if blockers is not None:
            progress["blockers"] = blockers[:5]
        if changes:
            progress["recent_changes"] = changes[:10]

        self.save_progress(name, progress)
        return progress


    def record_session_start(
        self,
        name: str,
        session_id: str,
    ) -> dict:
        """Record that a new session has started for a project.

        Adds a lightweight entry to progress.json so the session start
        timestamp is captured even if the session ends without a summary.
        Returns the updated progress dict.
        """
        progress = self.get_progress(name)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": "Session started.",
            "session_id": session_id,
        }
        progress["sessions"].append(entry)
        progress["sessions"] = progress["sessions"][-20:]
        self.save_progress(name, progress)
        return progress

    # --- Context Injection ---

    def get_active_project_context(self) -> str | None:
        """Build context string for the active project (for Claude subprocess).

        Returns None if no project is active (system track).
        """
        name = self.get_active_project_name()
        if name is None:
            return None

        project = self.get(name)
        if project is None:
            return None

        lines = [f"**Active Project: {project['project']}**"]

        if project.get("description"):
            lines.append(f"Description: {project['description']}")

        if project.get("stack"):
            lines.append(f"Stack: {', '.join(project['stack'])}")

        if project.get("where_we_left_off"):
            lines.append(f"Where we left off: {project['where_we_left_off']}")

        if project.get("next_steps"):
            lines.append("Next steps:")
            for step in project["next_steps"]:
                lines.append(f"  - {step}")

        if project.get("key_files"):
            lines.append("Key files:")
            for f in project["key_files"]:
                lines.append(f"  - {f}")

        if project.get("decisions"):
            lines.append("Recent decisions:")
            for d in project["decisions"][-5:]:
                lines.append(f"  - {d}")

        # Include session progress if available
        progress = self.get_progress(name)
        if progress.get("current_feature"):
            lines.append(f"Current feature: {progress['current_feature']}")
        if progress.get("blockers"):
            lines.append("Blockers:")
            for b in progress["blockers"]:
                lines.append(f"  - {b}")
        if progress.get("recent_changes"):
            lines.append("Recent changes:")
            for c in progress["recent_changes"][-5:]:
                lines.append(f"  - {c}")
        if progress.get("sessions"):
            last = progress["sessions"][-1]
            lines.append(f"Last session ({last.get('timestamp', '?')[:10]}): {last.get('summary', '')[:200]}")

        return "\n".join(lines)

    def format_status_table(self) -> str:
        """Format all projects as a display table."""
        projects = self.list_all()
        if not projects:
            return "No projects registered."

        active_name = self.get_active_project_name()
        lines = ["**Projects**\n"]
        lines.append("| Status | Name | Stack | Last Worked | Description |")
        lines.append("|--------|------|-------|-------------|-------------|")

        for p in projects:
            name = p.get("project", "?")
            status = p.get("status", "?")
            marker = " *" if name == active_name else ""

            # Status indicator
            status_icon = {"active": "+", "suspended": "~", "deprecated": "-"}.get(status, "?")

            stack = ", ".join(p.get("stack", [])[:3])
            last = p.get("last_worked", "")[:10]
            desc = p.get("description", "")[:60]

            lines.append(f"| {status_icon} {status}{marker} | {name} | {stack} | {last} | {desc} |")

        return "\n".join(lines)
