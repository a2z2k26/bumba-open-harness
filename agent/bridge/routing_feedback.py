"""MS4.4 — Negative-Feedback Routing.

Track per-tool and per-model performance.  Automatically reduce routing
weight for tools with high failure rates and escalate tasks to more
capable models when cheaper models consistently fail.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Health thresholds
HEALTHY_THRESHOLD = 0.70
DEGRADED_THRESHOLD = 0.30
RECOVERY_CONSECUTIVE = 5  # successes needed to recover

# Weight mapping
WEIGHT_HEALTHY = 1.0
WEIGHT_DEGRADED = 0.5
WEIGHT_UNHEALTHY = 0.1

# Model escalation
ESCALATION_FAILURE_THRESHOLD = 0.20  # 20% failure → escalate
ESCALATION_COOLDOWN_S = 86400  # 24 hours
DE_ESCALATION_SUCCESS_THRESHOLD = 0.80

_MODEL_TIERS = ["haiku", "sonnet", "opus"]

_CREATE_TOOL_TABLE = """\
CREATE TABLE IF NOT EXISTS tool_performance (
    tool_name TEXT PRIMARY KEY,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    total_latency_ms REAL NOT NULL DEFAULT 0.0,
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL DEFAULT (datetime('now'))
);"""

_CREATE_MODEL_TABLE = """\
CREATE TABLE IF NOT EXISTS model_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_tier TEXT NOT NULL,
    task_type TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(model_tier, task_type)
);"""


@dataclass
class ToolHealth:
    """Health status for a single tool."""

    name: str
    invocations: int = 0
    success_rate: float = 1.0
    avg_latency_ms: float = 0.0
    status: str = "healthy"  # healthy | degraded | unhealthy
    weight: float = WEIGHT_HEALTHY
    consecutive_successes: int = 0
    consecutive_failures: int = 0


@dataclass
class ModelPerformance:
    """Performance data for a model tier on a task type."""

    model_tier: str
    task_type: str
    attempts: int = 0
    successes: int = 0
    retries: int = 0
    success_rate: float = 1.0


@dataclass
class EscalationRecord:
    """Active model escalation."""

    task_type: str
    from_tier: str
    to_tier: str
    reason: str
    since: float  # monotonic time


class RoutingFeedbackEngine:
    """Track tool/model performance and adjust routing weights."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path) if db_path else ":memory:"
        self._lock = threading.Lock()
        self._escalations: dict[str, EscalationRecord] = {}
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(_CREATE_TOOL_TABLE)
            conn.execute(_CREATE_MODEL_TABLE)
            conn.commit()
        finally:
            conn.close()

    # -- tool tracking ------------------------------------------------------

    def record_tool_use(
        self, tool_name: str, success: bool, latency_ms: float = 0.0
    ) -> None:
        """Record a tool invocation result.  Thread-safe via atomic upsert."""
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            # Ensure row exists (no-op if already there)
            conn.execute(
                "INSERT OR IGNORE INTO tool_performance "
                "(tool_name, invocation_count, success_count, failure_count, "
                "total_latency_ms, consecutive_successes, consecutive_failures, "
                "last_updated) VALUES (?, 0, 0, 0, 0.0, 0, 0, ?)",
                (tool_name, now),
            )
            # Atomic update
            if success:
                conn.execute(
                    "UPDATE tool_performance SET "
                    "invocation_count = invocation_count + 1, "
                    "success_count = success_count + 1, "
                    "total_latency_ms = total_latency_ms + ?, "
                    "consecutive_successes = consecutive_successes + 1, "
                    "consecutive_failures = 0, "
                    "last_updated = ? WHERE tool_name = ?",
                    (latency_ms, now, tool_name),
                )
            else:
                conn.execute(
                    "UPDATE tool_performance SET "
                    "invocation_count = invocation_count + 1, "
                    "failure_count = failure_count + 1, "
                    "total_latency_ms = total_latency_ms + ?, "
                    "consecutive_successes = 0, "
                    "consecutive_failures = consecutive_failures + 1, "
                    "last_updated = ? WHERE tool_name = ?",
                    (latency_ms, now, tool_name),
                )
            conn.commit()
        finally:
            conn.close()

    def get_tool_health(self, tool_name: str) -> ToolHealth:
        """Get health status for a single tool."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT tool_name, invocation_count, success_count, failure_count, "
                "total_latency_ms, consecutive_successes, consecutive_failures "
                "FROM tool_performance WHERE tool_name = ?",
                (tool_name,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return ToolHealth(name=tool_name)

        inv = row[1]
        success_rate = row[2] / inv if inv > 0 else 1.0
        avg_latency = row[4] / inv if inv > 0 else 0.0

        if success_rate >= HEALTHY_THRESHOLD:
            status = "healthy"
            weight = WEIGHT_HEALTHY
        elif success_rate >= DEGRADED_THRESHOLD:
            status = "degraded"
            weight = WEIGHT_DEGRADED
        else:
            status = "unhealthy"
            weight = WEIGHT_UNHEALTHY

        return ToolHealth(
            name=row[0],
            invocations=inv,
            success_rate=success_rate,
            avg_latency_ms=avg_latency,
            status=status,
            weight=weight,
            consecutive_successes=row[5],
            consecutive_failures=row[6],
        )

    def get_all_tool_health(self) -> list[ToolHealth]:
        """Get health for all tracked tools, sorted by status."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT tool_name FROM tool_performance ORDER BY tool_name"
            ).fetchall()
        finally:
            conn.close()
        return [self.get_tool_health(r[0]) for r in rows]

    def get_tool_weight(self, tool_name: str) -> float:
        """Get routing weight for a tool (0.0 - 1.0)."""
        return self.get_tool_health(tool_name).weight

    def is_recovered(self, tool_name: str) -> bool:
        """Check if a tool has recovered (N consecutive successes)."""
        health = self.get_tool_health(tool_name)
        return health.consecutive_successes >= RECOVERY_CONSECUTIVE

    # -- model tracking -----------------------------------------------------

    def record_model_use(
        self,
        model_tier: str,
        task_type: str,
        success: bool,
        retry_needed: bool = False,
    ) -> None:
        """Record a model tier invocation result."""
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            existing = conn.execute(
                "SELECT attempts, successes, retries FROM model_performance "
                "WHERE model_tier = ? AND task_type = ?",
                (model_tier, task_type),
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE model_performance SET attempts = ?, successes = ?, "
                    "retries = ?, last_updated = ? "
                    "WHERE model_tier = ? AND task_type = ?",
                    (
                        existing[0] + 1,
                        existing[1] + (1 if success else 0),
                        existing[2] + (1 if retry_needed else 0),
                        now,
                        model_tier,
                        task_type,
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO model_performance "
                    "(model_tier, task_type, attempts, successes, retries, last_updated) "
                    "VALUES (?, ?, 1, ?, ?, ?)",
                    (
                        model_tier,
                        task_type,
                        1 if success else 0,
                        1 if retry_needed else 0,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_model_performance(
        self, model_tier: str, task_type: str
    ) -> ModelPerformance:
        """Get performance data for a model tier on a task type."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT model_tier, task_type, attempts, successes, retries "
                "FROM model_performance WHERE model_tier = ? AND task_type = ?",
                (model_tier, task_type),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return ModelPerformance(model_tier=model_tier, task_type=task_type)

        attempts = row[2]
        success_rate = row[3] / attempts if attempts > 0 else 1.0
        return ModelPerformance(
            model_tier=row[0],
            task_type=row[1],
            attempts=attempts,
            successes=row[3],
            retries=row[4],
            success_rate=success_rate,
        )

    # -- model escalation ---------------------------------------------------

    def check_escalation(
        self, model_tier: str, task_type: str
    ) -> str | None:
        """Check if model should be escalated.

        Returns the recommended tier (or None if no escalation needed).
        """
        # Already at max tier
        if model_tier == "opus":
            return None

        # Check cooldown
        esc_key = f"{model_tier}:{task_type}"
        with self._lock:
            existing = self._escalations.get(esc_key)
            if existing and (time.monotonic() - existing.since) < ESCALATION_COOLDOWN_S:
                return existing.to_tier

        perf = self.get_model_performance(model_tier, task_type)
        if perf.attempts < 5:  # Need minimum data
            return None

        failure_rate = 1.0 - perf.success_rate
        if failure_rate <= ESCALATION_FAILURE_THRESHOLD:
            return None

        # Escalate one tier up
        idx = _MODEL_TIERS.index(model_tier) if model_tier in _MODEL_TIERS else 0
        next_tier = _MODEL_TIERS[min(idx + 1, len(_MODEL_TIERS) - 1)]

        with self._lock:
            self._escalations[esc_key] = EscalationRecord(
                task_type=task_type,
                from_tier=model_tier,
                to_tier=next_tier,
                reason=f"Failure rate {failure_rate:.0%} exceeds {ESCALATION_FAILURE_THRESHOLD:.0%}",
                since=time.monotonic(),
            )

        return next_tier

    def check_de_escalation(
        self, model_tier: str, task_type: str
    ) -> str | None:
        """Check if a previously escalated model can de-escalate.

        Returns original tier if de-escalation is appropriate, else None.
        """
        esc_key_candidates = [
            f"{tier}:{task_type}" for tier in _MODEL_TIERS
            if _MODEL_TIERS.index(tier) < _MODEL_TIERS.index(model_tier)
        ]

        with self._lock:
            for key in esc_key_candidates:
                esc = self._escalations.get(key)
                if not esc:
                    continue
                # Check cooldown
                if (time.monotonic() - esc.since) < ESCALATION_COOLDOWN_S:
                    continue
                # Check original tier performance
                perf = self.get_model_performance(esc.from_tier, task_type)
                if perf.success_rate >= DE_ESCALATION_SUCCESS_THRESHOLD:
                    del self._escalations[key]
                    return esc.from_tier

        return None

    def get_active_escalations(self) -> list[EscalationRecord]:
        """Return all active model escalations."""
        with self._lock:
            return list(self._escalations.values())

    # -- routing report -----------------------------------------------------

    def format_routing_report(self) -> str:
        """Format a markdown routing report."""
        lines = ["## Tool Health\n"]
        lines.append("| Tool | Invocations | Success Rate | Avg Latency | Status | Weight |")
        lines.append("|------|-------------|-------------|-------------|--------|--------|")

        for th in self.get_all_tool_health():
            lines.append(
                f"| {th.name} | {th.invocations} | {th.success_rate:.0%} "
                f"| {th.avg_latency_ms:.0f}ms | {th.status} | {th.weight} |"
            )

        lines.append("\n## Active Escalations\n")
        escalations = self.get_active_escalations()
        if escalations:
            lines.append("| Task Type | From | To | Reason |")
            lines.append("|-----------|------|----|--------|")
            for esc in escalations:
                lines.append(
                    f"| {esc.task_type} | {esc.from_tier} | {esc.to_tier} "
                    f"| {esc.reason} |"
                )
        else:
            lines.append("_No active escalations._")

        return "\n".join(lines)
