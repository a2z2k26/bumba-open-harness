"""Tests for VAPI webhook authentication (P2.3, audit C8, issue #1578).

The /api/v1/voice/webhook endpoint is registered by
``_VapiDepartmentsRoutesMixin._register_vapi_departments_routes`` and the
handler body lives in ``_WebhooksRoutesMixin._handle_vapi_webhook``. Before
P2.3 the handler accepted every request unauthenticated; after P2.3 every
request must carry a correct ``X-VAPI-SECRET`` header.

This file covers:

* Header missing → 401
* Header wrong → 401
* Header correct → 200 (request reaches the handler body / VAPI dispatcher)
* Server-side secret unset → 401 even with a header
* Voice disabled → ``APIServer.start`` proceeds without enforcing the secret
  (route registers but every call 401s — defense in depth)
* Voice enabled + empty secret → ``APIServer.start`` raises RuntimeError
  (fail-closed)
* Voice enabled + non-empty secret → start succeeds
* Bearer-auth middleware skips the VAPI path (no double-401)
* ``secrets.compare_digest`` is the comparison primitive
* Config-loader picks up ``vapi_webhook_secret`` from .secrets
* Handler returns 401 without leaking secret presence/absence in the body
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    RateLimiter,
    create_auth_middleware,
    cors_middleware,
)

pytestmark = pytest.mark.socket

API_TOKEN = "vapi-test-bearer-token"
WEBHOOK_SECRET = "vapi-test-shared-secret-42"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Generous bucket so cross-test bleed cannot produce spurious 429s."""
    import bridge.api_server as _mod

    fresh = RateLimiter(rate=2.0, bucket_size=10_000)
    with patch.object(_mod, "_rate_limiter", fresh):
        yield


def _make_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = "/tmp/test-vapi-auth-data"
    bridge._db = AsyncMock()
    bridge._health_server = None
    bridge._tmux_agents = None
    bridge._session_mgr = None
    bridge._cost_tracker = None
    bridge._autonomy = None
    bridge._memory = None
    bridge._commands = None
    bridge._metrics = None
    bridge._tracer = None
    bridge._task_queue = None
    bridge._task_pipeline = None
    bridge._quality_gate = None
    bridge._webhook_receiver = None
    bridge._peer_registry = None
    bridge._merge_queue = None
    return bridge


def _make_vapi_client() -> Any:
    """Stub VAPI client whose handle_webhook records the call and returns {}.

    The real VAPIClient.handle_webhook is async and returns a dict; we mirror
    that minimal shape so the handler's ``await self._vapi_client.handle_webhook``
    path is exercised.
    """
    client = MagicMock()
    client.handle_webhook = AsyncMock(return_value={"ok": True})
    return client


async def _make_client(
    *,
    webhook_secret: str = WEBHOOK_SECRET,
    voice_enabled: bool = True,
    vapi_client: Any | None = None,
) -> tuple[TestClient, APIServer]:
    """Build a TestClient hitting the full APIServer route registration.

    Constructs an ``APIServer`` (without start()) and mounts its routes onto
    a fresh aiohttp app that wires both middlewares — same shape as the
    production stack. We bypass ``start()`` so the bind validators don't
    interfere; tests that need to exercise the validator do so directly.
    """
    bridge = _make_bridge()
    server = APIServer(
        bridge,
        api_token=API_TOKEN,
        voice_enabled=voice_enabled,
        vapi_webhook_secret=webhook_secret,
    )
    if vapi_client is not None:
        server.set_vapi_client(vapi_client)

    app = web.Application(
        middlewares=[
            cors_middleware,
            create_auth_middleware(server._api_token),
        ]
    )
    server._register_routes(app)
    ts = TestServer(app)
    client = TestClient(ts)
    await client.start_server()
    return client, server


def _payload() -> dict[str, Any]:
    """Minimum well-formed VAPI webhook body (matches D1.7b shape)."""
    return {"message": {"type": "status-update", "status": "in-progress"}}


