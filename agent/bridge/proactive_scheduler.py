"""Perpetual-proactive scheduler — work selection from the dep-graph.

D7.12 #1424 (slice 1) — addresses operator-friction finding F-Opt
("perpetual proactivity"). The strategic ask reduced to one mechanism:
between operator turns, when no interrupt is pending and budget allows,
pick the next-highest-value work item from the sprint dependency graph
and queue it for autonomous execution.

This module ships **slice 1** — the work-selection layer + activity
ledger. It is pure-function and append-only-write; it does NOT spawn
subagents, does NOT open PRs. The scheduler runs in dry-run mode by
default so the selection logic can be observed in production for a
soak window before slice 2 turns on dispatch.

Architecture:

    BridgeApp._proactive_scheduler_loop  (background asyncio task)
              │
              ├─ should_skip_tick(inbox, budget, halt) → reason | None
              │      │ inbox has pending → "operator_dialogue_active"
              │      │ budget > threshold → "budget_pressure"
              │      │ halt flag set     → "halted"
              │      └─ none of the above → None (proceed)
              │
              ├─ select_next_work_item(graph, candidates_filter)
              │      │ load docs/sprint-dependency-graph.json
              │      │ filter: state=open, all prereqs in `closed_issues`,
              │      │         labels intersect with allowed labelset,
              │      │         severity ∉ {critical, high}
              │      └─ returns WorkItem or None
              │
              └─ append_to_ledger(action, work_item, reason)
                       writes one JSON row to data/proactive-activity.jsonl

The slice-2 dispatch surface (subagent spawn + [autonomous] PR open)
hooks here — the scheduler invokes a callable after a successful pick
when ``dispatch_callback`` is wired in. Slice 1 ships with that
callback always None, so the dry-run path is the only path.

Why a separate module from `tick_manager.py`:

    TickManager injects <tick> prompts into the running Claude session
    so the agent decides what to do next. That's a *prompt-injection*
    proactive surface — agent-driven choice. The scheduler is the
    *bridge-driven* counterpart: the bridge decides what work to start,
    spawns it as an isolated subagent (slice 2), and only surfaces
    finished work to the operator. They're peers, not layers — both can
    run, and they're observed via different ledgers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from bridge.halt import HaltPolicy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skip reasons — exhaustive enumeration so the ledger is filterable
# ---------------------------------------------------------------------------

SKIP_OPERATOR_DIALOGUE = "operator_dialogue_active"
SKIP_BUDGET_PRESSURE = "budget_pressure"
SKIP_HALTED = "halted"
SKIP_NO_GRAPH = "graph_unavailable"
SKIP_NO_CANDIDATES = "no_eligible_work_items"


# Labels that are STRONG signals a sprint is too risky for autonomous
# pickup. The slice-1 scheduler refuses to surface these regardless of
# other state. Slice 2 will widen the safe-set as confidence grows.
_RISKY_LABELS: frozenset[str] = frozenset(
    {
        "severity:critical",
        "severity:high",
        "priority:keystone",
        "exec:operator",       # operator-only chains (D6-bis, rtk, Z3 flips)
        "exec:mac-mini",       # operator-gated
        "blocked",
        "needs-operator",
    }
)

# Labels that mark a sprint as a SAFE candidate for autonomous pickup
# in slice 1. The intersection is required: at least one of these must
# be present. Conservative on purpose — the soak window will tell us
# whether to widen.
_SAFE_LABELS: frozenset[str] = frozenset(
    {
        "size/S",
        "size/XS",
        "operator-friction",   # the D7 audit family — well-scoped
        "phase-d-7",
        "good-first-issue",
        "type:docs",
        "type:test",
    }
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkItem:
    """One sprint the scheduler picked as next-best autonomous work."""
    number: int
    title: str
    labels: tuple[str, ...]
    slug: str | None
    prereq_numbers: tuple[int, ...]


@dataclass
class ProactiveTickReport:
    """Outcome of one scheduler tick."""
    action: str  # "skipped" | "picked" | "dispatched"
    work_item: WorkItem | None
    reason: str  # skip reason or pick rationale
    timestamp: float = field(default_factory=lambda: time.time())


# ---------------------------------------------------------------------------
# Skip checks — each pure
# ---------------------------------------------------------------------------


async def should_skip_tick(
    *,
    inbox_pending_count: int,
    daily_spend_fraction: float,
    budget_threshold: float,
    halt_flag_present: bool,
) -> str | None:
    """Return a skip reason if the scheduler must abort this tick, else None.

    Order matters — the highest-priority reason wins. Operator dialogue
    pre-empts everything (D7.9 doctrine: operator messages are the
    highest-priority interrupt). Halt is checked second because a halted
    bridge should not be making *any* autonomous decisions.
    """
    if inbox_pending_count > 0:
        return SKIP_OPERATOR_DIALOGUE
    if halt_flag_present:
        return SKIP_HALTED
    if daily_spend_fraction >= budget_threshold:
        return SKIP_BUDGET_PRESSURE
    return None


# ---------------------------------------------------------------------------
# Work selection — pure-function over the dep-graph JSON
# ---------------------------------------------------------------------------


def load_graph(graph_path: Path) -> dict[str, Any] | None:
    """Read the dep-graph JSON. Returns None if the file is missing or
    malformed — the scheduler logs a `graph_unavailable` skip in that case
    rather than crashing the bridge.
    """
    if not graph_path.exists():
        return None
    try:
        return json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "proactive_scheduler: dep-graph at %s unreadable: %s",
            graph_path,
            exc,
        )
        return None


def _is_safe_candidate(node: dict[str, Any]) -> bool:
    """A node is a safe-set candidate when it has NO risky label AND
    at least one safe label.
    """
    labels = set(node.get("labels", []) or [])
    if labels & _RISKY_LABELS:
        return False
    return bool(labels & _SAFE_LABELS)


def _prereqs_for(node_number: int, edges: list[dict[str, Any]]) -> list[int]:
    """Collect prereq issue numbers for a node from the edge list."""
    return [
        e["from"]
        for e in edges
        if e.get("kind") == "prereq" and e.get("to") == node_number
    ]


def select_next_work_item(
    graph: dict[str, Any],
    *,
    closed_issues: Iterable[int] = (),
    skip_numbers: Iterable[int] = (),
) -> WorkItem | None:
    """Pick the next-highest-value safe work item from the dep-graph.

    Selection rules (in priority order):
      1. Node must pass `_is_safe_candidate` (safe-label, no risky-label)
      2. All prereq edges must terminate in a `closed_issues` member
      3. Node number must NOT be in `skip_numbers` (caller-supplied
         dedup — e.g. recently-picked ledger entries)
      4. Among eligible nodes, prefer the one with the FEWEST prereqs
         (closest to a leaf — most likely to actually be ready). Tie-
         break on lower issue number for determinism.

    Returns None when no eligible work item exists.
    """
    nodes: list[dict[str, Any]] = graph.get("nodes", []) or []
    edges: list[dict[str, Any]] = graph.get("edges", []) or []
    closed = set(closed_issues)
    skip = set(skip_numbers)

    eligible: list[tuple[int, int, dict[str, Any], list[int]]] = []
    for node in nodes:
        n = node["number"]
        if n in skip:
            continue
        if not _is_safe_candidate(node):
            continue
        prereqs = _prereqs_for(n, edges)
        if any(p not in closed for p in prereqs):
            continue
        eligible.append((len(prereqs), n, node, prereqs))

    if not eligible:
        return None

    eligible.sort(key=lambda t: (t[0], t[1]))
    _, _, picked, prereqs = eligible[0]
    return WorkItem(
        number=picked["number"],
        title=picked["title"],
        labels=tuple(picked.get("labels", []) or []),
        slug=picked.get("slug"),
        prereq_numbers=tuple(prereqs),
    )


# ---------------------------------------------------------------------------
# Activity ledger — append-only JSONL
# ---------------------------------------------------------------------------


def append_to_ledger(ledger_path: Path, report: ProactiveTickReport) -> None:
    """Write one report row to the proactive-activity ledger.

    Best-effort: a write failure logs a warning but does not raise.
    The ledger is observability — losing one row is far cheaper than
    crashing the scheduler loop.
    """
    entry: dict[str, Any] = {
        "ts": report.timestamp,
        "iso_ts": datetime.fromtimestamp(
            report.timestamp, tz=timezone.utc
        ).isoformat(),
        "action": report.action,
        "reason": report.reason,
    }
    if report.work_item is not None:
        entry["work_item"] = {
            "number": report.work_item.number,
            "title": report.work_item.title,
            "slug": report.work_item.slug,
            "prereq_count": len(report.work_item.prereq_numbers),
        }
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        logger.warning(
            "proactive_scheduler: ledger write failed (non-fatal): %s",
            exc,
        )


def read_ledger_window(
    ledger_path: Path, *, since_ts: float, max_rows: int = 1000
) -> list[dict[str, Any]]:
    """Read the last ``max_rows`` ledger entries newer than ``since_ts``.

    Returns an empty list if the ledger is missing — the scheduler may
    not have run yet.
    """
    if not ledger_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("ts", 0) >= since_ts:
                    rows.append(row)
    except OSError:
        return []
    if len(rows) > max_rows:
        rows = rows[-max_rows:]
    return rows


def summarize_ledger_for_status(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Roll up ledger rows for /proactive status.

    Returns counts by action + reason + the last 5 picks (for the late-
    night-profile shape from D7.11 — phone-readable in one screen).
    """
    by_action: dict[str, int] = {}
    by_skip_reason: dict[str, int] = {}
    last_picks: list[dict[str, Any]] = []
    for row in rows:
        action = row.get("action", "unknown")
        by_action[action] = by_action.get(action, 0) + 1
        if action == "skipped":
            reason = row.get("reason", "unknown")
            by_skip_reason[reason] = by_skip_reason.get(reason, 0) + 1
        elif action in ("picked", "dispatched"):
            wi = row.get("work_item")
            if wi:
                last_picks.append({
                    "number": wi.get("number"),
                    "title": wi.get("title"),
                    "iso_ts": row.get("iso_ts"),
                })
    last_picks = last_picks[-5:]
    return {
        "total_ticks": sum(by_action.values()),
        "by_action": by_action,
        "by_skip_reason": by_skip_reason,
        "last_picks": last_picks,
    }


