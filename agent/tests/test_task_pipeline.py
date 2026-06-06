"""Tests for the Kanban task pipeline module."""
from __future__ import annotations

import pytest
import pytest_asyncio
import aiosqlite

# ---------------------------------------------------------------------------
# Lightweight shim so TaskPipeline can call db.execute / db.fetchone / etc.
# without pulling in the full bridge Database class.
# ---------------------------------------------------------------------------


class _InMemoryDB:
    """Minimal async wrapper around an aiosqlite connection.

    Mirrors the interface that TaskPipeline expects:
        execute(sql, params) -> cursor
        fetchone(sql, params) -> Row | None
        fetchall(sql, params) -> list[Row]
        commit()
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        return await self._conn.execute(sql, params)

    async def fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()

    async def commit(self) -> None:
        await self._conn.commit()


from bridge.task_pipeline import TaskPipeline, TaskStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pipeline():
    """Yield a fully-initialised TaskPipeline backed by an in-memory DB."""
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = _InMemoryDB(conn)
        tp = TaskPipeline(db)
        await tp.initialize()
        yield tp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_returns_id(pipeline):
    task_id = await pipeline.create_task("Write docs")
    assert isinstance(task_id, int)
    assert task_id >= 1


@pytest.mark.asyncio
async def test_get_task_returns_correct_fields(pipeline):
    task_id = await pipeline.create_task(
        title="Build API",
        description="Design REST endpoints",
        priority="high",
        assigned_to="bumba",
        source="discord",
    )
    task = await pipeline.get_task(task_id)

    assert task is not None
    assert task["id"] == task_id
    assert task["title"] == "Build API"
    assert task["description"] == "Design REST endpoints"
    assert task["status"] == "inbox"
    assert task["priority"] == "high"
    assert task["assigned_to"] == "bumba"
    assert task["source"] == "discord"
    assert task["retry_count"] == 0
    assert task["created_at"] is not None
    assert task["updated_at"] is not None


@pytest.mark.asyncio
async def test_get_task_not_found(pipeline):
    result = await pipeline.get_task(9999)
    assert result is None


@pytest.mark.asyncio
async def test_valid_transitions_full_happy_path(pipeline):
    """Walk a task through the full happy path: inbox -> assigned -> in_progress -> review -> quality_review -> done."""
    task_id = await pipeline.create_task("Deploy feature")

    transitions = ["assigned", "in_progress", "review", "quality_review", "done"]
    for new_status in transitions:
        result = await pipeline.move_task(task_id, new_status)
        assert result is True
        task = await pipeline.get_task(task_id)
        assert task["status"] == new_status


@pytest.mark.asyncio
async def test_invalid_transition_raises_value_error(pipeline):
    """Jumping directly from inbox to done is not allowed."""
    task_id = await pipeline.create_task("Shortcut attempt")

    with pytest.raises(ValueError, match="Invalid transition"):
        await pipeline.move_task(task_id, "done")


@pytest.mark.asyncio
async def test_done_is_terminal(pipeline):
    """No transitions out of done."""
    task_id = await pipeline.create_task("Finished work")
    for status in ["assigned", "in_progress", "review", "quality_review", "done"]:
        await pipeline.move_task(task_id, status)

    with pytest.raises(ValueError, match="terminal state"):
        await pipeline.move_task(task_id, "inbox")


@pytest.mark.asyncio
async def test_failed_to_inbox_increments_retry_count(pipeline):
    task_id = await pipeline.create_task("Flaky job")

    # Move to failed first
    await pipeline.move_task(task_id, "failed")
    task = await pipeline.get_task(task_id)
    assert task["retry_count"] == 0

    # Retry: failed -> inbox should bump retry_count
    await pipeline.move_task(task_id, "inbox")
    task = await pipeline.get_task(task_id)
    assert task["retry_count"] == 1

    # Fail again and retry
    await pipeline.move_task(task_id, "failed")
    await pipeline.move_task(task_id, "inbox")
    task = await pipeline.get_task(task_id)
    assert task["retry_count"] == 2


@pytest.mark.asyncio
async def test_list_tasks_with_status_filter(pipeline):
    await pipeline.create_task("Task A")
    id_b = await pipeline.create_task("Task B")
    await pipeline.create_task("Task C")

    # Move B to assigned
    await pipeline.move_task(id_b, "assigned")

    inbox_tasks = await pipeline.list_tasks(status="inbox")
    assert len(inbox_tasks) == 2
    assert all(t["status"] == "inbox" for t in inbox_tasks)

    assigned_tasks = await pipeline.list_tasks(status="assigned")
    assert len(assigned_tasks) == 1
    assert assigned_tasks[0]["title"] == "Task B"


@pytest.mark.asyncio
async def test_list_tasks_returns_all_when_no_filter(pipeline):
    await pipeline.create_task("Task 1")
    await pipeline.create_task("Task 2")

    all_tasks = await pipeline.list_tasks()
    assert len(all_tasks) == 2


@pytest.mark.asyncio
async def test_get_pipeline_summary(pipeline):
    await pipeline.create_task("A")
    await pipeline.create_task("B")
    id_c = await pipeline.create_task("C")
    await pipeline.move_task(id_c, "assigned")

    summary = await pipeline.get_pipeline_summary()

    # All statuses should be present
    for status in TaskStatus:
        assert status.value in summary

    assert summary["inbox"] == 2
    assert summary["assigned"] == 1
    assert summary["in_progress"] == 0
    assert summary["done"] == 0


@pytest.mark.asyncio
async def test_priority_ordering_in_list_tasks(pipeline):
    """Tasks should be ordered by priority descending (urgent first)."""
    await pipeline.create_task("Low task", priority="low")
    await pipeline.create_task("Urgent task", priority="urgent")
    await pipeline.create_task("Medium task", priority="medium")
    await pipeline.create_task("Critical task", priority="critical")
    await pipeline.create_task("High task", priority="high")

    tasks = await pipeline.list_tasks()

    priorities = [t["priority"] for t in tasks]
    assert priorities == ["urgent", "critical", "high", "medium", "low"]


@pytest.mark.asyncio
async def test_assign_task(pipeline):
    task_id = await pipeline.create_task("Unassigned work")
    result = await pipeline.assign_task(task_id, "engineer-1")

    assert result is True
    task = await pipeline.get_task(task_id)
    assert task["assigned_to"] == "engineer-1"


@pytest.mark.asyncio
async def test_assign_task_not_found(pipeline):
    result = await pipeline.assign_task(9999, "nobody")
    assert result is False


@pytest.mark.asyncio
async def test_invalid_priority_raises_value_error(pipeline):
    with pytest.raises(ValueError, match="Invalid priority"):
        await pipeline.create_task("Bad priority", priority="super_urgent")


@pytest.mark.asyncio
async def test_invalid_status_raises_value_error(pipeline):
    task_id = await pipeline.create_task("Bad status")
    with pytest.raises(ValueError, match="Invalid status"):
        await pipeline.move_task(task_id, "nonexistent")


@pytest.mark.asyncio
async def test_move_nonexistent_task_raises_value_error(pipeline):
    with pytest.raises(ValueError, match="not found"):
        await pipeline.move_task(9999, "assigned")
