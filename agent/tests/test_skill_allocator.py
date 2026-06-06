"""Tests for skill_allocator — default-deny skill allocation for #1112 Phase 4.

Covers the SkillAllocator + AllocationRule public API and the custom loader
that parses agent/config/skill-allocation/proposed-allocations.yaml.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bridge.skill_allocator import (
    AgentSkillReport,
    AllocationRule,
    SkillAllocator,
    _extract_skills_from_group,
    _rule_specificity,
    _rule_summary,
)


PROPOSED_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "skill-allocation"
    / "proposed-allocations.yaml"
)


class TestDefaultDeny:
    """Default-deny: empty rules ⇒ empty allowed-skill set. Security invariant."""

    def test_empty_rules_zone3_returns_empty_set(self):
        allocator = SkillAllocator(rules=[])
        result = allocator.allowed_skills(zone=3)
        assert result == set()
        assert isinstance(result, set)

    def test_empty_rules_zone3_with_department_returns_empty_set(self):
        allocator = SkillAllocator(rules=[])
        assert allocator.allowed_skills(zone=3, department="engineering") == set()

    def test_empty_rules_zone4_returns_empty_set(self):
        allocator = SkillAllocator(rules=[])
        assert allocator.allowed_skills(zone=4, department="design") == set()

    def test_no_matching_rule_returns_empty_set(self):
        """A rule for zone 3 must NOT surface for a zone 4 query."""
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="python-patterns", zone=3, department="engineering"),
        ])
        assert allocator.allowed_skills(zone=4, department="engineering") == set()


class TestDepartmentAllocationCascade:
    """A department allocation flows to all roles + agents under that department."""

    def test_department_allocation_flows_to_unspecified_role_and_agent(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="audit", zone=3, department="engineering"),
        ])
        # No role/agent given — universal across the dept
        assert "audit" in allocator.allowed_skills(zone=3, department="engineering")

    def test_department_allocation_flows_to_chief(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="audit", zone=3, department="engineering"),
        ])
        assert "audit" in allocator.allowed_skills(
            zone=3, department="engineering", role="chief"
        )

    def test_department_allocation_flows_to_specialist(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="audit", zone=3, department="engineering"),
        ])
        assert "audit" in allocator.allowed_skills(
            zone=3, department="engineering", role="specialist"
        )

    def test_department_allocation_flows_to_specific_agent(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="audit", zone=3, department="engineering"),
        ])
        assert "audit" in allocator.allowed_skills(
            zone=3,
            department="engineering",
            role="specialist",
            agent_name="engineering-backend-architect",
        )

    def test_department_mismatch_does_not_flow(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="audit", zone=3, department="engineering"),
        ])
        assert "audit" not in allocator.allowed_skills(
            zone=4, department="design"
        )


class TestRoleNarrowing:
    """A rule with role=chief must NOT surface for a specialist query."""

    def test_chief_only_rule_surfaces_for_chief(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="architecture-patterns",
                zone=3,
                department="engineering",
                role="chief",
            ),
        ])
        assert "architecture-patterns" in allocator.allowed_skills(
            zone=3, department="engineering", role="chief"
        )

    def test_chief_only_rule_does_not_surface_for_specialist(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="architecture-patterns",
                zone=3,
                department="engineering",
                role="chief",
            ),
        ])
        assert "architecture-patterns" not in allocator.allowed_skills(
            zone=3, department="engineering", role="specialist"
        )


class TestAgentNarrowing:
    """A rule with agents=(...,) must only surface for those named agents."""

    def test_agent_specific_rule_surfaces_for_named_agent(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="python-patterns",
                zone=3,
                department="engineering",
                agents=("engineering-backend-architect", "engineering-api-engineer"),
            ),
        ])
        assert "python-patterns" in allocator.allowed_skills(
            zone=3,
            department="engineering",
            agent_name="engineering-backend-architect",
        )

    def test_agent_specific_rule_excludes_unnamed_agent(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="python-patterns",
                zone=3,
                department="engineering",
                agents=("engineering-backend-architect",),
            ),
        ])
        assert "python-patterns" not in allocator.allowed_skills(
            zone=3,
            department="engineering",
            agent_name="engineering-frontend-developer",
        )

    def test_agent_specific_rule_excludes_none_agent(self):
        """If a rule names specific agents, an unspecified agent_name should NOT match."""
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="python-patterns",
                zone=3,
                department="engineering",
                agents=("engineering-backend-architect",),
            ),
        ])
        assert "python-patterns" not in allocator.allowed_skills(
            zone=3, department="engineering"
        )


class TestCrossZoneAllocation:
    """The same skill allocated to both zone 3 and zone 4 should surface in both."""

    def test_skill_in_both_zones(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="security-review",
                zone=3,
                department="engineering",
                agents=("engineering-code-reviewer",),
            ),
            AllocationRule(
                skill="security-review",
                zone=4,
                department="qa",
                agents=("qa-security-auditor",),
            ),
        ])
        assert "security-review" in allocator.allowed_skills(
            zone=3,
            department="engineering",
            agent_name="engineering-code-reviewer",
        )
        assert "security-review" in allocator.allowed_skills(
            zone=4,
            department="qa",
            agent_name="qa-security-auditor",
        )


class TestExtractSkillsFromGroup:
    """Unit-level coverage of _extract_skills_from_group helper."""

    def test_extracts_skill_list(self):
        group = {
            "_skills": ["python-patterns", "python-testing"],
            "allocation": [{"zone": 3, "department": "engineering"}],
        }
        result = _extract_skills_from_group(group)
        assert set(result) == {"python-patterns", "python-testing"}

    def test_skips_allocation_key(self):
        group = {
            "_skills": ["a", "b"],
            "allocation": [{"zone": 3}],
        }
        assert "allocation" not in _extract_skills_from_group(group)


class TestFromManifestProposed:
    """Load the real proposed-allocations.yaml and verify acceptance criteria."""

    def test_parses_without_error(self):
        assert PROPOSED_PATH.exists(), f"fixture missing: {PROPOSED_PATH}"
        allocator = SkillAllocator.from_manifest(PROPOSED_PATH)
        assert isinstance(allocator, SkillAllocator)

    def test_rule_count_at_least_200(self):
        """Acceptance criterion: ≥200 rules in the loaded allocator."""
        allocator = SkillAllocator.from_manifest(PROPOSED_PATH)
        assert len(allocator.rules) >= 200, (
            f"expected ≥200 rules, got {len(allocator.rules)}"
        )

    def test_backend_architect_has_python_patterns(self):
        """Integration: spec example — engineering-backend-architect has python-patterns."""
        allocator = SkillAllocator.from_manifest(PROPOSED_PATH)
        allowed = allocator.allowed_skills(
            zone=3,
            department="engineering",
            agent_name="engineering-backend-architect",
        )
        assert "python-patterns" in allowed

    def test_design_ui_designer_has_figma_use(self):
        """Integration: design-ui-designer should get figma-use from figma_core group."""
        allocator = SkillAllocator.from_manifest(PROPOSED_PATH)
        allowed = allocator.allowed_skills(
            zone=4,
            department="design",
            agent_name="design-ui-designer",
        )
        assert "figma-use" in allowed

    def test_qa_security_auditor_has_security_review(self):
        """Integration: cross-zone — security-review allocated to qa-security-auditor."""
        allocator = SkillAllocator.from_manifest(PROPOSED_PATH)
        allowed = allocator.allowed_skills(
            zone=4,
            department="qa",
            agent_name="qa-security-auditor",
        )
        assert "security-review" in allowed

    def test_unallocated_agent_gets_empty_or_universal_only(self):
        """An agent in a department with no specific allocations only gets universal
        (department-wide, no agent narrowing) skills."""
        allocator = SkillAllocator.from_manifest(PROPOSED_PATH)
        allowed = allocator.allowed_skills(
            zone=4,
            department="design",
            agent_name="some-nonexistent-agent",
        )
        # No skill that was agent-narrowed should be present
        assert "figma-use" not in allowed  # figma-use is agent-narrowed
        # But universal department-level skills should be (e.g. "design")
        assert "design" in allowed


class TestAllocationRuleImmutability:
    """AllocationRule is frozen — protects rules from accidental mutation."""

    def test_rule_is_frozen(self):
        rule = AllocationRule(skill="a", zone=3, department="engineering")
        with pytest.raises((AttributeError, Exception)):
            rule.skill = "b"  # type: ignore[misc]


# ----------------------------------------------------------------------
# Sprint 4.04 / #2151 — per-agent discovery surface
# ----------------------------------------------------------------------


class TestDescribeAgentStructure:
    """describe_agent returns AgentSkillReport with the documented shape."""

    def test_returns_agent_skill_report(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="audit", zone=3, department="engineering"),
        ])
        report = allocator.describe_agent(
            zone=3,
            department="engineering",
            role="specialist",
            agent_name="engineering-backend-architect",
        )
        assert isinstance(report, AgentSkillReport)
        assert report.agent_name == "engineering-backend-architect"
        assert report.zone == 3
        assert report.department == "engineering"
        assert report.role == "specialist"

    def test_allowed_skills_sorted_alphabetically(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="zeta", zone=3, department="engineering"),
            AllocationRule(skill="alpha", zone=3, department="engineering"),
            AllocationRule(skill="mike", zone=3, department="engineering"),
        ])
        report = allocator.describe_agent(zone=3, department="engineering")
        assert report.allowed_skills == ("alpha", "mike", "zeta")

    def test_source_rules_aligned_with_allowed_skills(self):
        """source_rules tuple must be in the same order as allowed_skills."""
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="zeta", zone=3, department="engineering"),
            AllocationRule(skill="alpha", zone=3, department="engineering"),
        ])
        report = allocator.describe_agent(zone=3, department="engineering")
        skill_names_from_provenance = tuple(s for s, _ in report.source_rules)
        assert skill_names_from_provenance == report.allowed_skills

    def test_report_is_frozen(self):
        report = AgentSkillReport(
            agent_name="x",
            zone=3,
            department=None,
            role=None,
            allowed_skills=(),
            source_rules=(),
        )
        with pytest.raises((AttributeError, Exception)):
            report.agent_name = "y"  # type: ignore[misc]


class TestDescribeAgentProvenance:
    """Provenance per skill = the most-specific rule that granted it."""

    def test_provenance_captured_per_skill(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="python-patterns", zone=3, department="engineering"),
        ])
        report = allocator.describe_agent(
            zone=3, department="engineering", role="specialist",
        )
        # Exactly one row per skill
        assert len(report.source_rules) == len(report.allowed_skills) == 1
        skill, summary = report.source_rules[0]
        assert skill == "python-patterns"
        assert "zone=3" in summary
        assert "dept=engineering" in summary

    def test_most_specific_rule_wins_when_multiple_grant_same_skill(self):
        """When dept + role + agent rules all grant the same skill,
        the agent-narrowed rule (most specific) supplies provenance."""
        agent = "engineering-backend-architect"
        allocator = SkillAllocator(rules=[
            # Dept-wide rule (specificity 2)
            AllocationRule(skill="audit", zone=3, department="engineering"),
            # Role-narrowed rule (specificity 3)
            AllocationRule(
                skill="audit", zone=3, department="engineering",
                role="specialist",
            ),
            # Agent-narrowed rule (specificity 4 — should win)
            AllocationRule(
                skill="audit", zone=3, department="engineering",
                role="specialist", agents=(agent,),
            ),
        ])
        report = allocator.describe_agent(
            zone=3, department="engineering", role="specialist",
            agent_name=agent,
        )
        # Exactly one row even though three rules granted it
        assert report.allowed_skills == ("audit",)
        _, summary = report.source_rules[0]
        # Most-specific (agent-narrowed) summary must include the agent list
        assert "agents=" in summary
        assert agent in summary

    def test_universal_rule_marked_in_summary(self):
        """A dept-wide rule with no role/agent narrowing is marked '(universal)'."""
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="audit", zone=3, department="engineering"),
        ])
        report = allocator.describe_agent(zone=3, department="engineering")
        _, summary = report.source_rules[0]
        assert "(universal)" in summary

    def test_rule_specificity_ordering(self):
        """Specificity ordering — agents > role > dept > fully-universal."""
        universal = AllocationRule(skill="x", zone=3)
        dept_only = AllocationRule(skill="x", zone=3, department="engineering")
        role_narrowed = AllocationRule(
            skill="x", zone=3, department="engineering", role="chief",
        )
        agent_narrowed = AllocationRule(
            skill="x", zone=3, department="engineering",
            role="chief", agents=("engineering-chief",),
        )
        assert (
            _rule_specificity(universal)
            < _rule_specificity(dept_only)
            < _rule_specificity(role_narrowed)
            < _rule_specificity(agent_narrowed)
        )


class TestDescribeAgentDefaultDeny:
    """Default-deny: a query that matches no rule returns an empty report."""

    def test_empty_allocator_returns_empty_report(self):
        allocator = SkillAllocator(rules=[])
        report = allocator.describe_agent(
            zone=3, department="engineering", agent_name="nobody",
        )
        assert isinstance(report, AgentSkillReport)
        assert report.allowed_skills == ()
        assert report.source_rules == ()

    def test_mismatched_zone_returns_empty_report(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(skill="x", zone=3, department="engineering"),
        ])
        report = allocator.describe_agent(zone=4, department="design")
        assert report.allowed_skills == ()
        assert report.source_rules == ()


class TestDescribeAgentAgainstManifest:
    """End-to-end: real manifest → describe_agent → live operator scenario."""

    def test_backend_architect_report_includes_python_patterns(self):
        allocator = SkillAllocator.from_manifest(PROPOSED_PATH)
        report = allocator.describe_agent(
            zone=3,
            department="engineering",
            role="specialist",
            agent_name="engineering-backend-architect",
        )
        assert "python-patterns" in report.allowed_skills
        # Provenance captured for every skill
        assert len(report.source_rules) == len(report.allowed_skills)

    def test_unknown_agent_in_known_department_returns_universal_subset(self):
        """Agent name that no rule names → only universal department-level
        rules surface (no agent-narrowed rows)."""
        allocator = SkillAllocator.from_manifest(PROPOSED_PATH)
        report = allocator.describe_agent(
            zone=4, department="design", role="specialist",
            agent_name="some-nonexistent-agent",
        )
        # Agent-narrowed rules must NOT appear in provenance
        for _, summary in report.source_rules:
            assert "agents=" not in summary


class TestRuleSummaryFormatting:
    """_rule_summary surfaces the right operator-readable provenance string."""

    def test_universal_across_departments(self):
        summary = _rule_summary(AllocationRule(skill="x", zone=3))
        assert "zone=3" in summary
        assert "universal across departments" in summary

    def test_dept_only_marked_universal(self):
        summary = _rule_summary(
            AllocationRule(skill="x", zone=4, department="design")
        )
        assert "dept=design" in summary
        assert "(universal)" in summary

    def test_role_narrowed_summary(self):
        summary = _rule_summary(AllocationRule(
            skill="x", zone=3, department="engineering", role="chief",
        ))
        assert "role=chief" in summary
        # Role-narrowed is NOT universal
        assert "universal" not in summary

    def test_agent_narrowed_summary(self):
        summary = _rule_summary(AllocationRule(
            skill="x", zone=3, department="engineering",
            agents=("engineering-backend-architect",),
        ))
        assert "agents=[engineering-backend-architect]" in summary


class TestOverridePathway:
    """Sprint 4.05 (#2152) — per-agent override pathway.

    Operator can grant a skill to a specific named agent via an `overrides:`
    section in the manifest, bypassing categorical (zone, dept, role) matching.
    Overrides ADD skills; removal stays a categorical-rules edit.
    """

    def test_override_rule_grants_skill_to_named_agent(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="bumba-nlp-design",
                zone=3,
                agents=("engineering-backend-architect",),
                override=True,
            ),
        ])
        result = allocator.allowed_skills(
            zone=3,
            department="engineering",
            role="specialist",
            agent_name="engineering-backend-architect",
        )
        assert "bumba-nlp-design" in result

    def test_override_rule_does_not_leak_to_other_agents(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="bumba-nlp-design",
                zone=3,
                agents=("engineering-backend-architect",),
                override=True,
            ),
        ])
        result = allocator.allowed_skills(
            zone=3,
            department="engineering",
            role="specialist",
            agent_name="engineering-frontend-developer",
        )
        assert "bumba-nlp-design" not in result

    def test_override_rule_bypasses_zone_dept_role_matching(self):
        """Override grants regardless of zone/dept/role of the caller."""
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="stripe-integration",
                zone=3,  # sentinel — should be ignored on override
                agents=("design-ui-designer",),
                override=True,
            ),
        ])
        # Caller is zone=4, dept=design, role=specialist
        result = allocator.allowed_skills(
            zone=4,
            department="design",
            role="specialist",
            agent_name="design-ui-designer",
        )
        assert "stripe-integration" in result

    def test_override_requires_agent_name_in_query(self):
        """Department-wide query (agent_name=None) does NOT pick up overrides."""
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="bumba-nlp-design",
                zone=3,
                agents=("engineering-backend-architect",),
                override=True,
            ),
        ])
        result = allocator.allowed_skills(
            zone=3,
            department="engineering",
            role="specialist",
        )
        assert "bumba-nlp-design" not in result

    def test_override_adds_alongside_categorical_rules(self):
        """Override skills join the agent's allowed set; don't replace categorical."""
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="python-patterns",
                zone=3,
                department="engineering",
                agents=("engineering-backend-architect",),
            ),
            AllocationRule(
                skill="bumba-nlp-design",
                zone=3,
                agents=("engineering-backend-architect",),
                override=True,
            ),
        ])
        result = allocator.allowed_skills(
            zone=3,
            department="engineering",
            role="specialist",
            agent_name="engineering-backend-architect",
        )
        assert "python-patterns" in result
        assert "bumba-nlp-design" in result

    def test_describe_agent_tags_override_skill_with_OVERRIDE_in_provenance(self):
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="bumba-nlp-design",
                zone=3,
                agents=("engineering-backend-architect",),
                override=True,
            ),
        ])
        report = allocator.describe_agent(
            zone=3,
            department="engineering",
            role="specialist",
            agent_name="engineering-backend-architect",
        )
        assert report.allowed_skills == ("bumba-nlp-design",)
        # Provenance must surface the OVERRIDE prefix
        assert report.source_rules[0][0] == "bumba-nlp-design"
        assert "OVERRIDE" in report.source_rules[0][1]
        assert "engineering-backend-architect" in report.source_rules[0][1]

    def test_override_outranks_categorical_in_provenance(self):
        """When override AND categorical rule grant same skill, override wins
        the provenance row (operator's explicit grant is the answer to
        'why does this agent have this skill?')."""
        allocator = SkillAllocator(rules=[
            AllocationRule(
                skill="bumba-nlp-design",
                zone=4,
                department="design",
                agents=("design-ui-designer",),
            ),
            AllocationRule(
                skill="bumba-nlp-design",
                zone=3,  # override sentinel
                agents=("design-ui-designer",),
                override=True,
            ),
        ])
        report = allocator.describe_agent(
            zone=4,
            department="design",
            role="specialist",
            agent_name="design-ui-designer",
        )
        # Override wins provenance
        assert "OVERRIDE" in report.source_rules[0][1]

    def test_specificity_score_for_override_is_5_beats_agents_4(self):
        override_rule = AllocationRule(
            skill="x", zone=3,
            agents=("engineering-backend-architect",),
            override=True,
        )
        agent_rule = AllocationRule(
            skill="x", zone=3, department="engineering",
            agents=("engineering-backend-architect",),
        )
        assert _rule_specificity(override_rule) == 5
        assert _rule_specificity(agent_rule) == 4

    def test_override_rule_summary_has_OVERRIDE_prefix(self):
        summary = _rule_summary(AllocationRule(
            skill="x", zone=3,
            agents=("engineering-backend-architect",),
            override=True,
        ))
        assert summary.startswith("OVERRIDE")
        assert "engineering-backend-architect" in summary


class TestFromManifestOverrides:
    """Loading the `overrides:` section from a manifest YAML string."""

    def test_loads_single_override_entry(self, tmp_path: Path):
        manifest_text = """\
categories: []
overrides:
  - agent: engineering-backend-architect
    skills:
      - bumba-nlp-design
"""
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(manifest_text)
        allocator = SkillAllocator.from_manifest(manifest_path)
        # The override rule should be present
        override_rules = [r for r in allocator.rules if r.override]
        assert len(override_rules) == 1
        rule = override_rules[0]
        assert rule.skill == "bumba-nlp-design"
        assert rule.agents == ("engineering-backend-architect",)

    def test_loads_multiple_overrides_one_per_skill(self, tmp_path: Path):
        manifest_text = """\
categories: []
overrides:
  - agent: design-ui-designer
    skills:
      - stripe-integration
      - python-patterns
  - agent: engineering-backend-architect
    skills:
      - bumba-nlp-design
"""
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(manifest_text)
        allocator = SkillAllocator.from_manifest(manifest_path)
        override_rules = [r for r in allocator.rules if r.override]
        # 3 total: 2 for design-ui-designer + 1 for engineering-backend-architect
        assert len(override_rules) == 3
        # design-ui-designer gets both
        designer_skills = {r.skill for r in override_rules if "design-ui-designer" in r.agents}
        assert designer_skills == {"stripe-integration", "python-patterns"}

    def test_override_with_note_preserves_note(self, tmp_path: Path):
        manifest_text = """\
categories: []
overrides:
  - agent: design-ui-designer
    skills:
      - stripe-integration
    note: "rare cross-domain need for checkout-flow design"
"""
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(manifest_text)
        allocator = SkillAllocator.from_manifest(manifest_path)
        override_rules = [r for r in allocator.rules if r.override]
        assert override_rules[0].note == "rare cross-domain need for checkout-flow design"

    def test_missing_overrides_section_does_not_raise(self, tmp_path: Path):
        """Back-compat: a manifest without an `overrides:` section loads cleanly."""
        manifest_text = "categories: []\n"
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(manifest_text)
        allocator = SkillAllocator.from_manifest(manifest_path)
        override_rules = [r for r in allocator.rules if r.override]
        assert override_rules == []

    def test_malformed_override_entry_is_skipped(self, tmp_path: Path):
        """Defensive: a malformed override (missing `agent` or `skills`) is
        silently skipped, not an error. Operator may have a typo; better to
        load the rest of the manifest than refuse to start."""
        manifest_text = """\
categories: []
overrides:
  - agent: design-ui-designer
    skills:
      - stripe-integration
  - skills:
      - python-patterns
  - agent: ""
    skills:
      - bumba-nlp-design
"""
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(manifest_text)
        allocator = SkillAllocator.from_manifest(manifest_path)
        override_rules = [r for r in allocator.rules if r.override]
        # Only the valid first entry should produce a rule
        assert len(override_rules) == 1
        assert override_rules[0].skill == "stripe-integration"
