"""Tests for verification policy levels (P2.5 #1579).

Replaces the advisory-only verifier surface with three explicit policy
levels:

* ``off``   — verifier skipped entirely
* ``warn``  — failures appended to ``issues``; verdict untouched (pre-P2.5
              advisory behaviour, also the default)
* ``block`` — failures force ``verdict = "fail"`` so the existing
              ``response.evaluator.fail`` plumbing in ``app.py`` fires

Policy is resolved from ``BUMBA_VERIFICATION_POLICY`` at call time so
operators can flip it via env var. Config.toml exposure is deferred to a
follow-up issue.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.response_evaluator import ResponseEvaluator
from bridge.self_verifier import (
    DEFAULT_POLICY,
    POLICY_BLOCK,
    POLICY_ENV_VAR,
    POLICY_OFF,
    POLICY_WARN,
    VALID_POLICIES,
    VerificationResult,
    resolve_policy,
)


# Long enough to bypass the short-response skip in ResponseEvaluator.evaluate
_LONG = "x" * 200


@pytest.fixture
def evaluator(tmp_path):
    return ResponseEvaluator(data_dir=str(tmp_path), enabled=True)


def _mock_runner_passing():
    """Return a mock runner whose invoke returns a passing JSON eval."""
    mock_result = MagicMock()
    mock_result.is_error = False
    mock_result.response_text = json.dumps({
        "completeness": 8, "correctness": 8, "actionability": 8,
        "safety": 8, "overall": 8.0, "issues": [], "verdict": "pass",
    })
    runner = AsyncMock()
    runner.invoke = AsyncMock(return_value=mock_result)
    return runner


def _failing_verifier():
    """Mock verifier that reports a failure (passed=False, errors=[...])."""
    mv = AsyncMock()
    mv.verify_response = AsyncMock(
        return_value=VerificationResult(
            passed=False,
            errors=["HTTP 500 from http://localhost:3000/"],
            urls_checked=1,
        )
    )
    return mv


def _passing_verifier():
    """Mock verifier that reports success (passed=True, errors=[])."""
    mv = AsyncMock()
    mv.verify_response = AsyncMock(
        return_value=VerificationResult(passed=True, errors=[], urls_checked=1)
    )
    return mv


# -- resolve_policy() --

class TestResolvePolicy:
    """The policy resolver — env-var → default fallback chain."""

    def test_default_is_warn(self, monkeypatch):
        """No env var set → default is ``warn`` (pre-P2.5 advisory behaviour)."""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        assert resolve_policy() == POLICY_WARN
        assert DEFAULT_POLICY == POLICY_WARN

    def test_env_var_block(self, monkeypatch):
        monkeypatch.setenv(POLICY_ENV_VAR, "block")
        assert resolve_policy() == POLICY_BLOCK

    def test_env_var_off(self, monkeypatch):
        monkeypatch.setenv(POLICY_ENV_VAR, "off")
        assert resolve_policy() == POLICY_OFF

    def test_env_var_warn(self, monkeypatch):
        monkeypatch.setenv(POLICY_ENV_VAR, "warn")
        assert resolve_policy() == POLICY_WARN

    def test_env_var_case_insensitive(self, monkeypatch):
        monkeypatch.setenv(POLICY_ENV_VAR, "BLOCK")
        assert resolve_policy() == POLICY_BLOCK
        monkeypatch.setenv(POLICY_ENV_VAR, " Off ")
        assert resolve_policy() == POLICY_OFF

    def test_env_var_unrecognised_falls_back(self, monkeypatch, caplog):
        monkeypatch.setenv(POLICY_ENV_VAR, "loud")
        with caplog.at_level("WARNING"):
            assert resolve_policy() == DEFAULT_POLICY
        assert any("Unrecognised verification policy" in r.message for r in caplog.records)

    def test_override_argument_wins(self, monkeypatch):
        monkeypatch.setenv(POLICY_ENV_VAR, "block")
        assert resolve_policy(override="off") == POLICY_OFF
        # And without env, override still works.
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        assert resolve_policy(override="warn") == POLICY_WARN

    def test_valid_policies_constant(self):
        assert set(VALID_POLICIES) == {POLICY_OFF, POLICY_WARN, POLICY_BLOCK}


# -- ResponseEvaluator integration with policy --

class TestPolicyOff:
    """``off`` policy → verifier is not invoked even when wired."""

    @pytest.mark.asyncio
    async def test_verifier_not_called(self, evaluator, monkeypatch):
        monkeypatch.setenv(POLICY_ENV_VAR, "off")
        evaluator.set_runner(_mock_runner_passing())
        verifier = _failing_verifier()
        evaluator.set_verifier(verifier)

        result = await evaluator.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        verifier.verify_response.assert_not_called()
        # Pre-verifier verdict is preserved; no verification-blocked flag.
        assert result.verdict == "pass"
        assert result.verification_blocked is False
        # No verifier output → no extra issues appended.
        assert result.issues == []


class TestPolicyWarn:
    """``warn`` policy → pre-P2.5 advisory behaviour preserved."""

    @pytest.mark.asyncio
    async def test_failures_appended_verdict_untouched(self, evaluator, monkeypatch):
        monkeypatch.setenv(POLICY_ENV_VAR, "warn")
        evaluator.set_runner(_mock_runner_passing())
        evaluator.set_verifier(_failing_verifier())

        result = await evaluator.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        # Verifier errors appended to issues …
        assert any("HTTP 500" in i for i in result.issues)
        # … but verdict was NOT forced to fail.
        assert result.verdict == "pass"
        assert result.verification_blocked is False

    @pytest.mark.asyncio
    async def test_default_when_env_unset_is_warn(self, evaluator, monkeypatch):
        """No env var → default policy is ``warn`` (back-compat)."""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        evaluator.set_runner(_mock_runner_passing())
        evaluator.set_verifier(_failing_verifier())

        result = await evaluator.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        assert any("HTTP 500" in i for i in result.issues)
        assert result.verdict == "pass"
        assert result.verification_blocked is False


class TestPolicyBlock:
    """``block`` policy → verification failure forces ``verdict = "fail"``."""

    @pytest.mark.asyncio
    async def test_failure_forces_verdict_fail(self, evaluator, monkeypatch):
        monkeypatch.setenv(POLICY_ENV_VAR, "block")
        evaluator.set_runner(_mock_runner_passing())
        evaluator.set_verifier(_failing_verifier())

        result = await evaluator.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        assert result.verdict == "fail"
        assert result.verification_blocked is True
        # Errors still appended for diagnosis.
        assert any("HTTP 500" in i for i in result.issues)

    @pytest.mark.asyncio
    async def test_success_does_not_force_fail(self, evaluator, monkeypatch):
        """Block policy + passing verifier → verdict preserved."""
        monkeypatch.setenv(POLICY_ENV_VAR, "block")
        evaluator.set_runner(_mock_runner_passing())
        evaluator.set_verifier(_passing_verifier())

        result = await evaluator.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        assert result.verdict == "pass"
        assert result.verification_blocked is False
        assert result.issues == []

    @pytest.mark.asyncio
    async def test_stats_reaccounted_when_verdict_flips(self, evaluator, monkeypatch):
        """When block-policy flips verdict, ``_stats`` reflect the new
        verdict (so /eval-status and format_status() don't misreport)."""
        monkeypatch.setenv(POLICY_ENV_VAR, "block")
        evaluator.set_runner(_mock_runner_passing())
        evaluator.set_verifier(_failing_verifier())

        await evaluator.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        stats = evaluator.get_stats()
        assert stats["total"] == 1
        assert stats.get("fail", 0) == 1
        # The pre-verifier "pass" verdict was decremented.
        assert stats.get("pass", 0) == 0

    @pytest.mark.asyncio
    async def test_no_verifier_no_block(self, evaluator, monkeypatch):
        """Block policy without a verifier wired → no-op (verdict preserved).

        Defensive: policy applies only when there is something to verify
        against. Without a verifier the evaluator can't have an opinion.
        """
        monkeypatch.setenv(POLICY_ENV_VAR, "block")
        evaluator.set_runner(_mock_runner_passing())
        # Intentionally do NOT call evaluator.set_verifier(...)

        result = await evaluator.evaluate(
            "Build the dashboard page", "Dashboard built" + _LONG,
        )
        assert result.verdict == "pass"
        assert result.verification_blocked is False


class TestPolicyDoesNotBreakNonBlockingPaths:
    """Timeouts / exceptions in the verifier never propagate, regardless of policy."""

    @pytest.mark.asyncio
    async def test_block_policy_verifier_timeout_nonblocking(self, evaluator, monkeypatch):
        import asyncio
        monkeypatch.setenv(POLICY_ENV_VAR, "block")
        evaluator.set_runner(_mock_runner_passing())

        async def slow_verify(_text):
            await asyncio.sleep(100)

        mv = AsyncMock()
        mv.verify_response = slow_verify
        evaluator.set_verifier(mv)

        result = await evaluator.evaluate(
            "Build the app", "App at http://localhost:3000/" + _LONG,
        )
        # Timeout in the verifier is non-blocking even under policy=block;
        # we don't have failure information so verdict is NOT flipped.
        assert result.verdict == "pass"
        assert result.verification_blocked is False

    @pytest.mark.asyncio
    async def test_block_policy_verifier_exception_nonblocking(self, evaluator, monkeypatch):
        monkeypatch.setenv(POLICY_ENV_VAR, "block")
        evaluator.set_runner(_mock_runner_passing())

        mv = AsyncMock()
        mv.verify_response = AsyncMock(side_effect=RuntimeError("boom"))
        evaluator.set_verifier(mv)

        result = await evaluator.evaluate(
            "Fix the bug", "Bug fixed in auth module" + _LONG,
        )
        assert result.verdict == "pass"
        assert result.verification_blocked is False


# -- Config-source resolution (P2.5 follow-up #1664) --

class TestConfigPolicyResolution:
    """The ``config_policy`` parameter — bridge.toml as the canonical source.

    Resolution order is env-var > config_policy > DEFAULT_POLICY. The env
    var stays usable as an override so an operator can flip a single bridge
    instance without editing bridge.toml.
    """

    def test_config_policy_block(self, monkeypatch):
        """Config says 'block' and no env var → resolver returns block."""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        assert resolve_policy(config_policy="block") == POLICY_BLOCK

    def test_config_policy_off(self, monkeypatch):
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        assert resolve_policy(config_policy="off") == POLICY_OFF

    def test_config_policy_warn_matches_default(self, monkeypatch):
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        assert resolve_policy(config_policy="warn") == POLICY_WARN

    def test_config_policy_case_insensitive(self, monkeypatch):
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        assert resolve_policy(config_policy="BLOCK") == POLICY_BLOCK
        assert resolve_policy(config_policy=" Off ") == POLICY_OFF

    def test_env_var_overrides_config(self, monkeypatch):
        """Env var wins over config_policy (operator-visible override)."""
        monkeypatch.setenv(POLICY_ENV_VAR, "warn")
        assert resolve_policy(config_policy="block") == POLICY_WARN

    def test_override_arg_wins_over_config(self, monkeypatch):
        """Explicit override (e.g. tests) wins over config too."""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        assert resolve_policy(override="off", config_policy="block") == POLICY_OFF

    def test_config_policy_unrecognised_falls_back_to_default(self, monkeypatch, caplog):
        """Invalid bridge.toml value → fall back to default + WARNING log."""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        with caplog.at_level("WARNING"):
            assert resolve_policy(config_policy="loud") == DEFAULT_POLICY
        assert any(
            "Unrecognised verification policy" in r.message and "bridge.toml" in r.message
            for r in caplog.records
        )

    def test_none_config_policy_is_no_op(self, monkeypatch):
        """config_policy=None → behaves identically to omitting the arg."""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        assert resolve_policy(config_policy=None) == DEFAULT_POLICY

    def test_env_var_unrecognised_falls_through_to_config(self, monkeypatch, caplog):
        """Bad env-var value → fall through to config_policy (not default)."""
        monkeypatch.setenv(POLICY_ENV_VAR, "loud")
        with caplog.at_level("WARNING"):
            assert resolve_policy(config_policy="block") == POLICY_BLOCK


class TestConfigPolicyWiring:
    """End-to-end: ResponseEvaluator(verification_policy=...) drives the gate."""

    @pytest.mark.asyncio
    async def test_config_block_forces_fail(self, tmp_path, monkeypatch):
        """Construct evaluator with policy='block' from config; no env var
        set; failing verifier → verdict flipped to 'fail'."""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        ev = ResponseEvaluator(
            data_dir=str(tmp_path),
            enabled=True,
            verification_policy="block",
        )
        ev.set_runner(_mock_runner_passing())
        ev.set_verifier(_failing_verifier())

        result = await ev.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        assert result.verdict == "fail"
        assert result.verification_blocked is True

    @pytest.mark.asyncio
    async def test_config_off_skips_verifier(self, tmp_path, monkeypatch):
        """policy='off' from config + no env var → verifier never called."""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        ev = ResponseEvaluator(
            data_dir=str(tmp_path),
            enabled=True,
            verification_policy="off",
        )
        ev.set_runner(_mock_runner_passing())
        verifier = _failing_verifier()
        ev.set_verifier(verifier)

        result = await ev.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        verifier.verify_response.assert_not_called()
        assert result.verdict == "pass"
        assert result.verification_blocked is False

    @pytest.mark.asyncio
    async def test_env_var_overrides_config_in_evaluator(self, tmp_path, monkeypatch):
        """policy='block' from config, but env says 'warn' → env wins."""
        monkeypatch.setenv(POLICY_ENV_VAR, "warn")
        ev = ResponseEvaluator(
            data_dir=str(tmp_path),
            enabled=True,
            verification_policy="block",
        )
        ev.set_runner(_mock_runner_passing())
        ev.set_verifier(_failing_verifier())

        result = await ev.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        # Env-var "warn" wins → verdict NOT flipped.
        assert result.verdict == "pass"
        assert result.verification_blocked is False
        # But errors are still appended (warn behaviour).
        assert any("HTTP 500" in i for i in result.issues)

    @pytest.mark.asyncio
    async def test_evaluator_default_constructor_is_back_compat(self, tmp_path, monkeypatch):
        """Existing call sites that omit verification_policy keep the
        pre-P2.5-follow-up behaviour (default = warn)."""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        # Note: no verification_policy kwarg — back-compat constructor.
        ev = ResponseEvaluator(data_dir=str(tmp_path), enabled=True)
        ev.set_runner(_mock_runner_passing())
        ev.set_verifier(_failing_verifier())

        result = await ev.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        # Default policy is "warn": errors appended, verdict untouched.
        assert result.verdict == "pass"
        assert result.verification_blocked is False
        assert any("HTTP 500" in i for i in result.issues)


class TestConfigFieldLoad:
    """BridgeConfig.verification_policy is loadable from bridge.toml."""

    def test_default_value_is_warn(self):
        """Default matches the pre-P2.5 advisory behaviour (back-compat)."""
        from bridge.config import BridgeConfig

        cfg = BridgeConfig(
            discord_bot_token="x",
            operator_discord_id="1",
        )
        assert cfg.verification_policy == "warn"

    def test_field_loads_from_toml(self, tmp_path, monkeypatch):
        """`[verification] policy = "block"` in bridge.toml → field set."""
        from bridge.config import load_config

        toml_path = tmp_path / "bridge.toml"
        toml_path.write_text(
            '[verification]\npolicy = "block"\n'
        )
        # Minimum config to satisfy validation.
        monkeypatch.setenv("BUMBA_BRIDGE_CONFIG", str(toml_path))
        monkeypatch.setenv("BUMBA_DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setenv("BUMBA_OPERATOR_DISCORD_ID", "1234")
        monkeypatch.setenv("BUMBA_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BUMBA_LOG_DIR", str(tmp_path))

        cfg = load_config(skip_secrets=True, skip_validation=True)
        assert cfg.verification_policy == "block"

    def test_mode_alias_loads_from_toml(self, tmp_path, monkeypatch):
        """`[verification] mode = "off"` (spec-original key) also works."""
        from bridge.config import load_config

        toml_path = tmp_path / "bridge.toml"
        toml_path.write_text(
            '[verification]\nmode = "off"\n'
        )
        monkeypatch.setenv("BUMBA_BRIDGE_CONFIG", str(toml_path))
        monkeypatch.setenv("BUMBA_DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setenv("BUMBA_OPERATOR_DISCORD_ID", "1234")
        monkeypatch.setenv("BUMBA_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BUMBA_LOG_DIR", str(tmp_path))

        cfg = load_config(skip_secrets=True, skip_validation=True)
        assert cfg.verification_policy == "off"

    def test_invalid_value_falls_back_with_warning(self, tmp_path, monkeypatch, caplog):
        """Invalid bridge.toml value → resolve_policy emits warning + falls
        back to default. The dataclass holds the raw value; the resolver
        normalises it. (Matches the env-var path's back-compat shape per
        issue #1664 acceptance.)"""
        monkeypatch.delenv(POLICY_ENV_VAR, raising=False)
        with caplog.at_level("WARNING"):
            assert resolve_policy(config_policy="loud") == DEFAULT_POLICY
        assert any(
            "Unrecognised verification policy" in r.message
            for r in caplog.records
        )
