"""Department tool handlers for VAPI voice function calls.

Read-only operational tools are wired here with dependency-injected providers.
Tools that still need write access or external execution continue to return a
capability-gated ``not_wired`` payload so an operator on VAPI never sees a
fabricated success.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

Provider = Callable[[], dict[str, Any] | Awaitable[dict[str, Any]]]
ToolProvider = Callable[
    [dict[str, Any]],
    dict[str, Any] | Awaitable[dict[str, Any]],
]
_AGENT_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _AGENT_ROOT.parent
_WARM_CORE_MCP = _AGENT_ROOT / "config" / "warm-core-mcp.json"
_CANONICAL_MCP = _AGENT_ROOT / "config" / "mcp-servers.canonical.json"
_LEGACY_NESTED_MARKER = "agent-flat/agent/mcp-servers"
_DEFAULT_TOOL_TIMEOUT_SECONDS = 60.0
_MAX_CAPTURE_CHARS = 4000
_TEST_LANES = frozenset({"fast", "offline", "socket", "readiness"})
_GH_ENV_PREFIX = [
    "env",
    "-u",
    "GITHUB_TOKEN",
    "-u",
    "GITHUB_PERSONAL_ACCESS_TOKEN",
    "-u",
    "MCP_GITHUB_TOKEN",
]


# Capability metadata for every advertised department-tool function.
#
# Each entry advertises:
#   - status:       whether the handler is live or still gated.
#   - owner_issue:  stable identifier for a follow-up sprint when gated.
#   - backend:      the system the handler calls into or will call into.
#
# Adding a new tool: add the handler method on DepartmentToolHandler, add
# a ToolSpec entry to bridge.voice.vapi_tool_registry.VAPI_TOOLS, and add
# the matching capability entry here. The drift tests in
# tests/test_vapi_route_registry.py will fail until all three are present.
TOOL_CAPABILITIES: dict[str, dict[str, object]] = {
    "get_pr_status": {
        "status": "implemented",
        "owner_issue": "",
        "backend": "github",
    },
    "run_tests": {
        "status": "implemented",
        "owner_issue": "",
        "backend": "pytest",
    },
    "check_mcp_health": {
        "status": "implemented",
        "owner_issue": "",
        "backend": "mcp_monitor",
    },
    "get_system_status": {
        "status": "implemented",
        "owner_issue": "",
        "backend": "health",
    },
    "list_active_sessions": {
        "status": "implemented",
        "owner_issue": "",
        "backend": "chief_session_store",
    },
}


def _capability_response(tool_name: str, department: str) -> dict[str, Any]:
    """Build a capability-gated not_wired payload for a known tool.

    Includes ``success=False`` (so callers can distinguish stub responses
    from real failures), the capability metadata from
    :data:`TOOL_CAPABILITIES`, and the calling ``department`` so operator
    traces show which assistant attempted the call.
    """
    capability = TOOL_CAPABILITIES[tool_name]
    return {
        "success": False,
        "status": capability["status"],
        "owner_issue": capability["owner_issue"],
        "backend": capability["backend"],
        "department": department,
        "tool": tool_name,
        "message": (
            f"VAPI tool {tool_name!r} is not wired; follow-up: "
            f"{capability['owner_issue']} (backend: {capability['backend']})."
        ),
    }


async def _call_provider(provider: Provider) -> dict[str, Any]:
    """Call a sync or async provider and return its dict payload."""
    result = provider()
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        raise TypeError(f"provider returned {type(result).__name__}, expected dict")
    return result


async def _call_tool_provider(
    provider: ToolProvider,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Call a sync or async provider that accepts tool arguments."""
    result = provider(args)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        raise TypeError(f"provider returned {type(result).__name__}, expected dict")
    return result


