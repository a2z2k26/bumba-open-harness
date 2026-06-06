"""Session lifecycle management: resolve, create, expire, summarize."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .config import BridgeConfig
from .database import Database
from .drift_telemetry import MetricsRecord, record_metrics

if TYPE_CHECKING:
    from .daily_log import DailyLogWriter
    from .dialogue_delay_monitor import DialogueDelayMonitor

logger = logging.getLogger(__name__)


# Tool-name substrings that count as test-runner activity for the
# drift_telemetry test_frequency metric (Sprint 07.12).
_TEST_RUNNER_HINTS: tuple[str, ...] = ("pytest", "test", "unittest")


def _split_tool_names(raw: str | None) -> list[str]:
    """Split conversations.tools_used string into individual tool names.

    The column is a comma-separated string written by app.py:2615
    (``",".join(result.tools_used)``). Returns ``[]`` for ``None`` or
    empty/whitespace-only input.
    """
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_sqlite_ts(raw: str | None) -> datetime | None:
    """Parse a SQLite ``datetime('now')`` string into an aware UTC datetime.

    SQLite emits ``YYYY-MM-DD HH:MM:SS`` with no timezone. We attach UTC
    to make subtraction unambiguous. Returns ``None`` on parse failure.
    """
    if not raw:
        return None
    try:
        # SQLite's datetime('now') is UTC by spec but emits no offset.
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        # Fall back to fromisoformat for ISO-shaped timestamps.
        try:
            return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None


class SessionManager:
    """Manages Claude Code session lifecycle.

    Handles all 7 session triggers from BRIDGE-ARCHITECTURE.md Section 5.2.
    """

    def __init__(self, db: Database, config: BridgeConfig) -> None:
        self._db = db
        self._config = config
        self._daily_log: DailyLogWriter | None = None
        # #488: optional primer-write callback. Awaitable: (session_id, trigger) -> None.
        # Set via set_primer_callback. Invoked from _expire_session + handle_reset.
        self._primer_callback = None
        # Sprint 03.06 — optional memory reference for WAL drain at session end.
        # Wired via set_memory(). When unset, drain is a documented no-op.
        self._memory: Any | None = None
        # E1.5 — optional DialogueDelayMonitor for background message-age
        # observability. Wired via set_dialogue_delay_monitor(). When set,
        # the monitor is started on create_session() and stopped on
        # _expire_session(). Default None disables monitoring.
        self._monitor: "DialogueDelayMonitor | None" = None

    def set_memory(self, memory: Any) -> None:
        """Wire Memory for end-of-session WAL drain (Sprint 03.06).

        The drain runs from inside ``_expire_session`` (which fires for
        idle_timeout / operator_reset / file-size / error-count expiries),
        so a partial-session crash mid-write replays on next boot via
        ``Memory.recover_wal``. Failures never raise — drain is best-effort.
        """
        self._memory = memory

    def set_dialogue_delay_monitor(self, monitor: "DialogueDelayMonitor") -> None:
        """Wire a DialogueDelayMonitor for background message-age tracking (E1.5).

        When wired, the monitor is started at session creation (``create_session``)
        and stopped at session expiry (``_expire_session``). Start/stop are
        idempotent per the monitor contract, so rapid create/expire cycles are safe.
        """
        self._monitor = monitor

    # -- S57: Core implementation --

    async def resolve_session(self, chat_id: str) -> str | None:
        """Resolve the active session for a chat.

        Returns session_id if a valid session exists, None if a new one is needed.
        Handles idle timeout expiry automatically.
        """
        row = await self._db.fetchone(
            """SELECT id, claude_session_id, last_active_at, message_count
               FROM sessions
               WHERE chat_id = ? AND status = 'active'
               ORDER BY last_active_at DESC
               LIMIT 1""",
            (chat_id,),
        )

        if not row:
            return None

        session_db_id = row[0]
        session_id = row[1]
        last_active = row[2]

        # Check idle timeout using SQLite's time functions for consistency
        idle_row = await self._db.fetchone(
            """SELECT (julianday('now') - julianday(?)) * 86400""",
            (last_active,),
        )
        if idle_row and idle_row[0] > self._config.session_idle_timeout:
            await self._expire_session(session_db_id, "idle_timeout")
            return None

        return session_id

    def set_daily_log(self, writer: DailyLogWriter | None) -> None:
        """Wire DailyLogWriter for session logging."""
        self._daily_log = writer

    def set_primer_callback(self, callback) -> None:
        """Wire the primer-write callback (#488).

        Callback signature: ``async def cb(session_id: str, trigger: str) -> None``.
        Invoked on session expire (trigger='expire') and /reset (trigger='reset').
        Failures in the callback never raise — primer is best-effort.
        """
        self._primer_callback = callback

    async def _fire_primer(self, session_id: str, trigger: str) -> None:
        """Best-effort primer write. Never raises."""
        if self._primer_callback is None:
            return
        try:
            await self._primer_callback(session_id, trigger)
        except Exception:
            logger = __import__("logging").getLogger(__name__)
            logger.warning("primer callback failed", exc_info=True)

    async def create_session(self, chat_id: str) -> str:
        """Create a new session with a fresh UUID. Returns the claude_session_id."""
        session_id = str(uuid.uuid4())
        await self._db.execute(
            """INSERT INTO sessions (chat_id, claude_session_id, status)
               VALUES (?, ?, 'active')""",
            (chat_id, session_id),
        )
        await self._db.commit()
        # Log session creation (Phase 1, Sprint 1)
        if self._daily_log:
            self._daily_log.append(f"Session created: {session_id[:8]}...", category="session")
        # E1.5 — start background dialogue-delay monitor if wired.
        if self._monitor is not None:
            try:
                await self._monitor.start()
                logger.debug(
                    "dialogue_delay_monitor started for session %s", session_id
                )
            except Exception:
                logger.exception("dialogue_delay_monitor.start() failed — continuing")
        return session_id

    async def get_resume_id(self, chat_id: str) -> str | None:
        """Get Claude session_id for --resume, only if session has prior messages."""
        row = await self._db.fetchone(
            """SELECT claude_session_id FROM sessions
               WHERE chat_id = ? AND status = 'active' AND message_count > 0
               ORDER BY last_active_at DESC LIMIT 1""",
            (chat_id,),
        )
        return row[0] if row else None

    async def set_claude_session_id(self, chat_id: str, claude_session_id: str) -> None:
        """Store Claude's real session_id after first successful invocation."""
        await self._db.execute(
            """UPDATE sessions SET claude_session_id = ?
               WHERE chat_id = ? AND status = 'active'""",
            (claude_session_id, chat_id),
        )
        await self._db.commit()

    async def update_session(
        self,
        session_id: str,
        cost_usd: float = 0.0,
    ) -> None:
        """Update session stats after a message exchange."""
        await self._db.execute(
            """UPDATE sessions
               SET last_active_at = datetime('now'),
                   message_count = message_count + 1,
                   total_cost_usd = total_cost_usd + ?
               WHERE claude_session_id = ? AND status = 'active'""",
            (cost_usd, session_id),
        )
        await self._db.commit()

    async def handle_reset(self, chat_id: str) -> str:
        """Operator /reset: expire current session, create new. Returns new session_id."""
        # Snapshot the outgoing session id so the primer callback fires against it
        outgoing = await self.resolve_session(chat_id)
        await self.force_expire(chat_id)
        new_session_id = await self.create_session(chat_id)
        # #488: best-effort primer write on /reset
        if outgoing:
            await self._fire_primer(outgoing, trigger="reset")
        return new_session_id

    # -- S58: Expiry and summary --

    async def _expire_session(self, session_db_id: int, reason: str) -> None:
        """Mark session as expired with reason."""
        # Capture the claude_session_id before the UPDATE so we can pass it to the primer
        row = await self._db.fetchone(
            "SELECT claude_session_id FROM sessions WHERE id = ?", (session_db_id,),
        )
        claude_session_id = row[0] if row else None

        await self._db.execute(
            """UPDATE sessions
               SET status = 'expired', expired_reason = ?
               WHERE id = ?""",
            (reason, session_db_id),
        )
        await self._db.commit()
        logger.info("Session %d expired: %s", session_db_id, reason)

        # Sprint 07.12 — emit drift telemetry on session end. Best-effort:
        # any failure (DB error, malformed counters, IO error on JSONL write)
        # is logged but never raised — telemetry must not break teardown.
        if claude_session_id and getattr(
            self._config, "drift_telemetry_enabled", False
        ):
            try:
                metrics_record = await self._build_drift_metrics(
                    claude_session_id
                )
                metrics_path = (
                    Path(self._config.data_dir)
                    / self._config.bridge_metrics_path
                )
                record_metrics(metrics_record, metrics_path)
            except Exception:
                logger.exception(
                    "drift_telemetry.record_metrics failed for session=%s",
                    claude_session_id,
                )

        # #488: best-effort primer write on session expire
        if claude_session_id:
            await self._fire_primer(claude_session_id, trigger="expire")

        # Sprint 03.06 — drain memory WAL at session end. Best-effort:
        # any failure (consolidation lock held, applier raised, IO error)
        # is logged but never raised. The recovery path (Memory.recover_wal
        # at bridge startup) is what guarantees no-loss; this hook is the
        # happy-path drain.
        if self._memory is not None:
            try:
                drained = await self._memory.drain_wal()
                if drained:
                    logger.info(
                        "memory_wal drained %d entries on session end (reason=%s)",
                        drained,
                        reason,
                    )
            except Exception:
                logger.exception("memory_wal drain failed on session end")

        # E1.5 — stop background dialogue-delay monitor on session end.
        # Stop is idempotent per the monitor contract; errors are swallowed
        # so monitor teardown never interferes with session cleanup.
        if self._monitor is not None:
            try:
                await self._monitor.stop()
                logger.debug(
                    "dialogue_delay_monitor stopped for session reason=%s", reason
                )
            except Exception:
                logger.exception("dialogue_delay_monitor.stop() failed — continuing")

    async def _build_drift_metrics(self, session_id: str) -> MetricsRecord:
        """Assemble a MetricsRecord from session counters (Sprint 07.12).

        Derives the seven behavioural metrics from existing session and
        conversation tables. Fields with no natural source today fall back
        to conservative defaults (documented in the evidence file).

        Source bindings:
            - velocity: messages-per-hour from sessions.message_count and
              (last_active_at - created_at). 0.0 on zero duration.
            - bundling_indicator: avg tool calls per message. Counts
              comma-separated tokens in conversations.tools_used.
            - work_depth: total session duration in seconds.
            - test_frequency: count of tool calls whose name contains
              any of _TEST_RUNNER_HINTS (pytest/test/unittest).
            - honesty_indicator: defaults to 0.5 (no per-session score
              source today; self_verifier emits boolean URL checks only).
            - dialogue_responsiveness: average gap (seconds) between an
              operator (user) message and the next non-user reply.
            - engagement_indicator: ratio of operator (user) messages to
              agent (assistant) messages, clamped to [0.0, 1.0].
        """
        # Session-level stats: message_count + duration in seconds.
        session_row = await self._db.fetchone(
            """SELECT message_count,
                      (julianday(last_active_at) - julianday(created_at)) * 86400.0
               FROM sessions
               WHERE claude_session_id = ?""",
            (session_id,),
        )
        message_count: int = session_row[0] if session_row else 0
        duration_seconds: float = (
            float(session_row[1])
            if session_row and session_row[1] is not None
            else 0.0
        )

        # Per-message rows for tool-use + dialogue analysis.
        message_rows = await self._db.fetchall(
            """SELECT role, tools_used, created_at
               FROM conversations
               WHERE session_id = ?
               ORDER BY id ASC""",
            (session_id,),
        )

        total_tool_calls = 0
        test_tool_calls = 0
        operator_count = 0
        agent_count = 0
        responsiveness_samples: list[float] = []
        last_operator_at: datetime | None = None

        for role, tools_used, created_at in message_rows:
            tool_names = _split_tool_names(tools_used)
            total_tool_calls += len(tool_names)
            for name in tool_names:
                lowered = name.lower()
                if any(hint in lowered for hint in _TEST_RUNNER_HINTS):
                    test_tool_calls += 1

            if role == "user":
                operator_count += 1
                last_operator_at = _parse_sqlite_ts(created_at)
            elif role == "assistant":
                agent_count += 1
                if last_operator_at is not None:
                    reply_at = _parse_sqlite_ts(created_at)
                    if reply_at is not None:
                        delta = (reply_at - last_operator_at).total_seconds()
                        if delta >= 0:
                            responsiveness_samples.append(delta)
                        last_operator_at = None

        # 1. velocity — messages per hour
        if duration_seconds > 0 and message_count > 0:
            velocity = message_count / (duration_seconds / 3600.0)
        else:
            velocity = 0.0

        # 2. bundling_indicator — avg tool calls per message
        if message_count > 0:
            bundling_indicator = total_tool_calls / message_count
        else:
            bundling_indicator = 0.0

        # 3. work_depth — total session duration in seconds
        work_depth = max(duration_seconds, 0.0)

        # 4. test_frequency — raw count of test-runner tool calls
        test_frequency = float(test_tool_calls)

        # 5. honesty_indicator — no natural per-session source today
        honesty_indicator = 0.5

        # 6. dialogue_responsiveness — average operator→agent reply delay
        if responsiveness_samples:
            dialogue_responsiveness = sum(responsiveness_samples) / len(
                responsiveness_samples
            )
        else:
            dialogue_responsiveness = 0.0

        # 7. engagement_indicator — operator/agent ratio, clamped to [0, 1]
        if agent_count > 0:
            ratio = operator_count / agent_count
            engagement_indicator = max(0.0, min(ratio, 1.0))
        else:
            engagement_indicator = 0.0

        return MetricsRecord(
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            velocity=float(velocity),
            bundling_indicator=float(bundling_indicator),
            work_depth=float(work_depth),
            test_frequency=float(test_frequency),
            honesty_indicator=float(honesty_indicator),
            dialogue_responsiveness=float(dialogue_responsiveness),
            engagement_indicator=float(engagement_indicator),
        )

    async def force_expire(self, chat_id: str) -> None:
        """Expire all active sessions for a chat_id."""
        await self._db.execute(
            """UPDATE sessions
               SET status = 'expired', expired_reason = 'operator_reset'
               WHERE chat_id = ? AND status = 'active'""",
            (chat_id,),
        )
        await self._db.commit()

    async def expire_with_summary(
        self,
        chat_id: str,
        session_id: str,
        reason: str,
        summary_text: str | None = None,
    ) -> None:
        """Expire session and store summary in knowledge.

        The caller is responsible for generating the summary (e.g., via claude_runner).
        """
        # Get the DB row id
        row = await self._db.fetchone(
            "SELECT id FROM sessions WHERE claude_session_id = ? AND status = 'active'",
            (session_id,),
        )
        if row:
            await self._expire_session(row[0], reason)

        # Store summary if provided
        if summary_text:
            await self._db.execute(
                """INSERT INTO knowledge (key, value, tags, source)
                   VALUES (?, ?, 'session,summary', 'system')
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       updated_at = datetime('now')""",
                (f"session:summary:{session_id}", summary_text),
            )
            await self._db.commit()

    async def check_session_file_size(self, session_id: str) -> bool:
        """Check if Claude's session JSONL file exceeds max_file_size.

        Returns True if the file is too large (session should be expired).
        """
        # Claude Code stores sessions in ~/.claude/projects/
        projects_dir = Path.home() / ".claude" / "projects"
        if not projects_dir.exists():
            return False

        # Search for the session file
        for jsonl in projects_dir.rglob(f"{session_id}.jsonl"):
            if jsonl.stat().st_size > self._config.session_max_file_size:
                return True
        return False

    async def check_error_count(self, session_id: str) -> bool:
        """Check if consecutive errors have exceeded the threshold.

        Returns True if session should be expired due to errors.
        """
        rows = await self._db.fetchall(
            """SELECT role, content FROM conversations
               WHERE session_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (session_id, self._config.session_max_errors),
        )

        if len(rows) < self._config.session_max_errors:
            return False

        # Check if all recent entries are errors
        return all(
            r[0] == "system" and "error" in (r[1] or "").lower()
            for r in rows
        )


    async def context_pressure(self, session_id: str) -> float:
        """Estimate context window pressure as a ratio in [0.0, 1.0].

        Returns the maximum of three normalized ratios:
        - message_count / session_max_messages
        - session_age_seconds / session_max_duration
        - file_size / session_max_file_size

        A value > 0.7 indicates high pressure; > 0.9 suggests imminent expiry.
        Returns 0.0 for unknown or brand-new sessions.
        """
        row = await self._db.fetchone(
            """SELECT message_count, created_at
               FROM sessions
               WHERE claude_session_id = ? AND status = 'active'""",
            (session_id,),
        )
        if not row:
            return 0.0

        msg_count, created_at = row[0] or 0, row[1]

        # Ratio 1: message count
        msg_ratio = msg_count / max(self._config.session_max_messages, 1)

        # Ratio 2: age
        age_row = await self._db.fetchone(
            "SELECT (julianday('now') - julianday(?)) * 86400",
            (created_at,),
        )
        age_seconds = age_row[0] if age_row and age_row[0] is not None else 0.0
        age_ratio = age_seconds / max(self._config.session_max_duration, 1)

        # Ratio 3: file size
        size_ratio = 0.0
        projects_dir = Path.home() / ".claude" / "projects"
        if projects_dir.exists():
            for jsonl in projects_dir.rglob(f"{session_id}.jsonl"):
                size = jsonl.stat().st_size
                size_ratio = size / max(self._config.session_max_file_size, 1)
                break

        pressure = max(msg_ratio, age_ratio, size_ratio)
        return min(pressure, 1.0)

    async def get_context_status(self, chat_id: str) -> dict | None:
        """Return a context status dict for the active session of chat_id.

        Returns None if no active session.
        Dict keys: session_id, message_count, max_messages, pressure.
        """
        row = await self._db.fetchone(
            """SELECT claude_session_id, message_count, created_at
               FROM sessions
               WHERE chat_id = ? AND status = 'active'
               ORDER BY last_active_at DESC LIMIT 1""",
            (chat_id,),
        )
        if not row:
            return None

        session_id, msg_count, created_at = row[0], row[1] or 0, row[2]
        pressure = await self.context_pressure(session_id)

        age_row = await self._db.fetchone(
            "SELECT (julianday('now') - julianday(?)) * 86400",
            (created_at,),
        )
        age_seconds = int(age_row[0]) if age_row and age_row[0] is not None else 0

        return {
            "session_id": session_id,
            "message_count": msg_count,
            "max_messages": self._config.session_max_messages,
            "age_seconds": age_seconds,
            "max_duration": self._config.session_max_duration,
            "pressure": pressure,
        }

    async def get_session_stats(self) -> dict[str, Any]:
        """Get session statistics for /status and /uptime."""
        active = await self._db.fetchone(
            """SELECT claude_session_id, message_count, total_cost_usd,
                      created_at, last_active_at
               FROM sessions WHERE status = 'active'
               ORDER BY last_active_at DESC LIMIT 1""",
        )

        total_sessions = await self._db.fetchone(
            "SELECT COUNT(*) FROM sessions",
        )

        total_messages = await self._db.fetchone(
            "SELECT COUNT(*) FROM conversations",
        )

        return {
            "active_session": {
                "session_id": active[0] if active else None,
                "message_count": active[1] if active else 0,
                "cost_usd": active[2] if active else 0.0,
                "created_at": active[3] if active else None,
                "last_active_at": active[4] if active else None,
            },
            "total_sessions": total_sessions[0] if total_sessions else 0,
            "total_messages": total_messages[0] if total_messages else 0,
        }
