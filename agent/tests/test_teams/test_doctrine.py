"""Tests for Sprint 24 (Phase 5D) — tier doctrine injection.

Covers:
- Doctrine files exist on disk for every tier and stay under the line cap
- ``_load_doctrine`` returns file content for known tiers
- Missing doctrine file falls back to ``FALLBACK_DOCTRINE`` and logs an error
- Unknown tier raises ValueError (caller bug, not config bug — fail loud)
- ``_load_system_prompt`` prepends the right tier doctrine
- ``build_employee_agents`` produces specialist-doctrine-prefixed prompts
- ``build_manager_agent`` produces chief-doctrine-prefixed prompts AND
  the chief's prompt still contains the roster substitution from Sprint 19
- Final manager prompt order: ``<chief-doctrine>`` then base then roster
  block (substituted) then any expertise
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from teams._factory import (
    FALLBACK_DOCTRINE,
    _DOCTRINE_LINE_CAP,
    _DOCTRINE_ROOT,
    _load_doctrine,
    _load_system_prompt,
    build_employee_agents,
    build_manager_agent,
)
from teams._types import (
    AgentSpec,
    Constraints,
    DepartmentConfig,
)


# ---------------------------------------------------------------------------
# Doctrine files on disk
# ---------------------------------------------------------------------------


class TestDoctrineFilesOnDisk:
    @pytest.mark.parametrize(
        "filename", ["main-agent.md", "chiefs.md", "specialists.md"]
    )
    def test_file_exists(self, filename: str) -> None:
        path = _DOCTRINE_ROOT / filename
        assert path.exists(), f"doctrine file missing: {path}"

    @pytest.mark.parametrize(
        "filename", ["main-agent.md", "chiefs.md", "specialists.md"]
    )
    def test_file_under_line_cap(self, filename: str) -> None:
        path = _DOCTRINE_ROOT / filename
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        assert line_count <= _DOCTRINE_LINE_CAP, (
            f"{filename} has {line_count} lines (cap {_DOCTRINE_LINE_CAP})"
        )

    def test_load_specifications_present_in_chief_doctrine(self) -> None:
        text = (_DOCTRINE_ROOT / "chiefs.md").read_text(encoding="utf-8")
        # Spec asks for these load-bearing keywords
        assert "acknowledge_directive" in text
        assert "delegate" in text
        # Surface kinds the chief is expected to use
        assert "blocker" in text.lower()
        assert "policy_q" in text.lower()
        assert "synthes" in text.lower()  # synthesise / synthesis

    def test_specialist_doctrine_names_mandatory_result_surface(self) -> None:
        text = (_DOCTRINE_ROOT / "specialists.md").read_text(encoding="utf-8")
        assert "surface" in text.lower()
        assert "result" in text.lower()
        # Spec: "MUST emit at least one RESULT surface per task"
        assert "must" in text.lower()


# ---------------------------------------------------------------------------
# _load_doctrine
# ---------------------------------------------------------------------------


class TestLoadDoctrine:
    def test_loads_each_tier(self) -> None:
        for tier in ("main", "chief", "specialist"):
            text = _load_doctrine(tier)
            assert text  # non-empty
            # Real on-disk files start with a markdown heading; fallbacks
            # also start with one but include the word "(fallback)".
            assert text.startswith("#")

    def test_unknown_tier_raises_value_error(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            _load_doctrine("operator")  # not a real tier
        assert "Unknown doctrine tier" in str(excinfo.value)

    def test_missing_file_falls_back_and_logs_error(
        self, tmp_path: Path, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Point the doctrine root at an empty directory
        monkeypatch.setattr(
            "teams._factory._DOCTRINE_ROOT", tmp_path
        )
        with caplog.at_level(logging.ERROR, logger="teams._factory"):
            text = _load_doctrine("specialist")
        assert text == FALLBACK_DOCTRINE["specialist"]
        assert any("doctrine.missing" in r.message for r in caplog.records)

    def test_over_cap_logs_warning_but_loads(
        self, tmp_path: Path, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Stage an over-cap doctrine file
        big = tmp_path / "specialists.md"
        big.write_text("# Doctrine\n\n" + ("line\n" * 200), encoding="utf-8")
        monkeypatch.setattr(
            "teams._factory._DOCTRINE_ROOT", tmp_path
        )
        with caplog.at_level(logging.WARNING, logger="teams._factory"):
            text = _load_doctrine("specialist")
        assert "line\nline\nline" in text  # loaded anyway
        assert any("doctrine.over_cap" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _load_system_prompt — tier-specific prepend
# ---------------------------------------------------------------------------


class TestLoadSystemPromptInjectsDoctrine:
    def test_specialist_default_tier(self, tmp_path: Path) -> None:
        sp = tmp_path / "sp.md"
        sp.write_text("You are alpha.", encoding="utf-8")
        spec = AgentSpec(
            name="alpha", model="anthropic:claude-sonnet-4-6",
            role="alpha", system_prompt_path=str(sp),
        )
        result = _load_system_prompt(spec)
        # Default tier is specialist
        assert result.startswith("# Specialist Doctrine")
        assert result.endswith("You are alpha.")

    def test_chief_tier(self, tmp_path: Path) -> None:
        sp = tmp_path / "chief.md"
        sp.write_text("You are the chief.", encoding="utf-8")
        spec = AgentSpec(
            name="c-chief", model="anthropic:claude-opus-4-6",
            role="chief", system_prompt_path=str(sp),
        )
        result = _load_system_prompt(spec, tier="chief")
        assert result.startswith("# Chief Doctrine")
        assert result.endswith("You are the chief.")

    def test_main_tier(self) -> None:
        spec = AgentSpec(
            name="bumba", model="anthropic:claude-opus-4-6",
            role="main",
        )
        result = _load_system_prompt(spec, tier="main")
        assert result.startswith("# Main Agent Doctrine")
        # No system_prompt_path → falls back to "You are bumba. main"
        assert "You are bumba" in result


# ---------------------------------------------------------------------------
# build_employee_agents — specialist doctrine reaches the agent
# ---------------------------------------------------------------------------


def _config_for_factory() -> DepartmentConfig:
    return DepartmentConfig(
        name="dept-d",
        zone=4,
        description="",
        manager=AgentSpec(name="d-chief", model="anthropic:claude-opus-4-6", role="chief"),
        employees=(
            AgentSpec(name="alpha", model="anthropic:claude-sonnet-4-6", role="alpha"),
        ),
        constraints=Constraints(),
    )


class TestFactoryDoctrineWiring:
    def test_specialist_agent_prompt_starts_with_specialist_doctrine(self) -> None:
        config = _config_for_factory()
        employees = build_employee_agents(config)
        # pydantic-ai exposes the system prompt via _system_prompts (a list of
        # callables/strings). We capture by reading the list directly.
        # The first system_prompts entry is the static prompt we passed in.
        sp = employees["alpha"]._system_prompts[0]
        assert sp.startswith("# Specialist Doctrine"), (
            f"specialist prompt should lead with doctrine; got: {sp[:80]}"
        )

    def test_chief_agent_prompt_starts_with_chief_doctrine_and_has_roster(
        self,
    ) -> None:
        config = _config_for_factory()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        sp = manager._system_prompts[0]
        # Chief doctrine must lead
        assert sp.startswith("# Chief Doctrine"), (
            f"chief prompt should lead with chief doctrine; got: {sp[:80]}"
        )
        # Roster block (Sprint 19) must also be present
        assert "Your Team" in sp, "chief prompt missing roster block"
        assert "**alpha**" in sp, "chief roster missing specialist line"
        # Roster must come AFTER doctrine (doctrine is the prefix)
        assert sp.index("# Chief Doctrine") < sp.index("Your Team")
