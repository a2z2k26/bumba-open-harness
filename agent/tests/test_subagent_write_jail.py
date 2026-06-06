"""S03 — SUBAGENT write jail contract tests (#565)."""
from __future__ import annotations

import json
import os
import pathlib
import stat
from unittest.mock import MagicMock

import pytest

from bridge.executors.subagent import SubagentExecutor
from bridge.work_order import Environment, WorkOrder, WorkOrderStatus


def _wo() -> WorkOrder:
    return (
        WorkOrder.create(intent="hello", skill="chat", project="p")
        .with_environment(Environment.SUBAGENT, "t")
        .transition(WorkOrderStatus.ASSIGNED)
    )


@pytest.mark.asyncio
async def test_subagent_receives_filtered_mcp_config():
    """AC-1: Subagent invocation receives filtered MCP config containing only allowlisted servers."""
    runner = MagicMock()
    captured: dict = {}

    async def capture_invoke(**kwargs):
        captured.update(kwargs)
        cfg_path = kwargs.get("mcp_config_path")
        if cfg_path:
            captured["filtered"] = json.loads(pathlib.Path(cfg_path).read_text())
        return MagicMock(is_error=False, response_text="ok")

    runner.invoke = capture_invoke

    master = {
        "mcpServers": {
            "github": {"command": "x"},
            "cloudflare": {"command": "y"},
            "notion": {"command": "z"},
            "figma-console": {"command": "w"},
        }
    }
    allowed = ["github", "notion"]

    executor = SubagentExecutor(
        claude_runner=runner,
        master_mcp_config=master,
        allowed_mcp_servers=allowed,
    )
    await executor.execute(_wo())

    filtered = captured["filtered"]["mcpServers"]
    assert set(filtered.keys()) == {"github", "notion"}
    assert "cloudflare" not in filtered
    assert "figma-console" not in filtered


@pytest.mark.asyncio
async def test_subagent_env_vars_include_depth_flag():
    """AC-3: env_vars passed to invoke contain BUMBA_AGENT_DEPTH=1 and BUMBA_AGENT_TOOL=subagent."""
    runner = MagicMock()
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        return MagicMock(is_error=False, response_text="ok")

    runner.invoke = capture

    executor = SubagentExecutor(
        claude_runner=runner,
        master_mcp_config={"mcpServers": {"github": {}}},
        allowed_mcp_servers=["github"],
    )
    await executor.execute(_wo())

    env = captured.get("env_vars") or {}
    assert env.get("BUMBA_AGENT_DEPTH") == "1"
    assert env.get("BUMBA_AGENT_TOOL") == "subagent"


@pytest.mark.asyncio
async def test_subagent_config_file_mode_0600():
    """AC-2: Filtered config file is written with mode 0600."""
    runner = MagicMock()
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        cfg_path = kwargs.get("mcp_config_path")
        if cfg_path:
            mode = stat.S_IMODE(os.stat(cfg_path).st_mode)
            captured["file_mode"] = mode
        return MagicMock(is_error=False, response_text="ok")

    runner.invoke = capture

    executor = SubagentExecutor(
        claude_runner=runner,
        master_mcp_config={"mcpServers": {"github": {}}},
        allowed_mcp_servers=["github"],
    )
    await executor.execute(_wo())

    assert captured.get("file_mode") == 0o600, (
        f"Expected 0600, got {oct(captured.get('file_mode', 0))}"
    )


@pytest.mark.asyncio
async def test_subagent_cleanup_runs_on_exception():
    """AC-4: Temp filtered config file is deleted even when invoke raises."""
    runner = MagicMock()
    created_path: dict = {}

    async def invoke_and_fail(**kwargs):
        created_path["path"] = kwargs.get("mcp_config_path")
        raise RuntimeError("boom")

    runner.invoke = invoke_and_fail

    executor = SubagentExecutor(
        claude_runner=runner,
        master_mcp_config={"mcpServers": {"github": {}}},
        allowed_mcp_servers=["github"],
    )
    with pytest.raises(RuntimeError, match="boom"):
        await executor.execute(_wo())

    assert created_path["path"] is not None, "Expected a config path to have been created"
    assert not pathlib.Path(created_path["path"]).exists(), (
        "Filtered MCP config should be deleted after exception (cleanup in finally)"
    )


@pytest.mark.asyncio
async def test_subagent_cleanup_runs_on_success():
    """Temp filtered config file is deleted after successful invocation."""
    runner = MagicMock()
    created_path: dict = {}

    async def capture(**kwargs):
        created_path["path"] = kwargs.get("mcp_config_path")
        return MagicMock(is_error=False, response_text="ok")

    runner.invoke = capture

    executor = SubagentExecutor(
        claude_runner=runner,
        master_mcp_config={"mcpServers": {"github": {}}},
        allowed_mcp_servers=["github"],
    )
    await executor.execute(_wo())

    assert created_path["path"] is not None
    assert not pathlib.Path(created_path["path"]).exists(), (
        "Filtered MCP config should be deleted after successful invocation"
    )


@pytest.mark.asyncio
async def test_subagent_no_mcp_config_passthrough_when_no_master():
    """With no master_mcp_config provided, executor still works (empty filtered config)."""
    runner = MagicMock()
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        return MagicMock(is_error=False, response_text="ok")

    runner.invoke = capture

    executor = SubagentExecutor(
        claude_runner=runner,
        master_mcp_config=None,
        allowed_mcp_servers=["github"],
    )
    await executor.execute(_wo())

    # No error — empty filtered config is acceptable
    assert "mcp_config_path" in captured


