"""Tests for engineering team awareness and Zone 4 escalation awareness."""
from __future__ import annotations

from pathlib import Path


class TestEngineeringTeamSkill:
    def test_skill_file_exists(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        assert path.exists()

    def test_all_engineering_agents_listed(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        content = path.read_text()
        agents = [
            "engineering-chief", "backend-architect", "frontend-developer",
            "api-engineer", "code-reviewer", "database-specialist",
            "devops-engineer", "performance-engineer",
        ]
        for agent in agents:
            assert agent in content, f"Missing engineering agent: {agent}"

    def test_all_departments_listed(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        content = path.read_text()
        departments = ["QA", "Product Strategy", "Design", "Operations", "Strategy Board"]
        for dept in departments:
            assert dept in content, f"Missing department: {dept}"

    def test_complexity_rules_documented(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        content = path.read_text()
        assert "0-2" in content
        assert "3-5" in content
        assert "6-8" in content
        assert "9-10" in content

    def test_escalation_syntax_documented(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        content = path.read_text()
        assert "escalate(" in content
        assert 'department="qa"' in content
        assert 'department="board"' in content

    def test_when_not_to_escalate(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        content = path.read_text()
        assert "When NOT to Escalate" in content

    def test_frontmatter_present(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        content = path.read_text()
        assert content.startswith("---")
        assert "name: engineering-team" in content

    def test_all_five_departments_with_chiefs(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        content = path.read_text()
        chiefs = [
            "qa-chief", "strategy-product-chief", "design-chief",
            "ops-chief", "board-ceo",
        ]
        for chief in chiefs:
            assert chief in content, f"Missing chief: {chief}"

    def test_board_brief_format_shown(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        content = path.read_text()
        assert "Situation" in content or "brief=" in content

    def test_engineering_chief_coordinates(self):
        path = Path("config/claude-files/skills/engineering-team.md")
        content = path.read_text()
        assert "engineering-chief" in content
        assert "coordinat" in content.lower() or "6+" in content
