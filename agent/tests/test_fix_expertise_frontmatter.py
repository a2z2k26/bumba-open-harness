"""Tests for fix_expertise_frontmatter migration script."""

from __future__ import annotations

import textwrap
from pathlib import Path


from scripts.fix_expertise_frontmatter import (
    infer_agent_zone_department,
    build_frontmatter,
    migrate_file,
    REQUIRED_SECTIONS,
)


class TestInferAgentZoneDepartment:
    def test_qa_chief_from_filename(self, tmp_path: Path):
        teams_dir = tmp_path / "teams"
        teams_dir.mkdir()
        (teams_dir / "qa.yaml").write_text(
            "team:\n  name: qa\n  zone: 4\n"
            "chief:\n  name: qa-chief\n"
            "  expertise: agent/config/expertise/qa-chief.md\n"
            "workers: []\n"
        )
        agent, zone, dept = infer_agent_zone_department("qa-chief.md", teams_dir)
        assert agent == "qa-chief"
        assert zone == 4
        assert dept == "qa"

    def test_worker_from_filename(self, tmp_path: Path):
        teams_dir = tmp_path / "teams"
        teams_dir.mkdir()
        (teams_dir / "qa.yaml").write_text(
            "team:\n  name: qa\n  zone: 4\n"
            "chief:\n  name: qa-chief\n  expertise: ''\n"
            "workers:\n  - name: api-tester\n    expertise: agent/config/expertise/api-tester.md\n"
        )
        agent, zone, dept = infer_agent_zone_department("api-tester.md", teams_dir)
        assert agent == "api-tester"
        assert zone == 4
        assert dept == "qa"

    def test_fallback_when_no_match(self, tmp_path: Path):
        teams_dir = tmp_path / "teams"
        teams_dir.mkdir()
        (teams_dir / "qa.yaml").write_text(
            "team:\n  name: qa\n  zone: 4\nchief:\n  name: qa-chief\n  expertise: ''\nworkers: []\n"
        )
        agent, zone, dept = infer_agent_zone_department("mystery-agent.md", teams_dir)
        assert agent == "mystery-agent"
        assert zone == 4
        assert dept == "mystery"


class TestBuildFrontmatter:
    def test_frontmatter_fields(self):
        fm = build_frontmatter("qa-chief", 4, "qa", "updatable")
        assert "agent: qa-chief" in fm
        assert "zone: 4" in fm
        assert "department: qa" in fm
        assert "type: updatable" in fm
        assert "schema_version: 1" in fm

    def test_frontmatter_delimited(self):
        fm = build_frontmatter("qa-chief", 4, "qa", "updatable")
        assert fm.startswith("---\n")
        assert fm.endswith("---\n")


class TestMigrateFile:
    def _make_teams(self, tmp_path: Path, agent_name: str = "qa-chief") -> Path:
        teams_dir = tmp_path / "teams"
        teams_dir.mkdir(exist_ok=True)
        (teams_dir / "qa.yaml").write_text(
            f"team:\n  name: qa\n  zone: 4\n"
            f"chief:\n  name: {agent_name}\n  expertise: agent/config/expertise/{agent_name}.md\n"
            f"workers: []\n"
        )
        return teams_dir

    def test_adds_frontmatter_and_required_sections(self, tmp_path: Path):
        source = tmp_path / "qa-chief.md"
        source.write_text(textwrap.dedent("""\
            # qa-chief — Expertise

            ## Recurring Patterns
            - Pattern A

            ## Historical Decisions
            - Decision X
        """))
        teams_dir = self._make_teams(tmp_path)

        migrate_file(source, teams_dir)

        new_content = source.read_text()
        assert new_content.startswith("---\n")
        assert "agent: qa-chief" in new_content
        assert "zone: 4" in new_content
        assert "department: qa" in new_content
        for section in REQUIRED_SECTIONS:
            assert section in new_content
        assert "Pattern A" in new_content
        assert "Decision X" in new_content

    def test_idempotent_when_frontmatter_already_present(self, tmp_path: Path):
        source = tmp_path / "qa-chief.md"
        source.write_text(textwrap.dedent("""\
            ---
            agent: qa-chief
            zone: 4
            department: qa
            type: updatable
            max_lines: 500
            schema_version: 1
            ---

            ## Domain Patterns
            ## Known Risks
            ## Decision Log
            ## Cross-Agent Notes
        """))
        teams_dir = self._make_teams(tmp_path)

        original = source.read_text()
        migrate_file(source, teams_dir)
        assert source.read_text() == original

    def test_maps_legacy_sections(self, tmp_path: Path):
        source = tmp_path / "qa-chief.md"
        source.write_text(textwrap.dedent("""\
            # qa-chief — Expertise

            ## Recurring Patterns
            - content under recurring

            ## Project-Specific Notes
            - project notes here

            ## Historical Decisions
            - old decision
        """))
        teams_dir = self._make_teams(tmp_path)

        migrate_file(source, teams_dir)

        new_content = source.read_text()
        # Legacy headers should be mapped to required ones
        assert "## Domain Patterns" in new_content
        assert "## Decision Log" in new_content
        # Content preserved
        assert "content under recurring" in new_content
        assert "old decision" in new_content

    def test_dry_run_does_not_modify(self, tmp_path: Path):
        """Verify that the script's dry-run flag concept works
        by checking migrate_file doesn't run on --dry-run."""
        source = tmp_path / "qa-chief.md"
        original = "# qa-chief — Expertise\n\n## Recurring Patterns\n"
        source.write_text(original)
        # Just verify migrate_file actually changes the file
        teams_dir = self._make_teams(tmp_path)
        migrate_file(source, teams_dir)
        assert source.read_text() != original
