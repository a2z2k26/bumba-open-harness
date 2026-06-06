"""ATS form fill orchestrator — uses Claude subprocess with Playwright MCP.

Navigates to ANY job listing URL, finds the apply button, fills the form,
and submits.  ATS-specific prompt hints are injected for known systems
(Greenhouse, Lever, Ashby) but the generic handler works for any career page.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from bridge.paths import data_root

from ..boards.base import JobListing
from ..criteria import Candidate
from .detector import detect_ats
from .greenhouse import GREENHOUSE_PROMPT
from .lever import LEVER_PROMPT
from .ashby import ASHBY_PROMPT
from .generic import GENERIC_PROMPT

log = logging.getLogger(__name__)

SECRETS_PATH = data_root() / ".secrets"
TIMEOUT_SECONDS = 60  # Default page-load timeout (reduced from 480s)
GREENHOUSE_TIMEOUT = 90  # Greenhouse JS is heavier; allow extra headroom
MAX_TURNS = 50

# Cloudflare-specific signals that only appear on actual CF challenge/block pages.
# Deliberately excludes bare "cloudflare" (appears in normal JSON keys) and
# "just a moment" / "ray id" (too generic). Uses only multi-word phrases unique
# to CF challenge pages or the explicit blocker token emitted by the agent prompt.
_CLOUDFLARE_SIGNALS: tuple[str, ...] = (
    "cf-browser-verification",
    "ddos protection by cloudflare",
    "checking if the site connection is secure",
    "enable javascript and cookies to continue",
    "cloudflare ray id",    # "Cloudflare Ray ID:" printed on challenge pages
    "cloudflare_blocked",   # Explicit blocker token from the agent prompt
    "captcha_blocked",      # Covers Cloudflare Turnstile / hCaptcha fallback
)

# Known label variants for "How did you hear about us?" custom field
_HOW_DID_YOU_HEAR_LABELS: tuple[str, ...] = (
    "how did you hear",
    "how did you find",
    "how did you learn",
    "where did you hear",
    "referral source",
    "how did you hear about us",
    "how did you hear about this role",
    "how did you hear about this job",
    "source",
)


@dataclass
class ApplicationResult:
    success: bool
    submitted: bool = False
    screenshot_path: str = ""
    notes: str = ""
    cloudflare_blocked: bool = False


ATS_PROMPTS: dict[str, str] = {
    "greenhouse": GREENHOUSE_PROMPT,
    "lever": LEVER_PROMPT,
    "ashby": ASHBY_PROMPT,
}


def _load_oauth_token(secrets_path: Path = SECRETS_PATH) -> str:
    if not secrets_path.exists():
        return ""
    for line in secrets_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("claude_oauth_token="):
            return line.split("=", 1)[1].strip()
    return ""


def _find_claude_binary() -> str:
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


def _resolve_timeout(ats_type: str, override: int | None = None) -> int:
    """Return the appropriate subprocess timeout for the given ATS type."""
    if override is not None:
        return override
    if ats_type == "greenhouse":
        return GREENHOUSE_TIMEOUT
    return TIMEOUT_SECONDS


def _build_fill_prompt(
    listing: JobListing,
    candidate: Candidate,
    cover_letter: str,
    ats_type: str,
) -> str:
    """Build the prompt for ATS form filling."""
    ats_specific = ATS_PROMPTS.get(ats_type, GENERIC_PROMPT)

    additional_links = ""
    if candidate.portfolio_links:
        additional_links = "\n".join(f"  - {link}" for link in candidate.portfolio_links)

    resume_path = candidate.resume_local_path or candidate.resume_url
    first_name = candidate.name.split()[0] if candidate.name else ""
    last_name = (
        " ".join(candidate.name.split()[1:])
        if candidate.name and len(candidate.name.split()) > 1
        else ""
    )

    return f"""You are a job application bot. Your ONLY job is to fill out and submit a job application form using playwright-cli commands via Bash. You must COMPLETE the submission — a partially filled form is a failure.

## CANDIDATE DATA (use these exact values)
- First Name: {first_name}
- Last Name: {last_name}
- Full Name: {candidate.name}
- Email: {candidate.email}
- Phone: {candidate.phone}
- LinkedIn: {candidate.linkedin_url}
- Portfolio: {candidate.portfolio_url}
- Additional Portfolio Links: {additional_links or "None"}
- Resume file: {resume_path}
- Skills: {', '.join(candidate.skills)}

## COVER LETTER (paste into cover letter field if present)
{cover_letter[:2000]}

## TARGET
- URL: {listing.url}
- Job: {listing.title} @ {listing.company}

{ats_specific}

## RULES — READ CAREFULLY

1. **NEVER NARRATE.** Do not write "Let me...", "I'll now...", "I can see...". Every response must contain Bash commands. If you write a response with zero Bash calls, you have wasted a turn.

