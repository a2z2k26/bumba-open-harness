"""VAL-12 — Zone 3 OpenRouter text-only specialist smoke."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest

from bridge.backends.openrouter import OpenRouterBackend
from bridge.claude_runner import ClaudeRunner
from bridge.config import BridgeConfig
from zone3.claude_p_executor import run_claude_p_specialist


def _openrouter_backend() -> OpenRouterBackend:
    config = SimpleNamespace(
        openrouter_api_key="sk-or-test",
        openrouter_default_model="z-ai/glm-4.6",
        fallback_openrouter_model="z-ai/glm-4.6",
    )
    return OpenRouterBackend(config)


def _openrouter_config() -> BridgeConfig:
    return replace(
        BridgeConfig(),
        backends_enabled=True,
        backends_main="openrouter",
        backends_chiefs_default="openrouter",
        backends_specialists_default="openrouter",
        backends_specialists_overrides={},
        openrouter_api_key="sk-or-test",
        openrouter_default_model="z-ai/glm-4.6",
    )


async def test_zone3_text_only_review_specialist_runs_on_openrouter_without_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _openrouter_backend()
    requests: list[dict[str, str | None]] = []

    def request(*, message: str, system_prompt: str | None = None) -> dict[str, object]:
        requests.append({"message": message, "system_prompt": system_prompt})
        return {
            "id": "gen-z3-openrouter-review",
            "choices": [
                {
                    "message": {
                        "content": "Zone 3 text-only review can run on OpenRouter."
                    }
                }
            ],
            "usage": {"cost": 0.0},
        }

    async def spawn_should_not_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("Zone 3 OpenRouter text-only smoke spawned subprocess")

    monkeypatch.setattr(backend, "request", request)

    result = await run_claude_p_specialist(
        claude_binary="claude",
        specialist="engineering-code-reviewer",
        prompt=(
            "Zone 3 planning/review-only task. Summarize bug risk in prose. "
            "Do not use tools, files, shell, MCP, or repository mutation."
        ),
        cwd="/tmp",
        timeout_seconds=30,
        spawn=spawn_should_not_run,
        backend=backend,
    )

    assert result.success is True
    assert result.specialist == "engineering-code-reviewer"
    assert result.stdout == "Zone 3 text-only review can run on OpenRouter."
    assert result.stderr == ""
    assert result.exit_code == 0
    assert requests == [
        {
            "message": (
                "Zone 3 planning/review-only task. Summarize bug risk in prose. "
                "Do not use tools, files, shell, MCP, or repository mutation."
            ),
            "system_prompt": None,
        }
    ]


async def test_zone3_tool_required_work_blocks_openrouter_before_request(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = ClaudeRunner(_openrouter_config())

    def request(*, message: str, system_prompt: str | None = None) -> dict[str, object]:
        raise AssertionError("tool-required Zone 3 work reached OpenRouter")

    def fail_subprocess_boundary(*args: object, **kwargs: object) -> None:
        raise AssertionError("tool-required Zone 3 work spawned subprocess")

    monkeypatch.setattr(runner._backend, "request", request)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_subprocess_boundary)

    with caplog.at_level(logging.ERROR):
        result = await runner.invoke(
            "Zone 3 code review requiring repository file search and MCP tools.",
            mcp_config_path="/tmp/z3-specialist.mcp.json",
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
