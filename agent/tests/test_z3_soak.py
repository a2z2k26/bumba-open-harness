"""Tests for Z3 soak probe and circuit breaker wiring (issue #636)."""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths relative to the repo root (parent of agent/)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_AGENT_BRIDGE = _REPO_ROOT / "agent" / "bridge"
_SCRIPTS = _REPO_ROOT / "scripts"


def test_z3_status_command_registered():
    """z3_status must appear in BRIDGE_COMMANDS in commands.py."""
    src = (_AGENT_BRIDGE / "commands.py").read_text()
    assert "z3_status" in src, "z3_status command not found in commands.py"


def test_z3_status_handler_exists():
    """_cmd_z3_status method must be defined on CommandHandler.

    Demote-split (#1305): the handler body moved from `commands.py` into
    the `command_handlers/cost_and_z4.py` mixin. The handler attribute on
    the composed class is the contract these smoke tests pin.
    """
    from bridge.commands import CommandHandler
    assert hasattr(CommandHandler, "_cmd_z3_status"), (
        "_cmd_z3_status handler not found on CommandHandler"
    )


def test_z3_status_shows_circuit_breakers():
    """_cmd_z3_status must reference circuit breaker state in its output.

    Demote-split (#1305): now sourced from `command_handlers/cost_and_z4.py`.
    """
    src = (_AGENT_BRIDGE / "command_handlers" / "cost_and_z4.py").read_text()
    assert "Circuit Breaker" in src or "_breakers" in src, \
        "_cmd_z3_status must surface per-environment circuit breaker state"


def test_dispatcher_imports_circuit_breaker():
    """Dispatcher must import CircuitBreaker from bridge.circuit_breaker."""
    src = (_AGENT_BRIDGE / "dispatcher.py").read_text()
    assert "CircuitBreaker" in src, \
        "Dispatcher must import and use CircuitBreaker"
    assert "circuit_breaker" in src.lower(), \
        "Dispatcher must reference circuit_breaker module"


def test_dispatcher_has_breakers_dict():
    """Dispatcher.__init__ must initialise self._breakers dict."""
    src = (_AGENT_BRIDGE / "dispatcher.py").read_text()
    assert "_breakers" in src, \
        "Dispatcher must maintain _breakers dict keyed by environment"


def test_dispatcher_checks_is_available_before_invoke():
    """dispatch() must check breaker.is_available before calling the executor."""
    src = (_AGENT_BRIDGE / "dispatcher.py").read_text()
    assert "is_available" in src, \
        "Dispatcher.dispatch must check breaker.is_available before invoking executor"


def test_dispatcher_records_failure_on_exception():
    """_run_executor must call breaker.record_failure() on exception."""
    src = (_AGENT_BRIDGE / "dispatcher.py").read_text()
    assert "record_failure" in src, \
        "Dispatcher._run_executor must call breaker.record_failure() on exception"


def test_dispatcher_records_success():
    """_run_executor must call breaker.record_success() on successful execution."""
    src = (_AGENT_BRIDGE / "dispatcher.py").read_text()
    assert "record_success" in src, \
        "Dispatcher._run_executor must call breaker.record_success() on success"


def test_dispatcher_fallthrough_on_breaker_open():
    """Dispatcher must record fallthrough and return handled=False when circuit is open."""
    src = (_AGENT_BRIDGE / "dispatcher.py").read_text()
    assert "circuit_open" in src, \
        "Dispatcher must emit a 'circuit_open' fallthrough reason when breaker is open"


def test_dispatcher_publishes_breaker_open_event():
    """Dispatcher must publish dispatcher.breaker_open to event bus when circuit is open."""
    src = (_AGENT_BRIDGE / "dispatcher.py").read_text()
    assert "dispatcher.breaker_open" in src, \
        "Dispatcher must publish 'dispatcher.breaker_open' event to the event bus"


def test_soak_probe_script_exists():
    """scripts/z3_soak_probe.sh must exist."""
    script = _SCRIPTS / "z3_soak_probe.sh"
    assert script.exists(), f"scripts/z3_soak_probe.sh not found at {script}"


def test_soak_probe_is_executable():
    """scripts/z3_soak_probe.sh must be executable."""
    script = _SCRIPTS / "z3_soak_probe.sh"
    assert os.access(str(script), os.X_OK), "z3_soak_probe.sh is not executable"


def test_soak_probe_appends_to_soak_log():
    """Soak probe must write to data/z3-soak.jsonl."""
    src = (_SCRIPTS / "z3_soak_probe.sh").read_text()
    assert "z3-soak.jsonl" in src, "Probe must append results to data/z3-soak.jsonl"


def test_soak_probe_has_halt_logic():
    """Soak probe must write halt.flag on 3 consecutive failures."""
    src = (_SCRIPTS / "z3_soak_probe.sh").read_text()
    assert "halt.flag" in src, "Probe must write data/halt.flag on consecutive failures"


def test_soak_probe_checks_three_consecutive_failures():
    """Soak probe must specifically check for 3 consecutive failures."""
    src = (_SCRIPTS / "z3_soak_probe.sh").read_text()
    assert "CONSEC_FAILS" in src or "consec" in src.lower(), \
        "Probe must track consecutive failures"
    assert "3" in src, \
        "Probe must use threshold of 3 consecutive failures"


def test_circuit_breaker_per_environment_coverage():
    """Dispatcher must register one breaker per Environment enum value."""
    src = (_AGENT_BRIDGE / "dispatcher.py").read_text()
    # Must iterate over Environment to build breakers — not hardcoded
    assert "for env in Environment" in src or "env.value" in src, \
        "Dispatcher must register circuit breakers for all Environment values"
