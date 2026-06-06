"""Tests for D7.13 #1425 — validate_team_yaml.py.

Two surface areas:
- Schema validation (delegated to teams._config; just confirm errors propagate)
- Cross-reference checks: per-employee tool keys, expertise/system_prompt path
  existence (advisory by default, error under --strict)
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import scripts.validate_team_yaml as mod


def _write_team_yaml(path: Path, overrides: dict | None = None) -> Path:
    """Write a minimal valid team YAML at `path`. Apply nested overrides
    via dict-merge so each test can mutate just the field it cares about.
    """
    base: dict = {
        "team": {
            "name": "test-team",
            "zone": 4,
            "description": "Smoke test team.",
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
                "name": "test-chief",
                "model": "opus-4.6",
                "system_prompt": "",  # default empty — no path check
                "expertise": "",
            },
            "workers": [],
        },
        "mcp_servers": [],
    }
    if overrides:
        # Deep-merge "team" sub-dict only — sufficient for these tests.
        for k, v in overrides.items():
            if k == "team" and isinstance(v, dict):
                base["team"].update(v)
            else:
                base[k] = v
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return path


@pytest.fixture()
def fake_repo(tmp_path: Path, monkeypatch):
    """Stage a fake repo with the teams dir."""
    teams_dir = tmp_path / "agent" / "config" / "teams"
    teams_dir.mkdir(parents=True)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "TEAMS_DIR", teams_dir)
    monkeypatch.setattr(mod, "TEMPLATE_PATH", teams_dir / "_template.yaml")
    return tmp_path


# ---------------------------------------------------------------------------
# Schema validation surface
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_valid_minimal_team_passes(self, fake_repo: Path):
        yaml_path = _write_team_yaml(fake_repo / "agent/config/teams/test-team.yaml")
        report = mod.validate_team(yaml_path)
        assert report.ok, f"unexpected errors: {report.errors}"

    def test_unknown_field_surfaces_as_schema_error(self, fake_repo: Path):
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={"team": {"bogus_field": "hello"}},
        )
        report = mod.validate_team(yaml_path)
        assert not report.ok
        assert any("schema" in e for e in report.errors), report.errors

    def test_missing_yaml_aborts(self, fake_repo: Path):
        with pytest.raises(SystemExit) as exc:
            mod.main(["does-not-exist"])
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Cross-reference: per_employee key validity
# ---------------------------------------------------------------------------


class TestPerEmployeeKeys:
    def test_valid_per_employee_key_passes(self, fake_repo: Path):
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "tools": {
                        "common": [],
                        "department": [],
                        "per_employee": {"worker-one": ["tool-a"]},
                    },
                    "workers": [
                        {"name": "worker-one", "model": "sonnet-4.6"},
                    ],
                }
            },
        )
        report = mod.validate_team(yaml_path)
        assert report.ok, f"unexpected errors: {report.errors}"

    def test_unknown_per_employee_key_errors(self, fake_repo: Path):
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "tools": {
                        "common": [],
                        "department": [],
                        "per_employee": {"typo-name": ["tool-a"]},
                    },
                    "workers": [
                        {"name": "actual-worker", "model": "sonnet-4.6"},
                    ],
                }
            },
        )
        report = mod.validate_team(yaml_path)
        assert not report.ok
        joined = " | ".join(report.errors)
        assert "per_employee" in joined
        assert "typo-name" in joined


# ---------------------------------------------------------------------------
# Cross-reference: expertise / system_prompt path existence
# ---------------------------------------------------------------------------


class TestPathExistence:
    def test_existing_expertise_file_passes(self, fake_repo: Path):
        expertise_path = fake_repo / "agent" / "config" / "expertise" / "updatable" / "test-chief.md"
        expertise_path.parent.mkdir(parents=True, exist_ok=True)
        expertise_path.write_text("# expertise stub", encoding="utf-8")

        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "chief": {
                        "name": "test-chief",
                        "model": "opus-4.6",
                        "expertise": "agent/config/expertise/updatable/test-chief.md",
                        "system_prompt": "",
                    }
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=True)
        assert report.ok, f"unexpected errors: {report.errors}"

    def test_missing_expertise_warns_by_default(self, fake_repo: Path):
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "chief": {
                        "name": "test-chief",
                        "model": "opus-4.6",
                        "expertise": "agent/config/expertise/updatable/never.md",
                        "system_prompt": "",
                    }
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=False)
        assert report.ok  # advisory mode — warnings, not errors
        assert any("never.md" in w for w in report.warnings), report.warnings

    def test_missing_expertise_errors_under_strict(self, fake_repo: Path):
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "chief": {
                        "name": "test-chief",
                        "model": "opus-4.6",
                        "expertise": "agent/config/expertise/updatable/never.md",
                        "system_prompt": "",
                    }
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=True)
        assert not report.ok
        assert any("never.md" in e for e in report.errors), report.errors

    def test_missing_system_prompt_for_worker_errors_under_strict(self, fake_repo: Path):
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "workers": [
                        {
                            "name": "worker-one",
                            "model": "sonnet-4.6",
                            "system_prompt": "agent/config/agents/zone4/test-team/worker-one.md",
                        }
                    ]
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=True)
        assert not report.ok
        assert any("worker-one" in e for e in report.errors), report.errors


# ---------------------------------------------------------------------------
# CLI surface — --all + --check-template + exit codes
# ---------------------------------------------------------------------------


class TestCLI:
    def test_all_with_one_valid_team_exits_zero(self, fake_repo: Path, capsys):
        _write_team_yaml(fake_repo / "agent/config/teams/team-a.yaml")
        rc = mod.main(["--all"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "team-a" in out
        assert "1/1 OK" in out

    def test_all_skips_underscore_files(self, fake_repo: Path, capsys):
        _write_team_yaml(fake_repo / "agent/config/teams/team-a.yaml")
        # Underscore-prefixed files (e.g. _template.yaml) must be skipped
        # by --all, mirroring the registry discovery convention.
        _write_team_yaml(fake_repo / "agent/config/teams/_template.yaml")
        rc = mod.main(["--all"])
        out = capsys.readouterr().out
        assert "team-a" in out
        assert "_template" not in out
        assert rc == 0

    def test_check_template_succeeds_on_valid_template(self, fake_repo: Path, capsys):
        _write_team_yaml(fake_repo / "agent/config/teams/_template.yaml")
        rc = mod.main(["--check-template"])
        assert rc == 0

    def test_check_template_fails_when_missing(self, fake_repo: Path, capsys):
        # Don't write a template; --check-template should fail with a
        # clear "not found" message and exit non-zero.
        rc = mod.main(["--check-template"])
        assert rc == 1


# ---------------------------------------------------------------------------
# Sprint P3.6 — delegation floor + chief roster placeholder
# ---------------------------------------------------------------------------


class TestDelegationFloor:
    """`expected_min_specialists` must be > 0 for delegate-mode teams.

    Default 0 disables Gate 8 in `teams._verify` which lets the chief
    skip all delegations and direct-answer. For production teams that
    declare workers, that is almost always a misconfiguration. P3.6
    surfaces this as an advisory warning under both default and strict
    modes (Gate-8 activation per team requires companion test updates,
    sequenced as a follow-up).
    """

    def test_delegate_mode_zero_floor_warns_by_default(self, fake_repo: Path):
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "workers": [
                        {"name": "worker-one", "model": "sonnet-4.6"},
                    ],
                    # expected_min_specialists left at default (0) — should warn
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=False)
        assert report.ok  # advisory mode — warnings, not errors
        assert any(
            "delegation_floor" in w and "expected_min_specialists is 0" in w
            for w in report.warnings
        ), report.warnings

    def test_delegate_mode_zero_floor_errors_under_strict(self, fake_repo: Path):
        """#1645 strict-floor activation (2026-05-12): zero-floor delegate-mode
        teams MUST error under --strict. Default mode preserves the advisory
        warning behaviour for back-compat (see ``test_delegate_mode_zero_floor_warns_by_default``)."""
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "workers": [
                        {"name": "worker-one", "model": "sonnet-4.6"},
                    ],
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=True)
        assert not report.ok, "strict-floor should fail validation under --strict"
        assert any(
            "delegation_floor" in e and "expected_min_specialists is 0" in e
            for e in report.errors
        ), report.errors

    def test_delegate_mode_with_positive_floor_passes(self, fake_repo: Path):
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "constraints": {
                        "cost_limit_usd": 1.0,
                        "timeout_seconds": 300,
                        "concurrency_limit": 2,
                        "usage_limits": {
                            "request_limit": 10,
                            "request_token_limit": 10000,
                            "response_token_limit": 5000,
                        },
                        "expected_min_specialists": 1,
                    },
                    "workers": [
                        {"name": "worker-one", "model": "sonnet-4.6"},
                    ],
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=True)
        # No delegation_floor diagnostic should fire
        all_messages = report.errors + report.warnings
        assert not any("delegation_floor" in m for m in all_messages), all_messages

    def test_single_director_team_exempt_from_floor(self, fake_repo: Path):
        """Teams with `workers: []` are single-director architectures
        and don't need a delegation floor (there's no one to delegate to)."""
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={"team": {"workers": []}},
        )
        report = mod.validate_team(yaml_path, strict=True)
        all_messages = report.errors + report.warnings
        assert not any("delegation_floor" in m for m in all_messages), all_messages


class TestRosterPlaceholderCheck:
    """Delegate-mode teams must have a chief prompt with ``{{ROSTER}}``."""

    def _write_chief_prompt(
        self, fake_repo: Path, *, with_placeholder: bool, use_agent_prefix: bool
    ) -> str:
        """Stage a chief prompt file at the expected location.

        Returns the relative path string suitable for the YAML's
        `system_prompt:` field.
        """
        rel = "config/agents/zone4/test-team/test-chief.md"
        # Validator looks for `agent/<rel>` first (canonical), then `<rel>`
        # (the repo-root shadow). Stage the canonical so it's the one read.
        canonical = fake_repo / "agent" / rel
        canonical.parent.mkdir(parents=True, exist_ok=True)
        body = (
            "# Test Chief\n\nYou are the chief.\n\n"
            + ("{{ROSTER}}\n\n" if with_placeholder else "")
            + "Now go.\n"
        )
        canonical.write_text(body, encoding="utf-8")
        # When `use_agent_prefix=True`, the YAML declares the path as
        # `agent/config/...` (validator resolves directly). When False,
        # the YAML declares `config/...` (validator must rebase under
        # `agent/`).
        return f"agent/{rel}" if use_agent_prefix else rel

    def test_chief_prompt_with_placeholder_passes(self, fake_repo: Path):
        sp = self._write_chief_prompt(
            fake_repo, with_placeholder=True, use_agent_prefix=False
        )
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "constraints": {
                        "cost_limit_usd": 1.0,
                        "timeout_seconds": 300,
                        "concurrency_limit": 2,
                        "usage_limits": {
                            "request_limit": 10,
                            "request_token_limit": 10000,
                            "response_token_limit": 5000,
                        },
                        "expected_min_specialists": 1,
                    },
                    "chief": {
                        "name": "test-chief",
                        "model": "opus-4.6",
                        "system_prompt": sp,
                        "expertise": "",
                    },
                    "workers": [
                        {"name": "worker-one", "model": "sonnet-4.6"},
                    ],
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=True)
        all_messages = report.errors + report.warnings
        assert not any(
            "roster_placeholder" in m for m in all_messages
        ), all_messages

    def test_chief_prompt_missing_placeholder_warns_by_default(
        self, fake_repo: Path
    ):
        sp = self._write_chief_prompt(
            fake_repo, with_placeholder=False, use_agent_prefix=False
        )
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "constraints": {
                        "cost_limit_usd": 1.0,
                        "timeout_seconds": 300,
                        "concurrency_limit": 2,
                        "usage_limits": {
                            "request_limit": 10,
                            "request_token_limit": 10000,
                            "response_token_limit": 5000,
                        },
                        "expected_min_specialists": 1,
                    },
                    "chief": {
                        "name": "test-chief",
                        "model": "opus-4.6",
                        "system_prompt": sp,
                        "expertise": "",
                    },
                    "workers": [
                        {"name": "worker-one", "model": "sonnet-4.6"},
                    ],
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=False)
        assert report.ok  # advisory mode — warnings, not errors
        assert any("roster_placeholder" in w for w in report.warnings), (
            report.warnings
        )

    def test_chief_prompt_missing_placeholder_warns_under_strict(
        self, fake_repo: Path
    ):
        """P3.6 roster_placeholder stays advisory even under --strict
        (see validator module docstring rule 5 for rationale — the
        runtime's _inject_roster_into_prompt degrades gracefully with
        an end-of-prompt append + logged WARN).

        Uses ``use_agent_prefix=True`` so the file-existence check (rule
        3) does not fail — we want to isolate the placeholder warning.
        """
        sp = self._write_chief_prompt(
            fake_repo, with_placeholder=False, use_agent_prefix=True
        )
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "constraints": {
                        "cost_limit_usd": 1.0,
                        "timeout_seconds": 300,
                        "concurrency_limit": 2,
                        "usage_limits": {
                            "request_limit": 10,
                            "request_token_limit": 10000,
                            "response_token_limit": 5000,
                        },
                        "expected_min_specialists": 1,
                    },
                    "chief": {
                        "name": "test-chief",
                        "model": "opus-4.6",
                        "system_prompt": sp,
                        "expertise": "",
                    },
                    "workers": [
                        {"name": "worker-one", "model": "sonnet-4.6"},
                    ],
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=True)
        assert report.ok, report.errors
        assert any(
            "roster_placeholder" in w for w in report.warnings
        ), report.warnings

    def test_single_director_team_exempt_from_placeholder_check(
        self, fake_repo: Path
    ):
        """Teams with `workers: []` skip the placeholder check too."""
        sp = self._write_chief_prompt(
            fake_repo, with_placeholder=False, use_agent_prefix=False
        )
        yaml_path = _write_team_yaml(
            fake_repo / "agent/config/teams/test-team.yaml",
            overrides={
                "team": {
                    "chief": {
                        "name": "test-chief",
                        "model": "opus-4.6",
                        "system_prompt": sp,
                        "expertise": "",
                    },
                    "workers": [],
                }
            },
        )
        report = mod.validate_team(yaml_path, strict=True)
        all_messages = report.errors + report.warnings
        assert not any(
            "roster_placeholder" in m for m in all_messages
        ), all_messages
