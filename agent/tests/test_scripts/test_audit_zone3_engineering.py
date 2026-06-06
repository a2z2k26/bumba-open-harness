"""Tests for Z3-00 - deterministic Zone 3 engineering premise audit."""

from __future__ import annotations

from pathlib import Path

import scripts.audit_zone3_engineering as mod


def _write(path: Path, text: str = "stub") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_repo(tmp_path: Path) -> Path:
    """Build the minimum source tree the audit needs to answer Z3-00."""
    _write(
        tmp_path / "agent/bridge/commands.py",
        """
_TIER_2_Z4: frozenset[str] = frozenset({
    "board",
    "departments",
})
_TIER_2_Z3: frozenset[str] = frozenset({
    "engineering",
})
BRIDGE_COMMANDS: set[str] = set(_TIER_2_Z4) | set(_TIER_2_Z3)
""",
    )
    _write(
        tmp_path / "agent/bridge/executors/subagent.py",
        '"""SubagentExecutor - runs a WorkOrder as a subagent `claude -p` invocation."""\n',
    )
    _write(
        tmp_path / "agent/bridge/claude_runner.py",
        """
env = os.environ.copy()
env.update(_load_secrets_as_env(self.config.data_dir))
if oauth_token:
    env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
self._process = await asyncio.create_subprocess_exec(*cmd, env=env)
""",
    )
    _write(
        tmp_path / "agent/bridge/backends/claude.py",
        """
class ClaudeBackend:
    def build_command(self):
        cmd.append("-p")
""",
    )
    _write(
        tmp_path / "agent/bridge/runtime_secrets.py",
        '_CLAUDE_AUTH_KEYS_BLOCKLIST = frozenset({"ANTHROPIC_API_KEY"})\n',
    )

    _write(tmp_path / "agent/config/zone3/engineering-team.md")
    _write(tmp_path / "agent/config/agent-tool-configs/engineering-team.yaml")
    _write(tmp_path / "agent/config/claude-files/skills/engineering-team.md")
    _write(tmp_path / "agent/config/claude-files/docs/dept-engineering.md")
    for agent_id in mod.REQUIRED_ENGINEERING_AGENTS:
        _write(tmp_path / f"agent/config/claude-files/agents/{agent_id}.md")
    return tmp_path


def test_audit_classifies_engineering_as_zone3_shortcut(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)

    report = mod.audit_zone3_engineering(repo)

    assert report.command_is_zone3_shortcut is True
    assert report.command_is_z4_shortcut is False
    assert report.has_runtime_team_yaml is False
    assert report.teams_engineering_yaml_is_unsafe is True
    assert report.executor_path_to_extend == "agent/bridge/executors/subagent.py"
    assert report.new_zone3_executor_required is False


def test_audit_reports_prompt_and_roster_inventory(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    (repo / "agent/config/claude-files/agents/engineering-api-engineer.md").unlink()

    report = mod.audit_zone3_engineering(repo)

    assert report.missing_required_prompt_files == ["engineering-api-engineer"]
    assert "agent/config/zone3/engineering-team.md" in report.roster_files
    assert "agent/config/agent-tool-configs/engineering-team.yaml" in report.roster_files
    assert "agent/config/claude-files/docs/dept-engineering.md" in report.roster_files


def test_render_markdown_answers_required_premise_questions(tmp_path: Path) -> None:
    report = mod.audit_zone3_engineering(_fake_repo(tmp_path))

    markdown = mod.render_markdown(report)

    assert "Is `/engineering` already registered as a Zone 3 shortcut? **Yes.**" in markdown
    assert "Is any `engineering.yaml` in the runtime team directory? **No.**" in markdown
    assert "`agent/config/teams/engineering.yaml` is unsafe" in markdown
    assert "Existing executor to extend: `agent/bridge/executors/subagent.py`." in markdown
    assert "No new `agent/zone3/claude_p_executor.py` is required" in markdown
    assert "ANTHROPIC_API_KEY" in markdown
