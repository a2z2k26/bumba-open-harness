"""Z3-02 tests — Claude Code `claude -p` executor for engineering specialists.

Per the Z3-00 premise audit (agent/scripts/audit_zone3_engineering.py), the
real `claude -p` subprocess chain already exists as SubagentExecutor /
ClaudeRunner. This module does NOT add a second subprocess runner; it adds the
deterministic *contract* the Zone 3 engineering dispatcher consumes:

  - build_claude_p_argv()  — pure argv builder (no I/O)
  - EngineeringRunResult   — structured, frozen result
  - run_claude_p_specialist() — async runner that delegates to an injected
    subprocess-spawn callable so unit tests never spawn real Claude.

All tests mock subprocess creation. No real Claude is spawned.
"""

from __future__ import annotations

import asyncio

import pytest

from bridge.backends import BackendProtocol
from bridge.backends._protocol import StreamEvent
from zone3.claude_p_executor import (
    EngineeringRunResult,
    build_claude_p_argv,
    run_claude_p_specialist,
)


# --- build_claude_p_argv: pure, tested first -------------------------------


def test_build_claude_p_argv_uses_p_flag() -> None:
    assert build_claude_p_argv(claude_binary="/usr/local/bin/claude") == [
        "/usr/local/bin/claude",
        "-p",
    ]


def test_build_claude_p_argv_can_pin_model() -> None:
    assert build_claude_p_argv(claude_binary="claude", model="sonnet") == [
        "claude",
        "-p",
        "--model",
        "sonnet",
    ]


def test_build_claude_p_argv_ignores_empty_model() -> None:
    assert build_claude_p_argv(claude_binary="claude", model="") == ["claude", "-p"]


# --- EngineeringRunResult contract -----------------------------------------


def test_run_result_is_frozen() -> None:
    result = EngineeringRunResult(
        specialist="engineering-backend-architect",
        success=True,
        stdout="ok",
        stderr="",
        exit_code=0,
        duration_seconds=0.1,
    )
    with pytest.raises(Exception):
        result.success = False  # type: ignore[misc]


# --- run_claude_p_specialist: mocked subprocess ----------------------------


class _FakeProc:
    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self, _stdin: bytes) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _spawn_factory(proc: _FakeProc):
    async def _spawn(argv, *, cwd, env):
        _spawn.calls.append({"argv": list(argv), "cwd": cwd, "env": dict(env or {})})
        return proc

    _spawn.calls = []  # type: ignore[attr-defined]
    return _spawn


def test_run_success_returns_structured_result() -> None:
    spawn = _spawn_factory(_FakeProc(returncode=0, stdout=b"done", stderr=b""))
    result = asyncio.run(
        run_claude_p_specialist(
            claude_binary="claude",
            specialist="engineering-code-reviewer",
            prompt="review this",
            cwd="/tmp/work",
            timeout_seconds=30,
            spawn=spawn,
        )
    )
    assert result.success is True
    assert result.specialist == "engineering-code-reviewer"
    assert result.stdout == "done"
    assert result.exit_code == 0
    assert result.error_class is None
    assert result.duration_seconds >= 0.0
    # argv carries -p; prompt is delivered via stdin, never on argv.
    assert spawn.calls[0]["argv"] == ["claude", "-p"]
    assert "review this" not in " ".join(spawn.calls[0]["argv"])


def test_run_nonzero_exit_is_failure() -> None:
    spawn = _spawn_factory(_FakeProc(returncode=2, stdout=b"", stderr=b"boom"))
    result = asyncio.run(
        run_claude_p_specialist(
            claude_binary="claude",
            specialist="x",
            prompt="p",
            cwd="/tmp",
            timeout_seconds=30,
            spawn=spawn,
        )
    )
    assert result.success is False
    assert result.exit_code == 2
    assert result.error_class == "claude_p_failed"


def test_run_missing_binary_returns_deterministic_error() -> None:
    async def _spawn(argv, *, cwd, env):
        raise FileNotFoundError("claude")

    result = asyncio.run(
        run_claude_p_specialist(
            claude_binary="claude",
            specialist="x",
            prompt="p",
            cwd="/tmp",
            timeout_seconds=30,
            spawn=_spawn,
        )
    )
    assert result.success is False
    assert result.exit_code != 0
    assert result.error_class == "claude_p_missing_binary"


def test_run_timeout_returns_deterministic_error() -> None:
    class _HangProc:
        returncode = None

        async def communicate(self, _stdin: bytes) -> tuple[bytes, bytes]:
            await asyncio.sleep(10)
            return b"", b""

        def kill(self) -> None:  # pragma: no cover - invoked on timeout cleanup
            self.returncode = -9

    proc = _HangProc()

    async def _spawn(argv, *, cwd, env):
        return proc

    result = asyncio.run(
        run_claude_p_specialist(
            claude_binary="claude",
            specialist="x",
            prompt="p",
            cwd="/tmp",
            timeout_seconds=0,
            spawn=_spawn,
        )
    )
    assert result.success is False
    assert result.error_class == "claude_p_timeout"


