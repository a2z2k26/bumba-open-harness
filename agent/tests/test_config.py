"""Tests for bridge.config (S34)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from bridge.config import (
    BridgeConfig,
    ConfigError,
    _load_secrets_file,
    _require_private_file,
    _resolve_config_path,
    _validate,
    load_config,
)


class TestTomlLoading:
    """S32: TOML parsing and flattening."""

    def test_happy_path(self, sample_config_toml, mock_keyring, tmp_dirs):
        config = load_config(sample_config_toml)
        assert config.heartbeat_interval == 60
        assert config.claude_timeout == 120
        assert config.claude_max_turns == 25
        assert str(tmp_dirs["data_dir"]) == config.data_dir
        assert config.rate_limit_multiplier == 2.0
        assert "Bash(sudo *)" in config.security_disallowed_tools

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nonexistent.toml", skip_secrets=True)

    def test_invalid_toml(self, tmp_path):
        bad = tmp_path / "bad.toml"
        bad.write_text("[[[[invalid toml")
        with pytest.raises(ConfigError, match="Invalid TOML"):
            load_config(bad, skip_secrets=True, skip_validation=True)


class TestEnvOverrides:
    """S32: BUMBA_* environment variable overrides."""

    def test_int_override(self, sample_config_toml, mock_keyring):
        with patch.dict(os.environ, {"BUMBA_CLAUDE_TIMEOUT": "300"}):
            config = load_config(sample_config_toml)
        assert config.claude_timeout == 300

    def test_float_override(self, sample_config_toml, mock_keyring):
        with patch.dict(os.environ, {"BUMBA_RATE_LIMIT_MULTIPLIER": "3.5"}):
            config = load_config(sample_config_toml)
        assert config.rate_limit_multiplier == 3.5

    def test_invalid_int_env(self, sample_config_toml, mock_keyring):
        with patch.dict(os.environ, {"BUMBA_CLAUDE_TIMEOUT": "abc"}):
            with pytest.raises(ConfigError, match="must be int"):
                load_config(sample_config_toml)

    # -- audit-2026-05-16.B.06 (issue #2055, audit M-2) --
    # Strict bool env-override parsing: every accepted spelling resolves,
    # unrecognized values raise ConfigError instead of silently defaulting
    # to False. backends_enabled is the canary field (bool, default False).

    @pytest.mark.parametrize(
        "raw",
        ["1", "true", "TRUE", "True", "yes", "YES", "on", "ON",
         "  true  ", "\tyes\n"],
    )
    def test_bool_env_accepts_truthy_spellings(
        self, sample_config_toml, mock_keyring, raw
    ):
        with patch.dict(os.environ, {"BUMBA_BACKENDS_ENABLED": raw}):
            config = load_config(sample_config_toml)
        assert config.backends_enabled is True, raw

    @pytest.mark.parametrize(
        "raw",
        ["0", "false", "FALSE", "False", "no", "NO", "off", "OFF",
         "  false  "],
    )
    def test_bool_env_accepts_falsy_spellings(
        self, sample_config_toml, mock_keyring, raw
    ):
        with patch.dict(os.environ, {"BUMBA_BACKENDS_ENABLED": raw}):
            config = load_config(sample_config_toml)
        assert config.backends_enabled is False, raw

    def test_bool_env_typo_raises(self, sample_config_toml, mock_keyring):
        # Was silently False pre-B.06 — now must fail loud with the var name.
        with patch.dict(os.environ, {"BUMBA_BACKENDS_ENABLED": "treu"}):
            with pytest.raises(ConfigError, match="BUMBA_BACKENDS_ENABLED"):
                load_config(sample_config_toml)

    def test_bool_env_empty_string_raises(self, sample_config_toml, mock_keyring):
        with patch.dict(os.environ, {"BUMBA_BACKENDS_ENABLED": ""}):
            with pytest.raises(ConfigError, match="BUMBA_BACKENDS_ENABLED"):
                load_config(sample_config_toml)

    def test_bool_env_unrecognized_value_raises(
        self, sample_config_toml, mock_keyring
    ):
        with patch.dict(os.environ, {"BUMBA_BACKENDS_ENABLED": "maybe"}):
            with pytest.raises(ConfigError, match="must be one of"):
                load_config(sample_config_toml)


class TestSecretsAndValidation:
    """S33: Keychain secrets and validation."""

    def test_missing_token(self, sample_config_toml):
        """No keychain mock + no secrets file = no token = should fail validation."""
        with patch("bridge.config.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            with patch("bridge.config._load_secrets_file", return_value={}):
                with pytest.raises(ConfigError, match="Discord bot token is missing"):
                    load_config(sample_config_toml)

    def test_bad_timeout_relationship(self, sample_config_toml, mock_keyring):
        with patch.dict(os.environ, {"BUMBA_CLAUDE_HARD_TIMEOUT": "50"}):
            with pytest.raises(ConfigError, match="claude_hard_timeout must exceed"):
                load_config(sample_config_toml)

    def test_integration_round_trip(self, sample_config_toml, mock_keyring):
        """Full load → verify all sections populated."""
        config = load_config(sample_config_toml)
        assert isinstance(config, BridgeConfig)
        assert config.discord_bot_token.startswith("MTIzNDU2")
        assert config.operator_discord_id == "7565124764"
        assert config.session_idle_timeout == 1800
        assert config.memory_context_window == 20
        assert config.db_size_warn == 524288000


class TestBridgeConfigDefaults:
    """S31: Dataclass defaults."""

    def test_frozen(self):
        config = BridgeConfig()
        with pytest.raises(AttributeError):
            config.heartbeat_interval = 999

    def test_defaults(self):
        config = BridgeConfig()
        assert config.heartbeat_interval == 60
        assert config.claude_output_format == "stream-json"
        assert config.claude_binary is None
        assert config.warm_response_timeout_seconds == 60
        assert config.discord_first_response_sla_seconds == 30
        assert config.discord_progress_interval_seconds == 120
        assert config.security_disallowed_tools == ()

    def test_mcp_health_check_interval_default(self):
        """Issue #1543 — new ``[mcp]`` knob defaults to 300 seconds."""
        config = BridgeConfig()
        assert config.mcp_health_check_interval_seconds == 300

    def test_mcp_health_check_interval_toml_mapping(self, tmp_path):
        """``[mcp].health_check_interval_seconds`` populates the field."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[mcp]\n'
            'health_check_interval_seconds = 120\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.mcp_health_check_interval_seconds == 120

    def test_discord_latency_knobs_toml_mapping(self, tmp_path):
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[discord]\n'
            'first_response_sla_seconds = 15\n'
            'progress_interval_seconds = 45\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.discord_first_response_sla_seconds == 15
        assert config.discord_progress_interval_seconds == 45

    def test_warm_response_timeout_toml_mapping(self, tmp_path):
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[claude]\n'
            'warm_response_timeout_seconds = 45\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.warm_response_timeout_seconds == 45


class TestRemoteHaltDualMapping:
    """Sprint 01.06: remote_halt_url and remote_halt_check_interval are
    declared exactly once on BridgeConfig but populated from two TOML
    sections: [security] (legacy) and [remote_kill_switch] (canonical).
    """

    def test_config_remote_halt_from_security_section(self, tmp_path):
        """Legacy [security] section populates the canonical field."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[security]\n'
            'remote_halt_url = "https://example.com/halt"\n'
            'remote_halt_check_interval = 60\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.remote_halt_url == "https://example.com/halt"
        assert config.remote_halt_check_interval == 60

    def test_config_remote_halt_from_remote_kill_switch_section(self, tmp_path):
        """Canonical [remote_kill_switch] section populates the field."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[remote_kill_switch]\n'
            'halt_url = "https://example.com/halt2"\n'
            'check_interval = 120\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.remote_halt_url == "https://example.com/halt2"
        assert config.remote_halt_check_interval == 120


class TestSprint0107DeletedKnobs:
    """Sprint 01.07: six dead config knobs deleted from BridgeConfig.

    The original deletion list in plan-01 was 7 knobs. ``webhook_secret``
    was excluded after the pre-flight conflict check (PR #843 added it as
    a LIVE field for HMAC-SHA256 signing of outbound payloads at
    app.py:435). The remaining 6 had zero production consumers.

    Regression guard: if a future contributor re-adds one of the 6 dead
    fields, the AttributeError-on-access assertion catches it in CI
    before the config bloat returns.

    Critically, ``webhook_secret`` MUST stay accessible — the
    test_webhook_secret_remains_accessible test asserts it.
    """

    DELETED_KNOBS = (
        "webhook_url",
        "webhook_filter",
        "event_delivery_max_queue",
        "event_delivery_max_retries",
        "event_delivery_base_backoff",
        "proactive_default_sleep_seconds",
    )

    def test_deleted_knobs_do_not_regress(self):
        """Each of the 6 deleted dead-knob attribute names must raise
        AttributeError on a default-constructed BridgeConfig."""
        config = BridgeConfig()
        for knob in self.DELETED_KNOBS:
            with pytest.raises(AttributeError):
                getattr(config, knob)

    def test_webhook_secret_remains_accessible(self):
        """webhook_secret was DELIBERATELY excluded from the deletion list —
        PR #843 (Sprint 06.06 rework) added it as a live field for
        HMAC-SHA256 signing of outbound webhook payloads. app.py:435
        reads config.webhook_secret to construct SerialEventDeliverer.
        This test pins that the live field is preserved."""
        config = BridgeConfig()
        assert config.webhook_secret == ""
        assert hasattr(config, "webhook_secret")

    def test_skill_evolution_loop_default_off(self):
        """Sprint 03.08 (#998) — 3-trigger skill evolution loop ships off."""
        config = BridgeConfig()
        assert config.skill_evolution_loop_enabled is False

    def test_skill_evolution_loop_toml_mapping(self, tmp_path):
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[skill_evolution]\n'
            'loop_enabled = true\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.skill_evolution_loop_enabled is True

    def test_skill_crystallization_default_off(self):
        """Sprint 03.09 (#999) — crystallize-from-trace ships off."""
        config = BridgeConfig()
        assert config.skill_crystallization_enabled is False

    def test_skill_crystallization_toml_mapping(self, tmp_path):
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[skill_evolution]\n'
            'crystallization_enabled = true\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.skill_crystallization_enabled is True

    def test_markdown_skills_default_off(self):
        """Sprint 07.04 (#1033) — markdown-skill convention ships off."""
        config = BridgeConfig()
        assert config.markdown_skills_enabled is False

    def test_markdown_skills_toml_mapping(self, tmp_path):
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[skill_evolution]\n'
            'markdown_skills_enabled = true\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.markdown_skills_enabled is True

    def test_proactive_default_sleep_seconds_toml_mapping_removed(self, tmp_path):
        """The single _TOML_MAP entry for the deleted proactive knob must
        also be gone. Loading a bridge.toml that includes the would-be-mapped
        key must NOT raise — the loader should silently ignore the unknown
        TOML path now that no field maps to it."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[proactive]\n'
            'default_sleep_seconds = 999.0\n'
            'enabled = false\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.proactive_enabled is False
        with pytest.raises(AttributeError):
            getattr(config, "proactive_default_sleep_seconds")


class TestSprintD110DeletedKnobs:
    """Sprint D1.10 (#1182): three dead config knobs deleted from BridgeConfig.

    - ``daily_log_auto_categories``: DailyLogWriter uses hardcoded category strings;
      field was never read at any non-config call site.
    - ``agents_max_invocation_depth``: tier_manager.py owns depth gating without
      consulting this field; field was never read.
    - ``openai_api_key``: OpenAI SDK reads from OPENAI_API_KEY env directly; the
      BridgeConfig field was populated in _load_secrets_file but never consumed.

    Regression guard: AttributeError on access if any of the three fields
    reappears in BridgeConfig.
    """

    DELETED_KNOBS = (
        "daily_log_auto_categories",
        "agents_max_invocation_depth",
        "openai_api_key",
    )

    def test_deleted_knobs_do_not_regress(self):
        config = BridgeConfig()
        for knob in self.DELETED_KNOBS:
            with pytest.raises(AttributeError):
                getattr(config, knob)

    def test_toml_keys_silently_ignored(self, tmp_path):
        """Loading a bridge.toml with formerly-mapped TOML keys must not raise."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            "[agents]\n"
            "max_invocation_depth = 5\n"
            "[daily_log]\n"
            "enabled = true\n"
            'auto_categories = ["session", "error"]\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.daily_log_enabled is True
        with pytest.raises(AttributeError):
            getattr(config, "daily_log_auto_categories")


# ---------- D2.5: load_team_limits ----------


class TestLoadTeamLimits:
    """load_team_limits reads daily_limit_usd from team YAMLs (D2.5)."""

    def test_reads_limits_from_real_yamls(self, tmp_path):
        from teams._config import load_team_limits
        limits = load_team_limits()
        # All 6 team YAMLs should contribute a positive limit.
        # (Sprint P4.1 / #1727 deleted the dormant outreach.yaml; the live
        # outreach pipeline now runs through job_search → outreach-execute-specialist.)
        assert len(limits) >= 6
        assert all(v > 0 for v in limits.values())
        assert "design" in limits
        assert limits["design"] == 6.0

    def test_missing_field_skips_file(self, tmp_path):
        import yaml
        from teams._config import load_team_limits
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.dump({"team": {"name": "bad"}}))
        limits = load_team_limits(teams_dir=tmp_path)
        assert "bad" not in limits

    def test_valid_yaml_loaded(self, tmp_path):
        import yaml
        from teams._config import load_team_limits
        good = tmp_path / "myteam.yaml"
        good.write_text(yaml.dump({"team": {"budget": {"daily_limit_usd": 3.5}}}))
        limits = load_team_limits(teams_dir=tmp_path)
        assert limits == {"myteam": 3.5}


class TestD17aVapiConfigScaffold:
    """D1.7a (#1179): VAPI config scaffold — voice gate + VAPI field defaults."""

    def test_voice_enabled_defaults_false(self):
        """BridgeConfig() must default voice_enabled to False."""
        config = BridgeConfig()
        assert config.voice_enabled is False

    def test_vapi_fields_default_empty(self):
        """All four VAPI string fields must default to empty string."""
        config = BridgeConfig()
        assert config.vapi_api_key == ""
        assert config.vapi_phone_number_id == ""
        assert config.vapi_assistant_id_receptionist == ""
        assert config.vapi_webhook_url == ""

    def test_voice_toml_enabled_field_maps(self, tmp_path):
        """[voice] enabled = true in bridge.toml must set voice_enabled = True."""
        toml = tmp_path / "bridge.toml"
        toml.write_text("[voice]\nenabled = true\n")
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.voice_enabled is True

    def test_vapi_toml_fields_map(self, tmp_path):
        """[vapi] phone_number_id in bridge.toml must round-trip to vapi_phone_number_id."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            "[vapi]\n"
            'phone_number_id = "PN123"\n'
            'assistant_id_receptionist = "ASST456"\n'
            'webhook_url = "https://example.com/vapi"\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.vapi_phone_number_id == "PN123"
        assert config.vapi_assistant_id_receptionist == "ASST456"
        assert config.vapi_webhook_url == "https://example.com/vapi"


class TestConfigPathResolution:
    """Issue #1488 — load_config() must resolve config path via env var or cwd, not just hardcoded legacy path."""

    def test_env_var_override_wins(self, tmp_path, monkeypatch):
        """BUMBA_BRIDGE_CONFIG env var, when set and pointing at a real file, takes priority."""
        custom = tmp_path / "custom-config.toml"
        custom.write_text("[bridge]\nlog_level = \"DEBUG\"\n")
        monkeypatch.setenv("BUMBA_BRIDGE_CONFIG", str(custom))
        # Move cwd somewhere that has no config; env var should still win.
        monkeypatch.chdir(tmp_path)
        resolved = _resolve_config_path()
        assert resolved == custom

    def test_env_var_pointing_at_missing_file_raises(self, tmp_path, monkeypatch):
        """A typo in BUMBA_BRIDGE_CONFIG should fail loud, not silently fall through."""
        monkeypatch.setenv("BUMBA_BRIDGE_CONFIG", str(tmp_path / "does-not-exist.toml"))
        with pytest.raises(ConfigError, match="non-existent file"):
            _resolve_config_path()

    def test_cwd_relative_resolution(self, tmp_path, monkeypatch):
        """No env var, but cwd has config/bridge.toml — that wins over legacy."""
        monkeypatch.delenv("BUMBA_BRIDGE_CONFIG", raising=False)
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "bridge.toml"
        cfg_file.write_text("[bridge]\nlog_level = \"INFO\"\n")
        monkeypatch.chdir(tmp_path)
        resolved = _resolve_config_path()
        assert resolved == cfg_file

    def test_cwd_with_agent_subtree_resolution(self, tmp_path, monkeypatch):
        """No env var, but cwd has agent/config/bridge.toml — picks that."""
        monkeypatch.delenv("BUMBA_BRIDGE_CONFIG", raising=False)
        cfg_dir = tmp_path / "agent" / "config"
        cfg_dir.mkdir(parents=True)
        cfg_file = cfg_dir / "bridge.toml"
        cfg_file.write_text("[bridge]\nlog_level = \"WARNING\"\n")
        monkeypatch.chdir(tmp_path)
        resolved = _resolve_config_path()
        assert resolved == cfg_file

    def test_legacy_fallback_when_nothing_else_resolves(self, tmp_path, monkeypatch):
        """Empty env var + cwd has no config — falls through to the legacy hardcoded path."""
        monkeypatch.delenv("BUMBA_BRIDGE_CONFIG", raising=False)
        # tmp_path has no config/ or agent/config/, so resolution falls through.
        monkeypatch.chdir(tmp_path)
        resolved = _resolve_config_path()
        assert str(resolved) == "/opt/bumba-harness/agent/config/bridge.toml"

    def test_load_config_with_no_path_uses_resolution(self, tmp_path, monkeypatch):
        """load_config() with no path arg should walk the resolution chain."""
        monkeypatch.delenv("BUMBA_BRIDGE_CONFIG", raising=False)
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "bridge.toml"
        cfg_file.write_text("[bridge]\nheartbeat_interval = 42\n")
        monkeypatch.chdir(tmp_path)
        config = load_config(skip_secrets=True, skip_validation=True)
        assert config.heartbeat_interval == 42


class TestInterruptsGateKnobs:
    """fix/dialogue-gate-conversational-whitelist — interrupts.* knobs.

    Two new operator-tunable knobs in [interrupts]:
      - tool_call_gate_enabled (alias for universal_tool_gate_enabled)
      - min_pending_to_gate (int, default 1)
    """

    def test_tool_call_gate_alias_disables_gate(self, tmp_path):
        cfg_file = tmp_path / "bridge.toml"
        cfg_file.write_text(
            "[interrupts]\ntool_call_gate_enabled = false\n"
        )
        config = load_config(cfg_file, skip_secrets=True, skip_validation=True)
        assert config.universal_tool_gate_enabled is False

    def test_universal_tool_gate_original_name_still_works(self, tmp_path):
        cfg_file = tmp_path / "bridge.toml"
        cfg_file.write_text(
            "[interrupts]\nuniversal_tool_gate_enabled = false\n"
        )
        config = load_config(cfg_file, skip_secrets=True, skip_validation=True)
        assert config.universal_tool_gate_enabled is False

    def test_min_pending_to_gate_loads_from_toml(self, tmp_path):
        cfg_file = tmp_path / "bridge.toml"
        cfg_file.write_text(
            "[interrupts]\nmin_pending_to_gate = 2\n"
        )
        config = load_config(cfg_file, skip_secrets=True, skip_validation=True)
        assert config.min_pending_to_gate == 2

    def test_min_pending_to_gate_default_is_one(self, tmp_path):
        cfg_file = tmp_path / "bridge.toml"
        cfg_file.write_text("[bridge]\nheartbeat_interval = 42\n")
        config = load_config(cfg_file, skip_secrets=True, skip_validation=True)
        assert config.min_pending_to_gate == 1
        assert config.universal_tool_gate_enabled is True


class TestClaudeHardTimeoutStrictInequality:
    """Issue #1524 — regression guard for the PR #1522/#1523 incident.

    PR #1522 raised ``[claude] timeout`` 300→600 in ``bridge.toml`` without
    bumping ``hard_timeout`` (left at 600). The validator at
    ``bridge/config.py:1196`` requires strict inequality
    (``hard_timeout > timeout``), so the bridge crash-looped on every
    bootstrap until PR #1523 raised ``hard_timeout`` 600→900. ~20 minutes
    of bridge downtime mid-deploy.

    The validator caught the misconfiguration at startup, but not in CI.
    This class pins the strict-inequality contract so a future operator
    tuning timeouts trips a test, not the daemon.
    """

    @pytest.fixture
    def base_config_kwargs(self, tmp_path):
        """Minimum BridgeConfig overrides to reach the timeout checks in
        ``_validate``. We must supply discord_bot_token and
        operator_discord_id (earlier checks) and real existing directories
        for data_dir / log_dir (later checks, only reached on the positive
        path)."""
        return {
            "discord_bot_token": "test-token",
            "operator_discord_id": "test-operator",
            # Sprint audit-2026-05-16.B.03 (#2052) — _validate now refuses to
            # boot on empty claude_oauth_token; fixture must satisfy the new
            # invariant to reach the timeout checks under test here.
            "claude_oauth_token": "sk-ant-test-token",
            "data_dir": str(tmp_path),
            "log_dir": str(tmp_path),
            # Sprint audit-2026-05-16.B.04 (#2053) — _validate now refuses
            # to boot when api_enabled=True (default) and either
            # api_token or github_webhook_secret is empty; supply stubs so
            # the test can reach the timeout invariants under test here.
            "api_token": "test-api-token",
            "github_webhook_secret": "test-gh-webhook-secret",
        }

    def test_hard_timeout_equal_to_timeout_raises(self, base_config_kwargs):
        """hard_timeout == timeout must FAIL (the PR #1522 failure mode)."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(**base_config_kwargs),
            claude_timeout=600,
            claude_hard_timeout=600,
            claude_absolute_timeout=1800,
        )
        with pytest.raises(ConfigError, match="claude_hard_timeout must exceed claude_timeout"):
            _validate(config)

    def test_hard_timeout_less_than_timeout_raises(self, base_config_kwargs):
        """hard_timeout < timeout must FAIL."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(**base_config_kwargs),
            claude_timeout=600,
            claude_hard_timeout=300,
            claude_absolute_timeout=1800,
        )
        with pytest.raises(ConfigError, match="claude_hard_timeout must exceed claude_timeout"):
            _validate(config)

    def test_hard_timeout_greater_than_timeout_passes(self, base_config_kwargs):
        """hard_timeout > timeout must PASS (the PR #1523 fix shape)."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(**base_config_kwargs),
            claude_timeout=600,
            claude_hard_timeout=900,
            claude_absolute_timeout=1800,
        )
        # Must not raise.
        _validate(config)

    def test_absolute_timeout_equal_to_hard_timeout_raises(self, base_config_kwargs):
        """Parametrized companion — the adjacent strict-inequality check at
        config.py:1198 (absolute_timeout > hard_timeout) protects the same
        timeout-knob misuse class. Pin it here so the whole inequality chain
        is guarded."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(**base_config_kwargs),
            claude_timeout=600,
            claude_hard_timeout=900,
            claude_absolute_timeout=900,
        )
        with pytest.raises(ConfigError, match="claude_absolute_timeout must exceed claude_hard_timeout"):
            _validate(config)


