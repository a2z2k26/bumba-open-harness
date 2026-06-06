"""Tests for Sprint 04.04 — per-feature daily budget cap in cost_tracker.

Covers:
- ``CostEntry.feature`` field round-trips through JSONL
- Backward compatibility for legacy JSONL without the ``feature`` key
- ``CostTracker.check_feature_cap`` enforcement and bypass behavior
- ``CostTracker.register_feature_cap`` runtime cap registration
- ``CostTracker.get_feature_summary`` aggregation
- Default Board cap auto-registration via ``board_v2_enabled``

File-conflict awareness: this sprint adds the ``feature`` field. Sprint 02.09
will later add ``experiment_iter`` alongside; the dataclass-tolerant reader
in ``_read_entries`` already drops unknown keys so both can coexist without
JSONL-format breakage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.cost_tracker import (
    DEFAULT_BOARD_DAILY_CAP_USD,
    EXPERIMENT_ITER_ENV,
    CostEntry,
    CostTracker,
    ExperimentCostSummary,
    FeatureCostSummary,
    estimate_cost,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def tracker(tmp_path: Path) -> CostTracker:
    """CostTracker with feature caps enabled for cap-related tests."""
    return CostTracker(data_dir=tmp_path, feature_caps_enabled=True)


@pytest.fixture()
def tracker_bypass(tmp_path: Path) -> CostTracker:
    """CostTracker with feature caps DISABLED — exercises bypass mode."""
    return CostTracker(data_dir=tmp_path, feature_caps_enabled=False)


# ------------------------------------------------------------------
# CostEntry.feature field
# ------------------------------------------------------------------


class TestCostEntryFeatureField:
    def test_default_is_empty_string(self) -> None:
        entry = CostEntry(
            timestamp="2026-04-29T12:00:00+00:00",
            model="sonnet",
            input_tokens=10,
            output_tokens=5,
            estimated_cost=0.0,
            task_type="",
            was_override=False,
        )
        assert entry.feature == ""

    def test_round_trip_through_jsonl(self, tracker: CostTracker) -> None:
        tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            feature="board",
        )
        raw = tracker.path.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        assert data["feature"] == "board"

        # Re-read via _read_entries to confirm structured round-trip too.
        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].feature == "board"


# ------------------------------------------------------------------
# Backward compatibility — legacy JSONL without `feature`
# ------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_legacy_jsonl_without_feature_parses(self, tracker: CostTracker) -> None:
        legacy_line = json.dumps({
            "timestamp": "2026-03-01T00:00:00+00:00",
            "model": "sonnet",
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost": 0.001,
            "task_type": "chat",
            "was_override": False,
            "agent_id": "",
            "session_id": "",
        })
        tracker.path.write_text(legacy_line + "\n", encoding="utf-8")

        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].feature == ""
        assert entries[0].agent_id == ""

    def test_forward_compat_unknown_keys_dropped(self, tracker: CostTracker) -> None:
        """A JSONL line written by a future schema (e.g. 02.09 experiment_iter)
        must parse cleanly — the reader drops unknown keys."""
        future_line = json.dumps({
            "timestamp": "2026-05-01T00:00:00+00:00",
            "model": "haiku",
            "input_tokens": 10,
            "output_tokens": 5,
            "estimated_cost": 0.0001,
            "task_type": "",
            "was_override": False,
            "agent_id": "",
            "session_id": "",
            "feature": "board",
            "experiment_iter": "iter-7",  # not yet defined on CostEntry
        })
        tracker.path.write_text(future_line + "\n", encoding="utf-8")

        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].feature == "board"


# ------------------------------------------------------------------
# check_feature_cap
# ------------------------------------------------------------------


class TestCheckFeatureCap:
    def test_within_cap_returns_allowed(self, tracker: CostTracker) -> None:
        tracker.register_feature_cap("board", 1.00)
        # Spend $0.10 so far today.
        tracker._atomic_append(
            CostEntry(
                timestamp=_today_iso(),
                model="sonnet",
                input_tokens=0,
                output_tokens=0,
                estimated_cost=0.10,
                task_type="",
                was_override=False,
                feature="board",
            )
        )
        allowed, reason = tracker.check_feature_cap("board", cost_usd=0.50)
        assert allowed is True
        assert reason == ""

    def test_exceeds_cap_returns_blocked(self, tracker: CostTracker) -> None:
        tracker.register_feature_cap("board", 1.00)
        tracker._atomic_append(
            CostEntry(
                timestamp=_today_iso(),
                model="sonnet",
                input_tokens=0,
                output_tokens=0,
                estimated_cost=0.80,
                task_type="",
                was_override=False,
                feature="board",
            )
        )
        # 0.80 already spent + 0.50 projected = 1.30 > 1.00 cap.
        allowed, reason = tracker.check_feature_cap("board", cost_usd=0.50)
        assert allowed is False
        assert reason == "feature_cap_exceeded:board:1.00"

    def test_no_cap_registered_returns_allowed(self, tracker: CostTracker) -> None:
        allowed, reason = tracker.check_feature_cap("unknown_feature", cost_usd=999.0)
        assert allowed is True
        assert reason == ""

    def test_empty_feature_label_returns_allowed(self, tracker: CostTracker) -> None:
        # Even with caps enabled, an empty feature has no cap to check.
        tracker.register_feature_cap("board", 0.001)
        allowed, reason = tracker.check_feature_cap("", cost_usd=999.0)
        assert allowed is True
        assert reason == ""

    def test_feature_flag_off_always_allows(self, tracker_bypass: CostTracker) -> None:
        # Even when a cap is registered, bypass mode never blocks.
        tracker_bypass.register_feature_cap("board", 0.001)
        tracker_bypass._atomic_append(
            CostEntry(
                timestamp=_today_iso(),
                model="sonnet",
                input_tokens=0,
                output_tokens=0,
                estimated_cost=999.0,
                task_type="",
                was_override=False,
                feature="board",
            )
        )
        allowed, reason = tracker_bypass.check_feature_cap("board", cost_usd=999.0)
        assert allowed is True
        assert reason == ""


# ------------------------------------------------------------------
# register_feature_cap
# ------------------------------------------------------------------


class TestRegisterFeatureCap:
    def test_register_then_check_honors_new_cap(self, tracker: CostTracker) -> None:
        tracker.register_feature_cap("board", 0.50)
        tracker._atomic_append(
            CostEntry(
                timestamp=_today_iso(),
                model="sonnet",
                input_tokens=0,
                output_tokens=0,
                estimated_cost=0.40,
                task_type="",
                was_override=False,
                feature="board",
            )
        )
        # 0.40 + 0.20 = 0.60 > 0.50 cap.
        allowed, reason = tracker.check_feature_cap("board", cost_usd=0.20)
        assert allowed is False
        assert "0.50" in reason

        # Operator raises the cap at runtime.
        tracker.register_feature_cap("board", 5.00)
        allowed, reason = tracker.check_feature_cap("board", cost_usd=0.20)
        assert allowed is True
        assert reason == ""

    def test_get_feature_cap(self, tracker: CostTracker) -> None:
        assert tracker.get_feature_cap("board") is None
        tracker.register_feature_cap("board", 1.50)
        assert tracker.get_feature_cap("board") == 1.50

    def test_invalid_feature_label_rejected(self, tracker: CostTracker) -> None:
        with pytest.raises(ValueError):
            tracker.register_feature_cap("", 1.0)

    def test_negative_cap_rejected(self, tracker: CostTracker) -> None:
        with pytest.raises(ValueError):
            tracker.register_feature_cap("board", -0.01)


# ------------------------------------------------------------------
# get_feature_summary
# ------------------------------------------------------------------


class TestGetFeatureSummary:
    def test_aggregates_only_requested_feature(self, tracker: CostTracker) -> None:
        # Two board entries today, one experiment entry today, one no-feature.
        ts = _today_iso()
        for cost, feat in [(0.10, "board"), (0.20, "board"), (5.00, "experiment"), (1.00, "")]:
            tracker._atomic_append(
                CostEntry(
                    timestamp=ts,
                    model="sonnet",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=cost,
                    task_type="",
                    was_override=False,
                    feature=feat,
                )
            )

        summary = tracker.get_feature_summary("board", period="1d")
        assert isinstance(summary, FeatureCostSummary)
        assert summary.feature == "board"
        assert summary.request_count == 2
        assert summary.total_cost == pytest.approx(0.30, abs=1e-6)
        assert "sonnet" in summary.by_model
        assert summary.by_model["sonnet"]["count"] == 2

    def test_empty_when_no_entries(self, tracker: CostTracker) -> None:
        summary = tracker.get_feature_summary("board")
        assert summary.request_count == 0
        assert summary.total_cost == 0.0
        assert summary.by_model == {}

    def test_seven_day_window(self, tracker: CostTracker) -> None:
        # One entry today, one 100 days ago. Only today should land in 7d.
        from datetime import datetime, timedelta, timezone

        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        for ts, cost in [(_today_iso(), 0.10), (old_ts, 9.99)]:
            tracker._atomic_append(
                CostEntry(
                    timestamp=ts,
                    model="sonnet",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=cost,
                    task_type="",
                    was_override=False,
                    feature="board",
                )
            )
        summary = tracker.get_feature_summary("board", period="7d")
        assert summary.period == "7d"
        assert summary.request_count == 1
        assert summary.total_cost == pytest.approx(0.10, abs=1e-6)

    def test_unsupported_period_raises(self, tracker: CostTracker) -> None:
        with pytest.raises(ValueError):
            tracker.get_feature_summary("board", period="30d")


# ------------------------------------------------------------------
# Default Board cap auto-registration
# ------------------------------------------------------------------


class TestDefaultBoardCap:
    def test_board_v2_enabled_registers_default_cap(self, tmp_path: Path) -> None:
        t = CostTracker(
            data_dir=tmp_path,
            feature_caps_enabled=True,
            board_v2_enabled=True,
        )
        assert t.get_feature_cap("board") == DEFAULT_BOARD_DAILY_CAP_USD

    def test_board_v2_disabled_does_not_register(self, tmp_path: Path) -> None:
        t = CostTracker(data_dir=tmp_path, feature_caps_enabled=True, board_v2_enabled=False)
        assert t.get_feature_cap("board") is None


# ------------------------------------------------------------------
# Integration: record() persists feature, summary aggregates correctly
# ------------------------------------------------------------------


class TestRecordWithFeature:
    def test_record_persists_feature(self, tracker: CostTracker) -> None:
        entry = tracker.record(
            model="sonnet",
            input_tokens=1000,
            output_tokens=500,
            feature="board",
        )
        assert entry.feature == "board"
        # estimated_cost is positive — sanity check pricing wasn't broken.
        assert entry.estimated_cost == pytest.approx(estimate_cost("sonnet", 1000, 500))

        summary = tracker.get_feature_summary("board")
        assert summary.request_count == 1
        assert summary.total_cost == pytest.approx(entry.estimated_cost, abs=1e-9)

    def test_record_without_feature_has_empty_label(self, tracker: CostTracker) -> None:
        entry = tracker.record(model="haiku", input_tokens=10, output_tokens=5)
        assert entry.feature == ""


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _today_iso() -> str:
    """ISO-8601 UTC timestamp anchored to the current UTC calendar day.

    Used to seed entries that should fall inside ``get_feature_summary``'s
    1d window without depending on ``record()`` (which writes its own
    timestamp).
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# Sprint 02.09 — experiment_iter attribution
# ------------------------------------------------------------------


