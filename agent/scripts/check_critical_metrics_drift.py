"""Critical-metrics drift gate.

Sprint audit-2026-05-16.F.01 — finding SW-1.

A small static checker that asserts a hard-coded set of "must exist"
metrics — emitted by autonomous surfaces (experiment loop, halt
enforcement, cost accounting, deploy helper) — are present in the
metrics registry at ``agent/config/registry/metrics/``.

This is the metrics-side complement to the events-side drift checks:

- ``scripts/check_registry_completeness.py`` enforces *call site →
  registry* coverage (every ``publish()``/``increment()`` in
  ``agent/bridge/`` has a registry entry).
- ``agent/scripts/check_telemetry_map.py`` enforces *docs → registry*
  for events named in the curated telemetry map.
- This script enforces *audit-named critical metrics ⊆ registry*. It
  does NOT scan call sites; it only guarantees the registry declares
  every metric the audit cares about.

Path-correction note: the sprint manifest cited
``agent/bridge/telemetry.py`` and ``scripts/check_telemetry_drift.py``
as the target surfaces. Neither exists. The actual surfaces in this
repo are ``agent/bridge/drift_telemetry.py`` (per-session drift
metrics) and ``agent/scripts/check_telemetry_map.py`` (event-map vs
registry). This script lives next to ``check_telemetry_map.py`` and
mirrors its conventions.

Usage
-----
::

    cd agent
    .venv/bin/python scripts/check_critical_metrics_drift.py

Exit codes
----------
- ``0`` — every metric in ``CRITICAL_METRICS`` is declared in the registry.
- ``1`` — at least one critical metric is missing from the registry.
- ``2`` — internal harness error (missing dir, parse failure, etc.).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_METRICS_DIR = _REPO_ROOT / "agent" / "config" / "registry" / "metrics"


# Critical metrics that MUST be present in the registry. Sourced from
# the SW-1 finding of the 2026-05-16 whole-codebase audit and the
# Phase-F sprint spec. Add a member only when the metric is genuinely
# load-bearing for autonomous-surface observability — this is not a
# catchall list. When you add one, also drop a YAML entry into
# ``agent/config/registry/metrics/autonomous-surfaces.yaml`` (or the
# topic-appropriate file) so the gate passes.
CRITICAL_METRICS: frozenset[str] = frozenset({
    "experiment.iteration.started",
    "experiment.iteration.completed",
    "halt.blocked",
    "cost.unknown",
    "deploy.helper.invoked",
})


# Suggested destination file per metric prefix. Used to give the
# operator a concrete "add it here" hint when the gate fails. Falls
# back to autonomous-surfaces.yaml when the prefix is not mapped.
_SUGGESTED_FILE_BY_PREFIX: dict[str, str] = {
    "experiment.": "autonomous-surfaces.yaml",
    "halt.": "autonomous-surfaces.yaml",
    "cost.": "autonomous-surfaces.yaml",
    "deploy.": "autonomous-surfaces.yaml",
}


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one drift-gate pass."""

    registered: frozenset[str] = field(default_factory=frozenset)
    missing: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.missing


def load_registered_metric_names(metrics_dir: Path) -> frozenset[str]:
    """Return every ``metric_name`` string declared under ``metrics_dir``.

    Walks every ``*.yaml`` file in the directory (sorted, deterministic).
    Each file maps registry-key → entry-dict; only ``metric_name`` is
    extracted. Empty / non-mapping entries are silently skipped — they
    are not the contract this gate enforces.
    """
    if not metrics_dir.is_dir():
        raise FileNotFoundError(f"metrics registry dir not found: {metrics_dir}")

    names: set[str] = set()
    for path in sorted(metrics_dir.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            continue
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            metric_name = entry.get("metric_name")
            if isinstance(metric_name, str) and metric_name:
                names.add(metric_name)
    return frozenset(names)


def check(
    metrics_dir: Path,
    critical: frozenset[str] = CRITICAL_METRICS,
) -> CheckResult:
    """Verify ``critical`` is a subset of the registered metric names."""
    registered = load_registered_metric_names(metrics_dir)
    missing = tuple(sorted(critical - registered))
    return CheckResult(registered=registered, missing=missing)


def _suggested_file(metric_name: str) -> str:
    """Return the relative YAML filename the operator should edit."""
    for prefix, filename in _SUGGESTED_FILE_BY_PREFIX.items():
        if metric_name.startswith(prefix):
            return filename
    return "autonomous-surfaces.yaml"


def render_text(result: CheckResult) -> str:
    """Render a stable, grep-friendly summary for stdout."""
    lines = [
        "Critical-metrics drift gate (SW-1)",
        f"  registered_metrics: {len(result.registered)}",
        f"  critical_required:  {len(CRITICAL_METRICS)}",
        f"  missing:            {len(result.missing)}",
        "",
    ]
    if result.missing:
        lines.append(
            "MISSING CRITICAL METRICS (declare each in agent/config/registry/metrics/):"
        )
        for metric_name in result.missing:
            target = _suggested_file(metric_name)
            lines.append(f"  - {metric_name}  (suggested file: {target})")
        lines.append("")
        lines.append(
            "Add the entry, re-run this script, and ensure "
            "`check_registry_completeness` still passes."
        )
        lines.append("")
    else:
        lines.append("All critical metrics are registered. OK.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that every metric in CRITICAL_METRICS is declared in "
            "agent/config/registry/metrics/. See audit finding SW-1."
        )
    )
    parser.add_argument(
        "--metrics-dir",
        default=str(_REGISTRY_METRICS_DIR),
        help=(
            "Directory containing metric registry yaml files "
            f"(default: {_REGISTRY_METRICS_DIR})."
        ),
    )
    args = parser.parse_args(argv)

    metrics_dir = Path(args.metrics_dir)

    try:
        result = check(metrics_dir)
    except FileNotFoundError as exc:
        print(f"check_critical_metrics_drift: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(
            f"check_critical_metrics_drift: parse error: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    output = render_text(result)
    if result.ok:
        sys.stdout.write(output)
        return 0
    sys.stderr.write(output)
    return 1


if __name__ == "__main__":
    sys.exit(main())