# ---------------------------------------------------------------------------
# Weekly digest (D7.12 slice 3 #1424)
# ---------------------------------------------------------------------------
#
# Idempotent rolling markdown digest at `data/weekly-digest.md`. Each
# week-of-year gets exactly one section; re-rendering the same week
# replaces the existing section in place (no duplication, no append-only
# growth). The trigger is the first scheduler tick after a Sunday-18:00
# UTC boundary — cheap because the loop is already running.
#
# Section format (phone-readable; ~10-15 lines per week):
#
#     ## Week of 2026-05-04 (week 19)
#
#     - Ticks: 672  (skipped: 671, picked: 1, dispatched: 0)
#     - Skip reasons: operator_dialogue_active=410, no_eligible_work_items=261
#     - Picks (last 5):
#       - #42: Sprint D7.99 — example  (2026-05-08T03:14)
#     - Notes: dispatch was off this week; selection observed in dry-run.

# ISO week section anchor pattern — used to locate + replace existing
# sections without disturbing other weeks.
_WEEK_HEADER_PATTERN = "## Week of "


def _iso_week_key(ts: float) -> tuple[int, int]:
    """Return (iso_year, iso_week) for a Unix timestamp (UTC).

    ISO week-numbering: weeks start Monday, week 1 is the week containing
    the first Thursday of the year. We use ISO so a digest covering Sunday
    of week N + Monday of week N+1 doesn't end up in a numerically-confusing
    "week 53" or "week 0" shape.
    """
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    iso_year, iso_week, _ = dt.isocalendar()
    return iso_year, iso_week


