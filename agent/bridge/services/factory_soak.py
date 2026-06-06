"""Factory soak service — runs the Dark Factory shadow harness on a 4h cadence.

Sprint 14.11 — Plan 14 Phase 6 (production-enable gate).

Wraps :class:`bridge.factory.soak_harness.SoakHarness` as a scheduled
service so a LaunchDaemon can drive the 14-day shadow soak. Mirrors the
shape of :mod:`bridge.services.factory_orchestrator` (post-PR #1141)
deliberately — same interval, same data-dir conventions, same
``ServiceResult`` envelope — so the operator's mental model is one
service-pair (production + shadow) rather than two unrelated jobs.

Concept-only port of coleam00/dark-factory-experiment (no LICENSE, no
source copy).

The service is GATED by ``factory_soak_harness_enabled`` on the live
:class:`BridgeConfig`. Default OFF. When the flag is True, each tick
constructs a fresh :class:`FactoryOrchestrator` (its collaborators
default to the production wires) and hands it to a :class:`SoakHarness`
in observe-only mode. The orchestrator NEVER acts during a shadow tick
because the harness intercepts the routing path before any GitHub state
mutation.

After the soak window covers 14 days, at least ``min_verified_count`` entries
are verified correct, and ``correctness_rate >= min_correctness_rate``, the
operator can decide whether to flip ``factory_orchestrator_enabled`` to True
and disable this service.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from bridge.factory.soak_harness import (
    SoakEntry,
    SoakHarness,
)
from bridge.services.base import ServiceBase
from bridge.services.factory_orchestrator import (
    DEFAULT_REPO,
    FactoryOrchestrator,
)
from bridge.services.result import ServiceResult

logger = logging.getLogger(__name__)


# ── Service ──────────────────────────────────────────────────────────────


class FactorySoakService(ServiceBase):
    """Scheduled service. Drives the soak harness shadow tick.

    One tick per LaunchDaemon firing (every 4h). Each tick:

      1. Honors ``factory_soak_harness_enabled`` (early-return SKIP).
      2. Builds a :class:`FactoryOrchestrator` against the live config.
      3. Wraps it in a :class:`SoakHarness`.
      4. Runs ``shadow_tick`` — entries land in the soak JSONL.
      5. Returns a ``ServiceResult`` summarizing the tick.

    The orchestrator's production-action flag (``factory_orchestrator_enabled``)
    is independent — operators run shadow alone first, then flip prod.
    """

    def __init__(
        self,
        *,
        data_dir: str | Path,
        chat_id: str = "",
        repo: str = DEFAULT_REPO,
        config_enabled: bool = False,
        log_dir: Path | None = None,
        orchestrator: FactoryOrchestrator | None = None,
        event_callback: Callable[[str, dict], None] | None = None,
    ) -> None:
        super().__init__(data_dir=data_dir, event_callback=event_callback)
        self._chat_id = chat_id
        self._repo = repo
        self._config_enabled = config_enabled
        self._log_dir = (
            Path(log_dir) if log_dir is not None else self.data_dir / "factory-soak"
        )
        # Orchestrator can be injected by tests; production path lazily
        # constructs one in :meth:`run`.
        self._orchestrator = orchestrator

    async def run(self) -> ServiceResult:
        """Service entry — invoked by ``bridge.services.runner``.

        Honors ``factory_soak_harness_enabled``. Returns a
        ``ServiceResult`` normalized for the runner pipeline. The flag is
        read from the live ``BridgeConfig`` if the constructor did not
        pre-set it (the runner does not thread feature flags into
        constructors today).
        """
        start = time.monotonic()
        enabled = self._config_enabled
        if not enabled:
            try:
                from bridge.config import load_config
                cfg = load_config()
                enabled = bool(
                    getattr(cfg, "factory_soak_harness_enabled", False)
                )
            except Exception:  # pragma: no cover — defensive
                enabled = False
        if not enabled:
            return ServiceResult(
                service="factory_soak",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                cost_usd=0.0,
                skip_reason="feature flag OFF",
            )

        # Build the orchestrator on demand if none was injected. The
        # production wires use the orchestrator's defaults — implement,
        # validate, synthesize — so the shadow path exercises the same
        # code the production path will.
        orchestrator = self._orchestrator
        if orchestrator is None:
            orchestrator = FactoryOrchestrator(
                data_dir=self.data_dir,
                chat_id=self._chat_id,
                repo=self._repo,
                config_enabled=True,  # bypass orchestrator's own flag-check
            )

        harness = SoakHarness(
            orchestrator=orchestrator,
            log_dir=self._log_dir,
        )

        try:
            entries: tuple[SoakEntry, ...] = await harness.shadow_tick()
        except Exception as e:
            logger.exception("factory_soak: shadow_tick raised: %s", e)
            duration_ms = int((time.monotonic() - start) * 1000)
            return ServiceResult(
                service="factory_soak",
                ok=False,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                anomalies=("shadow_tick_failed",),
                narration=f"factory_soak: tick failed — {str(e)[:120]}",
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        total_cost = sum(e.cost_usd for e in entries)
        narration = (
            f"factory_soak: shadowed {len(entries)} issue(s), "
            f"cost ${total_cost:.4f}"
        )
        return ServiceResult(
            service="factory_soak",
            ok=True,
            work_items=len(entries),
            duration_ms=duration_ms,
            cost_usd=total_cost,
            narration=narration,
        )


__all__ = ["FactorySoakService"]
