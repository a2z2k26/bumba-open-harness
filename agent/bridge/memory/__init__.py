"""Conversation storage, knowledge queries, FTS5 search, context assembly, salience decay.

This module is a thin facade re-exporting the public API of the
``conversation`` and ``knowledge`` submodules. The previous monolith at
``bridge/memory.py`` was split per PR #1687 precedent (refs #1305) — the
``Memory`` class is now composed from ``ConversationMixin`` +
``KnowledgeMixin``.

External callers continue to use ``from bridge.memory import Memory`` (and
``MemoryKVAdapter``, ``KNOWLEDGE_CATEGORIES``, ``SALIENCE_MAX``, etc.)
exactly as before — Python resolves ``bridge.memory`` to this package's
``__init__.py``.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from ..config import BridgeConfig
from ..database import Database
from ..memory_wal import MemoryWAL
from .conversation import ConversationMixin, _escape_fts5_query
from .knowledge import (
    DECAY_EXEMPT_CATEGORIES,
    DECAY_EXEMPT_SOURCES,
    DECAY_RATES,
    IDENTITY_FILES,
    KNOWLEDGE_CATEGORIES,
    SALIENCE_MAX,
    SALIENCE_PRUNE_THRESHOLD,
    SALIENCE_REINFORCE_AMOUNT,
    KnowledgeMixin,
    MemoryKVAdapter,
)

__all__ = [
    "DECAY_EXEMPT_CATEGORIES",
    "DECAY_EXEMPT_SOURCES",
    "DECAY_RATES",
    "IDENTITY_FILES",
    "KNOWLEDGE_CATEGORIES",
    "Memory",
    "MemoryKVAdapter",
    "SALIENCE_MAX",
    "SALIENCE_PRUNE_THRESHOLD",
    "SALIENCE_REINFORCE_AMOUNT",
    "_escape_fts5_query",
]


class Memory(ConversationMixin, KnowledgeMixin):
    """Manages conversation history, knowledge store, and context assembly."""

    def __init__(
        self,
        db: Database,
        config: BridgeConfig,
        embedding_client=None,
        metrics=None,
        hybrid_search=None,
        wal: MemoryWAL | None = None,
    ) -> None:
        self._db = db
        self._config = config
        self._context_file: Path | None = None
        self._embedding_client = embedding_client
        self._metrics = metrics  # MetricsCollector, optional
        # Sprint 05.02 — HybridSearch (RRF fusion of FTS5 + vector search).
        # Plumbing only in this sprint; consumption in `search_knowledge`
        # lands in Sprint 05.03. Wired at construction OR via
        # `set_hybrid_search` from the BridgeApp wiring manifest after
        # HybridSearch is built (manifest convention from Plan 01).
        self._hybrid_search = hybrid_search
        # Sprint 03.06 — memory write-ahead log. Caller may inject; if None
        # the WAL is constructed in disabled mode (no-op) so existing
        # callers (and tests) don't have to pass anything until the
        # operator flips memory_wal_enabled.
        if wal is not None:
            self._wal = wal
        else:
            wal_path = Path(config.data_dir) / config.memory_wal_path
            self._wal = MemoryWAL(
                wal_path,
                enabled=getattr(config, "memory_wal_enabled", False),
            )
        # P2.5 (#1721) — retain references to background embedding tasks
        # so they cannot be GC'd mid-flight. Pattern mirrors
        # ``app.py:3033-3203``.
        self._pending_tasks: set[asyncio.Task] = set()
        # Sprint Mem-4 (#1845) — DualWritePipeline injection point. Wired
        # by ``BridgeApp._initialize`` via the WIRING_MANIFEST entry; left
        # as None when ``memory_tiers_enabled`` is False (flag-off path is
        # byte-identical to pre-Mem-4 because ``store_knowledge`` checks
        # both the flag AND this attribute before invoking the pipeline).
        self._dual_write_pipeline = None
        self._dual_write_missing_warned = False
        # Board Phase 3 WS1 (#2392) — learning knowledge store. When wired,
        # search_knowledge records recalled keys into the tracker and boosts
        # results whose used_count >= threshold. Left None by default so the
        # flag-off / un-wired path is byte-identical to pre-Phase-3 recall.
        self._recall_tracker = None

    def set_recall_tracker(self, recall_tracker) -> None:
        """Wire the RecallTracker post-construction (Board Phase 3 WS1, #2392).

        Setter form so the wire registers in the WIRING_MANIFEST. When unset,
        recall behaves exactly as before (no recording, no used_count boost).
        """
        self._recall_tracker = recall_tracker

    def set_hybrid_search(self, hybrid_search) -> None:
        """Wire HybridSearch post-construction.

        Called by the BridgeApp wiring manifest after `HybridSearch` is
        built (it is constructed later in `_initialize` than `Memory`).
        Sprint 05.02 ships this setter; Sprint 05.03 makes
        `search_knowledge` consume it.
        """
        self._hybrid_search = hybrid_search

    # -- S56: Context file writer --

    def write_context_file(self, context: str) -> Path:
        """Write context to a temp file for --append-system-prompt-file."""
        fd, path = tempfile.mkstemp(prefix="bumba-context-", suffix=".md")
        with open(fd, "w") as f:
            f.write(context)
        self._context_file = Path(path)
        return self._context_file

    def cleanup_context_file(self) -> None:
        """Remove the temp context file."""
        if self._context_file and self._context_file.exists():
            self._context_file.unlink()
            self._context_file = None
