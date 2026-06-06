"""Zone 3 engineering config parser tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from teams._registry import DepartmentRegistry
from zone3.engineering_config import (
    DEFAULT_ENGINEERING_CONFIG_PATH,
    EngineeringConfigError,
    load_engineering_team_config,
)


EXPECTED_SPECIALISTS = {
    "engineering-backend-architect",
    "engineering-frontend-developer",
    "engineering-api-engineer",
    "engineering-code-reviewer",
    "engineering-database-specialist",
    "engineering-devops-engineer",
    "engineering-performance-engineer",
    "engineering-tdd-orchestrator",
    "engineering-architect-reviewer",
    "engineering-refactoring-specialist",
}

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_prompt_files(repo_root: Path, agent_names: set[str]) -> None:
    prompts_dir = repo_root / "agent" / "config" / "claude-files" / "agents"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for name in agent_names:
        (prompts_dir / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")


def _valid_config_dict() -> dict:
    return {
        "team": {
            "name": "engineering",
            "zone": 3,
            "execution": "claude-p",
            "description": "Zone 3 engineering test config.",
            "chief": {
                "name": "engineering-chief",
                "model": "claude-code:max",
                "prompt": "agent/config/claude-files/agents/engineering-chief.md",
                "max_parallel_specialists": 3,
            },
            "constraints": {
                "timeout_seconds": 1800,
                "max_parallel_specialists": 3,
                "require_worktree": True,
                "require_local_ci": True,
                "escalation_thresholds": {
                    "delegate_at_complexity": 3,
                    "chief_at_complexity": 6,
                    "zone4_at_complexity": 8,
                },
            },
            "tools": {
                "common": ["read_file", "search_files", "run_tests", "local_ci"],
                "mcp_allowed_servers": ["github", "bumba-memory"],
            },
            "specialists": [
                {
                    "name": name,
                    "model": "claude-code:sonnet",
                    "prompt": f"agent/config/claude-files/agents/{name}.md",
                    "when_to_call": f"Use {name} for focused engineering work.",
                    "write_scopes": ["agent/", "docs/"],
                    "allowed_mcp_servers": ["github", "bumba-memory"],
                }
                for name in sorted(EXPECTED_SPECIALISTS)
            ],
        }
    }


def _write_config(repo_root: Path, config: dict) -> Path:
    config_path = repo_root / "agent" / "config" / "zone3" / "engineering.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def test_engineering_config_is_zone3_claude_p() -> None:
    cfg = load_engineering_team_config(DEFAULT_ENGINEERING_CONFIG_PATH)

    assert cfg.name == "engineering"
    assert cfg.zone == 3
    assert cfg.execution == "claude-p"
    assert cfg.chief_name == "engineering-chief"
    assert cfg.chief.model == "claude-code:max"
    assert len(cfg.specialists) >= 8
    assert EXPECTED_SPECIALISTS.issubset({specialist.name for specialist in cfg.specialists})
    assert cfg.require_worktree is True
    assert cfg.require_local_ci is True
    assert cfg.timeout_seconds == 1800


def test_engineering_config_is_immutable() -> None:
    cfg = load_engineering_team_config(DEFAULT_ENGINEERING_CONFIG_PATH)

    with pytest.raises(FrozenInstanceError):
        cfg.name = "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        cfg.specialists.append("not allowed")  # type: ignore[attr-defined]


def test_engineering_config_is_not_zone4_department() -> None:
    teams_dir = REPO_ROOT / "agent" / "config" / "teams"
    registry = DepartmentRegistry.from_directory(teams_dir)

    assert "engineering" not in registry.department_names()
    assert not (teams_dir / "engineering.yaml").exists()


def test_unknown_yaml_fields_are_rejected(tmp_path: Path) -> None:
    config = _valid_config_dict()
    config["team"]["specialists"][0]["typo_field"] = "should fail"
    repo_root = tmp_path
    _write_prompt_files(repo_root, EXPECTED_SPECIALISTS | {"engineering-chief"})
    config_path = _write_config(repo_root, config)

    with pytest.raises(EngineeringConfigError, match="specialists\\[0\\].typo_field"):
        load_engineering_team_config(config_path)


def test_missing_prompt_path_names_agent_and_path(tmp_path: Path) -> None:
    config = _valid_config_dict()
    missing_agent = "engineering-api-engineer"
    missing_path = f"agent/config/claude-files/agents/{missing_agent}.md"
    repo_root = tmp_path
    _write_prompt_files(
        repo_root,
        (EXPECTED_SPECIALISTS | {"engineering-chief"}) - {missing_agent},
    )
    config_path = _write_config(repo_root, config)

    with pytest.raises(EngineeringConfigError) as exc_info:
        load_engineering_team_config(config_path)

    message = str(exc_info.value)
    assert missing_agent in message
    assert missing_path in message
