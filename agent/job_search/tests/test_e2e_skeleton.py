"""E2E skeleton tests for job search pipeline shape."""
from __future__ import annotations
import os
from unittest.mock import patch
from bridge.services.base import ServiceBase


class TestPreparePhase:
    """PREPARE phase mock test -- proves pipeline shape."""

    def test_prepare_service_inherits_base(self):
        """JobSearchPrepareService extends ServiceBase."""
        from job_search.service import JobSearchPrepareService
        assert issubclass(JobSearchPrepareService, ServiceBase)

    def test_prepare_service_init(self, tmp_path):
        from job_search.service import JobSearchPrepareService
        svc = JobSearchPrepareService(data_dir=tmp_path, chat_id="test-123")
        assert svc.chat_id == "test-123"

    def test_prepare_should_run_outside_window(self, tmp_path):
        from job_search.service import JobSearchPrepareService
        svc = JobSearchPrepareService(data_dir=tmp_path, chat_id="test", run_hour=99)
        assert svc.should_run() is False

    def test_prepare_state_file(self, tmp_path):
        from job_search.service import JobSearchPrepareService
        svc = JobSearchPrepareService(data_dir=tmp_path, chat_id="test")
        state = svc.load_state(filename="job-search-state.json")
        assert "consecutive_failures" in state


class TestExecutePhase:
    """EXECUTE phase mock test -- proves pipeline shape."""

    def test_execute_service_inherits_base(self):
        from job_search.service import JobSearchExecuteService
        assert issubclass(JobSearchExecuteService, ServiceBase)

    def test_execute_service_init(self, tmp_path):
        from job_search.service import JobSearchExecuteService
        svc = JobSearchExecuteService(data_dir=tmp_path, chat_id="test-456")
        assert svc.chat_id == "test-456"


class TestPipelineShape:
    """Full pipeline PREPARE -> EXECUTE cycle proves shape."""

    def test_prepare_then_execute_cycle(self, tmp_path):
        """Both services can be instantiated and share data_dir."""
        from job_search.service import JobSearchPrepareService, JobSearchExecuteService

        prepare = JobSearchPrepareService(data_dir=tmp_path, chat_id="test")
        execute = JobSearchExecuteService(data_dir=tmp_path, chat_id="test")

        # Both use same data dir
        assert prepare.data_dir == execute.data_dir

        # State dirs exist
        assert prepare.state_dir.exists()
        assert execute.state_dir.exists()

        # Message dirs exist
        assert prepare.messages_dir.exists()
        assert execute.messages_dir.exists()

    def test_service_state_files_isolated(self, tmp_path):
        """Each service uses its own state file."""
        from job_search.service import JobSearchPrepareService, JobSearchExecuteService

        prepare = JobSearchPrepareService(data_dir=tmp_path, chat_id="test")
        execute = JobSearchExecuteService(data_dir=tmp_path, chat_id="test")

        # They should use different state filenames
        prepare.record_success(100, filename="job-search-state.json")
        execute.record_success(50, filename="job-execute-state.json")

        p_state = prepare.load_state(filename="job-search-state.json")
        e_state = execute.load_state(filename="job-execute-state.json")

        assert p_state["last_duration_ms"] == 100
        assert e_state["last_duration_ms"] == 50

    def test_notion_db_id_configurable(self):
        """Notion DB ID can come from environment."""
        with patch.dict(os.environ, {"BUMBA_NOTION_JOB_DB_ID": "test-db-id-123"}):
            from job_search.service import _get_notion_db_id
            assert _get_notion_db_id() == "test-db-id-123"
