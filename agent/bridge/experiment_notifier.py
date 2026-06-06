"""Experiment-loop Discord notification formatter (Sprint 02.10).

Builds the Discord message that the experiment loop posts after each
iteration. Splits formatting out of ``scripts/experiment_loop.py`` so
the format is unit-testable without spinning up a live loop.

The message includes:

* iteration id + outcome label (``[KEEP]`` / ``[DISCARD]`` / ``[CRASH]``)
* fitness Δ — before → after with absolute and percent change
* MAD-based 95% confidence band (Sprint 02.05). When the
  ``mad_confidence_seconds`` field is ``None`` the formatter degrades to
  a stub line so downstream consumers still see a deterministic message.
* per-iteration cost and per-model breakdown (Sprint 02.09 /
  ``cost_tracker.get_experiment_summary``)
* paths to the triple-write evidence files (Sprint 02.03 —
  ``experiments.jsonl`` and ``experiments.md``)

Operator-signed fitness metric: Option 1 — mean test runtime
(`pytest --durations=0`), banked 2026-05-01.

The bridge convention is plain-text labels (no emojis); see
`OPERATOR.md` and the audit of `bridge/` for the small number of
existing emoji uses (``output_router.py``, ``dream_notifier.py``) that
predate that convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Stable label map: outcome → bracketed plain-text tag. Matches the
# spec's example string and stays emoji-free per OPERATOR.md.
_OUTCOME_LABELS: dict[str, str] = {
    "keep": "[KEEP]",
    "discard": "[DISCARD]",
    "crash": "[CRASH]",
}


def _label_for(outcome: str) -> str:
    """Return the bracketed tag for a known outcome, else ``[UNKNOWN]``."""
    return _OUTCOME_LABELS.get((outcome or "").lower(), "[UNKNOWN]")


@dataclass(frozen=True)
class ExperimentNotification:
    """Structured input → formatted Discord message.

    Frozen so callers MUST treat instances as immutable. Construct a
    new ``ExperimentNotification`` rather than mutating fields.
    """

    iter_id: str
    outcome: str  # "keep" | "discard" | "crash"
    fitness_before: float | None  # None on first iteration
    fitness_after: float | None  # None on crash
    fitness_unit: str = "s"  # seconds for runtime metric
    cost_usd: float = 0.0
    cost_breakdown: dict[str, dict] = field(default_factory=dict)
    mad_confidence_seconds: float | None = None  # 02.05 dependency; None = stub mode
    jsonl_relpath: str | None = None  # link to experiments.jsonl entry
    md_relpath: str | None = None  # link to experiments.md entry


def _format_fitness_line(
    before: float | None,
    after: float | None,
    unit: str,
) -> str | None:
    """Return the fitness-Δ line, or ``None`` when there's nothing to say.

    First iteration (``before is None``): no Δ available yet.
    Crash (``after is None``): omit the line; outcome label already
    communicates the failure.
    """
    if before is None or after is None:
        return None

    delta_abs = after - before
    sign = "+" if delta_abs >= 0 else ""
    if before == 0:
        pct_str = "n/a"
    else:
        pct = (delta_abs / before) * 100.0
        pct_sign = "+" if pct >= 0 else ""
        pct_str = f"{pct_sign}{pct:.1f}%"

    return (
        f"Fitness: {before:.2f}{unit} -> {after:.2f}{unit} "
        f"(Δ {sign}{delta_abs:.2f}{unit}, {pct_str})"
    )


def _format_confidence_line(
    mad_confidence_seconds: float | None,
    unit: str,
) -> str:
    """Return the 95% CI line. Stub message when 02.05 hasn't shipped."""
    if mad_confidence_seconds is None:
        return "(95% CI not yet available — pending Sprint 02.05)"
    return f"Confidence: ±{mad_confidence_seconds:.2f}{unit} 95% CI"


def _format_cost_line(cost_usd: float, breakdown: dict[str, dict]) -> str:
    """Return the cost line with optional per-model breakdown."""
    base = f"Cost: ${cost_usd:.4f}"
    if not breakdown:
        return base
    # Stable ordering for tests: sort by model name.
    parts: list[str] = []
    for model in sorted(breakdown.keys()):
        stats = breakdown[model] or {}
        model_cost = stats.get("cost", 0.0)
        try:
            model_cost_f = float(model_cost)
        except (TypeError, ValueError):
            model_cost_f = 0.0
        parts.append(f"{model} ${model_cost_f:.4f}")
    return f"{base} ({', '.join(parts)})"


def _format_evidence_line(jsonl_relpath: str | None, md_relpath: str | None) -> str | None:
    """Return the evidence link line, or ``None`` if no paths supplied."""
    parts: list[str] = []
    if jsonl_relpath:
        parts.append(f"`{jsonl_relpath}`")
    if md_relpath:
        parts.append(f"`{md_relpath}`")
    if not parts:
        return None
    return "Evidence: " + " / ".join(parts)


def format_discord_summary(n: ExperimentNotification) -> str:
    """Format a Discord-friendly markdown message.

    Format::

        **Experiment iter-{iter_id}** — {outcome_label}

        Fitness: {before}s -> {after}s (Δ ±N.NNs, ±N.N%)
        Confidence: ±N.NNs 95% CI   (or stub when 02.05 not yet shipped)
        Cost: $X.XXXX (model $Y.YYYY, ...)

        Evidence: `experiments.jsonl` / `experiments.md`

    The fitness line is omitted on first iteration (no ``before``) and
    on crash (no ``after``). The evidence line is omitted when neither
    path is supplied.
    """
    label = _label_for(n.outcome)
    header = f"**Experiment iter-{n.iter_id}** — {label}"

    body_lines: list[str] = []
    fitness_line = _format_fitness_line(n.fitness_before, n.fitness_after, n.fitness_unit)
    if fitness_line is not None:
        body_lines.append(fitness_line)
        # Only show CI when a Δ was actually shown — the band describes
        # the noise around that delta and is meaningless without it.
        body_lines.append(_format_confidence_line(n.mad_confidence_seconds, n.fitness_unit))

    body_lines.append(_format_cost_line(n.cost_usd, n.cost_breakdown or {}))

    evidence_line = _format_evidence_line(n.jsonl_relpath, n.md_relpath)
    if evidence_line is not None:
        body_lines.append("")
        body_lines.append(evidence_line)

    return header + "\n\n" + "\n".join(body_lines)


def format_discord_short(n: ExperimentNotification) -> str:
    """Single-line short form for queue-summary lines (no emoji).

    Matches the spec example shape::

        iter-NNNN  KEEP  Δ +0.12s  cost $0.18  msg "<...>"

    Δ is omitted when before/after isn't a usable pair.
    """
    label = _label_for(n.outcome).strip("[]")
    parts: list[str] = [f"iter-{n.iter_id}", label]
    if n.fitness_before is not None and n.fitness_after is not None:
        delta_abs = n.fitness_after - n.fitness_before
        sign = "+" if delta_abs >= 0 else ""
        parts.append(f"Δ {sign}{delta_abs:.2f}{n.fitness_unit}")
    parts.append(f"cost ${n.cost_usd:.4f}")
    return "  ".join(parts)
