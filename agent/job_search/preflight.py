"""Pre-flight validation, phase gates, and audit trail.

Ensures all prerequisites are met before each run and validates
phase outputs before proceeding to the next phase.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


# -- Pre-flight checks --

def preflight_check(
    secrets_path: Path,
    criteria_path: Path,
    candidate_path: Path,
    db_path: Path,
    state_dir: Path,
    run_type: str = "prepare",
) -> tuple[bool, list[str]]:
    """Validate all prerequisites before a run.

    Returns (ok, errors). If ok is False, the run should abort.
    """
    errors: list[str] = []

    # 1. Secrets file
    if not secrets_path.exists():
        errors.append(f"Secrets file not found: {secrets_path}")
        return False, errors

    secrets_text = secrets_path.read_text()
    secrets_keys = {}
    for line in secrets_text.splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key = line.split("=", 1)[0].strip()
            secrets_keys[key] = True

    # 2. Required tokens
    if "notion_api_token" not in secrets_keys:
        errors.append("notion_api_token missing from .secrets")
    if "claude_oauth_token" not in secrets_keys:
        errors.append("claude_oauth_token missing from .secrets")

    # 3. Gmail credentials via gws CLI (execute cron only)
    if run_type == "execute":
        import shutil
        gws_bin = shutil.which("gws") or "/opt/homebrew/bin/gws"
        if not Path(gws_bin).is_file():
            errors.append("gws CLI not found — needed for outreach email sending")

    # 4. Config files
    if not criteria_path.exists():
        errors.append(f"Criteria config not found: {criteria_path}")
    else:
        try:
            json.loads(criteria_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"Criteria config invalid: {e}")

    if not candidate_path.exists():
        errors.append(f"Candidate config not found: {candidate_path}")
    else:
        try:
            json.loads(candidate_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"Candidate config invalid: {e}")

    # 5. DB writable
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.close()
    except sqlite3.Error as e:
        errors.append(f"Database not writable: {e}")

    # 6. Notion API reachable
    notion_token = ""
    for line in secrets_text.splitlines():
        if line.strip().startswith("notion_api_token="):
            notion_token = line.strip().split("=", 1)[1].strip()
    if notion_token:
        try:
            resp = httpx.get(
                f"{NOTION_API_BASE}/users/me",
                headers={
                    "Authorization": f"Bearer {notion_token}",
                    "Notion-Version": NOTION_VERSION,
                },
                timeout=10.0,
            )
            if resp.status_code == 401:
                errors.append("Notion API token is invalid (401)")
            elif resp.status_code >= 500:
                errors.append(f"Notion API unreachable (HTTP {resp.status_code})")
        except httpx.RequestError as e:
            errors.append(f"Notion API unreachable: {e}")

    # 7. Already ran today (prepare only)
    if run_type == "prepare":
        state_file = state_dir / "job-search-state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                if state.get("last_run") == date.today().isoformat():
                    errors.append("Already ran prepare today")
            except (json.JSONDecodeError, OSError):
                pass

    if errors:
        return False, errors
    return True, []


# -- Phase gates --

def phase_gate(phase_name: str, results: dict) -> tuple[bool, str]:
    """Validate phase output before proceeding.

    Returns (proceed, message). If proceed is False, skip remaining phases.
    """
    if phase_name == "research":
        fetched = results.get("fetched", 0)
        saved = results.get("saved", 0)
        if fetched == 0:
            return False, "No listings fetched from any board"
        if saved == 0:
            return False, "All listings were duplicates or excluded — nothing new"
        return True, f"Research complete: {saved} new listings from {fetched} total"

    elif phase_name == "rubric_gate":
        # Sprint 06.03 — rubric gate is observability-only (we always proceed
        # so downstream phases run on the ``passed`` subset). Surface the
        # split + threshold so the run audit captures the decision.
        if not results.get("enabled", False):
            return True, "Rubric gate disabled — all listings passed"
        passed = results.get("passed", 0)
        filtered = results.get("filtered", 0)
        total = results.get("total", 0)
        threshold = results.get("threshold", "B")
        return True, (
            f"Rubric gate (>= {threshold}): {passed} passed, "
            f"{filtered} filtered out of {total}"
        )

    elif phase_name == "cover_letters":
        # Cover letters are optional (manual mode), always proceed
        generated = results.get("generated", 0)
        return True, f"Cover letters: {generated} generated"

    elif phase_name == "outreach_research":
        total = results.get("total_contacts", 0)
        failed = results.get("failed_companies", 0)
        attempted = results.get("attempted", 0)
        if attempted > 0 and total == 0:
            return False, "Outreach research found no contacts at any company"
        return True, f"Outreach research: {total} contacts found ({failed} companies failed)"

    elif phase_name == "outreach_drafts":
        drafted = results.get("drafted", 0)
        return True, f"Outreach drafts: {drafted} emails drafted"

    elif phase_name == "staging":
        staged = results.get("staged", 0)
        errors = results.get("errors", 0)
        total = results.get("total", 0)
        if total > 0 and errors > total / 2:
            return False, f"Staging mostly failed: {errors}/{total} errors"
        return True, f"Staging: {staged} listings staged in Notion"

    return True, f"Phase '{phase_name}' passed (no gate defined)"


# -- Audit trail --

def start_audit(conn: sqlite3.Connection, run_type: str) -> int:
    """Begin an audit trail entry. Returns the audit ID."""
    cursor = conn.execute(
        "INSERT INTO run_audit (run_type, started_at) VALUES (?, ?)",
        (run_type, datetime.now().isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def update_audit(
    conn: sqlite3.Connection,
    audit_id: int,
    phase_results: dict,
    errors: list[str],
    success: bool,
) -> None:
    """Update an audit trail entry with results."""
    conn.execute(
        """UPDATE run_audit
           SET completed_at = ?, phase_results = ?, errors = ?, success = ?
           WHERE id = ?""",
        (
            datetime.now().isoformat(),
            json.dumps(phase_results),
            json.dumps(errors),
            1 if success else 0,
            audit_id,
        ),
    )
    conn.commit()