2. **BATCH COMMANDS.** Run multiple playwright-cli commands in a single Bash call using `&&`:
   ```
   playwright-cli fill ref1 "value1" && playwright-cli fill ref2 "value2" && playwright-cli select ref3 "value3"
   ```

3. **ALWAYS SNAPSHOT AFTER NAVIGATION.** After open, click, goto, or any page change, run `playwright-cli snapshot` to get fresh element refs. Old refs are invalid after navigation.

4. **RESUME UPLOAD.** Use: `playwright-cli upload "{resume_path}"` — this uploads to the currently focused file input. If there's a file input ref, click it first, then upload.

5. **DATE FIELDS.** If a form has date inputs, type the date directly: `playwright-cli fill <ref> "03/13/2026"`. Do NOT click calendar widgets — type into the input field directly.

6. **DROPDOWNS.** Try `playwright-cli select <ref> "value"` first. If that fails, try `playwright-cli click <ref>` to open, then `playwright-cli snapshot` to see options, then `playwright-cli click <option_ref>`.

7. **MULTI-STEP FORMS.** After filling visible fields, look for "Next", "Continue", or pagination. Click it, snapshot, fill next section. Repeat until you reach Submit.

8. **SUBMIT BUTTON.** After filling all fields, click Submit/Apply/Send. Then snapshot to verify confirmation. Look for: "thank you", "application received", "submitted", confirmation page.

9. **RETRY ON FAILURE.** If a fill or click fails, snapshot to get fresh refs and try again. Do not give up after one failed attempt.

10. **REQUIRED FIELDS.** If the form shows validation errors after submit attempt, snapshot to see which fields are missing, fill them, and submit again.

11. **"HOW DID YOU HEAR" FIELD.** If you see any field matching: {', '.join(_HOW_DID_YOU_HEAR_LABELS)} — always answer "Job Board" or select "Job Board" / "Other" from the dropdown.

## STEP-BY-STEP EXECUTION

Turn 1: `playwright-cli open "{listing.url}"` then `playwright-cli snapshot`
Turn 2: Find and click "Apply" / "Apply Now". Then `playwright-cli snapshot`
Turn 3+: Fill ALL visible form fields in one batch. Upload resume.
Next: Screenshot to verify, then click Submit.
Next: Snapshot to confirm submission.
Final: `playwright-cli close` and output JSON.

## BLOCKER DETECTION — stop immediately if:
- Login/account creation wall → output blocker: "requires_account"
- CAPTCHA or Cloudflare bot challenge → output blocker: "cloudflare_blocked"
- Premium/paywall → output blocker: "paywall_blocked"
- No form after 3 attempts → output blocker: "no_form_found"
- Site down/maintenance → output blocker: "site_down"

**Cloudflare signals**: page says "Checking if the site connection is secure", "Enable JavaScript and cookies to continue", shows "Cloudflare Ray ID:", or any Cloudflare challenge page → output "cloudflare_blocked" immediately.

## FINAL OUTPUT — output this JSON as your very last message:
{{"filled_fields": ["name", "email", ...], "missing_fields": [], "submitted": true, "blocker": null, "issues": []}}

The application is only successful if "submitted" is true. A partially filled form is a FAILURE."""


def is_cloudflare_blocked(text: str) -> bool:
    """Return True if the result text indicates a Cloudflare anti-bot block.

    Uses specific multi-word signals that only appear on actual CF challenge pages,
    not on normal pages that might mention "cloudflare" in other contexts (e.g. JSON keys).
    """
    lower = text.lower()
    return any(signal in lower for signal in _CLOUDFLARE_SIGNALS)


async def smoke_test_url(
    url: str,
    secrets_path: Path = SECRETS_PATH,
    timeout: int | None = None,
) -> ApplicationResult:
    """Smoke-test a single URL to verify it loads and is not Cloudflare-blocked.

    Used by the --test-url CLI flag to validate individual listings in isolation.
    """
    ats_result = detect_ats(url)
    resolved_timeout = _resolve_timeout(ats_result.ats, timeout)

    try:
        binary = _find_claude_binary()
    except FileNotFoundError as e:
        return ApplicationResult(success=False, notes=str(e))

    # JSON key is "cf_blocked" (not "cloudflare") to avoid triggering is_cloudflare_blocked()
    # on the probe output itself.
    prompt = f"""Open the URL below and take a snapshot. Report whether:
1. The page loaded successfully
2. Whether a Cloudflare bot-detection challenge is present
3. Whether there is an "Apply" button visible

URL: {url}

Run:
  playwright-cli open "{url}"
  playwright-cli snapshot

Then output JSON: {{"loaded": true/false, "cf_blocked": true/false, "apply_button": true/false, "notes": "..."}}

