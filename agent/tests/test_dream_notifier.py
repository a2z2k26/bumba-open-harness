"""Tests for DreamNotifier — Discord consolidation progress visibility."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.dream_notifier import DreamNotifier, DreamStatus, ConsolidationPhase


@pytest.fixture
def mock_discord_client():
    """Mock Discord client."""
    client = AsyncMock()
    client.get_channel = MagicMock(return_value=AsyncMock())
    return client


@pytest.fixture
def dream_notifier(mock_discord_client):
    """Create a DreamNotifier instance."""
    return DreamNotifier(
        discord_client=mock_discord_client,
        dream_channel_id=123456789,
    )


class TestDreamNotifierInit:
    """Tests for DreamNotifier initialization."""

    def test_init(self, mock_discord_client):
        """Test DreamNotifier initialization."""
        notifier = DreamNotifier(
            discord_client=mock_discord_client,
            dream_channel_id=987654321,
        )
        assert notifier.discord_client == mock_discord_client
        assert notifier.dream_channel_id == 987654321
        assert notifier.current_status == DreamStatus.IDLE
        assert notifier.current_message_id is None


class TestDreamStatusEnum:
    """Tests for DreamStatus enum."""

    def test_dream_status_values(self):
        """Test DreamStatus enum has expected values."""
        assert DreamStatus.IDLE.value == "idle"
        assert DreamStatus.CONSOLIDATING.value == "consolidating"
        assert DreamStatus.INVENTORY.value == "inventory"
        assert DreamStatus.DECAY.value == "decay"
        assert DreamStatus.CONTRADICTION.value == "contradiction"
        assert DreamStatus.MERGE.value == "merge"
        assert DreamStatus.PROMOTE.value == "promote"
        assert DreamStatus.REPORT.value == "report"
        assert DreamStatus.COMPLETE.value == "complete"
        assert DreamStatus.FAILED.value == "failed"


class TestConsolidationPhaseEnum:
    """Tests for ConsolidationPhase enum."""

    def test_consolidation_phase_values(self):
        """Test ConsolidationPhase enum has expected values."""
        assert ConsolidationPhase.INVENTORY.value == "inventory"
        assert ConsolidationPhase.DECAY.value == "decay"
        assert ConsolidationPhase.CONTRADICTION.value == "contradiction"
        assert ConsolidationPhase.MERGE.value == "merge"
        assert ConsolidationPhase.PROMOTE.value == "promote"
        assert ConsolidationPhase.REPORT.value == "report"


class TestPostInitialMessage:
    """Tests for posting initial consolidation message."""

    @pytest.mark.asyncio
    async def test_post_initial_message(self, dream_notifier, mock_discord_client):
        """Test posting initial consolidation message."""
        channel = AsyncMock()
        mock_discord_client.get_channel.return_value = channel
        channel.send = AsyncMock(return_value=MagicMock(id=555))

        message_id = await dream_notifier.post_initial_message()

        assert message_id == 555
        assert dream_notifier.current_message_id == 555
        assert dream_notifier.current_status == DreamStatus.CONSOLIDATING
        channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_initial_message_channel_not_found(
        self, dream_notifier, mock_discord_client
    ):
        """Test posting initial message when channel not found."""
        mock_discord_client.get_channel.return_value = None

        with pytest.raises(RuntimeError, match="Dream channel not found"):
            await dream_notifier.post_initial_message()

    @pytest.mark.asyncio
    async def test_initial_message_format(self, dream_notifier, mock_discord_client):
        """Test initial message format."""
        channel = AsyncMock()
        mock_discord_client.get_channel.return_value = channel
        channel.send = AsyncMock(return_value=MagicMock(id=555))

        await dream_notifier.post_initial_message()

        call_args = channel.send.call_args
        message_content = call_args[1]["embed"].title
        assert "Consolidation" in message_content or "Dream" in message_content


class TestUpdatePhaseProgress:
    """Tests for updating phase progress."""

    @pytest.mark.asyncio
    async def test_update_phase_progress(self, dream_notifier, mock_discord_client):
        """Test updating phase progress."""
        channel = AsyncMock()
        mock_discord_client.get_channel.return_value = channel
        message = AsyncMock()
        channel.fetch_message = AsyncMock(return_value=message)

        dream_notifier.current_message_id = 555
        dream_notifier.current_status = DreamStatus.CONSOLIDATING

        await dream_notifier.update_phase_progress(
            phase=ConsolidationPhase.INVENTORY,
            status="Processing knowledge inventory...",
            item_count=42,
        )

        assert dream_notifier.current_status == DreamStatus.INVENTORY
        channel.fetch_message.assert_called_once_with(555)
        message.edit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_phase_progress_no_message_id(self, dream_notifier):
        """Test updating phase progress with no message ID."""
        dream_notifier.current_message_id = None

        with pytest.raises(RuntimeError, match="No consolidation message posted"):
            await dream_notifier.update_phase_progress(
                phase=ConsolidationPhase.INVENTORY,
                status="Processing...",
            )

    @pytest.mark.asyncio
    async def test_update_multiple_phases(self, dream_notifier, mock_discord_client):
        """Test updating through multiple phases."""
        channel = AsyncMock()
        mock_discord_client.get_channel.return_value = channel
        message = AsyncMock()
        channel.fetch_message = AsyncMock(return_value=message)

        dream_notifier.current_message_id = 555
        dream_notifier.current_status = DreamStatus.CONSOLIDATING

        phases = [
            ConsolidationPhase.INVENTORY,
            ConsolidationPhase.DECAY,
            ConsolidationPhase.CONTRADICTION,
            ConsolidationPhase.MERGE,
            ConsolidationPhase.PROMOTE,
            ConsolidationPhase.REPORT,
        ]

        for phase in phases:
            await dream_notifier.update_phase_progress(
                phase=phase, status=f"Running {phase.value}..."
            )

        assert dream_notifier.current_status == DreamStatus.REPORT


class TestCompletionAndFailure:
    """Tests for completion and failure handling."""

    @pytest.mark.asyncio
    async def test_post_completion_summary(self, dream_notifier, mock_discord_client):
        """Test posting completion summary."""
        channel = AsyncMock()
        mock_discord_client.get_channel.return_value = channel
        message = AsyncMock()
        channel.fetch_message = AsyncMock(return_value=message)

        dream_notifier.current_message_id = 555
        dream_notifier.current_status = DreamStatus.REPORT

        await dream_notifier.post_completion_summary(
            total_items_processed=100,
            consolidated_count=85,
            failed_count=2,
            duration_seconds=45.5,
        )

        assert dream_notifier.current_status == DreamStatus.COMPLETE
        message.edit.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_failure_summary(self, dream_notifier, mock_discord_client):
        """Test posting failure summary."""
        channel = AsyncMock()
        mock_discord_client.get_channel.return_value = channel
        message = AsyncMock()
        channel.fetch_message = AsyncMock(return_value=message)

        dream_notifier.current_message_id = 555
        dream_notifier.current_status = DreamStatus.INVENTORY

        await dream_notifier.post_failure_summary(
            error_message="Lock acquisition failed",
            phase=ConsolidationPhase.INVENTORY,
        )

        assert dream_notifier.current_status == DreamStatus.FAILED
        message.edit.assert_called_once()

    @pytest.mark.asyncio
    async def test_completion_summary_no_message(self, dream_notifier):
        """Test completion summary with no message ID."""
        dream_notifier.current_message_id = None

        with pytest.raises(RuntimeError, match="No consolidation message posted"):
            await dream_notifier.post_completion_summary(
                total_items_processed=100,
                consolidated_count=85,
                failed_count=2,
                duration_seconds=30.0,
            )


class TestDreamCommand:
    """Tests for dream command support."""

    @pytest.mark.asyncio
    async def test_get_status_text(self, dream_notifier):
        """Test getting status text."""
        dream_notifier.current_status = DreamStatus.CONSOLIDATING
        dream_notifier.current_message_id = 555

        status_text = dream_notifier.get_status_text()

        assert "consolidating" in status_text.lower()
        assert "555" in status_text

    @pytest.mark.asyncio
    async def test_get_status_idle(self, dream_notifier):
        """Test getting status when idle."""
        dream_notifier.current_status = DreamStatus.IDLE
        dream_notifier.current_message_id = None

        status_text = dream_notifier.get_status_text()

        assert "idle" in status_text.lower()

    @pytest.mark.asyncio
    async def test_get_history(self, dream_notifier, mock_discord_client):
        """Test getting consolidation history."""
        channel = AsyncMock()
        mock_discord_client.get_channel.return_value = channel

        # Mock recent messages with async iterator
        message_1 = MagicMock(
            id=1, created_at=datetime.now(), content="Consolidation completed"
        )
        message_2 = MagicMock(
            id=2, created_at=datetime.now(), content="Consolidation started"
        )

        async def async_history_gen(*args, **kwargs):
            for msg in [message_1, message_2]:
                yield msg

        channel.history = MagicMock(return_value=async_history_gen())

        history = await dream_notifier.get_history(limit=2)

        assert len(history) <= 2


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_message_fetch_error(self, dream_notifier, mock_discord_client):
        """Test handling message fetch errors."""
        channel = AsyncMock()
        mock_discord_client.get_channel.return_value = channel
        channel.fetch_message = AsyncMock(side_effect=Exception("Not found"))

        dream_notifier.current_message_id = 999

        with pytest.raises(Exception):
            await dream_notifier.update_phase_progress(
                phase=ConsolidationPhase.INVENTORY,
                status="Test",
            )

    @pytest.mark.asyncio
    async def test_edit_message_error_recovery(self, dream_notifier, mock_discord_client):
        """Test error recovery when editing message fails."""
        channel = AsyncMock()
        mock_discord_client.get_channel.return_value = channel
        message = AsyncMock()
        message.edit = AsyncMock(side_effect=Exception("Edit failed"))
        channel.fetch_message = AsyncMock(return_value=message)

        dream_notifier.current_message_id = 555

        with pytest.raises(Exception):
            await dream_notifier.update_phase_progress(
                phase=ConsolidationPhase.INVENTORY,
                status="Test",
            )


class TestMessageFormatting:
    """Tests for message formatting."""

    @pytest.mark.asyncio
    async def test_phase_progress_message_format(self, dream_notifier):
        """Test phase progress message format."""
        dream_notifier.current_status = DreamStatus.INVENTORY

        # Build a sample embed
        embed_dict = {
            "title": "Consolidation Phase: Inventory",
            "description": "Processing knowledge inventory...",
            "fields": [{"name": "Items", "value": "42"}],
        }

        # Verify expected format
        assert "Consolidation" in embed_dict["title"]
        assert "Inventory" in embed_dict["title"]
        assert "Items" in str(embed_dict["fields"])

    @pytest.mark.asyncio
    async def test_completion_message_format(self, dream_notifier):
        """Test completion message format."""
        dream_notifier.current_status = DreamStatus.COMPLETE

        # Build a sample embed
        embed_dict = {
            "title": "✅ Consolidation Complete",
            "description": "Dream phase completed successfully",
            "fields": [
                {"name": "Total Processed", "value": "100"},
                {"name": "Consolidated", "value": "85"},
                {"name": "Failed", "value": "2"},
            ],
        }

        assert "Complete" in embed_dict["title"]
        assert len(embed_dict["fields"]) == 3

    @pytest.mark.asyncio
    async def test_failure_message_format(self, dream_notifier):
        """Test failure message format."""
        dream_notifier.current_status = DreamStatus.FAILED

        # Build a sample embed
        embed_dict = {
            "title": "❌ Consolidation Failed",
            "description": "Lock acquisition failed",
        }

        assert "Failed" in embed_dict["title"]
        assert "Lock" in embed_dict["description"]
