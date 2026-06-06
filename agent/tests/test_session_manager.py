"""Tests for bridge.session_manager (S59)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


class TestSessionLifecycle:
    """S57: All 7 session lifecycle triggers."""

    @pytest.mark.asyncio
    async def test_create_first_session(self, session_manager):
        """Trigger 1: First message ever → create new."""
        session_id = await session_manager.create_session("chat-1")
        assert session_id  # UUID string
        assert len(session_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_resolve_active_session(self, session_manager):
        """Trigger 2: Message within idle timeout → resume."""
        sid = await session_manager.create_session("chat-1")
        await session_manager.update_session(sid)

        resolved = await session_manager.resolve_session("chat-1")
        assert resolved == sid

    @pytest.mark.asyncio
    async def test_resolve_after_idle_timeout(self, session_manager, migrated_db):
        """Trigger 3: Message after idle timeout → expire + new."""
        sid = await session_manager.create_session("chat-1")

        # Simulate old last_active_at (2 hours ago)
        await migrated_db.execute(
            """UPDATE sessions
               SET last_active_at = datetime('now', '-2 hours')
               WHERE claude_session_id = ?""",
            (sid,),
        )
        await migrated_db.commit()

        resolved = await session_manager.resolve_session("chat-1")
        assert resolved is None  # Expired, need new session

    @pytest.mark.asyncio
    async def test_resolve_none(self, session_manager):
        """No session exists → None."""
        resolved = await session_manager.resolve_session("chat-never")
        assert resolved is None

    @pytest.mark.asyncio
    async def test_handle_reset(self, session_manager):
        """Trigger 4: /reset → expire current, create new."""
        old_sid = await session_manager.create_session("chat-1")
        new_sid = await session_manager.handle_reset("chat-1")

        assert new_sid != old_sid
        # Old session should be expired
        resolved = await session_manager.resolve_session("chat-1")
        assert resolved == new_sid

    @pytest.mark.asyncio
    async def test_force_expire(self, session_manager):
        """Force expire all active sessions for a chat."""
        await session_manager.create_session("chat-1")
        await session_manager.force_expire("chat-1")

        resolved = await session_manager.resolve_session("chat-1")
        assert resolved is None

    @pytest.mark.asyncio
    async def test_unique_active_constraint(self, session_manager, migrated_db):
        """Only one active session per chat_id (enforced by unique index)."""
        await session_manager.create_session("chat-1")

        # Creating a second without expiring the first should fail
        with pytest.raises(Exception):
            await session_manager.create_session("chat-1")


class TestSessionUpdates:
    """S57/S58: Session updates and stats."""

    @pytest.mark.asyncio
    async def test_update_session_stats(self, session_manager, migrated_db):
        sid = await session_manager.create_session("chat-1")
        await session_manager.update_session(sid, cost_usd=0.05)
        await session_manager.update_session(sid, cost_usd=0.03)

        row = await migrated_db.fetchone(
            "SELECT message_count, total_cost_usd FROM sessions WHERE claude_session_id = ?",
            (sid,),
        )
        assert row[0] == 2
        assert abs(row[1] - 0.08) < 0.001

    @pytest.mark.asyncio
    async def test_expire_with_summary(self, session_manager, migrated_db):
        sid = await session_manager.create_session("chat-1")
        await session_manager.expire_with_summary(
            "chat-1", sid, "idle_timeout", "Discussed auth refactor."
        )

        # Session should be expired
        resolved = await session_manager.resolve_session("chat-1")
        assert resolved is None

        # Summary should be in knowledge
        row = await migrated_db.fetchone(
            "SELECT value FROM knowledge WHERE key = ?",
            (f"session:summary:{sid}",),
        )
        assert row[0] == "Discussed auth refactor."

    @pytest.mark.asyncio
    async def test_get_session_stats(self, session_manager):
        sid = await session_manager.create_session("chat-1")
        await session_manager.update_session(sid, cost_usd=0.10)

        stats = await session_manager.get_session_stats()
        assert stats["active_session"]["session_id"] == sid
        assert stats["active_session"]["message_count"] == 1
        assert stats["total_sessions"] == 1


class TestErrorAndFileChecks:
    """S58: Error count and file size checks."""

    @pytest.mark.asyncio
    async def test_error_count_below_threshold(self, session_manager, migrated_db):
        sid = await session_manager.create_session("chat-1")
        # Only 1 error, threshold is 3
        await migrated_db.execute(
            "INSERT INTO conversations (session_id, chat_id, role, content) VALUES (?, ?, 'system', 'error: timeout')",
            (sid, "chat-1"),
        )
        await migrated_db.commit()

        should_expire = await session_manager.check_error_count(sid)
        assert should_expire is False

    @pytest.mark.asyncio
    async def test_error_count_exceeds_threshold(self, session_manager, migrated_db):
        sid = await session_manager.create_session("chat-1")
        for i in range(3):
            await migrated_db.execute(
                "INSERT INTO conversations (session_id, chat_id, role, content) VALUES (?, ?, 'system', 'error: timeout')",
                (sid, "chat-1"),
            )
        await migrated_db.commit()

        should_expire = await session_manager.check_error_count(sid)
        assert should_expire is True


class TestExpiryEdgeCases:
    """Issue #1539 — explicit coverage for the three documented expiry triggers
    (idle / file-size / 3-error) plus concurrent expiry attempts and session
    resumption after expiry.

    Trigger source map (see `bridge/session_manager.py`):
      - idle_timeout: ``resolve_session`` calls ``_expire_session`` when
        ``(now - last_active_at) > session_idle_timeout``.
      - file-size:    ``check_session_file_size`` returns True when the
        ``~/.claude/projects/<session_id>.jsonl`` file exceeds
        ``session_max_file_size`` (default 30 MB).
      - 3-error:      ``check_error_count`` returns True when the last
        ``session_max_errors`` (default 3) conversation rows are all
        error-tagged ``system`` messages.
      - concurrent:   ``force_expire``'s ``WHERE status = 'active'`` predicate
        means the second concurrent call sees zero active rows; only one
        chat_id→expired transition is recorded.
    """

    # -- idle timeout (30min by default) --

    @pytest.mark.asyncio
    async def test_idle_timeout_expiry_records_reason(
        self, session_manager, migrated_db
    ):
        """Idle timeout path stamps ``expired_reason = 'idle_timeout'``."""
        sid = await session_manager.create_session("chat-idle")

        # Simulate the session sitting idle for 2h (> default 1800s timeout).
        await migrated_db.execute(
            """UPDATE sessions
               SET last_active_at = datetime('now', '-2 hours')
               WHERE claude_session_id = ?""",
            (sid,),
        )
        await migrated_db.commit()

        # resolve_session triggers _expire_session("idle_timeout").
        resolved = await session_manager.resolve_session("chat-idle")
        assert resolved is None

        row = await migrated_db.fetchone(
            """SELECT status, expired_reason
               FROM sessions WHERE claude_session_id = ?""",
            (sid,),
        )
        assert row[0] == "expired"
        assert row[1] == "idle_timeout"

    # -- file-size trigger (>30MB) --

    @pytest.mark.asyncio
    async def test_file_size_below_threshold_does_not_expire(
        self, session_manager, tmp_path, monkeypatch
    ):
        """File at or below ``session_max_file_size`` → check returns False."""
        sid = await session_manager.create_session("chat-fs-small")
        # Point check_session_file_size at a fake home dir.
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        projects_dir = tmp_path / ".claude" / "projects" / "fake-project"
        projects_dir.mkdir(parents=True)
        jsonl = projects_dir / f"{sid}.jsonl"
        # 1 KB — far below 30 MB default.
        jsonl.write_bytes(b"x" * 1024)

        should_expire = await session_manager.check_session_file_size(sid)
        assert should_expire is False

    @pytest.mark.asyncio
    async def test_file_size_exceeds_threshold_expires(
        self, session_manager, tmp_path, monkeypatch
    ):
        """File >``session_max_file_size`` → check returns True; expire records
        ``expired_reason = 'file_size'`` after the operator's expire call.
        """
        sid = await session_manager.create_session("chat-fs-big")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        projects_dir = tmp_path / ".claude" / "projects" / "fake-project"
        projects_dir.mkdir(parents=True)
        jsonl = projects_dir / f"{sid}.jsonl"
        # Write 1 byte past the configured ceiling (sample_config: 31_457_280).
        threshold = session_manager._config.session_max_file_size
        with jsonl.open("wb") as fh:
            fh.truncate(threshold + 1)

        should_expire = await session_manager.check_session_file_size(sid)
        assert should_expire is True

        # Caller is responsible for invoking expire_with_summary; verify the
        # rest of the pipeline records the trigger reason verbatim.
        await session_manager.expire_with_summary(
            "chat-fs-big", sid, "file_size", None
        )
        resolved = await session_manager.resolve_session("chat-fs-big")
        assert resolved is None

    @pytest.mark.asyncio
    async def test_file_size_missing_projects_dir_returns_false(
        self, session_manager, tmp_path, monkeypatch
    ):
        """Missing ``~/.claude/projects`` → check returns False (no spurious
        expiry when Claude Code hasn't created its state dir yet).
        """
        sid = await session_manager.create_session("chat-fs-missing")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # No .claude/projects directory at all.
        should_expire = await session_manager.check_session_file_size(sid)
        assert should_expire is False

    # -- 3-error trigger --

    @pytest.mark.asyncio
    async def test_three_error_trigger_expires_with_reason(
        self, session_manager, migrated_db
    ):
        """3 consecutive error rows → check returns True; expiry records
        ``expired_reason = 'error_count'``.
        """
        sid = await session_manager.create_session("chat-3err")
        for _ in range(3):
            await migrated_db.execute(
                """INSERT INTO conversations (session_id, chat_id, role, content)
                   VALUES (?, ?, 'system', 'error: subprocess timeout')""",
                (sid, "chat-3err"),
            )
        await migrated_db.commit()

        assert await session_manager.check_error_count(sid) is True

        await session_manager.expire_with_summary(
            "chat-3err", sid, "error_count", None
        )

        row = await migrated_db.fetchone(
            """SELECT status, expired_reason
               FROM sessions WHERE claude_session_id = ?""",
            (sid,),
        )
        assert row[0] == "expired"
        assert row[1] == "error_count"

    @pytest.mark.asyncio
    async def test_error_count_recovers_when_non_error_intervenes(
        self, session_manager, migrated_db
    ):
        """A non-error row breaks the consecutive-error streak."""
        sid = await session_manager.create_session("chat-3err-recover")
        # Two errors, then a non-error system message, then one error.
        # ORDER BY created_at DESC LIMIT 3 → last three should NOT all be error.
        for _ in range(2):
            await migrated_db.execute(
                """INSERT INTO conversations (session_id, chat_id, role, content)
                   VALUES (?, ?, 'system', 'error: oops')""",
                (sid, "chat-3err-recover"),
            )
        await migrated_db.execute(
            """INSERT INTO conversations (session_id, chat_id, role, content)
               VALUES (?, ?, 'assistant', 'OK, recovered.')""",
            (sid, "chat-3err-recover"),
        )
        await migrated_db.execute(
            """INSERT INTO conversations (session_id, chat_id, role, content)
               VALUES (?, ?, 'system', 'error: again')""",
            (sid, "chat-3err-recover"),
        )
        await migrated_db.commit()

        assert await session_manager.check_error_count(sid) is False

    # -- concurrent expiry attempt --

    @pytest.mark.asyncio
    async def test_concurrent_force_expire_only_one_transitions(
        self, session_manager, migrated_db
    ):
        """Two ``force_expire`` calls dispatched via ``asyncio.gather`` against
        the same chat_id must converge to exactly ONE expired row — not two
        active rows, not a unique-index violation, and not an exception.

        The ``WHERE status = 'active'`` predicate in ``force_expire`` is the
        idempotency guard: the second call sees zero matching rows and is a
        no-op. We verify by counting rows in each terminal state.
        """
        sid = await session_manager.create_session("chat-race")

        # Two concurrent expire attempts on the same chat_id.
        await asyncio.gather(
            session_manager.force_expire("chat-race"),
            session_manager.force_expire("chat-race"),
        )

        # Exactly one row exists for this chat_id, in expired state, with the
        # operator_reset reason force_expire stamps.
        rows = await migrated_db.fetchall(
            """SELECT status, expired_reason
               FROM sessions WHERE chat_id = ?""",
            ("chat-race",),
        )
        assert len(rows) == 1, f"expected 1 session row, got {len(rows)}"
        assert rows[0][0] == "expired"
        assert rows[0][1] == "operator_reset"

        # No active session resolves for this chat_id.
        assert await session_manager.resolve_session("chat-race") is None

        # Unique-active index intact: we can still create a fresh session.
        new_sid = await session_manager.create_session("chat-race")
        assert new_sid != sid

    @pytest.mark.asyncio
    async def test_concurrent_expire_session_is_idempotent_on_row(
        self, session_manager, migrated_db
    ):
        """Two ``_expire_session`` calls on the same DB row id should both
        complete without raising and leave the row in expired state. Last
        writer wins on ``expired_reason``; nothing else should drift.
        """
        sid = await session_manager.create_session("chat-race-row")
        row = await migrated_db.fetchone(
            "SELECT id FROM sessions WHERE claude_session_id = ?", (sid,),
        )
        session_db_id = row[0]

        # Both call _expire_session against the same row. The method is
        # an unconditional UPDATE WHERE id = ?, so both succeed at DB level;
        # the test guards that neither raises and the row remains expired.
        await asyncio.gather(
            session_manager._expire_session(session_db_id, "idle_timeout"),
            session_manager._expire_session(session_db_id, "idle_timeout"),
        )

        final = await migrated_db.fetchone(
            """SELECT status, expired_reason
               FROM sessions WHERE id = ?""",
            (session_db_id,),
        )
        assert final[0] == "expired"
        assert final[1] == "idle_timeout"

    # -- resumption after expiry --

    @pytest.mark.asyncio
    async def test_new_session_after_expiry_is_not_a_resume(
        self, session_manager, migrated_db
    ):
        """After expiry, the next ``create_session`` returns a brand-new UUID
        and ``get_resume_id`` returns ``None`` (no prior-message-count row
        is eligible to resume).
        """
        old_sid = await session_manager.create_session("chat-resume")

        # Drive an idle expiry.
        await migrated_db.execute(
            """UPDATE sessions
               SET last_active_at = datetime('now', '-2 hours')
               WHERE claude_session_id = ?""",
            (old_sid,),
        )
        await migrated_db.commit()
        assert await session_manager.resolve_session("chat-resume") is None

        # New session is fresh — different UUID, status=active.
        new_sid = await session_manager.create_session("chat-resume")
        assert new_sid != old_sid
        assert len(new_sid) == 36

        row = await migrated_db.fetchone(
            """SELECT status, message_count
               FROM sessions WHERE claude_session_id = ?""",
            (new_sid,),
        )
        assert row[0] == "active"
        assert row[1] == 0

        # The expired row is NOT a resume candidate even though it once was
        # active for this chat_id — get_resume_id requires message_count > 0
        # AND status = 'active'. The new session has 0 messages, the old is
        # expired, so resume returns None.
        assert await session_manager.get_resume_id("chat-resume") is None

    @pytest.mark.asyncio
    async def test_get_resume_id_ignores_expired_sessions(
        self, session_manager, migrated_db
    ):
        """A previously-active session with messages, once expired, is NOT
        returned by ``get_resume_id`` — Claude must start clean, not pick up
        the expired conversation.
        """
        old_sid = await session_manager.create_session("chat-resume-msg")
        # Give the old session real message activity so the message_count > 0
        # branch of get_resume_id would otherwise match.
        await session_manager.update_session(old_sid, cost_usd=0.01)
        await session_manager.update_session(old_sid, cost_usd=0.01)

        # Expire via idle path.
        await migrated_db.execute(
            """UPDATE sessions
               SET last_active_at = datetime('now', '-2 hours')
               WHERE claude_session_id = ?""",
            (old_sid,),
        )
        await migrated_db.commit()
        assert await session_manager.resolve_session("chat-resume-msg") is None

        # No active session → get_resume_id returns None even though the
        # expired row has message_count = 2.
        assert await session_manager.get_resume_id("chat-resume-msg") is None