class TestBridgeConfigCrossFieldValidate:
    """Issue #1541 (Plan W W-5.2) — ``BridgeConfig.validate()`` cross-field
    invariants. Single-field range checks stay in ``_validate``; this
    method covers the combinatorial cases where individually-legal values
    are contradictory in pairs / triples.

    All tests exercise ``BridgeConfig.validate()`` directly so they
    isolate cross-field logic from the path / Keychain checks in
    ``_validate``. The full ``load_config`` path is covered by the
    existing ``TestSecretsAndValidation`` class above.
    """

    # ---------- chief_dispatcher_enabled × default_department ----------

    def test_chief_dispatcher_enabled_requires_default_department(self):
        """Empty default_department + chief_dispatcher_enabled = fail."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            chief_dispatcher_enabled=True,
            chief_dispatcher_default_department="",
        )
        with pytest.raises(
            ConfigError,
            match=r"chief_dispatcher_enabled.*chief_dispatcher_default_department",
        ):
            config.validate()

    def test_chief_dispatcher_enabled_with_whitespace_only_default_department_fails(self):
        """Whitespace-only is treated as empty (operator typo guard)."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            chief_dispatcher_enabled=True,
            chief_dispatcher_default_department="   ",
        )
        with pytest.raises(ConfigError, match=r"chief_dispatcher_default_department"):
            config.validate()

    def test_chief_dispatcher_disabled_with_empty_default_department_passes(self):
        """Disabled chief dispatcher tolerates empty default_department."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            chief_dispatcher_enabled=False,
            chief_dispatcher_default_department="",
        )
        # Must not raise.
        config.validate()

    def test_chief_dispatcher_enabled_with_default_department_passes(self):
        """Valid combination."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            chief_dispatcher_enabled=True,
            chief_dispatcher_default_department="strategy",
        )
        config.validate()

    # ---------- universal_tool_gate_enabled × min_pending_to_gate ----------

    @pytest.mark.parametrize("bad_value", [0, -1, -5])
    def test_tool_gate_enabled_requires_positive_min_pending(self, bad_value):
        """min_pending_to_gate < 1 with tool gate enabled = fail."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            universal_tool_gate_enabled=True,
            min_pending_to_gate=bad_value,
        )
        with pytest.raises(
            ConfigError,
            match=r"universal_tool_gate_enabled.*min_pending_to_gate",
        ):
            config.validate()

    def test_tool_gate_disabled_with_zero_min_pending_passes(self):
        """Disabled tool gate tolerates 0 / negative min_pending_to_gate
        (knob is dormant)."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            universal_tool_gate_enabled=False,
            min_pending_to_gate=0,
        )
        config.validate()

    def test_tool_gate_enabled_with_positive_min_pending_passes(self):
        """Valid combination."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            universal_tool_gate_enabled=True,
            min_pending_to_gate=2,
        )
        config.validate()

    # ---------- proactive_scheduler_enabled × interval ----------

    @pytest.mark.parametrize("bad_value", [0.0, -1.0, -300.0])
    def test_proactive_scheduler_enabled_requires_positive_interval(self, bad_value):
        """proactive_scheduler_interval_seconds <= 0 with scheduler enabled = fail."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            proactive_scheduler_enabled=True,
            proactive_scheduler_interval_seconds=bad_value,
        )
        with pytest.raises(
            ConfigError,
            match=r"proactive_scheduler_enabled.*proactive_scheduler_interval_seconds",
        ):
            config.validate()

    def test_proactive_scheduler_disabled_with_zero_interval_passes(self):
        """Disabled scheduler tolerates 0 interval (knob is dormant)."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            proactive_scheduler_enabled=False,
            proactive_scheduler_interval_seconds=0.0,
        )
        config.validate()

    def test_proactive_scheduler_enabled_with_positive_interval_passes(self):
        """Valid combination."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            proactive_scheduler_enabled=True,
            proactive_scheduler_interval_seconds=900.0,
        )
        config.validate()

    # ---------- voice_enabled × vapi_api_key ----------

    def test_voice_enabled_requires_vapi_api_key(self):
        """voice_enabled = true + empty vapi_api_key = fail.

        NOTE: PR #1681 adds an adjacent fail-closed check for
        `vapi_webhook_secret` in APIServer.start() — that's a *different*
        field (inbound webhook auth vs outbound API auth). Both checks
        coexist once #1681 merges; an operator enabling voice needs to
        satisfy both.
        """
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            voice_enabled=True,
            vapi_api_key="",
        )
        with pytest.raises(
            ConfigError,
            match=r"voice_enabled.*vapi_api_key",
        ):
            config.validate()

    def test_voice_enabled_with_whitespace_only_vapi_key_fails(self):
        """Whitespace-only is treated as empty."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            voice_enabled=True,
            vapi_api_key="   ",
        )
        with pytest.raises(ConfigError, match=r"vapi_api_key"):
            config.validate()

    def test_voice_disabled_with_empty_vapi_key_passes(self):
        """Disabled voice tolerates empty vapi_api_key (the default state)."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            voice_enabled=False,
            vapi_api_key="",
        )
        config.validate()

    def test_voice_enabled_with_vapi_key_passes(self):
        """Valid combination."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            voice_enabled=True,
            vapi_api_key="vapi-test-key",
        )
        config.validate()

    # ---------- e2b_executor_enabled × e2b_api_key ----------

    def test_e2b_executor_enabled_defaults_false(self):
        """E2B executor activation must remain opt-in."""
        config = BridgeConfig()
        assert config.e2b_executor_enabled is False

    def test_e2b_executor_enabled_requires_e2b_api_key(self):
        """E2B executor flag + empty credential = fail closed."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            e2b_executor_enabled=True,
            e2b_api_key="",
        )
        with pytest.raises(
            ConfigError,
            match=r"e2b_executor_enabled.*e2b_api_key",
        ):
            config.validate()

    def test_e2b_executor_disabled_with_empty_key_passes(self):
        """Disabled E2B executor tolerates empty e2b_api_key."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            e2b_executor_enabled=False,
            e2b_api_key="",
        )
        config.validate()

    def test_e2b_executor_enabled_with_key_passes_config_validation(self):
        """The flag/key pair may validate before sandbox lifecycle is live."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            e2b_executor_enabled=True,
            e2b_api_key="e2b-test-key",
        )
        config.validate()

    # ---------- api_enabled × api_port ----------

    @pytest.mark.parametrize("bad_port", [0, -1, 65536, 100000])
    def test_api_enabled_requires_valid_port(self, bad_port):
        """api_port outside [1, 65535] with api_enabled = fail."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            api_enabled=True,
            api_port=bad_port,
        )
        with pytest.raises(ConfigError, match=r"api_enabled.*api_port"):
            config.validate()

    def test_api_disabled_with_invalid_port_passes(self):
        """Disabled API tolerates an out-of-range port (knob is dormant)."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            api_enabled=False,
            api_port=0,
        )
        config.validate()

    def test_api_enabled_with_valid_port_passes(self):
        """Valid combination."""
        from dataclasses import replace
        config = replace(
            BridgeConfig(),
            api_enabled=True,
            api_port=8200,
        )
        config.validate()

    # ---------- budget_daily_budget non-negative ----------

    @pytest.mark.parametrize("bad_value", [-0.01, -1.0, -100.0])
    def test_budget_daily_budget_negative_fails(self, bad_value):
        """Negative daily budget = fail."""
        from dataclasses import replace
        config = replace(BridgeConfig(), budget_daily_budget=bad_value)
        with pytest.raises(ConfigError, match=r"budget_daily_budget.*>= 0"):
            config.validate()

    def test_budget_daily_budget_zero_passes(self):
        """0.0 means "no cap" — the default state."""
        from dataclasses import replace
        config = replace(BridgeConfig(), budget_daily_budget=0.0)
        config.validate()

    def test_budget_daily_budget_positive_passes(self):
        """Valid positive budget."""
        from dataclasses import replace
        config = replace(BridgeConfig(), budget_daily_budget=5.0)
        config.validate()

    # ---------- default config passes ----------

    def test_default_config_passes_validate(self):
        """Stock BridgeConfig() defaults must satisfy every invariant —
        otherwise the bridge couldn't boot from a fresh install."""
        BridgeConfig().validate()

    # ---------- wiring into _validate ----------

    def test_validate_runs_via_underscore_validate(self, tmp_path):
        """``_validate(config)`` must invoke ``config.validate()`` so the
        startup pipeline catches cross-field invariants too. Pin this
        wiring — a regression that drops the delegation would silently
        re-introduce the gap #1541 was opened to close."""
        from dataclasses import replace
        # Construct a config that passes every single-field check in
        # ``_validate`` but fails a cross-field invariant.
        config = replace(
            BridgeConfig(),
            discord_bot_token="test-token",
            operator_discord_id="test-operator",
            # Sprint audit-2026-05-16.B.03 (#2052) — _validate now refuses to
            # boot on empty claude_oauth_token; supply a stub so the test can
            # reach the chief_dispatcher cross-field invariant under test.
            claude_oauth_token="sk-ant-test-token",
            data_dir=str(tmp_path),
            log_dir=str(tmp_path),
            # Sprint audit-2026-05-16.B.04 (#2053) — _validate now refuses
            # to boot on empty api_token / github_webhook_secret when
            # api_enabled=True (default); supply stubs so the test can
            # reach the chief_dispatcher cross-field invariant under test.
            api_token="test-api-token",
            github_webhook_secret="test-gh-webhook-secret",
            chief_dispatcher_enabled=True,
            chief_dispatcher_default_department="",
        )
        with pytest.raises(
            ConfigError,
            match=r"chief_dispatcher_default_department",
        ):
            _validate(config)


