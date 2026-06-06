"""Tests for SelfVerifier (#20) and /verify command."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio

from bridge.self_verifier import SelfVerifier
from bridge.commands import CommandHandler
from bridge.hooks import SessionHookRegistry


# -- SelfVerifier unit tests (#20) --

class TestSelfVerifier:
    def test_disabled_by_default(self):
        v = SelfVerifier()
        assert v.enabled is False

    def test_extract_urls_localhost(self):
        v = SelfVerifier()
        text = "Check http://localhost:3000/dashboard and http://127.0.0.1:8080/api"
        urls = v.extract_urls(text)
        assert len(urls) == 2
        assert "http://localhost:3000/dashboard" in urls
        assert "http://127.0.0.1:8080/api" in urls

    def test_extract_urls_no_match(self):
        v = SelfVerifier()
        assert v.extract_urls("No URLs here") == []
        assert v.extract_urls("https://example.com/page") == []

    def test_extract_urls_with_port(self):
        v = SelfVerifier()
        urls = v.extract_urls("Running at http://localhost:5173/")
        assert len(urls) == 1

    @pytest.mark.asyncio
    async def test_verify_response_disabled(self):
        v = SelfVerifier(enabled=False)
        result = await v.verify_response("http://localhost:3000/test")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_response_no_urls(self):
        v = SelfVerifier(enabled=True)
        result = await v.verify_response("No localhost URLs in this text.")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_url_unreachable(self):
        """Unreachable URL should return passed=False gracefully."""
        v = SelfVerifier(enabled=True)
        result = await v.verify_url("http://localhost:59999/nonexistent")
        assert result.passed is False
        assert len(result.errors) > 0
        assert result.urls_checked == 1

    @pytest.mark.asyncio
    async def test_verify_response_with_unreachable_url(self):
        """verify_response should handle unreachable URLs gracefully."""
        v = SelfVerifier(enabled=True)
        result = await v.verify_response(
            "The app is running at http://localhost:59999/test"
        )
        assert result is not None
        assert result.passed is False
        assert result.urls_checked == 1

    @pytest.mark.asyncio
    async def test_verify_response_caps_at_3_urls(self):
        """Should only check up to 3 URLs."""
        v = SelfVerifier(enabled=True)
        text = " ".join(f"http://localhost:{9000+i}/page" for i in range(5))
        result = await v.verify_response(text)
        assert result is not None
        assert result.urls_checked == 3

    @pytest.mark.asyncio
    async def test_verify_url_success(self):
        """Mock a successful HTTP response."""
        v = SelfVerifier(enabled=True)
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await v.verify_url("http://localhost:3000/")
        assert result.passed is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_verify_url_http_error(self):
        """Mock a 500 HTTP response."""
        v = SelfVerifier(enabled=True)
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await v.verify_url("http://localhost:3000/")
        assert result.passed is False
        assert any("500" in e for e in result.errors)


# -- /verify command tests --

@pytest_asyncio.fixture
async def cmd_with_verifier(migrated_db, message_queue, session_manager):
    handler = CommandHandler(
        db=migrated_db,
        queue=message_queue,
        session_manager=session_manager,
        claude_runner=None,
    )
    v = SelfVerifier(enabled=False)
    handler.set_self_verifier(v)
    reg = SessionHookRegistry()
    reg.register("careful", "Force Opus")
    reg.register("freeze", "Read-only")
    handler.set_session_hooks(reg)
    return handler


class TestVerifyCommand:
    @pytest.mark.asyncio
    async def test_verify_on(self, cmd_with_verifier):
        result = await cmd_with_verifier.handle("chat-1", "verify", "on")
        assert "enabled" in result.lower()
        assert cmd_with_verifier._self_verifier.enabled is True

    @pytest.mark.asyncio
    async def test_verify_off(self, cmd_with_verifier):
        cmd_with_verifier._self_verifier.enabled = True
        result = await cmd_with_verifier.handle("chat-1", "verify", "off")
        assert "disabled" in result.lower()
        assert cmd_with_verifier._self_verifier.enabled is False

    @pytest.mark.asyncio
    async def test_verify_status(self, cmd_with_verifier):
        result = await cmd_with_verifier.handle("chat-1", "verify", "")
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_verify_not_initialized(self, migrated_db, message_queue, session_manager):
        handler = CommandHandler(
            db=migrated_db,
            queue=message_queue,
            session_manager=session_manager,
        )
        result = await handler.handle("chat-1", "verify", "on")
        assert "not initialized" in result
