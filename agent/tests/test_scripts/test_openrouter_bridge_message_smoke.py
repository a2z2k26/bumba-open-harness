"""Tests for the guarded OpenRouter bridge-message live smoke harness."""

from __future__ import annotations

import json
from typing import Any

import pytest

from bridge.backends.openrouter import OpenRouterBackend
from scripts import openrouter_bridge_message_smoke as smoke


class _DisconnectedDb:
    def __init__(self) -> None:
        self._conn = None
        self.connected = False
        self.migrated = False

    async def connect(self) -> None:
        self.connected = True
        self._conn = object()

    async def migrate(self) -> None:
        assert self.connected
        self.migrated = True


class _ConnectedDb:
    def __init__(self) -> None:
        self._conn = object()

    async def connect(self) -> None:
        raise AssertionError("already-connected DB should not reconnect")

    async def migrate(self) -> None:
        raise AssertionError("already-connected DB should not re-migrate")


class _AppWithDb:
    def __init__(self, db: object | None) -> None:
        self._db = db


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


def test_bridge_toml_text_keeps_openrouter_key_out_of_config(tmp_path) -> None:
    text = smoke._bridge_toml_text(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        working_dir=tmp_path / "agent",
        model="z-ai/glm-4.6",
    )

    assert "openrouter_api_key" not in text
    assert "z-ai/glm-4.6" in text
    assert 'main = "openrouter"' in text
    assert "[evaluator]" in text
    assert "enabled = false" in text


@pytest.mark.asyncio
async def test_run_live_bridge_message_uses_temp_queue_and_mocked_openrouter(
    monkeypatch,
) -> None:
    requests: list[dict[str, str | None]] = []

    def _fake_request(
        self: OpenRouterBackend,
        *,
        message: str,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        requests.append({"message": message, "system_prompt": system_prompt})
        return {
            "id": "gen-script-val09",
            "model": self._model,
            "choices": [
                {
                    "message": {
                        "content": "BUMBA_OPENROUTER_BRIDGE_MESSAGE_OK",
                    }
                }
            ],
            "usage": {"cost": 0.00031},
        }

    monkeypatch.setattr(OpenRouterBackend, "request", _fake_request)

    summary = await smoke._run_live_bridge_message(
        api_key="sk-or-test-not-real",
        model="z-ai/glm-4.6",
        prompt="Reply with the bridge marker.",
    )

    assert len(requests) == 1
    assert requests[0]["message"] == "Reply with the bridge marker."
    assert requests[0]["system_prompt"] is not None
    assert summary["backend"] == "openrouter"
    assert summary["response_id"] == "gen-script-val09"
    assert summary["cost"] == {
        "amount_usd": "0.00031",
        "source": "measured",
        "unknown": False,
    }
    assert summary["live_call_count"] == 1
    assert summary["queue_completed"] == 1
    assert summary["mocked_discord_messages"] == 1
    assert summary["daemon_started"] is False
    assert summary["discord_network_connected"] is False


@pytest.mark.asyncio
async def test_bridge_smoke_ensures_temp_database_is_connected() -> None:
    disconnected = _DisconnectedDb()

    await smoke._ensure_smoke_database_connected(_AppWithDb(disconnected))

    assert disconnected.connected is True
    assert disconnected.migrated is True

    await smoke._ensure_smoke_database_connected(_AppWithDb(_ConnectedDb()))


@pytest.mark.asyncio
async def test_bridge_smoke_fails_if_initialize_does_not_create_database() -> None:
    with pytest.raises(RuntimeError, match="database was not initialized"):
        await smoke._ensure_smoke_database_connected(_AppWithDb(None))


def test_main_prints_summary_from_bridge_message_smoke(monkeypatch, capsys) -> None:
    async def _fake_run_live_bridge_message(**kwargs):
        assert kwargs["api_key"] == "test-key"
        assert kwargs["model"] == "z-ai/glm-4.6"
        assert kwargs["prompt"] == "ping"
        return {
            "backend": "openrouter",
            "model": "z-ai/glm-4.6",
            "response_id": "gen-bridge-1",
            "session_id": "gen-bridge-1",
            "cost": {"amount_usd": "0.0007", "source": "measured", "unknown": False},
            "duration_ms": 321,
            "text_length": 11,
            "text_preview": "bridge pong",
            "live_call_count": 1,
            "queue_completed": 1,
            "mocked_discord_messages": 1,
            "warm_claude_enabled": False,
            "daemon_started": False,
            "launchd_touched": False,
            "discord_network_connected": False,
            "api_started": False,
        }

    monkeypatch.setattr(
        smoke, "_run_live_bridge_message", _fake_run_live_bridge_message
    )

    rc = smoke.main(
        ["--prompt", "ping", "--model", "z-ai/glm-4.6"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "test-key"},
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"] == "openrouter"
    assert payload["response_id"] == "gen-bridge-1"
    assert payload["session_id"] == "gen-bridge-1"
    assert payload["cost"]["amount_usd"] == "0.0007"
    assert payload["cost"]["source"] == "measured"
    assert payload["cost"]["unknown"] is False
    assert payload["live_call_count"] == 1
    assert payload["warm_claude_enabled"] is False
    assert payload["daemon_started"] is False
    assert payload["discord_network_connected"] is False


def test_main_fails_when_known_cost_exceeds_cap(monkeypatch, capsys) -> None:
    async def _fake_run_live_bridge_message(**_kwargs):
        return {
            "backend": "openrouter",
            "model": "z-ai/glm-4.6",
            "response_id": "gen-bridge-expensive",
            "session_id": "gen-bridge-expensive",
            "cost": {"amount_usd": "0.03", "source": "measured", "unknown": False},
            "duration_ms": 321,
            "text_length": 11,
            "text_preview": "bridge pong",
            "live_call_count": 1,
            "queue_completed": 1,
            "mocked_discord_messages": 1,
            "warm_claude_enabled": False,
            "daemon_started": False,
            "launchd_touched": False,
            "discord_network_connected": False,
            "api_started": False,
        }

    monkeypatch.setattr(
        smoke, "_run_live_bridge_message", _fake_run_live_bridge_message
    )

    rc = smoke.main(
        ["--max-cost-usd", "0.02"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "test-key"},
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "exceeded cap" in captured.err


def test_main_allows_unknown_cost_for_honest_reporting(monkeypatch, capsys) -> None:
    async def _fake_run_live_bridge_message(**_kwargs):
        return {
            "backend": "openrouter",
            "model": "z-ai/glm-4.6",
            "response_id": "gen-bridge-unknown",
            "session_id": "gen-bridge-unknown",
            "cost": {"amount_usd": "0", "source": "unknown", "unknown": True},
            "duration_ms": 321,
            "text_length": 11,
            "text_preview": "bridge pong",
            "live_call_count": 1,
            "queue_completed": 1,
            "mocked_discord_messages": 1,
            "warm_claude_enabled": False,
            "daemon_started": False,
            "launchd_touched": False,
            "discord_network_connected": False,
            "api_started": False,
        }

    monkeypatch.setattr(
        smoke, "_run_live_bridge_message", _fake_run_live_bridge_message
    )

    rc = smoke.main(
        ["--max-cost-usd", "0.02"],
        environ={"BUMBA_ALLOW_LIVE": "1", "OPENROUTER_API_KEY": "test-key"},
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cost"]["unknown"] is True
