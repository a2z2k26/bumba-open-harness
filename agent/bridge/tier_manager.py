"""MS5.4 — Graduated Kernel Access.

Trust-based tier migration for files. Files earn higher autonomy
tiers through demonstrated track record. Tier A files are immutable.

Tier hierarchy:
  A  — kernel/identity, never promotable
  B  — admin-only write, agent-read
  B+ — agent-prepare, admin-execute
  C  — agent-deployable
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIER_A = "A"
TIER_B = "B"
TIER_B_PLUS = "B+"
TIER_C = "C"

ALL_TIERS = (TIER_A, TIER_B, TIER_B_PLUS, TIER_C)

# Immutable files — NEVER promotable, always Tier A
IMMUTABLE_FILES = frozenset({
    "security.py",
    "trust_score.py",
    "tier_manager.py",
    "kernel-baseline.json",
    "system-prompt.md",
})

# Promotion criteria
C_TO_BPLUS_TRUST_MIN = 80
C_TO_BPLUS_DEPLOY_MIN = 30
C_TO_BPLUS_FILE_DEPLOY_MIN = 5
C_TO_BPLUS_ROLLBACK_FREE_DAYS = 30

BPLUS_TO_B_TRUST_MIN = 90
BPLUS_TO_B_DEPLOY_MIN = 100
BPLUS_TO_B_DAYS_IN_TIER = 60

PROMOTION_COOLDOWN_HOURS = 24


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TierHistoryEntry:
    """A single tier change record."""

    tier: str = ""
    assigned_date: str = ""
    reason: str = ""


@dataclass
class FileTracking:
    """Per-file tier tracking state."""

    path: str = ""
    current_tier: str = TIER_C
    tier_history: list[TierHistoryEntry] = field(default_factory=list)
    deploy_count: int = 0
    rollback_count: int = 0
    last_deploy: str = ""
    last_rollback: str = ""
    locked: bool = False
    lock_reason: str = ""
    promoted_at: str = ""  # when last promotion was applied


# ---------------------------------------------------------------------------
# TierManager
# ---------------------------------------------------------------------------


class TierManager:
    """Manages per-file tier assignments and promotions."""

    def __init__(self, data_path: Path | None = None) -> None:
        self._path = data_path
        self._files: dict[str, FileTracking] = {}
        self._load()

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for fpath, data in raw.items():
                ft = FileTracking(
                    path=fpath,
                    current_tier=data.get("current_tier", TIER_C),
                    deploy_count=data.get("deploy_count", 0),
                    rollback_count=data.get("rollback_count", 0),
                    last_deploy=data.get("last_deploy", ""),
                    last_rollback=data.get("last_rollback", ""),
                    locked=data.get("locked", False),
                    lock_reason=data.get("lock_reason", ""),
                    promoted_at=data.get("promoted_at", ""),
                )
                for h in data.get("tier_history", []):
                    ft.tier_history.append(TierHistoryEntry(**h))
                self._files[fpath] = ft
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load tier assignments: %s", exc)

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        raw: dict = {}
        for fpath, ft in self._files.items():
            raw[fpath] = {
                "current_tier": ft.current_tier,
                "deploy_count": ft.deploy_count,
                "rollback_count": ft.rollback_count,
                "last_deploy": ft.last_deploy,
                "last_rollback": ft.last_rollback,
                "locked": ft.locked,
                "lock_reason": ft.lock_reason,
                "promoted_at": ft.promoted_at,
                "tier_history": [
                    {"tier": h.tier, "assigned_date": h.assigned_date, "reason": h.reason}
                    for h in ft.tier_history
                ],
            }
        self._path.write_text(json.dumps(raw, indent=2))

    # -- file tracking ------------------------------------------------------

    def get_file(self, path: str) -> FileTracking | None:
        """Get tracking data for a file."""
        return self._files.get(path)

    def register_file(
        self, path: str, tier: str = TIER_C, locked: bool = False, lock_reason: str = ""
    ) -> FileTracking:
        """Register a file for tier tracking."""
        if path in self._files:
            return self._files[path]
        ft = FileTracking(
            path=path,
            current_tier=tier,
            locked=locked,
            lock_reason=lock_reason,
        )
        ft.tier_history.append(TierHistoryEntry(
            tier=tier,
            assigned_date=datetime.now(timezone.utc).isoformat(),
            reason="initial registration",
        ))
        self._files[path] = ft
        self._save()
        return ft

    def list_files(self, tier: str | None = None) -> list[FileTracking]:
        """List tracked files, optionally filtered by tier."""
        files = list(self._files.values())
        if tier:
            files = [f for f in files if f.current_tier == tier]
        return files

    def is_immutable(self, path: str) -> bool:
        """Check if a file is in the immutable set (Tier A forever)."""
        filename = Path(path).name
        return filename in IMMUTABLE_FILES

    # -- deploy tracking ----------------------------------------------------

    def record_deploy(self, path: str, success: bool) -> None:
        """Record a deploy event for a file."""
        ft = self._files.get(path)
        if not ft:
            ft = self.register_file(path)
        now = datetime.now(timezone.utc).isoformat()
        if success:
            ft.deploy_count += 1
            ft.last_deploy = now
        else:
            ft.rollback_count += 1
            ft.last_rollback = now
        self._save()

    # -- promotion checks ---------------------------------------------------

    def check_c_to_bplus(
        self, path: str, trust_score: float, total_deploys: int
    ) -> tuple[bool, str]:
        increment_module_counter("tier_manager.check_c_to_bplus", tier=1)
        """Check if a file qualifies for C → B+ promotion.

        Returns (eligible, reason).
        """
        if self.is_immutable(path):
            return False, "Immutable file (Tier A)"

        ft = self._files.get(path)
        if not ft:
            return False, "File not tracked"
        if ft.locked:
            return False, f"File locked: {ft.lock_reason}"
        if ft.current_tier != TIER_C:
            return False, f"Not at Tier C (currently {ft.current_tier})"

        if trust_score < C_TO_BPLUS_TRUST_MIN:
            return False, f"Trust score {trust_score:.1f} < {C_TO_BPLUS_TRUST_MIN}"
        if total_deploys < C_TO_BPLUS_DEPLOY_MIN:
            return False, f"Total deploys {total_deploys} < {C_TO_BPLUS_DEPLOY_MIN}"
        if ft.deploy_count < C_TO_BPLUS_FILE_DEPLOY_MIN:
            return False, f"File deploys {ft.deploy_count} < {C_TO_BPLUS_FILE_DEPLOY_MIN}"

        # Check rollback-free period
        if ft.last_rollback:
            try:
                rb_dt = datetime.fromisoformat(ft.last_rollback)
                days_since = (datetime.now(timezone.utc) - rb_dt).days
                if days_since < C_TO_BPLUS_ROLLBACK_FREE_DAYS:
                    return False, f"Rollback {days_since} days ago (need {C_TO_BPLUS_ROLLBACK_FREE_DAYS})"
            except ValueError:
                pass

        return True, "All criteria met"

    def check_bplus_to_b(
        self, path: str, trust_score: float, total_deploys: int
    ) -> tuple[bool, str]:
        """Check if a file qualifies for B+ → B promotion."""
        if self.is_immutable(path):
            return False, "Immutable file (Tier A)"

        ft = self._files.get(path)
        if not ft:
            return False, "File not tracked"
        if ft.locked:
            return False, f"File locked: {ft.lock_reason}"
        if ft.current_tier != TIER_B_PLUS:
            return False, f"Not at Tier B+ (currently {ft.current_tier})"

        if trust_score < BPLUS_TO_B_TRUST_MIN:
            return False, f"Trust score {trust_score:.1f} < {BPLUS_TO_B_TRUST_MIN}"
        if total_deploys < BPLUS_TO_B_DEPLOY_MIN:
            return False, f"Total deploys {total_deploys} < {BPLUS_TO_B_DEPLOY_MIN}"

        # Check time in tier
        if ft.promoted_at:
            try:
                promo_dt = datetime.fromisoformat(ft.promoted_at)
                days_in_tier = (datetime.now(timezone.utc) - promo_dt).days
                if days_in_tier < BPLUS_TO_B_DAYS_IN_TIER:
                    return False, f"Only {days_in_tier} days in B+ (need {BPLUS_TO_B_DAYS_IN_TIER})"
            except ValueError:
                pass

        return True, "All criteria met (requires operator approval)"

    # -- promote / demote ---------------------------------------------------

    def promote(self, path: str, new_tier: str, reason: str = "") -> bool:
        """Promote a file to a higher tier."""
        ft = self._files.get(path)
        if not ft:
            return False
        if ft.locked:
            return False
        if self.is_immutable(path):
            return False

        old_tier = ft.current_tier
        ft.current_tier = new_tier
        now = datetime.now(timezone.utc).isoformat()
        ft.promoted_at = now
        ft.tier_history.append(TierHistoryEntry(
            tier=new_tier,
            assigned_date=now,
            reason=reason or f"Promoted from {old_tier} to {new_tier}",
        ))
        self._save()
        return True

    def demote(self, path: str, new_tier: str, reason: str = "") -> bool:
        """Demote a file to a lower tier. Resets deploy counters."""
        ft = self._files.get(path)
        if not ft:
            return False

        old_tier = ft.current_tier
        ft.current_tier = new_tier
        now = datetime.now(timezone.utc).isoformat()
        ft.promoted_at = ""
        # Reset counters on demotion
        ft.deploy_count = 0
        ft.rollback_count = 0
        ft.tier_history.append(TierHistoryEntry(
            tier=new_tier,
            assigned_date=now,
            reason=reason or f"Demoted from {old_tier} to {new_tier}",
        ))
        self._save()
        return True

    # -- audit --------------------------------------------------------------

    def audit(self, trust_scores: dict[str, float]) -> list[dict]:
        """Run audit checking tier assignments match trust scores.

        Returns list of inconsistencies found.
        """
        issues: list[dict] = []
        deploy_trust = trust_scores.get("deploy", 50.0)

        for path, ft in self._files.items():
            if ft.locked:
                continue

            # Check: file at B+ but trust below threshold
            if ft.current_tier == TIER_B_PLUS and deploy_trust < C_TO_BPLUS_TRUST_MIN:
                issues.append({
                    "path": path,
                    "issue": "trust_below_tier",
                    "current_tier": ft.current_tier,
                    "trust_score": deploy_trust,
                    "action": f"Should demote to C (trust {deploy_trust:.1f} < {C_TO_BPLUS_TRUST_MIN})",
                })

            # Check: file at B but trust below B threshold
            if ft.current_tier == TIER_B and deploy_trust < BPLUS_TO_B_TRUST_MIN:
                issues.append({
                    "path": path,
                    "issue": "trust_below_tier",
                    "current_tier": ft.current_tier,
                    "trust_score": deploy_trust,
                    "action": f"Should demote to B+ (trust {deploy_trust:.1f} < {BPLUS_TO_B_TRUST_MIN})",
                })

        return issues

    def count(self, tier: str | None = None) -> int:
        """Count tracked files."""
        if tier:
            return sum(1 for f in self._files.values() if f.current_tier == tier)
        return len(self._files)

    def format_tier_table(self) -> str:
        """Format tier assignments as markdown table."""
        if not self._files:
            return "_No files tracked._"
        lines = [
            "| File | Tier | Deploys | Rollbacks | Locked |",
            "|------|------|---------|-----------|--------|",
        ]
        for ft in sorted(self._files.values(), key=lambda f: f.path):
            locked = "yes" if ft.locked else "no"
            lines.append(
                f"| {ft.path} | {ft.current_tier} | {ft.deploy_count} "
                f"| {ft.rollback_count} | {locked} |"
            )
        return "\n".join(lines)
