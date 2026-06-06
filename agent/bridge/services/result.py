"""ServiceResult — uniform output contract for every Zone 2 service.

This is BET 1 (the keystone). Every service returns one of these. The
structured completion line written to the log is what /services, monitor.sh,
and the future event bus all read. The per-service aggregate at
data/service_state/last_run.json gives operators an at-a-glance status.

Spec: docs/specs/2026-04-17-zone2-sprint-plan.md → Sprint S0.1 (GitHub #492).
S2.4 extension: render_service_detail() + SERVICE_NARRATIONS (GitHub #496).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServiceResult:
    """Typed return value of every scheduled-service ``run()`` method.

    Fields are designed to be forward-compatible with Zone 3's ``WorkOrder``
    and Zone 4's ``TeamResult`` so downstream observability stays uniform.
    """

    service: str
    ok: bool
    work_items: int
    duration_ms: int
    cost_usd: float
    # Paths or knowledge_store keys produced by the run.
    artifacts: tuple[str, ...] = ()
    # Short tags for anomalies: "oauth_401", "empty_payload", etc.
    anomalies: tuple[str, ...] = ()
    # Set to a short reason when the run was a correct no-op.
    skip_reason: str | None = None
    # Optional human-readable one-liner for Discord narration (S2.4 / S4.3).
    narration: str | None = None


def format_completion_line(r: ServiceResult) -> str:
    """Render ``r`` as the structured ``[SERVICE][...]`` log line.

    Three shapes:
        [SERVICE][OK   <name> work_items=N duration=Xs cost=$Y[ anomalies=...]]
        [SERVICE][FAIL <name> work_items=N duration=Xs cost=$Y[ anomalies=...]]
        [SERVICE][SKIP <name> reason=<why> duration=Xs]

    All three share the prefix ``[SERVICE][(OK|FAIL|SKIP) `` so a single regex
    is sufficient for log grep (FR-008).
    """
    dur_s = r.duration_ms / 1000
    if r.skip_reason:
        return (
            f"[SERVICE][SKIP {r.service} reason={r.skip_reason} "
            f"duration={dur_s:.1f}s]"
        )
    tag = "OK" if r.ok else "FAIL"
    base = (
        f"[SERVICE][{tag} {r.service} work_items={r.work_items} "
        f"duration={dur_s:.1f}s cost=${r.cost_usd:.2f}"
    )
    if r.anomalies:
        base += f" anomalies={','.join(r.anomalies)}"
    return base + "]"


def write_last_run(state_dir: Path, r: ServiceResult) -> None:
    """Atomically merge ``r`` into ``<state_dir>/last_run.json``.

    Uses tempfile + ``os.replace`` for crash-safe writes (matches the pattern
    in ``base.py``/``runner.py``). Corrupted existing JSON resets to ``{}``
    rather than raising — the edge-case spec requires graceful recovery.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "last_run.json"

    try:
        existing = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(existing, dict):
            existing = {}
    except (json.JSONDecodeError, OSError):
        existing = {}

    existing[r.service] = {
        "ok": r.ok,
        "work_items": r.work_items,
        "duration_ms": r.duration_ms,
        "cost_usd": r.cost_usd,
        "artifacts": list(r.artifacts),
        "anomalies": list(r.anomalies),
        "skip_reason": r.skip_reason,
        "narration": r.narration,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "completion_line": format_completion_line(r),
    }

    fd, tmp = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(existing, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_cumulative_state(data_dir: Path, service_name: str) -> dict[str, Any]:
    """Read the per-service cumulative state file ``<name>-state.json``.

    Board Phase 1 metering (#2390): the cumulative ``total_cost_usd`` /
    ``total_runs`` ledger lives in ``service_state/<name>-state.json``
    (written by ``ServiceBase.record_success``), NOT in ``last_run.json``
    (which is per-run only). Returns ``{}`` when the file is absent or
    unreadable so callers degrade gracefully.
    """
    path = data_dir / "service_state" / f"{service_name}-state.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def render_services_table(data_dir: Path) -> str:
    """Render ``data/service_state/last_run.json`` as a Discord-friendly block.

    Returns a user-facing message suitable for replying to the ``/services``
    slash command. Safe to call even when the file does not yet exist — the
    operator gets a "no runs recorded yet" hint instead of an error.

    Board Phase 1 metering (#2390): each line is annotated with the
    cumulative spend for that service, read from ``<name>-state.json``.
    """
    path = data_dir / "service_state" / "last_run.json"
    if not path.exists():
        return "No service runs recorded yet — check back after the first scheduled run."

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return f"Could not read last_run.json: {e}"

    if not isinstance(data, dict) or not data:
        return "No service runs recorded yet."

    lines = ["**Service Status** (most recent run per service):", "```"]
    for name in sorted(data.keys()):
        entry = data[name] if isinstance(data[name], dict) else {}
        line = entry.get("completion_line")
        if not line:
            line = f"{name}: (no completion line)"
        cumulative = _read_cumulative_state(data_dir, name)
        total_cost = cumulative.get("total_cost_usd")
        if isinstance(total_cost, (int, float)):
            line = f"{line} cumulative=${float(total_cost):.2f}"
        lines.append(line)
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# S2.4 — Per-service detail view
# ---------------------------------------------------------------------------

# Static narration strings shown when a service has not yet populated its own.
# Keys match the service names in SERVICE_MAP (runner.py).
SERVICE_NARRATIONS: dict[str, str] = {
    "briefing":              "Delivers the morning briefing: goals, calendar, and any drift flags.",
    "checkin":               "Mid-day check-in pulse — confirms the bridge is alive and responsive.",
    "email":                 "Scans Gmail every 2 hours and surfaces messages that need attention.",
    "calendar":              "Monitors cal.com for new bookings and upcoming events.",
    "knowledge_review":      "Reviews the knowledge store nightly and prunes stale entries.",
    "retro":                 "End-of-day retrospective — logs wins, blockers, and follow-ups.",
    "weekly_review":         "Sunday summary: week in review, next-week priorities.",
    "job_search":            "Morning PREPARE run: scrapes boards, generates cover letters, stages in Notion.",
    "job_search_execute":    "Checks Notion for operator-approved outreach and sends emails.",
    "consolidation":         "Deep-consolidation pass: summarises daily logs into the knowledge store.",
    "inbox_nurture":         "Daily inbox scan: picks the most actionable unanswered thread and drafts one reply for operator approval.",
    "subscription_tracker":  "Scans Gmail for subscription renewal emails, maintains subscriptions.json, and posts a weekly cost summary.",
    "project_pulse":         "Nightly repo-health report: last commit, open PRs by age, stale flags across all configured repos.",
    "funnel_post":           "Nightly 22:00 post: summarises the day's job-search funnel (scraped → sent) to Discord.",
    "meeting_prebrief":      "Posts a Discord prebrief card 30 minutes before every Cal.com meeting; event-driven on calcom.booking.created with a 10-minute polling fallback.",
    "factory_orchestrator":  "Dark Factory production loop: spawns work orders from queued specs every 4 hours (gate-flagged).",
    "factory_soak":          "Dark Factory shadow/soak harness: observe-only mirror of the orchestrator every 4 hours (gate-flagged).",
    "zone1_drift":           "Scans Zone 1 doctrine files for stale counts, dead references, and outdated verification stamps; drafts findings for operator review.",
    "weekly_ceo_review":     "Monday CEO review workflow: triggers the weekly-ceo-review WorkflowEngine run.",
}

# Approximate next-run schedule descriptions (static — for display only).
SERVICE_SCHEDULES: dict[str, str] = {
    "briefing":              "Daily at 08:00",
    "checkin":               "Multiple daily check-ins",
    "email":                 "Every 2 hours",
    "calendar":              "Every 15 minutes",
    "knowledge_review":      "Daily at 23:00",
    "retro":                 "Daily at 18:00",
    "weekly_review":         "Sunday at 18:00",
    "job_search":            "Daily at 08:00",
    "job_search_execute":    "Every 2 hours, 10:00–20:00",
    "consolidation":         "Nightly (variable)",
    "inbox_nurture":         "Daily at 09:15",
    "subscription_tracker":  "Daily at 11:00; weekly summary Sunday at 17:00",
    "project_pulse":         "Daily at 23:30",
    "funnel_post":           "Daily at 22:00",
    "meeting_prebrief":      "event-driven (calcom.booking.created) + poll every 10 min",
    "factory_orchestrator":  "Every 4 hours",
    "factory_soak":          "Every 4 hours",
    "zone1_drift":           "Monday and Thursday at 09:00",
    "weekly_ceo_review":     "Monday at 08:00 UTC",
}


def render_service_detail(data_dir: Path, service_name: str) -> str:
    """Render a single-service detail block for ``/services <name>``.

    Shows: narration, last run time, last result, next scheduled run,
    artifacts, and anomalies.

    Returns an error message when the service name is unknown or has no data.
    """
    # Validate service name — list known names from both SERVICE_NARRATIONS and
    # any data already recorded.
    path = data_dir / "service_state" / "last_run.json"
    recorded: dict[str, dict[str, Any]] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text())
            recorded = raw if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError):
            pass

    known_names = set(SERVICE_NARRATIONS.keys()) | set(recorded.keys())

    if service_name not in known_names:
        available = ", ".join(sorted(known_names)) or "(none yet)"
        return (
            f"Unknown service: `{service_name}`.\n"
            f"Available: {available}"
        )

    entry: dict[str, Any] = recorded.get(service_name, {})
    narration: str | None = entry.get("narration") or SERVICE_NARRATIONS.get(service_name)
    schedule: str = SERVICE_SCHEDULES.get(service_name, "unknown schedule")

    lines: list[str] = [f"**Service: `{service_name}`**"]

    # Narration
    if narration:
        # Truncate at 1800 chars to stay within Discord's 2000-char limit.
        narration_display = narration[:1800] + "…" if len(narration) > 1800 else narration
        lines.append(f"_{narration_display}_")

    lines.append("")

    if not entry:
        lines.append("No run data recorded yet.")
        lines.append(f"Next scheduled: {schedule}")
        return "\n".join(lines)

    # Last run time
    completed_at: str = entry.get("completed_at", "")
    if completed_at:
        lines.append(f"**Last run:** {completed_at}")

    # Result summary
    completion_line: str = entry.get("completion_line", "")
    if completion_line:
        lines.append(f"**Result:** `{completion_line}`")

    # Cumulative metering (Board Phase 1, #2390) — lifetime spend + run count
    # from <name>-state.json (not last_run.json).
    cumulative = _read_cumulative_state(data_dir, service_name)
    total_cost = cumulative.get("total_cost_usd")
    total_runs = cumulative.get("total_runs")
    if isinstance(total_cost, (int, float)):
        runs_part = (
            f" across {int(total_runs)} runs"
            if isinstance(total_runs, (int, float))
            else ""
        )
        lines.append(f"**Cumulative cost:** ${float(total_cost):.2f}{runs_part}")

    # Anomalies
    anomalies: list[str] = entry.get("anomalies") or []
    if anomalies:
        lines.append(f"**Anomalies:** {', '.join(anomalies)}")

    # Artifacts
    artifacts: list[str] = entry.get("artifacts") or []
    if artifacts:
        lines.append(f"**Artifacts:** {', '.join(str(a) for a in artifacts[:5])}")

    # Next scheduled
    lines.append(f"**Next scheduled:** {schedule}")

    return "\n".join(lines)


__all__ = [
    "ServiceResult",
    "format_completion_line",
    "render_services_table",
    "render_service_detail",
    "write_last_run",
    "SERVICE_NARRATIONS",
    "SERVICE_SCHEDULES",
]
