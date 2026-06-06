"""Generate a Zone 4 MCP/tool/skill capability inventory."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml

from bridge.skill_allocator import SkillAllocator
from bridge.tool_shed import ToolShed

Role = Literal["chief", "specialist"]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEAMS_DIR = REPO_ROOT / "agent" / "config" / "teams"
DEFAULT_GOVERNANCE_ROOT = REPO_ROOT / "agent" / "config" / "governance" / "zone4"
DEFAULT_SKILL_MANIFEST = (
    REPO_ROOT / "agent" / "config" / "skill-allocation" / "proposed-allocations.yaml"
)
DEFAULT_TOOL_SHED = REPO_ROOT / "agent" / "config" / "tool-shed.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "audits" / "2026-05-21-zone4-capability-inventory.md"
REQUIRED_GOVERNANCE_FILES = ("CLAUDE.md", "SOUL.md", "ARTIFACTS.md")


@dataclass(frozen=True)
class CapabilityRow:
    department: str
    role: Role
    agent: str
    in_process_tools: tuple[str, ...]
    tool_shed_tools: tuple[str, ...]
    mcp_mode: str
    mcp_servers: tuple[str, ...]
    yaml_skills: tuple[str, ...]
    allocated_skills: tuple[str, ...]
    read_scope: tuple[str, ...]
    governance_present: bool
    flags: tuple[str, ...]


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return value
    return ()


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in _sequence(value))


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _role_sort(role: Role) -> int:
    return 0 if role == "chief" else 1


def _governance_present(
    governance_root: Path,
    department: str,
    agent_name: str,
) -> bool:
    bundle = governance_root / department / agent_name
    return all((bundle / filename).is_file() for filename in REQUIRED_GOVERNANCE_FILES)


def _flags(
    *,
    read_scope: tuple[str, ...],
    mcp_mode: str,
    governance_present: bool,
    yaml_skills: tuple[str, ...],
    allocated_skills: tuple[str, ...],
) -> tuple[str, ...]:
    flags: list[str] = []
    if "*" in read_scope:
        flags.append("read:*")
    if mcp_mode == "permissive":
        flags.append("mcp:permissive")
    if not governance_present:
        flags.append("missing_governance")
    skill_count = len(set(yaml_skills) | set(allocated_skills))
    if skill_count > 5:
        flags.append("skills>5")
    return tuple(flags)


def _team_config_paths(teams_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in teams_dir.glob("*.yaml")
        if not path.name.startswith("_")
    )


def _agent_entries(team: Mapping[str, object]) -> list[tuple[Role, Mapping[str, object]]]:
    entries: list[tuple[Role, Mapping[str, object]]] = []
    chief = _mapping(team.get("chief"))
    if chief.get("name"):
        entries.append(("chief", chief))
    for worker in _sequence(team.get("workers")):
        worker_data = _mapping(worker)
        if worker_data.get("name"):
            entries.append(("specialist", worker_data))
    return entries


def build_capability_rows(
    teams_dir: Path,
    *,
    governance_root: Path,
    skill_allocator: SkillAllocator,
    tool_shed: ToolShed | None,
) -> list[CapabilityRow]:
    """Build one capability row per Zone 4 chief and specialist."""
    rows: list[CapabilityRow] = []

    for path in _team_config_paths(teams_dir):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        root = _mapping(loaded)
        team = _mapping(root.get("team"))
        if int(team.get("zone", 0)) != 4:
            continue

        department = str(team["name"])
        tools = _mapping(team.get("tools"))
        common_tools = _string_tuple(tools.get("common"))
        department_tools = _string_tuple(tools.get("department"))
        per_employee = _mapping(tools.get("per_employee"))
        mcp = _mapping(team.get("mcp"))
        mcp_mode = str(mcp.get("mode", "permissive"))
        mcp_servers = _string_tuple(mcp.get("allowed_servers"))

        for role, agent_data in _agent_entries(team):
            agent_name = str(agent_data["name"])
            yaml_skills = _string_tuple(agent_data.get("skills"))
            agent_tools = _string_tuple(per_employee.get(agent_name))
            in_process_tools = _dedupe(common_tools + department_tools + agent_tools)
            skill_report = skill_allocator.describe_agent(
                zone=4,
                department=department,
                role=role,
                agent_name=agent_name,
            )
            allocated_skills = skill_report.allowed_skills
            read_scope = _string_tuple(_mapping(agent_data.get("domain")).get("read"))
            governance = _governance_present(
                governance_root,
                department,
                agent_name,
            )
            rows.append(
                CapabilityRow(
                    department=department,
                    role=role,
                    agent=agent_name,
                    in_process_tools=in_process_tools,
                    tool_shed_tools=tuple(tool_shed.tools_for_agent(agent_name))
                    if tool_shed is not None
                    else (),
                    mcp_mode=mcp_mode,
                    mcp_servers=mcp_servers,
                    yaml_skills=yaml_skills,
                    allocated_skills=allocated_skills,
                    read_scope=read_scope,
                    governance_present=governance,
                    flags=_flags(
                        read_scope=read_scope,
                        mcp_mode=mcp_mode,
                        governance_present=governance,
                        yaml_skills=yaml_skills,
                        allocated_skills=allocated_skills,
                    ),
                )
            )

    return sorted(rows, key=lambda row: (row.department, _role_sort(row.role), row.agent))


def _cell(values: Sequence[str]) -> str:
    if not values:
        return "none"
    return ", ".join(values).replace("|", "\\|")


def _bool_cell(value: bool) -> str:
    return "yes" if value else "no"


def render_markdown(rows: Sequence[CapabilityRow]) -> str:
    flag_counts = Counter(flag for row in rows for flag in row.flags)
    departments = sorted({row.department for row in rows})
    lines = [
        "# Zone 4 Capability Inventory",
        "",
        "Generated from `agent/config/teams/*.yaml`, `tool-shed.yaml`, the "
        "SkillAllocator manifest, and governance bundle directories.",
        "",
        "This report is advisory only. It names current exposure and sprawl "
        "signals without changing runtime behavior.",
        "",
        "## Summary",
        "",
        f"- Departments: {len(departments)}",
        f"- Agents: {len(rows)}",
        f"- Rows with flags: {sum(1 for row in rows if row.flags)}",
        "",
        "## Overbroad Flags",
        "",
    ]
    if flag_counts:
        for flag, count in sorted(flag_counts.items()):
            lines.append(f"- `{flag}`: {count}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Inventory",
            "",
            "| Department | Role | Agent | In-process tools | Tool Shed tools | MCP | YAML skills | Allocated skills | Read scope | Governance | Flags |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        mcp = f"{row.mcp_mode}: {_cell(row.mcp_servers)}"
        lines.append(
            " | ".join(
                [
                    f"| {row.department}",
                    row.role,
                    row.agent,
                    _cell(row.in_process_tools),
                    _cell(row.tool_shed_tools),
                    mcp,
                    _cell(row.yaml_skills),
                    _cell(row.allocated_skills),
                    _cell(row.read_scope),
                    _bool_cell(row.governance_present),
                    _cell(row.flags) + " |",
                ]
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_report(rows: Sequence[CapabilityRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(rows), encoding="utf-8")


def _load_skill_allocator(manifest_path: Path) -> SkillAllocator:
    if not manifest_path.exists():
        return SkillAllocator()
    return SkillAllocator.from_manifest(manifest_path)


def _load_tool_shed(config_path: Path) -> ToolShed | None:
    if not config_path.exists():
        return None
    return ToolShed(config_path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teams-dir", type=Path, default=DEFAULT_TEAMS_DIR)
    parser.add_argument("--governance-root", type=Path, default=DEFAULT_GOVERNANCE_ROOT)
    parser.add_argument("--skill-manifest", type=Path, default=DEFAULT_SKILL_MANIFEST)
    parser.add_argument("--tool-shed", type=Path, default=DEFAULT_TOOL_SHED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    rows = build_capability_rows(
        args.teams_dir,
        governance_root=args.governance_root,
        skill_allocator=_load_skill_allocator(args.skill_manifest),
        tool_shed=_load_tool_shed(args.tool_shed),
    )
    write_report(rows, args.output)
    print(f"Wrote {len(rows)} Zone 4 capability rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
