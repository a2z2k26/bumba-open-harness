"""Offline bridge-message smoke for the OpenRouter main path."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.backends._protocol import StreamEvent
from bridge.backends.openrouter import OpenRouterBackend
from bridge.claude_runner import ClaudeResult
from bridge.cost_tracker import CostMeasurement


class _FakeOpenRouterHTTPBackend:
    """HTTP backend fixture that fails if the bridge touches subprocess APIs."""

    transport = "http"

    def __init__(
        self,
        *,
        text: str = "BUMBA_OPENROUTER_BRIDGE_MESSAGE_OK",
        cost_measurement: CostMeasurement | None = None,
    ) -> None:
        self.text = text
        self.requests: list[dict[str, str | None]] = []
        self.parsed_lines: list[str] = []
        self.cost_measurement = cost_measurement or CostMeasurement(
            amount_usd=Decimal("0.00042"),
            source="measured",
            backend="openrouter",
            raw_usage_id="gen-val-08",
        )

    def resolve_binary(self) -> list[str]:
        raise AssertionError("OpenRouter bridge smoke fell back to subprocess")

    def build_command(self, **_kwargs: object) -> list[str]:
        raise AssertionError("OpenRouter bridge smoke built a subprocess command")

    def auth_env(self) -> dict[str, str]:
        return {}

    def shutdown(self) -> None:
        return None

    def supports_tool_calling(self) -> bool:
        return False

    def supports_system_prompt(self) -> bool:
        return True

    def supports_mcp_config(self) -> bool:
        return False

    def supports_tool_preauth(self) -> bool:
        return False

    def request(self, *, message: str, system_prompt: str | None = None) -> dict[str, Any]:
        self.requests.append({"message": message, "system_prompt": system_prompt})
        return {
            "id": "gen-val-08",
            "model": "z-ai/glm-4.6",
            "choices": [{"message": {"content": self.text}}],
        }

    def parse_event(self, line: str) -> StreamEvent:
        self.parsed_lines.append(line)
        payload = json.loads(line)
        return StreamEvent(
            type="result",
            text=self.text,
            session_id=payload.get("id") or "gen-val-08",
        )

    def parse_cost(self, _event: object) -> CostMeasurement:
        return self.cost_measurement


@pytest.fixture
def openrouter_bridge_toml(sample_config_toml: Path, tmp_path: Path) -> Path:
    config_path = tmp_path / "openrouter-bridge-message.toml"
    config_path.write_text(
        sample_config_toml.read_text()
        + """

[backends]
enabled = true
main = "openrouter"
chiefs_default = "openrouter"
specialists_default = "openrouter"
specialists_overrides = {}

[openrouter]
default_model = "z-ai/glm-4.6"

[evaluator]
enabled = false
"""
    )
    return config_path


@pytest_asyncio.fixture
async def openrouter_bridge_app(openrouter_bridge_toml: Path, monkeypatch) -> BridgeApp:
    secrets = {
        "discord_bot_token": "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.FAKE.abcdef",
        "operator_discord_id": "7565124764",
        "api_token": "test-api-token",
        "github_webhook_secret": "test-gh-webhook-secret",
        "openrouter_api_key": "sk-or-test",
    }
    monkeypatch.setattr("bridge.config._load_secrets", lambda *_, **__: secrets)

    app = BridgeApp(config_path=str(openrouter_bridge_toml))
    await app._initialize()

    app._discord._start_typing = MagicMock()
    app._discord._stop_typing = MagicMock()
    app._discord.send_message = AsyncMock()
    app._discord.send_alert = AsyncMock()
    app._security.log_event = AsyncMock()

    try:
        yield app
    finally:
        if app._db:
            await app._db.close()


def _capture_runner_results(app: BridgeApp) -> list[ClaudeResult]:
    results: list[ClaudeResult] = []
    original_invoke = app._claude.invoke

    async def _invoke_spy(*args: object, **kwargs: object) -> ClaudeResult:
        result = await original_invoke(*args, **kwargs)
        results.append(result)
        return result

    app._claude.invoke = _invoke_spy
    return results


@pytest.mark.asyncio
async def test_openrouter_bridge_message_path_processes_one_message(
    openrouter_bridge_app: BridgeApp,
    monkeypatch,
) -> None:
    app = openrouter_bridge_app
    assert isinstance(app._claude._backend, OpenRouterBackend)
    assert app._warm_claude is None

    backend = _FakeOpenRouterHTTPBackend()
    app._claude._backend = backend
    results = _capture_runner_results(app)

    def _fail_subprocess_boundary(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("OpenRouter bridge smoke touched subprocess boundary")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fail_subprocess_boundary)

    await app._handle_new_message("chat-val-08", "Reply with the VAL-08 marker.", 808)
    msg = await app._queue.dequeue()
    assert msg is not None

    await app._process_single_message(msg)

    assert backend.requests
    assert backend.requests[0]["message"] == "Reply with the VAL-08 marker."
    assert backend.requests[0]["system_prompt"] is not None
    assert "OPERATOR PRIORITY" in backend.requests[0]["system_prompt"]
    assert backend.parsed_lines

    assert results
    assert results[0].response_text == "BUMBA_OPENROUTER_BRIDGE_MESSAGE_OK"
    assert results[0].session_id == "gen-val-08"
    assert results[0].cost_usd == pytest.approx(0.00042)
    assert results[0].cost_unknown is False

    app._discord.send_message.assert_awaited()
    sent_payloads = [call.args[1] for call in app._discord.send_message.await_args_list]
    assert "BUMBA_OPENROUTER_BRIDGE_MESSAGE_OK" in sent_payloads

    status = await app._queue.get_queue_status()
    assert status["counts"].get("completed", 0) == 1

    rows = await app._db.fetchall(
        "SELECT role, content, cost_usd FROM conversations ORDER BY id"
    )
    assert rows[-2][0] == "user"
    assert rows[-2][1] == "Reply with the VAL-08 marker."
    assert rows[-1][0] == "assistant"
    assert rows[-1][1] == "BUMBA_OPENROUTER_BRIDGE_MESSAGE_OK"
    assert rows[-1][2] == pytest.approx(0.00042)


@pytest.mark.asyncio
async def test_openrouter_bridge_message_preserves_unknown_cost_flag(
    openrouter_bridge_app: BridgeApp,
    monkeypatch,
) -> None:
    app = openrouter_bridge_app
    app._claude._backend = _FakeOpenRouterHTTPBackend(
        text="BUMBA_OPENROUTER_BRIDGE_UNKNOWN_COST_OK",
        cost_measurement=CostMeasurement(
            amount_usd=None,
            source="unknown",
            backend="openrouter",
            raw_usage_id="gen-val-08-unknown",
        ),
    )
    results = _capture_runner_results(app)

    def _fail_subprocess_boundary(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("OpenRouter bridge smoke touched subprocess boundary")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fail_subprocess_boundary)

    await app._queue.enqueue(809, "chat-val-08", "Return the unknown-cost marker.")
    msg = await app._queue.dequeue()
    assert msg is not None

    await app._process_single_message(msg)

    assert results
    assert results[0].response_text == "BUMBA_OPENROUTER_BRIDGE_UNKNOWN_COST_OK"
    assert results[0].cost_usd == 0.0
    assert results[0].cost_unknown is True
