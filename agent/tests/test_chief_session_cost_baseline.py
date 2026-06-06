"""Tests for scripts/chief_session_cost_baseline.py.

Z4-S43 #1403 — verifies the chief-session baseline aggregator filters
correctly by window AND by ``chief_session_id`` presence, rolls up
costs per session and per department, computes a cost-per-session
summary, and writes a markdown summary in the shape the runbook expects.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_module():
    """Import scripts/chief_session_cost_baseline.py as a module.

    Path resolution: agent/tests/<f>.py → parent → parent → REPO ROOT
    → scripts/chief_session_cost_baseline.py

    The module is registered in ``sys.modules`` before exec_module runs so
    that ``@dataclass(field(default_factory=...))`` annotation resolution
    can find the module's namespace via ``cls.__module__`` lookup. Without
    this, Python 3.13's dataclass machinery raises AttributeError on
    NoneType when annotations reference classes from the same module.
    """
    import sys
    name = "chief_session_cost_baseline"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / f"{name}.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Window filtering + chief_session_id gating
# ---------------------------------------------------------------------------


class TestWindowFilter:
    def test_includes_chief_session_entries_in_window(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-15T08:00:00Z", "model": "haiku",
             "chief_session_id": "cs-aaa", "team": "engineering",
             "estimated_cost": 0.002},
            {"timestamp": "2026-05-15T20:00:00Z", "model": "sonnet",
             "chief_session_id": "cs-aaa", "team": "engineering",
             "estimated_cost": 0.027},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 2
        assert summary.total_cost_usd == pytest.approx(0.029)

    def test_excludes_pre_z4_s40_rows_with_empty_chief_session_id(
        self, tmp_path: Path
    ):
        """Legacy rows (no chief_session_id) MUST be filtered out — they
        carry no chief-session attribution. Same with rows where the field
        defaults to "".
        """
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            # Legacy row — no chief_session_id field at all
            {"timestamp": "2026-05-15T08:00:00Z", "model": "haiku",
             "team": "engineering", "estimated_cost": 0.002},
            # Z4-S40 row but field defaulted to ""
            {"timestamp": "2026-05-15T09:00:00Z", "model": "haiku",
             "chief_session_id": "", "team": "engineering",
             "estimated_cost": 0.003},
            # Real chief-session row
            {"timestamp": "2026-05-15T20:00:00Z", "model": "sonnet",
             "chief_session_id": "cs-aaa", "team": "engineering",
             "estimated_cost": 0.027},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 1
        assert summary.total_cost_usd == pytest.approx(0.027)
        assert "cs-aaa" in summary.by_session

    def test_excludes_entries_before_window(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-14T23:59:59Z", "model": "haiku",
             "chief_session_id": "cs-aaa", "team": "engineering",
             "estimated_cost": 0.001},
            {"timestamp": "2026-05-15T00:00:00Z", "model": "sonnet",
             "chief_session_id": "cs-bbb", "team": "engineering",
             "estimated_cost": 0.027},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 1
        assert "cs-bbb" in summary.by_session
        assert "cs-aaa" not in summary.by_session

    def test_excludes_entries_at_or_after_end(self, tmp_path: Path):
        """End is exclusive — an entry at exactly end_ts is excluded."""
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-16T00:00:00Z", "model": "haiku",
             "chief_session_id": "cs-aaa", "team": "engineering",
             "estimated_cost": 0.001},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 0

    def test_handles_missing_log_file(self, tmp_path: Path):
        mod = _load_module()
        summary = mod.aggregate_window(
            tmp_path / "nope.jsonl",
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 0
        assert summary.total_cost_usd == 0.0

    def test_skips_malformed_lines(self, tmp_path: Path):
        """A malformed JSON line, missing-timestamp line, or unparseable
        timestamp must not crash the aggregator. Mirrors the rtk script's
        defensive shape.
        """
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        log.write_text(
            '{"timestamp":"2026-05-15T08:00:00Z","chief_session_id":"cs-aaa",'
            '"team":"engineering","estimated_cost":0.002}\n'
            "not valid json\n"
            "\n"
            '{"no_timestamp":true,"chief_session_id":"cs-x","estimated_cost":99}\n'
            '{"timestamp":"not-a-date","chief_session_id":"cs-x","estimated_cost":99}\n'
            '{"timestamp":"2026-05-15T20:00:00Z","chief_session_id":"cs-bbb",'
            '"team":"strategy","estimated_cost":0.027}\n',
            encoding="utf-8",
        )
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 2
        assert summary.total_cost_usd == pytest.approx(0.029)


# ---------------------------------------------------------------------------
# Roll-up shape — by department + by session
# ---------------------------------------------------------------------------


class TestDepartmentRollup:
    def test_by_department_attributes_via_team_field(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-15T08:00:00Z", "chief_session_id": "cs-a",
             "team": "engineering", "estimated_cost": 0.10},
            {"timestamp": "2026-05-15T09:00:00Z", "chief_session_id": "cs-a",
             "team": "engineering", "estimated_cost": 0.05},
            {"timestamp": "2026-05-15T10:00:00Z", "chief_session_id": "cs-b",
             "team": "strategy", "estimated_cost": 0.30},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        assert summary.by_department["engineering"].total_usd == pytest.approx(0.15)
        assert summary.by_department["engineering"].run_count == 2
        assert summary.by_department["engineering"].session_count == 1
        assert summary.by_department["strategy"].total_usd == pytest.approx(0.30)
        assert summary.by_department["strategy"].session_count == 1

    def test_empty_team_lands_in_unattributed(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-15T08:00:00Z", "chief_session_id": "cs-a",
             "team": "", "estimated_cost": 0.02},
            {"timestamp": "2026-05-15T09:00:00Z", "chief_session_id": "cs-b",
             "estimated_cost": 0.03},  # missing team field entirely
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        assert "(unattributed)" in summary.by_department
        assert summary.by_department["(unattributed)"].total_usd == pytest.approx(0.05)
        assert summary.by_department["(unattributed)"].session_count == 2


class TestSessionRollup:
    def test_session_total_aggregates_runs(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-15T08:00:00Z", "chief_session_id": "cs-aaa",
             "team": "engineering", "estimated_cost": 0.10},
            {"timestamp": "2026-05-15T09:00:00Z", "chief_session_id": "cs-aaa",
             "team": "engineering", "estimated_cost": 0.05},
            {"timestamp": "2026-05-15T10:00:00Z", "chief_session_id": "cs-aaa",
             "team": "engineering", "estimated_cost": 0.02},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        session = summary.by_session["cs-aaa"]
        assert session.run_count == 3
        assert session.total_usd == pytest.approx(0.17)
        assert session.department == "engineering"


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestMarkdownRender:
    def test_render_includes_header_department_and_top_sessions(
        self, tmp_path: Path
    ):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        # 12 sessions so we can verify the top-10 cap
        entries = []
        for i in range(12):
            entries.append({
                "timestamp": "2026-05-15T08:00:00Z",
                "chief_session_id": f"cs-{i:03d}",
                "team": "engineering" if i < 8 else "strategy",
                "estimated_cost": 0.10 * (i + 1),  # ascending so cs-011 is top
            })
        _write_jsonl(log, entries)
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="post-flip-week-1",
        )
        rendered = mod.render_markdown(summary)
        assert "# Chief-Session Cost Baseline — post-flip-week-1" in rendered
        assert "Chief-session entries: 12" in rendered
        assert "Distinct sessions: 12" in rendered
        assert "## By department" in rendered
        assert "## Top 10 most-expensive sessions" in rendered
        assert "## Cost-per-session summary" in rendered
        # Top session is cs-011 (cost = 0.10 * 12 = 1.20)
        assert "cs-011" in rendered
        # Verify top-10 cap — cs-000 (lowest cost) must NOT appear
        assert "| cs-000 |" not in rendered
        # Department sums: engineering = 0.10 * (1+2+..+8) = 3.6
        # strategy = 0.10 * (9+10+11+12) = 4.2
        assert "engineering" in rendered
        assert "strategy" in rendered

    def test_top_sessions_sorted_by_total_descending(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-15T08:00:00Z", "chief_session_id": "cs-mid",
             "team": "engineering", "estimated_cost": 0.50},
            {"timestamp": "2026-05-15T09:00:00Z", "chief_session_id": "cs-high",
             "team": "engineering", "estimated_cost": 1.00},
            {"timestamp": "2026-05-15T10:00:00Z", "chief_session_id": "cs-low",
             "team": "engineering", "estimated_cost": 0.10},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        rendered = mod.render_markdown(summary)
        # Index of each session row in the rendered output
        i_high = rendered.index("cs-high")
        i_mid = rendered.index("cs-mid")
        i_low = rendered.index("cs-low")
        assert i_high < i_mid < i_low

    def test_render_empty_window_states_so_with_extend_hint(self):
        mod = _load_module()
        summary = mod.WindowSummary(
            label="empty-week",
            start="2026-05-15T00:00:00+00:00",
            end="2026-05-22T00:00:00+00:00",
        )
        rendered = mod.render_markdown(summary)
        assert "Chief-session entries: 0" in rendered
        assert "_No chief-session cost entries in window._" in rendered
        assert "Extend the window" in rendered


# ---------------------------------------------------------------------------
# Cost-per-session summary stats
# ---------------------------------------------------------------------------


class TestCostPerSessionStats:
    def test_summary_includes_avg_p50_p95(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        # 20 sessions, each one run, costs 1..20 cents
        entries = []
        for i in range(1, 21):
            entries.append({
                "timestamp": "2026-05-15T08:00:00Z",
                "chief_session_id": f"cs-{i:03d}",
                "team": "engineering",
                "estimated_cost": i / 100.0,
            })
        _write_jsonl(log, entries)
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-15T00:00:00Z"),
            end=mod.parse_iso("2026-05-16T00:00:00Z"),
            label="test",
        )
        rendered = mod.render_markdown(summary)
        # avg = mean(0.01..0.20) = 0.105
        assert "$0.1050" in rendered
        # p50 = median, statistics.median of even-length list is mean of two
        # middle = (0.10 + 0.11) / 2 = 0.105
        # p95 nearest-rank = sorted[int(0.95 * 20 + 0.5) - 1] = sorted[18] = 0.19
        assert "$0.1900" in rendered


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------


class TestPercentile:
    def test_empty_returns_zero(self):
        mod = _load_module()
        assert mod.percentile([], 95.0) == 0.0

    def test_single_value(self):
        mod = _load_module()
        assert mod.percentile([0.42], 95.0) == 0.42

    def test_p95_over_20(self):
        mod = _load_module()
        # 20 values, p95 nearest-rank index = ceil(0.95 * 20) - 1 = 18
        vals = [i / 100.0 for i in range(1, 21)]
        assert mod.percentile(vals, 95.0) == pytest.approx(0.19)


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------


class TestCLI:
    def test_writes_summary_and_returns_zero_on_data(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-15T08:00:00Z", "model": "haiku",
             "chief_session_id": "cs-aaa", "team": "engineering",
             "estimated_cost": 0.002},
        ])
        out = tmp_path / "summary.md"
        rc = mod.main([
            "--start", "2026-05-15T00:00:00Z",
            "--end", "2026-05-16T00:00:00Z",
            "--label", "test-label",
            "--output", str(out),
            "--cost-log", str(log),
        ])
        assert rc == 0
        assert out.exists()
        body = out.read_text(encoding="utf-8")
        assert "test-label" in body
        assert "cs-aaa" in body

    def test_returns_one_when_log_missing(self, tmp_path: Path):
        mod = _load_module()
        out = tmp_path / "summary.md"
        rc = mod.main([
            "--start", "2026-05-15T00:00:00Z",
            "--end", "2026-05-16T00:00:00Z",
            "--label", "test",
            "--output", str(out),
            "--cost-log", str(tmp_path / "nope.jsonl"),
        ])
        # Empty summary written, exit 1 to flag the operator
        assert rc == 1
        assert out.exists()

    def test_returns_one_when_window_has_no_chief_sessions(self, tmp_path: Path):
        """Even when the cost log exists, an empty window (no chief-session
        entries) must exit 1 — the operator's signal to extend the window
        or re-verify chief_dispatcher_enabled is on.
        """
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        # Only legacy / non-chief rows — should yield zero entries
        _write_jsonl(log, [
            {"timestamp": "2026-05-15T08:00:00Z", "model": "haiku",
             "team": "engineering", "estimated_cost": 0.002},
            {"timestamp": "2026-05-15T09:00:00Z", "chief_session_id": "",
             "team": "engineering", "estimated_cost": 0.002},
        ])
        out = tmp_path / "summary.md"
        rc = mod.main([
            "--start", "2026-05-15T00:00:00Z",
            "--end", "2026-05-16T00:00:00Z",
            "--label", "test",
            "--output", str(out),
            "--cost-log", str(log),
        ])
        assert rc == 1
        assert "_No chief-session cost entries in window._" in out.read_text(
            encoding="utf-8"
        )

    def test_returns_two_on_inverted_window(self, tmp_path: Path):
        mod = _load_module()
        out = tmp_path / "summary.md"
        rc = mod.main([
            "--start", "2026-05-16T00:00:00Z",
            "--end", "2026-05-15T00:00:00Z",  # before start → error
            "--label", "test",
            "--output", str(out),
            "--cost-log", str(tmp_path / "nope.jsonl"),
        ])
        assert rc == 2

    def test_returns_two_on_bad_iso_timestamp(self, tmp_path: Path):
        mod = _load_module()
        out = tmp_path / "summary.md"
        rc = mod.main([
            "--start", "not-a-date",
            "--end", "2026-05-16T00:00:00Z",
            "--label", "test",
            "--output", str(out),
            "--cost-log", str(tmp_path / "nope.jsonl"),
        ])
        assert rc == 2


# ---------------------------------------------------------------------------
# P3.4 (#1586) — Blocking cost budget + mid-run cap
# ---------------------------------------------------------------------------
#
# Three behaviors covered:
#
# 1. Daily-budget pre-flight reject — ChiefDispatcher.dispatch consults the
#    wired BudgetGuard before creating the WARM session, and on
#    ``allowed=False`` it records a SHUTDOWN session with
#    ``metadata.block_reason="daily_budget_exhausted"``, publishes
#    ``chief_dispatcher.rejected`` with the reason, fires an URGENT
#    escalation surface, and never invokes WarmChief.
#
# 2. Team-side mid-run cap — DepartmentTeam.run flips ``success=False``
#    with a ``COST_CAP_EXCEEDED:`` error prefix when the estimated run cost
#    exceeds ``config.constraints.cost_limit_usd``. The check populates
#    ``total_cost_usd`` for downstream WarmChief attribution either way.
#
# 3. Per-delegation cap — the chief's ``delegate()`` tool refuses further
#    delegations once accumulated delegation cost exceeds the cap, returning
#    a ``COST_CAP_EXCEEDED:`` string to the chief's synthesis step.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestP34DailyBudgetPreflightReject:
    """ChiefDispatcher.dispatch rejects when BudgetGuard says budget exhausted.

    These tests build a minimal dispatcher with a fake budget guard, fake
    router (returning a fixed RoutingDecision), an InMemoryChiefSessionStore,
    and a real EventBus so the ``chief_dispatcher.rejected`` event is
    observable through the production publish path.
    """

    async def _dispatcher_and_deps(self, tmp_path: Path, *, allowed: bool,
                                    spent_today: float = 0.0,
                                    daily_limit: float = 5.0):
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.chief_session_store import InMemoryChiefSessionStore
        from bridge.event_bus import EventBus
        from bridge.work_order_router import (
            RoutingDecision,
            WorkOrderRouter,
        )
        from teams._types import AgentSpec, DepartmentConfig

        class _FakeBudget:
            async def check(self_inner):
                return {
                    "allowed": allowed,
                    "spent_today": spent_today,
                    "remaining": max(daily_limit - spent_today, 0.0),
                    "daily_limit": daily_limit,
                    "alert_level": "exceeded" if not allowed else "ok",
                }

        class _StaticRouter(WorkOrderRouter):
            async def route(self_inner, wo):
                return RoutingDecision(
                    department="qa",
                    rationale="static-test",
                    confidence=1.0,
                )

        class _FakeRegistry:
            def get_config(self_inner, name):
                return DepartmentConfig(
                    name="qa",
                    zone=4,
                    description="QA dept",
                    manager=AgentSpec(name="qa-chief", model="sonnet"),
                    employees=(),
                )

        class _RecordingEscalation:
            def __init__(self_inner) -> None:
                self_inner.calls: list[dict] = []

            def notify(self_inner, *, level, source, message) -> None:
                self_inner.calls.append(
                    {"level": level, "source": source, "message": message}
                )

        store = InMemoryChiefSessionStore()
        bus = EventBus(data_dir=tmp_path)
        esc = _RecordingEscalation()
        dispatcher = ChiefDispatcher(
            router=_StaticRouter(),
            session_store=store,
            dept_registry=_FakeRegistry(),
            event_bus=bus,
            escalation=esc,
            budget_guard=_FakeBudget(),
        )
        return dispatcher, store, bus, esc

    async def test_dispatch_rejects_when_budget_exhausted(self, tmp_path):
        from bridge.chief_session import ChiefSessionState
        from bridge.work_order import WorkOrder

        dispatcher, store, bus, esc = await self._dispatcher_and_deps(
            tmp_path, allowed=False, spent_today=10.0, daily_limit=5.0,
        )
        wo = WorkOrder.create(intent="run qa", skill="test",
                              project="test-project")
        session = await dispatcher.dispatch(wo, deps=object())

        # SHUTDOWN row landed in the store with the block telemetry.
        assert session.state == ChiefSessionState.SHUTDOWN
        assert session.metadata["block_reason"] == "daily_budget_exhausted"
        assert session.metadata["block_telemetry"]["spent_today"] == 10.0
        assert session.metadata["block_telemetry"]["daily_limit"] == 5.0
        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.SHUTDOWN

        # Rejected event carries the reason.
        rejected = [e for e in bus._recent_events
                    if e.event_type == "chief_dispatcher.rejected"]
        assert len(rejected) == 1
        assert rejected[0].payload["reason"] == "daily_budget_exhausted"
        assert rejected[0].payload["spent_today"] == 10.0
        assert rejected[0].payload["session_id"] == session.session_id

        # Escalation fired URGENT.
        assert len(esc.calls) == 1
        call = esc.calls[0]
        assert "daily_budget_exhausted" in call["message"].lower() or \
               "daily budget" in call["message"].lower()

    async def test_dispatch_proceeds_when_budget_has_headroom(self, tmp_path):
        """Allowed=True path is the no-op — dispatch routes normally.

        Patch WarmChief so we don't need an Anthropic key.
        """
        from unittest import mock
        from bridge.chief_session import ChiefSessionState
        from bridge.warm_chief import WarmChief
        from bridge.work_order import WorkOrder
        from teams._types import TeamResult

        dispatcher, store, bus, esc = await self._dispatcher_and_deps(
            tmp_path, allowed=True, spent_today=0.5, daily_limit=5.0,
        )
        wo = WorkOrder.create(intent="run qa", skill="test",
                              project="test-project")

        async def _fake_run_chief(self_inner):
            return TeamResult(
                department="qa",
                manager_output="ok",
                success=True,
                duration_seconds=0.01,
            )

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps=object())

        assert session.state == ChiefSessionState.AWAITING_EVALUATION
        # No rejected event, no escalation call.
        rejected = [e for e in bus._recent_events
                    if e.event_type == "chief_dispatcher.rejected"]
        assert rejected == []
        assert esc.calls == []

    async def test_budget_check_exception_fails_open(self, tmp_path):
        """A raising BudgetGuard.check() must NOT halt dispatch."""
        from unittest import mock
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.chief_session import ChiefSessionState
        from bridge.chief_session_store import InMemoryChiefSessionStore
        from bridge.event_bus import EventBus
        from bridge.warm_chief import WarmChief
        from bridge.work_order import WorkOrder
        from bridge.work_order_router import (
            RoutingDecision,
            WorkOrderRouter,
        )
        from teams._types import AgentSpec, DepartmentConfig, TeamResult

        class _ExplodingBudget:
            async def check(self_inner):
                raise RuntimeError("sqlite gone")

        class _StaticRouter(WorkOrderRouter):
            async def route(self_inner, wo):
                return RoutingDecision(
                    department="qa", rationale="t", confidence=1.0,
                )

        class _FakeRegistry:
            def get_config(self_inner, name):
                return DepartmentConfig(
                    name="qa", zone=4, description="QA",
                    manager=AgentSpec(name="qa-chief", model="sonnet"),
                    employees=(),
                )

        dispatcher = ChiefDispatcher(
            router=_StaticRouter(),
            session_store=InMemoryChiefSessionStore(),
            dept_registry=_FakeRegistry(),
            event_bus=EventBus(data_dir=tmp_path),
            budget_guard=_ExplodingBudget(),
        )
        wo = WorkOrder.create(intent="run qa", skill="test",
                              project="test-project")

        async def _fake_run_chief(self_inner):
            return TeamResult(
                department="qa", manager_output="ok", success=True,
            )

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps=object())
        # Dispatch proceeded despite the budget check raising.
        assert session.state == ChiefSessionState.AWAITING_EVALUATION

    async def test_no_budget_guard_preserves_legacy_dispatch(self, tmp_path):
        """budget_guard=None (the default) MUST keep existing dispatchers
        working with no behavior change.
        """
        from unittest import mock
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.chief_session import ChiefSessionState
        from bridge.chief_session_store import InMemoryChiefSessionStore
        from bridge.event_bus import EventBus
        from bridge.warm_chief import WarmChief
        from bridge.work_order import WorkOrder
        from bridge.work_order_router import (
            RoutingDecision,
            WorkOrderRouter,
        )
        from teams._types import AgentSpec, DepartmentConfig, TeamResult

        class _StaticRouter(WorkOrderRouter):
            async def route(self_inner, wo):
                return RoutingDecision(
                    department="qa", rationale="t", confidence=1.0,
                )

        class _FakeRegistry:
            def get_config(self_inner, name):
                return DepartmentConfig(
                    name="qa", zone=4, description="QA",
                    manager=AgentSpec(name="qa-chief", model="sonnet"),
                    employees=(),
                )

        dispatcher = ChiefDispatcher(
            router=_StaticRouter(),
            session_store=InMemoryChiefSessionStore(),
            dept_registry=_FakeRegistry(),
            event_bus=EventBus(data_dir=tmp_path),
        )
        wo = WorkOrder.create(intent="run qa", skill="test",
                              project="test-project")

        async def _fake_run_chief(self_inner):
            return TeamResult(
                department="qa", manager_output="ok", success=True,
            )

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps=object())
        assert session.state == ChiefSessionState.AWAITING_EVALUATION


class TestP34TeamSideMidRunCap:
    """``DepartmentTeam.run`` flips success=False on COST_CAP_EXCEEDED."""

    def test_under_cap_passes_through(self):
        """Under-cap is a pure passthrough — no mutation of TeamResult.

        Cost attribution stays on the existing D2.5 ``cost_tracker.record``
        path; this helper is a kill-switch, not an accountant.
        """
        from teams._team import _enforce_team_cost_cap
        from teams._types import (
            AgentSpec, Constraints, DepartmentConfig, TeamResult,
        )

        config = DepartmentConfig(
            name="qa", zone=4, description="QA",
            manager=AgentSpec(name="qa-chief", model="sonnet"),
            employees=(),
            constraints=Constraints(cost_limit_usd=10.0),
        )
        result = TeamResult(
            department="qa", manager_output="ok", success=True,
            total_tokens=1000,  # ~ tiny cost under cap
        )
        enforced = _enforce_team_cost_cap(result, config)
        assert enforced.success is True
        # Pure passthrough — cost field is not written under-cap so
        # existing test_z4_load expectations hold under TestModel.
        assert enforced.total_cost_usd == result.total_cost_usd
        # Error string untouched.
        assert enforced.error is None

    def test_over_cap_flips_success_and_records_error(self):
        from teams._team import _enforce_team_cost_cap
        from teams._types import (
            AgentSpec, Constraints, DepartmentConfig, TeamResult,
        )

        config = DepartmentConfig(
            name="qa", zone=4, description="QA",
            manager=AgentSpec(name="qa-chief", model="opus"),
            employees=(),
            # Tiny cap that token×opus pricing easily blows past.
            constraints=Constraints(cost_limit_usd=0.0001),
        )
        result = TeamResult(
            department="qa", manager_output="ok", success=True,
            total_tokens=100_000,
        )
        enforced = _enforce_team_cost_cap(result, config)
        assert enforced.success is False
        assert enforced.error is not None
        assert "COST_CAP_EXCEEDED" in enforced.error
        # Cost attribution populated with the breach value.
        assert enforced.total_cost_usd > 0.0001

    def test_no_cap_means_no_kill(self):
        from teams._team import _enforce_team_cost_cap
        from teams._types import (
            AgentSpec, Constraints, DepartmentConfig, TeamResult,
        )

        config = DepartmentConfig(
            name="qa", zone=4, description="QA",
            manager=AgentSpec(name="qa-chief", model="opus"),
            employees=(),
            constraints=Constraints(cost_limit_usd=0.0),  # cap disabled
        )
        result = TeamResult(
            department="qa", manager_output="ok", success=True,
            total_tokens=1_000_000,
        )
        enforced = _enforce_team_cost_cap(result, config)
        assert enforced.success is True
        assert enforced.error is None

    def test_existing_error_is_preserved_and_prefixed(self):
        """A gate-violator that ALSO busts the cap surfaces both errors."""
        from teams._team import _enforce_team_cost_cap
        from teams._types import (
            AgentSpec, Constraints, DepartmentConfig, TeamResult,
        )

        config = DepartmentConfig(
            name="qa", zone=4, description="QA",
            manager=AgentSpec(name="qa-chief", model="opus"),
            employees=(),
            constraints=Constraints(cost_limit_usd=0.0001),
        )
        result = TeamResult(
            department="qa", manager_output="ok", success=False,
            error="gate violation: synthesis missing",
            total_tokens=100_000,
        )
        enforced = _enforce_team_cost_cap(result, config)
        assert enforced.success is False
        assert "COST_CAP_EXCEEDED" in enforced.error
        assert "gate violation: synthesis missing" in enforced.error


class TestP34PerDelegationCap:
    """``delegate()`` refuses further work once cap exceeded."""

    def test_sum_delegation_cost_aggregates_tokens(self):
        from teams._factory import _sum_delegation_cost_usd
        from teams._types import EmployeeResult

        collector = [
            EmployeeResult(
                employee_name="qa-engineer", output="x", success=True,
                tokens_used=50_000,
            ),
            EmployeeResult(
                employee_name="qa-engineer", output="x", success=True,
                tokens_used=50_000,
            ),
        ]
        usd = _sum_delegation_cost_usd(collector, manager_model="opus")
        # Sum > 0 — exact value depends on PRICING which we don't pin here.
        assert usd > 0

    def test_empty_collector_returns_zero(self):
        from teams._factory import _sum_delegation_cost_usd

        assert _sum_delegation_cost_usd([], manager_model="opus") == 0.0

    def test_unknown_model_falls_back_to_sonnet_pricing(self):
        """``estimate_cost`` defaults to sonnet pricing on unknown models —
        the helper inherits that behavior. The point of the test is that
        an unknown model name does not raise.
        """
        from teams._factory import _sum_delegation_cost_usd
        from teams._types import EmployeeResult

        collector = [
            EmployeeResult(
                employee_name="qa-engineer", output="x", success=True,
                tokens_used=10_000,
            ),
        ]
        # ``estimate_cost`` accepts any model string; unknown maps to sonnet.
        assert _sum_delegation_cost_usd(collector, manager_model="unknown") > 0
