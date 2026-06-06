"""Tests for `bridge.memory_tiers` — Sprint Mem-1 (issue #1842).

Covers:
- Enum identity (3 members at ship; from_str case-insensitive; unknown raises)
- TierPolicy frozen-ness (mutation raises) and validation
  (retrieval_weight, ttl_seconds, promotion_access_threshold)
- load_tier_policies defaults (3 tiers when config empty)
- load_tier_policies round-trip (TOML override + per-tier fallback)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from bridge.config import BridgeConfig
from bridge.memory_tiers import (
    MemoryTier,
    TierPolicy,
    load_tier_policies,
)


# --- MemoryTier enum ---


def test_memory_tier_has_exactly_three_members():
    """Ship 3 tiers per operator decision Q1; expanding to 4 requires an amendment."""
    members = list(MemoryTier)
    assert len(members) == 3
    assert set(members) == {
        MemoryTier.PREFERENCE,
        MemoryTier.DECISION,
        MemoryTier.CONTEXT,
    }


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("preference", MemoryTier.PREFERENCE),
        ("PREFERENCE", MemoryTier.PREFERENCE),
        ("Preference", MemoryTier.PREFERENCE),
        ("  decision  ", MemoryTier.DECISION),
        ("CONTEXT", MemoryTier.CONTEXT),
    ],
)
def test_memory_tier_from_str_case_insensitive(raw: str, expected: MemoryTier):
    assert MemoryTier.from_str(raw) is expected


def test_memory_tier_from_str_rejects_unknown_tier():
    """Unknown tier names raise ValueError (no silent fallback)."""
    with pytest.raises(ValueError) as excinfo:
        MemoryTier.from_str("transient")
    msg = str(excinfo.value)
    assert "transient" in msg
    # Error message names valid tiers so the operator can self-correct.
    assert "preference" in msg
    assert "decision" in msg
    assert "context" in msg


def test_memory_tier_from_str_rejects_non_string():
    with pytest.raises(ValueError):
        MemoryTier.from_str(123)  # type: ignore[arg-type]


# --- TierPolicy dataclass ---


def test_tier_policy_is_frozen():
    """Mutation raises FrozenInstanceError (immutability discipline)."""
    policy = TierPolicy(
        tier=MemoryTier.PREFERENCE,
        ttl_seconds=None,
        destinations=("sqlite",),
        retrieval_weight=1.0,
        promotion_access_threshold=0,
    )
    # dataclasses(frozen=True) raises FrozenInstanceError on attribute set.
    with pytest.raises((FrozenInstanceError, AttributeError)):
        policy.retrieval_weight = 0.5  # type: ignore[misc]


def test_tier_policy_rejects_out_of_range_retrieval_weight():
    with pytest.raises(ValueError, match="retrieval_weight"):
        TierPolicy(
            tier=MemoryTier.PREFERENCE,
            ttl_seconds=None,
            destinations=("sqlite",),
            retrieval_weight=1.5,
            promotion_access_threshold=0,
        )
    with pytest.raises(ValueError, match="retrieval_weight"):
        TierPolicy(
            tier=MemoryTier.PREFERENCE,
            ttl_seconds=None,
            destinations=("sqlite",),
            retrieval_weight=-0.01,
            promotion_access_threshold=0,
        )


def test_tier_policy_accepts_retrieval_weight_at_bounds():
    """Both 0.0 and 1.0 are valid."""
    for w in (0.0, 1.0):
        p = TierPolicy(
            tier=MemoryTier.PREFERENCE,
            ttl_seconds=None,
            destinations=("sqlite",),
            retrieval_weight=w,
            promotion_access_threshold=0,
        )
        assert p.retrieval_weight == w


def test_tier_policy_rejects_zero_or_negative_ttl():
    with pytest.raises(ValueError, match="ttl_seconds"):
        TierPolicy(
            tier=MemoryTier.PREFERENCE,
            ttl_seconds=0,
            destinations=("sqlite",),
            retrieval_weight=1.0,
            promotion_access_threshold=0,
        )
    with pytest.raises(ValueError, match="ttl_seconds"):
        TierPolicy(
            tier=MemoryTier.PREFERENCE,
            ttl_seconds=-1,
            destinations=("sqlite",),
            retrieval_weight=1.0,
            promotion_access_threshold=0,
        )


def test_tier_policy_accepts_none_ttl():
    """None TTL means no expiry — the canonical PREFERENCE default."""
    p = TierPolicy(
        tier=MemoryTier.PREFERENCE,
        ttl_seconds=None,
        destinations=("sqlite",),
        retrieval_weight=1.0,
        promotion_access_threshold=0,
    )
    assert p.ttl_seconds is None


def test_tier_policy_rejects_negative_promotion_threshold():
    with pytest.raises(ValueError, match="promotion_access_threshold"):
        TierPolicy(
            tier=MemoryTier.PREFERENCE,
            ttl_seconds=None,
            destinations=("sqlite",),
            retrieval_weight=1.0,
            promotion_access_threshold=-1,
        )


# --- load_tier_policies ---


def test_load_tier_policies_returns_three_defaults_when_config_empty():
    """Empty config → three default policies per the Stage-1 epic AC-1."""
    config = BridgeConfig()
    policies = load_tier_policies(config)

    assert set(policies.keys()) == {
        MemoryTier.PREFERENCE,
        MemoryTier.DECISION,
        MemoryTier.CONTEXT,
    }

    pref = policies[MemoryTier.PREFERENCE]
    assert pref.tier is MemoryTier.PREFERENCE
    assert pref.ttl_seconds is None
    assert pref.destinations == ("sqlite", "second_brain", "vector")
    assert pref.retrieval_weight == 1.0
    assert pref.promotion_access_threshold == 0

    dec = policies[MemoryTier.DECISION]
    assert dec.tier is MemoryTier.DECISION
    assert dec.ttl_seconds == 2_592_000  # 30 days
    assert dec.destinations == ("sqlite", "vector")
    assert dec.retrieval_weight == 0.7
    # Mem-7 (#1848) bumped from 3 → 20 per operator decision Q3.
    assert dec.promotion_access_threshold == 20
    assert dec.demotion_inactivity_seconds == 2_592_000

    ctx = policies[MemoryTier.CONTEXT]
    assert ctx.tier is MemoryTier.CONTEXT
    assert ctx.ttl_seconds == 86_400  # 1 day
    assert ctx.destinations == ("sqlite",)
    assert ctx.retrieval_weight == 0.4
    assert ctx.promotion_access_threshold == 5
    assert ctx.demotion_inactivity_seconds is None


def test_load_tier_policies_round_trip_with_partial_override():
    """TOML override on one tier → that tier reflects override; others fall back."""
    config = BridgeConfig(
        memory_tiers_policies={
            "preference": {
                "destinations": ["sqlite"],
                "retrieval_weight": 0.5,
                "promotion_access_threshold": 2,
                # ttl_seconds omitted = None
            }
        }
    )
    policies = load_tier_policies(config)

    # PREFERENCE picks up the override.
    pref = policies[MemoryTier.PREFERENCE]
    assert pref.tier is MemoryTier.PREFERENCE
    assert pref.ttl_seconds is None
    assert pref.destinations == ("sqlite",)  # list → tuple
    assert pref.retrieval_weight == 0.5
    assert pref.promotion_access_threshold == 2

    # DECISION and CONTEXT fall back to defaults — not silently dropped.
    dec = policies[MemoryTier.DECISION]
    assert dec.ttl_seconds == 2_592_000
    assert dec.destinations == ("sqlite", "vector")
    assert dec.retrieval_weight == 0.7
    # Mem-7 (#1848) bumped from 3 → 20 per operator decision Q3.
    assert dec.promotion_access_threshold == 20

    ctx = policies[MemoryTier.CONTEXT]
    assert ctx.ttl_seconds == 86_400
    assert ctx.destinations == ("sqlite",)
    assert ctx.retrieval_weight == 0.4
    assert ctx.promotion_access_threshold == 5


def test_load_tier_policies_full_override():
    """All three tiers overridden — none fall back to defaults."""
    config = BridgeConfig(
        memory_tiers_policies={
            "preference": {
                "destinations": ["sqlite", "vector"],
                "retrieval_weight": 0.9,
                "promotion_access_threshold": 1,
                "ttl_seconds": 7200,
            },
            "decision": {
                "destinations": ["sqlite"],
                "retrieval_weight": 0.5,
                "promotion_access_threshold": 5,
                "ttl_seconds": 3600,
            },
            "context": {
                "destinations": ["sqlite"],
                "retrieval_weight": 0.1,
                "promotion_access_threshold": 10,
                "ttl_seconds": 600,
            },
        }
    )
    policies = load_tier_policies(config)

    assert policies[MemoryTier.PREFERENCE].ttl_seconds == 7200
    assert policies[MemoryTier.PREFERENCE].retrieval_weight == 0.9
    assert policies[MemoryTier.DECISION].ttl_seconds == 3600
    assert policies[MemoryTier.CONTEXT].ttl_seconds == 600
    assert policies[MemoryTier.CONTEXT].promotion_access_threshold == 10


def test_load_tier_policies_validates_overrides():
    """Invalid override values surface as ValueError at load time, not at use time."""
    config = BridgeConfig(
        memory_tiers_policies={
            "preference": {
                "destinations": ["sqlite"],
                "retrieval_weight": 1.5,  # invalid
                "promotion_access_threshold": 0,
            }
        }
    )
    with pytest.raises(ValueError, match="retrieval_weight"):
        load_tier_policies(config)


def test_load_tier_policies_rejects_non_sequence_destinations():
    config = BridgeConfig(
        memory_tiers_policies={
            "preference": {
                "destinations": "sqlite",  # string, not list/tuple — would silently iterate as chars
                "retrieval_weight": 1.0,
                "promotion_access_threshold": 0,
            }
        }
    )
    with pytest.raises(ValueError, match="destinations"):
        load_tier_policies(config)
