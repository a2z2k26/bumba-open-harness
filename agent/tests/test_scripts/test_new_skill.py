"""Tests for E4.7 — new_skill.py scaffold command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.new_skill as mod
from scripts._scaffolding_templates import (
    SKILL_BUNDLE,
    _SkillFrontmatterSchema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(argv: list[str], tmp_path: Path) -> int:
    """Run main() with SKILLS_DIR and CHECKLIST_DIR patched to tmp_path."""
    with (
        patch.object(mod, "SKILLS_DIR", tmp_path / "skills"),
        patch.object(mod, "CHECKLIST_DIR", tmp_path / "checklists"),
        patch.object(mod, "REPO_ROOT", tmp_path),
    ):
        return mod.main(argv)


# ---------------------------------------------------------------------------
# _SkillBundle unit tests
# ---------------------------------------------------------------------------


class TestSkillBundle:
    def test_standalone_path(self):
        result = SKILL_BUNDLE.render(name="foo", description="Does foo things for operators")
        assert len(result.files) == 1
        path, _ = result.files[0]
        assert path == "agent/config/skills/foo.md"

    def test_directory_form_path(self):
        result = SKILL_BUNDLE.render(name="bar", description="Bar skill", directory_form=True)
        path, _ = result.files[0]
        assert path == "agent/config/skills/bar/SKILL.md"

    def test_name_substituted_in_content(self):
        result = SKILL_BUNDLE.render(name="my-skill", description="Does things")
        _, content = result.files[0]
        assert "my-skill" in content

    def test_description_substituted_in_content(self):
        result = SKILL_BUNDLE.render(name="x", description="Unique description text here")
        _, content = result.files[0]
        assert "Unique description text here" in content

    def test_frontmatter_delimiter_present(self):
        result = SKILL_BUNDLE.render(name="x", description="Any description at all")
        _, content = result.files[0]
        lines = content.splitlines()
        assert lines[0] == "---"
        assert "---" in lines[1:]

    def test_returns_bundle_result_with_one_file(self):
        from scripts._scaffolding_templates import BundleResult

        result = SKILL_BUNDLE.render(name="z", description="Something")
        assert isinstance(result, BundleResult)
        assert len(result.files) == 1


# ---------------------------------------------------------------------------
# _SkillFrontmatterSchema unit tests
# ---------------------------------------------------------------------------


class TestSkillFrontmatterSchema:
    def test_minimal_valid(self):
        schema = _SkillFrontmatterSchema.model_validate(
            {"name": "foo", "description": "Does foo"}
        )
        assert schema.name == "foo"

    def test_allowed_tools_alias(self):
        schema = _SkillFrontmatterSchema.model_validate(
            {"name": "x", "description": "y", "allowed-tools": "Bash, Read"}
        )
        assert schema.allowed_tools == "Bash, Read"  # string, not list — matches repo YAML convention

    def test_extra_fields_allowed(self):
        schema = _SkillFrontmatterSchema.model_validate(
            {"name": "x", "description": "y", "user-invokable": True}
        )
        assert schema.name == "x"

    def test_missing_name_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _SkillFrontmatterSchema.model_validate({"description": "missing name"})


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


class TestNewSkillMain:
    def test_standalone_success(self, tmp_path: Path):
        rc = _run(["my-skill", "--description", "Does my-skill things properly"], tmp_path)
        assert rc == 0
        assert (tmp_path / "skills" / "my-skill.md").exists()

    def test_directory_form_success(self, tmp_path: Path):
        rc = _run(
            ["dir-skill", "--description", "Does dir-skill things", "--directory"], tmp_path
        )
        assert rc == 0
        assert (tmp_path / "skills" / "dir-skill" / "SKILL.md").exists()

    def test_generated_file_contains_name(self, tmp_path: Path):
        _run(["alpha", "--description", "Alpha skill does alpha"], tmp_path)
        content = (tmp_path / "skills" / "alpha.md").read_text()
        assert "alpha" in content

    def test_duplicate_standalone_aborts(self, tmp_path: Path):
        (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
        (tmp_path / "skills" / "existing.md").write_text("---\nname: existing\n---\n")
        with pytest.raises(SystemExit) as exc_info:
            _run(["existing", "--description", "Already there"], tmp_path)
        assert exc_info.value.code == 1

    def test_duplicate_directory_aborts(self, tmp_path: Path):
        (tmp_path / "skills" / "existing-dir").mkdir(parents=True)
        with pytest.raises(SystemExit) as exc_info:
            _run(["existing-dir", "--description", "Already there"], tmp_path)
        assert exc_info.value.code == 1

    def test_checklist_file_written(self, tmp_path: Path):
        _run(["beta", "--description", "Beta skill for testing purposes"], tmp_path)
        checklist = tmp_path / "checklists" / "beta-skill-checklist.md"
        assert checklist.exists()
        assert "beta" in checklist.read_text()

    def test_generated_frontmatter_passes_pydantic(self, tmp_path: Path):
        """End-to-end: generated file roundtrips through _SkillFrontmatterSchema."""
        import yaml

        _run(["gamma", "--description", "Gamma skill for validation tests"], tmp_path)
        content = (tmp_path / "skills" / "gamma.md").read_text()

        lines = content.splitlines()
        assert lines[0] == "---"
        fm_lines = []
        for line in lines[1:]:
            if line.strip() == "---":
                break
            fm_lines.append(line)

        raw = yaml.safe_load("\n".join(fm_lines)) or {}
        schema = _SkillFrontmatterSchema.model_validate(raw)
        assert schema.name == "gamma"

    def test_discovery_smoke(self, tmp_path: Path):
        """Generated skill is discoverable (file exists at expected path)."""
        _run(["smoke-test-skill", "--description", "Smoke test skill for discovery"], tmp_path)
        skill_path = tmp_path / "skills" / "smoke-test-skill.md"
        assert skill_path.exists()
        content = skill_path.read_text()
        assert content.startswith("---\n")
        assert "smoke-test-skill" in content
