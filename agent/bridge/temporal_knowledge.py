"""Version-controlled knowledge entries with full change history and temporal queries.

Production .put() caller is planned for Phase 5 Team Protocol directive persistence
(issues #661-#668 in the `blocked-by-activation` label set). This module is
load-bearing for that future work; do not delete. Until Phase 5 activates, the
`temporal_kb` table remains schema-only.

The /knowledge command (commands.py) is the only production reader.

Skill version DAG (Sprint 03.07, issue #997)
============================================

Concept-only port of OpenSpace's skill-version-graph idea (MIT license,
paraphrased — no source copied verbatim). Two sibling tables track skill
evolution as a directed acyclic graph:

* ``skill_dag_node`` — one row per (skill_name, version) with the body or
  diff blob, the diff format, and the trigger that produced this version.
* ``skill_dag_edge`` — parent->child edges; multiple parents per child
  expresses a *merge* (e.g. v4 synthesized from v2 + v3).

The shape is intentionally a sibling of ``knowledge_history``: it does not
extend that table because skill versions are *artifacts with lineage*, not
key-value entries with monotonic versions. Plan 07 (Sprint 07.07) will
extend the same surface with EvolutionEvent storage.

The ``skill_version_dag_enabled`` feature flag on ``BridgeConfig`` gates
*active* writes from skill_evolution (Plan 07 callers); the schema
migration always runs so the tables are present, and the read API
(:meth:`get_skill_lineage`, :meth:`get_skill_at_version`) is always
callable.

Memory tier hierarchy (Sprint 03.04, issue #993)
================================================

Concept-only port of GenericAgent's tiered-memory taxonomy (MIT license,
paraphrased — no source copied verbatim). Every row in ``knowledge_history``
carries an L0-L4 tier label that captures *altitude* rather than recency:

* ``L0`` — Ephemeral / session-scratch. Purgeable end-of-session.
* ``L1`` — Recent working memory. Last few sessions; decays fast.
* ``L2`` — Consolidated long-term knowledge (DEFAULT for new rows).
* ``L3`` — Canonical reference. Operator-pinned or doctrine-grade.
* ``L4`` — Archive. Cold, retained for audit but not surfaced by default.

Tier assignment defaults to ``L2`` for new ``put()`` calls — operator or agent
moves entries up via :meth:`TemporalKnowledgeStore.promote` and back down via
:meth:`TemporalKnowledgeStore.demote`. Promotion semantics:

* Promote/demote write a ``rollback``-flavoured ChangeRecord to preserve the
  audit trail (see :func:`format_timeline`).
* The pure-function helpers :func:`assign_tier` and :func:`promote_tier` are
  module-level utilities for plan-05 capture-side classification — they do not
  touch the DB.

Existing rows from before this migration will have ``tier IS NULL``; sprint
03.04b (issue #994) backfills them to ``L2``. This module treats NULL as a
queryable tier value (equivalent to "untiered") until the backfill ships.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


log = logging.getLogger(__name__)

# -- Temporal tier vocabulary (Sprint 03.04; renamed from MemoryTier in Mem-3.5 #1864) --

TemporalTier = Literal["L0", "L1", "L2", "L3", "L4"]
"""L0-L4 altitude labels. See module docstring for tier definitions.

