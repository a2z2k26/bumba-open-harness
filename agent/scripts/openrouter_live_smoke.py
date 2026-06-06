"""Guarded one-call OpenRouter live smoke for the model-agnostic runtime.

This script is intentionally narrow: it does not start the bridge daemon and
it refuses to run unless the operator explicitly sets both ``BUMBA_ALLOW_LIVE``
and ``OPENROUTER_API_KEY`` in the process environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Mapping, Sequence

from bridge.backends.openrouter import OpenRouterBackend

DEFAULT_SMOKE_MODEL = "z-ai/glm-4.6"
DEFAULT_PROMPT = "Reply with exactly: BUMBA_OPENROUTER_SMOKE_OK"
DEFAULT_MAX_COST_USD = Decimal("0.02")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL", DEFAULT_SMOKE_MODEL),
        help="OpenRouter model id for the single smoke request.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt for the single smoke request.",
    )
    parser.add_argument(
        "--max-cost-usd",
        default=os.environ.get("LIVE_COST_CAP", str(DEFAULT_MAX_COST_USD)),
        help="Fail if a known returned cost exceeds this cap.",
    )
    return parser.parse_args(argv)


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _build_backend(*, api_key: str, model: str) -> OpenRouterBackend:
    config = SimpleNamespace(
        openrouter_api_key=api_key,
        openrouter_default_model=model,
        fallback_openrouter_model=model,
    )
    return OpenRouterBackend(config)


def _json_amount(amount: Decimal | None) -> str | None:
    return str(amount) if amount is not None else None


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _parse_cost_cap(raw: str) -> Decimal:
    try:
        cap = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid --max-cost-usd value: {raw!r}") from exc
    if cap <= 0:
        raise ValueError("--max-cost-usd must be positive")
    return cap


def _summary(
    *,
    raw: dict,
    text: str,
    cost: object,
    requested_model: str,
    max_cost_usd: Decimal,
) -> dict:
    usage = raw.get("usage")
    return {
        "backend": "openrouter",
        "model": raw.get("model") or requested_model,
        "response_id": raw.get("id"),
        "max_cost_usd": _decimal_text(max_cost_usd),
        "usage": usage if isinstance(usage, dict) else {},
        "cost": {
            "source": getattr(cost, "source", "unknown"),
            "amount_usd": _json_amount(getattr(cost, "amount_usd", None)),
            "backend": getattr(cost, "backend", "openrouter"),
            "raw_usage_id": getattr(cost, "raw_usage_id", None),
        },
        "text_length": len(text),
        "text_preview": text[:240],
    }


def _known_cost_exceeds_cap(summary: Mapping[str, object], cap: Decimal) -> bool:
    cost = summary.get("cost")
    if not isinstance(cost, Mapping):
        return False
    if cost.get("source") != "measured":
        return False
    amount = cost.get("amount_usd")
    if amount is None:
        return False
    return Decimal(str(amount)) > cap


def _known_cost_amount(summary: Mapping[str, object]) -> object:
    cost = summary.get("cost")
    if not isinstance(cost, Mapping):
        return "unknown"
    return cost.get("amount_usd") or "unknown"


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    if env.get("BUMBA_ALLOW_LIVE") != "1":
        return _fail(
            "Refusing live OpenRouter smoke: set BUMBA_ALLOW_LIVE=1 only for "
            "an operator-approved live validation."
        )

    api_key = str(env.get("OPENROUTER_API_KEY", "") or "")
    if not api_key:
        return _fail(
            "Refusing live OpenRouter smoke: OPENROUTER_API_KEY is required."
        )

    args = _parse_args(argv)
    try:
        max_cost = _parse_cost_cap(args.max_cost_usd)
        backend = _build_backend(api_key=api_key, model=args.model)
        raw = backend.request(message=args.prompt, system_prompt=None)
        event = backend.parse_event(json.dumps(raw))
        if event is None or event.is_error:
            print(
                "OpenRouter smoke failed: response did not contain a parseable "
                "assistant message.",
                file=sys.stderr,
            )
            return 1
        cost = backend.parse_cost(raw)
        summary = _summary(
            raw=raw,
            text=event.text,
            cost=cost,
            requested_model=args.model,
            max_cost_usd=max_cost,
        )
    except Exception as exc:  # noqa: BLE001 - CLI must return a stable rc
        print(
            f"OpenRouter smoke failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    if _known_cost_exceeds_cap(summary, max_cost):
        amount = _known_cost_amount(summary)
        print(
            f"OpenRouter smoke failed: known cost {amount} exceeded cap "
            f"{_decimal_text(max_cost)}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
