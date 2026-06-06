"""Tests for D7.13 #1425 — scaffold_doctor.py.

End-to-end smoke: scaffold a fake team with a missing expertise file,
run doctor, confirm the gap is identified with an actionable fix command.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import scripts.scaffold_doctor as doctor
import scripts.validate_team_yaml as vmod


def _write_team_yaml(path: Path, overrides: dict | None = None) -> Path:
    """Minimal valid team YAML — same shape as the validator tests."""
    base: dict = {
        "team": {
            "name": "doctor-test",
            "zone": 4,
            "description": "Smoke test team for the doctor.",
            "constraints": {
                "cost_limit_usd": 1.0,
                "timeout_seconds": 300,
                "concurrency_limit": 2,
                "usage_limits": {
                    "request_limit": 10,
                    "request_token_limit": 10000,
                    "response_token_limit": 5000,
                },
            },
            "budget": {"daily_limit_usd": 2.0, "alert_thresholds": [0.5]},
            "tools": {"common": [], "department": [], "per_employee": {}},
            "vapi": {"enabled": False},
            "chief": {
                "name": "doctor-test-chief",
                "model": "opus-4.6",
                "system_prompt": "",
                "expertise": "",
            },
            "workers": [],
        },
        "mcp_servers": [],
    }
    if overrides:
        for k, v in overrides.items():
            if k == "team" and isinstance(v, dict):
                base["team"].update(v)
            else:
                base[k] = v
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return path


@pytest.fixture()
def fake_repo(tmp_path: Path, monkeypatch):
    teams_dir = tmp_path / "agent" / "config" / "teams"
    teams_dir.mkdir(parents=True)
    # Both modules look at REPO_ROOT / TEAMS_DIR / TEMPLATE_PATH
    monkeypatch.setattr(vmod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(vmod, "TEAMS_DIR", teams_dir)
    monkeypatch.setattr(vmod, "TEMPLATE_PATH", teams_dir / "_template.yaml")
    monkeypatch.setattr(doctor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(doctor, "TEAMS_DIR", teams_dir)
    monkeypatch.setattr(doctor, "TEMPLATE_PATH", teams_dir / "_template.yaml")
    return tmp_path


# ---------------------------------------------------------------------------
# Smoke flow — the issue's acceptance criterion #5
# ---------------------------------------------------------------------------


class TestSmokeScaffoldThenBreak:
    """Issue acceptance: scaffold → validate → test → break → doctor → identify."""

    def test_doctor_green_when_team_is_complete(self, fake_repo: Path):
        """A team with all referenced files on disk is doctor-ready."""
        # Plant the expertise + system_prompt files
        expertise_path = fake_repo / "agent/config/expertise/updatable/doctor-test-chief.md"
        expertise_path.parent.mkdir(parents=True, exist_ok=True)
        expertise_path.write_text("# expertise stub")
        sysprompt_path = fake_repo / "agent/config/agents/zone4/doctor-test/doctor-test-chief.md"
        sysprompt_path.parent.mkdir(parents=True, exist_ok=True)
        sysprompt_path.write_text("# sysprompt stub")

        # Plant the golden template so the field-set diff has something to compare
        _write_team_yaml(fake_repo / "agent/config/teams/_template.yaml")

        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/doctor-test.yaml",
            overrides={
                "team": {
                    "chief": {
                        "name": "doctor-test-chief",
                        "model": "opus-4.6",
                        "expertise": "agent/config/expertise/updatable/doctor-test-chief.md",
                        "system_prompt": "agent/config/agents/zone4/doctor-test/doctor-test-chief.md",
                    }
                }
            },
        )
        report = doctor.diagnose(yaml_path)
        assert report.ok, (
            f"unexpected errors: {report.validation.errors}; "
            f"missing fields: {report.missing_template_fields}"
        )

    def test_doctor_red_when_expertise_missing_with_fix_command(
        self, fake_repo: Path
    ):
        """The originating gap (a missing expertise file) is identified
        AND paired with a one-line shell fix command.
        """
        # Plant the template (so the field-set diff doesn't add noise)
        _write_team_yaml(fake_repo / "agent/config/teams/_template.yaml")

        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/doctor-test.yaml",
            overrides={
                "team": {
                    "chief": {
                        "name": "doctor-test-chief",
                        "model": "opus-4.6",
                        "expertise": "agent/config/expertise/updatable/missing.md",
                        "system_prompt": "",
                    }
                }
            },
        )
        report = doctor.diagnose(yaml_path)
        assert not report.ok
        # Validator surfaced the gap as an error (under --strict)
        assert any("missing.md" in e for e in report.validation.errors)
        # Doctor attached a `mkdir -p ... && touch ...` fix
        fix_commands = [f.command for f in report.fixes]
        assert any("mkdir -p" in c and "missing.md" in c for c in fix_commands), \
            f"expected mkdir/touch fix; got: {fix_commands}"


# ---------------------------------------------------------------------------
# Template field-set diff
# ---------------------------------------------------------------------------


class TestTemplateFieldDiff:
    def test_missing_required_field_is_reported(self, fake_repo: Path):
        """A team that omits a required top-level template key is flagged."""
        _write_team_yaml(fake_repo / "agent/config/teams/_template.yaml")

        # Write a YAML missing the `budget:` block — _diff_against_template
        # should catch it. Note: the schema would also reject this (budget
        # is required by _TeamSchema), but the diff layer reports it
        # as a *template-shape* gap with a copy-from-template fix.
        yaml_path = fake_repo / "agent/config/teams/doctor-test.yaml"
        raw_yaml = """
team:
  name: doctor-test
  zone: 4
  description: missing-budget
mcp_servers: []
"""
        yaml_path.write_text(raw_yaml, encoding="utf-8")

        report = doctor.diagnose(yaml_path)
        assert not report.ok
        # The schema-level error for the missing chief comes first; the
        # field-set diff should also flag absent template-required keys.
        assert "budget" in report.missing_template_fields or any(
            "budget" in e for e in report.validation.errors
        )

    def test_doctor_runs_without_template_present(self, fake_repo: Path, capsys):
        """If the template is missing, the doctor still runs the strict
        validator — it just skips the field-set diff with a clear warning.
        """
        # Note: NO template written
        yaml_path = _write_team_yaml(fake_repo / "agent/config/teams/doctor-test.yaml")
        report = doctor.diagnose(yaml_path)
        # Empty paths default to "" (skip), so this clean YAML is doctor-ready.
        assert report.ok
        captured = capsys.readouterr()
        assert "template not found" in captured.err.lower()


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------


class TestCLI:
    def test_main_exits_zero_on_ready_team(self, fake_repo: Path):
        _write_team_yaml(fake_repo / "agent/config/teams/_template.yaml")
        _write_team_yaml(fake_repo / "agent/config/teams/doctor-test.yaml")
        rc = doctor.main(["doctor-test"])
        assert rc == 0

    def test_main_exits_one_on_broken_team(self, fake_repo: Path):
        _write_team_yaml(fake_repo / "agent/config/teams/_template.yaml")
        _write_team_yaml(
            fake_repo / "agent/config/teams/doctor-test.yaml",
            overrides={
                "team": {
                    "chief": {
                        "name": "doctor-test-chief",
                        "model": "opus-4.6",
                        "expertise": "agent/config/expertise/updatable/missing.md",
                        "system_prompt": "",
                    }
                }
            },
        )
        rc = doctor.main(["doctor-test"])
        assert rc == 1
