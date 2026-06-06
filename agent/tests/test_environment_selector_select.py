"""EnvironmentSelector.select() — task-class × environment matrix (#564)."""
from __future__ import annotations


from bridge.environment_selector import EnvironmentSelector
from bridge.work_order import Environment, WorkOrder


def _wo(skill: str) -> WorkOrder:
    return WorkOrder.create(intent="x", skill=skill, project="p")


# AC-3: readonly skills → SUBAGENT
def test_select_readonly_skill_returns_subagent():
    s = EnvironmentSelector()
    env, rat = s.select(_wo("chat"))
    assert env == Environment.SUBAGENT
    assert "readonly" in rat


def test_select_chat_skill_returns_subagent():
    s = EnvironmentSelector()
    env, _ = s.select(_wo("chat"))
    assert env == Environment.SUBAGENT


def test_select_query_skill_returns_subagent():
    s = EnvironmentSelector()
    env, _ = s.select(_wo("query"))
    assert env == Environment.SUBAGENT


# AC-4: filesystem skills → WORKTREE
def test_select_filesystem_skill_returns_worktree():
    s = EnvironmentSelector()
    env, rat = s.select(_wo("fix-test"))
    assert env == Environment.WORKTREE
    assert "filesystem" in rat


def test_select_ship_feature_returns_worktree():
    s = EnvironmentSelector()
    env, _ = s.select(_wo("ship-feature"))
    assert env == Environment.WORKTREE


def test_select_refactor_returns_worktree():
    s = EnvironmentSelector()
    env, _ = s.select(_wo("refactor"))
    assert env == Environment.WORKTREE


# AC-5: department skills → DEPARTMENT
def test_select_department_skill_returns_department():
    s = EnvironmentSelector()
    env, _ = s.select(_wo("board-review"))
    assert env == Environment.DEPARTMENT


def test_select_qa_skill_returns_department():
    s = EnvironmentSelector()
    env, _ = s.select(_wo("qa-review"))
    assert env == Environment.DEPARTMENT


# Fallback: unknown skill → SUBAGENT
def test_select_unknown_skill_falls_back_to_subagent():
    s = EnvironmentSelector()
    env, rat = s.select(_wo("made-up-skill"))
    assert env == Environment.SUBAGENT
    assert "default" in rat


def test_select_returns_rationale_string():
    """select() always returns a non-empty rationale string."""
    s = EnvironmentSelector()
    for skill in ["chat", "fix-test", "board-review", "unknown-xyz"]:
        env, rat = s.select(_wo(skill))
        assert isinstance(rat, str) and len(rat) > 0, f"Empty rationale for skill={skill}"


def test_select_does_not_modify_history():
    """select() must NOT call record_usage internally — caller decides when to record."""
    s = EnvironmentSelector()
    s.select(_wo("chat"))
    s.select(_wo("fix-test"))
    assert len(s._history) == 0, "select() must not auto-record usage"
