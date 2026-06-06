"""Tests for issue #14: Skill frontmatter audit script."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path


# Import from the script directly
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from audit_skill_frontmatter import (
    audit_skill_file,
    find_skill_files,
    has_gotchas_section,
    parse_frontmatter,
    run_audit,
    format_text_report,
)


# ── parse_frontmatter ──

class TestParseFrontmatter:
    def test_parses_valid_frontmatter(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: my-skill\ndescription: A good description here.\n---\n# Title\n")
        fm = parse_frontmatter(f.read_text())
        assert fm is not None
        assert fm["name"] == "my-skill"
        assert fm["description"] == "A good description here."

    def test_no_frontmatter(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.write_text("# Title\nNo frontmatter here.\n")
        fm = parse_frontmatter(f.read_text())
        assert fm is None

    def test_unclosed_frontmatter(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: skill\ndescription: something\n# missing closing ---\n")
        fm = parse_frontmatter(f.read_text())
        assert fm is None

    def test_empty_frontmatter(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.write_text("---\n---\n# Title\n")
        fm = parse_frontmatter(f.read_text())
        assert fm == {}


# ── has_gotchas_section ──

class TestHasGotchasSection:
    def test_has_gotchas(self):
        content = "# Skill\n\n## Gotchas\n\n- Watch out for X\n"
        assert has_gotchas_section(content) is True

    def test_no_gotchas(self):
        content = "# Skill\n\n## When to Use\n\n- Use when X\n"
        assert has_gotchas_section(content) is False

    def test_gotchas_case_sensitive(self):
        content = "## gotchas\n"  # lowercase — should NOT match
        assert has_gotchas_section(content) is False

    def test_gotchas_must_be_heading(self):
        content = "Some text about Gotchas but not a heading\n"
        assert has_gotchas_section(content) is False


# ── audit_skill_file ──

class TestAuditSkillFile:
    def _write_skill(self, path: Path, content: str) -> Path:
        skill_dir = path / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(content)
        return skill_file

    def test_passing_skill(self, tmp_path):
        content = textwrap.dedent("""\
            ---
            name: my-skill
            description: This is a long enough description that will pass validation checks.
            ---
            # My Skill
            ## Gotchas
            - Be careful of X.
        """)
        skill_file = self._write_skill(tmp_path, content)
        result = audit_skill_file(skill_file)
        assert result["passing"] is True
        assert result["missing"] == []

    def test_missing_name(self, tmp_path):
        content = "---\ndescription: A good long description here.\n---\n# Skill\n"
        skill_file = self._write_skill(tmp_path, content)
        result = audit_skill_file(skill_file)
        assert result["passing"] is False
        assert "name" in result["missing"]

    def test_missing_description(self, tmp_path):
        content = "---\nname: my-skill\n---\n# Skill\n"
        skill_file = self._write_skill(tmp_path, content)
        result = audit_skill_file(skill_file)
        assert result["passing"] is False
        assert "description" in result["missing"]

    def test_vague_description_warning(self, tmp_path):
        content = "---\nname: my-skill\ndescription: Too short.\n---\n# Skill\n"
        skill_file = self._write_skill(tmp_path, content)
        result = audit_skill_file(skill_file)
        assert result["passing"] is True  # vague is a warning, not an error
        assert any("vague" in w for w in result["warnings"])

    def test_no_frontmatter_fails(self, tmp_path):
        content = "# No Frontmatter\nJust content.\n"
        skill_file = self._write_skill(tmp_path, content)
        result = audit_skill_file(skill_file)
        assert result["passing"] is False
        assert any("frontmatter" in m for m in result["missing"])

    def test_missing_gotchas_is_warning(self, tmp_path):
        content = textwrap.dedent("""\
            ---
            name: my-skill
            description: This is a good long description for this skill.
            ---
            # My Skill
        """)
        skill_file = self._write_skill(tmp_path, content)
        result = audit_skill_file(skill_file)
        assert any("Gotchas" in w for w in result["warnings"])

    def test_recommended_fields_warning(self, tmp_path):
        content = textwrap.dedent("""\
            ---
            name: my-skill
            description: A good description for this skill right here.
            ---
            # My Skill
            ## Gotchas
            - Nothing.
        """)
        skill_file = self._write_skill(tmp_path, content)
        result = audit_skill_file(skill_file)
        # Should warn about missing recommended fields
        assert any("type" in w or "recommended" in w for w in result["warnings"])


# ── find_skill_files ──

class TestFindSkillFiles:
    def test_finds_skill_md(self, tmp_path):
        (tmp_path / "skill-a").mkdir()
        (tmp_path / "skill-a" / "SKILL.md").write_text("---\nname: a\n---\n")
        (tmp_path / "skill-b").mkdir()
        (tmp_path / "skill-b" / "SKILL.md").write_text("---\nname: b\n---\n")
        files = find_skill_files([tmp_path])
        assert len(files) == 2

    def test_ignores_non_skill_files(self, tmp_path):
        (tmp_path / "skill-a").mkdir()
        (tmp_path / "skill-a" / "README.md").write_text("just a readme")
        files = find_skill_files([tmp_path])
        assert len(files) == 0

    def test_missing_path_skipped(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        files = find_skill_files([missing])
        assert files == []


# ── run_audit + format_text_report ──

class TestRunAudit:
    def test_run_audit_counts(self, tmp_path):
        good = tmp_path / "good-skill"
        good.mkdir()
        (good / "SKILL.md").write_text(
            "---\nname: good-skill\ndescription: A long enough description for this skill.\n---\n## Gotchas\n- X.\n"
        )
        bad = tmp_path / "bad-skill"
        bad.mkdir()
        (bad / "SKILL.md").write_text("# No frontmatter\n")
        report = run_audit([tmp_path])
        assert report["total"] == 2
        assert report["passing"] == 1
        assert report["with_issues"] == 1

    def test_json_output_validates(self, tmp_path):
        good = tmp_path / "good"
        good.mkdir()
        (good / "SKILL.md").write_text("---\nname: good\ndescription: A description that is long enough here.\n---\n## Gotchas\n- X.\n")
        report = run_audit([tmp_path])
        # Must be JSON-serializable
        json_str = json.dumps(report)
        assert json.loads(json_str)["total"] == 1

    def test_format_text_report_includes_summary(self, tmp_path):
        (tmp_path / "s").mkdir()
        (tmp_path / "s" / "SKILL.md").write_text("---\nname: s\ndescription: Short.\n---\n")
        report = run_audit([tmp_path])
        text = format_text_report(report)
        assert "skills scanned" in text

    def test_format_text_report_lists_issues(self, tmp_path):
        (tmp_path / "s").mkdir()
        (tmp_path / "s" / "SKILL.md").write_text("# No frontmatter\n")
        report = run_audit([tmp_path])
        text = format_text_report(report)
        assert "Issues" in text or "missing" in text
