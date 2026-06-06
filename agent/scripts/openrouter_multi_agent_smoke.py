"""Guarded three-call OpenRouter multi-agent text-only live smoke.

This validates a tiny chief -> specialist -> synthesis orchestration shape
without enabling tools. It does not start the daemon, touch launchd, connect
Discord, bind the API server, create worktrees, pass MCP config, preauthorize
tools, or permit subprocess execution.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Mapping, Protocol, Sequence

from bridge.claude_runner import ClaudeResult, ClaudeRunner
from bridge.config import BridgeConfig

DEFAULT_SMOKE_MODEL = "z-ai/glm-4.6"
DEFAULT_MAX_CALLS = 3
DEFAULT_MAX_COST_USD = Decimal("0.05")
DEFAULT_TASK = (
    "Decide whether the model-agnostic runtime can run a text-only "
    "chief/specialist validation smoke."
)


@dataclass(frozen=True)
class _SmokeStep:
    role: str
    prompt_template: str

    def render(self, *, task: str, chief_text: str, specialist_text: str) -> str:
        return self.prompt_template.format(
            task=task,
            chief_text=chief_text,
            specialist_text=specialist_text,
        )


@dataclass(frozen=True)
class _StepEvidence:
    role: str
    response_id: str | None
    cost_usd: Decimal
    cost_source: str
    duration_ms: int
    text: str


class _RunnerProtocol(Protocol):
    async def invoke(self, message: str) -> ClaudeResult:
        ...


SMOKE_STEPS = (
    _SmokeStep(
        role="chief",
        prompt_template=(
            "You are the chief agent in a live validation smoke. "
            "Do not use tools, shell, files, MCP, browser, Discord, or external "
            "systems. Reply in one short sentence with the coordination plan "
            "for this task: {task}"
        ),
    ),
    _SmokeStep(
        role="specialist",
        prompt_template=(
            "You are the specialist agent in a live validation smoke. "
            "Do not use tools, shell, files, MCP, browser, Discord, or external "
            "systems. Given the chief plan below, reply in one short sentence "
            "with a text-only finding.\n\nChief plan: {chief_text}"
        ),
    ),
    _SmokeStep(
        role="synthesis",
        prompt_template=(
            "You are the synthesizer in a live validation smoke. "
            "Do not use tools, shell, files, MCP, browser, Discord, or external "
            "systems. Combine the chief plan and specialist finding into one "
            "final sentence.\n\nChief plan: {chief_text}\n\n"
            "Specialist finding: {specialist_text}"
        ),
    ),
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL", DEFAULT_SMOKE_MODEL),
        help="OpenRouter model id for the multi-agent text-only smoke.",
    )
    parser.add_argument(
        "--task",
        default=DEFAULT_TASK,
        help="Tiny text-only task used by the chief/specialist flow.",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=DEFAULT_MAX_CALLS,
        help="Abort before attempting more than this many model calls.",
    )
    parser.add_argument(
        "--max-cost-usd",
        default=str(DEFAULT_MAX_COST_USD),
        help="Fail if known cumulative cost exceeds this cap.",
    )
    return parser.parse_args(argv)


def _fail(message: str, *, rc: int = 2) -> int:
    print(message, file=sys.stderr)
    return rc


def _build_config(*, api_key: str, model: str) -> BridgeConfig:
    return replace(
        BridgeConfig(),
        backends_enabled=True,
        backends_main="openrouter",
        backends_chiefs_default="openrouter",
        backends_specialists_default="openrouter",
        backends_specialists_overrides={},
        openrouter_api_key=api_key,
        openrouter_default_model=model,
        fallback_openrouter_model=model,
    )


def _build_runner(config: BridgeConfig) -> ClaudeRunner:
    return ClaudeRunner(config)


def _parse_cost_cap(raw: str) -> Decimal:
    try:
        cap = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid --max-cost-usd value: {raw!r}") from exc
    if cap <= 0:
        raise ValueError("--max-cost-usd must be positive")
    return cap


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _step_summary(step: _StepEvidence) -> dict[str, object]:
    return {
        "role": step.role,
        "response_id": step.response_id,
        "cost_usd": _decimal_text(step.cost_usd),
        "cost_source": step.cost_source,
        "duration_ms": step.duration_ms,
        "text_length": len(step.text),
        "text_preview": step.text[:240],
    }


async def _run_text_only_flow(
    *,
    runner: _RunnerProtocol,
    task: str,
    max_calls: int,
    max_cost_usd: Decimal,
) -> dict[str, object]:
    original_subprocess_exec = asyncio.create_subprocess_exec

    def _fail_subprocess_boundary(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("OpenRouter multi-agent smoke touched subprocess boundary")

    call_count = 0
    total_cost = Decimal("0")
    evidence: list[_StepEvidence] = []
    chief_text = ""
    specialist_text = ""

    asyncio.create_subprocess_exec = _fail_subprocess_boundary
    try:
        for step in SMOKE_STEPS:
            if call_count >= max_calls:
                raise RuntimeError(
                    f"OpenRouter multi-agent smoke attempted call {call_count + 1}, "
                    f"exceeding max-calls {max_calls}"
                )

            prompt = step.render(
                task=task,
                chief_text=chief_text,
                specialist_text=specialist_text,
            )
            call_count += 1
            result = await runner.invoke(prompt)
            if result.is_error or not result.response_text:
                detail = result.stderr_output or "empty response"
                raise RuntimeError(
                    f"{step.role} call failed: {result.error_type or 'error'}: {detail}"
                )
            if result.cost_unknown:
                raise RuntimeError(
                    f"{step.role} call returned unknown cost; cannot verify cap "
                    f"{max_cost_usd}"
                )

            step_cost = Decimal(str(result.cost_usd))
            total_cost += step_cost
            if total_cost > max_cost_usd:
                raise RuntimeError(
                    f"known cumulative cost {_decimal_text(total_cost)} exceeded cap "
                    f"{_decimal_text(max_cost_usd)} after {step.role}"
                )

            if step.role == "chief":
                chief_text = result.response_text
            elif step.role == "specialist":
                specialist_text = result.response_text

            evidence.append(
                _StepEvidence(
                    role=step.role,
                    response_id=result.cost_raw_usage_id or result.session_id or None,
                    cost_usd=step_cost,
                    cost_source=result.cost_source or "measured_or_estimated",
                    duration_ms=result.duration_ms,
                    text=result.response_text,
                )
            )
    finally:
        asyncio.create_subprocess_exec = original_subprocess_exec

    final_answer = evidence[-1].text if evidence else ""
    return {
        "backend": "openrouter",
        "model": DEFAULT_SMOKE_MODEL,
        "live_call_count": call_count,
        "max_calls": max_calls,
        "max_cost_usd": _decimal_text(max_cost_usd),
        "total_cost_usd": _decimal_text(total_cost),
        "cost_unknown": False,
        "response_ids": [step.response_id for step in evidence],
        "cost_sources": [step.cost_source for step in evidence],
        "steps": [_step_summary(step) for step in evidence],
        "final_answer": final_answer,
        "tool_invocation_count": 0,
        "mcp_config_path": None,
        "allowed_tools": [],
        "subprocess_spawned": False,
        "daemon_started": False,
        "launchd_touched": False,
        "discord_network_connected": False,
        "api_started": False,
        "filesystem_tools_enabled": False,
        "shell_tools_enabled": False,
    }


async def _run(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    if env.get("BUMBA_ALLOW_LIVE") != "1":
        return _fail(
            "Refusing live OpenRouter multi-agent smoke: set BUMBA_ALLOW_LIVE=1 "
            "only for an operator-approved live validation."
        )

    api_key = str(env.get("OPENROUTER_API_KEY", "") or "")
    if not api_key:
        return _fail(
            "Refusing live OpenRouter multi-agent smoke: OPENROUTER_API_KEY is "
            "required."
        )

    args = _parse_args(argv)
    try:
        max_cost = _parse_cost_cap(args.max_cost_usd)
        if args.max_calls < len(SMOKE_STEPS):
            return _fail(
                f"--max-calls must be at least {len(SMOKE_STEPS)} for the "
                "chief/specialist/synthesis smoke."
            )
        config = _build_config(api_key=api_key, model=args.model)
        runner = _build_runner(config)
        summary = await _run_text_only_flow(
            runner=runner,
            task=args.task,
            max_calls=args.max_calls,
            max_cost_usd=max_cost,
        )
        summary["model"] = args.model
    except Exception as exc:  # noqa: BLE001 - stable CLI failure surface
        print(
            f"OpenRouter multi-agent smoke failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    return asyncio.run(_run(argv, environ=environ))


if __name__ == "__main__":
    raise SystemExit(main())
