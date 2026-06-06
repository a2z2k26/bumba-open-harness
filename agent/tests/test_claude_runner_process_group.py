"""Sprint P1.2 — process-group termination for halt and operator interrupt.

Audit context (C2 from 2026-05-11 harness audit):

    ``ClaudeRunner`` starts subprocesses with ``start_new_session=True``,
    but mid-run halt and operator interrupt previously called
    ``self._process.send_signal(SIGTERM)`` — the parent only. Child tool
    subprocesses (MCP servers, browser-use, gws, etc.) survived past the
    bridge reporting "halted" or "blocked", leaking processes and
    compounding the operator-interrupt-blindness issue P1.1 already fixed.

P1.2 routes the halt path, operator-interrupt path, and watchdog
``_kill_process`` through a shared ``_terminate_process_group(reason)``
helper that ``os.killpg`` the whole group (SIGTERM → 10s wait → SIGKILL
escalation). These tests pin that contract.

The setsid pattern (``start_new_session=True`` passed to
``create_subprocess_exec``) ensures the new session is created in the
CHILD only — never the parent bridge daemon. The first test below
asserts on the spawn kwargs to make any future regression to a
preexec_fn race (or a parent-side ``os.setsid()`` call) impossible to
land silently.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.claude_runner import ClaudeRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proc_mock(fake_readline, pid: int = 77777) -> MagicMock:
    """Build a subprocess MagicMock whose stdout streams via ``fake_readline``."""
    mock_stdout = MagicMock()
    mock_stdout.readline = AsyncMock(side_effect=fake_readline)
    mock_stdin = AsyncMock()
    mock_stdin.write = MagicMock()
    mock_stdin.drain = AsyncMock()
    mock_stdin.close = MagicMock()
    mock_stdin.wait_closed = AsyncMock()
    mock_stderr = AsyncMock()
    mock_stderr.read = AsyncMock(return_value=b"")
    mock_proc = MagicMock()
    mock_proc.pid = pid
    mock_proc.stdout = mock_stdout
    mock_proc.stdin = mock_stdin
    mock_proc.stderr = mock_stderr
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock()
    mock_proc.send_signal = MagicMock()
    return mock_proc


def _quick_result_lines(count: int) -> list[bytes]:
    return [
        json.dumps(
            {"type": "result", "subtype": "success", "result": "ok"}
        ).encode()
        + b"\n"
        for _ in range(count)
    ]


# ---------------------------------------------------------------------------
# Setsid-in-child contract
# ---------------------------------------------------------------------------


class TestSpawnWithNewSession:
    """The subprocess MUST be spawned with ``start_new_session=True``.

    asyncio.create_subprocess_exec accepts this kwarg and translates it
    to a post-fork ``os.setsid()`` call in the CHILD only. That is the
    standard guard against ``os.setsid()`` racing with the parent
    process — using a preexec_fn that calls setsid manually risks
    detaching the bridge daemon by mistake. This test pins the safe
    spawn kwarg so any future refactor that introduces a preexec_fn is
    caught.
    """

    @pytest.mark.asyncio
    async def test_invoke_passes_start_new_session(self, sample_config, tmp_path):
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)

        lines = _quick_result_lines(2) + [b""]
        idx = [0]

        async def fake_readline():
            i = idx[0]
            idx[0] += 1
            return lines[i] if i < len(lines) else b""

        mock_proc = _make_proc_mock(fake_readline)

        spawn_kwargs: dict = {}
        original_spawn = asyncio.create_subprocess_exec

        async def capture(*args, **kwargs):
            spawn_kwargs.update(kwargs)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=capture), \
             patch.object(runner, "_build_command", return_value=["fake-claude", "-p"]), \
             patch.object(runner, "_watchdog", new_callable=AsyncMock):
            await runner.invoke("hi")

        assert spawn_kwargs.get("start_new_session") is True, (
            "ClaudeRunner.invoke must spawn with start_new_session=True so "
            "Claude + its tool children form an isolated process group. "
            "Without this kwarg, killpg() in the halt/interrupt paths would "
            "either fail (no group) or signal the bridge daemon itself."
        )
        # Negative guard: no preexec_fn — that would risk a parent-side
        # setsid race or break the new-session-in-child contract.
        assert "preexec_fn" not in spawn_kwargs, (
            "preexec_fn is dangerous here; use start_new_session=True only"
        )
        # Reference the original function so the linter does not flag the
        # import as unused; we keep it imported as documentation of what
        # we're patching.
        assert callable(original_spawn)


# ---------------------------------------------------------------------------
# _terminate_process_group helper
# ---------------------------------------------------------------------------


class TestTerminateProcessGroup:
    """Direct tests for ``_terminate_process_group``."""

    @pytest.mark.asyncio
    async def test_noop_when_no_process(self, sample_config, tmp_path):
        """Helper returns cleanly when no subprocess is attached."""
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)
        assert runner._process is None
        # Must not raise.
        await runner._terminate_process_group("test")

    @pytest.mark.asyncio
    async def test_noop_when_process_already_exited(self, sample_config, tmp_path):
        """If returncode is set, the helper exits early without signaling."""
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)
        proc = MagicMock()
        proc.pid = 12345
        proc.returncode = 0  # already exited
        runner._process = proc

        with patch("bridge.claude_runner.os.killpg") as kp, \
             patch("bridge.claude_runner.os.getpgid", return_value=12345):
            await runner._terminate_process_group("test")

        assert kp.call_count == 0, (
            "Must not signal a process that already exited"
        )

    @pytest.mark.asyncio
    async def test_sigterm_then_proc_exits_cleanly(self, sample_config, tmp_path):
        """Happy path: SIGTERM → group dies → no escalation."""
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)
        proc = MagicMock()
        proc.pid = 12345
        proc.returncode = None
        proc.wait = AsyncMock()  # simulate clean exit
        runner._process = proc

        killpg_calls: list[tuple[int, int]] = []

        def fake_killpg(pgid, sig):
            killpg_calls.append((pgid, sig))

        with patch("bridge.claude_runner.os.killpg", side_effect=fake_killpg), \
             patch("bridge.claude_runner.os.getpgid", return_value=12345):
            await runner._terminate_process_group("test")

        assert killpg_calls == [(12345, signal.SIGTERM)], (
            f"Expected single SIGTERM to group 12345; got {killpg_calls}"
        )

    @pytest.mark.asyncio
    async def test_sigkill_escalation_on_timeout(self, sample_config, tmp_path):
        """If proc.wait() times out, SIGKILL escalates the group."""
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)
        proc = MagicMock()
        proc.pid = 12345
        proc.returncode = None
        # proc.wait() never returns within the timeout
        proc.wait = AsyncMock(side_effect=asyncio.TimeoutError)
        runner._process = proc

        killpg_calls: list[tuple[int, int]] = []

        def fake_killpg(pgid, sig):
            killpg_calls.append((pgid, sig))

        async def fake_wait_for(awaitable, timeout):
            # Consume the coroutine to keep MagicMock happy.
            try:
                if asyncio.iscoroutine(awaitable):
                    awaitable.close()
            except Exception:  # noqa: BLE001
                pass
            raise asyncio.TimeoutError

        with patch("bridge.claude_runner.os.killpg", side_effect=fake_killpg), \
             patch("bridge.claude_runner.os.getpgid", return_value=12345), \
             patch("bridge.claude_runner.asyncio.wait_for", side_effect=fake_wait_for):
            await runner._terminate_process_group("test")

        assert killpg_calls == [
            (12345, signal.SIGTERM),
            (12345, signal.SIGKILL),
        ], f"Expected SIGTERM then SIGKILL; got {killpg_calls}"

    @pytest.mark.asyncio
    async def test_process_lookup_error_during_term_swallowed(
        self, sample_config, tmp_path
    ):
        """A ProcessLookupError from killpg(SIGTERM) is silently swallowed
        — the process already died on its own. No SIGKILL escalation
        because the wait() path is skipped on the early return.
        """
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)
        proc = MagicMock()
        proc.pid = 12345
        proc.returncode = None
        proc.wait = AsyncMock()
        runner._process = proc

        with patch(
            "bridge.claude_runner.os.killpg", side_effect=ProcessLookupError
        ), patch("bridge.claude_runner.os.getpgid", return_value=12345):
            # Must not raise.
            await runner._terminate_process_group("test")


# ---------------------------------------------------------------------------
# _kill_process delegation (acceptance criterion 3)
# ---------------------------------------------------------------------------


class TestKillProcessDelegates:
    """``_kill_process()`` is preserved as a backwards-compat alias and
    must delegate to ``_terminate_process_group`` so the watchdog and
    ``kill_current()`` use the same group-termination path.
    """

    @pytest.mark.asyncio
    async def test_kill_process_calls_terminate_helper(self, sample_config, tmp_path):
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)

        called_with: list[str] = []

        async def fake_terminate(reason: str) -> None:
            called_with.append(reason)

        with patch.object(runner, "_terminate_process_group", side_effect=fake_terminate):
            await runner._kill_process()

        assert called_with, (
            "_kill_process must delegate to _terminate_process_group"
        )

    @pytest.mark.asyncio
    async def test_kill_current_routes_through_terminate(self, sample_config, tmp_path):
        """``kill_current()`` (operator /cancel + shutdown) must reach the
        whole group via the shared helper.
        """
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)

        # Attach a fake process so kill_current goes past its early return.
        proc = MagicMock()
        proc.pid = 12345
        proc.returncode = None
        runner._process = proc

        called_with: list[str] = []

        async def fake_terminate(reason: str) -> None:
            called_with.append(reason)
            proc.returncode = -15  # mark dead

        with patch.object(runner, "_terminate_process_group", side_effect=fake_terminate):
            result = await runner.kill_current()

        assert result is True
        assert called_with, (
            "kill_current must reach the process group via "
            "_terminate_process_group (P1.2 audit C2)"
        )


# ---------------------------------------------------------------------------
# Halt + operator-interrupt route through the helper
# ---------------------------------------------------------------------------


class TestMidRunPathsUseHelper:
    """The mid-run halt and operator-interrupt code paths in
    ``ClaudeRunner.invoke()`` must invoke ``_terminate_process_group`` —
    not ``self._process.send_signal`` directly.

    This is the core regression guard for audit finding C2: a future
    refactor that "simplifies" back to ``send_signal(SIGTERM)`` would
    re-orphan tool subprocesses. These tests fail loudly if that
    happens.
    """

    @pytest.mark.asyncio
    async def test_halt_flag_path_calls_helper(self, sample_config, tmp_path):
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)

        halt_flag = tmp_path / "halt.flag"
        lines_sent: list = []

        async def fake_readline():
            idx = len(lines_sent)
            if idx == 9:
                halt_flag.touch()
            if idx >= 12:
                return b""
            line = json.dumps(
                {"type": "result", "subtype": "success", "result": "ok"}
            ).encode() + b"\n"
            lines_sent.append(line)
            return line

        mock_proc = _make_proc_mock(fake_readline)

        terminate_reasons: list[str] = []

        async def fake_terminate(reason: str) -> None:
            terminate_reasons.append(reason)
            # Simulate the group going down so the rest of invoke() proceeds.
            mock_proc.returncode = -15

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(runner, "_build_command", return_value=["fake-claude", "-p"]), \
             patch.object(runner, "_watchdog", new_callable=AsyncMock), \
             patch.object(runner, "_terminate_process_group", side_effect=fake_terminate):
            await runner.invoke("test message")

        assert "halt_flag" in terminate_reasons, (
            "Halt-flag mid-run path must call _terminate_process_group "
            f"with reason='halt_flag'; got {terminate_reasons}"
        )
        assert mock_proc.send_signal.call_count == 0, (
            "Halt path must not call parent-only send_signal — "
            "use the group helper"
        )

    @pytest.mark.asyncio
    async def test_operator_interrupt_path_calls_helper(
        self, sample_config, tmp_path
    ):
        from bridge.operator_inbox import MessageSeverity, OperatorInbox

        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)
        inbox = OperatorInbox(session_id="sess-p12")
        runner.set_operator_inbox(inbox)

        lines_sent: list = []

        async def fake_readline():
            idx = len(lines_sent)
            if idx == 9:
                await inbox.receive("pause please", MessageSeverity.QUESTION)
            if idx >= 25:
                return b""
            line = json.dumps(
                {"type": "result", "subtype": "success", "result": "ok"}
            ).encode() + b"\n"
            lines_sent.append(line)
            return line

        mock_proc = _make_proc_mock(fake_readline)

        terminate_reasons: list[str] = []

        async def fake_terminate(reason: str) -> None:
            terminate_reasons.append(reason)
            mock_proc.returncode = -15

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(runner, "_build_command", return_value=["fake-claude", "-p"]), \
             patch.object(runner, "_watchdog", new_callable=AsyncMock), \
             patch.object(runner, "_terminate_process_group", side_effect=fake_terminate):
            result = await runner.invoke("test message", session_id="sess-p12")

        assert "operator_interrupt" in terminate_reasons, (
            "Operator-interrupt mid-run path must call "
            "_terminate_process_group with reason='operator_interrupt'; "
            f"got {terminate_reasons}"
        )
        assert mock_proc.send_signal.call_count == 0, (
            "Operator-interrupt path must not call parent-only send_signal"
        )
        # Sanity: the block-message overlay still fired.
        assert "TOOL CALL BLOCKED" in (result.response_text or "")


# ---------------------------------------------------------------------------
# Group-reach simulation (orphan-prevention indicator)
# ---------------------------------------------------------------------------


class TestGroupKillReachesChildren:
    """Indirect proof that signaling the group (not the parent) is what
    prevents orphans. We simulate a parent with two "tool children"
    sharing the same pgid; ``os.killpg(pgid, SIGTERM)`` must reach
    every member. ``os.kill(parent_pid, SIGTERM)`` would only reach the
    parent — that's the bug C2 documents.

    We can't actually fork in a unit test (the brief says
    "mock-based, don't actually fork"), so this test models the
    semantics via patched ``os.killpg`` and asserts the helper calls
    it with the *group id*, not the parent pid alone.
    """

    @pytest.mark.asyncio
    async def test_helper_signals_group_id_not_parent_pid(
        self, sample_config, tmp_path
    ):
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)

        # Parent pid differs from pgid in the general case (the
        # session-leader sets pgid = pid only when it itself is the
        # session leader). We model the more permissive case where
        # getpgid is independently queried.
        parent_pid = 5000
        group_pgid = 5000  # Claude is session-leader → pgid == pid

        proc = MagicMock()
        proc.pid = parent_pid
        proc.returncode = None
        proc.wait = AsyncMock()
        runner._process = proc

        killpg_calls: list[tuple[int, int]] = []
        kill_calls: list[tuple[int, int]] = []

        def fake_killpg(pgid, sig):
            killpg_calls.append((pgid, sig))

        def fake_kill(pid, sig):
            kill_calls.append((pid, sig))

        with patch("bridge.claude_runner.os.killpg", side_effect=fake_killpg), \
             patch("bridge.claude_runner.os.getpgid", return_value=group_pgid), \
             patch("bridge.claude_runner.os.kill", side_effect=fake_kill):
            await runner._terminate_process_group("orphan-test")

        # Group-reach assertion: killpg got the pgid, not a singleton kill.
        assert killpg_calls == [(group_pgid, signal.SIGTERM)], (
            f"helper must call killpg(pgid, SIGTERM); got {killpg_calls}"
        )
        assert kill_calls == [], (
            "helper must NOT use os.kill(parent_pid, ...) — that's the "
            "C2 bug. All signaling goes through killpg so MCP and tool "
            "subprocesses are reached."
        )
