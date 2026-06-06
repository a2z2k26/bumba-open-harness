"""
cost.py — Zone 4 Sprint 10

Three-level cost attribution (agent / department / session) with budget checking.

Reads ToolCallRecords from the ToolTracker JSONL files and aggregates costs.
Also produces cost summary JSON files in the session directory.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from bridge.observability.tool_tracker import ToolTracker, ToolCallRecord

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentCostSummary:
    """Cost summary for a single agent within a department session."""

    agent_name: str
    department: str
    session_id: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_usd: float = 0.0
    call_count: int = 0
    blocked_calls: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DepartmentCostSummary:
    """Cost summary for an entire department within a session."""

    department: str
    session_id: str
    agents: tuple[AgentCostSummary, ...] = ()
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_usd: float = 0.0
    call_count: int = 0
    blocked_calls: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["agents"] = [a.to_dict() for a in self.agents]
        return d


@dataclass(frozen=True)
class SessionCostSummary:
    """Cost summary for an entire session across all departments."""

    session_id: str
    departments: tuple[DepartmentCostSummary, ...] = ()
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_usd: float = 0.0
    call_count: int = 0
    blocked_calls: int = 0
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["departments"] = [dept.to_dict() for dept in self.departments]
        return d


# ── CostAttributor ────────────────────────────────────────────────────────────

class CostAttributor:
    """
    Computes cost summaries at three levels by reading ToolTracker JSONL data.
    """

    def __init__(self, tracker: ToolTracker, sessions_dir: Path) -> None:
        self._tracker = tracker
        self._sessions_dir = sessions_dir

    # ── Agent-level ────────────────────────────────────────────────────────────

    def compute_agent_cost(
        self,
        session_id: str,
        department: str,
        agent_name: str,
    ) -> AgentCostSummary:
        """Compute cost for a single agent in a department session."""
        records = self._tracker.get_agent_calls(session_id, department, agent_name)
        return self._summarize_agent(records, agent_name, department, session_id)

    # ── Department-level ───────────────────────────────────────────────────────

    def compute_department_cost(
        self,
        session_id: str,
        department: str,
    ) -> DepartmentCostSummary:
        """Compute cost for all agents in a department for a session."""
        records = self._tracker.get_department_calls(session_id, department)

        # Group by agent
        by_agent: dict[str, list[ToolCallRecord]] = {}
        for r in records:
            by_agent.setdefault(r.agent_name, []).append(r)

        agents = tuple(
            self._summarize_agent(recs, name, department, session_id)
            for name, recs in sorted(by_agent.items())
        )

        total_in = sum(a.total_input_tokens for a in agents)
        total_out = sum(a.total_output_tokens for a in agents)
        total_usd = sum(a.total_usd for a in agents)
        total_calls = sum(a.call_count for a in agents)
        total_blocked = sum(a.blocked_calls for a in agents)

        return DepartmentCostSummary(
            department=department,
            session_id=session_id,
            agents=agents,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_usd=total_usd,
            call_count=total_calls,
            blocked_calls=total_blocked,
        )

    # ── Session-level ──────────────────────────────────────────────────────────

    def compute_session_cost(self, session_id: str) -> SessionCostSummary:
        """Compute cost for all departments across a session."""
        all_records = self._tracker.get_session_calls(session_id)

        # Group by department
        by_dept: dict[str, list[ToolCallRecord]] = {}
        for r in all_records:
            by_dept.setdefault(r.department, []).append(r)

        dept_summaries: list[DepartmentCostSummary] = []
        for dept_name in sorted(by_dept):
            dept_records = by_dept[dept_name]
            # Group by agent within department
            by_agent: dict[str, list[ToolCallRecord]] = {}
            for r in dept_records:
                by_agent.setdefault(r.agent_name, []).append(r)

            agents = tuple(
                self._summarize_agent(recs, name, dept_name, session_id)
                for name, recs in sorted(by_agent.items())
            )

            dept_summaries.append(DepartmentCostSummary(
                department=dept_name,
                session_id=session_id,
                agents=agents,
                total_input_tokens=sum(a.total_input_tokens for a in agents),
                total_output_tokens=sum(a.total_output_tokens for a in agents),
                total_usd=sum(a.total_usd for a in agents),
                call_count=sum(a.call_count for a in agents),
                blocked_calls=sum(a.blocked_calls for a in agents),
            ))

        departments = tuple(dept_summaries)
        return SessionCostSummary(
            session_id=session_id,
            departments=departments,
            total_input_tokens=sum(d.total_input_tokens for d in departments),
            total_output_tokens=sum(d.total_output_tokens for d in departments),
            total_usd=sum(d.total_usd for d in departments),
            call_count=sum(d.call_count for d in departments),
            blocked_calls=sum(d.blocked_calls for d in departments),
        )

    # ── Budget check ───────────────────────────────────────────────────────────

    def check_budget(
        self,
        session_id: str,
        budget_usd: float,
    ) -> tuple[bool, float]:
        """
        Check if a session is within budget.

        Returns (within_budget, current_cost_usd).
        """
        summary = self.compute_session_cost(session_id)
        return (summary.total_usd <= budget_usd, summary.total_usd)

    # ── Persist cost JSON ──────────────────────────────────────────────────────

    def write_cost_json(self, session_id: str) -> Path:
        """
        Write the session cost summary as cost.json in the session directory.
        Returns the path to the written file.
        """
        summary = self.compute_session_cost(session_id)
        cost_path = self._sessions_dir / session_id / "cost.json"
        cost_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            cost_path.write_text(
                json.dumps(summary.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed to write cost.json for session %s: %s", session_id, exc)

        return cost_path

    # ── Internal ───────────────────────────────────────────────────────────────

    def _summarize_agent(
        self,
        records: list[ToolCallRecord],
        agent_name: str,
        department: str,
        session_id: str,
    ) -> AgentCostSummary:
        total_in = sum(r.cost.input_tokens for r in records)
        total_out = sum(r.cost.output_tokens for r in records)
        total_usd = sum(r.cost.estimated_usd for r in records)
        blocked = sum(1 for r in records if r.status == "blocked")

        return AgentCostSummary(
            agent_name=agent_name,
            department=department,
            session_id=session_id,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_usd=total_usd,
            call_count=len(records),
            blocked_calls=blocked,
        )