def _truncate(text: str, max_chars: int = _MAX_CAPTURE_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...[truncated {len(text) - max_chars} chars]"


def _decode_output(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


async def _run_fixed_command(
    argv: list[str],
    *,
    cwd: Path,
    timeout_seconds: float = _DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run one fixed command with bounded output and timeout."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(
            f"command timed out after {timeout_seconds:.0f}s: {' '.join(argv)}"
        ) from None

    stdout = _truncate(_decode_output(stdout_b))
    stderr = _truncate(_decode_output(stderr_b))
    return {
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "command": argv,
    }


def _coerce_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


async def _default_pr_status_provider(args: dict[str, Any]) -> dict[str, Any]:
    """Read PR status through the GitHub CLI using fixed argument shapes."""
    if not args:
        raise ValueError("get_pr_status requires {'pr': <number>} or {'scope': 'open'}")
    if shutil.which("gh") is None:
        raise FileNotFoundError("gh CLI not found")

    pr_number = args.get("pr") or args.get("number") or args.get("pull_request")
    if pr_number is not None:
        number = _coerce_int(pr_number, default=0, minimum=0, maximum=999999)
        if number <= 0:
            raise ValueError("pr must be a positive integer")
        argv = [
            *_GH_ENV_PREFIX,
            "gh",
            "pr",
            "view",
            str(number),
            "--json",
            "number,title,state,mergeStateStatus,url,headRefName",
        ]
    else:
        scope = str(args.get("scope") or "").strip().lower()
        if scope != "open":
            raise ValueError("get_pr_status scope must be 'open' when pr is omitted")
        limit = _coerce_int(args.get("limit"), default=5, minimum=1, maximum=20)
        argv = [
            *_GH_ENV_PREFIX,
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,state,mergeStateStatus,url,headRefName",
        ]

    result = await _run_fixed_command(argv, cwd=_REPO_ROOT, timeout_seconds=20.0)
    parsed: Any = None
    if result["stdout"]:
        try:
            parsed = json.loads(result["stdout"])
        except json.JSONDecodeError:
            parsed = None
    return {
        "status": "ok" if result["exit_code"] == 0 else "failed",
        "github": parsed,
        **result,
    }


def _test_lane_command(lane: str) -> tuple[list[str], Path]:
    if lane == "fast":
        return ([str(_REPO_ROOT / "scripts" / "local-ci.sh"), "--fast"], _REPO_ROOT)
    if lane == "offline":
        return (["make", "test"], _REPO_ROOT)
    if lane == "socket":
        return (["make", "test-socket"], _REPO_ROOT)
    if lane == "readiness":
        return (["make", "readiness-strict"], _REPO_ROOT)
    raise ValueError(f"unsupported test lane: {lane}")


async def _default_test_runner_provider(args: dict[str, Any]) -> dict[str, Any]:
    lane = str(args.get("lane") or "").strip().lower()
    argv, cwd = _test_lane_command(lane)
    result = await _run_fixed_command(
        argv,
        cwd=cwd,
        timeout_seconds=300.0 if lane == "readiness" else 180.0,
    )
    return {
        "status": "passed" if result["exit_code"] == 0 else "failed",
        "lane": lane,
        **result,
    }


async def _default_active_sessions_provider(args: dict[str, Any]) -> dict[str, Any]:
    raise FileNotFoundError("chief session store provider not configured")


def _load_mcp_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_mcp_health_snapshot() -> dict[str, Any]:
    """Read canonical MCP config files without spawning shell commands."""
    checks: dict[str, bool] = {
        "warm_config_exists": _WARM_CORE_MCP.is_file(),
        "canonical_config_exists": _CANONICAL_MCP.is_file(),
        "bumba_memory_configured": False,
        "bumba_memory_uses_src_entrypoint": False,
        "no_legacy_nested_path": False,
        "matches_canonical_args": False,
    }
    warm_args: list[str] = []
    canonical_args: list[str] = []

    if checks["warm_config_exists"]:
        warm = _load_mcp_json(_WARM_CORE_MCP)
        bumba_memory = (warm.get("mcpServers") or {}).get("bumba-memory") or {}
        raw_args = bumba_memory.get("args") or []
        warm_args = [str(arg) for arg in raw_args]
        checks["bumba_memory_configured"] = bool(bumba_memory)
        checks["bumba_memory_uses_src_entrypoint"] = any(
            arg.endswith("/bumba-memory/src/mcp-server.js")
            for arg in warm_args
        )
        checks["no_legacy_nested_path"] = _LEGACY_NESTED_MARKER not in json.dumps(
            bumba_memory,
            sort_keys=True,
        )

    if checks["canonical_config_exists"]:
        canonical = _load_mcp_json(_CANONICAL_MCP)
        canonical_memory = (
            (canonical.get("mcpServers") or {}).get("bumba-memory") or {}
        )
        canonical_args = [str(arg) for arg in canonical_memory.get("args") or []]

    checks["matches_canonical_args"] = bool(warm_args) and warm_args == canonical_args
    healthy = all(checks.values())
    return {
        "status": "ok" if healthy else "degraded",
        "healthy": healthy,
        "checks": checks,
        "warm_bumba_memory_args": warm_args,
        "canonical_bumba_memory_args": canonical_args,
    }


class DepartmentToolHandler:
    """Dispatches tool calls to the appropriate department handler.

    Read-only handlers return real data from injected providers. Remaining
    handlers return the capability-gated ``not_wired`` payload defined by
    :data:`TOOL_CAPABILITIES`.
    """

    def __init__(
        self,
        *,
        health_provider: Provider | None = None,
        mcp_health_provider: Provider | None = None,
        pr_status_provider: ToolProvider | None = None,
        test_runner_provider: ToolProvider | None = None,
        active_sessions_provider: ToolProvider | None = None,
    ) -> None:
        self._health_provider = health_provider
        self._mcp_health_provider = (
            mcp_health_provider or _default_mcp_health_snapshot
        )
        self._pr_status_provider = (
            pr_status_provider or _default_pr_status_provider
        )
        self._test_runner_provider = (
            test_runner_provider or _default_test_runner_provider
        )
        self._active_sessions_provider = (
            active_sessions_provider or _default_active_sessions_provider
        )

    async def handle_tool_call(
        self, department: str, tool_name: str, args: dict
    ) -> dict:
        """Route a tool call to the correct handler."""
        handler_name = f"_handle_{tool_name}"
        handler = getattr(self, handler_name, None)

        if handler is None:
            logger.warning("Unknown tool: %s (department=%s)", tool_name, department)
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}",
                "department": department,
            }

        logger.info("Handling tool call: %s.%s", department, tool_name)
        return await handler(department, args)

    async def _handle_get_pr_status(self, department: str, args: dict) -> dict:
        return await self._run_provider_tool(
            "get_pr_status",
            department,
            args,
            self._pr_status_provider,
        )

    async def _handle_run_tests(self, department: str, args: dict) -> dict:
        lane = str(args.get("lane") or "").strip().lower()
        if lane not in _TEST_LANES:
            return {
                "success": False,
                "status": "invalid_request",
                "backend": "pytest",
                "department": department,
                "tool": "run_tests",
                "error": (
                    "run_tests requires lane to be one of: "
                    + ", ".join(sorted(_TEST_LANES))
                ),
            }
        return await self._run_provider_tool(
            "run_tests",
            department,
            {**args, "lane": lane},
            self._test_runner_provider,
        )

    async def _handle_check_mcp_health(self, department: str, args: dict) -> dict:
        try:
            snapshot = await _call_provider(self._mcp_health_provider)
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "status": "error",
                "backend": "mcp_monitor",
                "department": department,
                "tool": "check_mcp_health",
                "error": str(exc),
            }

        status = str(snapshot.get("status") or "unknown")
        healthy = bool(snapshot.get("healthy", status in {"ok", "healthy", "up"}))
        return {
            "success": True,
            "status": status,
            "healthy": healthy,
            "backend": "mcp_monitor",
            "department": department,
            "tool": "check_mcp_health",
            "snapshot": snapshot,
        }

    async def _handle_get_system_status(self, department: str, args: dict) -> dict:
        if self._health_provider is None:
            return {
                "success": True,
                "status": "unavailable",
                "healthy": False,
                "backend": "health",
                "department": department,
                "tool": "get_system_status",
                "message": "Health provider not available in this process.",
            }
        try:
            snapshot = await _call_provider(self._health_provider)
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "status": "error",
                "backend": "health",
                "department": department,
                "tool": "get_system_status",
                "error": str(exc),
            }

        status = str(snapshot.get("status") or "unknown")
        components = snapshot.get("components") or {}
        component_status = {
            name: value.get("status")
            for name, value in components.items()
            if isinstance(value, dict) and "status" in value
        }
        return {
            "success": True,
            "status": status,
            "healthy": status == "healthy",
            "backend": "health",
            "department": department,
            "tool": "get_system_status",
            "uptime_seconds": snapshot.get("uptime_seconds"),
            "version": snapshot.get("version"),
            "components": component_status,
        }

    async def _handle_list_active_sessions(self, department: str, args: dict) -> dict:
        return await self._run_provider_tool(
            "list_active_sessions",
            department,
            args,
            self._active_sessions_provider,
        )

    async def _run_provider_tool(
        self,
        tool_name: str,
        department: str,
        args: dict[str, Any],
        provider: ToolProvider,
    ) -> dict[str, Any]:
        capability = TOOL_CAPABILITIES[tool_name]
        backend = str(capability["backend"])
        try:
            payload = await _call_tool_provider(provider, args)
        except ValueError as exc:
            return {
                "success": False,
                "status": "invalid_request",
                "backend": backend,
                "department": department,
                "tool": tool_name,
                "error": str(exc),
            }
        except TimeoutError as exc:
            return {
                "success": False,
                "status": "timeout",
                "backend": backend,
                "department": department,
                "tool": tool_name,
                "error": str(exc),
            }
        except FileNotFoundError as exc:
            return {
                "success": False,
                "status": "unavailable",
                "backend": backend,
                "department": department,
                "tool": tool_name,
                "error": str(exc),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "status": "error",
                "backend": backend,
                "department": department,
                "tool": tool_name,
                "error": str(exc),
            }

        success = bool(payload.get("success", True))
        status = str(payload.get("status") or ("ok" if success else "error"))
        result = {
            "success": success,
            "status": status,
            "backend": backend,
            "department": department,
            "tool": tool_name,
        }
        result.update(payload)
        result["success"] = success
        result["status"] = status
        result["backend"] = backend
        result["department"] = department
        result["tool"] = tool_name
        return result
