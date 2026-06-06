"""Skill Journey Ledger — per-skill progression tracking.

Sprint S11: Every skill has a persistent record with tier (experimental |
graduated | canonical), success rate, per-agent proficiency, run history.
Automatic promotion/demotion via rolling-window thresholds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal

log = logging.getLogger(__name__)

SkillTier = Literal["experimental", "graduated", "canonical"]

# Promotion thresholds
PROMOTION_TO_GRADUATED_RUNS = 20       # runs
PROMOTION_TO_GRADUATED_SUCCESS = 0.90  # success rate over last N runs

PROMOTION_TO_CANONICAL_RUNS = 100
PROMOTION_TO_CANONICAL_SUCCESS = 0.95

# Demotion
DEMOTION_WINDOW = 10              # recent runs to inspect
DEMOTION_FAIL_THRESHOLD = 0.50   # >50% failures in last 10 → demote one tier

_TIER_ORDER: dict[SkillTier, int] = {
    "experimental": 0,
    "graduated": 1,
    "canonical": 2,
}


@dataclass(frozen=True)
class SkillRecord:
    """Immutable snapshot of a skill's journey state."""

    name: str
    tier: SkillTier = "experimental"
    success_count: int = 0
    failure_count: int = 0
    total_runs: int = 0
    last_run_at: str | None = None
    promoted_at: str | None = None
    demoted_at: str | None = None

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.success_count / self.total_runs

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tier": self.tier,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_runs": self.total_runs,
            "success_rate": self.success_rate,
            "last_run_at": self.last_run_at,
            "promoted_at": self.promoted_at,
            "demoted_at": self.demoted_at,
        }


@dataclass(frozen=True)
class AgentProficiency:
    """Per-agent × per-skill proficiency record."""

    skill: str
    agent_id: str
    success_count: int = 0
    failure_count: int = 0
    last_run_at: str | None = None

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.5

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "agent_id": self.agent_id,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "last_run_at": self.last_run_at,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillJourney:
    """Domain logic for the Skill Journey ledger.

    Uses SkillStore for persistence; stateless between calls.
    """

    def __init__(self, store: "SkillStore") -> None:
        self._store = store
        self._trust_manager: object | None = None

    def set_trust_manager(self, tm: object) -> None:
        """Inject trust_score manager for Dojo ranking integration (S15)."""
        self._trust_manager = tm

    def get_or_create(self, skill: str) -> SkillRecord:
        """Return the SkillRecord for a skill, creating it if new."""
        rec = self._store.get_skill(skill)
        if rec is None:
            rec = SkillRecord(name=skill)
            self._store.upsert_skill(rec)
        return rec

    def record_outcome(
        self,
        skill: str,
        success: bool,
        agent_id: str = "",
    ) -> SkillRecord:
        """Record a WO outcome and return the updated SkillRecord.

        Triggers promotion/demotion checks after recording.
        """
        rec = self.get_or_create(skill)
        now = _now_iso()

        updated = replace(
            rec,
            success_count=rec.success_count + (1 if success else 0),
            failure_count=rec.failure_count + (0 if success else 1),
            total_runs=rec.total_runs + 1,
            last_run_at=now,
        )
        updated = self._apply_promotion_demotion(updated)
        self._store.upsert_skill(updated)

        # Record per-agent proficiency
        if agent_id:
            self._record_agent_outcome(skill, agent_id, success, now)
            # S15: inform trust manager
            if self._trust_manager is not None:
                try:
                    self._trust_manager.record_skill_outcome(agent_id, skill, success)  # type: ignore
                except Exception:
                    log.exception("trust_manager.record_skill_outcome failed for %s/%s", agent_id, skill)

        return updated

    def _record_agent_outcome(
        self, skill: str, agent_id: str, success: bool, now: str
    ) -> None:
        prof = self._store.get_agent_proficiency(skill, agent_id)
        if prof is None:
            prof = AgentProficiency(skill=skill, agent_id=agent_id)
        updated = replace(
            prof,
            success_count=prof.success_count + (1 if success else 0),
            failure_count=prof.failure_count + (0 if success else 1),
            last_run_at=now,
        )
        self._store.upsert_agent_proficiency(updated)

    def _apply_promotion_demotion(self, rec: SkillRecord) -> SkillRecord:
        """Check thresholds and apply tier promotion or demotion."""
        now = _now_iso()
        tier = rec.tier

        # Promotion check (ascending)
        if tier == "experimental" and rec.total_runs >= PROMOTION_TO_GRADUATED_RUNS:
            if rec.success_rate >= PROMOTION_TO_GRADUATED_SUCCESS:
                log.info("Skill %r promoted: experimental → graduated (sr=%.2f, runs=%d)",
                         rec.name, rec.success_rate, rec.total_runs)
                return replace(rec, tier="graduated", promoted_at=now)

        elif tier == "graduated" and rec.total_runs >= PROMOTION_TO_CANONICAL_RUNS:
            if rec.success_rate >= PROMOTION_TO_CANONICAL_SUCCESS:
                log.info("Skill %r promoted: graduated → canonical (sr=%.2f, runs=%d)",
                         rec.name, rec.success_rate, rec.total_runs)
                return replace(rec, tier="canonical", promoted_at=now)

        # Demotion check (rolling window — approximate via overall stats)
        # Demotion is only applied once per window to avoid oscillation.
        if rec.total_runs >= DEMOTION_WINDOW:
            recent_fail_rate = rec.failure_count / rec.total_runs
            if recent_fail_rate > DEMOTION_FAIL_THRESHOLD:
                current_order = _TIER_ORDER.get(tier, 0)
                if current_order > 0:
                    new_tier: SkillTier = (
                        "graduated" if tier == "canonical" else "experimental"
                    )
                    log.warning(
                        "Skill %r demoted: %s → %s (fail_rate=%.2f)",
                        rec.name, tier, new_tier, recent_fail_rate,
                    )
                    return replace(rec, tier=new_tier, demoted_at=now)

        return rec

    def list_skills(self) -> list[SkillRecord]:
        """Return all skill records sorted by tier desc then name."""
        records = self._store.list_skills()
        return sorted(
            records,
            key=lambda r: (-_TIER_ORDER.get(r.tier, 0), r.name),
        )

    def get_agent_proficiency(self, skill: str, agent_id: str) -> AgentProficiency | None:
        """Return per-agent proficiency for a skill, or None if unseen."""
        return self._store.get_agent_proficiency(skill, agent_id)
