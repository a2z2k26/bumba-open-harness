"""Tests for `WarmChief._try_persist_message_history` — zone4-warmth.B.02 (#2294).

B.02 writes the serialized PydanticAI message_history to the
``chief_sessions.message_history_blob`` column on the success path of
``WarmChief.__aexit__``. This module covers the five spec cases:

1. ``test_aexit_success_path_persists_history`` — happy path, blob bytes
   land in the store via ``update_message_history``.
2. ``test_aexit_failure_path_does_not_persist`` — body-of-with raises;
   persistence is skipped.
3. ``test_serialization_error_does_not_crash_aexit`` — adapter throws;
   ``__aexit__`` continues, session still transitions, blob skipped.
4. ``test_oversize_blob_refused`` — blob > 1 MB is dropped with a WARNING.
5. ``test_persisted_blob_round_trips`` — full encode → decode integrity
   check against a real PydanticAI message list.

Note on test fixtures: the spec sketch references ``wc._result`` for the
RunResult; the shipped implementation distinguishes ``self._result``
(the ``TeamResult`` returned to callers via the ``.result`` property)
from ``self._run_result`` (the PydanticAI ``RunResult`` whose
``all_messages()`` powers the serialized blob). Tests below stash the
mock RunResult on ``wc._run_result`` to match the implementation.
"""
from __future__ import annotations

from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.chief_session import ChiefSession, ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore
from bridge.warm_chief import (
    _CHECKPOINT_HISTORY_BYTES,
    _MAX_MESSAGE_HISTORY_BYTES,
    WarmChief,
)
from teams._types import (
    AgentSpec,
    BridgeDeps,
    DepartmentConfig,
    TeamResult,
)
from tests.test_teams.conftest import make_deps


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session(
    *,
    session_id: str = "cs-persist01",
    work_order_id: str = "wo-persist",
    department: str = "qa",
    chief_name: str = "qa-chief",
    state: ChiefSessionState = ChiefSessionState.WARM,
) -> ChiefSession:
    return ChiefSession(
        session_id=session_id,
        work_order_id=work_order_id,
        department=department,
        chief_name=chief_name,
        state=state,
    )


@pytest.fixture
def config() -> DepartmentConfig:
    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA",
        manager=AgentSpec(name="qa-chief", model="anthropic:claude-opus-4-6"),
        employees=(
            AgentSpec(name="qa-engineer", model="anthropic:claude-sonnet-4-6"),
        ),
    )


@pytest.fixture
def deps() -> BridgeDeps:
    return make_deps(session_id="warmchief-persist", department="qa")


def _team_result(
    *,
    department: str = "qa",
    manager_output: str = "synthesised",
    cost_usd: float = 0.0,
    success: bool = True,
) -> TeamResult:
    return TeamResult(
        department=department,
        manager_output=manager_output,
        employee_results=(),
        total_tokens=0,
        total_cost_usd=cost_usd,
        duration_seconds=0.01,
        success=success,
        error=None,
    )


# ---------------------------------------------------------------------------
# Test cases (spec acceptance)
# ---------------------------------------------------------------------------


class TestSuccessPathPersists:
    @pytest.mark.asyncio
    async def test_aexit_success_path_persists_history(
        self, config, deps
    ):
        """Happy path: RunResult has messages, serialization succeeds, store
        receives the bytes via ``update_message_history``.
        """
        store = InMemoryChiefSessionStore()
        session = _make_session(session_id="cs-happy01")
        await store.create(session)

        team_result = _team_result(manager_output="QA done")

        mock_run_result = MagicMock()
        mock_run_result.all_messages.return_value = [
            MagicMock(name="msg-1"),
            MagicMock(name="msg-2"),
        ]

        async def _fake_run_chief(self):  # noqa: ANN001
            # Mirror what production ``_run_chief`` does: capture the run
            # result on self before returning the team_result.
            self._run_result = mock_run_result
            return team_result

        wc = WarmChief(session, store, config, deps, "review")
        with patch(
            "bridge.warm_chief.ModelMessagesTypeAdapter"
        ) as mock_adapter:
            mock_adapter.dump_json.return_value = b'{"messages": ["test"]}'
            with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                async with wc:
                    pass

        # The blob bytes the mock adapter returned must have been
        # handed to the store keyed by the session_id.
        persisted = await store.get_message_history_blob("cs-happy01")
        assert persisted == b'{"messages": ["test"]}'

        # The adapter was called with the messages list from
        # ``mock_run_result.all_messages()`` — proves the data path
        # reads from ``self._run_result`` (not stale state).
        mock_adapter.dump_json.assert_called_once()
        called_with = mock_adapter.dump_json.call_args[0][0]
        assert called_with == mock_run_result.all_messages.return_value

    @pytest.mark.asyncio
    async def test_aexit_success_path_writes_bounded_memory_checkpoint(
        self, config, deps
    ):
        """Every successful warm-chief run writes a compact checkpoint.

        The checkpoint is separate from the PydanticAI message_history blob:
        operators get a durable, searchable memory entry while small warm
        histories still persist unchanged for continuity.
        """
        store = InMemoryChiefSessionStore()
        session = _make_session(session_id="cs-checkpoint01")
        await store.create(session)

        deps.memory_store.set = AsyncMock(return_value=None)
        event_bus = MagicMock()
        event_bus.publish = MagicMock(return_value=None)

        team_result = _team_result(
            manager_output="QA recommends adding focused result tests.",
            success=True,
        )

        mock_run_result = MagicMock()
        mock_run_result.all_messages.return_value = [MagicMock()]

        async def _fake_run_chief(self):  # noqa: ANN001
            self._run_result = mock_run_result
            return team_result

        wc = WarmChief(
            session,
            store,
            config,
            deps,
            "review",
            event_bus=event_bus,
        )
        with patch(
            "bridge.warm_chief.ModelMessagesTypeAdapter"
        ) as mock_adapter:
            mock_adapter.dump_json.return_value = b'{"messages": ["small"]}'
            with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                async with wc:
                    pass

        persisted = await store.get_message_history_blob("cs-checkpoint01")
        assert persisted == b'{"messages": ["small"]}'

        deps.memory_store.set.assert_awaited_once()
        key, value = deps.memory_store.set.await_args.args
        assert key == "z4:checkpoint:qa:cs-checkpoint01"
        assert "QA recommends adding focused result tests." in value
        assert "history_blob_bytes" in value

        event_types = [
            call.args[0] for call in event_bus.publish.call_args_list
        ]
        assert "chief_session.memory_checkpointed" in event_types


