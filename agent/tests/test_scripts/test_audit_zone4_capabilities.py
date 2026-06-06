"""Tests for scripts/audit_zone4_capabilities.py."""

from __future__ import annotations

from pathlib import Path

import yaml

from bridge.skill_allocator import AllocationRule, SkillAllocator
from bridge.tool_shed import ToolShed
from scripts.audit_zone4_capabilities import (
    CapabilityRow,
    build_capability_rows,
    render_markdown,
    write_report,
)


def _write_team(path: Path) -> None:
    data: dict[str, object] = {
        "team": {
            "name": "design",
            "zone": 4,
            "tools": {
                "common": ["read_file"],
                "department": ["lookup_component"],
                "per_employee": {"design-ui-designer": ["render_mockup"]},
            },
            "mcp": {"mode": "permissive", "allowed_servers": ["figma"]},
            "chief": {
                "name": "design-chief",
                "skills": ["mental-model"],
                "domain": {"read": ["*"]},
            },
            "workers": [
                {
                    "name": "design-ui-designer",
                    "skills": [
                        "one",
                        "two",
                        "three",
                        "four",
                        "five",
                        "six",
                    ],
                    "domain": {"read": ["docs/design/"]},
                }
            ],
        }
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _write_tool_shed(path: Path) -> ToolShed:
    path.write_text(
        "\n".join(
            [
                "tools:",
                "  github:",
                "    category: code",
                "    always_loaded: true",
                "    agents: [all]",
                "  figma:",
                "    category: design",
                "    always_loaded: false",
                "    agents: [design-ui-designer]",
            ]
        ),
        encoding="utf-8",
    )
    return ToolShed(path)


def test_build_capability_rows_includes_yaml_tools_and_allocated_skills(
    tmp_path: Path,
) -> None:
    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()
    _write_team(teams_dir / "design.yaml")
    governance_root = tmp_path / "governance"
    chief_bundle = governance_root / "design" / "design-chief"
    chief_bundle.mkdir(parents=True)
    for filename in ("CLAUDE.md", "SOUL.md", "ARTIFACTS.md"):
        (chief_bundle / filename).write_text("ok", encoding="utf-8")
    allocator = SkillAllocator(
        [
            AllocationRule(
                skill="frontend-design",
                zone=4,
                department="design",
                role="specialist",
                agents=("design-ui-designer",),
            )
        ]
    )
    tool_shed = _write_tool_shed(tmp_path / "tool-shed.yaml")

    rows = build_capability_rows(
        teams_dir,
        governance_root=governance_root,
        skill_allocator=allocator,
        tool_shed=tool_shed,
    )

    assert [row.agent for row in rows] == ["design-chief", "design-ui-designer"]
    chief = rows[0]
    worker = rows[1]
    assert chief.in_process_tools == ("read_file", "lookup_component")
    assert chief.yaml_skills == ("mental-model",)
    assert chief.governance_present is True
    assert worker.in_process_tools == (
        "read_file",
        "lookup_component",
        "render_mockup",
    )
    assert worker.allocated_skills == ("frontend-design",)
    assert worker.tool_shed_tools == ("figma", "github")


def test_rows_flag_overbroad_capabilities(tmp_path: Path) -> None:
    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()
    _write_team(teams_dir / "design.yaml")

    rows = build_capability_rows(
        teams_dir,
        governance_root=tmp_path / "missing-governance",
        skill_allocator=SkillAllocator(),
        tool_shed=None,
    )

    chief = rows[0]
    worker = rows[1]
    assert chief.flags == (
        "read:*",
        "mcp:permissive",
        "missing_governance",
    )
    assert worker.flags == (
        "mcp:permissive",
        "missing_governance",
        "skills>5",
    )


def test_render_markdown_lists_rows_and_summary_flags() -> None:
    row = CapabilityRow(
        department="design",
        role="specialist",
        agent="design-ui-designer",
        in_process_tools=("read_file", "lookup_component"),
        tool_shed_tools=("figma",),
        mcp_mode="deny_by_default",
        mcp_servers=("figma",),
        yaml_skills=("mental-model",),
        allocated_skills=("frontend-design",),
        read_scope=("docs/design/",),
        governance_present=True,
        flags=("skills>5",),
    )

    markdown = render_markdown([row])

    assert "# Zone 4 Capability Inventory" in markdown
    assert "| design | specialist | design-ui-designer |" in markdown
    assert "read_file, lookup_component" in markdown
    assert "frontend-design" in markdown
    assert "## Overbroad Flags" in markdown
    assert "skills>5" in markdown


def test_write_report_persists_rendered_inventory(tmp_path: Path) -> None:
    output = tmp_path / "docs" / "inventory.md"
    row = CapabilityRow(
        department="ops",
        role="chief",
        agent="ops-chief",
        in_process_tools=(),
        tool_shed_tools=(),
        mcp_mode="deny_by_default",
        mcp_servers=(),
        yaml_skills=(),
        allocated_skills=(),
        read_scope=(),
        governance_present=False,
        flags=("missing_governance",),
    )

    write_report((row,), output)

    assert output.exists()
    assert "ops-chief" in output.read_text(encoding="utf-8")
