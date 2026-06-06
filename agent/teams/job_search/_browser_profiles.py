"""Per-board persistent browser-profile loader for the BrowserUseSpecialist (D5.7).

Profiles are operator-captured Playwright/Chromium ``storage_state.json`` files
that the BrowserUseSpecialist threads into the computer-use session via
``BrowserInput.storage_state_path``. Operator captures with
``agent/scripts/capture_browser_profile.py`` (one evening, 8-13 boards).

Profiles live at ``/opt/bumba-harness/data/browser-profiles/<board>.json``
(runtime tree) and are .gitignored. The 30-day staleness heuristic warns
without blocking the run — operator can re-capture at their convenience.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bridge.browser_trace import BrowserTraceWriter

log = logging.getLogger(__name__)

PROFILES_ROOT = Path("/opt/bumba-harness/data/browser-profiles")
STALE_THRESHOLD_DAYS = 30


@dataclass(frozen=True)
class BrowserProfile:
    """One captured browser profile for a single board."""

    board: str
    path: Path
    captured_at_utc: datetime
    is_stale: bool

    @property
    def age_days(self) -> int:
        return (datetime.now(timezone.utc) - self.captured_at_utc).days


def load_profile_for_board(
    board: str,
    *,
    profiles_root: Optional[Path] = None,
    stale_threshold_days: int = STALE_THRESHOLD_DAYS,
) -> Optional[BrowserProfile]:
    """Return a BrowserProfile for the given board, or None if no profile exists.

    Stale profiles (older than ``stale_threshold_days``) emit a WARNING log but
    are still returned — the specialist tries them and reports
    ``REQUIRES_LOGIN`` if cookies have expired.

    Pure I/O over the runtime profile directory (``Path.exists`` / ``stat``).
    No reads of profile contents — that's the BrowserUseSpecialist's job.
    """
    root = profiles_root if profiles_root is not None else PROFILES_ROOT
    profile_path = root / f"{board}.json"

    if not profile_path.exists():
        log.debug("no browser profile for board %s at %s", board, profile_path)
        return None

    try:
        mtime = profile_path.stat().st_mtime
    except OSError as exc:
        log.warning("failed to stat profile %s: %s", profile_path, exc)
        return None

    captured_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
    age_days = (datetime.now(timezone.utc) - captured_at).days
    is_stale = age_days > stale_threshold_days

    if is_stale:
        log.warning(
            "browser profile for %s is %d days old (>%d) — operator should re-capture; "
            "specialist will try the profile and surface REQUIRES_LOGIN if cookies expired",
            board,
            age_days,
            stale_threshold_days,
        )

    return BrowserProfile(
        board=board,
        path=profile_path,
        captured_at_utc=captured_at,
        is_stale=is_stale,
    )


def profile_path_for_board(
    board: str,
    *,
    profiles_root: Optional[Path] = None,
) -> Optional[str]:
    """Convenience: return the str path if a profile exists, else None.

    Used by the chief to decide whether to thread ``storage_state_path`` into
    ``BrowserInput``. Returns None for missing profiles — caller decides
    whether to run anonymous or skip the listing.
    """
    profile = load_profile_for_board(board, profiles_root=profiles_root)
    return str(profile.path) if profile is not None else None


def browser_trace_writer_from_deps(deps: Any) -> BrowserTraceWriter | None:
    """Return the browser trace writer registered for this run, if available."""
    existing = getattr(deps, "browser_trace", None)
    if existing is not None:
        return existing

    run_artifact_dir = getattr(deps, "run_artifact_dir", None)
    if run_artifact_dir is None:
        return None

    root = Path(run_artifact_dir).expanduser()
    if not (root / "manifest.json").exists():
        return None
    return BrowserTraceWriter(root)
