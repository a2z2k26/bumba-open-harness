"""E2BExecutor — operable sandbox run via the bumba-sandbox MCP (#416, #2345).

The executor reuses ``claude_runner`` against a filtered MCP config exposing
only the ``bumba-sandbox`` server, which owns the E2B SDK + sandbox lifecycle.
These tests drive ``execute()`` with a mocked claude_runner boundary and assert
a real sandbox run is invoked (not NotImplementedError), with the E2B
credential injected and the MCP config filtered to bumba-sandbox only. The
flag/key/runner gate paths are preserved.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bridge.executors.e2b import (
    E2B_ALLOWED_TOOLS,
    E2B_GATE_MESSAGE,
    E2B_MCP_SERVER,
    E2BExecutor,
)
from bridge.work_order import Environment, WorkOrder, WorkOrderStatus


def _make_wo(intent: str = "run e2b task") -> WorkOrder:
    return (
        WorkOrder.create(intent=intent, skill="ship-feature", project="p")
        .with_environment(Environment.E2B, "test")
        .transition(WorkOrderStatus.ASSIGNED)
    )


# Master MCP config mirroring the runtime .mcp.json shape — bumba-sandbox plus
# a couple of servers that MUST be filtered out of the E2B loadout.
_MASTER_MCP = {
    "mcpServers": {
        "bumba-sandbox": {
            "type": "stdio",
            "command": "node",
            "args": ["/x/bumba-sandbox/dist/mcp-servers/bumba-sandbox.js"],
            "env": {"E2B_API_KEY": "${E2B_API_KEY}"},
        },
        "github": {"type": "stdio", "command": "node", "args": ["gh.js"]},
        "bumba-memory": {"type": "stdio", "command": "node", "args": ["mem.js"]},
    }
}


def _make_result():
    from bridge.claude_runner import ClaudeResult

    return ClaudeResult(response_text="sandbox ran ok", session_id="e2b-x")


# ---------------------------------------------------------------------------
# Gate paths — non-routable combinations raise, never silently fall through
# ---------------------------------------------------------------------------


def test_status_default_is_conditional_unwired() -> None:
    """Default-off (no flag/key/runner) is non-routable."""
    assert E2BExecutor().get_status() == "conditional_unwired"


def test_status_flag_and_key_without_runner_is_conditional_unwired() -> None:
    """Flag + key but no runner is still non-routable — can't actually run."""
    ex = E2BExecutor(enabled=True, api_key="e2b-test-key")
    assert ex.get_status() == "conditional_unwired"


def test_status_enabled_with_key_and_runner_is_conditional_active() -> None:
    """Flag + key + runner clears the gate and is routable."""
    ex = E2BExecutor(
        enabled=True, api_key="e2b-test-key", claude_runner=AsyncMock()
    )
    assert ex.get_status() == "conditional_active"


def test_status_empty_key_is_conditional_unwired() -> None:
    """Whitespace-only key does not satisfy the credential gate."""
    ex = E2BExecutor(enabled=True, api_key="   ", claude_runner=AsyncMock())
    assert ex.get_status() == "conditional_unwired"


@pytest.mark.asyncio
async def test_execute_raises_when_gate_active() -> None:
    """Non-routable execute raises RuntimeError (no NotImplementedError, no
    silent fallthrough) with the activation checklist reference."""
    ex = E2BExecutor()  # default-off
    with pytest.raises(RuntimeError) as excinfo:
        await ex.execute(_make_wo())
    msg = str(excinfo.value)
    assert "executor-roadmap.md" in msg
    assert "#416" in msg
    assert "WORKTREE" in msg or "worktree" in msg.lower()


@pytest.mark.asyncio
async def test_execute_does_not_raise_not_implemented() -> None:
    """Regression: the operable path must NOT raise NotImplementedError."""
    runner = AsyncMock()
    runner.invoke.return_value = _make_result()
    ex = E2BExecutor(
        enabled=True,
        api_key="e2b-test-key",
        claude_runner=runner,
        master_mcp_config=_MASTER_MCP,
    )
    result = await ex.execute(_make_wo())  # must not raise
    assert result.response_text == "sandbox ran ok"


def test_gate_message_constant_references_roadmap_and_issue() -> None:
    assert "executor-roadmap.md" in E2B_GATE_MESSAGE
    assert "#416" in E2B_GATE_MESSAGE