@pytest.mark.asyncio
async def test_subagent_backwards_compat_no_jail_args():
    """SubagentExecutor created without jail args still works (AC-preserving regression)."""
    runner = MagicMock()

    async def simple_invoke(**kwargs):
        return MagicMock(is_error=False, response_text="ok")

    runner.invoke = simple_invoke

    # Old calling convention — no master_mcp_config, no allowed_mcp_servers
    executor = SubagentExecutor(claude_runner=runner)
    result = await executor.execute(_wo())
    assert result.response_text == "ok"


@pytest.mark.asyncio
async def test_subagent_mcp_config_path_passed_to_runner():
    """invoke() receives mcp_config_path kwarg when jail is active."""
    runner = MagicMock()
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        return MagicMock(is_error=False, response_text="ok")

    runner.invoke = capture

    executor = SubagentExecutor(
        claude_runner=runner,
        master_mcp_config={"mcpServers": {"github": {}}},
        allowed_mcp_servers=["github"],
    )
    await executor.execute(_wo())

    assert "mcp_config_path" in captured
    assert captured["mcp_config_path"] is not None
    assert captured["mcp_config_path"].endswith(".json")


# ---------------------------------------------------------------------------
# Sprint R5.2 (issue #1904) — denied-path proof + composition with env-vars.
# ---------------------------------------------------------------------------
#
# The pre-R5.2 tests above prove the ALLOW side: an allowlisted server
# survives filtering. R5.2 adds the symmetric DENY side: a server present
# in the master MCP config but absent from the allowlist must be physically
# absent from the filtered file the subagent receives — not merely
# "documented as forbidden". The composition test then asserts both the
# MCP filter and the `BUMBA_AGENT_DEPTH` recursion guard appear together
# on the same invocation, so a subagent cannot escape one boundary by
# triggering the other.
#
# These tests are referenced from `docs/security/write-jail-verification.md`
# (R5.2 acceptance: "Documentation links the tests to the write-territory
# doctrine").


@pytest.mark.asyncio
async def test_subagent_denied_mcp_server_absent_from_filtered_config():
    """R5.2: An MCP server present in master config but NOT on the allowlist
    is physically absent from the filtered file the subagent receives.

    Proves the DENY side of the write-jail: filtering is not advisory.
    """
    runner = MagicMock()
    captured: dict = {}

    # Capture both the parsed config AND the raw file text from inside
    # the invoke callback (before SubagentExecutor's `finally` cleans up
    # the temp file). The existing tests above all read inside the
    # callback for the same reason.
    async def capture_with_text(**kwargs):
        captured.update(kwargs)
        cfg_path = kwargs.get("mcp_config_path")
        if cfg_path:
            text = pathlib.Path(cfg_path).read_text()
            captured["filtered"] = json.loads(text)
            captured["cfg_text"] = text
        return MagicMock(is_error=False, response_text="ok")

    runner.invoke = capture_with_text

    master = {
        "mcpServers": {
            "github": {"command": "x"},
            "cloudflare-write": {"command": "y"},
            "destructive-bash": {"command": "z"},
        }
    }
    # Only github is allowed.
    executor = SubagentExecutor(
        claude_runner=runner,
        master_mcp_config=master,
        allowed_mcp_servers=["github"],
    )
    await executor.execute(_wo())

    filtered = captured["filtered"]["mcpServers"]
    # Denied servers MUST be completely absent — not just disabled or
    # listed-but-empty. The subagent has no path to invoke them.
    assert "cloudflare-write" not in filtered
    assert "destructive-bash" not in filtered
    # And the filtered file as written to disk does not contain the
    # server names anywhere (defense against partial-key-stripping bugs).
    cfg_text = captured["cfg_text"]
    assert "cloudflare-write" not in cfg_text
    assert "destructive-bash" not in cfg_text


@pytest.mark.asyncio
async def test_subagent_mcp_filter_and_depth_guard_compose():
    """R5.2: The MCP allowlist filter and the recursion-depth env-var
    arrive on the same invocation.

    This is the composition assertion called out in R5.2 task list:
    "MCP filtering and write-jail filtering compose." A subagent that
    received the filtered config but no `BUMBA_AGENT_DEPTH=1` could
    re-spawn its own subagents and bypass the depth guard; a subagent
    that received `BUMBA_AGENT_DEPTH=1` but the full master MCP config
    could read/write through any server. Both boundaries must hold
    simultaneously on every subagent dispatch.
    """
    runner = MagicMock()
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        cfg_path = kwargs.get("mcp_config_path")
        if cfg_path:
            captured["filtered"] = json.loads(pathlib.Path(cfg_path).read_text())
        return MagicMock(is_error=False, response_text="ok")

    runner.invoke = capture

    master = {
        "mcpServers": {
            "github": {"command": "x"},
            "denied-server": {"command": "y"},
        }
    }
    executor = SubagentExecutor(
        claude_runner=runner,
        master_mcp_config=master,
        allowed_mcp_servers=["github"],
    )
    await executor.execute(_wo())

    # Boundary 1: MCP filtering active.
    filtered_servers = set(captured["filtered"]["mcpServers"].keys())
    assert filtered_servers == {"github"}
    assert "denied-server" not in filtered_servers

    # Boundary 2: recursion-depth guard active on the same invocation.
    env = captured.get("env_vars") or {}
    assert env.get("BUMBA_AGENT_DEPTH") == "1"
    assert env.get("BUMBA_AGENT_TOOL") == "subagent"
