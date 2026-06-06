"""Version tracking for bridge deployments.

Tracks the current deployed version via data/version.json. Detects version
changes on startup and provides rollback flag support.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class VersionInfo:
    """Deployed version metadata."""

    version: str = "0.0.0"
    git_commit: str = "unknown"
    deployed_at: str = "unknown"
    deployed_by: str = "unknown"


_RUNNING_VERSION: str = "0.0.0"


def get_current_version(data_dir: str | Path | None = None) -> VersionInfo:
    """Read version from version.json."""
    if data_dir is None:
        version_file = Path("data/version.json")
    else:
        version_file = Path(data_dir) / "version.json"

    if not version_file.exists():
        return VersionInfo()

    try:
        data = json.loads(version_file.read_text())
        return VersionInfo(
            version=data.get("version", "0.0.0"),
            git_commit=data.get("git_commit", "unknown"),
            deployed_at=data.get("deployed_at", "unknown"),
            deployed_by=data.get("deployed_by", "unknown"),
        )
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to read version.json: %s", e)
        return VersionInfo()


def get_running_version() -> str:
    """Return the version that was loaded at bridge startup."""
    return _RUNNING_VERSION


def init_version(
    data_dir: str | Path | None = None,
    default_version: str = "0.0.0",
) -> VersionInfo:
    """Called once at bridge startup. Returns the loaded version info.

    When ``data/version.json`` is absent (fresh install or pre-deploy-script
    runtime), falls back to ``default_version`` rather than the dataclass
    default of ``"0.0.0"``. Callers (notably ``bridge/__main__.py``) pass the
    project version read from ``pyproject.toml`` so ``/healthz`` reports a
    meaningful source-tree version even when no deploy script has yet
    written ``version.json``.
    """
    global _RUNNING_VERSION
    info = get_current_version(data_dir)
    if info.version == "0.0.0" and default_version != "0.0.0":
        # version.json missing or empty — surface the source-tree version so
        # the bridge advertises a real version on first boot.
        info = VersionInfo(
            version=default_version,
            git_commit=info.git_commit,
            deployed_at=info.deployed_at,
            deployed_by=info.deployed_by,
        )
    _RUNNING_VERSION = info.version
    log.info("Bridge version: %s (commit: %s, deployed: %s)",
             info.version, info.git_commit, info.deployed_at)
    return info


def write_version(
    data_dir: str | Path,
    version: str,
    git_commit: str = "unknown",
    deployed_by: str = "manual",
) -> VersionInfo:
    """Write version.json. Called by deploy scripts/helper."""
    info = VersionInfo(
        version=version,
        git_commit=git_commit,
        deployed_at=datetime.now(timezone.utc).isoformat(),
        deployed_by=deployed_by,
    )
    version_file = Path(data_dir) / "version.json"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(json.dumps(asdict(info), indent=2) + "\n")
    return info


# --- Rollback flag ---

def check_rollback_flag(data_dir: str | Path | None = None) -> dict | None:
    """Check if operator has requested a rollback. Returns flag data or None."""
    if data_dir is None:
        flag_file = Path("data/rollback.flag")
    else:
        flag_file = Path(data_dir) / "rollback.flag"

    if not flag_file.exists():
        return None

    try:
        return json.loads(flag_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {"reason": "unknown", "requested_at": "unknown"}


def set_rollback_flag(data_dir: str | Path, reason: str) -> None:
    """Set rollback flag with reason."""
    flag_file = Path(data_dir) / "rollback.flag"
    flag_file.write_text(json.dumps({
        "reason": reason,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }))


def clear_rollback_flag(data_dir: str | Path | None = None) -> None:
    """Clear rollback flag after rollback is complete."""
    if data_dir is None:
        flag_file = Path("data/rollback.flag")
    else:
        flag_file = Path(data_dir) / "rollback.flag"
    flag_file.unlink(missing_ok=True)


def detect_version_change(
    data_dir: str | Path,
    state_file: str = "bridge-state.json",
) -> tuple[str, str] | None:
    """Compare current version.json against last known version from state.

    Returns (old_version, new_version) if changed, None otherwise.
    Also updates state with the new version.
    """
    current = get_current_version(data_dir)
    state_path = Path(data_dir) / "service_state" / state_file

    last_version = "0.0.0"
    state: dict = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            last_version = state.get("last_version", "0.0.0")
        except (json.JSONDecodeError, OSError):
            pass

    if current.version != last_version:
        log.info("Version change detected: %s → %s (commit: %s)",
                 last_version, current.version, current.git_commit)
        state["last_version"] = current.version
        state["last_version_change"] = datetime.now(timezone.utc).isoformat()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        return (last_version, current.version)

    return None
