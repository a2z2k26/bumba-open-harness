"""MS4.5 — ACE Reflection Loops.

Weekly reflection service: gathers metrics, failures, examples, and routing
data, produces structured insights, detects contradictions with prior
reflections, curates low-quality knowledge.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

MAX_REFLEXION_PAIRS = 3


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WeekData:
    """Aggregated data for a week of agent operation."""

    week_number: int = 0
    year: int = 0
    metrics_summaries: list[dict] = field(default_factory=list)
    failure_patterns: list[dict] = field(default_factory=list)
    few_shot_quality: dict = field(default_factory=dict)
    routing_health: list[dict] = field(default_factory=list)
    skill_proposals: list[dict] = field(default_factory=list)
    operator_feedback: list[str] = field(default_factory=list)


@dataclass
class ReflectionResult:
    """Structured output of a weekly reflection."""

    week_key: str = ""  # e.g., "reflection-2026-W11"
    achievements: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class Contradiction:
    """A detected contradiction between reflections."""

    old_insight: str
    new_insight: str
    resolution: str
    confidence: float = 0.0


@dataclass
class ReflexionPair:
    """In-session reflexion: failed attempt + reflection for context."""

    failed_input: str
    failed_output_summary: str
    reflection: str
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Reflection store (SQLite-backed)
# ---------------------------------------------------------------------------

import sqlite3
import threading

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_key TEXT NOT NULL UNIQUE,
    year INTEGER NOT NULL,
    week_number INTEGER NOT NULL,
    achievements TEXT DEFAULT '[]',
    improvements TEXT DEFAULT '[]',
    patterns TEXT DEFAULT '[]',
    contradictions TEXT DEFAULT '[]',
    recommendations TEXT DEFAULT '[]',
    raw_text TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);"""


class ReflectionStore:
    """SQLite-backed storage for weekly reflections."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path) if db_path else ":memory:"
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(_CREATE_TABLE)
            conn.commit()
        finally:
            conn.close()

    def store_reflection(self, result: ReflectionResult) -> None:
        """Store a weekly reflection."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO reflections "
                "(week_key, year, week_number, achievements, improvements, "
                "patterns, contradictions, recommendations, raw_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.week_key,
                    int(result.week_key.split("-")[1]) if "-" in result.week_key else 0,
                    int(result.week_key.split("W")[-1]) if "W" in result.week_key else 0,
                    json.dumps(result.achievements),
                    json.dumps(result.improvements),
                    json.dumps(result.patterns),
                    json.dumps(result.contradictions),
                    json.dumps(result.recommendations),
                    result.raw_text,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_reflection(self, week_key: str) -> ReflectionResult | None:
        """Get a specific week's reflection."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT week_key, achievements, improvements, patterns, "
                "contradictions, recommendations, raw_text "
                "FROM reflections WHERE week_key = ?",
                (week_key,),
            ).fetchone()
        finally:
            conn.close()
        return self._row_to_result(row) if row else None

    def get_recent(self, limit: int = 4, metrics: object | None = None) -> list[ReflectionResult]:
        """Get the most recent reflections.

        Increments the ``reflection_retrievals`` counter (#22).
        """
        # Increment retrieval counter on every get_recent() call (#22)
        if metrics is not None:
            try:
                from .metrics import REFLECTION_RETRIEVALS
                metrics.increment(REFLECTION_RETRIEVALS)
            except Exception:
                pass
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT week_key, achievements, improvements, patterns, "
                "contradictions, recommendations, raw_text "
                "FROM reflections ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [self._row_to_result(r) for r in rows]

    def count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM reflections").fetchone()
        finally:
            conn.close()
        return row[0] if row else 0

    def format_reflection(self, result: ReflectionResult) -> str:
        """Format a reflection as markdown."""
        lines = [f"# Reflection: {result.week_key}\n"]

        if result.achievements:
            lines.append("## Achievements")
            for a in result.achievements:
                lines.append(f"- {a}")
            lines.append("")

        if result.improvements:
            lines.append("## Areas for Improvement")
            for imp in result.improvements:
                lines.append(f"- {imp}")
            lines.append("")

        if result.patterns:
            lines.append("## Patterns Noticed")
            for p in result.patterns:
                lines.append(f"- {p}")
            lines.append("")

        if result.recommendations:
            lines.append("## Focus Next Week")
            for r in result.recommendations:
                lines.append(f"- {r}")
            lines.append("")

        if result.contradictions:
            lines.append("## Contradictions Detected")
            for c in result.contradictions:
                old = c.get("old_insight", "")
                new = c.get("new_insight", "")
                lines.append(f"- **Old**: {old}")
                lines.append(f"  **New**: {new}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _row_to_result(row: tuple) -> ReflectionResult:
        def _load(s):
            try:
                return json.loads(s) if s else []
            except (json.JSONDecodeError, TypeError):
                return []

        return ReflectionResult(
            week_key=row[0],
            achievements=_load(row[1]),
            improvements=_load(row[2]),
            patterns=_load(row[3]),
            contradictions=_load(row[4]),
            recommendations=_load(row[5]),
            raw_text=row[6] or "",
        )


# ---------------------------------------------------------------------------
# Week data gathering (pure computation, no I/O)
# ---------------------------------------------------------------------------

def make_week_key(dt: datetime | None = None) -> str:
    """Generate week key like 'reflection-2026-W11'."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    iso = dt.isocalendar()
    return f"reflection-{iso[0]}-W{iso[1]:02d}"


def gather_week_data_from_dicts(
    metrics: list[dict] | None = None,
    failures: list[dict] | None = None,
    examples_quality: dict | None = None,
    routing: list[dict] | None = None,
    proposals: list[dict] | None = None,
    feedback: list[str] | None = None,
) -> WeekData:
    """Build WeekData from pre-collected dicts (decoupled from DB)."""
    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    return WeekData(
        week_number=iso[1],
        year=iso[0],
        metrics_summaries=metrics or [],
        failure_patterns=failures or [],
        few_shot_quality=examples_quality or {},
        routing_health=routing or [],
        skill_proposals=proposals or [],
        operator_feedback=feedback or [],
    )


# ---------------------------------------------------------------------------
# In-session Reflexion (Shinn et al. inspired)
# ---------------------------------------------------------------------------

class ReflexionContext:
    """Manages in-session reflexion pairs for a single conversation."""

    def __init__(self, max_pairs: int = MAX_REFLEXION_PAIRS) -> None:
        self._pairs: list[ReflexionPair] = []
        self._max = max_pairs

    def add_pair(
        self, failed_input: str, failed_output: str, reflection: str
    ) -> None:
        """Add a reflexion pair (capped at max_pairs)."""
        if len(self._pairs) >= self._max:
            self._pairs.pop(0)  # Remove oldest
        self._pairs.append(ReflexionPair(
            failed_input=failed_input,
            failed_output_summary=failed_output[:200],
            reflection=reflection,
            timestamp=time.time(),
        ))

    def get_context(self) -> str:
        """Format reflexion pairs as context for next invocation."""
        if not self._pairs:
            return ""
        lines = ["## Previous Attempt Reflections\n"]
        for i, pair in enumerate(self._pairs, 1):
            lines.append(
                f"### Attempt {i} (failed)\n"
                f"**Input**: {pair.failed_input[:100]}\n"
                f"**What went wrong**: {pair.reflection}\n"
            )
        return "\n".join(lines)

    @property
    def count(self) -> int:
        return len(self._pairs)

    def clear(self) -> None:
        self._pairs.clear()
