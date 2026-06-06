"""Conversation storage and FTS5 search — half of the Memory mixin pair.

Provides:
- ``ConversationMixin`` — message store/retrieve/search methods composed into
  ``Memory`` in ``bridge/memory/__init__.py``.
- ``_escape_fts5_query`` — shared FTS5 query-escaping helper, imported by both
  this module and ``knowledge.py``.

Split from the monolithic ``bridge/memory.py`` per PR #1687 precedent
(refs #1305).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..memory_writes import MemoryWriteReceipt, emit as _emit_write_receipt

if TYPE_CHECKING:
    from ..config import BridgeConfig
    from ..database import Database

log = logging.getLogger(__name__)


def _escape_fts5_query(query: str) -> str:
    """Escape a user query string for safe FTS5 MATCH usage.

    Wraps each whitespace-delimited token in double quotes to prevent
    FTS5 operator interpretation (-, *, AND, OR, NOT, NEAR, etc.).
    Empty queries return a wildcard match.
    """
    tokens = query.strip().split()
    if not tokens:
        return "*"
    escaped = []
    for token in tokens:
        clean = token.replace('"', '""')  # Escape embedded quotes
        escaped.append(f'"{clean}"')
    return " ".join(escaped)  # Implicit AND between quoted terms


class ConversationMixin:
    """Conversation-side methods of the ``Memory`` class.

    Provides message storage, recent/session retrieval, and FTS5-backed
    conversation search. Mixed into ``Memory`` together with
    ``KnowledgeMixin`` — see ``bridge/memory/__init__.py``.
    """

    # Slots populated by the concrete ``Memory`` class. Declared here so
    # this mixin is type-checkable in isolation (Sprint S3.3, #2342).
    # Strings rather than direct imports avoid runtime circularity with
    # the ``bridge.database`` -> ``bridge.db`` -> back-to ``bridge.memory``
    # facade load order.
    _db: "Database"
    _config: "BridgeConfig"

    # -- S54: Store and retrieve conversations --

    async def store_message(
        self,
        session_id: str,
        chat_id: str,
        role: str,
        content: str,
        platform_message_id: int | None = None,
        tools_used: str | None = None,
        cost_usd: float | None = None,
        duration_ms: int | None = None,
    ) -> int:
        """Store a conversation message. Returns the row ID."""
        cursor = await self._db.execute(
            """INSERT INTO conversations
               (session_id, chat_id, role, content, platform_message_id,
                tools_used, cost_usd, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, chat_id, role, content, platform_message_id,
             tools_used, cost_usd, duration_ms),
        )
        await self._db.commit()
        row_id = cursor.lastrowid or 0
        # D2.3 — emit write receipt for operator observability
        try:
            _emit_write_receipt(MemoryWriteReceipt.now(
                subsystem="conversation", op="insert",
                key=f"{session_id}:{role}", payload_bytes=len(content or ""),
                actor="agent",
            ))
        except Exception:
            pass
        return row_id

    async def get_recent_messages(
        self, chat_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Get recent conversation messages for a chat."""
        if limit is None:
            limit = self._config.memory_context_window
        rows = await self._db.fetchall(
            """SELECT role, content, created_at
               FROM conversations
               WHERE chat_id = ?
               ORDER BY id DESC
               LIMIT ?""",
            (chat_id, limit),
        )
        return [
            {"role": r[0], "content": r[1], "created_at": r[2]}
            for r in reversed(rows)
        ]

    async def get_session_messages(
        self, session_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Get conversation messages for a specific session."""
        if limit is None:
            limit = self._config.memory_context_window
        rows = await self._db.fetchall(
            """SELECT role, content, created_at
               FROM conversations
               WHERE session_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (session_id, limit),
        )
        return [
            {"role": r[0], "content": r[1], "created_at": r[2]}
            for r in reversed(rows)
        ]

    # -- Conversation search (FTS5) --

    async def search_conversations(
        self,
        query: str,
        role_filter: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """FTS5 search across conversation history.

        Returns matches grouped by session_id with snippets and context.
        """
        if role_filter is None:
            role_filter = ["user", "assistant"]

        fts_query = _escape_fts5_query(query)
        placeholders = ",".join("?" for _ in role_filter)

        try:
            rows = await self._db.fetchall(
                f"""SELECT c.session_id, c.role, c.created_at,
                           snippet(conversations_fts, 0, '**', '**', '…', 40) AS snip,
                           rank
                    FROM conversations_fts
                    JOIN conversations c ON conversations_fts.rowid = c.id
                    WHERE conversations_fts MATCH ?
                      AND c.role IN ({placeholders})
                    ORDER BY rank
                    LIMIT ?""",
                (fts_query, *role_filter, limit),
            )
        except Exception as e:
            log.warning("Conversation FTS5 search failed for %r: %s", fts_query, e)
            return []

        if not rows:
            return []

        # Group by session_id, collect snippets
        from collections import OrderedDict
        sessions: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for row in rows:
            sid = row[0]
            if sid not in sessions:
                sessions[sid] = {
                    "session_id": sid,
                    "matches": [],
                    "match_count": 0,
                }
            sessions[sid]["matches"].append({
                "role": row[1],
                "created_at": row[2],
                "snippet": row[3],
            })
            sessions[sid]["match_count"] += 1

        # Add 1 message of context before/after each matched session
        result_list = []
        for sid, session_data in sessions.items():
            # Get surrounding context for the session
            ctx_rows = await self._db.fetchall(
                """SELECT role, content, created_at
                   FROM conversations
                   WHERE session_id = ?
                   ORDER BY id
                   LIMIT 20""",
                (sid,),
            )
            session_data["context"] = [
                {"role": r[0], "content": r[1][:200], "created_at": r[2]}
                for r in ctx_rows
            ]
            result_list.append(session_data)

        return result_list
