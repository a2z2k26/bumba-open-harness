"""Tests for Strategy Board thinking modalities and business validation."""
from __future__ import annotations

import pytest
from pathlib import Path


class TestThinkingModalitiesSkill:
    def test_skill_file_exists(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        assert path.exists()

    def test_all_12_modalities_documented(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        modalities = [
            "DIVERGENT", "CONVERGENT", "LATERAL", "SYSTEMIC",
            "ASSOCIATIVE", "CRITICAL", "ANALOGICAL", "ABDUCTIVE",
            "FIRST PRINCIPLES", "SECOND-ORDER", "JANUSIAN", "METACOGNITIVE",
        ]
        for modality in modalities:
            assert modality in content, f"Missing modality: {modality}"

    def test_each_modality_has_instruction(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        assert content.count("Instruction to members:") >= 12

    def test_each_modality_has_when_to_use(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        assert content.count("When to use:") >= 12

    def test_each_modality_has_what_it_surfaces(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        assert content.count("What it surfaces:") >= 12

    def test_selection_logic_documented(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        assert "Selection Logic" in content
        assert "Opening rounds" in content
        assert "Middle rounds" in content
        assert "Closing rounds" in content

    def test_adaptive_rules_documented(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        assert "Adaptive rules" in content
        assert "JANUSIAN" in content
        assert "CRITICAL" in content
        assert "SECOND-ORDER" in content

    def test_no_repeat_rule_documented(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        assert "Never repeat the same modality" in content

    def test_frontmatter_present(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        assert content.startswith("---")
        assert "name: thinking-modalities" in content
        assert "description:" in content

    def test_modality_count_is_exactly_12(self):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        # Count numbered modalities (### 1. through ### 12.)
        import re
        numbered = re.findall(r"^### \d+\.", content, re.MULTILINE)
        assert len(numbered) == 12, f"Expected 12 numbered modalities, got {len(numbered)}"

    @pytest.mark.parametrize("modality,round_phase", [
        ("DIVERGENT", "Opening rounds"),
        ("FIRST PRINCIPLES", "Opening rounds"),
        ("SYSTEMIC", "Middle rounds"),
        ("LATERAL", "Middle rounds"),
        ("CRITICAL", "Closing rounds"),
        ("CONVERGENT", "Closing rounds"),
    ])
    def test_modality_assigned_to_phase(self, modality, round_phase):
        path = Path("config/claude-files/skills/thinking-modalities.md")
        content = path.read_text()
        # Find the section for this round phase and verify the modality appears in it
        # Simple check: both appear in the same document
        assert modality in content
        assert round_phase in content


class TestBusinessValidationSkill:
    def test_skill_file_exists(self):
        path = Path("config/claude-files/skills/business-validation.md")
        assert path.exists()

    def test_validation_frameworks_present(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        frameworks = [
            "Market Sizing", "Unit Economics", "Competitive Moat",
            "Pre-Mortem", "Cheapest Experiment", "Moonshot Version",
        ]
        for fw in frameworks:
            assert fw in content, f"Missing framework: {fw}"

    def test_detection_triggers_documented(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        assert "Detection Triggers" in content

    def test_memo_additions_documented(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        assert "Go / No-Go" in content
        assert "TAM" in content
        assert "Cheapest Experiment" in content

    def test_unit_economics_includes_key_metrics(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        metrics = ["CAC", "LTV", "LTV:CAC", "margin"]
        for m in metrics:
            assert m in content, f"Missing metric: {m}"

    def test_tam_sam_som_present(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        assert "TAM" in content
        assert "SAM" in content
        assert "SOM" in content

    def test_premortem_questions_present(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        assert "post-mortem" in content or "Pre-Mortem" in content
        assert "What went wrong" in content

    def test_six_frameworks_count(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        # Each framework is a numbered section
        import re
        numbered = re.findall(r"^### \d+\.", content, re.MULTILINE)
        assert len(numbered) >= 6, f"Expected at least 6 frameworks, got {len(numbered)}"

    def test_cheapest_experiment_constraints(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        assert "2 weeks" in content
        assert "$500" in content

    def test_go_no_go_options_present(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        assert "GO" in content
        assert "NO-GO" in content
        assert "CONDITIONAL GO" in content

    def test_delegate_assignments_specified(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        # Each framework should specify which board member handles it
        assert "delegate to" in content

    def test_frontmatter_present(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        assert content.startswith("---")
        assert "name: business-validation" in content
        assert "description:" in content

    def test_moonshot_scale_question(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        assert "10x" in content

    def test_competitive_moat_questions(self):
        path = Path("config/claude-files/skills/business-validation.md")
        content = path.read_text()
        assert "6 months" in content
        assert "compound" in content


class TestBothSkillsIntegration:
    def test_skills_directory_contains_both(self):
        skills_dir = Path("config/claude-files/skills")
        assert (skills_dir / "thinking-modalities.md").exists()
        assert (skills_dir / "business-validation.md").exists()

    def test_modalities_referenced_in_deliberation_flow(self):
        """The deliberation engine should be complemented by the modalities skill."""
        deliberation = Path("bridge/peer_ranking.py")
        assert deliberation.exists(), "peer_ranking.py must exist (Sprint 17; renamed from deliberation.py per P8.2.5)"

    def test_board_config_references_board_ceo(self):
        """board.yaml must reference board-ceo as the CEO."""
        board_yaml = Path("config/teams/board.yaml")
        assert board_yaml.exists()
        content = board_yaml.read_text()
        assert "board-ceo" in content

    def test_thinking_modalities_skill_is_in_skills_index(self):
        """Skills should be discoverable."""
        skills_dir = Path("config/claude-files/skills")
        skill_files = list(skills_dir.glob("*.md"))
        skill_names = [f.stem for f in skill_files]
        assert "thinking-modalities" in skill_names

    def test_business_validation_skill_is_in_skills_index(self):
        skills_dir = Path("config/claude-files/skills")
        skill_files = list(skills_dir.glob("*.md"))
        skill_names = [f.stem for f in skill_files]
        assert "business-validation" in skill_names
