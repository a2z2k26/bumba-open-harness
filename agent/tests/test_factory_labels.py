"""Tests for bridge.factory.labels — Dark Factory label state machine.

Sprint 14.01 — Plan 14 Phase 1.

All `gh` subprocess calls are mocked. These tests must NEVER touch a live
GitHub repo — that would create labels and modify issue state.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from bridge.factory.labels import (
    FACTORY_LABELS,
    FACTORY_OPT_IN_LABEL,
    FactoryState,
    LabelStateError,
    ensure_labels_exist,
    get_state,
    transition_state,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _gh_view_payload(label_names: list[str]) -> tuple[int, str, str]:
    """Build a fake (rc, stdout, stderr) tuple for `gh issue view --json labels`."""
    body = json.dumps({"labels": [{"name": n} for n in label_names]})
    return (0, body, "")


def _gh_label_list_payload(existing_names: list[str]) -> tuple[int, str, str]:
    """Build a fake (rc, stdout, stderr) tuple for `gh label list --json name`."""
    body = json.dumps([{"name": n} for n in existing_names])
    return (0, body, "")


# ── Enum / constants invariants ─────────────────────────────────────────


def test_factory_labels_constant_covers_every_state_plus_opt_in():
    """FACTORY_LABELS must equal {opt-in} ∪ every FactoryState.value, no extras."""
    expected = {FACTORY_OPT_IN_LABEL, *(s.value for s in FactoryState)}
    assert set(FACTORY_LABELS) == expected
    # 12 = 1 marker + 11 states
    assert len(FACTORY_LABELS) == 12
    assert len(set(FACTORY_LABELS)) == len(FACTORY_LABELS), "FACTORY_LABELS has duplicates"


def test_factory_state_values_all_use_factory_prefix():
    """Invariant: every state label uses the `factory:` namespace."""
    for state in FactoryState:
        assert state.value.startswith("factory:"), state


# ── get_state ───────────────────────────────────────────────────────────


def test_get_state_returns_state_for_single_factory_label():
    with patch(
        "bridge.factory.labels._run_gh",
        return_value=_gh_view_payload(["factory:in-progress", "type:bug"]),
    ):
        result = get_state(42)
    assert result is FactoryState.IN_PROGRESS


def test_get_state_returns_none_for_no_factory_label():
    """Issues with only non-factory labels (or no labels) return None."""
    with patch(
        "bridge.factory.labels._run_gh",
        return_value=_gh_view_payload(["type:bug", "severity:high"]),
    ):
        assert get_state(42) is None


def test_get_state_treats_opt_in_alone_as_no_state():
    """`factory:opt-in` is a marker, not a state."""
    with patch(
        "bridge.factory.labels._run_gh",
        return_value=_gh_view_payload([FACTORY_OPT_IN_LABEL]),
    ):
        assert get_state(42) is None


def test_get_state_raises_when_multiple_factory_state_labels():
    """State-machine invariant: never two states. opt-in does not count."""
    with patch(
        "bridge.factory.labels._run_gh",
        return_value=_gh_view_payload(
            ["factory:in-progress", "factory:needs-review", FACTORY_OPT_IN_LABEL]
        ),
    ):
        with pytest.raises(LabelStateError) as exc:
            get_state(42)
    msg = str(exc.value)
    assert "factory:in-progress" in msg
    assert "factory:needs-review" in msg


def test_get_state_raises_runtime_error_on_gh_failure():
    with patch(
        "bridge.factory.labels._run_gh",
        return_value=(1, "", "could not resolve issue"),
    ):
        with pytest.raises(RuntimeError, match="gh issue view"):
            get_state(99)


# ── transition_state ────────────────────────────────────────────────────


def test_transition_state_succeeds_when_current_matches_from_state():
    """Happy path: optimistic check passes, edit succeeds."""
    calls: list[list[str]] = []

    def fake_run_gh(args: list[str]) -> tuple[int, str, str]:
        calls.append(list(args))
        if args[:2] == ["issue", "view"]:
            return _gh_view_payload(["factory:in-progress"])
        if args[:2] == ["issue", "edit"]:
            return (0, "", "")
        raise AssertionError(f"Unexpected gh call: {args}")

    with patch("bridge.factory.labels._run_gh", side_effect=fake_run_gh):
        ok = transition_state(42, FactoryState.IN_PROGRESS, FactoryState.NEEDS_REVIEW)

    assert ok is True
    # Verify the edit call carried both --add-label and --remove-label in one shot
    edit_call = next(c for c in calls if c[:2] == ["issue", "edit"])
    assert "--add-label" in edit_call
    assert "factory:needs-review" in edit_call
    assert "--remove-label" in edit_call
    assert "factory:in-progress" in edit_call


def test_transition_state_returns_false_when_current_does_not_match():
    """Optimistic concurrency: caller's `from_state` is stale, no change made."""
    calls: list[list[str]] = []

    def fake_run_gh(args: list[str]) -> tuple[int, str, str]:
        calls.append(list(args))
        if args[:2] == ["issue", "view"]:
            return _gh_view_payload(["factory:needs-review"])
        # If we ever hit edit, the test fails — that's the bug we're guarding against
        raise AssertionError(f"transition_state should not have called: {args}")

    with patch("bridge.factory.labels._run_gh", side_effect=fake_run_gh):
        ok = transition_state(42, FactoryState.IN_PROGRESS, FactoryState.NEEDS_REVIEW)

    assert ok is False
    # Only the view call should have happened
    assert len(calls) == 1
    assert calls[0][:2] == ["issue", "view"]


