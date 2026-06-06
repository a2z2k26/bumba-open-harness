"""Sprint 06.03: API halt persists to disk via _cmd_halt → SecurityManager.set_halt."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.commands import CommandHandler
from bridge.security import SecurityManager


@pytest.mark.asyncio
async def test_api_halt_persists_to_disk(tmp_path: Path):
    """Simulate API path → _cmd_halt → assert halt.flag on-disk exists."""
    # Set up SecurityManager with a real data_dir
    config = MagicMock()
    config.log_dir = str(tmp_path)
    config.data_dir = str(tmp_path)
    db = AsyncMock()
    security = SecurityManager(db, config)

    # Set up CommandHandler with wired SecurityManager
    handler = CommandHandler(
        db=db,
        queue=MagicMock(),
        session_manager=MagicMock(),
    )
    handler.set_security(security)

    # Simulate API dispatch of /halt
    result = await handler.handle("api-chat", "halt", "")
    assert "halted" in result.lower()

    # Verify halt.flag file exists on disk
    halt_flag = tmp_path / "halt.flag"
    assert halt_flag.exists(), "halt.flag was not written to disk"
    assert halt_flag.read_text() == "operator_halt"
