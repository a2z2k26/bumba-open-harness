"""Tests for bridge.discord_bot (Discord migration)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.discord_bot import DiscordBot


@pytest.fixture
def bot(sample_config):
    """Return a DiscordBot instance (not started)."""
    with patch("bridge.discord_bot.app_commands.CommandTree"):
        return DiscordBot(sample_config)


class TestAuthentication:
    """User authentication via operator Discord ID."""

    def test_auth_operator(self, bot):
        assert bot._authenticate(7565124764) is True

    def test_auth_stranger(self, bot):
        assert bot._authenticate(999999999) is False

    def test_auth_zero(self, bot):
        assert bot._authenticate(0) is False


class TestCallbacks:
    """Callback registration."""

    def test_set_message_callback(self, bot):
        cb = AsyncMock()
        bot.set_message_callback(cb)
        assert bot._message_callback is cb

    def test_set_command_callback(self, bot):
        cb = AsyncMock()
        bot.set_command_callback(cb)
        assert bot._command_callback is cb


class TestTyping:
    """Typing indicators."""

    @pytest.mark.asyncio
    async def test_start_typing(self, bot):
        bot._start_typing("123456")
        assert "123456" in bot._typing_tasks
        bot._stop_typing("123456")

    @pytest.mark.asyncio
    async def test_stop_typing(self, bot):
        bot._start_typing("123456")
        bot._stop_typing("123456")
        assert "123456" not in bot._typing_tasks

    def test_stop_typing_no_task(self, bot):
        # Should not raise
        bot._stop_typing("nonexistent")


class TestOnMessage:
    """Message handling via on_message event."""

    @pytest.mark.asyncio
    async def test_handle_authenticated_message(self, bot):
        callback = AsyncMock()
        bot.set_message_callback(callback)

        # Mock a discord.Message
        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 7565124764
        message.channel.id = 123456
        message.content = "Hello"
        message.id = 42

        # bot.user is None before login; set it to avoid self-message filter
        bot._connection = MagicMock()
        type(bot).user = property(lambda self: MagicMock(id=999))

        await bot.on_message(message)
        callback.assert_called_once_with("123456", "Hello", 42)

    @pytest.mark.asyncio
    async def test_handle_unauthenticated_message(self, bot):
        callback = AsyncMock()
        bot.set_message_callback(callback)

        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 999999999
        message.channel.id = 123456
        message.content = "Hello"
        message.id = 42

        type(bot).user = property(lambda self: MagicMock(id=999))

        await bot.on_message(message)
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_own_messages(self, bot):
        callback = AsyncMock()
        bot.set_message_callback(callback)

        bot_user = MagicMock()
        type(bot).user = property(lambda self: bot_user)

        message = MagicMock()
        message.author = bot_user  # Same as bot.user
        message.content = "Hello"

        await bot.on_message(message)
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_slash_commands_routed_not_to_claude(self, bot):
        """Messages starting with / go through command callback, not message callback."""
        msg_callback = AsyncMock()
        cmd_callback = AsyncMock(return_value="pong")
        bot.set_message_callback(msg_callback)
        bot.set_command_callback(cmd_callback)

        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 7565124764
        message.content = "/ping"
        message.reply = AsyncMock()

        type(bot).user = property(lambda self: MagicMock(id=999))

        await bot.on_message(message)
        msg_callback.assert_not_called()
        cmd_callback.assert_called_once()
        assert cmd_callback.call_args[0][1] == "ping"

    @pytest.mark.asyncio
    async def test_slash_command_with_args(self, bot):
        """Slash command args are parsed and forwarded."""
        cmd_callback = AsyncMock(return_value="done")
        bot.set_command_callback(cmd_callback)

        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 7565124764
        message.content = "/trust routing"
        message.reply = AsyncMock()

        type(bot).user = property(lambda self: MagicMock(id=999))

        await bot.on_message(message)
        cmd_callback.assert_called_once()
        assert cmd_callback.call_args[0][1] == "trust"
        assert cmd_callback.call_args[0][2] == "routing"


class TestImageAttachments:
    """Image attachment download and text injection."""

    @pytest.mark.asyncio
    async def test_image_attachment_appended_to_text(self, bot):
        """Image attachment paths are appended to message text."""
        callback = AsyncMock()
        bot.set_message_callback(callback)

        # Mock image attachment
        att = MagicMock()
        att.content_type = "image/png"
        att.filename = "screenshot.png"
        att.url = "https://cdn.example.com/screenshot.png"

        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 7565124764
        message.channel.id = 123456
        message.content = "What is this?"
        message.id = 42
        message.attachments = [att]

        type(bot).user = property(lambda self: MagicMock(id=999))

        with patch.object(bot, "_download_image_attachments", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = ["/tmp/bumba_img_abc.png"]
            await bot.on_message(message)

        # Text should include the image path
        called_text = callback.call_args[0][1]
        assert "[image: /tmp/bumba_img_abc.png]" in called_text
        assert "What is this?" in called_text

    @pytest.mark.asyncio
    async def test_image_only_message(self, bot):
        """Message with no text but an image attachment."""
        callback = AsyncMock()
        bot.set_message_callback(callback)

        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 7565124764
        message.channel.id = 123456
        message.content = ""
        message.id = 42
        message.attachments = [MagicMock()]

        type(bot).user = property(lambda self: MagicMock(id=999))

        with patch.object(bot, "_download_image_attachments", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = ["/tmp/bumba_img_xyz.jpg"]
            await bot.on_message(message)

        called_text = callback.call_args[0][1]
        assert called_text == "[image: /tmp/bumba_img_xyz.jpg]"

    @pytest.mark.asyncio
    async def test_non_image_attachment_ignored(self, bot):
        """Non-image attachments are not downloaded."""
        att = MagicMock()
        att.content_type = "application/pdf"
        att.filename = "document.pdf"

        result = await bot._download_image_attachments([att])
        assert result == []

    @pytest.mark.asyncio
    async def test_image_detected_by_extension(self, bot):
        """Image detected by file extension when content_type is None."""
        att = MagicMock()
        att.content_type = None
        att.filename = "photo.jpg"
        att.url = "https://cdn.example.com/photo.jpg"

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_resp = AsyncMock()
            mock_resp.read = AsyncMock(return_value=b"\x89PNG fake image data")
            mock_resp.raise_for_status = MagicMock()

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=mock_ctx)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            mock_session_cls.return_value = mock_session

            result = await bot._download_image_attachments([att])

        assert len(result) == 1
        assert "bumba_img_" in result[0]
        assert result[0].endswith(".jpg")

        # Cleanup
        import os
        os.unlink(result[0])

    @pytest.mark.asyncio
    async def test_download_failure_skipped(self, bot):
        """Failed download is logged and skipped, not raised."""
        att = MagicMock()
        att.content_type = "image/png"
        att.filename = "broken.png"
        att.url = "https://cdn.example.com/broken.png"

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.get = MagicMock(side_effect=Exception("connection refused"))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            result = await bot._download_image_attachments([att])

        assert result == []



class TestStatusEmbed:
    """Rich embed building for /status and /uptime."""

    def test_build_status_embed_healthy(self, bot):
        embed = bot._build_status_embed("status", "Agent online. Uptime: 1h 5m. Queue: 0 pending.")
        assert embed.title == "/status"
        assert embed.color.value == 0x2ecc71  # discord.Color.green()

    def test_build_status_embed_halted(self, bot):
        embed = bot._build_status_embed("status", "Agent online [HALTED]. Uptime: 0h 1m.")
        assert embed.color.value == 0xe67e22  # discord.Color.orange()

    def test_embed_has_fields(self, bot):
        embed = bot._build_status_embed("uptime", "Uptime: 2h 30m. Messages: 42.")
        assert len(embed.fields) >= 2


class TestSendMessage:
    """Message sending."""

    @pytest.mark.asyncio
    async def test_send_message_calls_channel_send(self, bot):
        channel = AsyncMock()
        bot.get_channel = MagicMock(return_value=channel)

        await bot.send_message("123456", "Hello!")
        channel.send.assert_called()

    @pytest.mark.asyncio
    async def test_send_alert(self, bot):
        channel = AsyncMock()
        bot.get_channel = MagicMock(return_value=channel)

        await bot.send_alert("System error!")
        channel.send.assert_called()
        call_args = channel.send.call_args
        assert "[ALERT]" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_long_response_sent_as_file(self, bot):
        channel = AsyncMock()
        bot.get_channel = MagicMock(return_value=channel)
        bot.fetch_channel = AsyncMock(return_value=channel)

        long_text = "x" * 7000  # Above _FILE_FALLBACK_THRESHOLD (6000)
        await bot.send_message("123456", long_text)
        # Should call channel.send with a file attachment
        channel.send.assert_called()


class TestVoiceWiring:
    """Voice manager wiring into DiscordBot."""

    def test_set_voice_manager(self, bot):
        vm = object()
        bot.set_voice_manager(vm)
        assert bot._voice_manager is vm

    def test_voice_manager_default_none(self, bot):
        assert bot._voice_manager is None


class TestSlashCommandRegistry:
    """Sprint 01.09: Discord slash registry = BRIDGE_COMMANDS | AGENT_COMMANDS."""

    def test_discord_slash_commands_match_bridge_commands(self):
        """Live registry must equal the union of both command sets — no drift.

        #1071 Part 2: ``BRIDGE_COMMANDS`` is now mutable (Tier 3 entries
        opt in via [commands]). The Discord bot resolves the union
        dynamically at slash-registration time via ``_current_commands()``.
        We verify the live function instead of the import-time
        ``_COMMANDS`` snapshot — that snapshot is kept only for backward
        compatibility with callers that still import it.
        """
        import re

        from bridge.commands import AGENT_COMMANDS, BRIDGE_COMMANDS
        from bridge.discord_bot import _current_commands

        # Equality: union of both registries is the single source of truth.
        # AGENT_COMMANDS (audit, memory, permissions, review, search, tmux,
        # skills) are commands that fall through to Claude as expanded prompts
        # via app.py:_handle_command. Operators expect them in slash autocomplete.
        union = BRIDGE_COMMANDS | AGENT_COMMANDS
        live = set(_current_commands())
        assert live == set(union), (
            f"_current_commands() drifted from BRIDGE_COMMANDS | "
            f"AGENT_COMMANDS. Missing: {set(union) - live}, "
            f"Extra: {live - set(union)}"
        )

        # Discord slash-command name rules: lowercase letters, digits,
        # underscores, 1-32 chars. Hyphens are illegal at the Discord layer
        # (the legacy `kill-agent` was invalid — fixed via the BRIDGE_COMMANDS
        # `kill_agent` entry; plain-text `/kill-agent` still works because
        # app.py normalizes hyphens to underscores before dispatch).
        discord_pattern = re.compile(r"^[a-z0-9_]{1,32}$")
        for name in live:
            assert discord_pattern.match(name), (
                f"Slash command name {name!r} violates Discord's "
                f"^[a-z0-9_]{{1,32}}$ rule"
            )

        # Sanity floor: original hardcoded list was 29; with all Tier 3
        # commands enabled (autouse conftest fixture), the surface should
        # be at least 60 commands (Tier 1 + Tier 2 + Tier 3 + AGENT).
        assert len(live) >= 60, (
            f"Expected at least 60 slash commands with Tier 3 enabled, "
            f"got {len(live)}"
        )

    def test_discord_slash_commands_sorted_deterministic(self):
        """Registration order is deterministic (sorted) for stable Discord sync."""
        from bridge.discord_bot import _current_commands

        live = _current_commands()
        assert live == sorted(live), (
            "_current_commands() must return a sorted list for "
            "deterministic Discord registration"
        )


# ---------------------------------------------------------------------------
# Slash-command response strategy (#1978)
# ---------------------------------------------------------------------------


class TestSlashResponseStrategy:
    """Pin the slash-command response delivery contract from #1978.

    Pre-#1978 the slash-command handler hard-truncated long responses
    via ``chunks[0][:2000]`` — a 3-5k /board synthesis memo lost ~60% of
    its content silently. Operator-signed expectation: responses exceeding
    the file-fallback threshold MUST be sent as a .md attachment with a
    brief summary. The strategy helper is the testable pivot."""

    def test_empty_response_returns_empty_strategy(self):
        from bridge.discord_bot import _slash_response_strategy

        assert _slash_response_strategy("") == "empty"

    def test_short_response_returns_chunked_strategy(self):
        from bridge.discord_bot import _slash_response_strategy

        assert _slash_response_strategy("hello world") == "chunked"

    def test_medium_response_at_threshold_returns_chunked(self):
        from bridge.discord_bot import _FILE_FALLBACK_THRESHOLD, _slash_response_strategy

        # Exactly at the threshold = still chunked (the > check is strict)
        assert (
            _slash_response_strategy("x" * _FILE_FALLBACK_THRESHOLD)
            == "chunked"
        )

    def test_long_response_above_threshold_returns_file(self):
        from bridge.discord_bot import _FILE_FALLBACK_THRESHOLD, _slash_response_strategy

        assert (
            _slash_response_strategy("x" * (_FILE_FALLBACK_THRESHOLD + 1))
            == "file"
        )

    def test_board_synthesis_memo_size_routes_to_file(self):
        """A realistic /board memo (observed 3-5k chars in #1978's
        repro) would today be ``chunked``; if the memo grows past the
        threshold in the future, this strategy returns ``file`` so the
        operator gets the full text as an attachment, never a truncated
        chat message."""
        from bridge.discord_bot import _slash_response_strategy

        # Simulate a much larger memo (post-#1975 we now have headroom
        # for 250k output tokens; memos at 8-10k chars are plausible).
        big_memo = "## Recommendation\n\n" + ("Lorem ipsum. " * 700)
        assert len(big_memo) > 6000  # above default threshold
        assert _slash_response_strategy(big_memo) == "file"

    def test_threshold_argument_is_honored(self):
        """The threshold is overridable for testing and for any future
        per-command tuning."""
        from bridge.discord_bot import _slash_response_strategy

        assert _slash_response_strategy("x" * 50, threshold=10) == "file"
        assert _slash_response_strategy("x" * 5, threshold=10) == "chunked"
