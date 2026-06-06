"""Cover letter generation via Claude Code subprocess."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

from bridge.paths import data_root

from .boards.base import JobListing
from .criteria import Candidate

log = logging.getLogger(__name__)

SECRETS_PATH = data_root() / ".secrets"
CANDIDATE_CONTEXT = Path(__file__).parent / "prompts" / "candidate_context.md"
TIMEOUT_SECONDS = 120


def _load_candidate_context() -> str:
    """Load the candidate resume context for prompt injection."""
    if CANDIDATE_CONTEXT.exists():
        return CANDIDATE_CONTEXT.read_text().strip()
    return ""


def _load_oauth_token(secrets_path: Path = SECRETS_PATH) -> str:
    """Load CLAUDE_CODE_OAUTH_TOKEN from .secrets."""
    if not secrets_path.exists():
        return ""
    for line in secrets_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("claude_oauth_token="):
            return line.split("=", 1)[1].strip()
    return ""


def _find_claude_binary() -> str:
    """Locate the claude binary."""
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


def _build_prompt(listing: JobListing, candidate: Candidate) -> str:
    """Build the cover letter generation prompt."""
    desc = listing.description[:2000] if listing.description else "No description available"
    resume_context = _load_candidate_context()

    template_guidance = ""
    if candidate.cover_letter_template:
        template_guidance = f"\n**Style guidance:** {candidate.cover_letter_template}\n"

    return f"""Write a professional cover letter for the following job application.

**Job Title:** {listing.title}
**Company:** {listing.company}
**Job Description:**
{desc}

**Candidate:**
- Name: {candidate.name}
- Portfolio: {candidate.portfolio_url}
- LinkedIn: {candidate.linkedin_url}

**Candidate Background:**
{resume_context}
{template_guidance}
**Instructions:**
- Write 3-4 paragraphs
- Draw on specific experience from the candidate's background that matches this role
- Reference concrete projects, metrics, and companies from the resume where relevant
- Show genuine interest in the company, not generic flattery
- Professional but warm tone — confident, not presumptuous
- Highlight the candidate's unique blend of design leadership and engineering capability
- Do NOT include placeholder text like [Company Name] — use the actual company name
- Do NOT list every skill — select 2-3 that are most relevant to this specific role
- Output ONLY the cover letter text, no preamble or explanation"""


async def generate_cover_letter(
    listing: JobListing,
    candidate: Candidate,
    secrets_path: Path = SECRETS_PATH,
    timeout: int = TIMEOUT_SECONDS,
) -> str | None:
    """Generate a cover letter using Claude Code subprocess.

    Returns the cover letter text, or None on failure.
    """
    try:
        binary = _find_claude_binary()
    except FileNotFoundError as e:
        log.error("Cover letter gen failed: %s", e)
        return None

    prompt = _build_prompt(listing, candidate)

    cmd = [
        binary, "-p",
        "--verbose",
        "--output-format", "stream-json",
        "--max-turns", "1",
        "--dangerously-skip-permissions",
    ]

    env = os.environ.copy()
    token = _load_oauth_token(secrets_path)
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )

        # Feed prompt via stdin
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=timeout,
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            log.error(
                "Cover letter subprocess failed (exit=%d): %s",
                proc.returncode, stderr[:500],
            )
            return None

        # Parse stream-json output for the result text
        text = _extract_result_text(stdout)
        if text:
            log.info(
                "Cover letter generated for '%s' @ %s (%d chars)",
                listing.title, listing.company, len(text),
            )
        else:
            log.warning("No result text in Claude output for '%s'", listing.title)

        return text

    except asyncio.TimeoutError:
        log.error("Cover letter generation timed out (%ds) for '%s'", timeout, listing.title)
        return None
    except Exception as e:
        log.error("Cover letter generation error for '%s': %s", listing.title, e)
        return None


def _extract_result_text(stdout: str) -> str | None:
    """Extract the final result text from stream-json NDJSON output."""
    text_parts: list[str] = []
    result_text = ""

    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = data.get("type", "")

        if msg_type == "assistant":
            message = data.get("message", {})
            if isinstance(message, dict):
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))

        elif msg_type == "result":
            result_text = data.get("result", "")

    # Prefer result text, fall back to last assistant text
    if result_text:
        return result_text
    if text_parts:
        return text_parts[-1]
    return None
