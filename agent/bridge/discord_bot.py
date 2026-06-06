"""Discord bot: message handling, authentication, typing indicators, sending."""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path

import discord
from discord import app_commands

from .base_channel import MessageCallback, CommandCallback
from .commands import BRIDGE_COMMANDS, AGENT_COMMANDS
from .config import BridgeConfig
from .handoff import HandoffPlan, consume_handoff, parse_handoff_message
from .stream_coalescer import StreamCoalescer
from .formatting import format_response, format_plain

# Responses longer than this are sent as a file attachment instead
_FILE_FALLBACK_THRESHOLD = 6000

logger = logging.getLogger(__name__)


def _slash_response_strategy(response: str, threshold: int = _FILE_FALLBACK_THRESHOLD) -> str:
    """Decide how a slash-command response should be delivered to Discord.

    Returns one of:
      - ``"empty"``       — falsy / blank response; send a ``✓`` ack.
      - ``"file"``        — length > threshold; send a summary + .md attachment.
      - ``"chunked"``     — length ≤ threshold but may still need splitting
                            via ``format_response`` into multiple chat messages.

    Pulled out as a pure function so issue #1978's contract (no silent
    truncation of long slash-command responses) can be unit-tested without
    spinning up Discord interaction mocks. The handler closure in
    ``_register_one_command`` consults this strategy and acts on it; the
    strategy itself has no Discord dependencies.
    """
    if not response:
        return "empty"
    if len(response) > threshold:
        return "file"
    return "chunked"

# Sprint 01.09: Discord slash-command registry — union of both command registries.
# BRIDGE_COMMANDS = bridge-handled commands (e.g. /ping, /status, /log).
# AGENT_COMMANDS  = commands routed to Claude as expanded prompts
#                   (e.g. /audit, /memory, /tmux, /search).
# Both registries are dispatched via app.py:_handle_command which falls
# through to the agent path when the command isn't a bridge command.
# Operators expect both visible in slash autocomplete.
#
# Every entry in the union already matches Discord's `^[a-z0-9_]{1,32}$`
# rule (verified by test_discord_slash_commands_match_bridge_commands) so no
# name translation or `help`-style reservation exclusion is required.
# The plain-text command parser in app.py normalizes hyphens via
# `command.replace("-", "_")` before lookup, so legacy `kill-agent` invocations
# still dispatch to BRIDGE_COMMANDS' `kill_agent` entry.
#
# #1071 Part 2 — BRIDGE_COMMANDS is now mutable (Tier 3 entries opt in
# via [commands] in bridge.toml), so the union is resolved per call
# instead of cached at import time. ``_register_slash_commands`` reads
# ``_current_commands()`` so Discord autocomplete reflects the current
# tier-gated surface.


def _current_commands() -> list[str]:
    """Resolve the live slash-command surface (BRIDGE ∪ AGENT) sorted."""
    return sorted(BRIDGE_COMMANDS | AGENT_COMMANDS)


# Backward-compatible module-level snapshot — kept for tests / callers
# that still import it directly. Not used by the bot itself.
_COMMANDS: list[str] = _current_commands()


