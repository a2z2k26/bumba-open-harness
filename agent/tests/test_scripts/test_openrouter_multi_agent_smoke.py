"""Tests for the guarded OpenRouter multi-agent live smoke harness."""

from __future__ import annotations

import json

from bridge.claude_runner import ClaudeResult
from scripts import openrouter_multi_agent_smoke as smoke


class _FakeRunner:
    def __init__(self, results: list[ClaudeResult]) -> None:
        self._results = list(results)
        self.messages: list[str] = []

    async def invoke(self, message: str) -> ClaudeResult:
        self.messages.append(message)
        if not self._results:
            raise AssertionError("fake runner received an unexpected fourth call")
        return self._results.pop(0)


def _result(
    *,
    text: str,
    session_id: str,
    cost_usd: float,
    cost_unknown: bool = False,
    cost_source: str = "measured",
) -> ClaudeResult:
    return ClaudeResult(
        response_text=text,
        session_id=session_id,
        cost_usd=cost_usd,
        cost_unknown=cost_unknown,
        cost_source=cost_source,
        cost_raw_usage_id=session_id,
        duration_ms=123,
        exit_code=0,
    )


def test_main_refuses_without_live_allow_env(capsys) -> None:
    rc = smoke.main([], environ={"OPENROUTER_API_KEY": "sk-or-secret-test"})

    captured = capsys.readouterr()
    assert rc == 2
    assert "BUMBA_ALLOW_LIVE=1" in captured.err
    assert "sk-or-secret-test" not in captured.err


def test_main_refuses_without_openrouter_key(capsys) -> None:
    rc = smoke.main([], environ={"BUMBA_ALLOW_LIVE": "1"})

    captured = capsys.readouterr()
    assert rc == 2
    assert "OPENROUTER_API_KEY" in captured.err


def test_build_config_selects_openrouter_for_all_roles() -> None:
    cfg = smoke._build_config(api_key="test-key", model="z-ai/glm-4.6")

    assert cfg.backends_enabled is True
    assert cfg.backends_main == "openrouter"
    assert cfg.backends_chiefs_default == "openrouter"
    assert cfg.backends_specialists_default == "openrouter"
    assert cfg.backends_specialists_overrides == {}
    assert cfg.openrouter_api_key == "test-key"


def test_main_rejects_max_calls_below_required_flow(capsys) -> None:
    rc = smoke.main(
        ["--max-calls", "2"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "test-key"},
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "at least 3" in captured.err


def test_main_prints_three_call_text_only_summary(monkeypatch, capsys) -> None:
    fake = _FakeRunner(
        [
            _result(text="chief brief", session_id="gen-chief", cost_usd=0.001),
            _result(text="specialist finding", session_id="gen-specialist", cost_usd=0.002),
            _result(text="final synthesis", session_id="gen-synthesis", cost_usd=0.003),
        ]
    )
    monkeypatch.setattr(smoke, "_build_runner", lambda _config: fake)

    rc = smoke.main(
        ["--max-calls", "3", "--max-cost-usd", "0.05", "--task", "ping"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "test-key"},
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"] == "openrouter"
    assert payload["model"] == "z-ai/glm-4.6"
    assert payload["live_call_count"] == 3
    assert payload["max_calls"] == 3
    assert payload["total_cost_usd"] == "0.006"
    assert payload["cost_unknown"] is False
    assert payload["response_ids"] == ["gen-chief", "gen-specialist", "gen-synthesis"]
    assert payload["cost_sources"] == ["measured", "measured", "measured"]
    assert payload["final_answer"] == "final synthesis"
    assert payload["tool_invocation_count"] == 0
    assert payload["subprocess_spawned"] is False
    assert payload["mcp_config_path"] is None
    assert payload["allowed_tools"] == []
    assert [step["role"] for step in payload["steps"]] == [
        "chief",
        "specialist",
        "synthesis",
    ]
    assert [step["cost_source"] for step in payload["steps"]] == [
        "measured",
        "measured",
        "measured",
    ]
    assert len(fake.messages) == 3
    assert all("Do not use tools" in message for message in fake.messages)


def test_main_fails_when_known_total_cost_exceeds_cap(monkeypatch, capsys) -> None:
    fake = _FakeRunner(
        [
            _result(text="chief brief", session_id="gen-chief", cost_usd=0.02),
            _result(text="specialist finding", session_id="gen-specialist", cost_usd=0.04),
            _result(text="final synthesis", session_id="gen-synthesis", cost_usd=0.001),
        ]
    )
    monkeypatch.setattr(smoke, "_build_runner", lambda _config: fake)

    rc = smoke.main(
        ["--max-calls", "3", "--max-cost-usd", "0.05"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "test-key"},
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "exceeded cap" in captured.err
    assert len(fake.messages) == 2


def test_main_fails_on_unknown_cost(monkeypatch, capsys) -> None:
    fake = _FakeRunner(
        [
            _result(
                text="chief brief",
                session_id="gen-chief",
                cost_usd=0.0,
                cost_unknown=True,
            ),
            _result(text="specialist finding", session_id="gen-specialist", cost_usd=0.002),
            _result(text="final synthesis", session_id="gen-synthesis", cost_usd=0.003),
        ]
    )
    monkeypatch.setattr(smoke, "_build_runner", lambda _config: fake)

    rc = smoke.main(
        ["--max-calls", "3", "--max-cost-usd", "0.05"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "test-key"},
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "unknown cost" in captured.err
    assert len(fake.messages) == 1
