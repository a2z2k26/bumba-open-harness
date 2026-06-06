"""Tests for Notion approval workflow."""

import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from job_search.approval import (
    RUBRIC_PROPERTY_NAMES,
    ApprovedItem,
    RubricStageData,
    _build_page_content,
    _build_rubric_properties,
    _build_staged_properties,
    _get_checkbox,
    _get_text_prop,
    _get_title_prop,
    _get_url_prop,
    _heading,
    _looks_like_missing_rubric_column,
    _paragraph,
    check_approvals,
    execute_approved,
    resolve_fingerprint,
    stage_listing,
)
from job_search.boards.base import JobListing
from job_search.notifier import NotionNotifier
from job_search.outreach import Contact, OutreachDraft


@pytest.fixture
def listing():
    return JobListing(
        url="https://example.com/jobs/1",
        title="Senior Designer",
        company="Acme Corp",
        board="weworkremotely",
        location="Remote",
        compensation="$120k",
        description="Design amazing products",
    )


@pytest.fixture
def contacts():
    return [
        Contact(name="Jane Smith", title="CTO", email="jane@acme.com", company="Acme Corp", hook="Design system launch"),
        Contact(name="Bob Jones", title="VP Eng", email="bob@acme.com", company="Acme Corp", hook="Conference talk"),
    ]


@pytest.fixture
def drafts(contacts):
    return [
        OutreachDraft(contact=contacts[0], subject="Quick intro", body="Hi Jane...", slot=1),
        OutreachDraft(contact=contacts[1], subject="Following up", body="Hi Bob...", slot=2),
    ]


@pytest.fixture
def notifier():
    n = NotionNotifier(database_id="test-db-id", token="test-token")
    return n


