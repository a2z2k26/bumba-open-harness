"""Sprint 02.08 — verify ``BridgeDeps.for_cron`` builds real bridge objects.

The cron job_search path used to construct ``BridgeDeps`` from
``unittest.mock.MagicMock`` / ``AsyncMock`` instances, which silently
forfeited event fan-out, trust gating, and cost tracking. Sprint 02.08
replaces those mocks with a real ``BridgeDeps.for_cron`` classmethod that
wires through real ``EventBus``, ``CostTracker``, ``TrustScoreEngine``,
and ``Memory``.

These tests are the regression guard. If a future change drops a real
field back to a mock, one of the assertions below will catch it.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from bridge.cost_tracker import CostTracker
from bridge.event_bus import EventBus
from bridge.memory import Memory, MemoryKVAdapter
from bridge.trust_score import TrustScoreEngine
from teams._types import BridgeDeps


pytestmark = pytest.mark.asyncio


async def _close_deps_db(deps: BridgeDeps) -> None:
    """Close the underlying SQLite connection so pytest tears down cleanly."""
    db = deps.memory_store._memory._db
    await db.close()


async def test_for_cron_returns_real_bridgedeps_with_real_event_bus(tmp_path: Path) -> None:
    """Test 1: ``for_cron`` returns BridgeDeps with a real ``EventBus`` instance."""
    deps = await BridgeDeps.for_cron(
        department="job_search",
        session_id="test-session",
        data_dir=str(tmp_path),
    )

    try:
        assert isinstance(deps, BridgeDeps)
        assert isinstance(deps.event_bus, EventBus), (
            f"event_bus must be a real EventBus, not {type(deps.event_bus).__name__}"
        )
        assert deps.session_id == "test-session"
        assert deps.department == "job_search"
    finally:
        await _close_deps_db(deps)


async def test_event_bus_publish_appends_to_jsonl_stream(tmp_path: Path) -> None:
    """Test 2: ``deps.event_bus.publish(...)`` writes a real line to the JSONL stream."""
    session_id = "test-publish-session"
    deps = await BridgeDeps.for_cron(
        department="job_search",
        session_id=session_id,
        data_dir=str(tmp_path),
    )

    try:
        deps.event_bus.publish(
            "schedule.triggered",
            {"source": "test", "iteration": 1},
            source="sprint-02.08-test",
        )
        deps.event_bus.publish(
            "schedule.triggered",
            {"source": "test", "iteration": 2},
            source="sprint-02.08-test",
        )

        # Per for_cron contract: events live at <data_dir>/cron/<session_id>/events/<date>.jsonl
        events_dir = tmp_path / "cron" / session_id / "events"
        assert events_dir.exists(), f"events dir not created at {events_dir}"

        jsonl_files = list(events_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 1, (
            f"expected exactly one JSONL stream file, found {len(jsonl_files)}: {jsonl_files}"
        )

        lines = jsonl_files[0].read_text().strip().splitlines()
        assert len(lines) == 2, f"expected 2 event lines, got {len(lines)}"

        # Each line must parse as a JSON event record.
        parsed = [json.loads(line) for line in lines]
        assert all(p["event_type"] == "schedule.triggered" for p in parsed)
        assert {p["payload"]["iteration"] for p in parsed} == {1, 2}
    finally:
        await _close_deps_db(deps)


async def test_cost_tracker_record_appends_to_cost_log(tmp_path: Path) -> None:
    """Test 3: ``deps.cost_tracker.record(...)`` writes to the cost log."""
    deps = await BridgeDeps.for_cron(
        department="job_search",
        session_id="test-cost-session",
        data_dir=str(tmp_path),
    )

    try:
        assert isinstance(deps.cost_tracker, CostTracker)

        deps.cost_tracker.record(
            model="haiku",
            input_tokens=100,
            output_tokens=50,
            task_type="cron_test",
            agent_id="job_search_director",
            session_id="test-cost-session",
        )
        deps.cost_tracker.record(
            model="sonnet",
            input_tokens=200,
            output_tokens=80,
            task_type="cron_test",
            session_id="test-cost-session",
        )

        # Per CostTracker contract: writes to <data_dir>/cost_tracking.jsonl
        cost_log = tmp_path / "cost_tracking.jsonl"
        assert cost_log.exists(), f"cost log not created at {cost_log}"

        lines = cost_log.read_text().strip().splitlines()
        assert len(lines) == 2, f"expected 2 cost entries, got {len(lines)}"

        parsed = [json.loads(line) for line in lines]
        assert {p["model"] for p in parsed} == {"haiku", "sonnet"}
        assert all(p["task_type"] == "cron_test" for p in parsed)
    finally:
        await _close_deps_db(deps)


async def test_memory_store_is_real_memory_kv_adapter(tmp_path: Path) -> None:
    """Test 4: ``deps.memory_store`` is a real ``MemoryKVAdapter`` over real ``Memory``."""
    deps = await BridgeDeps.for_cron(
        department="job_search",
        session_id="test-memory-session",
        data_dir=str(tmp_path),
    )

    try:
        assert isinstance(deps.memory_store, MemoryKVAdapter), (
            f"memory_store must be a real MemoryKVAdapter, "
            f"not {type(deps.memory_store).__name__}"
        )

        underlying_memory = deps.memory_store._memory
        assert isinstance(underlying_memory, Memory), (
            f"underlying memory must be a real Memory, "
            f"not {type(underlying_memory).__name__}"
        )

        # FTS5-only fallback: embedding_client must be None per the for_cron contract.
        assert underlying_memory._embedding_client is None, (
            "Memory was constructed with an embedding_client; "
            "for_cron requires embedding_client=None for FTS5 fallback."
        )

        # knowledge_search must be the bound method, not a mock callable.
        assert deps.knowledge_search == underlying_memory.search_knowledge

        # Trust manager must be real too.
        assert isinstance(deps.trust_manager, TrustScoreEngine), (
            f"trust_manager must be a real TrustScoreEngine, "
            f"not {type(deps.trust_manager).__name__}"
        )

        # Smoke: the FTS5 path actually executes (no semantic embedding required).
        # On a fresh DB the search returns []. The assertion is that it does NOT
        # raise — i.e. the real Database/Memory/FTS5 chain is wired correctly.
        results = await deps.knowledge_search("nonexistent query token", limit=5)
        assert isinstance(results, list)
    finally:
        await _close_deps_db(deps)


async def test_service_module_does_not_import_unittest_mock(tmp_path: Path) -> None:
    """Test 5: regression guard — production code must not import the mock library.

    The bug Sprint 02.08 fixes is exactly this: production code reaching for
    the standard-library mock module to silence missing dependencies. Both an
    AST scan of import statements and a runtime ``__dict__`` inspection must
    agree the import is gone.

    The check is import-only (not raw substring) so the module's docstring
    can still reference the historical bug for future readers.
    """
    import ast

    import job_search.service as service_module

    src = inspect.getsource(service_module)
    tree = ast.parse(src)

    forbidden_modules = {"unittest.mock"}
    forbidden_names = {"MagicMock", "AsyncMock", "Mock", "patch"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_modules, (
                    f"job_search.service imports forbidden module {alias.name}. "
                    "Production code must use BridgeDeps.for_cron, not stdlib mocks."
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module not in forbidden_modules, (
                f"job_search.service does `from {module} import ...`. "
                "Production code must use BridgeDeps.for_cron, not stdlib mocks."
            )
            for alias in node.names:
                assert alias.name not in forbidden_names, (
                    f"job_search.service imports {alias.name!r} from {module!r}. "
                    "Mock symbols must not appear in production code."
                )

    # Runtime check: no MagicMock/AsyncMock leaked into the module namespace.
    for name, value in vars(service_module).items():
        type_name = type(value).__name__
        assert "Mock" not in type_name, (
            f"job_search.service.{name} is a {type_name} instance — "
            f"mocks must not appear in production code."
        )