# ---------------------------------------------------------------------------
# 1-4. Header verification on the route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_secret_header_returns_401() -> None:
    """No X-VAPI-SECRET header → 401, handler body never runs."""
    vapi = _make_vapi_client()
    client, _ = await _make_client(vapi_client=vapi)
    try:
        resp = await client.post("/api/v1/voice/webhook", json=_payload())
        assert resp.status == 401
        assert vapi.handle_webhook.await_count == 0, (
            "handler body must not run when auth fails"
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_wrong_secret_header_returns_401() -> None:
    """Wrong X-VAPI-SECRET → 401, handler body never runs."""
    vapi = _make_vapi_client()
    client, _ = await _make_client(vapi_client=vapi)
    try:
        resp = await client.post(
            "/api/v1/voice/webhook",
            json=_payload(),
            headers={"X-VAPI-SECRET": "wrong-secret"},
        )
        assert resp.status == 401
        assert vapi.handle_webhook.await_count == 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_correct_secret_reaches_handler() -> None:
    """Correct X-VAPI-SECRET → 200 and VAPIClient.handle_webhook is awaited."""
    vapi = _make_vapi_client()
    client, _ = await _make_client(vapi_client=vapi)
    try:
        resp = await client.post(
            "/api/v1/voice/webhook",
            json=_payload(),
            headers={"X-VAPI-SECRET": WEBHOOK_SECRET},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body == {"ok": True}
        assert vapi.handle_webhook.await_count == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_server_side_empty_secret_rejects_all() -> None:
    """If the server forgot to load the secret (e.g. test fixture bypass), every
    call 401s — even a header matching ''. ``compare_digest('', '')`` returns
    True, so the handler additionally checks ``expected`` is truthy first."""
    vapi = _make_vapi_client()
    client, _ = await _make_client(
        webhook_secret="", voice_enabled=False, vapi_client=vapi
    )
    try:
        resp = await client.post(
            "/api/v1/voice/webhook",
            json=_payload(),
            headers={"X-VAPI-SECRET": ""},
        )
        assert resp.status == 401
        resp2 = await client.post(
            "/api/v1/voice/webhook", json=_payload()
        )
        assert resp2.status == 401
        assert vapi.handle_webhook.await_count == 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_correct_secret_with_empty_json_body_still_authorizes() -> None:
    """The auth check runs before JSON parsing — even a missing body should
    pass auth (the handler's JSON parse will then 400). This pins ordering:
    auth gate first, then payload validation."""
    vapi = _make_vapi_client()
    client, _ = await _make_client(vapi_client=vapi)
    try:
        resp = await client.post(
            "/api/v1/voice/webhook",
            data="not-json-at-all",
            headers={
                "X-VAPI-SECRET": WEBHOOK_SECRET,
                "Content-Type": "text/plain",
            },
        )
        assert resp.status == 400
        body = await resp.json()
        assert body.get("error") == "Invalid JSON body"
        assert vapi.handle_webhook.await_count == 0
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# 5. Middleware order — VAPI path bypasses Bearer auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_bearer_auth_required_on_vapi_path() -> None:
    """Absence of Authorization header must not produce a Bearer-flavored 401;
    the auth middleware skips ``/api/v1/voice/webhook``. The only auth in
    play here is the X-VAPI-SECRET header check inside the handler."""
    vapi = _make_vapi_client()
    client, _ = await _make_client(vapi_client=vapi)
    try:
        resp = await client.post(
            "/api/v1/voice/webhook",
            json=_payload(),
            headers={"X-VAPI-SECRET": WEBHOOK_SECRET},
            # Deliberately omit Authorization header.
        )
        assert resp.status == 200
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# 6-7. Fail-closed startup validator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_raises_when_voice_enabled_and_secret_empty() -> None:
    """voice_enabled=True with empty secret must refuse to boot."""
    bridge = _make_bridge()
    server = APIServer(
        bridge,
        host="127.0.0.1",
        port=0,
        api_token=API_TOKEN,
        voice_enabled=True,
        vapi_webhook_secret="",
    )
    with pytest.raises(RuntimeError) as excinfo:
        await server.start()
    msg = str(excinfo.value)
    # Error message must name BOTH knobs so the operator can recover.
    assert "voice_enabled" in msg, f"error must mention voice_enabled: {msg!r}"
    assert "vapi_webhook_secret" in msg, (
        f"error must mention vapi_webhook_secret: {msg!r}"
    )
    # Defensive: ensure no runner stuck around if start() raised early.
    await server.stop()


@pytest.mark.asyncio
async def test_start_succeeds_when_voice_enabled_and_secret_present() -> None:
    """voice_enabled=True + non-empty secret → start completes cleanly."""
    bridge = _make_bridge()
    server = APIServer(
        bridge,
        host="127.0.0.1",
        port=0,
        api_token=API_TOKEN,
        voice_enabled=True,
        vapi_webhook_secret=WEBHOOK_SECRET,
    )
    try:
        await server.start()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_start_succeeds_when_voice_disabled_and_secret_empty() -> None:
    """voice_enabled=False → secret may be empty; start proceeds."""
    bridge = _make_bridge()
    server = APIServer(
        bridge,
        host="127.0.0.1",
        port=0,
        api_token=API_TOKEN,
        voice_enabled=False,
        vapi_webhook_secret="",
    )
    try:
        await server.start()
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# 8. Constant-time comparison
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uses_constant_time_comparison() -> None:
    """The handler MUST use ``secrets.compare_digest`` to prevent timing
    attacks on the shared secret. We verify by patching the primitive and
    confirming it is called for a webhook request."""
    from unittest.mock import patch as _patch

    vapi = _make_vapi_client()
    client, _ = await _make_client(vapi_client=vapi)
    try:
        with _patch(
            "bridge.api.routes_webhooks._stdlib_secrets.compare_digest",
            wraps=__import__("secrets").compare_digest,
        ) as spy:
            resp = await client.post(
                "/api/v1/voice/webhook",
                json=_payload(),
                headers={"X-VAPI-SECRET": WEBHOOK_SECRET},
            )
            assert resp.status == 200
            assert spy.called, (
                "VAPI webhook auth MUST use secrets.compare_digest; "
                "string `==` is vulnerable to timing attacks."
            )
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# 9-10. .secrets loader picks up vapi_webhook_secret
# ---------------------------------------------------------------------------


def test_load_secrets_reads_vapi_webhook_secret(tmp_path) -> None:
    """``_load_secrets_file`` must extract ``vapi_webhook_secret`` from .secrets."""
    from bridge.config import _load_secrets_file

    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text(
        "discord_token=fake-discord\n"
        "vapi_webhook_secret=hello-secret-123\n"
        "vapi_api_key=fake-vapi-key\n",
        encoding="utf-8",
    )
    result = _load_secrets_file(str(secrets_file))
    assert result.get("vapi_webhook_secret") == "hello-secret-123"


def test_config_default_vapi_webhook_secret_is_empty() -> None:
    """BridgeConfig field defaults to empty string (back-compat with installs
    that haven't added the secret yet — the validator is what enforces
    fail-closed semantics, not the dataclass default)."""
    from bridge.config import BridgeConfig

    cfg = BridgeConfig()
    assert cfg.vapi_webhook_secret == ""


# ---------------------------------------------------------------------------
# 11. Voice-disabled route still 401s on every call (defense in depth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_disabled_route_registered_but_always_401s() -> None:
    """When voice_enabled=False and vapi_webhook_secret='' the route still
    registers (the mixin is unconditional), but every request 401s because
    the handler refuses an empty server-side secret. This is the layered
    defense — even if the operator forgets to flip the voice flag down, the
    endpoint cannot be exercised without explicit secret material."""
    vapi = _make_vapi_client()
    client, _ = await _make_client(
        webhook_secret="", voice_enabled=False, vapi_client=vapi
    )
    try:
        for header in (
            None,
            {"X-VAPI-SECRET": ""},
            {"X-VAPI-SECRET": "anything-at-all"},
        ):
            resp = await client.post(
                "/api/v1/voice/webhook",
                json=_payload(),
                headers=header or {},
            )
            assert resp.status == 401
        assert vapi.handle_webhook.await_count == 0
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# 12. Error body does not leak which knob is wrong
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_response_body_does_not_leak_which_side_is_wrong() -> None:
    """The 401 body must be a generic ``{"error": "Unauthorized"}`` whether
    the header is missing OR wrong — never reveal whether the server has a
    secret configured (or what its prefix is). This pins the
    information-disclosure surface."""
    vapi = _make_vapi_client()
    client, _ = await _make_client(vapi_client=vapi)
    try:
        # Missing header
        resp = await client.post("/api/v1/voice/webhook", json=_payload())
        assert resp.status == 401
        body_missing = await resp.json()
        # Wrong header
        resp = await client.post(
            "/api/v1/voice/webhook",
            json=_payload(),
            headers={"X-VAPI-SECRET": "bad-guess"},
        )
        assert resp.status == 401
        body_wrong = await resp.json()
        # Both bodies must be byte-identical so an attacker cannot
        # differentiate "server has no secret" from "wrong guess".
        assert body_missing == body_wrong
        assert body_missing == {"error": "Unauthorized"}
    finally:
        await client.close()
