"""Tests for execution environment selection and anti-default-gravity."""

from __future__ import annotations

import pytest

from bridge.environment_selector import EnvironmentSelector
from bridge.work_order import Environment


def test_record_and_get_stats() -> None:
    selector = EnvironmentSelector()
    selector.record_usage(Environment.SUBAGENT)
    selector.record_usage(Environment.SUBAGENT)
    selector.record_usage(Environment.TMUX)
    stats = selector.get_stats()
    assert stats.total == 3
    assert stats.distribution[Environment.SUBAGENT] == 2
    assert stats.distribution[Environment.TMUX] == 1


def test_skew_detected_above_threshold() -> None:
    selector = EnvironmentSelector(skew_threshold=0.6)
    for _ in range(7):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(3):
        selector.record_usage(Environment.TMUX)
    assert selector.is_skewed() is True
    skew = selector.get_skew_report()
    assert Environment.SUBAGENT in skew


def test_no_skew_when_balanced() -> None:
    selector = EnvironmentSelector(skew_threshold=0.6)
    for _ in range(3):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(3):
        selector.record_usage(Environment.TMUX)
    for _ in range(3):
        selector.record_usage(Environment.WORKTREE)
    assert selector.is_skewed() is False


def test_no_skew_with_no_data() -> None:
    selector = EnvironmentSelector()
    assert selector.is_skewed() is False


def test_validate_rationale_rejects_weak() -> None:
    selector = EnvironmentSelector()
    for _ in range(8):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(2):
        selector.record_usage(Environment.TMUX)
    warning = selector.validate_selection(Environment.SUBAGENT, "subagent because simple")
    assert warning is not None
    assert "skew" in warning.lower() or "over-indexing" in warning.lower()


def test_validate_rationale_passes_when_balanced() -> None:
    selector = EnvironmentSelector()
    for _ in range(3):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(3):
        selector.record_usage(Environment.TMUX)
    for _ in range(3):
        selector.record_usage(Environment.WORKTREE)
    warning = selector.validate_selection(Environment.SUBAGENT, "Quick focused task")
    assert warning is None


def test_recent_window() -> None:
    selector = EnvironmentSelector(window_size=5, skew_threshold=0.6)
    for _ in range(10):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(3):
        selector.record_usage(Environment.TMUX)
    for _ in range(2):
        selector.record_usage(Environment.WORKTREE)
    assert selector.is_skewed() is False


# ---------------------------------------------------------------------------
# Sprint 03.07 — skew warning as a first-class dispatch signal.
# ---------------------------------------------------------------------------


def test_validate_selection_returns_none_when_balanced() -> None:
    """A balanced history must produce no skew warning."""
    selector = EnvironmentSelector(skew_threshold=0.6)
    for _ in range(3):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(3):
        selector.record_usage(Environment.TMUX)
    for _ in range(3):
        selector.record_usage(Environment.WORKTREE)
    assert (
        selector.validate_selection(Environment.SUBAGENT, "readonly-default: subagent")
        is None
    )


def test_validate_selection_returns_warning_when_skewed() -> None:
    """A skewed history must surface a non-empty warning string for the
    over-indexed environment."""
    selector = EnvironmentSelector(skew_threshold=0.6)
    for _ in range(8):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(2):
        selector.record_usage(Environment.TMUX)
    warning = selector.validate_selection(
        Environment.SUBAGENT, "readonly-default: subagent"
    )
    assert isinstance(warning, str) and warning
    # The warning text quotes the offending environment value
    assert Environment.SUBAGENT.value in warning


def test_dispatch_logs_skew_warning() -> None:
    """dispatch path must call validate_selection, log at WARNING when the
    warning fires, and publish a `dispatcher.selector_skew_warning` event
    on the autonomy event bus.

    Source-level assertion: Sprint P6.1 (#1591) split the integration
    across two files (``app.py`` retains the seam; the dispatch body lives
    in ``bridge/invocation_pipeline.py``). We scan the combined text the
    same way the existing test_app_env_selector_integration.py suite does.
    """
    import pathlib
    bridge = pathlib.Path(__file__).parent.parent / "bridge"
    text = (bridge / "app.py").read_text() + "\n" + (
        bridge / "invocation_pipeline.py"
    ).read_text()
    assert "_env_selector.validate_selection" in text, (
        "dispatch path must call self._env_selector.validate_selection"
    )
    assert "env_selector skew detected" in text, (
        "dispatch path must log a WARNING when env_selector returns a skew warning"
    )
    assert '"dispatcher.selector_skew_warning"' in text, (
        "dispatch path must publish the dispatcher.selector_skew_warning event "
        "when validate_selection returns a non-None warning"
    )


