"""Tests for BaseChannel protocol and ChannelManager."""

from __future__ import annotations


import pytest

from bridge.base_channel import (
    BaseChannel,
    ChannelManager,
    CommandCallback,
    MessageCallback,
)


# ---------------------------------------------------------------------------
# Fake channel implementation for testing
# ---------------------------------------------------------------------------


class FakeChannel:
    """Minimal BaseChannel implementation for testing."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.started = False
        self.stopped = False
        self.sent_messages: list[tuple[str, str, int | None]] = []
        self.sent_alerts: list[str] = []
        self._message_callback: MessageCallback | None = None
        self._command_callback: CommandCallback | None = None

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_message(
        self, chat_id: str, text: str, reply_to: int | None = None
    ) -> None:
        self.sent_messages.append((chat_id, text, reply_to))

    async def send_alert(self, text: str) -> None:
        self.sent_alerts.append(text)

    def set_message_callback(self, callback: MessageCallback) -> None:
        self._message_callback = callback

    def set_command_callback(self, callback: CommandCallback) -> None:
        self._command_callback = callback


class FailingChannel:
    """Channel that raises on start/stop for error path testing."""

    async def start(self) -> None:
        raise ConnectionError("Cannot connect")

    async def stop(self) -> None:
        raise RuntimeError("Stop failed")

    async def send_message(
        self, chat_id: str, text: str, reply_to: int | None = None
    ) -> None:
        raise RuntimeError("Send failed")

    async def send_alert(self, text: str) -> None:
        raise RuntimeError("Alert failed")

    def set_message_callback(self, callback: MessageCallback) -> None:
        pass

    def set_command_callback(self, callback: CommandCallback) -> None:
        pass


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestBaseChannelProtocol:
    """Verify that FakeChannel satisfies the BaseChannel protocol."""

    def test_fake_channel_is_base_channel(self):
        ch = FakeChannel()
        assert isinstance(ch, BaseChannel)

    def test_failing_channel_is_base_channel(self):
        ch = FailingChannel()
        assert isinstance(ch, BaseChannel)

    def test_callback_types_importable(self):
        """MessageCallback and CommandCallback are importable and usable."""
        assert MessageCallback is not None
        assert CommandCallback is not None


# ---------------------------------------------------------------------------
# ChannelManager tests
# ---------------------------------------------------------------------------


class TestChannelManager:
    @pytest.fixture
    def manager(self) -> ChannelManager:
        return ChannelManager()

    @pytest.fixture
    def discord_ch(self) -> FakeChannel:
        return FakeChannel("discord")

    @pytest.fixture
    def vapi_ch(self) -> FakeChannel:
        return FakeChannel("vapi")

    # -- Registration --

    def test_register_channel(self, manager: ChannelManager, discord_ch: FakeChannel):
        manager.register("discord", discord_ch)
        assert manager.get("discord") is discord_ch
        assert manager.list_channels() == ["discord"]

    def test_register_sets_first_as_default(self, manager: ChannelManager, discord_ch: FakeChannel):
        manager.register("discord", discord_ch)
        assert manager.default_channel_name == "discord"
        assert manager.get_default() is discord_ch

    def test_register_explicit_default(
        self, manager: ChannelManager, discord_ch: FakeChannel, vapi_ch: FakeChannel
    ):
        manager.register("discord", discord_ch)
        manager.register("vapi", vapi_ch, default=True)
        assert manager.default_channel_name == "vapi"
        assert manager.get_default() is vapi_ch

    def test_register_overwrites(self, manager: ChannelManager):
        ch1 = FakeChannel("v1")
        ch2 = FakeChannel("v2")
        manager.register("test", ch1)
        manager.register("test", ch2)
        assert manager.get("test") is ch2

    def test_list_channels(
        self, manager: ChannelManager, discord_ch: FakeChannel, vapi_ch: FakeChannel
    ):
        manager.register("discord", discord_ch)
        manager.register("vapi", vapi_ch)
        names = manager.list_channels()
        assert "discord" in names
        assert "vapi" in names

    def test_get_nonexistent(self, manager: ChannelManager):
        assert manager.get("nonexistent") is None

    def test_get_default_empty(self, manager: ChannelManager):
        assert manager.get_default() is None
        assert manager.default_channel_name is None

    # -- Start / Stop --

    @pytest.mark.asyncio
    async def test_start_all(
        self, manager: ChannelManager, discord_ch: FakeChannel, vapi_ch: FakeChannel
    ):
        manager.register("discord", discord_ch)
        manager.register("vapi", vapi_ch)
        await manager.start_all()
        assert discord_ch.started
        assert vapi_ch.started

    @pytest.mark.asyncio
    async def test_stop_all(
        self, manager: ChannelManager, discord_ch: FakeChannel, vapi_ch: FakeChannel
    ):
        manager.register("discord", discord_ch)
        manager.register("vapi", vapi_ch)
        await manager.stop_all()
        assert discord_ch.stopped
        assert vapi_ch.stopped

    @pytest.mark.asyncio
    async def test_start_all_propagates_error(self, manager: ChannelManager):
        manager.register("failing", FailingChannel())
        with pytest.raises(ConnectionError):
            await manager.start_all()

    @pytest.mark.asyncio
    async def test_stop_all_swallows_errors(self, manager: ChannelManager):
        manager.register("failing", FailingChannel())
        # Should not raise
        await manager.stop_all()

    # -- Message routing --

    @pytest.mark.asyncio
    async def test_send_message_to_named_channel(
        self, manager: ChannelManager, discord_ch: FakeChannel, vapi_ch: FakeChannel
    ):
        manager.register("discord", discord_ch)
        manager.register("vapi", vapi_ch)
        await manager.send_message("vapi", "chat1", "hello", reply_to=42)
        assert len(vapi_ch.sent_messages) == 1
        assert vapi_ch.sent_messages[0] == ("chat1", "hello", 42)
        assert len(discord_ch.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_send_message_falls_back_to_default(
        self, manager: ChannelManager, discord_ch: FakeChannel
    ):
        manager.register("discord", discord_ch, default=True)
        await manager.send_message("nonexistent", "chat1", "hello")
        assert len(discord_ch.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_send_message_no_channels(self, manager: ChannelManager):
        # Should not raise, just log an error
        await manager.send_message("any", "chat1", "hello")

    # -- Alert routing --

    @pytest.mark.asyncio
    async def test_send_alert_default_channel(
        self, manager: ChannelManager, discord_ch: FakeChannel
    ):
        manager.register("discord", discord_ch, default=True)
        await manager.send_alert("urgent!")
        assert discord_ch.sent_alerts == ["urgent!"]

    @pytest.mark.asyncio
    async def test_send_alert_named_channel(
        self, manager: ChannelManager, discord_ch: FakeChannel, vapi_ch: FakeChannel
    ):
        manager.register("discord", discord_ch)
        manager.register("vapi", vapi_ch)
        await manager.send_alert("urgent!", channel_name="vapi")
        assert vapi_ch.sent_alerts == ["urgent!"]
        assert discord_ch.sent_alerts == []

    @pytest.mark.asyncio
    async def test_send_alert_no_channels(self, manager: ChannelManager):
        # Should not raise
        await manager.send_alert("urgent!")

    @pytest.mark.asyncio
    async def test_send_alert_nonexistent_channel(
        self, manager: ChannelManager, discord_ch: FakeChannel
    ):
        manager.register("discord", discord_ch)
        # Named channel doesn't exist — should not raise
        await manager.send_alert("urgent!", channel_name="nonexistent")

    # -- Callback wiring --

    @pytest.mark.asyncio
    async def test_set_message_callback(
        self, manager: ChannelManager, discord_ch: FakeChannel, vapi_ch: FakeChannel
    ):
        manager.register("discord", discord_ch)
        manager.register("vapi", vapi_ch)

        async def msg_cb(chat_id: str, text: str, mid: int) -> None:
            pass

        manager.set_message_callback(msg_cb)
        assert discord_ch._message_callback is msg_cb
        assert vapi_ch._message_callback is msg_cb

    @pytest.mark.asyncio
    async def test_set_command_callback(
        self, manager: ChannelManager, discord_ch: FakeChannel, vapi_ch: FakeChannel
    ):
        manager.register("discord", discord_ch)
        manager.register("vapi", vapi_ch)

        async def cmd_cb(chat_id: str, cmd: str, args: str) -> str | None:
            return None

        manager.set_command_callback(cmd_cb)
        assert discord_ch._command_callback is cmd_cb
        assert vapi_ch._command_callback is cmd_cb
