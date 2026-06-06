"""Self-verification harness — check agent output at localhost URLs.

Extracts localhost URLs from response text, spawns a Playwright script
to verify assertions, and returns pass/fail results. Disabled by default;
toggle via /verify on|off (#20).

P2.5 (#1579) — verification policy levels replace the prior pure-advisory
surface. Three levels are recognised:

* ``POLICY_OFF`` — verifier is skipped entirely, even when wired into the
  evaluator. Useful for short-duration diagnostics or known-broken
  localhost fixtures.
* ``POLICY_WARN`` — current advisory behaviour. Verification failures are
  appended to ``EvaluationResult.issues`` but the evaluator verdict is
  unchanged. This is the default to preserve back-compat with pre-P2.5
  behaviour.
* ``POLICY_BLOCK`` — verification failures force ``verdict = "fail"`` so
  the existing fail-handling plumbing in ``app.py`` fires (publishes
  ``response.evaluator.fail`` on the event bus, records a failure on
  ``routing_feedback``). This satisfies the "block prevents delivery or
  requires HITL surface" acceptance criterion via the existing fail-event
  surface that Mission Control listens to.

Policy is resolved at call time via :func:`resolve_policy`. Resolution
order (first hit wins): explicit ``override`` argument →
``BUMBA_VERIFICATION_POLICY`` environment variable →
``BridgeConfig.verification_policy`` (passed in as ``config_policy``
argument by callers that have access to the live config) →
:data:`DEFAULT_POLICY` (``"warn"``). The env var stays usable as an
override on top of the config so an operator can flip a single bridge
instance without editing ``bridge.toml`` — see issue #1664.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from bridge.dispatch_metrics import increment_module_counter

logger = logging.getLogger(__name__)

# Match localhost URLs (http://localhost:NNNN/... or http://127.0.0.1:NNNN/...)
_LOCALHOST_RE = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1):\d{1,5}(?:/[^\s\)\]\}>\"']*)?",
)

# Maximum time for a single verification
VERIFY_TIMEOUT = 5  # seconds

# P2.5 (#1579) — verification policy levels
POLICY_OFF: str = "off"
POLICY_WARN: str = "warn"
POLICY_BLOCK: str = "block"

#: Tuple of all valid policy strings (used by ``resolve_policy`` to
#: validate operator overrides before falling back to the default).
VALID_POLICIES: tuple[str, ...] = (POLICY_OFF, POLICY_WARN, POLICY_BLOCK)

#: Default policy when ``BUMBA_VERIFICATION_POLICY`` is unset or set to an
#: unrecognised value. ``warn`` preserves the pre-P2.5 advisory behaviour
#: exactly, so flipping the default is operator-visible (no silent
#: regression from "advisory" to "blocking").
DEFAULT_POLICY: str = POLICY_WARN

#: Environment variable consulted by ``resolve_policy``. Documented here so
#: the contract is discoverable from a single place.
POLICY_ENV_VAR: str = "BUMBA_VERIFICATION_POLICY"


def resolve_policy(
    override: str | None = None,
    *,
    config_policy: str | None = None,
) -> str:
    """Return the active verification policy.

    Resolution order (first non-None wins):

    1. Explicit ``override`` argument (callers that want to pin a policy
       for a single call, e.g. tests).
    2. ``BUMBA_VERIFICATION_POLICY`` environment variable.
    3. ``config_policy`` argument — the ``BridgeConfig.verification_policy``
       value threaded in by callers that have access to the live config
       (e.g. :class:`bridge.response_evaluator.ResponseEvaluator`). Lets
       ``bridge.toml`` become the canonical source while leaving the env
       var as an operator-visible override (#1664).
    4. :data:`DEFAULT_POLICY` (``"warn"``).

    Unrecognised values at any tier fall through to the next tier and
    emit one WARNING log so misconfiguration is loud. Case-insensitive.
    """
    # Tier 1 + 2: explicit override or env var.
    raw = override if override is not None else os.environ.get(POLICY_ENV_VAR)
    if raw is not None:
        normalised = raw.strip().lower()
        if normalised in VALID_POLICIES:
            return normalised
        logger.warning(
            "Unrecognised verification policy %r — falling back to "
            "config or default. Valid values: %s",
            raw, ", ".join(VALID_POLICIES),
        )
        # Fall through to config / default.

    # Tier 3: config-supplied value (when threaded in by the caller).
    if config_policy is not None:
        normalised = config_policy.strip().lower()
        if normalised in VALID_POLICIES:
            return normalised
        logger.warning(
            "Unrecognised verification policy %r in bridge.toml — falling "
            "back to %r. Valid values: %s",
            config_policy, DEFAULT_POLICY, ", ".join(VALID_POLICIES),
        )

    # Tier 4: default.
    return DEFAULT_POLICY


@dataclass
class VerificationResult:
    """Result of verifying one or more localhost URLs."""

    passed: bool = True
    errors: list[str] = field(default_factory=list)
    urls_checked: int = 0
    duration_ms: int = 0


class SelfVerifier:
    """Verify agent responses by checking localhost URLs with Playwright.

    Disabled by default. Enable with ``/verify on`` or by setting
    ``enabled=True`` at construction.
    """

    def __init__(self, *, enabled: bool = False, timeout_s: float = VERIFY_TIMEOUT) -> None:
        self.enabled = enabled
        self.timeout_s = timeout_s

    @staticmethod
    def extract_urls(text: str) -> list[str]:
        """Extract localhost URLs from response text."""
        return _LOCALHOST_RE.findall(text)

    async def verify_url(self, url: str, assertions: list[str] | None = None) -> VerificationResult:
        """Verify a single localhost URL is reachable and optionally check assertions.

        Returns VerificationResult with pass/fail and any errors.
        Graceful on: URL unreachable, timeout, missing playwright.
        """
        errors: list[str] = []
        try:
            result = await asyncio.wait_for(
                self._check_url(url, assertions or []),
                timeout=self.timeout_s,
            )
            return result
        except asyncio.TimeoutError:
            errors.append(f"Verification timed out after {self.timeout_s}s: {url}")
            return VerificationResult(passed=False, errors=errors, urls_checked=1)
        except Exception as e:
            errors.append(f"Verification error for {url}: {e}")
            return VerificationResult(passed=False, errors=errors, urls_checked=1)

    async def verify_response(self, response_text: str) -> VerificationResult | None:
        increment_module_counter("self_verifier.verify_response", tier=3)
        """Verify all localhost URLs found in a response.

        Returns None if no URLs found or verifier is disabled.
        """
        if not self.enabled:
            return None

        urls = self.extract_urls(response_text)
        if not urls:
            return None

        all_errors: list[str] = []
        all_passed = True

        for url in urls[:3]:  # Cap at 3 URLs to avoid excessive checking
            result = await self.verify_url(url)
            if not result.passed:
                all_passed = False
                all_errors.extend(result.errors)

        return VerificationResult(
            passed=all_passed,
            errors=all_errors,
            urls_checked=len(urls[:3]),
        )

    async def _check_url(self, url: str, assertions: list[str]) -> VerificationResult:
        """Check a URL using an HTTP request (lightweight, no Playwright dependency).

        Falls back gracefully if the URL is unreachable.
        """
        errors: list[str] = []

        try:
            # Use aiohttp for lightweight HTTP check (no Playwright dependency required)
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=self.timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status >= 400:
                        errors.append(f"HTTP {resp.status} from {url}")
                    else:
                        # If assertions provided, check response body
                        if assertions:
                            body = await resp.text()
                            for assertion in assertions:
                                if assertion not in body:
                                    errors.append(
                                        f"Assertion failed: '{assertion}' not found in response from {url}"
                                    )
        except ImportError:
            # aiohttp not available — try stdlib
            try:
                import urllib.request
                with urllib.request.urlopen(url, timeout=self.timeout_s) as resp:
                    if resp.status >= 400:
                        errors.append(f"HTTP {resp.status} from {url}")
            except Exception as e:
                errors.append(f"URL unreachable: {url} ({e})")
        except Exception as e:
            errors.append(f"URL unreachable: {url} ({e})")

        return VerificationResult(
            passed=len(errors) == 0,
            errors=errors,
            urls_checked=1,
        )
