"""Tests for Z4.4.3 — NamespaceGuard namespace enforcement."""

import pytest

from teams._namespace import NamespaceGuard, NamespaceViolationError, get_guard


@pytest.fixture(autouse=True)
def fresh_guard():
    """Provide a fresh NamespaceGuard for each test (isolated from singleton)."""
    guard = NamespaceGuard()
    yield guard
    # No cleanup needed — each test gets its own instance


# 1. register() succeeds for same department re-registration
def test_register_same_department_is_idempotent(fresh_guard):
    fresh_guard.register("qa", ["run_lint", "run_tests"])
    # Re-registering the same tools under the same department must not raise.
    fresh_guard.register("qa", ["run_lint"])
    assert "run_lint" in fresh_guard.list_tools("qa")


# 2. register() allows the same tool under multiple departments
def test_register_cross_department_allowed(fresh_guard):
    fresh_guard.register("qa", ["run_tests"])
    fresh_guard.register("engineering", ["run_tests"])
    assert fresh_guard.validate("qa", "run_tests") is True
    assert fresh_guard.validate("engineering", "run_tests") is True


# 3. validate() returns False for unregistered tool
def test_validate_returns_false_for_unregistered(fresh_guard):
    result = fresh_guard.validate("qa", "unknown_tool")
    assert result is False


# 4. validate() returns True for correctly registered tool
def test_validate_returns_true_for_correct_department(fresh_guard):
    fresh_guard.register("qa", ["run_lint"])
    result = fresh_guard.validate("qa", "run_lint")
    assert result is True


# 5. validate() raises NamespaceViolationError for wrong department
def test_validate_raises_for_wrong_department(fresh_guard):
    fresh_guard.register("qa", ["run_lint"])
    with pytest.raises(NamespaceViolationError) as exc_info:
        fresh_guard.validate("engineering", "run_lint")
    assert "run_lint" in str(exc_info.value)
    assert "qa" in str(exc_info.value)
    assert "engineering" in str(exc_info.value)


# 6. list_tools() returns correct names for a department
def test_list_tools_returns_department_tools(fresh_guard):
    fresh_guard.register("qa", ["run_lint", "run_tests"])
    fresh_guard.register("engineering", ["build", "deploy"])
    qa_tools = fresh_guard.list_tools("qa")
    assert sorted(qa_tools) == ["run_lint", "run_tests"]
    eng_tools = fresh_guard.list_tools("engineering")
    assert sorted(eng_tools) == ["build", "deploy"]


# 7. clear() resets state
def test_clear_resets_registry(fresh_guard):
    fresh_guard.register("qa", ["run_lint"])
    fresh_guard.clear()
    # After clearing, the same tool name can be registered under a different dept.
    fresh_guard.register("engineering", ["run_lint"])
    assert fresh_guard.validate("engineering", "run_lint") is True


# 8. get_guard() returns module-level singleton
def test_get_guard_returns_singleton():
    guard_a = get_guard()
    guard_b = get_guard()
    assert guard_a is guard_b
