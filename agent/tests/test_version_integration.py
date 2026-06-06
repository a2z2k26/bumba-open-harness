"""Integration tests for Sprint 07.10 — version wiring into bridge startup.

Covers:
- ``init_version`` semantics on a fresh install (no version.json)
- ``init_version`` semantics with a deploy-written version.json
- ``/healthz`` response includes a top-level ``version`` field
- ``_read_pyproject_version`` helper resolves the source-tree version
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge import version as version_mod
from bridge.health import HealthServer
from bridge.version import (
    VersionInfo,
    get_running_version,
    init_version,
    write_version,
)


@pytest.fixture(autouse=True)
def _reset_running_version():
    """Reset module-level running version between tests for isolation."""
    original = version_mod._RUNNING_VERSION
    yield
    version_mod._RUNNING_VERSION = original


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


# ─────────────────────────────────────────────────────────────────────
# init_version() side-effects on bridge startup
# ─────────────────────────────────────────────────────────────────────


class TestInitVersionStartup:
    def test_fresh_install_falls_back_to_pyproject_version(self, data_dir):
        """No version.json yet — running version reflects default_version."""
        info = init_version(data_dir, default_version="0.7.10")
        assert info.version == "0.7.10"
        assert get_running_version() == "0.7.10"
        # version.json itself is NOT written by init_version (deploy script's job)
        assert not (data_dir / "version.json").exists()

    def test_default_default_is_zero_zero_zero(self, data_dir):
        """Backward-compat: omitting default_version preserves old "0.0.0" behavior."""
        info = init_version(data_dir)
        assert info.version == "0.0.0"
        assert get_running_version() == "0.0.0"

    def test_deploy_written_version_wins(self, data_dir):
        """If deploy script wrote version.json, init_version uses it (default ignored)."""
        write_version(data_dir, "1.2.3", git_commit="abc1234", deployed_by="deploy-helper")
        info = init_version(data_dir, default_version="9.9.9")
        assert info.version == "1.2.3"
        assert info.git_commit == "abc1234"
        assert get_running_version() == "1.2.3"

    def test_init_version_creates_version_json_only_via_write_version(self, data_dir):
        """init_version itself never writes — it only reads. write_version is the writer."""
        init_version(data_dir, default_version="2.0.0")
        assert not (data_dir / "version.json").exists()
        write_version(data_dir, "2.0.0", deployed_by="manual")
        assert (data_dir / "version.json").exists()
        payload = json.loads((data_dir / "version.json").read_text())
        assert payload["version"] == "2.0.0"

    def test_returns_version_info_dataclass(self, data_dir):
        info = init_version(data_dir, default_version="0.7.10")
        assert isinstance(info, VersionInfo)
        assert info.version == "0.7.10"


# ─────────────────────────────────────────────────────────────────────
# /healthz integration — top-level "version" field
# ─────────────────────────────────────────────────────────────────────


def _make_mock_app(*, data_dir: str = "/tmp/test-data"):
    """Create a mock BridgeApp sufficient for collect_health()."""
    app = MagicMock()

    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.latency = 0.04
    app._discord = bot

    runner = MagicMock()
    runner._last_invocation = None
    app._claude = runner

    db = AsyncMock()
    db.db_path = MagicMock()
    db.db_path.exists.return_value = True
    db.db_path.stat.return_value = MagicMock(st_size=64 * 1024 * 1024)
    db.db_path.with_suffix.return_value = MagicMock(exists=lambda: False)
    db.fetchone = AsyncMock(side_effect=[
        MagicMock(__getitem__=lambda s, i: "ok"),
        MagicMock(__getitem__=lambda s, i: 1),
    ])
    db.fetchall = AsyncMock(return_value=[])
    app._db = db

    memory = AsyncMock()
    memory.search_knowledge = AsyncMock(return_value=[])
    app._memory = memory

    refresher = MagicMock()
    refresher._expires_at = time.time() + 7200
    app._token_refresher = refresher

    config = MagicMock()
    config.data_dir = data_dir
    app._config = config

    app._voice = None
    return app


class TestHealthzVersionField:
    @pytest.mark.asyncio
    async def test_healthz_includes_top_level_version_field(self):
        """Sprint 07.10 — /healthz response must surface a top-level version."""
        version_mod._RUNNING_VERSION = "0.7.10"
        server = HealthServer(_make_mock_app())
        health = await server.collect_health()

        assert "version" in health, "version must appear at the top level of /healthz"
        assert health["version"] == "0.7.10"
        # Defensive: NOT inside components — version is metadata, not a check.
        assert "version" not in health.get("components", {})

    @pytest.mark.asyncio
    async def test_healthz_version_is_non_empty_string(self):
        version_mod._RUNNING_VERSION = "0.0.0"
        server = HealthServer(_make_mock_app())
        health = await server.collect_health()
        assert isinstance(health["version"], str)
        assert health["version"]  # non-empty

    @pytest.mark.asyncio
    async def test_healthz_version_reflects_init_version(self, tmp_path):
        """End-to-end: init_version() on a fake data_dir, then /healthz reports it."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        write_version(data_dir, "3.14.15", deployed_by="test")
        init_version(data_dir, default_version="9.9.9")

        server = HealthServer(_make_mock_app(data_dir=str(data_dir)))
        health = await server.collect_health()
        assert health["version"] == "3.14.15"


# ─────────────────────────────────────────────────────────────────────
# pyproject.toml fallback helper
# ─────────────────────────────────────────────────────────────────────


class TestReadPyprojectVersion:
    def test_returns_real_project_version(self):
        from bridge.app import _read_pyproject_version
        v = _read_pyproject_version()
        # pyproject.toml currently pins 0.3.0; assert we got a non-fallback value.
        assert v != "0.0.0", "expected to find pyproject.toml in the agent tree"
        # Must look like a semver-ish string (digits + dots).
        assert all(part.isdigit() for part in v.split(".") if part)
