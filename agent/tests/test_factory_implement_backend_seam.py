"""P4.03 — implement._invoke_claude optional backend seam.

Phase 4 decoupling, mirroring P4.02 (triage) and P4.04 (zone3): the bypass
site grows an OPTIONAL ``backend`` param. None (default) preserves the
byte-identical legacy ``claude -p --output-format text
--dangerously-skip-permissions`` argv; a supplied backend routes through
spawn_one_shot, threading cwd + extra_env. Default path unchanged because the
implement workflow parses plain-text stdout, which stream-json would break.
"""
from __future__ import annotations

from unittest.mock import patch

from bridge.backends import BackendProtocol
from bridge.factory import implement


def test_default_path_preserves_hardcoded_argv():
    captured: dict = {}

    def fake_run(args, *, cwd=None, input_text=None, timeout=None, env=None):
        captured["args"] = args
        captured["cwd"] = cwd
        captured["input"] = input_text
        return (0, "OK", "")

    with patch("bridge.factory.implement._run_subprocess", side_effect=fake_run):
        with patch("bridge.factory.implement._load_oauth_token", return_value=None):
            rc, out, err = implement._invoke_claude("do it", cwd="/tmp/wt")

    assert rc == 0 and out == "OK"
    args = captured["args"]
    assert "-p" in args
    assert args[args.index("--output-format") + 1] == "text"
    assert "--dangerously-skip-permissions" in args
    assert captured["cwd"] == "/tmp/wt"
    assert captured["input"] == "do it"
    assert "do it" not in args


def test_backend_seam_routes_through_spawn_one_shot_with_cwd_and_env():
    seen: dict = {}

    class _StubBackend:
        @property
        def transport(self):
            return "subprocess"

        def resolve_binary(self):
            return "stub"

        def build_command(self, **kw):
            return ["stub"]

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

    def fake_spawn(backend, *, prompt, timeout, cwd=None, extra_env=None, **kw):
        from bridge.backends import OneShotResult

        seen["backend"] = backend
        seen["cwd"] = cwd
        seen["extra_env"] = extra_env
        return OneShotResult(returncode=0, stdout="BACKEND_OK", stderr="")

    stub = _StubBackend()
    assert isinstance(stub, BackendProtocol)
    with patch("bridge.factory.implement.spawn_one_shot", side_effect=fake_spawn):
        with patch("bridge.factory.implement._load_oauth_token", return_value="tok-1"):
            rc, out, err = implement._invoke_claude(
                "do it",
                cwd="/tmp/wt",
                extra_env={"BUMBA_MAILBOX_NAME": "m1"},
                backend=stub,
            )

    assert rc == 0 and out == "BACKEND_OK"
    assert seen["backend"] is stub
    assert seen["cwd"] == "/tmp/wt"
    # both caller extra_env AND oauth flow through
    assert seen["extra_env"]["BUMBA_MAILBOX_NAME"] == "m1"
    assert seen["extra_env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-1"
