"""YAML validation error surfacing (sprint B-S.3).

Ensures that typos in department YAML config fields raise InvalidConfigError
at load time rather than silently reverting to defaults.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from teams._config import InvalidConfigError, load_department_config


_MINIMAL_GOOD_YAML = """\
team:
  name: test-dept
  zone: 4
  description: "valid config"
  chief:
    name: chief
    model: opus-4.6
  workers:
    - name: worker-a
      model: sonnet-4.6
  constraints:
    cost_limit_usd: 1.5
    timeout_seconds: 300
"""

_GOOD_YAML_NO_WORKERS = """\
team:
  name: minimal-dept
  zone: 4
  chief:
    name: chief
    model: opus-4.6
"""


def test_load_good_yaml(tmp_path: Path) -> None:
    path = tmp_path / "test-dept.yaml"
    path.write_text(_MINIMAL_GOOD_YAML)
    cfg = load_department_config(path)
    assert cfg.name == "test-dept"
    assert cfg.zone == 4
    assert cfg.constraints.cost_limit_usd == 1.5
    assert cfg.constraints.timeout_seconds == 300
    assert len(cfg.employees) == 1
    assert cfg.employees[0].name == "worker-a"


def test_load_minimal_yaml_no_workers(tmp_path: Path) -> None:
    path = tmp_path / "minimal.yaml"
    path.write_text(_GOOD_YAML_NO_WORKERS)
    cfg = load_department_config(path)
    assert cfg.name == "minimal-dept"
    assert cfg.employees == ()


def test_load_unknown_field_on_chief_raises(tmp_path: Path) -> None:
    """An unknown field on the chief spec must raise InvalidConfigError."""
    yaml_content = """\
team:
  name: test-dept
  zone: 4
  chief:
    name: chief
    model: opus-4.6
    unknown_field: "should raise"
"""
    path = tmp_path / "bad-chief.yaml"
    path.write_text(yaml_content)
    with pytest.raises(InvalidConfigError, match="unknown_field"):
        load_department_config(path)


def test_load_unknown_field_on_constraints_raises(tmp_path: Path) -> None:
    """A typo in constraints must raise InvalidConfigError."""
    yaml_content = """\
team:
  name: test-dept
  zone: 4
  chief:
    name: chief
    model: opus-4.6
  constraints:
    cost_limit_us: 1.5
"""
    path = tmp_path / "bad-constraints.yaml"
    path.write_text(yaml_content)
    with pytest.raises(InvalidConfigError, match="cost_limit_us"):
        load_department_config(path)


def test_load_unknown_field_on_team_raises(tmp_path: Path) -> None:
    """An unrecognised top-level team field must raise InvalidConfigError."""
    yaml_content = """\
team:
  name: test-dept
  zone: 4
  chief:
    name: chief
    model: opus-4.6
  unknwon_section: "typo"
"""
    path = tmp_path / "bad-team.yaml"
    path.write_text(yaml_content)
    with pytest.raises(InvalidConfigError, match="unknwon_section"):
        load_department_config(path)


def test_load_missing_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.yaml"
    with pytest.raises(InvalidConfigError, match="not found"):
        load_department_config(path)


def test_load_invalid_yaml_syntax_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad-syntax.yaml"
    path.write_text("team: [\n")  # unclosed bracket
    with pytest.raises(InvalidConfigError, match="YAML parse error"):
        load_department_config(path)


def test_load_model_normalized(tmp_path: Path) -> None:
    """Short model aliases must be expanded to full anthropic: strings."""
    yaml_content = """\
team:
  name: test-dept
  zone: 4
  chief:
    name: chief
    model: sonnet-4.6
  workers:
    - name: worker
      model: haiku-4.5
"""
    path = tmp_path / "models.yaml"
    path.write_text(yaml_content)
    cfg = load_department_config(path)
    assert cfg.manager.model == "anthropic:claude-sonnet-4-6"
    assert cfg.employees[0].model == "anthropic:claude-haiku-4-5"


def test_load_tools_section(tmp_path: Path) -> None:
    """Tool lists must be parsed correctly into the config."""
    yaml_content = """\
team:
  name: test-dept
  zone: 4
  chief:
    name: chief
    model: opus-4.6
  workers:
    - name: worker-a
      model: sonnet-4.6
  tools:
    common:
      - read_file
      - search_knowledge
    department:
      - run_tests
    per_employee:
      worker-a:
        - coverage_report
"""
    path = tmp_path / "tools.yaml"
    path.write_text(yaml_content)
    cfg = load_department_config(path)
    assert "read_file" in cfg.common_tools
    assert "search_knowledge" in cfg.common_tools
    assert "run_tests" in cfg.department_tools
    assert cfg.per_employee_tools.get("worker-a") == ("coverage_report",)


def test_load_budget_section(tmp_path: Path) -> None:
    yaml_content = """\
team:
  name: test-dept
  zone: 4
  chief:
    name: chief
    model: opus-4.6
  budget:
    daily_limit_usd: 10.0
    alert_thresholds: [0.6, 0.8, 0.95]
"""
    path = tmp_path / "budget.yaml"
    path.write_text(yaml_content)
    cfg = load_department_config(path)
    assert cfg.budget.daily_limit_usd == 10.0
    assert cfg.budget.alert_thresholds == (0.6, 0.8, 0.95)


def test_existing_config_files_load_without_error() -> None:
    """All checked-in department YAML configs must pass validation."""
    from pathlib import Path as _Path

    config_dir = _Path(__file__).parent.parent.parent / "config" / "teams"
    if not config_dir.exists():
        pytest.skip("No config/teams directory found")

    configs = list(config_dir.glob("*.yaml"))
    if not configs:
        pytest.skip("No YAML configs in config/teams/")

    for config_path in configs:
        # Should not raise
        cfg = load_department_config(config_path)
        assert cfg.name, f"Config {config_path} has no name"


def test_existing_department_chiefs_use_anthropic_oauth_baseline() -> None:
    """Production chiefs use anthropic-oauth:claude-sonnet-4-5 (#2566).

    The OLD baseline (GLM 5.1 cheap-frontier chiefs, one anthropic-oauth
    canary) is obsolete. Chiefs REQUIRE tool-calling, which codex-exec
    cannot drive, so every dept chief now runs the anthropic-oauth
    subscription path. Workers run codex-exec — this test only pins the
    chief baseline.
    """
    from pathlib import Path as _Path

    expected_model = "anthropic-oauth:claude-sonnet-4-5"
    config_dir = _Path(__file__).parent.parent.parent / "config" / "teams"
    configs = [path for path in sorted(config_dir.glob("*.yaml")) if not path.name.startswith("_")]

    offenders: list[str] = []
    for config_path in configs:
        cfg = load_department_config(config_path)
        if cfg.manager.model != expected_model:
            offenders.append(
                f"{config_path.name}: {cfg.manager.name} uses {cfg.manager.model}"
            )

    assert not offenders, (
        "Production chief model baseline drifted from "
        f"{expected_model} (#2566 hybrid fleet — chiefs are anthropic-oauth):\n  "
        + "\n  ".join(offenders)
    )
