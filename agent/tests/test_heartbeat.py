"""Tests for MS1.3: Dead Man's Switches."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.heartbeat import HeartbeatPinger, ping_healthcheck


class TestHeartbeatPinger:
    """Dead man's switch heartbeat tests."""

    def test_no_url_skips(self):
        """No check URL configured should not crash."""
        pinger = HeartbeatPinger(None, MagicMock())
        assert pinger._check_url is None

    @pytest.mark.asyncio
    async def test_start_no_url(self):
        """Start with no URL does nothing (no task created)."""
        pinger = HeartbeatPinger(None, MagicMock())
        await pinger.start()
        assert pinger._task is None

    @pytest.mark.asyncio
    async def test_start_with_url_creates_task(self):
        """Start with URL creates a background task."""
        health = MagicMock()
        pinger = HeartbeatPinger("https://hc-ping.com/test-uuid", health)
        await pinger.start()
        assert pinger._task is not None
        await pinger.stop()

    @pytest.mark.asyncio
    async def test_ping_healthy(self):
        """Healthy status pings the normal URL."""
        health = AsyncMock()
        health.collect_health = AsyncMock(return_value={
            "status": "healthy",
            "uptime_seconds": 100,
        })

        pinger = HeartbeatPinger("https://hc-ping.com/test-uuid", health)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)

        await pinger._ping(mock_session)
        mock_session.post.assert_called_once()
        call_url = mock_session.post.call_args[0][0]
        assert call_url == "https://hc-ping.com/test-uuid"

    @pytest.mark.asyncio
    async def test_ping_unhealthy_uses_fail_url(self):
        """Unhealthy status pings the /fail URL."""
        health = AsyncMock()
        health.collect_health = AsyncMock(return_value={
            "status": "unhealthy",
            "uptime_seconds": 100,
        })

        pinger = HeartbeatPinger("https://hc-ping.com/test-uuid", health)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)

        await pinger._ping(mock_session)
        call_url = mock_session.post.call_args[0][0]
        assert call_url == "https://hc-ping.com/test-uuid/fail"


class TestServicePingHealthcheck:
    """Service completion ping tests."""

    @pytest.mark.asyncio
    async def test_no_url_skips(self):
        """No URL configured should silently skip."""
        with patch("bridge.heartbeat.aiohttp.ClientSession") as mock_session_cls:
            await ping_healthcheck(None, success=True)
            await ping_healthcheck(None, success=False, error="test")
            # With no URL the helper must short-circuit before opening
            # an HTTP session — no construction, no exception.
            mock_session_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_ping(self):
        """Successful service completion pings normal URL."""
        with patch("bridge.heartbeat.aiohttp.ClientSession") as mock_session_cls:
            mock_resp = AsyncMock()
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_resp)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            mock_session_cls.return_value = mock_session

            await ping_healthcheck("https://hc-ping.com/svc-uuid", success=True)
            mock_session.post.assert_called_once()
            call_url = mock_session.post.call_args[0][0]
            assert "/fail" not in call_url

    @pytest.mark.asyncio
    async def test_failure_ping(self):
        """Failed service pings /fail URL."""
        with patch("bridge.heartbeat.aiohttp.ClientSession") as mock_session_cls:
            mock_resp = AsyncMock()
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_resp)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            mock_session_cls.return_value = mock_session

            await ping_healthcheck("https://hc-ping.com/svc-uuid", success=False, error="DB timeout")
            call_url = mock_session.post.call_args[0][0]
            assert call_url.endswith("/fail")
