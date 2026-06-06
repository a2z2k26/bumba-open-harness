"""Learning knowledge store — recall-usage tracking (Board Phase 3 WS1, #2392).

The knowledge base accumulates entries but never improves retrieval quality
from operator usage. This module closes that loop without touching the public
``memory_manager`` API:

- **RecallTracker** holds a short in-memory window of recently-recalled keys
  (``record_recall``). When the operator *acts on* a recalled memory within the
  window (default 5 min), ``mark_used`` increments ``used_count`` for exactly
  the keys that were recalled recently — the "act within 5 min" signal from the
  acceptance criteria.
- ``boost_by_used_count`` is a pure re-rank: entries with ``used_count >= 3``
  float to the top of a recall result list, preserving relative order within
  each band (stable). Applied as a post-processing pass over whatever the
  underlying search branch returned.
- ``flag_stale_unused`` returns ``used_count == 0`` entries older than 90 days
  for the consolidation-review service.

DB ops take a ``db`` handle exposing ``execute`` / ``commit`` / ``fetchall``
(the bridge ``Database`` contract) so the tracker stays decoupled from the
``Memory`` object and is unit-testable against an in-memory SQLite.

Seam note (config↔runtime, registry↔wiring): ``used_count`` is the producer;
the consumers are ``boost_by_used_count`` (recall rank) and ``flag_stale_unused``
(consolidation). Both read the same column this module writes — verified
together in ``tests/test_recall_learning.py``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Threshold at which a memory's repeated usefulness boosts its recall rank.
USED_COUNT_BOOST_THRESHOLD = 3

# Default window: the operator "acted on" a recall if the action lands within
# this many seconds of the recall surfacing the key.
DEFAULT_RECALL_WINDOW_SECONDS = 300.0

# Age beyond which a never-used memory is flagged for consolidation review.
STALE_UNUSED_AGE_DAYS = 90


@dataclass
class RecallTracker:
    """In-memory window of recently-recalled knowledge keys.

    Not persisted — a bridge restart simply starts the window empty, which is
    correct: a recall the operator never acted on before the restart should
    not be retro-credited. One tracker per bridge process.
    """

    window_seconds: float = DEFAULT_RECALL_WINDOW_SECONDS
    _recalled: dict[str, float] = field(default_factory=dict)

    def record_recall(self, keys: list[str], *, now: float | None = None) -> None:
        """Record that ``keys`` were surfaced by a recall at ``now``."""
        if not keys:
            return
        ts = time.monotonic() if now is None else now
        for key in keys:
            self._recalled[key] = ts

    def recent_keys(self, *, now: float | None = None) -> list[str]:
        """Keys recalled within the window, pruning anything older."""
        ts = time.monotonic() if now is None else now
        live = [k for k, t in self._recalled.items() if (ts - t) <= self.window_seconds]
        # Prune expired entries so the dict can't grow unbounded.
        self._recalled = {k: self._recalled[k] for k in live}
        return live

    async def mark_used(self, db, candidate_keys: list[str], *, now: float | None = None) -> list[str]:
        """Increment ``used_count`` for candidate keys recalled within the window.

        ``candidate_keys`` is what the operator just acted on (e.g. keys
        referenced by the next action). Only those that were *recently recalled*
        are credited — acting on a key that was never recalled does not count.
        Returns the keys that were credited.
        """
        recent = set(self.recent_keys(now=now))
        credited = [k for k in candidate_keys if k in recent]
        if not credited:
            return []
        await increment_used_count(db, credited)
        # A key is credited once per recall window — drop it so a single recall
        # cannot be double-counted by two rapid actions.
        for k in credited:
            self._recalled.pop(k, None)
        return credited


async def increment_used_count(db, keys: list[str]) -> None:
    """Increment ``used_count`` and stamp ``last_recalled_at`` for ``keys``."""
    if not keys:
        return
    for key in keys:
        await db.execute(
            "UPDATE knowledge SET used_count = used_count + 1, "
            "last_recalled_at = datetime('now') WHERE key = ?",
            (key,),
        )
    await db.commit()


async def get_used_counts(db, keys: list[str]) -> dict[str, int]:
    """Return ``{key: used_count}`` for the given keys (missing keys omitted)."""
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    rows = await db.fetchall(
        f"SELECT key, used_count FROM knowledge WHERE key IN ({placeholders})",
        tuple(keys),
    )
    return {r[0]: int(r[1] or 0) for r in rows}


def boost_by_used_count(
    results: list[dict],
    used_counts: dict[str, int],
    *,
    threshold: int = USED_COUNT_BOOST_THRESHOLD,
) -> list[dict]:
    """Stable re-rank: entries with ``used_count >= threshold`` float to the top.

    Pure function — returns a new list, never mutates ``results`` or its dicts.
    Within the boosted band and within the unboosted band, the original
    relative order is preserved (so the underlying search relevance still
    governs ties). Each returned dict carries an added ``used_count`` field for
    observability; the original dicts are left untouched.
    """
    boosted: list[dict] = []
    rest: list[dict] = []
    for r in results:
        uc = int(used_counts.get(r.get("key"), 0) or 0)
        annotated = {**r, "used_count": uc}
        if uc >= threshold:
            boosted.append(annotated)
        else:
            rest.append(annotated)
    return boosted + rest


async def flag_stale_unused(db, *, age_days: int = STALE_UNUSED_AGE_DAYS, limit: int = 100) -> list[dict]:
    """Return never-used (``used_count == 0``) entries older than ``age_days``.

    Feeds the consolidation-review service: these are candidates for archival
    or summarization because the operator has never acted on them in recall.
    Excludes already-archived rows.
    """
    rows = await db.fetchall(
        """SELECT key, created_at, used_count
           FROM knowledge
           WHERE used_count = 0
             AND (archived IS NULL OR archived = 0)
             AND created_at IS NOT NULL
             AND julianday('now') - julianday(created_at) > ?
           ORDER BY created_at ASC
           LIMIT ?""",
        (age_days, limit),
    )
    return [
        {"key": r[0], "created_at": r[1], "used_count": int(r[2] or 0)}
        for r in rows
    ]
