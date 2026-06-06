"""Tests for teams._config module."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from teams._config import (
    load_department_config,
    _normalize_model_string,
    InvalidConfigError,
)


class TestNormalizeModelString:
    def test_adds_anthropic_prefix(self):
        assert _normalize_model_string("opus-4.6") == "anthropic:claude-opus-4-6"
        assert _normalize_model_string("sonnet-4.6") == "anthropic:claude-sonnet-4-6"
        assert _normalize_model_string("haiku-4.5") == "anthropic:claude-haiku-4-5"

    def test_already_prefixed_unchanged(self):
        assert _normalize_model_string("anthropic:claude-opus-4-6") == "anthropic:claude-opus-4-6"
        assert _normalize_model_string("openai:gpt-4o") == "openai:gpt-4o"


class TestLoadDepartmentConfig:
    def _write_minimal_yaml(self, tmp_path: Path) -> Path:
        path = tmp_path / "qa.yaml"
        path.write_text(textwrap.dedent("""\
            team:
              name: qa
              zone: 4
              description: QA department

              chief:
                name: qa-chief
                role: QA orchestrator
                model: opus-4.6
                expertise: agent/config/expertise/updatable/qa-chief.md
                system_prompt: agent/config/agents/zone4/qa/qa-chief.md

              workers:
                - name: qa-engineer
                  role: Test design and coverage
                  model: sonnet-4.6
                  expertise: agent/config/expertise/updatable/qa-engineer.md
                  system_prompt: agent/config/agents/zone4/qa/qa-engineer.md
        """))
        return path

    def test_minimal_config_loads(self, tmp_path: Path):
        path = self._write_minimal_yaml(tmp_path)
        cfg = load_department_config(path)
        assert cfg.name == "qa"
        assert cfg.zone == 4
        assert cfg.manager.name == "qa-chief"
        assert cfg.manager.model == "anthropic:claude-opus-4-6"
        assert len(cfg.employees) == 1
        assert cfg.employees[0].name == "qa-engineer"
        assert cfg.employees[0].model == "anthropic:claude-sonnet-4-6"

    def test_extended_config_fields(self, tmp_path: Path):
        path = tmp_path / "qa.yaml"
        path.write_text(textwrap.dedent("""\
            team:
              name: qa
              zone: 4
              description: QA department

              constraints:
                cost_limit_usd: 1.5
                timeout_seconds: 300
                concurrency_limit: 2

              budget:
                daily_limit_usd: 3.0
                alert_thresholds: [0.5, 0.8]

              tools:
                common: [read_file, search_knowledge]
                department: [run_tests]
                per_employee:
                  security-auditor: [run_bandit]

              vapi:
                enabled: true
                model: gpt-4o-mini
                voice: shimmer
                greeting: "Bumba QA, how can I help?"
                tools: [get_pr_status]

              chief:
                name: qa-chief
                model: opus-4.6

              workers:
                - name: security-auditor
                  model: sonnet-4.6
        """))
        cfg = load_department_config(path)
        assert cfg.constraints.cost_limit_usd == 1.5
        assert cfg.constraints.timeout_seconds == 300
        assert cfg.budget.daily_limit_usd == 3.0
        assert cfg.budget.alert_thresholds == (0.5, 0.8)
        assert cfg.common_tools == ("read_file", "search_knowledge")
        assert cfg.department_tools == ("run_tests",)
        assert cfg.per_employee_tools == {"security-auditor": ("run_bandit",)}
        assert cfg.vapi.enabled is True
        assert cfg.vapi.greeting == "Bumba QA, how can I help?"
        assert cfg.vapi.tools == ("get_pr_status",)

    def test_missing_team_key_raises(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("other_key: foo")
        with pytest.raises(InvalidConfigError):
            load_department_config(path)

    def test_missing_chief_raises(self, tmp_path: Path):
        path = tmp_path / "nochief.yaml"
        path.write_text(textwrap.dedent("""\
            team:
              name: qa
              zone: 4
              description: QA
              workers: []
        """))
        with pytest.raises(InvalidConfigError, match="chief"):
            load_department_config(path)
