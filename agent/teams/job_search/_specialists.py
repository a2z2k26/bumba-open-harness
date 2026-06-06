"""Zone 4 job-search specialist implementations.

D5.3 — AcquireAndPrepareSpecialist wraps the existing JobSearchAgent.prepare()
call. No logic moves in this sprint. The structured input/output contract
and per-listing JSONL emission are the deliverables.

D5.4 — OutreachExecuteSpecialist wraps JobSearchAgent.execute() with
structured types and per-message JSONL progress.
D5.5 — BrowserUseSpecialist — vision-driven form submission via Playwright MCP.
D5.6 — EmailVerificationSpecialist — narrow-scoped Gmail extraction via gws CLI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import datetime

from ._types import (
    AcquireInput,
    AcquireOutput,
    BrowserInput,
    BrowserOutput,
    BrowserStatus,
    ExecuteInput,
    ExecuteOutput,
    PreparedListing,
    SentMessage,
    SkippedMessage,
    SubmitStep,
    VerifyInput,
    VerifyOutput,
    VerifyStatus,
)

log = logging.getLogger(__name__)

# Per-run conversation log lives at data/teams/job_search/conversations/<run_id>.jsonl
# on the runtime host. Tests override via _CONVO_LOG_BASE_DIR.
_CONVO_LOG_BASE_DIR: Path | None = None


def _default_data_root() -> Path:
    """Resolve the data dir via the canonical helper (#1501 F4)."""
    from bridge.paths import data_root
    return data_root()


def _conversation_log_path(run_id: str, base_dir: Path | None = None) -> Path:
    root = base_dir or _CONVO_LOG_BASE_DIR or _default_data_root()
    return root / "teams" / "job_search" / "conversations" / f"{run_id}.jsonl"


def _append_progress(run_id: str, payload: dict, base_dir: Path | None = None) -> None:
    """Append one JSONL line to the per-run conversation log. Best-effort."""
    try:
        path = _conversation_log_path(run_id, base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": time.time(), "run_id": run_id, **payload})
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # pragma: no cover
        log.debug("job_search progress log failed: %s", exc)


class AcquireAndPrepareSpecialist:
    """PREPARE-phase specialist — wraps JobSearchAgent.prepare().

    D5.3: delegation seam only. All business logic remains in
    ``job_search.agent.JobSearchAgent``. This class provides the
    structured contract and per-listing JSONL audit trail that the
    Zone 4 chief and D5.8 funnel logger consume.

    D5.3+ sprints will progressively migrate logic here. Until then,
    this class is a thin adapter.
    """

    def __init__(self, *, log_base_dir: Path | None = None) -> None:
        self._log_base_dir = log_base_dir

    async def run(self, acquire_input: AcquireInput) -> AcquireOutput:
        """Execute the PREPARE phase and return a structured result.

        Delegates to ``JobSearchAgent.prepare()``. Emits one JSONL line
        per prepared listing (status=staged_in_notion) and one summary
        line at the end of the run.
        """
        run_id = acquire_input.run_id

        _append_progress(run_id, {
            "event": "acquire_started",
            "board_filter": list(acquire_input.board_filter),
            "rubric_threshold": acquire_input.rubric_threshold,
            "dry_run": acquire_input.dry_run,
        }, self._log_base_dir)

        raw_result: dict[str, Any] = {}
        errors: list[str] = []

        try:
            from job_search.agent import JobSearchAgent

            agent = JobSearchAgent(
                rubric_gate_enabled=True,
                rubric_threshold=acquire_input.rubric_threshold,
            )
            raw_result = await agent.prepare()
            errors = list(raw_result.get("errors") or [])
        except Exception as exc:
            log.error("AcquireAndPrepareSpecialist.run failed: %s", exc, exc_info=True)
            errors = [str(exc)]

        phases = raw_result.get("phases") or {}
        staging = phases.get("staging") or {}
        research = phases.get("research") or {}
        rubric_gate = phases.get("rubric_gate") or {}

        # Emit per-listing progress from staging results.
        staged_listings: list[PreparedListing] = []
        for page in staging.get("staged_pages") or []:
            listing_id = page.get("fingerprint") or page.get("listing_id") or ""
            pl = PreparedListing(
                listing_id=listing_id,
                board=page.get("board") or "",
                company=page.get("company") or "",
                title=page.get("title") or "",
                url=page.get("url") or "",
                ats_kind=page.get("ats") or None,
                rubric_grade=page.get("rubric_grade") or "",
                cover_letter_chars=page.get("cover_letter_chars") or 0,
                notion_page_id=page.get("notion_page_id") or "",
                cost_usd=float(page.get("cost_usd") or 0.0),
            )
            staged_listings.append(pl)
            _append_progress(run_id, {
                "event": "listing_progress",
                "listing_id": listing_id,
                "status": "staged_in_notion",
                "board": pl.board,
                "company": pl.company,
                "title": pl.title,
                "rubric_grade": pl.rubric_grade,
            }, self._log_base_dir)

        total_cost = float(
            sum(pl.cost_usd for pl in staged_listings)
        )
        skipped = int(research.get("skipped_dup", 0)) + int(research.get("skipped_excluded", 0))

        output = AcquireOutput(
            run_id=run_id,
            run_at=raw_result.get("run_at") or "",
            prepared_listings=tuple(staged_listings),
            skipped_count=skipped,
            board_health_snapshot={},
            total_cost_usd=total_cost,
            errors=tuple(errors),
            raw_phases=phases,
        )

        _append_progress(run_id, {
            "event": "acquire_completed",
            "prepared": len(staged_listings),
            "skipped": skipped,
            "rubric_passed": rubric_gate.get("passed", 0),
            "rubric_filtered": rubric_gate.get("filtered", 0),
            "total_cost_usd": total_cost,
            "errors": errors,
        }, self._log_base_dir)

        return output


class OutreachExecuteSpecialist:
    """EXECUTE-phase specialist — wraps JobSearchAgent.execute().

    D5.4: delegation seam only. Business logic remains in
    ``job_search.agent.JobSearchAgent``. Per-item SentMessage /
    SkippedMessage decomposition is deferred to future sprints; this sprint
    provides the structured contract and JSONL audit trail.
    """

    def __init__(self, *, log_base_dir: Path | None = None) -> None:
        self._log_base_dir = log_base_dir

    async def run(self, execute_input: ExecuteInput) -> ExecuteOutput:
        """Execute the EXECUTE phase and return a structured result.

        Delegates to ``JobSearchAgent.execute()``. Emits ``execute_started``
        and ``execute_completed`` JSONL events. ``errors`` in the raw result
        may be an int (count) or a list — both are normalised to a tuple of
        strings.
        """
        run_id = execute_input.run_id
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

        _append_progress(run_id, {
            "event": "execute_started",
            "dry_run": execute_input.dry_run,
            "max_sends": execute_input.max_sends,
        }, self._log_base_dir)

        raw_result: dict[str, Any] = {}
        errors: list[str] = []

        try:
            from job_search.agent import JobSearchAgent

            agent = JobSearchAgent()
            raw_result = await agent.execute()

            # Normalise errors field — legacy execute() returns an int count.
            errors_raw = raw_result.get("errors")
            if isinstance(errors_raw, int):
                error_count = errors_raw
                errors = [f"{error_count} execution error(s)"] if error_count else []
            elif isinstance(errors_raw, list):
                errors = [str(e) for e in errors_raw]
            else:
                errors = []
        except Exception as exc:
            log.error("OutreachExecuteSpecialist.run failed: %s", exc, exc_info=True)
            errors = [str(exc)]

        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

        # Build summary-level SentMessage stubs from the raw outreach_sent count.
        # Per-item decomposition requires deeper execute_approved instrumentation
        # and is deferred to a future sprint.
        outreach_sent_count = int(raw_result.get("outreach_sent") or 0)
        sent_stubs: list[SentMessage] = []
        for i in range(outreach_sent_count):
            sent_stubs.append(SentMessage(
                message_id=f"summary-{run_id}-{i}",
                notion_page_id="",
                recipient="",
                subject="",
                sent_at_utc=finished_at,
            ))

        # Build summary-level SkippedMessage stubs from approved_count delta.
        approved_count = int(raw_result.get("approved_count") or 0)
        skipped_count = max(0, approved_count - outreach_sent_count)
        skipped_stubs: list[SkippedMessage] = []
        for _ in range(skipped_count):
            skipped_stubs.append(SkippedMessage(
                notion_page_id="",
                reason="skipped_in_execute",
            ))

        output = ExecuteOutput(
            run_id=run_id,
            sent=tuple(sent_stubs),
            skipped=tuple(skipped_stubs),
            failed=(),
            total_cost_usd=0.0,
            started_at_utc=started_at,
            finished_at_utc=finished_at,
            errors=tuple(errors),
            raw_phases=raw_result.get("phases") or {},
            run_at=raw_result.get("run_at") or "",
        )

        _append_progress(run_id, {
            "event": "execute_completed",
            "outreach_sent": outreach_sent_count,
            "skipped": skipped_count,
            "errors": errors,
        }, self._log_base_dir)

        return output


_SECRETS_PATH = Path("/opt/bumba-harness/data/.secrets")


def _load_oauth_token(secrets_path: Path = _SECRETS_PATH) -> str:
    """Load the Claude OAuth token from the .secrets file."""
    if not secrets_path.exists():
        return ""
    for line in secrets_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("claude_oauth_token="):
            return line.split("=", 1)[1].strip()
    return ""


def _find_claude_binary() -> str:
    """Locate the claude CLI binary."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("Claude Code binary not found")


def _extract_last_text(stdout: str) -> str:
    """Extract the last meaningful text block from stream-json subprocess output.

    Mirrors the same function in job_search/ats/applicant.py — the stream-json
    format emits ``type=assistant`` blocks with content arrays and a final
    ``type=result`` block; we prefer the result block if present, otherwise the
    last assistant text block.
    """
    result_text = ""
    text_parts: list[str] = []

    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        if data.get("type") == "assistant":
            message = data.get("message", {})
            if isinstance(message, dict):
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
        elif data.get("type") == "result":
            result_text = data.get("result", "")

    return result_text or (text_parts[-1] if text_parts else "")


def _parse_browser_result(result_text: str, dry_run: bool) -> tuple[BrowserStatus, SubmitStep, str, str]:
    """Parse the JSON payload emitted by the BrowserUseSpecialist subprocess.

    Returns (status, last_step, blocker_reason, confirmation_text).
    Falls back to BLOCKED/NAVIGATING on parse failure.
    """
    # Scan all lines for a JSON object with a "status" key
    for line in result_text.splitlines():
        line = line.strip()
        if line.startswith("```"):
            continue
        if line.startswith("{"):
            try:
                data = json.loads(line)
                if "status" not in data:
                    continue
                raw_status = str(data.get("status", "")).lower()
                raw_step = str(data.get("last_step", "navigating")).lower()

                try:
                    status = BrowserStatus(raw_status)
                except ValueError:
                    status = BrowserStatus.BLOCKED

                try:
                    last_step = SubmitStep(raw_step)
                except ValueError:
                    last_step = SubmitStep.NAVIGATING

                return (
                    status,
                    last_step,
                    str(data.get("blocker_reason", "")),
                    str(data.get("confirmation_text", "")),
                )
            except (json.JSONDecodeError, AttributeError):
                pass

    # No parseable JSON — treat as a blocker
    return BrowserStatus.BLOCKED, SubmitStep.NAVIGATING, "no_parseable_result", ""


def _build_browser_prompt(browser_input: BrowserInput) -> str:
    """Build the system prompt for the BrowserUseSpecialist subprocess.

    The subprocess Claude uses Playwright MCP tools (vision-capable) rather than
    blind playwright-cli bash commands. It takes a screenshot to see the page,
    acts, then screenshots to verify — the vision loop that raises completion rate
    above the ~2% baseline of the blind approach.
    """
    dry_run_instruction = ""
    if browser_input.dry_run:
        dry_run_instruction = (
            "\n## DRY RUN MODE\n"
            "This is a dry run. Fill all form fields completely but DO NOT click the "
            "final Submit / Apply / Send button. When all fields are filled and you "
            "would normally click submit, stop and output:\n"
            '  {"status": "submitted", "last_step": "submit_click", '
            '"blocker_reason": "", "confirmation_text": "dry_run_would_submit", '
            '"dry_run": true}\n'
            "Stopping before the submit click is a SUCCESS in dry-run mode.\n"
        )

    storage_state_instruction = ""
    if browser_input.storage_state_path:
        storage_state_instruction = (
            "\n## LOGGED-IN SESSION AVAILABLE (D5.7)\n"
            f"A captured browser profile is available at: {browser_input.storage_state_path}\n"
            "BEFORE navigating, load the storage state into Playwright using "
            "`mcp__playwright__set_browser_context` (or equivalent — call with "
            f'`storageStatePath: "{browser_input.storage_state_path}"`). '
            "This restores cookies, localStorage, and tokens from the operator's "
            "earlier login. After loading, prefer the logged-in flow:\n"
            "  - If you land on a logged-in page (avatar, account menu, profile name visible): "
            "proceed normally; the form may have prefilled fields\n"
            "  - If the load fails or the page still shows a login wall: "
            "report `requires_login` (the profile may have expired)\n"
        )

    return f"""You are a job application automation agent. Your task is to navigate to a job listing URL and fill out the application form using Playwright MCP tools.

## YOUR TOOLS
Use ONLY these Playwright MCP tools — do NOT use Bash or playwright-cli commands:
- `mcp__playwright__navigate` — navigate to a URL
- `mcp__playwright__screenshot` — take a screenshot to see the current page state
- `mcp__playwright__click` — click an element by selector or coordinates
- `mcp__playwright__fill` — fill a text input field
- `mcp__playwright__select_option` — select a dropdown option

## VISION LOOP — mandatory pattern
1. Take a screenshot to see the page
2. Identify what action to take based on what you see
3. Take the action
4. Take another screenshot to verify the result
5. Repeat until done

Never act without seeing the page first. Never skip the verification screenshot.

## TARGET APPLICATION
- URL: {browser_input.url}
- Listing ID: {browser_input.listing_id}
{storage_state_instruction}
## COVER LETTER
{browser_input.cover_letter[:2000]}

## EXECUTION STEPS
1. Navigate to the URL and take a screenshot
2. Find and click the Apply / Apply Now button
3. Take a screenshot to see the form
4. Fill all visible form fields (name, email, phone, resume upload if applicable, cover letter)
5. If multi-step, continue to next page and fill remaining fields
6. Take a final screenshot to verify all fields are filled
{dry_run_instruction if dry_run_instruction else "7. Click Submit / Apply / Send button"}
{"7" if not dry_run_instruction else "8"}. Take a screenshot to confirm submission

## BLOCKER DETECTION — stop immediately and report if:
- CAPTCHA or bot challenge detected → {{"status": "blocked", "last_step": "captcha_detect", "blocker_reason": "captcha", "confirmation_text": ""}}
- Login / account creation wall → {{"status": "requires_login", "last_step": "navigating", "blocker_reason": "login_required", "confirmation_text": ""}}
- Email verification required → {{"status": "requires_email_verify", "last_step": "post_submit_confirm", "blocker_reason": "email_verify_required", "confirmation_text": ""}}
- Cloudflare challenge → {{"status": "blocked", "last_step": "navigating", "blocker_reason": "cloudflare_blocked", "confirmation_text": ""}}
- No form found after 3 attempts → {{"status": "blocked", "last_step": "navigating", "blocker_reason": "no_form_found", "confirmation_text": ""}}

## FINAL OUTPUT
Your last message MUST be a JSON object on a single line:
{{"status": "<submitted|blocked|requires_email_verify|requires_login>", "last_step": "<navigating|form_fill|file_upload|captcha_detect|submit_click|post_submit_confirm>", "blocker_reason": "<empty string or reason>", "confirmation_text": "<ATS confirmation text or empty string>"}}

The application is only successful when status is "submitted"."""


class BrowserUseSpecialist:
    """Vision-driven job application specialist (D5.5).

    Spawns a ``claude`` CLI subprocess authenticated via ``CLAUDE_CODE_OAUTH_TOKEN``
    (Max plan flat subscription — no per-token billing). The subprocess uses
    Playwright MCP tools (screenshot → act → screenshot) instead of the blind
    playwright-cli bash commands used by the legacy ``apply_to_job`` function.
    This is the seam that enables a vision upgrade: Claude sees the page before
    acting, which is why the legacy approach lands at ~2% completion rate.

    Ships with ``dry_run=True`` by default. Real submissions are a 1.1 milestone.
    Feature-flagged via ``browser_use_specialist_enabled`` in BridgeConfig.
    """

    def __init__(
        self,
        *,
        secrets_path: Path = _SECRETS_PATH,
        log_base_dir: Path | None = None,
    ) -> None:
        self._secrets_path = secrets_path
        self._log_base_dir = log_base_dir

    @staticmethod
    def _is_enabled() -> bool:
        """Check the feature flag — defaults to False if BridgeConfig is unavailable."""
        try:
            from bridge.config import load_config
            config = load_config()
            return bool(getattr(config, "browser_use_specialist_enabled", False))
        except Exception:
            return False

    async def run(self, browser_input: BrowserInput) -> BrowserOutput:
        """Fill a job application form using Claude + Playwright MCP (vision loop).

        Returns a ``BrowserOutput`` with status, last step, and any blocker detail.
        If ``dry_run=True``, the subprocess is instructed to stop before the final
        submit click; the returned status is still ``SUBMITTED`` to signal
        "would have submitted".
        """
        run_id = browser_input.run_id
        listing_id = browser_input.listing_id

        _append_progress(run_id, {
            "event": "browser_started",
            "listing_id": listing_id,
            "url": browser_input.url,
            "dry_run": browser_input.dry_run,
            "max_turns": browser_input.max_turns,
        }, self._log_base_dir)

        # Locate the binary before spawning so the error is surfaced cleanly.
        try:
            binary = _find_claude_binary()
        except FileNotFoundError as exc:
            _append_progress(run_id, {
                "event": "browser_completed",
                "listing_id": listing_id,
                "status": BrowserStatus.ERROR.value,
                "error_detail": str(exc),
            }, self._log_base_dir)
            return BrowserOutput(
                listing_id=listing_id,
                status=BrowserStatus.ERROR,
                last_step=SubmitStep.NAVIGATING,
                turns_used=0,
                error_detail=str(exc),
                dry_run=browser_input.dry_run,
            )

        cmd = [
            binary,
            "-p",
            "--verbose",
            "--output-format", "stream-json",
            "--max-turns", str(browser_input.max_turns),
            "--dangerously-skip-permissions",
        ]

        env = __import__("os").environ.copy()
        token = _load_oauth_token(self._secrets_path)
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        env["PATH"] = "/usr/local/bin:/opt/homebrew/bin:" + env.get("PATH", "")

        prompt = _build_browser_prompt(browser_input)
        turns_used = 0

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
            )

            stdout_bytes, _stderr_bytes = await proc.communicate(input=prompt.encode())
            stdout = stdout_bytes.decode("utf-8", errors="replace")

            # Estimate turns from the number of assistant blocks in the stream.
            turns_used = stdout.count('"type": "assistant"')

            _append_progress(run_id, {
                "event": "browser_step",
                "listing_id": listing_id,
                "turns_used": turns_used,
                "returncode": proc.returncode,
            }, self._log_base_dir)

            if proc.returncode != 0:
                stderr = _stderr_bytes.decode("utf-8", errors="replace")
                error_detail = f"Claude exit {proc.returncode}: {stderr[:300]}"
                _append_progress(run_id, {
                    "event": "browser_completed",
                    "listing_id": listing_id,
                    "status": BrowserStatus.ERROR.value,
                    "error_detail": error_detail,
                }, self._log_base_dir)
                return BrowserOutput(
                    listing_id=listing_id,
                    status=BrowserStatus.ERROR,
                    last_step=SubmitStep.NAVIGATING,
                    turns_used=turns_used,
                    error_detail=error_detail,
                    dry_run=browser_input.dry_run,
                )

            result_text = _extract_last_text(stdout)
            status, last_step, blocker_reason, confirmation_text = _parse_browser_result(
                result_text, browser_input.dry_run
            )

            _append_progress(run_id, {
                "event": "browser_completed",
                "listing_id": listing_id,
                "status": status.value,
                "last_step": last_step.value,
                "blocker_reason": blocker_reason,
                "turns_used": turns_used,
                "dry_run": browser_input.dry_run,
            }, self._log_base_dir)

            return BrowserOutput(
                listing_id=listing_id,
                status=status,
                last_step=last_step,
                turns_used=turns_used,
                blocker_reason=blocker_reason,
                confirmation_text=confirmation_text,
                dry_run=browser_input.dry_run,
            )

        except Exception as exc:
            log.error(
                "BrowserUseSpecialist.run failed for listing %s: %s",
                listing_id, exc, exc_info=True,
            )
            error_detail = f"Error: {exc}"
            _append_progress(run_id, {
                "event": "browser_completed",
                "listing_id": listing_id,
                "status": BrowserStatus.ERROR.value,
                "error_detail": error_detail,
            }, self._log_base_dir)
            return BrowserOutput(
                listing_id=listing_id,
                status=BrowserStatus.ERROR,
                last_step=SubmitStep.NAVIGATING,
                turns_used=turns_used,
                error_detail=error_detail,
                dry_run=browser_input.dry_run,
            )


# ---------------------------------------------------------------------------
# Heuristic extraction patterns (most-specific first)
# ---------------------------------------------------------------------------

HEURISTIC_PATTERNS: list[str] = [
    r'(?:code|Code|CODE)[:\s]+([A-Z0-9]{4,8})',
    r'(?:verification|verify)[:\s]+([A-Z0-9]{4,8})',
    r'\b(\d{6})\b',
    r'\b([A-Z0-9]{6,8})\b',
]

# Per-attempt log for email verify — separate from per-run conversation log.
_VERIFY_LOG_BASE_DIR: Path | None = None


def _verify_log_path(base_dir: Path | None = None) -> Path:
    root = base_dir or _VERIFY_LOG_BASE_DIR or _default_data_root()
    return root / "teams" / "job_search" / "email-verify-attempts.jsonl"


def _append_verify_attempt(
    listing_id: str,
    sender_domain: str,
    after_date: str,
    attempt_num: int,
    found: bool,
    base_dir: Path | None = None,
) -> None:
    """Best-effort JSONL append. Redacts timestamp to date only."""
    try:
        path = _verify_log_path(base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({
            "ts": time.time(),
            "listing_id": listing_id,
            "sender_domain": sender_domain,
            "after_date": after_date,
            "attempt_num": attempt_num,
            "found": found,
        })
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # pragma: no cover
        log.debug("email verify attempt log failed: %s", exc)


def _extract_code_heuristic(body: str) -> str:
    """Try heuristic patterns against email body. Return first match or ''."""
    for pattern in HEURISTIC_PATTERNS:
        match = re.search(pattern, body)
        if match:
            return match.group(1)
    return ""


def _extract_code_llm(body: str) -> str:
    """Shell out to claude -p for code extraction. Returns code or ''."""
    prompt = (
        "Extract the verification code from this email body.\n"
        "Return ONLY the code as a single token, nothing else.\n"
        "If you cannot find a verification code, return the literal string \"NOT_FOUND\".\n\n"
        f"Email body:\n{body[:2000]}"
    )
    try:
        result = subprocess.run(
            ["claude", "-p", "--max-turns", "2", prompt],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        if output and output != "NOT_FOUND":
            return output
    except Exception as exc:
        log.debug("LLM fallback subprocess failed: %s", exc)
    return ""


class EmailVerificationSpecialist:
    """Email verification code extractor — narrow-scoped Gmail query via gws CLI.

    Narrow-permission discipline: every query carries from: + after: filters.
    Refuses to run without both. Pattern mirrors PR #1165.
    """

    def __init__(self, *, log_base_dir: Path | None = None) -> None:
        self._log_base_dir = log_base_dir

    async def run(self, verify_input: VerifyInput) -> VerifyOutput:
        """Poll Gmail for a verification email and extract the code.

        Returns VerifyOutput with status CODE_EXTRACTED on success,
        NOT_YET on timeout, or EXTRACTION_FAILED if gws is missing or
        code could not be extracted from a found message.
        """
        listing_id = verify_input.listing_id

        if shutil.which("gws") is None:
            return VerifyOutput(
                listing_id=listing_id,
                status=VerifyStatus.EXTRACTION_FAILED,
                error_detail="gws CLI not found",
            )

        after_date = verify_input.after_timestamp_iso[:10]
        query = (
            f"from:{verify_input.sender_domain} "
            f"after:{after_date}"
        )

        elapsed = 0.0
        attempt = 0

        while elapsed <= verify_input.poll_max_seconds:
            attempt += 1

            email_body = self._query_gmail(query)
            found = email_body is not None

            _append_verify_attempt(
                listing_id=listing_id,
                sender_domain=verify_input.sender_domain,
                after_date=after_date,
                attempt_num=attempt,
                found=found,
                base_dir=self._log_base_dir,
            )

            if email_body is not None:
                # Heuristic extraction first
                code = _extract_code_heuristic(email_body)
                if code:
                    return VerifyOutput(
                        listing_id=listing_id,
                        status=VerifyStatus.CODE_EXTRACTED,
                        code=code,
                        extraction_method="heuristic",
                        attempts=attempt,
                    )

                # LLM fallback
                if verify_input.llm_fallback_enabled:
                    code = _extract_code_llm(email_body)
                    if code:
                        return VerifyOutput(
                            listing_id=listing_id,
                            status=VerifyStatus.CODE_EXTRACTED,
                            code=code,
                            extraction_method="llm_fallback",
                            attempts=attempt,
                        )

                return VerifyOutput(
                    listing_id=listing_id,
                    status=VerifyStatus.EXTRACTION_FAILED,
                    attempts=attempt,
                    error_detail="email found but code extraction failed",
                )

            # Not found yet — wait before next poll
            await asyncio.sleep(verify_input.poll_interval_seconds)
            elapsed += verify_input.poll_interval_seconds

        return VerifyOutput(
            listing_id=listing_id,
            status=VerifyStatus.NOT_YET,
            attempts=attempt,
        )

    def _query_gmail(self, query: str) -> str | None:
        """Run gws gmail search. Returns email body string or None if not found."""
        try:
            result = subprocess.run(
                ["gws", "gmail", "search", "--query", query, "--format", "json", "--limit", "1"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
            # Handle list or single-message response shapes
            messages = data if isinstance(data, list) else data.get("messages") or []
            if not messages:
                return None
            msg = messages[0]
            # Try common body field names
            return (
                msg.get("body")
                or msg.get("snippet")
                or msg.get("text")
                or ""
            ) or None
        except Exception as exc:
            log.debug("gws gmail search failed: %s", exc)
            return None
