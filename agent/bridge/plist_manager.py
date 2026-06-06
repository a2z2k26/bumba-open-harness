"""Safe, whitelisted LaunchDaemon plist management.

Provides controlled operations on Bumba agent LaunchDaemons with safety
constraints: protected services, cooldown enforcement, max disabled limit,
dependency awareness, and full operation logging.
"""

from __future__ import annotations

import json
import logging
import plistlib
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLIST_DIR = Path("/Library/LaunchDaemons")

# Map short names to launchd service labels
SERVICE_LABELS: dict[str, str] = {
    "briefing": "com.bumba.agent-briefing",
    "checkin": "com.bumba.agent-checkin",
    "email": "com.bumba.agent-email",
    "calendar": "com.bumba.agent-calendar",
    "knowledge-review": "com.bumba.agent-knowledge-review",
    "job-search": "com.bumba.agent-job-search",
    "job-execute": "com.bumba.agent-job-execute",
    "monitor": "com.bumba.agent-monitor",
    "bridge": "com.bumba.agent-bridge",
}

KNOWN_SERVICES: set[str] = set(SERVICE_LABELS.keys())
PROTECTED_SERVICES: frozenset[str] = frozenset({"bridge", "monitor"})

MAX_DISABLED = 2
COOLDOWN_SECONDS = 300  # 5 minutes

DEPENDENCIES: dict[str, list[str]] = {
    "email": [],
    "calendar": [],
    "briefing": ["email", "calendar"],
    "checkin": [],
    "knowledge-review": [],
    "job-search": [],
    "job-execute": ["job-search"],
}