@pytest.fixture
def db(tmp_path):
    """Create an in-memory DB with the job_listings schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE job_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            fingerprint TEXT NOT NULL,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            board TEXT NOT NULL,
            ats TEXT,
            location TEXT,
            remote TEXT,
            compensation TEXT,
            description TEXT,
            raw_json TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            applied_at TEXT,
            notion_page_id TEXT,
            cover_letter TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE outreach_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_fingerprint TEXT NOT NULL,
            name TEXT NOT NULL,
            title TEXT NOT NULL,
            email TEXT NOT NULL,
            company TEXT NOT NULL,
            personalization_hook TEXT,
            draft_subject TEXT,
            draft_email TEXT,
            slot INTEGER NOT NULL,
            approved INTEGER DEFAULT 0,
            sent INTEGER DEFAULT 0,
            sent_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


class TestBuildStagedProperties:
    def test_basic_properties(self, listing, contacts):
        props = _build_staged_properties(listing, "greenhouse", contacts)
        assert props["Title"]["title"][0]["text"]["content"] == "Senior Designer"
        assert props["Company"]["rich_text"][0]["text"]["content"] == "Acme Corp"
        assert props["URL"]["url"] == "https://example.com/jobs/1"
        assert props["Status"]["select"]["name"] == "Staged"
        assert props["Apply Approved"]["checkbox"] is False
        assert props["ATS"]["select"]["name"] == "greenhouse"

    def test_outreach_properties(self, listing, contacts):
        props = _build_staged_properties(listing, "unknown", contacts)
        assert props["Outreach 1 Name"]["rich_text"][0]["text"]["content"] == "Jane Smith"
        assert props["Outreach 1 Email"]["email"] == "jane@acme.com"
        assert props["Outreach 2 Name"]["rich_text"][0]["text"]["content"] == "Bob Jones"

    def test_no_ats_property_for_unknown(self, listing, contacts):
        props = _build_staged_properties(listing, "unknown", contacts)
        assert "ATS" not in props

    def test_no_ats_property_for_empty(self, listing, contacts):
        props = _build_staged_properties(listing, "", contacts)
        assert "ATS" not in props

    def test_checkboxes_all_false(self, listing, contacts):
        props = _build_staged_properties(listing, "", contacts)
        assert props["Apply Approved"]["checkbox"] is False
        assert props["Outreach 1 Approved"]["checkbox"] is False
        assert props["Outreach 1 Sent"]["checkbox"] is False
        assert props["Outreach 2 Approved"]["checkbox"] is False
        assert props["Outreach 2 Sent"]["checkbox"] is False


# Sprint 06.04 — additive Notion rubric columns.
class TestBuildRubricProperties:
    """Sprint 06.04 — five additive rubric columns for Notion."""

    def _sample_rubric(self) -> RubricStageData:
        return RubricStageData(
            letter_grade="B",
            weighted_score=3.4,
            rationale="Strong design role; comp slightly below target.",
            evaluated_at="2026-04-30T12:34:56+00:00",
            decision="pending",
        )

    def test_emits_all_five_columns_when_rubric_present(self):
        rubric = self._sample_rubric()
        props = _build_rubric_properties(rubric=rubric, rubric_gate_enabled=True)
        assert props["rubric_grade"]["select"]["name"] == "B"
        assert props["rubric_score"]["number"] == 3.4
        assert (
            props["rubric_rationale"]["rich_text"][0]["text"]["content"]
            == "Strong design role; comp slightly below target."
        )
        assert props["rubric_decision"]["select"]["name"] == "pending"
        assert (
            props["rubric_evaluated_at"]["date"]["start"] == "2026-04-30T12:34:56+00:00"
        )
        # All 5 expected keys present.
        for key in RUBRIC_PROPERTY_NAMES:
            assert key in props

    def test_rationale_truncated_to_2000_chars(self):
        rubric = RubricStageData(
            letter_grade="A",
            weighted_score=4.7,
            rationale="x" * 5000,
            evaluated_at="2026-04-30T00:00:00+00:00",
        )
        props = _build_rubric_properties(rubric=rubric, rubric_gate_enabled=True)
        assert len(props["rubric_rationale"]["rich_text"][0]["text"]["content"]) == 2000

    def test_no_rubric_and_gate_disabled_emits_nothing(self):
        # Backward-compat: pre-rubric rows with the gate off must not gain
        # any rubric columns (avoids polluting historical Notion entries).
        props = _build_rubric_properties(rubric=None, rubric_gate_enabled=False)
        assert props == {}

    def test_no_rubric_but_gate_enabled_marks_not_applicable(self):
        # Gate is on but this row was never evaluated (eval failure / opt-out).
        # Operator must see "not_applicable" so they know the gate ran.
        props = _build_rubric_properties(rubric=None, rubric_gate_enabled=True)
        assert props == {
            "rubric_decision": {"select": {"name": "not_applicable"}},
        }

    def test_score_coerced_to_float(self):
        # Defensive: SQLite may surface int — Notion number field expects
        # a number, but we explicitly cast to float to keep the schema
        # type stable.
        rubric = RubricStageData(
            letter_grade="C",
            weighted_score=2,  # type: ignore[arg-type]
            rationale="ok",
            evaluated_at="2026-04-30T00:00:00+00:00",
        )
        props = _build_rubric_properties(rubric=rubric, rubric_gate_enabled=True)
        assert isinstance(props["rubric_score"]["number"], float)
        assert props["rubric_score"]["number"] == 2.0


class TestBuildStagedPropertiesWithRubric:
    """Sprint 06.04 — _build_staged_properties wires the rubric helper in."""

    def test_includes_rubric_when_provided(self, listing, contacts):
        rubric = RubricStageData(
            letter_grade="A",
            weighted_score=4.5,
            rationale="Excellent fit.",
            evaluated_at="2026-04-30T10:00:00+00:00",
        )
        props = _build_staged_properties(
            listing, "greenhouse", contacts, rubric=rubric, rubric_gate_enabled=True,
        )
        assert props["rubric_grade"]["select"]["name"] == "A"
        assert props["rubric_score"]["number"] == 4.5
        assert props["rubric_decision"]["select"]["name"] == "pending"

    def test_omits_rubric_for_pre_rubric_listing(self, listing, contacts):
        # Backward-compat: gate disabled, no rubric → no rubric columns.
        props = _build_staged_properties(listing, "greenhouse", contacts)
        for key in RUBRIC_PROPERTY_NAMES:
            assert key not in props

    def test_gate_enabled_no_rubric_marks_not_applicable(self, listing, contacts):
        props = _build_staged_properties(
            listing, "greenhouse", contacts, rubric=None, rubric_gate_enabled=True,
        )
        assert props["rubric_decision"]["select"]["name"] == "not_applicable"
        assert "rubric_grade" not in props
        assert "rubric_score" not in props


class TestStageListingRubricFallback:
    """Sprint 06.04 — defensive write-with-warn when Notion DB lacks columns."""

    def _rubric(self) -> RubricStageData:
        return RubricStageData(
            letter_grade="B",
            weighted_score=3.0,
            rationale="Solid",
            evaluated_at="2026-04-30T00:00:00+00:00",
        )

    def test_success_with_rubric(self, listing, contacts, drafts, notifier):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "page-rub-1"}
        mock_client.post.return_value = mock_resp

        with patch.object(notifier, "_get_client", return_value=mock_client):
            page_id = stage_listing(
                notifier, listing, "greenhouse", "cl", contacts, drafts,
                rubric=self._rubric(), rubric_gate_enabled=True,
            )

        assert page_id == "page-rub-1"
        # First call must include all 5 rubric properties.
        first_body = mock_client.post.call_args_list[0][1]["json"]
        for key in RUBRIC_PROPERTY_NAMES:
            assert key in first_body["properties"]

    def test_retry_strips_rubric_when_column_missing(
        self, listing, contacts, drafts, notifier,
    ):
        # First POST raises an error mentioning rubric_grade (Notion
        # validation_error when a property doesn't exist on the DB).
        # Second POST (without rubric props) succeeds.
        mock_client = MagicMock()
        ok_resp = MagicMock()
        ok_resp.json.return_value = {"id": "page-retry-1"}

        first_err = Exception(
            "Notion API 400: rubric_grade is not a property that exists",
        )
        mock_client.post.side_effect = [first_err, ok_resp]

        with patch.object(notifier, "_get_client", return_value=mock_client):
            page_id = stage_listing(
                notifier, listing, "greenhouse", "cl", contacts, drafts,
                rubric=self._rubric(), rubric_gate_enabled=True,
            )

        assert page_id == "page-retry-1"
        assert mock_client.post.call_count == 2
        # Retry must NOT include any rubric properties.
        retry_body = mock_client.post.call_args_list[1][1]["json"]
        for key in RUBRIC_PROPERTY_NAMES:
            assert key not in retry_body["properties"]
        # But non-rubric properties survive.
        assert retry_body["properties"]["Title"]["title"][0]["text"]["content"] == (
            "Senior Designer"
        )

    def test_non_rubric_failure_does_not_retry(
        self, listing, contacts, drafts, notifier,
    ):
        # An error unrelated to rubric columns must NOT trigger a retry —
        # otherwise we'd silently mask real failures.
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("Notion API 500: server unavailable")

        with patch.object(notifier, "_get_client", return_value=mock_client):
            page_id = stage_listing(
                notifier, listing, "greenhouse", "cl", contacts, drafts,
                rubric=self._rubric(), rubric_gate_enabled=True,
            )

        assert page_id is None
        assert mock_client.post.call_count == 1

    def test_no_rubric_no_retry_path_taken(
        self, listing, contacts, drafts, notifier,
    ):
        # When no rubric data is staged, a column-missing-style error
        # is treated as a real failure (we have nothing rubric-specific
        # to strip).
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception(
            "Notion API 400: rubric_grade is not a property that exists",
        )

        with patch.object(notifier, "_get_client", return_value=mock_client):
            page_id = stage_listing(
                notifier, listing, "greenhouse", "cl", contacts, drafts,
                rubric=None, rubric_gate_enabled=False,
            )

        assert page_id is None
        # No retry — rubric props weren't in the first body.
        assert mock_client.post.call_count == 1


class TestRubricFallbackHeuristic:
    def test_recognises_rubric_property_in_error(self):
        err = Exception("validation_error: rubric_grade is unknown")
        assert _looks_like_missing_rubric_column(err) is True

    def test_ignores_unrelated_errors(self):
        err = Exception("connection reset by peer")
        assert _looks_like_missing_rubric_column(err) is False


class TestBuildPageContent:
    def test_includes_description(self, listing, drafts):
        children = _build_page_content(listing, "", drafts)
        assert any("Job Description" in str(c) for c in children)

    def test_includes_cover_letter(self, listing, drafts):
        children = _build_page_content(listing, "Dear Hiring Manager...", drafts)
        assert any("Cover Letter" in str(c) for c in children)

    def test_includes_outreach_drafts(self, listing, drafts):
        children = _build_page_content(listing, "", drafts)
        assert any("Outreach Email 1" in str(c) for c in children)
        assert any("Outreach Email 2" in str(c) for c in children)

    def test_no_cover_letter_section_when_empty(self, listing, drafts):
        children = _build_page_content(listing, "", drafts)
        assert not any("Cover Letter" in str(c) for c in children)


class TestHelperFunctions:
    def test_heading(self):
        h = _heading("Test")
        assert h["type"] == "heading_2"
        assert h["heading_2"]["rich_text"][0]["text"]["content"] == "Test"

    def test_paragraph(self):
        p = _paragraph("Body text")
        assert p["type"] == "paragraph"
        assert p["paragraph"]["rich_text"][0]["text"]["content"] == "Body text"

    def test_paragraph_truncates(self):
        p = _paragraph("x" * 3000)
        assert len(p["paragraph"]["rich_text"][0]["text"]["content"]) == 2000


class TestPropertyExtractors:
    def test_get_checkbox_true(self):
        props = {"Apply Approved": {"checkbox": True}}
        assert _get_checkbox(props, "Apply Approved") is True

    def test_get_checkbox_false(self):
        props = {"Apply Approved": {"checkbox": False}}
        assert _get_checkbox(props, "Apply Approved") is False

    def test_get_checkbox_missing(self):
        assert _get_checkbox({}, "Missing") is False

    def test_get_text_prop(self):
        props = {"Company": {"rich_text": [{"text": {"content": "Acme"}}]}}
        assert _get_text_prop(props, "Company") == "Acme"

    def test_get_text_prop_empty(self):
        assert _get_text_prop({}, "Missing") == ""

    def test_get_title_prop(self):
        props = {"Title": {"title": [{"text": {"content": "Designer"}}]}}
        assert _get_title_prop(props, "Title") == "Designer"

    def test_get_url_prop(self):
        props = {"URL": {"url": "https://example.com"}}
        assert _get_url_prop(props, "URL") == "https://example.com"


class TestStageListing:
    def test_success(self, listing, contacts, drafts, notifier):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "page-123"}
        mock_client.post.return_value = mock_resp

        with patch.object(notifier, "_get_client", return_value=mock_client):
            page_id = stage_listing(notifier, listing, "greenhouse", "cover letter", contacts, drafts)

        assert page_id == "page-123"
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/pages"

    def test_failure_returns_none(self, listing, contacts, drafts, notifier):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("API error")

        with patch.object(notifier, "_get_client", return_value=mock_client):
            page_id = stage_listing(notifier, listing, "", "", contacts, drafts)

        assert page_id is None


class TestCheckApprovals:
    def test_returns_approved_items(self, notifier):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": "page-abc",
                    "properties": {
                        "Title": {"title": [{"text": {"content": "Designer"}}]},
                        "Company": {"rich_text": [{"text": {"content": "Acme"}}]},
                        "URL": {"url": "https://example.com"},
                        "Apply Approved": {"checkbox": True},
                        "Outreach 1 Approved": {"checkbox": False},
                        "Outreach 2 Approved": {"checkbox": True},
                    },
                }
            ]
        }
        mock_client.post.return_value = mock_resp

        with patch.object(notifier, "_get_client", return_value=mock_client):
            items = check_approvals(notifier)

        assert len(items) == 1
        assert items[0].page_id == "page-abc"
        assert items[0].apply_approved is True
        assert items[0].outreach_1_approved is False
        assert items[0].outreach_2_approved is True

    @patch("job_search.notifier._load_notion_token", return_value="")
    def test_returns_empty_without_token(self, mock_load):
        notifier = NotionNotifier(database_id="test", token="")
        items = check_approvals(notifier)
        assert items == []

    def test_returns_empty_without_db_id(self):
        notifier = NotionNotifier(database_id="", token="test")
        items = check_approvals(notifier)
        assert items == []

    def test_handles_api_error(self, notifier):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("API down")

        with patch.object(notifier, "_get_client", return_value=mock_client):
            items = check_approvals(notifier)

        assert items == []


class TestResolveFingerprint:
    def test_found(self, db):
        db.execute(
            "INSERT INTO job_listings (url, fingerprint, title, company, board, notion_page_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("https://example.com", "fp-123", "Designer", "Acme", "wwr", "page-abc"),
        )
        db.commit()
        assert resolve_fingerprint(db, "page-abc") == "fp-123"

    def test_not_found(self, db):
        assert resolve_fingerprint(db, "page-missing") == ""


class TestExecuteApproved:
    def test_apply_approved_ignored_in_execute(self, db, notifier):
        """Applications auto-submit during PREPARE. Execute cron ignores apply_approved."""
        db.execute(
            "INSERT INTO job_listings (url, fingerprint, title, company, board, notion_page_id, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("https://example.com", "fp-1", "Designer", "Acme", "wwr", "page-1", "applied"),
        )
        db.commit()

        item = ApprovedItem(
            page_id="page-1", fingerprint="", company="Acme",
            apply_approved=True, outreach_1_approved=False, outreach_2_approved=False,
        )

        result = execute_approved(item, MagicMock(), db, notifier)

        # apply_approved is ignored — no status change, no action
        assert result.application_submitted is False
        row = db.execute("SELECT status FROM job_listings WHERE fingerprint = 'fp-1'").fetchone()
        assert row[0] == "applied"

    def test_outreach_sends_email(self, db, notifier):
        db.execute(
            "INSERT INTO job_listings (url, fingerprint, title, company, board, notion_page_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("https://example.com", "fp-2", "Designer", "Acme", "wwr", "page-2"),
        )
        db.execute(
            "INSERT INTO outreach_contacts (listing_fingerprint, name, title, email, company, draft_subject, draft_email, slot, sent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fp-2", "Jane", "CTO", "jane@acme.com", "Acme", "Subject", "Body", 1, 0),
        )
        db.commit()

        item = ApprovedItem(
            page_id="page-2", fingerprint="", company="Acme",
            apply_approved=False, outreach_1_approved=True, outreach_2_approved=False,
        )

        with patch("job_search.approval.resolve_fingerprint", return_value="fp-2"), \
             patch("bridge.services.gmail_interface.send_email", return_value=True) as mock_send, \
             patch.object(notifier, "_get_client", return_value=MagicMock()):
            result = execute_approved(item, MagicMock(), db, notifier)

        assert result.outreach_1_sent is True
        mock_send.assert_called_once_with(
            to="jane@acme.com", subject="Subject", body="Body", from_account="agent"
        )

    def test_skips_already_sent_outreach(self, db, notifier):
        db.execute(
            "INSERT INTO job_listings (url, fingerprint, title, company, board, notion_page_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("https://example.com", "fp-3", "Designer", "Acme", "wwr", "page-3"),
        )
        db.execute(
            "INSERT INTO outreach_contacts (listing_fingerprint, name, title, email, company, draft_subject, draft_email, slot, sent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fp-3", "Jane", "CTO", "jane@acme.com", "Acme", "Subject", "Body", 1, 1),  # already sent
        )
        db.commit()

        item = ApprovedItem(
            page_id="page-3", fingerprint="", company="Acme",
            apply_approved=False, outreach_1_approved=True, outreach_2_approved=False,
        )

        with patch("job_search.approval.resolve_fingerprint", return_value="fp-3"):
            result = execute_approved(item, MagicMock(), db, notifier)

        assert result.outreach_1_sent is False

    def test_no_fingerprint_returns_error(self, db, notifier):
        item = ApprovedItem(
            page_id="page-missing", fingerprint="", company="Acme",
            apply_approved=True, outreach_1_approved=False, outreach_2_approved=False,
        )
        result = execute_approved(item, MagicMock(), db, notifier)
        assert result.errors
        assert "No fingerprint" in result.errors[0]

    def test_gmail_send_failure_handled(self, db, notifier):
        """When gws CLI send_email returns False, error is recorded but doesn't crash."""
        db.execute(
            "INSERT INTO job_listings (url, fingerprint, title, company, board, notion_page_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("https://example.com", "fp-4", "Designer", "Acme", "wwr", "page-4"),
        )
        db.execute(
            "INSERT INTO outreach_contacts (listing_fingerprint, name, title, email, company, draft_subject, draft_email, slot, sent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fp-4", "Jane", "CTO", "jane@acme.com", "Acme", "Subject", "Body", 1, 0),
        )
        db.commit()

        item = ApprovedItem(
            page_id="page-4", fingerprint="", company="Acme",
            apply_approved=False, outreach_1_approved=True, outreach_2_approved=False,
        )

        with patch("job_search.approval.resolve_fingerprint", return_value="fp-4"), \
             patch("bridge.services.gmail_interface.send_email", return_value=False):
            result = execute_approved(item, MagicMock(), db, notifier)

        # Should have an error but not crash
        assert result.errors
        assert "returned False" in result.errors[0]
