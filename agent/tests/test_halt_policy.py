"""Tests for the shared HaltPolicy contract (audit-2026-05-16.C.01).

The HaltPolicy is the keystone contract that autonomous surfaces will
consult before starting new work or continuing in-flight work. This
sprint introduces the contract only; call-site migration is deferred
to C.02-C.05.
"""

from __future__ import annotations

import pytest

from bridge.halt import HaltDecision, HaltPolicy


# -- HaltDecision dataclass shape --


def test_halt_decision_is_frozen_dataclass() -> None:
    """HaltDecision must be a frozen dataclass to prevent mutation."""
    decision = HaltDecision(blocked=False)
    with pytest.raises((AttributeError, Exception)):
        decision.blocked = True  # type: ignore[misc]


def test_halt_decision_reason_defaults_to_none() -> None:
    """An unblocked decision should not need a reason."""
    decision = HaltDecision(blocked=False)
    assert decision.blocked is False
    assert decision.reason is None


def test_halt_decision_can_carry_reason() -> None:
    """A blocked decision carries a human-readable reason."""
    decision = HaltDecision(blocked=True, reason="halt flag set")
    assert decision.blocked is True
    assert decision.reason == "halt flag set"


# -- HaltPolicy.check_start --


def test_check_start_returns_non_blocked_when_halt_absent() -> None:
    """When the global halt flag is clear, new work may start."""
    policy = HaltPolicy(
        is_halted=lambda: False,
        halt_reason=lambda: None,
    )
    decision = policy.check_start("job-search")
    assert decision.blocked is False
    assert decision.reason is None


def test_check_start_returns_blocked_when_halt_present() -> None:
    """When the global halt flag is set, new work is blocked."""
    policy = HaltPolicy(
        is_halted=lambda: True,
        halt_reason=lambda: "operator halt via /halt",
    )
    decision = policy.check_start("factory")
    assert decision.blocked is True
    assert decision.reason is not None
    # Reason must be populated so operator logs are useful.
    assert len(decision.reason) > 0


def test_check_start_reason_includes_surface() -> None:
    """The surface argument must be observable in the blocked reason."""
    policy = HaltPolicy(
        is_halted=lambda: True,
        halt_reason=lambda: "kernel hash mismatch",
    )
    decision = policy.check_start("proactive")
    assert decision.blocked is True
    assert "proactive" in (decision.reason or "")


def test_check_start_reason_includes_raw_halt_reason() -> None:
    """The underlying halt reason should propagate to operator logs."""
    policy = HaltPolicy(
        is_halted=lambda: True,
        halt_reason=lambda: "remote kill switch",
    )
    decision = policy.check_start("warm-chief")
    assert decision.blocked is True
    assert "remote kill switch" in (decision.reason or "")


def test_check_start_handles_missing_halt_reason() -> None:
    """is_halted=True with reason=None should still produce a useful message."""
    policy = HaltPolicy(
        is_halted=lambda: True,
        halt_reason=lambda: None,
    )
    decision = policy.check_start("experiment-loop")
    assert decision.blocked is True
    assert decision.reason is not None
    assert "experiment-loop" in decision.reason


# -- HaltPolicy.check_continue --


def test_check_continue_returns_non_blocked_when_halt_absent() -> None:
    """In-flight work continues when halt is clear, regardless of cancel policy."""
    policy = HaltPolicy(
        is_halted=lambda: False,
        halt_reason=lambda: None,
        cancel_in_flight=True,
    )
    decision = policy.check_continue("workflow_engine")
    assert decision.blocked is False
    assert decision.reason is None


def test_check_continue_blocks_when_halt_present_and_configured_to_cancel() -> None:
    """When cancel_in_flight=True and halt is set, in-flight work is blocked."""
    policy = HaltPolicy(
        is_halted=lambda: True,
        halt_reason=lambda: "operator halt",
        cancel_in_flight=True,
    )
    decision = policy.check_continue("warm-chief")
    assert decision.blocked is True
    assert decision.reason is not None
    assert "warm-chief" in decision.reason


def test_check_continue_does_not_block_when_cancel_disabled() -> None:
    """When cancel_in_flight=False, in-flight work may finish even on halt."""
    policy = HaltPolicy(
        is_halted=lambda: True,
        halt_reason=lambda: "operator halt",
        cancel_in_flight=False,
    )
    decision = policy.check_continue("factory")
    # check_continue should NOT block — in-flight work is allowed to finish.
    assert decision.blocked is False
    assert decision.reason is None


def test_check_continue_defaults_to_cancel_in_flight_true() -> None:
    """Fail-safe default: halt cancels in-flight work unless explicitly opted out."""
    policy = HaltPolicy(
        is_halted=lambda: True,
        halt_reason=lambda: "halt",
    )
    decision = policy.check_continue("job-search")
    assert decision.blocked is True


# -- Surface argument propagation across both methods --


@pytest.mark.parametrize(
    "surface",
    [
        "job-search",
        "factory",
        "proactive",
        "warm-chief",
        "experiment-loop",
        "workflow_engine",
    ],
)
def test_surface_is_propagated_in_reason(surface: str) -> None:
    """All canonical surfaces must round-trip through the reason string."""
    policy = HaltPolicy(
        is_halted=lambda: True,
        halt_reason=lambda: "test",
    )
    start = policy.check_start(surface)
    cont = policy.check_continue(surface)
    assert surface in (start.reason or "")
    assert surface in (cont.reason or "")


# -- Purity: no I/O, no fixtures needed --


def test_policy_does_not_call_halt_source_when_constructed() -> None:
    """Policy should be lazy — halt source is only consulted on check_*."""
    call_count = {"is_halted": 0, "halt_reason": 0}

    def is_halted() -> bool:
        call_count["is_halted"] += 1
        return False

    def halt_reason() -> str | None:
        call_count["halt_reason"] += 1
        return None

    HaltPolicy(is_halted=is_halted, halt_reason=halt_reason)
    assert call_count["is_halted"] == 0
    assert call_count["halt_reason"] == 0
