"""Sprint 02.10 Phase 3 — SnapshotStore detects edit-after-approval drift.

The Z2-S2.3 disaster scenario:
  1. Agent stages outreach in Notion at 09:00.
  2. Operator approves at 11:00.
  3. Something edits the body at 13:00.
  4. EXECUTE fires at 14:00 — would silently send the edited version.

With Sprint 02.10 wiring, step 4 raises SnapshotMismatch on Path B
(``execute_approved`` via ``JobSearchAgent.execute``).

Path A coverage was removed in Sprint P4.2 (#1728) when the
``send_outreach_email`` Z4 tool was deleted — the outreach_department
that hosted it was retired in P4.1 (#1727 / PR #1804) so the tool had
no remaining production caller.
"""
from __future__ import annotations

import pytest

from job_search import quality_wiring
from job_search.snapshot import SnapshotStore


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BUMBA_JOB_SEARCH_DATA_DIR", str(tmp_path))
    quality_wiring.reset_caches()
    yield tmp_path
    quality_wiring.reset_caches()


class TestPathBExecuteApprovedSnapshotGate:
    def test_drift_blocks_execute_approved_path_b(
        self, isolated_data_dir, monkeypatch, tmp_path
    ):
        import sqlite3

        from job_search.approval import ApprovedItem, execute_approved
        from job_search.criteria import Candidate
        from job_search.notifier import NotionNotifier

        store = SnapshotStore(isolated_data_dir)
        page_id = "page-drift"
        snapshot_key = f"{page_id}:slot1"
        approved_payload = {
            "slot": 1,
            "to_email": "exec@example.com",
            "subject": "Original Subject",
            "body": "Original body content.",
            "name": "Operator",
            "title": "Manager",
        }
        store.record_approval(snapshot_key, approved_payload)

        # Build a sqlite db with one outreach contact whose draft body has
        # been edited compared to approval-time payload.
        db_path = tmp_path / "exec.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE job_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT, notion_page_id TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE outreach_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_fingerprint TEXT, name TEXT, title TEXT, email TEXT,
                company TEXT, personalization_hook TEXT, slot INTEGER,
                draft_subject TEXT, draft_email TEXT,
                sent INTEGER DEFAULT 0, sent_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO job_listings (fingerprint, notion_page_id) VALUES (?, ?)",
            ("fp1", page_id),
        )
        conn.execute(
            "INSERT INTO outreach_contacts "
            "(listing_fingerprint, name, title, email, company, slot, "
            "draft_subject, draft_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "fp1",
                "Operator",
                "Manager",
                "exec@example.com",
                "Acme",
                1,
                "Original Subject",
                "EDITED body — drift!",
            ),
        )
        conn.commit()

        # Patch send_email to detect whether the send happened.
        send_called = {"value": False}

        def fake_send(**kwargs):
            send_called["value"] = True
            return True

        monkeypatch.setattr(
            "bridge.services.gmail_interface.send_email", fake_send
        )
        # Patch notifier sync update so we don't hit Notion.
        monkeypatch.setattr(
            NotionNotifier, "update_status_sync", lambda self, *a, **k: None
        )

        candidate = Candidate(
            name="Test", email="t@t.com", phone="",
            cover_letter_mode="skip",
        )
        item = ApprovedItem(
            page_id=page_id,
            fingerprint="fp1",
            company="Acme",
            apply_approved=False,
            outreach_1_approved=True,
            outreach_2_approved=False,
        )

        result = execute_approved(
            item,
            candidate,
            conn,
            NotionNotifier(),
            snapshot_store=store,
            data_dir=isolated_data_dir,
        )

        assert result.snapshot_drift is True
        assert result.outreach_1_sent is False
        assert send_called["value"] is False, (
            "send_email was called despite snapshot drift"
        )
        # Snapshot store records the drift.
        record = store.get_record(snapshot_key)
        assert record["status"] == "snapshot_drift"
        conn.close()