Sprint Mem-3.5 (#1864) renamed this from ``MemoryTier`` to disambiguate
from ``bridge.memory_tiers.MemoryTier`` (the canonical PREFERENCE/
DECISION/CONTEXT enum from the memory-tier-architecture epic). The
two carry different vocabularies; the rename eliminates the lexical
shadow.
"""
# Back-compat alias — kept until external callers migrate. None today
# (the alias was strictly module-local), but the alias is cheap and lets
# any straggler import survive without an import-time error.
MemoryTier = TemporalTier

VALID_TIERS: tuple[str, ...] = ("L0", "L1", "L2", "L3", "L4")
"""Ordered tuple of valid tier strings; index doubles as numeric altitude."""

DEFAULT_TIER: TemporalTier = "L2"
"""Tier assigned to new rows when no explicit tier is provided."""

# Promotion-signal vocabulary for :func:`promote_tier`. Keeping this as a
# module-level constant lets callers (plan-05 capture-side) feature-test
# without importing private symbols.
PROMOTION_SIGNALS: frozenset[str] = frozenset(
    {
        "referenced_again",
        "operator_pinned",
        "consolidation_passed",
    }
)


def assign_tier(content: str, importance: float, age_seconds: float) -> TemporalTier:
    """Pure-function tier classifier for new memory rows.

    Thresholds (kept conservative — operator can promote afterwards):

    * ``importance >= 0.9`` → ``L3`` (canonical reference)
    * ``importance >= 0.6`` and ``age_seconds <= 86400`` → ``L1`` (recent working)
    * ``importance >= 0.3`` → ``L2`` (consolidated; the default)
    * ``importance < 0.3`` and ``age_seconds <= 3600`` → ``L0`` (ephemeral)
    * else → ``L4`` (low-importance + stale → archive)

    ``content`` is reserved for future heuristics (length / pattern weighting);
    today it only participates by being non-empty (an empty string forces L0).
    """
    if not content:
        return "L0"
    if importance >= 0.9:
        return "L3"
    if importance >= 0.6 and age_seconds <= 86400:
        return "L1"
    if importance >= 0.3:
        return "L2"
    if age_seconds <= 3600:
        return "L0"
    return "L4"


def promote_tier(current: TemporalTier, signal: str) -> TemporalTier:
    """Pure-function tier promoter responding to a named signal.

    * ``"referenced_again"`` — bump one tier up (L0 -> L1, ..., L3 -> L4 capped).
      L4 stays at L4 (already archive — re-reference doesn't push it further).
    * ``"operator_pinned"`` — jump to ``L3`` (canonical reference).
    * ``"consolidation_passed"`` — bump to at least ``L2`` if currently L0/L1.
    * Unknown signal — return ``current`` unchanged (no-op, never raises).
    """
    if signal == "operator_pinned":
        return "L3"
    if signal == "referenced_again":
        # Bump one rank, but L4 is the ceiling for plain re-reference.
        idx = VALID_TIERS.index(current)
        if current == "L4":
            return "L4"
        return VALID_TIERS[min(idx + 1, len(VALID_TIERS) - 1)]  # type: ignore[return-value]
    if signal == "consolidation_passed":
        if current in ("L0", "L1"):
            return "L2"
        return current
    return current


def backfill_default_tier(
    connection: sqlite3.Connection, default: TemporalTier = DEFAULT_TIER
) -> int:
    """Idempotently set ``temporal_tier`` to ``default`` for NULL rows.

    Sprint 03.04b (#994). Closes the gap left by the 03.04 ``ALTER TABLE ADD
    COLUMN temporal_tier TEXT DEFAULT 'L2'`` migration. On modern SQLite
    (>= 3.35) the DEFAULT clause auto-propagates to pre-existing rows so this
    helper is typically a no-op (returns 0). On older SQLite, pre-migration
    rows have ``temporal_tier IS NULL`` and this UPDATE backfills them.

    Mem-3.5 (#1864): probes for both the legacy ``tier`` column and the new
    ``temporal_tier`` column. If only the legacy column is present the rename
    has not yet run (called outside the normal init order); log + return 0.

    Returns the number of rows updated. Re-running on the same DB returns 0
    (idempotent).
    """
    if default not in VALID_TIERS:
        raise ValueError(f"backfill_default_tier: invalid tier {default!r}")

    cols = {row[1] for row in connection.execute("PRAGMA table_info(knowledge_history)")}
    if "temporal_tier" not in cols:
        log.warning(
            "temporal_knowledge: backfill_default_tier skipped — "
            "knowledge_history.temporal_tier column not present "
            "(run _apply_tier_migration first)"
        )
        return 0

    cursor = connection.execute(
        "UPDATE knowledge_history SET temporal_tier = ? WHERE temporal_tier IS NULL",
        (default,)
    )
    updated = cursor.rowcount or 0
    if updated:
        log.info(
            "temporal_knowledge: backfill_default_tier set tier=%s on %d row(s)",
            default,
            updated,
        )
    return updated


@dataclass
class VersionedEntry:
    """A single versioned knowledge entry."""

    key: str
    value: str
    version: int
    valid_from: str  # ISO timestamp
    valid_to: str | None  # ISO timestamp or None if current
    change_type: str  # "create" | "update" | "delete" | "rollback" | "promote" | "demote"
    reason: str
    changed_by: str  # "agent" | "operator" | "system"
    # Sprint 03.04 — L0-L4 tier label. Defaults to None so existing callers
    # constructing VersionedEntry positionally are not broken; the SQLite row
    # default ("L2") flows through `_row_to_entry` for new rows, and existing
    # rows from before the migration return None until 03.04b backfills them.
    tier: TemporalTier | None = None


@dataclass
class ChangeRecord:
    """A record of a single change to a knowledge entry."""

    key: str
    old_value: str | None
    new_value: str | None
    version: int
    timestamp: str  # ISO timestamp
    change_type: str  # "create" | "update" | "delete" | "rollback"
    reason: str
    changed_by: str  # "agent" | "operator" | "system"


# -- Sprint 03.07 — Skill version DAG vocabulary --

DiffKind = Literal["full", "unified", "json-patch"]
"""How ``SkillVersion.body_or_diff`` is encoded."""

VALID_DIFF_KINDS: tuple[str, ...] = ("full", "unified", "json-patch")

SkillEdgeType = Literal["derived_from", "merged_from"]
"""Edge semantics in the skill DAG.

* ``derived_from`` — single-parent linear evolution (vN -> vN+1).
* ``merged_from`` — multi-parent merge (e.g. v4 absorbs v2 + v3).
"""

VALID_EDGE_TYPES: tuple[str, ...] = ("derived_from", "merged_from")

SkillTrigger = Literal[
    "post_exec",
    "tool_degradation",
    "periodic",
    "crystallized",
    "legacy",
    "manual",
]
"""What caused this version to be recorded.

``legacy`` is reserved for the v0 backfill of pre-existing skill_proposals
(see :meth:`TemporalKnowledgeStore.backfill_skill_proposals_to_v0`).
"""


@dataclass(frozen=True)
class SkillVersion:
    """A single node in the skill version DAG.

    Frozen so callers cannot mutate stored rows; refresh by re-reading from
    the store. ``parent_versions`` is reconstructed from the edge table when
    the node is materialised — it is not stored on the node row itself.
    """

    id: int
    skill_name: str
    version: int
    body_or_diff: str
    diff_kind: DiffKind | None
    created_at: str  # ISO timestamp
    created_by_trigger: str | None
    parent_versions: tuple[int, ...] = ()


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS knowledge_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT,
    version INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    change_type TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    changed_by TEXT NOT NULL DEFAULT 'agent',
    expires_at TEXT,
    -- temporal_tier (renamed from `tier` in Mem-3.5 #1864 to disambiguate
    -- from the canonical `bridge.memory_tiers.MemoryTier` enum from the
    -- memory-tier-architecture epic). Carries L0-L4 strings — different
    -- vocabulary from the canonical PREFERENCE/DECISION/CONTEXT enum.
    temporal_tier TEXT DEFAULT 'L2'
);

CREATE INDEX IF NOT EXISTS idx_kh_key ON knowledge_history(key);
CREATE INDEX IF NOT EXISTS idx_kh_key_version ON knowledge_history(key, version);
CREATE INDEX IF NOT EXISTS idx_kh_key_valid ON knowledge_history(key, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_kh_expires ON knowledge_history(expires_at);
"""
# NOTE: idx_kh_tier is created inside `_apply_tier_migration` (after the
# ALTER TABLE adds the column on legacy DBs); attempting to create it here
# would fail on databases predating Sprint 03.04.


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class TemporalKnowledgeStore:
    """SQLite-backed store for version-controlled knowledge entries.

    Thread-safe: each public method acquires a connection from a shared
    serialized SQLite database (using check_same_thread=False with an
    explicit lock for write operations).
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            self._db_path = ":memory:"
            self._is_memory = True
        else:
            self._db_path = str(db_path)
            self._is_memory = False
        self._lock = threading.Lock()
        # For in-memory DBs keep a persistent connection so the DB survives
        # across calls (each sqlite3.connect(":memory:") creates a *new* DB).
        self._persistent_conn: sqlite3.Connection | None = None
        self._init_schema()

    # -- internal helpers --

    def _connect(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._persistent_conn is None:
                conn = sqlite3.connect(":memory:", check_same_thread=False)
                conn.row_factory = sqlite3.Row
                self._persistent_conn = conn
            return self._persistent_conn
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _release(self, conn: sqlite3.Connection) -> None:
        """Close a file-backed connection; no-op for in-memory persistent conn."""
        if not self._is_memory:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                self._apply_tier_migration(conn)
                self._apply_skill_dag_migration(conn)
                conn.commit()
            finally:
                self._release(conn)

    @staticmethod
    def _apply_tier_migration(conn: sqlite3.Connection) -> None:
        """Idempotent migration for the L0-L4 temporal_tier column.

        Three DB ages handled:

        1. **Fresh DB** — ``_SCHEMA`` already created ``temporal_tier``.
           This method is a no-op (apart from the idempotent backfill +
           index creation).
        2. **Legacy DB with ``tier`` column** (created by Sprint 03.04
           PR #993, before Mem-3.5 #1864 renamed the column). RENAME
           ``tier`` → ``temporal_tier`` via ``ALTER TABLE ... RENAME
           COLUMN`` (SQLite ≥ 3.25). Drop the old ``idx_kh_tier`` index
           if present so the new ``idx_kh_temporal_tier`` can replace it.
        3. **Ancient DB without either column** (pre-03.04). ADD COLUMN
           ``temporal_tier`` directly.

        Existing rows in case (3) receive ``NULL`` for ``temporal_tier``
        (SQLite ALTER ADD COLUMN does not retroactively populate the
        DEFAULT for pre-existing rows on older versions). Sprint 03.04b
        (#994) backfills NULLs to L2.
        """
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(knowledge_history)").fetchall()
        }
        # Mem-3.5 (#1864): rename legacy `tier` → `temporal_tier`.
        if "tier" in cols and "temporal_tier" not in cols:
            try:
                conn.execute(
                    "ALTER TABLE knowledge_history RENAME COLUMN tier TO temporal_tier"
                )
                log.info(
                    "temporal_knowledge: applied Mem-3.5 column rename "
                    "(tier → temporal_tier)"
                )
                # Drop the legacy index name; the new one is created below.
                conn.execute("DROP INDEX IF EXISTS idx_kh_tier")
            except sqlite3.OperationalError as exc:  # pragma: no cover - defensive
                log.warning(
                    "temporal_knowledge: Mem-3.5 rename skipped: %s", exc
                )
        elif "tier" not in cols and "temporal_tier" not in cols:
            # Pre-03.04 ancient DB — add the column directly under the new name.
            try:
                conn.execute(
                    "ALTER TABLE knowledge_history ADD COLUMN temporal_tier TEXT DEFAULT 'L2'"
                )
                log.info(
                    "temporal_knowledge: applied 03.04 + Mem-3.5 combined "
                    "temporal_tier-column migration"
                )
            except sqlite3.OperationalError as exc:  # pragma: no cover - defensive
                log.warning(
                    "temporal_knowledge: temporal_tier migration skipped: %s", exc
                )
        # Sprint 03.04b (#994): backfill any pre-existing NULL temporal_tier
        # rows. Idempotent — safe to re-run every init.
        backfill_default_tier(conn)
        # Index creation is idempotent and safe to run every init — it fires
        # only when the column was just added or already present.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_kh_temporal_tier ON knowledge_history(temporal_tier)"
        )

    @staticmethod
    def _apply_skill_dag_migration(conn: sqlite3.Connection) -> None:
        """Idempotent CREATE for the Sprint 03.07 skill version DAG tables.

        Two sibling tables (NOT extensions of ``knowledge_history``):

        * ``skill_dag_node`` — the (skill_name, version) artifact + body/diff
        * ``skill_dag_edge`` — parent->child lineage; multi-parent expresses
          a merge

        Both use ``CREATE TABLE IF NOT EXISTS`` so re-running on an already
        migrated database is a no-op. ON DELETE RESTRICT preserves history:
        a node referenced by an edge cannot be silently removed; archival
        moves to L4 instead (operator-driven, not auto).
        """
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_dag_node (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT NOT NULL,
                version INTEGER NOT NULL,
                body_or_diff TEXT NOT NULL,
                diff_kind TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_by_trigger TEXT,
                UNIQUE(skill_name, version)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_dag_name ON skill_dag_node(skill_name)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_dag_edge (
                parent_id INTEGER NOT NULL,
                child_id INTEGER NOT NULL,
                edge_type TEXT NOT NULL,
                diff_summary TEXT,
                PRIMARY KEY (parent_id, child_id),
                FOREIGN KEY (parent_id) REFERENCES skill_dag_node(id) ON DELETE RESTRICT,
                FOREIGN KEY (child_id) REFERENCES skill_dag_node(id) ON DELETE RESTRICT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_dag_edge_child "
            "ON skill_dag_edge(child_id)"
        )

    def _row_to_entry(self, row: sqlite3.Row) -> VersionedEntry:
        # Older rows (pre-Sprint-03.04 schema) do not have a "tier" key in
        # the row mapping; in newer schemas, the column may still be NULL
        # for unmigrated rows. Both cases collapse to ``tier=None``.
        try:
            tier_value = row["temporal_tier"]
        except (IndexError, KeyError):
            tier_value = None
        return VersionedEntry(
            key=row["key"],
            value=row["value"],
            version=row["version"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            change_type=row["change_type"],
            reason=row["reason"],
            changed_by=row["changed_by"],
            tier=tier_value,
        )

    # -- public API --

    def put(self, key: str, value: str, reason: str = "", changed_by: str = "agent") -> VersionedEntry:
        """Create or update a knowledge entry.

        If the key already exists (with valid_to IS NULL), the previous version's
        valid_to is set to now and a new version is inserted.  Returns the new entry.
        """
        now = _now_iso()

        with self._lock:
            conn = self._connect()
            try:
                # Find current version
                cur = conn.execute(
                    "SELECT * FROM knowledge_history WHERE key = ? AND valid_to IS NULL ORDER BY version DESC LIMIT 1",
                    (key,),
                )
                current = cur.fetchone()

                if current is None:
                    version = 1
                    change_type = "create"
                else:
                    version = current["version"] + 1
                    change_type = "update"
                    # Close out the previous version
                    conn.execute(
                        "UPDATE knowledge_history SET valid_to = ? WHERE id = ?",
                        (now, current["id"]),
                    )

                # Sprint 03.04 — preserve tier across updates: when a key already
                # exists, the new version inherits the previous version's tier
                # (or DEFAULT_TIER for fresh creates / migrated NULL rows).
                inherited_tier: str = DEFAULT_TIER
                if current is not None:
                    try:
                        prev_tier = current["temporal_tier"]
                    except (IndexError, KeyError):
                        prev_tier = None
                    if prev_tier:
                        inherited_tier = prev_tier

                conn.execute(
                    "INSERT INTO knowledge_history (key, value, version, valid_from, valid_to, change_type, reason, changed_by, temporal_tier) "
                    "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                    (key, value, version, now, change_type, reason, changed_by, inherited_tier),
                )
                conn.commit()

                entry = VersionedEntry(
                    key=key,
                    value=value,
                    version=version,
                    valid_from=now,
                    valid_to=None,
                    change_type=change_type,
                    reason=reason,
                    changed_by=changed_by,
                    tier=inherited_tier,
                )
                log.debug("put key=%s version=%d change_type=%s tier=%s", key, version, change_type, inherited_tier)
                # D2.3 — emit call ready here; deferred until production caller of put() exists.
                # When wired: _emit_write_receipt(MemoryWriteReceipt.now(
                #     subsystem="temporal_knowledge", op=change_type, key=key,
                #     payload_bytes=len(value or ""), actor=changed_by or "agent",
                #     notes=(reason or "")[:200]))
                return entry
            finally:
                self._release(conn)

    def get(self, key: str, metrics: object | None = None) -> VersionedEntry | None:
        """Get the current (valid_to IS NULL) version of a key.

        Increments the ``temporal_kb_queries`` counter (#22).
        """
        # Increment query counter on every KB get() (#22)
        if metrics is not None:
            try:
                from .metrics import TEMPORAL_KB_QUERIES
                metrics.increment(TEMPORAL_KB_QUERIES)
            except Exception:
                pass
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT * FROM knowledge_history WHERE key = ? AND valid_to IS NULL AND change_type != 'delete' "
                "ORDER BY version DESC LIMIT 1",
                (key,),
            )
            row = cur.fetchone()
            return self._row_to_entry(row) if row else None
        finally:
            self._release(conn)

    def get_at(self, key: str, timestamp: str) -> VersionedEntry | None:
        """Temporal query: what was the value of key at a specific point in time?

        Returns the version that was active at *timestamp* (valid_from <= timestamp
        and either valid_to IS NULL or valid_to > timestamp), excluding deletes.
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT * FROM knowledge_history "
                "WHERE key = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?) "
                "AND change_type != 'delete' "
                "ORDER BY version DESC LIMIT 1",
                (key, timestamp, timestamp),
            )
            row = cur.fetchone()
            return self._row_to_entry(row) if row else None
        finally:
            self._release(conn)

    def get_history(self, key: str) -> list[ChangeRecord]:
        """Return full change timeline for a key, ordered by version ascending."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT * FROM knowledge_history WHERE key = ? ORDER BY version ASC",
                (key,),
            )
            rows = cur.fetchall()

            records: list[ChangeRecord] = []
            prev_value: str | None = None
            for row in rows:
                records.append(
                    ChangeRecord(
                        key=row["key"],
                        old_value=prev_value,
                        new_value=row["value"],
                        version=row["version"],
                        timestamp=row["valid_from"],
                        change_type=row["change_type"],
                        reason=row["reason"],
                        changed_by=row["changed_by"],
                    )
                )
                prev_value = row["value"]

            return records
        finally:
            self._release(conn)

    def delete(self, key: str, reason: str = "", changed_by: str = "agent") -> bool:
        """Soft-delete a key: set valid_to on the current version and record a delete change.

        Returns True if the key existed and was deleted, False otherwise.
        """
        now = _now_iso()

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT * FROM knowledge_history WHERE key = ? AND valid_to IS NULL AND change_type != 'delete' "
                    "ORDER BY version DESC LIMIT 1",
                    (key,),
                )
                current = cur.fetchone()

                if current is None:
                    return False

                new_version = current["version"] + 1

                # Close out current version
                conn.execute(
                    "UPDATE knowledge_history SET valid_to = ? WHERE id = ?",
                    (now, current["id"]),
                )

                # Insert delete record
                # Sprint 03.04 — carry forward the tier on the delete record
                # so historical timeline queries don't drop tier metadata.
                try:
                    prev_tier = current["temporal_tier"]
                except (IndexError, KeyError):
                    prev_tier = None
                conn.execute(
                    "INSERT INTO knowledge_history (key, value, version, valid_from, valid_to, change_type, reason, changed_by, temporal_tier) "
                    "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)",
                    (key, new_version, now, now, "delete", reason, changed_by, prev_tier),
                )
                conn.commit()
                log.debug("deleted key=%s at version=%d", key, new_version)
                return True
            finally:
                self._release(conn)

    # -- Sprint 03.04: L0-L4 tier API --

    def tier(self, key: str) -> TemporalTier | None:
        """Return the current tier for ``key`` (``DEFAULT_TIER`` for new rows).

        Returns ``None`` if the key has no active version (deleted or never
        created), or if the row predates the 03.04 migration and has not yet
        been backfilled by 03.04b.
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT temporal_tier FROM knowledge_history "
                "WHERE key = ? AND valid_to IS NULL AND change_type != 'delete' "
                "ORDER BY version DESC LIMIT 1",
                (key,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            try:
                value = row["temporal_tier"]
            except (IndexError, KeyError):
                return None
            return value  # type: ignore[no-any-return]
        finally:
            self._release(conn)

    def set_tier(
        self,
        key: str,
        target_tier: TemporalTier,
        reason: str = "",
        changed_by: str = "agent",
    ) -> VersionedEntry | None:
        """Update the tier on the current active version of ``key`` in-place.

        Unlike :meth:`promote` / :meth:`demote`, this does not write a history
        record — it mutates the current row's ``tier`` column. Returns the
        refreshed VersionedEntry, or ``None`` if the key has no active version.

        Use :meth:`promote` / :meth:`demote` for auditable tier moves; this
        helper is for capture-side classifiers (e.g. plan-05) that set the
        initial tier right after the original ``put()``.
        """
        if target_tier not in VALID_TIERS:
            raise ValueError(
                f"Invalid tier {target_tier!r}; expected one of {VALID_TIERS}"
            )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE knowledge_history SET temporal_tier = ? "
                    "WHERE key = ? AND valid_to IS NULL AND change_type != 'delete'",
                    (target_tier, key),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None
                log.debug("set_tier key=%s tier=%s reason=%s", key, target_tier, reason)
            finally:
                self._release(conn)
        return self.get(key)

    def _promote_or_demote(
        self,
        key: str,
        target_tier: TemporalTier,
        reason: str,
        change_type: str,
        changed_by: str,
    ) -> VersionedEntry | None:
        """Shared engine for ``promote``/``demote`` — writes a new version.

        Closes out the current version, inserts a new row that mirrors the
        current value but carries the new tier and a ``promote``/``demote``
        change_type. Returns the new VersionedEntry, or ``None`` if there is
        no active version to operate on.
        """
        if target_tier not in VALID_TIERS:
            raise ValueError(
                f"Invalid tier {target_tier!r}; expected one of {VALID_TIERS}"
            )
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT * FROM knowledge_history "
                    "WHERE key = ? AND valid_to IS NULL AND change_type != 'delete' "
                    "ORDER BY version DESC LIMIT 1",
                    (key,),
                )
                current = cur.fetchone()
                if current is None:
                    return None

                new_version = current["version"] + 1
                conn.execute(
                    "UPDATE knowledge_history SET valid_to = ? WHERE id = ?",
                    (now, current["id"]),
                )
                conn.execute(
                    "INSERT INTO knowledge_history "
                    "(key, value, version, valid_from, valid_to, change_type, reason, changed_by, temporal_tier) "
                    "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                    (
                        key,
                        current["value"],
                        new_version,
                        now,
                        change_type,
                        reason,
                        changed_by,
                        target_tier,
                    ),
                )
                conn.commit()
                entry = VersionedEntry(
                    key=key,
                    value=current["value"],
                    version=new_version,
                    valid_from=now,
                    valid_to=None,
                    change_type=change_type,
                    reason=reason,
                    changed_by=changed_by,
                    tier=target_tier,
                )
                log.debug(
                    "%s key=%s new_version=%d tier=%s",
                    change_type,
                    key,
                    new_version,
                    target_tier,
                )
                return entry
            finally:
                self._release(conn)

    def promote(
        self,
        key: str,
        target_tier: TemporalTier,
        reason: str = "",
        changed_by: str = "agent",
    ) -> VersionedEntry | None:
        """Promote ``key`` to a higher tier, writing an auditable history record.

        Returns the new VersionedEntry (with ``change_type='promote'``), or
        ``None`` if there is no active version. Raises ``ValueError`` for
        invalid ``target_tier``. The promote is reversible via
        :meth:`demote` or :meth:`rollback` to a prior version.
        """
        return self._promote_or_demote(
            key, target_tier, reason, change_type="promote", changed_by=changed_by
        )

    def demote(
        self,
        key: str,
        target_tier: TemporalTier,
        reason: str = "",
        changed_by: str = "agent",
    ) -> VersionedEntry | None:
        """Demote ``key`` to a lower tier, writing an auditable history record.

        Mirror of :meth:`promote` with ``change_type='demote'``.
        """
        return self._promote_or_demote(
            key, target_tier, reason, change_type="demote", changed_by=changed_by
        )

    def query_by_tier(self, target_tier: TemporalTier | None) -> list[VersionedEntry]:
        """Return all *active* (non-deleted, ``valid_to IS NULL``) entries at ``target_tier``.

        Pass ``None`` to fetch entries with NULL tier — useful for finding rows
        that predate the 03.04 migration and still need 03.04b backfill.
        """
        if target_tier is not None and target_tier not in VALID_TIERS:
            raise ValueError(
                f"Invalid tier {target_tier!r}; expected one of {VALID_TIERS} or None"
            )
        conn = self._connect()
        try:
            if target_tier is None:
                cur = conn.execute(
                    "SELECT * FROM knowledge_history "
                    "WHERE temporal_tier IS NULL AND valid_to IS NULL AND change_type != 'delete' "
                    "ORDER BY key",
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM knowledge_history "
                    "WHERE temporal_tier = ? AND valid_to IS NULL AND change_type != 'delete' "
                    "ORDER BY key",
                    (target_tier,),
                )
            return [self._row_to_entry(row) for row in cur.fetchall()]
        finally:
            self._release(conn)

    def rollback(self, key: str, to_version: int, reason: str = "") -> VersionedEntry | None:
        """Roll back a key to a previous version's value.

        Creates a new version with the value from the specified old version.
        Returns the new entry, or None if the target version doesn't exist.
        """
        now = _now_iso()

        with self._lock:
            conn = self._connect()
            try:
                # Find the target version
                cur = conn.execute(
                    "SELECT * FROM knowledge_history WHERE key = ? AND version = ?",
                    (key, to_version),
                )
                target = cur.fetchone()
                if target is None:
                    return None

                # Find current active version (may be a delete or regular entry)
                cur = conn.execute(
                    "SELECT * FROM knowledge_history WHERE key = ? AND valid_to IS NULL ORDER BY version DESC LIMIT 1",
                    (key,),
                )
                current = cur.fetchone()

                if current is not None:
                    new_version = current["version"] + 1
                    # Close out current
                    conn.execute(
                        "UPDATE knowledge_history SET valid_to = ? WHERE id = ?",
                        (now, current["id"]),
                    )
                else:
                    # All versions are closed; determine next version number
                    cur = conn.execute(
                        "SELECT MAX(version) as max_v FROM knowledge_history WHERE key = ?",
                        (key,),
                    )
                    max_row = cur.fetchone()
                    new_version = (max_row["max_v"] or 0) + 1

                rollback_value = target["value"]

                # Sprint 03.04 — rollback adopts the *target version's* tier so
                # rolling back also restores the historical altitude. Falls back
                # to DEFAULT_TIER for pre-migration NULL rows.
                try:
                    rollback_tier = target["temporal_tier"] or DEFAULT_TIER
                except (IndexError, KeyError):
                    rollback_tier = DEFAULT_TIER

                conn.execute(
                    "INSERT INTO knowledge_history (key, value, version, valid_from, valid_to, change_type, reason, changed_by, temporal_tier) "
                    "VALUES (?, ?, ?, ?, NULL, 'rollback', ?, 'agent', ?)",
                    (key, rollback_value, new_version, now, reason, rollback_tier),
                )
                conn.commit()

                entry = VersionedEntry(
                    key=key,
                    value=rollback_value,
                    version=new_version,
                    valid_from=now,
                    valid_to=None,
                    change_type="rollback",
                    reason=reason,
                    changed_by="agent",
                    tier=rollback_tier,
                )
                log.debug("rollback key=%s to_version=%d new_version=%d", key, to_version, new_version)
                return entry
            finally:
                self._release(conn)

    def list_keys(self, include_deleted: bool = False) -> list[str]:
        """List all distinct keys.

        If include_deleted is False (default), only keys with at least one active
        (non-deleted, valid_to IS NULL) version are returned.
        """
        conn = self._connect()
        try:
            if include_deleted:
                cur = conn.execute("SELECT DISTINCT key FROM knowledge_history ORDER BY key")
            else:
                cur = conn.execute(
                    "SELECT DISTINCT key FROM knowledge_history "
                    "WHERE valid_to IS NULL AND change_type != 'delete' "
                    "ORDER BY key",
                )
            return [row["key"] for row in cur.fetchall()]
        finally:
            self._release(conn)

    def format_timeline(self, key: str) -> str:
        """Return a markdown-formatted timeline of all changes to a key."""
        history = self.get_history(key)
        if not history:
            return f"No history found for key: `{key}`"

        lines = [f"## Timeline for `{key}`\n"]
        for record in history:
            ts = record.timestamp
            # Truncate to seconds for readability
            if "." in ts:
                ts = ts.split(".")[0] + "Z"

            badge = {
                "create": "**[CREATE]**",
                "update": "**[UPDATE]**",
                "delete": "**[DELETE]**",
                "rollback": "**[ROLLBACK]**",
            }.get(record.change_type, f"**[{record.change_type.upper()}]**")

            line = f"- `v{record.version}` {ts} {badge} by {record.changed_by}"
            if record.reason:
                line += f" — {record.reason}"
            lines.append(line)

            if record.change_type == "delete":
                lines.append("  - Value: _(deleted)_")
            elif record.change_type in ("create", "rollback"):
                lines.append(f"  - Value: `{record.new_value}`")
            elif record.change_type == "update":
                lines.append(f"  - `{record.old_value}` -> `{record.new_value}`")

        return "\n".join(lines)

    def count(self) -> int:
        """Return the total number of active (non-deleted) entries."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT COUNT(DISTINCT key) as cnt FROM knowledge_history "
                "WHERE valid_to IS NULL AND change_type != 'delete'",
            )
            return cur.fetchone()["cnt"]
        finally:
            self._release(conn)

    def set_expiry(self, key: str, expires_at: str) -> None:
        """Mark the current version of a key to expire at a given ISO timestamp.

        Does nothing if the key has no active version.
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE knowledge_history SET expires_at = ? "
                    "WHERE key = ? AND valid_to IS NULL AND change_type != 'delete'",
                    (expires_at, key),
                )
                conn.commit()
                log.debug("set_expiry key=%s expires_at=%s", key, expires_at)
            finally:
                self._release(conn)

    def get_expired(self) -> list[str]:
        """Return keys whose expires_at has passed (compared to current UTC time)."""
        now = _now_iso()
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT DISTINCT key FROM knowledge_history "
                "WHERE expires_at IS NOT NULL AND expires_at <= ? "
                "AND valid_to IS NULL AND change_type != 'delete' "
                "ORDER BY key",
                (now,),
            )
            return [row["key"] for row in cur.fetchall()]
        finally:
            self._release(conn)

    # -- Sprint 03.07: skill version DAG API (issue #997) --
    #
    # Sibling surface to the knowledge_history API. The schema migration runs
    # unconditionally so the read API is always callable; production write
    # callers are gated by ``BridgeConfig.skill_version_dag_enabled``. Plan 07
    # (Sprint 07.07) extends this surface with EvolutionEvent emission.

    @staticmethod
    def _row_to_skill_version(
        row: sqlite3.Row,
        parent_versions: tuple[int, ...] = (),
    ) -> SkillVersion:
        return SkillVersion(
            id=row["id"],
            skill_name=row["skill_name"],
            version=row["version"],
            body_or_diff=row["body_or_diff"],
            diff_kind=row["diff_kind"],
            created_at=row["created_at"],
            created_by_trigger=row["created_by_trigger"],
            parent_versions=parent_versions,
        )

    def add_skill_node(
        self,
        skill_name: str,
        version: int,
        body_or_diff: str,
        diff_kind: DiffKind | None = None,
        created_by_trigger: str | None = None,
    ) -> int:
        """Insert a new skill version row, returning the row id.

        Validates ``diff_kind`` against :data:`VALID_DIFF_KINDS`. Raises
        ``sqlite3.IntegrityError`` if (skill_name, version) already exists.
        """
        if diff_kind is not None and diff_kind not in VALID_DIFF_KINDS:
            raise ValueError(
                f"Invalid diff_kind {diff_kind!r}; expected one of {VALID_DIFF_KINDS}"
            )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO skill_dag_node "
                    "(skill_name, version, body_or_diff, diff_kind, created_at, created_by_trigger) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        skill_name,
                        version,
                        body_or_diff,
                        diff_kind,
                        _now_iso(),
                        created_by_trigger,
                    ),
                )
                conn.commit()
                node_id = cur.lastrowid
                if node_id is None:  # pragma: no cover - SQLite always returns an id
                    raise RuntimeError("INSERT returned no lastrowid")
                log.debug(
                    "add_skill_node skill=%s version=%d trigger=%s",
                    skill_name,
                    version,
                    created_by_trigger,
                )
                return int(node_id)
            finally:
                self._release(conn)

    def add_skill_edge(
        self,
        parent_id: int,
        child_id: int,
        edge_type: SkillEdgeType = "derived_from",
        diff_summary: str | None = None,
    ) -> None:
        """Connect parent->child in the DAG.

        Multiple edges with the same ``child_id`` and different ``parent_id``
        values express a merge. Raises ``ValueError`` for unknown edge types
        and ``sqlite3.IntegrityError`` if the (parent_id, child_id) pair
        already exists or if either id is missing from ``skill_dag_node``.
        """
        if edge_type not in VALID_EDGE_TYPES:
            raise ValueError(
                f"Invalid edge_type {edge_type!r}; expected one of {VALID_EDGE_TYPES}"
            )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO skill_dag_edge (parent_id, child_id, edge_type, diff_summary) "
                    "VALUES (?, ?, ?, ?)",
                    (parent_id, child_id, edge_type, diff_summary),
                )
                conn.commit()
                log.debug(
                    "add_skill_edge parent=%d child=%d type=%s",
                    parent_id,
                    child_id,
                    edge_type,
                )
            finally:
                self._release(conn)

    def record_skill_version(
        self,
        skill_name: str,
        body_or_diff: str,
        parent_versions: list[int] | tuple[int, ...] = (),
        diff_kind: DiffKind | None = None,
        created_by_trigger: str | None = None,
        edge_type: SkillEdgeType = "derived_from",
        diff_summary: str | None = None,
    ) -> SkillVersion:
        """Convenience: append next version + wire edges in one call.

        Computes ``next_version`` as ``max(existing) + 1`` (or 1 if none),
        inserts the node, and creates one edge per parent version. When
        multiple parents are passed, each edge uses ``edge_type`` (caller
        should pass ``'merged_from'`` for explicit merges; default
        ``'derived_from'`` matches the linear-evolution case).

        Returns the newly inserted :class:`SkillVersion` (with
        ``parent_versions`` populated from the input).
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) AS max_v "
                    "FROM skill_dag_node WHERE skill_name = ?",
                    (skill_name,),
                )
                row = cur.fetchone()
                next_version = (row["max_v"] if row else 0) + 1
            finally:
                self._release(conn)

        # Resolve parent ids in a separate connection to avoid nested locks
        parent_ids: list[int] = []
        for parent_version in parent_versions:
            parent = self.get_skill_at_version(skill_name, parent_version)
            if parent is None:
                raise ValueError(
                    f"Parent version {parent_version} of skill {skill_name!r} not found"
                )
            parent_ids.append(parent.id)

        new_id = self.add_skill_node(
            skill_name,
            next_version,
            body_or_diff,
            diff_kind=diff_kind,
            created_by_trigger=created_by_trigger,
        )
        for parent_id in parent_ids:
            self.add_skill_edge(
                parent_id,
                new_id,
                edge_type=edge_type,
                diff_summary=diff_summary,
            )
        # Re-read so created_at reflects the persisted value.
        result = self.get_skill_at_version(skill_name, next_version)
        if result is None:  # pragma: no cover - defensive; just inserted
            raise RuntimeError("record_skill_version: row vanished after insert")
        return result

    def get_skill_at_version(
        self, skill_name: str, version: int
    ) -> SkillVersion | None:
        """Return the node for ``(skill_name, version)`` or ``None`` if absent.

        ``parent_versions`` on the returned :class:`SkillVersion` is populated
        from the edge table, sorted ascending for stable test output.
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT * FROM skill_dag_node WHERE skill_name = ? AND version = ?",
                (skill_name, version),
            )
            row = cur.fetchone()
            if row is None:
                return None
            parents_cur = conn.execute(
                "SELECT n.version AS pv FROM skill_dag_edge e "
                "JOIN skill_dag_node n ON n.id = e.parent_id "
                "WHERE e.child_id = ? "
                "ORDER BY n.version ASC",
                (row["id"],),
            )
            parent_versions = tuple(int(p["pv"]) for p in parents_cur.fetchall())
            return self._row_to_skill_version(row, parent_versions=parent_versions)
        finally:
            self._release(conn)

    def get_skill_lineage(self, skill_name: str) -> list[SkillVersion]:
        """Return every recorded version of a skill, ascending by version.

        Each :class:`SkillVersion` carries its ``parent_versions`` tuple so
        callers can reconstruct the DAG without a second query. v0 entries
        produced by :meth:`backfill_skill_proposals_to_v0` carry
        ``parent_versions=()``.
        """
        conn = self._connect()
        try:
            nodes = conn.execute(
                "SELECT * FROM skill_dag_node WHERE skill_name = ? "
                "ORDER BY version ASC",
                (skill_name,),
            ).fetchall()
            if not nodes:
                return []
            ids = [n["id"] for n in nodes]
            placeholders = ",".join("?" * len(ids))
            edges = conn.execute(
                f"SELECT e.child_id AS cid, n.version AS pv "  # noqa: S608 - ids only
                f"FROM skill_dag_edge e "
                f"JOIN skill_dag_node n ON n.id = e.parent_id "
                f"WHERE e.child_id IN ({placeholders}) "
                f"ORDER BY n.version ASC",
                ids,
            ).fetchall()
            parents_by_child: dict[int, list[int]] = {}
            for edge in edges:
                parents_by_child.setdefault(edge["cid"], []).append(int(edge["pv"]))
            return [
                self._row_to_skill_version(
                    n, parent_versions=tuple(parents_by_child.get(n["id"], []))
                )
                for n in nodes
            ]
        finally:
            self._release(conn)

    def backfill_skill_proposals_to_v0(
        self,
        proposals: list[tuple[str, str]],
        trigger: str = "legacy",
    ) -> int:
        """Backfill v0 nodes for pre-existing skill proposals.

        ``proposals`` is a list of ``(skill_name, body)`` pairs — the caller
        (typically a one-shot migration script that imports
        ``bridge.skill_evolution.SkillProposalStore``) decides where the
        proposals come from; this module deliberately does not import
        ``skill_evolution`` to keep the dependency direction one-way.

        Skips skills that already have *any* version recorded (idempotent).
        Returns the number of v0 rows inserted.
        """
        inserted = 0
        for skill_name, body in proposals:
            existing = self.get_skill_at_version(skill_name, 0)
            if existing is not None:
                continue
            # Also skip if a v1+ exists — backfill is only for skills with
            # no DAG history at all.
            lineage = self.get_skill_lineage(skill_name)
            if lineage:
                continue
            self.add_skill_node(
                skill_name,
                version=0,
                body_or_diff=body,
                diff_kind="full",
                created_by_trigger=trigger,
            )
            inserted += 1
        log.info(
            "backfill_skill_proposals_to_v0: inserted %d v0 rows (trigger=%s)",
            inserted,
            trigger,
        )
        return inserted
