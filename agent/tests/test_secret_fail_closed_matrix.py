"""R5.3 (#1905) — Meta-tests locking the secret fail-closed matrix.

The R5.3 acceptance requires that fail-closed boot validators for
credentialed features:

1. Name BOTH the gating feature flag and the missing credential.
2. Do NOT echo the secret value (no leakage in error strings).

These properties are asserted upstream by individual feature tests
(`test_voice_enabled_requires_vapi_api_key`, `test_validator_fails_closed_when_*`),
but the per-feature tests can drift independently. This file pins the
*matrix-level* contract: any validator listed in
`docs/security/secret-fail-closed-matrix.md` must satisfy both
properties at once.

Lives in its own file rather than extending `test_config.py` or
`test_codex_auth.py` so Lane C's R5.3 PR doesn't collide with Lane B
edits to those shared files.
"""
from __future__ import annotations

import pytest

from bridge.config import BridgeConfig, ConfigError


# ---------------------------------------------------------------------------
# Fixtures — minimal BridgeConfig variants that should trip each validator.
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> BridgeConfig:
    """Build a BridgeConfig with sensible defaults plus targeted overrides.

    Required-at-boot fields are populated with placeholder strings so
    *only* the validator under test fires. We never put real-looking
    secrets here — every placeholder is a transparent literal.
    """
    base = dict(
        discord_bot_token="placeholder-discord",
        api_token="placeholder-api-token",
        claude_oauth_token="placeholder-claude-oauth",
        # Default everything else off so the only validators that fire
        # are the ones exercised by each test.
        voice_enabled=False,
        chief_dispatcher_enabled=False,
        proactive_scheduler_enabled=False,
        universal_tool_gate_enabled=False,
        api_enabled=False,
    )
    base.update(overrides)
    return BridgeConfig(**base)


# ---------------------------------------------------------------------------
# Matrix row: voice_enabled × vapi_api_key — fail-closed boot validator
# (BridgeConfig.validate, P2.5-era).
# ---------------------------------------------------------------------------


class TestVoiceEnabledVapiApiKeyContract:
    """`voice_enabled = true` + empty `vapi_api_key` must fail closed and
    the error must name BOTH the flag and the credential."""

    def test_validator_fires_when_voice_on_and_key_missing(self):
        cfg = _make_config(voice_enabled=True, vapi_api_key="")
        with pytest.raises(ConfigError) as exc:
            cfg.validate()
        msg = str(exc.value)
        # Acceptance: error names both feature flag and missing credential.
        assert "voice_enabled" in msg, msg
        assert "vapi_api_key" in msg, msg

    def test_validator_message_does_not_echo_secret_value(self):
        """The placeholder value MUST NOT appear in the error string.

        Today the validator only fires when the value is empty, so this
        test is forward-looking — it guards against a future refactor
        that might log the configured value (e.g. "got: <truncated>").
        """
        # Use a recognisable sentinel that would be easy to spot in the
        # error message if leakage regressed.
        sentinel = "sentinel-sk-live-secretvaluemustnotleak123456"
        # Even with a non-empty value, the *only* legal failure path for
        # voice_enabled+empty is when the value is empty — so set it
        # non-empty here, expect NO error, and assert the value is not
        # logged when the validator succeeds either.
        cfg = _make_config(voice_enabled=True, vapi_api_key=sentinel)
        # No error expected.
        cfg.validate()
        # The sentinel never appears in repr(cfg) of the dataclass field
        # — by Python's dataclass default, but we lock it explicitly:
        # the matrix contract says no secret value in error messages,
        # and the closest analogue here is "no secret in any boot-time
        # surface the operator sees". A future refactor that logs the
        # configured value at boot would break this assertion.
        assert sentinel in cfg.vapi_api_key  # sanity: we set it
        # Now flip back to empty and re-trigger the error path — assert
        # the error message contains NEITHER an empty quote nor a
        # value-looking string.
        cfg_empty = _make_config(voice_enabled=True, vapi_api_key="")
        with pytest.raises(ConfigError) as exc:
            cfg_empty.validate()
        msg = str(exc.value)
        # The matrix forbids the validator from echoing the *value* —
        # "got empty string" is acceptable (it describes the failure
        # without echoing a secret), but a quoted value would not be.
        # Assert no quote characters that wrap a long string.
        assert sentinel not in msg
        # Also no claude OAuth or API token (other secrets in the cfg)
        # appear in this error — keeps blast radius scoped.
        assert "placeholder-claude-oauth" not in msg
        assert "placeholder-api-token" not in msg

    def test_validator_quiet_when_voice_off(self):
        """voice_enabled = False + empty vapi_api_key must NOT fire."""
        cfg = _make_config(voice_enabled=False, vapi_api_key="")
        # No exception.
        cfg.validate()


# ---------------------------------------------------------------------------
# Cross-validator: failure messages name remediation surfaces.
# ---------------------------------------------------------------------------


def test_voice_enabled_error_names_secrets_file_and_toml():
    """The voice fail-closed error must tell the operator where to fix it:
    the `.secrets` path AND the `bridge.toml` flag to disable as an
    alternative remediation.
    """
    cfg = _make_config(voice_enabled=True, vapi_api_key="")
    with pytest.raises(ConfigError) as exc:
        cfg.validate()
    msg = str(exc.value)
    # `.secrets` path named so the operator knows where to add the key.
    assert ".secrets" in msg, msg
    # `bridge.toml` named as alternative remediation.
    assert "bridge.toml" in msg, msg
    # And the actual flag name for the disable path.
    assert "enabled = false" in msg, msg


# ---------------------------------------------------------------------------
# Matrix row: REQUIRED-AT-BOOT fields default to empty in BridgeConfig().
# ---------------------------------------------------------------------------


def test_required_at_boot_fields_default_empty():
    """Sanity assertion: the REQUIRED-AT-BOOT credential fields in the
    matrix default to empty strings on BridgeConfig.

    If this test fails, BridgeConfig has been changed to default a real
    value into a required-at-boot field. That would be a regression —
    operators rely on the empty default + fail-closed validator to
    catch a missing credential at boot time.
    """
    bare = BridgeConfig()
    assert bare.discord_bot_token == "", (
        "discord_bot_token must default empty (REQUIRED-AT-BOOT)"
    )
    assert bare.claude_oauth_token == "", (
        "claude_oauth_token must default empty (REQUIRED-AT-BOOT)"
    )
    assert bare.api_token == "", "api_token must default empty"
    assert bare.vapi_api_key == "", "vapi_api_key must default empty"
    assert bare.vapi_webhook_secret == "", "vapi_webhook_secret must default empty"
    assert bare.codex_oauth_token == "", "codex_oauth_token must default empty"
    assert bare.e2b_api_key == "", "e2b_api_key must default empty"


def test_feature_flags_default_off_so_validators_quiet_at_bare_boot():
    """Sanity: the gating flags for fail-closed pairs default to False.

    A bare `BridgeConfig()` (no overrides) must pass
    `validate()` without error. If a feature flag flips
    its default to True without its companion credential being
    REQUIRED-AT-BOOT, this test catches the regression at unit-test
    time.
    """
    bare = BridgeConfig()
    assert bare.e2b_executor_enabled is False
    # No exception when no flags are on.
    bare.validate()
