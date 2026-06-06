"""Tests for D7.12 #1424 (slice 1) — proactive_scheduler.

Surface tested:
- should_skip_tick — skip-reason precedence (operator > halt > budget)
- select_next_work_item — safe-label gating, prereq-closure, leaf-preference
- ledger I/O — append + read-window + summarize
- ProactiveScheduler.tick_once — full pipeline (skip / pick / dispatch)
- dry_run=True never dispatches even when callback wired
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bridge.proactive_scheduler import (
    SKIP_BUDGET_PRESSURE,
    SKIP_HALTED,
    SKIP_NO_CANDIDATES,
    SKIP_NO_GRAPH,
    SKIP_OPERATOR_DIALOGUE,
    AutonomousPlanDrafter,
    ProactiveScheduler,
    ProactiveTickReport,
    WorkItem,
    append_to_ledger,
    load_closed_issue_cache,
    load_graph,
    make_drafter_callback,
    read_ledger_window,
    refresh_closed_issue_cache,
    render_weekly_digest_section,
    select_next_work_item,
    should_render_weekly_digest,
    should_skip_tick,
    summarize_ledger_for_status,
    upsert_weekly_digest,
)


# ---------------------------------------------------------------------------
# Skip precedence
# ---------------------------------------------------------------------------


class TestShouldSkipTick:
    @pytest.mark.asyncio
    async def test_clean_state_returns_none(self):
        result = await should_skip_tick(
            inbox_pending_count=0,
            daily_spend_fraction=0.1,
            budget_threshold=0.75,
            halt_flag_present=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_inbox_wins_over_everything(self):
        """Operator dialogue is the highest-priority skip — operator messages
        always pre-empt autonomous decisions (D7.9 doctrine).
        """
        result = await should_skip_tick(
            inbox_pending_count=1,
            daily_spend_fraction=0.99,
            budget_threshold=0.75,
            halt_flag_present=True,
        )
        assert result == SKIP_OPERATOR_DIALOGUE

    @pytest.mark.asyncio
    async def test_halt_wins_over_budget(self):
        result = await should_skip_tick(
            inbox_pending_count=0,
            daily_spend_fraction=0.99,
            budget_threshold=0.75,
            halt_flag_present=True,
        )
        assert result == SKIP_HALTED

    @pytest.mark.asyncio
    async def test_budget_pressure_at_threshold(self):
        result = await should_skip_tick(
            inbox_pending_count=0,
            daily_spend_fraction=0.75,
            budget_threshold=0.75,
            halt_flag_present=False,
        )
        assert result == SKIP_BUDGET_PRESSURE

    @pytest.mark.asyncio
    async def test_budget_under_threshold_proceeds(self):
        result = await should_skip_tick(
            inbox_pending_count=0,
            daily_spend_fraction=0.50,
            budget_threshold=0.75,
            halt_flag_present=False,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Work selection
# ---------------------------------------------------------------------------


def _node(number: int, labels: list[str], title: str = "stub") -> dict:
    return {
        "number": number,
        "title": title,
        "labels": labels,
        "slug": None,
    }


class TestSelectNextWorkItem:
    def test_no_nodes_returns_none(self):
        graph = {"nodes": [], "edges": []}
        assert select_next_work_item(graph) is None

    def test_only_risky_labels_returns_none(self):
        graph = {
            "nodes": [
                _node(1, ["severity:critical", "size/S"]),
                _node(2, ["priority:keystone", "operator-friction"]),
                _node(3, ["exec:operator", "size/XS"]),
            ],
            "edges": [],
        }
        assert select_next_work_item(graph) is None

    def test_picks_safe_node_with_no_prereqs(self):
        graph = {
            "nodes": [
                _node(1, ["operator-friction", "size/S"], title="ready"),
                _node(2, ["severity:critical", "size/S"], title="risky"),
            ],
            "edges": [],
        }
        item = select_next_work_item(graph)
        assert item is not None
        assert item.number == 1
        assert item.title == "ready"

    def test_skips_node_with_unclosed_prereq(self):
        graph = {
            "nodes": [
                _node(1, ["operator-friction", "size/S"]),
                _node(2, ["operator-friction", "size/XS"]),
            ],
            "edges": [
                {"from": 99, "to": 2, "kind": "prereq"},  # 99 not closed
            ],
        }
        item = select_next_work_item(graph, closed_issues=[])
        assert item is not None
        assert item.number == 1  # 2 has unclosed prereq, 1 has none

    def test_picks_node_when_prereq_closed(self):
        graph = {
            "nodes": [
                _node(2, ["operator-friction", "size/XS"], title="downstream"),
            ],
            "edges": [
                {"from": 99, "to": 2, "kind": "prereq"},
            ],
        }
        item = select_next_work_item(graph, closed_issues=[99])
        assert item is not None
        assert item.number == 2
        assert item.prereq_numbers == (99,)

    def test_skip_numbers_excludes_picked(self):
        """The recently_picked dedup set keeps the same item from being
        re-picked on the next tick.
        """
        graph = {
            "nodes": [
                _node(1, ["operator-friction", "size/S"], title="first"),
                _node(2, ["operator-friction", "size/S"], title="second"),
            ],
            "edges": [],
        }
        item = select_next_work_item(graph, skip_numbers=[1])
        assert item is not None
        assert item.number == 2

    def test_prefers_fewer_prereqs_then_lower_number(self):
        """Tie-break is fewest prereqs first, then lower issue number."""
        graph = {
            "nodes": [
                _node(10, ["operator-friction", "size/S"]),
                _node(20, ["operator-friction", "size/S"]),
            ],
            "edges": [
                {"from": 100, "to": 10, "kind": "prereq"},
                # 20 has no prereqs → wins
            ],
        }
        item = select_next_work_item(graph, closed_issues=[100])
        assert item is not None
        assert item.number == 20

    def test_safe_label_required(self):
        """Sprints with no risky labels but also no safe labels are NOT
        candidates — slice 1 is conservative and only surfaces explicitly
        safe-tagged work.
        """
        graph = {
            "nodes": [_node(1, ["random-label", "another"])],
            "edges": [],
        }
        assert select_next_work_item(graph) is None


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------


class TestLedger:
    def test_append_and_read(self, tmp_path: Path):
        ledger = tmp_path / "ledger.jsonl"
        report = ProactiveTickReport(
            action="picked",
            work_item=WorkItem(
                number=42,
                title="test",
                labels=("operator-friction", "size/S"),
                slug="D7.99",
                prereq_numbers=(),
            ),
            reason="dry_run",
            timestamp=1000.0,
        )
        append_to_ledger(ledger, report)
        rows = read_ledger_window(ledger, since_ts=0)
        assert len(rows) == 1
        assert rows[0]["action"] == "picked"
        assert rows[0]["work_item"]["number"] == 42

    def test_read_window_filters_old_rows(self, tmp_path: Path):
        ledger = tmp_path / "ledger.jsonl"
        for ts, action in [(100.0, "skipped"), (500.0, "picked"), (900.0, "picked")]:
            append_to_ledger(
                ledger,
                ProactiveTickReport(
                    action=action,
                    work_item=None,
                    reason="x",
                    timestamp=ts,
                ),
            )
        rows = read_ledger_window(ledger, since_ts=400)
        assert len(rows) == 2
        assert rows[0]["action"] == "picked"
        assert rows[1]["action"] == "picked"

    def test_missing_ledger_returns_empty(self, tmp_path: Path):
        rows = read_ledger_window(tmp_path / "nope.jsonl", since_ts=0)
        assert rows == []

    def test_summarize_rolls_up_action_counts(self, tmp_path: Path):
        ledger = tmp_path / "ledger.jsonl"
        items = [
            ("skipped", SKIP_OPERATOR_DIALOGUE, None),
            ("skipped", SKIP_BUDGET_PRESSURE, None),
            ("skipped", SKIP_OPERATOR_DIALOGUE, None),
            (
                "picked",
                "dry_run",
                WorkItem(7, "first", (), None, ()),
            ),
            (
                "picked",
                "dry_run",
                WorkItem(9, "second", (), None, ()),
            ),
        ]
        for action, reason, wi in items:
            append_to_ledger(
                ledger,
                ProactiveTickReport(
                    action=action, work_item=wi, reason=reason
                ),
            )
        rows = read_ledger_window(ledger, since_ts=0)
        summary = summarize_ledger_for_status(rows)
        assert summary["total_ticks"] == 5
        assert summary["by_action"] == {"skipped": 3, "picked": 2}
        assert summary["by_skip_reason"] == {
            SKIP_OPERATOR_DIALOGUE: 2,
            SKIP_BUDGET_PRESSURE: 1,
        }
        assert len(summary["last_picks"]) == 2
        assert summary["last_picks"][-1]["number"] == 9


# ---------------------------------------------------------------------------
# load_graph
# ---------------------------------------------------------------------------


class TestLoadGraph:
    def test_missing_file_returns_none(self, tmp_path: Path):
        assert load_graph(tmp_path / "nope.json") is None

    def test_malformed_json_returns_none(self, tmp_path: Path):
        bad = tmp_path / "graph.json"
        bad.write_text("{not valid json", encoding="utf-8")
        assert load_graph(bad) is None

    def test_valid_json_loads(self, tmp_path: Path):
        good = tmp_path / "graph.json"
        good.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
        graph = load_graph(good)
        assert graph == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# Scheduler — tick_once integration
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_path(tmp_path: Path) -> Path:
    """A minimal dep-graph file with one safe leaf node."""
    p = tmp_path / "graph.json"
    p.write_text(
        json.dumps({
            "nodes": [
                _node(1, ["operator-friction", "size/S"], title="ready-leaf"),
            ],
            "edges": [],
        }),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "ledger.jsonl"


class TestSchedulerTickOnce:
    @pytest.mark.asyncio
    async def test_skips_when_inbox_has_pending(self, graph_path, ledger_path):
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            get_inbox_pending_count=lambda: 1,
        )
        report = await scheduler.tick_once()
        assert report.action == "skipped"
        assert report.reason == SKIP_OPERATOR_DIALOGUE

    @pytest.mark.asyncio
    async def test_refreshes_inbox_pending_count_before_skip_decision(
        self, graph_path, ledger_path
    ):
        events: list[tuple[str, int]] = []
        pending = {"count": 0}

        def _pending_count() -> int:
            events.append(("read", pending["count"]))
            return pending["count"]

        async def _refresh_pending_count() -> int:
            events.append(("refresh", pending["count"]))
            pending["count"] = 1
            return pending["count"]

        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            get_inbox_pending_count=_pending_count,
        )
        scheduler.set_inbox_pending_refresh(_refresh_pending_count)

        report = await scheduler.tick_once()

        assert report.action == "skipped"
        assert report.reason == SKIP_OPERATOR_DIALOGUE
        assert events == [("refresh", 0), ("read", 1)]

    @pytest.mark.asyncio
    async def test_skips_when_budget_pressure(self, graph_path, ledger_path):
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            budget_threshold=0.5,
            get_daily_spend_fraction=lambda: 0.6,
        )
        report = await scheduler.tick_once()
        assert report.action == "skipped"
        assert report.reason == SKIP_BUDGET_PRESSURE

    @pytest.mark.asyncio
    async def test_skips_when_halted(self, graph_path, ledger_path):
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            get_halt_flag_present=lambda: True,
        )
        report = await scheduler.tick_once()
        assert report.action == "skipped"
        assert report.reason == SKIP_HALTED

    @pytest.mark.asyncio
    async def test_skips_when_graph_missing(self, tmp_path, ledger_path):
        scheduler = ProactiveScheduler(
            graph_path=tmp_path / "nope.json",
            ledger_path=ledger_path,
        )
        report = await scheduler.tick_once()
        assert report.action == "skipped"
        assert report.reason == SKIP_NO_GRAPH

    @pytest.mark.asyncio
    async def test_skips_when_no_eligible_candidates(self, tmp_path, ledger_path):
        graph = tmp_path / "graph.json"
        graph.write_text(
            json.dumps({
                "nodes": [_node(1, ["severity:critical", "size/S"])],
                "edges": [],
            }),
            encoding="utf-8",
        )
        scheduler = ProactiveScheduler(
            graph_path=graph,
            ledger_path=ledger_path,
        )
        report = await scheduler.tick_once()
        assert report.action == "skipped"
        assert report.reason == SKIP_NO_CANDIDATES

    @pytest.mark.asyncio
    async def test_picks_in_dry_run(self, graph_path, ledger_path):
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            dry_run=True,
        )
        report = await scheduler.tick_once()
        assert report.action == "picked"
        assert report.reason == "dry_run"
        assert report.work_item is not None
        assert report.work_item.number == 1

    @pytest.mark.asyncio
    async def test_dry_run_does_not_dispatch(self, graph_path, ledger_path):
        """Even with a dispatch_callback wired, dry_run=True must NOT call it.
        Slice 1 acceptance — observability without action.
        """
        dispatched: list = []

        async def _capture(item):
            dispatched.append(item)

        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            dry_run=True,
            dispatch_callback=_capture,
        )
        report = await scheduler.tick_once()
        assert report.action == "picked"
        assert dispatched == [], (
            f"dry_run should never dispatch; got {dispatched}"
        )

    @pytest.mark.asyncio
    async def test_dispatches_when_dry_run_off_and_callback_wired(
        self, graph_path, ledger_path
    ):
        """Slice 2 acceptance check — when dry_run=False AND callback is
        wired, the picked item is dispatched.
        """
        dispatched: list = []

        async def _capture(item):
            dispatched.append(item)

        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            dry_run=False,
            dispatch_callback=_capture,
        )
        report = await scheduler.tick_once()
        assert report.action == "dispatched"
        assert len(dispatched) == 1
        assert dispatched[0].number == 1

    # ── Sprint #1614 — wiring-discipline acceptance ───────────────────────

    @pytest.mark.asyncio
    async def test_dispatch_without_setter_raises_wiring_missing_error(self):
        """Sprint #1614 AC: calling ProactiveScheduler.dispatch(...) without
        the setter being called must raise WiringMissingError, not silently
        no-op.

        The whole point of the setter discipline is that silent no-op leaves
        the operator with no signal that the dispatch surface is unwired —
        this test pins the contract.
        """
        from bridge.wiring import WiringMissingError

        scheduler = ProactiveScheduler(
            graph_path=Path("/nonexistent.json"),
            ledger_path=Path("/tmp/_unused.jsonl"),
        )
        item = WorkItem(
            number=99, title="t", labels=("size/S",), slug=None,
            prereq_numbers=(),
        )
        with pytest.raises(WiringMissingError):
            await scheduler.dispatch(item)

    @pytest.mark.asyncio
    async def test_set_dispatch_registers_callback(self):
        """Sprint #1614: set_dispatch is the canonical wire-up for the
        dispatch callback. After set_dispatch, dispatch() invokes the
        callback rather than raising.
        """
        scheduler = ProactiveScheduler(
            graph_path=Path("/nonexistent.json"),
            ledger_path=Path("/tmp/_unused.jsonl"),
        )
        captured: list = []

        async def _cb(item):
            captured.append(item.number)
            return "ok"

        scheduler.set_dispatch(_cb)
        item = WorkItem(
            number=42, title="t", labels=("size/S",), slug=None,
            prereq_numbers=(),
        )
        result = await scheduler.dispatch(item)
        assert captured == [42]
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_set_dispatch_none_clears_callback(self):
        """Sprint #1614: passing None to set_dispatch clears a previously-
        registered callback. dispatch() then raises again.
        """
        from bridge.wiring import WiringMissingError

        scheduler = ProactiveScheduler(
            graph_path=Path("/nonexistent.json"),
            ledger_path=Path("/tmp/_unused.jsonl"),
        )

        async def _cb(item):
            return None

        scheduler.set_dispatch(_cb)
        scheduler.set_dispatch(None)
        item = WorkItem(
            number=1, title="t", labels=("size/S",), slug=None,
            prereq_numbers=(),
        )
        with pytest.raises(WiringMissingError):
            await scheduler.dispatch(item)

    @pytest.mark.asyncio
    async def test_tick_once_records_dispatch_error_when_no_setter_called(
        self, graph_path, ledger_path
    ):
        """Sprint #1614: when dry_run=False and no setter was called, the
        scheduler loop reaches dispatch(), catches WiringMissingError, and
        records ``dispatch_error: WiringMissingError(...)`` in the ledger.
        The loop must NOT crash.
        """
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            dry_run=False,
            # No dispatch_callback, no set_dispatch — fully unwired.
        )
        report = await scheduler.tick_once()
        assert report.action == "skipped"
        assert report.reason.startswith("dispatch_error:")
        # The reason serializes the exception's message, which names the
        # missing setter. The class name itself isn't in ``str(exc)`` for a
        # RuntimeError subclass — but the message is unambiguous.
        assert "set_dispatch" in report.reason

    @pytest.mark.asyncio
    async def test_recently_picked_dedupe_within_session(
        self, graph_path, ledger_path
    ):
        """The same work item should not be picked twice in one process."""
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
        )
        first = await scheduler.tick_once()
        second = await scheduler.tick_once()
        assert first.action == "picked"
        # Second tick has nothing left (only one safe leaf in the graph)
        assert second.action == "skipped"
        assert second.reason == SKIP_NO_CANDIDATES

    @pytest.mark.asyncio
    async def test_ledger_grows_one_row_per_tick(
        self, graph_path, ledger_path
    ):
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
        )
        await scheduler.tick_once()
        await scheduler.tick_once()
        rows = read_ledger_window(ledger_path, since_ts=0)
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# D7.12 slice 2 — closed-issue cache
# ---------------------------------------------------------------------------


class TestClosedIssueCache:
    def test_missing_cache_returns_empty_set(self, tmp_path: Path):
        assert load_closed_issue_cache(tmp_path / "nope.json") == set()

    def test_malformed_cache_returns_empty_set(self, tmp_path: Path):
        bad = tmp_path / "cache.json"
        bad.write_text("{not json", encoding="utf-8")
        assert load_closed_issue_cache(bad) == set()

    def test_valid_cache_loads(self, tmp_path: Path):
        good = tmp_path / "cache.json"
        good.write_text(
            json.dumps({"refreshed_at": 1.0, "issue_numbers": [1, 2, 3]}),
            encoding="utf-8",
        )
        assert load_closed_issue_cache(good) == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_refresh_writes_cache_when_missing(self, tmp_path: Path):
        cache = tmp_path / "cache.json"

        def _fake_fetch():
            return [10, 20, 30]

        result = await refresh_closed_issue_cache(cache, fetch_fn=_fake_fetch)
        assert result == {10, 20, 30}
        assert cache.exists()
        # Cache content matches
        assert load_closed_issue_cache(cache) == {10, 20, 30}

    @pytest.mark.asyncio
    async def test_refresh_skips_when_cache_fresh(self, tmp_path: Path):
        """Cache younger than ttl_seconds is not re-fetched."""
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps({"refreshed_at": 0.0, "issue_numbers": [99]}),
            encoding="utf-8",
        )

        called: list = []

        def _fake_fetch():
            called.append(1)
            return [1, 2, 3]

        result = await refresh_closed_issue_cache(
            cache, ttl_seconds=10_000, fetch_fn=_fake_fetch
        )
        # Cache is fresh — no fetch
        assert called == []
        # Returns existing cache content
        assert result == {99}

    @pytest.mark.asyncio
    async def test_refresh_returns_existing_on_fetch_failure(
        self, tmp_path: Path
    ):
        """Fetch failure falls back to whatever's already cached — never
        crashes the scheduler.
        """
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps({"refreshed_at": 0.0, "issue_numbers": [42]}),
            encoding="utf-8",
        )

        def _fake_fetch():
            raise RuntimeError("network down")

        result = await refresh_closed_issue_cache(
            cache, ttl_seconds=0, fetch_fn=_fake_fetch
        )
        assert result == {42}


# ---------------------------------------------------------------------------
# D7.12 slice 2 — AutonomousPlanDrafter + dispatch wiring
# ---------------------------------------------------------------------------


class _FakeRunner:
    """Minimal duck-type for ClaudeRunner used by AutonomousPlanDrafter."""
    def __init__(self, *, response_text: str = "", is_error: bool = False, raise_exc: Exception | None = None):
        self._response = response_text
        self._is_error = is_error
        self._raise = raise_exc
        self.calls: list[dict] = []

    async def invoke(self, *, message: str, model: str = "haiku"):
        self.calls.append({"message": message, "model": model})
        if self._raise is not None:
            raise self._raise

        class _R:
            pass
        r = _R()
        r.response_text = self._response
        r.is_error = self._is_error
        r.error_type = "fake_error" if self._is_error else ""
        return r


class TestAutonomousPlanDrafter:
    @pytest.mark.asyncio
    async def test_returns_failure_when_runner_raises(self, monkeypatch):
        runner = _FakeRunner(raise_exc=RuntimeError("boom"))
        drafter = AutonomousPlanDrafter(runner=runner)
        item = WorkItem(1, "Test sprint", ("size/S",), "D7.99", ())
        result = await drafter(item)
        assert result.posted is False
        assert "invoke_failed" in (result.error or "")

    @pytest.mark.asyncio
    async def test_returns_failure_when_runner_errors(self):
        runner = _FakeRunner(is_error=True)
        drafter = AutonomousPlanDrafter(runner=runner)
        item = WorkItem(1, "Test sprint", ("size/S",), "D7.99", ())
        result = await drafter(item)
        assert result.posted is False
        assert "invoke_returned_error" in (result.error or "")

    @pytest.mark.asyncio
    async def test_returns_failure_on_empty_plan_text(self):
        runner = _FakeRunner(response_text="   \n  ")
        drafter = AutonomousPlanDrafter(runner=runner)
        item = WorkItem(1, "Test", ("size/S",), None, ())
        result = await drafter(item)
        assert result.posted is False
        assert result.error == "empty_plan_text"

    @pytest.mark.asyncio
    async def test_posts_with_marker_prefix_on_success(self, monkeypatch):
        """The drafter calls `gh issue comment <N> --body <body>` with the
        `[autonomous]` marker prefix. We patch the executor-call to capture
        the args without running gh.
        """
        runner = _FakeRunner(
            response_text="- Step 1\n- Step 2\n- Step 3",
        )
        drafter = AutonomousPlanDrafter(runner=runner, gh_binary="gh-fake")
        item = WorkItem(99, "Mock sprint", ("size/S",), "D7.99", ())

        captured: dict = {}

        # Patch the internal executor — replace _post_comment so we don't
        # actually shell out.
        async def _fake_post(self, issue_number, body):
            captured["number"] = issue_number
            captured["body"] = body
            return True

        monkeypatch.setattr(
            AutonomousPlanDrafter, "_post_comment", _fake_post
        )

        result = await drafter(item)
        assert result.posted is True
        assert result.error is None
        assert captured["number"] == 99
        assert captured["body"].startswith("[autonomous]")
        assert "- Step 1" in captured["body"]
        assert "- Step 2" in captured["body"]
        assert "- Step 3" in captured["body"]

    @pytest.mark.asyncio
    async def test_marker_can_be_overridden(self, monkeypatch):
        runner = _FakeRunner(response_text="- a\n- b\n- c")
        drafter = AutonomousPlanDrafter(
            runner=runner, autonomous_marker="[BUMBA-AUTO]"
        )

        async def _fake_post(self, issue_number, body):
            return True

        monkeypatch.setattr(
            AutonomousPlanDrafter, "_post_comment", _fake_post
        )

        item = WorkItem(1, "T", (), None, ())
        result = await drafter(item)
        assert result.comment_text.startswith("[BUMBA-AUTO]")


class TestDrafterCallbackIntegration:
    @pytest.mark.asyncio
    async def test_callback_succeeds_records_dispatched(
        self, graph_path, ledger_path, monkeypatch
    ):
        """When the drafter callback succeeds, the scheduler logs
        action='dispatched' to the ledger.
        """
        runner = _FakeRunner(response_text="- a\n- b\n- c")
        drafter = AutonomousPlanDrafter(runner=runner)

        async def _fake_post(self, issue_number, body):
            return True

        monkeypatch.setattr(
            AutonomousPlanDrafter, "_post_comment", _fake_post
        )

        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            dry_run=False,
            dispatch_callback=make_drafter_callback(drafter),
        )
        report = await scheduler.tick_once()
        assert report.action == "dispatched"

    @pytest.mark.asyncio
    async def test_callback_failure_records_dispatch_error(
        self, graph_path, ledger_path, monkeypatch
    ):
        """When the drafter returns posted=False, the wrapper raises so the
        scheduler captures `dispatch_error: ...` in the ledger.
        """
        runner = _FakeRunner(response_text="- a\n- b\n- c")
        drafter = AutonomousPlanDrafter(runner=runner)

        async def _fake_post(self, issue_number, body):
            return False  # gh fails

        monkeypatch.setattr(
            AutonomousPlanDrafter, "_post_comment", _fake_post
        )

        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            dry_run=False,
            dispatch_callback=make_drafter_callback(drafter),
        )
        report = await scheduler.tick_once()
        # The scheduler's own exception path catches the RuntimeError raised
        # by make_drafter_callback wrapper and records as a skip with
        # dispatch_error reason.
        assert report.action == "skipped"
        assert "dispatch_error" in report.reason
        assert "plan_drafter_failed" in report.reason

    @pytest.mark.asyncio
    async def test_dry_run_blocks_dispatch_even_with_callback(
        self, graph_path, ledger_path, monkeypatch
    ):
        """Slice-1 contract preserved: dry_run=True never dispatches."""
        runner = _FakeRunner(response_text="- a\n- b\n- c")
        drafter = AutonomousPlanDrafter(runner=runner)
        called: list = []

        async def _fake_post(self, issue_number, body):
            called.append(1)
            return True

        monkeypatch.setattr(
            AutonomousPlanDrafter, "_post_comment", _fake_post
        )

        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            dry_run=True,  # ← the slice-1 safety
            dispatch_callback=make_drafter_callback(drafter),
        )
        report = await scheduler.tick_once()
        assert report.action == "picked"
        # The drafter's gh_post must never have been reached
        assert called == []


# ---------------------------------------------------------------------------
# D7.12 slice 3 — weekly digest
# ---------------------------------------------------------------------------


class TestWeeklyDigestRender:
    def test_section_includes_required_lines(self):
        rows = [
            {
                "ts": 1.0,
                "iso_ts": "2026-05-04T00:00:00",
                "action": "skipped",
                "reason": "operator_dialogue_active",
            },
            {
                "ts": 2.0,
                "iso_ts": "2026-05-05T00:00:00",
                "action": "picked",
                "reason": "dry_run",
                "work_item": {
                    "number": 42,
                    "title": "test sprint title",
                    "slug": "D7.99",
                    "prereq_count": 0,
                },
            },
        ]
        section = render_weekly_digest_section(
            iso_year=2026, iso_week=19, rows=rows, dispatch_active=False
        )
        assert "## Week of " in section
        assert "(week 19)" in section
        assert "Ticks: 2" in section
        assert "skipped: 1" in section
        assert "picked: 1" in section
        assert "Skip reasons:" in section
        assert "operator_dialogue_active=1" in section
        assert "Picks (last 5):" in section
        assert "#42" in section
        assert "test sprint title" in section
        # Footer note
        assert "dispatch was off this week" in section

    def test_section_notes_dispatch_active_but_zero_dispatched(self):
        rows = [
            {
                "ts": 1.0, "iso_ts": "2026-05-05T00:00:00",
                "action": "skipped", "reason": "no_eligible_work_items",
            },
        ]
        section = render_weekly_digest_section(
            iso_year=2026, iso_week=19, rows=rows, dispatch_active=True
        )
        assert "dispatch enabled but nothing was posted" in section

    def test_empty_week_renders_no_picks(self):
        section = render_weekly_digest_section(
            iso_year=2026, iso_week=19, rows=[], dispatch_active=False
        )
        assert "Picks: none this week" in section
        assert "Ticks: 0" in section


class TestUpsertWeeklyDigest:
    def test_creates_digest_file_when_missing(self, tmp_path: Path):
        digest = tmp_path / "weekly-digest.md"
        rows = [
            {"ts": 1.0, "iso_ts": "2026-05-04T00:00:00",
             "action": "picked", "reason": "dry_run",
             "work_item": {"number": 1, "title": "x", "slug": None, "prereq_count": 0}},
        ]
        upsert_weekly_digest(
            digest, iso_year=2026, iso_week=19,
            rows=rows, dispatch_active=False,
        )
        assert digest.exists()
        text = digest.read_text(encoding="utf-8")
        assert text.startswith("# Proactive Scheduler — Weekly Digest")
        assert "## Week of " in text
        assert "#1" in text

    def test_upsert_replaces_existing_week_section(self, tmp_path: Path):
        digest = tmp_path / "weekly-digest.md"
        # First render
        upsert_weekly_digest(
            digest, iso_year=2026, iso_week=19,
            rows=[], dispatch_active=False,
        )
        first_pass = digest.read_text(encoding="utf-8")
        assert "Picks: none this week" in first_pass

        # Re-render with different rows for the SAME week
        rows = [
            {"ts": 1.0, "iso_ts": "2026-05-04T00:00:00",
             "action": "picked", "reason": "dry_run",
             "work_item": {"number": 99, "title": "later pick", "slug": None, "prereq_count": 0}},
        ]
        upsert_weekly_digest(
            digest, iso_year=2026, iso_week=19,
            rows=rows, dispatch_active=False,
        )
        second_pass = digest.read_text(encoding="utf-8")
        # Old content gone
        assert "Picks: none this week" not in second_pass
        # New content present
        assert "#99" in second_pass
        assert "later pick" in second_pass
        # Section header still appears exactly once
        assert second_pass.count("(week 19)") == 1

    def test_upsert_inserts_new_week_above_existing(self, tmp_path: Path):
        digest = tmp_path / "weekly-digest.md"
        # Plant week 18
        upsert_weekly_digest(
            digest, iso_year=2026, iso_week=18,
            rows=[], dispatch_active=False,
        )
        # Then week 19
        upsert_weekly_digest(
            digest, iso_year=2026, iso_week=19,
            rows=[], dispatch_active=False,
        )
        text = digest.read_text(encoding="utf-8")
        # Both sections present
        assert "(week 18)" in text
        assert "(week 19)" in text
        # Newer week (19) appears ABOVE older week (18)
        assert text.index("(week 19)") < text.index("(week 18)")


class TestShouldRenderWeeklyDigest:
    def test_first_render_fires(self):
        """No prior render → fire on first tick."""
        assert should_render_weekly_digest(
            now_ts=time.time(), last_render_ts=None
        ) is True

    def test_same_week_does_not_fire(self):
        """Two ticks in the same ISO week → only one render."""
        # Use a known-Wednesday
        ts = datetime(2026, 5, 6, tzinfo=timezone.utc).timestamp()
        # 30 minutes later, same week
        later = ts + 1800
        assert should_render_weekly_digest(
            now_ts=later, last_render_ts=ts
        ) is False

    def test_crosses_iso_week_fires(self):
        """A tick after the next Monday → fire."""
        last = datetime(2026, 5, 4, tzinfo=timezone.utc).timestamp()
        # Following Monday (week 20) — boundary crossed
        now = datetime(2026, 5, 11, tzinfo=timezone.utc).timestamp()
        assert should_render_weekly_digest(
            now_ts=now, last_render_ts=last
        ) is True


class TestSchedulerDigestIntegration:
    @pytest.mark.asyncio
    async def test_tick_renders_digest_on_first_tick(
        self, graph_path, ledger_path, tmp_path
    ):
        """When digest_path is set, the FIRST tick renders the previous
        week's digest before producing this tick's ledger row.
        """
        digest = tmp_path / "weekly-digest.md"
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            digest_path=digest,
        )
        await scheduler.tick_once()
        # Digest file exists after the first tick
        assert digest.exists()
        text = digest.read_text(encoding="utf-8")
        assert "# Proactive Scheduler — Weekly Digest" in text
        assert "## Week of " in text

    @pytest.mark.asyncio
    async def test_tick_skips_digest_within_same_week(
        self, graph_path, ledger_path, tmp_path
    ):
        """The second tick in the same ISO week must NOT re-render."""
        digest = tmp_path / "weekly-digest.md"
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            digest_path=digest,
        )
        await scheduler.tick_once()
        first_mtime = digest.stat().st_mtime
        # Force a second tick — digest_path same week → no rewrite
        # Wait a tiny bit so mtime would change if a write happened
        time.sleep(0.01)
        await scheduler.tick_once()
        assert digest.stat().st_mtime == first_mtime, (
            "second tick in same ISO week should not rewrite the digest"
        )

    @pytest.mark.asyncio
    async def test_no_digest_path_means_no_render(
        self, graph_path, ledger_path, tmp_path
    ):
        """When digest_path is None (slice-1/2 default), nothing is written."""
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            # digest_path NOT set — None default
        )
        await scheduler.tick_once()
        # No digest file should appear in tmp_path
        candidates = list(tmp_path.glob("weekly-digest*"))
        assert candidates == [], f"unexpected digest files: {candidates}"


# ---------------------------------------------------------------------------
# audit-2026-05-16.C.05 — HaltPolicy convergence
# ---------------------------------------------------------------------------


class TestSchedulerHaltPolicyIntegration:
    """The scheduler honours the shared HaltPolicy contract.

    Pre-C.05 the scheduler had ``get_halt_flag_present`` as its only
    halt source. The audit (HI-3/SW-2) called for the global halt flag
    to flow through the shared contract instead, so operator logs grep
    consistently across surfaces. These tests cover:

      1. Halt policy wired and blocking → skip with SKIP_HALTED.
      2. Halt policy wired and not blocking → tick proceeds normally
         even if ``get_halt_flag_present`` would have returned True
         (the policy wins when wired).
      3. No policy wired → legacy callable path unchanged.
    """

    @pytest.mark.asyncio
    async def test_halt_policy_blocks_tick(self, graph_path, ledger_path):
        """Halt policy reports blocked → scheduler skips with halted reason."""
        from bridge.halt import HaltPolicy

        policy = HaltPolicy(
            is_halted=lambda: True,
            halt_reason=lambda: "operator pressed /halt",
        )
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            halt_policy=policy,
        )
        report = await scheduler.tick_once()
        assert report.action == "skipped"
        assert report.reason == SKIP_HALTED

    @pytest.mark.asyncio
    async def test_halt_policy_wins_over_legacy_callable(
        self, graph_path, ledger_path
    ):
        """When both halt_policy and get_halt_flag_present are passed, the
        policy is the authoritative source. The legacy callable's value
        is ignored.
        """
        from bridge.halt import HaltPolicy

        # Policy says NOT halted; legacy callable says halted. Policy wins.
        policy = HaltPolicy(
            is_halted=lambda: False,
            halt_reason=lambda: None,
        )
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            halt_policy=policy,
            get_halt_flag_present=lambda: True,
        )
        report = await scheduler.tick_once()
        # Should NOT skip with SKIP_HALTED — policy says clear.
        assert report.reason != SKIP_HALTED

    @pytest.mark.asyncio
    async def test_no_policy_preserves_legacy_callable(
        self, graph_path, ledger_path
    ):
        """Back-compat regression: when no halt_policy is wired, the
        existing ``get_halt_flag_present`` callable path is preserved
        unchanged.
        """
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            # halt_policy NOT set — None default
            get_halt_flag_present=lambda: True,
        )
        assert scheduler._halt_policy is None
        report = await scheduler.tick_once()
        assert report.action == "skipped"
        assert report.reason == SKIP_HALTED

    @pytest.mark.asyncio
    async def test_halt_absent_preserves_pick_behaviour(
        self, graph_path, ledger_path
    ):
        """Negative regression: halt absent → behaviour unchanged.

        Policy reports not-halted, no other skip condition → scheduler
        picks the one safe-leaf node as before C.05.
        """
        from bridge.halt import HaltPolicy

        policy = HaltPolicy(
            is_halted=lambda: False,
            halt_reason=lambda: None,
        )
        scheduler = ProactiveScheduler(
            graph_path=graph_path,
            ledger_path=ledger_path,
            halt_policy=policy,
        )
        report = await scheduler.tick_once()
        assert report.action == "picked"
        assert report.work_item is not None
        assert report.work_item.number == 1
