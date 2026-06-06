"""Tests for E4.2 — scaffold_zone4.py dispatcher.

Integration-level: tests write real files to tmp_path and verify outcomes.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures — patch REPO_ROOT so all writes go to tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_root(tmp_path: Path):
    """Return a fake repo root with the minimum directory skeleton."""
    # scaffold_zone4 uses REPO_ROOT / "agent/config/teams" etc.
    (tmp_path / "agent" / "config" / "teams").mkdir(parents=True)
    (tmp_path / "agent" / "config" / "expertise" / "updatable").mkdir(parents=True)
    (tmp_path / "agent" / "config" / "agents" / "zone4").mkdir(parents=True)
    return tmp_path


def _run(argv: list[str], fake_root: Path) -> int:
    """Invoke scaffold_zone4.main() with REPO_ROOT patched to fake_root."""
    import scripts.scaffold_zone4 as mod
    with patch.object(mod, "REPO_ROOT", fake_root):
        with patch.object(mod, "TEAMS_DIR", fake_root / "agent" / "config" / "teams"):
            # Suppress registry discovery — it requires pydantic + real YAML paths
            with patch.object(mod, "_check_registry_discovery", return_value=None):
                return mod.main(argv)


# ---------------------------------------------------------------------------
# Invalid kind
# ---------------------------------------------------------------------------


def test_invalid_kind_aborts(fake_root: Path, capsys):
    import scripts.scaffold_zone4 as mod
    with patch.object(mod, "REPO_ROOT", fake_root):
        with pytest.raises(SystemExit) as exc_info:
            mod.main(["bad-kind", "my-team"])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# single-agent
# ---------------------------------------------------------------------------


class TestSingleAgent:
    def test_creates_three_files(self, fake_root: Path):
        rc = _run(["single-agent", "solo-team"], fake_root)
        assert rc == 0
        assert (fake_root / "agent/config/expertise/updatable/solo-team.md").exists()
        assert (fake_root / "agent/config/agents/zone4/solo-team/solo-team.md").exists()
        assert (fake_root / "agent/config/teams/solo-team.yaml").exists()

    def test_yaml_has_empty_workers(self, fake_root: Path):
        _run(["single-agent", "solo-team"], fake_root)
        data = yaml.safe_load(
            (fake_root / "agent/config/teams/solo-team.yaml").read_text()
        )
        assert data["team"]["workers"] == []

    def test_yaml_chief_name_matches(self, fake_root: Path):
        _run(["single-agent", "solo-team"], fake_root)
        data = yaml.safe_load(
            (fake_root / "agent/config/teams/solo-team.yaml").read_text()
        )
        assert data["team"]["chief"]["name"] == "solo-team"

    def test_collision_aborts(self, fake_root: Path):
        _run(["single-agent", "solo-team"], fake_root)
        import scripts.scaffold_zone4 as mod
        with patch.object(mod, "REPO_ROOT", fake_root):
            with patch.object(mod, "TEAMS_DIR", fake_root / "agent" / "config" / "teams"):
                with pytest.raises(SystemExit) as exc_info:
                    mod.main(["single-agent", "solo-team"])
        assert exc_info.value.code == 1

    def test_invalid_name_aborts(self, fake_root: Path):
        import scripts.scaffold_zone4 as mod
        with patch.object(mod, "REPO_ROOT", fake_root):
            with patch.object(mod, "TEAMS_DIR", fake_root / "agent" / "config" / "teams"):
                with pytest.raises(SystemExit) as exc_info:
                    mod.main(["single-agent", "My_Team"])
        assert exc_info.value.code == 1

    def test_prints_file_list(self, fake_root: Path, capsys):
        _run(["single-agent", "solo-team"], fake_root)
        out = capsys.readouterr().out
        assert "solo-team" in out
        assert "done in" in out


# ---------------------------------------------------------------------------
# chief-specialist
# ---------------------------------------------------------------------------


class TestChiefSpecialist:
    def test_creates_five_files(self, fake_root: Path):
        rc = _run(["chief-specialist", "qa-lite"], fake_root)
        assert rc == 0
        # chief expertise, chief prompt, specialist expertise, specialist prompt, yaml
        assert (fake_root / "agent/config/expertise/updatable/qa-lite-chief.md").exists()
        assert (fake_root / "agent/config/agents/zone4/qa-lite/qa-lite-chief.md").exists()
        assert (fake_root / "agent/config/expertise/updatable/qa-lite-specialist.md").exists()
        assert (fake_root / "agent/config/agents/zone4/qa-lite/qa-lite-specialist.md").exists()
        assert (fake_root / "agent/config/teams/qa-lite.yaml").exists()

    def test_yaml_has_one_worker(self, fake_root: Path):
        _run(["chief-specialist", "qa-lite"], fake_root)
        data = yaml.safe_load(
            (fake_root / "agent/config/teams/qa-lite.yaml").read_text()
        )
        assert len(data["team"]["workers"]) == 1
        assert data["team"]["workers"][0]["name"] == "qa-lite-specialist"

    def test_yaml_chief_name_matches(self, fake_root: Path):
        _run(["chief-specialist", "qa-lite"], fake_root)
        data = yaml.safe_load(
            (fake_root / "agent/config/teams/qa-lite.yaml").read_text()
        )
        assert data["team"]["chief"]["name"] == "qa-lite-chief"

    def test_collision_aborts(self, fake_root: Path):
        _run(["chief-specialist", "qa-lite"], fake_root)
        import scripts.scaffold_zone4 as mod
        with patch.object(mod, "REPO_ROOT", fake_root):
            with patch.object(mod, "TEAMS_DIR", fake_root / "agent" / "config" / "teams"):
                with pytest.raises(SystemExit) as exc_info:
                    mod.main(["chief-specialist", "qa-lite"])
        assert exc_info.value.code == 1

    def test_prints_chief_and_specialist(self, fake_root: Path, capsys):
        _run(["chief-specialist", "qa-lite"], fake_root)
        out = capsys.readouterr().out
        assert "qa-lite-chief" in out
        assert "qa-lite-specialist" in out


# ---------------------------------------------------------------------------
# agent-team (forwarded to new_team.main)
# ---------------------------------------------------------------------------


class TestAgentTeam:
    def test_forwards_to_new_team_main(self, fake_root: Path, tmp_path: Path):
        """agent-team kind delegates entirely to new_team.main()."""
        import scripts.scaffold_zone4 as mod
        mock_main = MagicMock(return_value=0)
        with patch.object(mod.new_team, "main", mock_main):
            with patch.object(mod, "REPO_ROOT", fake_root):
                with patch.object(mod, "TEAMS_DIR", fake_root / "agent" / "config" / "teams"):
                    rc = mod._dispatch_agent_team("my-team", None)
        mock_main.assert_called_once_with(["my-team"])
        assert rc == 0

    def test_forwards_config_path(self, fake_root: Path):
        import scripts.scaffold_zone4 as mod
        mock_main = MagicMock(return_value=0)
        with patch.object(mod.new_team, "main", mock_main):
            with patch.object(mod, "REPO_ROOT", fake_root):
                with patch.object(mod, "TEAMS_DIR", fake_root / "agent" / "config" / "teams"):
                    rc = mod._dispatch_agent_team("my-team", "/tmp/spec.yaml")
        mock_main.assert_called_once_with(["my-team", "--config", "/tmp/spec.yaml"])
        assert rc == 0


# ---------------------------------------------------------------------------
# Registry discovery
# ---------------------------------------------------------------------------


class TestRegistryDiscovery:
    def test_discovery_success_is_silent(self, fake_root: Path, tmp_path: Path):
        """_check_registry_discovery does not raise when load_department_config succeeds."""
        import scripts.scaffold_zone4 as mod
        dummy_yaml = fake_root / "agent" / "config" / "teams" / "test-team.yaml"
        dummy_yaml.parent.mkdir(parents=True, exist_ok=True)
        dummy_yaml.write_text("team: {name: test-team, zone: 4, chief: {name: c}}")
        with patch.object(mod, "load_department_config") as mock_load:
            with patch.object(mod, "TEAMS_DIR", fake_root / "agent" / "config" / "teams"):
                mod._check_registry_discovery("test-team")  # should not raise
                # Silent success contract: the loader was called exactly
                # once with the team's YAML path and the helper returned
                # without calling sys.exit.
                mock_load.assert_called_once_with(dummy_yaml)

    def test_discovery_failure_exits_1(self, fake_root: Path):
        import scripts.scaffold_zone4 as mod
        with patch.object(mod, "load_department_config", side_effect=Exception("bad yaml")):
            with patch.object(mod, "TEAMS_DIR", fake_root / "agent" / "config" / "teams"):
                with pytest.raises(SystemExit) as exc_info:
                    mod._check_registry_discovery("bad-team")
        assert exc_info.value.code == 1
