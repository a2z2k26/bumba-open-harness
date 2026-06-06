"""Context object builder — assembles ambient awareness from all data sources.

Full build by BriefingService at 7:30am. Partial updates by other services.
Read by CheckinService for escalation decisions and voice fast-path for context injection.

All queries are local (SQLite + file reads). No API calls during build.
Calendar/email sections are updated by their respective services, not queried here.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

def _resolve_data_root() -> Path:
    """Resolve data dir via the canonical helper (#1501 F4)."""
    from bridge.paths import data_root
    return data_root()


DATA_DIR = _resolve_data_root()
CONTEXT_PATH = DATA_DIR / "service_state" / "context.json"
DB_PATH = DATA_DIR / "memory.db"


def _query_operator_contact(conn: sqlite3.Connection) -> dict:
    """Get last operator contact info."""
    row = conn.execute(
        "SELECT MAX(created_at) as last_msg FROM conversations WHERE role = 'user'"
    ).fetchone()
    last_contact = row[0] if row else None
    hours_ago = 999.0
    if last_contact:
        try:
            dt = datetime.fromisoformat(last_contact)
            hours_ago = (datetime.now() - dt).total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    # Active project from track state
    active_project = None
    track_path = DATA_DIR / "service_state" / "track.json"
    if track_path.exists():
        try:
            track = json.loads(track_path.read_text())
            active_project = track.get("active_project")
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "last_contact": last_contact,
        "last_contact_hours_ago": round(hours_ago, 1),
        "active_project": active_project,
    }


def _query_goals(conn: sqlite3.Connection) -> dict:
    """Get active and overdue goals."""
    rows = conn.execute(
        """SELECT key, value FROM knowledge
           WHERE key LIKE 'goal:%'
           AND (archived IS NULL OR archived = 0)"""
    ).fetchall()

    active = []
    overdue = []
    now = datetime.now()

    for row in rows:
        try:
            data = json.loads(row[1])
            entry = {
                "key": row[0],
                "deadline": data.get("deadline"),
                "status": "active",
            }
            deadline_str = data.get("deadline")
            if deadline_str:
                deadline = datetime.fromisoformat(deadline_str)
                if deadline < now:
                    entry["status"] = "overdue"
                    overdue.append(entry)
                else:
                    active.append(entry)
            else:
                active.append(entry)
        except (json.JSONDecodeError, ValueError, TypeError):
            active.append({"key": row[0], "deadline": None, "status": "active"})

    return {"active": active, "overdue": overdue}


def _query_system(conn: sqlite3.Connection) -> dict:
    """Get system health indicators."""
    # Error count in last hour
    row = conn.execute(
        """SELECT COUNT(*) FROM audit_log
           WHERE event_type LIKE '%error%'
           AND timestamp > datetime('now', '-1 hour')"""
    ).fetchone()
    error_count = row[0] if row else 0

    # Uptime from PID file
    uptime_hours = 0.0
    pid_path = DATA_DIR / "bridge.pid"
    if pid_path.exists():
        try:
            mtime = pid_path.stat().st_mtime
            uptime_hours = (datetime.now().timestamp() - mtime) / 3600
        except OSError:
            pass

    # Halt flag
    halt_flag = (DATA_DIR / "halt.flag").exists()

    # Disk space
    try:
        usage = shutil.disk_usage("/")
        disk_free_gb = round(usage.free / 1e9, 1)
    except OSError:
        disk_free_gb = 0.0

    return {
        "uptime_hours": round(uptime_hours, 1),
        "error_count_1h": error_count,
        "halt_flag": halt_flag,
        "disk_free_gb": disk_free_gb,
    }


def _query_knowledge(conn: sqlite3.Connection) -> dict:
    """Get knowledge base stats."""
    stats = {}
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE archived IS NULL OR archived = 0"
        ).fetchone()
        stats["entries_active"] = row[0] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE updated_at > datetime('now', '-24 hours')"
        ).fetchone()
        stats["entries_updated_24h"] = row[0] if row else 0

        row = conn.execute(
            """SELECT COUNT(*) FROM knowledge
               WHERE salience IS NOT NULL AND salience <= 0.3
               AND salience > 0.1
               AND (archived IS NULL OR archived = 0)"""
        ).fetchone()
        stats["entries_low_salience"] = row[0] if row else 0
    except sqlite3.OperationalError:
        stats.setdefault("entries_active", 0)
        stats.setdefault("entries_updated_24h", 0)
        stats.setdefault("entries_low_salience", 0)

    return stats