def test_dispatch_threads_skew_into_rationale() -> None:
    """When validate_selection returns a warning, the dispatch path must
    thread `skew_warning: ...` into the rationale passed to
    with_environment so the WorkOrder carries the skew context for
    downstream observers."""
    import pathlib
    bridge = pathlib.Path(__file__).parent.parent / "bridge"
    text = (bridge / "app.py").read_text() + "\n" + (
        bridge / "invocation_pipeline.py"
    ).read_text()
    assert "skew_warning:" in text, (
        "dispatch path must thread `skew_warning: ...` into the WorkOrder rationale"
    )
    # And the threaded rationale must precede with_environment(...)
    skew_idx = text.find("skew_warning:")
    with_env_idx = text.find("wo.with_environment(env, rationale)")
    assert skew_idx != -1 and with_env_idx != -1
    assert skew_idx < with_env_idx, (
        "skew_warning rationale-threading must happen before with_environment"
    )


def test_force_alternative_default_false_no_change() -> None:
    """Default config (force_alternative=False): even with a skewed
    history, select() returns the class default. Skew is observable but
    NOT auto-corrected — that is the spec contract for this sprint."""
    from bridge.work_order import WorkOrder
    selector = EnvironmentSelector(skew_threshold=0.6)  # force_alternative=False
    # Build a SUBAGENT-skewed history (≥60% over the last 20).
    for _ in range(15):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(5):
        selector.record_usage(Environment.TMUX)
    assert selector.is_skewed() is True
    wo = WorkOrder.create(intent="explain x", skill="explain-feature", project="")
    env, rationale = selector.select(wo)
    # readonly-class default is SUBAGENT — unchanged despite skew.
    assert env is Environment.SUBAGENT
    assert "readonly-default" in rationale
    assert "force_alternative" not in rationale


# ---------------------------------------------------------------------------
# Sprint S2.3 (Backend Operability, #2280) — route-selection guard.
# Selector must never auto-pick a non-routable executor (e.g. E2B while
# its status is ``stub``). The dispatcher rejects explicit assignments;
# the selector is the symmetric guard for the *automatic* path.
# ---------------------------------------------------------------------------


def test_is_environment_routable_predicate() -> None:
    """The shared predicate accepts the three routable statuses documented
    on Dispatcher.get_executor_statuses and rejects everything else."""
    from bridge.environment_selector import is_environment_routable

    assert is_environment_routable("active") is True
    assert is_environment_routable("active_low_traffic") is True
    assert is_environment_routable("conditional_active") is True
    # Non-routable statuses
    assert is_environment_routable("stub") is False
    assert is_environment_routable("conditional_unwired") is False
    assert is_environment_routable("unknown") is False
    assert is_environment_routable("") is False


def test_environment_selector_excludes_stubbed_e2b() -> None:
    """Sprint S2.3 — when ``executor_statuses`` reports ``e2b: stub`` the
    selector must not return ``Environment.E2B`` even under a skewed
    filesystem history that would otherwise reach E2B as the third
    fallback in the per-class fallback order."""
    from bridge.work_order import WorkOrder

    selector = EnvironmentSelector(skew_threshold=0.6, force_alternative=True)
    # Skew >60% toward WORKTREE (the filesystem default) so the
    # force_alternative branch fires; the fallback walk would otherwise
    # consider TMUX then E2B. With E2B status=stub, E2B must be skipped
    # and TMUX is returned.
    for _ in range(15):
        selector.record_usage(Environment.WORKTREE)
    for _ in range(5):
        selector.record_usage(Environment.TMUX)
    assert selector.is_skewed() is True

    wo = WorkOrder.create(intent="ship the thing", skill="ship-feature", project="p")
    statuses = {
        "subagent": "active",
        "department": "active",
        "worktree": "active_low_traffic",
        "tmux": "conditional_active",
        "e2b": "stub",
    }
    env, _ = selector.select(wo, executor_statuses=statuses)
    assert env is not Environment.E2B


def test_environment_selector_skips_e2b_when_default_unroutable() -> None:
    """Sprint S2.3 — if (hypothetically) the per-class default itself
    becomes non-routable, ``select`` must skip it and walk the fallback
    order, never returning a stubbed env. Covers the default-bypass
    branch alongside the skew-rebalance branch."""
    from bridge.work_order import WorkOrder

    selector = EnvironmentSelector(skew_threshold=0.6)
    wo = WorkOrder.create(intent="ship the thing", skill="ship-feature", project="p")
    # filesystem default = WORKTREE — pretend it has gone offline. TMUX
    # is the next entry; E2B remains stubbed and must be skipped.
    statuses = {
        "subagent": "active",
        "department": "active",
        "worktree": "stub",
        "tmux": "conditional_active",
        "e2b": "stub",
    }
    env, rationale = selector.select(wo, executor_statuses=statuses)
    assert env is Environment.TMUX
    assert env is not Environment.E2B
    assert "not routable" in rationale


