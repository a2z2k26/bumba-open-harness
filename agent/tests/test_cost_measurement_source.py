"""P0.03 — source-aware cost aggregation.

The four-state CostMeasurement contract already exists (cost_tracker.py).
This sprint adds an aggregator that honours the ``source`` state so an
``unknown`` cost is never silently summed as ``0.0`` (the SW-3 collapse),
and wires the same epistemic distinction into ClaudeResult via a
``cost_unknown`` flag.

Written against the REAL CostMeasurement API (amount_usd: Decimal | None,
required ``backend`` field), not the simplified shape the issue assumed.
"""

from decimal import Decimal

from bridge.cost_tracker import CostMeasurement, aggregate_measurements


def test_unknown_cost_not_coerced_to_zero():
    """An unknown measurement contributes 0.0 to the numeric total but flips
    had_unknown True so callers never mistake unknown for free."""
    m = CostMeasurement(amount_usd=None, source="unknown", backend="claude")
    total, had_unknown = aggregate_measurements([m])
    assert had_unknown is True
    assert total == 0.0


def test_measured_amounts_sum():
    measurements = [
        CostMeasurement(amount_usd=Decimal("0.10"), source="measured", backend="claude"),
        CostMeasurement(amount_usd=Decimal("0.25"), source="estimated", backend="codex"),
    ]
    total, had_unknown = aggregate_measurements(measurements)
    assert had_unknown is False
    assert total == 0.35


def test_measured_zero_is_not_unknown():
    """A measured Decimal('0') (e.g. a subscription turn) is free-and-known,
    distinct from unknown."""
    m = CostMeasurement(amount_usd=Decimal("0"), source="measured", backend="codex")
    total, had_unknown = aggregate_measurements([m])
    assert had_unknown is False
    assert total == 0.0


def test_not_applicable_excluded_without_unknown_flag():
    """Off-meter (not_applicable) contributes nothing and is NOT an unknown —
    it's known to be structurally off-meter."""
    m = CostMeasurement(amount_usd=None, source="not_applicable", backend="internal")
    total, had_unknown = aggregate_measurements([m])
    assert had_unknown is False
    assert total == 0.0


def test_mixed_unknown_and_measured():
    measurements = [
        CostMeasurement(amount_usd=Decimal("0.50"), source="measured", backend="claude"),
        CostMeasurement(amount_usd=None, source="unknown", backend="openrouter"),
    ]
    total, had_unknown = aggregate_measurements(measurements)
    assert total == 0.50
    assert had_unknown is True


def test_empty_list():
    total, had_unknown = aggregate_measurements([])
    assert total == 0.0
    assert had_unknown is False


def test_claude_result_carries_cost_unknown_flag():
    """ClaudeResult must be able to surface that the cost was unknown rather
    than collapsing it into the 0.0 default."""
    from bridge.claude_runner import ClaudeResult

    r = ClaudeResult()
    assert r.cost_unknown is False  # default: cost is known (0.0)
    r2 = ClaudeResult(cost_usd=0.0, cost_unknown=True)
    assert r2.cost_unknown is True


def test_process_events_surfaces_unknown_cost():
    """When the result stream event reports an unknown cost (cost_usd=None,
    cost_unknown=True), _process_events must set cost_unknown on the result
    and NOT report a measured 0.0 as if it were free."""
    from bridge.backends._protocol import StreamEvent
    from bridge.claude_runner import _process_events

    events = [
        StreamEvent(type="result", subtype="success", cost_usd=None, cost_unknown=True),
    ]
    result = _process_events(events)
    assert result.cost_unknown is True
    assert result.cost_usd == 0.0  # numeric stays 0, but the flag tells the truth


def test_process_events_known_cost_unchanged():
    """A normal measured cost still flows through with cost_unknown False."""
    from bridge.backends._protocol import StreamEvent
    from bridge.claude_runner import _process_events

    events = [
        StreamEvent(type="result", subtype="success", cost_usd=0.42, cost_unknown=False),
    ]
    result = _process_events(events)
    assert result.cost_unknown is False
    assert result.cost_usd == 0.42
