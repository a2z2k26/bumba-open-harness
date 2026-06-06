"""Provider-aware usage policy helpers for Zone 4 team runs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class UsagePolicy:
    provider: str
    request_limit: int | None
    input_tokens_limit: int | None
    output_tokens_limit: int | None
    provider_context_window_tokens: int
    preflight_context_chars: int
    clear_warm_context_after_tokens: int


_DEFAULT_CONTEXT_WINDOW_TOKENS = 250_000
_PROVIDER_CONTEXT_WINDOWS: dict[str, int] = {
    "anthropic": 200_000,
    "anthropic-oauth": 200_000,
    "codex-cli": 200_000,
    "openai": 1_000_000,
    "openrouter": 250_000,
    "unknown": _DEFAULT_CONTEXT_WINDOW_TOKENS,
}


def classify_model_provider(model: str) -> str:
    """Return the runtime provider family implied by a model string."""
    value = model.strip()
    if value.startswith("openrouter:"):
        return "openrouter"
    if value.startswith("anthropic-oauth:"):
        return "anthropic-oauth"
    if value.startswith("openai:"):
        return "openai"
    if value.startswith("codex-exec:"):
        return "codex-cli"
    if value.startswith("anthropic:") or value.startswith(
        ("claude-", "sonnet-", "opus-", "haiku-")
    ):
        return "anthropic"
    return "unknown"


def resolve_usage_policy(
    *,
    provider: str,
    configured_request_limit: int,
    configured_input_limit: int,
    configured_output_limit: int,
) -> UsagePolicy:
    """Resolve provider-aware policy while preserving configured caps."""
    provider_name = provider if provider in _PROVIDER_CONTEXT_WINDOWS else "unknown"
    if provider_name == "openai":
        preflight_context_chars = 500_000
        clear_warm_context_after_tokens = 200_000
    else:
        preflight_context_chars = 350_000
        clear_warm_context_after_tokens = 180_000

    return UsagePolicy(
        provider=provider_name,
        request_limit=_positive_or_none(configured_request_limit),
        input_tokens_limit=_positive_or_none(configured_input_limit),
        output_tokens_limit=_positive_or_none(configured_output_limit),
        provider_context_window_tokens=_PROVIDER_CONTEXT_WINDOWS[provider_name],
        preflight_context_chars=preflight_context_chars,
        clear_warm_context_after_tokens=clear_warm_context_after_tokens,
    )


def estimate_preflight_context_chars(
    *,
    task: str,
    message_history: object | None,
) -> int:
    """Estimate context size before spending provider requests."""
    total = len(task)
    if message_history is None:
        return total
    if isinstance(message_history, str):
        return total + len(message_history)
    if isinstance(message_history, Iterable):
        return total + sum(len(str(item)) for item in message_history)
    return total + len(str(message_history))


def usage_limit_failure_class(exc: BaseException) -> str | None:
    """Return a low-cardinality usage failure class when one is recognizable."""
    text = _exception_text(exc).lower()
    if type(exc).__name__ == "ModelHTTPError" and _looks_like_provider_context_cap(text):
        return "usage_provider_hard_cap"

    if type(exc).__name__ != "UsageLimitExceeded":
        return None

    if "request limit" in text or "requests" in text:
        return "usage_request_count_cap"
    if (
        "input_tokens_limit" in text
        or "request_token" in text
        or "input token" in text
    ):
        return "usage_internal_input_cap"
    if (
        "output_tokens_limit" in text
        or "response_token" in text
        or "output token" in text
    ):
        return "usage_internal_output_cap"
    return "usage_internal_cap"


def _positive_or_none(value: int) -> int | None:
    return value if value and value > 0 else None


def _looks_like_provider_context_cap(text: str) -> bool:
    needles = (
        "context length",
        "context window",
        "maximum context",
        "max context",
        "too many tokens",
    )
    return any(needle in text for needle in needles)


def _exception_text(exc: BaseException) -> str:
    parts: list[str] = [str(exc)]
    body = getattr(exc, "body", None)
    if body is not None:
        parts.extend(_flatten_body(body))
    return " ".join(part for part in parts if part)


def _flatten_body(body: object) -> list[str]:
    if isinstance(body, str):
        return [body]
    if isinstance(body, dict):
        values: list[str] = []
        for value in body.values():
            values.extend(_flatten_body(value))
        return values
    if isinstance(body, list | tuple):
        values = []
        for value in body:
            values.extend(_flatten_body(value))
        return values
    return [str(body)]