class TestResponseEvaluatorEnabledFlag:
    """Issue #1565 — operator opt-out for ResponseEvaluator.

    Default ``True`` preserves current behaviour (per-response evaluator call
    runs as it does today). Operators set ``[evaluator] enabled = false`` in
    ``bridge.toml`` to skip the call entirely. Sibling knob to
    ``[verification] policy`` — both gate adversarial quality scoring.
    """

    def test_default_is_true(self):
        """Default-constructed BridgeConfig has the flag ON, preserving
        pre-#1565 behaviour."""
        config = BridgeConfig()
        assert config.response_evaluator_enabled is True

    def test_toml_mapping_can_disable(self, tmp_path):
        """``[evaluator] enabled = false`` flips the field to False."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[evaluator]\n'
            'enabled = false\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.response_evaluator_enabled is False

    def test_toml_mapping_can_explicitly_enable(self, tmp_path):
        """``[evaluator] enabled = true`` is the explicit form of the default."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[evaluator]\n'
            'enabled = true\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.response_evaluator_enabled is True

    def test_omitted_from_toml_keeps_default(self, tmp_path):
        """Omitting the ``[evaluator]`` section entirely keeps the default
        True — back-compat with every existing bridge.toml."""
        toml = tmp_path / "bridge.toml"
        toml.write_text('# no [evaluator] section\n')
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.response_evaluator_enabled is True


