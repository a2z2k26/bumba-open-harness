"""MS5.2 — Operator Review Digest.

Weekly summary digest replacing daily operator management.  Aggregates
deploy history, trust scores, incidents, proposals, and resource usage
into a single markdown report.

Eight sections: Executive Summary, Deployments, Self-Improvements,
Incidents & Recovery, Proposals Pending, Trust Score Summary,
Resource Usage, Action Items.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DeployStats:
    """Aggregated deployment statistics for a week."""

    total: int = 0
    successes: int = 0
    failures: int = 0
    rollbacks: int = 0
    notable: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.successes / self.total if self.total > 0 else 0.0


@dataclass
class IncidentStats:
    """Aggregated incident statistics."""

    total: int = 0
    auto_recovered: int = 0
    escalated: int = 0
    unresolved: int = 0
    avg_recovery_minutes: float = 0.0
    summaries: list[str] = field(default_factory=list)


@dataclass
class ResourceUsage:
    """Weekly resource consumption."""

    total_tokens: int = 0
    api_calls: int = 0
    disk_usage_mb: float = 0.0
    cost_estimate_usd: float = 0.0
    by_service: dict[str, int] = field(default_factory=dict)


@dataclass
class DigestData:
    """All data needed to render a weekly digest."""

    week_start: str = ""
    week_end: str = ""
    deploys: DeployStats = field(default_factory=DeployStats)
    incidents: IncidentStats = field(default_factory=IncidentStats)
    resources: ResourceUsage = field(default_factory=ResourceUsage)
    trust_scores: dict[str, float] = field(default_factory=dict)
    trust_changes: list[dict] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    pending_proposals: list[dict] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_deploys(deploy_history: list[dict]) -> DeployStats:
    """Aggregate deploy events into summary stats."""
    stats = DeployStats()
    for entry in deploy_history:
        stats.total += 1
        status = entry.get("status", "")
        if status == "success":
            stats.successes += 1
        elif status == "failed":
            stats.failures += 1
            reason = entry.get("reason", "unknown")
            stats.notable.append(f"Failed: {entry.get('file', '?')} — {reason}")
        elif status == "rollback":
            stats.rollbacks += 1
            stats.notable.append(f"Rollback: {entry.get('file', '?')}")
        # Notable successes (new features)
        if status == "success" and entry.get("notable"):
            stats.notable.append(f"Deployed: {entry.get('description', entry.get('file', '?'))}")
    return stats


def aggregate_incidents(incidents: list[dict]) -> IncidentStats:
    """Aggregate incident records into summary stats."""
    stats = IncidentStats()
    recovery_times: list[float] = []
    for inc in incidents:
        stats.total += 1
        resolution = inc.get("resolution", "")
        if resolution == "auto_recovered":
            stats.auto_recovered += 1
            rt = inc.get("recovery_minutes", 0)
            if rt:
                recovery_times.append(rt)
        elif resolution == "escalated":
            stats.escalated += 1
        elif resolution == "unresolved":
            stats.unresolved += 1
        summary = inc.get("summary", "")
        if summary:
            stats.summaries.append(summary)
    if recovery_times:
        stats.avg_recovery_minutes = sum(recovery_times) / len(recovery_times)
    return stats


def aggregate_resources(usage_entries: list[dict]) -> ResourceUsage:
    """Aggregate resource usage data."""
    res = ResourceUsage()
    for entry in usage_entries:
        res.total_tokens += entry.get("tokens", 0)
        res.api_calls += entry.get("api_calls", 0)
        service = entry.get("service", "unknown")
        res.by_service[service] = res.by_service.get(service, 0) + entry.get("tokens", 0)
    # Rough cost estimate: $3 per 1M input tokens (Sonnet pricing)
    res.cost_estimate_usd = res.total_tokens / 1_000_000 * 3.0
    return res


def build_digest_data(
    deploys: list[dict] | None = None,
    incidents: list[dict] | None = None,
    usage: list[dict] | None = None,
    trust_scores: dict[str, float] | None = None,
    trust_changes: list[dict] | None = None,
    improvements: list[str] | None = None,
    pending_proposals: list[dict] | None = None,
    action_items: list[str] | None = None,
    week_start: str = "",
    week_end: str = "",
) -> DigestData:
    """Build digest data from available sources. Handles missing data gracefully."""
    data = DigestData(week_start=week_start, week_end=week_end)
    missing: list[str] = []

    if deploys is not None:
        data.deploys = aggregate_deploys(deploys)
    else:
        missing.append("deploy_history")

    if incidents is not None:
        data.incidents = aggregate_incidents(incidents)
    else:
        missing.append("incidents")

    if usage is not None:
        data.resources = aggregate_resources(usage)
    else:
        missing.append("resource_usage")

    data.trust_scores = trust_scores or {}
    data.trust_changes = trust_changes or []
    data.improvements = improvements or []
    data.pending_proposals = pending_proposals or []
    data.action_items = action_items or []
    data.missing_sources = missing

    if not trust_scores:
        missing.append("trust_scores")

    return data


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_TREND_ARROWS = {
    "up": "\u2191",    # ↑
    "down": "\u2193",  # ↓
    "stable": "\u2192",  # →
}


def _trend(changes: list[dict], capability: str) -> str:
    """Determine trend for a capability from change history."""
    cap_changes = [c for c in changes if c.get("capability") == capability]
    if not cap_changes:
        return _TREND_ARROWS["stable"]
    last = cap_changes[-1]
    diff = last.get("new_score", 0) - last.get("old_score", 0)
    if diff > 2:
        return _TREND_ARROWS["up"]
    elif diff < -2:
        return _TREND_ARROWS["down"]
    return _TREND_ARROWS["stable"]


def format_digest(data: DigestData) -> str:
    """Render a full weekly digest as markdown."""
    lines: list[str] = []

    lines.append(f"# Weekly Digest: {data.week_start} to {data.week_end}")
    lines.append("")

    # ── Section 1: Executive Summary ──
    lines.append("## Executive Summary")
    summary_parts: list[str] = []
    if data.deploys.total > 0:
        summary_parts.append(
            f"{data.deploys.total} deployments ({data.deploys.success_rate:.0%} success rate)"
        )
    if data.incidents.total > 0:
        summary_parts.append(
            f"{data.incidents.total} incidents "
            f"({data.incidents.auto_recovered} auto-recovered)"
        )
    if data.pending_proposals:
        summary_parts.append(f"{len(data.pending_proposals)} proposals pending review")
    if data.action_items:
        summary_parts.append(f"{len(data.action_items)} action items require attention")
    if not summary_parts:
        summary_parts.append("Quiet week — no notable events")
    lines.append(". ".join(summary_parts) + ".")
    lines.append("")

    # ── Section 2: Deployments ──
    lines.append("## Deployments")
    if data.deploys.total > 0:
        lines.append(f"- Total: {data.deploys.total}")
        lines.append(f"- Successes: {data.deploys.successes}")
        lines.append(f"- Failures: {data.deploys.failures}")
        lines.append(f"- Rollbacks: {data.deploys.rollbacks}")
        if data.deploys.notable:
            lines.append("")
            lines.append("**Notable:**")
            for n in data.deploys.notable[:10]:
                lines.append(f"- {n}")
    else:
        lines.append("_No deployments this week._")
    lines.append("")

    # ── Section 3: Self-Improvements ──
    lines.append("## Self-Improvements")
    if data.improvements:
        for imp in data.improvements:
            lines.append(f"- {imp}")
    else:
        lines.append("_No self-improvements this week._")
    lines.append("")

    # ── Section 4: Incidents & Recovery ──
    lines.append("## Incidents & Recovery")
    if data.incidents.total > 0:
        lines.append(f"- Total incidents: {data.incidents.total}")
        lines.append(f"- Auto-recovered: {data.incidents.auto_recovered}")
        lines.append(f"- Escalated: {data.incidents.escalated}")
        lines.append(f"- Unresolved: {data.incidents.unresolved}")
        if data.incidents.avg_recovery_minutes > 0:
            lines.append(f"- Avg recovery: {data.incidents.avg_recovery_minutes:.1f} min")
        if data.incidents.summaries:
            lines.append("")
            for s in data.incidents.summaries[:5]:
                lines.append(f"- {s}")
    else:
        lines.append("_No incidents this week._")
    lines.append("")

    # ── Section 5: Proposals Pending ──
    lines.append("## Proposals Pending")
    if data.pending_proposals:
        for p in data.pending_proposals:
            name = p.get("name", "?")
            score = p.get("priority_score", 0)
            lines.append(f"- **{name}** (priority: {score})")
    else:
        lines.append("_No pending proposals._")
    lines.append("")

    # ── Section 6: Trust Score Summary ──
    lines.append("## Trust Score Summary")
    if data.trust_scores:
        lines.append("| Capability | Score | Trend |")
        lines.append("|------------|-------|-------|")
        for cap, score in sorted(data.trust_scores.items()):
            trend = _trend(data.trust_changes, cap)
            lines.append(f"| {cap} | {score:.1f} | {trend} |")
    else:
        lines.append("_Trust scores unavailable._")
    lines.append("")

    # ── Section 7: Resource Usage ──
    lines.append("## Resource Usage")
    if data.resources.total_tokens > 0:
        lines.append(f"- Total tokens: {data.resources.total_tokens:,}")
        lines.append(f"- API calls: {data.resources.api_calls:,}")
        lines.append(f"- Est. cost: ${data.resources.cost_estimate_usd:.2f}")
        if data.resources.by_service:
            lines.append("")
            lines.append("**By service:**")
            for svc, tokens in sorted(
                data.resources.by_service.items(), key=lambda x: -x[1]
            ):
                lines.append(f"- {svc}: {tokens:,} tokens")
    else:
        lines.append("_No resource usage data available._")
    lines.append("")

    # ── Section 8: Action Items ──
    lines.append("## Action Items")
    if data.action_items:
        for idx, item in enumerate(data.action_items, 1):
            lines.append(f"{idx}. {item}")
    else:
        lines.append("_No action items this week._")
    lines.append("")

    # ── Missing data sources note ──
    if data.missing_sources:
        lines.append(f"_Note: data unavailable from: {', '.join(data.missing_sources)}_")

    return "\n".join(lines)


def save_digest(digest_md: str, data_dir: Path, week_label: str = "") -> Path:
    """Save digest to data/digests/ directory. Returns file path."""
    if not week_label:
        now = datetime.now(timezone.utc)
        week_label = f"{now.year}-W{now.isocalendar()[1]:02d}"
    digests_dir = data_dir / "digests"
    digests_dir.mkdir(parents=True, exist_ok=True)
    path = digests_dir / f"{week_label}-digest.md"
    path.write_text(digest_md)
    return path
