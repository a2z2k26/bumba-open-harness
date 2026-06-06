"""DreamNotifier — Discord consolidation progress visibility.

Posts and updates a Discord message tracking the consolidation workflow:
- Initial message on consolidation start
- Per-phase progress updates (Inventory → Decay → Contradiction → Merge → Promote → Report)
- Completion summary with stats
- Failure summary with error context
- `/dream` command support for status/history
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import discord


class DreamStatus(str, Enum):
    """Dream/consolidation status states."""

    IDLE = "idle"
    CONSOLIDATING = "consolidating"
    INVENTORY = "inventory"
    DECAY = "decay"
    CONTRADICTION = "contradiction"
    MERGE = "merge"
    PROMOTE = "promote"
    REPORT = "report"
    COMPLETE = "complete"
    FAILED = "failed"


class ConsolidationPhase(str, Enum):
    """Consolidation workflow phases."""

    INVENTORY = "inventory"
    DECAY = "decay"
    CONTRADICTION = "contradiction"
    MERGE = "merge"
    PROMOTE = "promote"
    REPORT = "report"


@dataclass(frozen=True)
class PhaseProgress:
    """Immutable phase progress tracking."""

    phase: ConsolidationPhase
    status: str
    item_count: Optional[int] = None
    completed_at: Optional[float] = None


class DreamNotifier:
    """
    Discord consolidation progress notifier.

    Posts initial dream message, updates per phase, handles completion/failure.
    Supports `/dream` command for status queries and history retrieval.
    """

    def __init__(self, discord_client: discord.Client, dream_channel_id: int):
        """
        Initialize DreamNotifier.

        Args:
            discord_client: Discord client for posting/updating messages
            dream_channel_id: Channel ID where consolidation messages are posted
        """
        self.discord_client = discord_client
        self.dream_channel_id = dream_channel_id
        self.current_status: DreamStatus = DreamStatus.IDLE
        self.current_message_id: Optional[int] = None
        self.phase_history: list[PhaseProgress] = []

    async def post_initial_message(self) -> int:
        """
        Post initial consolidation started message.

        Returns:
            Message ID of the posted message

        Raises:
            RuntimeError: If dream channel not found
        """
        channel = self.discord_client.get_channel(self.dream_channel_id)
        if not channel:
            raise RuntimeError(f"Dream channel not found: {self.dream_channel_id}")

        embed = discord.Embed(
            title="🌙 Consolidation Started",
            description="Beginning dream consolidation phase...",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Status",
            value="Starting consolidation workflow",
            inline=False,
        )

        message = await channel.send(embed=embed)
        self.current_message_id = message.id
        self.current_status = DreamStatus.CONSOLIDATING
        return message.id

    async def update_phase_progress(
        self,
        phase: ConsolidationPhase,
        status: str,
        item_count: Optional[int] = None,
    ) -> None:
        """
        Update phase progress in the consolidation message.

        Args:
            phase: Current consolidation phase
            status: Status message for the phase
            item_count: Optional count of items processed

        Raises:
            RuntimeError: If no consolidation message posted yet
        """
        if not self.current_message_id:
            raise RuntimeError("No consolidation message posted")

        channel = self.discord_client.get_channel(self.dream_channel_id)
        if not channel:
            raise RuntimeError(f"Dream channel not found: {self.dream_channel_id}")

        # Update status
        self.current_status = DreamStatus[phase.value.upper()]
        self.phase_history.append(
            PhaseProgress(
                phase=phase,
                status=status,
                item_count=item_count,
            )
        )

        # Fetch and update message
        message = await channel.fetch_message(self.current_message_id)

        # Build phase emoji map
        phase_emojis = {
            ConsolidationPhase.INVENTORY: "📦",
            ConsolidationPhase.DECAY: "💤",
            ConsolidationPhase.CONTRADICTION: "⚖️",
            ConsolidationPhase.MERGE: "🔗",
            ConsolidationPhase.PROMOTE: "⬆️",
            ConsolidationPhase.REPORT: "📊",
        }

        emoji = phase_emojis.get(phase, "⚙️")

        embed = discord.Embed(
            title=f"{emoji} Consolidation Phase: {phase.value.title()}",
            description=status,
            color=discord.Color.blue(),
        )

        if item_count is not None:
            embed.add_field(name="Items", value=str(item_count), inline=True)

        # Add phase history
        history_text = "\n".join(
            [f"{phase_emojis.get(p.phase, '⚙️')} {p.phase.value.title()}" for p in self.phase_history]
        )
        if history_text:
            embed.add_field(name="Phases Completed", value=history_text, inline=False)

        await message.edit(embed=embed)

    async def post_completion_summary(
        self,
        total_items_processed: int,
        consolidated_count: int,
        failed_count: int,
        duration_seconds: float,
    ) -> None:
        """
        Post consolidation completion summary.

        Args:
            total_items_processed: Total items processed
            consolidated_count: Count of successfully consolidated items
            failed_count: Count of failed items
            duration_seconds: Total duration in seconds

        Raises:
            RuntimeError: If no consolidation message posted yet
        """
        if not self.current_message_id:
            raise RuntimeError("No consolidation message posted")

        channel = self.discord_client.get_channel(self.dream_channel_id)
        if not channel:
            raise RuntimeError(f"Dream channel not found: {self.dream_channel_id}")

        message = await channel.fetch_message(self.current_message_id)
        self.current_status = DreamStatus.COMPLETE

        embed = discord.Embed(
            title="✅ Consolidation Complete",
            description="Dream phase completed successfully",
            color=discord.Color.green(),
        )

        embed.add_field(name="Total Processed", value=str(total_items_processed), inline=True)
        embed.add_field(name="Consolidated", value=str(consolidated_count), inline=True)
        embed.add_field(name="Failed", value=str(failed_count), inline=True)

        minutes, seconds = divmod(int(duration_seconds), 60)
        duration_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
        embed.add_field(name="Duration", value=duration_str, inline=True)

        success_rate = (
            (consolidated_count / total_items_processed * 100)
            if total_items_processed > 0
            else 0
        )
        embed.add_field(name="Success Rate", value=f"{success_rate:.1f}%", inline=True)

        await message.edit(embed=embed)

    async def post_failure_summary(
        self,
        error_message: str,
        phase: Optional[ConsolidationPhase] = None,
    ) -> None:
        """
        Post consolidation failure summary.

        Args:
            error_message: Error message describing failure
            phase: Phase where failure occurred

        Raises:
            RuntimeError: If no consolidation message posted yet
        """
        if not self.current_message_id:
            raise RuntimeError("No consolidation message posted")

        channel = self.discord_client.get_channel(self.dream_channel_id)
        if not channel:
            raise RuntimeError(f"Dream channel not found: {self.dream_channel_id}")

        message = await channel.fetch_message(self.current_message_id)
        self.current_status = DreamStatus.FAILED

        embed = discord.Embed(
            title="❌ Consolidation Failed",
            description=error_message,
            color=discord.Color.red(),
        )

        if phase:
            embed.add_field(name="Failed During", value=phase.value.title(), inline=False)

        # Add phases completed before failure
        history_text = "\n".join(
            [f"✓ {p.phase.value.title()}" for p in self.phase_history]
        )
        if history_text:
            embed.add_field(name="Completed Phases", value=history_text, inline=False)

        await message.edit(embed=embed)

    def get_status_text(self) -> str:
        """
        Get human-readable status text for `/dream` command.

        Returns:
            Status text
        """
        if self.current_status == DreamStatus.IDLE:
            return "🌙 Dream is idle — no consolidation in progress"

        status_emoji = {
            DreamStatus.CONSOLIDATING: "🔄",
            DreamStatus.INVENTORY: "📦",
            DreamStatus.DECAY: "💤",
            DreamStatus.CONTRADICTION: "⚖️",
            DreamStatus.MERGE: "🔗",
            DreamStatus.PROMOTE: "⬆️",
            DreamStatus.REPORT: "📊",
            DreamStatus.COMPLETE: "✅",
            DreamStatus.FAILED: "❌",
        }

        emoji = status_emoji.get(self.current_status, "⚙️")
        status_name = self.current_status.value.title()

        lines = [f"{emoji} **Status:** {status_name}"]

        if self.current_message_id:
            lines.append(f"**Message ID:** {self.current_message_id}")

        if self.phase_history:
            lines.append(f"**Phases Completed:** {len(self.phase_history)}")

        return "\n".join(lines)

    async def get_history(self, limit: int = 10) -> list[dict]:
        """
        Get recent consolidation messages from dream channel.

        Args:
            limit: Maximum number of messages to retrieve

        Returns:
            List of message dicts with timestamp and content
        """
        channel = self.discord_client.get_channel(self.dream_channel_id)
        if not channel:
            return []

        history = []
        async for message in channel.history(limit=limit):
            history.append(
                {
                    "id": message.id,
                    "created_at": message.created_at.isoformat(),
                    "content": message.content or "[Embed message]",
                }
            )

        return history
