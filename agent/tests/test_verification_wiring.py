"""Tests for Z3.11: VerificationLayer wiring into app.py Stage 3 (_post_process)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.message_queue import QueuedMessage


@pytest_asyncio.fixture
async def wired_app(tmp_path, sample_config_toml, mock_keyring):
    """BridgeApp with fully initialized components (no live Discord/Claude)."""
    app = BridgeApp(config_path=str(sample_config_toml))
    await app._initialize()
    yield app
    if app._db:
        await app._db.close()


def _make_msg(text: str = "What is 2+2?") -> QueuedMessage:
    return QueuedMessage(
        id=1,
        platform_message_id=100,
        chat_id="chat-1",
        text=text,
        received_at="2025-01-01T00:00:00",
        status="processing",
        attempt_count=1,
    )


@pytest.mark.asyncio
async def test_verification_pass_no_prefix(
    wired_app: BridgeApp,
    mock_claude_result,
):
    """When verifier returns passed=True, response is delivered without any prefix."""
    # Enable verification via config override (frozen dataclass — use object.__setattr__)
    object.__setattr__(wired_app._config, "verification_enabled", True)

    result = mock_claude_result(response_text="Four.")

    wired_app._discord._start_typing = MagicMock()
    wired_app._discord._stop_typing = MagicMock()
    wired_app._discord.send_message = AsyncMock()
    wired_app._security.log_event = AsyncMock()
    wired_app._security.check_anomalies = AsyncMock(return_value=[])
    wired_app._claude.invoke = AsyncMock(return_value=result)

    from bridge.verification import VerificationResult, VerificationTier
    passing_vr = VerificationResult(
        passed=True,
        tier=VerificationTier.STANDARD,
        score=0.9,
        issues=[],
        verified_at="2026-01-01T00:00:00+00:00",
    )

    with patch(
        "bridge.verification.VerificationLayer.verify",
        return_value=passing_vr,
    ):
        await wired_app._process_single_message(_make_msg())

    call_args = wired_app._discord.send_message.call_args
    sent_text = call_args[0][1]
    assert "[Verification warnings:" not in sent_text
    assert "Four." in sent_text


@pytest.mark.asyncio
async def test_verification_fail_adds_prefix(
    wired_app: BridgeApp,
    mock_claude_result,
):
    """When verifier returns passed=False with issues, response gets '[Verification warnings: N]' prefix."""
    # Enable verification via config override
    object.__setattr__(wired_app._config, "verification_enabled", True)

    result = mock_claude_result(response_text="Four.")

    wired_app._discord._start_typing = MagicMock()
    wired_app._discord._stop_typing = MagicMock()
    wired_app._discord.send_message = AsyncMock()
    wired_app._security.log_event = AsyncMock()
    wired_app._security.check_anomalies = AsyncMock(return_value=[])
    wired_app._claude.invoke = AsyncMock(return_value=result)

    from bridge.verification import VerificationResult, VerificationTier
    failing_vr = VerificationResult(
        passed=False,
        tier=VerificationTier.STANDARD,
        score=0.0,
        issues=["Missing 'confidence' field", "'result' value is empty"],
        verified_at="2026-01-01T00:00:00+00:00",
    )

    with patch(
        "bridge.verification.VerificationLayer.verify",
        return_value=failing_vr,
    ):
        await wired_app._process_single_message(_make_msg())

    call_args = wired_app._discord.send_message.call_args
    sent_text = call_args[0][1]
    assert "[Verification warnings: 2]" in sent_text
    assert "Four." in sent_text
