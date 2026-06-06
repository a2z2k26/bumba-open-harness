"""Post-run hygiene policy for Zone 4 team runs."""

from __future__ import annotations

from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.chief_session import ChiefSession, ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore
from bridge.run_artifacts import (
    append_manifest_artifact,
    create_run_workspace,
    write_artifact,
)
from bridge.warm_chief import WarmChief
from teams._post_run import (
    decide_post_run_hygiene,
    should_checkpoint,
    should_clear_message_history,
)
from teams._run_telemetry import RunTelemetry
from teams._types import AgentSpec, DepartmentConfig, TeamResult
from tests.test_teams.conftest import make_deps


def _config() -> DepartmentConfig:
    return DepartmentConfig(
        name="strategy",
        zone=4,
        description="Strategy",
        manager=AgentSpec(
            name="strategy-product-chief",
            model="anthropic:claude-opus-4-6",
        ),
        employees=(),
    )


def test_should_clear_message_history_after_usage_limit() -> None:
    assert should_clear_message_history(
        input_tokens=80_000,
        failure_class="usage_limit_exceeded",
        artifact_count=1,
    )


def test_should_clear_message_history_after_large_artifact_run() -> None:
    assert should_clear_message_history(
        input_tokens=200_000,
        failure_class=None,
        artifact_count=1,
    )


def test_should_not_clear_small_success_without_artifacts() -> None:
    assert not should_clear_message_history(
        input_tokens=10_000,
        failure_class=None,
        artifact_count=0,
    )


def test_should_checkpoint_substantive_success() -> None:
    result = TeamResult(
        department="strategy",
        manager_output="Decision memo complete.",
        success=True,
    )

    assert should_checkpoint(result, result.telemetry)


def test_decision_uses_telemetry_before_manifest_artifact_count(
    tmp_path: Path,
) -> None:
    workspace = create_run_workspace(
        tmp_path / "zone4-runs",
        session_id="session-1",
        department="strategy",
        directive_id=None,
        chief="strategy-product-chief",
        entropy="unit-test",
    )
    entry = write_artifact(
        workspace.run_dir,
        "strategy-product-chief/result/summary.md",
        "summary",
        kind="result",
        agent="strategy-product-chief",
    )
    append_manifest_artifact(workspace.run_dir, entry)
    telemetry = RunTelemetry(
        department="strategy",
        chief_name="strategy-product-chief",
        primary_model="anthropic:claude-opus-4-6",
        input_tokens=200_000,
        artifacts_written=1,
    )
    result = TeamResult(
        department="strategy",
        manager_output="done",
        total_tokens=100,
        success=True,
        telemetry=telemetry,
        manifest_path=str(workspace.manifest_path),
    )

    decision = decide_post_run_hygiene(result, result.telemetry)

    assert decision.checkpoint is True
    assert decision.input_tokens == 200_000
    assert decision.artifact_count == 1
    assert decision.clear_message_history is True


@pytest.mark.asyncio
async def test_warm_chief_policy_clears_small_history_after_checkpoint(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workspace = create_run_workspace(
        tmp_path / "zone4-runs",
        session_id="session-1",
        department="strategy",
        directive_id=None,
        chief="strategy-product-chief",
        entropy="unit-test",
    )
    entry = write_artifact(
        workspace.run_dir,
        "strategy-product-chief/result/summary.md",
        "summary",
        kind="result",
        agent="strategy-product-chief",
    )
    append_manifest_artifact(workspace.run_dir, entry)

    session = ChiefSession(
        session_id="cs-post-run01",
        work_order_id="wo-post-run01",
        department="strategy",
        chief_name="strategy-product-chief",
        state=ChiefSessionState.WARM,
    )
    store = InMemoryChiefSessionStore()
    await store.create(session)
    await store.update_message_history(session.session_id, b"old-history")

    deps = make_deps(session_id="session-1", department="strategy")
    deps.memory_store.set = AsyncMock(return_value=None)
    event_bus = MagicMock()
    event_bus.publish = MagicMock(return_value=None)

    telemetry = RunTelemetry(
        department="strategy",
        chief_name="strategy-product-chief",
        primary_model="anthropic:claude-opus-4-6",
        input_tokens=200_000,
        artifacts_written=1,
    )
    team_result = TeamResult(
        department="strategy",
        manager_output="Large artifact-backed run complete.",
        total_tokens=400_000,
        success=True,
        telemetry=telemetry,
        manifest_path=str(workspace.manifest_path),
        memory_ref=f"memory:zone4/strategy/{workspace.run_id}",
    )
    mock_run_result = MagicMock()
    mock_run_result.all_messages.return_value = [MagicMock()]

    async def _fake_run_chief(self: WarmChief) -> TeamResult:
        self._run_result = mock_run_result
        return team_result

    wc = WarmChief(
        session,
        store,
        _config(),
        deps,
        "task",
        event_bus=event_bus,
    )
    with patch("bridge.warm_chief.ModelMessagesTypeAdapter") as adapter:
        adapter.dump_json.return_value = b'{"messages":["small"]}'
        with caplog.at_level("INFO", logger="bridge.warm_chief"):
            with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                async with wc:
                    pass

    assert await store.get_message_history_blob(session.session_id) is None
    deps.memory_store.set.assert_awaited_once()
    assert any(
        "post_run.context_cleared" in record.getMessage()
        for record in caplog.records
    )

    event_types = [call.args[0] for call in event_bus.publish.call_args_list]
    assert event_types.index(
        "chief_session.memory_checkpointed"
    ) < event_types.index("chief_session.history_compacted")