def _week_start_ts(iso_year: int, iso_week: int) -> float:
    """Return the Unix timestamp of Monday 00:00 UTC for the given ISO week."""
    # ISO weekday for Monday is 1
    dt = datetime.fromisocalendar(iso_year, iso_week, 1).replace(tzinfo=timezone.utc)
    return dt.timestamp()


def render_weekly_digest_section(
    *,
    iso_year: int,
    iso_week: int,
    rows: list[dict[str, Any]],
    dispatch_active: bool,
) -> str:
    """Render one week's digest section as markdown.

    The section is self-contained (begins with `## Week of ...`, ends with
    a trailing newline). `rows` should already be filtered to the week in
    question — the renderer doesn't re-filter.
    """
    week_start = _week_start_ts(iso_year, iso_week)
    week_start_iso = datetime.fromtimestamp(
        week_start, tz=timezone.utc
    ).strftime("%Y-%m-%d")
    summary = summarize_ledger_for_status(rows)
    lines: list[str] = []
    lines.append(f"## Week of {week_start_iso} (week {iso_week})")
    lines.append("")

    by_action = summary["by_action"]
    total = summary["total_ticks"]
    action_breakdown = ", ".join(
        f"{k}: {v}" for k, v in sorted(by_action.items())
    ) or "—"
    lines.append(f"- Ticks: {total}  ({action_breakdown})")

    by_skip = summary["by_skip_reason"]
    if by_skip:
        skip_breakdown = ", ".join(
            f"{k}={v}" for k, v in sorted(
                by_skip.items(), key=lambda kv: -kv[1]
            )
        )
        lines.append(f"- Skip reasons: {skip_breakdown}")

    picks = summary["last_picks"]
    if picks:
        lines.append("- Picks (last 5):")
        for p in picks:
            num = p.get("number")
            title = (p.get("title") or "")[:60]
            iso_ts = (p.get("iso_ts") or "")[:16]  # YYYY-MM-DDTHH:MM
            lines.append(f"  - #{num}: {title}  ({iso_ts})")
    else:
        lines.append("- Picks: none this week")

    if not dispatch_active:
        lines.append(
            "- Notes: dispatch was off this week; selection observed in dry-run."
        )
    elif by_action.get("dispatched", 0) == 0:
        lines.append(
            "- Notes: dispatch enabled but nothing was posted "
            "(no eligible work landed during operator-idle windows)."
        )

    lines.append("")
    return "\n".join(lines)


