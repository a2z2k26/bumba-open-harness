"""MS5.1 — Trust Score System.

Per-capability trust scoring (0-100) based on track record.
Trust scores govern what the agent can do autonomously, what requires
approval, and what is disabled.

Seven capability domains: deploy, memory_edit, service_management,
escalation, routing, search, external_communication.

Four gating tiers:
  DISABLED        (score < 30)  — blocked, all attempts logged
  APPROVAL_REQUIRED (30-59)     — queued for operator approval
  AUTO_LOGGED     (60-89)       — auto-executed, full audit log
  AUTO_SILENT     (score >= 90) — auto-executed, minimal logging
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAPABILITY_DOMAINS = (
    "deploy",
    "memory_edit",
    "service_management",
    "escalation",
    "routing",
    "search",
    "external_communication",
)

INITIAL_SCORE = 50.0
MIN_SAMPLE_SIZE = 10
HISTORY_RETENTION_DAYS = 365
ROLLING_WINDOW_DAYS = 90
COOLDOWN_SECONDS = 86_400  # 24 hours after critical failure

# Tier boundaries
TIER_DISABLED_MAX = 30
TIER_APPROVAL_MAX = 60
TIER_AUTO_LOGGED_MAX = 90

# Score component weights
W_SUCCESS_RATE = 0.40
W_CONSISTENCY = 0.20
W_NO_ROLLBACKS = 0.20
W_APPROVAL_RATE = 0.20

# Penalty magnitudes
PENALTY_MINOR = 5
PENALTY_MAJOR = 15
PENALTY_CRITICAL = 30


# ---------------------------------------------------------------------------
# Tier names
# ---------------------------------------------------------------------------

TIER_DISABLED = "DISABLED"
TIER_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
TIER_AUTO_LOGGED = "AUTO_LOGGED"
TIER_AUTO_SILENT = "AUTO_SILENT"


def score_to_tier(score: float) -> str:
    """Map a numeric score to its gating tier."""
    if score < TIER_DISABLED_MAX:
        return TIER_DISABLED
    if score < TIER_APPROVAL_MAX:
        return TIER_APPROVAL_REQUIRED
    if score < TIER_AUTO_LOGGED_MAX:
        return TIER_AUTO_LOGGED
    return TIER_AUTO_SILENT


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AccessResult:
    """Result of a capability access check."""

    allowed: bool = False
    tier: str = ""
    requires_approval: bool = False
    cooldown_remaining: float = 0.0


@dataclass
class ScoreEvent:
    """A recorded event affecting a trust score."""

    timestamp: str = ""
    capability: str = ""
    old_score: float = 0.0
    new_score: float = 0.0
    reason: str = ""
    event_type: str = ""  # success|failure|rollback|operator_approved|operator_rejected|manual_override|recovery
    event_id: str = ""


@dataclass
class RecoveryState:
    """Per-capability recovery tracking after score drops."""

    drop_amount: float = 0.0
    successes_needed: int = 0
    successes_so_far: int = 0
    points_per_success: float = 0.0
    active: bool = False


@dataclass
class CapabilityScore:
    """Full state for a single capability domain."""

    score: float = INITIAL_SCORE
    total_actions: int = 0
    successes: int = 0
    failures: int = 0
    rollbacks: int = 0
    approvals: int = 0
    rejections: int = 0
    last_event: str = ""
    override_tier: str | None = None
    cooldown_until: float = 0.0
    recovery: RecoveryState = field(default_factory=RecoveryState)


# ---------------------------------------------------------------------------
# TrustScoreEngine
# ---------------------------------------------------------------------------


class TrustScoreEngine:
    """Per-capability trust scoring with tier-based gating."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else None
        self._lock = threading.Lock()
        self._scores: dict[str, CapabilityScore] = {}
        self._history: list[ScoreEvent] = []
        self._load()

    # -- persistence --------------------------------------------------------

    def _scores_path(self) -> Path | None:
        return self._data_dir / "trust_scores.json" if self._data_dir else None

    def _history_path(self) -> Path | None:
        return self._data_dir / "trust_history.jsonl" if self._data_dir else None

    def _load(self) -> None:
        """Load scores from disk, initialising missing domains."""
        for cap in CAPABILITY_DOMAINS:
            self._scores[cap] = CapabilityScore()

        path = self._scores_path()
        if path and path.exists():
            try:
                raw = json.loads(path.read_text())
                for cap, data in raw.items():
                    if cap in self._scores:
                        cs = self._scores[cap]
                        cs.score = data.get("score", INITIAL_SCORE)
                        cs.total_actions = data.get("total_actions", 0)
                        cs.successes = data.get("successes", 0)
                        cs.failures = data.get("failures", 0)
                        cs.rollbacks = data.get("rollbacks", 0)
                        cs.approvals = data.get("approvals", 0)
                        cs.rejections = data.get("rejections", 0)
                        cs.last_event = data.get("last_event", "")
                        cs.override_tier = data.get("override_tier")
                        cs.cooldown_until = data.get("cooldown_until", 0.0)
                        rec = data.get("recovery", {})
                        cs.recovery = RecoveryState(
                            drop_amount=rec.get("drop_amount", 0.0),
                            successes_needed=rec.get("successes_needed", 0),
                            successes_so_far=rec.get("successes_so_far", 0),
                            points_per_success=rec.get("points_per_success", 0.0),
                            active=rec.get("active", False),
                        )
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Failed to load trust scores: %s", exc)

        # Load history
        hpath = self._history_path()
        if hpath and hpath.exists():
            try:
                for line in hpath.read_text().splitlines():
                    if line.strip():
                        d = json.loads(line)
                        self._history.append(ScoreEvent(**d))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Failed to load trust history: %s", exc)

    def _save(self) -> None:
        """Persist scores to disk."""
        path = self._scores_path()
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for cap, cs in self._scores.items():
            data[cap] = {
                "score": cs.score,
                "total_actions": cs.total_actions,
                "successes": cs.successes,
                "failures": cs.failures,
                "rollbacks": cs.rollbacks,
                "approvals": cs.approvals,
                "rejections": cs.rejections,
                "last_event": cs.last_event,
                "override_tier": cs.override_tier,
                "cooldown_until": cs.cooldown_until,
                "recovery": {
                    "drop_amount": cs.recovery.drop_amount,
                    "successes_needed": cs.recovery.successes_needed,
                    "successes_so_far": cs.recovery.successes_so_far,
                    "points_per_success": cs.recovery.points_per_success,
                    "active": cs.recovery.active,
                },
            }
        path.write_text(json.dumps(data, indent=2))

    def _append_history(self, event: ScoreEvent) -> None:
        """Append a score event to history."""
        self._history.append(event)
        hpath = self._history_path()
        if hpath:
            hpath.parent.mkdir(parents=True, exist_ok=True)
            with open(hpath, "a") as f:
                f.write(json.dumps({
                    "timestamp": event.timestamp,
                    "capability": event.capability,
                    "old_score": event.old_score,
                    "new_score": event.new_score,
                    "reason": event.reason,
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                }) + "\n")

    # -- core API -----------------------------------------------------------

    def get_score(self, capability: str) -> float:
        """Get current trust score for a capability domain."""
        cs = self._scores.get(capability)
        return cs.score if cs else INITIAL_SCORE

    def get_tier(self, capability: str) -> str:
        """Get current tier, respecting operator overrides."""
        cs = self._scores.get(capability)
        if not cs:
            return score_to_tier(INITIAL_SCORE)
        if cs.override_tier:
            return cs.override_tier
        return score_to_tier(cs.score)

    def get_all_scores(self) -> dict[str, float]:
        """Get scores for all capability domains."""
        return {cap: cs.score for cap, cs in self._scores.items()}

    def get_capability_state(self, capability: str) -> CapabilityScore | None:
        """Get full state for a capability domain."""
        return self._scores.get(capability)

    def check_access(self, capability: str) -> AccessResult:
        """Check if a capability action is allowed under current trust level."""
        cs = self._scores.get(capability)
        if not cs:
            return AccessResult(allowed=False, tier=TIER_DISABLED)

        # Check cooldown
        now = time.time()
        if cs.cooldown_until > now:
            return AccessResult(
                allowed=False,
                tier=TIER_DISABLED,
                cooldown_remaining=cs.cooldown_until - now,
            )

        tier = self.get_tier(capability)
        if tier == TIER_DISABLED:
            return AccessResult(allowed=False, tier=tier)
        if tier == TIER_APPROVAL_REQUIRED:
            return AccessResult(allowed=False, tier=tier, requires_approval=True)
        return AccessResult(allowed=True, tier=tier)

    # -- score updates ------------------------------------------------------

    def record_event(
        self,
        capability: str,
        event_type: str,
        reason: str = "",
        event_id: str = "",
        severity: str = "minor",
    ) -> float:
        """Record an event and update the trust score.

        event_type: success | failure | rollback | operator_approved |
                    operator_rejected
        severity: minor | major | critical (only for failure/rollback)

        Returns the new score.
        """
        with self._lock:
            cs = self._scores.get(capability)
            if not cs:
                return INITIAL_SCORE

            old_score = cs.score
            cs.total_actions += 1
            now_iso = datetime.now(timezone.utc).isoformat()
            cs.last_event = now_iso

            if event_type == "success":
                cs.successes += 1
                self._handle_success(cs)
            elif event_type == "failure":
                cs.failures += 1
                self._handle_failure(cs, severity)
            elif event_type == "rollback":
                cs.rollbacks += 1
                self._handle_failure(cs, "major")
            elif event_type == "operator_approved":
                cs.approvals += 1
                self._handle_success(cs)
            elif event_type == "operator_rejected":
                cs.rejections += 1
                self._handle_failure(cs, "minor")

            # Clamp
            cs.score = max(0.0, min(100.0, cs.score))

            # Recalculate score from components if enough samples
            if cs.total_actions >= MIN_SAMPLE_SIZE:
                cs.score = self._compute_score(cs)

            cs.score = max(0.0, min(100.0, cs.score))

            self._append_history(ScoreEvent(
                timestamp=now_iso,
                capability=capability,
                old_score=old_score,
                new_score=cs.score,
                reason=reason,
                event_type=event_type,
                event_id=event_id,
            ))
            self._save()
            return cs.score

    def _compute_score(self, cs: CapabilityScore) -> float:
        """Compute weighted trust score from components."""
        # Success rate (0-100)
        success_rate = (cs.successes / cs.total_actions * 100) if cs.total_actions > 0 else 50.0

        # Consistency: we approximate as inverse of failure ratio volatility
        # Simple: high success rate with few failures = high consistency
        failure_ratio = cs.failures / cs.total_actions if cs.total_actions > 0 else 0.0
        consistency = (1.0 - failure_ratio) * 100

        # No rollbacks (0-100)
        if cs.total_actions > 0:
            no_rollbacks = (1.0 - cs.rollbacks / cs.total_actions) * 100
        else:
            no_rollbacks = 100.0

        # Operator approval rate (0-100)
        total_reviews = cs.approvals + cs.rejections
        if total_reviews > 0:
            approval_rate = cs.approvals / total_reviews * 100
        else:
            approval_rate = 50.0  # neutral when no reviews

        score = (
            success_rate * W_SUCCESS_RATE
            + consistency * W_CONSISTENCY
            + no_rollbacks * W_NO_ROLLBACKS
            + approval_rate * W_APPROVAL_RATE
        )
        return score

    def _handle_success(self, cs: CapabilityScore) -> None:
        """Process a success event, including recovery logic."""
        if cs.recovery.active:
            cs.recovery.successes_so_far += 1
            cs.score += cs.recovery.points_per_success
            if cs.recovery.successes_so_far >= cs.recovery.successes_needed:
                cs.recovery.active = False
        else:
            # Small boost for consistent success
            cs.score += 1.0

    def _handle_failure(self, cs: CapabilityScore, severity: str) -> None:
        """Process a failure event with severity-based penalties."""
        if severity == "critical":
            penalty = PENALTY_CRITICAL
            cs.cooldown_until = time.time() + COOLDOWN_SECONDS
        elif severity == "major":
            penalty = PENALTY_MAJOR
        else:
            penalty = PENALTY_MINOR

        cs.score -= penalty

        # Start recovery tracking
        successes_needed = max(1, math.ceil(penalty / 3))
        points_per = penalty / successes_needed
        cs.recovery = RecoveryState(
            drop_amount=penalty,
            successes_needed=successes_needed,
            successes_so_far=0,
            points_per_success=points_per,
            active=True,
        )

    # -- operator override --------------------------------------------------

    def set_override(self, capability: str, tier: str, reason: str = "") -> bool:
        """Manually override a capability's tier (operator action)."""
        valid_tiers = {TIER_DISABLED, TIER_APPROVAL_REQUIRED, TIER_AUTO_LOGGED, TIER_AUTO_SILENT}
        if tier not in valid_tiers:
            return False
        with self._lock:
            cs = self._scores.get(capability)
            if not cs:
                return False
            old_tier = self.get_tier(capability)
            cs.override_tier = tier
            self._append_history(ScoreEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                capability=capability,
                old_score=cs.score,
                new_score=cs.score,
                reason=f"Override: {old_tier} -> {tier}. {reason}",
                event_type="manual_override",
            ))
            self._save()
            return True

    def clear_override(self, capability: str) -> bool:
        """Clear an operator override, returning to score-based tier."""
        with self._lock:
            cs = self._scores.get(capability)
            if not cs:
                return False
            cs.override_tier = None
            self._save()
            return True

    # -- history queries ----------------------------------------------------

    def get_history(
        self, capability: str | None = None, limit: int = 50
    ) -> list[ScoreEvent]:
        """Get score change history, optionally filtered by capability."""
        events = self._history
        if capability:
            events = [e for e in events if e.capability == capability]
        return events[-limit:]

    def prune_history(self, retention_days: int = HISTORY_RETENTION_DAYS) -> int:
        """Remove history entries older than retention_days. Returns count removed."""
        cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
        original_count = len(self._history)
        self._history = [
            e for e in self._history
            if _parse_timestamp(e.timestamp) >= cutoff
        ]
        removed = original_count - len(self._history)
        if removed > 0:
            # Rewrite history file
            hpath = self._history_path()
            if hpath:
                with open(hpath, "w") as f:
                    for e in self._history:
                        f.write(json.dumps({
                            "timestamp": e.timestamp,
                            "capability": e.capability,
                            "old_score": e.old_score,
                            "new_score": e.new_score,
                            "reason": e.reason,
                            "event_type": e.event_type,
                            "event_id": e.event_id,
                        }) + "\n")
        return removed

    # -- formatting ---------------------------------------------------------

    def format_trust_table(self) -> str:
        """Format all capability scores as a markdown table."""
        lines = [
            "| Capability | Score | Tier | Actions | Override |",
            "|------------|-------|------|---------|----------|",
        ]
        for cap in CAPABILITY_DOMAINS:
            cs = self._scores[cap]
            tier = self.get_tier(cap)
            override = cs.override_tier or "-"
            lines.append(
                f"| {cap} | {cs.score:.1f} | {tier} | {cs.total_actions} | {override} |"
            )
        return "\n".join(lines)

    def format_capability_detail(self, capability: str) -> str | None:
        """Format detailed view for a single capability."""
        cs = self._scores.get(capability)
        if not cs:
            return None

        tier = self.get_tier(capability)
        lines = [
            f"# Trust: {capability}",
            f"**Score**: {cs.score:.1f} / 100",
            f"**Tier**: {tier}",
            f"**Total Actions**: {cs.total_actions}",
            f"**Successes**: {cs.successes}",
            f"**Failures**: {cs.failures}",
            f"**Rollbacks**: {cs.rollbacks}",
            f"**Approvals**: {cs.approvals}",
            f"**Rejections**: {cs.rejections}",
        ]

        if cs.override_tier:
            lines.append(f"**Override Tier**: {cs.override_tier}")

        if cs.recovery.active:
            lines.append("")
            lines.append("## Recovery In Progress")
            lines.append(
                f"Successes needed: {cs.recovery.successes_needed} "
                f"(have {cs.recovery.successes_so_far})"
            )

        # Recent history
        recent = self.get_history(capability, limit=5)
        if recent:
            lines.extend(["", "## Recent Events"])
            for e in recent:
                lines.append(
                    f"- [{e.event_type}] {e.old_score:.1f} -> {e.new_score:.1f}: {e.reason}"
                )

        return "\n".join(lines)


    # -----------------------------------------------------------------------
    # S15 — Per-skill proficiency (Dojo ranking)
    # -----------------------------------------------------------------------

    def get_skill_proficiency(self, agent_id: str, skill: str) -> float:
        """Return per-agent × per-skill proficiency score in [0.0, 1.0].

        Returns 0.5 as the default for any unseen (agent_id, skill) pair
        (middle-ground — not penalised, not trusted).

        Delegates to the SkillStore if one is wired in via set_skill_store().
        Falls back to 0.5 if no store is available.
        """
        store = getattr(self, "_skill_store", None)
        if store is None:
            return 0.5
        try:
            prof = store.get_agent_proficiency(skill, agent_id)
            if prof is None:
                return 0.5
            return prof.success_rate
        except Exception:
            log.exception("get_skill_proficiency failed for agent=%s skill=%s", agent_id, skill)
            return 0.5

    def record_skill_outcome(self, agent_id: str, skill: str, success: bool) -> None:
        """Record a skill execution outcome for an agent.

        Updates the per-agent proficiency in the SkillStore.
        No-op if no store is wired.
        """
        store = getattr(self, "_skill_store", None)
        if store is None:
            return
        try:
            from bridge.skill_journey import AgentProficiency
            from dataclasses import replace as dc_replace
            from datetime import datetime, timezone

            prof = store.get_agent_proficiency(skill, agent_id)
            if prof is None:
                prof = AgentProficiency(skill=skill, agent_id=agent_id)
            updated = dc_replace(
                prof,
                success_count=prof.success_count + (1 if success else 0),
                failure_count=prof.failure_count + (0 if success else 1),
                last_run_at=datetime.now(timezone.utc).isoformat(),
            )
            store.upsert_agent_proficiency(updated)
        except Exception:
            log.exception("record_skill_outcome failed for agent=%s skill=%s", agent_id, skill)

    def set_skill_store(self, store: object) -> None:
        """Wire a SkillStore instance for per-skill proficiency persistence."""
        self._skill_store = store


def _parse_timestamp(ts: str) -> float:
    """Parse ISO8601 timestamp to unix epoch."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0