def _query_escalation() -> dict:
    """Get escalation state from check-in service."""
    state_path = DATA_DIR / "service_state" / "checkin-state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            return {
                "current_level": 0,  # Computed from triggers, not stored
                "unanswered_checkins": state.get("unanswered_checkins", 0),
                "last_escalation": state.get("last_checkin_time"),
            }
        except (json.JSONDecodeError, OSError):
            pass
    return {"current_level": 0, "unanswered_checkins": 0, "last_escalation": None}


def build_context(db_path: Path | None = None) -> dict:
    """Build the full context object from all local data sources.

    Returns the context dict. Also writes to CONTEXT_PATH.
    """
    db = db_path or DB_PATH

    context = {
        "built_at": datetime.now().isoformat(),
        "operator": {},
        "schedule": {"next_event": None, "today_count": 0, "conflicts": []},
        "inbox": {"unread_total": 0, "unread_urgent": 0, "last_check": None},
        "goals": {"active": [], "overdue": []},
        "system": {},
        "knowledge": {},
        "escalation": {},
    }

    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        context["operator"] = _query_operator_contact(conn)
        context["goals"] = _query_goals(conn)
        context["system"] = _query_system(conn)
        context["knowledge"] = _query_knowledge(conn)
        conn.close()
    except Exception as e:
        log.error("Context build DB error: %s", e)

    context["escalation"] = _query_escalation()

    # Merge in existing schedule/inbox from previous service updates
    existing = load_context()
    if existing:
        if existing.get("schedule", {}).get("next_event"):
            context["schedule"] = existing["schedule"]
        if existing.get("inbox", {}).get("last_check"):
            context["inbox"] = existing["inbox"]

    # Write
    try:
        CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONTEXT_PATH.write_text(json.dumps(context, indent=2, default=str))
    except OSError as e:
        log.error("Failed to write context: %s", e)

    return context


def load_context() -> dict | None:
    """Load the current context object from disk."""
    if not CONTEXT_PATH.exists():
        return None
    try:
        return json.loads(CONTEXT_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def update_section(section: str, data: dict) -> None:
    """Update a single section of the context object."""
    context = load_context() or {}
    context[section] = data
    context["built_at"] = datetime.now().isoformat()
    try:
        CONTEXT_PATH.write_text(json.dumps(context, indent=2, default=str))
    except OSError as e:
        log.error("Failed to update context section '%s': %s", section, e)


def summarize_for_voice(max_tokens: int = 200) -> str:
    """Generate a brief context summary for voice session injection.

    Returns a ~200 token summary string.
    """
    ctx = load_context()
    if not ctx:
        return ""

    parts = []

    # Schedule
    sched = ctx.get("schedule", {})
    today_count = sched.get("today_count", 0)
    if today_count:
        next_ev = sched.get("next_event")
        if next_ev and next_ev.get("minutes_until"):
            parts.append(
                f"{today_count} meetings today (next: {next_ev['title']} in {next_ev['minutes_until']} min)"
            )
        else:
            parts.append(f"{today_count} meetings today")

    # Inbox
    inbox = ctx.get("inbox", {})
    unread = inbox.get("unread_total", 0)
    urgent = inbox.get("unread_urgent", 0)
    if unread:
        msg = f"{unread} unread emails"
        if urgent:
            msg += f" ({urgent} urgent)"
        parts.append(msg)

    # Goals
    goals = ctx.get("goals", {})
    active = len(goals.get("active", []))
    overdue = len(goals.get("overdue", []))
    if active or overdue:
        msg = f"{active} active goals"
        if overdue:
            msg += f", {overdue} overdue"
        parts.append(msg)

    # System
    system = ctx.get("system", {})
    if system.get("halt_flag"):
        parts.append("SYSTEM HALTED")
    elif system.get("error_count_1h", 0) > 0:
        parts.append(f"{system['error_count_1h']} errors in last hour")
    else:
        uptime = system.get("uptime_hours", 0)
        if uptime:
            parts.append(f"System healthy, {uptime:.0f}h uptime")

    if not parts:
        return "No notable context."

    return "Context: " + ". ".join(parts) + "."
