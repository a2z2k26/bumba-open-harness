"""MS4.3 — Evidence-Driven Skill Evolution.

Detect recurring failure patterns, generate skill proposals, validate
them for safety, and auto-deploy Tier A (non-kernel) skills.

Crystallization-from-trace (Sprint 03.09, #999)
-----------------------------------------------
``crystallize_from_trace`` distills a multi-step execution trace into a
``SkillProposal`` with ``reason="crystallized_from_trace"``. Concept-only
port of GenericAgent's auto-distill idea (MIT, paraphrased — no source
copied verbatim).

Heuristics (all must hold or the trace is rejected with ``None``):

* **Minimum length** — a trace shorter than ``CRYSTALLIZE_MIN_STEPS``
  (3) is too thin to crystallize into a reusable skill.
* **Retry / error budget** — at most 50% of steps may be retries or
  errors. A trace dominated by failures is not a successful pattern.
* **At least one tool call** — pure-LLM traces yield no portable
  procedure; we want a tool sequence that can be replayed.
* **Deduplication** — when a proposal with the derived skill name
  already exists in the store, we return ``None`` so operators are not
  flooded with redundant drafts.
* **Optional lineage** — when the caller passes a temporal-knowledge
  store *and* its ``skill_version_dag_enabled`` flag is on, the new
  proposal is recorded as a v0 entry via ``record_skill_version``.
  Otherwise the lineage hook is skipped.

Markdown-skill convention (Sprint 07.04, #1033)
-----------------------------------------------
``persist_skill_to_markdown`` and ``discover_markdown_skills`` add a
plain-markdown persistence + discovery layer for agent-authored skills.
Concept-only port of browser-harness's git-friendly skill directory
(MIT, paraphrased — no source code copied verbatim).

* Skills are written to
  ``agent/config/domain-skills/<domain>/<sanitized-skill-name>.md``.
* The proposal's ``failure_pattern["domain"]`` (or "general" if absent)
  determines the per-domain subdirectory.
* Skill-name sanitization: lowercase, runs of whitespace + slashes
  collapse to ``-``, all non-alphanumeric characters except ``-``/``_``
  are stripped. The resulting slug is the markdown filename stem.
* Files are written atomically via ``<file>.tmp`` rename to keep the
  directory in a parseable state on interrupted writes.
* Discovery is opt-in via the ``markdown_skills_enabled`` BridgeConfig
  flag — default OFF — and skips files that fail ``validate_skill``
  (logged at WARNING).
* Optional YAML frontmatter at the top of each file is parsed when the
  ``yaml`` library is importable; otherwise ``frontmatter`` is ``{}``.
* Sprint 07.05 will wire ``tool_shed`` to consume the discovered files.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3
FAILURE_WINDOW_DAYS = 7
MAX_PROPOSALS = 20
MAX_SAMPLE_MESSAGES = 5

# Sprint 03.08 (#998) — 3-trigger skill evolution loop thresholds.
# Concept-only port of OpenSpace's trigger model (MIT, paraphrased).
# A struggling post-execution record reports an error or low success
# signal; the trigger fires when those conditions show up in a single
# execution_record.
POST_EXEC_MIN_DURATION_MS = 0  # records with no duration still classify
TOOL_DEGRADATION_FAILURE_RATE = 0.40  # 40%+ failures = degraded tool
TOOL_DEGRADATION_MIN_INVOCATIONS = 5  # need this many to trust the rate
PERIODIC_HEALTH_STALE_DAYS = 30  # proposal not updated for this long is stale
PERIODIC_HEALTH_MIN_PROPOSALS = 1  # need at least this many to consider

# Sprint 03.09 (#999) — skill-crystallization-from-trace thresholds.
# Concept-only port of GenericAgent's auto-distill model (MIT,
# paraphrased). Each constant maps to one of the rejection rules
# documented in the module docstring.
CRYSTALLIZE_MIN_STEPS = 3
CRYSTALLIZE_MAX_BAD_RATIO = 0.5  # >50% retry/error → reject
# Tokens that flag a step as a retry or error in the heuristic check.
# Lower-cased before comparison; partial substring matches.
_BAD_STEP_TOKENS = ("retry", "error", "failed", "failure")

# Dangerous patterns that must never appear in generated skills
DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\beval\b"),
    re.compile(r"\bexec\b"),
    re.compile(r"\b__import__\b"),
    re.compile(r"\bos\.system\b"),
    re.compile(r"\bsubprocess\.call\b"),
    re.compile(r"--no-verify"),
    re.compile(r"force.?push"),
]

# Kernel-adjacent patterns → Tier B (requires approval)
KERNEL_PATTERNS = [
    re.compile(r"\bbridge/\b"),
    re.compile(r"\bsecurity\b"),
    re.compile(r"\bdeploy\b"),
    re.compile(r"\bkernel\b"),
    re.compile(r"\bLaunchDaemon\b"),
]

_CREATE_FAILURE_TABLE = """\
CREATE TABLE IF NOT EXISTS failure_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    context TEXT DEFAULT '{}',
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);"""
_CREATE_FAILURE_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_fp_task_ts "
    "ON failure_patterns(task_type, timestamp);"
)

_CREATE_PROPOSALS_TABLE = """\
CREATE TABLE IF NOT EXISTS skill_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    trigger_condition TEXT NOT NULL,
    approach TEXT NOT NULL,
    failure_pattern TEXT DEFAULT '{}',
    score REAL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'proposed',
    tier TEXT NOT NULL DEFAULT 'A',
    reject_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);"""

# Sprint 07.04 (#1033) — markdown-skill convention. Default base
# directory under which skills crystallize as plain markdown files.
# Layout: <base>/<domain>/<sanitized-skill-name>.md. Resolved relative
# to the repo root so ``agent/config/domain-skills`` matches existing
# config conventions (``agent/config/teams``, ``agent/config/expertise``,
# etc.). Callers may override per-call via ``base_dir=`` for tests.
DEFAULT_MARKDOWN_SKILLS_DIR = Path("agent/config/domain-skills")
_MARKDOWN_SKILL_DOMAIN_DEFAULT = "general"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FailurePattern:
    """A recurring failure pattern detected from failure_patterns table."""

    task_type: str
    error_type: str
    count: int
    first_seen: str
    last_seen: str
    sample_messages: list[str] = field(default_factory=list)


@dataclass
class SkillProposal:
    """A proposed skill to address a failure pattern or successful approach."""

    name: str
    description: str
    trigger_condition: str
    approach: list[str]
    failure_pattern: dict = field(default_factory=dict)
    score: float = 0.0
    status: str = "proposed"  # proposed | approved | deployed | rejected
    tier: str = "A"  # A (auto-deploy) | B (requires approval)
    reject_reason: str = ""
    id: int = 0
    created_at: str = ""
    # Sprint 03.08 (#998) — names the evolution trigger that emitted this
    # proposal. One of: "post_execution" | "tool_degradation" |
    # "periodic_health" | "" (legacy / unknown). Not persisted in the
    # SQLite ``skill_proposals`` table — kept in memory for dispatch /
    # routing. Concept-only port of OpenSpace's 3-trigger skill
    # evolution loop (MIT, paraphrased).
    reason: str = ""


@dataclass
class ValidationResult:
    """Result of skill validation."""

    passed: bool
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarkdownSkill:
    """Sprint 07.04 (#1033) — discovered markdown-persisted skill.

    Returned by :meth:`SkillEvolutionEngine.discover_markdown_skills`.
    Frozen so consumers can pass instances around without worrying
    about accidental mutation. Concept-only port of browser-harness's
    git-friendly skill directory (MIT, paraphrased).
    """

    path: Path
    domain: str
    name: str
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Severity scoring
# ---------------------------------------------------------------------------

_SEVERITY_WEIGHTS = {
    "crash": 3.0,
    "error": 2.0,
    "timeout": 2.0,
    "failure": 1.5,
    "warning": 1.0,
}


def _estimate_severity(error_type: str) -> float:
    """Estimate severity from error_type string."""
    error_lower = error_type.lower()
    for keyword, weight in _SEVERITY_WEIGHTS.items():
        if keyword in error_lower:
            return weight
    return 1.0


# ---------------------------------------------------------------------------
# SkillEvolutionEngine
# ---------------------------------------------------------------------------

class SkillEvolutionEngine:
    """Detects failure patterns, proposes skills, validates and deploys."""

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
            conn.execute(_CREATE_FAILURE_TABLE)
            conn.execute(_CREATE_FAILURE_IDX)
            conn.execute(_CREATE_PROPOSALS_TABLE)
            self._migrate_markdown_path_column(conn)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_markdown_path_column(conn: sqlite3.Connection) -> None:
        """Sprint 07.04 (#1033) — add ``markdown_path`` column idempotently.

        Mirrors the precedent set by the ``tier`` / ``reason`` columns: a
        plain ALTER TABLE inside a table_info() guard so re-running on an
        already-migrated database is a no-op.
        """
        rows = conn.execute("PRAGMA table_info(skill_proposals)").fetchall()
        existing_columns = {row[1] for row in rows}
        if "markdown_path" not in existing_columns:
            conn.execute(
                "ALTER TABLE skill_proposals ADD COLUMN markdown_path TEXT"
            )

    # -- failure recording --------------------------------------------------

    def record_failure(
        self,
        task_type: str,
        error_type: str,
        error_message: str,
        context: dict | None = None,
    ) -> None:
        """Record a failure for pattern detection."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO failure_patterns (task_type, error_type, error_message, context) "
                "VALUES (?, ?, ?, ?)",
                (task_type, error_type, error_message, json.dumps(context or {})),
            )
            conn.commit()
        finally:
            conn.close()

    # -- pattern detection --------------------------------------------------

    def detect_recurring_failures(
        self,
        window_days: int = FAILURE_WINDOW_DAYS,
        threshold: int = FAILURE_THRESHOLD,
    ) -> list[FailurePattern]:
        increment_module_counter("skill_evolution.detect_recurring_failures", tier=3)
        """Detect recurring failure patterns in the given window."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT task_type, error_type, COUNT(*) as cnt, "
                "MIN(timestamp) as first_seen, MAX(timestamp) as last_seen "
                "FROM failure_patterns "
                "WHERE timestamp >= datetime('now', ?) "
                "GROUP BY task_type, error_type "
                "HAVING cnt >= ? "
                "ORDER BY cnt DESC",
                (f"-{window_days} days", threshold),
            ).fetchall()

            patterns = []
            for row in rows:
                # Get sample messages
                samples = conn.execute(
                    "SELECT error_message FROM failure_patterns "
                    "WHERE task_type = ? AND error_type = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (row[0], row[1], MAX_SAMPLE_MESSAGES),
                ).fetchall()

                patterns.append(FailurePattern(
                    task_type=row[0],
                    error_type=row[1],
                    count=row[2],
                    first_seen=row[3],
                    last_seen=row[4],
                    sample_messages=[s[0] for s in samples],
                ))
        finally:
            conn.close()

        return patterns

    # -- proposal generation ------------------------------------------------

    def create_proposal(self, proposal: SkillProposal) -> int:
        """Store a skill proposal. Returns row ID."""
        # Classify tier
        proposal.tier = self._classify_tier(proposal)

        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT OR REPLACE INTO skill_proposals "
                "(name, description, trigger_condition, approach, failure_pattern, "
                "score, status, tier) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal.name,
                    proposal.description,
                    proposal.trigger_condition,
                    json.dumps(proposal.approach),
                    json.dumps(proposal.failure_pattern),
                    proposal.score,
                    proposal.status,
                    proposal.tier,
                ),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def _classify_tier(self, proposal: SkillProposal) -> str:
        """Classify proposal tier: A (auto-deploy) or B (requires approval)."""
        text = " ".join([
            proposal.description,
            proposal.trigger_condition,
            " ".join(proposal.approach),
        ])
        for pattern in KERNEL_PATTERNS:
            if pattern.search(text):
                return "B"
        return "A"

    # -- Pareto scoring -----------------------------------------------------

    def prioritize_proposals(
        self, proposals: list[SkillProposal], top_n: int = 3
    ) -> list[SkillProposal]:
        """Score and rank proposals by frequency * severity."""
        for p in proposals:
            freq = p.failure_pattern.get("count", 1)
            error_type = p.failure_pattern.get("error_type", "")
            severity = _estimate_severity(error_type)
            p.score = freq * severity

        proposals.sort(key=lambda p: p.score, reverse=True)
        return proposals[:top_n]

    # -- SKILL.md generation ------------------------------------------------

    @staticmethod
    def generate_skill_md(proposal: SkillProposal) -> str:
        """Render a SKILL.md file from a proposal."""
        steps = "\n".join(
            f"{i+1}. {step}" for i, step in enumerate(proposal.approach)
        )
        return (
            f"# {proposal.name}\n\n"
            f"## Description\n{proposal.description}\n\n"
            f"## When to Use\n{proposal.trigger_condition}\n\n"
            f"## Approach\n{steps}\n"
        )

    # -- validation ---------------------------------------------------------

    @staticmethod
    def validate_skill(content: str) -> ValidationResult:
        """Validate a skill file for safety and structure."""
        errors: list[str] = []

        # Structure checks
        if "# " not in content:
            errors.append("Missing title (no # heading found)")
        if "## " not in content:
            errors.append("Missing sections (no ## headings found)")

        # Dangerous pattern checks
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(content):
                errors.append(f"Dangerous pattern found: {pattern.pattern}")

        return ValidationResult(passed=len(errors) == 0, errors=errors)

    # -- proposal management ------------------------------------------------

    def get_proposals(
        self, status: str | None = None
    ) -> list[SkillProposal]:
        """List proposals, optionally filtered by status."""
        conn = self._connect()
        try:
            if status:
                rows = conn.execute(
                    "SELECT id, name, description, trigger_condition, approach, "
                    "failure_pattern, score, status, tier, reject_reason, created_at "
                    "FROM skill_proposals WHERE status = ? ORDER BY score DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, description, trigger_condition, approach, "
                    "failure_pattern, score, status, tier, reject_reason, created_at "
                    "FROM skill_proposals ORDER BY score DESC"
                ).fetchall()
        finally:
            conn.close()

        return [self._row_to_proposal(r) for r in rows]

    def get_proposal_by_name(self, name: str) -> SkillProposal | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, name, description, trigger_condition, approach, "
                "failure_pattern, score, status, tier, reject_reason, created_at "
                "FROM skill_proposals WHERE name = ?",
                (name,),
            ).fetchone()
        finally:
            conn.close()
        return self._row_to_proposal(row) if row else None

    def update_proposal_status(
        self, name: str, status: str, reject_reason: str = ""
    ) -> bool:
        """Update proposal status."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE skill_proposals SET status = ?, reject_reason = ?, "
                "updated_at = datetime('now') WHERE name = ?",
                (status, reject_reason, name),
            )
            conn.commit()
        finally:
            conn.close()
        return cur.rowcount > 0

    def proposal_exists(self, name: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM skill_proposals WHERE name = ?", (name,)
            ).fetchone()
        finally:
            conn.close()
        return row is not None

    def failure_count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM failure_patterns").fetchone()
        finally:
            conn.close()
        return row[0] if row else 0

    # -- gotchas generation -------------------------------------------------

    def get_failures_for_skill(
        self,
        skill_name: str,
        window_days: int = FAILURE_WINDOW_DAYS,
    ) -> list[dict]:
        """Return deduplicated failure rows where task_type matches skill_name.

        Matching is case-insensitive and strips hyphens/underscores so that
        "webapp-testing" matches task_type "webapp_testing" or "webapptesting".
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT error_type, error_message, COUNT(*) as cnt, "
                "MIN(timestamp) as first_seen, MAX(timestamp) as last_seen "
                "FROM failure_patterns "
                "WHERE task_type = ? "
                "AND timestamp >= datetime('now', ?) "
                "GROUP BY error_type, error_message "
                "ORDER BY cnt DESC",
                (skill_name, f"-{window_days} days"),
            ).fetchall()

            # Also try normalised form (hyphens → underscores, lower)
            normalised = skill_name.lower().replace("-", "_")
            if normalised != skill_name:
                extra = conn.execute(
                    "SELECT error_type, error_message, COUNT(*) as cnt, "
                    "MIN(timestamp) as first_seen, MAX(timestamp) as last_seen "
                    "FROM failure_patterns "
                    "WHERE task_type = ? "
                    "AND timestamp >= datetime('now', ?) "
                    "GROUP BY error_type, error_message "
                    "ORDER BY cnt DESC",
                    (normalised, f"-{window_days} days"),
                ).fetchall()
                rows = list(rows) + list(extra)

        finally:
            conn.close()

        # Dedup by (error_type, error_message), merging counts
        merged: dict[tuple[str, str], dict] = {}
        for row in rows:
            key = (row[0], row[1])
            if key in merged:
                merged[key]["count"] += row[2]
            else:
                merged[key] = {
                    "error_type": row[0],
                    "error_message": row[1],
                    "count": row[2],
                    "first_seen": row[3],
                    "last_seen": row[4],
                }
        return sorted(merged.values(), key=lambda x: x["count"], reverse=True)

    def generate_gotchas(
        self,
        skill_name: str,
        window_days: int = FAILURE_WINDOW_DAYS,
    ) -> str:
        """Generate a ``## Gotchas`` markdown section for *skill_name*.

        Returns empty string when no matching failures exist.

        Template per entry::
            **{error_type}** ({count}x in last {window} days): {message}.
        """
        failures = self.get_failures_for_skill(skill_name, window_days)
        if not failures:
            return ""

        lines = ["## Gotchas\n"]
        for f in failures:
            error_type = f["error_type"]
            count = f["count"]
            message = f["error_message"].rstrip(".")
            lines.append(
                f"- **{error_type}** ({count}x in last {window_days} days): {message}."
            )
        return "\n".join(lines)

    # -- Sprint 03.08 (#998) — 3-trigger skill evolution loop ---------------
    #
    # Each trigger is *pure*: it evaluates inputs and returns a
    # ``SkillProposal | None`` (or ``list[SkillProposal]`` for the
    # cadence trigger). Persistence is the caller's responsibility via
    # the existing :meth:`create_proposal` machinery. This split keeps
    # the triggers easy to test in isolation and lets feature-flag
    # gating happen at the call site, not inside the engine.
    #
    # Concept-only port of OpenSpace's three-trigger evolution model
    # (MIT, paraphrased — no source copied verbatim).

    def evaluate_post_execution(
        self, execution_record: dict[str, Any]
    ) -> SkillProposal | None:
        """Trigger 1 — fire when a single skill execution struggled.

        ``execution_record`` shape (best-effort, all keys optional):
            * ``skill_name`` (str) — required to emit a proposal
            * ``task_type`` (str) — used as fallback when skill_name absent
            * ``success`` (bool) — False signals a struggle
            * ``error_type`` (str) — present when execution raised
            * ``error_message`` (str) — sample message
            * ``retry_count`` (int) — non-zero implies struggle

        Returns a proposal when struggle is detected, else ``None``.
        Detection signals: ``success is False`` OR ``error_type``
        present OR ``retry_count > 0``. The proposal mirrors the
        existing ``create_proposal`` shape so downstream tier
        classification keeps working unchanged.
        """
        if not isinstance(execution_record, dict):
            return None

        skill_name = (
            execution_record.get("skill_name")
            or execution_record.get("task_type")
            or ""
        )
        if not skill_name:
            return None

        success = execution_record.get("success", True)
        error_type = execution_record.get("error_type", "") or ""
        error_message = execution_record.get("error_message", "") or ""
        retry_count = int(execution_record.get("retry_count", 0) or 0)

        struggling = (success is False) or bool(error_type) or retry_count > 0
        if not struggling:
            return None

        normalised_error = error_type or "execution_struggle"
        return SkillProposal(
            name=f"{skill_name}-post-exec-{normalised_error}",
            description=(
                f"Evolve `{skill_name}` after observed struggle "
                f"({normalised_error})."
            ),
            trigger_condition=(
                f"Post-execution analysis detected struggle in "
                f"`{skill_name}`."
            ),
            approach=[
                "Review the execution record for the failure mode.",
                "Add a defensive step or precondition check to the skill.",
                "Document the failure as a Gotcha for future runs.",
            ],
            failure_pattern={
                "skill_name": skill_name,
                "error_type": normalised_error,
                "error_message": error_message[:500],
                "retry_count": retry_count,
                "count": 1,
            },
            reason="post_execution",
        )

    def monitor_tool_degradation(
        self,
        tool_name: str,
        routing_feedback: Any | None = None,
        since: datetime | None = None,
    ) -> SkillProposal | None:
        """Trigger 2 — fire when a tool's failure rate climbs above threshold.

        Reads health from ``routing_feedback`` (typically a
        :class:`bridge.routing_feedback.RoutingFeedbackEngine`). The
        engine exposes ``get_tool_health(tool_name)`` returning a
        ``ToolHealth`` with ``invocations``, ``success_rate``, and
        ``status``; we use those instead of a custom read API. ``since``
        is accepted for spec parity but unused — the routing engine's
        own counters are cumulative and don't expose a windowed query.
        Surfaced as a known spec ambiguity in the dispatch report.

        Returns a proposal recommending a mitigation skill, else
        ``None`` when the tool is healthy or under-sampled.
        """
        if routing_feedback is None or not tool_name:
            return None

        get_health = getattr(routing_feedback, "get_tool_health", None)
        if get_health is None:
            return None

        try:
            health = get_health(tool_name)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("monitor_tool_degradation: %s", exc)
            return None

        invocations = getattr(health, "invocations", 0)
        success_rate = getattr(health, "success_rate", 1.0)
        if invocations < TOOL_DEGRADATION_MIN_INVOCATIONS:
            return None

        failure_rate = 1.0 - success_rate
        if failure_rate < TOOL_DEGRADATION_FAILURE_RATE:
            return None

        return SkillProposal(
            name=f"{tool_name}-degradation-mitigation",
            description=(
                f"Mitigate degraded `{tool_name}` "
                f"({failure_rate:.0%} failure rate over "
                f"{invocations} invocations)."
            ),
            trigger_condition=(
                f"`{tool_name}` failure rate exceeds "
                f"{TOOL_DEGRADATION_FAILURE_RATE:.0%}."
            ),
            approach=[
                f"Detect upstream `{tool_name}` failure before invocation.",
                "Fall back to an alternative tool or cached result.",
                "Surface the degradation in the next operator digest.",
            ],
            failure_pattern={
                "tool_name": tool_name,
                "failure_rate": failure_rate,
                "invocations": invocations,
                "error_type": "tool_degradation",
                "count": invocations,
            },
            reason="tool_degradation",
        )

    def periodic_health_check(
        self,
        stale_after_days: int = PERIODIC_HEALTH_STALE_DAYS,
    ) -> list[SkillProposal]:
        """Trigger 3 — scan for stale / unused / redundant skills.

        Walks the existing ``skill_proposals`` table for entries whose
        ``updated_at`` is older than ``stale_after_days`` and that are
        still in a non-terminal status (``proposed`` or ``approved``).
        For each match, emits a consolidation proposal so the operator
        can either redeploy, retire, or merge stale entries.

        Returns an empty list when no stale skills exist, supporting
        the spec's pure-function contract.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=stale_after_days)
        cutoff_iso = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT name, description, status, updated_at "
                "FROM skill_proposals "
                "WHERE updated_at < ? "
                "AND status IN ('proposed', 'approved') "
                "ORDER BY updated_at ASC",
                (cutoff_iso,),
            ).fetchall()
        finally:
            conn.close()

        proposals: list[SkillProposal] = []
        for row in rows:
            stale_name = row[0]
            stale_status = row[2]
            stale_updated = row[3] or "unknown"
            proposals.append(
                SkillProposal(
                    name=f"{stale_name}-consolidate",
                    description=(
                        f"Consolidate stale skill `{stale_name}` "
                        f"(status `{stale_status}`, last updated "
                        f"{stale_updated})."
                    ),
                    trigger_condition=(
                        f"`{stale_name}` has been idle for more than "
                        f"{stale_after_days} days."
                    ),
                    approach=[
                        f"Audit `{stale_name}` for active references.",
                        "Merge with an overlapping skill or retire it.",
                        "Update or reject the proposal to clear the queue.",
                    ],
                    failure_pattern={
                        "skill_name": stale_name,
                        "stale_since": stale_updated,
                        "error_type": "periodic_health_stale",
                        "count": 1,
                    },
                    reason="periodic_health",
                )
            )
        return proposals

    # -- Sprint 03.09 (#999) — skill crystallization from trace --------------
    #
    # Fourth trigger in spirit (alongside the three from 03.08): instead
    # of reacting to *failure*, this trigger reacts to *success* — a
    # multi-step trace that completed cleanly is candidate material for
    # a reusable skill. Pure function. The caller decides whether to
    # persist via ``create_proposal``; we only emit the candidate. See
    # the module docstring for the heuristic rules.

    def crystallize_from_trace(
        self,
        trace: list[dict[str, Any]],
        task_summary: str,
        *,
        enabled: bool = True,
        skill_version_store: Any | None = None,
        skill_version_dag_enabled: bool = False,
    ) -> SkillProposal | None:
        """Distill a successful execution trace into a ``SkillProposal``.

        Args:
            trace: ordered list of step dicts. Each step is best-effort
                shaped as ``{"tool": str, "input": dict, "output": dict,
                "ts": str}``. Unknown / missing keys are tolerated.
            task_summary: human-readable summary of the task whose
                trace is being crystallized. Used to derive the skill
                name and description.
            enabled: feature-flag gate. When ``False`` the method
                short-circuits to ``None`` so call sites can pass
                ``config.skill_crystallization_enabled`` directly
                without an extra ``if`` branch. Mirrors the 03.08
                trigger pattern (caller gates, engine stays pure).
            skill_version_store: optional
                :class:`bridge.temporal_knowledge.TemporalKnowledgeStore`.
                When provided *and* ``skill_version_dag_enabled`` is
                ``True``, the new proposal is logged as a v0 lineage
                entry via ``record_skill_version``. Lineage failures
                are logged and swallowed — they never block proposal
                emission.
            skill_version_dag_enabled: companion flag mirroring
                ``BridgeConfig.skill_version_dag_enabled``. Required to
                be ``True`` for the lineage hook to fire.

        Returns:
            A ``SkillProposal`` with ``reason="crystallized_from_trace"``
            when the trace meets the heuristic thresholds, else
            ``None``.
        """
        if not enabled:
            return None
        if not isinstance(trace, list) or len(trace) < CRYSTALLIZE_MIN_STEPS:
            return None
        if not isinstance(task_summary, str) or not task_summary.strip():
            return None

        bad_steps = 0
        tool_calls = 0
        tool_sequence: list[str] = []
        for step in trace:
            if not isinstance(step, dict):
                # Treat malformed entries conservatively as bad steps.
                bad_steps += 1
                continue
            tool_name = str(step.get("tool", "")).strip()
            if tool_name:
                tool_calls += 1
                tool_sequence.append(tool_name)
            if self._step_is_bad(step):
                bad_steps += 1

        if tool_calls == 0:
            return None

        bad_ratio = bad_steps / len(trace)
        if bad_ratio > CRYSTALLIZE_MAX_BAD_RATIO:
            return None

        skill_name = self._derive_skill_name(task_summary)
        if not skill_name:
            return None

        # Dedupe against existing proposals so operators aren't flooded
        # with redundant crystallizations.
        if self.proposal_exists(skill_name):
            return None

        approach = self._derive_approach(tool_sequence)
        proposal = SkillProposal(
            name=skill_name,
            description=(
                f"Crystallized skill distilled from a {len(trace)}-step "
                f"execution trace: {task_summary.strip()}."
            ),
            trigger_condition=(
                f"Reuse when a task resembles: {task_summary.strip()}."
            ),
            approach=approach,
            failure_pattern={
                "task_summary": task_summary.strip()[:500],
                "trace_length": len(trace),
                "tool_calls": tool_calls,
                "bad_step_ratio": round(bad_ratio, 3),
                "tool_sequence": tool_sequence,
                "count": 1,
            },
            reason="crystallized_from_trace",
        )

        # Optional lineage hook (gated by the temporal-knowledge flag).
        if skill_version_dag_enabled and skill_version_store is not None:
            record_fn = getattr(
                skill_version_store, "record_skill_version", None
            )
            if record_fn is not None:
                try:
                    record_fn(
                        skill_name=skill_name,
                        body_or_diff=self.generate_skill_md(proposal),
                        parent_versions=(),
                        created_by_trigger="crystallized_from_trace",
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning(
                        "crystallize_from_trace: lineage hook failed: %s",
                        exc,
                    )

        return proposal

    @staticmethod
    def _step_is_bad(step: dict[str, Any]) -> bool:
        """Return True when a trace step looks like a retry or error.

        Signals (any one is enough):
            * ``step["error"]`` truthy
            * ``step["status"]`` containing "fail" / "error" / "retry"
            * ``step["retry"]`` truthy or ``step["retry_count"] > 0``
            * ``step["output"]`` is a dict with a truthy ``error`` key
        """
        if step.get("error"):
            return True
        status = str(step.get("status", "")).lower()
        for token in _BAD_STEP_TOKENS:
            if token in status:
                return True
        if step.get("retry"):
            return True
        try:
            if int(step.get("retry_count", 0) or 0) > 0:
                return True
        except (TypeError, ValueError):
            pass
        output = step.get("output")
        if isinstance(output, dict) and output.get("error"):
            return True
        return False

    @staticmethod
    def _derive_skill_name(task_summary: str) -> str:
        """Slugify a task summary into a stable skill name.

        Lower-cases, replaces non-alphanumeric runs with hyphens,
        strips leading/trailing hyphens, caps length at 60 chars, and
        suffixes ``-crystallized`` so the source of the skill is
        obvious in the proposal store.
        """
        slug_chars: list[str] = []
        prev_dash = False
        for ch in task_summary.lower():
            if ch.isalnum():
                slug_chars.append(ch)
                prev_dash = False
            elif not prev_dash:
                slug_chars.append("-")
                prev_dash = True
        slug = "".join(slug_chars).strip("-")
        if not slug:
            return ""
        slug = slug[:60].rstrip("-")
        return f"{slug}-crystallized"

    @staticmethod
    def _derive_approach(tool_sequence: list[str]) -> list[str]:
        """Render the canonical tool sequence as numbered approach steps."""
        if not tool_sequence:
            return [
                "Review the source trace to confirm the working approach.",
                "Replay the recorded steps in order.",
                "Verify the success signal before declaring completion.",
            ]
        steps = [
            f"Invoke `{tool}` with the same shape as the source trace."
            for tool in tool_sequence
        ]
        steps.append(
            "Verify the success signal before declaring completion."
        )
        return steps

    # -- Sprint 07.04 (#1033) — markdown-skill convention -------------------
    #
    # Two-method pair: ``persist_skill_to_markdown`` writes a proposal to
    # ``<base_dir>/<domain>/<name>.md`` and dual-writes the path back into
    # the SQLite ``skill_proposals.markdown_path`` column.
    # ``discover_markdown_skills`` walks the same tree, skips invalid
    # files (with a WARNING log), and returns frozen ``MarkdownSkill``
    # records for downstream consumers (Sprint 07.05 wires this into
    # ``tool_shed``). Concept-only port of browser-harness's pattern
    # (MIT, paraphrased — no source copied).

    def persist_skill_to_markdown(
        self,
        proposal: SkillProposal,
        *,
        base_dir: Path | None = None,
    ) -> Path:
        """Write the proposal's markdown body to a domain-keyed file.

        Returns the absolute path to the written file. The write is
        atomic via ``<file>.tmp`` rename so an interrupted process
        leaves either the previous version or the new one — never a
        partial file.

        Side effect: when ``proposal`` is already persisted in the DB
        (i.e. ``proposal_exists(proposal.name)`` is True) the
        ``markdown_path`` column is populated with the written path.
        Sprint 07.04 spec calls this the "dual-write" option. New
        proposals not yet in the DB are written to disk only — the
        caller can follow up with ``create_proposal`` and a separate
        update if they want the link recorded.
        """
        if not isinstance(proposal, SkillProposal):
            raise TypeError("proposal must be a SkillProposal")
        if not proposal.name:
            raise ValueError("proposal.name must not be empty")

        target_root = Path(base_dir) if base_dir else DEFAULT_MARKDOWN_SKILLS_DIR
        domain = self._extract_domain(proposal)
        safe_name = self._sanitize_skill_name(proposal.name)
        if not safe_name:
            raise ValueError(
                f"proposal.name {proposal.name!r} sanitizes to empty"
            )

        target_dir = target_root / domain
        target_dir.mkdir(parents=True, exist_ok=True)

        body = self.generate_skill_md(proposal)
        target_path = target_dir / f"{safe_name}.md"
        tmp_path = target_dir / f"{safe_name}.md.tmp"

        # Write to a sibling tmp file then rename atomically. The rename
        # itself is the commit; if the process dies mid-write only the
        # tmp file lingers and is overwritten on the next attempt.
        tmp_path.write_text(body, encoding="utf-8")
        tmp_path.replace(target_path)

        # Dual-write the path into the proposal row when it exists.
        self._record_markdown_path(proposal.name, target_path)
        return target_path

    def discover_markdown_skills(
        self,
        base_dir: Path | None = None,
    ) -> list[MarkdownSkill]:
        """Walk ``base_dir`` for ``<domain>/<name>.md`` files.

        Returns frozen ``MarkdownSkill`` records for every file that
        passes :meth:`validate_skill`. Invalid files are skipped with
        a WARNING log so the bridge boot never aborts on a single
        malformed skill. Missing directories are tolerated and yield
        an empty list.

        YAML frontmatter at the top of a file (delimited by lines of
        exactly ``---``) is parsed when ``yaml`` is importable. When
        the library is not present, frontmatter is silently treated as
        body content and ``frontmatter`` is left empty — callers that
        require structured frontmatter should install ``pyyaml`` (or
        ``python-frontmatter``).
        """
        target_root = Path(base_dir) if base_dir else DEFAULT_MARKDOWN_SKILLS_DIR
        if not target_root.is_dir():
            return []

        results: list[MarkdownSkill] = []
        for md_path in sorted(target_root.glob("*/*.md")):
            try:
                raw = md_path.read_text(encoding="utf-8")
            except OSError as exc:  # pragma: no cover - defensive
                log.warning("discover_markdown_skills: %s unreadable: %s", md_path, exc)
                continue

            frontmatter, body = self._split_frontmatter(raw)
            validation = self.validate_skill(body)
            if not validation.passed:
                log.warning(
                    "discover_markdown_skills: skipping %s (invalid: %s)",
                    md_path,
                    "; ".join(validation.errors),
                )
                continue

            results.append(
                MarkdownSkill(
                    path=md_path,
                    domain=md_path.parent.name,
                    name=md_path.stem,
                    body=raw,
                    frontmatter=frontmatter,
                )
            )
        return results

    def _record_markdown_path(self, name: str, path: Path) -> None:
        """Populate ``skill_proposals.markdown_path`` when the row exists."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE skill_proposals SET markdown_path = ?, "
                "updated_at = datetime('now') WHERE name = ?",
                (str(path), name),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _extract_domain(proposal: SkillProposal) -> str:
        """Pull a domain hint out of ``failure_pattern`` (default 'general')."""
        domain = ""
        if isinstance(proposal.failure_pattern, dict):
            raw = proposal.failure_pattern.get("domain")
            if isinstance(raw, str):
                domain = raw.strip()
        if not domain:
            return _MARKDOWN_SKILL_DOMAIN_DEFAULT
        # Same sanitization rules as the skill name; domains live in
        # filesystem path segments and must stay simple.
        return SkillEvolutionEngine._sanitize_skill_name(domain) or _MARKDOWN_SKILL_DOMAIN_DEFAULT

    @staticmethod
    def _sanitize_skill_name(name: str) -> str:
        """Lowercase + collapse whitespace/slashes → ``-``, strip junk.

        Documented in the module docstring. Kept ASCII-only so files
        round-trip cleanly through git on case-insensitive filesystems
        (macOS) and Windows.
        """
        if not isinstance(name, str):
            return ""
        out: list[str] = []
        prev_dash = False
        for ch in name.lower():
            if ch.isalnum() or ch in ("-", "_"):
                out.append(ch)
                prev_dash = ch == "-"
                continue
            # whitespace / slash / anything else collapses to a single dash
            if not prev_dash:
                out.append("-")
                prev_dash = True
        slug = "".join(out).strip("-_")
        return slug

    @staticmethod
    def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
        """Return ``(frontmatter_dict, full_markdown_body)``.

        The body returned is the *full* original text (including the
        frontmatter block) so consumers can re-validate against the
        same content the operator sees. When YAML parsing is
        unavailable, frontmatter is empty and the file is treated as
        plain markdown.
        """
        if not raw.startswith("---\n"):
            return {}, raw

        # Find the closing fence.
        rest = raw[4:]
        end = rest.find("\n---\n")
        if end == -1:
            return {}, raw
        frontmatter_block = rest[:end]

        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            return {}, raw

        try:
            parsed = yaml.safe_load(frontmatter_block)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("discover_markdown_skills: frontmatter parse failed: %s", exc)
            return {}, raw

        if not isinstance(parsed, dict):
            return {}, raw
        return parsed, raw

    @staticmethod
    def _row_to_proposal(row: tuple) -> SkillProposal:
        approach = []
        try:
            approach = json.loads(row[4]) if row[4] else []
        except (json.JSONDecodeError, TypeError):
            pass
        fp = {}
        try:
            fp = json.loads(row[5]) if row[5] else {}
        except (json.JSONDecodeError, TypeError):
            pass
        return SkillProposal(
            id=row[0],
            name=row[1],
            description=row[2],
            trigger_condition=row[3],
            approach=approach,
            failure_pattern=fp,
            score=row[6],
            status=row[7],
            tier=row[8],
            reject_reason=row[9] or "",
            created_at=row[10] or "",
        )
