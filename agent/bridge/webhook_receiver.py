"""Inbound GitHub webhook handler.

Verifies HMAC-SHA256 signatures, routes events to typed handlers,
auto-creates tasks in the task pipeline, and publishes events to EventBus.

Z4/G-PR.1 + G-PR.2 — PR Ship Decision workflow trigger
--------------------------------------------------------
When a ``pull_request.opened`` event is received and a WorkflowRegistry is
attached, the ``pr-ship-decision`` workflow is triggered automatically with the
PR metadata as inputs.  The workflow handles QA + Strategy review, Board
decision, and optional operator gate via its YAML definition.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Board Phase 3 WS2 (#2392) — board-generated issues embed their originating
# board run as ``board_run_id: board-YYYYMMDD-xxxxxxxx`` in the issue body.
_BOARD_RUN_ID_RE = re.compile(r"board_run_id:\s*(board-\d{8}-[0-9a-f]{8})")


class WebhookReceiver:
    """Receive and route GitHub webhook events.

    Parameters
    ----------
    webhook_secret:
        Shared secret used to verify HMAC-SHA256 signatures from GitHub.
    task_pipeline:
        Optional pipeline with ``create_task(**kwargs)`` method. When present,
        qualifying events auto-create tasks. Skipped when ``None``.
    event_bus:
        Optional ``EventBus`` instance. When present, every handled event is
        published as ``webhook.github.<event_type>``. Skipped when ``None``.
    workflow_registry:
        Optional ``WorkflowRegistry``. When present and a WorkflowEngine is
        also attached, PR open events trigger the ``pr-ship-decision`` workflow.
    workflow_engine:
        Optional ``WorkflowEngine`` instance paired with ``workflow_registry``.
    """

    def __init__(
        self,
        webhook_secret: str,
        task_pipeline: Any | None = None,
        event_bus: Any | None = None,
        workflow_registry: Any | None = None,
        workflow_engine: Any | None = None,
    ) -> None:
        self._secret = webhook_secret.encode() if isinstance(webhook_secret, str) else webhook_secret
        self._pipeline = task_pipeline
        self._event_bus = event_bus
        self._workflow_registry = workflow_registry
        self._workflow_engine = workflow_engine
        # Board Phase 3 WS2 (#2392) — optional BoardRunStore. When wired, a
        # closed issue tagged with a board_run_id writes an outcome record so
        # the board's open loop can be evaluated against real outcomes.
        self._board_run_store = None

    def set_board_run_store(self, store: Any) -> None:
        """Wire the BoardRunStore (Board Phase 3 WS2, #2392)."""
        self._board_run_store = store

    # ------------------------------------------------------------------
    # Signature verification
    # ------------------------------------------------------------------

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify the GitHub HMAC-SHA256 signature.

        ``signature`` is the full ``X-Hub-Signature-256`` header value,
        e.g. ``sha256=abc123...``. The ``sha256=`` prefix is stripped before
        comparison. Uses ``hmac.compare_digest`` for constant-time equality.
        """
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        # Strip the "sha256=" prefix if present
        if signature.startswith("sha256="):
            signature = signature[len("sha256="):]
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def handle_webhook(
        self,
        body: bytes,
        signature: str,
        event_type: str,
    ) -> dict[str, Any]:
        """Process an inbound GitHub webhook delivery.

        Returns a response dict suitable for JSON serialisation back to the
        caller.  Raises no exceptions -- errors are returned as dicts with
        an ``error`` key.
        """
        # 1. Verify signature
        if not self.verify_signature(body, signature):
            log.warning("Webhook signature verification failed for event %s", event_type)
            return {"error": "invalid_signature", "status": 401}

        # 2. Parse payload
        try:
            payload: dict[str, Any] = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("Webhook payload parse error: %s", exc)
            return {"error": "invalid_payload", "status": 400}

        # 3. Route to handler
        handler = self._handlers.get(event_type)
        if handler is not None:
            result = await handler(self, payload)
        else:
            result = {"received": True, "event_type": event_type}

        # 4. Publish to EventBus (best-effort)
        self._publish_event(event_type, payload)

        return result

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_ping(self, payload: dict[str, Any]) -> dict[str, Any]:
        log.info("GitHub webhook ping received (zen: %s)", payload.get("zen", ""))
        return {"pong": True}

    async def _handle_pull_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        number = pr.get("number", "?")
        title = pr.get("title", "Untitled")
        author = pr.get("user", {}).get("login", "unknown")
        base_branch = pr.get("base", {}).get("ref", "main")
        head_branch = pr.get("head", {}).get("ref", "")
        repo = payload.get("repository", {}).get("full_name", "")

        if action == "opened":
            await self._create_task(
                title=f"Review PR #{number}: {title}",
                priority="high",
                source="github_webhook",
                metadata={"pr_number": number, "action": action},
            )

            # Z4/G-PR.1+G-PR.2: trigger pr-ship-decision workflow
            run_id = self._trigger_pr_ship_workflow(
                pr_number=str(number),
                pr_title=title,
                author=author,
                base_branch=base_branch,
                head_branch=head_branch,
                repo=repo,
            )
            if run_id:
                log.info(
                    "PR #%s: triggered pr-ship-decision workflow run %s",
                    number,
                    run_id,
                )

        return {"received": True, "event_type": "pull_request", "action": action}

    async def _handle_issues(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        title = issue.get("title", "Untitled")
        labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]

        if action == "opened" and "bug" in labels:
            await self._create_task(
                title=f"Fix bug: {title}",
                priority="high",
                assigned_to="engineering",
                source="github_webhook",
                metadata={"issue_number": issue.get("number"), "labels": labels},
            )

        # Board Phase 3 WS2 (#2392) — close-the-loop. When a board-generated
        # issue closes, record the outcome against its board_run_id so the
        # CEO review can compute implementation rate per board run.
        if action == "closed" and self._board_run_store is not None:
            self._record_board_outcome(issue)

        return {"received": True, "event_type": "issues", "action": action}

    def _record_board_outcome(self, issue: dict[str, Any]) -> None:
        """Extract a board_run_id from a closed issue and record the outcome.

        The board_run_id is embedded in the issue body as ``board_run_id:
        board-YYYYMMDD-xxxxxxxx``. No-op (and never raises) when the issue
        carries no board run id or the store write fails.
        """
        try:
            body = issue.get("body") or ""
            match = _BOARD_RUN_ID_RE.search(body)
            if not match:
                return
            board_run_id = match.group(1)
            number = issue.get("number")
            if number is None:
                return
            self._board_run_store.record_issue_closed(
                board_run_id,
                int(number),
                opened_at=issue.get("created_at"),
                closed_at=issue.get("closed_at"),
            )
            # Keep the run<->issue linkage current even if the issue was
            # created out-of-band (idempotent).
            self._board_run_store.link_issue(board_run_id, int(number))
        except Exception as exc:  # noqa: BLE001 — outcome tracking is best-effort
            log.warning("board outcome recording failed: %s", exc)

    async def _handle_check_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        check_run = payload.get("check_run", {})
        conclusion = check_run.get("conclusion", "")
        name = check_run.get("name", "unknown")

        if conclusion == "failure":
            await self._create_task(
                title=f"Fix failing tests: {name}",
                priority="critical",
                source="github_webhook",
                metadata={"check_name": name, "conclusion": conclusion},
            )

        return {"received": True, "event_type": "check_run", "conclusion": conclusion}

    async def _handle_push(self, payload: dict[str, Any]) -> dict[str, Any]:
        ref = payload.get("ref", "")
        commits = payload.get("commits", [])
        log.info("Push event: %s (%d commits)", ref, len(commits))
        # Push events are published to EventBus but do not create tasks.
        return {"received": True, "event_type": "push", "ref": ref}

    # Handler dispatch table -- maps event_type strings to bound methods.
    _handlers: dict[str, Any] = {
        "ping": _handle_ping,
        "pull_request": _handle_pull_request,
        "issues": _handle_issues,
        "check_run": _handle_check_run,
        "push": _handle_push,
    }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trigger_pr_ship_workflow(
        self,
        pr_number: str,
        pr_title: str,
        author: str = "",
        base_branch: str = "main",
        head_branch: str = "",
        repo: str = "",
    ) -> str | None:
        """Trigger the pr-ship-decision workflow if registry + engine are configured.

        Returns the new run_id or None if the workflow could not be triggered.
        """
        if self._workflow_registry is None or self._workflow_engine is None:
            return None

        workflow_name = "pr-ship-decision"
        cfg = self._workflow_registry.get(workflow_name)
        if cfg is None:
            log.debug(
                "Webhook: pr-ship-decision workflow not found in registry — skipping"
            )
            return None

        inputs = {
            "pr_number": pr_number,
            "pr_title": pr_title,
            "author": author,
            "base_branch": base_branch,
            "head_branch": head_branch,
            "repo": repo,
            # Confidence placeholder — board step will overwrite
            "confidence": "1.0",
        }

        try:
            run_id = self._workflow_registry.trigger(
                workflow_name, inputs, engine=self._workflow_engine
            )
            return run_id
        except Exception as exc:  # noqa: BLE001
            log.error(
                "Webhook: failed to trigger pr-ship-decision workflow: %s", exc
            )
            return None

    async def _create_task(self, **kwargs: Any) -> None:
        """Create a task in the pipeline if one is configured."""
        if self._pipeline is None:
            return
        try:
            await self._pipeline.create_task(**kwargs)
        except Exception as exc:
            log.error("Failed to create task via pipeline: %s", exc)

    def _publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Publish to EventBus if configured. Silently swallows errors."""
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                event_type=f"webhook.github.{event_type}",
                payload=payload,
                source="webhook_receiver",
            )
        except Exception as exc:
            # EventBus may reject unknown event types; swallow silently.
            log.debug("EventBus publish failed for webhook.github.%s: %s", event_type, exc)
