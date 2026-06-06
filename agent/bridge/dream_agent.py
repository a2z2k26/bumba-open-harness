"""Restricted Claude subprocess for deep memory consolidation.

DreamAgent spawns claude with a read-only bash allowlist and memory-dir-only
write scope, executing a 4-phase consolidation prompt.

Phases:
    1. Orient      — Inventory the memory directory and daily logs
    2. Gather      — Collect candidate entries for consolidation
    3. Consolidate — Merge duplicates, resolve contradictions, update facts
    4. Prune       — Remove stale or superseded entries

Allowed bash operations: ls, find, grep, cat, stat, wc, head, tail, sort, uniq, diff
All destructive bash and network mutations are disallowed.

Mem-7 (#1848) — Memory-Tier Architecture Phase C (consolidation):
    A Python-side deterministic tier-ops phase runs BEFORE the LLM-side
    consolidation when `memory_tiers_enabled = True` and a database path
    is wired. The tier-ops phase operates on the SQLite `knowledge` table
    (within-tier dedup, threshold-based promotion, inactivity-based
    demotion). The LLM phase keeps its file-based scope but gets a
    tier-awareness hint when the flag is on.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bridge.config import BridgeConfig
from bridge.claude_runner import ClaudeRunner  # module-level import for patchability
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool restriction constants
# ---------------------------------------------------------------------------

DREAM_DISALLOWED_TOOLS = [
    "Bash(rm *)",
    "Bash(mv *)",
    "Bash(cp *)",
    "Bash(chmod *)",
    "Bash(chown *)",
    "Bash(sudo *)",
    "Bash(pip *)",
    "Bash(npm *)",
    "Bash(git push *)",
    "Bash(git commit *)",
    "Bash(curl -X POST *)",
    "Bash(curl -X PUT *)",
    "Bash(curl -X DELETE *)",
]

DREAM_ALLOWED_BASH = "ls, find, grep, cat, stat, wc, head, tail, sort, uniq, diff"


# ---------------------------------------------------------------------------
# Result dataclass (frozen / immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DreamResult:
    """Immutable result returned by DreamAgent.run().

    The first six fields carry the LLM-phase consolidation summary
    (parsed from the Haiku subprocess JSON response).

    Mem-7 (#1848) appended four fields covering the Python-side tier-ops
    phase. All default to 0 / empty dict so flag-off invocations and any
    existing `DreamResult(...)` construction keep working byte-identically.
    """

    success: bool
    summary: str
    files_touched: list[str]
    entries_pruned: int
    contradictions_resolved: int
    merges_performed: int
    error: str | None = None
    # Mem-7 (#1848) — tier-ops summary. Populated only when
    # `memory_tiers_enabled = True` AND a database path is wired into
    # `DreamAgent.__init__`; otherwise zeroed.
    tier_promotions: int = 0
    tier_demotions: int = 0
    tier_dedups: int = 0
    per_tier_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# DreamAgent
# ---------------------------------------------------------------------------


class DreamAgent:
    """Restricted Claude subprocess for deep memory consolidation."""

    def __init__(
        self,
        config: BridgeConfig,
        daily_log=None,
        *,
        database=None,
        metrics=None,
    ) -> None:
        """Construct a DreamAgent.

        Args:
            config: BridgeConfig — must carry `data_dir`, optionally the
                `memory_tiers_*` fields.
            daily_log: optional daily log writer (forwarded by the
                consolidation service).
            database: Mem-7 (#1848) — anything providing the async
                `execute(sql, params) -> cursor (with .rowcount)` and
                `fetchall(sql, params) -> rows` shape. In production this
                is a `bridge.database.Database` instance (or a thin wrapper
                that opens/closes its own connection per pass). Pass `None`
                to skip the Python-side tier-ops phase entirely — preserves
                back-compat with all existing test fixtures.
            metrics: Mem-9.5 (#1877) — optional `MetricsCollector` for
                per-tier `memory.tier.promotions.*` and
                `memory.tier.demotions.*` emits in `_run_tier_ops`.
                Optional to preserve back-compat with all existing
                construction sites.
        """
        self._config = config
        self._daily_log = daily_log
        self._data_dir = Path(config.data_dir)
        self._memory_dir = self._data_dir / "memory"
        # Mem-7 (#1848) — tier-ops database (lazy: None means skip).
        self._database = database
        # Mem-9.5 (#1877) — optional metrics for tier-op observability.
        self._metrics = metrics

    # ------------------------------------------------------------------
    # Directory management
    # ------------------------------------------------------------------

    def _ensure_memory_dir(self) -> None:
        """Create data/memory/ and data/memory/snapshots/ if missing."""
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        (self._memory_dir / "snapshots").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Mem-7 (#1848) — Python-side tier-ops phase
    # ------------------------------------------------------------------

    async def _run_tier_ops(self) -> tuple[int, int, int, dict[str, int]]:
        """Deterministic tier operations on the SQLite knowledge table.

        Three sub-phases in order:

        1. **Within-tier dedup** — remove exact duplicate `(tier, key, value)`
           triples, keeping the most recently accessed row by `accessed_at`.
           Cross-tier dedup is FORBIDDEN per Mem-7 spec — different tiers
           carry different semantics and collapsing across them is a category
           error.
        2. **Demotion** — rows whose `accessed_at` is older than the policy's
           `demotion_inactivity_seconds` AND whose tier has a lower neighbour
           are moved one tier down. Done BEFORE promotion so a single pass
           does not yo-yo a row.
        3. **Promotion** — rows whose `access_count` is at-or-above the
           policy's `promotion_access_threshold` AND whose tier has a higher
           neighbour are moved one tier up.

        Returns ``(promotions, demotions, dedups, per_tier_counts)``.
        ``per_tier_counts`` is the post-op count of non-archived rows per
        tier value (string keys, e.g. ``{"preference": 3, "decision": 7}``).

        No-op when ``self._database is None`` OR the
        ``memory_tiers_enabled`` flag is off — returns zeros and an empty
        dict without touching the database.
        """
        if self._database is None or not getattr(
            self._config, "memory_tiers_enabled", False
        ):
            return (0, 0, 0, {})

        from .memory_tiers import MemoryTier, load_tier_policies

        # If the wrapped Database has not been connected yet (the common
        # case when wired sync from `services/runner.py`), connect lazily
        # inside this coroutine — aiosqlite connections must be opened in
        # the event loop they're used in, and `_run_tier_ops` is the only
        # coroutine that touches the DB. Close it again at the end so we
        # leave no half-open WAL files on exit.
        opened_locally = False
        if (
            hasattr(self._database, "_conn")
            and getattr(self._database, "_conn", None) is None
            and hasattr(self._database, "connect")
        ):
            await self._database.connect()
            opened_locally = True

        policies = load_tier_policies(self._config)
        # CONTEXT (bottom) → DECISION → PREFERENCE (top). Index N+1 is the
        # promotion target; index N-1 is the demotion target.
        tier_order = [MemoryTier.CONTEXT, MemoryTier.DECISION, MemoryTier.PREFERENCE]

        promotions = 0
        demotions = 0
        dedups = 0

        # --- 1. Within-tier dedup -----------------------------------------
        # Conservative: only EXACT (tier, key, value) duplicates are
        # collapsed. Fuzzy dedup stays the LLM phase's job. For each
        # duplicate group, keep MAX(rowid) (the most recent insert, a
        # stable tie-breaker when accessed_at is NULL or equal) and
        # delete the rest. Cross-tier dedup is FORBIDDEN per spec.
        cursor = await self._database.execute(
            """
            DELETE FROM knowledge
            WHERE rowid IN (
                SELECT k.rowid FROM knowledge AS k
                JOIN (
                    SELECT tier, key, value, MAX(rowid) AS keep_rowid
                    FROM knowledge
                    WHERE archived IS NULL OR archived = 0
                    GROUP BY tier, key, value
                    HAVING COUNT(*) > 1
                ) AS keepers
                  ON keepers.tier = k.tier
                 AND keepers.key  = k.key
                 AND keepers.value = k.value
                WHERE k.rowid <> keepers.keep_rowid
                  AND (k.archived IS NULL OR k.archived = 0)
            )
            """
        )
        if cursor.rowcount and cursor.rowcount > 0:
            dedups += cursor.rowcount

        # --- 2. Demotion --------------------------------------------------
        # Done BEFORE promotion so a stale-but-accessed entry doesn't get
        # demoted right after being promoted in the same pass.
        for tier in tier_order:
            policy = policies.get(tier)
            if policy is None or policy.demotion_inactivity_seconds is None:
                continue
            idx = tier_order.index(tier)
            if idx == 0:
                # CONTEXT (bottom tier) — no lower neighbour. Treat any
                # demotion config as a no-op rather than failing loud.
                continue
            lower_tier = tier_order[idx - 1]
            cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=policy.demotion_inactivity_seconds
            )
            cutoff_iso = cutoff.isoformat()
            cursor = await self._database.execute(
                """
                UPDATE knowledge
                SET tier = ?
                WHERE tier = ?
                  AND accessed_at IS NOT NULL
                  AND accessed_at < ?
                  AND (archived IS NULL OR archived = 0)
                """,
                (lower_tier.value, tier.value, cutoff_iso),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                demotions += cursor.rowcount
                # Sprint Mem-9.5 (#1877) — emit `memory.tier.demotions`
                # counter labelled by (from, to) tier values. Label folded
                # into the metric name since MetricsCollector.observe takes
                # no labels: `memory.tier.demotions.<from>_to_<to>`.
                if self._metrics is not None:
                    self._metrics.observe(
                        f"memory.tier.demotions.{tier.value}_to_{lower_tier.value}",
                        float(cursor.rowcount),
                    )

        # --- 3. Promotion -------------------------------------------------
        for tier in tier_order:
            policy = policies.get(tier)
            if policy is None or policy.promotion_access_threshold <= 0:
                continue
            idx = tier_order.index(tier)
            if idx == len(tier_order) - 1:
                # PREFERENCE (top tier) — no higher neighbour.
                continue
            higher_tier = tier_order[idx + 1]
            cursor = await self._database.execute(
                """
                UPDATE knowledge
                SET tier = ?
                WHERE tier = ?
                  AND access_count >= ?
                  AND (archived IS NULL OR archived = 0)
                """,
                (higher_tier.value, tier.value, policy.promotion_access_threshold),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                promotions += cursor.rowcount
                # Sprint Mem-9.5 (#1877) — emit `memory.tier.promotions`
                # counter labelled by (from, to) tier values. Label folded
                # into the metric name since MetricsCollector.observe takes
                # no labels: `memory.tier.promotions.<from>_to_<to>`.
                if self._metrics is not None:
                    self._metrics.observe(
                        f"memory.tier.promotions.{tier.value}_to_{higher_tier.value}",
                        float(cursor.rowcount),
                    )

        # Commit the in-pass mutations so post-op counts reflect them.
        commit = getattr(self._database, "commit", None)
        if commit is not None:
            await commit()

        # --- 4. Per-tier counts (post-op) ---------------------------------
        rows = await self._database.fetchall(
            """
            SELECT tier, COUNT(*)
            FROM knowledge
            WHERE archived IS NULL OR archived = 0
            GROUP BY tier
            """
        )
        per_tier_counts: dict[str, int] = {}
        for r in rows:
            tier_key = r[0]
            count = r[1]
            if tier_key is None:
                continue
            per_tier_counts[str(tier_key)] = int(count)

        log.info(
            "DreamAgent tier-ops: promotions=%d demotions=%d dedups=%d per_tier=%s",
            promotions,
            demotions,
            dedups,
            per_tier_counts,
        )

        # If we opened the connection ourselves above, close it cleanly so
        # the WAL doesn't linger when DreamAgent is reused across runs.
        if opened_locally and hasattr(self._database, "close"):
            try:
                await self._database.close()
            except Exception as exc:
                log.debug("DreamAgent: tier-ops close raised %s; ignoring", exc)

        return (promotions, demotions, dedups, per_tier_counts)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(self, session_ids: list[str], extra: str = "") -> str:
        """Build the 4-phase consolidation prompt.

        When `memory_tiers_enabled = True` (Mem-7 #1848), a tier-awareness
        hint is appended so the LLM-side file-based judgement preserves
        tier markers and refuses to merge across tiers (semantics differ).
        When the flag is off, the prompt is byte-identical to pre-Mem-7.
        """
        logs_dir = self._data_dir / "logs"
        session_count = len(session_ids)

        if getattr(self._config, "memory_tiers_enabled", False):
            # Mem-7 (#1848): tier hint surfaced only when the flag is on.
            tier_hint = (
                "\n## Tier awareness (memory-tier-architecture epic, Mem-7 #1848)\n"
                "Entries in the SQLite knowledge table carry a `tier` column "
                "with values `preference`, `decision`, or `context`. The bridge "
                "has already applied within-tier dedup and threshold-based "
                "promotion/demotion deterministically BEFORE this consolidation "
                "pass (Python-side, by `DreamAgent._run_tier_ops`).\n\n"
                "When consolidating file-based memory in the directory below, "
                "preserve any tier markers you find in YAML frontmatter or "
                "content (e.g. `tier: preference`). Do NOT merge entries across "
                "different tiers — they carry different semantics and "
                "lifecycles. Merge within tier only.\n"
            )
        else:
            tier_hint = ""

        return f"""# Dream: Memory Consolidation

You are running a deep memory consolidation pass. Your task is to review,
organise, and prune the memory directory using only read-safe bash tools.

## Allowed bash operations
{DREAM_ALLOWED_BASH}

Do NOT use any other bash commands. Do NOT write outside {self._memory_dir}.

## Memory directory
{self._memory_dir}

## Daily logs directory
{logs_dir}
{tier_hint}---

## Phase 1: Orient
Survey the memory directory. List all files, check sizes and modification
times. Count total entries and identify the most recently modified files.

## Phase 2: Gather
Collect entries that are candidates for consolidation:
- Near-duplicate facts (same topic, slightly different wording)
- Contradictory statements about the same entity
- Outdated facts superseded by newer entries
- Low-salience entries with no recent access

## Phase 3: Consolidate
For each candidate group:
- Merge near-duplicates into a single authoritative entry
- Resolve contradictions by keeping the most recent / highest-confidence fact
- Update stale facts with current values where known

## Phase 4: Prune
Remove entries confirmed as:
- Superseded by a merged entry
- Contradicted and lower-confidence
- Salience below threshold with no access in 30+ days

---

Sessions reviewed: {session_count}
{extra}

When complete, return a JSON summary (no prose before or after):
{{"summary": "...", "files_touched": [...], "entries_pruned": N, "contradictions_resolved": N, "merges_performed": N}}
"""

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self, session_ids: list[str]) -> DreamResult:
        """Execute the dream consolidation pass.

        Spawns a restricted ClaudeRunner with DREAM_DISALLOWED_TOOLS merged
        into the config's security_disallowed_tools list.

        Args:
            session_ids: IDs of sessions to include in the consolidation pass.

        Returns:
            DreamResult with stats. On error, success=False and error is set.
        """
        self._ensure_memory_dir()

        # Mem-7 (#1848) — Python-side tier-ops phase. Runs BEFORE the LLM
        # phase so the LLM phase sees the post-promote/demote state and the
        # operator-visible per-tier counts in the returned DreamResult
        # match what the LLM was reasoning about. No-op when the flag is
        # off or no database is wired.
        try:
            (
                tier_promotions,
                tier_demotions,
                tier_dedups,
                per_tier_counts,
            ) = await self._run_tier_ops()
        except Exception as exc:
            # Tier-ops failure must NOT break the LLM-side consolidation;
            # log loud, zero out the tier counters, and continue.
            log.warning(
                "DreamAgent: tier-ops phase raised %s; continuing with LLM phase",
                exc,
            )
            tier_promotions = 0
            tier_demotions = 0
            tier_dedups = 0
            per_tier_counts = {}

        # Build a restricted config: merge dream disallowed tools with any
        # existing config-level disallowed tools. BridgeConfig is frozen, so
        # use dataclasses.replace() to produce an immutable copy.
        existing = list(self._config.security_disallowed_tools)
        merged = list(dict.fromkeys(existing + DREAM_DISALLOWED_TOOLS))  # dedup, preserve order
        restricted_config = dataclasses.replace(
            self._config,
            security_disallowed_tools=tuple(merged),
        )

        prompt = self._build_prompt(session_ids)
        runner = ClaudeRunner(restricted_config)

        log.info(
            "DreamAgent: starting consolidation pass, sessions=%d, disallowed_tools=%d",
            len(session_ids),
            len(merged),
        )

        try:
            result = await runner.invoke(
                message=prompt,
                model="claude-haiku-4-5-20251001",
            )
        except Exception as exc:
            log.error("DreamAgent: runner raised exception: %s", exc)
            # Determinism Spectrum (Sprint #1115): judged-LLM, Tier 3.
            increment_module_counter(
                "dream_agent.run",
                tier=3,
                escalation=True,
            )
            return DreamResult(
                success=False,
                summary="",
                files_touched=[],
                entries_pruned=0,
                contradictions_resolved=0,
                merges_performed=0,
                error=str(exc),
                tier_promotions=tier_promotions,
                tier_demotions=tier_demotions,
                tier_dedups=tier_dedups,
                per_tier_counts=per_tier_counts,
            )

        # Determinism Spectrum (Sprint #1115): judged-LLM, Tier 3 — record
        # invocation + cost on every non-exception path; ``is_error`` flips
        # the escalation bit so operator-visible failures show up in the
        # /determinism digest.
        increment_module_counter(
            "dream_agent.run",
            tier=3,
            cost_usd=float(getattr(result, "cost_usd", 0.0) or 0.0),
            escalation=bool(getattr(result, "is_error", False)),
        )

        # Handle runner-level errors
        if result.is_error:
            error_msg = result.error_type or "unknown_error"
            log.warning("DreamAgent: ClaudeRunner returned error: %s", error_msg)
            return DreamResult(
                success=False,
                summary="",
                files_touched=[],
                entries_pruned=0,
                contradictions_resolved=0,
                merges_performed=0,
                error=error_msg,
                tier_promotions=tier_promotions,
                tier_demotions=tier_demotions,
                tier_dedups=tier_dedups,
                per_tier_counts=per_tier_counts,
            )

        # Parse JSON response
        text = result.response_text or ""
        try:
            data = json.loads(text)
            dream_result = DreamResult(
                success=True,
                summary=data.get("summary", ""),
                files_touched=data.get("files_touched", []),
                entries_pruned=int(data.get("entries_pruned", 0)),
                contradictions_resolved=int(data.get("contradictions_resolved", 0)),
                merges_performed=int(data.get("merges_performed", 0)),
                tier_promotions=tier_promotions,
                tier_demotions=tier_demotions,
                tier_dedups=tier_dedups,
                per_tier_counts=per_tier_counts,
            )
            log.info(
                "DreamAgent: done — pruned=%d, resolved=%d, merged=%d, "
                "tier_promotions=%d, tier_demotions=%d, tier_dedups=%d",
                dream_result.entries_pruned,
                dream_result.contradictions_resolved,
                dream_result.merges_performed,
                dream_result.tier_promotions,
                dream_result.tier_demotions,
                dream_result.tier_dedups,
            )
            return dream_result
        except (json.JSONDecodeError, AttributeError, ValueError):
            # Plain-text fallback: return truncated summary, no structured stats
            log.warning(
                "DreamAgent: response is not JSON, using plain-text summary (len=%d)", len(text)
            )
            return DreamResult(
                success=True,
                summary=text[:500],
                files_touched=[],
                entries_pruned=0,
                contradictions_resolved=0,
                merges_performed=0,
                tier_promotions=tier_promotions,
                tier_demotions=tier_demotions,
                tier_dedups=tier_dedups,
                per_tier_counts=per_tier_counts,
            )