class TestExperimentMode:
    """Sprint audit-2026-05-15.B.01 (#1996): experiment_mode field."""

    def test_default_mode_is_shadow(self):
        """A default-constructed BridgeConfig has experiment_mode='shadow'."""
        config = BridgeConfig()
        assert config.experiment_mode == "shadow"

    def test_toml_override_to_production(self, tmp_path):
        """``[experiment_loop] mode = "production"`` lands on the attribute."""
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[experiment_loop]\n'
            'mode = "production"\n'
        )
        config = load_config(toml, skip_secrets=True, skip_validation=True)
        assert config.experiment_mode == "production"

    def test_invalid_mode_raises_config_error(self):
        """_validate fails closed on an unknown experiment_mode value."""
        config = BridgeConfig(
            discord_bot_token="MTIzNDU2.FAKE-TOKEN.x",
            operator_discord_id="7565124764",
            experiment_mode="bogus",
        )
        with pytest.raises(ConfigError, match="experiment_loop.mode"):
            _validate(config)


class TestRequirePrivateFile:
    """Sprint audit-2026-05-16.B.01 (#2050, HI-1): canonical secrets file
    permissions are enforced at load time. `_load_secrets_file` refuses to
    read a `.secrets` whose mode is group/world readable. The error names
    the path and the remediation command but never surfaces file contents.
    """

    def test_mode_0600_passes(self, tmp_path):
        path = tmp_path / ".secrets"
        path.write_text("discord_token=fake\n")
        path.chmod(0o600)
        # No exception expected.
        _require_private_file(path, purpose="test")

    def test_mode_0644_raises_config_error(self, tmp_path):
        path = tmp_path / ".secrets"
        path.write_text("discord_token=fake\n")
        path.chmod(0o644)
        with pytest.raises(ConfigError) as exc_info:
            _require_private_file(path, purpose="test")
        msg = str(exc_info.value)
        assert str(path) in msg
        assert "chmod 600" in msg

    def test_mode_0660_raises_config_error(self, tmp_path):
        path = tmp_path / ".secrets"
        path.write_text("discord_token=fake\n")
        path.chmod(0o660)
        with pytest.raises(ConfigError):
            _require_private_file(path, purpose="test")

    def test_mode_0400_passes(self, tmp_path):
        path = tmp_path / ".secrets"
        path.write_text("discord_token=fake\n")
        path.chmod(0o400)
        # No exception expected — read-only owner is acceptable.
        _require_private_file(path, purpose="test")

    def test_missing_file_does_not_raise(self, tmp_path):
        path = tmp_path / "does-not-exist"
        # No exception expected — caller handles missing-file fallback.
        _require_private_file(path, purpose="test")

    def test_error_message_excludes_file_contents(self, tmp_path):
        path = tmp_path / ".secrets"
        path.write_text("SECRET=topsecretvalue\n")
        path.chmod(0o644)
        with pytest.raises(ConfigError) as exc_info:
            _require_private_file(path, purpose="test")
        assert "topsecretvalue" not in str(exc_info.value)

    def test_load_secrets_file_rejects_world_readable(self, tmp_path):
        """Integration: `_load_secrets_file` itself surfaces the perm error."""
        path = tmp_path / ".secrets"
        path.write_text("discord_token=fake\n")
        path.chmod(0o644)
        with pytest.raises(ConfigError) as exc_info:
            _load_secrets_file(str(path))
        assert "chmod 600" in str(exc_info.value)


