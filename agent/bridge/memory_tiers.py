"""Memory-tier schema module — `MemoryTier` enum + `TierPolicy` dataclass.

This is the SCHEMA module for the Memory-Tier Architecture epic (Sprint Mem-1,
issue #1842). It defines the in-memory shape of tiers and their policies but
deliberately does NOT wire them into any call site — that lands in Mem-3,
which flips the `memory_tiers_enabled` flag (default-off here) and routes the
capture-side classifiers (`classify_intent`, `score_importance`) through this
module.

Three tiers ship at Mem-1 — `PREFERENCE | DECISION | CONTEXT` — per operator
decision Q1. The enum value-space deliberately reserves room for a future
`TRANSIENT` tier (no `@unique` decorator) so adding a fourth tier later is a
non-breaking change.

Defaults match the Stage-1 epic acceptance criterion:
- PREFERENCE: no TTL, written to sqlite + second_brain + vector, retrieval weight 1.0
- DECISION:   30-day TTL, written to sqlite + vector, retrieval weight 0.7
- CONTEXT:    1-day TTL, written to sqlite only, retrieval weight 0.4

When `config.memory_tiers_policies` is empty (the default), `load_tier_policies`
returns the three defaults above. TOML overrides land at
`[memory_tiers.policies.<tier>]` and fall back to defaults per-field (missing
keys do not silently drop the tier).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bridge.config import BridgeConfig


class MemoryTier(Enum):
    """Memory tier identity.

    Three members at ship (PREFERENCE, DECISION, CONTEXT) per operator
    decision Q1. No `@unique` decorator — the enum value-space reserves room
    for a future `TRANSIENT` tier without breaking existing serialized rows.
    """

    PREFERENCE = "preference"
    DECISION = "decision"
    CONTEXT = "context"

    @classmethod
    def from_str(cls, value: str) -> "MemoryTier":
        """Case-insensitive string → MemoryTier.

        Accepts `"preference"`, `"PREFERENCE"`, `"Preference"` — all map to
        `MemoryTier.PREFERENCE`. Raises `ValueError` on unknown values.
        """
        if not isinstance(value, str):
            raise ValueError(
                f"MemoryTier.from_str requires a string, got {type(value).__name__}"
            )
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        valid = ", ".join(m.value for m in cls)
        raise ValueError(f"Unknown memory tier {value!r}; valid: {valid}")


@dataclass(frozen=True)
class TierPolicy:
    """Per-tier policy: TTL, destinations, retrieval weight, promotion/demotion thresholds.

    Frozen dataclass — immutable post-construction. Validation runs in
    `__post_init__`; constructing an instance with invalid arguments raises
    `ValueError`.

    Mem-7 (#1848) adds `demotion_inactivity_seconds` — the inactivity window
    (in seconds, measured via `knowledge.accessed_at`) after which an entry
    is moved one tier down. `None` means the tier never demotes (top tier or
    bottom tier). `promotion_access_threshold` was added at Mem-1; together
    they drive the deterministic tier-ops phase in `DreamAgent._run_tier_ops`.
    """

    tier: MemoryTier
    ttl_seconds: Optional[int]
    destinations: tuple[str, ...]
    retrieval_weight: float
    promotion_access_threshold: int
    demotion_inactivity_seconds: Optional[int] = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.retrieval_weight <= 1.0:
            raise ValueError(
                f"retrieval_weight must be in [0.0, 1.0]; got {self.retrieval_weight}"
            )
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError(
                f"ttl_seconds must be None or > 0; got {self.ttl_seconds}"
            )
        if self.promotion_access_threshold < 0:
            raise ValueError(
                f"promotion_access_threshold must be >= 0; got {self.promotion_access_threshold}"
            )
        if (
            self.demotion_inactivity_seconds is not None
            and self.demotion_inactivity_seconds <= 0
        ):
            raise ValueError(
                "demotion_inactivity_seconds must be None or > 0; got "
                f"{self.demotion_inactivity_seconds}"
            )


_DEFAULT_POLICIES: dict[MemoryTier, TierPolicy] = {
    MemoryTier.PREFERENCE: TierPolicy(
        tier=MemoryTier.PREFERENCE,
        ttl_seconds=None,
        destinations=("sqlite", "second_brain", "vector"),
        retrieval_weight=1.0,
        promotion_access_threshold=0,  # top tier — never promotes
        demotion_inactivity_seconds=None,  # curated content — never demotes
    ),
    MemoryTier.DECISION: TierPolicy(
        tier=MemoryTier.DECISION,
        ttl_seconds=2_592_000,  # 30 days
        destinations=("sqlite", "vector"),
        retrieval_weight=0.7,
        # Mem-7 operator decision: promote DECISION → PREFERENCE after 20
        # lifetime accesses (Mem-1 shipped this at 3; bumped here per Q3
        # for the consolidation phase).
        promotion_access_threshold=20,
        demotion_inactivity_seconds=2_592_000,  # 30 days — matches TTL
    ),
    MemoryTier.CONTEXT: TierPolicy(
        tier=MemoryTier.CONTEXT,
        ttl_seconds=86_400,  # 24 hours
        destinations=("sqlite",),
        retrieval_weight=0.4,
        promotion_access_threshold=5,  # CONTEXT → DECISION at 5 lifetime accesses
        demotion_inactivity_seconds=None,  # bottom tier — no demote target
    ),
}


def _build_policy_from_overrides(
    tier: MemoryTier, default: TierPolicy, overrides: dict
) -> TierPolicy:
    """Merge per-tier TOML overrides on top of the default policy."""
    destinations = overrides.get("destinations", default.destinations)
    if isinstance(destinations, list):
        destinations = tuple(destinations)
    elif not isinstance(destinations, tuple):
        # Reject non-sequence types — better to fail loud than coerce.
        raise ValueError(
            f"destinations for tier {tier.value!r} must be a list/tuple; "
            f"got {type(destinations).__name__}"
        )

    return TierPolicy(
        tier=tier,
        ttl_seconds=overrides.get("ttl_seconds", default.ttl_seconds),
        destinations=destinations,
        retrieval_weight=overrides.get("retrieval_weight", default.retrieval_weight),
        promotion_access_threshold=overrides.get(
            "promotion_access_threshold", default.promotion_access_threshold
        ),
        demotion_inactivity_seconds=overrides.get(
            "demotion_inactivity_seconds", default.demotion_inactivity_seconds
        ),
    )


def load_tier_policies(config: "BridgeConfig") -> dict[MemoryTier, TierPolicy]:
    """Load tier policies from `BridgeConfig`, falling back to module defaults.

    Reads `config.memory_tiers_policies` (set by the TOML loader for the
    `[memory_tiers.policies.<tier>]` blocks). When the attribute is missing or
    empty, returns the three default policies in `_DEFAULT_POLICIES`. When
    only some tiers have overrides, the rest fall back to defaults (not
    silently dropped).
    """
    overrides_by_tier_name = getattr(config, "memory_tiers_policies", None) or {}

    policies: dict[MemoryTier, TierPolicy] = {}
    for tier, default_policy in _DEFAULT_POLICIES.items():
        tier_overrides = overrides_by_tier_name.get(tier.value)
        if tier_overrides:
            policies[tier] = _build_policy_from_overrides(
                tier, default_policy, tier_overrides
            )
        else:
            policies[tier] = default_policy
    return policies