# ---------------------------------------------------------------------------
# Operable path — a real sandbox run is invoked through claude_runner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_invokes_runner_once_with_wo_intent() -> None:
    """The WorkOrder intent is the message handed to the sandbox agent."""
    runner = AsyncMock()
    runner.invoke.return_value = _make_result()
    ex = E2BExecutor(
        enabled=True,
        api_key="e2b-test-key",
        claude_runner=runner,
        master_mcp_config=_MASTER_MCP,
    )
    wo = _make_wo(intent="build and test the widget")
    await ex.execute(wo)

    runner.invoke.assert_awaited_once()
    kwargs = runner.invoke.await_args.kwargs
    assert kwargs["message"] == "build and test the widget"
    # A sandbox run is one-shot — claude must start a FRESH session, so no
    # session_id is passed (None → no --resume flag in build_command).
    assert kwargs["session_id"] is None


@pytest.mark.asyncio
async def test_execute_does_not_pass_synthetic_session_id_to_resume() -> None:
    """Regression guard (#2345): the executor MUST NOT hand claude_runner a
    synthetic non-UUID session id.

    claude's ``--resume`` requires a real UUID / existing session title. A
    synthetic ``e2b-<hash>`` made ``claude -p --resume e2b-<hash>`` fail with
    "not a UUID and does not match any session" (exit 1, num_turns 0). The fix
    is to start a fresh session: session_id passed to invoke must be falsy AND
    must never be the synthetic ``e2b-<hash>`` label. Asserting the real invoke
    kwargs guards the boundary against regression.
    """
    runner = AsyncMock()
    runner.invoke.return_value = _make_result()
    ex = E2BExecutor(
        enabled=True,
        api_key="e2b-test-key",
        claude_runner=runner,
        master_mcp_config=_MASTER_MCP,
    )
    wo = _make_wo()
    await ex.execute(wo)

    passed_session_id = runner.invoke.await_args.kwargs["session_id"]
    # No --resume → fresh session.
    assert not passed_session_id
    # And specifically NOT the synthetic e2b-<hash> id that claude rejects.
    assert passed_session_id != f"e2b-{wo.id[:8]}"


@pytest.mark.asyncio
async def test_execute_injects_e2b_api_key_into_env() -> None:
    """The credential reaches the subprocess env so bumba-sandbox can auth."""
    runner = AsyncMock()
    runner.invoke.return_value = _make_result()
    ex = E2BExecutor(
        enabled=True,
        api_key="e2b-secret-123",
        claude_runner=runner,
        master_mcp_config=_MASTER_MCP,
    )
    await ex.execute(_make_wo())

    env = runner.invoke.await_args.kwargs["env_vars"]
    assert env["E2B_API_KEY"] == "e2b-secret-123"
    # write-jail markers present
    assert env["BUMBA_AGENT_DEPTH"] == "1"
    assert env["BUMBA_AGENT_TOOL"] == "e2b"


@pytest.mark.asyncio
async def test_execute_filters_mcp_config_to_bumba_sandbox_only() -> None:
    """The agent only sees bumba-sandbox — github/memory are filtered out.

    The temp config is cleaned up in execute()'s finally block, so we read it
    DURING the invoke (while it still exists on disk).
    """
    captured: dict = {}

    async def _invoke(*args, **kwargs):
        captured["written"] = json.loads(Path(kwargs["mcp_config_path"]).read_text())
        return _make_result()

    runner = AsyncMock()
    runner.invoke = _invoke
    ex = E2BExecutor(
        enabled=True,
        api_key="e2b-test-key",
        claude_runner=runner,
        master_mcp_config=_MASTER_MCP,
    )
    await ex.execute(_make_wo())

    written = captured["written"]
    # SCHEMA GUARD (#2345): the written file `claude -p --mcp-config` reads
    # MUST carry a top-level `mcpServers` object. A mock that only checks
    # invoke kwargs (the prior test shape) hid the real-binary rejection
    # "mcpServers: Does not adhere to MCP server configuration schema".
    assert set(written.keys()) == {"mcpServers"}, (
        f"filtered config must have exactly the mcpServers key, got {written!r}"
    )
    servers = written["mcpServers"]
    assert E2B_MCP_SERVER in servers
    assert "github" not in servers
    assert "bumba-memory" not in servers
    # The bumba-sandbox entry must keep its canonical stdio shape.
    entry = servers[E2B_MCP_SERVER]
    assert entry["type"] == "stdio"
    assert entry["command"] == "node"
    assert isinstance(entry["args"], list)


