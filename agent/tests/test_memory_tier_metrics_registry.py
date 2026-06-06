"""Tests for Mem-9 (#1850): memory-tier metrics registry presence.

Sprint Mem-9 ships the registry YAML + test scaffolding only. Emit-call
wiring is deferred to Mem-4 / Mem-5 / Mem-7 implementers; this test asserts
the five `memory.tier.*` metric names are present in the registry so the
emit sites have a name to register against when they land.

When Mem-4/5/7 ship the emit sites, extend this file (or add sibling tests)
with the `assert_called_with(...)` checks against `MetricsCollector.increment`
that the original AC-9 spec describes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.registry_loader import RegistryLoader


REGISTRY_ROOT = Path(__file__).parent.parent / "config" / "registry"

EXPECTED_MEMORY_TIER_METRICS = frozenset(
    {
        "memory.tier.writes",
        "memory.tier.retrievals",
        "memory.tier.evictions",
        "memory.tier.promotions",
        "memory.tier.demotions",
    }
)


@pytest.fixture(scope="module")
def loaded_index():
    """Load the live registry once; reused across module tests."""
    if not REGISTRY_ROOT.exists():
        pytest.skip(f"Registry root not found at {REGISTRY_ROOT}")
    index = RegistryLoader().load_all(REGISTRY_ROOT)
    # Surface registry errors loudly — silent drift is the failure mode this
    # test exists to catch.
    assert index.errors == [], f"Registry validation errors: {index.errors}"
    return index


class TestMemoryTierMetricsRegistered:
    """Mem-9 (#1850): five memory.tier.* metrics must be present in the registry."""

    def test_all_five_memory_tier_metrics_present(self, loaded_index) -> None:
        registered_names = {m.metric_name for m in loaded_index.metrics}
        missing = EXPECTED_MEMORY_TIER_METRICS - registered_names
        assert not missing, (
            f"Missing memory.tier.* metrics in registry: {sorted(missing)}. "
            f"Add to agent/config/registry/metrics/memory-tiers.yaml."
        )

    @pytest.mark.parametrize("metric_name", sorted(EXPECTED_MEMORY_TIER_METRICS))
    def test_each_metric_resolvable_by_find_api(
        self, loaded_index, metric_name: str
    ) -> None:
        entry = loaded_index.find_metric_by_name(metric_name)
        assert entry is not None, (
            f"{metric_name!r} not findable via RegistryIndex.find_metric_by_name. "
            f"This is the same call path the registry-completeness CI gate uses."
        )
        assert entry.category.value == "Memory", (
            f"{metric_name!r} category is {entry.category.value!r}, expected 'Memory'."
        )

    def test_label_dimensions_documented_in_schema_ref(self, loaded_index) -> None:
        """Per Mem-9 spec the labels are part of the contract — verify schema_ref documents them."""
        for metric_name in EXPECTED_MEMORY_TIER_METRICS:
            entry = loaded_index.find_metric_by_name(metric_name)
            assert entry is not None
            if metric_name in {
                "memory.tier.writes",
                "memory.tier.retrievals",
                "memory.tier.evictions",
            }:
                assert "tier:" in entry.schema_ref, (
                    f"{metric_name!r} schema_ref must document the `tier` label: "
                    f"got {entry.schema_ref!r}"
                )
            else:  # promotions / demotions
                assert "from:" in entry.schema_ref and "to:" in entry.schema_ref, (
                    f"{metric_name!r} schema_ref must document `from` and `to` labels: "
                    f"got {entry.schema_ref!r}"
                )
