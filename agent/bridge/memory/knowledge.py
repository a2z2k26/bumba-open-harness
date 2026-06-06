"""Knowledge store, FTS5/hybrid/semantic search, salience decay, and
context assembly — half of the Memory mixin pair.

Provides:
- Module-level constants: ``KNOWLEDGE_CATEGORIES``, ``DECAY_RATES``,
  ``DECAY_EXEMPT_SOURCES``, ``DECAY_EXEMPT_CATEGORIES``,
  ``SALIENCE_REINFORCE_AMOUNT``, ``SALIENCE_MAX``,
  ``SALIENCE_PRUNE_THRESHOLD``, ``IDENTITY_FILES``.
- ``KnowledgeMixin`` — knowledge-store methods composed into ``Memory`` in
  ``bridge/memory/__init__.py``.

The ``assemble_context`` method lives here because the bulk of its work
reads knowledge rows; it inherits ``search_conversations`` and
``get_recent_messages`` from ``ConversationMixin`` via the composed class.

Split from the monolithic ``bridge/memory.py`` per PR #1687 precedent
(refs #1305).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..memory_enhancement import ScoredEntry, classify_intent, compute_importance
from ..memory_tiers import MemoryTier
from ..memory_writes import MemoryWriteReceipt, emit as _emit_write_receipt
from .conversation import _escape_fts5_query

log = logging.getLogger(__name__)

# Canonical knowledge categories with priority ordering (lower = higher priority in context)
KNOWLEDGE_CATEGORIES = {
    "preference": 1,
    "person": 2,
    "project": 3,
    "decision": 4,
    "process": 5,
    "learning": 6,
    "tool": 7,
    "reference": 8,
}

# Decay rates per category (multiplied daily; lower = faster decay)
# Exempt categories are not listed here — they never decay.
DECAY_RATES = {
    "project": 0.99,
    "decision": 0.99,
    "process": 0.99,
    "learning": 0.98,
    "tool": 0.98,
    "reference": 0.98,
}

# Categories/sources exempt from decay
DECAY_EXEMPT_SOURCES = {"operator"}
DECAY_EXEMPT_CATEGORIES = {"preference", "person"}

# Salience constants
SALIENCE_REINFORCE_AMOUNT = 0.1
SALIENCE_MAX = 5.0
SALIENCE_PRUNE_THRESHOLD = 0.1

# Identity injection (Sprint 17 / issue #637 / activation #817)
# Files searched at project_root and project_root/agent for the bridge's
# identity documents. Order matters: SOUL first (who I am), then OPERATOR
# (who the operator is), then RULES (how we work).
IDENTITY_FILES: tuple[str, ...] = ("SOUL.md", "OPERATOR.md", "RULES.md")
_IDENTITY_TRUNCATION_MARKER = "[...truncated for context window...]"


def _load_identity_text(identity_max: int) -> str:
    """Load IDENTITY_FILES contents, capped at *identity_max* bytes total.

    Searches each filename at both ``project_root`` and ``project_root/"agent"``
    to support the two-user (source vs runtime) layout. Returns markdown with
    ``## <filename>`` section headers, in IDENTITY_FILES order. When a section
    would exceed the byte budget the content is truncated and the marker
    ``[...truncated for context window...]`` is appended; subsequent files
    are skipped.
    """
    if identity_max <= 0:
        return ""
    # bridge/memory/knowledge.py → bridge/memory/ → bridge/ → agent/ → repo root
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    parts: list[str] = []
    used = 0
    for fname in IDENTITY_FILES:
        candidates = (project_root / fname, project_root / "agent" / fname)
        chosen = None
        for cand in candidates:
            try:
                if cand.exists():
                    chosen = cand
                    break
            except OSError:
                continue
        if chosen is None:
            continue
        try:
            content = chosen.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        section = f"## {fname}\n{content}\n"
        section_bytes = len(section.encode("utf-8"))
        if used + section_bytes <= identity_max:
            parts.append(section)
            used += section_bytes
            continue
        # Doesn't fit — write a truncated section then stop.
        header = f"## {fname}\n"
        header_bytes = len(header.encode("utf-8"))
        marker_with_nl = _IDENTITY_TRUNCATION_MARKER + "\n"
        marker_bytes = len(marker_with_nl.encode("utf-8"))
        budget = identity_max - used - header_bytes - marker_bytes
        if budget > 0:
            content_bytes = content.encode("utf-8")[:budget]
            content_trunc = content_bytes.decode("utf-8", errors="ignore")
            parts.append(f"{header}{content_trunc}{marker_with_nl}")
        else:
            parts.append(f"{header}{marker_with_nl}")
        break
    return "".join(parts)


class MemoryKVAdapter:
    """Adapts Memory to the get/set k/v contract Zone 4 tools expect."""

    def __init__(self, memory) -> None:
        self._memory = memory

    async def get(self, key: str) -> str | None:
        return await self._memory.get_knowledge(key)

    async def set(self, key: str, value: str) -> None:
        await self._memory.store_knowledge(key, value, source="zone4-tool")

    async def list_prefix(self, prefix: str) -> list[str]:
        """Return all knowledge keys that start with *prefix*, sorted.

        Backed by a parameterized SELECT key FROM knowledge WHERE key LIKE ?
        query. Safe against SQL injection — the wildcard is appended in Python
        after binding so only the prefix is sent as a parameter.
        """
        rows = await self._memory._db.fetchall(
            "SELECT key FROM knowledge WHERE key LIKE ? ORDER BY key",
            (prefix + "%",),
        )
        return [row[0] for row in rows]


class KnowledgeMixin:
    """Knowledge-side methods of the ``Memory`` class.

    Provides knowledge storage, FTS5/hybrid/semantic search, salience
    reinforcement/decay, goal tracking, tag processing, and the
    cross-cutting ``assemble_context`` (which calls into conversation
    methods inherited from ``ConversationMixin``).
    """

    # -- S55: Knowledge and context assembly --

    def set_dual_write_pipeline(self, pipeline) -> None:
        """Wire the Mem-4 DualWritePipeline (#1845).

        Called by ``BridgeApp._initialize`` via the WIRING_MANIFEST entry.
        The pipeline is consulted on ``store_knowledge`` and on WAL replay
        only when ``config.memory_tiers_enabled`` is True; flag-off behaviour
        is byte-identical to pre-Mem-4 because the gate in both sites checks
        the pipeline attribute before invoking it.
        """
        self._dual_write_pipeline = pipeline

    def _warn_missing_dual_write_pipeline(self, operation: str) -> None:
        """Log once when tiers are on but the manifest wire is absent."""
        if getattr(self, "_dual_write_missing_warned", False):
            return
        log.warning(
            "memory_tiers enabled but set_dual_write_pipeline() has not "
            "wired a DualWritePipeline; falling back to primary SQLite for %s",
            operation,
        )
        self._dual_write_missing_warned = True

    async def _classify_for_write(
        self, key: str, value: str, category: str | None
    ) -> tuple[MemoryTier, float]:
        """Classify a memory entry into (tier, importance_score).

        Sprint Mem-3 — Memory-Tier Architecture epic (#1844).

        Gated by ``config.memory_tiers_enabled``. When False, returns
        ``(MemoryTier.CONTEXT, 0.0)`` without invoking the classifier — the
        column DEFAULT picks up the tier label and importance is unused.

        On classifier exception, falls back to CONTEXT + 0.0 with a single
        WARNING log. Never raises.
        """
        # `getattr` with default tolerates minimal config mocks used by some
        # legacy integration tests (e.g. _MinimalConfig in
        # test_integration_memory_lifecycle). Production `BridgeConfig`
        # always carries the field — defaulting False here is safe and
        # preserves byte-identical pre-Mem-3 behaviour when missing.
        if not getattr(self._config, "memory_tiers_enabled", False):
            return MemoryTier.CONTEXT, 0.0
        try:
            intent = classify_intent(value)
            entry = ScoredEntry(
                key=key,
                value=value,
                category=category or "reference",
                intent=intent,
                created_at=time.time(),
            )
            importance = compute_importance(entry)
            tier_map = {
                "preference": MemoryTier.PREFERENCE,
                "decision": MemoryTier.DECISION,
            }
            tier = tier_map.get(intent, MemoryTier.CONTEXT)
            return tier, importance
        except Exception as exc:
            log.warning(
                "memory_tiers: classifier failed for key=%r, falling back to CONTEXT: %s",
                key, exc,
            )
            return MemoryTier.CONTEXT, 0.0

    async def _lazy_classify_if_null(self, row: dict[str, Any]) -> dict[str, Any]:
        """Lazy-on-read fallback for rows with ``tier IS NULL``.

        Sprint Mem-8 (Memory-Tier Architecture, #1849).

        When ``memory_tiers_enabled`` is True and a result row carries no
        tier (``None`` or empty string), this helper classifies it via
        ``_classify_for_write`` and persists the result with a single
        UPDATE. The row dict is mutated in place so the caller sees the
        same shape post-call (plus the new ``tier`` field).

        Defensive-only scaffolding: Migration 14 declares ``tier TEXT
        DEFAULT 'context' NOT NULL``, so on the current schema every row
        already carries a tier and this helper is a no-op. It exists for:
          (a) future migrations that introduce a NULL-tier path,
          (b) shadow rows that bypass ``store_knowledge`` (untested).

        No-op when:
          - ``memory_tiers_enabled`` is False,
          - the row already has a truthy tier.

        Failure UPDATEs are logged at WARNING and swallowed — the helper
        never raises into the search path.
        """
        if not getattr(self._config, "memory_tiers_enabled", False):
            return row

        existing_tier = row.get("tier")
        if existing_tier:
            return row

        # Try to enrich tier from the live row if the result dict doesn't
        # carry it. If the DB row is also NULL/empty, classify + UPDATE.
        key = row.get("key", "")
        if not key:
            return row

        try:
            db_row = await self._db.fetchone(
                "SELECT tier, value FROM knowledge WHERE key = ?", (key,),
            )
        except Exception as exc:
            log.warning("_lazy_classify_if_null: SELECT failed for key=%r: %s", key, exc)
            return row

        if db_row is None:
            return row

        db_tier = db_row[0] if db_row[0] else None
        if db_tier:
            # Schema-default 'context' or any other tier already in place —
            # propagate to the result dict and we're done.
            row["tier"] = db_tier
            return row

        # Truly NULL/empty tier on disk — classify + persist.
        value = row.get("value") or db_row[1] or ""
        tier, _importance = await self._classify_for_write(
            key, value, row.get("category"),
        )
        row["tier"] = tier.value

        try:
            await self._db.execute(
                "UPDATE knowledge SET tier = ? WHERE key = ?",
                (tier.value, key),
            )
            await self._db.commit()
        except Exception as exc:
            log.warning(
                "_lazy_classify_if_null: UPDATE failed for key=%r: %s", key, exc,
            )
        return row

    async def store_knowledge(
        self,
        key: str,
        value: str,
        tags: str | None = None,
        source: str = "agent",
        category: str = "reference",
    ) -> None:
        """Store or update a knowledge entry."""
        # Sprint 03.06 — write-ahead the mutation BEFORE hitting SQLite.
        # When the WAL is disabled this is a no-op (returns None). On
        # success below we drain the just-written entry; on crash mid-call
        # the next bridge boot calls `MemoryWAL.recover` which re-applies
        # the mutation through `apply_wal_entry`.
        wal_entry = await self._wal.enqueue(
            target_store="knowledge",
            payload={
                "key": key,
                "value": value,
                "tags": tags,
                "source": source,
                "category": category,
            },
        )

        # Sprint Mem-3 (#1844) — capture-side tier classification + importance
        # scoring. Helper is a no-op when memory_tiers_enabled is False
        # (returns CONTEXT + 0.0); the INSERT below uses the SQLite column
        # DEFAULT ('context') in that path, so behaviour-off is byte-identical
        # to pre-Mem-3. Importance is logged at DEBUG but NOT persisted (no
        # importance_score column on the schema in this PR).
        tier, importance = await self._classify_for_write(key, value, category)
        log.debug(
            "memory_tiers: key=%r tier=%s importance=%.3f",
            key, tier.value, importance,
        )

        # Sprint Mem-4 (#1845) — when memory_tiers_enabled AND the pipeline
        # is wired, route the write through DualWritePipeline so secondary
        # destinations (second_brain, vector) receive it per the tier's
        # policy. Flag-off OR pipeline-not-wired falls through to the
        # pre-Mem-4 direct INSERT below — byte-identical behaviour.
        if (
            getattr(self._config, "memory_tiers_enabled", False)
            and self._dual_write_pipeline is not None
        ):
            try:
                from ..memory_tiers import load_tier_policies
                policies = load_tier_policies(self._config)
                policy = policies[tier]
                await self._dual_write_pipeline.write(
                    key=key,
                    value=value,
                    tags=tags or "",
                    source=source,
                    category=category,
                    tier=tier.value,
                    destinations=policy.destinations,
                    metadata=None,
                )
            except Exception:
                # Primary failure on the pipeline path is fatal — re-raise
                # so the WAL stays armed. Secondary failures are swallowed
                # inside the pipeline; only the primary's exception reaches
                # this except block.
                log.exception(
                    "memory_tiers: DualWritePipeline.write failed for key=%r",
                    key,
                )
                raise
        else:
            if getattr(self._config, "memory_tiers_enabled", False):
                self._warn_missing_dual_write_pipeline("store_knowledge")
            await self._db.execute(
                """INSERT INTO knowledge (key, value, tags, source, category, tier, last_accessed_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       tags = excluded.tags,
                       source = excluded.source,
                       category = excluded.category,
                       tier = excluded.tier,
                       updated_at = datetime('now'),
                       last_accessed_at = datetime('now')""",
                (key, value, tags, source, category, tier.value),
            )
            await self._db.commit()

        # Drain the WAL entry we just wrote — SQLite write succeeded, so
        # the WAL no longer needs to retain it. The applier returns True
        # for the matching write_id (idempotent: already-applied) so the
        # entry is removed.
        if wal_entry is not None:
            try:
                await self._wal.drain(self._wal_applier_default)
            except Exception:
                log.exception(
                    "memory_wal drain after store_knowledge failed (non-fatal)"
                )

        # Fire async embedding generation (non-blocking). P2.5 (#1721) —
        # retain the task reference on ``self._pending_tasks`` so it
        # cannot be GC'd mid-flight, and auto-discard on completion.
        if self._embedding_client and self._embedding_client.is_configured:
            import asyncio
            embed_task = asyncio.create_task(
                self._generate_embedding(key, value),
                name=f"knowledge-embed-{key}",
            )
            self._pending_tasks.add(embed_task)
            embed_task.add_done_callback(self._pending_tasks.discard)

        # D2.3 — emit write receipt for operator observability
        try:
            _emit_write_receipt(MemoryWriteReceipt.now(
                subsystem="knowledge", op="insert",
                key=f"{category}:{key}", payload_bytes=len(value or ""),
                actor=source or "agent",
            ))
        except Exception:
            pass

        # Sprint Mem-9.5 (#1877) — emit `memory.tier.writes` counter per tier
        # value. `MetricsCollector.observe` does not accept labels, so the
        # tier label is folded into the metric name (e.g.
        # `memory.tier.writes.preference`). Registry: `memory-tiers.yaml`.
        # Flag-off path falls through to the legacy CONTEXT default — we
        # only emit when the operator has opted into tier-aware capture so
        # the metric represents real tier activity, not the default-context
        # fallback.
        if (
            self._metrics
            and getattr(self._config, "memory_tiers_enabled", False)
        ):
            self._metrics.observe(
                f"memory.tier.writes.{tier.value}", 1.0
            )

    async def _wal_applier_default(self, op: dict[str, Any]) -> bool:
        """Default applier for replaying WAL entries.

        Routes by ``target_store`` to the appropriate canonical write.
        Returns True on success (entry drained), False to retain.
        Used by both startup recovery and the post-write drain path.
        """
        target = op.get("target_store")
        payload = op.get("payload") or {}
        try:
            if target == "knowledge":
                # Sprint Mem-3 (#1844) — re-classify on WAL replay. The WAL
                # payload doesn't carry tier (added post-Mem-2), so the
                # applier re-runs the same classification path. Same flag-off
                # behaviour: helper returns CONTEXT + 0.0 and the SQLite
                # DEFAULT preserves byte-identical pre-Mem-3 semantics.
                replay_key = payload.get("key")
                replay_value = payload.get("value")
                replay_category = payload.get("category", "reference")
                tier, importance = await self._classify_for_write(
                    replay_key, replay_value, replay_category
                )
                log.debug(
                    "memory_tiers: wal_replay key=%r tier=%s importance=%.3f",
                    replay_key, tier.value, importance,
                )
                # Sprint Mem-4 (#1845) — WAL-replay path mirrors the
                # store_knowledge gate so a crash mid-write still re-runs
                # through the pipeline when the flag is on. Idempotency on
                # primary is preserved by the SQLite ON CONFLICT(key)
                # upsert that SQLiteDestination performs.
                if (
                    getattr(self._config, "memory_tiers_enabled", False)
                    and self._dual_write_pipeline is not None
                ):
                    try:
                        from ..memory_tiers import load_tier_policies
                        policies = load_tier_policies(self._config)
                        policy = policies[tier]
                        await self._dual_write_pipeline.write(
                            key=replay_key,
                            value=replay_value,
                            tags=payload.get("tags") or "",
                            source=payload.get("source", "agent"),
                            category=replay_category,
                            tier=tier.value,
                            destinations=policy.destinations,
                            metadata=None,
                        )
                    except Exception:
                        log.exception(
                            "memory_tiers: WAL-replay DualWritePipeline.write "
                            "failed for key=%r",
                            replay_key,
                        )
                        return False
                else:
                    if getattr(self._config, "memory_tiers_enabled", False):
                        self._warn_missing_dual_write_pipeline("wal_replay")
                    # Re-apply via the same SQL — idempotent on (key) UNIQUE.
                    await self._db.execute(
                        """INSERT INTO knowledge (key, value, tags, source, category, tier, last_accessed_at)
                           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                           ON CONFLICT(key) DO UPDATE SET
                               value = excluded.value,
                               tags = excluded.tags,
                               source = excluded.source,
                               category = excluded.category,
                               tier = excluded.tier,
                               updated_at = datetime('now'),
                               last_accessed_at = datetime('now')""",
                        (
                            replay_key,
                            replay_value,
                            payload.get("tags"),
                            payload.get("source", "agent"),
                            replay_category,
                            tier.value,
                        ),
                    )
                    await self._db.commit()
                return True
            log.warning(
                "memory_wal applier: unknown target_store=%r — dropping",
                target,
            )
            return True
        except Exception:
            log.exception("memory_wal applier failed for op=%s", op)
            return False

    @property
    def wal(self):
        """Expose the memory WAL (used by SessionManager for end-of-session drain)."""
        return self._wal

    async def drain_wal(self) -> int:
        """Drain pending WAL entries through the default applier.

        Returns the count drained. Called by SessionManager at session end
        and at bridge restart to recover from prior crashes.
        """
        result = await self._wal.drain(self._wal_applier_default)
        return result.drained

    async def recover_wal(self) -> int:
        """Recover entries left over from a prior session.

        Called once at bridge startup before any new mutations land.
        Forces drain regardless of consolidation lock state since the
        recovery path runs before consolidation can re-arm.
        """
        result = await self._wal.recover(self._wal_applier_default)
        return result.drained

    async def _generate_embedding(self, key: str, text: str) -> None:
        """Generate and store an embedding for a knowledge entry (async, non-blocking)."""
        try:
            blob = self._embedding_client.generate(text)
            if blob:
                await self._db.execute(
                    "UPDATE knowledge SET embedding = ? WHERE key = ?", (blob, key)
                )
                await self._db.commit()
        except Exception as e:
            log.warning("Embedding generation failed for %s: %s", key, e)

    async def get_knowledge(self, key: str) -> str | None:
        """Get a single knowledge entry by key.

        Mem-2.5 (#1863): on hit, updates ``last_accessed_at`` so the
        future tier-eviction sweep (Mem-7) can distinguish warm entries
        from stale ones. Salience math (``_reinforce_entries``) is NOT
        called here — single-key get is not a search hit.
        """
        row = await self._db.fetchone(
            "SELECT value FROM knowledge WHERE key = ?", (key,),
        )
        if row:
            await self._touch_last_accessed([key])
            return row[0]
        return None

    async def search_knowledge(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search knowledge with four-branch ordering:

        0. **Tiered** (Sprint Mem-6, #1847) — per-tier RRF fusion via
           ``HybridSearch.search_tiered`` + tier-weighted context-window
           assembly via ``assemble_context_window``. Fires only when
           ``config.memory_tiers_enabled`` is True AND ``self._hybrid_search``
           is wired AND the hybrid implementation exposes ``search_tiered``.
           Falls through to Branch 1 on any exception (byte-identical to
           pre-Mem-6 at flag-off).
        1. **Hybrid** — RRF fusion of FTS5 + vector via `HybridSearch.search`,
           when ``self._hybrid_search`` is wired (Sprint 05.02 plumbing,
           Sprint 05.03 activation).
        2. **Semantic** — `self._embedding_client.generate(text)` against the
           ``knowledge.embedding`` column. Intermediate fallback for callers
           constructing Memory with only an embedding_client (no hybrid).
        3. **FTS5** — BM25-ranked keyword search. Last-resort fallback when
           neither vector path is wired or both raised.

        Results are reinforced (salience bumped) on retrieval.
        """
        _search_start = time.monotonic()

        # Branch 0 — tier-aware retrieval (Sprint Mem-6, #1847). Gated by
        # the memory_tiers feature flag AND a wired hybrid_search with
        # `search_tiered` available. Defensive `hasattr` covers test
        # doubles and a hypothetical pre-Mem-5 deployment where the
        # method may be missing.
        if (
            getattr(self._config, "memory_tiers_enabled", False)
            and self._hybrid_search is not None
            and hasattr(self._hybrid_search, "search_tiered")
        ):
            try:
                results = await self._tiered_search_branch(query, limit)
                if results:
                    await self._reinforce_entries([r["key"] for r in results])
                    await self._touch_last_accessed([r["key"] for r in results])
                    if self._metrics:
                        elapsed_ms = (time.monotonic() - _search_start) * 1000
                        self._metrics.observe(
                            "memory_search_latency_ms", elapsed_ms
                        )
                        self._metrics.observe(
                            "memory_search_tiered_count", float(len(results))
                        )
                    # Sprint Mem-8 (#1849) — lazy-on-read tier fallback.
                    results = [await self._lazy_classify_if_null(r) for r in results]
                    return await self._apply_recall_learning(results)
            except Exception as e:
                log.warning(
                    "Tiered search failed, falling back to hybrid/semantic/FTS5: %s",
                    e,
                )

        # Branch 1 — hybrid (Sprint 05.03)
        if self._hybrid_search is not None:
            try:
                results = await self._hybrid_search_branch(query, limit)
                if results:
                    await self._reinforce_entries([r["key"] for r in results])
                    await self._touch_last_accessed([r["key"] for r in results])
                    if self._metrics:
                        elapsed_ms = (time.monotonic() - _search_start) * 1000
                        self._metrics.observe("memory_search_latency_ms", elapsed_ms)
                        self._metrics.observe(
                            "memory_search_hybrid_count", float(len(results))
                        )
                    # Sprint Mem-8 (#1849) — lazy-on-read tier fallback.
                    results = [await self._lazy_classify_if_null(r) for r in results]
                    return await self._apply_recall_learning(results)
            except Exception as e:
                log.warning(
                    "Hybrid search failed, falling back to semantic/FTS5: %s", e
                )

        # Branch 2 — semantic (pre-existing path; intermediate fallback)
        if self._embedding_client and self._embedding_client.is_configured:
            try:
                results = await self._semantic_search(query, limit)
                if results:
                    await self._reinforce_entries([r["key"] for r in results])
                    await self._touch_last_accessed([r["key"] for r in results])
                    # Sprint Mem-8 (#1849) — lazy-on-read tier fallback.
                    results = [await self._lazy_classify_if_null(r) for r in results]
                    return await self._apply_recall_learning(results)
            except Exception as e:
                log.warning("Semantic search failed, falling back to FTS5: %s", e)

        # FTS5 BM25-ranked search (excludes archived)
        fts_query = _escape_fts5_query(query)
        try:
            rows = await self._db.fetchall(
                """SELECT k.key, k.value, k.tags, k.source,
                          rank
                   FROM knowledge_fts
                   JOIN knowledge k ON knowledge_fts.rowid = k.rowid
                   WHERE knowledge_fts MATCH ?
                     AND (k.archived IS NULL OR k.archived = 0)
                   ORDER BY rank
                   LIMIT ?""",
                (fts_query, limit),
            )
        except Exception as e:
            log.warning("FTS5 search failed for query %r: %s", fts_query, e)
            rows = []

        if not rows:
            # Fallback: return top entries by salience (no FTS match)
            rows = await self._db.fetchall(
                """SELECT key, value, tags, source, -salience as rank
                   FROM knowledge
                   WHERE (archived IS NULL OR archived = 0)
                   ORDER BY salience DESC
                   LIMIT ?""",
                (limit,),
            )

        results = [
            {"key": r[0], "value": r[1], "tags": r[2], "source": r[3], "rank": r[4]}
            for r in rows
        ]
        if results:
            await self._reinforce_entries([r["key"] for r in results])
            await self._touch_last_accessed([r["key"] for r in results])

        # Record search metrics
        if self._metrics:
            elapsed_ms = (time.monotonic() - _search_start) * 1000
            self._metrics.observe("memory_search_latency_ms", elapsed_ms)
            self._metrics.observe("memory_search_result_count", float(len(results)))

        # Sprint Mem-8 (#1849) — lazy-on-read tier fallback.
        results = [await self._lazy_classify_if_null(r) for r in results]
        return await self._apply_recall_learning(results)

    async def _tiered_search_branch(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Branch 0 — per-tier RRF + tier-weighted context-window assembly.

        Sprint Mem-6 (#1847). Calls Mem-5's ``HybridSearch.search_tiered``
        to get per-tier ranked ``SearchResult`` lists, converts them to
        ``ScoredEntry`` instances with composite importance scores, then
        delegates to ``assemble_context_window`` (Mem-6 tiered mode) to
        rank and cull within a token budget.

        Returns the same dict shape as the other branches (``key`` /
        ``value`` / ``tags`` / ``source`` / ``rank``) so the caller in
        ``search_knowledge`` is shape-agnostic across branches.

        ``HybridSearch.search_tiered`` takes a sync ``sqlite3.Connection``;
        we open a transient short-lived connection to ``self._db.db_path``
        inside the executor thread, run the search, and close. Avoids
        cross-thread sharing of the aiosqlite worker connection.
        """
        import asyncio
        import sqlite3

        from ..hybrid_search import SearchResult  # noqa: F401 — type hint
        from ..memory_enhancement import (
            ScoredEntry,
            assemble_context_window,
            compute_importance,
        )
        from ..memory_tiers import MemoryTier, load_tier_policies

        db_path = str(self._db.db_path)
        hybrid = self._hybrid_search
        config = self._config

        def _run_tiered() -> dict[MemoryTier, list[SearchResult]]:
            # Read-only short-lived connection so we never share a
            # sqlite3.Connection across threads. `uri=True` lets us pass
            # `mode=ro` to enforce read-only at the kernel level.
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            try:
                return hybrid.search_tiered(
                    query,
                    db_connection=conn,
                    config=config,
                    limit_per_tier=limit,
                )
            finally:
                conn.close()

        loop = asyncio.get_running_loop()
        tier_results_raw = await loop.run_in_executor(None, _run_tiered)

        # Convert SearchResult → ScoredEntry, scoring importance up-front.
        # `SearchResult` carries content, category, and the tier-weighted
        # rrf_score from Mem-5; we treat rrf_score as the initial salience
        # so `compute_importance` factors search relevance + decay together.
        policies = load_tier_policies(config)
        now = time.time()
        tier_results: dict[MemoryTier, list[ScoredEntry]] = {}
        for tier, search_results in tier_results_raw.items():
            scored: list[ScoredEntry] = []
            for sr in search_results:
                entry = ScoredEntry(
                    key=sr.doc_id,
                    value=sr.content,
                    category=sr.category or "reference",
                    intent="fact",  # tier carries semantic class; intent is opaque here
                    salience=sr.rrf_score,
                    created_at=now,
                )
                entry.importance = compute_importance(entry)
                scored.append(entry)
            tier_results[tier] = scored

        tier_weights = {
            t: policies[t].retrieval_weight for t in MemoryTier
        }
        budget_tokens = getattr(
            config, "memory_tiers_context_window_tokens", 4000
        )
        # `max_chars` is a byte budget; ~4 chars/token is the same ratio
        # the legacy MAX_CONTEXT_TOKENS path uses.
        selected = assemble_context_window(
            tier_results=tier_results,
            tier_weights=tier_weights,
            max_entries=limit,
            max_chars=budget_tokens * 4,
        )

        # Map back to the dict shape that `search_knowledge`'s callers
        # expect. `rank` carries a sortable score where lower is better
        # (mirrors the FTS5 / semantic / hybrid branches' contract).
        return [
            {
                "key": e.key,
                "value": e.value,
                "tags": "",
                "source": "",
                "rank": -e.importance,
            }
            for e in selected
        ]

    async def _hybrid_search_branch(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """RRF-fused hybrid branch (Sprint 05.03).

        Builds the ``fts5_results`` tuple list that ``HybridSearch.search``
        expects, plus a ``documents`` dict so the vector branch has data
        to score. Returns dicts with the same shape as the FTS5 / semantic
        branches (``key`` / ``value`` / ``tags`` / ``source`` / ``rank``)
        so back-compat with the existing callers is preserved. The
        ``rank`` field carries the RRF score on this path (a float).

        ``HybridSearch.search`` re-embeds documents inline on every call
        (no cached-blob lookup yet — that's a future sprint). To bound
        cost, ``documents`` is built from the FTS5 candidate set plus
        the top-salience entries (capped at ``HYBRID_DOC_CAP``) so
        semantic-only matches against the most-reinforced knowledge
        still surface.
        """
        HYBRID_DOC_CAP = 50

        fts_query = _escape_fts5_query(query)

        # Run the same FTS5 query as the legacy branch.
        try:
            fts_rows = await self._db.fetchall(
                """SELECT k.key, k.value, k.tags, k.source, rank
                   FROM knowledge_fts
                   JOIN knowledge k ON knowledge_fts.rowid = k.rowid
                   WHERE knowledge_fts MATCH ?
                     AND (k.archived IS NULL OR k.archived = 0)
                   ORDER BY rank
                   LIMIT ?""",
                (fts_query, limit),
            )
        except Exception as e:
            log.warning("Hybrid: FTS5 fetch failed for %r: %s", fts_query, e)
            fts_rows = []

        # Tuple shape expected by HybridSearch.search:
        # (doc_id, content, category, score)
        fts5_results: list[tuple[str, str, str, float]] = [
            (r[0], r[1] or "", (r[2] or r[3] or ""), float(r[4]))
            for r in fts_rows
        ]

        # Build documents dict — FTS5 candidates + top-salience entries
        # capped at HYBRID_DOC_CAP for cost control.
        documents: dict[str, str] = {
            r[0]: (r[1] or "") for r in fts_rows
        }
        if len(documents) < HYBRID_DOC_CAP:
            need = HYBRID_DOC_CAP - len(documents)
            sal_rows = await self._db.fetchall(
                """SELECT key, value FROM knowledge
                   WHERE (archived IS NULL OR archived = 0)
                   ORDER BY salience DESC
                   LIMIT ?""",
                (need + len(documents),),  # over-fetch in case of overlap
            )
            for sk, sv in sal_rows:
                if sk not in documents:
                    documents[sk] = sv or ""
                    if len(documents) >= HYBRID_DOC_CAP:
                        break

        # Delegate to HybridSearch — it re-embeds and merges via RRF.
        # Note: HybridSearch.search is sync; run it on the loop default
        # executor to avoid blocking the asyncio event loop on
        # CPU-bound embedding work.
        import asyncio

        loop = asyncio.get_running_loop()
        merged = await loop.run_in_executor(
            None,
            lambda: self._hybrid_search.search(
                query, fts5_results, documents=documents, top_k=limit
            ),
        )

        # Re-fetch tags/source for any merged result that came in via the
        # vector-only path (i.e., wasn't in fts5_results). The
        # HybridSearch.merge_results path leaves vector-only entries
        # without category populated.
        out: list[dict[str, Any]] = []
        for sr in merged:
            tags = ""
            source = ""
            if sr.category:
                tags = sr.category  # category came from FTS5 row
            else:
                # Vector-only hit — re-fetch metadata
                row = await self._db.fetchone(
                    "SELECT tags, source FROM knowledge WHERE key = ?",
                    (sr.doc_id,),
                )
                if row:
                    tags = row[0] or ""
                    source = row[1] or ""
            out.append({
                "key": sr.doc_id,
                "value": sr.content,
                "tags": tags,
                "source": source,
                "rank": sr.rrf_score,
            })

        return out

    async def _semantic_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Perform semantic search using embeddings."""
        from ..embeddings import cosine_similarity

        query_blob = self._embedding_client.generate(query)
        if not query_blob:
            return []

        # Get all knowledge entries with embeddings
        rows = await self._db.fetchall(
            """SELECT key, value, tags, source, embedding
               FROM knowledge
               WHERE embedding IS NOT NULL
               AND (archived IS NULL OR archived = 0)""",
        )

        if not rows:
            return []

        # Compute similarity scores
        scored = []
        for row in rows:
            sim = cosine_similarity(query_blob, row[4])
            if sim >= 0.3:  # Similarity threshold
                scored.append((sim, row))

        # Sort by similarity (descending) and limit
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"key": r[1][0], "value": r[1][1], "tags": r[1][2], "source": r[1][3], "rank": -score}
            for score, r in scored[:limit]
        ]

    async def get_session_summaries(
        self, chat_id: str, limit: int | None = None
    ) -> list[dict[str, str]]:
        """Get previous session summaries, most recent first."""
        if limit is None:
            limit = self._config.memory_summary_count
        rows = await self._db.fetchall(
            """SELECT k.key, k.value, k.updated_at
               FROM knowledge k
               WHERE k.key LIKE 'session:summary:%'
               AND k.key IN (
                   SELECT 'session:summary:' || claude_session_id
                   FROM sessions
                   WHERE chat_id = ?
               )
               ORDER BY k.updated_at DESC
               LIMIT ?""",
            (chat_id, limit),
        )
        return [
            {"key": r[0], "value": r[1], "updated_at": r[2]}
            for r in rows
        ]

    # Sorted longest-first so the most specific keyword matches first
    _RECALL_KEYWORDS = (
        "we talked about", "what did we", "remember when",
        "last time we", "you mentioned", "we discussed",
        "earlier you", "you said", "did we", "previously",
    )

    async def assemble_context(self, chat_id: str, session_id: str, user_message: str = "") -> str:
        """Assemble cross-session context as markdown.

        Includes: session summaries, recent messages, relevant knowledge,
        and recall results when the user message contains recall-intent keywords.
        Truncated to max_context_tokens (~3000 words ≈ 4000 tokens).
        """
        max_chars = self._config.memory_max_context_tokens * 3  # ~3 chars per token
        parts: list[str] = []

        # Identity injection (Sprint 17 / #637) — must come FIRST in context so
        # the agent sees who-it-is before any conversational history. Gated by
        # config.inject_identity (default False for safe rollout).
        if getattr(self._config, "inject_identity", False):
            identity_max = getattr(self._config, "identity_max_bytes", 24576)
            try:
                identity_text = _load_identity_text(identity_max)
            except Exception as e:  # noqa: BLE001 - identity must never crash assembly
                log.warning("Identity injection failed: %s", e)
                identity_text = ""
            if identity_text:
                parts.append(identity_text)

        # Recall-intent detection: search past conversations when keywords present
        if user_message:
            msg_lower = user_message.lower()
            matched_kw = next((kw for kw in self._RECALL_KEYWORDS if kw in msg_lower), None)
            if matched_kw:
                # Strip recall keyword and common words to get substantive terms
                remainder = msg_lower.split(matched_kw, 1)[-1].strip().rstrip("?.")
                if not remainder:
                    remainder = msg_lower.replace(matched_kw, "").strip().rstrip("?.")
                # Filter to content words only (skip common words)
                _skip = {"do", "you", "we", "the", "a", "an", "is", "was", "were",
                         "about", "when", "how", "what", "that", "this", "it"}
                content_words = [w for w in remainder.split() if w not in _skip and len(w) > 1]
                recall_query = " ".join(content_words) if content_words else remainder
                try:
                    recall_results = await self.search_conversations(
                        recall_query or user_message, limit=10,
                    )
                    if recall_results:
                        parts.append("## Relevant Past Conversations\n")
                        for session in recall_results[:5]:
                            parts.append(
                                f"[Session {session['session_id'][:8]}] "
                                f"({session['match_count']} match{'es' if session['match_count'] != 1 else ''})"
                            )
                            for match in session["matches"][:3]:
                                parts.append(
                                    f"- [{match['role']}]: {match['snippet']}"
                                )
                            parts.append("")
                except Exception as e:
                    log.warning("Recall search failed: %s", e)

        # Previous session summaries
        summaries = await self.get_session_summaries(chat_id)
        if summaries:
            parts.append("## Previous Session Summaries\n")
            for s in summaries:
                parts.append(f"### {s['key']}\n{s['value']}\n")

        # Recent conversation messages
        messages = await self.get_recent_messages(chat_id)
        if messages:
            parts.append("## Recent Conversation\n")
            for m in messages:
                parts.append(f"**{m['role']}**: {m['content']}\n")

        # Relevant knowledge entries (salience + category-priority ordered)
        knowledge = await self._db.fetchall(
            """SELECT key, value FROM knowledge
               WHERE source IN ('operator', 'agent')
               AND (expires_at IS NULL OR expires_at > datetime('now'))
               AND (archived IS NULL OR archived = 0)
               AND salience >= ?
               ORDER BY
                   salience DESC,
                   CASE category
                       WHEN 'preference' THEN 1
                       WHEN 'person' THEN 2
                       WHEN 'project' THEN 3
                       WHEN 'decision' THEN 4
                       WHEN 'process' THEN 5
                       WHEN 'learning' THEN 6
                       WHEN 'tool' THEN 7
                       ELSE 8
                   END,
                   updated_at DESC
               LIMIT 10""",
            (SALIENCE_PRUNE_THRESHOLD,),
        )
        if knowledge:
            parts.append("## Relevant Memory\n")
            for row in knowledge:
                parts.append(f"- {row[0]} = {row[1]}\n")
            await self._reinforce_entries([row[0] for row in knowledge])
            await self._touch_last_accessed([row[0] for row in knowledge])

        context = "\n".join(parts)

        # Truncate: drop oldest summaries first
        while len(context) > max_chars and summaries:
            summaries.pop()
            parts_trimmed = []
            if summaries:
                parts_trimmed.append("## Previous Session Summaries\n")
                for s in summaries:
                    parts_trimmed.append(f"### {s['key']}\n{s['value']}\n")
            if messages:
                parts_trimmed.append("## Recent Conversation\n")
                for m in messages:
                    parts_trimmed.append(f"**{m['role']}**: {m['content']}\n")
            if knowledge:
                parts_trimmed.append("## Relevant Memory\n")
                for row in knowledge:
                    parts_trimmed.append(f"- {row[0]} = {row[1]}\n")
            context = "\n".join(parts_trimmed)

        # Hard truncate if still too long
        if len(context) > max_chars:
            context = context[:max_chars] + "\n\n[Context truncated]"

        return context

    # -- Knowledge extraction from conversations --

    async def extract_and_store_knowledge(
        self, user_text: str, assistant_text: str
    ) -> int:
        """Extract knowledge patterns from a user+assistant exchange.

        Detects operator requests to remember things and stores them.
        Returns count of entries stored.
        """
        import re

        stored = 0

        # Pattern 1: Operator explicitly asks to remember something
        # "remember that X", "remember my X is Y", "note that X"
        remember_patterns = [
            r"(?i)remember\s+(?:that\s+)?(?:my\s+)?(.+?)(?:\.|$)",
            r"(?i)(?:note|record)\s+(?:that\s+)?(.+?)(?:\.|$)",
            r"(?i)(?:always|never)\s+(.+?)(?:\.|$)",
            r"(?i)(?:i\s+prefer|my\s+preference\s+is)\s+(.+?)(?:\.|$)",
            r"(?i)(?:my\s+(?:name|favorite|fav)\s+\w+\s+is)\s+(.+?)(?:\.|$)",
            r"(?i)(?:call\s+me)\s+(.+?)(?:\.|$)",
        ]

        for pattern in remember_patterns:
            match = re.search(pattern, user_text)
            if match:
                fact = match.group(1).strip().rstrip(".")
                # Generate a key from the fact
                key_topic = re.sub(r"[^a-z0-9]+", "-", fact.lower())[:50]
                key = f"user:{key_topic}"
                value = f"Operator said: {user_text.strip()}"
                await self.store_knowledge(key, value, tags="user-fact", source="operator", category="preference")
                stored += 1
                break  # One match per message is enough

        # Pattern 2: Detect if assistant confirmed remembering
        # This catches cases where the agent said "I'll remember" but
        # the sqlite3 command may not have been executed
        if stored == 0:
            confirm_patterns = [
                r"(?i)(?:i'?ll|i\s+will)\s+remember",
                r"(?i)(?:noted|stored|saved|recorded)(?:\s+that)?(?:\s+to\s+memory)?",
                r"(?i)(?:i'?ve|i\s+have)\s+(?:stored|saved|recorded|noted)",
            ]
            for pattern in confirm_patterns:
                if re.search(pattern, assistant_text):
                    # The agent claims to have stored it — check if it actually did
                    # by looking for sqlite3 in tools_used (handled elsewhere).
                    # As a fallback, store the user's message as a user fact
                    if len(user_text) < 500:  # Only short messages
                        key_topic = re.sub(r"[^a-z0-9]+", "-", user_text.lower())[:50]
                        key = f"user:{key_topic}"
                        value = f"Operator: {user_text.strip()}"
                        await self.store_knowledge(key, value, tags="user-fact,auto-extracted", source="operator", category="preference")
                        stored += 1
                    break

        return stored

    # -- Knowledge categories and archiving --

    async def archive_knowledge(self, key: str) -> bool:
        """Archive a knowledge entry by key. Returns True if found and archived."""
        row = await self._db.fetchone("SELECT key FROM knowledge WHERE key = ?", (key,))
        if not row:
            return False
        await self._db.execute(
            "UPDATE knowledge SET archived = 1, updated_at = datetime('now') WHERE key = ?",
            (key,),
        )
        await self._db.commit()
        return True

    async def get_knowledge_by_category(
        self, category: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get knowledge entries by category (excludes archived)."""
        rows = await self._db.fetchall(
            """SELECT key, value, tags, source, updated_at
               FROM knowledge
               WHERE category = ? AND (archived IS NULL OR archived = 0)
               ORDER BY updated_at DESC
               LIMIT ?""",
            (category, limit),
        )
        return [
            {"key": r[0], "value": r[1], "tags": r[2], "source": r[3], "updated_at": r[4]}
            for r in rows
        ]

    async def fetch_all_knowledge_rows(self) -> list[dict]:
        """Fetch all non-archived knowledge rows for consolidation pipeline.

        Mem-2.5 (#1863) added ``last_accessed_at`` to the projection so the
        future tier-eviction sweep (Mem-7) can read it without a separate
        query.
        """
        rows = await self._db.fetchall(
            """SELECT key, value, category, source, salience, access_count,
                      created_at, updated_at, last_accessed_at
               FROM knowledge
               WHERE (archived IS NULL OR archived = 0)
               ORDER BY updated_at DESC""",
        )
        return [
            {
                "key": r[0],
                "value": r[1],
                "category": r[2],
                "source": r[3],
                "salience": r[4],
                "access_count": r[5],
                "created_at": r[6],
                "updated_at": r[7],
                "last_accessed_at": r[8],
            }
            for r in rows
        ]

    # -- Goals --

    async def store_goal(self, description: str, deadline_str: str | None = None) -> str:
        """Store a goal as a knowledge entry. Returns the key."""
        import re
        from ..tag_parser import parse_natural_deadline

        key_slug = re.sub(r"[^a-z0-9]+", "-", description.lower())[:40]
        key = f"goal:{key_slug}"

        goal_data = {
            "description": description,
            "status": "active",
            "created_at": datetime.now().isoformat(),
        }

        if deadline_str:
            deadline = parse_natural_deadline(deadline_str)
            if deadline:
                goal_data["deadline"] = deadline.isoformat()
            else:
                goal_data["deadline_raw"] = deadline_str

        await self.store_knowledge(
            key=key,
            value=json.dumps(goal_data),
            tags="goal",
            source="operator",
            category="project",
        )
        log.info("Stored goal: %s", key)
        return key

    async def complete_goal(self, match: str) -> bool:
        """Mark a goal as completed by fuzzy matching. Returns True if found."""
        match_lower = match.lower()
        rows = await self._db.fetchall(
            """SELECT key, value FROM knowledge
               WHERE key LIKE 'goal:%'
               AND (archived IS NULL OR archived = 0)""",
        )
        for row in rows:
            key, value = row[0], row[1]
            # Match against the key or the description in the JSON
            if match_lower in key.lower():
                return await self._finish_goal(key, value, "completed")
            try:
                data = json.loads(value)
                if match_lower in data.get("description", "").lower():
                    return await self._finish_goal(key, value, "completed")
            except (json.JSONDecodeError, AttributeError):
                if match_lower in value.lower():
                    return await self._finish_goal(key, value, "completed")
        return False

    async def cancel_goal(self, match: str) -> bool:
        """Cancel a goal by fuzzy matching. Returns True if found."""
        match_lower = match.lower()
        rows = await self._db.fetchall(
            """SELECT key, value FROM knowledge
               WHERE key LIKE 'goal:%'
               AND (archived IS NULL OR archived = 0)""",
        )
        for row in rows:
            key, value = row[0], row[1]
            if match_lower in key.lower():
                return await self._finish_goal(key, value, "cancelled")
            try:
                data = json.loads(value)
                if match_lower in data.get("description", "").lower():
                    return await self._finish_goal(key, value, "cancelled")
            except (json.JSONDecodeError, AttributeError):
                if match_lower in value.lower():
                    return await self._finish_goal(key, value, "cancelled")
        return False

    async def _finish_goal(self, key: str, value: str, status: str) -> bool:
        """Update goal status and archive it."""
        try:
            data = json.loads(value)
            data["status"] = status
            data["finished_at"] = datetime.now().isoformat()
            new_value = json.dumps(data)
        except (json.JSONDecodeError, AttributeError):
            new_value = value

        await self._db.execute(
            "UPDATE knowledge SET value = ?, archived = 1, updated_at = datetime('now') WHERE key = ?",
            (new_value, key),
        )
        await self._db.commit()
        log.info("Goal %s: %s", status, key)
        return True

    async def get_active_goals(self) -> list[dict[str, Any]]:
        """Get all active (non-archived) goals."""
        rows = await self._db.fetchall(
            """SELECT key, value, updated_at FROM knowledge
               WHERE key LIKE 'goal:%'
               AND (archived IS NULL OR archived = 0)
               ORDER BY updated_at DESC""",
        )
        goals = []
        for row in rows:
            try:
                data = json.loads(row[1])
            except (json.JSONDecodeError, AttributeError):
                data = {"description": row[1]}
            data["key"] = row[0]
            data["updated_at"] = row[2]
            goals.append(data)
        return goals

    # -- Tag processing --

    async def process_tags(self, tags: list) -> int:
        """Process parsed tags from Claude's response. Returns count of actions taken."""
        from ..tag_parser import TagType

        count = 0
        for tag in tags:
            if tag.tag_type == TagType.REMEMBER:
                import re
                key_slug = re.sub(r"[^a-z0-9]+", "-", tag.value.lower())[:50]
                await self.store_knowledge(
                    key=f"user:{key_slug}",
                    value=tag.value,
                    tags="user-fact,tag-extracted",
                    source="operator",
                    category="preference",
                )
                count += 1

            elif tag.tag_type == TagType.FORGET:
                # Fuzzy match and archive
                rows = await self._db.fetchall(
                    "SELECT key FROM knowledge WHERE (archived IS NULL OR archived = 0)",
                )
                match_lower = tag.value.lower()
                for row in rows:
                    if match_lower in row[0].lower():
                        await self.archive_knowledge(row[0])
                        count += 1
                        break
                    # Also check value
                    full_row = await self._db.fetchone(
                        "SELECT value FROM knowledge WHERE key = ?", (row[0],),
                    )
                    if full_row and match_lower in full_row[0].lower():
                        await self.archive_knowledge(row[0])
                        count += 1
                        break

            elif tag.tag_type == TagType.GOAL:
                await self.store_goal(tag.value, tag.deadline)
                count += 1

            elif tag.tag_type == TagType.DONE:
                if await self.complete_goal(tag.value):
                    count += 1

            elif tag.tag_type == TagType.CANCEL:
                if await self.cancel_goal(tag.value):
                    count += 1

        return count

    # -- Salience: reinforcement and decay --

    async def _apply_recall_learning(self, results: list[dict]) -> list[dict]:
        """Record recalled keys + boost by used_count (Board Phase 3 WS1, #2392).

        No-op (returns ``results`` unchanged) when no RecallTracker is wired,
        so the pre-Phase-3 recall path is byte-identical. When wired:
          1. records the recalled keys into the tracker's window, and
          2. re-ranks so entries with ``used_count >= threshold`` float up.
        Best-effort: any failure logs and returns the original results so a
        learning-store hiccup never breaks recall.
        """
        tracker = getattr(self, "_recall_tracker", None)
        if tracker is None or not results:
            return results
        try:
            from .recall_learning import boost_by_used_count, get_used_counts
            keys = [r["key"] for r in results if r.get("key")]
            tracker.record_recall(keys)
            used_counts = await get_used_counts(self._db, keys)
            return boost_by_used_count(results, used_counts)
        except Exception as e:  # noqa: BLE001 — recall must not break on learning
            log.warning("recall-learning boost failed, returning unboosted: %s", e)
            return results

    async def _touch_last_accessed(self, keys: list[str]) -> None:
        """Update ``last_accessed_at`` on every read — Mem-2.5 (#1863).

        Distinct from :meth:`_reinforce_entries`: that method bumps salience
        + access_count + accessed_at and is coupled to the salience-decay
        regime (only the entries that result from a search bump). This
        helper is salience-agnostic and meant for the future tier-eviction
        sweep (Mem-7) to detect "warm" entries even if they're not the
        top-N hit on any given query.

        Idempotent + cheap (single UPDATE per key, no SELECT). Empty key
        list is a no-op so caller doesn't need to guard.
        """
        if not keys:
            return
        for key in keys:
            await self._db.execute(
                "UPDATE knowledge SET last_accessed_at = datetime('now') "
                "WHERE key = ?",
                (key,),
            )
        await self._db.commit()

    async def _reinforce_entries(self, keys: list[str]) -> None:
        """Bump salience and update accessed_at for retrieved knowledge entries."""
        if not keys:
            return
        now = datetime.now().isoformat()
        for key in keys:
            await self._db.execute(
                """UPDATE knowledge
                   SET salience = MIN(salience + ?, ?),
                       accessed_at = ?,
                       access_count = access_count + 1
                   WHERE key = ?""",
                (SALIENCE_REINFORCE_AMOUNT, SALIENCE_MAX, now, key),
            )
        await self._db.commit()

    async def run_decay_sweep(self) -> dict[str, int]:
        """Apply daily salience decay and auto-archive entries below threshold.

        Returns counts of decayed and archived entries.
        """
        decayed = 0
        archived = 0

        # Decay per category (skip exempt)
        for category, rate in DECAY_RATES.items():
            cursor = await self._db.execute(
                """UPDATE knowledge
                   SET salience = salience * ?
                   WHERE category = ?
                     AND source NOT IN ('operator')
                     AND (archived IS NULL OR archived = 0)
                     AND accessed_at < datetime('now', '-1 day')""",
                (rate, category),
            )
            decayed += cursor.rowcount

        # Also decay session summaries faster (0.95/day)
        cursor = await self._db.execute(
            """UPDATE knowledge
               SET salience = salience * 0.95
               WHERE key LIKE 'session:summary:%'
                 AND (archived IS NULL OR archived = 0)
                 AND accessed_at < datetime('now', '-1 day')""",
        )
        decayed += cursor.rowcount

        # Auto-archive entries below threshold (reversible — not deleted)
        cursor = await self._db.execute(
            """UPDATE knowledge
               SET archived = 1, updated_at = datetime('now')
               WHERE salience < ?
                 AND source != 'operator'
                 AND category NOT IN ('preference', 'person')
                 AND key NOT LIKE 'goal:%'
                 AND (archived IS NULL OR archived = 0)""",
            (SALIENCE_PRUNE_THRESHOLD,),
        )
        archived = cursor.rowcount

        await self._db.commit()

        if decayed or archived:
            log.info(
                "Decay sweep: %d entries decayed, %d auto-archived",
                decayed, archived,
            )

        return {"decayed": decayed, "archived": archived}
