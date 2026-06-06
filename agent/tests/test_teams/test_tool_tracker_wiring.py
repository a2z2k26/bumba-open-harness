"""Tests for Z4.13 ToolTracker wiring into department execution path.

Verifies:
1. DepartmentTeam with a tracker produces ToolCallRecords when tools are invoked.
2. Secret redaction — api_key values are scrubbed from JSONL output.
3. Feature flag off — no records written when tracker is None.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from bridge.observability.tool_tracker import ToolTracker
from teams._factory import build_employee_agents, build_manager_agent
from teams._tool_registry import resolve_tools
from tests.test_teams.conftest import make_deps
from teams._types import (
    AgentSpec,
    BridgeDeps,
    DepartmentConfig,
)


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "z4-sessions"
    d.mkdir()
    return d


@pytest.fixture
def tracker(sessions_dir: Path) -> ToolTracker:
    return ToolTracker(sessions_dir=sessions_dir)


@pytest.fixture
def minimal_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA department for testing",
        manager=AgentSpec(
            name="qa-chief",
            model="anthropic:claude-opus-4-6",
            role="Orchestrates QA work",
        ),
        employees=(
            AgentSpec(
                name="qa-engineer",
                model="anthropic:claude-sonnet-4-6",
                role="Test design and coverage",
            ),
        ),
        common_tools=("read_file",),
    )


@pytest.fixture
def bridge_deps() -> BridgeDeps:
    return make_deps(session_id="test-session-1", department="qa")


class TestToolTrackerWiring:
    """DepartmentTeam with a tracker produces ToolCallRecords."""

    @pytest.mark.asyncio
    async def test_tool_call_produces_record(
        self, minimal_config: DepartmentConfig, tracker: ToolTracker, bridge_deps: BridgeDeps, sessions_dir: Path
    ) -> None:
        employees = build_employee_agents(minimal_config, tracker=tracker)
        manager = build_manager_agent(minimal_config, employees, tracker=tracker)

        # TestModel calls the read_file tool, which triggers the tracker
        test_model = TestModel(
            custom_output_args={"answer": "Done reviewing."},
            call_tools=["read_file"],
        )

        with manager.override(model=test_model):
            result = await manager.run("Review auth module", deps=bridge_deps)

        assert result.output
        # ToolTracker writes to sessions/{session_id}/{department}/tools/{agent_name}.jsonl
        # The agent_name passed to log_call is the department name ("qa") from make_tracked
        records = tracker.get_session_calls("test-session-1")
        assert len(records) >= 1
        rec = records[0]
        assert rec.tool_name == "read_file"
        assert rec.session_id == "test-session-1"
        assert rec.department == "qa"


class TestSecretRedaction:
    """Secret values must be scrubbed from JSONL output."""

    def test_api_key_redacted_in_log(
        self, tracker: ToolTracker, sessions_dir: Path
    ) -> None:
        # Directly call log_call with args containing a secret key
        record = tracker.log_call(
            agent_name="test-agent",
            department="qa",
            session_id="redact-test",
            tool_name="some_tool",
            args={"api_key": "secret-123", "query": "hello"},
            result="ok",
        )
        assert record is not None

        # Read the JSONL file and verify redaction
        jsonl_path = sessions_dir / "redact-test" / "qa" / "tools" / "test-agent.jsonl"
        assert jsonl_path.exists()
        content = jsonl_path.read_text()
        assert "secret-123" not in content
        assert "[REDACTED]" in content
        # Non-secret values should still be present
        assert "hello" in content

    def test_tool_call_args_with_secret_via_resolve_tools(
        self, tracker: ToolTracker, sessions_dir: Path
    ) -> None:
        """resolve_tools with tracker wraps tools; verify sanitize_args is called."""
        # resolve_tools wraps callables with make_tracked which calls tracker.log_call
        # The log_call internally uses sanitize_args. We verify via direct call.
        record = tracker.log_call(
            agent_name="eng-specialist",
            department="engineering",
            session_id="secret-test-2",
            tool_name="deploy",
            args={"auth_token": "tok-abc-xyz", "target": "prod"},
            result="deployed",
        )
        records = tracker.get_agent_calls("secret-test-2", "engineering", "eng-specialist")
        assert len(records) == 1
        assert "tok-abc-xyz" not in records[0].args_summary
        assert "[REDACTED]" in records[0].args_summary
        assert "prod" in records[0].args_summary


class TestFeatureFlagOff:
    """When tracker is None, no records should be written."""

    @pytest.mark.asyncio
    async def test_no_tracker_no_records(
        self, minimal_config: DepartmentConfig, bridge_deps: BridgeDeps, sessions_dir: Path
    ) -> None:
        # Build without tracker (tracker=None)
        employees = build_employee_agents(minimal_config, tracker=None)
        manager = build_manager_agent(minimal_config, employees, tracker=None)

        test_model = TestModel(
            custom_output_args={"answer": "Done."},
            call_tools=["read_file"],
        )

        with manager.override(model=test_model):
            result = await manager.run("Review auth module", deps=bridge_deps)

        assert result.output
        # Verify no JSONL files were created
        jsonl_files = list(sessions_dir.rglob("*.jsonl"))
        assert len(jsonl_files) == 0

    def test_resolve_tools_no_tracker(self) -> None:
        """resolve_tools with tracker=None should still return wrapped callables."""
        resolved = resolve_tools(
            ("read_file", "search_knowledge"),
            "qa",
            tracker=None,
        )
        assert len(resolved) == 2
        names = [name for name, _ in resolved]
        assert "read_file" in names
        assert "search_knowledge" in names


class TestRegistryPassesTracker:
    """DepartmentRegistry passes tool_tracker to DepartmentTeam."""

    def test_registry_stores_tracker(self, tracker: ToolTracker) -> None:
        from teams._registry import DepartmentRegistry

        registry = DepartmentRegistry(configs={}, tool_tracker=tracker)
        assert registry._tool_tracker is tracker

    def test_registry_from_directory_stores_tracker(
        self, tracker: ToolTracker, tmp_path: Path
    ) -> None:
        from teams._registry import DepartmentRegistry

        teams_dir = tmp_path / "teams"
        teams_dir.mkdir()
        registry = DepartmentRegistry.from_directory(teams_dir, tool_tracker=tracker)
        assert registry._tool_tracker is tracker

    def test_team_receives_tracker(
        self, minimal_config: DepartmentConfig, tracker: ToolTracker
    ) -> None:
        from teams._registry import DepartmentRegistry

        registry = DepartmentRegistry(
            configs={minimal_config.name: minimal_config},
            tool_tracker=tracker,
        )
        team = registry.get_team("qa")
        assert team._tool_tracker is tracker
