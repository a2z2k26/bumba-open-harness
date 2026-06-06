"""Tests for bridge.task_queue."""

from __future__ import annotations

import pytest

from bridge.task_queue import TaskQueue, detect_question_with_options


@pytest.fixture
def task_queue(migrated_db):
    return TaskQueue(migrated_db)


class TestDetectQuestionWithOptions:
    """Option detection in Claude responses."""

    def test_detect_numbered_options(self):
        text = """How should I proceed?

1. Deploy immediately
2. Run more tests first
3. Wait for review"""
        result = detect_question_with_options(text)
        assert result is not None
        question, options = result
        assert "proceed" in question
        assert len(options) == 3
        assert options[0] == "Deploy immediately"

    def test_detect_with_parenthesis_format(self):
        text = """Choose a strategy:

1) Conservative approach
2) Aggressive approach
3) Balanced approach"""
        result = detect_question_with_options(text)
        assert result is not None
        _, options = result
        assert len(options) == 3

    def test_no_options_returns_none(self):
        text = "Just a normal response with no options."
        assert detect_question_with_options(text) is None

    def test_single_option_not_detected(self):
        text = "Here's step 1. Do this thing."
        assert detect_question_with_options(text) is None

    def test_two_options_minimum(self):
        text = """Pick one:

1. Option A
2. Option B"""
        result = detect_question_with_options(text)
        assert result is not None
        _, options = result
        assert len(options) == 2

    def test_non_sequential_not_detected(self):
        text = """Options:

1. First
3. Third
5. Fifth"""
        assert detect_question_with_options(text) is None

    def test_generic_question_when_no_text_before(self):
        text = """1. Option A
2. Option B"""
        result = detect_question_with_options(text)
        assert result is not None
        question, _ = result
        assert "choose" in question.lower()


class TestTaskQueue:
    """Task CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_task(self, task_queue):
        task_id = await task_queue.create(
            chat_id="chat-123",
            pending_question="Which option?",
            pending_options=["A", "B", "C"],
            claude_session_id="claude-sess-1",
        )
        assert task_id > 0

    @pytest.mark.asyncio
    async def test_get_task(self, task_queue):
        task_id = await task_queue.create(
            chat_id="chat-123",
            pending_question="Choose:",
            pending_options=["X", "Y"],
        )
        task = await task_queue.get(task_id)
        assert task is not None
        assert task.status == "needs_input"
        assert task.pending_question == "Choose:"
        assert task.pending_options == ["X", "Y"]
        assert task.chat_id == "chat-123"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, task_queue):
        task = await task_queue.get(99999)
        assert task is None

    @pytest.mark.asyncio
    async def test_submit_response(self, task_queue):
        task_id = await task_queue.create(
            chat_id="chat-123",
            pending_question="Pick:",
            pending_options=["A", "B"],
        )
        await task_queue.submit_response(task_id, "A")
        task = await task_queue.get(task_id)
        assert task.status == "pending"
        assert task.user_response == "A"

    @pytest.mark.asyncio
    async def test_complete_task(self, task_queue):
        task_id = await task_queue.create(chat_id="chat-123")
        await task_queue.complete(task_id, "Task completed successfully")
        task = await task_queue.get(task_id)
        assert task.status == "completed"
        assert task.result == "Task completed successfully"

    @pytest.mark.asyncio
    async def test_fail_task(self, task_queue):
        task_id = await task_queue.create(chat_id="chat-123")
        await task_queue.fail(task_id, "Something went wrong")
        task = await task_queue.get(task_id)
        assert task.status == "failed"

    @pytest.mark.asyncio
    async def test_get_next_pending_with_response(self, task_queue):
        # Create and respond to a task
        task_id = await task_queue.create(
            chat_id="chat-123",
            pending_question="Pick:",
            pending_options=["A", "B"],
        )
        await task_queue.submit_response(task_id, "B")

        # Should find it
        task = await task_queue.get_next_pending_with_response()
        assert task is not None
        assert task.id == task_id
        assert task.user_response == "B"

    @pytest.mark.asyncio
    async def test_no_pending_returns_none(self, task_queue):
        task = await task_queue.get_next_pending_with_response()
        assert task is None

    @pytest.mark.asyncio
    async def test_get_tasks_for_chat(self, task_queue):
        await task_queue.create(chat_id="chat-A")
        await task_queue.create(chat_id="chat-A")
        await task_queue.create(chat_id="chat-B")

        tasks = await task_queue.get_tasks_for_chat("chat-A")
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_full_hitl_flow(self, task_queue):
        """End-to-end: create → needs_input → submit_response → complete."""
        task_id = await task_queue.create(
            chat_id="chat-123",
            claude_session_id="claude-sess-abc",
            pending_question="Deploy now or later?",
            pending_options=["Now", "Later"],
        )

        # User picks an option
        await task_queue.submit_response(task_id, "Now")

        # Bridge picks up the pending task
        task = await task_queue.get_next_pending_with_response()
        assert task is not None
        assert task.claude_session_id == "claude-sess-abc"
        assert task.user_response == "Now"

        # Claude resumes and completes
        await task_queue.complete(task_id, "Deploying now...")
        task = await task_queue.get(task_id)
        assert task.status == "completed"
        assert task.result == "Deploying now..."
