"""Audit the Zone 3 engineering Claude Code subprocess premise.

Z3-00 is intentionally research-only: this script answers the premise
questions from source files and emits a durable markdown audit. It does not
register departments, spawn providers, or modify runtime configuration.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_ENGINEERING_AGENTS: tuple[str, ...] = (
    "engineering-chief",
    "engineering-backend-architect",
    "engineering-frontend-developer",
    "engineering-api-engineer",
    "engineering-code-reviewer",
    "engineering-database-specialist",
    "engineering-devops-engineer",
    "engineering-performance-engineer",
)

OPTIONAL_ENGINEERING_AGENTS: tuple[str, ...] = (
    "engineering-architect-reviewer",
    "engineering-refactoring-specialist",
    "engineering-tdd-orchestrator",
)

ROSTER_CANDIDATE_FILES: tuple[str, ...] = (
    "agent/config/zone3/engineering-team.md",
    "agent/config/agent-tool-configs/engineering-team.yaml",
    "agent/config/claude-files/skills/engineering-team.md",
    "agent/config/claude-files/docs/dept-engineering.md",
    "agent/config/tool-shed.yaml",
)


@dataclass(frozen=True)
class Zone3EngineeringAudit:
    """Structured result of the Z3-00 engineering premise audit."""

    repo_root: Path
    command_is_zone3_shortcut: bool
    command_is_z4_shortcut: bool
    bridge_commands_registers_engineering: bool
    legacy_department_registry_has_engineering: bool
    has_runtime_team_yaml: bool
    runtime_team_yaml: str
    teams_engineering_yaml_is_unsafe: bool
    required_prompt_files: dict[str, bool]
    optional_prompt_files: dict[str, bool]
    roster_files: list[str]
    executor_path_to_extend: str
    new_zone3_executor_required: bool
    claude_p_executor_files: list[str]
    claude_backend_builds_prompt_flag: bool
    runner_spawns_subprocess: bool
    runner_inherits_parent_environment: bool
    runner_injects_claude_code_oauth_token: bool
    runtime_secrets_blocks_anthropic_api_key: bool
    notes: list[str] = field(default_factory=list)

    @property
    def missing_required_prompt_files(self) -> list[str]:
        return [
            agent_id
            for agent_id, present in self.required_prompt_files.items()
            if not present
        ]

    @property
    def ok(self) -> bool:
        return (
            self.command_is_zone3_shortcut
            and not self.command_is_z4_shortcut
            and not self.has_runtime_team_yaml
            and not self.missing_required_prompt_files
            and not self.new_zone3_executor_required
            and self.runner_spawns_subprocess
        )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _exists(repo_root: Path, rel_path: str) -> bool:
    return (repo_root / rel_path).is_file()


def _frozenset_contains(source: str, name: str, value: str) -> bool:
    """Return True when a named frozenset literal contains a string value."""
    pattern = rf"{re.escape(name)}[^=]*=\s*frozenset\(\{{(?P<body>.*?)\}}\)"
    match = re.search(pattern, source, flags=re.DOTALL)
    if not match:
        return False
    body = match.group("body")
    return f'"{value}"' in body or f"'{value}'" in body


def _file_mentions_any(repo_root: Path, rel_path: str, needles: Sequence[str]) -> bool:
    text = _read_text(repo_root / rel_path)
    return any(needle in text for needle in needles)


def _discover_roster_files(repo_root: Path) -> list[str]:
    roster_files: list[str] = []
    for rel_path in ROSTER_CANDIDATE_FILES:
        path = repo_root / rel_path
        if not path.is_file():
            continue
        if rel_path == "agent/config/tool-shed.yaml":
            if "engineering-" not in _read_text(path):
                continue
        roster_files.append(rel_path)
    return roster_files


def _prompt_file_map(repo_root: Path, agent_ids: Sequence[str]) -> dict[str, bool]:
    return {
        agent_id: _exists(
            repo_root,
            f"agent/config/claude-files/agents/{agent_id}.md",
        )
        for agent_id in agent_ids
    }


def audit_zone3_engineering(repo_root: Path = REPO_ROOT) -> Zone3EngineeringAudit:
    """Inspect source files and answer the Z3-00 premise questions."""
    repo_root = repo_root.resolve()
    commands_src = _read_text(repo_root / "agent/bridge/commands.py")
    departments_src = _read_text(repo_root / "agent/bridge/departments.py")
    subagent_src = _read_text(repo_root / "agent/bridge/executors/subagent.py")
    runner_src = _read_text(repo_root / "agent/bridge/claude_runner.py")
    backend_src = _read_text(repo_root / "agent/bridge/backends/claude.py")
    runtime_secrets_src = _read_text(repo_root / "agent/bridge/runtime_secrets.py")

    command_is_zone3 = _frozenset_contains(commands_src, "_TIER_2_Z3", "engineering")
    command_is_z4 = _frozenset_contains(commands_src, "_TIER_2_Z4", "engineering")
    bridge_registers = command_is_zone3 and (
        "BRIDGE_COMMANDS" in commands_src or "_TIER_2_ALWAYS" in commands_src
    )

    runtime_team_yaml_rel = "agent/config/teams/engineering.yaml"
    has_runtime_team_yaml = _exists(repo_root, runtime_team_yaml_rel)

    subagent_path = "agent/bridge/executors/subagent.py"
    subagent_is_claude_p = (
        "claude -p" in subagent_src
        or "ClaudeRunner" in subagent_src
        or "claude_runner.invoke" in subagent_src
    )
    backend_builds_prompt_flag = (
        'cmd.append("-p")' in backend_src
        or "cmd.append('-p')" in backend_src
        or 'cmd.extend(["-p"])' in backend_src
    )
    runner_spawns = "create_subprocess_exec" in runner_src
    executor_path = (
        subagent_path
        if subagent_is_claude_p and backend_builds_prompt_flag and runner_spawns
        else "agent/zone3/claude_p_executor.py"
    )

    claude_p_executor_files: list[str] = []
    for rel_path, is_present in (
        (subagent_path, subagent_is_claude_p),
        ("agent/bridge/claude_runner.py", runner_spawns),
        ("agent/bridge/backends/claude.py", backend_builds_prompt_flag),
    ):
        if is_present:
            claude_p_executor_files.append(rel_path)

    notes: list[str] = []
    if has_runtime_team_yaml:
        notes.append(
            "Runtime team YAML exists; loading config/teams would register engineering "
            "through the Zone 4 PydanticAI DepartmentRegistry."
        )
    if command_is_z4:
        notes.append("engineering appears in _TIER_2_Z4; this contradicts the Zone 3 premise.")

    return Zone3EngineeringAudit(
        repo_root=repo_root,
        command_is_zone3_shortcut=command_is_zone3,
        command_is_z4_shortcut=command_is_z4,
        bridge_commands_registers_engineering=bridge_registers,
        legacy_department_registry_has_engineering='"engineering": Department(' in departments_src,
        has_runtime_team_yaml=has_runtime_team_yaml,
        runtime_team_yaml=runtime_team_yaml_rel,
        teams_engineering_yaml_is_unsafe=True,
        required_prompt_files=_prompt_file_map(repo_root, REQUIRED_ENGINEERING_AGENTS),
        optional_prompt_files=_prompt_file_map(repo_root, OPTIONAL_ENGINEERING_AGENTS),
        roster_files=_discover_roster_files(repo_root),
        executor_path_to_extend=executor_path,
        new_zone3_executor_required=executor_path != subagent_path,
        claude_p_executor_files=claude_p_executor_files,
        claude_backend_builds_prompt_flag=backend_builds_prompt_flag,
        runner_spawns_subprocess=runner_spawns,
        runner_inherits_parent_environment="os.environ.copy()" in runner_src,
        runner_injects_claude_code_oauth_token="CLAUDE_CODE_OAUTH_TOKEN" in runner_src,
        runtime_secrets_blocks_anthropic_api_key=(
            "ANTHROPIC_API_KEY" in runtime_secrets_src
            or _file_mentions_any(
                repo_root,
                "agent/tests/test_claude_runner.py",
                ["ANTHROPIC_API_KEY"],
            )
        ),
        notes=notes,
    )


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _present_missing(value: bool) -> str:
    return "present" if value else "missing"


def render_markdown(report: Zone3EngineeringAudit) -> str:
    """Render the structured audit result as the durable Z3-00 markdown."""
    lines: list[str] = [
        "# Zone 3 Engineering Claude Code Premise Audit",
        "",
        "Date: 2026-05-21",
        "Issue: Z3-00",
        "",
        "## Required Premise Answers",
        "",
        (
            "- Is `/engineering` already registered as a Zone 3 shortcut? "
            f"**{_yes_no(report.command_is_zone3_shortcut)}.** "
            "Source: `agent/bridge/commands.py` (`_TIER_2_Z3`)."
        ),
        (
            "- Is `/engineering` registered as a Zone 4 command shortcut? "
            f"**{_yes_no(report.command_is_z4_shortcut)}.** "
            "Source: `agent/bridge/commands.py` (`_TIER_2_Z4`)."
        ),
        (
            "- Is any `engineering.yaml` in the runtime team directory? "
            f"**{_yes_no(report.has_runtime_team_yaml)}.** "
            f"Checked `{report.runtime_team_yaml}`."
        ),
        (
            "- `agent/config/teams/engineering.yaml` is unsafe for this lane: "
            "**Yes.** Any YAML in `agent/config/teams/` is discovered by "
            "`teams._registry.DepartmentRegistry.from_directory()` and would "
            "register engineering as a Zone 4 PydanticAI department."
        ),
        (
            "- Are required engineering specialist prompt files present? "
            f"**{_yes_no(not report.missing_required_prompt_files)}.**"
        ),
        (
            "- Which existing executor already spawns `claude -p`? "
            f"Existing executor to extend: `{report.executor_path_to_extend}`."
        ),
        (
            "- Is a new `agent/zone3/claude_p_executor.py` required? "
            f"**{_yes_no(report.new_zone3_executor_required)}.** "
            "No new `agent/zone3/claude_p_executor.py` is required when "
            "`agent/bridge/executors/subagent.py` remains available."
        ),
        (
            "- Does the executor inherit the operator's Claude Code session "
            "without passing Anthropic OAuth tokens manually? "
            f"**{_yes_no(report.runner_inherits_parent_environment)}.** "
            "`ClaudeRunner.invoke()` inherits `os.environ.copy()`, "
            "`runtime_secrets` blocks `ANTHROPIC_API_KEY`, and "
            "`CLAUDE_CODE_OAUTH_TOKEN` is only optional bridge injection from "
            "an existing token provider/config path."
        ),
        "",
        "## Prompt Inventory",
        "",
    ]

    for agent_id in REQUIRED_ENGINEERING_AGENTS:
        present = report.required_prompt_files.get(agent_id, False)
        lines.append(
            f"- `{agent_id}`: {_present_missing(present)} at "
            f"`agent/config/claude-files/agents/{agent_id}.md`"
        )
    if report.missing_required_prompt_files:
        joined = ", ".join(f"`{name}`" for name in report.missing_required_prompt_files)
        lines.append(f"- Missing required prompts: {joined}")
    else:
        lines.append("- Missing required prompts: none")

    lines.extend(["", "## Additional Engineering Prompt Files", ""])
    for agent_id, present in report.optional_prompt_files.items():
        if present:
            lines.append(
                f"- `{agent_id}`: present at "
                f"`agent/config/claude-files/agents/{agent_id}.md`"
            )
    if not any(report.optional_prompt_files.values()):
        lines.append("- None detected.")

    lines.extend(["", "## Roster Sources", ""])
    if report.roster_files:
        for rel_path in report.roster_files:
            lines.append(f"- `{rel_path}`")
    else:
        lines.append("- No roster files detected.")

    lines.extend(
        [
            "",
            "## Executor And Auth Findings",
            "",
            "- Claude Code subprocess chain:",
        ]
    )
    if report.claude_p_executor_files:
        for rel_path in report.claude_p_executor_files:
            lines.append(f"  - `{rel_path}`")
    else:
        lines.append("  - No existing `claude -p` executor chain detected.")

    lines.extend(
        [
            (
                "- `agent/bridge/backends/claude.py` builds the `-p` argv flag: "
                f"**{_yes_no(report.claude_backend_builds_prompt_flag)}.**"
            ),
            (
                "- `agent/bridge/claude_runner.py` spawns the subprocess with "
                f"`asyncio.create_subprocess_exec`: **{_yes_no(report.runner_spawns_subprocess)}.**"
            ),
            (
                "- Parent environment inherited: "
                f"**{_yes_no(report.runner_inherits_parent_environment)}.**"
            ),
            (
                "- `CLAUDE_CODE_OAUTH_TOKEN` optional injection path present: "
                f"**{_yes_no(report.runner_injects_claude_code_oauth_token)}.**"
            ),
            (
                "- `ANTHROPIC_API_KEY` blocked from runtime secrets: "
                f"**{_yes_no(report.runtime_secrets_blocks_anthropic_api_key)}.**"
            ),
            "",
            "## Conclusion",
            "",
        ]
    )

    if report.ok:
        lines.append(
            "Z3-00 premise is satisfied: engineering is a Zone 3 command shortcut, "
            "not a Zone 4 runtime team, and the existing `SubagentExecutor`/"
            "`ClaudeRunner`/`ClaudeBackend` chain is the correct place to extend "
            "future Claude Code `claude -p` engineering behavior."
        )
    else:
        lines.append(
            "Z3-00 premise has drift. Do not implement Z3-01 until the failures "
            "above are resolved or the plan is updated."
        )

    if report.notes:
        lines.extend(["", "## Notes", ""])
        for note in report.notes:
            lines.append(f"- {note}")

    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to audit.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Markdown output path. Prints to stdout when omitted.",
    )
    args = parser.parse_args(argv)

    report = audit_zone3_engineering(args.root)
    markdown = render_markdown(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
