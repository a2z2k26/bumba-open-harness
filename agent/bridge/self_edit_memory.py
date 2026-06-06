"""MS4.8 — Self-Editing Core Memory.

Agent-editable memory with tiered approval, audit logging, and rollback.
Tier A (learning, tools, examples) = auto-approved.
Tier B (preferences, decisions) = requires operator approval.
Tier C (identity, security) = always rejected.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Tier classification by category
TIER_A_CATEGORIES = frozenset({"learning", "tools", "examples", "general", "reference"})
TIER_B_CATEGORIES = frozenset({"preference", "decision", "process", "person"})
TIER_C_CATEGORIES = frozenset({"identity", "security", "kernel", "operator"})

# All valid actions
VALID_ACTIONS = frozenset({"create", "update", "delete", "rollback"})

_CREATE_AUDIT_TABLE = """\
CREATE TABLE IF NOT EXISTS memory_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    action TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    reason TEXT DEFAULT '',
    tier TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    auto_approved INTEGER NOT NULL DEFAULT 0,
    trace_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);"""
_CREATE_AUDIT_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_audit_key ON memory_audit(key);"
)
_CREATE_AUDIT_IDX_TIME = (
    "CREATE INDEX IF NOT EXISTS idx_audit_time ON memory_audit(created_at);"
)

_CREATE_PENDING_TABLE = """\
CREATE TABLE IF NOT EXISTS memory_pending_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    action TEXT NOT NULL,
    new_value TEXT,
    reason TEXT DEFAULT '',
    category TEXT DEFAULT '',
    tier TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);"""


@dataclass
class EditRequest:
    """A request to edit agent memory."""

    key: str
    action: str  # create | update | delete
    new_value: str | None = None
    reason: str = ""
    category: str = "general"
    trace_id: str | None = None


@dataclass
class EditResult:
    """Result of an edit attempt."""

    success: bool = False
    tier: str = ""
    auto_approved: bool = False
    needs_approval: bool = False
    rejected: bool = False
    reject_reason: str = ""
    audit_id: int = 0
    version: int = 0


@dataclass
class AuditEntry:
    """An entry in the memory audit log."""

    id: int = 0
    key: str = ""
    action: str = ""
    old_value: str | None = None
    new_value: str | None = None
    reason: str = ""
    tier: str = ""
    approved: bool = False
    auto_approved: bool = False
    trace_id: str | None = None
    created_at: str = ""


def classify_tier(category: str) -> str:
    """Classify a category into approval tier."""
    if category in TIER_A_CATEGORIES:
        return "A"
    if category in TIER_B_CATEGORIES:
        return "B"
    if category in TIER_C_CATEGORIES:
        return "C"
    return "A"  # Default to most permissive for unknown categories


class SelfEditMemory:
    """Manages agent self-editing of memory with tiered approval."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path) if db_path else ":memory:"
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(_CREATE_AUDIT_TABLE)
            conn.execute(_CREATE_AUDIT_IDX)
            conn.execute(_CREATE_AUDIT_IDX_TIME)
            conn.execute(_CREATE_PENDING_TABLE)
            conn.commit()
        finally:
            conn.close()

    # -- edit request processing --------------------------------------------

    def process_edit(
        self, request: EditRequest, old_value: str | None = None,
        metrics: object | None = None,
    ) -> EditResult:
        """Process a memory edit request through the tiered system.

        Tier A: auto-approved, executed immediately.
        Tier B: queued for operator approval.
        Tier C: rejected immediately.
        Increments the ``self_edit_requests`` counter on every request (#22).
        """
        # Increment counter for every edit request received (#22)
        if metrics is not None:
            try:
                from .metrics import SELF_EDIT_REQUESTS
                metrics.increment(SELF_EDIT_REQUESTS)
            except Exception:
                pass
        tier = classify_tier(request.category)

        if tier == "C":
            return EditResult(
                rejected=True,
                tier="C",
                reject_reason=f"Category '{request.category}' is protected (Tier C)",
            )

        if tier == "A":
            audit_id = self._log_audit(
                key=request.key,
                action=request.action,
                old_value=old_value,
                new_value=request.new_value,
                reason=request.reason,
                tier="A",
                approved=True,
                auto_approved=True,
                trace_id=request.trace_id,
            )
            return EditResult(
                success=True,
                tier="A",
                auto_approved=True,
                audit_id=audit_id,
            )

        # Tier B: queue for approval
        self._queue_pending(request, tier)
        self._log_audit(
            key=request.key,
            action=request.action,
            old_value=old_value,
            new_value=request.new_value,
            reason=request.reason,
            tier="B",
            approved=False,
            auto_approved=False,
            trace_id=request.trace_id,
        )
        return EditResult(
            needs_approval=True,
            tier="B",
        )

    # -- pending edits management -------------------------------------------

    def _queue_pending(self, request: EditRequest, tier: str) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO memory_pending_edits "
                "(key, action, new_value, reason, category, tier) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    request.key,
                    request.action,
                    request.new_value,
                    request.reason,
                    request.category,
                    tier,
                ),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def get_pending_edits(self) -> list[dict]:
        """Get all pending edits awaiting approval."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, key, action, new_value, reason, category, tier, created_at "
                "FROM memory_pending_edits WHERE status = 'pending' "
                "ORDER BY created_at DESC"
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "id": r[0], "key": r[1], "action": r[2], "new_value": r[3],
                "reason": r[4], "category": r[5], "tier": r[6], "created_at": r[7],
            }
            for r in rows
        ]

    def approve_pending(self, pending_id: int) -> bool:
        """Approve a pending edit."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE memory_pending_edits SET status = 'approved' WHERE id = ?",
                (pending_id,),
            )
            conn.commit()
        finally:
            conn.close()
        return cur.rowcount > 0

    def reject_pending(self, pending_id: int, reason: str = "") -> bool:
        """Reject a pending edit."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE memory_pending_edits SET status = 'rejected' WHERE id = ?",
                (pending_id,),
            )
            conn.commit()
        finally:
            conn.close()
        return cur.rowcount > 0

    # -- audit logging ------------------------------------------------------

    def _log_audit(
        self,
        key: str,
        action: str,
        old_value: str | None,
        new_value: str | None,
        reason: str,
        tier: str,
        approved: bool,
        auto_approved: bool,
        trace_id: str | None = None,
    ) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO memory_audit "
                "(key, action, old_value, new_value, reason, tier, "
                "approved, auto_approved, trace_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    action,
                    old_value,
                    new_value,
                    reason,
                    tier,
                    1 if approved else 0,
                    1 if auto_approved else 0,
                    trace_id,
                ),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def get_audit_log(
        self, key: str | None = None, limit: int = 50
    ) -> list[AuditEntry]:
        """Get audit log, optionally filtered by key."""
        conn = self._connect()
        try:
            if key:
                rows = conn.execute(
                    "SELECT id, key, action, old_value, new_value, reason, "
                    "tier, approved, auto_approved, trace_id, created_at "
                    "FROM memory_audit WHERE key = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (key, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, key, action, old_value, new_value, reason, "
                    "tier, approved, auto_approved, trace_id, created_at "
                    "FROM memory_audit ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        finally:
            conn.close()

        return [
            AuditEntry(
                id=r[0], key=r[1], action=r[2], old_value=r[3],
                new_value=r[4], reason=r[5], tier=r[6],
                approved=bool(r[7]), auto_approved=bool(r[8]),
                trace_id=r[9], created_at=r[10],
            )
            for r in rows
        ]

    def get_audit_entry(self, audit_id: int) -> AuditEntry | None:
        """Get a single audit entry by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, key, action, old_value, new_value, reason, "
                "tier, approved, auto_approved, trace_id, created_at "
                "FROM memory_audit WHERE id = ?",
                (audit_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return AuditEntry(
            id=row[0], key=row[1], action=row[2], old_value=row[3],
            new_value=row[4], reason=row[5], tier=row[6],
            approved=bool(row[7]), auto_approved=bool(row[8]),
            trace_id=row[9], created_at=row[10],
        )

    def audit_count(self, key: str | None = None) -> int:
        conn = self._connect()
        try:
            if key:
                row = conn.execute(
                    "SELECT COUNT(*) FROM memory_audit WHERE key = ?", (key,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM memory_audit").fetchone()
        finally:
            conn.close()
        return row[0] if row else 0

    # -- format audit log ---------------------------------------------------

    def format_audit_log(self, entries: list[AuditEntry]) -> str:
        """Format audit entries as markdown table."""
        if not entries:
            return "_No audit entries found._"

        lines = [
            "| Time | Key | Action | Tier | Approved | Reason |",
            "|------|-----|--------|------|----------|--------|",
        ]
        for e in entries:
            approved = "auto" if e.auto_approved else ("yes" if e.approved else "no")
            lines.append(
                f"| {e.created_at} | {e.key} | {e.action} | {e.tier} "
                f"| {approved} | {e.reason[:50]} |"
            )
        return "\n".join(lines)