class TestRuntimeSecrets:
    """Sprint audit-2026-05-16.B.02 (#2051, M-1): RuntimeSecrets helper.

    Collapses four duplicate ``.secrets`` readers into one canonical parse
    + typed accessor surface. Tests pin the public API contract so the
    four delegating call sites
    (``_load_secrets_file``, ``_load_secrets_as_env``, ``_read_secrets``,
    ``_get_notion_db_id``) stay behaviour-preserving.
    """

    def _write_secrets(self, tmp_path, body: str, mode: int = 0o600):
        path = tmp_path / ".secrets"
        path.write_text(body)
        path.chmod(mode)
        return path

    def test_load_returns_parsed_dict(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(
            tmp_path,
            "discord_token=abc\nbumba_notion_job_db_id=xyz\n",
        )
        rs = RuntimeSecrets(secrets_path=path)
        parsed = rs.as_dict()
        assert parsed == {"discord_token": "abc", "bumba_notion_job_db_id": "xyz"}

    def test_load_returns_empty_on_missing_file(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        rs = RuntimeSecrets(secrets_path=tmp_path / "missing.secrets")
        assert rs.as_dict() == {}

    def test_rejects_world_readable(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "k=v\n", mode=0o644)
        rs = RuntimeSecrets(secrets_path=path)
        with pytest.raises(ConfigError) as exc_info:
            rs.as_dict()
        assert "chmod 600" in str(exc_info.value)

    def test_enforce_permissions_false_tolerates_loose_mode(self, tmp_path):
        """Opt-out flag preserves pre-B.02 contract for experiment loop / job search."""
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "k=v\n", mode=0o644)
        rs = RuntimeSecrets(secrets_path=path, enforce_permissions=False)
        # No exception expected — soft-fail readers preserve their pre-B.02
        # behaviour even on a permission anomaly.
        assert rs.as_dict() == {"k": "v"}

    def test_claude_oauth_token_required_raises_when_missing(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "other_key=other_val\n")
        rs = RuntimeSecrets(secrets_path=path)
        with pytest.raises(ConfigError) as exc_info:
            rs.claude_oauth_token(required=True)
        assert "claude_oauth_token" in str(exc_info.value)

    def test_claude_oauth_token_required_falls_back_to_legacy_file(self, tmp_path):
        """Preserves experiment_loop's deprecation-fallback contract (#1991)."""
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "# no token here\n")
        legacy = tmp_path / ".claude-token"
        legacy.write_text("fallback-token-from-legacy-cache")

        rs = RuntimeSecrets(secrets_path=path)
        # required=False: still gets the fallback (mirrors loop's contract).
        assert rs.claude_oauth_token(required=False) == "fallback-token-from-legacy-cache"

    def test_claude_oauth_token_primary_wins_over_legacy(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "claude_oauth_token=primary\n")
        legacy = tmp_path / ".claude-token"
        legacy.write_text("legacy-should-not-be-used")

        rs = RuntimeSecrets(secrets_path=path)
        assert rs.claude_oauth_token() == "primary"

    def test_caches_on_first_load(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "k=v1\n")
        rs = RuntimeSecrets(secrets_path=path)
        assert rs.as_dict() == {"k": "v1"}

        # Mutate the underlying file — cached read should NOT pick it up.
        path.write_text("k=v2\n")
        path.chmod(0o600)
        assert rs.as_dict() == {"k": "v1"}

    def test_reload_clears_cache(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "k=v1\n")
        rs = RuntimeSecrets(secrets_path=path)
        assert rs.as_dict() == {"k": "v1"}

        path.write_text("k=v2\n")
        path.chmod(0o600)
        rs.reload()
        assert rs.as_dict() == {"k": "v2"}

    def test_as_env_dict_excludes_anthropic_api_key(self, tmp_path):
        """CRITICAL regression guard from claude_runner._load_secrets_as_env."""
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(
            tmp_path,
            "ANTHROPIC_API_KEY=sk-test-123\nNOTION_TOKEN=abc\n",
        )
        rs = RuntimeSecrets(secrets_path=path)
        env = rs.as_env_dict()
        assert "ANTHROPIC_API_KEY" not in env
        assert env["NOTION_TOKEN"] == "abc"

    def test_get_required_raises_with_key_name(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "other=val\n")
        rs = RuntimeSecrets(secrets_path=path)
        with pytest.raises(ConfigError) as exc_info:
            rs.get("missing_key", required=True)
        assert "missing_key" in str(exc_info.value)

    def test_claude_oauth_expires_at_int_parse(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "claude_oauth_expires_at=1730000000\n")
        rs = RuntimeSecrets(secrets_path=path)
        assert rs.claude_oauth_expires_at() == 1730000000

    def test_claude_oauth_expires_at_returns_none_on_bogus(self, tmp_path):
        """Mirrors the silent-skip behaviour from the legacy config.py loader."""
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "claude_oauth_expires_at=not-an-int\n")
        rs = RuntimeSecrets(secrets_path=path)
        assert rs.claude_oauth_expires_at() is None

    def test_notion_db_id_typed_accessor(self, tmp_path):
        from bridge.runtime_secrets import RuntimeSecrets

        path = self._write_secrets(tmp_path, "bumba_notion_job_db_id=abc-123\n")
        rs = RuntimeSecrets(secrets_path=path)
        assert rs.notion_db_id() == "abc-123"

    def test_legacy_load_secrets_file_still_returns_dict(self, tmp_path):
        """Regression: existing callers of `_load_secrets_file` get the same shape."""
        path = self._write_secrets(
            tmp_path,
            "discord_token=fake\noperator_id=12345\ne2b_api_key=e2b-secret\n",
        )
        result = _load_secrets_file(str(path))
        # Aliases resolved as before: discord_token → discord_bot_token, etc.
        assert result["discord_bot_token"] == "fake"
        assert result["operator_discord_id"] == "12345"
        assert result["e2b_api_key"] == "e2b-secret"

    def test_legacy_load_secrets_as_env_still_returns_dict(self, tmp_path):
        """Regression: claude_runner._load_secrets_as_env contract preserved."""
        from bridge.claude_runner import _load_secrets_as_env

        path = self._write_secrets(tmp_path, "MY_VAR=hello\nOTHER=world\n")
        # _load_secrets_as_env takes a data_dir, not the secrets path.
        env = _load_secrets_as_env(str(tmp_path))
        assert env["MY_VAR"] == "hello"
        assert env["OTHER"] == "world"

    def test_get_runtime_secrets_returns_singleton(self):
        from bridge.runtime_secrets import get_runtime_secrets

        a = get_runtime_secrets()
        b = get_runtime_secrets()
        assert a is b


