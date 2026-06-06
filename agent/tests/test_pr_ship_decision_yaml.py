"""Tests for pr-ship-decision workflow YAML + webhook trigger (sprint G-PR.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from config.workflows._schema import ActionStep, DepartmentStep, GateStep, load_workflow_config


YAML_PATH = (
    Path(__file__).parent.parent / "config" / "workflows" / "pr-ship-decision.yaml"
)


@pytest.fixture()
def cfg():
    return load_workflow_config(YAML_PATH.read_text())


class TestPRShipDecisionYAML:
    def test_file_exists(self) -> None:
        assert YAML_PATH.exists(), "pr-ship-decision.yaml must exist"

    def test_name(self, cfg) -> None:
        assert cfg.name == "pr-ship-decision"

    def test_trigger_webhook(self, cfg) -> None:
        assert cfg.trigger == "webhook"

    def test_webhook_event(self, cfg) -> None:
        assert cfg.webhook == "github.pull_request.opened"

    def test_budget_cap(self, cfg) -> None:
        assert cfg.budget.max_cost_usd == 2.0

    def test_has_qa_step(self, cfg) -> None:
        qa_steps = [
            s for s in cfg.steps
            if isinstance(s, DepartmentStep) and s.department == "qa"
        ]
        assert qa_steps, "Must have a QA department step"

    def test_has_strategy_step(self, cfg) -> None:
        strategy_steps = [
            s for s in cfg.steps
            if isinstance(s, DepartmentStep) and s.department == "strategy"
        ]
        assert strategy_steps, "Must have a strategy department step"

    def test_has_board_decision_step(self, cfg) -> None:
        board_steps = [
            s for s in cfg.steps
            if isinstance(s, DepartmentStep) and s.department == "board"
        ]
        assert board_steps, "Must have a board department step"

    def test_parallel_qa_strategy(self, cfg) -> None:
        """QA and strategy steps should run in parallel."""
        dept_steps = [s for s in cfg.steps if isinstance(s, DepartmentStep)]
        parallel_refs = {s.parallel_with for s in dept_steps if s.parallel_with}
        assert parallel_refs, "QA and strategy should run in parallel"

    def test_has_operator_gate(self, cfg) -> None:
        gate_steps = [s for s in cfg.steps if isinstance(s, GateStep)]
        assert gate_steps, "Must have an operator gate step"

    def test_gate_has_condition(self, cfg) -> None:
        gate_steps = [s for s in cfg.steps if isinstance(s, GateStep)]
        assert gate_steps[0].condition is not None, "Gate must have a condition"
        # Condition should reference confidence
        assert "confidence" in gate_steps[0].condition

    def test_gate_timeout(self, cfg) -> None:
        gate_steps = [s for s in cfg.steps if isinstance(s, GateStep)]
        assert gate_steps[0].timeout_seconds == 3600

    def test_has_github_comment_action(self, cfg) -> None:
        action_steps = [
            s for s in cfg.steps
            if isinstance(s, ActionStep) and s.action == "publish_github_comment"
        ]
        assert action_steps, "Must have a publish_github_comment action step"

    def test_schema_validates(self) -> None:
        cfg = load_workflow_config(YAML_PATH.read_text())
        assert cfg is not None


class TestWebhookTriggersPRShipWorkflow:
    """Test that WebhookReceiver triggers pr-ship-decision on PR opened."""

    @pytest.mark.asyncio
    async def test_pr_opened_triggers_workflow(self) -> None:
        import hashlib
        import hmac as _hmac
        import json

        from bridge.webhook_receiver import WebhookReceiver

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=object())  # Workflow exists
        mock_registry.trigger = MagicMock(return_value="run-pr-456")
        mock_engine = MagicMock()

        receiver = WebhookReceiver(
            webhook_secret="test-secret",
            workflow_registry=mock_registry,
            workflow_engine=mock_engine,
        )

        payload = {
            "action": "opened",
            "pull_request": {
                "number": 42,
                "title": "Add feature X",
                "user": {"login": "dev-user"},
                "base": {"ref": "main"},
                "head": {"ref": "feature/x"},
            },
            "repository": {"full_name": "org/repo"},
        }
        body = json.dumps(payload).encode()
        secret = b"test-secret"
        sig = "sha256=" + _hmac.new(secret, body, hashlib.sha256).hexdigest()

        result = await receiver.handle_webhook(body, sig, "pull_request")
        assert result.get("received") is True

        # Workflow should have been triggered
        mock_registry.trigger.assert_called_once()
        call_kwargs = mock_registry.trigger.call_args
        assert call_kwargs[0][0] == "pr-ship-decision"

    @pytest.mark.asyncio
    async def test_pr_opened_inputs_include_pr_number(self) -> None:
        import hashlib
        import hmac as _hmac
        import json

        from bridge.webhook_receiver import WebhookReceiver

        inputs_passed: dict = {}

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=object())

        def capture_trigger(name, inputs, engine):
            inputs_passed.update(inputs or {})
            return "run-capture"

        mock_registry.trigger = MagicMock(side_effect=capture_trigger)
        mock_engine = MagicMock()

        receiver = WebhookReceiver(
            webhook_secret="s",
            workflow_registry=mock_registry,
            workflow_engine=mock_engine,
        )

        payload = {
            "action": "opened",
            "pull_request": {
                "number": 99,
                "title": "Test PR",
                "user": {"login": "author"},
                "base": {"ref": "main"},
                "head": {"ref": "feature/test"},
            },
            "repository": {"full_name": "org/bumba"},
        }
        body = json.dumps(payload).encode()
        sig = "sha256=" + _hmac.new(b"s", body, hashlib.sha256).hexdigest()

        await receiver.handle_webhook(body, sig, "pull_request")

        assert inputs_passed.get("pr_number") == "99"
        assert inputs_passed.get("pr_title") == "Test PR"
        assert inputs_passed.get("repo") == "org/bumba"

    @pytest.mark.asyncio
    async def test_workflow_not_triggered_without_registry(self) -> None:
        import hashlib
        import hmac as _hmac
        import json

        from bridge.webhook_receiver import WebhookReceiver

        receiver = WebhookReceiver(webhook_secret="test-secret")

        payload = {
            "action": "opened",
            "pull_request": {"number": 1, "title": "T", "user": {"login": "u"},
                             "base": {"ref": "main"}, "head": {"ref": "f"}},
        }
        body = json.dumps(payload).encode()
        sig = "sha256=" + _hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()

        result = await receiver.handle_webhook(body, sig, "pull_request")
        assert result.get("received") is True  # No crash, just no workflow

    @pytest.mark.asyncio
    async def test_non_opened_action_does_not_trigger(self) -> None:
        import hashlib
        import hmac as _hmac
        import json

        from bridge.webhook_receiver import WebhookReceiver

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=object())
        mock_registry.trigger = MagicMock()
        mock_engine = MagicMock()

        receiver = WebhookReceiver(
            webhook_secret="s",
            workflow_registry=mock_registry,
            workflow_engine=mock_engine,
        )

        payload = {
            "action": "synchronize",  # Not 'opened'
            "pull_request": {"number": 1, "title": "T", "user": {"login": "u"},
                             "base": {"ref": "main"}, "head": {"ref": "f"}},
        }
        body = json.dumps(payload).encode()
        sig = "sha256=" + _hmac.new(b"s", body, hashlib.sha256).hexdigest()

        await receiver.handle_webhook(body, sig, "pull_request")
        mock_registry.trigger.assert_not_called()
