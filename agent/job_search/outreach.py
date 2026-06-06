"""Outreach research and email drafting via Claude subprocess.

Phase 3: Research decision-makers at target companies.
Phase 4: Draft personalized outreach emails.
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

from .boards.base import JobListing
from .criteria import Candidate

log = logging.getLogger(__name__)

SECRETS_PATH = data_root() / ".secrets"
PROMPTS_DIR = Path(__file__).parent / "prompts"
CANDIDATE_CONTEXT = PROMPTS_DIR / "candidate_context.md"
RESEARCH_TIMEOUT = 90  # Reduced from 300s — 3x faster failure-detection per company
DRAFT_TIMEOUT = 60


def _load_candidate_context() -> str:
    """Load the candidate resume context for prompt injection."""
    if CANDIDATE_CONTEXT.exists():
        return CANDIDATE_CONTEXT.read_text().strip()
    return ""


@dataclass
class Contact:
    """A decision-maker at a target company."""

    name: str
    title: str
    email: str
    company: str
    hook: str  # personalization note


@dataclass
class OutreachDraft:
    """A drafted outreach email ready for approval."""

    contact: Contact
    subject: str
    body: str
    slot: int  # 1 or 2


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


def _build_research_prompt(company: str, job_url: str, job_title: str) -> str:
    """Build the prompt for decision-maker research."""
    return f"""Find 2 decision-makers at **{company}** who would be relevant to a **{job_title}** role.

Job posting URL: {job_url}

Follow the instructions in your system prompt. Return only valid JSON."""


def _build_draft_prompt(contact: Contact, listing: JobListing, candidate: Candidate) -> str:
    """Build the prompt for outreach email drafting."""
    resume_context = _load_candidate_context()

    return f"""Write an outreach email to the following person:

**Recipient:** {contact.name}, {contact.title} at {contact.company}
**Personalization hook:** {contact.hook}

**Role applied for:** {listing.title} at {listing.company}
**Job URL:** {listing.url}

**Candidate:**
- Name: {candidate.name}
- Portfolio: {candidate.portfolio_url}
- LinkedIn: {candidate.linkedin_url}

**Candidate Background:**
{resume_context}

Follow the instructions in your system prompt. Draw on specific experience from the candidate's background that is most relevant to this role and this recipient's area of responsibility. Return the email in the exact format specified."""


def _parse_contacts_json(text: str, company: str) -> list[Contact]:
    """Parse the JSON output from the research subprocess."""
    # Try to find JSON array in the text
    text = text.strip()

    # Handle markdown code fences
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                text = part
                break

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON array from surrounding text
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                log.warning("Failed to parse contacts JSON: %s", text[:200])
                return []
        else:
            log.warning("No JSON array found in research output: %s", text[:200])
            return []

    if not isinstance(data, list):
        return []

    contacts = []
    for item in data[:2]:  # Max 2 contacts
        if not isinstance(item, dict):
            continue
        name = item.get("name", "").strip()
        email = item.get("email", "").strip()
        if not name or not email:
            continue
        contacts.append(
            Contact(
                name=name,
                title=item.get("title", "").strip(),
                email=email,
                company=company,
                hook=item.get("hook", "").strip(),
            )
        )

    return contacts


def _parse_email_draft(text: str) -> tuple[str, str]:
    """Parse subject and body from the email draft output."""
    text = text.strip()

    # Handle code fences
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.upper().startswith("SUBJECT:") or part.startswith("subject:"):
                text = part
                break

    subject = ""
    body_lines: list[str] = []
    in_body = False

    for line in text.splitlines():
        if line.upper().startswith("SUBJECT:") and not subject:
            subject = line.split(":", 1)[1].strip()
            in_body = True
            continue
        if in_body:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()

    if not subject and body_lines:
        # Fallback: first line is subject, rest is body
        subject = body_lines[0]
        body = "\n".join(body_lines[1:]).strip()

    return subject, body


async def research_decision_makers(
    company: str,
    job_url: str,
    job_title: str,
    secrets_path: Path = SECRETS_PATH,
    timeout: int = RESEARCH_TIMEOUT,
) -> list[Contact]:
    """Research 2 decision-makers at the target company using Claude with playwright-cli.

    Returns list of Contact (max 2), or empty list on failure.
    """
    try:
        binary = _find_claude_binary()
    except FileNotFoundError as e:
        log.error("Outreach research failed: %s", e)
        return []

    prompt = _build_research_prompt(company, job_url, job_title)
    system_prompt = PROMPTS_DIR / "outreach_research.md"

    cmd = [
        binary,
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--max-turns",
        "15",
        "--dangerously-skip-permissions",
    ]
    if system_prompt.exists():
        cmd.extend(["--append-system-prompt-file", str(system_prompt)])

    env = os.environ.copy()
    token = _load_oauth_token(secrets_path)
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    # Ensure playwright-cli is on PATH
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
            timeout=timeout,
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            log.error(
                "Outreach research subprocess failed (exit=%d): %s", proc.returncode, stderr[:300]
            )
            return []

        result_text = _extract_result_text(stdout)
        if not result_text:
            log.warning("No result text from outreach research for %s", company)
            return []

        contacts = _parse_contacts_json(result_text, company)
        log.info("Found %d contacts at %s", len(contacts), company)
        return contacts

    except asyncio.TimeoutError:
        log.error("Outreach research timed out (%ds) for %s", timeout, company)
        return []
    except Exception as e:
        log.error("Outreach research error for %s: %s", company, e)
        return []


async def draft_outreach_email(
    contact: Contact,
    listing: JobListing,
    candidate: Candidate,
    secrets_path: Path = SECRETS_PATH,
    timeout: int = DRAFT_TIMEOUT,
) -> OutreachDraft | None:
    """Draft a personalized outreach email to a decision-maker.

    Returns OutreachDraft or None on failure.
    """
    try:
        binary = _find_claude_binary()
    except FileNotFoundError as e:
        log.error("Outreach draft failed: %s", e)
        return None

    prompt = _build_draft_prompt(contact, listing, candidate)
    system_prompt = PROMPTS_DIR / "outreach_email.md"

    cmd = [
        binary,
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--max-turns",
        "1",
        "--dangerously-skip-permissions",
    ]
    if system_prompt.exists():
        cmd.extend(["--append-system-prompt-file", str(system_prompt)])

    env = os.environ.copy()
    token = _load_oauth_token(secrets_path)
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    # Ensure playwright-cli is on PATH
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
            timeout=timeout,
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            log.error("Outreach draft failed (exit=%d): %s", proc.returncode, stderr[:300])
            return None

        result_text = _extract_result_text(stdout)
        if not result_text:
            log.warning(
                "No result text from outreach draft for %s at %s", contact.name, contact.company
            )
            return None

        subject, body = _parse_email_draft(result_text)
        if not subject or not body:
            log.warning("Failed to parse email draft for %s", contact.name)
            return None

        log.info(
            "Drafted outreach email to %s (%s) — subject: %s", contact.name, contact.title, subject
        )
        return OutreachDraft(contact=contact, subject=subject, body=body, slot=0)

    except asyncio.TimeoutError:
        log.error("Outreach draft timed out (%ds) for %s", timeout, contact.name)
        return None
    except Exception as e:
        log.error("Outreach draft error for %s: %s", contact.name, e)
        return None


def _extract_result_text(stdout: str) -> str | None:
    """Extract the final result text from stream-json output."""
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

    if result_text:
        return result_text
    if text_parts:
        return text_parts[-1]
    return None
