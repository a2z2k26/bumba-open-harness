"""Quality review routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``.
"""
from __future__ import annotations

import json

from aiohttp import web

from ._helpers import _error, _ok


class _ReviewsRoutesMixin:
    """Provides /api/reviews/* handlers (Phase 5 quality gate)."""

    def _register_reviews_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/reviews", self._handle_list_reviews)
        app.router.add_post("/api/reviews", self._handle_create_review)
        app.router.add_post(
            "/api/reviews/{review_id}/decide", self._handle_decide_review
        )

    # ------------------------------------------------------------------
    # Reviews (Phase 5)
    # ------------------------------------------------------------------

    async def _handle_list_reviews(
        self, request: web.Request
    ) -> web.Response:
        """List quality reviews."""
        gate = getattr(self._bridge, "_quality_gate", None)
        if gate is None:
            return _error("Quality gate not initialized", 503)
        try:
            task_id = request.query.get("task_id")
            reviews = await gate.get_pending_reviews(
                task_id=int(task_id) if task_id else None
            )
            return _ok({"reviews": reviews, "count": len(reviews)})
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_create_review(
        self, request: web.Request
    ) -> web.Response:
        """Request a quality review for a task."""
        gate = getattr(self._bridge, "_quality_gate", None)
        if gate is None:
            return _error("Quality gate not initialized", 503)
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        task_id = body.get("task_id")
        reviewer = body.get("reviewer", "")
        if not task_id:
            return _error("'task_id' field is required")
        try:
            review_id = await gate.request_review(
                task_id=task_id,
                reviewer=reviewer,
                review_type=body.get("type", "quality"),
            )
            return _ok({"id": review_id, "task_id": task_id}, status=201)
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_decide_review(
        self, request: web.Request
    ) -> web.Response:
        """Submit a review decision."""
        review_id = int(request.match_info["review_id"])
        gate = getattr(self._bridge, "_quality_gate", None)
        if gate is None:
            return _error("Quality gate not initialized", 503)
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        decision = body.get("decision", "")
        if decision not in ("approved", "rejected", "needs_changes"):
            return _error(
                "'decision' must be 'approved', 'rejected', or 'needs_changes'"
            )
        try:
            decided = await gate.submit_decision(
                review_id=review_id,
                decision=decision,
                comment=body.get("comment", ""),
            )
            if not decided:
                return _error(f"Review {review_id} not found", 404)
            return _ok({"id": review_id, "decision": decision})
        except Exception as e:
            return _error(str(e), 500)
