"""Weekly CEO Review service — Zone 4 Layer 2 workflow trigger.

Scheduled: Monday 08:00 UTC (via com.bumba.agent-weekly-ceo-review LaunchDaemon).

This service is a thin wrapper that triggers the ``weekly-ceo-review`` workflow
via WorkflowEngine rather than running the review itself.  All department
invocations and Discord posting are handled by the workflow engine.

Usage::

    python3 -m bridge.services.runner weekly_ceo_review

## Dependency behavior

The standalone service runner injects a ``WorkflowRegistry`` and
``WorkflowEngine`` for this service. If either dependency cannot be
constructed, ``run()`` still returns an explicit
``ServiceResult(ok=False, narration="... workflow engine not configured")``
instead of silently reporting success.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .base import ServiceBase
from .result import ServiceResult

log = logging.getLogger(__name__)

WORKFLOW_NAME = "weekly-ceo-review"


class WeeklyCEOReviewService(ServiceBase):
    """Trigger the weekly-ceo-review Z4 workflow."""

    SERVICE_NAME = "weekly_ceo_review"

    def __init__(
        self,
        data_dir: str | Path,
        workflow_registry: Any | None = None,
        workflow_engine: Any | None = None,
        chat_id: str = "operator",
        board_run_store: Any | None = None,
    ) -> None:
        super().__init__(data_dir)
        self._workflow_registry = workflow_registry
        self._workflow_engine = workflow_engine
        self._chat_id = chat_id
        # Board Phase 3 WS2 (#2392) — when wired, the CEO review computes the
        # board implementation rate (issues generated / closed / avg close
        # time per board run) and injects it as workflow context. Falls back
        # to a fresh store from data_dir so the service works even without
        # explicit injection.
        if board_run_store is None:
            try:
                from bridge.board_run_store import BoardRunStore
                board_run_store = BoardRunStore(data_dir)
            except Exception:  # noqa: BLE001
                board_run_store = None
        self._board_run_store = board_run_store

    async def run(self) -> ServiceResult:
        """Trigger the weekly-ceo-review workflow and return immediately.

        The workflow runs asynchronously; this service records the run_id
        and returns so the LaunchDaemon process can exit.
        """
        if self._workflow_registry is None or self._workflow_engine is None:
            log.error(
                "WeeklyCEOReviewService: workflow_registry or workflow_engine not set — cannot run"
            )
            return ServiceResult(
                service=self.SERVICE_NAME,
                ok=False,
                work_items=0,
                duration_ms=0,
                cost_usd=0.0,
                narration="Weekly CEO Review skipped — workflow engine not configured.",
            )

        cfg = self._workflow_registry.get(WORKFLOW_NAME)
        if cfg is None:
            log.error(
                "WeeklyCEOReviewService: workflow '%s' not found in registry",
                WORKFLOW_NAME,
            )
            return ServiceResult(
                service=self.SERVICE_NAME,
                ok=False,
                work_items=0,
                duration_ms=0,
                cost_usd=0.0,
                narration=f"Weekly CEO Review skipped — workflow '{WORKFLOW_NAME}' not found.",
            )

        inputs = {"_chat_id": self._chat_id}

        # Board Phase 3 WS2 (#2392) — board implementation rate as context.
        board_summary = ""
        if self._board_run_store is not None:
            try:
                stats = self._board_run_store.compute_implementation_rate()
                inputs["board_implementation_rate"] = stats
                rate = stats.get("implementation_rate")
                if stats.get("total_generated"):
                    board_summary = (
                        f" Board: {stats['total_closed']}/{stats['total_generated']} "
                        f"issues closed"
                        + (f" ({rate:.0%} implementation rate)." if rate is not None else ".")
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("board implementation-rate compute failed: %s", exc)

        run_id = self._workflow_registry.trigger(
            WORKFLOW_NAME, inputs, engine=self._workflow_engine
        )

        log.info("WeeklyCEOReviewService: triggered workflow run %s", run_id)
        return ServiceResult(
            service=self.SERVICE_NAME,
            ok=True,
            work_items=1,
            duration_ms=0,
            cost_usd=0.0,
            narration=f"Weekly CEO Review triggered — run ID: {run_id}.{board_summary}",
        )

    # Synchronous entry point for runner.py
    def run_sync(self) -> ServiceResult:
        return asyncio.run(self.run())
