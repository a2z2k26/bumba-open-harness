"""MS4.2 — Self-Generated Few-Shot Examples.

Detect successful interactions, extract input/output pairs as learning
examples, store with quality scores, retrieve relevant ones for prompt
injection.  Keeps a capped pool of high-quality examples.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Lazy import to avoid circular imports
def _get_metrics():
    try:
        from .metrics import FEW_SHOT_INJECTIONS
        return FEW_SHOT_INJECTIONS
    except ImportError:
        return None

MAX_EXAMPLES = 50
MIN_QUALITY_FOR_INJECTION = 0.3
MAX_INJECTION_CHARS = 2000  # ~500 tokens
DEFAULT_QUALITY = 1.0

# Task type classification keywords
_TASK_PATTERNS: dict[str, list[str]] = {
    "code_review": ["review", "code review", "check this code", "refactor", "lint"],
    "search": ["search", "find", "look up", "lookup", "google"],
    "analysis": ["analyze", "analyse", "explain", "why does", "how does", "investigate"],
    "creative": ["write", "draft", "compose", "generate text", "story", "poem"],
    "admin": ["deploy", "restart", "status", "health", "config"],
    "deploy": ["deploy", "ship", "release", "push to prod"],
    "debug": ["bug", "error", "fix", "broken", "crash", "traceback", "exception"],
}

# Tools → task type mapping
_TOOL_TASK_MAP: dict[str, str] = {
    "brave-search": "search",
    "exa": "search",
    "playwright": "search",
    "github": "code_review",
    "filesystem": "analysis",
    "notion": "admin",
}

# Patterns to strip from examples (PII, secrets)
_PII_PATTERNS = [
    re.compile(r"<@!?\d+>"),               # Discord mentions
    re.compile(r"[A-Za-z0-9+/]{40,}=*"),   # Long base64 (potential secrets)
    re.compile(r"sk-[A-Za-z0-9]{20,}"),     # API keys
    re.compile(r"xox[bpars]-[A-Za-z0-9-]+"),  # Slack tokens
]

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS few_shot_examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    input_text TEXT NOT NULL,
    output_text TEXT NOT NULL,
    tools_used TEXT DEFAULT '[]',
    quality_score REAL NOT NULL DEFAULT 1.0,
    use_count INTEGER NOT NULL DEFAULT 0,
    last_used TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata TEXT DEFAULT '{}'
);"""
_CREATE_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_fse_task_type "
    "ON few_shot_examples(task_type);"
)
_CREATE_IDX_QUALITY = (
    "CREATE INDEX IF NOT EXISTS idx_fse_quality "
    "ON few_shot_examples(quality_score);"
)


@dataclass
class FewShotExample:
    """A stored input/output learning example."""

    id: int = 0
    task_type: str = "general"
    input_text: str = ""
    output_text: str = ""
    tools_used: list[str] = field(default_factory=list)
    quality_score: float = DEFAULT_QUALITY
    use_count: int = 0
    last_used: str | None = None
    created_at: str = ""
    metadata: dict = field(default_factory=dict)


def classify_task_type(message: str, tools_used: list[str] | None = None) -> str:
    """Classify a message into a task type via keywords and tools."""
    msg_lower = message.lower()

    # Check tools first (more reliable signal)
    if tools_used:
        for tool in tools_used:
            tool_base = tool.split("__")[0] if "__" in tool else tool
            if tool_base in _TOOL_TASK_MAP:
                return _TOOL_TASK_MAP[tool_base]

    # Keyword matching — first match wins (ordered by specificity)
    for task_type in ["deploy", "debug", "code_review", "search", "analysis", "creative", "admin"]:
        for kw in _TASK_PATTERNS.get(task_type, []):
            if kw in msg_lower:
                return task_type

    return "general"


