"""Tests for Sprint Mem-6 — tier-aware context-window assembly (#1847).

Memory-Tier Architecture epic, Phase B (retrieval). Verifies:

- ``assemble_context_window`` legacy mode is byte-identical to the
  pre-Mem-6 ``select_context_window`` (and ``select_context_window`` is
  still callable as an alias).
- ``assemble_context_window`` tiered mode merges per-tier ranked lists
  with per-tier weight multipliers.
- Token budget (``max_chars``) is honored cumulatively across both modes.
- Empty inputs return ``[]``.
- Tier weights default to 1.0 per tier when omitted.
- Branch 0 in ``KnowledgeMixin.search_knowledge`` is invisible at flag-off
  — search results are byte-identical to pre-Mem-6.
"""

from __future__ import annotations

import dataclasses
import time

import pytest

from bridge.memory_enhancement import (
    DEFAULT_CONTEXT_WINDOW,
    ScoredEntry,
    assemble_context_window,
    compute_importance,
    select_context_window,
)
from bridge.memory_tiers import MemoryTier


def _make_entry(
    key: str = "test-key",
    value: str = "test value",
    category: str = "general",
    intent: str = "fact",
    salience: float = 0.5,
    access_count: int = 0,
    last_accessed: float = 0.0,
    created_at: float | None = None,
) -> ScoredEntry:
    """Build a ScoredEntry with sensible defaults for tests."""
    return ScoredEntry(
        key=key,
        value=value,
        category=category,
        intent=intent,
        salience=salience,
        access_count=access_count,
        last_accessed=last_accessed,
        created_at=created_at if created_at is not None else time.time(),
    )


# ── Legacy-mode byte-identical ──────────────────────────────────────────


class TestLegacyModeAlias:
    """The rename keeps `select_context_window` callable as an alias."""

    def test_alias_is_same_callable(self):
        # `select_context_window = assemble_context_window` literal assignment.
        assert select_context_window is assemble_context_window

    def test_alias_returns_same_result_for_same_input(self):
        # Build two identical entry lists — one for each invocation, since
        # the legacy path mutates `entry.importance` in place.
        entries_a = [
            _make_entry(key=f"k{i}", salience=i * 0.1) for i in range(8)
        ]
        entries_b = [
            _make_entry(key=f"k{i}", salience=i * 0.1) for i in range(8)
        ]
        out_a = assemble_context_window(entries_a, max_entries=4)
        out_b = select_context_window(entries_b, max_entries=4)
        assert [e.key for e in out_a] == [e.key for e in out_b]


class TestLegacyMode:
    """Re-validate pre-Mem-6 semantics survived the rename + signature change."""

    def test_returns_top_n_by_importance(self):
        entries = [
            _make_entry(key=f"k{i}", salience=i * 0.1)
            for i in range(10)
        ]
        out = assemble_context_window(entries, max_entries=3)
        assert len(out) == 3
        # Highest salience should land first.
        assert out[0].key == "k9"

    def test_respects_max_entries(self):
        entries = [_make_entry(key=f"k{i}") for i in range(50)]
        out = assemble_context_window(
            entries, max_entries=DEFAULT_CONTEXT_WINDOW
        )
        assert len(out) <= DEFAULT_CONTEXT_WINDOW

    def test_respects_char_budget(self):
        entries = [
            _make_entry(key=f"k{i}", value="x" * 1000, salience=0.9)
            for i in range(20)
        ]
        out = assemble_context_window(entries, max_chars=5000)
        total = sum(len(e.key) + len(e.value) for e in out)
        assert total <= 5000

    def test_empty_entries_returns_empty(self):
        assert assemble_context_window([]) == []
        assert assemble_context_window(None) == []

    def test_intent_boost_lifts_matching_entry(self):
        decision = _make_entry(key="dec", intent="decision", salience=0.3)
        fact = _make_entry(key="fact", intent="fact", salience=0.5)
        out = assemble_context_window(
            [decision, fact], query_intent="decision", max_entries=1,
        )
        assert len(out) == 1
        assert out[0].key == "dec"


# ── Tiered mode (Mem-6 net-new) ─────────────────────────────────────────


