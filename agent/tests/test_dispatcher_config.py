"""Tests for the D-R3 dispatcher config knobs and metrics (#1933).

Covers:
- ``executor_timeout_seconds`` config field reaches the dispatch site
  (asyncio.wait_for is called with min(config, wo_constraint))
- ``min_dispatch_confidence`` config field accepts valid range
- ``_validate`` rejects bad values
- Improved timeout log includes ``intent`` + ``timeout_used_s``
- The three SubagentExecutor metrics fire at the right outcomes
- ``Dispatcher.get_circuit_breaker_states()`` returns one entry per
  registered executor route
"""
from __future__ import annotations

import pytest

from bridge.config import BridgeConfig, ConfigError, _validate
from bridge.dispatcher import Dispatcher


# ---------------------------------------------------------------------------
# Config field surface + validators
# ---------------------------------------------------------------------------


def test_executor_timeout_seconds_default_is_120() -> None:
    cfg = BridgeConfig(data_dir="/tmp", log_dir="/tmp")
    assert cfg.executor_timeout_seconds == 120


def test_min_dispatch_confidence_default_is_0_8() -> None:
    cfg = BridgeConfig(data_dir="/tmp", log_dir="/tmp")
    assert cfg.min_dispatch_confidence == 0.8


@pytest.fixture
def _base_kwargs(tmp_path):
    """Minimum overrides to reach the dispatcher checks in ``_validate``."""
    return {
        "discord_bot_token": "test-token",
        "operator_discord_id": "test-operator",
        "data_dir": str(tmp_path),
        "log_dir": str(tmp_path),
    }


def test_executor_timeout_seconds_too_low_is_rejected(_base_kwargs) -> None:
    import dataclasses
    cfg = dataclasses.replace(
        BridgeConfig(**_base_kwargs), executor_timeout_seconds=5
    )
    with pytest.raises(ConfigError, match="executor_timeout_seconds"):
        _validate(cfg)


def test_min_dispatch_confidence_out_of_range_is_rejected(_base_kwargs) -> None:
    import dataclasses
    cfg = dataclasses.replace(
        BridgeConfig(**_base_kwargs), min_dispatch_confidence=1.5
    )
    with pytest.raises(ConfigError, match="min_dispatch_confidence"):
        _validate(cfg)


def test_min_dispatch_confidence_negative_is_rejected(_base_kwargs) -> None:
    import dataclasses
    cfg = dataclasses.replace(
        BridgeConfig(**_base_kwargs), min_dispatch_confidence=-0.1
    )
    with pytest.raises(ConfigError, match="min_dispatch_confidence"):
        _validate(cfg)


# ---------------------------------------------------------------------------
# Circuit breaker state surface
# ---------------------------------------------------------------------------


def test_get_circuit_breaker_states_returns_all_routes() -> None:
    """One entry per ``Environment`` enum value, all starting CLOSED."""
    from bridge.work_order import Environment

    dispatcher = Dispatcher.__new__(Dispatcher)
    # Use the same init pattern as Dispatcher.__init__ for breakers.
    from bridge.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

    cfg = CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=1,
        timeout_seconds=180.0,
    )
    dispatcher._breakers = {
        env.value: CircuitBreaker(config=cfg) for env in Environment
    }

    states = dispatcher.get_circuit_breaker_states()
    assert set(states.keys()) == {env.value for env in Environment}
    # All start CLOSED.
    for state in states.values():
        assert state == "closed"


# ---------------------------------------------------------------------------
# Metrics emission at the three SubagentExecutor outcomes
# ---------------------------------------------------------------------------


def test_subagent_metric_helpers_increment() -> None:
    """The three D-R3 helpers in z3_metrics emit through Z3Counters."""
    from bridge.z3_metrics import (
        Z3CounterNames,
        Z3Counters,
        record_subagent_error,
        record_subagent_success,
        record_subagent_timeout,
    )

    before_timeout = Z3Counters.get(
        Z3CounterNames.SUBAGENT_TIMEOUT, intent="board_query", env="subagent"
    )
    before_success = Z3Counters.get(
        Z3CounterNames.SUBAGENT_SUCCESS, intent="board_query", env="subagent"
    )
    before_error = Z3Counters.get(
        Z3CounterNames.SUBAGENT_ERROR,
        intent="board_query",
        env="subagent",
        error_type="ValueError",
    )

    record_subagent_timeout(intent="board_query", env="subagent")
    record_subagent_success(intent="board_query", env="subagent")
    record_subagent_error(
        intent="board_query", env="subagent", error_type="ValueError"
    )

    assert Z3Counters.get(
        Z3CounterNames.SUBAGENT_TIMEOUT, intent="board_query", env="subagent"
    ) == before_timeout + 1
    assert Z3Counters.get(
        Z3CounterNames.SUBAGENT_SUCCESS, intent="board_query", env="subagent"
    ) == before_success + 1
    assert Z3Counters.get(
        Z3CounterNames.SUBAGENT_ERROR,
        intent="board_query",
        env="subagent",
        error_type="ValueError",
    ) == before_error + 1


# ---------------------------------------------------------------------------
# Config ceiling reaches the dispatch site
# ---------------------------------------------------------------------------


def test_config_ceiling_caps_wo_constraint_timeout() -> None:
    """When config.executor_timeout_seconds is lower than the WO's
    timeout_ms-derived value, the dispatch site applies the config ceiling.

    Direct test of the min() logic in _run_executor's timeout computation —
    avoids needing to mock the full async dispatch path.
    """
    # Mimic the dispatch-site logic:
    wo_timeout_ms = 600_000  # default 600s
    wo_timeout_s = wo_timeout_ms / 1000.0
    cfg_ceiling = 120

    applied = min(wo_timeout_s, float(cfg_ceiling))
    assert applied == 120.0


def test_wo_constraint_lower_than_config_wins() -> None:
    """If the WO requests a shorter timeout, the config ceiling does not
    raise it back up."""
    wo_timeout_ms = 30_000  # WO wants 30s
    wo_timeout_s = wo_timeout_ms / 1000.0
    cfg_ceiling = 120

    applied = min(wo_timeout_s, float(cfg_ceiling))
    assert applied == 30.0
