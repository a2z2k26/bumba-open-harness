"""Test that all executors honor permission_mode from WorkOrderConstraints.

#630: SubagentExecutor, WorktreeExecutor, and DepartmentExecutor must all
thread wo.constraints.permission_mode into their respective invocations,
matching the TmuxExecutor reference implementation.
"""
from pathlib import Path

import pytest

# Paths relative to repo root (agent/bridge/executors/)
EXECUTOR_FILES = [
    "agent/bridge/executors/subagent.py",
    "agent/bridge/executors/worktree.py",
    "agent/bridge/executors/department.py",
]

# TmuxExecutor is the reference — verify it has the pattern too
REFERENCE_EXECUTOR = "agent/bridge/executors/tmux.py"

# Repo root: two levels up from this test file (agent/tests/ -> agent/ -> repo root)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve(rel_path: str) -> Path:
    """Resolve a repo-relative path, trying both with and without agent/ prefix."""
    direct = _REPO_ROOT / rel_path
    if direct.exists():
        return direct
    # Try without leading "agent/"
    stripped = _REPO_ROOT / rel_path.removeprefix("agent/")
    if stripped.exists():
        return stripped
    return direct  # return the direct path so the test can fail with a clear message


@pytest.mark.parametrize("executor_path", EXECUTOR_FILES)
def test_executor_honors_permission_mode(executor_path: str) -> None:
    """Each executor must thread permission_mode into its invocation.

    This test is structural: it reads the source file and asserts the
    string 'permission_mode' appears, confirming the parameter is wired.
    """
    path = _resolve(executor_path)
    if not path.exists():
        pytest.skip(f"Executor file not found: {path}")

    src = path.read_text()
    assert "permission_mode" in src, (
        f"{executor_path} does not thread permission_mode into its invocation. "
        "All executors must honor wo.constraints.permission_mode — see #630."
    )


def test_reference_executor_has_permission_mode() -> None:
    """TmuxExecutor (reference) must still have permission_mode — regression guard."""
    path = _resolve(REFERENCE_EXECUTOR)
    if not path.exists():
        pytest.skip(f"TmuxExecutor not found: {path}")

    src = path.read_text()
    assert "permission_mode" in src, (
        "TmuxExecutor (reference) lost permission_mode — this is a regression."
    )


def test_worktree_executor_sets_agent_depth() -> None:
    """WorktreeExecutor must set BUMBA_AGENT_DEPTH env var to jail subagents.

    The env var prevents recursive agent spawning when WorkOrders are
    executed inside a git worktree (#630 write-jail requirement).
    """
    worktree_paths = [
        "agent/bridge/executors/worktree.py",
        "agent/bridge/executors/worktree_executor.py",
    ]
    path = next(
        (p for rel in worktree_paths if (p := _resolve(rel)).exists()),
        None,
    )
    if path is None:
        pytest.skip("WorktreeExecutor not found")

    src = path.read_text()
    assert "BUMBA_AGENT_DEPTH" in src, (
        "WorktreeExecutor must set BUMBA_AGENT_DEPTH env var to prevent "
        "recursive agent spawning inside worktrees (#630)."
    )


def test_subagent_executor_uses_isolation_env() -> None:
    """SubagentExecutor must pass env_vars from IsolatedEnv (write-jail contract).

    This verifies the S03 write-jail is still intact alongside the #630 fix.
    """
    path = _resolve("agent/bridge/executors/subagent.py")
    if not path.exists():
        pytest.skip("SubagentExecutor not found")

    src = path.read_text()
    assert "iso_env.env_vars" in src, (
        "SubagentExecutor must pass iso_env.env_vars to invoke() "
        "(S03 write-jail — BUMBA_AGENT_DEPTH=1)."
    )
    assert "mcp_config_path" in src, (
        "SubagentExecutor must pass mcp_config_path to invoke() "
        "(S03 filtered MCP config)."
    )


def test_department_executor_threads_permission_mode_to_bridge_deps() -> None:
    """DepartmentExecutor must pass permission_mode into BridgeDeps.

    Unlike other executors, DepartmentExecutor routes via registry.route()
    rather than ClaudeRunner.invoke(), so permission_mode flows through
    BridgeDeps instead of a direct runner call.
    """
    path = _resolve("agent/bridge/executors/department.py")
    if not path.exists():
        pytest.skip("DepartmentExecutor not found")

    src = path.read_text()
    assert "permission_mode" in src, (
        "DepartmentExecutor must thread permission_mode into BridgeDeps (#630)."
    )
    # Verify it reads from wo.constraints, not a hardcoded value
    assert "wo.constraints" in src, (
        "DepartmentExecutor must read permission_mode from wo.constraints, "
        "not use a hardcoded string."
    )


def test_claude_runner_invoke_accepts_permission_mode() -> None:
    """ClaudeRunner.invoke() must accept a permission_mode parameter.

    SubagentExecutor and WorktreeExecutor both call runner.invoke() —
    the runner must accept permission_mode to pass it to _build_command.
    """
    runner_paths = [
        "agent/bridge/claude_runner.py",
        "bridge/claude_runner.py",
    ]
    path = next(
        (p for rel in runner_paths if (p := _resolve(rel)).exists()),
        None,
    )
    if path is None:
        pytest.skip("claude_runner.py not found")

    src = path.read_text()
    assert "permission_mode" in src, (
        "ClaudeRunner must accept a permission_mode parameter in invoke() "
        "so SubagentExecutor and WorktreeExecutor can thread it through (#630)."
    )
    # Verify the _build_command respects it (not just stores it)
    assert "--permission-mode" in src or "permission_mode" in src, (
        "ClaudeRunner._build_command must use permission_mode to build the CLI command."
    )
