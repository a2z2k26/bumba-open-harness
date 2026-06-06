"""Z3-04 tests — governance bundles + prompt loading for Zone 3 engineering.

Every configured engineering agent (chief + specialists) must have a governance
bundle (CLAUDE.md, SOUL.md, ARTIFACTS.md). Prompt assembly must place governance
before the task and must never load a Zone 4 governance path. Governance files
are line-capped to prevent context bloat.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zone3.engineering_config import load_engineering_team_config
from zone3.engineering_prompts import (
    GOVERNANCE_FILE_NAMES,
    GOVERNANCE_LINE_CAP,
    ZONE3_GOVERNANCE_ROOT,
    build_engineering_prompt,
    governance_bundle_dir,
    load_zone3_governance,
)


@pytest.fixture()
def config():
    return load_engineering_team_config()


def _all_agent_names(config) -> list[str]:
    return [config.chief_name, *[s.name for s in config.specialists]]


def test_every_agent_has_a_governance_bundle(config) -> None:
    for name in _all_agent_names(config):
        bundle = governance_bundle_dir(name)
        assert bundle.is_dir(), f"missing governance dir for {name}: {bundle}"
        for filename in GOVERNANCE_FILE_NAMES:
            path = bundle / filename
            assert path.is_file(), f"missing {filename} for {name}"
            assert path.read_text(encoding="utf-8").strip(), f"empty {filename} for {name}"


def test_governance_files_are_line_capped(config) -> None:
    for name in _all_agent_names(config):
        for filename in GOVERNANCE_FILE_NAMES:
            path = governance_bundle_dir(name) / filename
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            assert line_count <= GOVERNANCE_LINE_CAP, (
                f"{name}/{filename} has {line_count} lines (cap {GOVERNANCE_LINE_CAP})"
            )


def test_governance_root_is_zone3_not_zone4() -> None:
    assert "zone3" in ZONE3_GOVERNANCE_ROOT.as_posix()
    assert "zone4" not in ZONE3_GOVERNANCE_ROOT.as_posix()


def test_chief_governance_covers_required_topics(config) -> None:
    text = load_zone3_governance(agent_name=config.chief_name).lower()
    for topic in ("tdd", "worktree", "local ci", "premise", "escalat", "merge to main"):
        assert topic in text, f"chief governance missing topic: {topic}"


def test_load_governance_unknown_agent_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_zone3_governance(agent_name="not-an-engineering-agent")


def test_build_prompt_places_governance_before_task(config) -> None:
    specialist = next(
        s for s in config.specialists if s.name == "engineering-code-reviewer"
    )
    prompt = build_engineering_prompt(config, specialist, "review the diff")
    gov_idx = prompt.lower().index("premise")
    task_idx = prompt.index("review the diff")
    assert gov_idx < task_idx, "governance must precede the task"
    assert "Task:" in prompt


def test_build_prompt_does_not_load_zone4_path(config) -> None:
    specialist = config.specialists[0]
    prompt = build_engineering_prompt(config, specialist, "do work")
    assert "zone4" not in prompt.lower()


def test_governance_bundle_dir_is_under_zone3_engineering(config) -> None:
    bundle = governance_bundle_dir("engineering-chief")
    assert bundle.parent == ZONE3_GOVERNANCE_ROOT
    assert Path(*bundle.parts[-3:]) == Path("zone3/engineering/engineering-chief")
