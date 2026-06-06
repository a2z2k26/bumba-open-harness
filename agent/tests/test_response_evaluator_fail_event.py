"""Sprint 05.10 — verdict=fail publishes EventBus event + records routing-feedback.

When ``ResponseEvaluator.evaluate()`` returns verdict="fail" inside
``BridgeApp._deliver_response``, the bridge must:

1. Publish ``response.evaluator.fail`` on the autonomy EventBus with a
   structured payload (session_id, verdict, evaluator_score, response_prefix
   trimmed to 200 chars, timestamp, model).
2. Record a failure signal on routing_feedback so the model_router can
   auto-escalate on repeated failures.

Both calls are wrapped in try/except — neither may block response delivery.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.app import BridgeApp, MessageContext
from bridge.claude_runner import ClaudeResult
from bridge.message_queue import QueuedMessage
from bridge.response_evaluator import EvaluationResult


# -- helpers --


def _queued_message(text: str = "do the thing") -> QueuedMessage:
    return QueuedMessage(
        id=1,
        platform_message_id=42,
        chat_id="chat-abc",
        text=text,
        received_at="2026-04-26T00:00:00Z",
        status="processing",
        attempt_count=1,
    )


def _claude_result(model: str = "sonnet", text: str = "x" * 250) -> ClaudeResult:
    r = ClaudeResult(
        response_text=text,
        session_id="sess-xyz",
        cost_usd=0.001,
        num_turns=1,
        tools_used=[],
        is_error=False,
        duration_ms=120,
    )
    # ClaudeResult has no model field by default; attach for routing_feedback path.
    setattr(r, "model", model)
    return r


def _make_app(*, eval_result: EvaluationResult, evaluator_raises: bool = False) -> BridgeApp:
    """Build a BridgeApp with only the deps _deliver_response touches mocked."""
    app = BridgeApp.__new__(BridgeApp)

    # Evaluator
    evaluator = MagicMock()
    if evaluator_raises:
        evaluator.evaluate = AsyncMock(side_effect=RuntimeError("evaluator boom"))
    else:
        evaluator.evaluate = AsyncMock(return_value=eval_result)
    app._evaluator = evaluator

    # Config (drives few_shot_active flag inside the eval call)
    app._config = MagicMock(few_shot_enabled=True)

    # Autonomy + EventBus
    autonomy = MagicMock()
    autonomy.event_bus = MagicMock()
    autonomy.event_bus.publish = MagicMock()
    autonomy.event_bus.complete_chain = MagicMock()
    app._autonomy = autonomy

    # Routing feedback
    app._routing_feedback = MagicMock()
    app._routing_feedback.record_model_use = MagicMock()

    # Discord send_response — return success
    app._send_response = AsyncMock(return_value=True)

    # MessageQueue (only mark_send_failed used on failure path)
    app._queue = MagicMock()
    app._queue.mark_send_failed = AsyncMock()

    # DailyLog disabled
    app._daily_log = None

    # Security audit
    app._security = MagicMock()
    app._security.log_event = AsyncMock()

    # Commands
    app._commands = MagicMock()
    app._commands.record_message = MagicMock()

    # Few-shot disabled (used by routing_feedback task_type classify path)
    app._few_shot = None

    # D7.9 #1421 (slice 2) — auto-ACK gate inside _deliver_response checks
    # ``self._operator_inbox is not None`` before acting. Tests run with the
    # gate disabled.
    app._operator_inbox = None

    return app


def _ctx(model: str = "sonnet") -> tuple[MessageContext, ClaudeResult]:
    msg = _queued_message()
    result = _claude_result(model=model)
    ctx = MessageContext(
        msg=msg,
        correlation_id="corr-1",
        msg_start=0.0,
        session_id="sess-xyz",
        result=result,
    )
    return ctx, result


# -- tests --


class TestEvaluatorFailEvent:
    @pytest.mark.asyncio
    async def test_fail_verdict_publishes_event_with_expected_payload(self):
        eval_result = EvaluationResult(
            completeness=3.0,
            correctness=2.0,
            actionability=4.0,
            safety=8.0,
            overall=3.5,
            issues=["incomplete", "wrong"],
            verdict="fail",
        )
        app = _make_app(eval_result=eval_result)
        ctx, result = _ctx(model="sonnet")

        await app._deliver_response(ctx, result)

        # Find the response.evaluator.fail publish call (message.processed also fires)
        publish = app._autonomy.event_bus.publish
        fail_calls = [
            c for c in publish.call_args_list
            if c.args and c.args[0] == "response.evaluator.fail"
        ]
        assert len(fail_calls) == 1, f"expected 1 fail event, got {publish.call_args_list}"

        call = fail_calls[0]
        # event_type as positional arg
        assert call.args[0] == "response.evaluator.fail"
        # payload via kwarg or positional
        payload = call.kwargs.get("payload") if "payload" in call.kwargs else call.args[1]
        assert payload["session_id"] == "sess-xyz"
        assert payload["verdict"] == "fail"
        assert payload["model"] == "sonnet"
        assert "timestamp" in payload
        assert isinstance(payload["timestamp"], (int, float))
        # response_prefix is exactly first 200 chars
        assert len(payload["response_prefix"]) == 200
        assert payload["response_prefix"] == "x" * 200
        # evaluator_score is a breakdown dict
        score = payload["evaluator_score"]
        assert score["overall"] == 3.5
        assert score["completeness"] == 3.0
        assert score["correctness"] == 2.0
        assert score["actionability"] == 4.0
        assert score["safety"] == 8.0
        assert score["issues"] == ["incomplete", "wrong"]

    @pytest.mark.asyncio
    async def test_fail_verdict_records_routing_feedback_failure(self):
        eval_result = EvaluationResult(overall=2.0, verdict="fail", issues=["bad"])
        app = _make_app(eval_result=eval_result)
        ctx, result = _ctx(model="haiku")

        await app._deliver_response(ctx, result)

        rf = app._routing_feedback.record_model_use
        # The fail-path call should be the only one in _deliver_response
        # (success path lives in _record_telemetry, not _deliver_response).
        assert rf.call_count == 1
        kwargs = rf.call_args.kwargs
        assert kwargs.get("success") is False
        # model_tier should reflect the model that produced the failed response
        assert kwargs.get("model_tier") == "haiku"

    @pytest.mark.asyncio
    async def test_pass_verdict_does_not_trigger_fail_event(self):
        eval_result = EvaluationResult(overall=8.0, verdict="pass", issues=[])
        app = _make_app(eval_result=eval_result)
        ctx, result = _ctx()

        await app._deliver_response(ctx, result)

        publish = app._autonomy.event_bus.publish
        fail_calls = [
            c for c in publish.call_args_list
            if c.args and c.args[0] == "response.evaluator.fail"
        ]
        assert fail_calls == []
        app._routing_feedback.record_model_use.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_verdict_does_not_trigger_fail_event(self):
        eval_result = EvaluationResult(overall=5.5, verdict="flag", issues=["minor"])
        app = _make_app(eval_result=eval_result)
        ctx, result = _ctx()

        await app._deliver_response(ctx, result)

        publish = app._autonomy.event_bus.publish
        fail_calls = [
            c for c in publish.call_args_list
            if c.args and c.args[0] == "response.evaluator.fail"
        ]
        assert fail_calls == []
        app._routing_feedback.record_model_use.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_block_response_delivery(self):
        eval_result = EvaluationResult(overall=2.0, verdict="fail", issues=["bad"])
        app = _make_app(eval_result=eval_result)
        # Make publish raise — note that _deliver_response also publishes
        # message.processed, so we only fail the evaluator.fail one.
        original_publish = app._autonomy.event_bus.publish

        def _selective_raise(event_type, *args, **kwargs):
            if event_type == "response.evaluator.fail":
                raise RuntimeError("event bus down")
            return MagicMock()

        app._autonomy.event_bus.publish = MagicMock(side_effect=_selective_raise)
        ctx, result = _ctx()

        # Must not raise — full response pipeline must complete.
        await app._deliver_response(ctx, result)

        # Send was still called
        app._send_response.assert_awaited_once()
        # Routing feedback still recorded (independent try/except)
        app._routing_feedback.record_model_use.assert_called_once()
        # Audit log still ran
        app._security.log_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_routing_feedback_failure_does_not_block_response_delivery(self):
        eval_result = EvaluationResult(overall=2.0, verdict="fail", issues=["bad"])
        app = _make_app(eval_result=eval_result)
        app._routing_feedback.record_model_use.side_effect = RuntimeError("db down")
        ctx, result = _ctx()

        # Must not raise.
        await app._deliver_response(ctx, result)

        app._send_response.assert_awaited_once()
        # Publish still fired (independent try/except)
        publish = app._autonomy.event_bus.publish
        fail_calls = [
            c for c in publish.call_args_list
            if c.args and c.args[0] == "response.evaluator.fail"
        ]
        assert len(fail_calls) == 1


class TestResponseEvaluatorEnabledFlag:
    """Issue #1565 — operator opt-out for ResponseEvaluator.

    The gate sits in ``BridgeApp._deliver_response``. When
    ``config.response_evaluator_enabled`` is False, ``evaluator.evaluate``
    must NOT be called — no model call, no fail event, no routing-feedback
    signal. Default is True, preserving pre-#1565 behaviour.
    """

    @pytest.mark.asyncio
    async def test_default_on_invokes_evaluator(self):
        """Default ``response_evaluator_enabled=True`` keeps the existing
        behaviour: evaluator.evaluate IS called on every response."""
        eval_result = EvaluationResult(overall=8.0, verdict="pass", issues=[])
        app = _make_app(eval_result=eval_result)
        # Default flag = True (the MagicMock auto-spawns truthy attrs, but
        # we set it explicitly here to make the test self-documenting).
        app._config = MagicMock(few_shot_enabled=True, response_evaluator_enabled=True)
        ctx, result = _ctx()

        await app._deliver_response(ctx, result)

        app._evaluator.evaluate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_explicit_off_skips_evaluator_call(self):
        """``response_evaluator_enabled=False`` skips evaluator.evaluate
        entirely — the operator opt-out path."""
        eval_result = EvaluationResult(overall=2.0, verdict="fail", issues=["bad"])
        app = _make_app(eval_result=eval_result)
        app._config = MagicMock(few_shot_enabled=True, response_evaluator_enabled=False)
        ctx, result = _ctx()

        await app._deliver_response(ctx, result)

        # No evaluator call — operator opted out
        app._evaluator.evaluate.assert_not_called()
        # No fail event published (because no verdict)
        publish = app._autonomy.event_bus.publish
        fail_calls = [
            c for c in publish.call_args_list
            if c.args and c.args[0] == "response.evaluator.fail"
        ]
        assert fail_calls == []
        # No routing-feedback failure signal (because no verdict)
        app._routing_feedback.record_model_use.assert_not_called()
        # Response delivery still completes
        app._send_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_explicit_off_saves_evaluator_cost(self):
        """When the flag is off, the evaluator is not called even if it
        WOULD have produced a fail verdict — the per-response model call
        cost is saved entirely."""
        eval_result = EvaluationResult(overall=2.0, verdict="fail", issues=["bad"])
        app = _make_app(eval_result=eval_result)
        app._config = MagicMock(few_shot_enabled=True, response_evaluator_enabled=False)
        ctx, result = _ctx()

        await app._deliver_response(ctx, result)

        # Cost-saved assertion: evaluator (which would trigger a model
        # call internally) is never invoked.
        assert app._evaluator.evaluate.call_count == 0
