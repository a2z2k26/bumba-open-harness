"""Unit tests for the pure verdict logic in
``scripts/verify_e2b_sandbox_live.py``.

The script's I/O (spawning a warm process, hitting a real E2B sandbox) is not
unit-testable, but the PASS/FAIL decision is a pure function — ``evaluate_run``.
These tests pin its contract: a run only PASSES when the bumba-sandbox tools
were called for the full init/exec/kill lifecycle, the output has "4", and there
is no host-Bash fallback.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "verify_e2b_sandbox_live.py"
)
_spec = importlib.util.spec_from_file_location("verify_e2b_sandbox_live", _SCRIPT)
assert _spec and _spec.loader
verify = importlib.util.module_from_spec(_spec)
# Register before exec so the module's frozen dataclass can resolve its own
# field types (dataclasses looks the module up in sys.modules by __module__).
sys.modules["verify_e2b_sandbox_live"] = verify
_spec.loader.exec_module(verify)


_FULL_TOOLS = [
    "mcp__bumba-sandbox__sandbox_init",
    "mcp__bumba-sandbox__execute_command",
    "mcp__bumba-sandbox__sandbox_kill",
]


def test_full_lifecycle_with_four_passes():
    v = verify.evaluate_run(
        tools_used=_FULL_TOOLS,
        response_text="The command printed 4 inside the sandbox.",
        is_error=False,
    )
    assert v.passed
    assert v.called_init and v.called_execute and v.called_kill
    assert v.output_has_four
    assert not v.used_host_bash_fallback
    assert v.reasons == ()


def test_command_execute_alias_recognized():
    # The MCP exposes both execute_command and command_execute aliases.
    v = verify.evaluate_run(
        tools_used=[
            "mcp__bumba-sandbox__sandbox_create",
            "mcp__bumba-sandbox__command_execute",
            "mcp__bumba-sandbox__sandbox_kill",
        ],
        response_text="stdout: 4",
        is_error=False,
    )
    assert v.passed
    assert v.called_init  # sandbox_create counts as init
    assert v.called_execute  # command_execute alias counts as exec


def test_host_bash_fallback_fails():
    # The cold-start failure mode: '4' via host Bash, zero sandbox tools.
    v = verify.evaluate_run(
        tools_used=["Bash"],
        response_text="4",
        is_error=False,
    )
    assert not v.passed
    assert v.used_host_bash_fallback
    assert v.sandbox_tools_called == ()
    assert any("HOST BASH FALLBACK" in r for r in v.reasons)


def test_no_kill_fails_and_flags_leak():
    v = verify.evaluate_run(
        tools_used=[
            "mcp__bumba-sandbox__sandbox_init",
            "mcp__bumba-sandbox__execute_command",
        ],
        response_text="4",
        is_error=False,
    )
    assert not v.passed
    assert not v.called_kill
    assert any("kill" in r and "leak" in r for r in v.reasons)


def test_missing_four_fails():
    v = verify.evaluate_run(
        tools_used=_FULL_TOOLS,
        response_text="The sandbox ran but produced nothing useful.",
        is_error=False,
    )
    assert not v.passed
    assert not v.output_has_four
    assert any("'4'" in r for r in v.reasons)


def test_is_error_fails():
    v = verify.evaluate_run(
        tools_used=_FULL_TOOLS,
        response_text="4",
        is_error=True,
    )
    assert not v.passed
    assert any("is_error" in r for r in v.reasons)


def test_only_sandbox_tools_count_not_other_mcp():
    # A non-sandbox MCP tool must not satisfy the sandbox-tool requirement.
    v = verify.evaluate_run(
        tools_used=["mcp__bumba-memory__recall"],
        response_text="4",
        is_error=False,
    )
    assert not v.passed
    assert v.sandbox_tools_called == ()


@pytest.mark.parametrize(
    "tool,expect_init,expect_exec,expect_kill",
    [
        ("mcp__bumba-sandbox__sandbox_init", True, False, False),
        ("mcp__bumba-sandbox__sandbox_create", True, False, False),
        ("mcp__bumba-sandbox__execute_command", False, True, False),
        ("mcp__bumba-sandbox__command_execute", False, True, False),
        ("mcp__bumba-sandbox__sandbox_kill", False, False, True),
    ],
)
def test_marker_classification(tool, expect_init, expect_exec, expect_kill):
    v = verify.evaluate_run(tools_used=[tool], response_text="4", is_error=False)
    assert v.called_init is expect_init
    assert v.called_execute is expect_exec
    assert v.called_kill is expect_kill
