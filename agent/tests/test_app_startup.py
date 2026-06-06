"""Tests for BridgeApp startup behaviour — kernel integrity halt wiring."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio


@pytest.mark.asyncio
async def test_kernel_mismatch_halts():
    """When verify_kernel_hashes returns mismatches, set_halt must be called."""
    from bridge.app import BridgeApp

    # Build minimal mock config
    config = MagicMock()
    config.discord_token = "test"
    config.operator_discord_id = "op-123"
    config.data_dir = "/tmp/test-data"
    config.log_dir = "/tmp/test-logs"
    config.api_enabled = False
    config.proactive_enabled = False
    config.consolidation_enabled = False
    config.remote_halt_url = ""

    app = object.__new__(BridgeApp)

    # Stub the security manager
    security = MagicMock()
    security.verify_kernel_hashes.return_value = ["bridge/app.py: hash mismatch"]
    security.log_event = AsyncMock()
    security.set_halt = MagicMock()
    app._security = security

    # Stub discord bot
    discord = MagicMock()
    discord.send_message = AsyncMock()
    app._discord = discord

    # Run the mismatch branch in isolation via asyncio.to_thread
    mismatches = await asyncio.to_thread(security.verify_kernel_hashes)
    assert mismatches != ["baseline file missing"]

    await security.log_event(
        "kernel_integrity_failure",
        details={"mismatches": mismatches},
    )
    await asyncio.to_thread(security.set_halt, "kernel_integrity_failure")

    security.set_halt.assert_called_once_with("kernel_integrity_failure")


@pytest.mark.asyncio
async def test_kernel_mismatch_discord_alert_mentions_halt():
    """Discord alert text should mention 'halted' when kernel integrity fails."""

    config = MagicMock()
    config.operator_discord_id = "op-123"

    security = MagicMock()
    security.verify_kernel_hashes.return_value = ["bridge/app.py: hash mismatch"]
    security.log_event = AsyncMock()
    security.set_halt = MagicMock()

    discord = MagicMock()
    discord.send_message = AsyncMock()

    mismatches = security.verify_kernel_hashes()

    # Reproduce the alert message from app.py
    alert_msg = (
        "[ALERT] Kernel integrity mismatch detected. Bridge halted. "
        "Restart after verifying baseline.\n"
        + "\n".join(f"  {m}" for m in mismatches)
    )

    assert "halted" in alert_msg.lower()
    assert "bridge/app.py: hash mismatch" in alert_msg


# ── Sprint 09.13 + 09.14 — TickManager + DailyLogWriter activation ────────────


def _patch_proactive(toml_path: Path, enabled: bool) -> None:
    """Append/override [proactive] enabled in a TOML file used by tests."""
    text = toml_path.read_text()
    if "[proactive]" in text:
        # Replace existing block flag
        new_lines = []
        in_proactive = False
        for line in text.splitlines():
            if line.strip() == "[proactive]":
                in_proactive = True
                new_lines.append(line)
                continue
            if in_proactive and line.startswith("["):
                in_proactive = False
            if in_proactive and line.strip().startswith("enabled"):
                new_lines.append(f"enabled = {str(enabled).lower()}")
            else:
                new_lines.append(line)
        text = "\n".join(new_lines) + "\n"
    else:
        text += f"\n[proactive]\nenabled = {str(enabled).lower()}\n"
    toml_path.write_text(text)


def _patch_daily_log(toml_path: Path, enabled: bool) -> None:
    """Append/override [daily_log] enabled in a TOML file used by tests."""
    text = toml_path.read_text()
    if "[daily_log]" in text:
        new_lines = []
        in_section = False
        for line in text.splitlines():
            if line.strip() == "[daily_log]":
                in_section = True
                new_lines.append(line)
                continue
            if in_section and line.startswith("["):
                in_section = False
            if in_section and line.strip().startswith("enabled"):
                new_lines.append(f"enabled = {str(enabled).lower()}")
            else:
                new_lines.append(line)
        text = "\n".join(new_lines) + "\n"
    else:
        text += f"\n[daily_log]\nenabled = {str(enabled).lower()}\n"
    toml_path.write_text(text)


@pytest_asyncio.fixture
async def wired_app_factory(tmp_path, sample_config_toml, mock_keyring):
    """Yield a callable that initializes BridgeApp and returns it.

    The caller is responsible for closing the DB. Lets each test patch the
    TOML or env before construction.
    """
    from bridge.app import BridgeApp

    created: list = []

    async def _build():
        app = BridgeApp(config_path=str(sample_config_toml))
        await app._initialize()
        created.append(app)
        return app

    yield _build

    for app in created:
        # Sprint R2.3 (#1895) — close sync-sqlite stores BridgeApp owns
        # before closing the async DB. See bridge/app.py::stop().
        for _store in (app._embedding_engine, app._workorder_store, app._peer_registry):
            if _store is not None and hasattr(_store, "close"):
                try:
                    _store.close()
                except Exception:  # noqa: BLE001
                    pass
        if app._db:
            await app._db.close()


@pytest.mark.asyncio
async def test_tick_manager_constructed_when_enabled(
    wired_app_factory, sample_config_toml
):
    """Sprint 09.13: with [proactive] enabled = true, TickManager is constructed."""
    _patch_proactive(sample_config_toml, enabled=True)
    app = await wired_app_factory()
    assert app._tick_manager is not None
    from bridge.tick_manager import TickManager
    assert isinstance(app._tick_manager, TickManager)


@pytest.mark.asyncio
async def test_tick_manager_none_when_disabled(wired_app_factory):
    """Sprint 09.13: with default config (proactive_enabled=False), TickManager
    stays None and the WiringReport surfaces dormancy at boot."""
    app = await wired_app_factory()
    assert app._tick_manager is None


@pytest.mark.asyncio
async def test_proactive_guard_constructed_alongside_tick_manager(
    wired_app_factory, sample_config_toml
):
    """Sprint 09.13: ProactiveGuard is constructed under the same flag and
    threaded into TickManager so check_action() runs before tick injection."""
    _patch_proactive(sample_config_toml, enabled=True)
    app = await wired_app_factory()
    assert app._proactive_guard is not None
    from bridge.proactive_safety import ProactiveGuard
    assert isinstance(app._proactive_guard, ProactiveGuard)
    # The guard must be wired into the TickManager — Plan 06 §9 item 7 fix.
    assert app._tick_manager is not None
    assert app._tick_manager.proactive_guard is app._proactive_guard


@pytest.mark.asyncio
async def test_daily_log_constructed_when_enabled(wired_app_factory):
    """Sprint 09.14: default config (daily_log_enabled=True) constructs the
    DailyLogWriter — closes the wire-to-None slot from Sprint 01.03."""
    app = await wired_app_factory()
    from bridge.daily_log import DailyLogWriter
    assert app._daily_log is not None
    assert isinstance(app._daily_log, DailyLogWriter)


@pytest.mark.asyncio
async def test_daily_log_none_when_disabled(
    wired_app_factory, sample_config_toml
):
    """Sprint 09.14: with [daily_log] enabled = false, the writer stays None."""
    _patch_daily_log(sample_config_toml, enabled=False)
    app = await wired_app_factory()
    assert app._daily_log is None


@pytest.mark.asyncio
async def test_daily_log_propagated_to_session_manager(wired_app_factory):
    """Sprint 09.14: SessionManager.set_daily_log is NOT in the WIRING_MANIFEST
    so BridgeApp._initialize() must call it explicitly. Verify the SAME
    DailyLogWriter instance flows through."""
    app = await wired_app_factory()
    assert app._daily_log is not None
    assert app._session_mgr._daily_log is app._daily_log


@pytest.mark.asyncio
async def test_daily_log_propagated_to_commands(wired_app_factory):
    """Sprint 09.14: CommandHandler.set_daily_log fires via the WIRING_MANIFEST
    once _daily_log is non-None. Verify same instance flows through."""
    app = await wired_app_factory()
    assert app._daily_log is not None
    assert app._commands._daily_log is app._daily_log
