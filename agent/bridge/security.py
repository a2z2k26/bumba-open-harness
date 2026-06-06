"""Audit logging, anomaly detection, halt management, kernel integrity."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import aiohttp

from .config import BridgeConfig
from .database import Database

logger = logging.getLogger(__name__)

# Prompt injection detection patterns.
# These flag suspicious inputs for audit logging — messages are NOT blocked.
INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ignore\s+(previous|all\s+prior|above)\s+(instructions|prompts)", re.I), "instruction_override"),
    (re.compile(r"disregard\s+(above|previous|all)", re.I), "instruction_override"),
    (re.compile(r"^system:", re.M), "system_injection"),
    (re.compile(r"you\s+are\s+now|pretend\s+to\s+be", re.I), "role_override"),
    (re.compile(r"[A-Za-z0-9+/]{100,}={0,2}", re.M), "base64_block"),
    (re.compile(r"^(ADMIN|OPERATOR|ROOT|SUDO):", re.M), "authority_spoof"),
]


class SecurityManager:
    """Audit logging, anomaly detection, halt flag, kernel hash verification."""

    def __init__(self, db: Database, config: BridgeConfig) -> None:
        self._db = db
        self._config = config
        self._jsonl_path = Path(config.log_dir) / "audit.jsonl"
        self._halt_path = Path(config.data_dir) / "halt.flag"
        self._counters: dict[str, list[float]] = defaultdict(list)

    # -- S73: Audit logging core --

    async def log_event(
        self,
        event_type: str,
        details: dict[str, Any] | None = None,
        tool_name: str | None = None,
        arguments: str | None = None,
        outcome: str | None = None,
        session_id: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        """Log an audit event to SQLite and JSONL."""
        # Truncate arguments to 500 chars per schema spec
        if arguments and len(arguments) > 500:
            arguments = arguments[:500]

        details_json = json.dumps(details) if details else None

        # SQLite
        try:
            await self._db.execute(
                """INSERT INTO audit_log
                   (event_type, tool_name, arguments, outcome, details, session_id, chat_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (event_type, tool_name, arguments, outcome, details_json, session_id, chat_id),
            )
            await self._db.commit()
        except Exception as e:
            logger.error(
                "Failed to write audit to SQLite: %s. "
                "Check disk space and DB permissions. Audit trail has a gap.", e
            )

        # JSONL (offloaded to thread to avoid blocking the event loop)
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event_type": event_type,
            "tool_name": tool_name,
            "arguments": arguments,
            "outcome": outcome,
            "details": details,
            "session_id": session_id,
            "chat_id": chat_id,
        }
        try:
            await asyncio.to_thread(self._append_jsonl_sync, entry)
        except Exception as e:
            logger.error(
                "Failed to write audit to JSONL (%s): %s. "
                "Check disk space and file permissions.", self._jsonl_path, e
            )

    def _append_jsonl_sync(self, entry: dict[str, Any]) -> None:
        """Synchronous JSONL append — runs in a thread via asyncio.to_thread()."""
        with open(self._jsonl_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    async def get_recent_events(
        self, limit: int = 50, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Query recent audit events."""
        if event_type:
            rows = await self._db.fetchall(
                """SELECT timestamp, event_type, tool_name, outcome, details
                   FROM audit_log
                   WHERE event_type = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (event_type, limit),
            )
        else:
            rows = await self._db.fetchall(
                """SELECT timestamp, event_type, tool_name, outcome, details
                   FROM audit_log
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            )
        return [
            {
                "timestamp": r[0], "event_type": r[1], "tool_name": r[2],
                "outcome": r[3], "details": r[4],
            }
            for r in rows
        ]

    # -- S74: Anomaly detection --

    def _update_counter(self, key: str, window_seconds: int) -> int:
        """Add current timestamp to sliding window counter. Returns count in window."""
        now = time.monotonic()
        cutoff = now - window_seconds
        self._counters[key] = [t for t in self._counters[key] if t > cutoff]
        self._counters[key].append(now)
        return len(self._counters[key])

    async def check_anomalies(
        self, event_type: str, details: dict[str, Any] | None = None
    ) -> list[str]:
        """Check for anomalies and return alert messages."""
        alerts: list[str] = []

        # Tool failure burst
        if event_type == "tool_failure":
            tool = (details or {}).get("tool_name", "unknown")
            count = self._update_counter(
                f"tool_failure:{tool}", self._config.tool_failure_window
            )
            if count >= self._config.tool_failure_threshold:
                alerts.append(
                    f"Tool failure burst: {tool} failed {count} times "
                    f"in {self._config.tool_failure_window}s"
                )

        # Rate limit storm
        if event_type == "rate_limit":
            count = self._update_counter("rate_limit", self._config.crash_loop_window)
            if count >= 3:
                alerts.append(f"Rate limit storm: {count} rate limits in window")

        # Database size check
        if event_type in ("message_processed", "bridge_startup"):
            db_path = Path(self._config.data_dir) / "memory.db"
            if db_path.exists():
                size = db_path.stat().st_size
                if size >= self._config.db_size_alert:
                    alerts.append(
                        f"Database size ALERT: {size / 1024 / 1024:.0f}MB "
                        f"(threshold: {self._config.db_size_alert / 1024 / 1024:.0f}MB)"
                    )
                elif size >= self._config.db_size_warn:
                    alerts.append(
                        f"Database size WARNING: {size / 1024 / 1024:.0f}MB "
                        f"(threshold: {self._config.db_size_warn / 1024 / 1024:.0f}MB)"
                    )

        return alerts

    def check_crash_loop(self) -> bool:
        """Check if crash loop threshold is exceeded. Returns True if in crash loop."""
        crash_log = Path(self._config.data_dir) / "crash.log"
        if not crash_log.exists():
            return False

        now = time.time()
        cutoff = now - self._config.crash_loop_window
        recent = 0

        try:
            for line in crash_log.read_text().strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    ts = float(line)
                    if ts > cutoff:
                        recent += 1
                except ValueError:
                    continue
        except OSError:
            return False

        return recent >= self._config.crash_loop_threshold

    def record_crash_timestamp(self) -> None:
        """Append current timestamp to crash.log for crash loop detection."""
        crash_log = Path(self._config.data_dir) / "crash.log"
        try:
            with open(crash_log, "a") as f:
                f.write(f"{time.time()}\n")
        except OSError as e:
            logger.error(
                "Failed to write crash timestamp to %s: %s. "
                "Crash loop detection may not work correctly.", crash_log, e
            )

    # -- S75: Halt flag and kernel hash verification --

    def set_halt(self, reason: str = "") -> None:
        """Set the halt flag."""
        self._halt_path.write_text(reason or "halted")
        logger.warning("Halt flag set: %s", reason)

    def clear_halt(self) -> None:
        """Clear the halt flag."""
        self._halt_path.unlink(missing_ok=True)
        logger.info("Halt flag cleared")

    def is_halted(self) -> bool:
        """Check if halt flag is set."""
        return self._halt_path.exists()

    def check_halt_flag(self) -> str | None:
        """Read halt flag reason. Returns None if not halted."""
        if self._halt_path.exists():
            return self._halt_path.read_text().strip() or "halted"
        return None

    async def check_remote_halt(self, session: aiohttp.ClientSession) -> bool:
        """Poll remote endpoint for halt signal.

        Returns True if endpoint returns 200 and body contains "halt" (case-insensitive).
        Returns False on any error or timeout (fail-open).
        Logs warnings on errors.
        """
        url = self._config.remote_halt_url
        if not url:
            return False

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    body = await resp.text()
                    return "halt" in body.lower()
                logger.warning("Remote halt check: unexpected status %d", resp.status)
                return False
        except asyncio.TimeoutError:
            logger.warning("Remote halt check timed out after 5s: %s", url)
            return False
        except aiohttp.ClientError as e:
            logger.warning("Remote halt check failed: %s", e)
            return False
        except Exception as e:
            logger.warning("Remote halt check unexpected error: %s", e)
            return False

    def verify_kernel_hashes(
        self, baseline_path: str | Path | None = None,
    ) -> list[str]:
        """Verify kernel file hashes against baseline. Returns mismatched files."""
        if baseline_path is None:
            baseline_path = Path(self._config.data_dir) / "kernel-baseline.json"
        else:
            baseline_path = Path(baseline_path)

        # Auto-correct stale underscore variant if the correct hyphen file is missing
        underscore_path = baseline_path.parent / "kernel_baseline.json"
        if not baseline_path.exists() and underscore_path.exists():
            logger.warning(
                "Found kernel_baseline.json (underscore) but not kernel-baseline.json (hyphen). "
                "Renaming to correct filename. This is a deploy script bug."
            )
            underscore_path.rename(baseline_path)

        if not baseline_path.exists():
            return ["baseline file missing"]

        try:
            baseline = json.loads(baseline_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            return [f"baseline read error: {e}"]

        mismatches: list[str] = []
        for file_path, expected_hash in baseline.get("files", {}).items():
            p = Path(file_path)
            if not p.exists():
                mismatches.append(f"MISSING: {file_path}")
                continue
            actual = hashlib.sha256(p.read_bytes()).hexdigest()
            if actual != expected_hash:
                mismatches.append(f"CHANGED: {file_path}")

        return mismatches

    @staticmethod
    def format_alert(title: str, details: str = "") -> str:
        """Format an alert message for the operator."""
        msg = f"[ALERT] {title}"
        if details:
            msg += f"\n{details}"
        return msg