def test_run_does_not_inject_anthropic_token_into_env() -> None:
    spawn = _spawn_factory(_FakeProc(returncode=0, stdout=b"ok", stderr=b""))
    asyncio.run(
        run_claude_p_specialist(
            claude_binary="claude",
            specialist="x",
            prompt="p",
            cwd="/tmp",
            timeout_seconds=30,
            spawn=spawn,
            env={"PATH": "/usr/bin"},
        )
    )
    passed_env = spawn.calls[0]["env"]
    assert "ANTHROPIC_API_KEY" not in passed_env
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in passed_env


# --- backend-routing seam (P4.04) ------------------------------------------


class _StubZ3Backend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    @property
    def transport(self):
        return "subprocess"

    def resolve_binary(self):
        return "/opt/codex"

    def build_command(self, **kwargs):
        self.calls.append(kwargs)
        return ["/opt/codex", "exec", "--json"]

    def parse_event(self, line: str):
        return None

    def parse_cost(self, event):
        from bridge.cost_tracker import CostMeasurement

        return CostMeasurement(source="not_applicable", amount_usd=None)

    def auth_env(self):
        return {}

    def shutdown(self):
        return None

    def supports_tool_calling(self):
        return True

    def supports_system_prompt(self):
        return True

    def supports_mcp_config(self):
        return True

    def supports_tool_preauth(self):
        return True


class _HttpZ3Backend:
    @property
    def transport(self):
        return "http"

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def resolve_binary(self):
        raise AssertionError("HTTP Z3 run must not resolve a subprocess binary")

    def build_command(self, **kwargs):
        raise AssertionError("HTTP Z3 run must not build argv")

    def request(self, *, message: str, system_prompt: str | None = None):
        self.requests.append({"message": message, "system_prompt": system_prompt})
        return {"id": "gen-z3", "choices": [{"message": {"content": "done"}}]}

    def parse_event(self, line: str):
        return StreamEvent(type="result", text="done")

    def parse_cost(self, event):
        from bridge.cost_tracker import CostMeasurement

        return CostMeasurement(source="not_applicable", amount_usd=None)

    def auth_env(self):
        return {}

    def shutdown(self):
        return None

    def supports_tool_calling(self):
        return False

    def supports_system_prompt(self):
        return False

    def supports_mcp_config(self):
        return False

    def supports_tool_preauth(self):
        return False


def test_build_argv_sources_from_backend_when_provided() -> None:
    backend = _StubZ3Backend()
    assert isinstance(backend, BackendProtocol)
    argv = build_claude_p_argv(
        claude_binary="/usr/bin/claude",
        model="sonnet",
        backend=backend,
    )
    # backend wins: argv is the backend's command, not the hardcoded claude -p
    assert argv == ["/opt/codex", "exec", "--json"]
    # build_command was asked with the model threaded through; message is
    # empty because the prompt is delivered on stdin, never argv
    assert backend.calls[0]["model"] == "sonnet"
    assert backend.calls[0]["message"] == ""


def test_build_argv_falls_back_to_hardcoded_when_no_backend() -> None:
    argv = build_claude_p_argv(claude_binary="/usr/bin/claude", model="sonnet")
    assert argv == ["/usr/bin/claude", "-p", "--model", "sonnet"]


def test_build_argv_hardcoded_omits_model_when_none() -> None:
    argv = build_claude_p_argv(claude_binary="claude")
    assert argv == ["claude", "-p"]


def test_build_argv_rejects_http_backend() -> None:
    assert isinstance(_HttpZ3Backend(), BackendProtocol)
    with pytest.raises(ValueError, match="HTTP backend"):
        build_claude_p_argv(claude_binary="claude", backend=_HttpZ3Backend())


def test_run_specialist_supports_http_backend_without_spawn() -> None:
    backend = _HttpZ3Backend()
    assert isinstance(backend, BackendProtocol)

    async def _spawn_should_not_run(argv, *, cwd, env):
        raise AssertionError("HTTP Z3 run must not spawn a subprocess")

    result = asyncio.run(
        run_claude_p_specialist(
            claude_binary="claude",
            specialist="engineering-code-reviewer",
            prompt="review",
            cwd="/tmp",
            timeout_seconds=30,
            spawn=_spawn_should_not_run,
            backend=backend,
        )
    )

    assert result.success is True
    assert result.stdout == "done"
    assert result.exit_code == 0
    assert backend.requests == [{"message": "review", "system_prompt": None}]