def upsert_weekly_digest(
    digest_path: Path,
    *,
    iso_year: int,
    iso_week: int,
    rows: list[dict[str, Any]],
    dispatch_active: bool,
) -> None:
    """Write or replace the section for ``(iso_year, iso_week)`` at
    ``digest_path``.

    Idempotent: re-rendering the same week's digest replaces the existing
    section in place. Other weeks' sections are preserved verbatim. If
    the digest file doesn't exist, it's created with a top-level header
    and the new section.
    """
    new_section = render_weekly_digest_section(
        iso_year=iso_year,
        iso_week=iso_week,
        rows=rows,
        dispatch_active=dispatch_active,
    )

    week_start_iso = datetime.fromtimestamp(
        _week_start_ts(iso_year, iso_week), tz=timezone.utc
    ).strftime("%Y-%m-%d")
    week_anchor = f"{_WEEK_HEADER_PATTERN}{week_start_iso}"

    if not digest_path.exists():
        try:
            digest_path.parent.mkdir(parents=True, exist_ok=True)
            header = (
                "# Proactive Scheduler — Weekly Digest\n\n"
                "_Generated by the perpetual-proactive loop "
                "(D7.12 #1424). Newest week appears at the top._\n\n"
            )
            digest_path.write_text(header + new_section, encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "proactive_scheduler: digest write failed: %s", exc
            )
        return

    try:
        existing = digest_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("proactive_scheduler: digest read failed: %s", exc)
        return

    # Locate the existing section (if any) and replace it. We split on
    # `## ` headings to avoid regex pain — each section is a single
    # contiguous block ending where the next `## ` starts (or EOF).
    if week_anchor in existing:
        # Find the section's start
        start = existing.index(week_anchor)
        # Find the next `## ` heading after this section's start (skip
        # the heading we just found by adding 1)
        next_idx = existing.find("\n## ", start + 1)
        if next_idx == -1:
            # Section is at EOF — replace tail
            updated = existing[:start] + new_section
        else:
            # Replace just this section's slice; preserve everything
            # after the next-heading newline. The `\n` is preserved by
            # using next_idx + 1 (start of `## `).
            updated = existing[:start] + new_section + existing[next_idx + 1:]
    else:
        # New week — insert ABOVE existing week sections so the digest
        # reads newest-first. Find the first `## ` heading and prepend.
        first_section = existing.find("\n## ")
        if first_section == -1:
            # No existing sections — append after the file's preamble
            sep = "" if existing.endswith("\n\n") else "\n"
            updated = existing + sep + new_section
        else:
            # Insert new section before the existing first section. The
            # split point is the newline that precedes `## `.
            updated = (
                existing[: first_section + 1]
                + new_section
                + existing[first_section + 1 :]
            )

    try:
        digest_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        logger.warning("proactive_scheduler: digest write failed: %s", exc)


def should_render_weekly_digest(
    *,
    now_ts: float,
    last_render_ts: float | None,
) -> bool:
    """Return True when the scheduler should render this tick.

    Trigger rule: the first tick after the Sunday-18:00-UTC boundary that
    closes a week. We compare the ISO-week tuples — when `now_ts` is in a
    different (iso_year, iso_week) than `last_render_ts`, we're in a new
    week and the previous week is ready to be rendered.

    `last_render_ts=None` (no prior render) → render immediately so the
    first-ever tick produces a digest entry. After that, the rule self-
    rate-limits to once per ISO-week boundary crossing.
    """
    if last_render_ts is None:
        return True
    return _iso_week_key(now_ts) != _iso_week_key(last_render_ts)


# ---------------------------------------------------------------------------
# Closed-issue cache — feeds `select_next_work_item(closed_issues=...)` so
# the selector picks sprints whose prereqs have closed.
# ---------------------------------------------------------------------------
#
# D7.12 slice 2 #1424. The cache is a thin JSON file refreshed on a cooldown
# (default 6h). Slice 1 left this empty; slice 2 populates it via a single
# `gh issue list --state closed` shellout, idempotent and rate-friendly.
#
# Refresh failures are non-fatal — the scheduler degrades to "no closed
# issues known" (more conservative selection) rather than crashing.


_CLOSED_CACHE_DEFAULT_TTL_SECONDS: float = 6 * 3600.0


def load_closed_issue_cache(cache_path: Path) -> set[int]:
    """Read the closed-issue cache JSON. Returns empty set on any failure
    (missing file, malformed JSON, OS error). The selector then picks
    only zero-prereq sprints, which is the safe degradation.
    """
    if not cache_path.exists():
        return set()
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    numbers = raw.get("issue_numbers", []) if isinstance(raw, dict) else []
    return {int(n) for n in numbers if isinstance(n, (int, str))}


