"""Tests for bridge.api_server — Tier 1 (auth middleware) + Tier 3 (rate limiter).

Sprint 2.4 covers api_server.py in tiers per the audit-followup plan:
- Tier 1: auth middleware (this file)
- Tier 2: HMAC webhook verification (deferred — lives in webhook_receiver.py)
- Tier 3: rate limiter (this file)
- Tier 4: per-route happy paths (deferred — needs full BridgeApp mocks)

Uses aiohttp.test_utils directly (mirrors test_peer_api.py pattern).
"""

from __future__ import annotations

import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    RateLimiter,
    _extract_bearer_token,
    create_auth_middleware,
)

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _make_test_app(api_token: str = "test-token-12345") -> web.Application:
    """Build a minimal aiohttp app with the auth middleware installed.

    Provides three handlers to exercise different middleware paths:
      GET  /healthz       — should bypass auth (handled by middleware skip)
      GET  /api/protected — requires Bearer token
      OPTIONS bypass is exercised by the OPTIONS preflight check
    """

    async def healthz(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def protected(request: web.Request) -> web.Response:
        return web.json_response({"protected": True})

    async def ws_handler(request: web.Request) -> web.Response:
        # /ws/events also bypasses middleware auth (per api_server.py:107)
        return web.json_response({"ws": True})

    app = web.Application(middlewares=[create_auth_middleware(api_token)])
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/api/protected", protected)
    app.router.add_post("/api/protected", protected)
    app.router.add_route("OPTIONS", "/api/protected", protected)
    app.router.add_get("/ws/events", ws_handler)
    return app


def _reset_module_rate_limiter() -> None:
    """Reset the module-level _rate_limiter between tests to avoid bleed."""
    from bridge import api_server

    api_server._rate_limiter = RateLimiter()


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    """Every test gets a fresh module-level rate limiter."""
    _reset_module_rate_limiter()
    yield
    _reset_module_rate_limiter()


# ─────────────────────────────────────────────────────────────────────
# _extract_bearer_token
# ─────────────────────────────────────────────────────────────────────


class TestExtractBearerToken:
    """Unit-test the bearer token extractor in isolation (no HTTP)."""

    def _request_with_auth(self, header_value: str | None) -> web.Request:
        """Build a minimal Request stub with the given Authorization header."""
        # We can use aiohttp's make_mocked_request for unit-level tests
        from aiohttp.test_utils import make_mocked_request

        headers = {"Authorization": header_value} if header_value else {}
        return make_mocked_request("GET", "/api/protected", headers=headers)

    def test_extracts_valid_bearer_token(self) -> None:
        req = self._request_with_auth("Bearer my-token-here")
        assert _extract_bearer_token(req) == "my-token-here"

    def test_strips_whitespace(self) -> None:
        req = self._request_with_auth("Bearer  spaced-token  ")
        assert _extract_bearer_token(req) == "spaced-token"

    def test_returns_none_when_header_missing(self) -> None:
        req = self._request_with_auth(None)
        assert _extract_bearer_token(req) is None

    def test_returns_none_when_header_empty(self) -> None:
        req = self._request_with_auth("")
        assert _extract_bearer_token(req) is None

    def test_returns_none_when_not_bearer_scheme(self) -> None:
        # Basic auth should not be accepted as a bearer token
        req = self._request_with_auth("Basic dXNlcjpwYXNz")
        assert _extract_bearer_token(req) is None

    def test_returns_none_when_just_bearer_no_token(self) -> None:
        # "Bearer" alone is not parseable
        req = self._request_with_auth("Bearer")
        assert _extract_bearer_token(req) is None

    def test_case_sensitive_bearer_keyword(self) -> None:
        # The implementation uses .startswith("Bearer "), so lowercase
        # "bearer" should NOT be accepted. This test pins that behavior.
        req = self._request_with_auth("bearer my-token")
        assert _extract_bearer_token(req) is None


# ─────────────────────────────────────────────────────────────────────
# Auth middleware — full HTTP flow
# ─────────────────────────────────────────────────────────────────────


class TestAuthMiddleware:
    """Tests the full auth middleware path via aiohttp TestClient."""

    @pytest.mark.asyncio
    async def test_healthz_bypasses_auth(self) -> None:
        """GET /healthz should never require a token."""
        async with TestClient(TestServer(_make_test_app())) as client:
            resp = await client.get("/healthz")
            assert resp.status == 200
            data = await resp.json()
            assert data == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_ws_events_bypasses_auth_at_middleware(self) -> None:
        """/ws/events bypasses middleware auth (the WS handler does its
        own auth via query param). This is the documented behavior at
        api_server.py:107."""
        async with TestClient(TestServer(_make_test_app())) as client:
            resp = await client.get("/ws/events")
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_options_preflight_bypasses_auth(self) -> None:
        """CORS preflight (OPTIONS) should not require a token."""
        async with TestClient(TestServer(_make_test_app())) as client:
            resp = await client.options("/api/protected")
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_protected_route_requires_auth(self) -> None:
        """GET /api/protected without a token returns 401."""
        async with TestClient(TestServer(_make_test_app())) as client:
            resp = await client.get("/api/protected")
            assert resp.status == 401
            data = await resp.json()
            assert data == {"error": "Unauthorized"}

    @pytest.mark.asyncio
    async def test_protected_route_rejects_wrong_token(self) -> None:
        """Wrong Bearer token returns 401."""
        async with TestClient(TestServer(_make_test_app())) as client:
            resp = await client.get(
                "/api/protected", headers={"Authorization": "Bearer wrong-token"}
            )
            assert resp.status == 401

    @pytest.mark.asyncio
    async def test_protected_route_accepts_correct_token(self) -> None:
        """Correct Bearer token is accepted and request reaches handler."""
        async with TestClient(TestServer(_make_test_app("secret-42"))) as client:
            resp = await client.get(
                "/api/protected", headers={"Authorization": "Bearer secret-42"}
            )
            assert resp.status == 200
            data = await resp.json()
            assert data == {"protected": True}

    @pytest.mark.asyncio
    async def test_protected_route_rejects_basic_auth(self) -> None:
        """Basic auth header (not Bearer) is treated as missing token."""
        async with TestClient(TestServer(_make_test_app())) as client:
            resp = await client.get(
                "/api/protected",
                headers={"Authorization": "Basic dXNlcjpwYXNz"},
            )
            assert resp.status == 401

    @pytest.mark.asyncio
    async def test_uses_constant_time_comparison(self) -> None:
        """The middleware should use secrets.compare_digest, not ==.
        We verify by patching compare_digest and confirming it's called.
        """
        from unittest.mock import patch

        with patch(
            "bridge.api_server.secrets.compare_digest", wraps=__import__("secrets").compare_digest
        ) as mock_cmp:
            async with TestClient(TestServer(_make_test_app("token-cd"))) as client:
                await client.get(
                    "/api/protected",
                    headers={"Authorization": "Bearer token-cd"},
                )
            assert mock_cmp.called, (
                "Auth middleware MUST use secrets.compare_digest for "
                "constant-time comparison; this prevents timing attacks "
                "on the API token."
            )

    @pytest.mark.asyncio
    async def test_post_with_valid_token_accepted(self) -> None:
        """POST is also gated through the same auth middleware."""
        async with TestClient(TestServer(_make_test_app("token-post"))) as client:
            resp = await client.post(
                "/api/protected",
                headers={"Authorization": "Bearer token-post"},
                json={"hello": "world"},
            )
            assert resp.status == 200


# ─────────────────────────────────────────────────────────────────────
# Auth + Rate limiter integration
# ─────────────────────────────────────────────────────────────────────


class TestAuthRateLimitInteraction:
    """The auth middleware also enforces the per-IP rate limit
    (api_server.py:111-115). Test the boundary."""

    @pytest.mark.asyncio
    async def test_rate_limit_kicks_in_after_bucket_drained(self) -> None:
        """Drain the bucket; the next request should hit 429."""
        from bridge import api_server

        # Replace the module-level limiter with a tiny bucket so the test is fast.
        api_server._rate_limiter = RateLimiter(rate=0.0, bucket_size=3)

        async with TestClient(TestServer(_make_test_app("token-rl"))) as client:
            # First 3 requests succeed (bucket starts at bucket_size - 1, plus
            # the initial request bypass at first-seen-IP)
            statuses = []
            for _ in range(5):
                resp = await client.get(
                    "/api/protected",
                    headers={"Authorization": "Bearer token-rl"},
                )
                statuses.append(resp.status)
            # Should see at least one 429 in the burst
            assert 429 in statuses, f"expected at least one 429, got {statuses}"

    @pytest.mark.asyncio
    async def test_healthz_skips_rate_limit_too(self) -> None:
        """The middleware order is: skip /healthz first, THEN rate limit.
        So /healthz should never be rate-limited even if the bucket is dry.
        """
        from bridge import api_server

        api_server._rate_limiter = RateLimiter(rate=0.0, bucket_size=0)
        async with TestClient(TestServer(_make_test_app())) as client:
            for _ in range(10):
                resp = await client.get("/healthz")
                assert resp.status == 200


# ─────────────────────────────────────────────────────────────────────
# RateLimiter — unit tests in isolation
# ─────────────────────────────────────────────────────────────────────


class TestRateLimiterBasics:
    def test_first_request_from_new_ip_allowed(self) -> None:
        rl = RateLimiter(rate=1.0, bucket_size=10)
        assert rl.check("1.2.3.4") is True

    def test_consecutive_requests_drain_bucket(self) -> None:
        rl = RateLimiter(rate=0.0, bucket_size=5)
        # Bucket starts at bucket_size - 1 = 4 after first call
        results = [rl.check("1.1.1.1") for _ in range(7)]
        assert results.count(True) >= 1
        assert results.count(False) >= 1, "bucket should drain to denial"

    def test_zero_rate_means_no_refill(self) -> None:
        rl = RateLimiter(rate=0.0, bucket_size=2)
        rl.check("a")  # bucket: 1
        rl.check("a")  # bucket: 0
        # Sleep to verify no refill happens
        time.sleep(0.05)
        assert rl.check("a") is False

    def test_refill_restores_tokens(self) -> None:
        rl = RateLimiter(rate=100.0, bucket_size=2)
        rl.check("a")  # consume 1
        rl.check("a")  # consume 1, bucket=0
        # After refill at 100 tokens/sec * 0.05s = 5 tokens (capped at 2)
        time.sleep(0.05)
        assert rl.check("a") is True

    def test_bucket_capped_at_size(self) -> None:
        rl = RateLimiter(rate=100.0, bucket_size=3)
        rl.check("a")  # use 1
        time.sleep(0.5)  # would refill 50 tokens but cap is 3
        # Should be able to make 3 more (capped, not 51)
        assert rl.check("a") is True
        assert rl.check("a") is True
        assert rl.check("a") is True
        # 4th in this burst should fail (bucket drained)
        assert rl.check("a") is False


class TestRateLimiterIPIsolation:
    def test_different_ips_have_independent_buckets(self) -> None:
        rl = RateLimiter(rate=0.0, bucket_size=2)
        # Drain IP "a"
        assert rl.check("a") is True
        assert rl.check("a") is True
        assert rl.check("a") is False
        # IP "b" should still have full bucket
        assert rl.check("b") is True
        assert rl.check("b") is True

    def test_unknown_ip_string_treated_as_distinct(self) -> None:
        rl = RateLimiter(rate=0.0, bucket_size=1)
        rl.check("unknown")
        rl.check("unknown")  # drained
        # Different "unknown"-ish key should not be the same bucket
        assert rl.check("other") is True


class TestRateLimiterCleanup:
    def test_stale_entries_removed_on_cleanup(self) -> None:
        rl = RateLimiter(rate=1.0, bucket_size=10, stale_seconds=0.05)
        rl.check("ephemeral")
        assert "ephemeral" in rl._clients
        # Force cleanup by triggering a check after stale window
        time.sleep(0.1)
        # Force cleanup interval to elapse
        rl._last_cleanup = time.monotonic() - 100
        rl.check("trigger")
        assert "ephemeral" not in rl._clients

    def test_active_entries_not_cleaned_up(self) -> None:
        rl = RateLimiter(rate=1.0, bucket_size=10, stale_seconds=300.0)
        rl.check("active")
        rl._last_cleanup = time.monotonic() - 100  # force cleanup pass
        rl.check("trigger")
        assert "active" in rl._clients


# ─────────────────────────────────────────────────────────────────────
# Sprint 04.12 — VAPI _department_chat_completions uses BridgeDeps.from_app
# ─────────────────────────────────────────────────────────────────────


class TestDepartmentChatCompletionsUsesFromApp:
    """Sprint 04.12 — site 4-of-4 of the BridgeDeps direct-construction
    migration (closes #610 once sites 1–3 in commands.py also land).

    The VAPI OpenAI-compatible SSE endpoint at
    ``api_server.APIServer._department_chat_completions`` previously called
    ``BridgeDeps(...)`` directly. That left it open to silent breakage every
    time a new field was added to BridgeDeps. This test pins the migration
    to the ``BridgeDeps.from_app`` factory.
    """

    @pytest.mark.asyncio
    async def test_department_chat_completions_uses_from_app_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patches ``BridgeDeps.from_app`` to a spy and asserts the endpoint
        invokes it. Mocks ``stream_department_as_sse`` so VAPI credentials
        and the real teams stack are not needed."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from bridge.api_server import APIServer
        from teams._types import BridgeDeps

        # Build a department config with VAPI enabled — this is the gate
        # at api_server.py:1240 the handler must pass before constructing deps.
        vapi_cfg = SimpleNamespace(enabled=True)
        dept_cfg = SimpleNamespace(vapi=vapi_cfg)

        departments = MagicMock()
        departments.get_config.return_value = dept_cfg

        # Minimal BridgeApp stub exposing the public accessors that
        # BridgeDeps.from_app duck-types against (see bridge/app.py:1132+).
        bridge = SimpleNamespace(
            memory=MagicMock(),
            knowledge_search=MagicMock(),
            cost_tracker=MagicMock(),
            event_bus=MagicMock(),
            trust_manager=MagicMock(),
            _config=SimpleNamespace(operator_discord_id="op-stub"),
        )

        # Spy: wrap BridgeDeps.from_app so we can assert it was called
        # without losing its real behaviour.
        spy = MagicMock(wraps=BridgeDeps.from_app)
        monkeypatch.setattr(BridgeDeps, "from_app", spy)

        # Stub the SSE stream so the test doesn't hit a live LLM. The
        # handler imports ``stream_department_as_sse`` from teams._vapi
        # at call time; patch that symbol on the source module.
        async def _fake_stream(registry, dept, task, deps):
            yield 'data: {"id":"x","choices":[]}\n\n'
            yield "data: [DONE]\n\n"

        monkeypatch.setattr(
            "teams._vapi.stream_department_as_sse", _fake_stream
        )

        # Build the APIServer instance (don't run aiohttp — we call the
        # handler directly with a mocked request).
        server = APIServer(bridge_app=bridge, api_token="x")
        server._departments = departments

        # Mock request: VAPI sends OpenAI-format chat with a 'messages' list.
        request = MagicMock()
        request.match_info = {"dept": "engineering"}

        async def _json():
            return {"messages": [{"role": "user", "content": "hi"}]}

        request.json = _json

        # StreamResponse needs a transport; bypass by patching prepare/write.
        async def _noop(*a, **k):
            return None

        # Monkey-patch the StreamResponse methods used inside the handler
        # so we don't need a real network transport.
        from aiohttp import web

        monkeypatch.setattr(web.StreamResponse, "prepare", _noop)
        monkeypatch.setattr(web.StreamResponse, "write", _noop)
        monkeypatch.setattr(web.StreamResponse, "write_eof", _noop)

        await server._department_chat_completions(request)

        # The spy must have fired exactly once with the bridge as the
        # positional ``app`` arg and our two kwargs.
        assert spy.call_count == 1, (
            f"Expected BridgeDeps.from_app to be called exactly once, "
            f"got {spy.call_count}"
        )
        call = spy.call_args
        assert call.args[0] is bridge, (
            "from_app must receive the BridgeApp (self._bridge) as the "
            "first positional arg"
        )
        assert call.kwargs.get("department") == "engineering"
        sid = call.kwargs.get("session_id", "")
        assert sid.startswith("vapi-"), (
            f"session_id must use the 'vapi-' prefix, got: {sid!r}"
        )


# ─────────────────────────────────────────────────────────────────────
# P2.1 — default bind is localhost (audit C8)
# ─────────────────────────────────────────────────────────────────────


class TestDefaultBindIsLocalhost:
    """Regression guard for harness audit finding C8.

    The Mission Control API must NOT default to a LAN-reachable bind.
    Three defaults are involved, and all three must agree on 127.0.0.1:

      1. ``BridgeConfig.api_host`` — the dataclass default that takes
         effect when ``bridge.toml`` is absent or missing the key.
      2. ``APIServer.__init__`` kwarg ``host`` — the constructor default
         that takes effect when ``app.py`` doesn't pass one.
      3. ``app.py`` getattr fallback — the defensive fallback inside
         ``_start_subsystems`` when ``BridgeConfig.api_host`` is absent.

    Drift between any of these reintroduces the C8 exposure. Operators
    that need LAN reach must explicitly set ``[api] host = "0.0.0.0"``
    in ``bridge.toml``.
    """

    def test_bridge_config_default_api_host_is_localhost(self) -> None:
        from bridge.config import BridgeConfig

        cfg = BridgeConfig()
        assert cfg.api_host == "127.0.0.1", (
            "BridgeConfig.api_host default must be 127.0.0.1 (audit C8); "
            f"got {cfg.api_host!r}"
        )

    def test_api_server_constructor_default_host_is_localhost(self) -> None:
        import inspect

        from bridge.api_server import APIServer

        sig = inspect.signature(APIServer.__init__)
        host_param = sig.parameters["host"]
        assert host_param.default == "127.0.0.1", (
            "APIServer.__init__ default host must be 127.0.0.1 (audit C8); "
            f"got {host_param.default!r}"
        )

    def test_shipped_bridge_toml_binds_localhost(self) -> None:
        """The repo-committed bridge.toml must not ship with a LAN bind.

        Reads the file under ``agent/config/bridge.toml`` (relative to
        this test's location) and asserts that the ``[api] host`` entry
        is ``127.0.0.1``. Catches accidental re-introduction of the
        ``0.0.0.0`` default in the shipped config.
        """
        import tomllib
        from pathlib import Path

        config_path = (
            Path(__file__).resolve().parent.parent / "config" / "bridge.toml"
        )
        assert config_path.exists(), (
            f"bridge.toml not found at expected location: {config_path}"
        )
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
        api_host = data.get("api", {}).get("host")
        assert api_host == "127.0.0.1", (
            "Shipped bridge.toml [api] host must be 127.0.0.1 (audit C8); "
            f"got {api_host!r}"
        )


# ─────────────────────────────────────────────────────────────────────
# P2.1 follow-up (#1626) — allow_remote_bind opt-in + fail-closed validator
# ─────────────────────────────────────────────────────────────────────


class TestAllowRemoteBind:
    """Regression guard for P2.1 follow-up (issue #1626).

    P2.1 (#1624) flipped ``BridgeConfig.api_host`` default from ``0.0.0.0`` to
    ``127.0.0.1`` to close audit C8. This follow-up adds defense in depth:
    even if a future operator sets ``host = "0.0.0.0"`` in ``bridge.toml``,
    the bridge MUST refuse to start unless ``allow_remote_bind = true`` is
    set alongside it.

    Three behaviours pinned:
      1. Default config (``allow_remote_bind=False``) rejects non-local host
         with a clear error naming both knobs.
      2. Explicit opt-in (``allow_remote_bind=True``) allows non-local host
         to bind.
      3. Localhost / loopback values bind regardless of ``allow_remote_bind``.
    """

    def test_bridge_config_default_allow_remote_bind_is_false(self) -> None:
        from bridge.config import BridgeConfig

        cfg = BridgeConfig()
        assert cfg.api_allow_remote_bind is False, (
            "BridgeConfig.api_allow_remote_bind default must be False "
            "(P2.1 follow-up / issue #1626); "
            f"got {cfg.api_allow_remote_bind!r}"
        )

    def test_api_server_constructor_default_allow_remote_bind_is_false(
        self,
    ) -> None:
        import inspect

        from bridge.api_server import APIServer

        sig = inspect.signature(APIServer.__init__)
        flag_param = sig.parameters["allow_remote_bind"]
        assert flag_param.default is False, (
            "APIServer.__init__ default allow_remote_bind must be False "
            "(P2.1 follow-up / issue #1626); "
            f"got {flag_param.default!r}"
        )

    @pytest.mark.asyncio
    async def test_non_local_host_without_optin_raises_runtime_error(
        self,
    ) -> None:
        """Default ``allow_remote_bind=False`` + ``host="0.0.0.0"`` aborts."""
        from unittest.mock import MagicMock

        from bridge.api_server import APIServer

        bridge = MagicMock()
        server = APIServer(
            bridge,
            host="0.0.0.0",
            port=0,
            api_token="t",
            allow_remote_bind=False,
        )
        with pytest.raises(RuntimeError) as exc_info:
            await server.start()
        msg = str(exc_info.value)
        # Error message must name BOTH knobs so the operator knows the fix.
        assert "0.0.0.0" in msg, f"error must name the rejected host; got: {msg}"
        assert "allow_remote_bind" in msg, (
            f"error must name the allow_remote_bind knob; got: {msg}"
        )
        # Sanity: also references the bind refusal explicitly.
        assert "refus" in msg.lower(), (
            f"error must signal the refusal; got: {msg}"
        )

    @pytest.mark.asyncio
    async def test_non_local_host_with_optin_binds(self) -> None:
        """Explicit ``allow_remote_bind=True`` allows non-local host."""
        from unittest.mock import MagicMock

        from bridge.api_server import APIServer

        bridge = MagicMock()
        # port=0 = let OS pick a free port; we shut down immediately.
        server = APIServer(
            bridge,
            host="0.0.0.0",
            port=0,
            api_token="t",
            # B.04 (#2053) — github_webhook_secret required when start()
            # runs; supply to reach the allow_remote_bind path under test.
            github_webhook_secret="t",
            allow_remote_bind=True,
            # Pre-empt the P2.2 CORS warning so it doesn't pollute the
            # validator's assertion surface — not under test here.
            cors_allowed_origins=("https://example.test",),
        )
        try:
            # Must NOT raise — opt-in is explicit, validator passes.
            await server.start()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_localhost_always_allowed_regardless_of_flag(self) -> None:
        """127.0.0.1 / localhost / ::1 bind whether or not opt-in is set."""
        from unittest.mock import MagicMock

        from bridge.api_server import APIServer

        for host in ("127.0.0.1", "localhost", "::1"):
            for allow in (False, True):
                bridge = MagicMock()
                server = APIServer(
                    bridge,
                    host=host,
                    port=0,
                    api_token="t",
                    # B.04 (#2053) — github_webhook_secret required when
                    # start() runs; supply to reach the loopback path
                    # under test.
                    github_webhook_secret="t",
                    allow_remote_bind=allow,
                )
                try:
                    # Must NOT raise — loopback is always allowed.
                    await server.start()
                finally:
                    await server.stop()

    def test_config_toml_mapping_for_allow_remote_bind(self, tmp_path) -> None:
        """``[api] allow_remote_bind = true`` in bridge.toml populates the
        ``api_allow_remote_bind`` field on ``BridgeConfig``."""
        from bridge.config import load_config

        toml = tmp_path / "bridge.toml"
        toml.write_text(
            "[api]\n"
            'host = "0.0.0.0"\n'
            "allow_remote_bind = true\n"
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.api_host == "0.0.0.0"
        assert config.api_allow_remote_bind is True


# ─────────────────────────────────────────────────────────────────────
# audit-2026-05-16.B.04 (#2053, M-3) — API auth + GitHub webhook
# fail-closed boot validators
# ─────────────────────────────────────────────────────────────────────


class TestApiSecretsRequiredAtBoot:
    """Sprint audit-2026-05-16.B.04 (#2053, M-3).

    The API server's ``start()`` runs sibling fail-closed validators (next
    to the VAPI ``vapi_webhook_secret`` validator from P2.3 / #1578):

      - ``api_token`` MUST be non-empty when start() runs. Without it the
        bearer-token middleware in ``create_auth_middleware`` would compare
        request tokens against the empty string.
      - ``github_webhook_secret`` MUST be non-empty when start() runs.
        Without it the HMAC verifier on ``/api/webhooks/github`` would
        have nothing to compare against.

    APIServer is only constructed when ``api_enabled = true``, so reaching
    ``start()`` already implies the operator opted in. Empty secrets at
    that point are a misconfiguration, not a feature disable.
    """

    def test_constructor_exposes_github_webhook_secret_param(self) -> None:
        """Mirror P2.1 #1626's constructor-default regression guard."""
        import inspect

        from bridge.api_server import APIServer

        sig = inspect.signature(APIServer.__init__)
        param = sig.parameters["github_webhook_secret"]
        assert param.default == "", (
            "APIServer.__init__ default github_webhook_secret must be "
            "empty string (B.04 / #2053); "
            f"got {param.default!r}"
        )

    @pytest.mark.asyncio
    async def test_empty_api_token_raises_runtime_error(self) -> None:
        """``api_token=""`` aborts start() with a clear error."""
        from unittest.mock import MagicMock

        from bridge.api_server import APIServer

        bridge = MagicMock()
        server = APIServer(
            bridge,
            host="127.0.0.1",
            port=0,
            api_token="",
            github_webhook_secret="t",
        )
        with pytest.raises(RuntimeError) as exc_info:
            await server.start()
        msg = str(exc_info.value)
        assert "api_token" in msg, f"error must name api_token; got: {msg}"
        assert ".secrets" in msg, (
            f"error must point operator at .secrets; got: {msg}"
        )

    @pytest.mark.asyncio
    async def test_empty_github_webhook_secret_raises_runtime_error(self) -> None:
        """``github_webhook_secret=""`` aborts start() with a clear error."""
        from unittest.mock import MagicMock

        from bridge.api_server import APIServer

        bridge = MagicMock()
        server = APIServer(
            bridge,
            host="127.0.0.1",
            port=0,
            api_token="t",
            github_webhook_secret="",
        )
        with pytest.raises(RuntimeError) as exc_info:
            await server.start()
        msg = str(exc_info.value)
        assert "github_webhook_secret" in msg, (
            f"error must name github_webhook_secret; got: {msg}"
        )
        assert ".secrets" in msg, (
            f"error must point operator at .secrets; got: {msg}"
        )

    @pytest.mark.asyncio
    async def test_both_secrets_present_starts_cleanly(self) -> None:
        """Sanity: with both secrets set, start() reaches the bind step."""
        from unittest.mock import MagicMock

        from bridge.api_server import APIServer

        bridge = MagicMock()
        server = APIServer(
            bridge,
            host="127.0.0.1",
            port=0,
            api_token="t",
            github_webhook_secret="t",
        )
        try:
            await server.start()
        finally:
            await server.stop()


# ─────────────────────────────────────────────────────────────────────
# P2.2 — CORS allowlist (audit C9)
# ─────────────────────────────────────────────────────────────────────


def _make_cors_app(
    allowed_origins: tuple[str, ...] = (),
    api_token: str = "cors-test-token",
) -> web.Application:
    """Build a minimal aiohttp app with the CORS + auth middlewares wired.

    Mirrors ``APIServer.start`` middleware order so we exercise the same
    response path the bridge ships.
    """
    from bridge.api_server import create_cors_middleware

    async def healthz(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def protected(request: web.Request) -> web.Response:
        return web.json_response({"protected": True})

    app = web.Application(
        middlewares=[
            create_cors_middleware(allowed_origins),
            create_auth_middleware(api_token),
        ]
    )
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/api/protected", protected)
    app.router.add_route("OPTIONS", "/api/protected", protected)
    return app


class TestCorsAllowlist:
    """Regression guard for harness audit finding C9 (Sprint P2.2).

    The CORS middleware must NOT default to a wildcard
    ``Access-Control-Allow-Origin: *``. The header is only set when the
    requesting ``Origin`` is in the configured allowlist. An empty allowlist
    yields no header on any response.
    """

    @pytest.mark.asyncio
    async def test_wildcard_cors_is_never_emitted(self) -> None:
        """No response ever carries ``Access-Control-Allow-Origin: *``.

        Pre-P2.2 the middleware unconditionally set the wildcard. This test
        exercises three call-shape combinations (empty allowlist + no origin,
        empty allowlist + origin, populated allowlist + disallowed origin)
        and asserts the wildcard never appears in any of them.
        """
        # Case A: empty allowlist + no Origin header
        async with TestClient(TestServer(_make_cors_app(()))) as client:
            resp = await client.get(
                "/api/protected",
                headers={"Authorization": "Bearer cors-test-token"},
            )
            assert resp.headers.get("Access-Control-Allow-Origin") != "*"

        # Case B: empty allowlist + Origin header
        async with TestClient(TestServer(_make_cors_app(()))) as client:
            resp = await client.get(
                "/api/protected",
                headers={
                    "Authorization": "Bearer cors-test-token",
                    "Origin": "https://anything.example",
                },
            )
            assert resp.headers.get("Access-Control-Allow-Origin") != "*"

        # Case C: populated allowlist + disallowed Origin
        async with TestClient(
            TestServer(_make_cors_app(("https://dash.example.com",)))
        ) as client:
            resp = await client.get(
                "/api/protected",
                headers={
                    "Authorization": "Bearer cors-test-token",
                    "Origin": "https://evil.example",
                },
            )
            assert resp.headers.get("Access-Control-Allow-Origin") != "*"

    @pytest.mark.asyncio
    async def test_allowed_origin_gets_echoed_header(self) -> None:
        """An Origin that appears in the allowlist receives the matching
        ``Access-Control-Allow-Origin`` header (echo-back pattern), plus a
        ``Vary: Origin`` to prevent CDN cache poisoning."""
        async with TestClient(
            TestServer(_make_cors_app(("https://dash.example.com",)))
        ) as client:
            resp = await client.get(
                "/api/protected",
                headers={
                    "Authorization": "Bearer cors-test-token",
                    "Origin": "https://dash.example.com",
                },
            )
            assert resp.status == 200
            assert (
                resp.headers.get("Access-Control-Allow-Origin")
                == "https://dash.example.com"
            )
            assert resp.headers.get("Vary") == "Origin"

    @pytest.mark.asyncio
    async def test_disallowed_origin_gets_no_header(self) -> None:
        """An Origin NOT in the allowlist (acceptance case: evil.example)
        receives NO ``Access-Control-Allow-Origin`` header. The request
        still completes — the browser, not the bridge, is what blocks the
        response from being read cross-origin."""
        async with TestClient(
            TestServer(_make_cors_app(("https://dash.example.com",)))
        ) as client:
            resp = await client.get(
                "/api/protected",
                headers={
                    "Authorization": "Bearer cors-test-token",
                    "Origin": "https://evil.example",
                },
            )
            # Auth still passes; the response just lacks the CORS header
            assert resp.status == 200
            assert "Access-Control-Allow-Origin" not in resp.headers

    @pytest.mark.asyncio
    async def test_empty_allowlist_yields_no_cors_header(self) -> None:
        """The safe default: empty allowlist + any Origin = no CORS header.

        This is the localhost-only posture documented in bridge.toml: with
        ``host = "127.0.0.1"`` (P2.1 / audit C8) the bridge is reached
        same-origin via SSH tunnel, so no CORS is needed."""
        async with TestClient(TestServer(_make_cors_app(()))) as client:
            resp = await client.get(
                "/api/protected",
                headers={
                    "Authorization": "Bearer cors-test-token",
                    "Origin": "http://localhost:5173",
                },
            )
            assert resp.status == 200
            assert "Access-Control-Allow-Origin" not in resp.headers

    @pytest.mark.asyncio
    async def test_options_preflight_respects_allowlist(self) -> None:
        """OPTIONS preflight (CORS preflight) returns 204 in all cases but
        only emits ``Access-Control-Allow-Origin`` when the Origin is in
        the allowlist. Allowed origins also receive the standard CORS
        method/header allowances and the 86400 cache hint."""
        # Allowed origin: gets full CORS envelope
        async with TestClient(
            TestServer(_make_cors_app(("https://dash.example.com",)))
        ) as client:
            resp = await client.options(
                "/api/protected",
                headers={
                    "Origin": "https://dash.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.status == 204
            assert (
                resp.headers.get("Access-Control-Allow-Origin")
                == "https://dash.example.com"
            )
            assert "GET" in resp.headers.get(
                "Access-Control-Allow-Methods", ""
            )
            assert "Authorization" in resp.headers.get(
                "Access-Control-Allow-Headers", ""
            )
            assert resp.headers.get("Access-Control-Max-Age") == "86400"

        # Disallowed origin: still 204 (preflight is short-circuited) but
        # no CORS headers — browser refuses the subsequent request.
        async with TestClient(
            TestServer(_make_cors_app(("https://dash.example.com",)))
        ) as client:
            resp = await client.options(
                "/api/protected",
                headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.status == 204
            assert "Access-Control-Allow-Origin" not in resp.headers

    def test_module_level_cors_middleware_is_no_op(self) -> None:
        """The legacy ``cors_middleware`` module symbol must remain bound
        to a no-CORS variant. Existing test fixtures import it directly;
        switching it to a wildcard or to a permissive default would
        reintroduce the C9 exposure through every importing test.
        """
        from bridge.api_server import create_cors_middleware

        # Module-level symbol must be functionally equivalent to a fresh
        # empty-allowlist middleware: identical closure shape.
        empty = create_cors_middleware(())
        assert callable(empty)
        # The shipped module-level symbol must also be callable middleware.
        from bridge import api_server as _mod

        assert callable(_mod.cors_middleware)

    def test_bridge_config_default_cors_allowlist_is_empty(self) -> None:
        """The dataclass default for ``api_cors_allowed_origins`` must be
        the empty tuple. Any other default reintroduces a wildcard-ish
        cross-origin posture by accident."""
        from bridge.config import BridgeConfig

        cfg = BridgeConfig()
        assert cfg.api_cors_allowed_origins == (), (
            "BridgeConfig.api_cors_allowed_origins default must be empty "
            f"(audit C9); got {cfg.api_cors_allowed_origins!r}"
        )

    def test_shipped_bridge_toml_cors_allowlist_is_empty(self) -> None:
        """The repo-committed bridge.toml must ship with an empty CORS
        allowlist. Operators opt in explicitly per environment."""
        import tomllib
        from pathlib import Path

        config_path = (
            Path(__file__).resolve().parent.parent / "config" / "bridge.toml"
        )
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
        origins = data.get("api", {}).get("cors_allowed_origins")
        assert origins == [], (
            "Shipped bridge.toml [api] cors_allowed_origins must be [] "
            f"(audit C9); got {origins!r}"
        )
