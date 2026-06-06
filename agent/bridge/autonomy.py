"""Phase 5 Autonomy Integration Layer.

Central orchestration point for all Phase 5 autonomy modules:
guardrails, event bus, escalation, trust scoring, tier management,
discovery/proposals, and digest generation.

Wire this into BridgeApp to activate all autonomy features.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .discovery import ProposalStore, ScanCache
from .escalation import EscalationEngine
from .event_bus import EventBus
from .guardrails import GuardrailEngine, GuardrailConfig
from .tier_manager import TierManager
from .trust_score import TrustScoreEngine

log = logging.getLogger(__name__)


class AutonomyLayer:
    """Unified access to all Phase 5 autonomy engines."""

    def __init__(self, data_dir: Path, operator_mention: str = "") -> None:
        self._data_dir = data_dir

        # Ensure subdirectories exist
        (data_dir / "events").mkdir(parents=True, exist_ok=True)
        (data_dir / "proposals").mkdir(parents=True, exist_ok=True)

        # Instantiate all engines
        self._guardrails = GuardrailEngine(
            config=GuardrailConfig(),
            incident_path=data_dir / "guardrail_incidents.jsonl",
        )
        self._event_bus = EventBus(data_dir=data_dir)
        self._escalation = EscalationEngine(
            state_dir=data_dir / "service_state",
            operator_mention=operator_mention,
        )
        self._trust = TrustScoreEngine(data_dir=data_dir)
        self._tiers = TierManager(
            data_path=data_dir / "tier_assignments.json",
        )
        self._proposals = ProposalStore(
            proposals_dir=data_dir / "proposals",
        )
        self._scan_cache = ScanCache(
            cache_path=data_dir / "scan_cache.json",
        )

    # -- Properties for engine access --

    @property
    def guardrails(self) -> GuardrailEngine:
        return self._guardrails

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    @property
    def escalation(self) -> EscalationEngine:
        return self._escalation

    @property
    def trust(self) -> TrustScoreEngine:
        return self._trust

    @property
    def tiers(self) -> TierManager:
        return self._tiers

    @property
    def proposals(self) -> ProposalStore:
        return self._proposals

    @property
    def scan_cache(self) -> ScanCache:
        return self._scan_cache

    # -- Lifecycle --

    async def initialize(self) -> None:
        """Load persisted state for all engines."""
        log.info("Autonomy layer initializing...")
        self._escalation.load_state()
        log.info("Autonomy layer initialized (guardrails, event_bus, escalation, trust, tiers, proposals)")

    async def shutdown(self) -> None:
        """Persist state for all engines before shutdown."""
        log.info("Autonomy layer shutting down...")
        try:
            self._trust._save()
        except Exception as e:
            log.warning("Failed to save trust scores: %s", e)
        try:
            self._escalation.save_state()
        except Exception as e:
            log.warning("Failed to save escalation state: %s", e)
        log.info("Autonomy layer shutdown complete")

    # -- Convenience methods --

    def build_weekly_digest(self) -> str:
        """Build a weekly digest from current autonomy state."""
        from .digest import build_digest_data, format_digest
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        week_end = now.strftime("%Y-%m-%d")

        # Gather trust scores
        trust_scores = self._trust.get_all_scores()

        # Gather trust change history
        trust_changes = []
        for event in self._trust.get_history(limit=50):
            trust_changes.append({
                "capability": event.capability,
                "old_score": event.old_score,
                "new_score": event.new_score,
            })

        # Gather pending proposals
        pending = self._proposals.list_pending()
        pending_dicts = [
            {"name": p.name, "priority_score": p.priority_score}
            for p in pending
        ]

        data = build_digest_data(
            trust_scores=trust_scores,
            trust_changes=trust_changes,
            pending_proposals=pending_dicts,
            week_start=week_start,
            week_end=week_end,
        )
        return format_digest(data)

    def scan_for_proposals(self, docs_dir: Path) -> list[str]:
        """Scan documents for feature ideas, deduplicate, save new proposals."""
        from .discovery import extract_feature_ideas, is_duplicate, file_hash, FeatureProposal, FeasibilityScore

        new_proposals: list[str] = []
        existing = self._proposals.list_all()

        for doc_path in sorted(docs_dir.rglob("*.md")):
            if not self._scan_cache.is_changed(doc_path):
                continue

            try:
                text = doc_path.read_text(errors="replace")
            except OSError:
                continue

            doc_h = file_hash(doc_path)
            ideas = extract_feature_ideas(text, source_doc=str(doc_path), doc_hash=doc_h)

            for idea in ideas:
                dup = is_duplicate(idea.name, idea.description, existing)
                if dup:
                    continue

                proposal = FeatureProposal(
                    name=idea.name,
                    source_document=idea.source_doc,
                    source_quote=idea.source_quote,
                    description=idea.description,
                    feasibility=FeasibilityScore(),
                )
                self._proposals.save(proposal)
                existing.append(proposal)
                new_proposals.append(idea.name)

            self._scan_cache.mark_scanned(doc_path)

        return new_proposals


# ---------------------------------------------------------------------------
# Sprint-mode subprocess lifecycle (#262)
# ---------------------------------------------------------------------------

SPRINT_MAX_TURNS = 200


async def run_sprint_mode(
    plan_path: Path,
    state_path: Path,
    claude_runner: object,
    *,
    max_turns: int = SPRINT_MAX_TURNS,
    on_phase_boundary: object | None = None,
) -> list[dict]:
    """Outer loop: one fresh subprocess per sprint.

    Reads sprint-state.md, finds the next actionable sprint, launches
    a fresh Claude Code subprocess for it, and repeats until all sprints
    are complete or blocked.

    Each subprocess re-reads CLAUDE.md, sprint-state.md, and the plan
    source at boot — no stale context carryover.

    Args:
        plan_path: Path to the plan markdown file.
        state_path: Path to sprint-state.md.
        claude_runner: ClaudeRunner instance (must support invoke()).
        max_turns: Max conversation turns per sprint subprocess.
        on_phase_boundary: Optional async callback(current_phase, next_phase)
            that pauses for operator proceed. If None, phase boundaries
            are logged but not gated.

    Returns:
        List of sprint result dicts with sprint_id, status, duration_s.
    """
    import asyncio
    import time
    from .plan_state import load_sprint_state, next_actionable_sprint, format_sprint_context

    results: list[dict] = []
    last_phase: str | None = None

    while True:
        # Re-read state file every iteration (externalized state)
        rows = load_sprint_state(state_path)
        sprint = next_actionable_sprint(rows)

        if sprint is None:
            log.info("sprint_mode.complete: no actionable sprints remain")
            break

        # Phase boundary check
        if last_phase is not None and sprint.phase != last_phase:
            log.info(
                "sprint_mode.phase_boundary: %s -> %s (sprint %s)",
                last_phase, sprint.phase, sprint.sprint_id,
            )
            if on_phase_boundary is not None:
                try:
                    await on_phase_boundary(last_phase, sprint.phase)
                except asyncio.CancelledError:
                    log.info("sprint_mode.halted: operator cancelled at phase boundary")
                    break

        last_phase = sprint.phase

        # Build sprint context for injection
        context = format_sprint_context(rows)
        sprint_prompt = (
            f"You are executing Sprint {sprint.sprint_id} (Phase {sprint.phase}).\n"
            f"Read the plan at: {plan_path}\n"
            f"Read the sprint state at: {state_path}\n\n"
            f"{context}\n\n"
            f"Execute ONLY Sprint {sprint.sprint_id}. Do not skip or reorder sprints. "
            f"When complete, update sprint-state.md to mark this sprint as 'complete'."
        )

        log.info(
            "sprint_mode.start: sprint=%s phase=%s max_turns=%d",
            sprint.sprint_id, sprint.phase, max_turns,
        )
        start = time.monotonic()

        try:
            # Fresh session — no --resume, clean context window
            result = await claude_runner.invoke(
                text=sprint_prompt,
                session_id=None,  # fresh session
                max_turns=max_turns,
            )
            duration = time.monotonic() - start

            results.append({
                "sprint_id": sprint.sprint_id,
                "phase": sprint.phase,
                "status": "completed" if result and getattr(result, "response_text", "") else "no_output",
                "duration_s": round(duration, 1),
            })

            log.info(
                "sprint_mode.done: sprint=%s duration=%.1fs",
                sprint.sprint_id, duration,
            )

        except Exception as e:
            duration = time.monotonic() - start
            log.error(
                "sprint_mode.error: sprint=%s error=%s duration=%.1fs",
                sprint.sprint_id, e, duration,
            )
            results.append({
                "sprint_id": sprint.sprint_id,
                "phase": sprint.phase,
                "status": "error",
                "error": str(e)[:200],
                "duration_s": round(duration, 1),
            })
            break  # Don't continue on error — let operator investigate

    return results