def test_environment_selector_no_status_map_preserves_history() -> None:
    """Sprint S2.3 — passing no ``executor_statuses`` preserves the
    pre-S2.3 behaviour: the per-class default is returned regardless of
    which executors might be stubbed at runtime. Guards against silent
    behaviour drift for callers that have not yet been updated."""
    from bridge.work_order import WorkOrder

    selector = EnvironmentSelector(skew_threshold=0.6)
    wo = WorkOrder.create(intent="explain x", skill="explain-feature", project="p")
    env, rationale = selector.select(wo)
    assert env is Environment.SUBAGENT
    assert "readonly-default" in rationale


def test_force_alternative_true_picks_second() -> None:
    """force_alternative=True + skewed history: select() returns the
    second-highest-scoring (per-class fallback) env with a rationale that
    flags the rebalance."""
    from bridge.work_order import WorkOrder
    selector = EnvironmentSelector(
        skew_threshold=0.6,
        force_alternative=True,
    )
    # Skew toward SUBAGENT (the readonly-class default).
    for _ in range(15):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(5):
        selector.record_usage(Environment.TMUX)
    assert selector.is_skewed() is True
    wo = WorkOrder.create(intent="explain x", skill="explain-feature", project="")
    env, rationale = selector.select(wo)
    # Default would be SUBAGENT; rebalanced to the next available
    # readonly-class fallback (WORKTREE).
    assert env is not Environment.SUBAGENT
    assert env is Environment.WORKTREE
    assert "force_alternative" in rationale
    assert "skewed" in rationale


# ---------------------------------------------------------------------------
# Sprint 03.04 — _derive_department() single-source-of-truth helper used by
# the 3 production WorkOrder creation sites to populate
# WorkOrder.department_target. Must read the exact same _SKILL_CLASS_RULES
# table as _classify_skill so derivation can never drift from classification.
# ---------------------------------------------------------------------------


def test_derive_department_board() -> None:
    from bridge.environment_selector import _derive_department
    assert _derive_department("board") == "board"
    assert _derive_department("board-of-directors") == "board"


def test_derive_department_qa() -> None:
    from bridge.environment_selector import _derive_department
    assert _derive_department("qa-tests") == "qa"
    assert _derive_department("qa_audit") == "qa"


def test_derive_department_strategy() -> None:
    from bridge.environment_selector import _derive_department
    assert _derive_department("strategy-roadmap") == "strategy"


def test_derive_department_design() -> None:
    from bridge.environment_selector import _derive_department
    assert _derive_department("design-explore") == "design"


def test_derive_department_ops() -> None:
    from bridge.environment_selector import _derive_department
    assert _derive_department("ops-runbook") == "ops"


def test_derive_department_dept() -> None:
    from bridge.environment_selector import _derive_department
    assert _derive_department("dept-engineering") == "dept"


def test_derive_department_returns_none_for_non_department() -> None:
    """Skills that don't match a department rule must return None.

    Critical regression guard: if this returns a string for a non-department
    skill, _every_ WorkOrder gets a department_target and DepartmentExecutor
    rejects them. The 3 creation sites must see None for filesystem/readonly.
    """
    from bridge.environment_selector import _derive_department
    # Filesystem-class skills — no department.
    assert _derive_department("fix-test-failure") is None
    assert _derive_department("refactor-auth") is None
    assert _derive_department("implement-jwt") is None
    # Readonly-class skills — no department.
    assert _derive_department("chat") is None
    assert _derive_department("query-knowledge") is None
    assert _derive_department("summarize-pr") is None
    # Unknown skill — no department.
    assert _derive_department("totally-novel-skill") is None
    # Edge case: empty string.
    assert _derive_department("") is None


