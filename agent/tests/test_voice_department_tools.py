"""Tests guarding VAPI department-tool behavior."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

# Import the module under test (sys.path pattern from tests/test_experiment_loop.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "voice"))
import department_tools  # noqa: E402


HANDLER_PREFIX = "_handle_"
IMPLEMENTED_HANDLERS = {
    "_handle_check_mcp_health",
    "_handle_get_pr_status",
    "_handle_get_system_status",
    "_handle_list_active_sessions",
    "_handle_run_tests",
}


def _discover_handlers() -> list[str]:
    handler = department_tools.DepartmentToolHandler()
    return [
        name
        for name in dir(handler)
        if name.startswith(HANDLER_PREFIX) and callable(getattr(handler, name))
    ]


def _call_handler(handler_name: str) -> dict:
    handler = department_tools.DepartmentToolHandler()
    coro = getattr(handler, handler_name)("engineering", {})
    return asyncio.run(coro)


def test_unimplemented_handlers_return_not_wired():
    """Unimplemented tools keep the loud not_wired payload."""
    handlers = _discover_handlers()
    assert handlers, "expected at least one _handle_* method on DepartmentToolHandler"

    for handler_name in handlers:
        if handler_name in IMPLEMENTED_HANDLERS:
            continue
        result = _call_handler(handler_name)
        assert result["success"] is False, f"{handler_name} returned success != False: {result}"
        assert result["status"] == "not_wired", (
            f"{handler_name} returned status != 'not_wired': {result}"
        )
        assert "owner_issue" in result, f"{handler_name} missing owner_issue: {result}"


def test_get_system_status_returns_injected_health_snapshot():
    async def health_provider():
        return {
            "status": "healthy",
            "uptime_seconds": 42,
            "version": "test-version",
            "components": {
                "discord": {"status": "up"},
                "token": {"status": "up"},
            },
        }

    handler = department_tools.DepartmentToolHandler(
        health_provider=health_provider
    )
    result = asyncio.run(
        handler.handle_tool_call("ops", "get_system_status", {})
    )

    assert result["success"] is True
    assert result["status"] == "healthy"
    assert result["healthy"] is True
    assert result["uptime_seconds"] == 42
    assert result["components"] == {"discord": "up", "token": "up"}


def test_check_mcp_health_returns_injected_snapshot():
    handler = department_tools.DepartmentToolHandler(
        mcp_health_provider=lambda: {
            "status": "ok",
            "healthy": True,
            "summary": {"running": 4, "crash_loop": 0},
        }
    )

    result = asyncio.run(
        handler.handle_tool_call("ops", "check_mcp_health", {})
    )

    assert result["success"] is True
    assert result["status"] == "ok"
    assert result["healthy"] is True
    assert result["snapshot"]["summary"]["running"] == 4


def test_get_pr_status_returns_injected_snapshot():
    async def pr_provider(args):
        assert args == {"pr": 2410}
        return {
            "status": "ok",
            "pull_request": {"number": 2410, "state": "OPEN"},
        }

    handler = department_tools.DepartmentToolHandler(
        pr_status_provider=pr_provider
    )
    result = asyncio.run(
        handler.handle_tool_call("engineering", "get_pr_status", {"pr": 2410})
    )

    assert result["success"] is True
    assert result["status"] == "ok"
    assert result["backend"] == "github"
    assert result["pull_request"]["number"] == 2410


def test_default_pr_status_provider_unsets_github_token_env(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_run_fixed_command(argv, *, cwd, timeout_seconds):
        captured["argv"] = argv
        captured["cwd"] = cwd
        captured["timeout_seconds"] = timeout_seconds
        return {
            "exit_code": 0,
            "stdout": '{"number": 2411}',
            "stderr": "",
            "command": argv,
        }

    monkeypatch.setattr(department_tools.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(
        department_tools,
        "_run_fixed_command",
        fake_run_fixed_command,
    )

    result = asyncio.run(
        department_tools._default_pr_status_provider({"pr": 2411})
    )

    assert result["status"] == "ok"
    assert captured["argv"][:7] == [
        "env",
        "-u",
        "GITHUB_TOKEN",
        "-u",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "-u",
        "MCP_GITHUB_TOKEN",
    ]
    assert captured["argv"][7:10] == ["gh", "pr", "view"]


def test_run_tests_rejects_missing_lane_without_running_default_command():
    result = asyncio.run(
        department_tools.DepartmentToolHandler().handle_tool_call(
            "qa", "run_tests", {}
        )
    )

    assert result["success"] is False
    assert result["status"] == "invalid_request"
    assert "lane" in result["error"]


def test_run_tests_returns_injected_snapshot_for_approved_lane():
    async def test_provider(args):
        assert args == {"lane": "fast"}
        return {
            "status": "passed",
            "lane": "fast",
            "exit_code": 0,
        }

    handler = department_tools.DepartmentToolHandler(
        test_runner_provider=test_provider
    )
    result = asyncio.run(
        handler.handle_tool_call("qa", "run_tests", {"lane": "fast"})
    )

    assert result["success"] is True
    assert result["status"] == "passed"
    assert result["backend"] == "pytest"
    assert result["lane"] == "fast"


def test_list_active_sessions_returns_injected_snapshot():
    async def sessions_provider(args):
        assert args == {"limit": 2}
        return {
            "status": "ok",
            "count": 1,
            "sessions": [{"session_id": "cs-123", "department": "ops"}],
        }

    handler = department_tools.DepartmentToolHandler(
        active_sessions_provider=sessions_provider
    )
    result = asyncio.run(
        handler.handle_tool_call("ops", "list_active_sessions", {"limit": 2})
    )

    assert result["success"] is True
    assert result["status"] == "ok"
    assert result["backend"] == "chief_session_store"
    assert result["sessions"][0]["session_id"] == "cs-123"


@pytest.mark.parametrize(
    ("tool_name", "provider_kw", "backend"),
    [
        ("get_pr_status", "pr_status_provider", "github"),
        ("run_tests", "test_runner_provider", "pytest"),
        ("list_active_sessions", "active_sessions_provider", "chief_session_store"),
    ],
)
@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (TimeoutError("timed out"), "timeout"),
        (FileNotFoundError("missing dependency"), "unavailable"),
        (RuntimeError("boom"), "error"),
    ],
)
def test_implemented_tool_provider_failures_are_shaped(
    tool_name,
    provider_kw,
    backend,
    exc,
    status,
):
    async def provider(args):
        raise exc

    handler = department_tools.DepartmentToolHandler(**{provider_kw: provider})
    result = asyncio.run(
        handler.handle_tool_call("engineering", tool_name, {"lane": "fast"})
    )

    assert result["success"] is False
    assert result["status"] == status
    assert result["backend"] == backend
    assert result["tool"] == tool_name
    assert str(exc) in result["error"]


def test_check_mcp_health_default_rejects_legacy_nested_path():
    result = asyncio.run(
        department_tools.DepartmentToolHandler().handle_tool_call(
            "ops", "check_mcp_health", {}
        )
    )

    assert result["success"] is True
    checks = result["snapshot"]["checks"]
    assert checks["no_legacy_nested_path"] is True
    assert checks["bumba_memory_uses_src_entrypoint"] is True


def test_voice_enabled_true_cannot_surface_fabricated_all_green_payload():
    """No fabricated success strings may appear in any handler response."""
    fabricated = (
        "approved",
        "23 healthy",
        "582 passed",
        "green",
        "stub-session-001",
    )

    handlers = _discover_handlers()
    assert handlers, "expected at least one _handle_* method on DepartmentToolHandler"

    for handler_name in handlers:
        result = _call_handler(handler_name)
        serialized = json.dumps(result)
        for token in fabricated:
            assert token not in serialized, (
                f"{handler_name} surfaced fabricated token {token!r}: {serialized}"
            )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