def _shellout_gh_closed_issues(limit: int = 1000) -> list[int]:
    """Run `gh issue list --state closed --json number` and parse.

    Synchronous shellout (subprocess.run) — called from the async refresh
    in a thread executor by the caller, so this stays simple. Returns []
    on any failure; logging happens at the caller.
    """
    import subprocess
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--state", "closed",
            "--limit", str(limit),
            "--json", "number",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload = json.loads(result.stdout)
    return [int(item["number"]) for item in payload if "number" in item]


async def refresh_closed_issue_cache(
    cache_path: Path,
    *,
    ttl_seconds: float = _CLOSED_CACHE_DEFAULT_TTL_SECONDS,
    fetch_fn: Callable[[], list[int]] | None = None,
) -> set[int]:
    """Refresh the closed-issue cache when older than ttl_seconds.

    Returns the live set (read from cache after refresh, or read directly
    if the cache is fresh). ``fetch_fn`` is injectable for tests; when
    None, falls back to `_shellout_gh_closed_issues`.
    """
    if cache_path.exists():
        try:
            age = time.time() - cache_path.stat().st_mtime
        except OSError:
            age = ttl_seconds + 1
        if age < ttl_seconds:
            return load_closed_issue_cache(cache_path)

    fetcher = fetch_fn or _shellout_gh_closed_issues
    try:
        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, fetcher)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "proactive_scheduler: closed-issue refresh failed (non-fatal): %s",
            exc,
        )
        # Fall back to whatever's already in the cache (possibly empty).
        return load_closed_issue_cache(cache_path)

    payload = {
        "refreshed_at": time.time(),
        "iso_refreshed_at": datetime.fromtimestamp(
            time.time(), tz=timezone.utc
        ).isoformat(),
        "issue_numbers": sorted(numbers),
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "proactive_scheduler: closed-issue cache write failed: %s", exc
        )
    return set(numbers)


# ---------------------------------------------------------------------------
# Autonomous plan drafter — the slice-2 dispatch surface
# ---------------------------------------------------------------------------
#
# Given a WorkItem, asks Claude for a tight 3-bullet plan and posts it to
# the issue as an `[autonomous]`-prefixed comment. Read-only artifact:
# operator can delete the comment in one click; nothing about the
# repository state is mutated. Cost-capped per call (passed via runner
# config); budget-aware (the scheduler already skipped on budget pressure
# before reaching here).
#
# Why issue-comment over draft-PR-creation:
#   - one shellout (gh issue comment), no branch creation, no file write
#   - reversible by operator without git operations
#   - matches exactly what the audit asks for ("draft a 3-bullet plan as
#     a PR-draft comment") — the comment lands on the issue, which is
#     the same surface a future draft PR would link to


_PLAN_DRAFT_PROMPT_TEMPLATE = """\
You are Bumba's autonomous proactive loop. The scheduler picked this sprint
as the next-best safe work item from the dependency graph:

Issue #{number}: {title}
Labels: {labels}

Your job is to draft a 3-bullet implementation plan that the operator can
review later. NO preamble, NO scope expansion, NO meta-commentary about
what you're doing. Just the three bullets.

Format: exactly three lines, each starting with "- ". Each bullet is one
sentence (or one tight sentence + a one-clause amplifier). The plan
should be specific to the sprint title — name files, modules, functions,
or test surfaces by their literal path where possible.

Output exactly the three bullet lines and nothing else.
"""


@dataclass
class PlanDraftResult:
    """Outcome of one AutonomousPlanDrafter call."""
    posted: bool
    comment_text: str
    error: str | None = None


