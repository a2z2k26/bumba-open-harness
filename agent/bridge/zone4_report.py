"""Zone 4 operator report — cost, provider path, and reliability (Z4-23 #2449).

Reads the run manifests the Zone 4 pipeline persists under
``zone4_artifact_root`` (one ``<run-id>/manifest.json`` per run, written by
:func:`bridge.run_artifacts.create_run_workspace` and finalized by
``teams/_team.py::_finalize_run_relay``) and aggregates them by department
for a time window.

The report answers the operator's standing questions:

- Which teams ran, and how often?
- Which model providers did they use (primary vs fallback)?
- How many runs succeeded vs failed, and by what failure class?
- How many tokens did each department burn?
- Where do the artifacts live (manifest paths, not embedded bodies)?
- How long did runs take (average + longest)?

Design constraints (acceptance criteria, #2449):

- **Metadata only.** The loader reads each ``manifest.json`` and the
  telemetry block it carries — never the artifact bodies. The artifact byte
  totals come from the manifest's ``artifacts[].bytes`` field, not a file
  ``stat``/read. This keeps the report cheap regardless of artifact size.
- **Links, not bodies.** Each department report carries the list of manifest
  paths so the operator can drill into individual runs.
- **Degrades gracefully.** A missing root, an empty root, or a corrupt
  ``manifest.json`` never raises — corrupt manifests are counted in
  ``skipped_count`` and skipped.

Provider-path note (2026-05-21 context): 46/52 Zone 4 seats are configured
against an OpenRouter key that 401s at invocation. This report is the surface
the operator uses to *see* OpenRouter spend drift — the ``primary`` and
``fallback`` provider counts make the OpenRouter dependency visible and
quantified per the program's Definition of Done.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
)


# ---------------------------------------------------------------------------
# Report data classes (immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DepartmentReport:
    """Aggregate stats for one department over a window."""

    department: str
    runs: int
    success: int
    failure: int
    running: int
    failures_by_class: dict[str, int]
    primary_provider_counts: dict[str, int]
    fallback_provider_counts: dict[str, int]
    input_tokens: int
    output_tokens: int
    request_count: int
    artifact_count: int
    artifact_bytes: int
    missing_surface_count: int
    fallback_count: int
    average_duration_seconds: float
    longest_duration_seconds: float
    manifest_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "department": self.department,
            "runs": self.runs,
            "success": self.success,
            "failure": self.failure,
            "running": self.running,
            "failures": dict(self.failures_by_class),
            "providers": dict(self.primary_provider_counts),
            "fallback_providers": dict(self.fallback_provider_counts),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "request_count": self.request_count,
            "artifacts": self.artifact_count,
            "artifact_bytes": self.artifact_bytes,
            "missing_surfaces": self.missing_surface_count,
            "fallbacks": self.fallback_count,
            "average_duration_seconds": self.average_duration_seconds,
            "longest_duration_seconds": self.longest_duration_seconds,
            "manifest_paths": list(self.manifest_paths),
        }


@dataclass(frozen=True)
class Zone4Report:
    """Top-level report across all departments for a window."""

    window: str
    window_start_utc: str
    window_end_utc: str
    total_runs: int
    skipped_count: int
    departments: tuple[DepartmentReport, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "window": self.window,
            "window_start_utc": self.window_start_utc,
            "window_end_utc": self.window_end_utc,
            "total_runs": self.total_runs,
            "skipped_count": self.skipped_count,
            "departments": [d.to_dict() for d in self.departments],
        }


# ---------------------------------------------------------------------------
# Window parsing
# ---------------------------------------------------------------------------


def parse_window(
    window: str | None,
    *,
    since: str | None = None,
    until: str | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime, str]:
    """Resolve a window spec into (start, end, label).

    Either ``window`` ("24h" / "7d") or an explicit ``since`` + ``until``
    pair (ISO-8601) must be supplied. Explicit bounds win when both
    ``since`` and ``until`` are present.

    Raises ``ValueError`` on an unknown window token, an unparseable
    timestamp, or a since-after-until inversion.
    """
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if since is not None and until is not None:
        start_dt = _parse_ts(since)
        end_dt = _parse_ts(until)
        if start_dt > end_dt:
            raise ValueError(
                f"'since' ({since}) is after 'until' ({until})"
            )
        label = f"{since}..{until}"
        return start_dt, end_dt, label

    token = (window or "24h").strip().lower()
    if token == "24h":
        return end - timedelta(hours=24), end, "24h"
    if token == "7d":
        return end - timedelta(days=7), end, "7d"
    raise ValueError(
        f"Unknown window {window!r}; use '24h', '7d', or since+until."
    )


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_report(
    artifact_root: Path | str,
    *,
    window: str | None = None,
    since: str | None = None,
    until: str | None = None,
    now: datetime | None = None,
) -> Zone4Report:
    """Walk ``artifact_root/*/manifest.json`` and aggregate by department.

    Manifests whose ``completed_at_utc`` falls inside the resolved window
    are included; runs without a completion timestamp fall back to
    ``started_at_utc``. Corrupt manifests are skipped (counted), never
    fatal.
    """
    start, end, label = parse_window(
        window, since=since, until=until, now=now
    )

    root = Path(artifact_root).expanduser()
    accumulators: dict[str, _DeptAccumulator] = {}
    skipped = 0
    total = 0

    if root.is_dir():
        for manifest_path in sorted(root.glob("*/manifest.json")):
            payload = _read_manifest(manifest_path)
            if payload is None:
                skipped += 1
                continue
            ts = _run_timestamp(payload)
            if ts is None or not (start <= ts <= end):
                continue
            department = str(payload.get("department") or "unknown")
            acc = accumulators.setdefault(
                department, _DeptAccumulator(department)
            )
            acc.add(payload, manifest_path)
            total += 1

    departments = tuple(
        accumulators[name].finalize()
        for name in sorted(accumulators)
    )

    return Zone4Report(
        window=label,
        window_start_utc=_fmt(start),
        window_end_utc=_fmt(end),
        total_runs=total,
        skipped_count=skipped,
        departments=departments,
    )


