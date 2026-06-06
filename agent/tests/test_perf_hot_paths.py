"""Hot-path performance budgets — Sprint R7.2 (#1910).

These tests guard against order-of-magnitude regressions in the four
hot paths called frequently during autonomous operation: metrics
counters (covered by ``test_metrics.py::TestPerformance``), event-bus
publish, registry lookup, and FTS5 knowledge search.

Discipline
----------
- **Marked ``perf``** so coverage runs deselect them — pytest-cov
  instrumentation adds 10-30% overhead and would cause flakes.
- **Generous budgets.** Wall-clock ceilings are 3-10x the observed
  median on developer hardware. We catch a regression that turns a
  microsecond loop into a millisecond loop, NOT a 5% slowdown that's
  just GC noise.
- **Deterministic on CI and Mac mini.** All tests use in-memory state,
  no network, no fixtures that vary between hosts.
- **Adjustment protocol.** Bumping a budget is a deliberate decision,
  not a fix for a flake. See ``docs/testing/performance-budgets.md``.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Event bus publish — synchronous fan-out under load
# ---------------------------------------------------------------------------


@pytest.mark.perf
class TestEventBusPublish:
    """``EventBus.publish`` is invoked on every chief-session lifecycle
    transition + every dispatcher routing decision + every workflow step.
    A regression in this path bottlenecks every Zone 4 dispatch.
    """

    def test_publish_no_subscribers_overhead(self, tmp_path):
        """1000 publishes with no subscribers — pure ring-write + JSONL."""
        from bridge.event_bus import EventBus

        bus = EventBus(data_dir=tmp_path)
        start = time.monotonic()
        for i in range(1000):
            bus.publish("test.event", {"i": i})
        elapsed = time.monotonic() - start
        # 1000 publishes should complete in <500ms (typical: ~50-100ms).
        # Generous ceiling: catches a 5x regression but tolerates GC + I/O jitter.
        assert elapsed < 0.5, (
            f"1000 publish() calls took {elapsed:.3f}s; "
            f"budget is 0.5s — see docs/testing/performance-budgets.md"
        )

    def test_publish_with_one_subscriber_overhead(self, tmp_path):
        """1000 publishes with one trivial subscriber."""
        from bridge.event_bus import EventBus

        bus = EventBus(data_dir=tmp_path)
        seen: list[str] = []

        def _handler(event):
            seen.append(event.event_type)

        bus.subscribe("test.event", _handler)
        start = time.monotonic()
        for i in range(1000):
            bus.publish("test.event", {"i": i})
        elapsed = time.monotonic() - start
        # Subscriber adds a function call per event; budget stays at 0.5s
        # because the handler is trivial. If a future change makes
        # publish iterate subscribers in O(n), this catches it.
        assert elapsed < 0.5, (
            f"1000 publish() with 1 subscriber took {elapsed:.3f}s; "
            f"budget is 0.5s"
        )
        assert len(seen) == 1000


# ---------------------------------------------------------------------------
# Registry lookup — boot-time + warm-path catalog reads
# ---------------------------------------------------------------------------


@pytest.mark.perf
class TestRegistryLookup:
    """``RegistryLoader.load_all`` runs at every bridge boot and is
    consulted by the registry-completeness CI gate. A regression here
    slows every cold start.
    """

    def test_load_all_under_one_second(self):
        """Load the actual on-disk registry. Must complete in <1s.

        Generous ceiling — typical wall is 50-150ms. The 1s budget
        catches a regression that turns YAML parsing into a per-file
        round-trip to disk or similar pathology.
        """
        from bridge.registry_loader import RegistryLoader

        repo_root = Path(__file__).resolve().parent.parent.parent
        registry_root = repo_root / "agent" / "config" / "registry"
        assert registry_root.is_dir(), f"missing: {registry_root}"

        loader = RegistryLoader()
        start = time.monotonic()
        index = loader.load_all(registry_root)
        elapsed = time.monotonic() - start
        # Index should be non-trivial — proves we actually loaded something.
        assert len(index.events) >= 50, (
            f"registry produced only {len(index.events)} events; "
            "either the directory is empty or load_all is misbehaving"
        )
        assert elapsed < 1.0, (
            f"RegistryLoader.load_all took {elapsed:.3f}s on "
            f"{len(index.events)} events + {len(index.metrics)} metrics + "
            f"{len(index.actions)} actions; budget is 1.0s"
        )

    def test_repeated_load_all_remains_under_budget(self):
        """5 sequential loads — caches must not blow up unbounded."""
        from bridge.registry_loader import RegistryLoader

        repo_root = Path(__file__).resolve().parent.parent.parent
        registry_root = repo_root / "agent" / "config" / "registry"

        start = time.monotonic()
        for _ in range(5):
            RegistryLoader().load_all(registry_root)
        elapsed = time.monotonic() - start
        # 5x single-load budget: 5s. Catches a regression where each
        # successive load gets slower (memory pressure, file-handle leak).
        assert elapsed < 5.0, (
            f"5 sequential RegistryLoader.load_all took {elapsed:.3f}s; "
            f"budget is 5.0s"
        )


# ---------------------------------------------------------------------------
# Readiness report parsing — operator-facing CLI hot path
# ---------------------------------------------------------------------------


@pytest.mark.perf
class TestReadinessParsing:
    """``readiness_diff.py``'s ``parse_report`` (Sprint R3.3) and
    ``check_readiness_docs.py``'s parsers (Sprint R6.2) are invoked
    by the operator-facing diff CLI and the doc-drift gate. They must
    stay snappy enough for interactive use and CI.
    """

    def test_parse_readiness_report_under_50ms(self):
        """Parse a 50-row synthetic report 100 times. Must stay <50ms total."""
        from scripts.readiness_diff import parse_report

        # Build a 50-row report.
        rows = "\n".join(
            f"| {i} | check_{i} | PASS | note for check {i} |"
            for i in range(1, 51)
        )
        text = (
            "## Checks\n\n"
            "| # | Check | Status | Notes |\n"
            "|---|-------|--------|-------|\n"
            f"{rows}\n\n"
            "## Detail\n"
        )

        start = time.monotonic()
        for _ in range(100):
            result = parse_report(text)
        elapsed = time.monotonic() - start
        assert len(result) == 50
        # 100 parses of a 50-row report should be near-instant.
        assert elapsed < 0.05, (
            f"100x parse_report(50 rows) took {elapsed:.3f}s; "
            f"budget is 0.05s"
        )

    def test_parse_readiness_sh_against_real_file(self):
        """Parse the actual on-disk readiness.sh. Must stay <50ms."""
        from scripts.check_readiness_docs import parse_readiness_sh

        repo_root = Path(__file__).resolve().parent.parent.parent
        sh_path = repo_root / "agent" / "scripts" / "readiness.sh"
        assert sh_path.is_file()

        text = sh_path.read_text(encoding="utf-8")
        start = time.monotonic()
        for _ in range(100):
            rows = parse_readiness_sh(text)
        elapsed = time.monotonic() - start
        assert len(rows.live) >= 5, (
            f"parser found only {len(rows.live)} live rows in readiness.sh; "
            "either the file is empty or the parser is misbehaving"
        )
        assert elapsed < 0.05, (
            f"100x parse_readiness_sh took {elapsed:.3f}s on "
            f"{len(rows.live)} live + {len(rows.pending)} pending rows; "
            f"budget is 0.05s"
        )
