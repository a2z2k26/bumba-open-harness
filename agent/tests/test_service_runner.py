"""Tests for the universal service runner (MS2.1 hardening)."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch, MagicMock

import pytest

from bridge.services.base import ServiceBase, REQUIRED_STATE_FIELDS
from bridge.services.runner import (
    SERVICE_MAP,
    SERVICE_TIMEOUTS,
    _resolve_service_name,
    _write_crash_state,
    _write_crash_alert,
    run_service_with_timeout,
    list_services,
    run_service,
)


@pytest.fixture
def tmp_data(tmp_path):
    """Set up temp data directory structure."""
    (tmp_path / "service_messages").mkdir()
    (tmp_path / "service_state").mkdir()
    return tmp_path


# -- T2.1.1: SERVICE_MAP completeness --


class TestServiceMap:
    # Core 10 services plus the Z2-S5.x additions (#599) and funnel_post (FR-005).
    # Extending this set requires also updating SERVICE_NARRATIONS and SERVICE_SCHEDULES.
    CORE_SERVICES = {
        "briefing", "checkin", "email", "calendar", "knowledge_review",
        "job_search", "job_search_execute", "retro", "weekly_review", "consolidation",
    }
    Z2_S5_SERVICES = {
        "inbox_nurture", "subscription_tracker", "project_pulse",
    }
    FUNNEL_POST_SERVICES = {"funnel_post"}
    REVIEW_SERVICES = {"weekly_ceo_review"}
    # Sprint 02.07 — event-driven Cal.com prebrief + 10-min polling fallback
    MEETING_PREBRIEF_SERVICES = {"meeting_prebrief"}
    # Sprint 14.10 / 14.11 — Dark Factory orchestrator + soak harness (cron every 4h)
    FACTORY_SERVICES = {"factory_orchestrator", "factory_soak"}
    # Sprint 2.07 — Zone 1 doctrine drift detector
    ZONE1_SERVICES = {"zone1_drift"}

    EXPECTED_SERVICES = (
        CORE_SERVICES
        | Z2_S5_SERVICES
        | FUNNEL_POST_SERVICES
        | REVIEW_SERVICES
        | MEETING_PREBRIEF_SERVICES
        | FACTORY_SERVICES
        | ZONE1_SERVICES
    )

    def test_all_services_in_map(self):
        assert set(SERVICE_MAP.keys()) == self.EXPECTED_SERVICES

    def test_service_map_size(self):
        assert len(SERVICE_MAP) == len(self.EXPECTED_SERVICES)

    def test_all_entries_are_tuples(self):
        for name, entry in SERVICE_MAP.items():
            assert isinstance(entry, tuple), f"{name} is not a tuple"
            assert len(entry) == 2

    def test_all_modules_importable(self):
        import importlib
        for name, (module_path, class_name) in SERVICE_MAP.items():
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            assert cls is not None, f"Failed to import {class_name} from {module_path}"

    def test_all_timeouts_defined(self):
        for name in SERVICE_MAP:
            assert name in SERVICE_TIMEOUTS, f"Missing timeout for {name}"

    def test_resolve_alias_knowledge_review(self):
        assert _resolve_service_name("knowledge-review") == "knowledge_review"

    def test_resolve_alias_job_search(self):
        assert _resolve_service_name("job-search") == "job_search"

    def test_resolve_direct_name(self):
        assert _resolve_service_name("briefing") == "briefing"

    def test_resolve_unknown_passes_through(self):
        assert _resolve_service_name("nonexistent") == "nonexistent"

    def test_list_services(self, capsys):
        list_services()
        output = capsys.readouterr().out
        assert "briefing" in output
        assert "checkin" in output
        assert "job_search" in output

    def test_unknown_service_raises(self, tmp_data):
        import bridge.services.runner as runner
        original = runner.DATA_DIR
        runner.DATA_DIR = tmp_data
        try:
            with pytest.raises(ValueError, match="Unknown service"):
                run_service("nonexistent")
        finally:
            runner.DATA_DIR = original


# -- T2.1.3: Service state schema --


class TestServiceState:
    """Verify REQUIRED_STATE_FIELDS and state operations."""

    def test_required_fields_exist(self):
        assert "last_run" in REQUIRED_STATE_FIELDS
        assert "last_error" in REQUIRED_STATE_FIELDS
        assert "consecutive_failures" in REQUIRED_STATE_FIELDS
        assert "total_runs" in REQUIRED_STATE_FIELDS
        assert "total_failures" in REQUIRED_STATE_FIELDS
        assert "last_duration_ms" in REQUIRED_STATE_FIELDS
        assert "last_error_time" in REQUIRED_STATE_FIELDS

    def test_load_state_empty_returns_defaults(self, tmp_path):
        svc = ServiceBase(data_dir=tmp_path)
        state = svc.load_state("test-state.json")
        for key, default in REQUIRED_STATE_FIELDS.items():
            assert key in state, f"Missing required field: {key}"
            assert state[key] == default

    def test_load_state_merges_with_existing(self, tmp_path):
        svc = ServiceBase(data_dir=tmp_path)
        state_path = svc.state_dir / "test-state.json"
        state_path.write_text(json.dumps({"custom_field": "hello", "total_runs": 42}))
        state = svc.load_state("test-state.json")
        assert state["custom_field"] == "hello"
        assert state["total_runs"] == 42
        assert state["consecutive_failures"] == 0  # default merged

    def test_save_state_includes_required_fields(self, tmp_path):
        svc = ServiceBase(data_dir=tmp_path)
        svc.save_state({"custom": True}, "test-state.json")
        state = svc.load_state("test-state.json")
        assert state["custom"] is True
        for key in REQUIRED_STATE_FIELDS:
            assert key in state

    def test_save_state_atomic_no_tmp_files(self, tmp_path):
        svc = ServiceBase(data_dir=tmp_path)
        svc.save_state({"x": 1}, "test-state.json")
        tmp_files = list(svc.state_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_record_success(self, tmp_path):
        svc = ServiceBase(data_dir=tmp_path)
        svc.record_failure("broke", "test-state.json")
        assert svc.load_state("test-state.json")["consecutive_failures"] == 1

        svc.record_success(150, "test-state.json")
        state = svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 0
        assert state["last_error"] is None
        assert state["last_run"] is not None
        assert state["total_runs"] == 1
        assert state["last_duration_ms"] == 150

    def test_record_failure(self, tmp_path):
        svc = ServiceBase(data_dir=tmp_path)
        svc.record_failure("error A", "test-state.json")
        svc.record_failure("error B", "test-state.json")
        state = svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 2
        assert state["total_failures"] == 2
        assert state["last_error"] == "error B"
        assert state["last_error_time"] is not None

    def test_record_success_resets_consecutive_keeps_total(self, tmp_path):
        svc = ServiceBase(data_dir=tmp_path)
        svc.record_failure("err", "test-state.json")
        svc.record_failure("err", "test-state.json")
        svc.record_failure("err", "test-state.json")
        assert svc.load_state("test-state.json")["consecutive_failures"] == 3
        svc.record_success(100, "test-state.json")
        state = svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 0
        assert state["total_failures"] == 3

    def test_backwards_compat_old_location(self, tmp_path):
        svc = ServiceBase(data_dir=tmp_path)
        old_path = tmp_path / "legacy-state.json"
        old_path.write_text(json.dumps({"legacy_key": "found"}))
        state = svc.load_state("legacy-state.json")
        assert state["legacy_key"] == "found"
        assert "consecutive_failures" in state

    def test_state_dir_preferred_over_old(self, tmp_path):
        svc = ServiceBase(data_dir=tmp_path)
        (tmp_path / "dual-state.json").write_text(json.dumps({"source": "old"}))
        (tmp_path / "service_state" / "dual-state.json").write_text(json.dumps({"source": "new"}))
        loaded = svc.load_state(filename="dual-state.json")
        assert loaded["source"] == "new"


# -- T2.1.2: Timeout wrapper --


class TestServiceTimeout:
    """Verify timeout protection."""

    @pytest.mark.asyncio
    async def test_timeout_fires(self, tmp_path):
        class SlowService(ServiceBase):
            def __init__(self):
                super().__init__(data_dir=tmp_path)
            def run(self):
                time.sleep(10)
                return True

        svc = SlowService()
        with patch("bridge.services.runner._import_service_class", return_value=type(svc)), \
             patch("bridge.services.runner._instantiate_service", return_value=svc), \
             patch.dict(SERVICE_TIMEOUTS, {"test_slow": 1}):

            with pytest.raises(asyncio.TimeoutError):
                await run_service_with_timeout("test_slow")

    @pytest.mark.asyncio
    async def test_fast_service_completes(self, tmp_path):
        class FastService(ServiceBase):
            def __init__(self):
                super().__init__(data_dir=tmp_path)
            def run(self):
                return True

        svc = FastService()
        with patch("bridge.services.runner._import_service_class", return_value=type(svc)), \
             patch("bridge.services.runner._instantiate_service", return_value=svc):

            result = await run_service_with_timeout("checkin")
            assert result is True

    @pytest.mark.asyncio
    async def test_timeout_records_failure(self, tmp_path):
        class HangService(ServiceBase):
            def __init__(self):
                super().__init__(data_dir=tmp_path)
            def run(self):
                time.sleep(10)

        svc = HangService()
        with patch("bridge.services.runner._import_service_class", return_value=type(svc)), \
             patch("bridge.services.runner._instantiate_service", return_value=svc), \
             patch.dict(SERVICE_TIMEOUTS, {"test_hang": 1}):

            with pytest.raises(asyncio.TimeoutError):
                await run_service_with_timeout("test_hang")

            state = svc.load_state()
            assert state["consecutive_failures"] == 1
            assert "timeout" in (state.get("last_error") or "")

    @pytest.mark.asyncio
    async def test_error_records_failure(self, tmp_path):
        class CrashService(ServiceBase):
            def __init__(self):
                super().__init__(data_dir=tmp_path)
            def run(self):
                raise RuntimeError("oops")

        svc = CrashService()
        with patch("bridge.services.runner._import_service_class", return_value=type(svc)), \
             patch("bridge.services.runner._instantiate_service", return_value=svc):

            with pytest.raises(RuntimeError):
                await run_service_with_timeout("checkin")

            state = svc.load_state()
            assert state["consecutive_failures"] == 1
            assert "oops" in (state.get("last_error") or "")

    @pytest.mark.asyncio
    async def test_success_records_duration(self, tmp_path):
        class QuickService(ServiceBase):
            def __init__(self):
                super().__init__(data_dir=tmp_path)
            def run(self):
                time.sleep(0.05)
                return True

        svc = QuickService()
        with patch("bridge.services.runner._import_service_class", return_value=type(svc)), \
             patch("bridge.services.runner._instantiate_service", return_value=svc):

            await run_service_with_timeout("checkin")

            state = svc.load_state()
            assert state["last_duration_ms"] >= 40
            assert state["total_runs"] == 1


# -- T2.1.1: Instantiation tests --


class TestRunService:
    @patch("bridge.services.runner.DATA_DIR")
    @patch("bridge.services.runner.DB_PATH")
    @patch("bridge.services.runner._load_chat_id", return_value="test-chat")
    def test_briefing_instantiates(self, mock_chat, mock_db, mock_data, tmp_data):
        mock_data.__truediv__ = tmp_data.__truediv__
        mock_data.__str__ = lambda s: str(tmp_data)
        mock_db.__str__ = lambda s: str(tmp_data / "memory.db")

        import importlib
        mod = importlib.import_module(SERVICE_MAP["briefing"][0])
        cls = getattr(mod, SERVICE_MAP["briefing"][1])

        svc = cls(data_dir=tmp_data, db_path=tmp_data / "memory.db", chat_id="test")
        assert svc.chat_id == "test"
        assert svc.data_dir == tmp_data

    def test_email_instantiates(self, tmp_data):
        from bridge.services.email import EmailService
        svc = EmailService(data_dir=tmp_data, chat_id="test")
        assert svc.chat_id == "test"

    def test_calendar_instantiates(self, tmp_data):
        from bridge.services.calendar import CalendarService
        svc = CalendarService(data_dir=tmp_data, chat_id="test")
        assert svc.chat_id == "test"

    def test_knowledge_review_instantiates(self, tmp_data):
        from bridge.services.knowledge_review import KnowledgeReviewService
        svc = KnowledgeReviewService(
            data_dir=tmp_data, db_path=tmp_data / "memory.db", chat_id="test"
        )
        assert svc.chat_id == "test"


# -- T2.1.4: Structured logging --


class TestStructuredLogging:
    @pytest.mark.asyncio
    async def test_lifecycle_logging(self, tmp_path, caplog):
        """Verify service lifecycle events are logged."""
        class LogTestService(ServiceBase):
            def __init__(self):
                super().__init__(data_dir=tmp_path)
            def run(self):
                return True

        svc = LogTestService()
        with patch("bridge.services.runner._import_service_class", return_value=type(svc)), \
             patch("bridge.services.runner._instantiate_service", return_value=svc):

            import logging
            with caplog.at_level(logging.INFO):
                await run_service_with_timeout("checkin")

            log_messages = caplog.text
            assert "service.run.begin" in log_messages
            assert "service.run.complete" in log_messages


# -- Chat ID loading --


class TestLoadChatId:
    def test_reads_operator_id_from_secrets(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("operator_discord_id=12345\n")
        import bridge.services.runner as runner
        original = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        try:
            result = runner._load_chat_id()
            assert result == "12345"
        finally:
            runner.DATA_DIR = original

    def test_service_channel_id_takes_priority(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("operator_discord_id=12345\nservice_channel_id=99999\n")
        import bridge.services.runner as runner
        original = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        try:
            result = runner._load_chat_id()
            assert result == "99999"
        finally:
            runner.DATA_DIR = original

    def test_falls_back_to_operator_id_without_service_channel(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("operator_discord_id=12345\n")
        import bridge.services.runner as runner
        original = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        try:
            result = runner._load_chat_id()
            assert result == "12345"
        finally:
            runner.DATA_DIR = original

    def test_empty_when_no_secrets(self, tmp_path):
        import bridge.services.runner as runner
        original = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        try:
            result = runner._load_chat_id()
            assert result == ""
        finally:
            runner.DATA_DIR = original


# -- Crash state helpers --


class TestCrashState:
    def test_write_crash_state_creates_file(self, tmp_path):
        import bridge.services.runner as runner
        original = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        try:
            _write_crash_state("test_svc", "TypeError: unexpected kwarg")
            state_path = tmp_path / "service_state" / "test_svc-state.json"
            assert state_path.exists()
            state = json.loads(state_path.read_text())
            assert state["consecutive_failures"] == 1
            assert "TypeError" in state["last_error"]
            assert state["service"] == "test_svc"
        finally:
            runner.DATA_DIR = original

    def test_write_crash_state_increments(self, tmp_path):
        import bridge.services.runner as runner
        original = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        try:
            _write_crash_state("test_svc", "error 1")
            _write_crash_state("test_svc", "error 2")
            state_path = tmp_path / "service_state" / "test_svc-state.json"
            state = json.loads(state_path.read_text())
            assert state["consecutive_failures"] == 2
            assert "error 2" in state["last_error"]
        finally:
            runner.DATA_DIR = original

    def test_write_crash_alert_creates_file(self, tmp_path):
        import bridge.services.runner as runner
        original = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        try:
            _write_crash_alert("test_svc", "crashed hard")
            messages_dir = tmp_path / "service_messages"
            alert_files = list(messages_dir.glob("crash_test_svc_*.json"))
            assert len(alert_files) == 1
            alert = json.loads(alert_files[0].read_text())
            assert alert["type"] == "crash"
            assert alert["service"] == "test_svc"
            assert "crashed hard" in alert["message"]
        finally:
            runner.DATA_DIR = original

    @pytest.mark.asyncio
    async def test_instantiation_crash_writes_state(self, tmp_path):
        """When _instantiate_service raises, crash state + alert are written."""
        import bridge.services.runner as runner
        original = runner.DATA_DIR
        runner.DATA_DIR = tmp_path

        def _bad_instantiate(name, cls, event_callback=None):
            raise TypeError("unexpected keyword argument 'event_callback'")

        try:
            with patch("bridge.services.runner._import_service_class", return_value=MagicMock), \
                 patch("bridge.services.runner._instantiate_service", side_effect=_bad_instantiate):
                with pytest.raises(TypeError):
                    await run_service_with_timeout("job_search_execute")

            state_path = tmp_path / "service_state" / "job_search_execute-state.json"
            assert state_path.exists()
            state = json.loads(state_path.read_text())
            assert state["consecutive_failures"] == 1
            assert "TypeError" in state["last_error"]

            messages_dir = tmp_path / "service_messages"
            alert_files = list(messages_dir.glob("crash_job_search_execute_*.json"))
            assert len(alert_files) == 1
        finally:
            runner.DATA_DIR = original


# ---------------------------------------------------------------------------
# Sprint 06.10 — Halt flag gate
# ---------------------------------------------------------------------------

class TestHaltFlagGate:
    """runner skips service execution when data/halt.flag exists."""

    @pytest.mark.asyncio
    async def test_halt_flag_prevents_service_run(self, tmp_path):
        """When halt.flag exists, _async_main exits without running the service."""
        import bridge.services.runner as runner

        original_data_dir = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        halt_flag = tmp_path / "halt.flag"
        halt_flag.touch()

        ran = []

        async def fake_run(*_args, **_kwargs):
            ran.append(True)
            return True

        try:
            with patch("bridge.services.runner.run_service_with_timeout", side_effect=fake_run), \
                 patch("bridge.services.runner._shutdown_event") as mock_evt:
                mock_evt.is_set.return_value = False
                await runner._async_main("briefing")
        finally:
            runner.DATA_DIR = original_data_dir

        assert ran == [], "Service should NOT run when halt flag is set"

    @pytest.mark.asyncio
    async def test_no_halt_flag_allows_service_run(self, tmp_path):
        """When halt.flag is absent, _async_main proceeds to run the service."""
        import bridge.services.runner as runner

        original_data_dir = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        # Ensure halt flag does NOT exist
        halt_flag = tmp_path / "halt.flag"
        assert not halt_flag.exists()

        ran = []

        async def fake_run(name, **_kwargs):
            # Sprint 02.02 added an optional ``extra_kwargs`` to
            # ``run_service_with_timeout``; accept-and-ignore any kwargs
            # so this halt-flag test stays focused on the gating behaviour.
            ran.append(name)
            return True

        try:
            with patch("bridge.services.runner.run_service_with_timeout", side_effect=fake_run), \
                 patch("bridge.services.runner._shutdown_event") as mock_evt:
                mock_evt.is_set.return_value = False
                await runner._async_main("briefing")
        finally:
            runner.DATA_DIR = original_data_dir

        assert ran == ["briefing"], "Service SHOULD run when halt flag is absent"


# ---------------------------------------------------------------------------
# #2513 — Weekly CEO workflow dependency injection
# ---------------------------------------------------------------------------


class TestWeeklyCEOReviewRunnerWiring:
    class _CaptureService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def test_instantiate_service_threads_weekly_ceo_workflow_dependencies(
        self, tmp_path
    ):
        import bridge.services.runner as runner

        original_data_dir = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        fake_registry = object()
        fake_engine = object()
        try:
            with patch(
                "bridge.services.runner._build_weekly_ceo_workflow_kwargs",
                return_value={
                    "workflow_registry": fake_registry,
                    "workflow_engine": fake_engine,
                },
            ):
                svc = runner._instantiate_service(
                    "weekly_ceo_review", self._CaptureService
                )
        finally:
            runner.DATA_DIR = original_data_dir

        assert svc.kwargs["workflow_registry"] is fake_registry
        assert svc.kwargs["workflow_engine"] is fake_engine

    def test_build_weekly_ceo_workflow_kwargs_constructs_dependencies(self):
        import bridge.services.runner as runner
        from bridge.workflow_engine import WorkflowEngine
        from bridge.workflow_registry import WorkflowRegistry

        kwargs = runner._build_weekly_ceo_workflow_kwargs()

        assert isinstance(kwargs["workflow_registry"], WorkflowRegistry)
        assert isinstance(kwargs["workflow_engine"], WorkflowEngine)
        assert kwargs["workflow_registry"].get("weekly-ceo-review") is not None

    def test_missing_weekly_ceo_dependencies_preserve_honest_skip(
        self, tmp_path
    ):
        import bridge.services.runner as runner
        from bridge.services.weekly_ceo_review import WeeklyCEOReviewService

        original_data_dir = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        try:
            with patch(
                "bridge.services.runner._build_weekly_ceo_workflow_kwargs",
                return_value={},
            ):
                svc = runner._instantiate_service(
                    "weekly_ceo_review", WeeklyCEOReviewService
                )
        finally:
            runner.DATA_DIR = original_data_dir

        result = asyncio.run(svc.run())
        assert result.ok is False
        assert "workflow engine not configured" in result.narration

    @pytest.mark.asyncio
    async def test_weekly_ceo_review_not_blocked_by_deferred_guard(self, tmp_path):
        import bridge.services.runner as runner

        original_data_dir = runner.DATA_DIR
        runner.DATA_DIR = tmp_path
        ran = []

        async def fake_run(name, **_kwargs):
            ran.append(name)
            return True

        try:
            with patch(
                "bridge.services.runner.run_service_with_timeout",
                side_effect=fake_run,
            ), patch("bridge.services.runner._shutdown_event") as mock_evt:
                mock_evt.is_set.return_value = False
                await runner._async_main("weekly_ceo_review")
        finally:
            runner.DATA_DIR = original_data_dir

        assert ran == ["weekly_ceo_review"]


# ---------------------------------------------------------------------------
# Sprint P4.1 — Service runner import contract (regression lock)
# ---------------------------------------------------------------------------

class TestServiceRunnerImportContract:
    """Lock the three contract guarantees the P4.1 sprint shipped.

    These tests fail if a future change drifts the runner away from the
    invariants the dedicated CI workflow (.github/workflows/validate-services.yml)
    enforces. Having them in the pytest suite means the contract surfaces in
    the same test sweep as the rest of the runner, not only when the dedicated
    workflow runs.
    """

    def test_every_service_map_entry_imports(self):
        """Contract 1: every SERVICE_MAP entry must import (no orphan keys)."""
        import importlib

        for name, (module_path, class_name) in SERVICE_MAP.items():
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name, None)
            assert cls is not None, (
                f"SERVICE_MAP[{name!r}] -> {module_path}:{class_name} "
                f"failed to resolve"
            )

    def test_every_plist_label_is_service_alias_or_documented(self):
        """Contract 2: every plist com.bumba.agent-<label>.plist resolves to a
        SERVICE_MAP key, a SERVICE_ALIAS, or sits in the documented
        ON_DEMAND_PLISTS exception set inside validate_services().
        """
        import glob as _glob
        import re
        from pathlib import Path
        from bridge.services.runner import SERVICE_ALIASES

        # Mirror the search roots used by validate_services() so a failure here
        # matches a failure in CI.
        runner_file = Path(
            __import__("bridge.services.runner", fromlist=["runner"]).__file__
        )
        repo_root = runner_file.resolve().parent.parent.parent.parent

        plist_labels: set[str] = set()
        for pattern in (
            "agent/scripts/com.bumba.agent-*.plist",
            "agent/config/launchdaemons/com.bumba.agent-*.plist",
            "scripts/com.bumba.agent-*.plist",
        ):
            for plist in _glob.glob(str(repo_root / pattern)):
                m = re.search(r"com\.bumba\.agent-([^./]+)\.plist", plist)
                if m:
                    plist_labels.add(m.group(1))

        # The set of documented on-demand / infrastructure plists. Kept in sync
        # with validate_services() so the test is the authoritative spec.
        ON_DEMAND_PLISTS = {
            "bridge",
            "maintenance",
            "cost-rollup",
            "monitor",
            "oauth-refresh",
            "deploy-helper",
            "experiment",
            "consolidation-deep",
            "consolidation-micro",
            "consolidation-standard",
            "weekly-ceo-review",
            "job-execute",
        }

        unresolved: list[str] = []
        for label in plist_labels:
            if label in ON_DEMAND_PLISTS:
                continue
            normalized = label.replace("-", "_")
            if (
                label in SERVICE_MAP
                or normalized in SERVICE_MAP
                or label in SERVICE_ALIASES
                or normalized in SERVICE_ALIASES
            ):
                continue
            unresolved.append(label)

        assert not unresolved, (
            f"Unresolved plist labels (not in SERVICE_MAP, SERVICE_ALIASES, or "
            f"ON_DEMAND_PLISTS): {sorted(unresolved)}"
        )

    def test_validate_services_returns_true(self):
        """Contract 3: `python -m bridge.services.runner --validate` must pass.

        validate_services() is the function the CI workflow shells into; this
        test runs the same code path in-process so a regression surfaces in
        the unit test sweep, not only in the dedicated CI job.
        """
        from bridge.services.runner import validate_services

        assert validate_services() is True, (
            "validate_services() returned False — see stderr in test output "
            "for the structural rule(s) that failed."
        )


# ---------------------------------------------------------------------------
# F3 of #1501 — lazy AGENT_ROOT resolution via PEP 562
# ---------------------------------------------------------------------------


class TestAgentRootLazyResolution:
    """F3 of #1501 — ``AGENT_ROOT`` re-resolves on each attribute access.

    Pre-fix the constant was bound at import time and froze. Post-fix the
    PEP 562 ``__getattr__`` on ``bridge.services.runner`` calls
    ``_resolve_agent_root()`` on each access so tests/scripts that mutate
    ``cwd`` or ``BUMBA_AGENT_ROOT`` between reads see the current value.
    """

    @staticmethod
    def _make_fake_agent_tree(root):
        """Build the minimum tree shape that ``bridge.paths.agent_root`` validates."""
        (root / "bridge").mkdir(parents=True, exist_ok=True)
        (root / "bridge" / "__init__.py").write_text("")

    def test_agent_root_re_resolves_between_reads(self, tmp_path, monkeypatch):
        """Back-to-back ``runner.AGENT_ROOT`` reads pick up an env-var change."""
        import bridge.services.runner as runner

        first = tmp_path / "first"
        second = tmp_path / "second"
        self._make_fake_agent_tree(first)
        self._make_fake_agent_tree(second)

        monkeypatch.setenv("BUMBA_AGENT_ROOT", str(first))
        value_a = runner.AGENT_ROOT
        monkeypatch.setenv("BUMBA_AGENT_ROOT", str(second))
        value_b = runner.AGENT_ROOT

        assert value_a == first
        assert value_b == second
        assert value_a != value_b

    def test_agent_root_unknown_attribute_raises(self):
        """PEP 562 only catches ``AGENT_ROOT`` — other attribute names error."""
        import bridge.services.runner as runner

        try:
            runner.NOPE_NOT_A_REAL_ATTR  # noqa: B018
        except AttributeError as exc:
            assert "NOPE_NOT_A_REAL_ATTR" in str(exc)
        else:  # pragma: no cover — defensive
            raise AssertionError("Expected AttributeError for unknown attribute")
