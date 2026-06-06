"""Tests for agent.scripts.new_specialist and _scaffolding_templates.

All tests are offline-marked (no API key required).

Five test cases:
  1. test_new_specialist_success — 5 files written, correct content
  2. test_new_specialist_duplicate_aborts — idempotency check exits 1
  3. test_new_specialist_missing_team_aborts — team-not-found error path
  4. test_new_specialist_yaml_reparses — generated YAML is valid pyyaml
  5. test_new_specialist_single_domain_patterns_header — duplicate-header bug
     regression (A4 §"Structural problems #1")
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from scripts._scaffolding_templates import (
    DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER,
    DEFAULT_ZONE4_TOOL_CAPABLE_MODEL,
    expertise_for,
    worker_prompt_for,
)
from scripts.new_specialist import (
    _resolve_paths,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_TEAM_YAML = textwrap.dedent("""\
    team:
      name: {team}
      zone: 4
      description: Test team for scaffolding tests.

      chief:
        name: {team}-chief
        role: Orchestrates the team.
        model: {model}
        adapter: "{adapter}"
        expertise: agent/config/expertise/updatable/{team}-chief.md
        system_prompt: agent/config/agents/zone4/{team}/{team}-chief.md

      workers: []
""")


def _write_team_yaml(tmp_path: Path, team: str) -> Path:
    teams_dir = tmp_path / "agent" / "config" / "teams"
    teams_dir.mkdir(parents=True, exist_ok=True)
    p = teams_dir / f"{team}.yaml"
    p.write_text(
        MINIMAL_TEAM_YAML.format(
            team=team,
            model=DEFAULT_ZONE4_TOOL_CAPABLE_MODEL,
            adapter=DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER,
        ),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# Monkeypatch REPO_ROOT so scripts operate inside tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return a tmp_path that looks like repo root with the minimal scaffold."""
    import scripts.new_specialist as ns_mod

    monkeypatch.setattr(ns_mod, "REPO_ROOT", tmp_path)
    # Ensure scripts module also uses the patched root for _team_yaml_path
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Success path
# ---------------------------------------------------------------------------

@pytest.mark.offline
def test_new_specialist_success(fake_repo: Path):
    team = "testteam"
    name = "cool-specialist"
    _write_team_yaml(fake_repo, team)

    rc = main([team, name])

    assert rc == 0

    paths = _resolve_paths(team, name)
    # All 5 files must exist.
    expertise_path = fake_repo / f"agent/config/expertise/updatable/{name}.md"
    prompt_path = fake_repo / f"agent/config/agents/zone4/{team}/{name}.md"
    test_path = fake_repo / f"agent/tests/test_teams/test_specialist_{name.replace('-', '_')}.py"
    checklist_path = fake_repo / f"agent/data/scaffolding/{name}-checklist.md"
    team_yaml = fake_repo / f"agent/config/teams/{team}.yaml"

    assert expertise_path.exists(), "expertise file not written"
    assert prompt_path.exists(), "system prompt file not written"
    assert test_path.exists(), "placeholder test not written"
    assert checklist_path.exists(), "checklist file not written"

    # Team YAML must now include the worker block.
    raw = yaml.safe_load(team_yaml.read_text(encoding="utf-8"))
    workers = raw.get("team", {}).get("workers", []) or []
    names = [w.get("name") for w in workers]
    assert name in names, f"worker {name!r} not found in team YAML; workers={names}"
    worker = next(w for w in workers if w.get("name") == name)
    assert worker["model"] == DEFAULT_ZONE4_TOOL_CAPABLE_MODEL
    assert worker["adapter"] == DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER


# ---------------------------------------------------------------------------
# 2. Duplicate aborts (idempotency)
# ---------------------------------------------------------------------------

@pytest.mark.offline
def test_new_specialist_duplicate_aborts(fake_repo: Path):
    team = "testteam"
    name = "dupe-specialist"
    _write_team_yaml(fake_repo, team)

    # First call should succeed.
    rc1 = main([team, name])
    assert rc1 == 0

    # Second call must abort with exit 1.
    with pytest.raises(SystemExit) as exc_info:
        main([team, name])
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# 3. Missing team aborts
# ---------------------------------------------------------------------------

@pytest.mark.offline
def test_new_specialist_missing_team_aborts(fake_repo: Path):
    # Ensure teams dir exists but no yaml for "ghost-team".
    teams_dir = fake_repo / "agent" / "config" / "teams"
    teams_dir.mkdir(parents=True, exist_ok=True)
    (teams_dir / "existingteam.yaml").write_text("team:\n  name: existingteam\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main(["ghost-team", "any-specialist"])
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# 4. Generated YAML re-parses cleanly
# ---------------------------------------------------------------------------

@pytest.mark.offline
def test_new_specialist_yaml_reparses(fake_repo: Path):
    team = "yamlteam"
    name = "parse-specialist"
    _write_team_yaml(fake_repo, team)
    main([team, name])

    team_yaml = fake_repo / f"agent/config/teams/{team}.yaml"
    parsed = yaml.safe_load(team_yaml.read_text(encoding="utf-8"))
    assert parsed is not None
    workers = parsed.get("team", {}).get("workers") or []
    assert any(w.get("name") == name for w in workers), (
        f"worker {name!r} not in parsed YAML; workers={workers}"
    )


# ---------------------------------------------------------------------------
# 5. Single ## Domain Patterns header (A4 duplicate-header bug regression)
# ---------------------------------------------------------------------------

@pytest.mark.offline
def test_new_specialist_single_domain_patterns_header():
    content = expertise_for("test-agent", "test-team")
    count = content.count("## Domain Patterns")
    assert count == 1, (
        f"Expected exactly 1 '## Domain Patterns' header in expertise template, "
        f"got {count}. This is the A4 duplicate-header regression."
    )


# ---------------------------------------------------------------------------
# Template unit tests (no filesystem)
# ---------------------------------------------------------------------------

@pytest.mark.offline
def test_expertise_template_no_unresolved_placeholders():
    rendered = expertise_for("my-agent", "my-team")
    assert "{name}" not in rendered
    assert "{team}" not in rendered


@pytest.mark.offline
def test_expertise_template_frontmatter_agent_field():
    rendered = expertise_for("qa-hawk", "qa")
    assert "agent: qa-hawk" in rendered
    assert "department: qa" in rendered


@pytest.mark.offline
def test_worker_prompt_template_no_unresolved_placeholders():
    rendered = worker_prompt_for("my-agent", "my-team")
    assert "{name}" not in rendered
    assert "{team}" not in rendered
    assert "{role}" not in rendered


@pytest.mark.offline
def test_worker_prompt_template_name_present():
    rendered = worker_prompt_for("ops-specialist", "ops")
    assert "ops-specialist" in rendered
    assert "ops department" in rendered
