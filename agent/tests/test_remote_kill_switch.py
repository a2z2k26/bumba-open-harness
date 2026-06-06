"""Sprint 06.09: bridge.remote_kill_switch has been deleted.

Verify the module no longer exists (importing it raises ImportError).
Remote halt polling is now handled inline in background_loops.heartbeat_loop
via security.check_remote_halt() and config.remote_halt_url.
"""
from __future__ import annotations

import importlib

import pytest


def test_remote_kill_switch_module_deleted():
    """bridge.remote_kill_switch must not exist after Sprint 06.09 deletion."""
    with pytest.raises(ImportError):
        importlib.import_module("bridge.remote_kill_switch")


def test_config_still_has_remote_halt_url():
    """BridgeConfig.remote_halt_url still exists (used by inline halt check)."""
    from bridge.config import BridgeConfig

    cfg = BridgeConfig()
    assert hasattr(cfg, "remote_halt_url")
    assert cfg.remote_halt_url == ""


def test_config_still_has_remote_halt_check_interval():
    """BridgeConfig.remote_halt_check_interval still exists."""
    from bridge.config import BridgeConfig

    cfg = BridgeConfig()
    assert hasattr(cfg, "remote_halt_check_interval")
    assert cfg.remote_halt_check_interval == 300