class CheckinView(discord.ui.View):
    """Discord UI buttons for check-in messages (Snooze / Got it)."""

    def __init__(self, data_dir: str = "") -> None:
        super().__init__(timeout=3600)
        self._data_dir = data_dir

    @discord.ui.button(label="Snooze 30m", style=discord.ButtonStyle.secondary, custom_id="checkin:snooze_30")
    async def snooze(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from .services.checkin import CheckinService
        svc = CheckinService(data_dir=self._data_dir, db_path="", chat_id="")
        svc.handle_response("snooze_30")
        await interaction.response.send_message("Snoozed for 30 minutes.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Got it", style=discord.ButtonStyle.primary, custom_id="checkin:dismiss")
    async def dismiss(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from .services.checkin import CheckinService
        svc = CheckinService(data_dir=self._data_dir, db_path="", chat_id="")
        svc.handle_response("dismiss")
        await interaction.response.send_message("Check-in acknowledged.", ephemeral=True)
        self.stop()


class TaskResponseView(discord.ui.View):
    """Discord UI buttons for HITL task responses."""

    def __init__(self, task_id: int, options: list[str], db: object | None = None) -> None:
        super().__init__(timeout=7200)
        self._task_id = task_id
        self._db = db
        for i, option in enumerate(options[:5]):  # Max 5 buttons
            button = discord.ui.Button(
                label=option[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"task:{task_id}:{i}",
            )
            button.callback = self._make_callback(option)
            self.add_item(button)

    def _make_callback(self, option: str):
        async def callback(interaction: discord.Interaction) -> None:
            if self._db:
                from .task_queue import TaskQueue
                tq = TaskQueue(self._db)
                await tq.submit_response(self._task_id, option)
            await interaction.response.send_message(
                f"Selected: **{option}**. Processing...", ephemeral=True
            )
            self.stop()
        return callback


class DiscordBot(discord.Client):
    """Discord bot interface with authentication and message handling."""

    def __init__(self, config: BridgeConfig) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="for messages",
        )
        super().__init__(
            intents=intents,
            status=discord.Status.online,
            activity=activity,
        )

        self._config = config
        self._message_callback: MessageCallback | None = None
        self._command_callback: CommandCallback | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._stream_coalescer: StreamCoalescer | None = None
        self._voice_manager = None
        self.tree = app_commands.CommandTree(self)

        # Register slash commands synchronously (decorators, no await needed)
        self._register_slash_commands()

    # -- Authentication --

    def _operator_id(self) -> str:
        """Return operator Discord ID."""
        return self._config.operator_discord_id

    def _bot_token(self) -> str:
        """Return Discord bot token."""
        return self._config.discord_bot_token

    def _guild_id(self) -> str | None:
        """Return Discord guild ID if configured."""
        return self._config.discord_guild_id or None

    def _authenticate(self, user_id: int) -> bool:
        """Check if user is the authorized operator."""
        return str(user_id) == self._operator_id()

    def set_message_callback(self, callback: MessageCallback) -> None:
        """Set the callback for incoming messages."""
        self._message_callback = callback

    def set_command_callback(self, callback: CommandCallback) -> None:
        """Set the callback for commands."""
        self._command_callback = callback

    def set_stream_coalescer(self, coalescer: "StreamCoalescer | None") -> None:
        """Opt-in: set a StreamCoalescer to buffer streaming text deltas before delivery.

        When set, callers should push() each delta and finalize() at stream end.
        If None, streaming coalescing is disabled (no behaviour change).
        """
        self._stream_coalescer = coalescer

    def set_voice_manager(self, vm) -> None:
        """Wire a voice manager into the bot."""
        self._voice_manager = vm

    # -- Slash command registration --

    def _register_slash_commands(self) -> None:
        """Register all slash commands on the command tree.

        Resolves the surface dynamically via ``_current_commands()`` so
        Discord autocomplete reflects the tier gating applied at startup
        (#1071 Part 2).
        """
        for cmd_name in _current_commands():
            self._register_one_command(cmd_name)

    def _register_one_command(self, cmd_name: str) -> None:
        """Register a single slash command with a closure over cmd_name."""
        bot = self

        @self.tree.command(name=cmd_name, description=f"Bridge command: /{cmd_name}")
        @app_commands.describe(args="Optional arguments")
        async def _handler(interaction: discord.Interaction, args: str = ""):
            if not bot._authenticate(interaction.user.id):
                await interaction.response.send_message("Unauthorized.", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            chat_id = str(interaction.channel_id or interaction.user.id)

            if bot._command_callback:
                response = await bot._command_callback(chat_id, cmd_name, args)
                strategy = _slash_response_strategy(response or "")
                if strategy == "empty":
                    await interaction.followup.send("\u2713 Done.")
                elif cmd_name in ("status", "uptime"):
                    embed = bot._build_status_embed(cmd_name, response)
                    await interaction.followup.send(embed=embed)
                elif strategy == "file":
                    # Issue #1978 \u2014 long slash-command responses (e.g. a
                    # /board synthesis memo, observed at 3-5k chars) used
                    # to silently truncate via ``chunks[0][:2000]``. When a
                    # response exceeds the file-fallback threshold, send
                    # a brief summary + the full response as a .md
                    # attachment. Mirrors ``send_message``'s long-text
                    # path so the slash-command surface and the
                    # conversational surface agree.
                    fp = io.BytesIO(response.encode("utf-8"))
                    file = discord.File(fp, filename=f"{cmd_name}-response.md")
                    summary = (
                        f"_({cmd_name} response too long for chat \u2014 "
                        f"{len(response):,} chars; full text attached.)_"
                    )
                    await interaction.followup.send(summary, file=file)
                else:  # strategy == "chunked"
                    chunks = format_response(response)
                    text = chunks[0][:2000] if chunks else "\u2713"
                    await interaction.followup.send(text)
                    channel = interaction.channel
                    if channel:
                        for chunk in chunks[1:]:
                            await channel.send(chunk[:2000])  # type: ignore[union-attr]

    def _build_status_embed(self, cmd_name: str, text: str) -> discord.Embed:
        """Build a rich embed for /status and /uptime responses."""
        # Color: green = healthy, orange = halted
        color = discord.Color.orange() if "HALTED" in text else discord.Color.green()
        embed = discord.Embed(
            title=f"/{cmd_name}",
            color=color,
        )
        # Parse key: value pairs separated by ". " or newlines into fields
        lines = [s.strip() for s in text.replace(". ", "\n").splitlines() if s.strip()]
        for line in lines:
            if ": " in line:
                name, value = line.split(": ", 1)
                embed.add_field(name=name, value=value, inline=True)
            else:
                embed.add_field(name="\u200b", value=line, inline=False)
        return embed

    # -- Start / Stop --

    async def start(self, max_retries: int = 30, initial_delay: float = 5.0) -> None:  # type: ignore[override]
        """Connect to Discord with retry loop."""
        token = self._bot_token()
        delay = initial_delay
        for attempt in range(1, max_retries + 1):
            try:
                # login() verifies the token without blocking indefinitely
                await self.login(token)
                logger.info("Discord bot logged in (attempt %d)", attempt)

                # Sync slash commands to guild (instant) or globally (up to 1hr delay)
                guild_id = self._guild_id()
                if guild_id:
                    guild = discord.Object(id=int(guild_id))
                    self.tree.copy_global_to(guild=guild)
                    await self.tree.sync(guild=guild)
                else:
                    await self.tree.sync()
                logger.info("Slash commands synced")

                # Start the websocket in the background; connect() blocks indefinitely
                asyncio.create_task(self.connect())
                return
            except (discord.LoginFailure, discord.HTTPException, OSError) as e:
                if attempt >= max_retries:
                    logger.critical(
                        "Discord connection failed after %d attempts: %s",
                        max_retries, e,
                    )
                    raise
                logger.warning(
                    "Network not ready (attempt %d/%d): %s — retrying in %.0fs",
                    attempt, max_retries, e, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 60.0)

    async def stop(self) -> None:
        """Stop the bot and cancel typing tasks."""
        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()
        await self.close()
        logger.info("Discord bot stopped")

    # -- Event handlers --

    async def on_ready(self) -> None:
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for messages",
            ),
        )
        logger.info("Discord bot ready as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming text messages."""
        # Ignore bot's own messages
        if message.author == self.user:
            return

        if not self._authenticate(message.author.id):
            # Sprint 1112.1.03 (#2140): narrow peer-handoff fall-through.
            # Reached ONLY after the standard operator-auth gate has
            # already rejected this author. The function returns True
            # when (and only when) the message is a valid handoff from
            # an allowlisted peer-bot — the existing rejection path
            # otherwise applies unchanged.
            if await self._route_peer_handoff(message):
                return
            if not message.content.startswith("/"):
                logger.warning("Unauthorized message from user %d", message.author.id)
            return

        chat_id = str(message.channel.id)

        # Route "/" messages as commands (fallback for when slash commands
        # haven't synced yet or user types them as plain text)
        if message.content.startswith("/"):
            parts = message.content[1:].split(None, 1)
            cmd = parts[0].lower() if parts else ""
            args = parts[1] if len(parts) > 1 else ""
            if cmd and self._command_callback:
                response = await self._command_callback(chat_id, cmd, args)
                if response:
                    await message.reply(response[:2000])
            return

        text = message.content
        platform_message_id = message.id

        # Download image attachments and append file paths for Claude to read
        image_paths = await self._download_image_attachments(message.attachments)
        if image_paths:
            paths_block = "\n".join(f"[image: {p}]" for p in image_paths)
            text = f"{text}\n\n{paths_block}" if text.strip() else paths_block

        if self._message_callback:
            await self._message_callback(chat_id, text, platform_message_id)

    # -- Sprint 1112.1.03 (#2140) — peer-handoff receiver-side branch --
    #
    # The three helpers below are reachable ONLY from the narrow
    # ``on_message`` fall-through. They never widen ``_authenticate``;
    # ``_route_peer_handoff`` enforces its own (stricter) preconditions
    # before consuming any message.

    async def _route_peer_handoff(self, message: discord.Message) -> bool:
        """Consume a peer-bot handoff if-and-only-if it matches the strict schema.

        Returns ``True`` when the message was consumed and surfaced to the
        operator (so ``on_message`` can short-circuit), and ``False`` for
        anything that fails ANY precondition:

        1. ``message.author.bot`` is False — humans never reach this path,
           the operator-auth gate is the human surface.
        2. ``message.author.id`` is NOT in ``peer_harness_bot_ids`` — the
           sender is a bot but is not on this harness's allowlist.
        3. ``message.content`` does not parse, or parses but targets a
           different harness — schema mismatch.

        On accept, the consumed plan is delivered to the OPERATOR's channel
        (never back to the sending bot). This is the load-bearing
        anti-runaway property of the protocol.
        """
        if not getattr(message.author, "bot", False):
            return False
        if str(message.author.id) not in self._config.peer_harness_bot_ids:
            return False
        packet = parse_handoff_message(message.content, self._config.harness_id)
        if packet is None:
            return False
        plan = consume_handoff(packet)
        operator_msg = self._format_plan_for_operator(plan)
        await self._send_to_operator_channel(operator_msg)
        return True

    def _format_plan_for_operator(self, plan: HandoffPlan) -> str:
        """Render a :class:`HandoffPlan` as an operator-readable summary.

        Deterministic, single-message format. Every load-bearing field
        appears verbatim so the operator can audit the handoff at a glance
        before approving any execution.
        """
        steps = "\n".join(f"  - {step}" for step in plan.proposed_steps)
        return (
            "[handoff received]\n"
            f"from: {plan.from_harness}\n"
            f"to:   {plan.to_harness}\n"
            f"artifact: {plan.artifact_url}\n"
            f"summary: {plan.summary}\n"
            "proposed steps:\n"
            f"{steps}"
        )

    async def _send_to_operator_channel(self, text: str) -> None:
        """Deliver ``text`` to the operator's Discord surface (DM channel).

        The operator's Discord ID is the chat target — never the sending
        peer-bot's channel. This is what makes the receiver "respond to the
        operator, never to the sender" property structural.
        """
        operator_id = self._config.operator_discord_id
        channel = await self._resolve_channel(operator_id)
        await channel.send(text[:2000])  # type: ignore[union-attr]

    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

    async def _download_image_attachments(
        self, attachments: list[discord.Attachment],
    ) -> list[str]:
        """Download image attachments to /tmp, return list of file paths."""
        import tempfile
        import aiohttp

        paths: list[str] = []
        for att in attachments:
            is_image = (
                (att.content_type and att.content_type.startswith("image/"))
                or any(att.filename.lower().endswith(ext) for ext in self._IMAGE_EXTENSIONS)
            )
            if not is_image:
                continue
            try:
                suffix = Path(att.filename).suffix or ".png"
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=suffix, prefix="bumba_img_",
                )
                async with aiohttp.ClientSession() as session:
                    async with session.get(att.url) as resp:
                        resp.raise_for_status()
                        tmp.write(await resp.read())
                tmp.close()
                paths.append(tmp.name)
                logger.info("Downloaded attachment %s -> %s", att.filename, tmp.name)
            except Exception as e:
                logger.warning("Failed to download attachment %s: %s", att.filename, e)
        return paths

    # -- Typing indicators --

    def _start_typing(self, chat_id: str) -> None:
        """Start sending typing indicators every 8 seconds."""
        if chat_id in self._typing_tasks:
            return

        bot = self

        async def typing_loop():
            try:
                while True:
                    channel = bot.get_channel(int(chat_id))
                    if channel is not None:
                        async with channel.typing():  # type: ignore[union-attr]
                            await asyncio.sleep(8)
                    else:
                        await asyncio.sleep(8)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug("Typing indicator error: %s", e)

        self._typing_tasks[chat_id] = asyncio.create_task(typing_loop())

    def _stop_typing(self, chat_id: str) -> None:
        """Stop typing indicators for a channel."""
        task = self._typing_tasks.pop(chat_id, None)
        if task:
            task.cancel()

    # -- Message sending --

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to: int | None = None,
    ) -> None:
        """Send a message with markdown splitting, file fallback, and reply threading."""
        # Very long responses → single file attachment
        if len(text) > _FILE_FALLBACK_THRESHOLD:
            await self._send_as_file(chat_id, text, reply_to=reply_to)
            return

        chunks = format_response(text)

        for chunk in chunks:
            sent = await self._send_with_retry(chat_id, chunk, reply_to=reply_to)
            if not sent:
                plain_chunks = format_plain(text)
                for plain in plain_chunks:
                    await self._send_with_retry(chat_id, plain, reply_to=reply_to)
                break
            # Only reply to the first chunk
            reply_to = None

    async def _send_as_file(
        self,
        chat_id: str,
        text: str,
        reply_to: int | None = None,
    ) -> None:
        """Send a long response as a .md file attachment."""
        try:
            channel = await self._resolve_channel(chat_id)
            fp = io.BytesIO(text.encode("utf-8"))
            file = discord.File(fp, filename="response.md")
            kwargs: dict = {"file": file, "content": f"_(response too long — {len(text):,} chars)_"}
            if reply_to:
                try:
                    ref_msg = await channel.fetch_message(reply_to)  # type: ignore[union-attr]
                    await ref_msg.reply(**kwargs)
                    return
                except Exception as exc:
                    logger.warning("file-reply fallback to plain send: %s", exc)
            await channel.send(**kwargs)  # type: ignore[union-attr]
        except Exception as e:
            logger.error("File send failed: %s", e)
            # Last resort: truncate and send as plain text
            truncated = text[:1900] + "\n…(truncated)"
            await self._send_with_retry(chat_id, truncated, reply_to=reply_to)

    async def send_alert(self, text: str) -> None:
        """Send an alert DM to the operator."""
        alert_text = f"[ALERT] {text}"
        await self.send_message(self._operator_id(), alert_text)

    async def _resolve_channel(self, chat_id: str) -> discord.abc.Messageable:
        """Resolve a chat_id to a messageable channel or DM."""
        target_id = int(chat_id)
        # Try cached channel first
        channel = self.get_channel(target_id)
        if channel is not None:
            return channel  # type: ignore[return-value]
        # Try fetching as a channel
        try:
            return await self.fetch_channel(target_id)  # type: ignore[return-value]
        except (discord.NotFound, discord.HTTPException):
            pass
        # Might be a user ID — open DM
        user = await self.fetch_user(target_id)
        return await user.create_dm()

    async def _send_with_retry(
        self,
        chat_id: str,
        text: str,
        reply_to: int | None = None,
        max_retries: int = 3,
    ) -> bool:
        """Send a single message with retry on network errors."""
        for attempt in range(max_retries):
            try:
                channel = await self._resolve_channel(chat_id)

                truncated = text[:2000]  # Discord hard limit
                if reply_to:
                    try:
                        ref_msg = await channel.fetch_message(reply_to)  # type: ignore[union-attr]
                        await ref_msg.reply(truncated)
                    except Exception:
                        await channel.send(truncated)  # type: ignore[union-attr]
                else:
                    await channel.send(truncated)  # type: ignore[union-attr]
                return True
            except (discord.HTTPException, OSError) as e:
                logger.warning(
                    "Send failed (attempt %d/%d): %s", attempt + 1, max_retries, e
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
            except Exception as e:
                logger.error("Send error: %s", e)
                return False
        return False
