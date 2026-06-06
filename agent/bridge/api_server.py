"""Mission Control REST API server.

Extends the existing HealthServer with a full REST API for dashboard access.
Bearer token auth, CORS, JSON responses. Binds to 127.0.0.1 by default
(P2.1 / audit C8); operators wanting LAN reach override via
``[api] host = "0.0.0.0"`` in ``bridge.toml``.

Sprint P6.2 (issue #1593) extracted the per-domain handler bodies into
separate modules under ``bridge/api/`` (``routes_<domain>.py``). This
module now contains:

- Module-level middleware factories (``create_auth_middleware``,
  ``create_cors_middleware``, ``cors_middleware``) and helpers
  (``_extract_bearer_token``, ``_error``, ``_ok``,
  ``_redact_heartbeat_url``, ``_ROUTE_DESCRIPTIONS``,
  ``_is_public_path``, ``_enumerate_public_routes``, ``RateLimiter``).
- The ``APIServer`` class itself — construction, middleware wiring,
  lifecycle (start/stop), and the thin ``_register_routes`` that walks
  through each per-domain mixin and any conditional route blocks
  (peer_api, chief_sessions, zone4, directives).

The handler bodies are provided by mixin classes the ``APIServer``
multiple-inherits from. Each mixin defines ``_handle_*`` methods and a
``_register_<domain>_routes(self, app)`` registration helper. Tests
that import ``APIServer`` and call ``server._handle_*`` or
``server._register_routes(app)`` work unchanged.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web

from .api._helpers import _error, _ok, _redact_heartbeat_url  # noqa: F401  re-exported
from .api.routes_agents import _AgentsRoutesMixin
from .api.routes_chief_sessions import _ChiefSessionsRoutesMixin
from .api.routes_commands import _CommandsRoutesMixin
from .api.routes_cost_trust import _CostTrustRoutesMixin
from .api.routes_dashboard import _DashboardRoutesMixin
from .api.routes_events_knowledge import _EventsKnowledgeRoutesMixin
from .api.routes_health import _HealthRoutesMixin
from .api.routes_hitl import _HitlRoutesMixin
from .api.routes_job_search import _JobSearchRoutesMixin
from .api.routes_roster import _RosterRoutesMixin
from .api.routes_metrics import _MetricsRoutesMixin
from .api.routes_reviews import _ReviewsRoutesMixin
from .api.routes_services import _ServicesRoutesMixin
from .api.routes_tasks import _TasksRoutesMixin
from .api.routes_vapi_departments import _VapiDepartmentsRoutesMixin
from .api.routes_webhooks import _WebhooksRoutesMixin
from .api.routes_websocket import _WebSocketRoutesMixin
from .api.routes_workflows import _WorkflowRoutesMixin
from .api.routes_workorders import _WorkordersRoutesMixin
from .api.routes_zone4_reports import _Zone4ReportsRoutesMixin
from .peer_api import register_peer_routes

if TYPE_CHECKING:
    from .app import BridgeApp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter (token bucket, per-client-IP)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Token-bucket rate limiter keyed by client IP.

    Defaults to 120 requests/min (2 tokens/s, bucket size 120).
    """

    def __init__(
        self,
        rate: float = 2.0,
        bucket_size: int = 120,
        stale_seconds: float = 300.0,
    ) -> None:
        self._rate = rate
        self._bucket_size = bucket_size
        self._stale_seconds = stale_seconds
        self._clients: dict[str, dict[str, float]] = {}
        self._last_cleanup = time.monotonic()

    def check(self, client_ip: str) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.monotonic()
        if now - self._last_cleanup > 60.0:
            self._cleanup(now)

        entry = self._clients.get(client_ip)
        if entry is None:
            self._clients[client_ip] = {
                "tokens": self._bucket_size - 1.0,
                "last_refill": now,
            }
            return True

        elapsed = now - entry["last_refill"]
        entry["tokens"] = min(
            self._bucket_size,
            entry["tokens"] + elapsed * self._rate,
        )
        entry["last_refill"] = now

        if entry["tokens"] >= 1.0:
            entry["tokens"] -= 1.0
            return True
        return False

    def _cleanup(self, now: float) -> None:
        self._last_cleanup = now
        stale = [
            ip for ip, e in self._clients.items()
            if now - e["last_refill"] > self._stale_seconds
        ]
        for ip in stale:
            del self._clients[ip]


_rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

def _extract_bearer_token(request: web.Request) -> str | None:
    """Extract Bearer token from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def create_auth_middleware(api_token: str):
    """Create auth middleware that validates Bearer tokens."""

    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        # Skip auth for healthz, CORS preflight, and WebSocket (WS auth is handled in-handler via query param)
        if request.path in ("/healthz", "/ws/events") or request.method == "OPTIONS":
            return await handler(request)

        # Cal.com (HMAC), GitHub (HMAC), and VAPI (X-VAPI-SECRET, P2.3 #1578)
        # webhooks each use their own auth scheme — skip the Bearer check
        # here; the per-handler auth runs inside the route module.
        if request.path in (
            "/api/webhooks/calcom",
            "/api/webhooks/github",
            "/api/v1/voice/webhook",
        ) and request.method == "POST":
            return await handler(request)

        # Rate limiting (healthz already returned above)
        client_ip = request.remote or "unknown"
        if not _rate_limiter.check(client_ip):
            return web.json_response(
                {"error": "Rate limit exceeded"}, status=429
            )

        token = _extract_bearer_token(request)
        if token is None or not secrets.compare_digest(token, api_token):
            return web.json_response(
                {"error": "Unauthorized"}, status=401
            )

        # Access logging
        logger.info("API %s %s from %s", request.method, request.path, client_ip)

        return await handler(request)

    return auth_middleware


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------
#
# Audit C9 (Sprint P2.2): a wildcard ``Access-Control-Allow-Origin: *`` header
# combined with bearer-token auth defeats the browser same-origin policy.
# CORS is now an opt-in allowlist driven by ``[api] cors_allowed_origins`` in
# ``bridge.toml``. Empty allowlist == no ``Access-Control-Allow-Origin``
# header. Per-request, the header is set to the requesting ``Origin`` only
# when it appears in the allowlist (echo-back pattern). Disallowed origins
# never get the header. The shared-symbol ``cors_middleware`` is preserved as
# a no-CORS variant (empty allowlist) so existing test fixtures that import
# it keep their existing semantics.


def create_cors_middleware(allowed_origins: tuple[str, ...] = ()):
    """Build a CORS middleware bound to ``allowed_origins``.

    The middleware echoes back the requesting ``Origin`` header only when it
    appears in the allowlist; disallowed origins receive no
    ``Access-Control-Allow-Origin`` header. An empty allowlist disables CORS
    entirely (safe default — assumes the API is reached same-origin via SSH
    tunnel / tailscale, per P2.1 / audit C8).

    OPTIONS preflight is short-circuited to a 204 even when the origin is
    disallowed (so browsers see a clean preflight failure rather than a 405
    method-not-allowed bubbling up from aiohttp). Other methods proceed
    through the handler chain normally.
    """
    allowed = frozenset(allowed_origins)

    @web.middleware
    async def cors_middleware(request: web.Request, handler):
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)

        origin = request.headers.get("Origin")
        if origin and origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type"
            )
            response.headers["Access-Control-Max-Age"] = "86400"
        return response

    return cors_middleware


# Back-compat: module-level ``cors_middleware`` is the no-CORS variant (empty
# allowlist). Existing test fixtures that import this symbol keep working;
# production builds use ``create_cors_middleware(config.api_cors_allowed_origins)``
# wired through ``APIServer.start``.
cors_middleware = create_cors_middleware(())


# ---------------------------------------------------------------------------
# Error helpers — re-exported from bridge.api._helpers for back-compat. The
# helper bodies live in ``bridge/api/_helpers.py``; rebinding them at module
# scope keeps any pre-existing import `from bridge.api_server import _ok`
# working without surgery.
# ---------------------------------------------------------------------------

# (``_error``, ``_ok``, ``_redact_heartbeat_url`` imported above.)


# ---------------------------------------------------------------------------
# Route introspection (Sprint 07.02)
# ---------------------------------------------------------------------------

# Hand-authored descriptions keyed by canonical path. Optional: any path not
# present in this map is still surfaced — it just renders without a description.
# CLAUDE.md is the authoritative operator-facing doc; this map keeps the API
# index human-readable. Plan 09 keeps both in sync.
_ROUTE_DESCRIPTIONS: dict[str, str] = {
    "/healthz": "Health check (no auth)",
    "/api": "API endpoint index",
    "/api/heartbeat/status": "Dead-man's switch heartbeat status (Sprint 07.09)",
    "/api/agents": "List all agents",
    "/api/agents/{agent_id}": "Get agent by ID",
    "/api/agents/spawn": "Spawn a new agent",
    "/api/agents/{agent_id}/kill": "Kill an agent",
    "/api/sessions": "List active sessions",
    "/api/sessions/reset": "Reset a session",
    "/api/cost": "Cost summary (daily + weekly)",
    "/api/trust": "Trust scores for all domains",
    "/api/escalation": "Active escalation alerts",
    "/api/escalation/acknowledge": "Acknowledge an alert",
    "/api/escalation/defer": "Defer an alert",
    "/api/events": "Recent EventBus events",
    "/api/knowledge": "Knowledge entries",
    "/api/knowledge/search": "Search knowledge (FTS5)",
    "/api/services": "LaunchDaemon service states",
    "/api/commands": "Bridge commands (GET to list, POST to dispatch)",
    "/api/metrics/{name}": "Metric data by name",
    "/api/traces": "Recent trace spans",
    "/api/tasks": "Task pipeline (Kanban) — GET to list, POST to create",
    "/api/tasks/{task_id}": "Get task by ID",
    "/api/tasks/{task_id}/status": "Move task to new status",
    "/api/tasks/{task_id}/move": "Move task between pipeline stages",
    "/api/tasks/{task_id}/assign": "Assign task to agent",
    "/api/reviews": "Quality gate reviews — GET to list, POST to create",
    "/api/reviews/{review_id}/decide": "Submit review decision",
    "/api/webhooks/github": "GitHub webhook receiver",
    "/api/webhooks/calcom": "Cal.com booking webhook receiver (Z2-S4.1)",
    "/api/hitl/pending": "Pending HITL approvals",
    "/api/hitl/{task_id}/respond": "Respond to HITL item",
    "/ws/events": "WebSocket event stream",
    "/api/workorders": "Create WorkOrder from external spec (S12)",
    "/api/workorders/{wo_id}": "Retrieve WorkOrder state",
    "/api/workflows": "List loaded workflow definitions (WS3.5)",
    "/api/workflows/{name}/start": "Trigger a workflow by name (WS3.5)",
    "/api/workflows/runs": "List recent workflow runs across all workflows (WS3.5)",
    "/api/workflows/runs/{run_id}": "Get a workflow run — live engine state, store fallback (WS3.5)",
    "/api/workflows/runs/{run_id}/cancel": "Cancel an active workflow run (WS3.5)",
    "/ws/workorders/{wo_id}": "WebSocket stream of WorkOrder state transitions",
    "/api/v1/departments": "List departments registered in DepartmentRegistry (VAPI)",
    "/api/v1/departments/{dept}": "Department metadata (VAPI)",
    "/api/v1/departments/{dept}/chat/completions":
        "OpenAI-compatible SSE chat completion for a department (VAPI)",
    "/api/v1/voice/webhook": "VAPI inbound webhook receiver (D1.7b)",
    "/api/roster": "Registered roster specialists across all departments (RR.3)",
    "/api/roster/{department}": "Registered roster overlay for one department (RR.3)",
    "/api/roster/register": "Register a runtime specialist (validated; 400 on rejection) (RR.3)",
    "/api/roster/unregister": "Unregister a runtime specialist (404 if absent) (RR.3)",
}


def _is_public_path(path: str) -> bool:
    """Filter rule: include /api/, /ws/, /healthz; exclude /internal/."""
    if path.startswith("/internal/"):
        return False
    return (
        path == "/healthz"
        or path.startswith("/api/")
        or path == "/api"
        or path.startswith("/ws/")
    )


def _enumerate_public_routes(
    app: web.Application | None,
) -> list[dict[str, str]]:
    """Walk ``app.router.routes()`` and return public route descriptors.

    Returns a list of ``{"method": ..., "path": ..., "description": ...}``
    dicts. Auto-generated HEAD twins (aiohttp emits one for every GET) are
    suppressed. Duplicates on (method, path) are deduped — the first wins.
    """
    if app is None:
        return []

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []

    for route in app.router.routes():
        # Resolve canonical path. Routes without a resource (defensive
        # — should not happen for our handlers) are skipped.
        resource = getattr(route, "resource", None)
        if resource is None:
            continue
        path = getattr(resource, "canonical", None)
        if not isinstance(path, str):
            continue

        method = (route.method or "").upper()
        if not method or method == "HEAD":
            # aiohttp auto-mirrors GET as HEAD; suppress the twin.
            continue

        if not _is_public_path(path):
            continue

        key = (method, path)
        if key in seen:
            continue
        seen.add(key)

        descriptor: dict[str, str] = {"method": method, "path": path}
        description = _ROUTE_DESCRIPTIONS.get(path)
        if description:
            descriptor["description"] = description
        out.append(descriptor)

    return out


# ---------------------------------------------------------------------------
# APIServer
# ---------------------------------------------------------------------------

class APIServer(
    _HealthRoutesMixin,
    _AgentsRoutesMixin,
    _CostTrustRoutesMixin,
    _DashboardRoutesMixin,
    _EventsKnowledgeRoutesMixin,
    _ServicesRoutesMixin,
    _CommandsRoutesMixin,
    _MetricsRoutesMixin,
    _TasksRoutesMixin,
    _ReviewsRoutesMixin,
    _WebhooksRoutesMixin,
    _HitlRoutesMixin,
    _VapiDepartmentsRoutesMixin,
    _WebSocketRoutesMixin,
    _WorkordersRoutesMixin,
    _WorkflowRoutesMixin,
    _JobSearchRoutesMixin,
    _RosterRoutesMixin,
    _ChiefSessionsRoutesMixin,
    _Zone4ReportsRoutesMixin,
):
    """REST API server for the Mission Control dashboard.

    Sprint P6.2 (#1593): handler bodies live in per-domain mixins under
    ``bridge/api/routes_*.py``. This class wires them together,
    constructs the middleware stack, and owns lifecycle (start/stop).
    """

    # Safe commands that can be dispatched via POST /api/commands
    SAFE_COMMANDS = frozenset({
        "status", "health", "trust", "escalation", "events", "cost",
        "queue", "agents", "knowledge", "trace", "routing", "resources",
        "mcp", "skills", "failures", "departments", "diagnose",
        "halt", "resume", "spawn", "goals", "tasks", "digest",
        "proposals", "reflect", "edits", "fewshot", "z4_cost",
    })

    def __init__(
        self,
        bridge_app: BridgeApp,
        *,
        host: str = "127.0.0.1",
        port: int = 8200,
        api_token: str = "",
        cors_allowed_origins: tuple[str, ...] = (),
        allow_remote_bind: bool = False,
        voice_enabled: bool = False,
        vapi_webhook_secret: str = "",
        github_webhook_secret: str = "",
    ) -> None:
        self._bridge = bridge_app
        self._host = host
        self._port = port
        self._api_token = api_token
        # Audit C9 (P2.2): CORS is an opt-in allowlist. Empty tuple = no CORS
        # header on any response. Operators wanting browser-side dashboards
        # add origins via [api] cors_allowed_origins in bridge.toml.
        self._cors_allowed_origins: tuple[str, ...] = tuple(cors_allowed_origins)
        # P2.1 follow-up (#1626): explicit two-knob opt-in for non-local
        # bind. Enforced in ``start()`` — a non-local ``host`` with
        # ``allow_remote_bind=False`` aborts startup with a clear error.
        self._allow_remote_bind = allow_remote_bind
        # P2.3 (#1578, audit C8): VAPI webhook auth. ``voice_enabled`` mirrors
        # the bridge-level switch and gates whether the fail-closed startup
        # validator in ``start()`` enforces the secret. ``vapi_webhook_secret``
        # is consumed by the ``_handle_vapi_webhook`` handler in
        # ``api/routes_webhooks.py`` for constant-time header comparison.
        self._voice_enabled = voice_enabled
        self._vapi_webhook_secret = vapi_webhook_secret
        # Sprint audit-2026-05-16.B.04 (#2053, M-3): API auth + GitHub webhook
        # secret. Both gate fail-closed boot validators in ``start()`` —
        # when the API server is starting at all, ``api_token`` must be set
        # (bearer-token middleware compares against it) and
        # ``github_webhook_secret`` must be set (HMAC-SHA256 verifier on
        # /api/webhooks/github relies on it). Mirrors the VAPI pattern above.
        self._github_webhook_secret = github_webhook_secret
        self._runner: web.AppRunner | None = None
        self._start_time = time.monotonic()
        self._ws_clients: list[web.WebSocketResponse] = []
        self._departments: Any | None = None
        self._zone4_routes: Any | None = None
        self._directive_routes: Any | None = None
        self._app_ref: web.Application | None = None
        # Cal.com webhook handler (Z2-S4.1) — wired lazily on first request
        self._calcom_webhook_handler: Any | None = None
        # VAPI client (D1.7b) — wired at startup when voice_enabled=True
        self._vapi_client: Any | None = None

    @property
    def port(self) -> int:
        return self._port

    def set_departments(self, registry: Any) -> None:
        """Wire DepartmentRegistry for Zone 4 VAPI routes."""
        self._departments = registry

    def set_vapi_client(self, client: Any) -> None:
        """Wire VAPIClient for the /api/v1/voice/webhook endpoint (D1.7b)."""
        self._vapi_client = client

    def set_directive_routes(self, directive_routes: Any) -> None:
        """Register DirectiveRoutes (Sprint 23) on the aiohttp app.

        Mirrors set_zone4_routes — pre-start (preferred) stashes the
        routes for mounting during _register_routes; post-start the
        routes module's register() handles the frozen-router case
        with a logged warning.
        """
        self._directive_routes = directive_routes
        if self._app_ref:
            directive_routes.register(self._app_ref)
            logger.info("DirectiveRoutes registered post-start (4 endpoints)")

    def set_zone4_routes(self, z4_routes: Any) -> None:
        """Register Zone4Routes on the aiohttp app.

        Two supported call orders:
          1. Before ``start()``: routes are stashed and mounted during
             ``_register_routes`` while the router is still mutable.
          2. After ``start()``: router is already frozen; this path works
             only if ``register()`` tolerates a frozen router (graceful
             degradation hotfix, #617). Prefer pre-start ordering.
        """
        self._zone4_routes = z4_routes
        if self._app_ref:
            z4_routes.register(self._app_ref)
            logger.info("Zone4Routes registered post-start (%d endpoints)", 14)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the API server."""
        # P2.1 follow-up (#1626): fail-closed validator. The bridge refuses
        # to bind to a non-local interface unless the operator has also set
        # ``[api] allow_remote_bind = true`` in ``bridge.toml``. Defense in
        # depth on top of P2.1's 127.0.0.1 default — single-knob
        # misconfiguration ("host = 0.0.0.0" alone) is rejected at startup
        # rather than silently re-exposing the API.
        if (
            self._host not in ("127.0.0.1", "localhost", "::1")
            and not self._allow_remote_bind
        ):
            raise RuntimeError(
                f"API bind refused: host={self._host!r} requires "
                "allow_remote_bind=True to start; refusing to bind to a "
                "non-local interface without explicit opt-in. Set "
                "[api] allow_remote_bind = true in bridge.toml alongside "
                "[api] host to authorize LAN exposure, or revert host to "
                "127.0.0.1."
            )
        # P2.3 (#1578, audit C8): fail-closed validator. When voice is enabled
        # the VAPI webhook route (/api/v1/voice/webhook) is registered and
        # must be authenticated; refuse to boot if the shared secret is
        # missing. Mirrors #1626's allow_remote_bind pattern — the bridge
        # never silently accepts unauthenticated VAPI calls. The route is part
        # of the API surface even when voice_enabled=False, but with an empty
        # secret the handler rejects callbacks defensively and the VAPI client
        # is not wired.
        if self._voice_enabled and not self._vapi_webhook_secret:
            raise RuntimeError(
                "API bind refused: [voice] voice_enabled = true requires a "
                "non-empty vapi_webhook_secret. The /api/v1/voice/webhook "
                "endpoint would otherwise accept unauthenticated VAPI "
                "callbacks. Add `vapi_webhook_secret=<shared-secret>` to "
                "/opt/bumba-harness/data/.secrets (mode 0600) and restart, "
                "or set [voice] voice_enabled = false in bridge.toml to "
                "disable the voice subsystem."
            )
        # Sprint audit-2026-05-16.B.04 (#2053, M-3): API auth + GitHub
        # webhook fail-closed when the API server is starting. Pre-B.04
        # the bridge would bind the route, then accept empty-token requests
        # (api_token="") or unsigned GitHub webhooks
        # (github_webhook_secret=""). Mirrors the VAPI validator above and
        # the boot-time _validate_codex_oauth pattern. The API server is
        # only constructed when `api_enabled = true`, so reaching ``start``
        # already implies the operator opted in — empty secrets at this
        # point are a misconfiguration, not a feature disable.
        if not self._api_token:
            raise RuntimeError(
                "Bridge API is starting but api_token is missing from "
                ".secrets. The bearer-token middleware (api_server.py:163) "
                "would accept empty-token requests. Add "
                "`api_token=<token>` to /opt/bumba-harness/data/.secrets, "
                "chmod 600, and restart. "
                "Sprint audit-2026-05-16.B.04 (#2053, M-3)."
            )
        if not self._github_webhook_secret:
            raise RuntimeError(
                "Bridge API is starting but github_webhook_secret is missing "
                "from .secrets. The /api/webhooks/github handler would "
                "accept unsigned callbacks. Add "
                "`github_webhook_secret=<shared-secret>` to "
                "/opt/bumba-harness/data/.secrets, chmod 600, and restart. "
                "Sprint audit-2026-05-16.B.04 (#2053, M-3)."
            )
        # Audit C9 (P2.2): non-local bind without an allowlist means the API
        # is reachable from the network but no browser can use it cross-origin.
        # That is the *correct* posture if the operator only uses CLI clients,
        # but it's an easy footgun otherwise — warn loudly at startup.
        if (
            self._host not in ("127.0.0.1", "localhost", "::1")
            and not self._cors_allowed_origins
        ):
            logger.warning(
                "API bound to %s with empty CORS allowlist — "
                "browsers will refuse cross-origin requests. "
                "Set [api] cors_allowed_origins in bridge.toml if a "
                "browser dashboard needs access.",
                self._host,
            )
        app = web.Application(
            middlewares=[
                create_cors_middleware(self._cors_allowed_origins),
                create_auth_middleware(self._api_token),
            ]
        )
        self._register_routes(app)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info(
            "API server started on http://%s:%d", self._host, self._port
        )

    async def stop(self) -> None:
        """Stop the API server."""
        # Close all WebSocket clients
        for ws in list(self._ws_clients):
            await ws.close()
        self._ws_clients.clear()

        if self._runner:
            await self._runner.cleanup()

    def _register_routes(self, app: web.Application) -> None:
        """Register all API routes.

        Each per-domain mixin contributes a ``_register_<domain>_routes``
        helper that mounts its routes against ``app.router``. The order
        below preserves the historical registration sequence so the
        introspective ``/api`` index walks routes in the same order
        operators previously saw.
        """
        # Hold the app ref for handlers that need it (e.g. /api index
        # walks self._app_ref.router.routes()).
        self._app_ref = app

        # Health + API index + heartbeat
        self._register_health_routes(app)

        # Agents + sessions
        self._register_agents_routes(app)

        # Cost + trust + escalation
        self._register_cost_trust_routes(app)

        # Operator dashboard (Board Phase 2 WS1, #2391) — read aggregation
        # over services/escalation/halt/wiring/cost. JSON + minimal HTML.
        self._register_dashboard_routes(app)

        # Events + knowledge
        self._register_events_knowledge_routes(app)

        # Services
        self._register_services_routes(app)

        # Commands
        self._register_commands_routes(app)

        # Metrics + traces
        self._register_metrics_routes(app)

        # Tasks (Phase 3)
        self._register_tasks_routes(app)

        # Reviews (Phase 5)
        self._register_reviews_routes(app)

        # Webhooks (GitHub + Cal.com — VAPI webhook registered with VAPI
        # department routes below).
        self._register_webhooks_routes(app)

        # HITL (Phase 7)
        self._register_hitl_routes(app)

        # WebSocket (/ws/events)
        self._register_websocket_routes(app)

        # S12 — WorkOrder Public API
        self._register_workorders_routes(app)

        # WS3.5 (#2570) — Workflow run status + control surface
        self._register_workflows_routes(app)

        # Zone 4 VAPI department routes + VAPI webhook
        self._register_vapi_departments_routes(app)

        # Sprint 07.06 / E1.5 (#1715) — Mount peer coordination routes
        # when the feature flag is on AND the bridge wired the registry.
        # peer_api.register_peer_routes() adds 6 endpoints under
        # /api/peers* (post-#1613, the MergeQueue stub and its three
        # /api/merge-queue* routes were removed) and stashes the
        # registry into app["peer_registry"] for the handlers. Flag-off
        # behavior is the historical default: routes absent, GET
        # /api/peers returns aiohttp 404. The introspective /api index
        # (Sprint 07.02) auto-surfaces the new routes — no second edit
        # needed here.
        bridge_config = getattr(self._bridge, "_config", None)
        peer_flag_on = bool(
            getattr(bridge_config, "peer_coordination_enabled", False)
        )
        peer_registry = getattr(self._bridge, "_peer_registry", None)
        if peer_flag_on and peer_registry is not None:
            register_peer_routes(app, peer_registry)
            logger.info(
                "Peer coordination routes mounted (6 endpoints under "
                "/api/peers*)"
            )

        # D5.8 — Job search funnel-failure aggregator endpoint
        self._register_job_search_routes(app)

        # RR.3 (#2593) — self-serve roster registry (operator add/remove
        # of runtime specialists; overlay read by the chief at build time).
        self._register_roster_routes(app)

        # Z4-23 (#2449) — Zone 4 operator report (cost/provider/reliability).
        # Always registered; reads run manifests under zone4_artifact_root.
        self._register_zone4_reports_routes(app)

        # Z4-S12 (#1383) — ChiefSession REST endpoints. Gated by
        # ``chief_dispatcher_enabled`` because Z4-S22 (BridgeApp wiring)
        # has not landed yet; without the store the handlers can only
        # 503. Routes register only when the flag is True so the API
        # surface stays clean for operators who haven't opted in.
        chief_flag_on = bool(
            getattr(bridge_config, "chief_dispatcher_enabled", False)
        )
        if chief_flag_on:
            app.router.add_get(
                "/api/chief_sessions", self._handle_list_chief_sessions
            )
            # zone4-warmth.D.02 (#2300) — aggregate warm-session stats.
            # MUST register before ``/api/chief_sessions/{session_id}``:
            # aiohttp's UrlDispatcher uses first-match resolution, so the
            # dynamic ``{session_id}`` route would otherwise swallow
            # ``warmth_stats`` as a literal id and return 404 from
            # ``store.get("warmth_stats")``.
            app.router.add_get(
                "/api/chief_sessions/warmth_stats",
                self._handle_chief_sessions_warmth_stats,
            )
            app.router.add_get(
                "/api/chief_sessions/{session_id}",
                self._handle_get_chief_session,
            )
            logger.info(
                "ChiefSession REST endpoints mounted "
                "(/api/chief_sessions, /api/chief_sessions/warmth_stats, "
                "/api/chief_sessions/{session_id})"
            )

            # Z4-S42 (#1401) — per-session cost endpoint. Layered on top
            # of the Z4-S12 routes; only mounts when *both* the store and
            # the cost tracker are wired so the handler doesn't have to
            # 503 on partial wiring. Without the cost tracker the
            # response surface is meaningless.
            chief_session_store = getattr(
                self._bridge, "_chief_session_store", None
            )
            cost_tracker = getattr(self._bridge, "_cost_tracker", None)
            if chief_session_store is not None and cost_tracker is not None:
                app.router.add_get(
                    "/api/chief_sessions/{session_id}/cost",
                    self._handle_get_chief_session_cost,
                )
                logger.info(
                    "ChiefSession cost endpoint mounted "
                    "(/api/chief_sessions/{session_id}/cost)"
                )

        # Mount Zone4 observability routes if they were pre-registered
        # (via set_zone4_routes called before start()). This is the correct
        # place — router is still mutable here, frozen after start() returns.
        if self._zone4_routes is not None:
            self._zone4_routes.register(app)
            logger.info("Zone4Routes mounted during _register_routes")

        # Mount Sprint 23 directive lifecycle routes if they were pre-registered.
        # Same router-ordering lesson as Zone4Routes — register before start().
        if self._directive_routes is not None:
            self._directive_routes.register(app)
            logger.info("DirectiveRoutes mounted during _register_routes (4 endpoints)")