def test_derive_department_matches_classify_skill() -> None:
    """Whenever _classify_skill returns 'department', _derive_department
    must return a non-None value, and vice versa. This is the
    single-source-of-truth invariant — both functions read the same
    _SKILL_CLASS_RULES table, so they cannot drift.
    """
    from bridge.environment_selector import _classify_skill, _derive_department, _SKILL_CLASS_RULES
    sample_skills = [
        "board", "qa-tests", "qa_audit", "strategy-roadmap",
        "design-explore", "ops-runbook", "dept-engineering",
        "fix-test", "refactor", "implement", "chat", "query",
        "summarize", "review-pr", "novel-skill", "",
    ]
    for skill in sample_skills:
        klass = _classify_skill(skill)
        derived = _derive_department(skill)
        if klass == "department":
            assert derived is not None, (
                f"skill={skill!r} classified as 'department' but "
                f"_derive_department returned None"
            )
        else:
            assert derived is None, (
                f"skill={skill!r} classified as {klass!r} but "
                f"_derive_department returned {derived!r}"
            )
    # And: _SKILL_CLASS_RULES retains the documented shape.
    assert isinstance(_SKILL_CLASS_RULES, list)
    assert all(isinstance(r, tuple) and len(r) == 2 for r in _SKILL_CLASS_RULES)


# ---------------------------------------------------------------------------
# Sprint 04.01 — Board skill end-to-end through the environment selector.
# ---------------------------------------------------------------------------


def test_board_skill_classifies_as_department() -> None:
    """The "board-query" skill string from _INTENT_SKILL_MAP must classify
    to ``Environment.DEPARTMENT`` and derive department ``"board"``.

    This is the bridge between Sprint 04.01 (CommandRouter → app.py
    _INTENT_SKILL_MAP) and Sprint 03.04 (department_target plumbing).
    The "board-query" skill string is the contract: change the prefix
    rule in _SKILL_CLASS_RULES and this test breaks loudly.
    """
    from bridge.environment_selector import (
        EnvironmentSelector,
        _classify_skill,
        _derive_department,
    )
    from bridge.work_order import Environment, WorkOrder

    skill = "board-query"

    # Skill must classify as department-class — matches "board" prefix in
    # _SKILL_CLASS_RULES.
    assert _classify_skill(skill) == "department"

    # Single-source-of-truth helper must derive the bare department name.
    assert _derive_department(skill) == "board"

    # End-to-end through the selector: a WO with this skill must select
    # Environment.DEPARTMENT (not SUBAGENT, not WORKTREE).
    wo = WorkOrder.create(intent="convene the board", skill=skill, project="bumba")
    selector = EnvironmentSelector()
    env, rationale = selector.select(wo)
    assert env is Environment.DEPARTMENT, (
        f"board-query skill must route to DEPARTMENT, got {env.value!r} "
        f"(rationale: {rationale})"
    )
    assert "department" in rationale.lower()


# ---------------------------------------------------------------------------
# Sprint 04.02 — broaden environment classification to QA / Ops / Strategy /
# Design skill strings. Each test mirrors test_board_skill_classifies_as_department
# above for one of the four department prefixes already present in
# _SKILL_CLASS_RULES (read-only — Sprint 04.02 does not touch that table).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skill, expected_department",
    [
        ("qa-review", "qa"),
        ("ops-diagnose", "ops"),
        ("strategy-analyze", "strategy"),
        ("design-review", "design"),
    ],
)
def test_department_skills_classify_as_department(
    skill: str, expected_department: str
) -> None:
    """Each of the 4 new Sprint 04.02 skill strings must classify as
    ``"department"`` task class, derive the expected bare department name,
    and route to ``Environment.DEPARTMENT`` end-to-end through the selector.

    This is the contract between Sprint 04.02 (CommandRouter → app.py
    _INTENT_SKILL_MAP) and Sprint 03.04 (department_target plumbing). If
    _SKILL_CLASS_RULES changes the prefix order or drops a department
    prefix, these assertions break loudly.

    Note for ``strategy-analyze`` and ``design-review``: the skill string
    contains a readonly substring (``analyze`` / ``review``), but the
    department prefix is declared earlier in _SKILL_CLASS_RULES so
    first-match-wins keeps the classification at ``"department"``.
    """
    from bridge.environment_selector import (
        EnvironmentSelector,
        _classify_skill,
        _derive_department,
    )
    from bridge.work_order import Environment, WorkOrder

    assert _classify_skill(skill) == "department", (
        f"{skill!r} must classify as department-class, not "
        f"{_classify_skill(skill)!r}. If this fails, _SKILL_CLASS_RULES order "
        "may have regressed (department prefixes must precede readonly ones)."
    )

    assert _derive_department(skill) == expected_department, (
        f"_derive_department({skill!r}) returned {_derive_department(skill)!r}, "
        f"expected {expected_department!r}"
    )

    wo = WorkOrder.create(intent=f"please run {skill}", skill=skill, project="bumba")
    selector = EnvironmentSelector()
    env, rationale = selector.select(wo)
    assert env is Environment.DEPARTMENT, (
        f"{skill!r} must route to DEPARTMENT, got {env.value!r} "
        f"(rationale: {rationale})"
    )
    assert "department" in rationale.lower()
