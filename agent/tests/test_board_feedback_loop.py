"""Tests for Board Phase 3 WS2 feedback loops (#2392).

Covers the close-the-loop seam: a closed board-generated issue (producer:
GitHub webhook) writes an outcome record (consumer: BoardRunStore) which the
CEO review and the next board deliberation both read.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock


from bridge.board_run_store import BoardRunStore
from bridge.webhook_receiver import WebhookReceiver


def _signed(receiver: WebhookReceiver, payload: dict):
    body = json.dumps(payload).encode()
    import hashlib
    import hmac
    sig = "sha256=" + hmac.new(receiver._secret, body, hashlib.sha256).hexdigest()
    return body, sig


class TestWebhookClosesLoop:
    def test_closed_board_issue_records_outcome(self, tmp_path):
        store = BoardRunStore(str(tmp_path))
        rec = store.record_run(
            session_id="s", question="q", synthesis="x", success=True,
            board_run_id="board-20260601-abcdef12",
        )
        receiver = WebhookReceiver(webhook_secret="secret")
        receiver.set_board_run_store(store)

        payload = {
            "action": "closed",
            "issue": {
                "number": 4242,
                "title": "Board directive: ship dashboard",
                "body": "Implements the board plan.\n\nboard_run_id: board-20260601-abcdef12",
                "created_at": "2026-06-01T00:00:00+00:00",
                "closed_at": "2026-06-02T00:00:00+00:00",
                "labels": [],
            },
        }
        body, sig = _signed(receiver, payload)
        result = asyncio.run(receiver.handle_webhook(body=body, signature=sig, event_type="issues"))
        assert result["action"] == "closed"

        outcomes = store.get_outcomes(rec.board_run_id)
        assert any(c["issue"] == 4242 for c in outcomes["closed_issues"])
        # link_issue also fired (idempotent linkage).
        assert 4242 in store.get_run(rec.board_run_id).linked_issues

    def test_closed_issue_without_board_run_id_is_noop(self, tmp_path):
        store = BoardRunStore(str(tmp_path))
        receiver = WebhookReceiver(webhook_secret="secret")
        receiver.set_board_run_store(store)
        payload = {
            "action": "closed",
            "issue": {"number": 1, "title": "Random", "body": "no tag here", "labels": []},
        }
        body, sig = _signed(receiver, payload)
        result = asyncio.run(receiver.handle_webhook(body=body, signature=sig, event_type="issues"))
        assert result["action"] == "closed"
        # No outcomes files written.
        assert list(store.directory.glob("*-outcomes.json")) == []

    def test_no_store_wired_is_safe(self, tmp_path):
        receiver = WebhookReceiver(webhook_secret="secret")  # no store
        payload = {
            "action": "closed",
            "issue": {"number": 1, "title": "X", "body": "board_run_id: board-20260601-abcdef12", "labels": []},
        }
        body, sig = _signed(receiver, payload)
        result = asyncio.run(receiver.handle_webhook(body=body, signature=sig, event_type="issues"))
        assert result["action"] == "closed"


class TestCEOReviewSurfacesRate:
    def test_implementation_rate_in_narration(self, tmp_path):
        from bridge.services.weekly_ceo_review import WeeklyCEOReviewService

        store = BoardRunStore(str(tmp_path))
        rec = store.record_run(session_id="s", question="q", synthesis="x", success=True)
        store.link_issue(rec.board_run_id, 1)
        store.link_issue(rec.board_run_id, 2)
        store.record_issue_closed(rec.board_run_id, 1)

        registry = MagicMock()
        registry.get.return_value = {"name": "weekly-ceo-review"}
        registry.trigger.return_value = "run-123"
        engine = MagicMock()

        svc = WeeklyCEOReviewService(
            data_dir=str(tmp_path),
            workflow_registry=registry,
            workflow_engine=engine,
            board_run_store=store,
        )
        result = asyncio.run(svc.run())
        assert result.ok
        assert "Board: 1/2 issues closed" in result.narration
        # The implementation-rate stats were injected as workflow input.
        call_inputs = registry.trigger.call_args[0][1]
        assert "board_implementation_rate" in call_inputs
        assert call_inputs["board_implementation_rate"]["total_generated"] == 2


class TestBoardOutcomeContextInjection:
    def test_outcome_summary_prepended_to_question(self, tmp_path):
        # Build a handler whose store has prior outcomes, then verify the
        # board route receives the augmented question while persistence keeps
        # the original.
        import tests.test_commands_board as tcb

        handler = tcb._make_handler()
        app = tcb._make_fake_app(data_dir=str(tmp_path))
        app._config.data_dir = str(tmp_path)
        handler.set_app(app)

        # Seed a prior run + outcome so outcome_summary_for_prompt is non-empty.
        store = BoardRunStore(str(tmp_path))
        prior = store.record_run(session_id="old", question="prior", synthesis="x", success=True)
        store.link_issue(prior.board_run_id, 9)
        store.record_issue_closed(prior.board_run_id, 9)

        from unittest.mock import AsyncMock
        registry = MagicMock()
        registry.route = AsyncMock(return_value=tcb._make_team_result(manager_output="ok"))
        handler.set_departments(registry)

        asyncio.run(handler._cmd_board("chat-1", "New strategic question?"))

        routed_q = registry.route.call_args[0][1]
        assert "Prior board-run outcomes" in routed_q
        assert "New strategic question?" in routed_q
