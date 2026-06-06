"""P3.03 — HttpBackend estimated cost from usage + model capabilities.

No live calls — cost is computed from a usage dict the caller hands in.
Placed flat (tests/test_http_backend_cost.py); no tests/test_backends/ package.
"""
from __future__ import annotations

from decimal import Decimal

from bridge.backends.http_base import HttpBackend


def _backend(model: str = "deepseek/deepseek-chat") -> HttpBackend:
    return HttpBackend(
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-test",
        model=model,
        timeout=30,
        price_per_1m=(0.14, 0.28),
    )


def test_parse_cost_estimated_from_usage() -> None:
    event = {
        "model": "deepseek/deepseek-chat",
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
        "id": "gen-abc",
    }
    cost = _backend().parse_cost(event)
    assert cost.source == "estimated"
    # 1M input @ 0.14 + 1M output @ 0.28 = 0.42 USD.
    assert cost.amount_usd == Decimal("0.42")
    assert cost.backend == "http"
    assert cost.raw_usage_id == "gen-abc"


def test_parse_cost_unknown_when_usage_absent() -> None:
    cost = _backend().parse_cost({"model": "deepseek/deepseek-chat", "id": "gen-x"})
    assert cost.source == "unknown"
    assert cost.amount_usd is None


def test_parse_cost_unknown_when_no_pricing_configured() -> None:
    backend = HttpBackend(
        base_url="https://x/api/v1", api_key="k", model="m", timeout=30,
    )  # no price_per_1m
    cost = backend.parse_cost(
        {"usage": {"prompt_tokens": 100, "completion_tokens": 50}, "id": "g"}
    )
    assert cost.source == "unknown"
    assert cost.amount_usd is None


def test_capabilities_reports_streaming_and_model() -> None:
    caps = _backend().capabilities
    assert caps["model"] == "deepseek/deepseek-chat"
    assert caps["streaming"] is False
    assert caps["transport"] == "http"
