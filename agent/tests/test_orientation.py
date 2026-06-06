"""Tests for the structured orientation document (E3.1 + E3.3)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from bridge.orientation import (
    DEFAULT_ORIENTATION_PATH,
    ORIENTATION_SCHEMA_VERSION,
    Orientation,
    Priority,
    WinCriterion,
    is_redirect_message,
    is_confirm_message,
    update_on_step_completed,
    update_on_decision_logged,
    update_on_operator_redirect,
    promote_pending_focus_if_confirmed,
)


# ---------------------------------------------------------------------------
# Frozen dataclass behaviour
# ---------------------------------------------------------------------------

class TestOrientationFrozen:
    def test_priority_is_frozen(self):
        p = Priority(rank=1, title="t", rationale="r")
        with pytest.raises((AttributeError, TypeError)):
            p.rank = 2  # type: ignore[misc]

    def test_win_criterion_is_frozen(self):
        w = WinCriterion(label="l", description="d")
        with pytest.raises((AttributeError, TypeError)):
            w.label = "x"  # type: ignore[misc]

    def test_orientation_is_frozen(self):
        o = Orientation.empty()
        with pytest.raises((AttributeError, TypeError)):
            o.current_focus = "changed"  # type: ignore[misc]

    def test_priorities_stored_as_tuple(self):
        o = Orientation(
            priorities=[Priority(rank=1, title="t", rationale="r")],
        )
        assert isinstance(o.priorities, tuple)

    def test_win_criteria_stored_as_tuple(self):
        o = Orientation(
            win_criteria=[WinCriterion(label="l", description="d")],
        )
        assert isinstance(o.win_criteria, tuple)


# ---------------------------------------------------------------------------
# Defaults / empty
# ---------------------------------------------------------------------------

class TestEmpty:
    def test_empty_returns_current_schema_version(self):
        o = Orientation.empty()
        assert o.schema_version == ORIENTATION_SCHEMA_VERSION

    def test_empty_has_no_priorities(self):
        assert Orientation.empty().priorities == ()

    def test_empty_has_no_win_criteria(self):
        assert Orientation.empty().win_criteria == ()

    def test_default_path_constant(self):
        # Sanity check — DEFAULT_ORIENTATION_PATH points at the canonical
        # state location relative to the repo root.
        assert DEFAULT_ORIENTATION_PATH == Path("agent/state/orientation.json")


# ---------------------------------------------------------------------------
# Mutator immutability
# ---------------------------------------------------------------------------

class TestMutators:
    def test_with_focus_returns_new_instance(self):
        o = Orientation.empty()
        new = o.with_focus("ship 1.0")
        assert o.current_focus == ""
        assert new.current_focus == "ship 1.0"
        assert o is not new

    def test_with_focus_updates_timestamp(self):
        o = Orientation.empty()
        new = o.with_focus("ship 1.0")
        assert new.updated_at != ""
        assert new.updated_at != o.updated_at

    def test_with_priorities_returns_new_instance(self):
        o = Orientation.empty()
        ps = (Priority(rank=1, title="t", rationale="r"),)
        new = o.with_priorities(ps)
        assert o.priorities == ()
        assert new.priorities == ps

    def test_with_priorities_accepts_list(self):
        o = Orientation.empty()
        new = o.with_priorities([Priority(rank=1, title="t", rationale="r")])
        assert isinstance(new.priorities, tuple)
        assert len(new.priorities) == 1

    def test_with_win_criteria_returns_new_instance(self):
        o = Orientation.empty()
        ws = (WinCriterion(label="l", description="d"),)
        new = o.with_win_criteria(ws)
        assert o.win_criteria == ()
        assert new.win_criteria == ws


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_to_dict_from_dict_round_trip(self):
        o = Orientation(
            schema_version=ORIENTATION_SCHEMA_VERSION,
            current_focus="ship 1.0",
            priorities=(
                Priority(rank=1, title="t1", rationale="r1", plan_ref="ref1"),
                Priority(rank=2, title="t2", rationale="r2", plan_ref=None),
            ),
            win_criteria=(WinCriterion(label="l1", description="d1"),),
            updated_at="2026-05-04T00:00:00+00:00",
        )
        restored = Orientation.from_dict(o.to_dict())
        assert restored == o

    def test_write_load_round_trip(self, tmp_path: Path):
        target = tmp_path / "orientation.json"
        o = Orientation(
            current_focus="ship 1.0",
            priorities=(Priority(rank=1, title="t", rationale="r"),),
            win_criteria=(WinCriterion(label="l", description="d"),),
            updated_at="2026-05-04T00:00:00+00:00",
        )
        o.write(target)
        restored = Orientation.load(target)
        assert restored == o

    def test_write_creates_parent_directory(self, tmp_path: Path):
        target = tmp_path / "nested" / "dir" / "orientation.json"
        Orientation.empty().write(target)
        assert target.exists()

    def test_write_is_atomic_no_tmp_file_left(self, tmp_path: Path):
        target = tmp_path / "orientation.json"
        Orientation.empty().write(target)
        # Only the final file should remain — no .tmp leftovers.
        leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []


# ---------------------------------------------------------------------------
# Failure-mode loading
# ---------------------------------------------------------------------------

class TestLoadFailureModes:
    def test_load_missing_file_returns_empty(self, tmp_path: Path):
        o = Orientation.load(tmp_path / "does-not-exist.json")
        assert o == Orientation.empty()

    def test_load_corrupt_json_returns_empty_and_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        bad = tmp_path / "orientation.json"
        bad.write_text("{not valid json")
        with caplog.at_level(logging.WARNING, logger="bridge.orientation"):
            o = Orientation.load(bad)
        assert o == Orientation.empty()
        assert any("Failed to read orientation" in rec.message for rec in caplog.records)

    def test_load_schema_mismatch_logs_warning_but_loads(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        future = tmp_path / "orientation.json"
        future.write_text(
            json.dumps(
                {
                    "schema_version": 99,
                    "current_focus": "future",
                    "priorities": [],
                    "win_criteria": [],
                    "updated_at": "2030-01-01T00:00:00+00:00",
                }
            )
        )
        with caplog.at_level(logging.WARNING, logger="bridge.orientation"):
            o = Orientation.load(future)
        # Best-effort: focus loads even though schema is unknown.
        assert o.current_focus == "future"
        assert any("schema version mismatch" in rec.message for rec in caplog.records)

    def test_from_dict_drops_malformed_priority(
        self, caplog: pytest.LogCaptureFixture
    ):
        data = {
            "schema_version": ORIENTATION_SCHEMA_VERSION,
            "current_focus": "x",
            "priorities": [
                {"rank": 1, "title": "good", "rationale": "r"},
                {"rank": "not-an-int", "title": "bad", "rationale": "r"},
            ],
            "win_criteria": [],
            "updated_at": "",
        }
        with caplog.at_level(logging.WARNING, logger="bridge.orientation"):
            o = Orientation.from_dict(data)
        assert len(o.priorities) == 1
        assert o.priorities[0].title == "good"
        assert any("Dropping malformed priority" in rec.message for rec in caplog.records)

    def test_from_dict_drops_malformed_win_criterion(
        self, caplog: pytest.LogCaptureFixture
    ):
        data = {
            "schema_version": ORIENTATION_SCHEMA_VERSION,
            "current_focus": "x",
            "priorities": [],
            "win_criteria": [
                {"label": "good", "description": "d"},
                {"description": "missing-label"},
            ],
            "updated_at": "",
        }
        with caplog.at_level(logging.WARNING, logger="bridge.orientation"):
            o = Orientation.from_dict(data)
        assert len(o.win_criteria) == 1
        assert o.win_criteria[0].label == "good"
        assert any("Dropping malformed win_criterion" in rec.message for rec in caplog.records)

    def test_load_tolerates_unknown_top_level_keys(self, tmp_path: Path):
        # Unknown fields (e.g. operator-added anti_patterns / active_plan_refs)
        # are silently ignored rather than causing the load to fail.
        target = tmp_path / "orientation.json"
        target.write_text(
            json.dumps(
                {
                    "schema_version": ORIENTATION_SCHEMA_VERSION,
                    "current_focus": "x",
                    "priorities": [],
                    "win_criteria": [],
                    "updated_at": "2026-05-04T00:00:00+00:00",
                    "anti_patterns": ["foo"],
                    "active_plan_refs": ["bar"],
                }
            )
        )
        o = Orientation.load(target)
        assert o.current_focus == "x"


# ---------------------------------------------------------------------------
# Seed file sanity
# ---------------------------------------------------------------------------

class TestSeedFile:
    """The committed seed at agent/state/orientation.json must always load.

    Pinned check so a later hand-edit can't ship a malformed seed.
    """

    def test_committed_seed_loads_cleanly(self):
        # Locate the seed relative to this test file so it works regardless
        # of pytest's cwd.
        seed = Path(__file__).resolve().parent.parent / "state" / "orientation.json"
        if not seed.exists():
            pytest.skip(f"Seed file not present at {seed}")
        o = Orientation.load(seed)
        assert o.schema_version == ORIENTATION_SCHEMA_VERSION
        assert o.current_focus != ""
        assert len(o.priorities) >= 1
        assert len(o.win_criteria) >= 1


# ---------------------------------------------------------------------------
# E3.3 — pending_focus_change field + promote helpers
# ---------------------------------------------------------------------------

class TestPendingFocus:
    def test_with_pending_focus_stores_value(self):
        o = Orientation.empty()
        o2 = o.with_pending_focus("new direction")
        assert o2.pending_focus_change == "new direction"
        assert o.pending_focus_change is None  # original unchanged

    def test_with_pending_focus_none_clears(self):
        o = Orientation.empty().with_pending_focus("something")
        o2 = o.with_pending_focus(None)
        assert o2.pending_focus_change is None

    def test_promote_pending_focus_promotes_and_clears(self):
        o = Orientation(current_focus="old", pending_focus_change="new direction")
        o2 = o.promote_pending_focus()
        assert o2.current_focus == "new direction"
        assert o2.pending_focus_change is None

    def test_promote_pending_focus_with_none_is_noop(self):
        o = Orientation(current_focus="stays", pending_focus_change=None)
        o2 = o.promote_pending_focus()
        assert o2.current_focus == "stays"
        assert o2 is o  # same object returned

    def test_pending_focus_round_trips_json(self, tmp_path):
        path = tmp_path / "o.json"
        o = Orientation(current_focus="x", pending_focus_change="staged")
        o.write(path)
        o2 = Orientation.load(path)
        assert o2.pending_focus_change == "staged"

    def test_missing_pending_focus_loads_as_none(self, tmp_path):
        path = tmp_path / "o.json"
        # Write JSON without the pending_focus_change key
        data = Orientation.empty().to_dict()
        data.pop("pending_focus_change", None)
        path.write_text(json.dumps(data))
        o = Orientation.load(path)
        assert o.pending_focus_change is None


# ---------------------------------------------------------------------------
# E3.3 — Redirect + confirm classifiers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("content", [
    "redirect: focus on shipping",
    "Redirect: something",
    "focus: new area",
    "FOCUS: all caps",
    "instead: do this",
    "new focus: pivoting",
    "new focus:no space after colon",
])
def test_is_redirect_message_matches_prefixes(content):
    assert is_redirect_message(content) is True


@pytest.mark.parametrize("content", [
    "yes",
    "Looks good, redirect later",
    "just a message",
    "",
    "focusnot",
])
def test_is_redirect_message_negative_cases(content):
    assert is_redirect_message(content) is False


@pytest.mark.parametrize("content", [
    "yes",
    "YES",
    "confirm",
    "Confirm.",
    "go",
    "go!",
])
def test_is_confirm_message_matches(content):
    assert is_confirm_message(content) is True


@pytest.mark.parametrize("content", [
    "yes please continue working on X",
    "not yet",
    "redirect: new focus",
    "",
])
def test_is_confirm_message_negative_cases(content):
    assert is_confirm_message(content) is False


# ---------------------------------------------------------------------------
# E3.3 — Trigger functions
# ---------------------------------------------------------------------------

class TestUpdateOnStepCompleted:
    def test_appends_to_matching_priority_rationale(self, tmp_path):
        path = tmp_path / "o.json"
        o = Orientation(
            current_focus="x",
            priorities=(Priority(rank=1, title="Ship E3", rationale="original", plan_ref="plan-abc"),),
        )
        o.write(path)
        update_on_step_completed("step-1", "plan-abc", path)
        loaded = Orientation.load(path)
        assert "(last completed: step-1)" in loaded.priorities[0].rationale

    def test_no_match_is_noop(self, tmp_path):
        path = tmp_path / "o.json"
        o = Orientation(
            current_focus="x",
            priorities=(Priority(rank=1, title="Ship E3", rationale="original", plan_ref="plan-abc"),),
        )
        o.write(path)
        update_on_step_completed("step-1", "plan-other", path)
        loaded = Orientation.load(path)
        assert loaded.priorities[0].rationale == "original"

    def test_missing_file_is_silent(self, tmp_path):
        target = tmp_path / "nonexistent.json"
        assert not target.exists()
        # Should not raise even when the target file is missing.
        update_on_step_completed("step-1", "plan-x", target)
        # Contract: Orientation.load() returns empty() for a missing
        # file and the subsequent write produces a default-shaped
        # orientation. The helper completes silently — what we verify
        # is the loaded result matches the empty schema (no priorities
        # to update against plan-x).
        loaded = Orientation.load(target)
        assert loaded.priorities == ()


class TestUpdateOnDecisionLogged:
    def test_appends_to_focus(self, tmp_path):
        path = tmp_path / "o.json"
        Orientation(current_focus="Ship 1.0").write(path)
        update_on_decision_logged("Use Infisical for secrets", path)
        loaded = Orientation.load(path)
        assert "recent decision: Use Infisical" in loaded.current_focus

    def test_truncates_long_summary(self, tmp_path):
        path = tmp_path / "o.json"
        Orientation(current_focus="focus").write(path)
        long_summary = "x" * 200
        update_on_decision_logged(long_summary, path)
        loaded = Orientation.load(path)
        # Max 120 chars of the decision summary
        assert len(loaded.current_focus) <= len("focus") + len(" | recent decision: ") + 120


class TestUpdateOnOperatorRedirect:
    def test_stages_pending_change(self, tmp_path):
        path = tmp_path / "o.json"
        Orientation(current_focus="original").write(path)
        update_on_operator_redirect("redirect: focus on E4 templates", path)
        loaded = Orientation.load(path)
        assert loaded.pending_focus_change == "focus on E4 templates"
        assert loaded.current_focus == "original"  # not overwritten

    def test_strips_various_prefixes(self, tmp_path):
        for prefix in ["focus:", "instead:", "new focus:"]:
            path = tmp_path / f"o_{prefix[:3]}.json"
            Orientation(current_focus="x").write(path)
            update_on_operator_redirect(f"{prefix} new direction", path)
            loaded = Orientation.load(path)
            assert loaded.pending_focus_change == "new direction"

    def test_empty_body_after_prefix_is_noop(self, tmp_path):
        path = tmp_path / "o.json"
        Orientation(current_focus="x").write(path)
        update_on_operator_redirect("redirect:", path)
        loaded = Orientation.load(path)
        assert loaded.pending_focus_change is None


class TestPromotePendingFocusIfConfirmed:
    def test_promotes_on_confirm(self, tmp_path):
        path = tmp_path / "o.json"
        Orientation(current_focus="old", pending_focus_change="new").write(path)
        result = promote_pending_focus_if_confirmed("yes", path)
        assert result is True
        loaded = Orientation.load(path)
        assert loaded.current_focus == "new"
        assert loaded.pending_focus_change is None

    def test_no_pending_confirm_is_noop(self, tmp_path):
        path = tmp_path / "o.json"
        Orientation(current_focus="stays").write(path)
        result = promote_pending_focus_if_confirmed("yes", path)
        assert result is False
        assert Orientation.load(path).current_focus == "stays"

    def test_non_confirm_is_noop(self, tmp_path):
        path = tmp_path / "o.json"
        Orientation(current_focus="x", pending_focus_change="staged").write(path)
        result = promote_pending_focus_if_confirmed("just chatting", path)
        assert result is False
        assert Orientation.load(path).pending_focus_change == "staged"
