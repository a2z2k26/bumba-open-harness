"""ServiceDispatchAdapter — composition primitive (Z2-S3.1).

Wraps ``DepartmentRegistry.route()`` behind a service-friendly API so
scheduled services can optionally route their work through a Zone 4
department instead of running inline.

Usage::

    adapter = ServiceDispatchAdapter(registry)
    result = await adapter.synthesize(
        department="strategy",
        task="Compose EOD memo with following context: ...",
        deps=deps,
    )
    if result.success:
        message = result.manager_output
    else:
        # fall back to direct render
        message = fallback_render()

The adapter NEVER raises. All exceptions are caught and returned as a
SynthesisResult with ``success=False``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from teams._types import BridgeDeps


@dataclass(frozen=True)
class SynthesisResult:
    """Uniform return type from ServiceDispatchAdapter.synthesize().

    Forward-compatible with ServiceResult (S0.1) and TeamResult (Z4) so
    downstream cost tracking and observability stay uniform.
    """

    manager_output: str
    success: bool = True
    error: str | None = None
    cost_usd: float = 0.0
    duration_s: float = 0.0


class ServiceDispatchAdapter:
    """Thin adapter that exposes DepartmentRegistry.route() as a service API.

    Args:
        registry: A ``DepartmentRegistry`` instance (or any object that
            exposes ``async def route(department, task, deps) -> TeamResult``).
            Pass ``None`` to get a no-op adapter that always returns
            ``success=False`` — useful for tests and feature-flag-off paths.
    """

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        department: str,
        task: str,
        deps: "BridgeDeps",
    ) -> SynthesisResult:
        """Route *task* to *department* via the registry and return a SynthesisResult.

        Never raises. Returns ``success=False`` on any error including:
        - Registry is None (feature flag off)
        - Department not found
        - Route raises an exception
        - Cost cap exceeded (propagated from TeamResult)

        Args:
            department: Name of the Z4 department (e.g. ``"strategy"``).
            task: The task description passed to the department manager.
            deps: BridgeDeps injected at dispatch time.

        Returns:
            SynthesisResult with manager_output, success, error, cost_usd,
            and duration_s populated.
        """
        import time

        if self._registry is None:
            return SynthesisResult(
                manager_output="",
                success=False,
                error="ServiceDispatchAdapter: registry is None (feature flag off)",
            )

        t0 = time.monotonic()
        try:
            team_result = await self._registry.route(department, task, deps)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            error_msg = str(exc)[:200]
            log.warning(
                "service_dispatch_adapter.route_failed department=%s error=%s",
                department, error_msg,
            )
            return SynthesisResult(
                manager_output="",
                success=False,
                error=error_msg,
                duration_s=elapsed,
            )

        elapsed = time.monotonic() - t0

        # Normalise None → "" so services can safely concatenate
        raw_output: str = team_result.manager_output or ""

        return SynthesisResult(
            manager_output=raw_output,
            success=team_result.success,
            error=team_result.error,
            cost_usd=team_result.total_cost_usd,
            duration_s=elapsed,
        )

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def disabled(cls) -> "ServiceDispatchAdapter":
        """Return a no-op adapter (registry=None) for when the flag is off."""
        return cls(registry=None)
