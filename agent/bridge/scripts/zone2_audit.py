"""Zone 2 service health-state aggregator (Phase 3 Sprint 3.01 of #1112 plan).

Consumes #2076's authoritative service registry as inventory source. Reads each
service's state file from ``<state_dir>/<name>-state.json`` and produces both a
markdown report (operator-readable) and an optional JSON dump
(machine-readable).

NO recurring scheduling. NO remediation. JUST the aggregation pass.

Read-only invariant
-------------------
This script DOES NOT modify any state files. It opens state files in read mode
only; the only files it ever writes are the markdown report (``--out``) and the
optional JSON dump (``--json-out``). See ``tests/test_zone2_audit.py`` for the
invariant test (captures stat() before and after invocation).

State schema reference
----------------------
Canonical state-file fields live in
``agent/bridge/services/base.py::REQUIRED_STATE_FIELDS`` and are documented in
``agent/CLAUDE.md`` "Scheduled-service state-file schema". The fields we
consume here are a subset; unknown fields are ignored.

Registry shape
--------------
#2076 declared ``SERVICE_MAP`` in ``bridge/services/runner.py`` as the
authoritative code-as-registry. We import that map directly when available. If
the in-tree import fails (script invoked outside the agent root, or registry
JSON file is provided), we fall back in this order:

    1. ``--registry`` path, if it exists and parses as JSON.
    2. Plist scan: ``agent/config/launchdaemons/com.bumba.agent-*.plist``.

Each registry entry has the canonical shape ``{"service": str, "plist": str,
"schedule": str}``. Extra fields are ignored.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Per #1806 schema in agent/CLAUDE.md and base.py::REQUIRED_STATE_FIELDS.
HEALTH_FIELDS: tuple[str, ...] = (
    "last_run",
    "last_status",
    "last_error",
    "last_error_time",
    "consecutive_failures",
    "total_runs",
    "total_failures",
    "total_skipped",
    "last_skipped_at",
    "last_skipped_reason",
    "last_skipped_class",
    "last_duration_ms",
)

# Bucket order for rendering — higher-severity buckets first.
BUCKETS: tuple[str, ...] = ("broken", "degraded", "stale", "healthy", "no-data")

# Skip-classes that indicate the service has fallen idle waiting on an external
# precondition (credential / config / dependency drift). When the skip rate is
# above the stale threshold AND the most recent skip carries one of these
# classes, the service is bucketed "stale" rather than "healthy".
STALE_SKIP_CLASSES: frozenset[str] = frozenset({
    "missing_secret",
    "missing_config",
    "dependency_unavailable",
})

# Tunable thresholds — see PR description on #2143 for rationale. Operators
# may override at invocation via CLI; we lift them to module-level constants so
# tests can reference them without recomputation.
BROKEN_CONSECUTIVE_FAILURES = 5
DEGRADED_FAILURE_RATE = 0.05
STALE_SKIP_RATIO = 0.5


@dataclass(frozen=True)
class ServiceHealth:
    """Immutable health record for one service."""

    service: str
    plist: str
    schedule: str
    last_run: str | None
    last_status: str | None
    consecutive_failures: int
    total_runs: int
    total_failures: int
    total_skipped: int
    last_skipped_reason: str | None
    last_skipped_class: str | None
    last_duration_ms: int
    bucket: str  # one of BUCKETS


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(health_data: dict) -> str:
    """Bucket a single service by its state-file contents.

    Categories (in order of severity):

    * ``broken`` — ``consecutive_failures >= BROKEN_CONSECUTIVE_FAILURES``.
    * ``degraded`` — ``1 <= consecutive_failures < BROKEN_CONSECUTIVE_FAILURES``
      OR lifetime failure rate (``total_failures / total_runs``) exceeds
      ``DEGRADED_FAILURE_RATE``.
    * ``stale`` — skip ratio (skipped / (runs + skipped + failures)) exceeds
      ``STALE_SKIP_RATIO`` AND ``last_skipped_class`` is in
      ``STALE_SKIP_CLASSES``.
    * ``no-data`` — file missing OR all counters at default (service never
      executed).
    * ``healthy`` — anything else.

    The first matching category wins; we check severity-descending.
    """
    if not health_data:
        return "no-data"

    last_run = health_data.get("last_run")
    total_runs = health_data.get("total_runs", 0) or 0
    total_failures = health_data.get("total_failures", 0) or 0
    total_skipped = health_data.get("total_skipped", 0) or 0
    consecutive_failures = health_data.get("consecutive_failures", 0) or 0

    if last_run is None and total_runs == 0 and total_failures == 0 and total_skipped == 0:
        return "no-data"

    if consecutive_failures >= BROKEN_CONSECUTIVE_FAILURES:
        return "broken"

    if consecutive_failures >= 1:
        return "degraded"

    if total_runs > 0:
        failure_rate = total_failures / total_runs
        if failure_rate > DEGRADED_FAILURE_RATE:
            return "degraded"

    total = total_runs + total_skipped + total_failures
    if total > 0 and (total_skipped / total) > STALE_SKIP_RATIO:
        skip_class = health_data.get("last_skipped_class") or ""
        if skip_class in STALE_SKIP_CLASSES:
            return "stale"

    return "healthy"


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------


def _load_from_service_map() -> list[dict] | None:
    """Try importing ``SERVICE_MAP`` from ``bridge.services.runner``.

    Returns a list of registry entries with the canonical shape, or ``None``
    if the import fails. We deliberately swallow ``ImportError`` so the
    script remains useful in contexts where the bridge package is not on
    ``sys.path`` (e.g. invoked from outside the agent root).
    """
    try:
        from bridge.services.runner import SERVICE_MAP  # type: ignore[import-not-found]
        from bridge.services.result import SERVICE_SCHEDULES  # type: ignore[import-not-found]
    except Exception:
        return None

    entries: list[dict] = []
    for name in SERVICE_MAP:
        entries.append(
            {
                "service": name,
                "plist": f"com.bumba.agent-{name.replace('_', '-')}",
                "schedule": SERVICE_SCHEDULES.get(name, ""),
            }
        )
    return entries


def _load_from_plists(plist_dir: Path) -> list[dict]:
    """Last-resort fallback: enumerate plist files under ``plist_dir``."""
    if not plist_dir.exists():
        return []
    entries: list[dict] = []
    for plist_path in sorted(plist_dir.glob("com.bumba.agent-*.plist")):
        # com.bumba.agent-<service-name>.plist → <service-name>
        suffix = plist_path.stem[len("com.bumba.agent-") :]
        # Normalise hyphens to underscores so the name matches SERVICE_MAP keys.
        service = suffix.replace("-", "_")
        entries.append(
            {
                "service": service,
                "plist": plist_path.stem,
                "schedule": "see-plist",
            }
        )
    return entries


def load_service_registry(
    registry_path: Path,
    *,
    plist_dir: Path | None = None,
) -> list[dict]:
    """Resolve the service inventory.

    Resolution order:

    1. If ``registry_path`` exists and parses as a JSON list, use it.
    2. Otherwise, try importing ``SERVICE_MAP`` from the live bridge code.
    3. Otherwise, fall back to scanning ``plist_dir`` for
       ``com.bumba.agent-*.plist``.

    The function is read-only — it never writes to ``registry_path`` or
    creates new files.
    """
    if registry_path.exists():
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                # Normalise minimal shape; missing keys default to empty.
                return [
                    {
                        "service": entry["service"],
                        "plist": entry.get("plist", ""),
                        "schedule": entry.get("schedule", ""),
                    }
                    for entry in payload
                    if isinstance(entry, dict) and "service" in entry
                ]
        except (json.JSONDecodeError, OSError):
            # Fall through to import fallback.
            pass

    from_map = _load_from_service_map()
    if from_map is not None:
        return from_map

    if plist_dir is None:
        plist_dir = Path("agent/config/launchdaemons")
    return _load_from_plists(plist_dir)


# ---------------------------------------------------------------------------
# State gathering
# ---------------------------------------------------------------------------


def _read_state_file(state_file: Path) -> dict:
    """Read a state file in read-only mode. Returns ``{}`` on any error."""
    if not state_file.exists():
        return {}
    try:
        with state_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def gather_health(registry: Iterable[dict], state_dir: Path) -> list[ServiceHealth]:
    """Read state for every registry entry and return immutable records."""
    out: list[ServiceHealth] = []
    for entry in registry:
        name = entry["service"]
        state_file = state_dir / f"{name}-state.json"
        data = _read_state_file(state_file)
        out.append(
            ServiceHealth(
                service=name,
                plist=entry.get("plist", ""),
                schedule=entry.get("schedule", ""),
                last_run=data.get("last_run"),
                last_status=data.get("last_status"),
                consecutive_failures=int(data.get("consecutive_failures", 0) or 0),
                total_runs=int(data.get("total_runs", 0) or 0),
                total_failures=int(data.get("total_failures", 0) or 0),
                total_skipped=int(data.get("total_skipped", 0) or 0),
                last_skipped_reason=data.get("last_skipped_reason"),
                last_skipped_class=data.get("last_skipped_class"),
                last_duration_ms=int(data.get("last_duration_ms", 0) or 0),
                bucket=classify(data),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(rows: list[ServiceHealth], *, now: datetime | None = None) -> str:
    """Render a markdown report, ordered by severity bucket.

    ``now`` is injectable for deterministic tests; defaults to UTC current
    time.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    lines: list[str] = [
        "# Zone 2 service health audit",
        "",
        f"Generated: {now.isoformat()}",
        "",
        f"Total services: {len(rows)}",
        "",
    ]

    for bucket in BUCKETS:
        bucket_rows = [r for r in rows if r.bucket == bucket]
        if not bucket_rows:
            continue
        lines.append(f"## {bucket.title()} ({len(bucket_rows)})")
        lines.append("")
        lines.append(
            "| service | last_run | last_status | consec_fail | runs/fails/skips | last_skipped_reason |"
        )
        lines.append("|---|---|---|---|---|---|")
        for row in bucket_rows:
            lines.append(
                f"| `{row.service}` "
                f"| {row.last_run or '—'} "
                f"| {row.last_status or '—'} "
                f"| {row.consecutive_failures} "
                f"| {row.total_runs}/{row.total_failures}/{row.total_skipped} "
                f"| {row.last_skipped_reason or '—'} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate Zone 2 scheduled-service health state.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("agent/config/services-registry.json"),
        help=(
            "Optional JSON registry path. If missing, falls back to importing "
            "SERVICE_MAP from the bridge package, then to plist scanning."
        ),
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("data/service_state"),
        help="Directory containing <service>-state.json files.",
    )
    parser.add_argument(
        "--plist-dir",
        type=Path,
        default=Path("agent/config/launchdaemons"),
        help="Plist directory for the last-resort inventory fallback.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/audits/zone2-audit.md"),
        help="Markdown output path. Parent directory is created if missing.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional JSON dump of the full health record list.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Programmatic entrypoint; returns a shell-style exit code."""
    registry = load_service_registry(args.registry, plist_dir=args.plist_dir)
    rows = gather_health(registry, args.state_dir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(rows), encoding="utf-8")

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps([asdict(r) for r in rows], indent=2),
            encoding="utf-8",
        )

    print(f"Wrote {args.out} ({len(rows)} services)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":  # pragma: no cover - exercised via integration smoke
    sys.exit(main())