def test_required_boot_secret_key_constants_match_validation_contract() -> None:
    from bridge import config as config_mod

    assert config_mod.REQUIRED_BOOT_SECRET_KEYS == ("claude_oauth_token",)
    assert config_mod.API_ENABLED_REQUIRED_SECRET_KEYS == (
        "api_token",
        "github_webhook_secret",
    )


def test_mock_keyring_injects_every_required_boot_secret(mock_keyring, tmp_path) -> None:
    from bridge import config as config_mod

    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text("", encoding="utf-8")
    secrets_file.chmod(0o600)

    secrets = config_mod._load_secrets(secrets_file=str(secrets_file))
    required = (
        config_mod.REQUIRED_BOOT_SECRET_KEYS
        + config_mod.API_ENABLED_REQUIRED_SECRET_KEYS
    )

    assert all(secrets.get(key) for key in required)


class TestClaudeOAuthBootRequirement:
    """Sprint audit-2026-05-16.B.03 (#2052, HI-5) — Claude OAuth fail-closed.

    Two validation seams ensure the bridge refuses to boot with an empty
    ``claude_oauth_token``:

      1. ``config._validate`` — fires during ``load_config`` (early surface).
      2. ``app._validate_claude_oauth_required`` — fires during boot
         ``BridgeApp._initialize`` (late surface, mirrors ``_validate_codex_oauth``).
    """

    def _make_base_config(self, tmp_path, **overrides) -> BridgeConfig:
        """Build a BridgeConfig that satisfies all checks except the OAuth one.

        Mirrors the ``base_config_kwargs`` fixture used elsewhere in this file
        (discord/operator tokens + real directories for path checks). The OAuth
        token is supplied by default; tests targeting the empty-token failure
        mode override it explicitly.
        """
        defaults: dict[str, object] = {
            "discord_bot_token": "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.FAKE.abcdef",
            "operator_discord_id": "7565124764",
            "claude_oauth_token": "sk-ant-test-token",
            "api_token": "test-api-token",  # B.04 fires alongside B.03
            "github_webhook_secret": "test-gh-webhook-secret",  # B.04
            "data_dir": str(tmp_path),
            "log_dir": str(tmp_path),
        }
        defaults.update(overrides)
        return BridgeConfig(**defaults)

    def test_config_validation_rejects_empty_claude_oauth_token(self, tmp_path):
        """``_validate`` raises ConfigError when claude_oauth_token is empty."""
        config = self._make_base_config(tmp_path, claude_oauth_token="")
        with pytest.raises(ConfigError, match="claude_oauth_token"):
            _validate(config)

    def test_config_validation_passes_with_claude_oauth_token(self, tmp_path):
        """``_validate`` returns normally when claude_oauth_token is set."""
        config = self._make_base_config(
            tmp_path, claude_oauth_token="sk-ant-real-token"
        )
        _validate(config)  # must not raise

    def test_config_validation_allows_openrouter_only_without_claude_token(
        self, tmp_path
    ):
        """OpenRouter-only config validation does not require Claude OAuth."""
        config = self._make_base_config(
            tmp_path,
            claude_oauth_token="",
            openrouter_api_key="sk-or-test",
            backends_enabled=True,
            backends_main="openrouter",
            backends_chiefs_default="openrouter",
            backends_specialists_default="openrouter",
            backends_specialists_overrides={},
        )
        _validate(config)  # must not raise

    def test_config_validation_requires_openrouter_key_when_active(
        self, tmp_path
    ):
        """OpenRouter-routed configs fail early without an API key."""
        config = self._make_base_config(
            tmp_path,
            openrouter_api_key="",
            backends_enabled=True,
            backends_main="openrouter",
            backends_chiefs_default="claude",
            backends_specialists_default="claude",
            backends_specialists_overrides={},
        )
        with pytest.raises(ConfigError, match="openrouter_api_key"):
            _validate(config)

    def test_load_config_accepts_openrouter_only_staging_without_claude_token(
        self, tmp_path, sample_config_toml
    ):
        """Staging bridge.toml + secrets can boot OpenRouter without Claude OAuth."""
        staging_toml = tmp_path / "openrouter-staging.toml"
        staging_toml.write_text(
            sample_config_toml.read_text()
            + """

[backends]
enabled = true
main = "openrouter"
chiefs_default = "openrouter"
specialists_default = "openrouter"
specialists_overrides = {}

[openrouter]
default_model = "z-ai/glm-4.6"
"""
        )
        secrets = {
            "discord_bot_token": "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.FAKE.abcdef",
            "operator_discord_id": "7565124764",
            "api_token": "test-api-token",
            "github_webhook_secret": "test-gh-webhook-secret",
            "openrouter_api_key": "REPLACE_WITH_OPENROUTER_KEY",
        }

        with patch("bridge.config._load_secrets", return_value=secrets):
            config = load_config(staging_toml)

        assert config.backends_enabled is True
        assert config.backends_main == "openrouter"
        assert config.backends_chiefs_default == "openrouter"
        assert config.backends_specialists_default == "openrouter"
        assert config.openrouter_default_model == "z-ai/glm-4.6"
        assert config.openrouter_api_key == "REPLACE_WITH_OPENROUTER_KEY"
        assert config.claude_oauth_token == ""

    def test_load_config_rejects_openrouter_staging_without_key(
        self, tmp_path, sample_config_toml
    ):
        """OpenRouter staging config fails at load time when the key is absent."""
        staging_toml = tmp_path / "openrouter-staging.toml"
        staging_toml.write_text(
            sample_config_toml.read_text()
            + """

[backends]
enabled = true
main = "openrouter"
chiefs_default = "openrouter"
specialists_default = "openrouter"
specialists_overrides = {}

[openrouter]
default_model = "z-ai/glm-4.6"
"""
        )
        secrets = {
            "discord_bot_token": "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.FAKE.abcdef",
            "operator_discord_id": "7565124764",
            "api_token": "test-api-token",
            "github_webhook_secret": "test-gh-webhook-secret",
        }

        with patch("bridge.config._load_secrets", return_value=secrets):
            with pytest.raises(ConfigError, match="openrouter_api_key"):
                load_config(staging_toml)

    def test_validate_claude_oauth_required_passes_when_token_set(self, tmp_path):
        """Boot-time validator is a no-op when the OAuth token is non-empty."""
        from bridge.app import _validate_claude_oauth_required

        config = self._make_base_config(
            tmp_path, claude_oauth_token="sk-ant-real-token"
        )
        _validate_claude_oauth_required(config)  # must not raise

    def test_validate_claude_oauth_required_raises_when_token_empty(self, tmp_path):
        """Boot-time validator raises RuntimeError on empty OAuth token."""
        from bridge.app import _validate_claude_oauth_required

        config = self._make_base_config(tmp_path, claude_oauth_token="")
        with pytest.raises(RuntimeError) as exc_info:
            _validate_claude_oauth_required(config)
        msg = str(exc_info.value)
        assert "claude_oauth_token" in msg
        assert ".secrets" in msg

    def test_validate_claude_oauth_required_allows_openrouter_only_without_token(
        self, tmp_path
    ):
        """OpenRouter-only boot does not require dormant Claude credentials."""
        from bridge.app import _validate_claude_oauth_required

        config = self._make_base_config(
            tmp_path,
            claude_oauth_token="",
            openrouter_api_key="sk-or-test",
            backends_enabled=True,
            backends_main="openrouter",
            backends_chiefs_default="openrouter",
            backends_specialists_default="openrouter",
            backends_specialists_overrides={},
        )
        _validate_claude_oauth_required(config)  # must not raise

    def test_validate_openrouter_api_key_required_raises_when_active_without_key(
        self, tmp_path
    ):
        """Boot-time validator rejects OpenRouter routing without a key."""
        from bridge.app import _validate_openrouter_api_key_required

        config = self._make_base_config(
            tmp_path,
            openrouter_api_key="",
            backends_enabled=True,
            backends_main="openrouter",
            backends_chiefs_default="claude",
            backends_specialists_default="claude",
            backends_specialists_overrides={},
        )
        with pytest.raises(RuntimeError, match="openrouter_api_key"):
            _validate_openrouter_api_key_required(config)

    def test_validate_openrouter_api_key_required_passes_when_key_set(
        self, tmp_path
    ):
        """Boot-time validator accepts OpenRouter routing with a key."""
        from bridge.app import _validate_openrouter_api_key_required

        config = self._make_base_config(
            tmp_path,
            openrouter_api_key="sk-or-test",
            backends_enabled=True,
            backends_main="openrouter",
            backends_chiefs_default="claude",
            backends_specialists_default="claude",
            backends_specialists_overrides={},
        )
        _validate_openrouter_api_key_required(config)  # must not raise


