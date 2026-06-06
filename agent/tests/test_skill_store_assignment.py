"""Tests for E4.8 — skill assignment model in SkillStore."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.skill_store import SkillStore
from bridge.skill_journey import SkillJourney


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> SkillStore:
    return SkillStore(":memory:")


@pytest.fixture
def journey(store: SkillStore) -> SkillJourney:
    return SkillJourney(store)


# ---------------------------------------------------------------------------
# Migration + schema
# ---------------------------------------------------------------------------


def test_assignment_column_exists(store: SkillStore) -> None:
    """migration ran: assignment column present in skill_journey."""
    cols = store._conn.execute(
        "PRAGMA table_info(skill_journey)"
    ).fetchall()
    col_names = {row[1] for row in cols}
    assert "assignment" in col_names


def test_migration_is_idempotent() -> None:
    """Opening SkillStore twice on same in-memory DB does not fail."""
    store1 = SkillStore(":memory:")
    version_after_init = store1._conn.execute("PRAGMA user_version").fetchone()[0]
    # Simulate a second init on same connection (tests the guard path)
    store1._apply_migrations()
    store1._apply_migrations()
    # Idempotency contract: user_version is unchanged after re-running,
    # so the guard short-circuited rather than re-applying the migration.
    final_version = store1._conn.execute("PRAGMA user_version").fetchone()[0]
    assert final_version == version_after_init


def test_seeded_skills_default_to_main(store: SkillStore) -> None:
    """Canonical seeds (fix-test, review-pr, ship-feature) get assignment='main'."""
    for name in ["fix-test", "review-pr", "ship-feature"]:
        assert store.get_assignment(name) == "main"


# ---------------------------------------------------------------------------
# set_assignment / get_assignment
# ---------------------------------------------------------------------------


def test_set_and_get_assignment(store: SkillStore, journey: SkillJourney) -> None:
    journey.get_or_create("my-skill")
    store.set_assignment("my-skill", "global")
    assert store.get_assignment("my-skill") == "global"


def test_get_assignment_nonexistent_returns_none(store: SkillStore) -> None:
    assert store.get_assignment("no-such-skill") is None


def test_set_assignment_team_name(store: SkillStore, journey: SkillJourney) -> None:
    journey.get_or_create("design-skill")
    store.set_assignment("design-skill", "design")
    assert store.get_assignment("design-skill") == "design"


# ---------------------------------------------------------------------------
# skills_for_team
# ---------------------------------------------------------------------------


def test_skills_for_team_returns_team_match(store: SkillStore, journey: SkillJourney) -> None:
    journey.get_or_create("qa-skill")
    store.set_assignment("qa-skill", "qa")
    results = store.skills_for_team("qa")
    names = {r.name for r in results}
    assert "qa-skill" in names


def test_skills_for_team_returns_global(store: SkillStore, journey: SkillJourney) -> None:
    journey.get_or_create("cross-cutting")
    store.set_assignment("cross-cutting", "global")
    # global skills appear under any team query
    for team in ("design", "qa", "ops"):
        names = {r.name for r in store.skills_for_team(team)}
        assert "cross-cutting" in names


def test_skills_for_team_excludes_other_team(store: SkillStore, journey: SkillJourney) -> None:
    journey.get_or_create("design-only")
    store.set_assignment("design-only", "design")
    # Should NOT appear under qa
    names = {r.name for r in store.skills_for_team("qa")}
    assert "design-only" not in names


def test_skills_for_team_excludes_main_assignment(store: SkillStore, journey: SkillJourney) -> None:
    journey.get_or_create("main-only-skill")
    # assignment stays 'main' (default)
    names = {r.name for r in store.skills_for_team("design")}
    assert "main-only-skill" not in names


def test_skills_for_team_combines_team_and_global(
    store: SkillStore, journey: SkillJourney
) -> None:
    journey.get_or_create("global-skill")
    journey.get_or_create("design-specific")
    store.set_assignment("global-skill", "global")
    store.set_assignment("design-specific", "design")
    results = {r.name for r in store.skills_for_team("design")}
    assert "global-skill" in results
    assert "design-specific" in results


# ---------------------------------------------------------------------------
# new_skill.py --assignment integration
# ---------------------------------------------------------------------------

import scripts.new_skill as mod_new_skill
from scripts._scaffolding_templates import _SkillFrontmatterSchema


def _run_new_skill(argv: list[str], tmp_path: Path) -> int:
    with (
        patch.object(mod_new_skill, "SKILLS_DIR", tmp_path / "skills"),
        patch.object(mod_new_skill, "CHECKLIST_DIR", tmp_path / "checklists"),
        patch.object(mod_new_skill, "REPO_ROOT", tmp_path),
        patch.object(mod_new_skill, "TEAMS_DIR", tmp_path / "teams"),
    ):
        # Pre-create teams dir with a design team so assignment='design' is valid
        (tmp_path / "teams").mkdir(parents=True, exist_ok=True)
        (tmp_path / "teams" / "design.yaml").write_text("team:\n  name: design\n  zone: 4\n")
        return mod_new_skill.main(argv)


def test_assignment_main_in_frontmatter(tmp_path: Path) -> None:
    _run_new_skill(["sk", "--description", "Does sk things for operators", "--assignment", "main"], tmp_path)
    content = (tmp_path / "skills" / "sk.md").read_text()
    assert "assignment: main" in content


def test_assignment_global_in_frontmatter(tmp_path: Path) -> None:
    _run_new_skill(["gsk", "--description", "Global skill for all teams here"], tmp_path)
    # Default is main; let's test explicit global
    _run_new_skill(["gsk2", "--description", "Global skill two for teams", "--assignment", "global"], tmp_path)
    content = (tmp_path / "skills" / "gsk2.md").read_text()
    assert "assignment: global" in content


def test_assignment_team_name_in_frontmatter(tmp_path: Path) -> None:
    _run_new_skill(
        ["dsk", "--description", "Design team specific skill here", "--assignment", "design"],
        tmp_path,
    )
    content = (tmp_path / "skills" / "dsk.md").read_text()
    assert "assignment: design" in content


def test_invalid_assignment_aborts(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_new_skill(
            ["bad", "--description", "Bad assignment test skill here", "--assignment", "nonexistent-team"],
            tmp_path,
        )
    assert exc_info.value.code == 1


def test_generated_frontmatter_assignment_passes_schema(tmp_path: Path) -> None:
    import yaml

    _run_new_skill(
        ["asgn", "--description", "Assignment validation test skill here", "--assignment", "global"],
        tmp_path,
    )
    content = (tmp_path / "skills" / "asgn.md").read_text()
    lines = content.splitlines()
    fm_lines = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)
    raw = yaml.safe_load("\n".join(fm_lines)) or {}
    schema = _SkillFrontmatterSchema.model_validate(raw)
    assert schema.assignment == "global"
