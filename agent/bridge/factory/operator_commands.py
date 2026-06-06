"""Operator-command helpers for the Dark Factory loop (Sprint 14.11).

Concept-only port of coleam00/dark-factory-experiment — `concept-only-no-license`
(no LICENSE upstream, no source copied).

Purpose
-------
Plan 14 reached feature-complete status with PRs #1116 / #1117 / #1123 /
#1131 / #1134 / #1135 / #1136 / #1141 / #1144 / #1152 — but the operator
has no runtime visibility or control over the orchestrator's tick loop.
This module is the missing UX layer: a small set of pure helpers
(``is_paused``, ``pause``, ``resume``, ``collect_status``,
``escalate_issue``, ``format_status_for_discord``) that the new
``/factory`` operator command in :mod:`bridge.commands` composes.

Keeping the logic out of ``commands.py`` lets us unit-test the
mechanics without spinning up the full ``CommandHandler`` fixture, and
keeps ``commands.py`` from absorbing yet another factory subsystem.

The pause flag is a sentinel file at ``data/factory-paused.flag``
(operator-supplied path is honoured for tests). Both the production
orchestrator (:class:`bridge.services.factory_orchestrator.FactoryOrchestrator`)
and the shadow harness (:class:`bridge.factory.soak_harness.SoakHarness`)
check :func:`is_paused` at the top of their tick. A paused tick exits
cleanly with an explanatory error/log entry; no GitHub state is mutated.

Escalation routes a stuck issue (e.g. a per-target lock that has been
contended for hours) to ``factory:needs-human`` and posts an operator
comment naming the operator and reason.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bridge.factory.labels import FactoryState, get_state, transition_state

logger = logging.getLogger(__name__)


# Default repository — mirrors ``factory_orchestrator.DEFAULT_REPO``. Kept
# here as a separate constant so this module has no import-time
# dependency on the orchestrator (avoids a circular when commands.py
# eventually wires both modules).
DEFAULT_REPO = "your-org/bumba-open-harness"

# Pause flag — operators flip this via ``/factory pause``. Path is
# relative-by-design; the live caller passes an absolute path resolved
# from ``self._db.db_path.parent``. The relative default is convenient
# for unit tests that work in ``tmp_path``.
PAUSE_FLAG_PATH: Path = Path("data/factory-paused.flag")


# ── Result types ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FactoryStatus:
    """Aggregate status surfaced by ``/factory status``.

    Defensive defaults — every field has a sensible zero so a partial
    data-source failure never blows up the operator command.
    """

    orchestrator_enabled: bool
    paused: bool
    last_tick_at_iso: Optional[str]
    last_tick_cost_usd: float
    issues_processed_today: int
    issues_processed_this_week: int
    total_cost_today_usd: float
    total_cost_this_week_usd: float
    pending_accepted_count: int
    in_flight_count: int
    soak_ready_to_enable: bool
    soak_ready_reason: str
    paused_meta: dict[str, Any] = field(default_factory=dict)


# ── Pause flag helpers ──────────────────────────────────────────────────


def is_paused(flag_path: Path = PAUSE_FLAG_PATH) -> bool:
    """Return True iff the pause flag file currently exists.

    The mere existence is the signal — body content is metadata. Callers
    that want the metadata use :func:`read_pause_meta`.
    """
    return Path(flag_path).exists()


def read_pause_meta(flag_path: Path = PAUSE_FLAG_PATH) -> dict[str, Any]:
    """Best-effort read of pause metadata. Returns ``{}`` on any failure."""
    p = Path(flag_path)
    if not p.exists():
        return {}
    try:
        text = p.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        return json.loads(text)
    except (OSError, json.JSONDecodeError):
        # Pause is signalled by the file's presence — metadata corruption
        # must not flip pause off.
        return {}


def pause(
    flag_path: Path = PAUSE_FLAG_PATH,
    *,
    by: str = "operator",
    reason: str = "",
) -> None:
    """Atomically write the pause flag with timestamp + actor + reason.

    Written via temp-file + ``os.replace`` so a partial write can never
    leave a half-formed flag visible to a concurrent ``is_paused`` check.
    Metadata body is JSON: ``{"paused_at_iso", "by", "reason"}``.
    """
    p = Path(flag_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "paused_at_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "by": by,
        "reason": reason,
    }
    body = json.dumps(payload, sort_keys=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(p.parent), prefix=p.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp_path, p)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def resume(flag_path: Path = PAUSE_FLAG_PATH) -> bool:
    """Remove the pause flag. Returns True on removal, False if absent."""
    p = Path(flag_path)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        # Race — another caller cleared it between exists() and unlink().
        return False


# ── GitHub helper (small, no orchestrator dep) ──────────────────────────


def _run_gh_count_accepted(repo: str) -> int:
    """Return the count of open ``factory:accepted`` issues. 0 on any failure."""
    try:
        proc = subprocess.run(
            [
                "gh", "issue", "list",
                "--repo", repo,
                "--state", "open",
                "--label", FactoryState.ACCEPTED.value,
                "--json", "number",
                "--limit", "1000",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return 0
    if proc.returncode != 0:
        return 0
    try:
        rows = json.loads(proc.stdout) if proc.stdout.strip() else []
    except json.JSONDecodeError:
        return 0
    return len(rows) if isinstance(rows, list) else 0


def _run_gh_count_in_flight(repo: str) -> int:
    """Count issues in any in-flight factory state. 0 on any failure.

    Counts ``factory:in-progress`` plus the two fix-attempt labels so
    operators can see how many tasks are mid-pipeline. Each call is one
    ``gh`` invocation per label — three is fine for a status command.
    """
    total = 0
    for state in (
        FactoryState.IN_PROGRESS,
        FactoryState.FIX_ATTEMPT_1,
        FactoryState.FIX_ATTEMPT_2,
    ):
        try:
            proc = subprocess.run(
                [
                    "gh", "issue", "list",
                    "--repo", repo,
                    "--state", "open",
                    "--label", state.value,
                    "--json", "number",
                    "--limit", "1000",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except (FileNotFoundError, OSError):
            continue
        if proc.returncode != 0:
            continue
        try:
            rows = json.loads(proc.stdout) if proc.stdout.strip() else []
        except json.JSONDecodeError:
            continue
        if isinstance(rows, list):
            total += len(rows)
    return total


# ── Last-tick + cost summary helpers ────────────────────────────────────


def _read_last_run_tick(log_dir: Path) -> tuple[Optional[str], float]:
    """Return (last_tick_at_iso, last_tick_cost_usd) from last_run.json.

    Reads ``data/service_state/last_run.json`` (the runner's per-service
    record) for the ``factory_orchestrator`` entry. Returns (None, 0.0)
    on any failure.
    """
    last_run_path = log_dir / "service_state" / "last_run.json"
    if not last_run_path.exists():
        return (None, 0.0)
    try:
        with last_run_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return (None, 0.0)
    entry = data.get("factory_orchestrator") if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        return (None, 0.0)
    ts = entry.get("ts") or entry.get("timestamp_iso") or entry.get("at_iso")
    cost = entry.get("cost_usd", 0.0) or 0.0
    try:
        cost_f = float(cost)
    except (TypeError, ValueError):
        cost_f = 0.0
    return (str(ts) if ts else None, cost_f)


def _read_soak_status(
    soak_log_dir: Path,
    *,
    days: int = 14,
    min_correctness: float = 0.80,
    min_verified: int = 5,
) -> tuple[bool, str]:
    """Return (ready_to_enable, reason) by aggregating the soak window.

    Defensive — any failure (missing dir, malformed log, import error)
    collapses to (False, "<error>"). The caller surfaces the reason
    verbatim so operators can debug from the Discord output.
    """
    try:
        from bridge.factory.soak_harness import aggregate_soak_window
    except Exception as exc:  # pragma: no cover — defensive
        return (False, f"soak harness unavailable: {exc}")
    try:
        report = aggregate_soak_window(
            days=days,
            log_dir=soak_log_dir,
            min_correctness_rate=min_correctness,
            min_verified_count=min_verified,
        )
    except Exception as exc:
        return (False, f"soak aggregation failed: {exc}")
    return (
        bool(getattr(report, "ready_to_enable", False)),
        str(getattr(report, "ready_reason", "") or ""),
    )


def collect_status(
    *,
    orchestrator_enabled: bool,
    log_dir: Optional[Path] = None,
    soak_log_dir: Optional[Path] = None,
    flag_path: Path = PAUSE_FLAG_PATH,
    repo: str = DEFAULT_REPO,
    cost_tracker: object | None = None,
) -> FactoryStatus:
    """Assemble a :class:`FactoryStatus` from all available sources.

    Defensive by default — if a source is missing or raises, the
    corresponding field collapses to a sane zero so the operator command
    still renders.

    ``cost_tracker`` is the optional :class:`bridge.cost_tracker.CostTracker`
    instance held by ``CommandHandler``. We read its daily/weekly totals
    when present; otherwise totals are 0.0.
    """
    paused_now = is_paused(flag_path)
    paused_meta = read_pause_meta(flag_path) if paused_now else {}

    last_tick_iso, last_tick_cost = (
        _read_last_run_tick(log_dir) if log_dir is not None else (None, 0.0)
    )

    # Cost source — best-effort. The runtime cost tracker exposes
    # ``get_daily_summary`` + ``get_weekly_summary``; we don't filter by
    # service here because the orchestrator is one of several budget
    # consumers and the operator wants the total. A future enhancement
    # could add per-service attribution to CostTracker.
    total_today_usd = 0.0
    total_week_usd = 0.0
    if cost_tracker is not None:
        try:
            daily = cost_tracker.get_daily_summary()  # type: ignore[attr-defined]
            total_today_usd = float(daily.get("total_cost", 0.0) or 0.0)
        except Exception:
            total_today_usd = 0.0
        try:
            weekly = cost_tracker.get_weekly_summary()  # type: ignore[attr-defined]
            total_week_usd = float(weekly.get("total_cost", 0.0) or 0.0)
        except Exception:
            total_week_usd = 0.0

    # Issues-processed counters — derived from the soak JSONL when the
    # soak dir is supplied, else 0. The soak harness's daily files are
    # the most precise local source we have. Simple counts; no de-dupe.
    issues_today = 0
    issues_week = 0
    if soak_log_dir is not None:
        issues_today, issues_week = _count_processed_from_soak(soak_log_dir)

    pending_accepted = _run_gh_count_accepted(repo)
    in_flight = _run_gh_count_in_flight(repo)

    soak_ready, soak_reason = (
        _read_soak_status(soak_log_dir)
        if soak_log_dir is not None
        else (False, "soak directory not configured")
    )

    return FactoryStatus(
        orchestrator_enabled=bool(orchestrator_enabled),
        paused=paused_now,
        last_tick_at_iso=last_tick_iso,
        last_tick_cost_usd=last_tick_cost,
        issues_processed_today=issues_today,
        issues_processed_this_week=issues_week,
        total_cost_today_usd=total_today_usd,
        total_cost_this_week_usd=total_week_usd,
        pending_accepted_count=pending_accepted,
        in_flight_count=in_flight,
        soak_ready_to_enable=soak_ready,
        soak_ready_reason=soak_reason,
        paused_meta=paused_meta,
    )


def _count_processed_from_soak(soak_log_dir: Path) -> tuple[int, int]:
    """Count today's + this week's soak entries. (0, 0) on any failure."""
    p = Path(soak_log_dir)
    if not p.is_dir():
        return (0, 0)
    today = datetime.now(timezone.utc).date()
    today_count = 0
    week_count = 0
    try:
        for child in sorted(p.iterdir()):
            name = child.name
            # SOAK_LOG_NAME_FMT is ``soak-YYYY-MM-DD.jsonl`` per soak_harness.
            if not (name.startswith("soak-") and name.endswith(".jsonl")):
                continue
            date_str = name[len("soak-"):-len(".jsonl")]
            try:
                entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            age_days = (today - entry_date).days
            if age_days < 0 or age_days > 6:
                continue
            try:
                lines = child.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            line_count = sum(1 for line in lines if line.strip())
            week_count += line_count
            if entry_date == today:
                today_count += line_count
    except OSError:
        return (0, 0)
    return (today_count, week_count)


# ── Escalation ──────────────────────────────────────────────────────────


def escalate_issue(
    issue_number: int,
    *,
    reason: str,
    actor: str = "operator",
    repo: str = DEFAULT_REPO,
    transition_fn: Any = None,
    comment_fn: Any = None,
) -> dict[str, Any]:
    """Manually transition an issue to ``factory:needs-human``.

    Returns a dict describing the action:

      * ``issue_number``,
      * ``prior_state`` (str | None) — the state we observed,
      * ``new_state`` (str) — always ``factory:needs-human`` on success,
      * ``transitioned`` (bool) — True iff the label move succeeded,
      * ``comment_posted`` (bool) — best-effort, True iff ``gh`` returned 0.

    Never raises. Failures land in the dict so the operator command can
    surface them. ``transition_fn`` / ``comment_fn`` are injection seams
    for tests; defaults call the real ``gh`` CLI via
    :func:`bridge.factory.labels.transition_state` and a local
    ``gh issue comment`` invocation.
    """
    if transition_fn is None:
        transition_fn = transition_state
    if comment_fn is None:
        comment_fn = _gh_issue_comment

    # Read the current state so we can pass it as ``from_state`` to the
    # optimistic transition. ``get_state`` returns None if no factory
    # state label is set, which is a valid input.
    try:
        prior = get_state(issue_number)
    except Exception as e:
        logger.warning(
            "operator_commands: get_state(#%s) raised: %s — proceeding with from_state=None",
            issue_number, e,
        )
        prior = None
    prior_state_str = prior.value if isinstance(prior, FactoryState) else None

    transitioned = False
    try:
        transitioned = bool(
            transition_fn(issue_number, prior, FactoryState.NEEDS_HUMAN)
        )
    except Exception as e:
        logger.exception(
            "operator_commands: transition #%s → needs-human raised: %s",
            issue_number, e,
        )

    comment_body = (
        f"**Factory operator escalation** — manually routed to "
        f"`{FactoryState.NEEDS_HUMAN.value}` by `{actor}`.\n\n"
        f"_Reason:_ {reason or '(no reason provided)'}\n\n"
        "---\n_concept-only-no-license — Dark Factory_"
    )
    comment_posted = False
    try:
        comment_posted = bool(
            comment_fn(issue_number=issue_number, body=comment_body, repo=repo)
        )
    except Exception as e:
        logger.warning(
            "operator_commands: comment on #%s raised: %s", issue_number, e
        )

    return {
        "issue_number": issue_number,
        "prior_state": prior_state_str,
        "new_state": FactoryState.NEEDS_HUMAN.value,
        "transitioned": transitioned,
        "comment_posted": comment_posted,
    }


def _gh_issue_comment(*, issue_number: int, body: str, repo: str) -> bool:
    """Post a comment on an issue via ``gh``. Returns True on rc==0."""
    try:
        proc = subprocess.run(
            [
                "gh", "issue", "comment", str(issue_number),
                "--repo", repo, "--body", body,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as e:
        logger.warning("operator_commands: gh not available: %s", e)
        return False
    if proc.returncode != 0:
        logger.warning(
            "operator_commands: gh issue comment #%s failed (rc=%s): %s",
            issue_number, proc.returncode, proc.stderr.strip()[:200],
        )
        return False
    return True


# ── Discord rendering ───────────────────────────────────────────────────


def format_status_for_discord(status: FactoryStatus) -> str:
    """Render :class:`FactoryStatus` as a multi-line markdown block.

    Output is bounded — under Discord's 2000-char ceiling for plausible
    inputs. The format is operator-tuned: top line summarizes prod state,
    sub-blocks call out paused/cost/queue/soak signals.
    """
    enabled_str = "ENABLED" if status.orchestrator_enabled else "DISABLED"
    pause_str = "PAUSED" if status.paused else "running"
    soak_str = (
        "READY TO ENABLE" if status.soak_ready_to_enable else "NOT READY"
    )

    lines = [
        f"**Factory status** — orchestrator **{enabled_str}**, **{pause_str}**",
        "",
    ]

    if status.paused and status.paused_meta:
        meta = status.paused_meta
        by = meta.get("by", "?")
        reason = meta.get("reason", "") or "(no reason)"
        at = meta.get("paused_at_iso", "?")
        lines.append(f"_Paused by `{by}` at {at} — {reason}_")
        lines.append("")

    last_at = status.last_tick_at_iso or "never"
    lines.extend([
        f"**Last tick**: {last_at} (cost ${status.last_tick_cost_usd:.4f})",
        "",
        "**Throughput**:",
        f"  • Today: {status.issues_processed_today} issue(s)",
        f"  • Last 7 days: {status.issues_processed_this_week} issue(s)",
        "",
        "**Cost**:",
        f"  • Today: ${status.total_cost_today_usd:.4f}",
        f"  • Last 7 days: ${status.total_cost_this_week_usd:.4f}",
        "",
        "**Queue**:",
        f"  • Pending `factory:accepted`: {status.pending_accepted_count}",
        f"  • In-flight: {status.in_flight_count}",
        "",
        f"**Soak harness**: {soak_str}",
    ])
    if status.soak_ready_reason:
        lines.append(f"  _{status.soak_ready_reason}_")

    return "\n".join(lines)


__all__ = [
    "DEFAULT_REPO",
    "FactoryStatus",
    "PAUSE_FLAG_PATH",
    "collect_status",
    "escalate_issue",
    "format_status_for_discord",
    "is_paused",
    "pause",
    "read_pause_meta",
    "resume",
]
