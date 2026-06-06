"""Verify the telemetry map agrees with the registry catalog.

Sprint R7.3 (current-state improvement plan) — narrow guardrail that
catches one specific drift: the telemetry map at
``docs/observability/telemetry-map.md`` names events/metrics but the
registry at ``agent/config/registry/`` does not declare them, or
vice-versa.

The check does NOT scan ``publish()`` call sites — that would require
import-time analysis of every module under ``bridge/``. It only
guarantees that every event the map cites is declared in the registry.
The registry-completeness CI gate already enforces "every code-emitted
event has a registry entry" from the other direction; this script
covers the doc → registry direction.

Usage
-----
::

    cd agent
    .venv/bin/python scripts/check_telemetry_map.py

Exit codes
----------
- ``0`` — every event named in the map has a registry entry.
- ``1`` — at least one event named in the map is missing from the
  registry (or vice-versa, when ``--strict-bidirectional`` is set).
- ``2`` — internal harness error (file missing, parse failed, etc.).
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TELEMETRY_MAP = _REPO_ROOT / "docs" / "observability" / "telemetry-map.md"
_REGISTRY_EVENTS_DIR = _REPO_ROOT / "agent" / "config" / "registry" / "events"

# Match `chief_dispatcher.routed`, `chief_session.state_changed`,
# `webhook.auth.failed`, etc. Backticks bracket every event reference in
# the map by convention.
_EVENT_RE = re.compile(r"`([a-z_]+\.[a-z_.]+)`")


@dataclass
class CheckResult:
    """Outcome of one check pass."""

    map_events: set[str] = field(default_factory=set)
    registry_events: set[str] = field(default_factory=set)
    missing_from_registry: list[str] = field(default_factory=list)
    missing_from_map: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_from_registry


def parse_map_events(text: str) -> set[str]:
    """Extract event identifiers from the telemetry map.

    Only inspects rows in the ``## Map`` section that start with
    ``| Event |`` — the dedicated event rows in each operation's table.
    This intentionally ignores ``| Metric |``, ``| Log |``, ``| Side
    effect |``, and ``| Operator-visible |`` rows (which legitimately
    cite metric names or event names in deferred notes), and skips the
    ``## Map coverage gaps`` section entirely.
    """
    events: set[str] = set()
    in_map = False
    for raw_line in text.splitlines():
        # Only the `## Map` H2 (exact string after stripping) opens the
        # section. Sibling H2s like `## Map coverage gaps` are treated
        # as section terminators.
        stripped = raw_line.rstrip()
        if stripped == "## Map":
            in_map = True
            continue
        if in_map and stripped.startswith("## "):
            in_map = False
            continue
        if not in_map:
            continue
        # Only `| Event | ... |` rows count as emit-site declarations.
        if not raw_line.lstrip().startswith("| Event |"):
            continue
        for match in _EVENT_RE.findall(raw_line):
            if "/" in match or match.startswith("bridge."):
                continue
            head = match.split(".")[0]
            if head not in _EVENT_DOMAINS:
                continue
            events.add(match)
    return events


# Domains the map references. Updates here when a new top-level event
# family lands (e.g. `webhook`, `bridge`, `cron`, ...).
_EVENT_DOMAINS = frozenset({
    "chief_dispatcher",
    "chief_session",
    "webhook",
    "bridge",
    "cron",
    "compaction",
    "memory",
    "agent",
    "agents",
    "deploy",
    "health_status",
    "hook_lifecycle",
    "jobs",
    "actionable_hitl",
    "work_progress",
    "sample",
})


def parse_registry_events(events_dir: Path) -> set[str]:
    """Collect every ``event_type`` field from the registry yaml files."""
    if not events_dir.is_dir():
        raise FileNotFoundError(f"registry events dir not found: {events_dir}")
    events: set[str] = set()
    for path in sorted(events_dir.glob("*.yaml")):
        with path.open() as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            continue
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            ev = entry.get("event_type")
            if isinstance(ev, str):
                events.add(ev)
    return events


def check(map_text: str, events_dir: Path) -> CheckResult:
    """Compare map events against registry events; populate result lists."""
    map_events = parse_map_events(map_text)
    registry_events = parse_registry_events(events_dir)
    missing_from_registry = sorted(map_events - registry_events)
    missing_from_map = sorted(registry_events - map_events)
    return CheckResult(
        map_events=map_events,
        registry_events=registry_events,
        missing_from_registry=missing_from_registry,
        missing_from_map=missing_from_map,
    )


def render_text(result: CheckResult, *, strict_bidirectional: bool) -> str:
    lines = [
        "Telemetry map check",
        f"  map_events:        {len(result.map_events)}",
        f"  registry_events:   {len(result.registry_events)}",
        f"  missing_from_registry: {len(result.missing_from_registry)}",
        f"  missing_from_map:      {len(result.missing_from_map)}",
        "",
    ]
    if result.missing_from_registry:
        lines.append("MISSING FROM REGISTRY (the map names these but no event_type matches):")
        for ev in result.missing_from_registry:
            lines.append(f"  - {ev}")
        lines.append("")
    if result.missing_from_map and strict_bidirectional:
        lines.append("MISSING FROM MAP (registry has these but the map does not mention them):")
        for ev in result.missing_from_map:
            lines.append(f"  - {ev}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the telemetry map at docs/observability/telemetry-map.md "
            "agrees with the registry catalog at agent/config/registry/events/."
        )
    )
    parser.add_argument(
        "--map",
        default=str(_TELEMETRY_MAP),
        help=f"Path to the telemetry map markdown (default: {_TELEMETRY_MAP}).",
    )
    parser.add_argument(
        "--events-dir",
        default=str(_REGISTRY_EVENTS_DIR),
        help=(
            "Directory containing event registry yaml files "
            f"(default: {_REGISTRY_EVENTS_DIR})."
        ),
    )
    parser.add_argument(
        "--strict-bidirectional",
        action="store_true",
        help=(
            "Also fail when the registry declares events the map does not "
            "mention. Off by default — the map is intentionally a curated "
            "operator-facing subset, not an exhaustive list."
        ),
    )
    args = parser.parse_args(argv)

    map_path = Path(args.map)
    events_dir = Path(args.events_dir)

    if not map_path.is_file():
        print(
            f"check_telemetry_map: map not found: {map_path}",
            file=sys.stderr,
        )
        return 2
    if not events_dir.is_dir():
        print(
            f"check_telemetry_map: events dir not found: {events_dir}",
            file=sys.stderr,
        )
        return 2

    try:
        result = check(map_path.read_text(encoding="utf-8"), events_dir)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(
            f"check_telemetry_map: parse error: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    sys.stdout.write(render_text(result, strict_bidirectional=args.strict_bidirectional))

    if result.missing_from_registry:
        return 1
    if args.strict_bidirectional and result.missing_from_map:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