class TestTieredMode:
    def _seed_tiers(self) -> dict[MemoryTier, list[ScoredEntry]]:
        """Construct a tier-results dict with importance pre-scored."""
        # Three entries per tier with distinct identifiers and pre-scored
        # importance so we can predict ranking deterministically.
        def make(key: str, importance: float) -> ScoredEntry:
            e = _make_entry(key=key, salience=0.5, value="x" * 100)
            e.importance = importance
            return e

        return {
            MemoryTier.PREFERENCE: [
                make("p1", 0.5), make("p2", 0.4), make("p3", 0.3),
            ],
            MemoryTier.DECISION: [
                make("d1", 0.5), make("d2", 0.4), make("d3", 0.3),
            ],
            MemoryTier.CONTEXT: [
                make("c1", 0.5), make("c2", 0.4), make("c3", 0.3),
            ],
        }

    def test_tier_weight_lifts_higher_weighted_tier(self):
        """Equal raw importance + higher tier weight → tier wins the ranking.

        At equal raw importance, a higher tier weight always wins. The
        ranking is `importance * tier_weight`, so we test at the boundary:
        preference 0.5 * 1.0 = 0.50 > decision 0.5 * 0.7 = 0.35.
        """
        tier_results = self._seed_tiers()
        weights = {
            MemoryTier.PREFERENCE: 1.0,
            MemoryTier.DECISION: 0.7,
            MemoryTier.CONTEXT: 0.4,
        }
        out = assemble_context_window(
            tier_results=tier_results, tier_weights=weights, max_entries=9,
        )
        # Top-1 must be a preference row (highest tier weight × max importance).
        assert out[0].key.startswith("p")
        # Among entries that have raw importance 0.5 (the tier's top row),
        # preference wins via weight.
        # p1 (0.5 * 1.0 = 0.50) > d1 (0.5 * 0.7 = 0.35) > c1 (0.5 * 0.4 = 0.20).
        weighted = {e.key: e.importance for e in out}
        assert weighted["p1"] > weighted["d1"] > weighted["c1"]

    def test_tier_weights_default_to_one(self):
        """When tier_weights is None, every tier weighted 1.0 → pure importance order."""
        tier_results = self._seed_tiers()
        out = assemble_context_window(
            tier_results=tier_results, max_entries=9,
        )
        # All importance=0.5 rows should outrank importance=0.4 ones, etc.
        # Top-3 should all have importance 0.5.
        top_three_keys = {e.key for e in out[:3]}
        assert top_three_keys == {"p1", "d1", "c1"}

    def test_empty_tier_results_returns_empty(self):
        tier_results = {t: [] for t in MemoryTier}
        out = assemble_context_window(tier_results=tier_results)
        assert out == []

    def test_token_budget_honored(self):
        """`max_chars` caps cumulative key+value length across tiers."""
        long_entry = _make_entry(key="long", value="x" * 200, salience=0.9)
        long_entry.importance = 0.9
        tier_results = {
            MemoryTier.PREFERENCE: [long_entry],
            MemoryTier.DECISION: [long_entry],
            MemoryTier.CONTEXT: [long_entry],
        }
        out = assemble_context_window(
            tier_results=tier_results, max_chars=210, max_entries=99,
        )
        # 200 + 4 (key) = 204 → one entry fits, the second would push to
        # 408 (over 210), so we stop.
        assert len(out) == 1
        total = sum(len(e.key) + len(e.value) for e in out)
        assert total <= 210

    def test_input_dict_not_mutated(self):
        """Immutability rule — tier-mode rebuilds ScoredEntry copies."""
        tier_results = self._seed_tiers()
        p1 = tier_results[MemoryTier.PREFERENCE][0]
        original_importance = p1.importance
        weights = {
            MemoryTier.PREFERENCE: 0.5,
            MemoryTier.DECISION: 0.5,
            MemoryTier.CONTEXT: 0.5,
        }
        assemble_context_window(
            tier_results=tier_results, tier_weights=weights, max_entries=9,
        )
        # Input's `p1.importance` should be unchanged — copies, not mutation.
        assert p1.importance == original_importance


# ── Mem-3 regression — capture-side wiring still passes ─────────────────


class TestMem3ImportPath:
    """Mem-6 doesn't break the Mem-3 capture-side import path."""

    def test_compute_importance_still_importable_from_enhancement(self):
        from bridge.memory_enhancement import compute_importance as ci
        assert ci is compute_importance


# ── search_knowledge flag-off byte-identical ────────────────────────────


@pytest.fixture
async def memory_no_tiers(migrated_db, sample_config):
    """A Memory instance with `memory_tiers_enabled = False` (default)."""
    from bridge.memory import Memory
    return Memory(migrated_db, sample_config)


@pytest.fixture
async def memory_with_tiers(migrated_db, sample_config):
    """A Memory instance with `memory_tiers_enabled = True` but no hybrid_search wired."""
    from bridge.memory import Memory
    enabled = dataclasses.replace(sample_config, memory_tiers_enabled=True)
    return Memory(migrated_db, enabled)


class TestBranch0Gate:
    """Branch 0 fires only when all three conditions are met."""

    @pytest.mark.asyncio
    async def test_flag_off_skips_branch_0(self, memory_no_tiers):
        """With flag off, search_knowledge never touches `_tiered_search_branch`."""
        # Seed a row so FTS5 has something to find.
        await memory_no_tiers.store_knowledge(
            key="ctrl:1", value="discord oauth setup", category="reference",
        )
        # Sanity — flag is off, no hybrid_search wired, so Branch 0 is gated
        # out by the first clause regardless of hybrid_search state.
        assert memory_no_tiers._config.memory_tiers_enabled is False
        results = await memory_no_tiers.search_knowledge("discord oauth")
        # Falls through to FTS5 (Branch 3) — should find the row.
        assert any(r["key"] == "ctrl:1" for r in results)

    @pytest.mark.asyncio
    async def test_flag_on_without_hybrid_skips_branch_0(self, memory_with_tiers):
        """Flag-on but no hybrid_search wired → Branch 0 short-circuits, FTS5 wins."""
        await memory_with_tiers.store_knowledge(
            key="trt:1", value="discord oauth setup", category="reference",
        )
        # hybrid_search is None — Branch 0 gated out by the second clause.
        assert memory_with_tiers._hybrid_search is None
        results = await memory_with_tiers.search_knowledge("discord oauth")
        assert any(r["key"] == "trt:1" for r in results)
