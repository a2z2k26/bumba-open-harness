"""Tests for ``scripts/core_loop_soak.py``.

Sprint R7.1 acceptance: assert the short soak completes deterministically
in well under 60s, all four loops report PASS by default, output carries
the resource summary + per-loop failure counts, and the CLI's exit-code
contract (0 = ok, 1 = at least one loop failed, 2 = harness error) is
honoured.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from scripts.core_loop_soak import (
    LoopStats,
    SoakResult,
    main,
    render_json,
    render_text,
    run_soak,
)


# ---------------------------------------------------------------------------
# Happy-path soak — short iteration count keeps the test under the
# pytest-tolerable budget; the script's own "≤ 60s for the CI-safe
# short soak" acceptance is exercised by the CLI test below.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soak_happy_path_returns_complete_result():
    """All four loops exercised for 5 iterations end clean."""
    from scripts.core_loop_soak import _run_soak_async

    result = await _run_soak_async(
        iterations=5,
        include=["metrics", "event_bus", "dispatcher", "consolidation_lock"],
    )

    assert result.ok is True
    assert result.iterations == 5
    assert set(result.loops_included) == {
        "metrics",
        "event_bus",
        "dispatcher",
        "consolidation_lock",
    }
    assert result.total_failures == 0
    # event_bus loop publishes 5/iter; dispatcher publishes 3/iter.
    # 5 iters * (5 + 3) = 40 minimum. Allow some headroom for noise.
    assert result.total_events_published >= 40
    assert result.wall_time_s > 0
    assert result.peak_memory_kb > 0

    # Each loop ran the full 5 iterations with zero failures.
    by_name = {loop.name: loop for loop in result.loops}
    assert set(by_name) == {
        "metrics",
        "event_bus",
        "dispatcher",
        "consolidation_lock",
    }
    for loop in result.loops:
        assert loop.iterations == 5
        assert loop.failures == 0
        assert loop.duration_total_s > 0
        # P50/P95/P99 must be monotonic in the right direction.
        assert loop.duration_p50_s <= loop.duration_p95_s
        assert loop.duration_p95_s <= loop.duration_p99_s
        assert loop.duration_p99_s <= loop.duration_max_s


def test_run_soak_sync_wrapper():
    """The synchronous wrapper drives the async soak to completion."""
    result = run_soak(
        iterations=3,
        include=["metrics", "event_bus"],
    )
    assert result.ok is True
    assert result.iterations == 3
    assert result.loops_included == ("metrics", "event_bus")


def test_include_narrow_runs_only_named_loops():
    """`--include` restricts execution to the named loops."""
    result = run_soak(iterations=2, include=["consolidation_lock"])
    assert result.ok is True
    assert result.loops_included == ("consolidation_lock",)
    assert len(result.loops) == 1
    assert result.loops[0].name == "consolidation_lock"


def test_invalid_iterations_raises():
    """Zero or negative iterations is a programmer error, not a soak fail."""
    with pytest.raises(ValueError):
        run_soak(iterations=0, include=["metrics"])


def test_invalid_loop_name_raises():
    with pytest.raises(ValueError, match="unknown loop name"):
        run_soak(iterations=1, include=["bogus_loop"])


def test_empty_include_raises():
    with pytest.raises(ValueError, match="at least one loop"):
        run_soak(iterations=1, include=[])


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def test_render_text_includes_summary_and_per_loop_lines():
    result = SoakResult(
        ok=True,
        iterations=10,
        loops_included=("metrics", "event_bus"),
        wall_time_s=0.42,
        peak_memory_kb=1234,
        memory_growth_kb=12,
        total_events_published=50,
        total_failures=0,
        loops=(
            LoopStats(
                name="metrics",
                iterations=10,
                failures=0,
                duration_total_s=0.10,
                duration_p50_s=0.001,
                duration_p95_s=0.002,
                duration_p99_s=0.003,
                duration_max_s=0.004,
            ),
            LoopStats(
                name="event_bus",
                iterations=10,
                failures=0,
                duration_total_s=0.20,
                duration_p50_s=0.005,
                duration_p95_s=0.010,
                duration_p99_s=0.012,
                duration_max_s=0.015,
            ),
        ),
    )
    text = render_text(result)
    assert "ok:                     True" in text
    assert "iterations:             10" in text
    assert "wall_time_s:            0.420" in text
    assert "peak_memory_kb:         1234" in text
    assert "memory_growth_kb:       12" in text
    assert "total_events_published: 50" in text
    assert "[PASS] metrics" in text
    assert "[PASS] event_bus" in text


def test_render_text_marks_failed_loop():
    result = SoakResult(
        ok=False,
        iterations=5,
        loops_included=("metrics",),
        wall_time_s=0.1,
        peak_memory_kb=100,
        memory_growth_kb=0,
        total_events_published=0,
        total_failures=2,
        loops=(
            LoopStats(
                name="metrics",
                iterations=5,
                failures=2,
                duration_total_s=0.05,
                duration_p50_s=0.001,
                duration_p95_s=0.002,
                duration_p99_s=0.003,
                duration_max_s=0.004,
            ),
        ),
    )
    text = render_text(result)
    assert "[FAIL] metrics: iters=5 failures=2" in text


def test_render_json_is_parseable_and_contains_expected_keys():
    result = SoakResult(
        ok=True,
        iterations=3,
        loops_included=("metrics",),
        wall_time_s=0.05,
        peak_memory_kb=100,
        memory_growth_kb=1,
        total_events_published=0,
        total_failures=0,
        loops=(
            LoopStats(
                name="metrics",
                iterations=3,
                failures=0,
                duration_total_s=0.01,
                duration_p50_s=0.001,
                duration_p95_s=0.002,
                duration_p99_s=0.003,
                duration_max_s=0.004,
            ),
        ),
    )
    payload = json.loads(render_json(result))
    assert payload["ok"] is True
    assert payload["iterations"] == 3
    assert payload["loops_included"] == ["metrics"]
    assert payload["total_failures"] == 0
    assert payload["loops"][0]["name"] == "metrics"
    assert payload["loops"][0]["failures"] == 0


# ---------------------------------------------------------------------------
# CLI exit-code contract
# ---------------------------------------------------------------------------


class TestMainExitCodes:
    def test_exit_zero_on_happy_path(self, capsys):
        rc = main(["--iterations", "3", "--include", "metrics"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ok:                     True" in out

    def test_json_flag_emits_parseable_payload(self, capsys):
        rc = main(["--iterations", "2", "--include", "metrics", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["iterations"] == 2
        assert payload["loops_included"] == ["metrics"]

    def test_exit_one_when_loop_fails(self, capsys):
        """A soak result with `ok=False` maps to exit 1."""
        failing = SoakResult(
            ok=False,
            iterations=5,
            loops_included=("metrics",),
            wall_time_s=0.1,
            peak_memory_kb=100,
            memory_growth_kb=0,
            total_events_published=0,
            total_failures=3,
            loops=(
                LoopStats(
                    name="metrics",
                    iterations=5,
                    failures=3,
                    duration_total_s=0.05,
                    duration_p50_s=0.001,
                    duration_p95_s=0.002,
                    duration_p99_s=0.003,
                    duration_max_s=0.004,
                ),
            ),
        )
        with mock.patch(
            "scripts.core_loop_soak.run_soak", return_value=failing,
        ):
            rc = main(["--iterations", "5", "--include", "metrics"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "ok:                     False" in out
        assert "[FAIL] metrics" in out

    def test_exit_two_when_run_soak_raises(self, capsys):
        """An unexpected exception during soak construction maps to exit 2."""
        with mock.patch(
            "scripts.core_loop_soak.run_soak",
            side_effect=RuntimeError("import broke"),
        ):
            rc = main(["--iterations", "3", "--include", "metrics"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "internal harness error" in err
        assert "RuntimeError" in err

    def test_default_includes_all_loops(self, capsys):
        """Omitting --include exercises all four loops."""
        rc = main(["--iterations", "2", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert set(payload["loops_included"]) == {
            "metrics",
            "event_bus",
            "dispatcher",
            "consolidation_lock",
        }


# ---------------------------------------------------------------------------
# Acceptance — short soak runs in under 60s
# ---------------------------------------------------------------------------


class TestShortSoakAcceptance:
    """The R7.1 spec's primary acceptance gate: short soak < 60s."""

    def test_default_short_soak_under_60s(self, capsys):
        """100 iters across all four loops MUST exit 0 in well under 60s.

        This is the headline acceptance criterion; if this regresses,
        the soak harness is no longer fast enough for pre-merge use.
        We measure wall time from the soak's own report (already the
        operator-visible signal) rather than wrapping `main` in a
        timer here — keeps the assertion tied to the contract the CLI
        renders.
        """
        rc = main(["--iterations", "100", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["iterations"] == 100
        # Hard ceiling: 60s. Realistic budget is < 5s on a developer
        # laptop, so 30s gives 6x headroom and still flags a serious
        # regression. Tunable if CI runner P99 drifts.
        assert payload["wall_time_s"] < 30.0, (
            f"short soak exceeded 30s wall budget: {payload['wall_time_s']:.2f}s; "
            "soak harness has regressed"
        )
        # Resource summary present.
        assert "peak_memory_kb" in payload
        assert "memory_growth_kb" in payload
        assert "total_events_published" in payload
        # Per-loop failure counts present.
        for loop in payload["loops"]:
            assert "failures" in loop
            assert loop["failures"] == 0


# ---------------------------------------------------------------------------
# Offline / determinism contract
# ---------------------------------------------------------------------------


class TestOffline:
    """Soak must not call any external service.

    The dispatcher loop is the only one that reaches deep enough to
    *want* to call a model — it patches `WarmChief._run_chief` so the
    chief returns synthetically. If the patch leaked, the underlying
    `_run_chief` would attempt a model call and fail in this offline
    environment.
    """

    def test_no_anthropic_call_during_soak(self):
        """A successful dispatcher loop means the patch held."""
        result = run_soak(iterations=3, include=["dispatcher"])
        assert result.ok is True
        assert result.total_failures == 0

    def test_event_ring_does_not_grow_unbounded(self):
        """event_bus loop publishes 5/iter; ring is meant to cap at 100.

        Ring growth past 100 events would manifest as a memory growth
        spike in the soak result. This guards the ring's bounded-size
        invariant under repeated load.
        """
        from bridge.event_bus import EventBus

        # Drive 30 iters through the event_bus loop (= 150 publishes,
        # comfortably past the 100-cap) and confirm the ring stayed
        # capped at 100 via direct inspection of a fresh bus driven
        # the same way.
        bus = EventBus()
        for i in range(30):
            for j in range(5):
                bus.publish(
                    "soak.tick", payload={"iter": i, "j": j}, source="test"
                )
        assert len(bus._recent_events) == 100
