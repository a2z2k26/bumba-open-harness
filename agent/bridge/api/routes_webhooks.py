"""Webhook routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. Three inbound webhook endpoints
co-located: GitHub, Cal.com, and VAPI. Each one uses its own auth
(HMAC / signature / X-VAPI-SECRET header), not Bearer-token auth — the
auth middleware in ``api_server.py`` explicitly skips Bearer enforcement
for these paths.

P2.3 (#1578, audit C8): VAPI webhook now authenticates via the
``X-VAPI-SECRET`` header. Missing/wrong secret returns 401; correct
secret reaches the handler body. Constant-time comparison via
``secrets.compare_digest`` prevents timing attacks.
"""
from __future__ import annotations

import logging
import secrets as _stdlib_secrets

from aiohttp import web

from ._helpers import _error, _ok

logger = logging.getLogger(__name__)


class _WebhooksRoutesMixin:
    """Provides /api/webhooks/* + /api/v1/voice/webhook handlers."""

    def _register_webhooks_routes(self, app: web.Application) -> None:
        # Webhooks (Phase 6)
        app.router.add_post(
            "/api/webhooks/github", self._handle_github_webhook
        )

        # Cal.com webhooks (Z2-S4.1)
        app.router.add_post(
            "/api/webhooks/calcom", self._handle_calcom_webhook
        )

    # ------------------------------------------------------------------
    # Webhooks (Phase 6)
    # ------------------------------------------------------------------

    async def _handle_github_webhook(
        self, request: web.Request
    ) -> web.Response:
        """Handle inbound GitHub webhook."""
        receiver = getattr(self._bridge, "_webhook_receiver", None)
        if receiver is None:
            return _error("Webhook receiver not initialized", 503)
        try:
            body = await request.read()
            signature = request.headers.get("X-Hub-Signature-256", "")
            event_type = request.headers.get("X-GitHub-Event", "")

            result = await receiver.handle_webhook(
                body=body,
                signature=signature,
                event_type=event_type,
            )
            return _ok(result)
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_calcom_webhook(
        self, request: web.Request
    ) -> web.Response:
        """Handle inbound Cal.com booking webhook (Z2-S4.1).

        Signature verification is performed inside CalcomWebhookHandler using
        the ``calcom_webhook_secret`` from .secrets. Post audit-2026-05-16.B.05
        (#2054, HI-6) the handler rejects unsigned requests with 401 and the
        boot validator refuses to start with ``calcom_webhook_enabled=true``
        and an empty secret.
        """
        # audit-2026-05-16.B.05 (#2054, HI-6) — config gate. When the
        # operator hasn't opted in, return 503 so external callers see
        # "not available" rather than a misleading 401. The boot validator
        # already prevented the enabled+no-secret state from reaching here.
        bridge_config = getattr(self._bridge, "_config", None)
        if not getattr(bridge_config, "calcom_webhook_enabled", False):
            return _error("Cal.com webhook receiver disabled", 503)

        # Lazy-instantiate the handler, wiring the live EventBus if available.
        if self._calcom_webhook_handler is None:
            try:
                from bridge.calcom_webhook import CalcomWebhookHandler
                from bridge.event_bus import EventBus
                event_bus = EventBus.get_instance()
                self._calcom_webhook_handler = CalcomWebhookHandler(event_bus=event_bus)
                logger.info("CalcomWebhookHandler initialised")
            except Exception as exc:
                logger.error("calcom_webhook.init_failed: %s", exc)
                return _error("Cal.com webhook handler not available", 503)

        return await self._calcom_webhook_handler.handle(request)

    async def _handle_vapi_webhook(
        self, request: web.Request
    ) -> web.Response:
        """Handle inbound VAPI webhook events (D1.7b).

        Authenticated via the ``X-VAPI-SECRET`` header (P2.3, audit C8).
        Missing/wrong secret returns 401 with no body details (don't leak
        which knob is wrong); the request never reaches the dispatcher.
        Constant-time comparison via ``secrets.compare_digest`` prevents
        timing-attack secret discovery.

        Event types handled by VAPIClient.handle_webhook:
        - assistant-request, function-call, status-update,
          end-of-call-report, hang, transcript
        """
        # P2.3 (#1578) — verify shared secret before any handler work.
        # The APIServer.start() fail-closed validator guarantees
        # ``self._vapi_webhook_secret`` is non-empty whenever voice is
        # enabled; here we defensively re-check rather than trusting that
        # invariant (test fixtures that bypass start() must still 401).
        expected = getattr(self, "_vapi_webhook_secret", "") or ""
        provided = request.headers.get("X-VAPI-SECRET", "") or ""
        if not expected or not _stdlib_secrets.compare_digest(provided, expected):
            logger.warning(
                "VAPI webhook auth failed: header %s, expected %s",
                "missing" if not provided else "wrong",
                "missing" if not expected else "present",
            )
            return _error("Unauthorized", 401)

        if self._vapi_client is None:
            logger.debug("VAPI webhook received but vapi_client not wired — ignoring")
            return web.json_response({})

        try:
            payload: dict = await request.json()
        except Exception as exc:
            logger.warning("VAPI webhook: failed to parse JSON body: %s", exc)
            return _error("Invalid JSON body", 400)

        # VAPI wraps the event type in message.type
        message = payload.get("message", payload)
        event_type: str = message.get("type", "")
        if not event_type:
            logger.warning("VAPI webhook: missing message.type in payload")
            return web.json_response({})

        try:
            response = await self._vapi_client.handle_webhook(event_type, message)
            return web.json_response(response)
        except Exception as exc:
            logger.error("VAPI webhook handler raised: %s", exc)
            return _error("Internal error handling VAPI event", 500)