If a Cloudflare challenge page is shown (page says "Enable JavaScript and cookies to continue",
"Checking if the site connection is secure", or shows "Cloudflare Ray ID"), set "cf_blocked": true
and include "cloudflare_blocked" in your notes."""

    cmd = [
        binary,
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--max-turns",
        "5",
        "--dangerously-skip-permissions",
    ]

    env = os.environ.copy()
    token = _load_oauth_token(secrets_path)
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    env["PATH"] = "/usr/local/bin:/opt/homebrew/bin:" + env.get("PATH", "")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=resolved_timeout,
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            return ApplicationResult(
                success=False,
                notes=f"Smoke test failed (exit {proc.returncode}): {stderr[:200]}",
            )

        result_text = _extract_last_text(stdout)
        blocked = is_cloudflare_blocked(result_text)

        return ApplicationResult(
            success=not blocked,
            cloudflare_blocked=blocked,
            notes=result_text[:500] if result_text else "No output",
        )

    except asyncio.TimeoutError:
        return ApplicationResult(
            success=False,
            notes=f"Smoke test timed out after {resolved_timeout}s",
        )
    except Exception as e:
        return ApplicationResult(success=False, notes=f"Smoke test error: {e}")


async def apply_to_job(
    listing: JobListing,
    candidate: Candidate,
    cover_letter: str,
    secrets_path: Path = SECRETS_PATH,
    timeout: int | None = None,
) -> ApplicationResult:
    """Fill and submit a job application using Claude with playwright-cli.

    Works with any job URL — navigates to the page, finds the apply button,
    and fills the form.  ATS-specific hints are injected for known systems.
    """
    ats_result = detect_ats(listing.url)
    ats_type = ats_result.ats
    resolved_timeout = _resolve_timeout(ats_type, timeout)

    try:
        binary = _find_claude_binary()
    except FileNotFoundError as e:
        return ApplicationResult(success=False, notes=str(e))

    prompt = _build_fill_prompt(listing, candidate, cover_letter, ats_type)

    cmd = [
        binary,
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--max-turns",
        str(MAX_TURNS),
        "--dangerously-skip-permissions",
    ]

    env = os.environ.copy()
    token = _load_oauth_token(secrets_path)
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    # Ensure playwright-cli and npx are on PATH
    env["PATH"] = "/usr/local/bin:/opt/homebrew/bin:" + env.get("PATH", "")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=resolved_timeout,
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            return ApplicationResult(
                success=False,
                notes=f"Claude exit {proc.returncode}: {stderr[:300]}",
            )

        # Extract result text
        result_text = _extract_last_text(stdout)
        log.info(
            "Application result for '%s' @ %s: %s",
            listing.title,
            listing.company,
            result_text[:300] if result_text else "empty",
        )

        # Check for Cloudflare block first (distinct from generic failure)
        if is_cloudflare_blocked(result_text):
            log.info("Cloudflare block detected for '%s' @ %s", listing.title, listing.company)
            return ApplicationResult(
                success=False,
                cloudflare_blocked=True,
                notes="cloudflare_blocked",
            )

        # Check for other blockers
        blocker = _check_blocker(result_text)
        if blocker:
            log.info("Application blocked for '%s': %s", listing.title, blocker)
            return ApplicationResult(
                success=False,
                notes=f"Blocked: {blocker}",
            )

        # Check if submission was confirmed
        submitted = _check_submitted(result_text)

        return ApplicationResult(
            success=True,
            submitted=submitted,
            notes=result_text or "Form fill completed",
        )

    except asyncio.TimeoutError:
        return ApplicationResult(
            success=False,
            notes=f"Timed out after {resolved_timeout}s",
        )
    except Exception as e:
        return ApplicationResult(
            success=False,
            notes=f"Error: {e}",
        )


def _check_blocker(result_text: str) -> str | None:
    """Check if the result contains a known blocker signal."""
    text = result_text.lower()
    blockers = [
        "requires_account",
        "captcha_blocked",
        "paywall_blocked",
        "no_form_found",
        "site_down",
    ]
    for b in blockers:
        if b in text:
            return b
    return None


def _check_submitted(result_text: str) -> bool:
    """Check if the Claude output indicates the form was submitted."""
    text = result_text.lower()
    # Check for JSON "submitted": true — scan all lines for JSON objects
    for line in result_text.splitlines():
        line = line.strip()
        # Handle JSON possibly wrapped in markdown code fences
        if line.startswith("```"):
            continue
        if line.startswith("{"):
            try:
                data = json.loads(line)
                if data.get("submitted") is True:
                    return True
            except (json.JSONDecodeError, AttributeError):
                pass
    # Fallback: look for confirmation language from the page itself
    submit_signals = [
        "successfully submitted",
        "application submitted",
        "application sent",
        "successfully applied",
        "thank you for applying",
        "thanks for applying",
        "application has been received",
        "application received",
        "form submitted",
        "we've received your application",
        "we have received your application",
        "your application has been submitted",
        '"submitted": true',
        "'submitted': true",
    ]
    return any(signal in text for signal in submit_signals)


def _extract_last_text(stdout: str) -> str:
    """Extract last meaningful text from stream-json output."""
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
