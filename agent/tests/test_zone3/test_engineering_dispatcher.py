"""Z3-03 tests — Zone 3 engineering dispatcher.

The dispatcher is a pure-decision + executor-call object:
  - readiness asks return a deterministic roster with zero Claude calls;
  - substantive tasks select a specialist, build a prompt, and call the
    injected executor;
  - tasks needing QA/Ops/Design/Strategy produce a structured cross-zone
    handoff instead of silently invoking Zone 4.

A fake executor records calls so we can assert "no Claude spawned" precisely.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zone3.claude_p_executor import EngineeringRunResult
from zone3.engineering_config import load_engineering_team_config
from zone3.engineering_dispatcher import (
    CrossZoneHandoff,
    EngineeringDispatcher,
    classify_cross_zone_handoff,
    is_engineering_readiness_prompt,
    render_engineering_readiness,
    select_engineering_specialist,
)


class FakeExecutor:
    """Records every run() call; returns a canned success result."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(
        self,
        *,
        specialist: str,
        prompt: str,
        cwd: Path,
        timeout_seconds: int,
    ) -> EngineeringRunResult:
        self.calls.append(
            {
                "specialist": specialist,
                "prompt": prompt,
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
            }
        )
        return EngineeringRunResult(
            specialist=specialist,
            success=True,
            stdout=f"{specialist} done",
            stderr="",
            exit_code=0,
            duration_seconds=0.0,
        )


@pytest.fixture()
def config():
    return load_engineering_team_config()


@pytest.fixture()
def dispatcher(config):
    return EngineeringDispatcher(config=config, executor=FakeExecutor())


# --- readiness --------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    ["ready to work?", "READY?", "status", "roster", "who is on the team"],
)
def test_readiness_prompts_detected(prompt: str) -> None:
    assert is_engineering_readiness_prompt(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    ["review the latest diff", "sketch the API boundary", "fix the bug"],
)
def test_substantive_prompts_not_readiness(prompt: str) -> None:
    assert is_engineering_readiness_prompt(prompt) is False


async def test_readiness_does_not_spawn_claude(dispatcher) -> None:
    result = await dispatcher.route("ready to work?", cwd=Path.cwd())
    assert result.success is True
    assert "engineering-chief" in result.stdout
    assert dispatcher.executor.calls == []


def test_render_readiness_lists_chief_and_specialists(config) -> None:
    text = render_engineering_readiness(config)
    assert "engineering-chief" in text
    assert "engineering-code-reviewer" in text
    assert "Zone 3" in text


# --- specialist selection ---------------------------------------------------


def test_select_code_reviewer(config) -> None:
    chosen = select_engineering_specialist(config, "review the latest diff")
    assert chosen.name == "engineering-code-reviewer"


def test_select_backend_architect(config) -> None:
    chosen = select_engineering_specialist(
        config, "sketch the safest API boundary for team artifacts"
    )
    assert chosen.name in {
        "engineering-backend-architect",
        "engineering-api-engineer",
    }


def test_select_defaults_when_ambiguous(config) -> None:
    chosen = select_engineering_specialist(config, "do something vague")
    assert chosen.name in {s.name for s in config.specialists}


# --- substantive routing ----------------------------------------------------


async def test_substantive_route_reaches_executor(dispatcher) -> None:
    result = await dispatcher.route("review the latest diff", cwd=Path("/tmp/x"))
    assert result.success is True
    assert len(dispatcher.executor.calls) == 1
    call = dispatcher.executor.calls[0]
    assert call["specialist"] == "engineering-code-reviewer"
    assert "review the latest diff" in call["prompt"]
    assert call["timeout_seconds"] == dispatcher.config.timeout_seconds


# --- cross-zone handoff -----------------------------------------------------


def test_qa_escalation_classified() -> None:
    handoff = classify_cross_zone_handoff("verify this needs broader QA coverage")
    assert isinstance(handoff, CrossZoneHandoff)
    assert handoff.target_zone == 4
    assert handoff.department == "qa"


def test_ops_escalation_only_with_infra_scope() -> None:
    handoff = classify_cross_zone_handoff("prepare deploy risk notes for infra")
    assert handoff is not None
    assert handoff.department == "ops"


def test_no_handoff_for_pure_engineering() -> None:
    assert classify_cross_zone_handoff("review the latest diff") is None


async def test_handoff_returns_structured_result_without_executor(dispatcher) -> None:
    result = await dispatcher.route(
        "verify this needs broader QA coverage", cwd=Path.cwd()
    )
    # Handoff is surfaced as a deterministic result; Zone 4 is NOT invoked here.
    assert result.success is True
    assert "handoff" in result.stdout.lower()
    assert "qa" in result.stdout.lower()
    assert dispatcher.executor.calls == []