class AutonomousPlanDrafter:
    """Generates a 3-bullet plan for a WorkItem and posts it as a comment.

    Conservative slice-2 dispatch surface. The scheduler hands a picked
    WorkItem here; the drafter calls Claude (one-shot, capped), prefixes
    the result with `[autonomous]`, and posts it via `gh issue comment`.

    Failures are surfaced as `posted=False` + `error=...` so the
    scheduler can record them in the ledger; nothing raises into the
    scheduler loop.
    """

    def __init__(
        self,
        *,
        runner,  # bridge.claude_runner.ClaudeRunner — duck-typed
        model: str = "haiku",
        gh_binary: str = "gh",
        autonomous_marker: str = "[autonomous]",
    ) -> None:
        self._runner = runner
        self._model = model
        self._gh = gh_binary
        self._marker = autonomous_marker

    async def __call__(self, item: WorkItem) -> PlanDraftResult:
        """Draft + post in one call. Always returns a PlanDraftResult."""
        prompt = _PLAN_DRAFT_PROMPT_TEMPLATE.format(
            number=item.number,
            title=item.title,
            labels=", ".join(item.labels) or "(none)",
        )
        try:
            result = await self._runner.invoke(
                message=prompt,
                model=self._model,
            )
        except Exception as exc:  # noqa: BLE001
            return PlanDraftResult(
                posted=False, comment_text="", error=f"invoke_failed: {exc}",
            )
        if getattr(result, "is_error", False):
            return PlanDraftResult(
                posted=False,
                comment_text="",
                error=f"invoke_returned_error: {getattr(result, 'error_type', '')}",
            )
        plan_text = (result.response_text or "").strip()
        if not plan_text:
            return PlanDraftResult(
                posted=False, comment_text="", error="empty_plan_text",
            )

        # Marker placed at the top so the operator can grep + delete via
        # the GitHub UI's "delete comment" without reading the body.
        comment_body = (
            f"{self._marker} (D7.12 #1424 proactive scheduler)\n\n"
            f"{plan_text}\n\n"
            f"---\n"
            f"_Posted by the perpetual-proactive loop. Edit/delete freely; "
            f"this is a starting-point draft, not a commitment._"
        )
        try:
            posted = await self._post_comment(item.number, comment_body)
        except Exception as exc:  # noqa: BLE001
            return PlanDraftResult(
                posted=False,
                comment_text=comment_body,
                error=f"gh_post_failed: {exc}",
            )
        return PlanDraftResult(posted=posted, comment_text=comment_body)

    async def _post_comment(self, issue_number: int, body: str) -> bool:
        """Run `gh issue comment <N> --body <body>` in a thread executor."""
        import subprocess

        def _run() -> bool:
            r = subprocess.run(
                [self._gh, "issue", "comment", str(issue_number),
                 "--body", body],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode != 0:
                logger.warning(
                    "AutonomousPlanDrafter: gh comment failed rc=%d stderr=%s",
                    r.returncode, r.stderr[:300],
                )
                return False
            return True

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run)


def make_drafter_callback(
    drafter: AutonomousPlanDrafter,
) -> Callable[[WorkItem], "asyncio.Future | None"]:
    """Wrap an AutonomousPlanDrafter as a DispatchCallback for the scheduler.

    The scheduler treats anything truthy from dispatch_callback as a
    successful dispatch (logs `dispatched` to the ledger); a failure
    result causes the scheduler to fall through to `dispatch_error: ...`
    via the existing exception path. This wrapper raises on
    `posted=False` so the ledger captures *why* dispatch failed instead
    of recording an inert success.
    """
    async def _cb(item: WorkItem):
        result = await drafter(item)
        if not result.posted:
            raise RuntimeError(
                f"plan_drafter_failed: {result.error or 'no detail'}"
            )
        return result
    return _cb


# ---------------------------------------------------------------------------
# Scheduler — the bridge-side loop
# ---------------------------------------------------------------------------


# Type alias for the optional dispatch hook (slice 2 will set this).
DispatchCallback = Callable[[WorkItem], "asyncio.Future | None"]
InboxPendingRefreshCallback = Callable[[], Awaitable[int]]


