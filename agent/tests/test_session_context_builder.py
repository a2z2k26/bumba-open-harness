"""Tests for session context builder."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from bridge.session_context_builder import (
    SessionContext,
    build_session_context,
    format_session_context,
    load_capsule_for_session,
    format_capsule_block,
)


class TestSessionContext:
    def test_empty_context(self):
        ctx = SessionContext(
            active_tasks=[],
            pending_approvals=[],
            stale_tasks=[],
            recent_decisions=0,
        )
        assert len(ctx.active_tasks) == 0

    def test_with_active_tasks(self):
        ctx = SessionContext(
            active_tasks=[
                {"id": 1, "title": "Implement verification", "status": "in_progress", "project": "bumba-open-harness"},
            ],
            pending_approvals=[],
            stale_tasks=[],
            recent_decisions=3,
        )
        assert len(ctx.active_tasks) == 1


class TestFormatSessionContext:
    def test_empty_context_returns_minimal(self):
        ctx = SessionContext(active_tasks=[], pending_approvals=[], stale_tasks=[], recent_decisions=0)
        result = format_session_context(ctx)
        assert result is None or result == ""

    def test_active_tasks_formatted(self):
        ctx = SessionContext(
            active_tasks=[
                {"id": 12, "title": "Implement verification hooks", "status": "in_progress", "project": "bumba-open-harness"},
                {"id": 15, "title": "Review API security", "status": "review", "project": "business"},
            ],
            pending_approvals=[],
            stale_tasks=[],
            recent_decisions=2,
        )
        result = format_session_context(ctx)
        assert "Implement verification hooks" in result
        assert "Review API security" in result
        assert "#12" in result
        assert "in_progress" in result

    def test_stale_tasks_flagged(self):
        ctx = SessionContext(
            active_tasks=[],
            pending_approvals=[],
            stale_tasks=[
                {"id": 5, "title": "Old stuck task", "status": "in_progress", "updated_at": "2026-03-30"},
            ],
            recent_decisions=0,
        )
        result = format_session_context(ctx)
        assert "stale" in result.lower() or "Old stuck task" in result

    def test_pending_approvals_mentioned(self):
        ctx = SessionContext(
            active_tasks=[],
            pending_approvals=[
                {"id": 1, "key": "some-key", "action": "update", "new_value": "x", "reason": "fix"},
                {"id": 2, "key": "other-key", "action": "delete", "new_value": "", "reason": "cleanup"},
            ],
            stale_tasks=[],
            recent_decisions=0,
        )
        result = format_session_context(ctx)
        assert result is not None
        assert "2" in result

    def test_recent_decisions_included(self):
        ctx = SessionContext(
            active_tasks=[],
            pending_approvals=[],
            stale_tasks=[],
            recent_decisions=5,
        )
        result = format_session_context(ctx)
        assert result is not None
        assert "5" in result


class TestBuildSessionContext:
    @pytest.mark.asyncio
    async def test_build_with_empty_db(self):
        """build_session_context handles empty/missing tables gracefully."""
        db = MagicMock()
        db.fetchall = AsyncMock(side_effect=Exception("no such table"))
        db.fetchone = AsyncMock(side_effect=Exception("no such table"))

        ctx = await build_session_context(db)
        assert isinstance(ctx, SessionContext)
        assert ctx.active_tasks == []
        assert ctx.stale_tasks == []

    @pytest.mark.asyncio
    async def test_build_with_active_tasks(self):
        """build_session_context returns tasks from task_pipeline."""
        task_row = {"id": 7, "title": "Refactor auth", "status": "in_progress",
                    "priority": "high", "assigned_to": None, "project": "bumba-open-harness",
                    "updated_at": "2026-04-04T10:00:00+00:00"}

        call_count = 0

        async def fake_fetchall(query, *args):
            nonlocal call_count
            call_count += 1
            if "task_pipeline" in query:
                return [task_row]
            return []

        db = MagicMock()
        db.fetchall = fake_fetchall
        db.fetchone = AsyncMock(return_value={"cnt": 0})

        ctx = await build_session_context(db)
        assert len(ctx.active_tasks) == 1
        assert ctx.active_tasks[0]["title"] == "Refactor auth"


# ---------------------------------------------------------------------------
# E1.3 — capsule injection tests
# ---------------------------------------------------------------------------

_VALID_CAPSULE = {
    "capsule_version": 1,
    "session_id": "sess-abc",
    "created_at": "2026-05-05T10:00:00+00:00",
    "active_sprint": "E1.3",
    "active_pr": 1235,
    "active_tasks": ["Implement capsule injection"],
    "files_in_flight": ["agent/bridge/session_context_builder.py"],
    "workflow_state": {},
    "recent_decisions": ["decided to use verbatim JSON"],
    "open_questions": [],
    "tool_usage": {"Edit": 3},
    "permission_summary": [],
    "last_handoff_reason": "context_pressure_compact_now",
    "message_count_before": 42,
    "estimated_tokens_before": 80000,
}


class TestLoadCapsuleForSession:
    def test_returns_dict_for_valid_capsule(self, tmp_path: Path) -> None:
        (tmp_path / "sess-abc.json").write_text(json.dumps(_VALID_CAPSULE))
        result = load_capsule_for_session("sess-abc", tmp_path)
        assert result is not None
        assert result["capsule_version"] == 1
        assert result["active_sprint"] == "E1.3"

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert load_capsule_for_session("no-such-session", tmp_path) is None

    def test_returns_none_for_corrupt_json(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("{not valid json")
        assert load_capsule_for_session("bad", tmp_path) is None

    def test_returns_none_for_version_mismatch(self, tmp_path: Path) -> None:
        capsule = {**_VALID_CAPSULE, "capsule_version": 2}
        (tmp_path / "v2.json").write_text(json.dumps(capsule))
        assert load_capsule_for_session("v2", tmp_path) is None

    def test_returns_none_for_missing_version_key(self, tmp_path: Path) -> None:
        capsule = {k: v for k, v in _VALID_CAPSULE.items() if k != "capsule_version"}
        (tmp_path / "nover.json").write_text(json.dumps(capsule))
        assert load_capsule_for_session("nover", tmp_path) is None

    def test_accepts_extra_fields_forward_compat(self, tmp_path: Path) -> None:
        capsule = {**_VALID_CAPSULE, "future_field": "ignored"}
        (tmp_path / "sess-fwd.json").write_text(json.dumps(capsule))
        result = load_capsule_for_session("sess-fwd", tmp_path)
        assert result is not None
        assert result.get("future_field") == "ignored"


class TestFormatCapsuleBlock:
    def test_header_present(self) -> None:
        block = format_capsule_block(_VALID_CAPSULE)
        assert "RESUMED FROM CAPSULE (capsule_version=1):" in block

    def test_fenced_json(self) -> None:
        block = format_capsule_block(_VALID_CAPSULE)
        assert "```json" in block
        assert "```" in block

    def test_capsule_fields_in_output(self) -> None:
        block = format_capsule_block(_VALID_CAPSULE)
        assert '"active_sprint": "E1.3"' in block
        assert '"active_pr": 1235' in block


class TestFormatSessionContextCapsule:
    def test_capsule_prepended_before_tasks(self) -> None:
        ctx = SessionContext(
            active_tasks=[{"id": 1, "title": "Some task", "status": "in_progress", "project": ""}],
            pending_approvals=[],
            stale_tasks=[],
            recent_decisions=0,
            capsule_block="RESUMED FROM CAPSULE (capsule_version=1):\n```json\n{}\n```",
        )
        result = format_session_context(ctx)
        assert result is not None
        capsule_pos = result.index("RESUMED FROM CAPSULE")
        tasks_pos = result.index("ACTIVE TASKS")
        assert capsule_pos < tasks_pos

    def test_capsule_only_context_not_none(self) -> None:
        ctx = SessionContext(
            active_tasks=[],
            pending_approvals=[],
            stale_tasks=[],
            recent_decisions=0,
            capsule_block="RESUMED FROM CAPSULE (capsule_version=1):\n```json\n{}\n```",
        )
        result = format_session_context(ctx)
        assert result is not None
        assert "RESUMED FROM CAPSULE" in result

    def test_no_capsule_no_change_in_output(self) -> None:
        ctx = SessionContext(
            active_tasks=[{"id": 2, "title": "Task", "status": "review", "project": ""}],
            pending_approvals=[],
            stale_tasks=[],
            recent_decisions=0,
        )
        result = format_session_context(ctx)
        assert result is not None
        assert "RESUMED FROM CAPSULE" not in result


class TestBuildSessionContextCapsule:
    @pytest.mark.asyncio
    async def test_capsule_block_populated_when_found(self, tmp_path: Path) -> None:
        (tmp_path / "sess-xyz.json").write_text(json.dumps(_VALID_CAPSULE))
        db = MagicMock()
        db.fetchall = AsyncMock(side_effect=Exception("empty"))
        db.fetchone = AsyncMock(side_effect=Exception("empty"))
        ctx = await build_session_context(db, session_id="sess-xyz", checkpoint_dir=tmp_path)
        assert ctx.capsule_block != ""
        assert "RESUMED FROM CAPSULE" in ctx.capsule_block

    @pytest.mark.asyncio
    async def test_capsule_block_empty_when_no_file(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.fetchall = AsyncMock(side_effect=Exception("empty"))
        db.fetchone = AsyncMock(side_effect=Exception("empty"))
        ctx = await build_session_context(db, session_id="missing", checkpoint_dir=tmp_path)
        assert ctx.capsule_block == ""

    @pytest.mark.asyncio
    async def test_no_capsule_args_skips_lookup(self) -> None:
        db = MagicMock()
        db.fetchall = AsyncMock(side_effect=Exception("empty"))
        db.fetchone = AsyncMock(side_effect=Exception("empty"))
        ctx = await build_session_context(db)
        assert ctx.capsule_block == ""
