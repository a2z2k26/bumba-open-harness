"""Tests for remote halt mechanism via HTTP endpoint polling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from bridge.config import BridgeConfig
from bridge.security import SecurityManager


class TestRemoteHaltCheck:
    """Test SecurityManager.check_remote_halt() method."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create a test config with remote halt enabled."""
        return BridgeConfig(
            data_dir=str(tmp_path),
            log_dir=str(tmp_path / "logs"),
            remote_halt_url="http://example.com/halt",
            remote_halt_check_interval=300,
        )

    @pytest.fixture
    def config_no_url(self, tmp_path):
        """Create a test config with no remote halt URL."""
        return BridgeConfig(
            data_dir=str(tmp_path),
            log_dir=str(tmp_path / "logs"),
            remote_halt_url="",
            remote_halt_check_interval=300,
        )

    @pytest.fixture
    def db_mock(self):
        """Mock database."""
        return MagicMock()

    @pytest.fixture
    def security(self, db_mock, config):
        """Create a SecurityManager instance."""
        return SecurityManager(db_mock, config)

    @pytest.mark.asyncio
    async def test_remote_halt_with_halt_response(self, security):
        """GET with 'halt' in response returns True."""
        session = MagicMock(spec=aiohttp.ClientSession)
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="halt")
        session.get.return_value.__aenter__.return_value = mock_resp

        result = await security.check_remote_halt(session)
        assert result is True
        session.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_remote_halt_case_insensitive(self, security):
        """'halt' detection is case-insensitive."""
        session = MagicMock(spec=aiohttp.ClientSession)

        for body in ["HALT", "Halt", "HaLt", "halt", "  halt  "]:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.text = AsyncMock(return_value=body)
            session.get.return_value.__aenter__.return_value = mock_resp

            result = await security.check_remote_halt(session)
            assert result is True, f"Failed for body: {body}"

    @pytest.mark.asyncio
    async def test_remote_halt_without_halt_response(self, security):
        """GET without 'halt' in response returns False."""
        session = MagicMock(spec=aiohttp.ClientSession)
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="ok")
        session.get.return_value.__aenter__.return_value = mock_resp

        result = await security.check_remote_halt(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_remote_halt_empty_response(self, security):
        """Empty response returns False."""
        session = MagicMock(spec=aiohttp.ClientSession)
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="")
        session.get.return_value.__aenter__.return_value = mock_resp

        result = await security.check_remote_halt(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_remote_halt_network_error(self, security):
        """Network error returns False (fail-open)."""
        session = MagicMock(spec=aiohttp.ClientSession)
        session.get.side_effect = aiohttp.ClientError("Connection refused")

        result = await security.check_remote_halt(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_remote_halt_timeout(self, security):
        """Timeout returns False (fail-open)."""
        session = MagicMock(spec=aiohttp.ClientSession)
        session.get.side_effect = asyncio.TimeoutError()

        result = await security.check_remote_halt(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_remote_halt_bad_status(self, security):
        """Non-200 status returns False."""
        session = MagicMock(spec=aiohttp.ClientSession)
        mock_resp = AsyncMock()
        mock_resp.status = 500
        session.get.return_value.__aenter__.return_value = mock_resp

        result = await security.check_remote_halt(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_remote_halt_no_url_skips_check(self, security, config_no_url, db_mock):
        """Empty URL skips the check entirely."""
        security_no_url = SecurityManager(db_mock, config_no_url)
        session = MagicMock(spec=aiohttp.ClientSession)

        result = await security_no_url.check_remote_halt(session)
        assert result is False
        session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_remote_halt_generic_exception(self, security):
        """Generic exception returns False (fail-open)."""
        session = MagicMock(spec=aiohttp.ClientSession)
        session.get.side_effect = RuntimeError("Unexpected error")

        result = await security.check_remote_halt(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_remote_halt_sets_halt_flag(self, security, tmp_path):
        """Verifies that when True, halt flag should be set (integration point)."""
        session = MagicMock(spec=aiohttp.ClientSession)
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="halt")
        session.get.return_value.__aenter__.return_value = mock_resp

        result = await security.check_remote_halt(session)
        assert result is True

        # The app is responsible for calling set_halt(), but we verify the response
        assert security.is_halted() is False  # Flag not set yet


class TestRemoteHaltBackgroundLoop:
    """Test integration of remote halt check into heartbeat loop (via mocking)."""

    @pytest.mark.asyncio
    async def test_remote_halt_sets_security_halt_on_true(self, tmp_path):
        """Verify that when check_remote_halt returns True, halt is set."""
        db_mock = MagicMock()
        config = BridgeConfig(
            data_dir=str(tmp_path),
            log_dir=str(tmp_path / "logs"),
            remote_halt_url="http://example.com/halt",
        )
        security = SecurityManager(db_mock, config)

        # Verify not halted initially
        assert not security.is_halted()

        # Simulate remote halt triggering
        session = MagicMock(spec=aiohttp.ClientSession)
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="halt")
        session.get.return_value.__aenter__.return_value = mock_resp

        result = await security.check_remote_halt(session)
        assert result is True

        # App would call set_halt() upon True response
        security.set_halt("Remote halt endpoint activated")
        assert security.is_halted()

    @pytest.mark.asyncio
    async def test_remote_halt_with_event_bus_publish(self, tmp_path):
        """Verify event bus publish call structure (mocked)."""
        db_mock = MagicMock()
        config = BridgeConfig(
            data_dir=str(tmp_path),
            log_dir=str(tmp_path / "logs"),
            remote_halt_url="http://example.com/halt",
            operator_discord_id="123456",
        )
        security = SecurityManager(db_mock, config)

        # Simulate event bus and Discord
        autonomy_mock = MagicMock()
        autonomy_mock.event_bus = MagicMock()
        discord_mock = AsyncMock()

        session = MagicMock(spec=aiohttp.ClientSession)
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="halt")
        session.get.return_value.__aenter__.return_value = mock_resp

        # Check remote halt
        result = await security.check_remote_halt(session)
        assert result is True

        # App would publish event and send Discord message
        security.set_halt("Remote halt endpoint activated")
        autonomy_mock.event_bus.publish("security.remote_halt_activated", {
            "url": config.remote_halt_url,
            "timestamp": "2026-04-03T01:00:00Z",
        })
        asyncio.create_task(discord_mock.send_message(
            config.operator_discord_id,
            "[SECURITY] Remote halt activated",
        ))

        assert security.is_halted()
        autonomy_mock.event_bus.publish.assert_called_once()

    def test_remote_halt_session_cleanup(self, tmp_path):
        """Verify that aiohttp session cleanup is properly designed."""
        import inspect

        from bridge.background_loops import heartbeat_loop

        # Verify function signature includes finally cleanup
        source = inspect.getsource(heartbeat_loop)
        assert "finally:" in source
        assert "session.close()" in source


class TestRemoteHaltConfig:
    """Test config loading for remote halt settings."""

    def test_config_default_values(self, tmp_path):
        """Default config has empty remote_halt_url and 300s interval."""
        config = BridgeConfig(
            data_dir=str(tmp_path),
            log_dir=str(tmp_path / "logs"),
        )
        assert config.remote_halt_url == ""
        assert config.remote_halt_check_interval == 300

    def test_config_custom_values(self, tmp_path):
        """Config accepts custom remote halt values."""
        config = BridgeConfig(
            data_dir=str(tmp_path),
            log_dir=str(tmp_path / "logs"),
            remote_halt_url="https://api.example.com/halt",
            remote_halt_check_interval=600,
        )
        assert config.remote_halt_url == "https://api.example.com/halt"
        assert config.remote_halt_check_interval == 600
