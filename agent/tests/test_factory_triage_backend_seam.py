"""P4.02 — triage._invoke_claude optional backend seam.

Phase 4 decoupling: _invoke_claude grows an OPTIONAL ``backend`` parameter.
When None (default), it preserves the byte-identical hardcoded one-shot
``claude -p --output-format text --max-turns 0 --setting-sources user`` argv
(the factory parses plain-text stdout as JSON, which stream-json would break,
so the default path must NOT change). When a backend is supplied, it routes
through spawn_one_shot so a future BackendRegistry wire-in can swap the CLI.

These tests lock in BOTH halves of the seam and preserve the existing
_run_subprocess patch surface other triage tests rely on.
"""
from __future__ import annotations

from unittest.mock import patch

from bridge.backends import BackendProtocol
from bridge.factory import triage


def test_default_path_preserves_hardcoded_oneshot_argv():
    """With no backend, _invoke_claude must emit the exact legacy argv via
    _run_subprocess — output-format text, max-turns 0 — so the text-parsing
    classifier is unaffected."""
    captured: dict = {}

    def fake_run(args, *, input_text=None, timeout=None):
        captured["args"] = args
        captured["input"] = input_text
        return (0, "OK", "")

    with patch("bridge.factory.triage._run_subprocess", side_effect=fake_run):
        with patch("bridge.factory.triage._load_oauth_token", return_value=None):
            rc, out, err = triage._invoke_claude("classify this")

    assert rc == 0 and out == "OK"
    args = captured["args"]
    assert "-p" in args
    assert args[args.index("--output-format") + 1] == "text"
    assert args[args.index("--max-turns") + 1] == "0"
    assert "--setting-sources" in args
    # prompt on stdin, never argv
    assert captured["input"] == "classify this"
    assert "classify this" not in args


def test_backend_seam_routes_through_spawn_one_shot():
    """With a backend supplied, _invoke_claude must route through
    spawn_one_shot and return its (rc, stdout, stderr)."""
    calls: dict = {}

    class _StubBackend:
        @property
        def transport(self):
            return "subprocess"

        def resolve_binary(self):
            return "stub"

        def build_command(self, **kw):
            return ["stub", "-p"]

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

    def fake_spawn(backend, *, prompt, timeout, **kw):
        calls["backend"] = backend
        calls["prompt"] = prompt
        return triage_spawn_result(0, "BACKEND_OK", "")

    # OneShotResult-shaped stand-in
    from bridge.backends import OneShotResult

    def triage_spawn_result(rc, out, err):
        return OneShotResult(returncode=rc, stdout=out, stderr=err)

    stub = _StubBackend()
    assert isinstance(stub, BackendProtocol)
    with patch("bridge.factory.triage.spawn_one_shot", side_effect=fake_spawn):
        with patch("bridge.factory.triage._load_oauth_token", return_value=None):
            rc, out, err = triage._invoke_claude("hi", backend=stub)

    assert rc == 0 and out == "BACKEND_OK"
    assert calls["backend"] is stub
    assert calls["prompt"] == "hi"


def test_backend_seam_layers_oauth_into_extra_env():
    """When routing through a backend, the OAuth token still flows — via
    spawn_one_shot's extra_env — so auth parity with the legacy path holds."""
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

    def fake_spawn(backend, *, prompt, timeout, extra_env=None, **kw):
        seen["extra_env"] = extra_env
        from bridge.backends import OneShotResult

        return OneShotResult(returncode=0, stdout="", stderr="")

    with patch("bridge.factory.triage.spawn_one_shot", side_effect=fake_spawn):
        with patch("bridge.factory.triage._load_oauth_token", return_value="tok-xyz"):
            stub = _StubBackend()
            assert isinstance(stub, BackendProtocol)
            triage._invoke_claude("hi", backend=stub)

    assert seen["extra_env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-xyz"
