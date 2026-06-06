"""Guarded one-call OpenRouter live smoke through ``ClaudeRunner``.

This script is intentionally narrow: it does not start the bridge daemon and
it refuses to run unless the operator explicitly sets both ``BUMBA_ALLOW_LIVE``
and ``OPENROUTER_API_KEY`` in the process environment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import replace
from typing import Mapping, Sequence

from bridge.claude_runner import ClaudeResult, ClaudeRunner
from bridge.config import BridgeConfig

DEFAULT_SMOKE_MODEL = "z-ai/glm-4.6"
DEFAULT_PROMPT = "Reply with exactly: BUMBA_OPENROUTER_RUNNER_SMOKE_OK"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL", DEFAULT_SMOKE_MODEL),
        help="OpenRouter model id for the single ClaudeRunner smoke request.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt for the single ClaudeRunner smoke request.",
    )
    return parser.parse_args(argv)


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _build_config(*, api_key: str, model: str) -> BridgeConfig:
    return replace(
        BridgeConfig(),
        backends_enabled=True,
        backends_main="openrouter",
        openrouter_api_key=api_key,
        openrouter_default_model=model,
        fallback_openrouter_model=model,
    )


def _build_runner(config: BridgeConfig) -> ClaudeRunner:
    return ClaudeRunner(config)


def _json_cost_amount(amount: float) -> str:
    text = f"{amount:.12f}".rstrip("0").rstrip(".")
    return text or "0"


def _summary(*, result: ClaudeResult, requested_model: str) -> dict:
    return {
        "backend": "openrouter",
        "model": requested_model,
        "response_id": result.cost_raw_usage_id or result.session_id or None,
        "session_id": result.session_id or None,
        "cost": {
            "amount_usd": _json_cost_amount(result.cost_usd),
            "source": result.cost_source
            or ("unknown" if result.cost_unknown else "measured_or_estimated"),
            "unknown": result.cost_unknown,
        },
        "duration_ms": result.duration_ms,
        "live_call_count": 1,
        "text_length": len(result.response_text),
        "text_preview": result.response_text[:240],
    }


async def _run(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    if env.get("BUMBA_ALLOW_LIVE") != "1":
        return _fail(
            "Refusing live OpenRouter runner smoke: set BUMBA_ALLOW_LIVE=1 "
            "only for an operator-approved live validation."
        )

    api_key = str(env.get("OPENROUTER_API_KEY", "") or "")
    if not api_key:
        return _fail(
            "Refusing live OpenRouter runner smoke: OPENROUTER_API_KEY is "
            "required."
        )

    args = _parse_args(argv)
    try:
        config = _build_config(api_key=api_key, model=args.model)
        runner = _build_runner(config)
        result = await runner.invoke(args.prompt)
    except Exception as exc:  # noqa: BLE001 - CLI must return a stable rc
        print(
            f"OpenRouter runner smoke failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    if result.is_error or not result.response_text:
        error_type = result.error_type or "empty_response"
        detail = result.stderr_output or "ClaudeRunner returned no response text"
        print(
            f"OpenRouter runner smoke failed: {error_type}: {detail}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            _summary(result=result, requested_model=args.model),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    return asyncio.run(_run(argv, environ=environ))


if __name__ == "__main__":
    raise SystemExit(main())
