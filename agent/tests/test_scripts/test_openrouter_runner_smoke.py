"""Tests for the guarded OpenRouter ClaudeRunner smoke harness."""

from __future__ import annotations

import json

from bridge.claude_runner import ClaudeResult
from scripts import openrouter_runner_smoke as smoke


def test_main_refuses_without_live_allow_env(capsys) -> None:
    rc = smoke.main([], environ={})

    captured = capsys.readouterr()
    assert rc == 2
    assert "BUMBA_ALLOW_LIVE=1" in captured.err


def test_main_refuses_without_openrouter_key(capsys) -> None:
    rc = smoke.main([], environ={"BUMBA_ALLOW_LIVE": "1"})

    captured = capsys.readouterr()
    assert rc == 2
    assert "OPENROUTER_API_KEY" in captured.err


def test_build_config_selects_openrouter_main_backend() -> None:
    cfg = smoke._build_config(api_key="test-key", model="z-ai/glm-4.6")

    assert cfg.backends_enabled is True
    assert cfg.backends_main == "openrouter"
    assert cfg.openrouter_api_key == "test-key"
    assert cfg.openrouter_default_model == "z-ai/glm-4.6"
    assert cfg.fallback_openrouter_model == "z-ai/glm-4.6"


def test_main_prints_summary_from_runner(monkeypatch, capsys) -> None:
    class _FakeRunner:
        async def invoke(self, message: str):
            assert message == "ping"
            return ClaudeResult(
                response_text="runner pong",
                session_id="gen-runner-1",
                cost_usd=0.000002,
                cost_unknown=False,
                cost_source="measured",
                cost_raw_usage_id="gen-runner-1",
                duration_ms=123,
                exit_code=0,
            )

    monkeypatch.setattr(smoke, "_build_runner", lambda _config: _FakeRunner())

    rc = smoke.main(
        ["--prompt", "ping", "--model", "z-ai/glm-4.6"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "test-key"},
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"] == "openrouter"
    assert payload["model"] == "z-ai/glm-4.6"
    assert payload["response_id"] == "gen-runner-1"
    assert payload["session_id"] == "gen-runner-1"
    assert payload["cost"]["amount_usd"] == "0.000002"
    assert payload["cost"]["source"] == "measured"
    assert payload["cost"]["unknown"] is False
    assert payload["duration_ms"] == 123
    assert payload["live_call_count"] == 1
    assert payload["text_length"] == 11
    assert payload["text_preview"] == "runner pong"


def test_main_reports_runner_error(monkeypatch, capsys) -> None:
    class _FakeRunner:
        async def invoke(self, message: str):
            return ClaudeResult(
                response_text="",
                is_error=True,
                error_type="http_backend_error",
                stderr_output="backend failed",
                exit_code=1,
            )

    monkeypatch.setattr(smoke, "_build_runner", lambda _config: _FakeRunner())

    rc = smoke.main(
        ["--prompt", "ping", "--model", "z-ai/glm-4.6"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "test-key"},
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "http_backend_error" in captured.err
    assert "backend failed" in captured.err