class ProactiveScheduler:
    """Background scheduler loop wrapping the work-selection logic.

    Slice 1 ships this in dry-run mode only: every tick calls the
    selector, writes a ledger entry, but does NOT dispatch a subagent.
    Slice 2 flips ``dry_run=False`` and wires ``dispatch_callback`` to
    a function that opens an [autonomous] PR.
    """

    def __init__(
        self,
        *,
        graph_path: Path,
        ledger_path: Path,
        budget_threshold: float = 0.75,
        interval_seconds: float = 900.0,
        dry_run: bool = True,
        get_inbox_pending_count: Callable[[], int] | None = None,
        get_daily_spend_fraction: Callable[[], float] | None = None,
        get_halt_flag_present: Callable[[], bool] | None = None,
        get_closed_issue_numbers: Callable[[], Iterable[int]] | None = None,
        dispatch_callback: DispatchCallback | None = None,
        digest_path: Path | None = None,
        # audit-2026-05-16.C.05 — shared HaltPolicy contract. When wired,
        # ``check_start("proactive")`` replaces the ad-hoc
        # ``get_halt_flag_present`` callable as the halt source for the
        # tick-skip decision. The callable still serves as a fallback
        # when no policy is wired (keeps the legacy keyword-only kwarg
        # path working unchanged so back-compat for existing callers is
        # preserved). When BOTH are passed, the policy wins.
        halt_policy: HaltPolicy | None = None,
    ) -> None:
        self.graph_path = graph_path
        self.ledger_path = ledger_path
        self.budget_threshold = budget_threshold
        self.interval_seconds = interval_seconds
        self.dry_run = dry_run
        self._inbox_pending_count = get_inbox_pending_count or (lambda: 0)
        self._inbox_pending_refresh: InboxPendingRefreshCallback | None = None
        self._daily_spend = get_daily_spend_fraction or (lambda: 0.0)
        self._halt = get_halt_flag_present or (lambda: False)
        self._closed_issues = get_closed_issue_numbers or (lambda: ())
        self._dispatch = dispatch_callback
        # audit-2026-05-16.C.05 — shared halt-policy handle (may be None).
        self._halt_policy = halt_policy
        self._task: asyncio.Task[None] | None = None
        # Issue numbers picked in the current process — prevents the same
        # work item from being picked again on the next tick before the
        # ledger window catches up. Cleared on each process restart.
        self._recently_picked: set[int] = set()
        # D7.12 slice 3 #1424 — weekly digest. ``digest_path=None`` keeps
        # the digest disabled; callers in BridgeApp pass
        # ``data/weekly-digest.md`` to enable it. The trigger logic
        # (`should_render_weekly_digest`) self-rate-limits to once per
        # ISO-week boundary crossing, so attaching the path is the only
        # thing the operator has to do.
        self.digest_path = digest_path
        self._last_digest_render_ts: float | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── Wiring discipline (Sprint #1614) ──────────────────────────────────
    #
    # ``set_dispatch`` is the canonical setter for the dispatch callback.
    # Earlier code (pre-#1614) assigned ``self._dispatch = callback``
    # directly on the BridgeApp side — that bypassed the WIRING_MANIFEST
    # contract and made dispatch wiring invisible to the boot-time wiring
    # report. The setter exists so the manifest can fire it like every
    # other wire.

    def set_inbox_pending_refresh(
        self, callback: InboxPendingRefreshCallback | None
    ) -> None:
        """Register the async inbox refresh that runs before tick selection.

        BridgeApp owns the async OperatorInbox surface, while
        ``should_skip_tick`` reads a synchronous pending-count provider.
        This setter is the explicit wire between those shapes, replacing
        the older BridgeApp-side ``tick_once`` monkey patch.
        """
        self._inbox_pending_refresh = callback

    def set_dispatch(self, callback: "DispatchCallback | None") -> None:
        """Register (or clear) the dispatch callback.

        The callback is invoked from :meth:`dispatch` when ``dry_run`` is
        False and a work item has been picked. Pass ``None`` to clear a
        previously-set callback (useful for tests and for operator-driven
        runtime disable).
        """
        self._dispatch = callback

    async def dispatch(self, item: WorkItem) -> Any:
        """Invoke the wired dispatch callback for ``item``.

        Raises :class:`bridge.wiring.WiringMissingError` when no callback
        has been registered via :meth:`set_dispatch` — the contract is that
        callers (the scheduler loop) only reach this method when
        ``dry_run=False``, so silent no-op would leave the operator with no
        signal that dispatch is broken. The exception bubbles up to
        :meth:`tick_once`'s exception handler, which records
        ``dispatch_error: WiringMissingError(...)`` in the ledger.
        """
        if self._dispatch is None:
            # Imported lazily to avoid a circular import at module load.
            from bridge.wiring import WiringMissingError

            raise WiringMissingError(
                "ProactiveScheduler.dispatch called but no callback was "
                "registered via set_dispatch(). The scheduler reached a "
                "non-dry-run dispatch branch without a wired callback — "
                "see the 'Wiring discipline' section in agent/CLAUDE.md."
            )
        return await self._dispatch(item)

    async def start(self) -> None:
        """Start the background loop. Idempotent — calling while already
        running is a no-op.
        """
        if self.is_running:
            return
        self._task = asyncio.create_task(self._run())
        logger.info(
            "proactive_scheduler: started (interval=%ds, dry_run=%s)",
            int(self.interval_seconds),
            self.dry_run,
        )

    async def stop(self) -> None:
        """Cancel the background loop and wait for exit. Idempotent."""
        if self._task is None:
            return
        task = self._task
        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        """Loop body: tick, sleep, repeat. Cancellation-safe."""
        while True:
            try:
                await self.tick_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("proactive_scheduler: tick failed")
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                raise

    def _maybe_render_digest(self) -> None:
        """Render the weekly digest if the ISO-week boundary has crossed.

        Called at the top of every tick. Idempotent within a week — only
        the first tick after Monday-00:00-UTC produces a render; subsequent
        ticks in the same week no-op via `should_render_weekly_digest`.
        Any failure is logged and swallowed; the digest is observability,
        not correctness — losing a render is far cheaper than crashing
        the scheduler loop.
        """
        if self.digest_path is None:
            return
        now_ts = time.time()
        if not should_render_weekly_digest(
            now_ts=now_ts,
            last_render_ts=self._last_digest_render_ts,
        ):
            return
        try:
            # Render the PREVIOUS ISO week (the one that just closed).
            # Compute previous week by subtracting 7 days from now.
            prev_ts = now_ts - 7 * 24 * 3600
            iso_year, iso_week = _iso_week_key(prev_ts)
            week_start = _week_start_ts(iso_year, iso_week)
            week_end = week_start + 7 * 24 * 3600
            rows = read_ledger_window(self.ledger_path, since_ts=week_start)
            # Trim rows that crossed into the new week (only if next week's
            # picks landed before the digest fired)
            rows = [r for r in rows if r.get("ts", 0) < week_end]
            dispatch_active = (not self.dry_run) and (self._dispatch is not None)
            upsert_weekly_digest(
                self.digest_path,
                iso_year=iso_year,
                iso_week=iso_week,
                rows=rows,
                dispatch_active=dispatch_active,
            )
            self._last_digest_render_ts = now_ts
            logger.info(
                "proactive_scheduler: weekly digest rendered (week %d-%02d)",
                iso_year, iso_week,
            )
        except Exception:
            logger.exception(
                "proactive_scheduler: weekly digest render failed (non-fatal)"
            )

    async def tick_once(self) -> ProactiveTickReport:
        """One scheduler pass — pure-ish unit, callable from tests + diagnostics."""
        # D7.12 slice 3 — render previous week's digest if we crossed an
        # ISO-week boundary. Best-effort, non-blocking.
        self._maybe_render_digest()

        if self._inbox_pending_refresh is not None:
            await self._inbox_pending_refresh()

        # audit-2026-05-16.C.05 — route the halt-flag read through the
        # shared HaltPolicy when wired; fall back to the legacy
        # ``get_halt_flag_present`` callable when not. Log the policy
        # reason at INFO when blocked so operators can grep the surface.
        halt_blocked: bool
        if self._halt_policy is not None:
            decision = self._halt_policy.check_start("proactive")
            halt_blocked = decision.blocked
            if decision.blocked:
                logger.info(
                    "proactive_scheduler: halt-policy blocked start — %s",
                    decision.reason,
                )
        else:
            halt_blocked = self._halt()

        skip = await should_skip_tick(
            inbox_pending_count=self._inbox_pending_count(),
            daily_spend_fraction=self._daily_spend(),
            budget_threshold=self.budget_threshold,
            halt_flag_present=halt_blocked,
        )
        if skip is not None:
            report = ProactiveTickReport(
                action="skipped", work_item=None, reason=skip
            )
            append_to_ledger(self.ledger_path, report)
            return report

        graph = load_graph(self.graph_path)
        if graph is None:
            report = ProactiveTickReport(
                action="skipped", work_item=None, reason=SKIP_NO_GRAPH
            )
            append_to_ledger(self.ledger_path, report)
            return report

        item = select_next_work_item(
            graph,
            closed_issues=self._closed_issues(),
            skip_numbers=self._recently_picked,
        )
        if item is None:
            report = ProactiveTickReport(
                action="skipped", work_item=None, reason=SKIP_NO_CANDIDATES
            )
            append_to_ledger(self.ledger_path, report)
            return report

        # Slice-1: dry-run only — do NOT dispatch even when the callback
        # is wired. The callback path lives here so slice 2 only needs to
        # flip the flag.
        #
        # Sprint #1614 — the guard is now ``self.dry_run`` ONLY (no
        # ``or self._dispatch is None`` clause). Pre-#1614, a missing
        # callback silently fell into the "picked" branch even when
        # dry_run was off, leaving the operator with no signal that the
        # dispatch surface was unwired. Now: if dry_run is False and no
        # setter was called, the code below reaches ``self.dispatch``
        # which raises ``WiringMissingError`` — caught by the
        # ``except Exception`` block and recorded as ``dispatch_error``
        # in the ledger. Loud, not silent.
        if self.dry_run:
            report = ProactiveTickReport(
                action="picked", work_item=item, reason="dry_run"
            )
            self._recently_picked.add(item.number)
            append_to_ledger(self.ledger_path, report)
            return report

        # Slice-2 path. Routes through ``self.dispatch`` so the
        # WiringMissingError contract fires loudly if the callback wasn't
        # registered via ``set_dispatch`` (Sprint #1614).
        try:
            await self.dispatch(item)
            report = ProactiveTickReport(
                action="dispatched", work_item=item, reason="dispatched"
            )
        except Exception as exc:
            logger.exception("proactive_scheduler: dispatch failed")
            report = ProactiveTickReport(
                action="skipped",
                work_item=item,
                reason=f"dispatch_error: {exc}",
            )
        self._recently_picked.add(item.number)
        append_to_ledger(self.ledger_path, report)
        return report
