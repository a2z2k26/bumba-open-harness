"""WorktreeExecutor — isolation, cleanup, rebase-gate, concurrency (S02b #562)."""
from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.executors.worktree import WorktreeExecutor
from bridge.work_order import Environment, WorkOrder, WorkOrderStatus


@pytest.fixture
def git_repo(tmp_path):
    """A throwaway git repo for worktree tests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _make_wo():
    return (
        WorkOrder.create(intent="do x", skill="fix-test", project="p")
        .with_environment(Environment.WORKTREE, "isolated task")
        .transition(WorkOrderStatus.ASSIGNED)
    )


@pytest.mark.asyncio
async def test_worktree_executor_creates_and_cleans_up(git_repo):
    """AC-1: worktree created; AC (implicit): cleaned up after success."""
    runner = MagicMock()
    runner.invoke = AsyncMock(return_value=MagicMock(
        is_error=False, response_text="ok", cost_usd=0.0, num_turns=0, duration_ms=0, error_type=""
    ))
    executor = WorktreeExecutor(claude_runner=runner, repo_root=git_repo)
    wo = _make_wo()

    result = await executor.execute(wo)
    assert result.is_error is False

    # Worktree directory removed after completion
    wt_path = git_repo / ".worktrees" / f"z3-{wo.id[:8]}"
    assert not wt_path.exists()

    # Branch deleted after completion
    branches = subprocess.run(
        ["git", "branch", "--list"], cwd=git_repo, capture_output=True, text=True
    ).stdout
    assert f"z3-{wo.id[:8]}" not in branches


@pytest.mark.asyncio
async def test_worktree_executor_cleanup_runs_on_exception(git_repo):
    """AC-2: cleanup happens even when runner raises an exception."""
    runner = MagicMock()
    runner.invoke = AsyncMock(side_effect=RuntimeError("runner exploded"))
    executor = WorktreeExecutor(claude_runner=runner, repo_root=git_repo)
    wo = _make_wo()

    with pytest.raises(RuntimeError, match="runner exploded"):
        await executor.execute(wo)

    # Worktree directory still cleaned up
    wt_path = git_repo / ".worktrees" / f"z3-{wo.id[:8]}"
    assert not wt_path.exists()


@pytest.mark.asyncio
async def test_worktree_executor_concurrent_safe(git_repo):
    """AC-3: three concurrent executions use separate branch/paths, no collisions."""
    runner = MagicMock()

    async def slow_invoke(**kwargs):
        await asyncio.sleep(0.05)
        return MagicMock(
            is_error=False, response_text="ok", cost_usd=0.0, num_turns=0,
            duration_ms=0, error_type=""
        )

    runner.invoke = slow_invoke
    executor = WorktreeExecutor(claude_runner=runner, repo_root=git_repo)

    wos = [_make_wo() for _ in range(3)]
    results = await asyncio.gather(*(executor.execute(w) for w in wos))

    assert all(r.is_error is False for r in results)
    # All worktrees cleaned
    for w in wos:
        wt_path = git_repo / ".worktrees" / f"z3-{w.id[:8]}"
        assert not wt_path.exists()


@pytest.mark.asyncio
async def test_worktree_executor_raises_when_runner_missing(git_repo):
    """RuntimeError raised immediately if runner not configured."""
    executor = WorktreeExecutor(claude_runner=None, repo_root=git_repo)
    wo = _make_wo()

    with pytest.raises(RuntimeError, match="no runner"):
        await executor.execute(wo)


@pytest.mark.asyncio
async def test_worktree_executor_session_id_format(git_repo):
    """Session ID must start with 'worktree-' and include WO id prefix."""
    captured_kwargs: dict = {}

    async def capturing_invoke(**kwargs):
        captured_kwargs.update(kwargs)
        return MagicMock(
            is_error=False, response_text="done", cost_usd=0.0, num_turns=0,
            duration_ms=0, error_type=""
        )

    runner = MagicMock()
    runner.invoke = capturing_invoke
    executor = WorktreeExecutor(claude_runner=runner, repo_root=git_repo)
    wo = _make_wo()

    await executor.execute(wo)

    assert captured_kwargs["session_id"].startswith("worktree-")
    assert wo.id[:8] in captured_kwargs["session_id"]
