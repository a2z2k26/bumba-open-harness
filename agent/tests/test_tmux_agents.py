"""Tests for bridge.tmux_agents — TmuxAgentManager lifecycle."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_TMPDIR = Path(tempfile.gettempdir())

from bridge.tmux_agents import AgentState, TmuxAgentManager


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory with required subdirs."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "service_messages").mkdir()
    return tmp_path


@pytest.fixture
def mock_config(tmp_data_dir):
    cfg = MagicMock()
    cfg.data_dir = str(tmp_data_dir)
    cfg.claude_working_dir = "/tmp"
    cfg.claude_oauth_token = "test-token-123"
    cfg.claude_binary = "/usr/local/bin/claude"
    cfg.operator_discord_id = "123456"
    return cfg


@pytest.fixture
def mock_tmux():
    tmux = AsyncMock()
    tmux.is_available = AsyncMock(return_value=True)
    tmux.create_session = AsyncMock(return_value=(0, "", ""))
    tmux.session_exists = AsyncMock(return_value=True)
    tmux.kill_session = AsyncMock(return_value=True)
    tmux.list_sessions = AsyncMock(return_value=[])
    tmux.capture_pane = AsyncMock(return_value="some output")
    return tmux


@pytest.fixture
def mock_token_provider():
    tp = MagicMock()
    tp.access_token = "fresh-token-456"
    return tp


@pytest.fixture
def manager(mock_tmux, mock_config, mock_token_provider):
    return TmuxAgentManager(
        tmux=mock_tmux,
        config=mock_config,
        token_provider=mock_token_provider,
        autonomy=None,
        max_concurrent=3,
    )


class TestSpawnAgent:
    @pytest.mark.asyncio
    async def test_spawn_success(self, manager, mock_tmux):
        result = await manager.spawn_agent("Analyze code")
        assert isinstance(result, AgentState)
        assert result.status == "running"
        assert result.task == "Analyze code"
        assert result.agent_id
        mock_tmux.create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_spawn_empty_task(self, manager):
        result = await manager.spawn_agent("  ")
        assert isinstance(result, str)
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_spawn_max_concurrent(self, manager, mock_tmux):
        # Spawn 3 agents
        for i in range(3):
            r = await manager.spawn_agent(f"Task {i}")
            assert isinstance(r, AgentState)

        # 4th should fail
        result = await manager.spawn_agent("Task 4")
        assert isinstance(result, str)
        assert "Max concurrent" in result

    @pytest.mark.asyncio
    async def test_spawn_no_tmux(self, manager, mock_tmux):
        mock_tmux.is_available = AsyncMock(return_value=False)
        result = await manager.spawn_agent("Test")
        assert isinstance(result, str)
        assert "tmux" in result.lower()

    @pytest.mark.asyncio
    async def test_spawn_creates_task_file(self, manager, tmp_data_dir):
        result = await manager.spawn_agent("Do something")
        assert isinstance(result, AgentState)
        task_file = tmp_data_dir / "agents" / result.agent_id / "task.txt"
        assert task_file.exists()
        assert task_file.read_text() == "Do something"

    @pytest.mark.asyncio
    async def test_spawn_uses_token_provider(self, manager, mock_tmux, mock_token_provider):
        """S05: token lives in wrapper script body, NOT env=/argv."""
        result = await manager.spawn_agent("Test")
        assert isinstance(result, AgentState)

        # Must NOT appear in env= (what leaked via ps in the old code)
        call_kwargs = mock_tmux.create_session.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env") or {}
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env

        # The command passed to tmux is now the wrapper script path
        cmd = call_kwargs.kwargs.get("command", "")
        assert cmd == result.wrapper_script
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in cmd  # script PATH carries no secrets
        assert "fresh-token-456" not in cmd         # token string absent from argv

        # But the token IS in the wrapper script's file body
        body = Path(result.wrapper_script).read_text()
        assert "fresh-token-456" in body
        assert "export CLAUDE_CODE_OAUTH_TOKEN=" in body

    @pytest.mark.asyncio
    async def test_spawn_tmux_failure(self, manager, mock_tmux):
        mock_tmux.create_session = AsyncMock(return_value=(1, "", "cannot create"))
        result = await manager.spawn_agent("Test")
        assert isinstance(result, str)
        assert "Failed" in result

    @pytest.mark.asyncio
    async def test_spawn_saves_registry(self, manager, tmp_data_dir):
        await manager.spawn_agent("Test")
        registry = tmp_data_dir / "agents" / "registry.json"
        assert registry.exists()
        data = json.loads(registry.read_text())
        assert len(data) == 1


class TestMonitorAgents:
    @pytest.mark.asyncio
    async def test_completed_agent_collected(self, manager, mock_tmux, tmp_data_dir):
        # Spawn an agent
        agent = await manager.spawn_agent("Test task")
        assert isinstance(agent, AgentState)

        # Write output file with result
        output_path = Path(agent.output_file)
        output_path.write_text(
            '{"type":"result","cost_usd":0.05,"num_turns":3,"result":"Done!","is_error":false}\n'
            'EXIT_CODE:0\n'
        )

        # Session is now gone
        mock_tmux.session_exists = AsyncMock(return_value=False)

        messages = await manager.monitor_agents()
        assert len(messages) == 1
        assert agent.status == "completed"
        assert agent.cost_usd == 0.05
        assert agent.result_text == "Done!"

    @pytest.mark.asyncio
    async def test_lifetime_exceeded_kills_agent(self, manager, mock_tmux, tmp_data_dir):
        agent = await manager.spawn_agent("Long task")
        assert isinstance(agent, AgentState)

        # Fake old start time
        agent.started_at = time.time() - 20000
        agent.max_lifetime_s = 100

        # Write minimal output so collect doesn't fail
        Path(agent.output_file).write_text('EXIT_CODE:137\n')

        messages = await manager.monitor_agents()
        assert len(messages) == 1
        assert agent.status == "killed"
        mock_tmux.kill_session.assert_called()

    @pytest.mark.asyncio
    async def test_still_running_no_change(self, manager, mock_tmux):
        agent = await manager.spawn_agent("Active task")
        assert isinstance(agent, AgentState)

        messages = await manager.monitor_agents()
        assert len(messages) == 0
        assert agent.status == "running"


class TestCollectResult:
    @pytest.mark.asyncio
    async def test_parse_stream_json_output(self, manager, tmp_data_dir):
        agent = AgentState(
            agent_id="abc12345",
            session_name="bumba-abc12345",
            task="Test",
            status="running",
            started_at=time.time(),
            output_file=str(tmp_data_dir / "agents" / "abc12345" / "output.jsonl"),
        )
        (tmp_data_dir / "agents" / "abc12345").mkdir(parents=True, exist_ok=True)

        output = (
            '{"type":"system","subtype":"init","session_id":"sess-1"}\n'
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Analyzing..."}]}}\n'
            '{"type":"result","cost_usd":0.12,"num_turns":5,"result":"Found 3 issues.","is_error":false}\n'
            'EXIT_CODE:0\n'
        )
        Path(agent.output_file).write_text(output)

        await manager._collect_result(agent)
        assert agent.status == "completed"
        assert agent.cost_usd == 0.12
        assert agent.num_turns == 5
        assert "3 issues" in agent.result_text
        assert agent.exit_code == 0

    @pytest.mark.asyncio
    async def test_missing_output_file(self, manager):
        agent = AgentState(
            agent_id="xyz",
            session_name="bumba-xyz",
            task="Test",
            status="running",
            output_file="/nonexistent/output.jsonl",
        )
        await manager._collect_result(agent)
        assert agent.status == "failed"
        assert "not found" in agent.error

    @pytest.mark.asyncio
    async def test_delivers_service_message(self, manager, tmp_data_dir):
        agent = AgentState(
            agent_id="msg12345",
            session_name="bumba-msg12345",
            task="Generate report",
            status="running",
            started_at=time.time(),
            output_file=str(tmp_data_dir / "agents" / "msg12345" / "output.jsonl"),
        )
        (tmp_data_dir / "agents" / "msg12345").mkdir(parents=True, exist_ok=True)
        Path(agent.output_file).write_text(
            '{"type":"result","cost_usd":0.01,"num_turns":1,"result":"Report ready.","is_error":false}\n'
            'EXIT_CODE:0\n'
        )

        await manager._collect_result(agent)

        # Check service message was written
        msgs = list((tmp_data_dir / "service_messages").glob("tmux-agent_*.json"))
        assert len(msgs) == 1
        msg_data = json.loads(msgs[0].read_text())
        assert msg_data["source"] == "tmux-agent"
        assert "Report ready" in msg_data["text"]


class TestKillAgent:
    @pytest.mark.asyncio
    async def test_kill_running_agent(self, manager, mock_tmux, tmp_data_dir):
        agent = await manager.spawn_agent("Kill me")
        assert isinstance(agent, AgentState)

        # Write output file
        Path(agent.output_file).write_text('EXIT_CODE:137\n')

        result = await manager.kill_agent(agent.agent_id)
        assert result is True
        assert agent.status == "killed"

    @pytest.mark.asyncio
    async def test_kill_nonexistent(self, manager):
        result = await manager.kill_agent("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_kill_completed_agent(self, manager, mock_tmux, tmp_data_dir):
        agent = await manager.spawn_agent("Done task")
        assert isinstance(agent, AgentState)
        agent.status = "completed"
        result = await manager.kill_agent(agent.agent_id)
        assert result is False


class TestFormatting:
    def test_empty_table(self, manager):
        assert manager.format_agents_table() == "No agents."

    @pytest.mark.asyncio
    async def test_table_with_agents(self, manager, mock_tmux):
        await manager.spawn_agent("Task A")
        await manager.spawn_agent("Task B")
        table = manager.format_agents_table()
        assert "Task A" in table
        assert "Task B" in table
        assert "running" in table

    @pytest.mark.asyncio
    async def test_detail_found(self, manager, mock_tmux):
        agent = await manager.spawn_agent("Detail task")
        assert isinstance(agent, AgentState)
        detail = manager.format_agent_detail(agent.agent_id)
        assert detail is not None
        assert "Detail task" in detail

    def test_detail_not_found(self, manager):
        assert manager.format_agent_detail("nope") is None


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_preserves_active_agents(self, manager, mock_tmux, tmp_data_dir):
        await manager.spawn_agent("Active 1")
        await manager.spawn_agent("Active 2")
        await manager.shutdown()
        # Agents should NOT be killed — they survive bridge restarts
        assert mock_tmux.kill_session.call_count == 0
        # Registry should be saved for recovery
        registry = tmp_data_dir / "agents" / "registry.json"
        assert registry.exists()
        data = json.loads(registry.read_text())
        assert len(data) == 2


class TestRecovery:
    @pytest.mark.asyncio
    async def test_recover_from_restart(self, manager, mock_tmux, tmp_data_dir):
        # Create a registry with a "running" agent
        agent = AgentState(
            agent_id="recov123",
            session_name="bumba-recov123",
            task="Recover me",
            status="running",
            started_at=time.time() - 100,
            output_file=str(tmp_data_dir / "agents" / "recov123" / "output.jsonl"),
        )
        (tmp_data_dir / "agents" / "recov123").mkdir(parents=True, exist_ok=True)

        registry = tmp_data_dir / "agents" / "registry.json"
        registry.write_text(json.dumps({"recov123": agent.to_dict()}))

        # Write output
        Path(agent.output_file).write_text('EXIT_CODE:0\n')

        # Session is gone
        mock_tmux.session_exists = AsyncMock(return_value=False)

        count = await manager.recover_from_restart()
        assert count == 1
        assert manager._agents["recov123"].status in ("completed", "failed")


class TestAgentStateSerialize:
    def test_roundtrip(self):
        state = AgentState(
            agent_id="test123",
            session_name="bumba-test123",
            task="Roundtrip test",
            status="running",
            started_at=time.time(),
        )
        d = state.to_dict()
        restored = AgentState.from_dict(d)
        assert restored.agent_id == state.agent_id
        assert restored.task == state.task
        assert restored.status == state.status

    def test_wrapper_script_roundtrip(self):
        """S05: wrapper_script field survives registry serialization."""
        state = AgentState(
            agent_id="s05test",
            wrapper_script=str(_TMPDIR / "bumba-tmux-wrap-s05test-abc.sh"),
        )
        assert AgentState.from_dict(state.to_dict()).wrapper_script == state.wrapper_script


# ----------------------------------------------------------------------
# S05 — TMUX token leak fix: wrapper-script architecture (issue #567)
# ----------------------------------------------------------------------

S05_TOKEN = "SECRET-TEST-TOKEN-do-not-leak-via-ps"


@pytest.fixture
def s05_config(tmp_data_dir):
    cfg = MagicMock()
    cfg.data_dir = str(tmp_data_dir)
    cfg.claude_working_dir = "/tmp"
    cfg.claude_oauth_token = S05_TOKEN
    cfg.claude_binary = "/usr/local/bin/claude-fake"
    cfg.operator_discord_id = "ignore"
    return cfg


@pytest.fixture
def s05_mgr(mock_tmux, s05_config):
    # No token provider — falls back to config.claude_oauth_token
    return TmuxAgentManager(tmux=mock_tmux, config=s05_config)


def _spawn_cmd(mock_tmux) -> str:
    return mock_tmux.create_session.await_args.kwargs["command"]


def _spawn_env(mock_tmux) -> dict:
    return mock_tmux.create_session.await_args.kwargs.get("env") or {}


class TestS05NoArgvLeak:
    """AC-1: OAuth token never appears in argv or the env dict passed to tmux."""

    @pytest.mark.asyncio
    async def test_token_not_in_tmux_env(self, s05_mgr, mock_tmux):
        result = await s05_mgr.spawn_agent("test task")
        assert isinstance(result, AgentState)

        env = _spawn_env(mock_tmux)
        # The whole point of S05: no env dict gets passed at all
        assert env == {} or env is None
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in (env or {})

    @pytest.mark.asyncio
    async def test_token_not_in_command_argv(self, s05_mgr, mock_tmux):
        result = await s05_mgr.spawn_agent("test task")
        assert isinstance(result, AgentState)

        cmd = _spawn_cmd(mock_tmux)
        # cmd is the script PATH, not a shell command with export
        assert S05_TOKEN not in cmd
        assert "export" not in cmd
        assert cmd.startswith(str(_TMPDIR / "bumba-tmux-wrap-"))
        assert cmd.endswith(".sh")


class TestS05WrapperScriptBody:
    """AC-2: wrapper script contains the token in its file body, mode 0700."""

    @pytest.mark.asyncio
    async def test_wrapper_contains_token(self, s05_mgr):
        result = await s05_mgr.spawn_agent("test task")
        assert isinstance(result, AgentState)

        body = Path(result.wrapper_script).read_text()
        assert "export CLAUDE_CODE_OAUTH_TOKEN=" in body
        assert S05_TOKEN in body

    @pytest.mark.asyncio
    async def test_wrapper_mode_0700(self, s05_mgr):
        result = await s05_mgr.spawn_agent("test task")
        assert isinstance(result, AgentState)

        mode = os.stat(result.wrapper_script).st_mode & 0o777
        assert mode == 0o700, f"wrapper mode is {oct(mode)}, expected 0o700"

    @pytest.mark.asyncio
    async def test_wrapper_runs_expected_claude_invocation(self, s05_mgr):
        """Ensure the wrapper still runs `cat task | claude -p ...`."""
        result = await s05_mgr.spawn_agent("test task", max_turns=5)
        body = Path(result.wrapper_script).read_text()

        assert "claude-fake" in body       # binary path
        assert "cat " in body              # task piped in
        assert "--max-turns 5" in body     # turns threaded through
        assert "--output-format stream-json" in body
        assert "--permission-mode bypassPermissions" in body
        assert "--dangerously-skip-permissions" not in body


class TestS05PermissionMode:
    """AC-3 + AC-4: native --permission-mode, no --dangerously-skip-permissions."""

    @pytest.mark.asyncio
    async def test_default_bypass(self, s05_mgr):
        result = await s05_mgr.spawn_agent("test task")
        body = Path(result.wrapper_script).read_text()
        assert "--permission-mode bypassPermissions" in body

    @pytest.mark.asyncio
    async def test_plan_mode(self, s05_mgr):
        result = await s05_mgr.spawn_agent("test task", permission_mode="plan")
        body = Path(result.wrapper_script).read_text()
        assert "--permission-mode plan" in body
        assert "--dangerously-skip-permissions" not in body

    @pytest.mark.asyncio
    async def test_auto_mode(self, s05_mgr):
        result = await s05_mgr.spawn_agent("test task", permission_mode="auto")
        body = Path(result.wrapper_script).read_text()
        assert "--permission-mode auto" in body


class TestS05WrapperCleanup:
    """AC-5: wrapper script is removed on session end, missing output, spawn fail."""

    @pytest.mark.asyncio
    async def test_cleanup_after_session_end(self, s05_mgr, mock_tmux):
        agent = await s05_mgr.spawn_agent("test task")
        wrapper = agent.wrapper_script
        assert Path(wrapper).exists()

        # Seed output file so _collect_result takes the happy path
        Path(agent.output_file).write_text(
            '{"type":"result","cost_usd":0.0,"num_turns":1,"result":"done"}\nEXIT_CODE:0\n'
        )
        mock_tmux.session_exists = AsyncMock(return_value=False)
        await s05_mgr.monitor_agents()

        assert not Path(wrapper).exists(), f"wrapper NOT removed: {wrapper}"
        assert agent.wrapper_script == ""

    @pytest.mark.asyncio
    async def test_cleanup_on_missing_output(self, s05_mgr, mock_tmux):
        agent = await s05_mgr.spawn_agent("test task")
        wrapper = agent.wrapper_script
        # No output file created — early-return path in _collect_result
        mock_tmux.session_exists = AsyncMock(return_value=False)
        await s05_mgr.monitor_agents()

        assert not Path(wrapper).exists()
        assert agent.wrapper_script == ""

    @pytest.mark.asyncio
    async def test_cleanup_on_spawn_failure(self, mock_tmux, s05_config):
        """Spawn failure cleans up the wrapper script it just created."""
        existing = set(_TMPDIR.glob("bumba-tmux-wrap-*.sh"))

        mock_tmux.create_session = AsyncMock(return_value=(1, "", "boom"))
        mgr = TmuxAgentManager(tmux=mock_tmux, config=s05_config)

        result = await mgr.spawn_agent("test task")
        assert isinstance(result, str)
        assert "boom" in result

        after = set(_TMPDIR.glob("bumba-tmux-wrap-*.sh"))
        assert not (after - existing), "spawn failure left orphan wrapper scripts"

    def test_reap_orphan_wrapper_scripts(self, mock_tmux, s05_config):
        mgr = TmuxAgentManager(tmux=mock_tmux, config=s05_config)

        orphan_id = "deadbeef"
        orphan = _TMPDIR / f"bumba-tmux-wrap-{orphan_id}-xxx.sh"
        orphan.write_text("#!/bin/bash\nexit 0\n")
        orphan.chmod(0o700)
        try:
            removed = mgr.reap_orphan_wrapper_scripts()
            assert removed >= 1
            assert not orphan.exists()
        finally:
            if orphan.exists():
                orphan.unlink()

    def test_reap_keeps_known_agent_wrappers(self, mock_tmux, s05_config):
        mgr = TmuxAgentManager(tmux=mock_tmux, config=s05_config)

        known_id = "cafe1234"
        wrapper = _TMPDIR / f"bumba-tmux-wrap-{known_id}-yyy.sh"
        wrapper.write_text("#!/bin/bash\nexit 0\n")
        wrapper.chmod(0o700)
        mgr._agents[known_id] = AgentState(agent_id=known_id, wrapper_script=str(wrapper))
        try:
            mgr.reap_orphan_wrapper_scripts()
            assert wrapper.exists()
        finally:
            if wrapper.exists():
                wrapper.unlink()


class TestS05WorkOrderPermissionMode:
    """WorkOrderConstraints.permission_mode survives serialization."""

    def test_default_is_bypass(self):
        from bridge.work_order import WorkOrderConstraints
        c = WorkOrderConstraints()
        assert c.permission_mode == "bypassPermissions"

    def test_roundtrip(self):
        from bridge.work_order import (
            Environment, WorkOrder, WorkOrderConstraints, WorkOrderStatus,
        )
        wo = WorkOrder(
            id="wo-s05-001",
            intent="test",
            skill="test-skill",
            project="bumba-open-harness",
            status=WorkOrderStatus.PENDING,
            environment=Environment.TMUX,
            constraints=WorkOrderConstraints(permission_mode="plan"),
        )
        assert WorkOrder.from_dict(wo.to_dict()).constraints.permission_mode == "plan"
