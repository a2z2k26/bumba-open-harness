"""Tests for teams._handoff — HandoffEnvelope structured cross-department transfers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from teams._handoff import HandoffEnvelope, load_handoff, store_handoff


class TestHandoffEnvelope:
    def test_frozen(self):
        env = HandoffEnvelope(from_department="qa", to_department="design", task="Fix contrast")
        with pytest.raises((AttributeError, TypeError)):
            env.task = "other"  # type: ignore[misc]

    def test_defaults_set(self):
        env = HandoffEnvelope(from_department="qa", to_department="ops", task="deploy")
        assert env.correlation_id  # non-empty
        assert env.created_at
        assert env.findings == ""
        assert env.context_files == ()

    def test_json_round_trip(self):
        env = HandoffEnvelope(
            from_department="qa",
            to_department="strategy",
            task="Analyze failure rates",
            findings="3 critical failures found",
            context_files=("tests/test_auth.py", "tests/test_api.py"),
        )
        restored = HandoffEnvelope.from_json(env.to_json())
        assert restored.from_department == env.from_department
        assert restored.to_department == env.to_department
        assert restored.task == env.task
        assert restored.findings == env.findings
        assert restored.context_files == env.context_files
        assert restored.correlation_id == env.correlation_id
        assert restored.created_at == env.created_at

    def test_context_files_tuple_preserved(self):
        env = HandoffEnvelope(
            from_department="qa", to_department="ops", task="t",
            context_files=("a.py", "b.py"),
        )
        restored = HandoffEnvelope.from_json(env.to_json())
        assert isinstance(restored.context_files, tuple)
        assert restored.context_files == ("a.py", "b.py")

    def test_correlation_id_unique(self):
        e1 = HandoffEnvelope(from_department="qa", to_department="ops", task="t")
        e2 = HandoffEnvelope(from_department="qa", to_department="ops", task="t")
        assert e1.correlation_id != e2.correlation_id

    def test_to_json_is_valid_json(self):
        env = HandoffEnvelope(from_department="qa", to_department="ops", task="deploy check")
        parsed = json.loads(env.to_json())
        assert parsed["from_department"] == "qa"
        assert isinstance(parsed["context_files"], list)


class TestHandoffMemoryStore:
    @pytest.mark.asyncio
    async def test_store_and_load(self):
        store: dict[str, str] = {}
        mock_store = AsyncMock()
        mock_store.set.side_effect = lambda k, v: store.__setitem__(k, v)
        mock_store.get.side_effect = lambda k: store.get(k)

        env = HandoffEnvelope(
            from_department="qa",
            to_department="design",
            task="Fix WCAG contrast issues",
            findings="5 contrast violations found",
        )
        await store_handoff(env, mock_store)
        loaded = await load_handoff(env.correlation_id, mock_store)

        assert loaded is not None
        assert loaded.task == "Fix WCAG contrast issues"
        assert loaded.findings == "5 contrast violations found"
        assert loaded.correlation_id == env.correlation_id

    @pytest.mark.asyncio
    async def test_store_key_format(self):
        mock_store = AsyncMock()
        env = HandoffEnvelope(from_department="qa", to_department="ops", task="t")
        await store_handoff(env, mock_store)
        mock_store.set.assert_called_once_with(
            f"handoff:{env.correlation_id}", env.to_json()
        )

    @pytest.mark.asyncio
    async def test_load_missing_returns_none(self):
        mock_store = AsyncMock()
        mock_store.get.return_value = None
        result = await load_handoff("nonexistent-id", mock_store)
        assert result is None

    @pytest.mark.asyncio
    async def test_store_no_op_when_memory_store_none(self):
        # Should not raise — and must not attempt to publish anything
        # when the memory_store is None (early return).
        env = HandoffEnvelope(from_department="qa", to_department="ops", task="t")
        bus = MagicMock()
        bus.publish = MagicMock()
        await store_handoff(env, None, event_bus=bus)
        bus.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_returns_none_when_memory_store_none(self):
        result = await load_handoff("any-id", None)
        assert result is None


class TestHandoffTools:
    """Round-trip tests exercising initiate_handoff → continue_handoff via tools."""

    @staticmethod
    def _make_ctx(department: str, memory_store):
        """Build a minimal RunContext-like object for tool functions."""
        from tests.test_teams.conftest import make_deps

        deps = make_deps(
            session_id="test-session",
            department=department,
            memory_store=memory_store,
        )
        ctx = MagicMock()
        ctx.deps = deps
        return ctx

    @staticmethod
    def _make_memory_store():
        """Create a dict-backed async memory store mock."""
        store: dict[str, str] = {}
        mock = AsyncMock()
        mock.set.side_effect = lambda k, v: store.__setitem__(k, v)
        mock.get.side_effect = lambda k: store.get(k)
        return mock, store

    @pytest.mark.asyncio
    async def test_initiate_and_continue_round_trip(self):
        from teams.tools._ops import continue_handoff
        from teams.tools._strategy import initiate_handoff

        mock_store, _backing = self._make_memory_store()
        ctx_strategy = self._make_ctx("strategy", mock_store)
        ctx_ops = self._make_ctx("ops", mock_store)

        result = await initiate_handoff(
            ctx_strategy, to_department="ops", task="Deploy staging", findings="All tests pass"
        )
        assert "correlation_id=" in result
        correlation_id = result.split("correlation_id=")[1]

        continued = await continue_handoff(ctx_ops, correlation_id)
        assert "strategy" in continued
        assert "ops" in continued
        assert "Deploy staging" in continued
        assert "All tests pass" in continued

    @pytest.mark.asyncio
    async def test_continue_handoff_missing_id(self):
        from teams.tools._ops import continue_handoff

        mock_store, _backing = self._make_memory_store()
        ctx = self._make_ctx("ops", mock_store)
        result = await continue_handoff(ctx, "nonexistent-id")
        assert "No handoff found" in result

    @pytest.mark.asyncio
    async def test_initiate_handoff_no_memory_store(self):
        from teams.tools._strategy import initiate_handoff

        ctx = self._make_ctx("strategy", None)
        result = await initiate_handoff(
            ctx, to_department="ops", task="Deploy", findings=""
        )
        # Should still succeed — store_handoff is a no-op when memory_store is None
        assert "correlation_id=" in result

    @pytest.mark.asyncio
    async def test_continue_handoff_no_memory_store(self):
        from teams.tools._ops import continue_handoff

        ctx = self._make_ctx("ops", None)
        result = await continue_handoff(ctx, "some-id")
        assert "No handoff found" in result
