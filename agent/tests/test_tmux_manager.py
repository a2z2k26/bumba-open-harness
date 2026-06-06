"""Tests for bridge.tmux_manager — TmuxManager async wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bridge.tmux_manager import TmuxManager


@pytest.fixture
def mgr():
    return TmuxManager(socket_name="test-socket")


class TestIsAvailable:
    @pytest.mark.asyncio
    async def test_available_when_binary_found(self, mgr):
        with patch("bridge.tmux_manager.shutil.which", return_value="/usr/bin/tmux"):
            assert await mgr.is_available() is True

    @pytest.mark.asyncio
    async def test_unavailable_when_no_binary(self, mgr):
        with patch("bridge.tmux_manager.shutil.which", return_value=None):
            assert await mgr.is_available() is False


class TestRunTmux:
    @pytest.mark.asyncio
    async def test_passes_socket_flag(self, mgr):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            rc, stdout, stderr = await mgr._run_tmux("list-sessions")

        call_args = mock_exec.call_args[0]
        assert call_args[0] == "tmux"
        assert call_args[1] == "-L"
        assert call_args[2] == "test-socket"
        assert call_args[3] == "list-sessions"
        assert rc == 0
        assert stdout == "ok"

    @pytest.mark.asyncio
    async def test_handles_stderr(self, mgr):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error text"))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            rc, stdout, stderr = await mgr._run_tmux("bad-command")

        assert rc == 1
        assert stderr == "error text"


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_basic_create(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(0, "", ""))
        rc, _, _ = await mgr.create_session("test-session", "echo hello")
        args = mgr._run_tmux.call_args[0]
        assert "new-session" in args
        assert "-d" in args
        assert "-s" in args
        assert "test-session" in args

    @pytest.mark.asyncio
    async def test_with_working_dir(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(0, "", ""))
        await mgr.create_session("s1", "echo hi", working_dir="/tmp/test")
        args = mgr._run_tmux.call_args[0]
        assert "-c" in args
        assert "/tmp/test" in args

    @pytest.mark.asyncio
    async def test_with_env_vars(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(0, "", ""))
        await mgr.create_session("s1", "echo hi", env={"FOO": "bar"})
        args = mgr._run_tmux.call_args[0]
        # The shell command should contain export
        shell_arg = args[-1]  # Last arg is the bash -c command
        assert "export" in shell_arg
        assert "FOO" in shell_arg


class TestKillSession:
    @pytest.mark.asyncio
    async def test_kill_success(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(0, "", ""))
        assert await mgr.kill_session("s1") is True

    @pytest.mark.asyncio
    async def test_kill_failure(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(1, "", "no session"))
        assert await mgr.kill_session("s1") is False


class TestSessionExists:
    @pytest.mark.asyncio
    async def test_exists(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(0, "", ""))
        assert await mgr.session_exists("s1") is True

    @pytest.mark.asyncio
    async def test_not_exists(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(1, "", ""))
        assert await mgr.session_exists("s1") is False


class TestListSessions:
    @pytest.mark.asyncio
    async def test_parses_format(self, mgr):
        output = "bumba-abc|1|1710000000\nbumba-def|1|1710000100"
        mgr._run_tmux = AsyncMock(return_value=(0, output, ""))
        sessions = await mgr.list_sessions()
        assert len(sessions) == 2
        assert sessions[0]["name"] == "bumba-abc"
        assert sessions[1]["name"] == "bumba-def"

    @pytest.mark.asyncio
    async def test_empty_when_no_server(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(1, "", "no server"))
        sessions = await mgr.list_sessions()
        assert sessions == []


class TestCapture:
    @pytest.mark.asyncio
    async def test_capture_returns_output(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(0, "line1\nline2", ""))
        text = await mgr.capture_pane("s1", lines=10)
        assert "line1" in text

    @pytest.mark.asyncio
    async def test_capture_failure_returns_empty(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(1, "", "error"))
        text = await mgr.capture_pane("s1")
        assert text == ""


class TestSendKeys:
    @pytest.mark.asyncio
    async def test_send_keys_success(self, mgr):
        mgr._run_tmux = AsyncMock(return_value=(0, "", ""))
        assert await mgr.send_keys("s1", "C-c") is True


class TestKillAll:
    @pytest.mark.asyncio
    async def test_kills_all_sessions(self, mgr):
        mgr.list_sessions = AsyncMock(return_value=[
            {"name": "s1", "windows": "1", "created": "0"},
            {"name": "s2", "windows": "1", "created": "0"},
        ])
        mgr.kill_session = AsyncMock(return_value=True)
        count = await mgr.kill_all_sessions()
        assert count == 2
        assert mgr.kill_session.call_count == 2
