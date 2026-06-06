"""Job Search Services — two-cron model routing via DepartmentRegistry.

JobSearchPrepareService (08:00 daily):
  Constructs BridgeDeps and calls registry.route("job_search", "prepare ...", deps).

JobSearchExecuteService (every 2hrs, 10:00-20:00):
  Constructs BridgeDeps and calls registry.route("job_search", "execute ...", deps).

Sprint D5.6: Cron entry points are now thin — no in-service agent construction.
Agent construction, tool registration, circuit breaker, semaphore, namespace
guard, cost tracking, and verification gates all come from teams/ infra.

Sprint 02.08: replaced ``unittest.mock`` mocks in the cron deps with real
:meth:`teams._types.BridgeDeps.for_cron` so the cron path now wires through
real EventBus / CostTracker / TrustScoreEngine / Memory. Without this, cron
runs were invisible to the bridge's observability stack.

Sprint 02.09: ``preflight_check`` (7 environment checks: secrets file, OAuth
+ Notion tokens, gws CLI for execute, criteria/candidate JSON config files,
SQLite DB writability, Notion API reachability, dedup state) is now invoked
at the very top of every cron run. On failure, the service is recorded as a
SKIP (env problem — not a service bug, must not increment
``consecutive_failures``) and exits before any deps are built or tokens are
spent. Without this, missing tokens, bad config, or unreachable Notion would
not surface until partway through a phase, after costs were already incurred
and partial state was written to disk.

Sprint P5.3 (#1588): shared cron helpers (``_preflight_paths``,
``_run_preflight``, ``_failure_key``, ``_get_notion_db_id``,
``_resolve_agent_root``, ``_resolve_data_root``, ``_STATE_FILE``) extracted
to :mod:`job_search._pipeline` so the CLI entry in :mod:`job_search.__main__`
can join the same canonical path without duplicating them. Names are
re-imported here so existing tests that ``patch("job_search.service.*")``
continue to work — pytest patches whichever module looked the attribute up.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from pathlib import Path

from bridge.services.base import ServiceBase, SkipClass, SkipReason
from bridge.services.result import ServiceResult
from teams._types import BridgeDeps, TeamResult

from job_search._pipeline import (
    _STATE_FILE,
    _build_halt_policy,
    _failure_key,
    _get_notion_db_id,
    _preflight_paths,
    _resolve_agent_root,
    _resolve_data_root,
    _run_preflight,
)

log = logging.getLogger(__name__)


AGENT_ROOT = _resolve_agent_root()
DATA_DIR = _resolve_data_root()

__all__ = [
    "JobSearchPrepareService",
    "JobSearchExecuteService",
    "JobSearchService",
    "AGENT_ROOT",
    "DATA_DIR",
    "_STATE_FILE",
    "_build_halt_policy",
    "_failure_key",
    "_get_notion_db_id",
    "_preflight_paths",
    "_preflight_skip_reason",
    "_resolve_agent_root",
    "_resolve_data_root",
    "_run_preflight",
]


def _preflight_skip_reason(error: str) -> SkipReason:
    """Map preflight errors onto the service skip taxonomy.

    ``preflight_check`` returns human-readable messages. The service state
    needs an actionable ``last_skipped_class`` so stale-skip audits can
    distinguish "operator needs to update a secret" from "dependency is down".
    """
    key = _failure_key(error)
    normalized = error.lower()

    if key in {"notion_api_token", "claude_oauth_token"}:
        return SkipReason(SkipClass.MISSING_SECRET, key)
    if "secrets file not found" in normalized:
        return SkipReason(SkipClass.MISSING_SECRET, "secrets_file")
    if "notion api token is invalid" in normalized:
        return SkipReason(SkipClass.MISSING_SECRET, "notion_api_token")
    if "criteria config" in normalized:
        return SkipReason(SkipClass.MISSING_CONFIG, "job_search.criteria")
    if "candidate config" in normalized:
        return SkipReason(SkipClass.MISSING_CONFIG, "job_search.candidate")
    if "gws cli not found" in normalized:
        return SkipReason(SkipClass.DEPENDENCY_UNAVAILABLE, "gws")
    if "notion api unreachable" in normalized:
        return SkipReason(SkipClass.DEPENDENCY_UNAVAILABLE, "notion_api")
    if "database not writable" in normalized:
        return SkipReason(SkipClass.DEPENDENCY_UNAVAILABLE, "job_search_db")
    if "already ran prepare today" in normalized:
        return SkipReason(SkipClass.NOT_DUE, "already ran prepare today")
    return SkipReason(SkipClass.DEPENDENCY_UNAVAILABLE, key)


class JobSearchPrepareService(ServiceBase):
    """Morning cron — PREPARE pipeline via DepartmentRegistry."""

    def __init__(
        self,
        data_dir: str | Path = DATA_DIR,
        chat_id: str = "",
        *,
        run_hour: int = 8,
        event_callback=None,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.chat_id = chat_id
        self.run_hour = run_hour

    def should_run(self) -> bool:
        """Check time window (run_hour ± 30min) and daily dedup."""
        now = datetime.now()
        target_minutes = self.run_hour * 60
        current_minutes = now.hour * 60 + now.minute
        if abs(current_minutes - target_minutes) > 30:
            return False

        state = self.load_state(filename=_STATE_FILE)
        last_run = state.get("last_run")
        if last_run:
            try:
                last_run_date = last_run[:10]  # "YYYY-MM-DD"
            except (TypeError, AttributeError):
                last_run_date = None
            if last_run_date == date.today().isoformat():
                return False

        return True

    def run(self) -> ServiceResult:
        """Execute the PREPARE pipeline via DepartmentRegistry.

        Constructs BridgeDeps and calls department.run_prepare, which routes
        through registry.route("job_search", intent, deps). Returns a
        :class:`ServiceResult` consumed by ``run_service_with_timeout`` for
        uniform observability — OK on success, SKIP for window/preflight
        no-ops, FAIL when the underlying TeamResult is unsuccessful.

        Sprint 02.09: ``preflight_check`` runs BEFORE ``BridgeDeps.for_cron``
        so missing secrets, bad config, or unreachable Notion fail fast as a
        SKIP (no consecutive_failures bump, no department invocation, no
        cost incurred).

        Sprint #1755: migrated from ``-> bool`` to ``-> ServiceResult`` to
        complete Plan 02 02.01's residual; aligns with ``funnel_post`` and
        the ``test_all_services_return_service_result_type`` regression
        guard.
        """
        t0 = time.monotonic()

        if not self.should_run():
            log.info("Job search prepare skipped (outside window or already ran today)")
            self.record_skipped("outside window or already ran today", filename=_STATE_FILE)
            return ServiceResult(
                service="job_search",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=0.0,
                skip_reason="outside_window_or_already_ran",
            )

        # Halt gate (audit-2026-05-16.C.04, #2059) — entry check.
        # Belt-and-suspenders with bridge.services.runner._async_main, which
        # already exits before constructing the service. The runner gate is
        # what the LaunchDaemon hits; this gate guards every other caller
        # (tests, ad-hoc Python invocations, future schedulers).
        halt_policy = _build_halt_policy(Path(self.data_dir))
        decision = halt_policy.check_start("job-search")
        if decision.blocked:
            skip_reason = f"halt_flag_set:{decision.reason or 'halted'}"
            log.warning("Job search prepare blocked by halt: %s", decision.reason)
            self.record_skipped(skip_reason, filename=_STATE_FILE)
            return ServiceResult(
                service="job_search",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=0.0,
                skip_reason=skip_reason,
            )

        # Preflight gate — fail fast on env issues before spending tokens.
        ok, errors = _run_preflight(self.data_dir, run_type="prepare")
        if not ok:
            failure_key = _failure_key(errors[0]) if errors else "unknown"
            skip = _preflight_skip_reason(errors[0] if errors else "")
            skip_reason = skip.render()
            log.warning(
                "Preflight failed for job_search prepare: %s (errors=%s)",
                failure_key,
                errors,
            )
            self.record_skipped(skip, filename=_STATE_FILE)
            return ServiceResult(
                service="job_search",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=0.0,
                skip_reason=skip_reason,
            )

        # Halt gate — continuation check between preflight (cheap env probe)
        # and the LLM-heavy department call. If the operator halted between
        # should_run() and here, skip cleanly without spending tokens.
        decision = halt_policy.check_continue("job-search")
        if decision.blocked:
            skip_reason = f"halt_flag_set:{decision.reason or 'halted'}"
            log.warning(
                "Job search prepare blocked by halt mid-run: %s", decision.reason
            )
            self.record_skipped(skip_reason, filename=_STATE_FILE)
            return ServiceResult(
                service="job_search",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=0.0,
                skip_reason=skip_reason,
            )

        from job_search.department import run_prepare

        now_tag = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"jobsearch-prepare-{now_tag}"
        deps_data_dir = str(self.data_dir)

        async def _build_and_run() -> TeamResult:
            deps = await BridgeDeps.for_cron(
                department="job_search",
                session_id=session_id,
                data_dir=deps_data_dir,
            )
            return await run_prepare(deps)

        try:
            result = asyncio.run(_build_and_run())
        except Exception as exc:
            self.record_failure(str(exc)[:500], filename=_STATE_FILE)
            log.exception("Job search prepare failed")
            raise

        duration_ms = int((time.monotonic() - t0) * 1000)

        if not result.success:
            error_msg = (result.error or "unknown")[:500]
            self.record_failure(error_msg, filename=_STATE_FILE)
            log.error("Job search prepare returned failure: %s", error_msg)
            if self.chat_id:
                self.deliver_message(
                    self.chat_id,
                    f"**Job Search — Prepare FAILED**\n{error_msg}",
                    source="job_search",
                )
            return ServiceResult(
                service="job_search",
                ok=False,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=float(result.total_cost_usd or 0.0),
                anomalies=("team_result_failure",),
                narration=f"Job search prepare FAILED: {error_msg[:160]}",
            )

        self.record_success(duration_ms, filename=_STATE_FILE)

        message = _format_prepare_result(result)
        if self.chat_id:
            self.deliver_message(self.chat_id, message, source="job_search")

        log.info("Job search prepare complete: cost=%.4f duration_ms=%d", result.total_cost_usd, duration_ms)
        return ServiceResult(
            service="job_search",
            ok=True,
            work_items=1,
            duration_ms=duration_ms,
            cost_usd=float(result.total_cost_usd or 0.0),
            narration="Job search prepare complete.",
        )


class JobSearchExecuteService(ServiceBase):
    """Execution cron — check Notion approvals, submit, send."""

    def __init__(
        self,
        data_dir: str | Path = DATA_DIR,
        chat_id: str = "",
        event_callback=None,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.chat_id = chat_id

    def should_run(self) -> bool:
        """Run between 10:00-20:00."""
        now = datetime.now()
        if now.hour < 10 or now.hour >= 20:
            return False
        return True

    def run(self) -> ServiceResult:
        """Execute the EXECUTE pipeline via DepartmentRegistry.

        Constructs BridgeDeps and calls department.run_execute, which routes
        through registry.route("job_search", intent, deps). Returns a
        :class:`ServiceResult` consumed by ``run_service_with_timeout`` for
        uniform observability — OK on success, SKIP for window/preflight
        no-ops, FAIL when the underlying TeamResult is unsuccessful.

        Sprint 02.09: ``preflight_check`` runs BEFORE ``BridgeDeps.for_cron``
        so missing secrets, bad config, missing gws CLI, or unreachable
        Notion fail fast as a SKIP (no consecutive_failures bump, no
        department invocation, no cost incurred).

        Sprint #1755: migrated from ``-> bool`` to ``-> ServiceResult`` to
        complete Plan 02 02.01's residual; aligns with ``funnel_post`` and
        the ``test_all_services_return_service_result_type`` regression
        guard.
        """
        t0 = time.monotonic()

        if not self.should_run():
            log.info("Job search execute skipped (outside 10:00-20:00 window)")
            self.record_skipped("outside 10:00-20:00 window", filename=_STATE_FILE)
            return ServiceResult(
                service="job_search_execute",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=0.0,
                skip_reason="outside_10_20_window",
            )

        # Halt gate (audit-2026-05-16.C.04, #2059) — entry check; see Prepare
        # service for rationale.
        halt_policy = _build_halt_policy(Path(self.data_dir))
        decision = halt_policy.check_start("job-search")
        if decision.blocked:
            skip_reason = f"halt_flag_set:{decision.reason or 'halted'}"
            log.warning("Job search execute blocked by halt: %s", decision.reason)
            self.record_skipped(skip_reason, filename=_STATE_FILE)
            return ServiceResult(
                service="job_search_execute",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=0.0,
                skip_reason=skip_reason,
            )

        # Preflight gate — fail fast on env issues before spending tokens.
        # run_type="execute" additionally checks for the gws CLI used to
        # send approved outreach emails.
        ok, errors = _run_preflight(self.data_dir, run_type="execute")
        if not ok:
            failure_key = _failure_key(errors[0]) if errors else "unknown"
            skip = _preflight_skip_reason(errors[0] if errors else "")
            skip_reason = skip.render()
            log.warning(
                "Preflight failed for job_search execute: %s (errors=%s)",
                failure_key,
                errors,
            )
            self.record_skipped(skip, filename=_STATE_FILE)
            return ServiceResult(
                service="job_search_execute",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=0.0,
                skip_reason=skip_reason,
            )

        # Halt gate — continuation check between preflight and LLM call.
        decision = halt_policy.check_continue("job-search")
        if decision.blocked:
            skip_reason = f"halt_flag_set:{decision.reason or 'halted'}"
            log.warning(
                "Job search execute blocked by halt mid-run: %s", decision.reason
            )
            self.record_skipped(skip_reason, filename=_STATE_FILE)
            return ServiceResult(
                service="job_search_execute",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=0.0,
                skip_reason=skip_reason,
            )

        from job_search.department import run_execute

        now_tag = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"jobsearch-execute-{now_tag}"
        deps_data_dir = str(self.data_dir)

        async def _build_and_run() -> TeamResult:
            deps = await BridgeDeps.for_cron(
                department="job_search",
                session_id=session_id,
                data_dir=deps_data_dir,
            )
            return await run_execute(deps)

        try:
            result = asyncio.run(_build_and_run())
        except Exception as exc:
            self.record_failure(str(exc)[:500], filename=_STATE_FILE)
            log.exception("Job search execute failed")
            raise

        duration_ms = int((time.monotonic() - t0) * 1000)

        if not result.success:
            error_msg = (result.error or "unknown")[:500]
            self.record_failure(error_msg, filename=_STATE_FILE)
            log.error("Job search execute returned failure: %s", error_msg)
            return ServiceResult(
                service="job_search_execute",
                ok=False,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=float(result.total_cost_usd or 0.0),
                anomalies=("team_result_failure",),
                narration=f"Job search execute FAILED: {error_msg[:160]}",
            )

        self.record_success(duration_ms, filename=_STATE_FILE)

        if self.chat_id:
            message = _format_execute_result(result)
            self.deliver_message(self.chat_id, message, source="job_search_execute")

        log.info("Job search execute complete: cost=%.4f duration_ms=%d", result.total_cost_usd, duration_ms)
        return ServiceResult(
            service="job_search_execute",
            ok=True,
            work_items=1,
            duration_ms=duration_ms,
            cost_usd=float(result.total_cost_usd or 0.0),
            narration="Job search execute complete.",
        )


# Keep backward compat alias
JobSearchService = JobSearchPrepareService


def _format_prepare_result(result: TeamResult) -> str:
    """Format a TeamResult from the PREPARE pipeline as a Discord message."""
    lines = ["**Job Search — Prepare Report**"]
    output = result.manager_output or ""
    if output:
        # Take first 800 chars of director output
        lines.append(output[:800])
    if result.total_cost_usd:
        lines.append(f"Cost: ${result.total_cost_usd:.4f}")
    return "\n".join(lines)


def _format_execute_result(result: TeamResult) -> str:
    """Format a TeamResult from the EXECUTE pipeline as a Discord message."""
    lines = ["**Job Search — Execute Report**"]
    output = result.manager_output or ""
    if output:
        lines.append(output[:800])
    if result.total_cost_usd:
        lines.append(f"Cost: ${result.total_cost_usd:.4f}")
    return "\n".join(lines)
