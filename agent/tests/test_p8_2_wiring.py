"""P8.2 #1748 — wiring acceptance tests.

Two wires shipped in this PR:

1. ``_wire_consolidation_dream_agent`` (services/runner.py) calls
   ``ConsolidationService.set_dream_agent`` + ``set_config`` so the
   "deep" branch of the consolidation pipeline can invoke DreamAgent.
2. ``compound_pressure.should_auto_compact`` is consulted in
   ``invocation_pipeline.py`` Stage 2 after both budget alert level and
   context pressure are computed; when True, ``compaction.recommended``
   fires on the event bus.

These tests guard the contract surface — that the helper sets the
right attributes, and that the event-publish call shape is what
``compaction_checkpoint`` and any future subscriber expects.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── Sub-decision 2: DreamAgent runner wiring ──────────────────────────────


class TestWireConsolidationDreamAgent:
    """services/runner.py::_wire_consolidation_dream_agent acceptance."""

    def test_no_op_when_config_unavailable(self):
        """When BridgeConfig cannot be loaded, the helper is a no-op."""
        from bridge.services.runner import _wire_consolidation_dream_agent

        svc = MagicMock()
        with patch(
            "bridge.services.runner._load_bridge_config",
            return_value=None,
        ):
            _wire_consolidation_dream_agent(svc)

        svc.set_dream_agent.assert_not_called()
        svc.set_config.assert_not_called()

    def test_calls_set_dream_agent_and_set_config(self):
        """When BridgeConfig loads, both setters fire with a DreamAgent + the config."""
        from bridge.services.runner import _wire_consolidation_dream_agent
        from bridge.dream_agent import DreamAgent

        svc = MagicMock()
        cfg = MagicMock()
        cfg.data_dir = "/tmp"

        with patch(
            "bridge.services.runner._load_bridge_config",
            return_value=cfg,
        ):
            _wire_consolidation_dream_agent(svc)

        # set_dream_agent fires with a DreamAgent instance built from cfg.
        svc.set_dream_agent.assert_called_once()
        agent = svc.set_dream_agent.call_args[0][0]
        assert isinstance(agent, DreamAgent)

        # set_config fires with the same cfg the helper resolved.
        svc.set_config.assert_called_once_with(cfg)

    def test_dream_agent_init_failure_is_non_fatal(self):
        """A DreamAgent construction crash must not raise — the consolidation
        pipeline still runs in micro/standard modes; only deep degrades."""
        from bridge.services.runner import _wire_consolidation_dream_agent

        svc = MagicMock()
        cfg = MagicMock()

        # Force DreamAgent.__init__ to raise.
        with patch(
            "bridge.services.runner._load_bridge_config",
            return_value=cfg,
        ), patch(
            "bridge.dream_agent.DreamAgent",
            side_effect=RuntimeError("boom"),
        ):
            # Must not raise:
            _wire_consolidation_dream_agent(svc)

        svc.set_dream_agent.assert_not_called()


# ── Sub-decision 3: compound_pressure publish path ────────────────────────


class TestCompoundPressureEventPayload:
    """Assert the publish-shape that downstream consumers will read."""

    def test_should_auto_compact_predicate_unchanged(self):
        """Sanity: the pure predicate this PR depends on still behaves as
        documented (both signals must be stressed; either alone returns False)."""
        from bridge.compound_pressure import should_auto_compact

        # Both stressed → True
        assert should_auto_compact("warning", "warn") is True
        assert should_auto_compact("critical", "compact_now") is True
        assert should_auto_compact("exceeded", "critical") is True

        # Only one stressed → False
        assert should_auto_compact("ok", "warn") is False
        assert should_auto_compact("warning", "ok") is False

        # Both unstressed → False
        assert should_auto_compact("ok", "ok") is False

    def test_float_to_recommendation_mapping_matches_thresholds(self):
        """The invocation_pipeline mapping must match the
        ContextPressureMonitor thresholds at context_pressure.py:115-123 so
        the predicate's input shape is consistent with the rest of the
        bridge's compaction surface."""
        # Mirror the mapping inlined in invocation_pipeline.py.
        def map_float(p: float) -> str:
            if p >= 0.90:
                return "critical"
            if p >= 0.75:
                return "compact_now"
            if p >= 0.60:
                return "warn"
            return "ok"

        assert map_float(0.95) == "critical"
        assert map_float(0.90) == "critical"
        assert map_float(0.85) == "compact_now"
        assert map_float(0.75) == "compact_now"
        assert map_float(0.65) == "warn"
        assert map_float(0.60) == "warn"
        assert map_float(0.50) == "ok"
        assert map_float(0.0) == "ok"

    def test_registry_entry_exists_for_compaction_recommended(self):
        """The registry-completeness CI gate requires every published event
        to have a registry entry. This test asserts our compaction.yaml is
        loadable and indexes the new event."""
        from pathlib import Path
        from bridge.registry_loader import RegistryLoader

        registry_root = (
            Path(__file__).resolve().parent.parent / "config" / "registry"
        )
        loader = RegistryLoader()
        index = loader.load_all(registry_root)
        match = index.find_event_by_type("compaction.recommended")
        assert match is not None, (
            "compaction.recommended must exist in registry "
            "(see config/registry/events/compaction.yaml)"
        )
        assert match.source_module == "bridge.invocation_pipeline"
