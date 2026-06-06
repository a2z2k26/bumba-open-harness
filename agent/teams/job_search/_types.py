"""Structured input/output contracts for the job-search Zone 4 team.

D5.3 — AcquireInput / AcquireOutput / PreparedListing are the contracts
for the PREPARE phase. All dataclasses are frozen per the immutability rule.
D5.4 — SentMessage / SkippedMessage / FailedMessage + richer ExecuteOutput.
D5.5 — BrowserStatus / SubmitStep / BrowserInput / BrowserOutput for the
        vision-driven Playwright MCP application loop.
D5.6 — VerifyInput / VerifyOutput / VerifyStatus for email verification wall.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class AcquireInput:
    """PREPARE-phase input the chief constructs once per cron tick.

    All fields are optional so the cron's "just run today's sweep" case
    maps to ``AcquireInput(run_id=<uuid>)`` with defaults. Debug runs
    can scope down via board_filter or max_listings.
    """

    run_id: str
    board_filter: tuple[str, ...] = ()
    max_listings: Optional[int] = None
    rubric_threshold: str = "B"
    dry_run: bool = False


@dataclass(frozen=True)
class PreparedListing:
    """One listing that passed the rubric gate and was staged in Notion."""

    listing_id: str
    board: str
    company: str
    title: str
    url: str
    ats_kind: Optional[str]
    rubric_grade: str
    cover_letter_chars: int
    notion_page_id: str
    cost_usd: float


@dataclass(frozen=True)
class AcquireOutput:
    """Structured result of one PREPARE cron cycle.

    ``raw_phases`` carries the original phase-result dict from
    ``JobSearchAgent.prepare()`` so downstream consumers (D5.8 funnel
    logger, cost tracker) can read it without a re-format pass.
    """

    run_id: str
    run_at: str
    prepared_listings: tuple[PreparedListing, ...] = field(default_factory=tuple)
    skipped_count: int = 0
    board_health_snapshot: dict = field(default_factory=dict)
    total_cost_usd: float = 0.0
    errors: tuple[str, ...] = field(default_factory=tuple)
    raw_phases: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExecuteInput:
    """EXECUTE-phase input."""

    run_id: str
    dry_run: bool = False
    max_sends: Optional[int] = None


@dataclass(frozen=True)
class SentMessage:
    """One outreach email successfully sent."""

    message_id: str
    notion_page_id: str
    recipient: str
    subject: str
    sent_at_utc: str
    cost_usd: float = 0.0


@dataclass(frozen=True)
class SkippedMessage:
    """One outreach candidate skipped (e.g. already sent, not approved)."""

    notion_page_id: str
    reason: str


@dataclass(frozen=True)
class FailedMessage:
    """One outreach attempt that errored."""

    notion_page_id: str
    recipient: str
    error_kind: str
    error_detail: str


@dataclass(frozen=True)
class ExecuteOutput:
    """Structured result of one EXECUTE cron cycle."""

    run_id: str
    sent: tuple[SentMessage, ...] = field(default_factory=tuple)
    skipped: tuple[SkippedMessage, ...] = field(default_factory=tuple)
    failed: tuple[FailedMessage, ...] = field(default_factory=tuple)
    total_cost_usd: float = 0.0
    started_at_utc: str = ""
    finished_at_utc: str = ""
    errors: tuple[str, ...] = field(default_factory=tuple)
    raw_phases: dict = field(default_factory=dict)
    # kept for backward compat
    run_at: str = ""


# ---------------------------------------------------------------------------
# D5.5 — Browser automation types
# ---------------------------------------------------------------------------

class BrowserStatus(str, Enum):
    SUBMITTED = "submitted"
    BLOCKED = "blocked"                       # captcha / unfillable / max_turns exceeded
    REQUIRES_EMAIL_VERIFY = "requires_email_verify"
    REQUIRES_LOGIN = "requires_login"
    ERROR = "error"                           # our-side failure only


class SubmitStep(str, Enum):
    NAVIGATING = "navigating"
    FORM_FILL = "form_fill"
    FILE_UPLOAD = "file_upload"
    CAPTCHA_DETECT = "captcha_detect"
    SUBMIT_CLICK = "submit_click"
    POST_SUBMIT_CONFIRM = "post_submit_confirm"


@dataclass(frozen=True)
class BrowserInput:
    listing_id: str
    url: str
    cover_letter: str
    run_id: str
    dry_run: bool = True          # default True — shadow mode until operator flips
    max_turns: int = 40           # turn cap replaces dollar cost cap (Max plan)
    storage_state_path: Optional[str] = None   # per-board browser profile (D5.7)


@dataclass(frozen=True)
class BrowserOutput:
    listing_id: str
    status: BrowserStatus
    last_step: SubmitStep
    turns_used: int
    blocker_reason: str = ""      # populated when status=BLOCKED
    confirmation_text: str = ""   # ATS confirmation message if status=SUBMITTED
    dry_run: bool = True
    error_detail: str = ""


# ---------------------------------------------------------------------------
# D5.6 — Email verification types
# ---------------------------------------------------------------------------

MAX_VERIFY_WINDOW_AGE_SECONDS = 600  # 10 minutes — sanity rail


class VerifyStatus(str, Enum):
    CODE_EXTRACTED = "code_extracted"
    NOT_YET = "not_yet"            # polled but no message landed in window
    EXTRACTION_FAILED = "extraction_failed"  # message landed, neither heuristic nor LLM extracted


@dataclass(frozen=True)
class VerifyInput:
    """Narrow-scoped Gmail extraction request.

    Refuses construction without both sender_domain and after_timestamp_iso
    no older than 10 minutes. Narrow-permission discipline enforced at type
    boundary.
    """

    listing_id: str
    sender_domain: str            # e.g. "@noreply.greenhouse.io" — REQUIRED
    after_timestamp_iso: str      # ISO-8601 UTC — REQUIRED
    poll_interval_seconds: int = 30
    poll_max_seconds: int = 300   # 5 min total
    llm_fallback_enabled: bool = True
    expected_code_pattern: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.sender_domain:
            raise ValueError(
                "VerifyInput.sender_domain is required (narrow-permission discipline)"
            )
        if not self.after_timestamp_iso:
            raise ValueError(
                "VerifyInput.after_timestamp_iso is required (narrow-permission discipline)"
            )
        try:
            ts = datetime.fromisoformat(
                self.after_timestamp_iso.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                f"VerifyInput.after_timestamp_iso not parseable: {exc}"
            ) from None
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > MAX_VERIFY_WINDOW_AGE_SECONDS:
            raise ValueError(
                f"VerifyInput.after_timestamp_iso is {age:.0f}s old; "
                f"max allowed is {MAX_VERIFY_WINDOW_AGE_SECONDS}s "
                f"(narrow-permission discipline)"
            )


@dataclass(frozen=True)
class VerifyOutput:
    listing_id: str
    status: VerifyStatus
    code: str = ""               # populated when status=CODE_EXTRACTED
    extraction_method: str = ""  # "heuristic" | "llm_fallback" | ""
    attempts: int = 0
    error_detail: str = ""


# ---------------------------------------------------------------------------
# D5.8 — Funnel report types
# ---------------------------------------------------------------------------
#
# P5.1 (2026-05-11): the FunnelBucket / FunnelReport DTOs were moved to
# `job_search.contracts` to break the job_search ↔ teams.job_search
# circular import chain. They are re-exported here so existing import
# sites (e.g. `from teams.job_search._types import FunnelBucket`) keep
# working — but new code should import from `job_search.contracts`
# directly.
from job_search.contracts import FunnelBucket, FunnelReport  # noqa: F401, E402
