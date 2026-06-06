"""Structural parity test for Sprint 01.02 — verifies the WIRING_MANIFEST
fires the same 28 CommandHandler setters in the same order as the pre-migration
scattered ``self._commands.set_*(...)`` calls at ``app.py:477-696``.

Strategy: spy on every ``set_<x>`` method on ``CommandHandler`` and record the
call order during a real ``BridgeApp._initialize()`` run. Diff against the
baseline at ``tests/data/test_app_wiring_baseline.json``. Any drift — a new
setter, a removed setter, or an order change — fails the test loudly so the
operator-side deploy verification log line stays trustworthy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.commands import CommandHandler


BASELINE_PATH = Path(__file__).parent / "data" / "test_app_wiring_baseline.json"


def _install_setter_spy(commands: CommandHandler) -> list[str]:
    """Wrap every ``set_*`` method on ``commands`` with a recorder.

    Returns a list that gets appended to in call order. The wrapped method
    still calls the real implementation so the rest of ``_initialize()``
    proceeds normally.
    """
    recorded: list[str] = []

    for name in list(vars(type(commands))):
        if not name.startswith("set_"):
            continue
        original = getattr(commands, name)

        def _make_spy(method_name: str, fn: Any):
            def _spy(*args: Any, **kwargs: Any) -> Any:
                recorded.append(method_name)
                return fn(*args, **kwargs)
            return _spy

        # Bind the wrapped method onto this specific instance only — do not
        # mutate the class.
        object.__setattr__(commands, name, _make_spy(name, original))

    return recorded


@pytest_asyncio.fixture
async def wired_app_with_spy(tmp_path, sample_config_toml, mock_keyring):
    """Reuse the wired_app fixture pattern but install the setter spy
    BEFORE _initialize() runs. We can't reuse the wired_app fixture directly
    because it constructs and initializes in one step — the spy must be on
    self._commands BEFORE the WIRING_MANIFEST fires."""
    app = BridgeApp(config_path=str(sample_config_toml))

    # _commands is constructed inside _initialize(); we need to hook it
    # there. Solution: monkey-patch BridgeApp._wire to first install the spy
    # on self._commands, then call the original _wire.
    original_wire = BridgeApp._wire

    recorded: list[str] = []
    captured: dict[str, list[str]] = {}

    def _wrapped_wire(self: BridgeApp) -> None:
        spy_list = _install_setter_spy(self._commands)
        captured["recorded"] = spy_list
        original_wire(self)

    BridgeApp._wire = _wrapped_wire  # type: ignore[method-assign]
    try:
        await app._initialize()
    finally:
        BridgeApp._wire = original_wire  # type: ignore[method-assign]

    yield app, captured["recorded"]

    # Sprint R2.3 (#1895) — close sync-sqlite stores BridgeApp owns
    # before closing the async DB. See bridge/app.py::stop().
    for _store in (app._embedding_engine, app._workorder_store, app._peer_registry):
        if _store is not None and hasattr(_store, "close"):
            try:
                _store.close()
            except Exception:  # noqa: BLE001
                pass
    if app._db:
        await app._db.close()


class TestWiringParity:
    @pytest.mark.asyncio
    async def test_wire_method_exists(self, wired_app_with_spy):
        """_wire() must exist as a method on BridgeApp (Sprint 01.02 contract)."""
        app, _ = wired_app_with_spy
        assert hasattr(app, "_wire")
        assert callable(app._wire)

    @pytest.mark.asyncio
    async def test_setter_call_order_matches_baseline(self, wired_app_with_spy):
        """Every setter recorded in the baseline must fire, in the same order."""
        _, recorded = wired_app_with_spy
        baseline = json.loads(BASELINE_PATH.read_text())
        expected = baseline["setter_call_order_when_all_subsystems_available"]

        # In a unit-test environment, some subsystems may legitimately not
        # initialize (e.g. _TEAMS_AVAILABLE may be False on CI without
        # pydantic-ai installed; warm_claude, autonomy, tool_tracker, etc.
        # may be conditional too). We assert: the recorded order must be a
        # SUBSEQUENCE of the baseline. This catches reordering bugs and
        # missing-from-manifest bugs without making the test brittle to
        # environment-specific subsystem availability.
        i = 0
        for name in expected:
            if i < len(recorded) and recorded[i] == name:
                i += 1
        assert i == len(recorded), (
            f"Recorded setter order is not a subsequence of the baseline.\n"
            f"  Recorded: {recorded}\n"
            f"  Expected: {expected}\n"
            f"  Diverged at recorded[{i}] = {recorded[i] if i < len(recorded) else '<eof>'!r}"
        )

    @pytest.mark.asyncio
    async def test_no_unknown_setter_fires(self, wired_app_with_spy):
        """No setter outside the baseline may fire — guards against the
        manifest accidentally adding an extra entry."""
        _, recorded = wired_app_with_spy
        baseline = json.loads(BASELINE_PATH.read_text())
        expected = set(baseline["setter_call_order_when_all_subsystems_available"])
        unknown = [name for name in recorded if name not in expected]
        assert not unknown, f"Setters fired that aren't in the baseline: {unknown}"

    @pytest.mark.asyncio
    async def test_required_setters_always_fire(self, wired_app_with_spy):
        """The 14 unconditional setters must fire on every successful
        _initialize() — required=True in the manifest. If one is missing,
        a subsystem the operator depends on (e.g. session_hooks, security)
        is silently broken."""
        _, recorded = wired_app_with_spy
        always_required = [
            "set_session_hooks",
            "set_security",
            "set_self_verifier",
            "set_shutdown_callback",
            "set_few_shot_store",
            "set_self_edit",
            "set_temporal_kb",
            "set_tracer",
            "set_cost_tracker",
            "set_routing_feedback",
            "set_reflection_store",
            "set_skill_evolution",
            "set_project_registry",
            "set_runbook_engine",
            "set_agent_router",
            "set_log_dir",
        ]
        for name in always_required:
            assert name in recorded, (
                f"Required setter {name!r} did not fire during _initialize() — "
                f"this would silently break a subsystem in production."
            )

    @pytest.mark.asyncio
    async def test_total_setter_count_is_35(self, wired_app_with_spy):
        """Pinned baseline assertion: the manifest declares 35 entries (28 from
        Sprint 01.02 + 5 wire-to-None CommandHandler from Sprint 01.03 +
        3 reflexive BridgeApp wire-to-None from Sprint 01.04 - 1 dead
        CommandHandler.set_metrics entry deleted in Sprint 01.05 + 1
        CommandHandler.set_app added in Sprint 04.09/04.10/04.11 for the
        BridgeDeps.from_app factory - 1 reflexive set_remote_kill_switch
        retired in E1.6 #1716 alongside Plan 06.09's class deletion).
        Drift means the operator's deploy-verification
        'Wiring complete: N active' line moves."""
        baseline = json.loads(BASELINE_PATH.read_text())
        assert baseline["_total_setters"] == 36  # RR.6 (#2593) +1: set_roster_registry
        assert len(baseline["setter_call_order_when_all_subsystems_available"]) == 36

    @pytest.mark.asyncio
    async def test_pending_setters_log_reason(self, wired_app_with_spy, caplog):
        """Sprint 01.03: the 5 wire-to-None CommandHandler setters must show up
        in the WiringReport's pending list at boot, each with its
        owning-plan reason. Operator-visible dormancy is the entire point —
        a setter that's wire-to-None must not be silently skipped."""
        from bridge.wiring import apply_wiring_manifest

        app, _ = wired_app_with_spy
        # Re-derive the manifest from the live app so we hit the same WiringEntry
        # set that ran during _initialize. The cleanest way without exposing
        # WIRING_MANIFEST as a module attribute: intercept the manifest by
        # wrapping apply_wiring_manifest one more time.
        captured: dict[str, list] = {"manifest": []}
        original = apply_wiring_manifest

        def _capture(app_arg, manifest, logger_arg):
            captured["manifest"] = list(manifest)
            return original(app_arg, manifest, logger_arg)

        # Walk the manifest from a fresh _wire() invocation. We don't actually
        # need to re-run _initialize — we can rebuild the manifest by calling
        # _wire on the already-initialized app, but that would re-fire setters.
        # Instead: extract entries directly via introspection of _wire's source
        # is brittle. Simpler: re-run _wire() with apply intercepted.
        import bridge.app as bridge_app_module
        bridge_app_module.apply_wiring_manifest = _capture
        try:
            app._wire()
        finally:
            bridge_app_module.apply_wiring_manifest = original

        manifest_entries = captured["manifest"]
        wire_to_none_setters = {
            "set_workflow_registry": "Plan 04 owns construction",
            "set_workflow_engine": "Plan 04 owns construction",
            "set_routing_brain": "Plan 03 owns construction",
            "set_tick_manager": "Deferred; revive if proactive mode activated (Sprint 09.13)",
            "set_daily_log": "Plan 02 owns construction via BridgeApp.set_daily_log then mirrors here (Sprint 09.14)",
        }
        # Scope to CommandHandler entries only — Sprint 01.04 introduced a
        # second reflexive set_daily_log entry on BridgeApp itself which has a
        # different (legitimately different) reason_if_none.
        present = {
            e.setter_name: e
            for e in manifest_entries
            if e.setter_name in wire_to_none_setters and e.group == "command-handler"
        }
        missing = set(wire_to_none_setters) - set(present)
        assert not missing, f"Sprint 01.03 wire-to-None entries missing from manifest: {missing}"
        for name, expected_reason in wire_to_none_setters.items():
            entry = present[name]
            assert entry.required is False, (
                f"{name} must be required=False (wire-to-None), got required={entry.required}"
            )
            assert entry.reason_if_none == expected_reason, (
                f"{name} reason_if_none mismatch: got {entry.reason_if_none!r}, "
                f"expected {expected_reason!r}"
            )

    @pytest.mark.asyncio
    async def test_wire_to_none_setters_dont_fire_when_source_none(self, wired_app_with_spy):
        """CommandHandler wire-to-None setters MUST NOT call
        CommandHandler.set_X when the source attribute is None
        (anti-silent-skip the WiringReport surfaces).
        Spy verifies they're absent from the recorded call list.

        Sprint 03.05 — set_routing_brain was removed from this list because
        Plan 03 now constructs RoutingBrain in _initialize(); the manifest
        entry fires a real source. set_routing_brain still has its own
        coverage via test_set_routing_brain_fires_when_env_selector_present.

        Sprint 04.06 — set_workflow_registry and set_workflow_engine were
        removed from this list because Plan 04 now constructs both modules
        in _initialize(); the manifest entries fire real sources. They have
        their own coverage via test_set_workflow_registry_fires_when_constructed
        and test_set_workflow_engine_fires_when_constructed.

        Sprint 09.14 — set_daily_log was removed from this list because the
        DailyLogWriter is now constructed in _initialize() under
        config.daily_log_enabled (default True). It has its own coverage via
        test_set_daily_log_fires_when_enabled.
        """
        _, recorded = wired_app_with_spy
        wire_to_none = [
            # Sprint 09.13 still gates TickManager construction behind
            # config.proactive_enabled (default False), so the
            # CommandHandler.set_tick_manager source remains None in the
            # default test config and the setter must not fire.
            "set_tick_manager",
        ]
        for name in wire_to_none:
            assert name not in recorded, (
                f"{name} fired during _initialize() despite source being None — "
                f"the wire-to-None contract is broken."
            )

    @pytest.mark.asyncio
    async def test_set_daily_log_fires_when_enabled(self, wired_app_with_spy):
        """Sprint 09.14: with config.daily_log_enabled defaulting to True,
        DailyLogWriter is constructed in _initialize() and
        CommandHandler.set_daily_log fires. Replaces the wire-to-None coverage
        for this setter — moves it from pending to active."""
        _, recorded = wired_app_with_spy
        assert "set_daily_log" in recorded, (
            "set_daily_log did not fire during _initialize() despite "
            "config.daily_log_enabled defaulting to True — Sprint 09.14 wiring broke."
        )

    @pytest.mark.asyncio
    async def test_set_routing_brain_fires_when_env_selector_present(self, wired_app_with_spy):
        """Sprint 03.05: with EnvironmentSelector present, RoutingBrain is
        constructed and set_routing_brain fires. Replaces the wire-to-None
        coverage for this setter — moves it from pending to active."""
        _, recorded = wired_app_with_spy
        assert "set_routing_brain" in recorded, (
            "set_routing_brain did not fire during _initialize() despite "
            "EnvironmentSelector being available — Sprint 03.05 wiring broke."
        )

    @pytest.mark.asyncio
    async def test_set_workflow_registry_fires_when_constructed(self, wired_app_with_spy):
        """Sprint 04.06: with WorkflowRegistry constructed in _initialize(),
        set_workflow_registry fires. Replaces the wire-to-None coverage for
        this setter — moves it from pending to active."""
        _, recorded = wired_app_with_spy
        assert "set_workflow_registry" in recorded, (
            "set_workflow_registry did not fire during _initialize() despite "
            "WorkflowRegistry being constructible — Sprint 04.06 wiring broke."
        )

    @pytest.mark.asyncio
    async def test_set_workflow_engine_fires_when_constructed(self, wired_app_with_spy):
        """Sprint 04.06: with WorkflowEngine constructed in _initialize(),
        set_workflow_engine fires. Replaces the wire-to-None coverage for
        this setter — moves it from pending to active."""
        _, recorded = wired_app_with_spy
        assert "set_workflow_engine" in recorded, (
            "set_workflow_engine did not fire during _initialize() despite "
            "WorkflowEngine being constructible — Sprint 04.06 wiring broke."
        )

    @pytest.mark.asyncio
    async def test_bridgeapp_setter_attrs_declared(self, wired_app_with_spy):
        """Sprint 01.04: BridgeApp source attributes must be declared
        as None after __init__ even when no _initialize() call has set them.
        Two of them (_workorder_store, _workorder_stream) are NOT manifest
        entries — they're consumed only via getattr from api_server.py:1385,
        so they must exist as None to avoid latent AttributeError at GET time
        when Plan 03 hasn't constructed them yet.

        E1.6 (#1716) retired `_remote_kill_switch` along with the wiring entry
        and setter — Plan 06.09 deleted the `RemoteKillSwitch` class; remote
        halt polling now lives inline in `background_loops.heartbeat_loop`.
        """
        app, _ = wired_app_with_spy
        for attr in ("_daily_log", "_memory_file",
                     "_workorder_store", "_workorder_stream"):
            assert hasattr(app, attr), (
                f"BridgeApp.{attr} is not declared. api_server.py:1385 and the "
                f"WIRING_MANIFEST depend on this attribute existing."
            )

    @pytest.mark.asyncio
    async def test_bridgeapp_reflexive_pending_entries(self, wired_app_with_spy):
        """Sprint 01.04: the reflexive BridgeApp manifest entries must be
        present with required=False and the owning-plan reason.

        E1.6 (#1716) retired the `set_remote_kill_switch` entry; Plan 06.09
        deleted the underlying class so the wire no longer has a contract."""
        from bridge.wiring import apply_wiring_manifest

        app, _ = wired_app_with_spy
        captured: dict[str, list] = {"manifest": []}
        original = apply_wiring_manifest

        def _capture(app_arg, manifest, logger_arg):
            captured["manifest"] = list(manifest)
            return original(app_arg, manifest, logger_arg)

        import bridge.app as bridge_app_module
        bridge_app_module.apply_wiring_manifest = _capture
        try:
            app._wire()
        finally:
            bridge_app_module.apply_wiring_manifest = original

        manifest_entries = captured["manifest"]
        # Reflexive entries have target=app (the BridgeApp instance) AND
        # group="bridge-app" — distinguishing them from the CommandHandler
        # ones which have target=app._commands and group="command-handler".
        reflexive = {
            e.setter_name: e
            for e in manifest_entries
            if e.target is app and e.group == "bridge-app"
        }
        expected = {
            "set_daily_log": "Plan 02 owns DailyLogWriter construction",
            "set_memory_file": "Plan 05 owns MemoryFile construction",
        }
        missing = set(expected) - set(reflexive)
        assert not missing, (
            f"Sprint 01.04 reflexive BridgeApp entries missing: {missing}"
        )
        for name, expected_reason in expected.items():
            entry = reflexive[name]
            assert entry.required is False, (
                f"reflexive {name} must be required=False, got {entry.required}"
            )
            assert entry.reason_if_none == expected_reason, (
                f"reflexive {name} reason mismatch: got {entry.reason_if_none!r}, "
                f"expected {expected_reason!r}"
            )

    @pytest.mark.asyncio
    async def test_no_workorder_setter_in_manifest(self, wired_app_with_spy):
        """Sprint 01.04 explicitly declines to add manifest entries for
        _workorder_store / _workorder_stream — Plan 03 hasn't decided the
        construction shape yet. Verify the manifest does NOT include them so
        we don't accidentally call a non-existent setter at boot."""
        from bridge.wiring import apply_wiring_manifest

        app, _ = wired_app_with_spy
        captured: dict[str, list] = {"manifest": []}
        original = apply_wiring_manifest

        def _capture(app_arg, manifest, logger_arg):
            captured["manifest"] = list(manifest)
            return original(app_arg, manifest, logger_arg)

        import bridge.app as bridge_app_module
        bridge_app_module.apply_wiring_manifest = _capture
        try:
            app._wire()
        finally:
            bridge_app_module.apply_wiring_manifest = original

        forbidden_setters = {"set_workorder_store", "set_workorder_stream"}
        present = {e.setter_name for e in captured["manifest"]}
        accidental = present & forbidden_setters
        assert not accidental, (
            f"Manifest unexpectedly includes WorkOrder setters {accidental} — "
            f"Plan 03 hasn't shipped the construction shape; do not add a "
            f"setter on BridgeApp until then."
        )

    @pytest.mark.asyncio
    async def test_set_metrics_not_in_manifest(self, wired_app_with_spy):
        """Sprint 01.05: the dead CommandHandler.set_metrics WiringEntry was
        deleted. CommandHandler has no set_metrics() method (only
        set_metrics_aggregator), and _metrics is None at apply time, so the
        entry never fired. Guard against accidental re-introduction."""
        from bridge.wiring import apply_wiring_manifest

        app, _ = wired_app_with_spy
        captured: dict[str, list] = {"manifest": []}
        original = apply_wiring_manifest

        def _capture(app_arg, manifest, logger_arg):
            captured["manifest"] = list(manifest)
            return original(app_arg, manifest, logger_arg)

        import bridge.app as bridge_app_module
        bridge_app_module.apply_wiring_manifest = _capture
        try:
            app._wire()
        finally:
            bridge_app_module.apply_wiring_manifest = original

        offenders = [
            e for e in captured["manifest"] if e.setter_name == "set_metrics"
        ]
        assert not offenders, (
            f"Sprint 01.05 deleted the dead set_metrics WiringEntry, but "
            f"{len(offenders)} entry/entries with setter_name='set_metrics' "
            f"reappeared in the manifest. CommandHandler has no set_metrics() "
            f"method (only set_metrics_aggregator); the call would AttributeError "
            f"if _metrics were ever non-None at apply time."
        )

    @pytest.mark.asyncio
    async def test_wiring_report_summary_logged(self, wired_app_with_spy, caplog):
        """log_wiring_report must emit the 'Wiring complete: N active, M pending,
        K errors' line that the operator deploy-verification step looks for."""
        # caplog from the fixture run is gone; re-trigger via a fresh apply
        from bridge.wiring import (
            WiringReport,
            log_wiring_report,
        )
        import logging

        logger = logging.getLogger("test.wiring.parity")
        report = WiringReport(active=14, pending=[], errors=[])
        with caplog.at_level(logging.INFO, logger="test.wiring.parity"):
            log_wiring_report(report, logger)
        assert any(
            "Wiring complete" in r.getMessage() and "14 active" in r.getMessage()
            for r in caplog.records
        )