class PlistManager:
    """Manages LaunchDaemon plist operations with safety constraints."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self._state_path = self.data_dir / "plist-management-state.json"
        self._log_path = self.data_dir / "plist_operations.jsonl"
        self._state: dict[str, Any] = self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        """Load persisted state from disk."""
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load plist state: %s", exc)
        return {"disabled_services": [], "last_operation": {}}

    def _save_state(self) -> None:
        """Persist state to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self._state, indent=2))

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_service_name(self, name: str) -> str | None:
        """Return an error message if *name* is not a known service."""
        if name not in KNOWN_SERVICES:
            return f"Unknown service: {name!r}. Valid services: {sorted(KNOWN_SERVICES)}"
        return None

    def is_protected(self, name: str) -> bool:
        """Return True if the service cannot be modified."""
        return name in PROTECTED_SERVICES

    def _check_cooldown(self, name: str) -> str | None:
        """Return an error message if the service is still in cooldown."""
        last_ops: dict[str, float] = self._state.get("last_operation", {})
        last_time = last_ops.get(name, 0.0)
        elapsed = time.time() - last_time
        if elapsed < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - elapsed)
            return (
                f"Service {name!r} is in cooldown. "
                f"{remaining}s remaining (min {COOLDOWN_SECONDS}s between operations)."
            )
        return None

    def _check_max_disabled(self) -> str | None:
        """Return an error message if max disabled limit is reached."""
        disabled: list[str] = self._state.get("disabled_services", [])
        if len(disabled) >= MAX_DISABLED:
            return (
                f"Cannot disable: already {len(disabled)} services disabled "
                f"(max {MAX_DISABLED}). Currently disabled: {disabled}"
            )
        return None

    def _record_operation(self, name: str, operation: str, result: dict) -> None:
        """Update cooldown timestamp and append to operation log."""
        # Update last-operation timestamp
        if "last_operation" not in self._state:
            self._state["last_operation"] = {}
        self._state["last_operation"][name] = time.time()
        self._save_state()

        # Append to JSONL log
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "service": name,
            "operation": operation,
            "success": result.get("success", False),
            "message": result.get("message", ""),
        }
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            logger.error("Failed to write operation log: %s", exc)

    # ------------------------------------------------------------------
    # Dependency helpers
    # ------------------------------------------------------------------

    def get_dependents(self, name: str) -> list[str]:
        """Return services that depend on *name*."""
        dependents: list[str] = []
        for svc, deps in DEPENDENCIES.items():
            if name in deps:
                dependents.append(svc)
        return sorted(dependents)

    # ------------------------------------------------------------------
    # Command execution (mockable)
    # ------------------------------------------------------------------

    def _execute_command(self, cmd: list[str]) -> tuple[int, str, str]:
        """Run a subprocess command. Returns (returncode, stdout, stderr).

        This method exists so tests can mock it without running real
        launchctl commands.
        """
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return 1, "", "Command timed out"
        except Exception as exc:
            return 1, "", str(exc)

    # ------------------------------------------------------------------
    # Service label / plist path helpers
    # ------------------------------------------------------------------

    def _label(self, name: str) -> str:
        return SERVICE_LABELS[name]

    def _plist_path(self, name: str) -> Path:
        return PLIST_DIR / f"{self._label(name)}.plist"

    # ------------------------------------------------------------------
    # Whitelisted operations
    # ------------------------------------------------------------------

    def restart_service(self, name: str) -> dict:
        """Bootout then bootstrap a service (restart)."""
        err = self._validate_service_name(name)
        if err:
            return {"success": False, "message": err}
        if self.is_protected(name):
            return {"success": False, "message": f"Service {name!r} is protected and cannot be modified."}
        err = self._check_cooldown(name)
        if err:
            return {"success": False, "message": err}

        label = self._label(name)
        plist = str(self._plist_path(name))

        # Bootout (stop)
        rc, _, stderr = self._execute_command(
            ["sudo", "launchctl", "bootout", f"system/{label}"]
        )
        # Bootout failure is acceptable if the service wasn't loaded
        if rc != 0 and "Could not find specified service" not in stderr:
            result = {"success": False, "message": f"Bootout failed: {stderr.strip()}"}
            self._record_operation(name, "restart", result)
            return result

        # Bootstrap (start)
        rc, _, stderr = self._execute_command(
            ["sudo", "launchctl", "bootstrap", "system", plist]
        )
        if rc != 0:
            result = {"success": False, "message": f"Bootstrap failed: {stderr.strip()}"}
            self._record_operation(name, "restart", result)
            return result

        result = {"success": True, "message": f"Service {name!r} restarted."}
        self._record_operation(name, "restart", result)
        return result

    def enable_service(self, name: str) -> dict:
        """Bootstrap a previously disabled service."""
        err = self._validate_service_name(name)
        if err:
            return {"success": False, "message": err}
        if self.is_protected(name):
            return {"success": False, "message": f"Service {name!r} is protected and cannot be modified."}
        err = self._check_cooldown(name)
        if err:
            return {"success": False, "message": err}

        plist = str(self._plist_path(name))

        rc, _, stderr = self._execute_command(
            ["sudo", "launchctl", "bootstrap", "system", plist]
        )
        if rc != 0:
            result = {"success": False, "message": f"Bootstrap failed: {stderr.strip()}"}
            self._record_operation(name, "enable", result)
            return result

        # Remove from disabled list
        disabled: list[str] = self._state.get("disabled_services", [])
        if name in disabled:
            disabled.remove(name)
            self._state["disabled_services"] = disabled

        result = {"success": True, "message": f"Service {name!r} enabled."}
        self._record_operation(name, "enable", result)
        return result

    def disable_service(self, name: str) -> dict:
        """Bootout a running service."""
        err = self._validate_service_name(name)
        if err:
            return {"success": False, "message": err}
        if self.is_protected(name):
            return {"success": False, "message": f"Service {name!r} is protected and cannot be modified."}
        err = self._check_cooldown(name)
        if err:
            return {"success": False, "message": err}

        # Check max disabled (only if not already in the disabled list)
        disabled: list[str] = self._state.get("disabled_services", [])
        if name not in disabled:
            err = self._check_max_disabled()
            if err:
                return {"success": False, "message": err}

        # Warn about dependents
        warnings: list[str] = []
        dependents = self.get_dependents(name)
        if dependents:
            warnings.append(
                f"Warning: disabling {name!r} may affect dependent services: {dependents}"
            )
            logger.warning("Disabling %r which has dependents: %s", name, dependents)

        label = self._label(name)

        rc, _, stderr = self._execute_command(
            ["sudo", "launchctl", "bootout", f"system/{label}"]
        )
        if rc != 0 and "Could not find specified service" not in stderr:
            result = {"success": False, "message": f"Bootout failed: {stderr.strip()}"}
            self._record_operation(name, "disable", result)
            return result

        # Track in disabled list
        if name not in disabled:
            disabled.append(name)
            self._state["disabled_services"] = disabled

        msg = f"Service {name!r} disabled."
        if warnings:
            msg = f"{msg} {' '.join(warnings)}"

        result = {"success": True, "message": msg}
        if warnings:
            result["warnings"] = warnings
        self._record_operation(name, "disable", result)
        return result

    def update_interval(self, name: str, seconds: int) -> dict:
        """Update the StartInterval value in a service's plist file."""
        err = self._validate_service_name(name)
        if err:
            return {"success": False, "message": err}
        if self.is_protected(name):
            return {"success": False, "message": f"Service {name!r} is protected and cannot be modified."}
        err = self._check_cooldown(name)
        if err:
            return {"success": False, "message": err}

        if seconds < 60:
            result = {"success": False, "message": f"Interval too small: {seconds}s (min 60s)."}
            return result
        if seconds > 86400:
            result = {"success": False, "message": f"Interval too large: {seconds}s (max 86400s)."}
            return result

        plist_path = self._plist_path(name)

        try:
            with plist_path.open("rb") as f:
                plist_data = plistlib.load(f)
        except FileNotFoundError:
            result = {"success": False, "message": f"Plist file not found: {plist_path}"}
            self._record_operation(name, "update_interval", result)
            return result
        except Exception as exc:
            result = {"success": False, "message": f"Failed to read plist: {exc}"}
            self._record_operation(name, "update_interval", result)
            return result

        if "StartInterval" not in plist_data:
            result = {
                "success": False,
                "message": f"Service {name!r} does not use StartInterval (may use StartCalendarInterval).",
            }
            self._record_operation(name, "update_interval", result)
            return result

        old_interval = plist_data["StartInterval"]
        plist_data["StartInterval"] = seconds

        try:
            with plist_path.open("wb") as f:
                plistlib.dump(plist_data, f)
        except Exception as exc:
            result = {"success": False, "message": f"Failed to write plist: {exc}"}
            self._record_operation(name, "update_interval", result)
            return result

        result = {
            "success": True,
            "message": (
                f"Service {name!r} interval updated: {old_interval}s -> {seconds}s. "
                f"Restart the service for changes to take effect."
            ),
        }
        self._record_operation(name, "update_interval", result)
        return result

    def get_service_status(self, name: str) -> dict:
        """Check if a service is currently loaded/running via launchctl."""
        err = self._validate_service_name(name)
        if err:
            return {"success": False, "message": err}

        label = self._label(name)

        rc, stdout, stderr = self._execute_command(
            ["sudo", "launchctl", "print", f"system/{label}"]
        )

        disabled: list[str] = self._state.get("disabled_services", [])

        if rc != 0:
            return {
                "success": True,
                "service": name,
                "label": label,
                "loaded": False,
                "disabled_by_manager": name in disabled,
                "message": f"Service {name!r} is not loaded.",
            }

        return {
            "success": True,
            "service": name,
            "label": label,
            "loaded": True,
            "disabled_by_manager": name in disabled,
            "message": f"Service {name!r} is loaded.",
        }