class TestFailurePathSkipsPersistence:
    @pytest.mark.asyncio
    async def test_aexit_failure_path_does_not_persist(
        self, config, deps
    ):
        """Body of the ``async with`` raises; persistence is skipped even
        though ``self._run_result`` is populated.

        The session may still transition (the chief already finished),
        but the blob must not be written — a failed-body run produces
        a transcript the caller never consumed and we won't cache it.
        """
        store = InMemoryChiefSessionStore()
        session = _make_session(session_id="cs-fail01")
        await store.create(session)

        team_result = _team_result(manager_output="QA done")

        mock_run_result = MagicMock()
        mock_run_result.all_messages.return_value = [MagicMock()]

        async def _fake_run_chief(self):  # noqa: ANN001
            self._run_result = mock_run_result
            return team_result

        wc = WarmChief(session, store, config, deps, "task")
        with patch(
            "bridge.warm_chief.ModelMessagesTypeAdapter"
        ) as mock_adapter:
            mock_adapter.dump_json.return_value = b'{"x": "y"}'
            with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                with pytest.raises(RuntimeError, match="body failed"):
                    async with wc:
                        raise RuntimeError("body failed")

        # Persistence path must not have run.
        mock_adapter.dump_json.assert_not_called()
        persisted = await store.get_message_history_blob("cs-fail01")
        assert persisted is None


class TestSerializationErrorIsNonFatal:
    @pytest.mark.asyncio
    async def test_serialization_error_does_not_crash_aexit(
        self, config, deps
    ):
        """``ModelMessagesTypeAdapter.dump_json`` raising must not bubble
        up. ``__aexit__`` continues, the session transitions to
        AWAITING_EVALUATION, the blob remains NULL.
        """
        store = InMemoryChiefSessionStore()
        session = _make_session(session_id="cs-serr01")
        await store.create(session)

        team_result = _team_result(manager_output="ok")

        mock_run_result = MagicMock()
        mock_run_result.all_messages.return_value = [MagicMock()]

        async def _fake_run_chief(self):  # noqa: ANN001
            self._run_result = mock_run_result
            return team_result

        wc = WarmChief(session, store, config, deps, "task")
        with patch(
            "bridge.warm_chief.ModelMessagesTypeAdapter"
        ) as mock_adapter:
            mock_adapter.dump_json.side_effect = RuntimeError(
                "serialization broken"
            )
            with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                # Must NOT raise — serialization error is non-fatal.
                async with wc:
                    pass

        # Session still transitioned to AWAITING_EVALUATION.
        stored = await store.get("cs-serr01")
        assert stored.state == ChiefSessionState.AWAITING_EVALUATION
        # But the blob is missing.
        persisted = await store.get_message_history_blob("cs-serr01")
        assert persisted is None


