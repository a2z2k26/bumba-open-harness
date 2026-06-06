"""Tests for ``bridge.experiment_notifier`` (Sprint 02.10)."""

from __future__ import annotations

import dataclasses

import pytest

from bridge.experiment_notifier import (
    ExperimentNotification,
    format_discord_short,
    format_discord_summary,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _base(**overrides) -> ExperimentNotification:
    """Build an ``ExperimentNotification`` with sensible defaults."""
    base = dict(
        iter_id="0042",
        outcome="keep",
        fitness_before=12.40,
        fitness_after=11.80,
        fitness_unit="s",
        cost_usd=0.1834,
        cost_breakdown={"sonnet": {"cost": 0.1500, "count": 3}, "haiku": {"cost": 0.0334, "count": 5}},
        mad_confidence_seconds=0.30,
        jsonl_relpath="data/experiments.jsonl",
        md_relpath="data/experiments.md",
    )
    base.update(overrides)
    return ExperimentNotification(**base)


# ----------------------------------------------------------------------
# format_discord_summary — outcomes & deltas
# ----------------------------------------------------------------------


def test_format_summary_keep_with_improvement():
    """Δ shows the improvement (after < before) with negative absolute and percent."""
    n = _base(outcome="keep", fitness_before=12.40, fitness_after=11.80)
    out = format_discord_summary(n)

    assert "**Experiment iter-0042**" in out
    assert "[KEEP]" in out
    assert "Fitness: 12.40s -> 11.80s" in out
    assert "Δ -0.60s" in out
    assert "-4.8%" in out
    assert "Confidence: ±0.30s 95% CI" in out
    assert "Cost: $0.1834" in out


def test_format_summary_discard_with_regression():
    """Δ shows regression (after > before) with explicit ``+`` signs."""
    n = _base(outcome="discard", fitness_before=10.00, fitness_after=10.50)
    out = format_discord_summary(n)

    assert "[DISCARD]" in out
    assert "Fitness: 10.00s -> 10.50s" in out
    assert "Δ +0.50s" in out
    assert "+5.0%" in out


def test_format_summary_crash_omits_fitness_line():
    """Crash (after=None) drops the fitness line entirely."""
    n = _base(outcome="crash", fitness_before=12.40, fitness_after=None)
    out = format_discord_summary(n)

    assert "[CRASH]" in out
    assert "Fitness:" not in out
    # Confidence band is paired with fitness; both omitted.
    assert "Confidence:" not in out
    assert "95% CI" not in out
    assert "Cost: $" in out


def test_format_summary_first_iteration_omits_delta():
    """First iteration (before=None) has nothing to compare against."""
    n = _base(fitness_before=None, fitness_after=11.80)
    out = format_discord_summary(n)

    assert "Fitness:" not in out
    assert "Confidence:" not in out
    assert "Cost: $" in out


# ----------------------------------------------------------------------
# format_discord_summary — confidence band
# ----------------------------------------------------------------------


def test_format_summary_confidence_populated():
    """When MAD confidence is available, show the ±value 95% CI line."""
    n = _base(mad_confidence_seconds=0.42)
    out = format_discord_summary(n)
    assert "Confidence: ±0.42s 95% CI" in out


def test_format_summary_confidence_stub_when_none():
    """Without 02.05, surface the deterministic stub message."""
    n = _base(mad_confidence_seconds=None)
    out = format_discord_summary(n)
    assert "(95% CI not yet available — pending Sprint 02.05)" in out


# ----------------------------------------------------------------------
# format_discord_summary — cost
# ----------------------------------------------------------------------


def test_format_summary_empty_cost_breakdown_still_shows_cost_line():
    """``cost_breakdown={}`` keeps a bare ``Cost: $X.XXXX`` line — no parens."""
    n = _base(cost_breakdown={}, cost_usd=0.0)
    out = format_discord_summary(n)
    assert "Cost: $0.0000" in out
    # No per-model parens when the breakdown is empty.
    assert "Cost: $0.0000\n" in out + "\n"


def test_format_summary_cost_breakdown_sorted_by_model_name():
    """Per-model breakdown is alphabetised so tests are deterministic."""
    n = _base(
        cost_breakdown={
            "sonnet": {"cost": 0.20, "count": 2},
            "haiku": {"cost": 0.05, "count": 4},
        },
        cost_usd=0.25,
    )
    out = format_discord_summary(n)
    # haiku should come before sonnet (alphabetical).
    haiku_idx = out.index("haiku")
    sonnet_idx = out.index("sonnet")
    assert haiku_idx < sonnet_idx
    assert "haiku $0.0500" in out
    assert "sonnet $0.2000" in out


# ----------------------------------------------------------------------
# format_discord_summary — evidence + emoji-free convention
# ----------------------------------------------------------------------


def test_format_summary_includes_evidence_paths():
    n = _base(jsonl_relpath="data/experiments.jsonl", md_relpath="data/experiments.md")
    out = format_discord_summary(n)
    assert "Evidence:" in out
    assert "`data/experiments.jsonl`" in out
    assert "`data/experiments.md`" in out


def test_format_summary_no_emojis_in_output():
    """the operator's convention: no emojis unless asked. Sprint output stays plain."""
    n = _base()
    out = format_discord_summary(n)
    forbidden = ["🧪", "✅", "⏭️", "💥", "🔥", "📊"]
    for ch in forbidden:
        assert ch not in out


# ----------------------------------------------------------------------
# format_discord_short
# ----------------------------------------------------------------------


def test_format_short_single_line():
    n = _base()
    out = format_discord_short(n)
    assert "\n" not in out
    assert "iter-0042" in out
    assert "KEEP" in out
    assert "Δ -0.60s" in out
    assert "cost $0.1834" in out


def test_format_short_no_delta_when_no_pair():
    n = _base(fitness_before=None, fitness_after=11.80)
    out = format_discord_short(n)
    assert "\n" not in out
    assert "Δ" not in out


# ----------------------------------------------------------------------
# Dataclass round-trip
# ----------------------------------------------------------------------


def test_notification_is_frozen_dataclass():
    """ExperimentNotification is immutable — mutation raises FrozenInstanceError."""
    n = _base()
    with pytest.raises(dataclasses.FrozenInstanceError):
        n.iter_id = "9999"  # type: ignore[misc]


def test_notification_dataclass_round_trip():
    """``dataclasses.replace`` produces a new instance with the override applied."""
    n = _base()
    n2 = dataclasses.replace(n, iter_id="0099", outcome="discard")
    assert n.iter_id == "0042"
    assert n2.iter_id == "0099"
    assert n2.outcome == "discard"
    # Other fields preserved.
    assert n2.fitness_before == n.fitness_before
    assert n2.cost_breakdown == n.cost_breakdown
