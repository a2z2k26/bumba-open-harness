"""Token bucket rate limiter for subprocess invocation.

Prevents overwhelming the Claude API with requests. Supports
dynamic rate adjustment on 429 responses.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class TokenBucket:
    """Token bucket rate limiter.

    Starts with `capacity` tokens, refills at `refill_rate` tokens/second.
    Each request consumes 1 token by default.
    """

    def __init__(
        self,
        capacity: float = 10.0,
        refill_rate: float = 0.5,
    ) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._total_allowed = 0
        self._total_denied = 0

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def check(self, tokens: float = 1.0) -> tuple[bool, float]:
        """Check if request is allowed without consuming. Returns (allowed, wait_seconds)."""
        self._refill()
        if self._tokens >= tokens:
            return True, 0.0
        deficit = tokens - self._tokens
        return False, deficit / self._refill_rate

    def consume(self, tokens: float = 1.0) -> tuple[bool, float]:
        """Try to consume tokens. Returns (allowed, wait_seconds)."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            self._total_allowed += 1
            return True, 0.0
        deficit = tokens - self._tokens
        self._total_denied += 1
        return False, deficit / self._refill_rate

    async def wait_and_consume(self, tokens: float = 1.0) -> None:
        """Block until tokens are available, then consume."""
        while True:
            allowed, wait = self.consume(tokens)
            if allowed:
                return
            await asyncio.sleep(wait)

    def on_rate_limited(self) -> None:
        """Call when a 429 is received. Reduces refill rate by 20%."""
        old = self._refill_rate
        self._refill_rate = max(self._refill_rate * 0.8, 0.01)
        self._tokens = 0  # drain bucket
        logger.info("Rate limited: refill %.3f -> %.3f tokens/s", old, self._refill_rate)

    def on_success(self) -> None:
        """Call on success. Slowly restores refill rate toward capacity."""
        original = self._capacity / 20.0  # default: capacity/20 per second
        if self._refill_rate < original:
            self._refill_rate = min(self._refill_rate * 1.05, original)

    def get_status(self) -> dict:
        self._refill()
        return {
            "tokens": round(self._tokens, 2),
            "capacity": self._capacity,
            "refill_rate": round(self._refill_rate, 3),
            "total_allowed": self._total_allowed,
            "total_denied": self._total_denied,
        }


# ---------------------------------------------------------------------------
# Per-provider orchestration rate limiter (moved from bridge/orchestration/)
# ---------------------------------------------------------------------------
from dataclasses import dataclass as _dataclass, field as _field
from typing import Dict as _Dict, Optional as _Optional


@_dataclass
class RateLimitConfig:
    """Rate limit configuration for a provider."""
    requests_per_minute: int
    tokens_per_minute: int
    burst_multiplier: float = 1.5


@_dataclass
class RateLimitResult:
    """Result of a rate-limit check."""
    allowed: bool
    wait_seconds: float
    reason: str


# Default limits per provider
DEFAULT_LIMITS: _Dict[str, RateLimitConfig] = {
    "anthropic": RateLimitConfig(requests_per_minute=50, tokens_per_minute=100_000),
    "openai": RateLimitConfig(requests_per_minute=500, tokens_per_minute=300_000),
    "default": RateLimitConfig(requests_per_minute=60, tokens_per_minute=50_000),
}


@_dataclass
class _ProviderBucket:
    """Internal token-bucket state for a single provider."""
    config: RateLimitConfig
    request_tokens: float = _field(init=False)
    token_tokens: float = _field(init=False)
    last_refill: float = _field(default_factory=time.monotonic)
    model_usage: _Dict[str, _Dict] = _field(default_factory=dict)

    def __post_init__(self) -> None:
        self.request_tokens = self.config.requests_per_minute * self.config.burst_multiplier
        self.token_tokens = self.config.tokens_per_minute * self.config.burst_multiplier

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        req_refill = (self.config.requests_per_minute / 60.0) * elapsed
        tok_refill = (self.config.tokens_per_minute / 60.0) * elapsed
        max_req = self.config.requests_per_minute * self.config.burst_multiplier
        max_tok = self.config.tokens_per_minute * self.config.burst_multiplier
        self.request_tokens = min(self.request_tokens + req_refill, max_req)
        self.token_tokens = min(self.token_tokens + tok_refill, max_tok)

    def check(self, estimated_tokens: int) -> "RateLimitResult":
        self._refill()
        if self.request_tokens < 1:
            wait = (1 - self.request_tokens) / (self.config.requests_per_minute / 60.0)
            return RateLimitResult(allowed=False, wait_seconds=round(wait, 2), reason="request rate limit exceeded")
        if estimated_tokens > 0 and self.token_tokens < estimated_tokens:
            wait = (estimated_tokens - self.token_tokens) / (self.config.tokens_per_minute / 60.0)
            return RateLimitResult(allowed=False, wait_seconds=round(wait, 2), reason="token rate limit exceeded")
        return RateLimitResult(allowed=True, wait_seconds=0.0, reason="")

    def consume(self, tokens_used: int) -> None:
        self._refill()
        self.request_tokens = max(0.0, self.request_tokens - 1)
        if tokens_used > 0:
            self.token_tokens = max(0.0, self.token_tokens - tokens_used)

    def status(self) -> _Dict:
        self._refill()
        return {
            "request_tokens": round(self.request_tokens, 2),
            "token_tokens": round(self.token_tokens, 2),
            "model_usage": dict(self.model_usage),
        }


class TokenBucketRateLimiter:
    """Per-provider token-bucket rate limiter (moved from bridge/orchestration/)."""

    def __init__(self, custom_limits: _Optional[_Dict[str, RateLimitConfig]] = None) -> None:
        self._limits: _Dict[str, RateLimitConfig] = {**DEFAULT_LIMITS, **(custom_limits or {})}
        self._buckets: _Dict[str, _ProviderBucket] = {}

    def _get_bucket(self, provider: str) -> _ProviderBucket:
        if provider not in self._buckets:
            config = self._limits.get(provider, self._limits["default"])
            self._buckets[provider] = _ProviderBucket(config=config)
        return self._buckets[provider]

    def check_request(self, provider: str, model: str, estimated_tokens: int = 0) -> RateLimitResult:
        return self._get_bucket(provider).check(estimated_tokens)

    def record_usage(self, provider: str, model: str, tokens_used: int) -> None:
        bucket = self._get_bucket(provider)
        bucket.consume(tokens_used)
        if model not in bucket.model_usage:
            bucket.model_usage[model] = {"requests": 0, "tokens": 0}
        bucket.model_usage[model]["requests"] += 1
        bucket.model_usage[model]["tokens"] += tokens_used

    def get_bucket_status(self, provider: str) -> _Dict:
        return self._get_bucket(provider).status()
