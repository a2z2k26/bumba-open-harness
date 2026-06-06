"""BaseChannel protocol and ChannelManager for multi-channel message routing.

Defines the contract that all channel implementations (Discord, VAPI, etc.)
must satisfy, plus a registry/router that dispatches messages across channels.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Callback type for incoming messages: (chat_id, text, platform_message_id) -> None
MessageCallback = Callable[[str, str, int], Awaitable[None]]

# Callback type for commands: (chat_id, command, args) -> response text or None
CommandCallback = Callable[[str, str, str], Awaitable[str | None]]


@runtime_checkable
class BaseChannel(Protocol):
    """Protocol defining the interface every channel adapter must implement.

    Channels are transport-agnostic message endpoints (Discord, VAPI/Twilio,
    Slack, etc.). Each channel can start/stop independently, send messages,
    and register callbacks for inbound messages and commands.
    """

    async def start(self) -> None:
        """Connect and begin listening for inbound messages."""
        ...

    async def stop(self) -> None:
        """Disconnect and clean up resources."""
        ...

    async def send_message(
        self, chat_id: str, text: str, reply_to: int | None = None
    ) -> None:
        """Send a text message to a specific chat/channel.

        Args:
            chat_id: Target chat or channel identifier.
            text: Message body.
            reply_to: Optional platform-specific message ID to reply to.
        """
        ...

    async def send_alert(self, text: str) -> None:
        """Send an alert/notification to the operator."""
        ...

    def set_message_callback(self, callback: MessageCallback) -> None:
        """Register the callback invoked when a new message arrives."""
        ...

    def set_command_callback(self, callback: CommandCallback) -> None:
        """Register the callback invoked when a command is received."""
        ...


class ChannelManager:
    """Registry and router for multiple channel adapters.

    Holds named channels, starts/stops them together, and routes outbound
    messages to the correct channel by name.
    """

    def __init__(self) -> None:
        self._channels: dict[str, BaseChannel] = {}
        self._default_channel: str | None = None

    def register(self, name: str, channel: BaseChannel, *, default: bool = False) -> None:
        """Register a channel adapter under a given name.

        Args:
            name: Unique channel identifier (e.g. "discord", "vapi").
            channel: Channel instance implementing BaseChannel.
            default: If True, this channel becomes the default for outbound messages.
        """
        if name in self._channels:
            logger.warning("Overwriting existing channel registration: %s", name)
        self._channels[name] = channel
        if default or self._default_channel is None:
            self._default_channel = name
        logger.info("Channel registered: %s (default=%s)", name, default or self._default_channel == name)

    def get(self, name: str) -> BaseChannel | None:
        """Retrieve a channel by name, or None if not registered."""
        return self._channels.get(name)

    def get_default(self) -> BaseChannel | None:
        """Return the default channel, or None if no channels are registered."""
        if self._default_channel is None:
            return None
        return self._channels.get(self._default_channel)

    @property
    def default_channel_name(self) -> str | None:
        """Return the name of the default channel."""
        return self._default_channel

    def list_channels(self) -> list[str]:
        """Return names of all registered channels."""
        return list(self._channels.keys())

    async def start_all(self) -> None:
        """Start all registered channels."""
        for name, channel in self._channels.items():
            try:
                await channel.start()
                logger.info("Channel started: %s", name)
            except Exception as e:
                logger.error("Failed to start channel %s: %s", name, e)
                raise

    async def stop_all(self) -> None:
        """Stop all registered channels (errors are logged, not raised)."""
        for name, channel in self._channels.items():
            try:
                await channel.stop()
                logger.info("Channel stopped: %s", name)
            except Exception as e:
                logger.warning("Error stopping channel %s: %s", name, e)

    async def send_message(
        self,
        channel_name: str,
        chat_id: str,
        text: str,
        reply_to: int | None = None,
    ) -> None:
        """Route an outbound message to the named channel.

        Falls back to the default channel if the named channel is not found.
        """
        channel = self._channels.get(channel_name)
        if channel is None:
            channel = self.get_default()
            if channel is None:
                logger.error("No channel available for %s (and no default set)", channel_name)
                return
            logger.debug("Channel %s not found, falling back to default", channel_name)
        await channel.send_message(chat_id, text, reply_to=reply_to)

    async def send_alert(self, text: str, channel_name: str | None = None) -> None:
        """Send an alert to the operator via the specified or default channel."""
        target = channel_name or self._default_channel
        if target is None:
            logger.error("No channel available for alert")
            return
        channel = self._channels.get(target)
        if channel is None:
            logger.error("Alert channel %s not registered", target)
            return
        await channel.send_alert(text)

    def set_message_callback(self, callback: MessageCallback) -> None:
        """Set the message callback on all registered channels."""
        for channel in self._channels.values():
            channel.set_message_callback(callback)

    def set_command_callback(self, callback: CommandCallback) -> None:
        """Set the command callback on all registered channels."""
        for channel in self._channels.values():
            channel.set_command_callback(callback)
