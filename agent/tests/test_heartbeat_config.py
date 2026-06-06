"""Sprint 07.09 — heartbeat dead-man's switch config wiring.

The bridge must learn ``healthcheck_bridge_url`` from EITHER:
  - ``config/bridge.toml`` ``[heartbeat] healthcheck_bridge_url``
  - ``/opt/bumba-harness/data/.secrets`` ``healthcheck_bridge_url=...``

When both are set, ``.secrets`` wins (the URL is a deployment-topology
secret per spec Q12 #3). When neither is set, ``HeartbeatPinger.start()``
must short-circuit with a single INFO log and never schedule a task.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from bridge.config import load_config
from bridge.heartbeat import HeartbeatPinger


class TestSprint0709HeartbeatConfig:
    """Three named tests pinned by the sprint spec."""

    @pytest.mark.asyncio
    async def test_pinger_starts_when_url_in_toml(self, tmp_path):
        """[heartbeat].healthcheck_bridge_url in bridge.toml → pinger starts."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[heartbeat]\n'
            'healthcheck_bridge_url = "https://hc-ping.com/from-toml"\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.healthcheck_bridge_url == "https://hc-ping.com/from-toml"

        pinger = HeartbeatPinger(config.healthcheck_bridge_url, MagicMock())
        await pinger.start()
        assert pinger._task is not None
        await pinger.stop()

    @pytest.mark.asyncio
    async def test_pinger_starts_when_url_in_secrets(
        self, tmp_path, monkeypatch
    ):
        """healthcheck_bridge_url in .secrets → pinger starts AND wins over toml.

        Asserts the precedence rule (Q12 #3): ``.secrets`` overrides
        ``bridge.toml`` so the operator can deploy with a TOML placeholder
        and override per-host via .secrets without redeploying config.
        """
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[heartbeat]\n'
            'healthcheck_bridge_url = "https://hc-ping.com/from-toml"\n'
        )
        secrets_file = tmp_path / ".secrets"
        secrets_file.write_text(
            "healthcheck_bridge_url=https://hc-ping.com/from-secrets\n"
        )
        secrets_file.chmod(0o600)

        # Steer _load_secrets_file at the secrets file we just wrote, and
        # neutralize the Keychain lookup so it returns nothing here.
        from bridge import config as config_mod
        monkeypatch.setattr(
            config_mod,
            "_load_secrets",
            lambda **_kw: config_mod._load_secrets_file(str(secrets_file)),
        )
        # Discord credentials still need to load for skip_validation=False —
        # but we're using skip_validation=True so empty strings are fine.
        config = load_config(toml, skip_secrets=False, skip_validation=True)
        assert config.healthcheck_bridge_url == "https://hc-ping.com/from-secrets"

        pinger = HeartbeatPinger(config.healthcheck_bridge_url, MagicMock())
        await pinger.start()
        assert pinger._task is not None
        await pinger.stop()

    @pytest.mark.asyncio
    async def test_pinger_disabled_when_url_missing_single_info_log(
        self, tmp_path, caplog
    ):
        """No URL anywhere → pinger.start() logs ONE info line, no task."""
        toml = tmp_path / "bridge.toml"
        toml.write_text("[bridge]\ndata_dir = \"/tmp\"\n")
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.healthcheck_bridge_url == ""

        pinger = HeartbeatPinger(
            config.healthcheck_bridge_url or None, MagicMock()
        )
        with caplog.at_level(logging.INFO, logger="bridge.heartbeat"):
            await pinger.start()

        # No background task scheduled.
        assert pinger._task is None
        # Exactly one INFO log line — the "no check URL configured" notice.
        skip_messages = [
            r for r in caplog.records
            if r.name == "bridge.heartbeat"
            and r.levelno == logging.INFO
            and "no check URL configured" in r.message
        ]
        assert len(skip_messages) == 1
