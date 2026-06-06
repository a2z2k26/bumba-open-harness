"""VAL-10 — OpenRouter text-only multi-agent capability gate.

OpenRouter is intentionally text-only in this runtime. These tests lock the
runner boundary that multi-agent executors reach: prompt-only work may use
OpenRouter, but explicit tool surfaces must fail before a live HTTP request or
subprocess spawn can occur.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from bridge.claude_runner import ClaudeRunner
from bridge.config import BridgeConfig


def _openrouter_config(config: BridgeConfig) -> BridgeConfig:
    return replace(
        config,
        backends_enabled=True,
        backends_main="openrouter",
        backends_chiefs_default="openrouter",
        backends_specialists_default="openrouter",
        backends_specialists_overrides={},
        openrouter_api_key="sk-or-test",
        openrouter_default_model="z-ai/glm-4.6",
    )


def _completion(text: str = "BUMBA_OPENROUTER_TEXT_ONLY_OK") -> dict[str, object]:
    return {
        "id": "gen-val-10",
        "choices": [{"message": {"content": text}}],
        "usage": {"cost": 0.0},
    }


async def test_openrouter_text_only_flow_is_allowed(
    sample_config: BridgeConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ClaudeRunner(_openrouter_config(sample_config))
    requests: list[dict[str, str | None]] = []
    prompt = tmp_path / "chief-system-prompt.md"
    prompt.write_text("Stay text-only.")

    def request(*, message: str, system_prompt: str | None = None) -> dict[str, object]:
        requests.append({"message": message, "system_prompt": system_prompt})
        return _completion()

    def fail_subprocess_boundary(*args: object, **kwargs: object) -> None:
        raise AssertionError("OpenRouter text-only flow touched subprocess boundary")

    monkeypatch.setattr(runner._backend, "request", request)
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        fail_subprocess_boundary,
    )

    result = await runner.invoke(
        "Coordinate a chief and specialist response without tools.",
        system_prompt_file=str(prompt),
    )

    assert result.is_error is False
    assert result.response_text == "BUMBA_OPENROUTER_TEXT_ONLY_OK"
    assert requests == [
        {
            "message": "Coordinate a chief and specialist response without tools.",
            "system_prompt": "Stay text-only.",
        }
    ]


async def test_openrouter_mcp_config_flow_is_blocked_before_live_request(
    sample_config: BridgeConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = ClaudeRunner(_openrouter_config(sample_config))

    def request(*, message: str, system_prompt: str | None = None) -> dict[str, object]:
        raise AssertionError("tool-required OpenRouter flow made a live request")

    def fail_subprocess_boundary(*args: object, **kwargs: object) -> None:
        raise AssertionError("tool-required OpenRouter flow spawned a subprocess")

    monkeypatch.setattr(runner._backend, "request", request)
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        fail_subprocess_boundary,
    )

    with caplog.at_level(logging.ERROR):
        result = await runner.invoke(
            "Use the isolated MCP tools for this specialist task.",
            mcp_config_path="/tmp/specialist.mcp.json",
        )

    assert result.is_error is True
    assert result.error_type == "capability_misroute"
    assert result.exit_code == 1
    assert "openrouter" in result.stderr_output
    assert "mcp_config" in result.stderr_output
    assert "tool_calling" in result.stderr_output
    assert any(
        "CAPABILITY MISROUTE BLOCKED" in record.getMessage()
        and "openrouter" in record.getMessage()
        and "mcp_config" in record.getMessage()
        for record in caplog.records
    )


async def test_openrouter_tool_preauth_flow_is_blocked_before_live_request(
    sample_config: BridgeConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ClaudeRunner(_openrouter_config(sample_config))

    def request(*, message: str, system_prompt: str | None = None) -> dict[str, object]:
        raise AssertionError("tool-preauth OpenRouter flow made a live request")

    monkeypatch.setattr(runner._backend, "request", request)

    result = await runner.invoke(
        "Run a shell-backed specialist with preauthorized tools.",
        allowed_tools=["mcp__bumba-sandbox__command_exec"],
    )

    assert result.is_error is True
    assert result.error_type == "capability_misroute"
    assert "openrouter" in result.stderr_output
    assert "tool_preauth" in result.stderr_output
    assert "tool_calling" in result.stderr_output


async def test_openrouter_combined_tool_flow_reports_all_missing_capabilities(
    sample_config: BridgeConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ClaudeRunner(_openrouter_config(sample_config))

    def request(*, message: str, system_prompt: str | None = None) -> dict[str, object]:
        raise AssertionError("combined tool OpenRouter flow made a live request")

    monkeypatch.setattr(runner._backend, "request", request)

    result = await runner.invoke(
        "Use files, shell, MCP tools, and preauthorized sandbox tools.",
        mcp_config_path="/tmp/specialist.mcp.json",
        allowed_tools=["mcp__bumba-sandbox__files_read"],
    )

    assert result.is_error is True
    assert result.error_type == "capability_misroute"
    assert "openrouter" in result.stderr_output
    assert "mcp_config" in result.stderr_output
    assert "tool_calling" in result.stderr_output
    assert "tool_preauth" in result.stderr_output