class TestApiSecretsBootRequirement:
    """Sprint audit-2026-05-16.B.04 (#2053, M-3) — API auth + GitHub webhook
    fail-closed when ``api_enabled = true``.

    Pre-B.04 the bridge would boot with an empty ``api_token`` and accept
    bearer-token requests with empty tokens, and would boot with an empty
    ``github_webhook_secret`` and accept unsigned GitHub callbacks. The fix
    is two paired ``_validate`` checks (early surface during ``load_config``)
    plus paired boot-time validators in ``APIServer.start`` (late surface,
    covered by ``test_api_server.py``).

    Tests below exercise the ``_validate`` seam directly via the helper
    ``_make_valid_config`` so they isolate the new invariant from path /
    Keychain / TOML loading.
    """

    def _make_valid_config(self, tmp_path, **overrides) -> BridgeConfig:
        """Build a BridgeConfig that satisfies all ``_validate`` checks.

        Mirrors the helper patterns in ``TestClaudeHardTimeoutStrictInequality``
        and ``TestSprintB03`` (B.03 sibling sprint). Defaults satisfy the
        new B.04 invariants so tests targeting the empty-secret failure
        mode override them explicitly.
        """
        from dataclasses import replace
        defaults: dict[str, object] = {
            "discord_bot_token": "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.FAKE.abcdef",
            "operator_discord_id": "7565124764",
            "claude_oauth_token": "sk-ant-test-token",  # B.03 fires before B.04
            "data_dir": str(tmp_path),
            "log_dir": str(tmp_path),
            "api_enabled": True,
            "api_token": "test-api-token",
            "github_webhook_secret": "test-gh-webhook-secret",
        }
        defaults.update(overrides)
        return replace(BridgeConfig(), **defaults)

    def test_validate_rejects_empty_api_token_when_enabled(self, tmp_path):
        """api_enabled=True + empty api_token raises ConfigError."""
        config = self._make_valid_config(tmp_path, api_token="")
        with pytest.raises(ConfigError, match=r"api_token"):
            _validate(config)

    def test_validate_rejects_empty_github_webhook_secret_when_enabled(
        self, tmp_path
    ):
        """api_enabled=True + empty github_webhook_secret raises ConfigError."""
        config = self._make_valid_config(tmp_path, github_webhook_secret="")
        with pytest.raises(ConfigError, match=r"github_webhook_secret"):
            _validate(config)

    def test_validate_passes_with_both_secrets(self, tmp_path):
        """Both secrets present + api_enabled=True passes."""
        config = self._make_valid_config(tmp_path)
        # Must not raise.
        _validate(config)

    def test_validate_passes_when_api_disabled(self, tmp_path):
        """api_enabled=False tolerates both secrets being empty."""
        config = self._make_valid_config(
            tmp_path,
            api_enabled=False,
            api_token="",
            github_webhook_secret="",
        )
        # Must not raise — the gate is api_enabled, not the secret presence.
        _validate(config)


