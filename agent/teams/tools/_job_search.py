"""Job search department tool functions for the teams/ Z4 registry.

8 tools migrated from job_search/tools/ and wrapped with RunContext[BridgeDeps]:
  scrape_boards, score_and_deduplicate, generate_cover_letter,
  stage_listing_to_notion, get_approved_listings, update_notion_status,
  send_discord_alert, research_contacts.

Original job_search/tools/ modules are kept as pass-through shims.

Sprint 02.10: every tool that produces a pipeline-relevant outcome now
writes to the shared FunnelStore via :func:`job_search.quality_wiring.bump_today`.
``generate_cover_letter`` runs the result through :func:`lint_cover_letter`
before returning success, and ``stage_listing_to_notion`` records an approval
snapshot so the edit-after-approval drift gate fires at send time.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext

from job_search.quality_wiring import (
    bump_today,
    get_snapshot_store,
)
from teams._types import BridgeDeps

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# scrape_boards
# ---------------------------------------------------------------------------

async def scrape_boards(ctx: RunContext[BridgeDeps], keywords: list[str]) -> dict[str, Any]:
    """Scrape all configured job boards in parallel and return a flat listing set.

    Args:
        ctx: PydanticAI run context carrying BridgeDeps.
        keywords: List of search keywords to pass to each board.

    Returns:
        Dict with keys: listings (list), boards_queried (list), error_boards (list).
    """
    try:
        from job_search.criteria import SearchCriteria
        from job_search.tools.boards import scrape_boards as _scrape

        # Build a minimal SearchCriteria from caller-supplied keywords. The
        # SearchCriteria dataclass exposes ``roles`` (not ``keywords``); the
        # downstream ``criteria.keyword_list()`` call returns ``roles`` plus
        # any field-root augmentation, so seeding ``roles=keywords`` is the
        # canonical wiring (matches JobSearchAgent._research_phase usage).
        criteria = SearchCriteria(roles=keywords)
        result = await _scrape(ctx, criteria)
        # Sprint 02.10: bump scraped on the funnel for the 22:00 summary.
        bump_today("scraped", count=len(result.listings))
        return {
            "listings": [l.model_dump() for l in result.listings],
            "boards_queried": result.boards_queried,
            "error_boards": result.error_boards,
            "total": len(result.listings),
        }
    except Exception as exc:
        log.error("scrape_boards failed: %s", exc)
        return {"listings": [], "boards_queried": [], "error_boards": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# score_and_deduplicate
# ---------------------------------------------------------------------------

async def score_and_deduplicate(
    ctx: RunContext[BridgeDeps],
    listings: list[dict[str, Any]],
    min_score: int = 1,
) -> dict[str, Any]:
    """Score and deduplicate a raw listing set.

    Args:
        ctx: PydanticAI run context.
        listings: List of listing dicts (from scrape_boards output).
        min_score: Minimum score threshold; listings below this are excluded.

    Returns:
        Dict with keys: listings (scored, sorted), total_scraped, total_after_dedup,
        total_after_scoring, duplicate_count, filtered_count.
    """
    try:
        from job_search.criteria import SearchCriteria
        from job_search.models import JobListing
        from job_search.tools.scoring import score_and_deduplicate as _score

        job_listings = [JobListing(**l) for l in listings]
        # Use a permissive criteria for scoring (no role filter applied here;
        # ``SearchCriteria`` field is ``roles`` not ``keywords``).
        criteria = SearchCriteria(roles=[])
        result = await _score(ctx, job_listings, criteria)
        # Sprint 02.10: bump deduped count on the funnel.
        if result.duplicate_count:
            bump_today("deduped", count=result.duplicate_count)
        return {
            "listings": [l.model_dump() for l in result.listings if l.score >= min_score],
            "total_scraped": result.total_scraped,
            "total_after_dedup": result.total_after_dedup,
            "total_after_scoring": result.total_after_scoring,
            "duplicate_count": result.duplicate_count,
            "filtered_count": result.filtered_count,
        }
    except Exception as exc:
        log.error("score_and_deduplicate failed: %s", exc)
        return {
            "listings": [],
            "total_scraped": len(listings),
            "total_after_dedup": 0,
            "total_after_scoring": 0,
            "duplicate_count": 0,
            "filtered_count": len(listings),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# generate_cover_letter
# ---------------------------------------------------------------------------

async def generate_cover_letter(
    ctx: RunContext[BridgeDeps],
    job_title: str,
    company: str,
    description: str,
    url: str,
) -> dict[str, Any]:
    """Generate a tailored cover letter for a job listing via Claude subprocess.

    Args:
        ctx: PydanticAI run context.
        job_title: Job title from the listing.
        company: Company name.
        description: Job description text (first 2000 chars used).
        url: URL of the job listing.

    Returns:
        Dict with keys: cover_letter (str or None), success (bool), error (str or None).
    """
    try:
        from job_search.agent import DEFAULT_CANDIDATE
        from job_search.cover_letter import generate_cover_letter as _gen
        from job_search.criteria import Candidate
        from job_search.lint import lint_cover_letter

        # The criteria module exposes ``Candidate.from_file``; there is no
        # ``load_candidate`` helper. Mirror the legacy ``JobSearchAgent``
        # construction (agent.py:84) so Path A and Path B both load from
        # ``agent/job_search/candidate.json``.
        candidate = Candidate.from_file(DEFAULT_CANDIDATE)
        # Build a minimal JobListing-like object. ``board`` is a required
        # positional field on the dataclass; pass an empty string so the
        # construction does not raise.
        from job_search.boards.base import JobListing as LegacyListing
        listing = LegacyListing(
            url=url,
            title=job_title,
            company=company,
            board="",
            description=description,
        )
        text = await _gen(listing, candidate)
        if text is None:
            return {"cover_letter": None, "success": False, "error": None}

        # Sprint 02.10: lint gate before returning success.
        lint_result = lint_cover_letter(text, company=company)
        if not lint_result.ok:
            reason = ",".join(lint_result.failures) or "unknown"
            log.warning(
                "Cover letter lint failed for %s @ %s: %s",
                job_title, company, reason,
            )
            bump_today("lint_failed")
            return {
                "cover_letter": None,
                "success": False,
                "error": f"lint_failed:{reason}",
                "lint_failures": list(lint_result.failures),
            }

        bump_today("lint_passed")
        bump_today("covered")
        return {"cover_letter": text, "success": True, "error": None}
    except Exception as exc:
        log.error("generate_cover_letter failed: %s", exc)
        return {"cover_letter": None, "success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# stage_listing_to_notion
# ---------------------------------------------------------------------------

async def stage_listing_to_notion(
    ctx: RunContext[BridgeDeps],
    listing: dict[str, Any],
    cover_letter: str = "",
    ats: str = "unknown",
    outreach_drafts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Stage a scored listing in the Notion Job Applications database.

    Args:
        ctx: PydanticAI run context.
        listing: Listing dict (from score_and_deduplicate output).
        cover_letter: Optional cover letter text to include on the page.
        ats: Detected ATS system name (e.g. "Greenhouse", "Lever").
        outreach_drafts: Optional list of outreach payloads to snapshot at
            approval time. Each item must contain at minimum
            ``slot``, ``to_email``, ``subject``, and ``body``. When provided,
            an approval snapshot is recorded per slot so the EXECUTE-phase
            ``execute_approved`` path can detect edit-after-approval drift.

    Returns:
        Dict with keys: page_id (str or None), success (bool), error (str or None),
        snapshot_keys (list of strings recorded; empty when no drafts supplied).
    """
    try:
        import os
        from job_search.notifier import NotionNotifier
        from job_search.boards.base import JobListing as LegacyListing

        notion_db_id = os.environ.get("BUMBA_NOTION_JOB_DB_ID")
        if not notion_db_id:
            raise RuntimeError("Set BUMBA_NOTION_JOB_DB_ID before staging listings.")
        notifier = NotionNotifier(database_id=notion_db_id)
        leg = LegacyListing(
            url=listing.get("url", ""),
            title=listing.get("title", ""),
            company=listing.get("company", ""),
            description=listing.get("description", ""),
            location=listing.get("location"),
            compensation=listing.get("compensation"),
            board=listing.get("board"),
        )
        result = await notifier.log_listing(leg, ats=ats, cover_letter=cover_letter)

        snapshot_keys: list[str] = []
        if result.success and result.page_id:
            # Sprint 02.10: bump staged on the funnel.
            bump_today("staged")

            # Sprint 02.10: record approval snapshots for any outreach drafts.
            if outreach_drafts:
                snapshot_store = get_snapshot_store()
                for draft in outreach_drafts:
                    try:
                        slot = int(draft.get("slot", 0)) or len(snapshot_keys) + 1
                        payload = {
                            "slot": slot,
                            "to_email": draft.get("to_email", ""),
                            "subject": draft.get("subject", ""),
                            "body": draft.get("body", ""),
                            "name": draft.get("name", ""),
                            "title": draft.get("title", ""),
                        }
                        key = f"{result.page_id}:slot{slot}"
                        snapshot_store.record_approval(key, payload)
                        snapshot_keys.append(key)
                    except Exception as snap_err:  # pragma: no cover — defensive
                        log.warning("Snapshot record failed: %s", snap_err)

        return {
            "page_id": result.page_id,
            "success": result.success,
            "error": result.error,
            "snapshot_keys": snapshot_keys,
        }
    except Exception as exc:
        log.error("stage_listing_to_notion failed: %s", exc)
        return {"page_id": None, "success": False, "error": str(exc), "snapshot_keys": []}


