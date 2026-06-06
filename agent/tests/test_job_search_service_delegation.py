"""Sprint D5.2 (#1207) — job_search_team_enabled flag-gated delegation.

Tests that:
- Flag OFF → existing JobSearchAgent.prepare()/execute() path runs unchanged.
- Flag ON  → ``job_search.department.run_{prepare,execute}`` is invoked.
- Flag ON + delegation failure → falls back to direct JobSearchAgent path.

Sprint P5.3 (#1588) — ``_run_via_team`` now routes through
:func:`job_search.department.run_prepare` / ``run_execute`` instead of calling
``DepartmentRegistry.route`` directly. The department wrappers carry the
``asyncio.timeout`` protection that the previous direct ``registry.route``
call silently bypassed. Tests below assert against the canonical join point.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


import job_search.__main__ as _main


# ---------------------------------------------------------------------------
# flag OFF — direct path
# ---------------------------------------------------------------------------

class TestFlagOff:
    def test_is_team_enabled_returns_false_when_config_missing(self):
        with patch("bridge.config.load_config", side_effect=FileNotFoundError):
            result = _main._is_team_enabled()
        assert result is False

    def test_is_team_enabled_returns_false_on_exception(self):
        with patch("bridge.config.load_config", side_effect=RuntimeError("boom")):
            result = _main._is_team_enabled()
        assert result is False

    def test_is_team_enabled_returns_false_when_flag_off(self, tmp_path):
        cfg_mock = MagicMock()
        cfg_mock.job_search_team_enabled = False
        with patch("bridge.config.load_config", return_value=cfg_mock):
            with patch.object(Path, "exists", return_value=True):
                result = _main._is_team_enabled()
        assert result is False

    def test_is_team_enabled_returns_true_when_flag_on(self, tmp_path):
        cfg_mock = MagicMock()
        cfg_mock.job_search_team_enabled = True
        with patch("bridge.config.load_config", return_value=cfg_mock):
            with patch.object(Path, "exists", return_value=True):
                result = _main._is_team_enabled()
        assert result is True


# ---------------------------------------------------------------------------
# flag ON — team delegation path
# ---------------------------------------------------------------------------

class TestFlagOn:
    def _team_result(self, manager_output: str | None) -> MagicMock:
        """TeamResult-shaped success object the CLI path treats as success.

        ``_run_via_team`` reads ``.manager_output`` (P5.3 canonical) — the
        same field the cron services read from ``run_prepare``/``run_execute``.
        """
        result_mock = MagicMock()
        result_mock.manager_output = manager_output
        result_mock.success = True
        result_mock.error = None
        result_mock.total_cost_usd = 0.0
        return result_mock

    def test_prepare_delegates_to_department(self):
        """Flag ON → ``_run_via_team("prepare")`` invokes ``department.run_prepare``."""
        team_result = self._team_result("team-prepare-output")
        deps_mock = MagicMock()

        with (
            patch("teams._types.BridgeDeps.for_cron", new_callable=AsyncMock, return_value=deps_mock),
            patch("job_search.department.run_prepare", new_callable=AsyncMock, return_value=team_result) as mock_prepare,
        ):
            summary = asyncio.run(_main._run_via_team("prepare"))

        mock_prepare.assert_awaited_once_with(deps_mock)
        assert summary == "team-prepare-output"

    def test_execute_delegates_to_department(self):
        """Flag ON → ``_run_via_team("execute")`` invokes ``department.run_execute``."""
        team_result = self._team_result("team-execute-output")
        deps_mock = MagicMock()

        with (
            patch("teams._types.BridgeDeps.for_cron", new_callable=AsyncMock, return_value=deps_mock),
            patch("job_search.department.run_execute", new_callable=AsyncMock, return_value=team_result) as mock_execute,
        ):
            summary = asyncio.run(_main._run_via_team("execute"))

        mock_execute.assert_awaited_once_with(deps_mock)
        assert summary == "team-execute-output"

    def test_fallback_on_department_failure(self):
        """If Zone 4 delegation raises, fall back to direct JobSearchAgent."""
        agent_mock = MagicMock()
        agent_mock.prepare = AsyncMock(return_value="fallback-prepare")

        with (
            patch("teams._types.BridgeDeps.for_cron", new_callable=AsyncMock, side_effect=RuntimeError("no deps")),
            patch("job_search.agent.JobSearchAgent", return_value=agent_mock),
        ):
            summary = asyncio.run(_main._run_via_team("prepare"))

        assert summary == "fallback-prepare"
        agent_mock.prepare.assert_awaited_once()

    def test_none_output_returns_default_message(self):
        team_result = self._team_result(None)
        deps_mock = MagicMock()

        with (
            patch("teams._types.BridgeDeps.for_cron", new_callable=AsyncMock, return_value=deps_mock),
            patch("job_search.department.run_prepare", new_callable=AsyncMock, return_value=team_result),
        ):
            summary = asyncio.run(_main._run_via_team("prepare"))

        assert "completed prepare" in summary


# ---------------------------------------------------------------------------
# config flag round-trip
# ---------------------------------------------------------------------------

class TestConfigFlag:
    def test_flag_defaults_false(self):
        from bridge.config import BridgeConfig
        cfg = BridgeConfig()
        assert cfg.job_search_team_enabled is False

    def test_flag_readable_from_toml(self, tmp_path):
        from bridge.config import load_config

        (tmp_path / "bridge.toml").write_text(
            f"""
[discord]

[bridge]
data_dir = "{tmp_path}"
log_dir = "{tmp_path}"

[job_search]
team_enabled = true
"""
        )

        cfg = load_config(tmp_path / "bridge.toml", skip_secrets=True, skip_validation=True)
        assert cfg.job_search_team_enabled is True

    def test_flag_false_from_toml(self, tmp_path):
        from bridge.config import load_config

        (tmp_path / "bridge.toml").write_text(
            f"""
[discord]

[bridge]
data_dir = "{tmp_path}"
log_dir = "{tmp_path}"

[job_search]
team_enabled = false
"""
        )

        cfg = load_config(tmp_path / "bridge.toml", skip_secrets=True, skip_validation=True)
        assert cfg.job_search_team_enabled is False