class TestValidatorReadinessContract:
    """Sprint audit-2026-05-16.E.03 (#2071, Section 8.1) — holdout validator
    readiness contract.

    The experiment-loop validator can flip ``status="discard"`` on a
    REGRESSION or NOISE verdict, so enabling it without bounded cost,
    timeout, and minimum-signal requirements would let it silently kill
    iterations. ``_validate`` enforces that flipping
    ``experiment_validator_enabled = true`` requires all four backing
    fields (cost_cap_usd, model, timeout_seconds, min_signals) to be set
    to positive/non-empty values.

    The two new bounding fields (``experiment_validator_timeout_seconds``
    and ``experiment_validator_min_signals``) default to 0 so the
    enabled=False default posture preserves the
    ``test_default_config_passes_validate`` contract. Mirrors the B.03 /
    B.04 fail-closed-at-load pattern.
    """

    def _make_valid_config(self, tmp_path, **overrides) -> BridgeConfig:
        """Build a BridgeConfig that satisfies all ``_validate`` checks
        including the B.03 / B.04 invariants. Tests targeting the
        readiness-contract failure modes override validator fields
        explicitly.
        """
        from dataclasses import replace
        defaults: dict[str, object] = {
            "discord_bot_token": "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.FAKE.abcdef",
            "operator_discord_id": "7565124764",
            "claude_oauth_token": "sk-ant-test-token",  # B.03
            "api_token": "test-api-token",  # B.04
            "github_webhook_secret": "test-gh-webhook-secret",  # B.04
            "data_dir": str(tmp_path),
            "log_dir": str(tmp_path),
        }
        defaults.update(overrides)
        return replace(BridgeConfig(), **defaults)

    def test_validator_disabled_tolerates_empty_bounds(self, tmp_path):
        """enabled=False + all four bounding fields zero/empty passes."""
        config = self._make_valid_config(
            tmp_path,
            experiment_validator_enabled=False,
            experiment_validator_cost_cap_usd=0.0,
            experiment_validator_model="",
            experiment_validator_timeout_seconds=0,
            experiment_validator_min_signals=0,
        )
        # Must not raise — the gate is enabled, not the bound presence.
        _validate(config)

    def test_validator_enabled_requires_cost_cap(self, tmp_path):
        """enabled=True + cost_cap=0 raises ConfigError mentioning cost_cap."""
        config = self._make_valid_config(
            tmp_path,
            experiment_validator_enabled=True,
            experiment_validator_cost_cap_usd=0.0,
            experiment_validator_model="haiku",
            experiment_validator_timeout_seconds=60,
            experiment_validator_min_signals=1,
        )
        with pytest.raises(ConfigError, match=r"cost_cap"):
            _validate(config)

    def test_validator_enabled_rejects_negative_cost_cap(self, tmp_path):
        """enabled=True + cost_cap<0 raises ConfigError mentioning cost_cap."""
        config = self._make_valid_config(
            tmp_path,
            experiment_validator_enabled=True,
            experiment_validator_cost_cap_usd=-0.1,
            experiment_validator_model="haiku",
            experiment_validator_timeout_seconds=60,
            experiment_validator_min_signals=1,
        )
        with pytest.raises(ConfigError, match=r"cost_cap"):
            _validate(config)

    def test_validator_enabled_requires_model(self, tmp_path):
        """enabled=True + empty model raises ConfigError mentioning model."""
        config = self._make_valid_config(
            tmp_path,
            experiment_validator_enabled=True,
            experiment_validator_cost_cap_usd=0.30,
            experiment_validator_model="",
            experiment_validator_timeout_seconds=60,
            experiment_validator_min_signals=1,
        )
        with pytest.raises(ConfigError, match=r"model"):
            _validate(config)

    def test_validator_enabled_requires_timeout(self, tmp_path):
        """enabled=True + timeout=0 raises ConfigError mentioning timeout."""
        config = self._make_valid_config(
            tmp_path,
            experiment_validator_enabled=True,
            experiment_validator_cost_cap_usd=0.30,
            experiment_validator_model="haiku",
            experiment_validator_timeout_seconds=0,
            experiment_validator_min_signals=1,
        )
        with pytest.raises(ConfigError, match=r"timeout"):
            _validate(config)

    def test_validator_enabled_rejects_negative_timeout(self, tmp_path):
        """enabled=True + timeout<0 raises ConfigError mentioning timeout."""
        config = self._make_valid_config(
            tmp_path,
            experiment_validator_enabled=True,
            experiment_validator_cost_cap_usd=0.30,
            experiment_validator_model="haiku",
            experiment_validator_timeout_seconds=-5,
            experiment_validator_min_signals=1,
        )
        with pytest.raises(ConfigError, match=r"timeout"):
            _validate(config)

    def test_validator_enabled_requires_min_signals(self, tmp_path):
        """enabled=True + min_signals=0 raises ConfigError mentioning min_signals."""
        config = self._make_valid_config(
            tmp_path,
            experiment_validator_enabled=True,
            experiment_validator_cost_cap_usd=0.30,
            experiment_validator_model="haiku",
            experiment_validator_timeout_seconds=60,
            experiment_validator_min_signals=0,
        )
        with pytest.raises(ConfigError, match=r"min_signals"):
            _validate(config)

    def test_validator_enabled_passes_with_all_four_bounds(self, tmp_path):
        """enabled=True + all four bounds positive/non-empty passes."""
        config = self._make_valid_config(
            tmp_path,
            experiment_validator_enabled=True,
            experiment_validator_cost_cap_usd=0.30,
            experiment_validator_model="haiku",
            experiment_validator_timeout_seconds=60,
            experiment_validator_min_signals=1,
        )
        # Must not raise — all four bounds satisfied.
        _validate(config)

    def test_validator_default_config_passes_validate(self, tmp_path):
        """Regression guard: BridgeConfig defaults (validator disabled,
        timeout=0, min_signals=0) must still satisfy ``_validate``.

        Mirrors the ``test_default_config_passes_validate`` contract that
        B.03 / B.04 honored — defaults must be loadable so dataclass tests
        using ``replace(BridgeConfig(), ...)`` keep working.
        """
        config = self._make_valid_config(tmp_path)
        # No validator overrides — fields are at their factory defaults
        # (enabled=False, timeout=0, signals=0). Must not raise.
        _validate(config)