class TestOversizeBlobRefused:
    @pytest.mark.asyncio
    async def test_oversize_blob_refused(self, config, deps, caplog):
        """A blob larger than ``_MAX_MESSAGE_HISTORY_BYTES`` is dropped.

        The session still transitions cleanly; the persistence helper
        logs a WARNING and returns. No write to the store happens.
        """
        store = InMemoryChiefSessionStore()
        session = _make_session(session_id="cs-big01")
        await store.create(session)

        team_result = _team_result(manager_output="ok")
        mock_run_result = MagicMock()
        mock_run_result.all_messages.return_value = [MagicMock()]

        async def _fake_run_chief(self):  # noqa: ANN001
            self._run_result = mock_run_result
            return team_result

        oversize_blob = b"x" * (_MAX_MESSAGE_HISTORY_BYTES + 1)

        wc = WarmChief(session, store, config, deps, "task")
        with patch(
            "bridge.warm_chief.ModelMessagesTypeAdapter"
        ) as mock_adapter:
            mock_adapter.dump_json.return_value = oversize_blob
            with caplog.at_level("WARNING", logger="bridge.warm_chief"):
                with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                    async with wc:
                        pass

        persisted = await store.get_message_history_blob("cs-big01")
        assert persisted is None

        # WARNING line emitted with the bytes count.
        warning_lines = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "blob_too_large" in r.getMessage() for r in warning_lines
        ), f"expected blob_too_large warning, got: {[r.getMessage() for r in warning_lines]}"


class TestHistoryCompaction:
    @pytest.mark.asyncio
    async def test_large_blob_writes_checkpoint_and_clears_history(
        self, config, deps
    ):
        """A large-but-serializable blob is replaced by a memory checkpoint.

        This keeps warm reuse from feeding a huge transcript back into the
        next request. Clearing the blob is intentional: the next chief run
        starts fresh and can recover durable context from memory/tools rather
        than replaying the whole transcript.
        """
        store = InMemoryChiefSessionStore()
        session = _make_session(session_id="cs-compact01")
        await store.create(session)
        await store.update_message_history(session.session_id, b"old-history")

        deps.memory_store.set = AsyncMock(return_value=None)
        event_bus = MagicMock()
        event_bus.publish = MagicMock(return_value=None)

        team_result = _team_result(manager_output="Large run summary")
        mock_run_result = MagicMock()
        mock_run_result.all_messages.return_value = [MagicMock()]

        async def _fake_run_chief(self):  # noqa: ANN001
            self._run_result = mock_run_result
            return team_result

        large_blob = b"x" * (_CHECKPOINT_HISTORY_BYTES + 1)
        wc = WarmChief(
            session,
            store,
            config,
            deps,
            "task",
            event_bus=event_bus,
        )
        with patch(
            "bridge.warm_chief.ModelMessagesTypeAdapter"
        ) as mock_adapter:
            mock_adapter.dump_json.return_value = large_blob
            with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                async with wc:
                    pass

        assert await store.get_message_history_blob("cs-compact01") is None
        deps.memory_store.set.assert_awaited_once()

        compacted_call = next(
            call for call in event_bus.publish.call_args_list
            if call.args[0] == "chief_session.history_compacted"
        )
        payload = compacted_call.args[1]
        assert payload["session_id"] == "cs-compact01"
        assert payload["reason"] == "checkpoint_threshold"
        assert payload["history_blob_bytes"] == len(large_blob)

    @pytest.mark.asyncio
    async def test_checkpoint_failure_does_not_block_small_history_persist(
        self, config, deps, caplog
    ):
        """Memory checkpoint writes are best-effort.

        A memory-store outage must not drop a compact message_history blob or
        fail the chief lifecycle.
        """
        store = InMemoryChiefSessionStore()
        session = _make_session(session_id="cs-checkpoint-fail01")
        await store.create(session)

        deps.memory_store.set = AsyncMock(side_effect=RuntimeError("memory down"))

        team_result = _team_result(manager_output="still usable")
        mock_run_result = MagicMock()
        mock_run_result.all_messages.return_value = [MagicMock()]

        async def _fake_run_chief(self):  # noqa: ANN001
            self._run_result = mock_run_result
            return team_result

        wc = WarmChief(session, store, config, deps, "task")
        with patch(
            "bridge.warm_chief.ModelMessagesTypeAdapter"
        ) as mock_adapter:
            mock_adapter.dump_json.return_value = b'{"messages": ["small"]}'
            with caplog.at_level("WARNING", logger="bridge.warm_chief"):
                with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                    async with wc:
                        pass

        persisted = await store.get_message_history_blob(
            "cs-checkpoint-fail01"
        )
        assert persisted == b'{"messages": ["small"]}'
        assert any(
            "memory_checkpoint_failed" in r.getMessage()
            for r in caplog.records
        )


class TestPersistedBlobRoundTrips:
    def test_persisted_blob_round_trips(self):
        """Real PydanticAI message → serialize → deserialize → identity.

        End-to-end check that the bytes we'd write are the bytes that
        deserialize back to the original message structure. Does not
        go through WarmChief — exercises the serialization contract
        the persistence helper depends on.
        """
        from pydantic_ai.messages import (
            ModelMessagesTypeAdapter,
            ModelRequest,
            UserPromptPart,
        )

        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello world")]),
        ]
        blob = ModelMessagesTypeAdapter.dump_json(messages)

        # Bytes-typed payload — what the SQLite BLOB column accepts.
        assert isinstance(blob, (bytes, bytearray))

        decoded = ModelMessagesTypeAdapter.validate_json(blob)
        assert len(decoded) == 1
        assert decoded[0].parts[0].content == "hello world"