# ---------------------------------------------------------------------------
# Internal accumulator (mutates only its own short-lived instance)
# ---------------------------------------------------------------------------


@dataclass
class _DeptAccumulator:
    department: str
    runs: int = 0
    success: int = 0
    failure: int = 0
    running: int = 0
    failures_by_class: Counter = field(default_factory=Counter)
    primary_providers: Counter = field(default_factory=Counter)
    fallback_providers: Counter = field(default_factory=Counter)
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    artifact_count: int = 0
    artifact_bytes: int = 0
    missing_surface_count: int = 0
    fallback_count: int = 0
    durations: list = field(default_factory=list)
    manifest_paths: list = field(default_factory=list)

    def add(self, payload: dict, manifest_path: Path) -> None:
        self.runs += 1
        self.manifest_paths.append(str(manifest_path))

        status = str(payload.get("status") or "").lower()
        if status == "success":
            self.success += 1
        elif status == "failed":
            self.failure += 1
        elif status == "running":
            self.running += 1

        telemetry = payload.get("telemetry") or {}
        if not isinstance(telemetry, dict):
            telemetry = {}

        failure_class = telemetry.get("failure_class")
        if failure_class:
            self.failures_by_class[str(failure_class)] += 1

        primary_model = str(telemetry.get("primary_model") or "")
        if primary_model:
            self.primary_providers[_provider_of(primary_model)] += 1

        fallback_model = telemetry.get("fallback_model")
        if fallback_model:
            self.fallback_providers[_provider_of(str(fallback_model))] += 1
            self.fallback_count += 1

        self.input_tokens += _int(telemetry.get("input_tokens"))
        self.output_tokens += _int(telemetry.get("output_tokens"))
        self.request_count += _int(telemetry.get("request_count"))
        self.durations.append(_float(telemetry.get("duration_seconds")))

        artifacts = payload.get("artifacts")
        if isinstance(artifacts, list):
            self.artifact_count += len(artifacts)
            for entry in artifacts:
                if isinstance(entry, dict):
                    self.artifact_bytes += _int(entry.get("bytes"))

        surfaces = payload.get("surfaces")
        surface_n = len(surfaces) if isinstance(surfaces, list) else 0
        if surface_n == 0:
            self.missing_surface_count += 1

    def finalize(self) -> DepartmentReport:
        avg = sum(self.durations) / len(self.durations) if self.durations else 0.0
        longest = max(self.durations) if self.durations else 0.0
        return DepartmentReport(
            department=self.department,
            runs=self.runs,
            success=self.success,
            failure=self.failure,
            running=self.running,
            failures_by_class=dict(self.failures_by_class),
            primary_provider_counts=dict(self.primary_providers),
            fallback_provider_counts=dict(self.fallback_providers),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            request_count=self.request_count,
            artifact_count=self.artifact_count,
            artifact_bytes=self.artifact_bytes,
            missing_surface_count=self.missing_surface_count,
            fallback_count=self.fallback_count,
            average_duration_seconds=avg,
            longest_duration_seconds=longest,
            manifest_paths=tuple(self.manifest_paths),
        )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _read_manifest(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — corrupt manifest is skipped, not fatal
        return None
    return payload if isinstance(payload, dict) else None


def _run_timestamp(payload: dict) -> datetime | None:
    raw = payload.get("completed_at_utc") or payload.get("started_at_utc")
    if not raw:
        return None
    try:
        return _parse_ts(str(raw))
    except ValueError:
        return None


def _parse_ts(value: str) -> datetime:
    text = value.strip()
    for fmt in _TS_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    # Last resort: fromisoformat handles a broader set of ISO strings.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unparseable timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _provider_of(model: str) -> str:
    """Return the provider segment of a ``provider:model`` string."""
    if ":" not in model:
        return model or "unknown"
    return model.split(":", 1)[0] or "unknown"


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
