"""
metrics_aggregator.py — Zone 4 Sprint 10

Cross-session metrics aggregation: daily cost trends and agent utilization.

Scans all session directories under the sessions root to build aggregate views.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bridge.observability.cost import CostAttributor
from bridge.observability.tool_tracker import ToolTracker

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DailyCostEntry:
    """Cost total for a single day."""

    date: str  # ISO date YYYY-MM-DD
    total_usd: float = 0.0
    session_count: int = 0
    total_calls: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AgentUtilization:
    """Utilization metrics for a single agent across sessions."""

    agent_name: str
    session_count: int = 0
    total_calls: int = 0
    total_usd: float = 0.0
    avg_cost_per_session: float = 0.0
    blocked_calls: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ── MetricsAggregator ────────────────────────────────────────────────────────

class MetricsAggregator:
    """
    Aggregates cost and utilization metrics across multiple sessions.

    Scans session directories to find meta.json (which contains created_at
    timestamps) and uses CostAttributor for per-session cost data.
    """

    def __init__(self, tracker: ToolTracker, sessions_dir: Path) -> None:
        self._tracker = tracker
        self._sessions_dir = sessions_dir
        self._attributor = CostAttributor(tracker, sessions_dir)

    # ── Daily cost ─────────────────────────────────────────────────────────────

    def daily_cost(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[DailyCostEntry]:
        """
        Compute daily cost totals across all sessions.

        Dates are ISO format YYYY-MM-DD. Both bounds are inclusive.
        If no bounds provided, returns all available days.
        """
        session_ids = self._list_session_ids()
        if not session_ids:
            return []

        # Map session_id → date string (from meta.json or directory mtime)
        daily: dict[str, dict] = {}  # date_str → {usd, sessions, calls}

        for sid in session_ids:
            session_date = self._get_session_date(sid)
            if not session_date:
                continue

            # Apply date filters
            if start_date and session_date < start_date:
                continue
            if end_date and session_date > end_date:
                continue

            summary = self._attributor.compute_session_cost(sid)

            if session_date not in daily:
                daily[session_date] = {"usd": 0.0, "sessions": 0, "calls": 0}

            daily[session_date]["usd"] += summary.total_usd
            daily[session_date]["sessions"] += 1
            daily[session_date]["calls"] += summary.call_count

        return [
            DailyCostEntry(
                date=d,
                total_usd=v["usd"],
                session_count=v["sessions"],
                total_calls=v["calls"],
            )
            for d, v in sorted(daily.items())
        ]

    # ── Agent utilization ──────────────────────────────────────────────────────

    def agent_utilization(self) -> list[AgentUtilization]:
        """
        Compute utilization metrics for each agent across all sessions.

        Returns agents sorted by total cost descending.
        """
        session_ids = self._list_session_ids()
        if not session_ids:
            return []

        # Aggregate per agent
        agents: dict[str, dict] = {}

        for sid in session_ids:
            records = self._tracker.get_session_calls(sid)

            for r in records:
                name = r.agent_name
                if name not in agents:
                    agents[name] = {
                        "sessions": set(),
                        "calls": 0,
                        "usd": 0.0,
                        "blocked": 0,
                    }
                agents[name]["sessions"].add(sid)
                agents[name]["calls"] += 1
                agents[name]["usd"] += r.cost.estimated_usd
                if r.status == "blocked":
                    agents[name]["blocked"] += 1

        result = []
        for name, data in agents.items():
            session_count = len(data["sessions"])
            avg_cost = data["usd"] / session_count if session_count > 0 else 0.0
            result.append(AgentUtilization(
                agent_name=name,
                session_count=session_count,
                total_calls=data["calls"],
                total_usd=data["usd"],
                avg_cost_per_session=round(avg_cost, 6),
                blocked_calls=data["blocked"],
            ))

        # Sort by total cost descending
        result.sort(key=lambda a: a.total_usd, reverse=True)
        return result

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _list_session_ids(self) -> list[str]:
        """List all session IDs (directory names) in the sessions root."""
        if not self._sessions_dir.exists():
            return []
        return sorted(
            d.name
            for d in self._sessions_dir.iterdir()
            if d.is_dir()
        )

    def _get_session_date(self, session_id: str) -> Optional[str]:
        """
        Extract the date for a session.

        Tries meta.json created_at first, then falls back to directory mtime.
        Returns ISO date string YYYY-MM-DD or None.
        """
        session_dir = self._sessions_dir / session_id
        meta_path = session_dir / "meta.json"

        # Try meta.json
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                created_at = meta.get("created_at", "")
                if created_at:
                    # Parse ISO datetime, extract date
                    dt = datetime.fromisoformat(created_at)
                    return dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        # Fallback to directory mtime
        try:
            mtime = session_dir.stat().st_mtime
            dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
