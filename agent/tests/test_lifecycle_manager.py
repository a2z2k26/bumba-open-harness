"""Fail-loud guards for WorkLifecycleManager stub surfaces."""

from __future__ import annotations

import pytest

from bridge.lifecycle_manager import (
    EXPERIMENTAL_USE_ACK,
    PipelineStage,
    WorkLifecycleManager,
)
from bridge.work_order import WorkOrder


def _work_order() -> WorkOrder:
    return WorkOrder.create(intent="build the feature", skill="@engineering", project="p")


def _lifecycle(**kwargs: object) -> WorkLifecycleManager:
    return WorkLifecycleManager(experimental_ack=EXPERIMENTAL_USE_ACK, **kwargs)


def test_constructor_requires_experimental_ack() -> None:
    with pytest.raises(RuntimeError, match="experimental"):
        WorkLifecycleManager()


def test_execute_work_without_executor_fails_loud() -> None:
    lifecycle = _lifecycle()
    assigned = lifecycle.assign(_work_order())

    with pytest.raises(NotImplementedError, match="executor"):
        lifecycle.execute_work(assigned)


def test_verify_without_verifier_fails_loud() -> None:
    lifecycle = _lifecycle()

    with pytest.raises(NotImplementedError, match="verifier"):
        lifecycle.verify(_work_order(), {"result": "fabricated"})


def test_execute_reports_failed_result_when_executor_is_unwired() -> None:
    lifecycle = _lifecycle()

    result = lifecycle.execute(_work_order())

    assert result.status == "failed"
    assert result.stage == PipelineStage.EXECUTE
    assert result.error is not None
    assert "executor" in result.error


def test_execute_completes_when_executor_and_verifier_are_injected() -> None:
    lifecycle = _lifecycle(
        executor=lambda work_order: {
            "result": f"completed {work_order.intent}",
            "confidence": 0.9,
            "work_order_id": work_order.id,
        },
        verifier=lambda _work_order, _output: True,
    )

    result = lifecycle.execute(_work_order())

    assert result.status == "completed"
    assert result.stage == PipelineStage.SYNTHESIZE
    assert result.output == {
        "result": "completed build the feature",
        "confidence": 0.9,
        "source_count": 1,
    }