def test_transition_state_from_none_omits_remove_label():
    """First-ever transition (from_state=None) should not pass --remove-label."""
    calls: list[list[str]] = []

    def fake_run_gh(args: list[str]) -> tuple[int, str, str]:
        calls.append(list(args))
        if args[:2] == ["issue", "view"]:
            return _gh_view_payload([FACTORY_OPT_IN_LABEL])  # opt-in only, no state
        if args[:2] == ["issue", "edit"]:
            return (0, "", "")
        raise AssertionError(f"Unexpected gh call: {args}")

    with patch("bridge.factory.labels._run_gh", side_effect=fake_run_gh):
        ok = transition_state(42, None, FactoryState.UNTRIAGED)

    assert ok is True
    edit_call = next(c for c in calls if c[:2] == ["issue", "edit"])
    assert "--add-label" in edit_call
    assert "factory:untriaged" in edit_call
    assert "--remove-label" not in edit_call


def test_transition_state_raises_runtime_error_when_edit_fails():
    """If gh edit fails for non-concurrency reasons, surface the failure."""

    def fake_run_gh(args: list[str]) -> tuple[int, str, str]:
        if args[:2] == ["issue", "view"]:
            return _gh_view_payload(["factory:in-progress"])
        if args[:2] == ["issue", "edit"]:
            return (1, "", "API rate limit exceeded")
        raise AssertionError(f"Unexpected gh call: {args}")

    with patch("bridge.factory.labels._run_gh", side_effect=fake_run_gh):
        with pytest.raises(RuntimeError, match="API rate limit"):
            transition_state(42, FactoryState.IN_PROGRESS, FactoryState.NEEDS_REVIEW)


# ── ensure_labels_exist ─────────────────────────────────────────────────


def test_ensure_labels_exist_creates_all_when_repo_is_empty():
    create_calls: list[list[str]] = []

    def fake_run_gh(args: list[str]) -> tuple[int, str, str]:
        if args[:2] == ["label", "list"]:
            return _gh_label_list_payload([])
        if args[:2] == ["label", "create"]:
            create_calls.append(list(args))
            return (0, "", "")
        raise AssertionError(f"Unexpected gh call: {args}")

    with patch("bridge.factory.labels._run_gh", side_effect=fake_run_gh):
        created = ensure_labels_exist("your-org/test-repo")

    assert created == len(FACTORY_LABELS) == 12
    # Each create call must name a factory label
    created_names = {call[2] for call in create_calls}
    assert created_names == set(FACTORY_LABELS)
    # Each create must target the requested repo
    for call in create_calls:
        assert "--repo" in call
        assert call[call.index("--repo") + 1] == "your-org/test-repo"


def test_ensure_labels_exist_is_idempotent_on_second_call():
    """If every factory label already exists, ensure_labels_exist returns 0."""

    def fake_run_gh(args: list[str]) -> tuple[int, str, str]:
        if args[:2] == ["label", "list"]:
            return _gh_label_list_payload(list(FACTORY_LABELS))
        if args[:2] == ["label", "create"]:
            raise AssertionError(
                f"Idempotent call must not invoke `label create`; got {args}"
            )
        raise AssertionError(f"Unexpected gh call: {args}")

    with patch("bridge.factory.labels._run_gh", side_effect=fake_run_gh):
        created = ensure_labels_exist("your-org/test-repo")

    assert created == 0


def test_ensure_labels_exist_creates_only_the_missing_subset():
    """Partial-existence case: create only the gaps, leave the rest alone."""
    already_present = [FACTORY_OPT_IN_LABEL, "factory:untriaged", "factory:accepted"]
    create_calls: list[list[str]] = []

    def fake_run_gh(args: list[str]) -> tuple[int, str, str]:
        if args[:2] == ["label", "list"]:
            return _gh_label_list_payload(already_present)
        if args[:2] == ["label", "create"]:
            create_calls.append(list(args))
            return (0, "", "")
        raise AssertionError(f"Unexpected gh call: {args}")

    with patch("bridge.factory.labels._run_gh", side_effect=fake_run_gh):
        created = ensure_labels_exist("your-org/test-repo")

    expected_missing = set(FACTORY_LABELS) - set(already_present)
    assert created == len(expected_missing)
    assert {c[2] for c in create_calls} == expected_missing


def test_ensure_labels_exist_raises_if_label_list_fails():
    with patch(
        "bridge.factory.labels._run_gh",
        return_value=(1, "", "auth required"),
    ):
        with pytest.raises(RuntimeError, match="gh label list"):
            ensure_labels_exist("your-org/test-repo")
