"""Tests for the guarded OpenRouter live-smoke harness."""

from __future__ import annotations

import json

from scripts import openrouter_live_smoke as smoke


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


def test_main_prints_summary_from_backend(monkeypatch, capsys) -> None:
    class _FakeBackend:
        def request(self, *, message: str, system_prompt: str | None = None):
            assert message == "ping"
            assert system_prompt is None
            return {
                "id": "gen-test",
                "model": "z-ai/glm-4.6",
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 4,
                    "total_tokens": 7,
                    "cost": 0.000001,
                },
                "choices": [{"message": {"content": "pong"}}],
            }

        def parse_event(self, line: str):
            from bridge.backends._protocol import StreamEvent

            return StreamEvent(type="result", text="pong", session_id="gen-test")

        def parse_cost(self, raw):
            from decimal import Decimal
            from bridge.cost_tracker import CostMeasurement

            return CostMeasurement(
                amount_usd=Decimal("0.000001"),
                source="measured",
                backend="openrouter",
                raw_usage_id="gen-test",
            )

    monkeypatch.setattr(smoke, "_build_backend", lambda **_kwargs: _FakeBackend())

    rc = smoke.main(
        ["--prompt", "ping", "--model", "z-ai/glm-4.6"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "sk-or-test"},
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"] == "openrouter"
    assert payload["model"] == "z-ai/glm-4.6"
    assert payload["response_id"] == "gen-test"
    assert payload["max_cost_usd"] == "0.02"
    assert payload["usage"]["total_tokens"] == 7
    assert payload["cost"]["source"] == "measured"
    assert payload["cost"]["amount_usd"] == "0.000001"
    assert payload["text_preview"] == "pong"


def test_main_refuses_invalid_cost_cap_before_backend(monkeypatch, capsys) -> None:
    def _unexpected_backend(**_kwargs):
        raise AssertionError("backend should not be constructed for invalid cap")

    monkeypatch.setattr(smoke, "_build_backend", _unexpected_backend)

    rc = smoke.main(
        ["--max-cost-usd", "0"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "sk-or-test"},
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "--max-cost-usd must be positive" in captured.err


def test_main_fails_when_measured_cost_exceeds_cap(monkeypatch, capsys) -> None:
    class _FakeBackend:
        def request(self, *, message: str, system_prompt: str | None = None):
            assert message == smoke.DEFAULT_PROMPT
            assert system_prompt is None
            return {
                "id": "gen-expensive",
                "model": "z-ai/glm-4.6",
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 4,
                    "total_tokens": 7,
                    "cost": 0.03,
                },
                "choices": [{"message": {"content": "pong"}}],
            }

        def parse_event(self, line: str):
            assert "gen-expensive" in line
            from bridge.backends._protocol import StreamEvent

            return StreamEvent(type="result", text="pong", session_id="gen-expensive")

        def parse_cost(self, raw):
            assert raw["id"] == "gen-expensive"
            from decimal import Decimal
            from bridge.cost_tracker import CostMeasurement

            return CostMeasurement(
                amount_usd=Decimal("0.03"),
                source="measured",
                backend="openrouter",
                raw_usage_id="gen-expensive",
            )

    monkeypatch.setattr(smoke, "_build_backend", lambda **_kwargs: _FakeBackend())

    rc = smoke.main(
        ["--max-cost-usd", "0.02"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "sk-or-test"},
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "known cost 0.03 exceeded cap 0.02" in captured.err
    assert captured.out == ""