def clean_text(text: str) -> str:
    """Strip PII and secrets from text."""
    result = text
    for pattern in _PII_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _cosine_sim_words(a: str, b: str) -> float:
    """Simple word-overlap cosine similarity for retrieval ranking."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / ((len(words_a) * len(words_b)) ** 0.5)


class FewShotStore:
    """SQLite-backed few-shot example storage with quality tracking."""

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
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_IDX)
            conn.execute(_CREATE_IDX_QUALITY)
            conn.commit()
        finally:
            conn.close()

    # -- store --------------------------------------------------------------

    def store(self, example: FewShotExample) -> int:
        """Store a new few-shot example. Returns the new row ID."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO few_shot_examples "
                "(task_type, input_text, output_text, tools_used, quality_score, "
                "use_count, last_used, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    example.task_type,
                    clean_text(example.input_text),
                    clean_text(example.output_text),
                    json.dumps(example.tools_used),
                    example.quality_score,
                    example.use_count,
                    example.last_used,
                    json.dumps(example.metadata),
                ),
            )
            conn.commit()
            row_id = cur.lastrowid or 0
        finally:
            conn.close()

        self.enforce_cap()
        return row_id

    # -- retrieve -----------------------------------------------------------

    def get(self, example_id: int) -> FewShotExample | None:
        """Get a single example by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, task_type, input_text, output_text, tools_used, "
                "quality_score, use_count, last_used, created_at, metadata "
                "FROM few_shot_examples WHERE id = ?",
                (example_id,),
            ).fetchone()
        finally:
            conn.close()
        return self._row_to_example(row) if row else None

    def get_relevant(
        self,
        message: str,
        task_type: str | None = None,
        limit: int = 2,
    ) -> list[FewShotExample]:
        """Retrieve most relevant examples for a message.

        Ranking: similarity * 0.6 + quality * 0.3 + recency * 0.1
        """
        conn = self._connect()
        try:
            if task_type:
                rows = conn.execute(
                    "SELECT id, task_type, input_text, output_text, tools_used, "
                    "quality_score, use_count, last_used, created_at, metadata "
                    "FROM few_shot_examples "
                    "WHERE quality_score >= ? AND task_type = ?",
                    (MIN_QUALITY_FOR_INJECTION, task_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, task_type, input_text, output_text, tools_used, "
                    "quality_score, use_count, last_used, created_at, metadata "
                    "FROM few_shot_examples WHERE quality_score >= ?",
                    (MIN_QUALITY_FOR_INJECTION,),
                ).fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        now = time.time()
        scored: list[tuple[float, FewShotExample]] = []

        for row in rows:
            ex = self._row_to_example(row)
            sim = _cosine_sim_words(message, ex.input_text)

            # Recency: 1.0 for today, decays over 30 days
            try:
                created_ts = datetime.fromisoformat(ex.created_at).timestamp()
            except (ValueError, TypeError):
                created_ts = now - 86400 * 30
            age_days = max(0, (now - created_ts) / 86400)
            recency = max(0.0, 1.0 - age_days / 30.0)

            score = sim * 0.6 + ex.quality_score * 0.3 + recency * 0.1
            scored.append((score, ex))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in scored[:limit]]

    # -- quality tracking ---------------------------------------------------

    def update_quality(self, example_id: int, helped: bool) -> None:
        """Update quality score after an example was used.

        new_score = (old_score * use_count + helped) / (use_count + 1)
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT quality_score, use_count FROM few_shot_examples WHERE id = ?",
                (example_id,),
            ).fetchone()
            if not row:
                return

            old_score, use_count = row
            new_score = (old_score * use_count + (1.0 if helped else 0.0)) / (use_count + 1)
            now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

            conn.execute(
                "UPDATE few_shot_examples SET quality_score = ?, use_count = ?, "
                "last_used = ? WHERE id = ?",
                (new_score, use_count + 1, now_ts, example_id),
            )
            conn.commit()
        finally:
            conn.close()

    # -- cap enforcement ----------------------------------------------------

    def enforce_cap(self, max_examples: int = MAX_EXAMPLES) -> int:
        """Remove lowest-quality examples if count exceeds max. Returns removed count."""
        conn = self._connect()
        try:
            count = conn.execute("SELECT COUNT(*) FROM few_shot_examples").fetchone()[0]
            if count <= max_examples:
                return 0

            excess = count - max_examples
            conn.execute(
                "DELETE FROM few_shot_examples WHERE id IN ("
                "  SELECT id FROM few_shot_examples "
                "  ORDER BY quality_score ASC, created_at ASC LIMIT ?"
                ")",
                (excess,),
            )
            conn.commit()
        finally:
            conn.close()
        return excess

    # -- injection formatting -----------------------------------------------

    def format_injection(self, examples: list[FewShotExample], metrics: object | None = None) -> str:
        """Format examples as markdown for system prompt injection.

        Hard cap at MAX_INJECTION_CHARS (~500 tokens).
        Increments the ``few_shot_injections`` counter when examples are injected.
        """
        if not examples:
            return ""

        sections = ["## Recent Successful Approaches\n"]
        total_chars = len(sections[0])

        for ex in examples:
            tools_str = ", ".join(ex.tools_used) if ex.tools_used else "none"
            section = (
                f"### Task: {ex.input_text[:100]}\n"
                f"**Approach**: {ex.output_text[:300]}\n"
                f"**Tools**: {tools_str}\n\n"
            )
            if total_chars + len(section) > MAX_INJECTION_CHARS:
                break
            sections.append(section)
            total_chars += len(section)

        if len(sections) <= 1:
            return ""
        result = "".join(sections).rstrip()
        # Increment usage counter when injection produces output (#22)
        if result and metrics is not None:
            try:
                from .metrics import FEW_SHOT_INJECTIONS
                metrics.increment(FEW_SHOT_INJECTIONS)
            except Exception:
                pass
        return result

    # -- count / list -------------------------------------------------------

    def count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM few_shot_examples").fetchone()
        finally:
            conn.close()
        return row[0] if row else 0

    def list_all(self, limit: int = 100) -> list[FewShotExample]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, task_type, input_text, output_text, tools_used, "
                "quality_score, use_count, last_used, created_at, metadata "
                "FROM few_shot_examples ORDER BY quality_score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [self._row_to_example(r) for r in rows]

    def delete(self, example_id: int) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM few_shot_examples WHERE id = ?", (example_id,)
            )
            conn.commit()
        finally:
            conn.close()
        return cur.rowcount > 0

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _row_to_example(row: tuple) -> FewShotExample:
        tools = []
        try:
            tools = json.loads(row[4]) if row[4] else []
        except (json.JSONDecodeError, TypeError):
            pass
        metadata = {}
        try:
            metadata = json.loads(row[9]) if row[9] else {}
        except (json.JSONDecodeError, TypeError):
            pass
        return FewShotExample(
            id=row[0],
            task_type=row[1],
            input_text=row[2],
            output_text=row[3],
            tools_used=tools,
            quality_score=row[5],
            use_count=row[6],
            last_used=row[7],
            created_at=row[8],
            metadata=metadata,
        )