# ---------------------------------------------------------------------------
# get_approved_listings
# ---------------------------------------------------------------------------

async def get_approved_listings(ctx: RunContext[BridgeDeps]) -> dict[str, Any]:
    """Query Notion for listings that the operator has approved for execution.

    Returns:
        Dict with keys: items (list of approved item dicts), count (int).
    """
    try:
        import os
        from job_search.notifier import NotionNotifier
        from job_search.approval import check_approvals

        notion_db_id = os.environ.get("BUMBA_NOTION_JOB_DB_ID")
        if not notion_db_id:
            raise RuntimeError("Set BUMBA_NOTION_JOB_DB_ID before reading approvals.")
        notifier = NotionNotifier(database_id=notion_db_id)
        approved = check_approvals(notifier)
        items = [
            {
                "page_id": item.page_id,
                "company": item.company,
                "apply_approved": item.apply_approved,
                "outreach_1_approved": item.outreach_1_approved,
                "outreach_2_approved": item.outreach_2_approved,
            }
            for item in approved
        ]
        return {"items": items, "count": len(items)}
    except Exception as exc:
        log.error("get_approved_listings failed: %s", exc)
        return {"items": [], "count": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# update_notion_status
# ---------------------------------------------------------------------------

async def update_notion_status(
    ctx: RunContext[BridgeDeps],
    page_id: str,
    status: str,
    applied_at: str = "",
) -> dict[str, Any]:
    """Update the status field of a Notion Job Applications page.

    Args:
        ctx: PydanticAI run context.
        page_id: Notion page ID to update.
        status: New status value (e.g. "Applied", "Staged", "Rejected").
        applied_at: Optional ISO datetime string for the Applied At field.

    Returns:
        Dict with keys: success (bool), error (str or None).
    """
    try:
        from job_search.notifier import NotionNotifier

        notifier = NotionNotifier()
        result = await notifier.update_status(page_id, status, applied_at=applied_at)
        return {"success": result.success, "error": result.error}
    except Exception as exc:
        log.error("update_notion_status failed: %s", exc)
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# send_discord_alert
# ---------------------------------------------------------------------------

async def send_discord_alert(
    ctx: RunContext[BridgeDeps],
    message: str,
    source: str = "job_search",
) -> dict[str, Any]:
    """Send an alert message to the operator via Discord.

    Args:
        ctx: PydanticAI run context (BridgeDeps.event_bus used if available).
        message: The message text to send.
        source: Logical source tag for the message (default: "job_search").

    Returns:
        Dict with keys: success (bool), error (str or None).
    """
    try:
        # Attempt to publish via event_bus if available
        if ctx.deps.event_bus is not None:
            ctx.deps.event_bus.publish("discord.send", {"message": message, "source": source})
            return {"success": True, "error": None}

        # Fallback: write a service_messages file for pickup by the bridge
        import json
        import os
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path

        messages_dir = Path("/opt/bumba-harness/data/service_messages")
        messages_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "type": "alert",
            "service": source,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        alert_path = messages_dir / f"{source}_{ts}.json"

        fd, tmp = tempfile.mkstemp(dir=messages_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, alert_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

        log.info("Discord alert written to %s", alert_path.name)
        return {"success": True, "error": None}
    except Exception as exc:
        log.error("send_discord_alert failed: %s", exc)
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# research_contacts
# ---------------------------------------------------------------------------

async def research_contacts(
    ctx: RunContext[BridgeDeps],
    company: str,
    job_url: str,
    job_title: str,
) -> dict[str, Any]:
    """Research up to 2 decision-maker contacts at a target company.

    Uses Claude subprocess with playwright-cli for web research.

    Args:
        ctx: PydanticAI run context.
        company: Company name to research.
        job_url: URL of the job posting.
        job_title: Job title being applied for.

    Returns:
        Dict with keys: contacts (list of contact dicts), count (int).
        Each contact dict has: name, title, email, company, hook.
    """
    try:
        from job_search.outreach import research_decision_makers

        contacts = await research_decision_makers(company, job_url, job_title)
        contact_dicts = [
            {
                "name": c.name,
                "title": c.title,
                "email": c.email,
                "company": c.company,
                "hook": c.hook,
            }
            for c in contacts
        ]
        return {"contacts": contact_dicts, "count": len(contact_dicts)}
    except Exception as exc:
        log.error("research_contacts failed for %s: %s", company, exc)
        return {"contacts": [], "count": 0, "error": str(exc)}
