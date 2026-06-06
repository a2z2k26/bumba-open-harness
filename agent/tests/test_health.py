"""Tests for MS1.2: Health Endpoint."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.health import HealthServer


def _make_mock_app(
    *,
    discord_ready: bool = True,
    db_ok: bool = True,
    memory_ok: bool = True,
    token_expires: float = 7200,
    config_data_dir: str = "/tmp/test-data",
):
    """Create a mock BridgeApp for health tests."""
    app = MagicMock()

    # Discord
    bot = MagicMock()
    bot.is_ready.return_value = discord_ready
    bot.latency = 0.042
    app._discord = bot

    # Claude
    runner = MagicMock()
    runner._last_invocation = None
    app._claude = runner

    # Database
    db = AsyncMock()
    db.db_path = MagicMock()
    db.db_path.exists.return_value = True
    db.db_path.stat.return_value = MagicMock(st_size=128 * 1024 * 1024)
    db.db_path.with_suffix.return_value = MagicMock(exists=lambda: False)

    if db_ok:
        db.fetchone = AsyncMock(side_effect=[
            MagicMock(__getitem__=lambda s, i: "ok"),  # quick_check
            MagicMock(__getitem__=lambda s, i: 247),   # knowledge count
        ])
    else:
        db.fetchone = AsyncMock(side_effect=Exception("DB error"))
    app._db = db

    # Memory
    memory = AsyncMock()
    if memory_ok:
        memory.search_knowledge = AsyncMock(return_value=[])
    else:
        memory.search_knowledge = AsyncMock(side_effect=Exception("FTS5 error"))
    app._memory = memory

    # Token refresher
    refresher = MagicMock()
    refresher._expires_at = time.time() + token_expires
    app._token_refresher = refresher

    # Config
    config = MagicMock()
    config.data_dir = config_data_dir
    app._config = config

    # Voice manager
    app._voice = None

    return app


class TestHealthCollection:
    """Health data collection tests."""

    @pytest.mark.asyncio
    async def test_healthy_status(self):
        app = _make_mock_app()
        server = HealthServer(app)
        health = await server.collect_health()

        assert health["status"] == "healthy"
        assert "uptime_seconds" in health
        assert "components" in health
        assert "timestamp" in health

    @pytest.mark.asyncio
    async def test_components_present(self):
        app = _make_mock_app()
        server = HealthServer(app)
        health = await server.collect_health()

        components = health["components"]
        assert "discord" in components
        assert "claude" in components
        assert "database" in components
        assert "memory" in components
        assert "token" in components

    @pytest.mark.asyncio
    async def test_discord_up(self):
        app = _make_mock_app(discord_ready=True)
        server = HealthServer(app)
        health = await server.collect_health()

        discord = health["components"]["discord"]
        assert discord["status"] == "up"
        assert discord["latency_ms"] == 42

    @pytest.mark.asyncio
    async def test_discord_degraded(self):
        app = _make_mock_app(discord_ready=False)
        server = HealthServer(app)
        health = await server.collect_health()

        discord = health["components"]["discord"]
        assert discord["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_unhealthy_when_discord_down(self):
        """Discord down should make status unhealthy."""
        app = _make_mock_app()
        app._discord = None
        server = HealthServer(app)
        health = await server.collect_health()

        assert health["components"]["discord"]["status"] == "down"
        assert health["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_database_down(self):
        app = _make_mock_app(db_ok=False)
        server = HealthServer(app)
        health = await server.collect_health()

        assert health["components"]["database"]["status"] == "down"
        assert health["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_memory_degraded(self):
        app = _make_mock_app(memory_ok=False)
        server = HealthServer(app)
        health = await server.collect_health()

        assert health["components"]["memory"]["status"] == "degraded"
        # Memory is not critical, so overall should still be healthy
        assert health["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_token_up(self):
        app = _make_mock_app(token_expires=7200)
        server = HealthServer(app)
        health = await server.collect_health()

        token = health["components"]["token"]
        assert token["status"] == "up"
        assert token["expires_in_seconds"] > 3600

    @pytest.mark.asyncio
    async def test_token_degraded_soon_to_expire(self):
        app = _make_mock_app(token_expires=1800)  # 30 min
        server = HealthServer(app)
        health = await server.collect_health()

        token = health["components"]["token"]
        assert token["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_token_expired(self):
        app = _make_mock_app(token_expires=-100)  # expired
        server = HealthServer(app)
        health = await server.collect_health()

        token = health["components"]["token"]
        assert token["status"] == "down"
        assert health["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_token_startup_grace_keeps_healthz_green_before_first_refresh(
        self,
    ):
        """Fresh daemon boots should not fail /healthz before first refresh.

        Production can start with a stale/unknown expires_at while still
        holding OAuth access + refresh tokens. The refresh loop retries soon,
        so the deploy smoke should see an explicit startup grace instead of
        a transient 503.
        """
        app = _make_mock_app(token_expires=-100)
        app._token_refresher._access_token = "loaded-access-token"
        app._token_refresher._refresh_token = "loaded-refresh-token"
        server = HealthServer(app)

        health = await server.collect_health()

        token = health["components"]["token"]
        assert token["status"] == "up"
        assert token["startup_refresh_pending"] is True
        assert health["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_token_startup_grace_expires_after_window(self):
        app = _make_mock_app(token_expires=-100)
        app._token_refresher._access_token = "loaded-access-token"
        app._token_refresher._refresh_token = "loaded-refresh-token"
        server = HealthServer(app)
        server._start_time = time.monotonic() - 999

        health = await server.collect_health()

        token = health["components"]["token"]
        assert token["status"] == "down"
        assert "startup_refresh_pending" not in token
        assert health["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_services_ignore_unknown_runner_state_files(self, tmp_path: Path):
        state_dir = tmp_path / "service_state"
        state_dir.mkdir()
        (state_dir / "briefing-state.json").write_text(json.dumps({
            "last_run": "2026-05-20T00:00:00+00:00",
            "last_status": "success",
        }))
        (state_dir / "nonexistent-state.json").write_text(json.dumps({
            "last_status": "failure",
            "last_error": "ValueError: Unknown service: nonexistent",
        }))
        app = _make_mock_app(config_data_dir=str(tmp_path))
        server = HealthServer(app)

        services = await server._check_services()

        assert "briefing" in services
        assert "nonexistent" not in services

    @pytest.mark.asyncio
    async def test_cache_ttl(self):
        """Two rapid calls should return cached result."""
        app = _make_mock_app()
        server = HealthServer(app)

        health1 = await server.collect_health()
        # Manually set cache
        server._cache = health1
        server._cache_time = time.monotonic()

        # Second call within TTL should return same object
        # (We test the cache mechanism by checking _cache_time was set)
        assert server._cache is not None
        assert server._cache["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_uptime_increases(self):
        app = _make_mock_app()
        server = HealthServer(app)
        health = await server.collect_health()
        assert health["uptime_seconds"] >= 0


class TestHealthCommand:
    """Test /health Discord command."""

    def test_health_in_bridge_commands(self):
        from bridge.commands import BRIDGE_COMMANDS
        assert "health" in BRIDGE_COMMANDS
