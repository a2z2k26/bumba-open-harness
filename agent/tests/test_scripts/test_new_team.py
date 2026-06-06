"""Tests for agent/scripts/new_team.py — D3.2.

Test cases:
  1. Non-interactive (--config) mode produces all expected files
  2. Interactive (stdin-piped) mode produces all expected files
  3. Duplicate team name aborts with exit code 1
  4. Generated team YAML re-parses cleanly with yaml.safe_load
  5. Generated chief system prompt contains literal {ROSTER} placeholder
  6. DepartmentRegistry auto-discovery: generated YAML is loadable via load_department_config
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
import yaml

# Make agent package importable from within the tests dir tree.
AGENT_ROOT = Path(__file__).resolve().parents[3]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from agent.scripts.new_team import (
    _collect_interactive,
    _parse_config,
    _verify_no_duplicate_team,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_teams_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Redirect TEAMS_DIR and REPO_ROOT inside new_team module to tmp_path."""
    import agent.scripts.new_team as mod

    teams_dir = tmp_path / "agent" / "config" / "teams"
    teams_dir.mkdir(parents=True)

    monkeypatch.setattr(mod, "TEAMS_DIR", teams_dir)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

    yield teams_dir


def _make_config_yaml(tmp_path: Path) -> Path:
    """Write a minimal valid non-interactive spec YAML and return its path."""
    spec = {
        "prefix": "ts",
        "description": "Test department for automated scaffold testing.",
        "chief_role": "Orchestrate the test department and delegate to specialists.",
        "chief_mission": "Ensure comprehensive test coverage and quality gates.",
        "workers": [
            {"name": "unit-tester", "role": "Write and maintain unit test suites"},
            {"name": "integration-tester", "role": "End-to-end and integration test coverage"},
        ],
    }
    config_path = tmp_path / "test-spec.yaml"
    config_path.write_text(yaml.dump(spec), encoding="utf-8")
    return config_path


# ---------------------------------------------------------------------------
# Test 1: --config mode produces all expected files
# ---------------------------------------------------------------------------

def test_config_mode_produces_all_files(tmp_teams_dir: Path, tmp_path: Path) -> None:
    """Non-interactive --config mode must write all 8+ expected files."""
    config_path = _make_config_yaml(tmp_path)
    import agent.scripts.new_team as mod

    spec = _parse_config("test-dept", config_path)
    paths = mod._resolve_paths(spec)
    mod._scaffold(spec)

    # Core files must exist
    assert Path(paths.team_yaml).exists(), "team YAML missing"
    assert Path(paths.chief_expertise).exists(), "chief expertise missing"
    assert Path(paths.chief_prompt).exists(), "chief system prompt missing"
    assert Path(paths.checklist).exists(), "checklist missing"

    # Worker files must all exist (2 workers × 2 files = 4 files)
    for ep in paths.worker_expertises:
        assert Path(ep).exists(), f"worker expertise missing: {ep}"
    for wp in paths.worker_prompts:
        assert Path(wp).exists(), f"worker prompt missing: {wp}"


# ---------------------------------------------------------------------------
# Test 2: interactive (stdin-piped) mode produces all expected files
# ---------------------------------------------------------------------------

def test_interactive_mode_produces_all_files(tmp_teams_dir: Path, tmp_path: Path) -> None:
    """Interactive stdin-piped mode must write all files without errors."""
    import agent.scripts.new_team as mod

    # Simulate stdin: prefix, description, chief_role, chief_mission, worker1 name+role, blank
    stdin_input = (
        "it\n"                                               # prefix
        "IT department for integration testing.\n"           # description
        "Orchestrate IT operations and delegate to techs.\n" # chief role
        "Deliver reliable IT infrastructure and support.\n"  # chief mission
        "sysadmin\n"                                         # worker 1 short name
        "System administration and server management\n"      # worker 1 role
        "\n"                                                 # done (blank = finish roster)
    )

    with patch("sys.stdin", io.StringIO(stdin_input)):
        spec = _collect_interactive("it-dept")

    assert spec.name == "it-dept"
    assert spec.prefix == "it"
    assert len(spec.workers) == 1
    assert spec.workers[0]["name"] == "it-sysadmin"

    paths = mod._scaffold(spec)
    assert Path(paths.team_yaml).exists()
    assert Path(paths.chief_expertise).exists()
    assert Path(paths.chief_prompt).exists()
    assert Path(paths.checklist).exists()
    assert len(paths.worker_expertises) == 1
    assert Path(paths.worker_expertises[0]).exists()
    assert Path(paths.worker_prompts[0]).exists()


