"""Tests for the peer-handoff receiver-side branch (sprint 1112.1.03, issue #2140).

Scope discipline (per spec):
- The narrow ``_route_peer_handoff`` fall-through is reachable ONLY after
  the standard ``_authenticate`` rejection. It does not widen the auth gate.
- A valid handoff message is consumed and surfaced to the OPERATOR channel,
  never replied to the sender.
- Any message that fails ANY of {author.bot, peer-allowlist, harness-target
  schema} is rejected (returns ``False``), and the existing on_message
  rejection path applies unchanged.

The tests in this file pair with ``test_handoff.py`` (which covers the
``parse_handoff_message`` / ``consume_handoff`` pure layer) — here we only
verify the Discord-listener wiring.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.config import BridgeConfig
from bridge.discord_bot import DiscordBot
from bridge.handoff import HandoffPlan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bot(sample_config):
    """Return a DiscordBot with peer-harness allowlist configured."""
    cfg = dataclasses.replace(
        sample_config,
        harness_id="local-1",
        peer_harness_ids=("mini-1",),
        peer_harness_bot_ids=("4242424242",),
    )
    with patch("bridge.discord_bot.app_commands.CommandTree"):
        return DiscordBot(cfg)


def _make_message(
    *,
    author_id: int,
    is_bot: bool,
    content: str,
) -> MagicMock:
    """Build a duck-typed mock of ``discord.Message`` that covers the
    attributes the peer-listener path consults."""
    msg = MagicMock()
    msg.author = MagicMock()
    msg.author.id = author_id
    msg.author.bot = is_bot
    msg.channel = MagicMock()
    msg.channel.id = 123456
    msg.content = content
    msg.id = 99
    msg.reply = AsyncMock()
    return msg


# ---------------------------------------------------------------------------
# BridgeConfig: new field is additive
# ---------------------------------------------------------------------------


def test_bridge_config_has_peer_harness_bot_ids_default_empty():
    cfg = BridgeConfig()
    assert cfg.peer_harness_bot_ids == ()
    assert isinstance(cfg.peer_harness_bot_ids, tuple)


def test_bridge_config_peer_harness_bot_ids_overrideable():
    cfg = dataclasses.replace(BridgeConfig(), peer_harness_bot_ids=("111", "222"))
    assert cfg.peer_harness_bot_ids == ("111", "222")


def test_bridge_config_peer_harness_bot_ids_frozen():
    cfg = BridgeConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.peer_harness_bot_ids = ("999",)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _route_peer_handoff — rejection paths (must return False without consuming)
# ---------------------------------------------------------------------------


class TestRoutePeerHandoffRejection:
    """A handoff packet is consumed only when ALL three preconditions hold:
    author.bot True, author.id in peer_harness_bot_ids, schema matches.
    """

    @pytest.mark.asyncio
    async def test_rejects_non_bot_message(self, bot):
        """Even if the schema and ID matched, a human-author message is rejected."""
        msg = _make_message(
            author_id=4242424242,
            is_bot=False,
            content="[handoff to:local-1] https://gist.github.com/x/abc audit",
        )
        with patch.object(bot, "_send_to_operator_channel", AsyncMock()) as send:
            result = await bot._route_peer_handoff(msg)
        assert result is False
        send.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_bot_not_in_allowlist(self, bot):
        """A bot message from an unknown ID is rejected even with a valid schema."""
        msg = _make_message(
            author_id=9999999999,
            is_bot=True,
            content="[handoff to:local-1] https://gist.github.com/x/abc audit",
        )
        with patch.object(bot, "_send_to_operator_channel", AsyncMock()) as send:
            result = await bot._route_peer_handoff(msg)
        assert result is False
        send.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_wrong_harness_target(self, bot):
        """``[handoff to:other-harness]`` is rejected — not addressed to us."""
        msg = _make_message(
            author_id=4242424242,
            is_bot=True,
            content="[handoff to:other-box] https://gist.github.com/x/abc audit",
        )
        with patch.object(bot, "_send_to_operator_channel", AsyncMock()) as send:
            result = await bot._route_peer_handoff(msg)
        assert result is False
        send.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_malformed_schema(self, bot):
        """A peer-bot message without the handoff header is rejected."""
        msg = _make_message(
            author_id=4242424242,
            is_bot=True,
            content="hello world",
        )
        with patch.object(bot, "_send_to_operator_channel", AsyncMock()) as send:
            result = await bot._route_peer_handoff(msg)
        assert result is False
        send.assert_not_called()


# ---------------------------------------------------------------------------
# _route_peer_handoff — acceptance path
# ---------------------------------------------------------------------------


class TestRoutePeerHandoffAcceptance:

    @pytest.mark.asyncio
    async def test_accepts_valid_handoff_and_surfaces_to_operator(self, bot):
        """Valid handoff: consume_handoff → operator channel send → return True."""
        msg = _make_message(
            author_id=4242424242,
            is_bot=True,
            content="[handoff to:local-1] https://gist.github.com/example/abc123 audit policy.py",
        )
        fake_plan = HandoffPlan(
            from_harness="",
            to_harness="local-1",
            artifact_url="https://gist.github.com/example/abc123",
            summary="audit policy.py",
            proposed_steps=("operator-review-required",),
        )
        with patch("bridge.discord_bot.consume_handoff", return_value=fake_plan) as cons, \
                patch.object(bot, "_send_to_operator_channel", AsyncMock()) as send:
            result = await bot._route_peer_handoff(msg)

        assert result is True
        cons.assert_called_once()
        send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_accepted_handoff_does_not_reply_to_sender(self, bot):
        """Receiver never replies back to peer bot — operator-only response."""
        msg = _make_message(
            author_id=4242424242,
            is_bot=True,
            content="[handoff to:local-1] https://gist.github.com/example/abc123 audit",
        )
        fake_plan = HandoffPlan(
            from_harness="",
            to_harness="local-1",
            artifact_url="https://gist.github.com/example/abc123",
            summary="audit",
            proposed_steps=("operator-review-required",),
        )
        with patch("bridge.discord_bot.consume_handoff", return_value=fake_plan), \
                patch.object(bot, "_send_to_operator_channel", AsyncMock()):
            await bot._route_peer_handoff(msg)

        # The sender's message.reply must never be invoked.
        msg.reply.assert_not_called()


# ---------------------------------------------------------------------------
# on_message integration — narrow fall-through is reached only after
# _authenticate fails and is invoked BEFORE the unauthorized-warning path
# ---------------------------------------------------------------------------


class TestOnMessageIntegration:

    @pytest.mark.asyncio
    async def test_unauthenticated_bot_handoff_reaches_route_peer_branch(self, bot):
        """Unauth bot message with valid handoff schema → _route_peer_handoff
        is awaited, message_callback is NOT called.
        """
        msg_cb = AsyncMock()
        bot.set_message_callback(msg_cb)
        msg = _make_message(
            author_id=4242424242,
            is_bot=True,
            content="[handoff to:local-1] https://gist.github.com/example/abc123 audit",
        )
        type(bot).user = property(lambda self: MagicMock(id=999))

        with patch.object(bot, "_route_peer_handoff", AsyncMock(return_value=True)) as route:
            await bot.on_message(msg)

        route.assert_awaited_once_with(msg)
        msg_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_authenticated_message_does_not_invoke_route_peer(self, bot):
        """Operator-authed messages keep the existing path — route_peer must
        not be touched.
        """
        msg_cb = AsyncMock()
        bot.set_message_callback(msg_cb)
        msg = _make_message(
            author_id=7565124764,  # operator
            is_bot=False,
            content="hi",
        )
        type(bot).user = property(lambda self: MagicMock(id=999))

        with patch.object(bot, "_route_peer_handoff", AsyncMock()) as route:
            await bot.on_message(msg)

        route.assert_not_called()
        msg_cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unauthenticated_human_falls_through_unchanged(self, bot):
        """Unauth human (non-bot) → _route_peer_handoff returns False →
        existing rejection path applies (no callback fired).
        """
        msg_cb = AsyncMock()
        bot.set_message_callback(msg_cb)
        msg = _make_message(
            author_id=999999999,
            is_bot=False,
            content="hello",
        )
        type(bot).user = property(lambda self: MagicMock(id=999))

        await bot.on_message(msg)

        msg_cb.assert_not_called()


# ---------------------------------------------------------------------------
# _format_plan_for_operator: produces a deterministic, operator-readable
# summary containing every load-bearing HandoffPlan field.
# ---------------------------------------------------------------------------


def test_format_plan_for_operator_includes_all_fields(bot):
    plan = HandoffPlan(
        from_harness="mini-1",
        to_harness="local-1",
        artifact_url="https://gist.github.com/example/abc123",
        summary="audit policy.py for missing fail-closed paths",
        proposed_steps=("operator-review-required",),
    )
    msg = bot._format_plan_for_operator(plan)
    assert "mini-1" in msg
    assert "local-1" in msg
    assert "https://gist.github.com/example/abc123" in msg
    assert "audit policy.py" in msg


# ---------------------------------------------------------------------------
# _send_to_operator_channel: uses the existing _resolve_channel helper with
# the operator's Discord ID, not the sender's channel.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_to_operator_channel_resolves_operator_id(bot):
    fake_channel = MagicMock()
    fake_channel.send = AsyncMock()
    with patch.object(bot, "_resolve_channel", AsyncMock(return_value=fake_channel)) as resolve:
        await bot._send_to_operator_channel("hello operator")

    # The resolved channel target must be the operator ID, not the peer-bot ID.
    resolve.assert_awaited_once_with(bot._config.operator_discord_id)
    fake_channel.send.assert_awaited_once()
    # Payload contains the message body.
    sent = fake_channel.send.await_args[0][0]
    assert "hello operator" in sent
