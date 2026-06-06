#!/usr/bin/env python3
"""Rigorous live verification: prove the E2B executor runs a REAL E2B sandbox
end-to-end against a WARM, already-handshaked ``bumba-sandbox`` MCP server.

WHY THIS EXISTS (and why ``scripts/diag_e2b_executor.py`` is insufficient)
==========================================================================
The standalone diag drives ``E2BExecutor.execute`` → ``ClaudeRunner.invoke``,
which is the **one-shot** Claude path. One-shot COLD-STARTS the
``bumba-sandbox`` MCP server (a node process) on every invocation. That server
does not complete its MCP handshake inside the one-shot window, so its tools
(``mcp__bumba-sandbox__sandbox_init`` / ``execute_command`` / ``sandbox_kill``)
never register — the agent falls back to host Bash and returns "4" WITHOUT a
sandbox. Confirmed across many runs: the executor is correct; the failure is
cold-start MCP-handshake timing.

The production warm path (``WarmClaudeProcess`` in ``bridge/claude_runner.py``
~L1073-1273) keeps the Claude subprocess AND its MCP servers alive across
messages: it spawns with ``--mcp-config <path> --strict-mcp-config`` and a
warmup ``"hi"`` message that blocks up to 120s for MCP init to complete
(claude_runner.py L1187-1205, L1261). Tools register during warmup; subsequent
messages hit an already-handshaked server.

APPROACH CHOSEN: OPTION A — pre-warm a WarmClaudeProcess pointed at a
``bumba-sandbox``-only MCP config (built with the SAME ``filter_mcp_config``
machinery the real E2BExecutor uses) + the SAME ``config/system-prompts/e2b.md``
system prompt the executor injects. Warmup completes the bumba-sandbox handshake
BEFORE the WorkOrder intent is sent. We then send the executor's WorkOrder
intent as a stream-json message to the warm process and assert the sandbox tools
were actually called.

Why not Option B (drive the running daemon's warm process)? The daemon's
WarmClaudeProcess is spawned with ``warm_mcp_config = config/warm-core-mcp.json``,
which lists only bumba-memory / github / notion / brave-search — NOT
bumba-sandbox. The live daemon has no warm process with the sandbox MCP
connected, and no endpoint dispatches an E2B WorkOrder through a warm process
(E2BExecutor uses the one-shot ``invoke``). So B is not achievable today without
new daemon wiring. Option A faithfully reproduces the production warm machinery
while exercising the E2B executor's exact prompt + tool surface.

OPERATOR COMMAND (run on the Mac mini as bumba-agent, E2B key in env):

    cd /opt/bumba-harness/agent-flat/agent
    sudo -u bumba-agent env HOME=/opt/bumba-harness \
        E2B_API_KEY="$(sudo -u bumba-agent grep '^e2b_api_key=' \
            /opt/bumba-harness/data/.secrets | cut -d= -f2)" \
        GITHUB_PERSONAL_ACCESS_TOKEN="$(sudo -u bumba-agent grep \
            '^github_personal_access_token=' /opt/bumba-harness/data/.secrets \
            | cut -d= -f2)" \
        .venv/bin/python scripts/verify_e2b_sandbox_live.py

PASS criteria (all must hold):
  - tools_used contains mcp__bumba-sandbox__ tool calls (init + execute + kill)
  - the sandbox command output contains "4"
  - the sandbox was torn down (a kill tool was called)
Exit 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

# The single MCP server the E2B agent is allowed to reach. Mirrors
# bridge/executors/e2b.py::E2B_MCP_SERVER — keep in lockstep.
E2B_MCP_SERVER = "bumba-sandbox"

# Prefix every bumba-sandbox tool surfaces as in tools_used
# (e.g. mcp__bumba-sandbox__sandbox_init).
_SANDBOX_TOOL_PREFIX = f"mcp__{E2B_MCP_SERVER}__"

# Substrings (lowercased) that identify each lifecycle phase within a
# bumba-sandbox tool name. The MCP exposes sandbox_init / sandbox_create,
# command_execute / execute_command, sandbox_kill — match on the verb.
_INIT_MARKERS = ("sandbox_init", "sandbox_create")
_EXEC_MARKERS = ("execute_command", "command_execute")
_KILL_MARKERS = ("sandbox_kill",)

# The WorkOrder intent — identical shape to scripts/diag_e2b_executor.py so we
# exercise the same task the executor would run.
WORKORDER_INTENT = (
    "In an E2B sandbox, run the shell command "
    '`python3 -c "print(2+2)"`, report the exact stdout, '
    "then kill the sandbox."
)


@dataclasses.dataclass(frozen=True)
class VerifyVerdict:
    """Pure verdict over a warm-process E2B run. No I/O — unit-testable."""

    passed: bool
    sandbox_tools_called: tuple[str, ...]
    called_init: bool
    called_execute: bool
    called_kill: bool
    output_has_four: bool
    used_host_bash_fallback: bool
    reasons: tuple[str, ...]


def _matches_any(tool_name: str, markers: tuple[str, ...]) -> bool:
    low = tool_name.lower()
    return any(m in low for m in markers)


def evaluate_run(
    *,
    tools_used: list[str],
    response_text: str,
    is_error: bool,
) -> VerifyVerdict:
    """Decide PASS/FAIL from a warm-process result. Pure function.

    A run PASSES iff: not an error, the agent called bumba-sandbox init +
    execute + kill tools, the output contains "4", and there is no sign of a
    host-Bash fallback (the cold-start failure mode this harness exists to
    distinguish from a broken executor).
    """
    sandbox_tools = tuple(t for t in tools_used if t.startswith(_SANDBOX_TOOL_PREFIX))

    called_init = any(_matches_any(t, _INIT_MARKERS) for t in sandbox_tools)
    called_execute = any(_matches_any(t, _EXEC_MARKERS) for t in sandbox_tools)
    called_kill = any(_matches_any(t, _KILL_MARKERS) for t in sandbox_tools)

    output_has_four = "4" in (response_text or "")

    # Host-Bash fallback signal: the agent used the built-in Bash tool and
    # never touched a bumba-sandbox tool. That is the cold-start failure mode —
    # "4" via the host, not the sandbox.
    used_bash = any(t == "Bash" or t.endswith("__Bash") for t in tools_used)
    used_host_bash_fallback = used_bash and not sandbox_tools

    reasons: list[str] = []
    if is_error:
        reasons.append("warm process returned is_error=True")
    if not sandbox_tools:
        reasons.append(
            f"no {_SANDBOX_TOOL_PREFIX}* tools in tools_used "
            "(sandbox MCP did not surface / was not used)"
        )
    if not called_init:
        reasons.append("sandbox init tool was not called")
    if not called_execute:
        reasons.append("sandbox execute tool was not called")
    if not called_kill:
        reasons.append("sandbox kill tool was not called (sandbox may have leaked)")
    if not output_has_four:
        reasons.append("output does not contain '4'")
    if used_host_bash_fallback:
        reasons.append(
            "HOST BASH FALLBACK detected — '4' came from the host, not a sandbox"
        )

    passed = (
        not is_error
        and bool(sandbox_tools)
        and called_init
        and called_execute
        and called_kill
        and output_has_four
        and not used_host_bash_fallback
    )

    return VerifyVerdict(
        passed=passed,
        sandbox_tools_called=sandbox_tools,
        called_init=called_init,
        called_execute=called_execute,
        called_kill=called_kill,
        output_has_four=output_has_four,
        used_host_bash_fallback=used_host_bash_fallback,
        reasons=tuple(reasons),
    )


def _build_sandbox_only_mcp_config(repo_root: Path) -> Path:
    """Write a temp MCP config exposing ONLY the bumba-sandbox server.

    Uses the SAME ``filter_mcp_config`` machinery the real E2BExecutor uses
    (via IsolatedToolRegistry), reading the runtime ``.mcp.json`` so the
    bumba-sandbox command/args/env match production exactly.
    """
    from bridge.tool_isolation import filter_mcp_config

    mcp_path = repo_root / ".mcp.json"
    if not mcp_path.exists():
        raise FileNotFoundError(
            f"runtime .mcp.json not found at {mcp_path}; cannot build "
            "bumba-sandbox config"
        )
    master = json.loads(mcp_path.read_text())
    filtered = filter_mcp_config(master, [E2B_MCP_SERVER])

    servers = filtered.get("mcpServers", {})
    if E2B_MCP_SERVER not in servers:
        raise KeyError(
            f"{E2B_MCP_SERVER!r} not present in {mcp_path} mcpServers — "
            f"available: {sorted(master.get('mcpServers', {}))}"
        )

    out_dir = Path(tempfile.gettempdir()) / "bumba-e2b-verify"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"warm-sandbox-mcp-{uuid.uuid4().hex[:8]}.json"
    out_path.write_text(json.dumps(filtered, indent=2))
    try:
        os.chmod(str(out_path), 0o600)
    except OSError:
        pass
    return out_path


def _print_header(text: str) -> None:
    print(f"\n{'=' * 4} {text} {'=' * 4}")


async def _run() -> int:
    from bridge.claude_runner import WarmClaudeProcess
    from bridge.config import load_config

    _print_header("E2B LIVE SANDBOX VERIFICATION (warm-MCP, Option A)")
    print("E2B_API_KEY present in env:", bool(os.environ.get("E2B_API_KEY")))

    cfg = load_config()

    # Gate check — mirror E2BExecutor._is_routable so we fail with the same
    # operator-facing reason rather than a cryptic MCP error.
    if not getattr(cfg, "e2b_executor_enabled", False):
        print("FAIL: e2b_executor_enabled is false. Set [dispatcher] "
              "e2b_executor_enabled = true in bridge.toml.")
        return 1
    api_key = str(getattr(cfg, "e2b_api_key", "")).strip()
    if not api_key:
        print("FAIL: e2b_api_key is empty in config. Add e2b_api_key=<key> "
              "to /opt/bumba-harness/data/.secrets.")
        return 1
    # bumba-sandbox resolves ${E2B_API_KEY} from the subprocess env; spawn
    # copies os.environ, so make sure the key is exported for substitution.
    os.environ.setdefault("E2B_API_KEY", api_key)

    repo_root = Path(__file__).resolve().parent.parent  # .../agent
    sandbox_mcp_config = _build_sandbox_only_mcp_config(repo_root)
    e2b_prompt = repo_root / "config" / "system-prompts" / "e2b.md"
    print(f"warm bumba-sandbox MCP config: {sandbox_mcp_config}")
    print(f"e2b system prompt: {e2b_prompt} (exists={e2b_prompt.exists()})")

    # OPTION A: point the warm process at the bumba-sandbox-only config. The
    # warmup message blocks until that server completes its MCP handshake, so
    # by the time we send the WorkOrder the tools are already registered.
    warm_cfg = dataclasses.replace(cfg, warm_mcp_config=str(sandbox_mcp_config))

    warm = WarmClaudeProcess(warm_cfg)

    _print_header("SPAWN + WARMUP (handshakes bumba-sandbox MCP)")
    working_dir = warm_cfg.claude_working_dir or str(repo_root)
    spawned = await warm.spawn(
        working_dir=working_dir,
        model="sonnet",
        system_prompt_file=str(e2b_prompt) if e2b_prompt.exists() else None,
    )
    if not spawned:
        print("FAIL: WarmClaudeProcess.spawn() returned False — warmup or MCP "
              "handshake failed. Check stderr above for the bumba-sandbox node "
              "process error (bad E2B key, missing node, MCP crash).")
        try:
            sandbox_mcp_config.unlink(missing_ok=True)
        except OSError:
            pass
        return 1
    print(f"warmup complete; session_id={warm.session_id}")

    try:
        _print_header("SEND WORKORDER INTENT (warm path)")
        print(f"intent: {WORKORDER_INTENT}")
        # Generous budget: sandbox spin-up + command + teardown over a warm
        # MCP. Warmup already paid the handshake cost.
        result = await warm.send_message(WORKORDER_INTENT, timeout_s=300.0)
    finally:
        await warm.close()
        try:
            sandbox_mcp_config.unlink(missing_ok=True)
        except OSError:
            pass

    _print_header("RESULT")
    print("is_error:", result.is_error)
    print("error_type:", result.error_type)
    print("num_turns:", result.num_turns)
    print("cost_usd:", round(result.cost_usd, 4))
    print("tools_used:", result.tools_used)
    print("response_text:", repr(result.response_text)[:800])

    verdict = evaluate_run(
        tools_used=result.tools_used,
        response_text=result.response_text,
        is_error=result.is_error,
    )

    _print_header("VERDICT")
    print("sandbox tools called:", list(verdict.sandbox_tools_called))
    print("  init  :", verdict.called_init)
    print("  exec  :", verdict.called_execute)
    print("  kill  :", verdict.called_kill)
    print("output contains '4':", verdict.output_has_four)
    print("host-Bash fallback :", verdict.used_host_bash_fallback)
    if verdict.reasons:
        print("reasons:")
        for r in verdict.reasons:
            print(f"  - {r}")

    if verdict.passed:
        print("\nPASS: E2B executor ran the command INSIDE a real sandbox via "
              "bumba-sandbox MCP, returned '4', and tore the sandbox down.")
        return 0

    print("\nFAIL: see reasons above. If the only failure is missing "
          "bumba-sandbox tools with a host-Bash fallback, the MCP still did "
          "not surface even when warm — escalate as an MCP-handshake bug, not "
          "an executor bug.")
    return 1


def main() -> int:
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
