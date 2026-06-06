"""Neutral DTO module for job-search ↔ teams contract boundary.

Sprint P5.1 (2026-05-11 harness audit). Breaks the circular import chain:

    job_search.canary
      → job_search.funnel
        → teams.job_search._types   (DTOs lived here historically)
          → teams.__init__
            → teams._factory
              → teams._tool_registry
                → teams.tools._job_search
                  → job_search.quality_wiring  (circular)

The fix: shared DTOs live in `agent/job_search/contracts.py` — the
`job_search` package leaf, with no `teams.*` imports — so `funnel.py`
can pull them in without re-entering `teams.__init__`. The legacy
`teams.job_search._types` module re-exports these symbols so existing
import sites keep working without churn.

D5.8 — Funnel report types (originally in `teams.job_search._types`).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FunnelBucket:
    """One aggregated row: (board, ats, submit_step) cross-product."""

    board: str
    ats: str          # "" if unknown
    submit_step: str  # SubmitStep value or "unknown"
    submitted: int = 0
    blocked: int = 0
    requires_email_verify: int = 0
    requires_login: int = 0
    error: int = 0

    @property
    def attempts_total(self) -> int:
        return (
            self.submitted
            + self.blocked
            + self.requires_email_verify
            + self.requires_login
            + self.error
        )

    @property
    def submission_rate(self) -> float:
        return self.submitted / self.attempts_total if self.attempts_total else 0.0


@dataclass(frozen=True)
class FunnelReport:
    """Aggregator output for one time window."""

    window_start_iso: str
    window_end_iso: str
    window_label: str
    buckets: tuple[FunnelBucket, ...]
    total_attempts: int
    total_submitted: int
    total_blocked: int
    total_requires_email_verify: int
    total_requires_login: int
    total_error: int

    @property
    def overall_submission_rate(self) -> float:
        return self.total_submitted / self.total_attempts if self.total_attempts else 0.0