@pytest.mark.asyncio
async def test_execute_writes_schema_valid_config_when_sandbox_absent() -> None:
    """Live seam bug #2345: when the master config has no bumba-sandbox entry
    (the runtime state the diagnostic hit), the filter used to degrade to a
    bare ``{}`` — which claude rejects with "mcpServers: Does not adhere to
    MCP server configuration schema" before the sandbox ever starts. The
    written file MUST still carry an (empty) ``mcpServers`` object so the
    subprocess boots instead of crashing with num_turns=0.
    """
    captured: dict = {}

    async def _invoke(*args, **kwargs):
        captured["written"] = json.loads(Path(kwargs["mcp_config_path"]).read_text())
        return _make_result()

    runner = AsyncMock()
    runner.invoke = _invoke
    # Master config WITHOUT bumba-sandbox — reproduces the runtime mismatch.
    ex = E2BExecutor(
        enabled=True,
        api_key="e2b-test-key",
        claude_runner=runner,
        master_mcp_config={"mcpServers": {"github": {"type": "stdio", "command": "x"}}},
    )
    await ex.execute(_make_wo())

    written = captured["written"]
    assert "mcpServers" in written, (
        "schema-invalid: claude -p --mcp-config rejects a config with no "
        "mcpServers key (the #2345 crash)"
    )
    assert written["mcpServers"] == {}  # zero matches, but well-formed


@pytest.mark.asyncio
async def test_execute_passes_allowed_tools_for_deferred_mcp_surfacing() -> None:
    """The bumba-sandbox MCP tools are pre-authorized via allowed_tools (#2345).

    Recent Claude Code defers MCP tools behind ToolSearch — they are not in
    the init tools list and are not callable unless allowed. The executor must
    name the concrete ``mcp__bumba-sandbox__<tool>`` identifiers so the one-shot
    agent can call them the moment ToolSearch surfaces them.
    """
    runner = AsyncMock()
    runner.invoke.return_value = _make_result()
    ex = E2BExecutor(
        enabled=True,
        api_key="e2b-test-key",
        claude_runner=runner,
        master_mcp_config=_MASTER_MCP,
    )
    await ex.execute(_make_wo())

    allowed = runner.invoke.await_args.kwargs["allowed_tools"]
    assert allowed == E2B_ALLOWED_TOOLS
    # Every entry is the fully-qualified mcp__<server>__<tool> identifier.
    assert all(t.startswith(f"mcp__{E2B_MCP_SERVER}__") for t in allowed)
    # The lifecycle-critical tools (real registered names) are present.
    assert f"mcp__{E2B_MCP_SERVER}__sandbox_init" in allowed
    assert f"mcp__{E2B_MCP_SERVER}__execute_command" in allowed
    assert f"mcp__{E2B_MCP_SERVER}__sandbox_kill" in allowed


@pytest.mark.asyncio
async def test_execute_uses_e2b_system_prompt_when_present() -> None:
    """The E2B sandbox system prompt is shipped and passed to the runner."""
    runner = AsyncMock()
    runner.invoke.return_value = _make_result()
    ex = E2BExecutor(
        enabled=True,
        api_key="e2b-test-key",
        claude_runner=runner,
        master_mcp_config=_MASTER_MCP,
    )
    await ex.execute(_make_wo())

    prompt = runner.invoke.await_args.kwargs["system_prompt_file"]
    assert prompt is not None and prompt.endswith("e2b.md")
    assert Path(prompt).exists()


@pytest.mark.asyncio
async def test_execute_cleans_up_temp_config_on_runner_error() -> None:
    """A runner exception propagates but the temp MCP config is cleaned up."""
    captured: dict[str, str] = {}

    async def _invoke(*args, **kwargs):
        captured["cfg"] = kwargs["mcp_config_path"]
        raise RuntimeError("sandbox blew up")

    runner = AsyncMock()
    runner.invoke = _invoke
    ex = E2BExecutor(
        enabled=True,
        api_key="e2b-test-key",
        claude_runner=runner,
        master_mcp_config=_MASTER_MCP,
    )
    with pytest.raises(RuntimeError, match="sandbox blew up"):
        await ex.execute(_make_wo())

    assert captured.get("cfg")
    assert not Path(captured["cfg"]).exists(), "temp MCP config must be cleaned up"
