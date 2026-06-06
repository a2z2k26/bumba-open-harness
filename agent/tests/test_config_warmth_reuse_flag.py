"""Tests for zone4-warmth.C.01 — chief_dispatcher_warmth_reuse_enabled flag.

This is a flag-only sprint: no runtime call site consults the flag yet.
C.02 wires the dispatcher lookup; C.03 wires the message_history reload;
C.04 flips the default to True after a shadow-soak window.

Tests cover:
  - Dataclass default is False
  - Field is present on BridgeConfig
  - TOML alias [chief_dispatcher] warmth_reuse_enabled → field
  - Env-var override BUMBA_CHIEF_DISPATCHER_WARMTH_REUSE_ENABLED with
    every accepted truthy/falsy spelling
  - Strict-bool semantics per audit-2026-05-16.B.06 (#2055): typos and
    unrecognized values raise ConfigError
  - Field is included in dataclasses.asdict() output
"""
from __future__ import annotations

import dataclasses
import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.config import BridgeConfig, ConfigError, load_config


def test_flag_defaults_true():
    """C.04 bypass (2026-05-18): default flipped True without shadow soak
    per operator decision. Operators wanting cold-start-every-dispatch can
    flip False via [chief_dispatcher] warmth_reuse_enabled in bridge.toml.
    """
    cfg = BridgeConfig()
    assert cfg.chief_dispatcher_warmth_reuse_enabled is True


def test_flag_field_exists_on_bridge_config():
    cfg = BridgeConfig()
    assert hasattr(cfg, "chief_dispatcher_warmth_reuse_enabled")


def test_toml_alias_round_trips(sample_config_toml: Path, mock_keyring):
    """`[chief_dispatcher] warmth_reuse_enabled = true` maps to the flag."""
    sample_config_toml.write_text(
        sample_config_toml.read_text()
        + textwrap.dedent(
            """

            [chief_dispatcher]
            warmth_reuse_enabled = true
            """
        )
    )
    cfg = load_config(sample_config_toml)
    assert cfg.chief_dispatcher_warmth_reuse_enabled is True


def test_toml_alias_false(sample_config_toml: Path, mock_keyring):
    sample_config_toml.write_text(
        sample_config_toml.read_text()
        + textwrap.dedent(
            """

            [chief_dispatcher]
            warmth_reuse_enabled = false
            """
        )
    )
    cfg = load_config(sample_config_toml)
    assert cfg.chief_dispatcher_warmth_reuse_enabled is False


def test_env_var_override_true(sample_config_toml: Path, mock_keyring):
    with patch.dict(
        os.environ,
        {"BUMBA_CHIEF_DISPATCHER_WARMTH_REUSE_ENABLED": "true"},
    ):
        cfg = load_config(sample_config_toml)
    assert cfg.chief_dispatcher_warmth_reuse_enabled is True


@pytest.mark.parametrize("val", ["1", "yes", "on", "TRUE", "YES", "ON"])
def test_env_var_override_truthy_variants(
    sample_config_toml: Path, mock_keyring, val: str
):
    with patch.dict(
        os.environ,
        {"BUMBA_CHIEF_DISPATCHER_WARMTH_REUSE_ENABLED": val},
    ):
        cfg = load_config(sample_config_toml)
    assert cfg.chief_dispatcher_warmth_reuse_enabled is True, val


@pytest.mark.parametrize("val", ["0", "no", "off", "FALSE", "No", "OFF"])
def test_env_var_override_falsy_variants(
    sample_config_toml: Path, mock_keyring, val: str
):
    with patch.dict(
        os.environ,
        {"BUMBA_CHIEF_DISPATCHER_WARMTH_REUSE_ENABLED": val},
    ):
        cfg = load_config(sample_config_toml)
    assert cfg.chief_dispatcher_warmth_reuse_enabled is False, val


def test_env_var_invalid_value_raises(sample_config_toml: Path, mock_keyring):
    """Per audit-2026-05-16.B.06 strict-bool behavior, typos raise."""
    with patch.dict(
        os.environ,
        {"BUMBA_CHIEF_DISPATCHER_WARMTH_REUSE_ENABLED": "treu"},
    ):
        with pytest.raises(
            ConfigError, match="BUMBA_CHIEF_DISPATCHER_WARMTH_REUSE_ENABLED"
        ):
            load_config(sample_config_toml)


def test_flag_in_to_dict():
    """Flag is serialized when BridgeConfig is dumped via dataclasses.asdict."""
    cfg = BridgeConfig()
    d = dataclasses.asdict(cfg)
    assert "chief_dispatcher_warmth_reuse_enabled" in d
    assert d["chief_dispatcher_warmth_reuse_enabled"] is True
