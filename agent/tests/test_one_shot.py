"""Unit tests for the one-shot backend spawn helper (Sprint P4.01).

Placed at tests/test_one_shot.py to match the repo's flat backend-test
convention (test_claude_backend.py, test_backend_registry.py, …) rather than
the tests/test_backends/ subpackage the issue body assumed — no such package
exists in the tree.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from bridge.backends.one_shot import OneShotResult, spawn_one_shot
from bridge.backends import BackendProtocol
from bridge.backends._protocol import StreamEvent


class _StubBackend:
    """Minimal BackendProtocol stub — records the args build_command saw."""

    def __init__(self, *, binary="claude", env=None):
        self._binary = binary
        self._env = env or {}
        self.build_command_calls: list[dict] = []

    @property
    def transport(self):
        return "subprocess"

    def resolve_binary(self):
        return self._binary

    def build_command(self, **kwargs):
        self.build_command_calls.append(kwargs)
        binary = self._binary
        prefix = [binary] if isinstance(binary, str) else list(binary)
        return [*prefix, "-p", "--output-format", "text"]

    def auth_env(self):
        return dict(self._env)

    def parse_event(self, line: str):
        return None

    def parse_cost(self, event):
        from bridge.cost_tracker import CostMeasurement

        return CostMeasurement(source="not_applicable", amount_usd=None)

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


class _HttpBackend:
    @property
    def transport(self):
        return "http"

    def __init__(self):
        self.requests: list[dict] = []

    def resolve_binary(self):
        raise AssertionError("HTTP one-shot must not resolve a subprocess binary")

    def build_command(self, **kwargs):
        raise AssertionError("HTTP one-shot must not build argv")

    def request(self, *, message: str, system_prompt: str | None = None):
        self.requests.append({"message": message, "system_prompt": system_prompt})
        return {"id": "gen-1", "choices": [{"message": {"content": "OK"}}]}

    def parse_event(self, line: str):
        return StreamEvent(type="result", text="OK", session_id="gen-1")

    def auth_env(self):
        return {}

    def parse_cost(self, event):
        from bridge.cost_tracker import CostMeasurement

        return CostMeasurement(source="not_applicable", amount_usd=None)

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


def test_spawn_one_shot_builds_argv_via_backend_and_passes_prompt_on_stdin():
    backend = _StubBackend(binary="/usr/bin/claude")
    assert isinstance(backend, BackendProtocol)

    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["input"] = kwargs.get("input")
        captured["env"] = kwargs.get("env")
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(args, 0, stdout="OK", stderr="")

    with patch("bridge.backends.one_shot.subprocess.run", side_effect=fake_run):
        result = spawn_one_shot(
            backend,
            prompt="classify this",
            timeout=120,
            permission_mode="default",
        )

    assert isinstance(result, OneShotResult)
    assert result.returncode == 0
    assert result.stdout == "OK"
    # argv came from the backend, NOT a hardcoded ["claude","-p",...]
    assert captured["args"][0] == "/usr/bin/claude"
    assert "-p" in captured["args"]
    # prompt delivered on stdin, never in argv
    assert captured["input"] == "classify this"
    assert "classify this" not in captured["args"]
    # build_command got the permission_mode through
    assert backend.build_command_calls[0]["permission_mode"] == "default"
    assert backend.build_command_calls[0]["message"] == "classify this"


def test_spawn_one_shot_merges_auth_env_over_base_env():
    backend = _StubBackend(env={"CLAUDE_CODE_OAUTH_TOKEN": "tok-123"})

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 0, stdout=kwargs["env"].get("CLAUDE_CODE_OAUTH_TOKEN", ""), stderr=""
        )

    with patch("bridge.backends.one_shot.subprocess.run", side_effect=fake_run):
        result = spawn_one_shot(backend, prompt="x", timeout=60)

    # auth_env() values landed in the subprocess env
    assert result.stdout == "tok-123"


def test_spawn_one_shot_propagates_timeout_expired():
    backend = _StubBackend()

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout"))

    with patch("bridge.backends.one_shot.subprocess.run", side_effect=fake_run):
        with pytest.raises(subprocess.TimeoutExpired):
            spawn_one_shot(backend, prompt="x", timeout=5)


def test_spawn_one_shot_forwards_cwd_and_extra_env():
    backend = _StubBackend()
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch("bridge.backends.one_shot.subprocess.run", side_effect=fake_run):
        spawn_one_shot(
            backend,
            prompt="x",
            timeout=30,
            cwd="/tmp/wt",
            extra_env={"BUMBA_MAILBOX_NAME": "m1"},
        )

    assert captured["cwd"] == "/tmp/wt"
    assert captured["env"]["BUMBA_MAILBOX_NAME"] == "m1"


def test_spawn_one_shot_supports_http_backend_without_subprocess():
    backend = _HttpBackend()
    assert isinstance(backend, BackendProtocol)

    result = spawn_one_shot(backend, prompt="classify this", timeout=30)

    assert result == OneShotResult(returncode=0, stdout="OK", stderr="")
    assert backend.requests == [{"message": "classify this", "system_prompt": None}]
