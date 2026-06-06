"""Permission decision audit trail.

Records every tool permission decision with structured reason codes,
enabling replay and debugging of permission behavior.

Reason types (7 — simplified from Claude Code's 11):
    allowlist_match  — Tool matched an allow rule in settings
    denylist_match   — Tool matched a deny pattern
    tier_gate        — Blocked by trust tier (Tier C file, etc.)
    budget_exceeded  — Daily token budget exhausted
    circuit_open     — Circuit breaker is OPEN for this service
    operator_approval — Operator explicitly approved/denied
    default_deny     — No matching rule, default to deny

Integration:
    - tool_isolation.py: log decisions from check_bash_command(), validate_invocation()
    - budget.py: log budget-denied requests
    - circuit_breaker.py: log circuit-open denials
    - commands.py: /permissions query command
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from bridge.database import Database

logger = logging.getLogger(__name__)

VALID_REASON_TYPES = frozenset({
    "allowlist_match",
    "denylist_match",
    "tier_gate",
    "budget_exceeded",
    "circuit_open",
    "operator_approval",
    "default_deny",
})

VALID_ACTIONS = frozenset({"allow", "deny", "ask"})

VALID_CONTEXTS = frozenset({"interactive", "autonomous", "orchestrated"})


@dataclass(frozen=True)
class PermissionDecision:
    """A single permission decision record."""
    decision_id: str
    tool_name: str
    action: str  # allow | deny | ask
    reason_type: str  # one of VALID_REASON_TYPES
    reason_detail: str = ""
    rule_source: str | None = None
    matched_pattern: str | None = None
    context: str = "interactive"  # interactive | autonomous | orchestrated
    agent_id: str | None = None
    session_id: str = ""
    timestamp: str = ""

    def __init__(
        self,
        decision_id: str = "",
        tool_name: str = "",
        action: str = "deny",
        reason_type: str = "default_deny",
        reason_detail: str = "",
        rule_source: str | None = None,
        matched_pattern: str | None = None,
        context: str = "interactive",
        agent_id: str | None = None,
        session_id: str = "",
        timestamp: str = "",
    ) -> None:
        object.__setattr__(self, "decision_id", decision_id or uuid.uuid4().hex[:16])
        object.__setattr__(self, "tool_name", tool_name)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "reason_type", reason_type)
        object.__setattr__(self, "reason_detail", reason_detail)
        object.__setattr__(self, "rule_source", rule_source)
        object.__setattr__(self, "matched_pattern", matched_pattern)
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "agent_id", agent_id)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(
            self, "timestamp",
            timestamp or datetime.now(timezone.utc).isoformat(),
        )


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS permission_decisions (
    decision_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    action TEXT NOT NULL,
    reason_type TEXT NOT NULL,
    reason_detail TEXT DEFAULT '',
    rule_source TEXT,
    matched_pattern TEXT,
    context TEXT NOT NULL DEFAULT 'interactive',
    agent_id TEXT,
    session_id TEXT,
    timestamp TEXT NOT NULL
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_perm_tool ON permission_decisions(tool_name)",
    "CREATE INDEX IF NOT EXISTS idx_perm_action ON permission_decisions(action)",
    "CREATE INDEX IF NOT EXISTS idx_perm_time ON permission_decisions(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_perm_context ON permission_decisions(context)",
]


class PermissionAuditLog:
    """Structured permission decision audit trail backed by SQLite."""

    def __init__(self, db: "Database") -> None:
        self._db = db

    async def initialize(self) -> None:
        await self._db.execute(_CREATE_TABLE)
        for idx in _CREATE_INDEXES:
            await self._db.execute(idx)
        await self._db.commit()

    async def log(self, decision: PermissionDecision) -> None:
        """Persist a permission decision."""
        await self._db.execute(
            """INSERT OR REPLACE INTO permission_decisions
               (decision_id, tool_name, action, reason_type, reason_detail,
                rule_source, matched_pattern, context, agent_id, session_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision.decision_id, decision.tool_name, decision.action,
                decision.reason_type, decision.reason_detail,
                decision.rule_source, decision.matched_pattern,
                decision.context, decision.agent_id, decision.session_id,
                decision.timestamp,
            ),
        )
        await self._db.commit()

    async def query(
        self,
        tool_name: str | None = None,
        action: str | None = None,
        context: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[PermissionDecision]:
        """Query permission history with filters."""
        conditions = []
        params: list[Any] = []

        if tool_name:
            conditions.append("tool_name = ?")
            params.append(tool_name)
        if action:
            conditions.append("action = ?")
            params.append(action)
        if context:
            conditions.append("context = ?")
            params.append(context)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        rows = await self._db.fetchall(
            f"SELECT * FROM permission_decisions {where} ORDER BY timestamp DESC LIMIT ?",
            tuple(params),
        )

        return [
            PermissionDecision(
                decision_id=r["decision_id"],
                tool_name=r["tool_name"],
                action=r["action"],
                reason_type=r["reason_type"],
                reason_detail=r["reason_detail"],
                rule_source=r["rule_source"],
                matched_pattern=r["matched_pattern"],
                context=r["context"],
                agent_id=r["agent_id"],
                session_id=r["session_id"],
                timestamp=r["timestamp"],
            )
            for r in rows
        ]

    async def get_denial_summary(self, hours: int = 24) -> dict[str, int]:
        """Get denial counts by tool in the last N hours."""
        rows = await self._db.fetchall(
            """SELECT tool_name, COUNT(*) as cnt
               FROM permission_decisions
               WHERE action = 'deny'
                 AND timestamp > datetime('now', ?)
               GROUP BY tool_name
               ORDER BY cnt DESC""",
            (f"-{hours} hours",),
        )
        return {r["tool_name"]: r["cnt"] for r in rows}
