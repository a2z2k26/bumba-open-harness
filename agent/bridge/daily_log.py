"""Append-only daily log writer.

Writes timestamped markdown bullets to data/logs/YYYY/MM/YYYY-MM-DD.md.
Files are strictly append-only — no rewrites, no reorganization.
The consolidation pipeline reads these as source input.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# E3.3 — module-level hook list for daily-log entry events.
# Callbacks receive (entry: str, category: str). Wrapped in try/except at callsite.
_entry_hooks: list[Callable[[str, str], None]] = []


def register_entry_hook(callback: Callable[[str, str], None]) -> None:
    """Register a callback to fire when an entry is appended to the daily log."""
    _entry_hooks.append(callback)


class DailyLogWriter:
    """Thread-safe, append-only daily log writer."""

    def __init__(self, config: object) -> None:
        """Initialize with a config object that has a data_dir attribute."""
        self._base_dir = Path(config.data_dir) / "logs"
        self._lock = threading.Lock()

    def _log_path(self, now: datetime | None = None) -> Path:
        """Return path for today's log: data/logs/YYYY/MM/YYYY-MM-DD.md."""
        now = now or datetime.now(timezone.utc).astimezone()
        return self._base_dir / f"{now:%Y}" / f"{now:%m}" / f"{now:%Y-%m-%d}.md"

    def append(
        self,
        entry: str,
        *,
        category: str = "general",
        correlation_id: str | None = None,
    ) -> None:
        """Append a timestamped bullet to today's log.

        Args:
            entry: The log entry text (one line, no leading bullet).
            category: Optional category tag (memory, event, error, decision,
                      message, response, session, service, dream, alert, search,
                      proactive). Use 'general' for untagged entries.
            correlation_id: Optional correlation ID for cross-file tracing.
                Truncated to 8 chars in the log for readability.
        """
        now = datetime.now(timezone.utc).astimezone()
        path = self._log_path(now)

        tag = f"[{category}] " if category != "general" else ""
        corr = f"[corr:{correlation_id[:8]}] " if correlation_id else ""
        timestamp = now.strftime("%H:%M")
        line = f"- {timestamp} {corr}{tag}{entry}\n"

        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)

        # E3.3 — fire entry hooks outside the lock to avoid re-entrancy issues.
        for hook in _entry_hooks:
            try:
                hook(entry, category)
            except Exception as exc:
                logger.warning("daily_log: entry hook %r failed: %s", hook, exc)

    def read_today(self) -> str:
        """Read today's log contents. Returns empty string if no log yet."""
        path = self._log_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def read_date(self, date: datetime) -> str:
        """Read a specific date's log. Returns empty string if no log exists."""
        path = self._log_path(date)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def list_recent(self, days: int = 7) -> list[Path]:
        """List log files from the last N days, newest first."""
        now = datetime.now(timezone.utc).astimezone()
        paths = []
        for i in range(days):
            d = now - timedelta(days=i)
            p = self._log_path(d)
            if p.exists():
                paths.append(p)
        return paths

    def log_service_completion(
        self,
        service_name: str,
        status: str,
        reason: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Append a structured service completion line to today's log.

        Format:
            [SERVICE][OK] <service> (<duration_ms>ms)
            [SERVICE][FAIL: <reason>] <service>
            [SERVICE][SKIP: <reason>] <service>

        Args:
            service_name: The name of the service (e.g. "briefing", "email").
            status: "OK", "FAIL", or "SKIP".
            reason: Optional detail for FAIL and SKIP statuses.
            duration_ms: Wall-clock duration for OK status.
        """
        status = status.upper()
        if status == "OK":
            tag = f"[SERVICE][OK] {service_name} ({duration_ms}ms)"
        elif status == "FAIL":
            detail = f": {reason[:120]}" if reason else ""
            tag = f"[SERVICE][FAIL{detail}] {service_name}"
        elif status == "SKIP":
            detail = f": {reason[:80]}" if reason else ""
            tag = f"[SERVICE][SKIP{detail}] {service_name}"
        else:
            tag = f"[SERVICE][{status}] {service_name}"

        self.append(tag, category="service")