class TestExperimentAttribution:
    """Round-trip + aggregation for ``CostEntry.experiment_iter`` (Sprint 02.09)."""

    def test_experiment_iter_default_is_empty_string(self) -> None:
        entry = CostEntry(
            timestamp="2026-04-29T12:00:00+00:00",
            model="sonnet",
            input_tokens=10,
            output_tokens=5,
            estimated_cost=0.0,
            task_type="",
            was_override=False,
        )
        assert entry.experiment_iter == ""

    def test_round_trip_through_jsonl(self, tracker: CostTracker) -> None:
        tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            experiment_iter="iter-0042",
        )
        raw = tracker.path.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        assert data["experiment_iter"] == "iter-0042"

        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].experiment_iter == "iter-0042"

    def test_legacy_jsonl_without_experiment_iter_parses(
        self, tracker: CostTracker
    ) -> None:
        """Existing JSONL lines (pre-02.09) must parse with empty iter."""
        legacy_line = json.dumps(
            {
                "timestamp": "2026-03-01T00:00:00+00:00",
                "model": "sonnet",
                "input_tokens": 100,
                "output_tokens": 50,
                "estimated_cost": 0.001,
                "task_type": "chat",
                "was_override": False,
                "agent_id": "",
                "feature": "",
                "session_id": "",
                # no experiment_iter
            }
        )
        tracker.path.write_text(legacy_line + "\n", encoding="utf-8")

        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].experiment_iter == ""

    def test_get_experiment_summary_aggregates_only_requested_iter(
        self, tracker: CostTracker
    ) -> None:
        ts = _today_iso()
        # Two iter-0001 entries, one iter-0002, one non-experiment.
        for cost, iter_id in [
            (0.10, "iter-0001"),
            (0.20, "iter-0001"),
            (5.00, "iter-0002"),
            (1.00, ""),
        ]:
            tracker._atomic_append(
                CostEntry(
                    timestamp=ts,
                    model="sonnet",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=cost,
                    task_type="",
                    was_override=False,
                    experiment_iter=iter_id,
                )
            )

        summary = tracker.get_experiment_summary("iter-0001")
        assert isinstance(summary, ExperimentCostSummary)
        assert summary.iter_id == "iter-0001"
        assert summary.call_count == 2
        assert summary.total_usd == pytest.approx(0.30, abs=1e-6)
        assert "sonnet" in summary.model_breakdown
        assert summary.model_breakdown["sonnet"]["count"] == 2

    def test_empty_iter_id_returns_zero_spend_summary(
        self, tracker: CostTracker
    ) -> None:
        # Even if there are non-experiment entries, "" must not match them.
        tracker._atomic_append(
            CostEntry(
                timestamp=_today_iso(),
                model="sonnet",
                input_tokens=0,
                output_tokens=0,
                estimated_cost=1.00,
                task_type="",
                was_override=False,
                experiment_iter="",
            )
        )
        summary = tracker.get_experiment_summary("")
        assert summary.iter_id == ""
        assert summary.call_count == 0
        assert summary.total_usd == 0.0
        assert summary.model_breakdown == {}
        assert summary.started_at == ""
        assert summary.ended_at == ""

    def test_unknown_iter_returns_zero_spend_summary(
        self, tracker: CostTracker
    ) -> None:
        summary = tracker.get_experiment_summary("iter-does-not-exist")
        assert summary.call_count == 0
        assert summary.total_usd == 0.0
        assert summary.started_at == ""
        assert summary.ended_at == ""

    def test_summary_window_timestamps(self, tracker: CostTracker) -> None:
        from datetime import datetime, timedelta, timezone

        base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        first = base.isoformat()
        last = (base + timedelta(minutes=30)).isoformat()
        for ts in [first, last]:
            tracker._atomic_append(
                CostEntry(
                    timestamp=ts,
                    model="sonnet",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=0.05,
                    task_type="",
                    was_override=False,
                    experiment_iter="iter-window",
                )
            )
        summary = tracker.get_experiment_summary("iter-window")
        assert summary.started_at == first
        assert summary.ended_at == last

    def test_per_iter_sum_matches_total(self, tracker: CostTracker) -> None:
        """Regression guard — sum of per-iter costs == total experiment cost."""
        ts = _today_iso()
        seeded = [
            ("iter-A", 0.10),
            ("iter-A", 0.20),
            ("iter-B", 0.50),
            ("iter-C", 1.25),
            # Non-experiment entries must NOT inflate the total.
            ("", 9.99),
        ]
        for iter_id, cost in seeded:
            tracker._atomic_append(
                CostEntry(
                    timestamp=ts,
                    model="sonnet",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=cost,
                    task_type="",
                    was_override=False,
                    experiment_iter=iter_id,
                )
            )

        iter_ids = tracker.list_experiment_iters()
        assert set(iter_ids) == {"iter-A", "iter-B", "iter-C"}
        per_iter_total = sum(
            tracker.get_experiment_summary(i).total_usd for i in iter_ids
        )
        expected = 0.10 + 0.20 + 0.50 + 1.25
        assert per_iter_total == pytest.approx(expected, abs=1e-6)

    def test_record_picks_up_env_var_when_kwarg_missing(
        self, tracker: CostTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(EXPERIMENT_ITER_ENV, "iter-from-env")
        tracker.record(model="haiku", input_tokens=10, output_tokens=5)
        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].experiment_iter == "iter-from-env"

    def test_explicit_kwarg_wins_over_env_var(
        self, tracker: CostTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(EXPERIMENT_ITER_ENV, "iter-from-env")
        tracker.record(
            model="haiku",
            input_tokens=10,
            output_tokens=5,
            experiment_iter="iter-explicit",
        )
        entries = tracker._read_entries()
        assert entries[0].experiment_iter == "iter-explicit"

    def test_record_without_iter_env_or_kwarg_is_empty(
        self, tracker: CostTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(EXPERIMENT_ITER_ENV, raising=False)
        tracker.record(model="haiku", input_tokens=10, output_tokens=5)
        entries = tracker._read_entries()
        assert entries[0].experiment_iter == ""

    def test_feature_and_experiment_iter_coexist(
        self, tracker: CostTracker
    ) -> None:
        """One entry can carry both attribution tags independently."""
        tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            feature="board",
            experiment_iter="iter-mix",
        )
        entries = tracker._read_entries()
        assert entries[0].feature == "board"
        assert entries[0].experiment_iter == "iter-mix"

        # And both summaries surface the same entry.
        feat = tracker.get_feature_summary("board")
        assert feat.request_count == 1
        exp = tracker.get_experiment_summary("iter-mix")
        assert exp.call_count == 1
        assert exp.total_usd == pytest.approx(feat.total_cost, abs=1e-9)


class TestListExperimentIters:
    def test_returns_distinct_chronological(self, tracker: CostTracker) -> None:
        from datetime import datetime, timedelta, timezone

        base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        seeded = [
            ((base + timedelta(seconds=10)).isoformat(), "iter-B"),
            ((base + timedelta(seconds=20)).isoformat(), "iter-A"),
            ((base + timedelta(seconds=30)).isoformat(), "iter-A"),  # dup
            ((base + timedelta(seconds=5)).isoformat(), "iter-A"),  # earliest A
            ((base + timedelta(seconds=40)).isoformat(), ""),  # ignored
        ]
        for ts, iid in seeded:
            tracker._atomic_append(
                CostEntry(
                    timestamp=ts,
                    model="sonnet",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=0.01,
                    task_type="",
                    was_override=False,
                    experiment_iter=iid,
                )
            )
        # iter-A's earliest ts is +5s, iter-B's is +10s.
        assert tracker.list_experiment_iters() == ["iter-A", "iter-B"]


# ---------- D2.5: team attribution + per-team budget ----------


class TestTeamCostAttribution:
    """CostEntry team field + get_team_summary + check_team_budget (D2.5)."""

    def test_cost_entry_has_team_field(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        entry = tracker.record(model="haiku", input_tokens=100, output_tokens=50, team="design")
        assert entry.team == "design"

    def test_record_persists_team_kwarg(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(model="haiku", input_tokens=100, output_tokens=50, team="qa")
        lines = (tmp_path / "cost_tracking.jsonl").read_text().splitlines()
        import json
        row = json.loads(lines[-1])
        assert row["team"] == "qa"

    def test_record_default_team_is_empty_string(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        entry = tracker.record(model="haiku", input_tokens=10, output_tokens=5)
        assert entry.team == ""

    def test_get_team_summary_aggregates(self, tmp_path: Path) -> None:
        tracker = CostTracker(
            data_dir=tmp_path,
            team_limits={"design": 6.0, "qa": 5.0},
        )
        tracker.record(model="haiku", input_tokens=0, output_tokens=0, team="design")
        tracker.record(model="haiku", input_tokens=0, output_tokens=0, team="design")
        tracker.record(model="haiku", input_tokens=0, output_tokens=0, team="qa")

        summary = tracker.get_team_summary()
        assert "design" in summary
        assert summary["design"]["count"] == 2
        assert summary["qa"]["count"] == 1
        assert summary["design"]["limit"] == 6.0
        assert summary["qa"]["limit"] == 5.0

    def test_get_team_summary_unattributed_bucket(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(model="haiku", input_tokens=0, output_tokens=0)
        summary = tracker.get_team_summary()
        assert "unattributed" in summary

    def test_get_team_summary_breach_flag(self, tmp_path: Path) -> None:
        import json
        tracker = CostTracker(data_dir=tmp_path, team_limits={"qa": 0.000001})
        # Write a manual entry with cost > limit
        entry_dict = {
            "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "model": "haiku",
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost": 0.001,
            "task_type": "",
            "was_override": False,
            "agent_id": "",
            "feature": "",
            "session_id": "",
            "experiment_iter": "",
            "team": "qa",
        }
        with open(tmp_path / "cost_tracking.jsonl", "w") as f:
            f.write(json.dumps(entry_dict) + "\n")

        summary = tracker.get_team_summary()
        assert summary["qa"]["breach"] is True

    def test_check_team_budget_within(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path, team_limits={"design": 6.0})
        within, spend, limit = tracker.check_team_budget("design")
        assert within is True
        assert limit == 6.0
        assert spend == 0.0

    def test_check_team_budget_no_limit(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        within, spend, limit = tracker.check_team_budget("unknown_team")
        assert within is True
        assert limit == 0.0

    def test_team_limits_constructor_kwarg(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path, team_limits={"design": 6.0, "qa": 5.0})
        assert tracker._team_limits == {"design": 6.0, "qa": 5.0}

    def test_team_limits_default_is_empty(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        assert tracker._team_limits == {}


class TestWorkflowCostAttribution:
    """CostEntry workflow field + get_cost_by_workflow (WS3.1, #2570)."""

    def test_cost_entry_workflow_default_empty(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        entry = tracker.record(model="haiku", input_tokens=10, output_tokens=5)
        assert entry.workflow == ""

    def test_record_persists_workflow_kwarg(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(model="haiku", input_tokens=100, output_tokens=50, workflow="alpha")
        lines = (tmp_path / "cost_tracking.jsonl").read_text().splitlines()
        row = json.loads(lines[-1])
        assert row["workflow"] == "alpha"

    def test_cost_entry_old_jsonl_parses(self, tmp_path: Path) -> None:
        """Legacy JSONL lines without a ``workflow`` key parse cleanly,
        defaulting the field to ``""`` via the dataclass-tolerant reader."""
        entry_dict = {
            "timestamp": "2026-06-02T00:00:00+00:00",
            "model": "haiku",
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost": 0.001,
            "task_type": "",
            "was_override": False,
            "agent_id": "",
            "feature": "",
            "session_id": "",
            "experiment_iter": "",
            "team": "",
        }
        with open(tmp_path / "cost_tracking.jsonl", "w") as f:
            f.write(json.dumps(entry_dict) + "\n")
        tracker = CostTracker(data_dir=tmp_path)
        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].workflow == ""

    def test_get_cost_by_workflow_groups(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(model="haiku", input_tokens=100, output_tokens=50, workflow="alpha")
        tracker.record(model="haiku", input_tokens=100, output_tokens=50, workflow="alpha")
        tracker.record(model="haiku", input_tokens=100, output_tokens=50, workflow="beta")
        tracker.record(model="haiku", input_tokens=100, output_tokens=50)

        by_workflow = tracker.get_cost_by_workflow()
        assert by_workflow["alpha"]["count"] == 2
        assert by_workflow["beta"]["count"] == 1
        assert "" not in by_workflow


# ---------------------------------------------------------------------------
# rtk gain integration (Sprint 01.06 / issue #974)
# ---------------------------------------------------------------------------


def test_read_rtk_gain_parses_valid_json(tmp_path):
    import json as _json
    from unittest.mock import patch, MagicMock
    from bridge.cost_tracker import read_rtk_gain

    fake_output = _json.dumps({
        "tokens_saved": 12000,
        "dollars_saved_estimated": 0.036,
        "period_start": "2026-05-01T00:00:00Z",
        "period_end": "2026-05-06T00:00:00Z",
    })
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = fake_output
    mock_result.stderr = ""

    with patch("shutil.which", return_value="/usr/local/bin/rtk"):
        with patch("subprocess.run", return_value=mock_result):
            summary = read_rtk_gain("1d")

    assert summary is not None
    assert summary.tokens_saved == 12000
    assert summary.dollars_saved_estimated == pytest.approx(0.036)


def test_read_rtk_gain_returns_none_when_rtk_missing():
    from unittest.mock import patch
    from bridge.cost_tracker import read_rtk_gain

    with patch("shutil.which", return_value=None):
        result = read_rtk_gain("1d")
    assert result is None


def test_daily_summary_includes_rtk_line_when_present(tmp_path):
    from unittest.mock import patch
    from bridge.cost_tracker import CostTracker, RtkGainSummary

    ct = CostTracker(tmp_path)
    fake_rtk = RtkGainSummary(
        tokens_saved=5000,
        dollars_saved_estimated=0.015,
        period_start="2026-05-06T00:00:00Z",
        period_end="2026-05-06T23:59:59Z",
    )
    with patch("bridge.cost_tracker.read_rtk_gain", return_value=fake_rtk):
        summary = ct.get_daily_summary()

    assert "rtk_savings" in summary
    assert summary["rtk_savings"]["tokens_saved"] == 5000


def test_daily_summary_omits_rtk_line_when_rtk_missing(tmp_path):
    from unittest.mock import patch
    from bridge.cost_tracker import CostTracker

    ct = CostTracker(tmp_path)
    with patch("bridge.cost_tracker.read_rtk_gain", return_value=None):
        summary = ct.get_daily_summary()

    assert "rtk_savings" not in summary


# ---------------------------------------------------------------------------
# Z4-S40 — work_order_id + chief_session_id attribution + get_session_cost
# ---------------------------------------------------------------------------


class TestZ4S40CostAttribution:
    """CostEntry.work_order_id + chief_session_id round-trip + get_session_cost.

    Z4-S40 (#1398) adds two optional attribution tags so per-WorkOrder and
    per-ChiefSession cost queries become possible without reshaping the
    JSONL log. Defaults are empty strings (not ``None``) so existing rows
    parse cleanly and ``get_session_cost("")`` does not bucket every
    legacy row.
    """

    def test_cost_entry_default_fields_are_empty(self) -> None:
        entry = CostEntry(
            timestamp="2026-05-09T00:00:00+00:00",
            model="sonnet",
            input_tokens=10,
            output_tokens=5,
            estimated_cost=0.0,
            task_type="",
            was_override=False,
        )
        assert entry.work_order_id == ""
        assert entry.chief_session_id == ""

    def test_record_persists_both_fields(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        entry = tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            work_order_id="wo-abc123",
            chief_session_id="cs-deadbeef0001",
        )
        assert entry.work_order_id == "wo-abc123"
        assert entry.chief_session_id == "cs-deadbeef0001"

        # JSONL on disk also carries them.
        raw = tracker.path.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        assert data["work_order_id"] == "wo-abc123"
        assert data["chief_session_id"] == "cs-deadbeef0001"

    def test_record_without_kwargs_defaults_to_empty(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        entry = tracker.record(model="haiku", input_tokens=10, output_tokens=5)
        assert entry.work_order_id == ""
        assert entry.chief_session_id == ""

        # JSONL row carries explicit "" — the dataclass `asdict` includes
        # every field; this is the back-compat contract the rtk
        # aggregator and baseline scripts depend on.
        raw = tracker.path.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        assert data["work_order_id"] == ""
        assert data["chief_session_id"] == ""

    def test_legacy_jsonl_without_new_fields_parses(self, tmp_path: Path) -> None:
        """Existing rows (pre-Z4-S40) parse cleanly via dataclass defaults."""
        tracker = CostTracker(data_dir=tmp_path)
        legacy_line = json.dumps(
            {
                "timestamp": "2026-03-01T00:00:00+00:00",
                "model": "sonnet",
                "input_tokens": 100,
                "output_tokens": 50,
                "estimated_cost": 0.001,
                "task_type": "chat",
                "was_override": False,
                "agent_id": "",
                "feature": "",
                "session_id": "",
                "experiment_iter": "",
                "team": "",
                # no work_order_id, no chief_session_id
            }
        )
        tracker.path.write_text(legacy_line + "\n", encoding="utf-8")

        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].work_order_id == ""
        assert entries[0].chief_session_id == ""

    def test_get_session_cost_sums_across_rows(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        ts = _today_iso()
        # Three entries on cs-abc, two on cs-xyz, one with no chief session.
        seeded = [
            ("cs-abc", 0.10),
            ("cs-abc", 0.20),
            ("cs-abc", 0.05),
            ("cs-xyz", 1.00),
            ("cs-xyz", 2.00),
            ("", 9.99),
        ]
        for sid, cost in seeded:
            tracker._atomic_append(
                CostEntry(
                    timestamp=ts,
                    model="sonnet",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=cost,
                    task_type="",
                    was_override=False,
                    chief_session_id=sid,
                )
            )

        assert tracker.get_session_cost("cs-abc") == pytest.approx(0.35, abs=1e-9)
        assert tracker.get_session_cost("cs-xyz") == pytest.approx(3.00, abs=1e-9)

    def test_get_session_cost_unknown_session_returns_zero(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(
            model="haiku",
            input_tokens=10,
            output_tokens=5,
            chief_session_id="cs-known",
        )
        assert tracker.get_session_cost("cs-does-not-exist") == 0.0

    def test_get_session_cost_missing_file_returns_zero(self, tmp_path: Path) -> None:
        tracker = CostTracker(data_dir=tmp_path)
        # No record() calls — the JSONL never gets created.
        assert not tracker.path.exists()
        assert tracker.get_session_cost("cs-anything") == 0.0

    def test_get_session_cost_empty_session_returns_zero(self, tmp_path: Path) -> None:
        """Querying with empty session_id must not bucket legacy rows."""
        tracker = CostTracker(data_dir=tmp_path)
        # Several rows with empty chief_session_id — the historical case.
        for _ in range(3):
            tracker.record(model="haiku", input_tokens=10, output_tokens=5)
        assert tracker.get_session_cost("") == 0.0

    def test_get_session_cost_mixed_legacy_and_tagged_rows(self, tmp_path: Path) -> None:
        """A log with both legacy rows (no field) and new rows aggregates cleanly.

        The legacy row has no ``chief_session_id`` key; ``_read_entries``
        defaults it to ``""``. Only the two tagged rows count toward
        ``cs-mix`` — legacy + empty-tagged rows are excluded.
        """
        tracker = CostTracker(data_dir=tmp_path)
        # Hand-write one legacy row (no chief_session_id) and one
        # explicit empty-tag row, then add two cs-mix rows.
        legacy = json.dumps(
            {
                "timestamp": "2026-03-01T00:00:00+00:00",
                "model": "sonnet",
                "input_tokens": 100,
                "output_tokens": 50,
                "estimated_cost": 99.0,  # large; must NOT match cs-mix
                "task_type": "",
                "was_override": False,
            }
        )
        tracker.path.write_text(legacy + "\n", encoding="utf-8")
        # Two tagged rows with deterministic costs.
        for cost in (0.25, 0.10):
            tracker._atomic_append(
                CostEntry(
                    timestamp=_today_iso(),
                    model="sonnet",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=cost,
                    task_type="",
                    was_override=False,
                    chief_session_id="cs-mix",
                )
            )

        assert tracker.get_session_cost("cs-mix") == pytest.approx(0.35, abs=1e-9)

    def test_work_order_id_round_trip(self, tmp_path: Path) -> None:
        """work_order_id alone (no chief_session_id) round-trips through JSONL."""
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            work_order_id="wo-zone3-001",
        )
        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].work_order_id == "wo-zone3-001"
        assert entries[0].chief_session_id == ""

    def test_all_attribution_tags_coexist(self, tmp_path: Path) -> None:
        """A single entry carries feature + experiment_iter + team + work_order_id +
        chief_session_id without any tag interfering with the others."""
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            feature="board",
            experiment_iter="iter-99",
            team="design",
            work_order_id="wo-multi",
            chief_session_id="cs-multi",
        )
        entries = tracker._read_entries()
        assert entries[0].feature == "board"
        assert entries[0].experiment_iter == "iter-99"
        assert entries[0].team == "design"
        assert entries[0].work_order_id == "wo-multi"
        assert entries[0].chief_session_id == "cs-multi"


# ------------------------------------------------------------------
# Sprint audit-2026-05-16.D.01 — CostMeasurement data contract (#2062)
# ------------------------------------------------------------------
#
# Keystone contract for Phase D. Encodes the four cost-knowledge states
# (measured / estimated / unknown / not_applicable) so budget gates can stop
# treating ``None``, ``0.0``, and missing parse data as the same thing.
# Contract-only — no callers wired here; D.02/D.04/D.06/D.07 consume.


from decimal import Decimal  # noqa: E402

from bridge.cost_tracker import (  # noqa: E402
    CostMeasurement,
    DEFAULT_OPENROUTER_DAILY_CAP_USD,
    DEFAULT_OPENROUTER_SMOKE_CAP_USD,
    evaluate_cost_measurement_against_cap,
    from_legacy_float,
    is_chargeable_under_strict_budget,
    to_legacy_float,
)


class TestCostMeasurementContract:
    """SW-3 — the four cost-knowledge states must stay distinct."""

    def test_cost_measurement_unknown_not_equal_zero(self) -> None:
        """Unknown cost MUST NOT compare equal to a measured zero — that
        collapse is the exact failure mode budget gates need to avoid."""
        unknown = CostMeasurement(
            amount_usd=None, source="unknown", backend="codex"
        )
        measured_zero = CostMeasurement(
            amount_usd=Decimal("0"), source="measured", backend="codex"
        )
        assert unknown != measured_zero
        # And the inverse — defensive: equality is symmetric.
        assert measured_zero != unknown
        # Two unknown values with the same backend ARE equal (same epistemic
        # state); two unknowns with different backends are not.
        assert unknown == CostMeasurement(
            amount_usd=None, source="unknown", backend="codex"
        )
        assert unknown != CostMeasurement(
            amount_usd=None, source="unknown", backend="claude"
        )

    def test_cost_measurement_zero_measured_representable(self) -> None:
        """A measured zero ($0.00 confirmed by a parser) round-trips through
        the legacy float helpers and remains ``source='measured'`` — this is
        the case Codex subscription-billed turns will eventually express."""
        m = from_legacy_float(0.0, backend="codex")
        assert m.source == "measured"
        assert m.amount_usd == Decimal("0")
        # to_legacy_float MUST return 0.0, not None, for measured zero.
        assert to_legacy_float(m) == 0.0

    def test_cost_measurement_strict_budget_gate_rejects_unknown(self) -> None:
        """Under a strict budget gate, unknown and not_applicable do NOT
        count as chargeable — the gate cannot rely on them being zero or
        any other comparable number. Measured and estimated DO count."""
        unknown = CostMeasurement(
            amount_usd=None, source="unknown", backend="codex"
        )
        not_applicable = CostMeasurement(
            amount_usd=None, source="not_applicable", backend="internal"
        )
        measured = CostMeasurement(
            amount_usd=Decimal("0.05"), source="measured", backend="claude"
        )
        estimated = CostMeasurement(
            amount_usd=Decimal("0.05"), source="estimated", backend="claude"
        )
        assert is_chargeable_under_strict_budget(unknown) is False
        assert is_chargeable_under_strict_budget(not_applicable) is False
        assert is_chargeable_under_strict_budget(measured) is True
        assert is_chargeable_under_strict_budget(estimated) is True

    def test_cost_measurement_from_legacy_float(self) -> None:
        """A concrete float from a legacy parser becomes a measured
        CostMeasurement with the float widened to Decimal (via str() to
        avoid binary-float rounding artefacts)."""
        m = from_legacy_float(0.05, backend="codex", raw_usage_id="usage-1")
        assert m.source == "measured"
        assert m.amount_usd == Decimal("0.05")
        assert m.backend == "codex"
        assert m.raw_usage_id == "usage-1"

    def test_cost_measurement_from_legacy_none_is_unknown(self) -> None:
        """A None from a legacy parser becomes an unknown CostMeasurement —
        NOT a measured zero. This is the collapse SW-3 calls out."""
        m = from_legacy_float(None, backend="codex")
        assert m.source == "unknown"
        assert m.amount_usd is None
        assert m.backend == "codex"
        assert m.raw_usage_id is None

    def test_cost_measurement_to_legacy_float_unknown_raises(self) -> None:
        """Converting an unknown back to ``float | None`` MUST fail loudly.
        Silently returning 0.0 (or None and letting the caller treat it as
        zero downstream) is the exact failure mode the contract exists to
        prevent. Discipline: fail-closed with ValueError."""
        unknown = CostMeasurement(
            amount_usd=None, source="unknown", backend="codex"
        )
        with pytest.raises(ValueError, match="unknown"):
            to_legacy_float(unknown)
        # not_applicable also raises — caller must consciously handle it.
        not_applicable = CostMeasurement(
            amount_usd=None, source="not_applicable", backend="internal"
        )
        with pytest.raises(ValueError, match="not_applicable"):
            to_legacy_float(not_applicable)
        # Measured non-zero round-trips cleanly.
        measured = CostMeasurement(
            amount_usd=Decimal("0.123456"), source="measured", backend="claude"
        )
        assert to_legacy_float(measured) == 0.123456


class TestOpenRouterBudgetPolicy:
    """VAL-16 — OpenRouter cap and unknown-cost behavior."""

    def test_default_caps_are_explicit(self) -> None:
        assert DEFAULT_OPENROUTER_DAILY_CAP_USD == Decimal("1.00")
        assert DEFAULT_OPENROUTER_SMOKE_CAP_USD == Decimal("0.05")

    def test_measured_cost_under_cap_is_allowed(self) -> None:
        decision = evaluate_cost_measurement_against_cap(
            CostMeasurement(
                amount_usd=Decimal("0.01"),
                source="measured",
                backend="openrouter",
            ),
            cap_usd=DEFAULT_OPENROUTER_SMOKE_CAP_USD,
        )

        assert decision.allowed is True
        assert decision.reason == "within_cap"
        assert decision.amount_usd == Decimal("0.01")
        assert decision.cap_usd == DEFAULT_OPENROUTER_SMOKE_CAP_USD

    def test_estimated_cost_over_cap_is_blocked(self) -> None:
        decision = evaluate_cost_measurement_against_cap(
            CostMeasurement(
                amount_usd=Decimal("0.06"),
                source="estimated",
                backend="openrouter",
            ),
            cap_usd=DEFAULT_OPENROUTER_SMOKE_CAP_USD,
        )

        assert decision.allowed is False
        assert decision.reason == "over_cap"
        assert decision.amount_usd == Decimal("0.06")

    def test_unknown_cost_fails_closed_not_zero(self) -> None:
        decision = evaluate_cost_measurement_against_cap(
            CostMeasurement(
                amount_usd=None,
                source="unknown",
                backend="openrouter",
            ),
            cap_usd=DEFAULT_OPENROUTER_SMOKE_CAP_USD,
        )

        assert decision.allowed is False
        assert decision.reason == "unknown_cost"
        assert decision.amount_usd is None
        assert decision.cap_usd == DEFAULT_OPENROUTER_SMOKE_CAP_USD

    def test_not_applicable_cost_is_off_meter(self) -> None:
        decision = evaluate_cost_measurement_against_cap(
            CostMeasurement(
                amount_usd=None,
                source="not_applicable",
                backend="internal",
            ),
            cap_usd=DEFAULT_OPENROUTER_SMOKE_CAP_USD,
        )

        assert decision.allowed is True
        assert decision.reason == "not_applicable"
        assert decision.amount_usd is None


# ------------------------------------------------------------------
# Sprint audit-2026-05-16.D.05 — last_session_measurement accessor (#2066)
# ------------------------------------------------------------------
#
# D.04's strict-mode budget gate (ChiefDispatcher.dispatch) uses
# ``hasattr(cost_tracker, "last_session_measurement")`` to no-op when the
# accessor is missing. Shipping the accessor here activates the gate; the
# tests below pin the contract D.04 reads against.


class TestLastSessionMeasurement:
    """``CostTracker.last_session_measurement`` — D.04 strict-budget gate input."""

    def test_returns_none_when_no_entries(self, tmp_path: Path) -> None:
        """Empty log → None for any session id."""
        tracker = CostTracker(data_dir=tmp_path)
        assert tracker.last_session_measurement("cs-anything") is None

    def test_returns_none_for_empty_session_id(self, tmp_path: Path) -> None:
        """Empty session id MUST NOT match legacy rows whose
        ``chief_session_id`` defaulted to ``""`` — mirrors the same
        guard ``get_session_cost`` carries."""
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(model="haiku", input_tokens=10, output_tokens=5)
        assert tracker.last_session_measurement("") is None

    def test_returns_none_when_session_not_present(self, tmp_path: Path) -> None:
        """An unrelated session's rows MUST NOT leak across the lookup."""
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(
            model="haiku",
            input_tokens=10,
            output_tokens=5,
            chief_session_id="cs-other",
        )
        assert tracker.last_session_measurement("cs-missing") is None

    def test_returns_most_recent_for_session(self, tmp_path: Path) -> None:
        """Three entries for cs-A interleaved with one for cs-B — the
        accessor MUST return the newest cs-A entry. Anchors the
        per-session contract for D.04's strict-mode last-look."""
        tracker = CostTracker(data_dir=tmp_path)
        seeded = [
            ("2026-05-15T10:00:00+00:00", "cs-A", 0.10),
            ("2026-05-15T11:00:00+00:00", "cs-B", 0.50),
            ("2026-05-15T12:00:00+00:00", "cs-A", 0.20),
            ("2026-05-15T13:00:00+00:00", "cs-A", 0.30),  # newest for cs-A
        ]
        for ts, sid, cost in seeded:
            tracker._atomic_append(
                CostEntry(
                    timestamp=ts,
                    model="sonnet",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=cost,
                    task_type="",
                    was_override=False,
                    chief_session_id=sid,
                )
            )

        m = tracker.last_session_measurement("cs-A")
        assert m is not None
        assert m.amount_usd == Decimal("0.3")

    def test_returns_cost_measurement_shape(self, tmp_path: Path) -> None:
        """Return type MUST be ``CostMeasurement``, not ``CostEntry`` — the
        D.04 gate reads ``.source`` and ``.backend`` off this value."""
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            chief_session_id="cs-shape",
        )
        m = tracker.last_session_measurement("cs-shape")
        assert isinstance(m, CostMeasurement)
        # Legacy-float wrapping path: any recorded entry is ``source='measured'``
        # until D.06/D.07 thread an explicit source signal through. Pin the
        # contract here so the D.04 gate's ``unknown`` branch never fires off a
        # recorded row.
        assert m.source == "measured"

    def test_backend_propagates_from_entry(self, tmp_path: Path) -> None:
        """When a recorded entry carries a non-empty ``backend``, the
        wrapped CostMeasurement preserves it. Empty backend falls back to
        ``"claude"`` (matches the historical bucketing in the summary
        aggregators)."""
        tracker = CostTracker(data_dir=tmp_path)
        tracker.record(
            model="sonnet",
            input_tokens=10,
            output_tokens=5,
            chief_session_id="cs-codex",
            backend="codex",
        )
        m = tracker.last_session_measurement("cs-codex")
        assert m is not None
        assert m.backend == "codex"

        # Empty-backend row gets bucketed as "claude" — the legacy default.
        tracker.record(
            model="haiku",
            input_tokens=10,
            output_tokens=5,
            chief_session_id="cs-legacy",
        )
        m2 = tracker.last_session_measurement("cs-legacy")
        assert m2 is not None
        assert m2.backend == "claude"


# ------------------------------------------------------------------
# Sprint audit-2026-05-16.D.07 — shared subprocess cost parser (#2068)
# ------------------------------------------------------------------
#
# M-4 in docs/audits/2026-05-16-whole-codebase-audit-expanded.md flags that
# ``job_search/rubric.py::_extract_payload`` and ``experiment_loop.py``'s
# validator-subprocess parser are two independent ad-hoc implementations of
# the same logic. Both walk Claude ``stream-json`` stdout, look for the
# terminal ``result`` event, and read ``cost_usd``. They diverge on edge
# cases (missing field, empty stdout, malformed JSON) and on how the
# missing-cost state is surfaced (one falls back to 0.0, the other to NaN).
#
# This sprint introduces a shared, source-aware parser in ``cost_tracker``:
#
#   - ``parse_subprocess_result_cost(event: dict, *, backend: str)`` —
#     pure function over a single result event. Easiest to test.
#   - ``parse_claude_stream_json_cost(stdout: str, *, backend: str)`` —
#     walks NDJSON and feeds the terminal result event through the function
#     above. This is what the ad-hoc callers replace.

from bridge.cost_tracker import (  # noqa: E402
    parse_claude_stream_json_cost,
    parse_subprocess_result_cost,
)


class TestParseSubprocessResultCost:
    """Single-event parser — measured / estimated / unknown discrimination."""

    def test_parse_subprocess_result_cost_measured(self) -> None:
        """Event with a positive ``cost_usd`` → ``source='measured'``."""
        event = {"type": "result", "cost_usd": 0.5, "session_id": "s-1"}
        m = parse_subprocess_result_cost(event, backend="claude")
        assert m.source == "measured"
        assert m.amount_usd == Decimal("0.5")
        assert m.backend == "claude"
        assert m.raw_usage_id == "s-1"

    def test_parse_subprocess_result_cost_measured_zero(self) -> None:
        """A confirmed ``cost_usd: 0.0`` is a measured zero, NOT unknown.
        This is the SW-3 invariant — measured zero and unknown must stay
        distinct. (Codex subscription-billed turns hit this branch.)"""
        event = {"type": "result", "cost_usd": 0.0, "session_id": "s-z"}
        m = parse_subprocess_result_cost(event, backend="claude")
        assert m.source == "measured"
        assert m.amount_usd == Decimal("0")

    def test_parse_subprocess_result_cost_estimated_from_tokens(self) -> None:
        """No ``cost_usd`` but a ``usage`` block with token counts → fall
        back to the ``PRICING`` table for the named backend and tag the
        result ``source='estimated'``. Demonstrates the third state SW-3
        names — between measured and unknown."""
        event = {
            "type": "result",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
            "session_id": "s-est",
        }
        m = parse_subprocess_result_cost(event, backend="sonnet")
        assert m.source == "estimated"
        # Sonnet pricing: (3.0, 15.0) per 1M tokens → 1000*3/1e6 + 500*15/1e6
        # = 0.003 + 0.0075 = 0.0105
        assert m.amount_usd == Decimal(str(0.0105))

    def test_parse_subprocess_result_cost_unknown_when_no_signal(self) -> None:
        """No ``cost_usd``, no ``usage`` → ``unknown``. Amount MUST be
        ``None`` (not 0.0) so downstream code cannot misread the gap."""
        event = {"type": "result", "session_id": "s-u"}
        m = parse_subprocess_result_cost(event, backend="claude")
        assert m.source == "unknown"
        assert m.amount_usd is None
        # session_id preserved on the unknown so forensic trace still works.
        assert m.raw_usage_id == "s-u"

    def test_parse_subprocess_result_cost_unknown_for_unknown_backend(self) -> None:
        """Token usage present but the named backend isn't in ``PRICING``
        → ``unknown``. We MUST NOT invent pricing for an unfamiliar model."""
        event = {
            "type": "result",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
            "session_id": "s-codex",
        }
        m = parse_subprocess_result_cost(event, backend="codex")
        assert m.source == "unknown"
        assert m.amount_usd is None
        assert m.backend == "codex"

    def test_parse_subprocess_result_cost_unknown_for_malformed_cost(self) -> None:
        """A ``cost_usd`` that won't parse as Decimal (e.g. a string token
        like ``"n/a"``) → ``unknown``, not measured-zero."""
        event = {"type": "result", "cost_usd": "n/a", "session_id": "s-bad"}
        m = parse_subprocess_result_cost(event, backend="claude")
        assert m.source == "unknown"
        assert m.amount_usd is None


class TestParseClaudeStreamJsonCost:
    """Stream-walker that finds the final ``result`` event and delegates."""

    def test_parses_measured_cost_from_full_stream(self) -> None:
        """Realistic stream-json: system init, assistant chunks, terminal
        result event with ``cost_usd``. Parser walks every line and reads
        the result event."""
        stream = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "s-A"}),
            json.dumps({"type": "assistant", "message": {"content": []}}),
            json.dumps({
                "type": "result", "subtype": "success",
                "cost_usd": 0.012, "session_id": "s-A",
            }),
        ])
        m = parse_claude_stream_json_cost(stream, backend="claude")
        assert m.source == "measured"
        assert m.amount_usd == Decimal("0.012")
        assert m.raw_usage_id == "s-A"

    def test_unknown_when_stdout_empty(self) -> None:
        """No stdout → unknown (the subprocess crashed before emitting
        anything; we have nothing to measure)."""
        m = parse_claude_stream_json_cost("", backend="claude")
        assert m.source == "unknown"
        assert m.amount_usd is None

    def test_unknown_when_no_result_event(self) -> None:
        """Stream has assistant chunks but no terminal ``result`` event
        (e.g. timeout mid-stream) → unknown."""
        stream = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "s-B"}),
            json.dumps({"type": "assistant", "message": {"content": []}}),
        ])
        m = parse_claude_stream_json_cost(stream, backend="claude")
        assert m.source == "unknown"
        assert m.amount_usd is None

    def test_non_json_lines_ignored(self) -> None:
        """Stray non-JSON lines (rare; stderr leaking onto stdout) MUST
        NOT crash the parser. They are silently skipped; the real result
        event still wins."""
        stream = "\n".join([
            "this is not json",
            json.dumps({
                "type": "result", "cost_usd": 0.007, "session_id": "s-mix",
            }),
            "trailing garbage",
        ])
        m = parse_claude_stream_json_cost(stream, backend="claude")
        assert m.source == "measured"
        assert m.amount_usd == Decimal("0.007")

    def test_terminal_result_wins_on_duplicate(self) -> None:
        """If a stream ever contains two result events (defensive; Claude
        currently emits one), the terminal one wins — matches the
        last-seen semantics in the legacy ad-hoc parsers."""
        stream = "\n".join([
            json.dumps({"type": "result", "cost_usd": 0.001, "session_id": "s-x"}),
            json.dumps({"type": "result", "cost_usd": 0.999, "session_id": "s-x"}),
        ])
        m = parse_claude_stream_json_cost(stream, backend="claude")
        assert m.source == "measured"
        assert m.amount_usd == Decimal("0.999")
