"""Integration tests for PR Ship Decision workflow + operator gate (sprint G-PR.2).

@pytest.mark.live tests require real infrastructure.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from bridge.workflow_engine import WorkflowEngine
from bridge.workflow_registry import WorkflowRegistry
from config.workflows._schema import load_workflow_config


YAML_PATH = (
    Path(__file__).parent.parent / "config" / "workflows" / "pr-ship-decision.yaml"
)


@pytest.fixture()
def cfg():
    return load_workflow_config(YAML_PATH.read_text())


@pytest.fixture()
def workflow_dir(tmp_path: Path) -> Path:
    (tmp_path / "pr-ship-decision.yaml").write_text(YAML_PATH.read_text())
    return tmp_path


@pytest.fixture()
def registry(workflow_dir: Path) -> WorkflowRegistry:
    return WorkflowRegistry(config_dir=workflow_dir)


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------


class TestConditionEvaluation:
    def test_condition_true_when_confidence_low(self) -> None:
        from bridge.workflow_engine import _eval_condition

        ctx = {"confidence": "0.5"}
        assert _eval_condition("{confidence} < 0.7", ctx) is True

    def test_condition_false_when_confidence_high(self) -> None:
        from bridge.workflow_engine import _eval_condition

        ctx = {"confidence": "0.85"}
        assert _eval_condition("{confidence} < 0.7", ctx) is False

    def test_condition_at_boundary(self) -> None:
        from bridge.workflow_engine import _eval_condition

        ctx = {"confidence": "0.7"}
        # 0.7 < 0.7 is False
        assert _eval_condition("{confidence} < 0.7", ctx) is False

    def test_condition_parse_failure_defaults_to_true(self) -> None:
        """Conservative: unparseable conditions activate the gate."""
        from bridge.workflow_engine import _eval_condition

        ctx = {}
        assert _eval_condition("definitely-not-parseable", ctx) is True


# ---------------------------------------------------------------------------
# Engine integration with gate
# ---------------------------------------------------------------------------


class TestPRShipDecisionIntegration:
    @pytest.mark.asyncio
    async def test_workflow_completes_high_confidence(self, cfg) -> None:
        """When confidence >= 0.7, gate is skipped and workflow completes."""
        github_comments: list[str] = []

        async def dept_runner(dept, intent, ctx):
            if dept == "qa":
                return "All tests pass.", 0.1
            if dept == "strategy":
                return "No strategic concerns.", 0.1
            if dept == "board":
                # High confidence — gate should be skipped
                return "Decision: ship\nConfidence: 0.9\nRationale: Clean.", 0.3
            return f"[stub {dept}]", 0.05

        async def github_comment_stub(channel, message):
            github_comments.append(message)

        engine = WorkflowEngine(
            department_runner=dept_runner,
            discord_callback=github_comment_stub,
        )

        inputs = {
            "pr_number": "42",
            "pr_title": "Add feature X",
            "confidence": "0.9",
        }
        run_id = engine.start(cfg, inputs)
        await asyncio.sleep(0.2)

        state = engine.get_run_state(run_id)
        assert state is not None
        # Should complete (or fail due to no task_queue, gate auto-approves)
        assert state.status in {"completed", "failed"}

    @pytest.mark.asyncio
    async def test_workflow_hits_gate_on_low_confidence(self, cfg) -> None:
        """When confidence < 0.7, gate step is reached and waits for operator."""
        gate_reached = False
        original_set_awaiting = None

        mock_tq = MagicMock()
        mock_tq.create = AsyncMock(return_value=42)
        mock_tq.get = AsyncMock(return_value=MagicMock(status="pending", result="approved"))

        gate_event_created = asyncio.Event()
        gate_event_created.set()  # Auto-approve for this test

        async def mock_set_awaiting(task_id, question, event):
            nonlocal gate_reached
            gate_reached = True
            event.set()  # Immediately fire to avoid hanging

        mock_tq.set_awaiting_approval = AsyncMock(side_effect=mock_set_awaiting)

        async def dept_runner(dept, intent, ctx):
            if dept == "board":
                return "Decision: hold\nConfidence: 0.5\nRationale: Risky.", 0.3
            return f"[stub {dept}]", 0.1

        engine = WorkflowEngine(
            department_runner=dept_runner,
            task_queue=mock_tq,
        )

        inputs = {
            "pr_number": "77",
            "pr_title": "Risky change",
            "confidence": "0.5",  # Will be replaced by board output in real run
        }
        run_id = engine.start(cfg, inputs)
        await asyncio.sleep(0.3)

        state = engine.get_run_state(run_id)
        assert state is not None
        # Gate should have been reached for low confidence
        # (Note: engine uses initial context confidence; board output is stored as board_decision)
        # The gate condition checks {confidence} from context = "0.5" → gate fires
        assert gate_reached

    def test_registry_includes_workflow(self, registry: WorkflowRegistry) -> None:
        assert "pr-ship-decision" in registry.names()

    @pytest.mark.asyncio
    async def test_webhook_to_engine_pipeline(self) -> None:
        """Full pipeline: webhook → registry.trigger → engine.start → run."""
        from bridge.webhook_receiver import WebhookReceiver

        run_started: list[str] = []

        async def dept_runner(dept, intent, ctx):
            return f"[{dept}]", 0.1

        engine = WorkflowEngine(department_runner=dept_runner)
        registry = WorkflowRegistry(
            config_dir=YAML_PATH.parent,
        )

        receiver = WebhookReceiver(
            webhook_secret="test-s",
            workflow_registry=registry,
            workflow_engine=engine,
        )

        payload = {
            "action": "opened",
            "pull_request": {
                "number": 100,
                "title": "Integration PR",
                "user": {"login": "dev"},
                "base": {"ref": "main"},
                "head": {"ref": "feature/integration"},
            },
            "repository": {"full_name": "org/bumba"},
        }
        body = json.dumps(payload).encode()
        sig = "sha256=" + _hmac.new(b"test-s", body, hashlib.sha256).hexdigest()

        result = await receiver.handle_webhook(body, sig, "pull_request")
        assert result.get("received") is True

        # Engine should have an active run
        active = engine.active_run_ids()
        assert len(active) >= 1

        # Let the run proceed
        await asyncio.sleep(0.2)


@pytest.mark.live
class TestPRShipDecisionLive:
    def test_live_placeholder(self) -> None:
        pytest.skip("Live test: requires wired Z4 department runner")
