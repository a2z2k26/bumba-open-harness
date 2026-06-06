"""Daily log wiring for the consolidation pipeline.

Provides three components:
- LogConsolidationSource: reads daily logs, extracts actionable entries,
  marks logs as consolidated.
- DateChangeDetector: detects midnight rollovers (flushOnDateChange pattern).
- SessionTranscriptScanner: lists session IDs by mtime only — never reads
  full transcript content.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bridge.daily_log import DailyLogWriter


class LogConsolidationSource:
    """Reads daily logs as consolidation input."""

    CONSOLIDATED_HEADER_RE = re.compile(
        r'^<!-- consolidated: [\d\-T:Z]+ -->', re.MULTILINE
    )

    def __init__(self, daily_log: "DailyLogWriter") -> None:
        self._daily_log = daily_log

    def get_recent_logs(self, days: int = 7) -> list[tuple[date, str]]:
        """Return (date, content) for the last N days, skipping missing days."""
        results = []
        for path in self._daily_log.list_recent(days=days):
            try:
                content = path.read_text(encoding="utf-8")
                # Parse date from filename YYYY-MM-DD.md
                date_str = path.stem  # e.g. "2026-04-03"
                log_date = date.fromisoformat(date_str)
                results.append((log_date, content))
            except (OSError, ValueError):
                continue
        return results

    def extract_actionable(self, content: str) -> list[str]:
        """Filter log content to meaningful entries.

        Removes:
        - Blank / whitespace-only lines
        - HTML comment lines (consolidated headers, etc.)
        - Bare markdown heading lines with no real text (# or ## etc. alone)
        """
        lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("<!--"):
                continue
            # Strip bare heading markers with nothing meaningful after them
            heading_match = re.match(r'^(#{1,6})\s*$', stripped)
            if heading_match:
                continue
            lines.append(stripped)
        return lines

    def mark_consolidated(
        self,
        log_path: Path,
        timestamp: datetime | None = None,
    ) -> None:
        """Prepend consolidated header to log file.

        Creates the file if it does not exist.
        """
        ts = (timestamp or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        header = f"<!-- consolidated: {ts} -->\n"
        existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        log_path.write_text(header + existing, encoding="utf-8")

    def is_already_consolidated(self, content: str) -> bool:
        """Return True if this log has already been processed.

        Checks for the <!-- consolidated: ... --> header at the start
        of the content (allowing leading whitespace).
        """
        return bool(self.CONSOLIDATED_HEADER_RE.match(content.lstrip()))


class DateChangeDetector:
    """Detects midnight rollovers to flush buffered state.

    Pattern: call check_and_flush() periodically. Returns True only
    on the first call after the calendar date has changed.
    """

    def __init__(self) -> None:
        self._last_date: date | None = None

    def check_and_flush(self, now: datetime | None = None) -> bool:
        """Return True (and update internal state) if the date has changed.

        On the very first call, initialises the last-seen date and returns False.
        """
        today = (now or datetime.now()).date()
        if self._last_date is None:
            self._last_date = today
            return False
        if today != self._last_date:
            self._last_date = today
            return True
        return False


class SessionTranscriptScanner:
    """Scans session directory for sessions modified since last consolidation.

    IMPORTANT: Only checks file mtime via os.scandir(). Never opens or reads
    transcript content — keeps memory usage flat regardless of session size.
    """

    def __init__(self, sessions_dir: Path) -> None:
        self._sessions_dir = sessions_dir

    def get_sessions_since(self, since_timestamp: float) -> list[str]:
        """Return session filenames (IDs) modified after since_timestamp.

        Args:
            since_timestamp: Unix timestamp (float, from time.time()).

        Returns:
            List of filenames (not full paths) modified after the threshold.
        """
        if not self._sessions_dir.exists():
            return []
        session_ids: list[str] = []
        try:
            for entry in os.scandir(self._sessions_dir):
                if entry.is_file() and entry.stat().st_mtime > since_timestamp:
                    session_ids.append(entry.name)
        except OSError:
            pass
        return session_ids
