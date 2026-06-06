"""Notion approval workflow — stage items, check approvals, execute.

Prepare cron stages listings + outreach in Notion with checkboxes unchecked.
Operator reviews and checks approval boxes.
Execute cron picks up approved items and acts.

Z2-S2.3: SnapshotStore is integrated at the execute layer.  Before sending
any outreach email, execute_approved() calls snapshot.verify_or_raise().
On SnapshotMismatch, the send is BLOCKED, the listing is marked
``snapshot_drift`` in Notion, and a Discord service message is written for
the operator.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from bridge.paths import data_root

from .boards.base import JobListing
from .criteria import Candidate
from .notifier import NotionNotifier
from .outreach import Contact, OutreachDraft

log = logging.getLogger(__name__)

DATA_DIR = data_root()


# Sprint 06.04 — Notion DB additive columns for rubric review.
# Operator must add these columns to the Notion DB manually (see
# docs/operator/notion-rubric-columns.md). The bridge writes them
# defensively: if the columns are missing, the write retries WITHOUT
# the rubric properties so the row still lands.
RUBRIC_PROPERTY_NAMES: tuple[str, ...] = (
    "rubric_grade",
    "rubric_score",
    "rubric_rationale",
    "rubric_decision",
    "rubric_evaluated_at",
)


@dataclass(frozen=True)
class RubricStageData:
    """Per-listing rubric data threaded into Notion staging.

    Sprint 06.04: when the rubric gate is enabled and a listing has been
    evaluated, ``_staging_phase`` packages the persisted rubric row into
    this frozen DTO so ``stage_listing`` can render it as Notion
    properties without re-evaluating.

    ``rubric_decision`` is the operator-override switch:
      - ``"pending"``   — rubric data present, awaiting operator review
                          (default for any evaluated listing)
      - ``"approved"``  — operator flipped this back to cover-letter
                          generation despite a sub-threshold grade
      - ``"rejected"``  — operator confirmed the filter
      - ``"not_applicable"`` — rubric gate disabled at staging time, no
                               rubric data on this listing

    The bridge only WRITES ``"pending"`` and ``"not_applicable"``.
    ``"approved"`` / ``"rejected"`` are operator-set in Notion.
    """

    letter_grade: str
    weighted_score: float
    rationale: str
    evaluated_at: str  # ISO8601
    decision: str = "pending"


@dataclass
class ApprovedItem:
    """An item approved by the operator in Notion."""
    page_id: str
    fingerprint: str
    company: str
    apply_approved: bool
    outreach_1_approved: bool
    outreach_2_approved: bool


@dataclass
class ExecutionResult:
    """Result of executing an approved item."""
    page_id: str
    application_submitted: bool = False
    outreach_1_sent: bool = False
    outreach_2_sent: bool = False
    snapshot_drift: bool = False
    errors: list[str] | None = None


def stage_listing(
    notifier: NotionNotifier,
    listing: JobListing,
    ats: str,
    cover_letter: str,
    contacts: list[Contact],
    drafts: list[OutreachDraft],
    status: str = "Staged",
    *,
    snapshot_store=None,
    rubric: RubricStageData | None = None,
    rubric_gate_enabled: bool = False,
) -> str | None:
    """Stage a listing with cover letter and outreach drafts in Notion.

    Creates a Notion page with the given status and outreach approval checkboxes unchecked.
    Returns the page_id or None on failure.

    If snapshot_store is provided, records an approval snapshot for each outreach
    draft so EXECUTE can verify the payload hasn't been modified before sending.

    Sprint 06.04: when ``rubric`` is provided, five additive Notion columns are
    populated (grade / score / rationale / decision / evaluated_at). When the
    Notion DB is missing those columns the API call fails for that property —
    we catch the failure and retry the write WITHOUT the rubric properties so
    the row still lands. ``rubric_gate_enabled`` toggles the
    ``"not_applicable"`` decision when no rubric data is present.
    """
    properties = _build_staged_properties(
        listing,
        ats,
        contacts,
        status=status,
        rubric=rubric,
        rubric_gate_enabled=rubric_gate_enabled,
    )

    body: dict = {
        "parent": {"database_id": notifier.database_id},
        "properties": properties,
    }

    # Build page content
    children = _build_page_content(listing, cover_letter, drafts)
    if children:
        body["children"] = children

    page_id = _post_page_with_rubric_fallback(notifier, listing, body)
    if page_id is None:
        return None

    log.info(
        "Staged listing in Notion: '%s' @ %s — page_id=%s",
        listing.title, listing.company, page_id,
    )

    # Record approval snapshot for each outreach draft (Z2-S2.3).
    if snapshot_store is not None and page_id:
        for slot, draft in enumerate(drafts[:2], start=1):
            payload = _build_outreach_payload(draft, slot)
            try:
                snapshot_store.record_approval(f"{page_id}:slot{slot}", payload)
            except Exception as snap_err:
                log.warning(
                    "Snapshot record failed for page %s slot %d: %s",
                    page_id, slot, snap_err,
                )

    return page_id


def _post_page_with_rubric_fallback(
    notifier: NotionNotifier,
    listing: JobListing,
    body: dict,
) -> str | None:
    """POST /pages, retry without rubric fields if the schema lacks them.

    Sprint 06.04: the Notion DB is operator-managed; rubric columns must be
    added by hand. If they are missing, Notion 400s on the unknown property.
    Rather than dropping the entire row, strip the rubric fields and retry
    once. Any other failure is logged and surfaced as ``None``.
    """
    properties = body.get("properties", {})
    has_rubric_props = any(name in properties for name in RUBRIC_PROPERTY_NAMES)

    try:
        client = notifier._get_client()
        resp = client.post("/pages", json=body)
        resp.raise_for_status()
        return resp.json().get("id", "")
    except Exception as e:
        if has_rubric_props and _looks_like_missing_rubric_column(e):
            log.warning(
                "Notion rejected rubric column for '%s' — retrying without "
                "rubric fields (operator must add columns: %s). Error: %s",
                listing.title,
                ", ".join(RUBRIC_PROPERTY_NAMES),
                e,
            )
            stripped = {
                k: v for k, v in properties.items() if k not in RUBRIC_PROPERTY_NAMES
            }
            retry_body = dict(body)
            retry_body["properties"] = stripped
            try:
                client = notifier._get_client()
                resp = client.post("/pages", json=retry_body)
                resp.raise_for_status()
                return resp.json().get("id", "")
            except Exception as retry_err:
                log.error(
                    "Failed to stage listing '%s' even after rubric retry: %s",
                    listing.title, retry_err,
                )
                return None
        log.error("Failed to stage listing '%s': %s", listing.title, e)
        return None


def _looks_like_missing_rubric_column(err: Exception) -> bool:
    """Heuristic: does this exception look like Notion rejecting a rubric col?

    Notion validation_error messages mention the offending property name.
    We accept any error that mentions one of our rubric property names — the
    cost of a false positive is one extra retry without rubric fields.
    """
    blob = repr(err)
    return any(name in blob for name in RUBRIC_PROPERTY_NAMES)


def _build_outreach_payload(draft: OutreachDraft, slot: int) -> dict:
    """Build the canonical outreach payload dict that is hashed for snapshot."""
    return {
        "slot": slot,
        "to_email": draft.contact.email,
        "subject": draft.subject,
        "body": draft.body,
        "name": draft.contact.name,
        "title": draft.contact.title,
    }


def _build_staged_properties(
    listing: JobListing,
    ats: str,
    contacts: list[Contact],
    status: str = "Staged",
    *,
    rubric: RubricStageData | None = None,
    rubric_gate_enabled: bool = False,
) -> dict:
    """Build Notion page properties for a staged listing.

    Sprint 06.04: when ``rubric`` is non-None, five additive columns are
    appended (rubric_grade / rubric_score / rubric_rationale /
    rubric_decision / rubric_evaluated_at). When ``rubric`` is None, only
    ``rubric_decision = "not_applicable"`` is set IF the gate is enabled
    (so the operator knows the gate was on but skipped this row); otherwise
    no rubric columns are written for backward compatibility.
    """
    props: dict = {
        "Title": {"title": [{"text": {"content": listing.title}}]},
        "Company": {"rich_text": [{"text": {"content": listing.company}}]},
        "URL": {"url": listing.url},
        "Board": {"select": {"name": listing.board or "unknown"}},
        "Status": {"select": {"name": status}},
        "Apply Approved": {"checkbox": False},
        "Outreach 1 Approved": {"checkbox": False},
        "Outreach 1 Sent": {"checkbox": False},
        "Outreach 2 Approved": {"checkbox": False},
        "Outreach 2 Sent": {"checkbox": False},
    }
    if ats and ats != "unknown":
        props["ATS"] = {"select": {"name": ats}}
    if listing.compensation:
        props["Compensation"] = {"rich_text": [{"text": {"content": listing.compensation}}]}
    if listing.location:
        props["Location"] = {"rich_text": [{"text": {"content": listing.location}}]}

    # Outreach contact properties
    for i, contact in enumerate(contacts[:2], start=1):
        props[f"Outreach {i} Name"] = {"rich_text": [{"text": {"content": contact.name}}]}
        props[f"Outreach {i} Title"] = {"rich_text": [{"text": {"content": contact.title}}]}
        props[f"Outreach {i} Email"] = {"email": contact.email}

    props.update(_build_rubric_properties(rubric=rubric, rubric_gate_enabled=rubric_gate_enabled))

    return props


def _build_rubric_properties(
    *,
    rubric: RubricStageData | None,
    rubric_gate_enabled: bool,
) -> dict:
    """Render the 5 additive rubric columns for Notion.

    Returns an empty dict when no rubric data is available AND the gate is
    disabled, preserving backward compatibility for pre-rubric-era rows.

    When the gate IS enabled but ``rubric`` is None (gate skipped this
    listing — eg. eval failure), only ``rubric_decision`` is emitted with
    value ``"not_applicable"`` so the operator can tell the gate ran but
    no grade was produced.
    """
    if rubric is None:
        if rubric_gate_enabled:
            return {
                "rubric_decision": {"select": {"name": "not_applicable"}},
            }
        return {}

    return {
        "rubric_grade": {"select": {"name": rubric.letter_grade}},
        "rubric_score": {"number": float(rubric.weighted_score)},
        "rubric_rationale": {
            "rich_text": [{"text": {"content": (rubric.rationale or "")[:2000]}}]
        },
        "rubric_decision": {"select": {"name": rubric.decision}},
        "rubric_evaluated_at": {"date": {"start": rubric.evaluated_at}},
    }


def _build_page_content(
    listing: JobListing,
    cover_letter: str,
    drafts: list[OutreachDraft],
) -> list[dict]:
    """Build the Notion page body blocks."""
    children: list[dict] = []

    # Job description
    if listing.description:
        children.append(_heading("Job Description"))
        children.append(_paragraph(listing.description[:2000]))

    # Cover letter
    if cover_letter:
        children.append(_heading("Cover Letter"))
        children.append(_paragraph(cover_letter[:2000]))

    # Outreach emails
    for i, draft in enumerate(drafts, start=1):
        children.append(_heading(f"Outreach Email {i}"))
        children.append(_paragraph(
            f"To: {draft.contact.name} ({draft.contact.title})\n"
            f"Email: {draft.contact.email}\n"
            f"Hook: {draft.contact.hook}"
        ))
        children.append(_paragraph(f"Subject: {draft.subject}\n\n{draft.body}"))

    return children


def _heading(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"text": {"content": text}}]},
    }


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"text": {"content": text[:2000]}}]},
    }


def check_approvals(notifier: NotionNotifier) -> list[ApprovedItem]:
    """Query Notion for items that have been approved but not yet executed.

    Filters: Status="Staged" AND any approval checkbox is checked.
    """
    if not notifier.database_id or not notifier._token:
        return []

    try:
        client = notifier._get_client()
        filter_body = {
            "filter": {
                "and": [
                    {"property": "Status", "select": {"equals": "Staged"}},
                    {
                        "or": [
                            {"property": "Apply Approved", "checkbox": {"equals": True}},
                            {"property": "Outreach 1 Approved", "checkbox": {"equals": True}},
                            {"property": "Outreach 2 Approved", "checkbox": {"equals": True}},
                        ]
                    },
                ]
            }
        }

        resp = client.post(
            f"/databases/{notifier.database_id}/query",
            json=filter_body,
        )
        resp.raise_for_status()
        data = resp.json()

        items: list[ApprovedItem] = []
        for page in data.get("results", []):
            props = page.get("properties", {})
            company = _get_text_prop(props, "Company")

            items.append(ApprovedItem(
                page_id=page["id"],
                fingerprint="",  # Will be resolved from DB by URL
                company=company,
                apply_approved=_get_checkbox(props, "Apply Approved"),
                outreach_1_approved=_get_checkbox(props, "Outreach 1 Approved"),
                outreach_2_approved=_get_checkbox(props, "Outreach 2 Approved"),
            ))

        log.info("Found %d approved items in Notion", len(items))
        return items

    except Exception as e:
        log.error("Failed to check approvals: %s", e)
        return []


def resolve_fingerprint(conn: sqlite3.Connection, page_id: str) -> str:
    """Look up the listing fingerprint from a Notion page_id."""
    row = conn.execute(
        "SELECT fingerprint FROM job_listings WHERE notion_page_id = ?", (page_id,)
    ).fetchone()
    return row[0] if row else ""


def execute_approved(
    item: ApprovedItem,
    candidate: Candidate,
    conn: sqlite3.Connection,
    notifier: NotionNotifier,
    *,
    snapshot_store=None,
    data_dir: Path | None = None,
) -> ExecutionResult:
    """Execute approved actions for a single item.

    Applications are auto-submitted during the PREPARE phase.
    This method only handles outreach email sending after operator approval.

    Z2-S2.3: If snapshot_store is provided, each outreach send is preceded by
    snapshot.verify_or_raise().  On SnapshotMismatch the send is BLOCKED,
    the listing is marked snapshot_drift in Notion, and a Discord alert file
    is written.
    """
    result = ExecutionResult(page_id=item.page_id, errors=[])
    fingerprint = resolve_fingerprint(conn, item.page_id)

    if not fingerprint:
        result.errors.append(f"No fingerprint found for page {item.page_id}")
        return result

    # Outreach emails
    for slot, approved in [(1, item.outreach_1_approved), (2, item.outreach_2_approved)]:
        if not approved:
            continue

        # Check if already sent
        row = conn.execute(
            "SELECT id, draft_subject, draft_email, email, name, title "
            "FROM outreach_contacts WHERE listing_fingerprint = ? AND slot = ? AND sent = 0",
            (fingerprint, slot),
        ).fetchone()

        if not row:
            log.info("Outreach slot %d for %s: already sent or no draft", slot, item.company)
            continue

        # Row columns: id, draft_subject, draft_email (body), email (to), name, title
        col_count = len(row)
        contact_id = row[0]
        subject = row[1]
        body = row[2]
        to_email = row[3]
        contact_name = row[4] if col_count > 4 else ""
        contact_title = row[5] if col_count > 5 else ""

        # --- Snapshot verification (Z2-S2.3) ---
        if snapshot_store is not None:
            from .snapshot import SnapshotMismatch
            current_payload = {
                "slot": slot,
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "name": contact_name,
                "title": contact_title,
            }
            snapshot_key = f"{item.page_id}:slot{slot}"
            try:
                snapshot_store.verify_or_raise(snapshot_key, current_payload)
            except SnapshotMismatch as mismatch:
                log.error(
                    "SNAPSHOT DRIFT blocked send for page %s slot %d: %s",
                    item.page_id, slot, mismatch,
                )
                result.snapshot_drift = True
                result.errors = result.errors or []
                result.errors.append(f"snapshot_drift:slot{slot}")
                # Mark drift in Notion
                try:
                    notifier.update_status_sync(item.page_id, "Snapshot Drift")
                except Exception:
                    pass
                # Write Discord alert file
                _write_drift_alert(item, slot, mismatch, data_dir or DATA_DIR)
                continue  # Do NOT send

        try:
            from bridge.services.gmail_interface import send_email
            success = send_email(to=to_email, subject=subject, body=body, from_account="agent")

            if success:
                conn.execute(
                    "UPDATE outreach_contacts SET sent = 1, sent_at = datetime('now') WHERE id = ?",
                    (contact_id,),
                )
                conn.commit()

                # Mark sent in Notion
                _mark_outreach_sent(notifier, item.page_id, slot)

                # Mark snapshot as sent
                if snapshot_store is not None:
                    try:
                        snapshot_store.mark_sent(f"{item.page_id}:slot{slot}")
                    except Exception:
                        pass

                if slot == 1:
                    result.outreach_1_sent = True
                else:
                    result.outreach_2_sent = True

                log.info("Outreach email %d sent to %s for %s", slot, to_email, item.company)
            else:
                result.errors = result.errors or []
                result.errors.append(f"Gmail send_email returned False for slot {slot}")

        except ImportError:
            result.errors = result.errors or []
            result.errors.append("Gmail interface not available — google libs not installed")
        except Exception as e:
            result.errors = result.errors or []
            result.errors.append(f"Outreach email {slot} send failed: {e}")

    # Update overall status if anything was executed
    if result.outreach_1_sent or result.outreach_2_sent:
        try:
            notifier.update_status_sync(item.page_id, "Outreach Sent")
        except Exception:
            pass

    return result


def _write_drift_alert(
    item: ApprovedItem,
    slot: int,
    mismatch: "SnapshotMismatch",
    data_dir: Path,
) -> None:
    """Write a Discord alert file for snapshot drift detection."""
    import json
    import os
    import tempfile
    from datetime import datetime, timezone

    messages_dir = data_dir / "service_messages"
    messages_dir.mkdir(parents=True, exist_ok=True)

    text = (
        f"**SNAPSHOT DRIFT DETECTED**\n"
        f"Page: `{item.page_id}` | Company: {item.company} | Slot: {slot}\n"
        f"Approved hash: `{mismatch.approved_hash[:16]}...`\n"
        f"Current hash:  `{mismatch.current_hash[:16]}...`\n"
        f"The outreach email was modified after you approved it. Send BLOCKED.\n"
        f"Status set to `Snapshot Drift` in Notion. Review and re-approve."
    )

    alert = {
        "type": "snapshot_drift",
        "service": "job_search_execute",
        "message": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    alert_path = messages_dir / f"snapshot_drift_{item.page_id[:8]}_{ts}.json"

    fd, tmp = tempfile.mkstemp(dir=messages_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(alert, f, indent=2)
        os.replace(tmp, alert_path)
        log.info("Drift alert written: %s", alert_path.name)
    except Exception as e:
        log.error("Failed to write drift alert: %s", e)
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _mark_outreach_sent(notifier: NotionNotifier, page_id: str, slot: int) -> None:
    """Mark an outreach email as sent in Notion."""
    try:
        client = notifier._get_client()
        props = {f"Outreach {slot} Sent": {"checkbox": True}}
        client.patch(f"/pages/{page_id}", json={"properties": props})
    except Exception as e:
        log.warning("Failed to mark Outreach %d Sent in Notion: %s", slot, e)


# -- Property extraction helpers --

def _get_checkbox(props: dict, name: str) -> bool:
    prop = props.get(name, {})
    return prop.get("checkbox", False)


def _get_text_prop(props: dict, name: str) -> str:
    prop = props.get(name, {})
    rich_text = prop.get("rich_text", [])
    if rich_text and isinstance(rich_text, list):
        return rich_text[0].get("text", {}).get("content", "")
    return ""


def _get_title_prop(props: dict, name: str) -> str:
    prop = props.get(name, {})
    title = prop.get("title", [])
    if title and isinstance(title, list):
        return title[0].get("text", {}).get("content", "")
    return ""


def _get_url_prop(props: dict, name: str) -> str:
    prop = props.get(name, {})
    return prop.get("url", "")
