"""Tests for Sprint 04.03 — expertise injection into _load_system_prompt.

The 40 updatable + 6 read-only expertise files at config/expertise/ are
captured into AgentSpec.expertise_path at config-load time but were never
read by _factory._load_system_prompt before this sprint. These tests assert
the new behaviour: a populated, readable expertise file is appended to the
system prompt with a stable "## Expertise" marker; missing or empty files
fall back to the system prompt unchanged (no dangling separator).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from teams._factory import _load_expertise, _load_system_prompt
from teams._types import AgentSpec


SEPARATOR = "\n\n---\n\n"
EXPERTISE_MARKER = "## Expertise"
REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = REPO_ROOT / "agent"


def _spec(
    *,
    system_prompt_path: str = "",
    expertise_path: str = "",
    name: str = "qa-engineer",
    role: str = "Test design and coverage",
) -> AgentSpec:
    return AgentSpec(
        name=name,
        model="anthropic:claude-sonnet-4-6",
        role=role,
        system_prompt_path=system_prompt_path,
        expertise_path=expertise_path,
    )


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadExpertiseHelper:
    def test_empty_path_returns_empty_string(self):
        assert _load_expertise(_spec(expertise_path="")) == ""

    def test_missing_file_warns_and_returns_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        ghost = tmp_path / "missing.md"
        spec = _spec(expertise_path=str(ghost))
        with caplog.at_level(logging.WARNING, logger="teams._factory"):
            result = _load_expertise(spec)
        assert result == ""
        assert any("Expertise file missing" in r.message for r in caplog.records)

    def test_populated_file_returns_marked_block(self, tmp_path: Path):
        body = "# Role\nDesign tests."
        path = _write(tmp_path / "exp.md", body)
        result = _load_expertise(_spec(expertise_path=str(path)))
        assert result == f"{EXPERTISE_MARKER}\n\n{body}"

    def test_whitespace_only_file_returns_empty(self, tmp_path: Path):
        path = _write(tmp_path / "blank.md", "   \n\n\t  \n")
        assert _load_expertise(_spec(expertise_path=str(path))) == ""


class TestLoadSystemPromptWithExpertise:
    def test_expertise_file_present_appends_with_separator(self, tmp_path: Path):
        sp = _write(tmp_path / "sp.md", "You are a careful QA engineer.")
        ex_body = "Pyramid: many unit tests, fewer integration, even fewer E2E."
        ex = _write(tmp_path / "exp.md", ex_body)
        spec = _spec(system_prompt_path=str(sp), expertise_path=str(ex))

        result = _load_system_prompt(spec)

        # Sprint 24: _load_system_prompt now prepends tier doctrine. The
        # base+expertise composition still produces the same agent section,
        # which lands at the END of the result — assert on suffix.
        expected_agent_section = (
            "You are a careful QA engineer."
            + SEPARATOR
            + EXPERTISE_MARKER
            + "\n\n"
            + ex_body
        )
        assert result.endswith(expected_agent_section)
        # And the doctrine block prefixes the result
        assert result.startswith("# Specialist Doctrine") or result.startswith("# Chief Doctrine")

    def test_expertise_file_missing_returns_system_prompt_unchanged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        sp = _write(tmp_path / "sp.md", "You are a careful QA engineer.")
        ghost = tmp_path / "exp-missing.md"
        spec = _spec(system_prompt_path=str(sp), expertise_path=str(ghost))

        with caplog.at_level(logging.WARNING, logger="teams._factory"):
            result = _load_system_prompt(spec)

        # Sprint 24: doctrine prefix expected; the agent section is the suffix.
        # No expertise marker should appear since the file is missing.
        assert result.endswith("You are a careful QA engineer.")
        assert EXPERTISE_MARKER not in result
        assert any("Expertise file missing" in r.message for r in caplog.records)

    def test_expertise_path_empty_returns_system_prompt_unchanged(
        self, tmp_path: Path
    ):
        sp = _write(tmp_path / "sp.md", "You are a careful QA engineer.")
        spec = _spec(system_prompt_path=str(sp), expertise_path="")

        result = _load_system_prompt(spec)

        # Sprint 24: doctrine prepended; no expertise content.
        assert result.endswith("You are a careful QA engineer.")
        assert EXPERTISE_MARKER not in result

    def test_expertise_file_empty_returns_system_prompt_unchanged(
        self, tmp_path: Path
    ):
        sp = _write(tmp_path / "sp.md", "You are a careful QA engineer.")
        ex = _write(tmp_path / "exp-blank.md", "   \n\n\t\n")
        spec = _spec(system_prompt_path=str(sp), expertise_path=str(ex))

        result = _load_system_prompt(spec)

        # Sprint 24: doctrine prepended; no expertise content.
        assert result.endswith("You are a careful QA engineer.")
        assert EXPERTISE_MARKER not in result

    def test_agent_prefixed_paths_resolve_when_cwd_is_agent_root(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """Production launchd runs from agent/ while YAML paths use agent/config/."""
        monkeypatch.chdir(AGENT_ROOT)
        spec = _spec(
            name="board-ceo",
            role="Chairs the Strategy Board.",
            system_prompt_path="agent/config/agents/zone4/board/board-ceo.md",
            expertise_path="agent/config/expertise/updatable/board-ceo.md",
        )

        with caplog.at_level(logging.WARNING, logger="teams._factory"):
            result = _load_system_prompt(spec, tier="chief")

        assert "Board CEO" in result
        assert "{{ROSTER}}" in result
        assert "agent: board-ceo" in result
        messages = [record.message for record in caplog.records]
        assert not any("System prompt file not found" in msg for msg in messages)
        assert not any("Expertise file missing" in msg for msg in messages)