# ---------------------------------------------------------------------------
# Test 3: duplicate team name aborts with exit code 1
# ---------------------------------------------------------------------------

def test_duplicate_team_aborts(tmp_teams_dir: Path) -> None:
    """If a team YAML already exists, _verify_no_duplicate_team must raise SystemExit(1)."""
    (tmp_teams_dir / "existing-team.yaml").write_text("team:\n  name: existing-team\n")

    with pytest.raises(SystemExit) as exc_info:
        _verify_no_duplicate_team("existing-team")

    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Test 4: generated YAML re-parses cleanly
# ---------------------------------------------------------------------------

def test_generated_yaml_reparses_cleanly(tmp_teams_dir: Path, tmp_path: Path) -> None:
    """The generated team YAML must be loadable by yaml.safe_load without errors."""
    config_path = _make_config_yaml(tmp_path)
    import agent.scripts.new_team as mod

    spec = _parse_config("test-reparseable", config_path)
    paths = mod._scaffold(spec)

    loaded = yaml.safe_load(Path(paths.team_yaml).read_text(encoding="utf-8"))
    assert loaded is not None
    assert isinstance(loaded, dict), "parsed YAML root must be a dict"
    assert "team" in loaded, "parsed YAML must have 'team' key"
    assert loaded["team"]["name"] == "test-reparseable"
    # Chief block must be present
    assert "chief" in loaded["team"], "team YAML must have 'chief' block"
    # Workers block must be present with correct count
    assert "workers" in loaded["team"], "team YAML must have 'workers' block"
    assert len(loaded["team"]["workers"]) == 2


# ---------------------------------------------------------------------------
# Test 5: chief system prompt contains {ROSTER} placeholder
# ---------------------------------------------------------------------------

def test_chief_prompt_contains_roster_placeholder(tmp_teams_dir: Path, tmp_path: Path) -> None:
    """The generated chief system prompt must contain the literal {ROSTER} placeholder."""
    config_path = _make_config_yaml(tmp_path)
    import agent.scripts.new_team as mod

    spec = _parse_config("test-roster", config_path)
    paths = mod._scaffold(spec)

    chief_prompt_content = Path(paths.chief_prompt).read_text(encoding="utf-8")
    assert "{ROSTER}" in chief_prompt_content, (
        "Chief system prompt must contain the literal {ROSTER} placeholder "
        "for DepartmentRegistry.prewarm() injection. "
        f"Actual content:\n{chief_prompt_content[:500]}"
    )


# ---------------------------------------------------------------------------
# Test 6: DepartmentRegistry auto-discovery via load_department_config
# ---------------------------------------------------------------------------

def test_generated_yaml_loadable_by_department_config(
    tmp_teams_dir: Path, tmp_path: Path
) -> None:
    """Generated team YAML must be loadable via teams._config.load_department_config.

    load_department_config returns DepartmentConfig(manager=<chief>, employees=<workers>).
    We verify: manager name is the chief, and both workers are present in employees.
    """
    try:
        from teams._config import load_department_config  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("teams._config not importable in this environment")

    config_path = _make_config_yaml(tmp_path)
    import agent.scripts.new_team as mod

    spec = _parse_config("test-discovery", config_path)
    paths = mod._scaffold(spec)

    dept_config = load_department_config(Path(paths.team_yaml))
    assert dept_config is not None

    # Chief lives in dept_config.manager, not employees
    assert dept_config.manager is not None, "manager (chief) must be set"
    assert "chief" in dept_config.manager.name, (
        f"Chief name expected to contain 'chief', got: {dept_config.manager.name}"
    )

    # Workers are in dept_config.employees
    worker_names = {e.name for e in dept_config.employees}
    assert "ts-unit-tester" in worker_names, (
        f"Expected 'ts-unit-tester' in employees; got: {sorted(worker_names)}"
    )
    assert "ts-integration-tester" in worker_names, (
        f"Expected 'ts-integration-tester' in employees; got: {sorted(worker_names)}"
    )
