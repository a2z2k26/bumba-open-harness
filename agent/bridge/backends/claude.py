"""ClaudeBackend — Claude Code CLI implementation of ``BackendProtocol``.

Lifted from ``bridge.claude_runner`` by Codex-1 (issue #1835) with zero
observable behavior change. The three Claude-specific surfaces it owns:

    - Binary resolution: ``BUMBA_CLAUDE_BINARY`` env override →
      ``config.claude_binary`` → ``shutil.which("claude")`` →
      ``~/.local/bin/claude`` → ``/usr/local/bin/claude``.
    - Command building: emits ``claude -p --output-format stream-json
      --verbose [--resume <sid>] --max-turns <N> [--permission-mode <mode> |
      --dangerously-skip-permissions] [--model <m>] [--disallowedTools ...]
      [--append-system-prompt-file <path>] [--mcp-config <path>]``.
    - Stream parsing: NDJSON event protocol with malformed-JSON repair.

The module-level helpers (``_try_repair_json``, ``_parse_stream_line``) stay
module-level so ``claude_runner.py`` can re-export them for backwards
compatibility with existing imports (`from bridge.claude_runner import
_parse_stream_line, _try_repair_json`).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..cost_tracker import CostMeasurement
from ._protocol import StreamEvent

if TYPE_CHECKING:
    from ..config import BridgeConfig

logger = logging.getLogger(__name__)


# -- S47: Stream-JSON parser (module-level pure helpers) --

def _try_repair_json(line: str) -> dict | None:
    """Attempt to repair malformed JSON from Claude stdout.

    Returns parsed dict on success, None on failure.
    Common issues: trailing commas, leading garbage text, truncation.
    """
    # Strategy 1: Extract JSON object from surrounding garbage
    match = re.search(r'\{.*\}', line, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Strategy 2: Remove trailing commas before closing braces/brackets
    cleaned = re.sub(r',\s*([}\]])', r'\1', line)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Strategy 3: Try to close truncated JSON
    opens = line.count('{') - line.count('}')
    if opens > 0:
        try:
            return json.loads(line + '"' + '}' * opens)
        except json.JSONDecodeError:
            pass

    return None


def _parse_stream_line(line: str) -> StreamEvent | None:
    """Parse a single NDJSON line from Claude Code stdout."""
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        data = _try_repair_json(line)
        if data is None:
            logger.warning("Invalid JSON from Claude stdout (unrepairable): %s", line[:200])
            return None
        logger.info("Repaired malformed JSON from Claude stdout")

    event = StreamEvent()
    event.type = data.get("type", "")
    event.subtype = data.get("subtype", "")

    if event.type == "system" and event.subtype == "init":
        event.session_id = data.get("session_id", "")

    elif event.type == "assistant":
        # Text content from assistant. P1.5: assistant.message.content[] may
        # also carry tool_use blocks — surface their names so _process_events
        # records them in tools_used alongside top-level tool_use events.
        message = data.get("message", {})
        if isinstance(message, dict):
            for block in message.get("content", []):
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    event.text = block.get("text", "")
                elif block_type == "tool_use":
                    name = block.get("name", "") or block.get("tool_name", "")
                    if name:
                        event.tool_names.append(name)

    elif event.type == "tool_use":
        event.tool_name = data.get("tool_name", data.get("name", ""))

    elif event.type == "result":
        event.is_error = data.get("is_error", False)
        event.subtype = data.get("subtype", "")
        event.session_id = data.get("session_id", "")
        event.cost_usd = data.get("cost_usd", 0.0)
        event.num_turns = data.get("num_turns", 0)
        event.duration_ms = data.get("duration_ms", 0)
        # Result text
        result_text = data.get("result", "")
        if isinstance(result_text, str):
            event.text = result_text

    return event


class ClaudeBackend:
    """Claude Code CLI backend.

    Wraps the three Claude-specific surfaces (binary resolution, command
    building, stream parsing) behind the ``BackendProtocol`` interface.
    Construction takes a ``BridgeConfig`` so the backend can read
    ``claude_binary``, ``claude_output_format``, ``claude_max_turns``, and
    ``security_disallowed_tools`` without an extra wiring step.
    """

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config

    @property
    def transport(self) -> str:
        """Claude Code is a subprocess-CLI backend."""
        return "subprocess"

    def resolve_binary(self) -> str | list[str]:
        """Find the Claude Code binary.

        Returns either the resolved binary path (``str``) or a multi-token
        invocation (``list[str]``) such as ``["/usr/bin/python3",
        "/path/to/shim.py"]``. The list form is reserved for the test-harness
        override below; production code paths always return ``str``.

        Resolution order:
            1. ``BUMBA_CLAUDE_BINARY`` env var (test-harness override).
               Whitespace-containing values are split into argv tokens so
               callers can point at e.g. ``"<python> <fake_claude.py>"``.
            2. ``self.config.claude_binary`` (operator-set TOML/env).
            3. ``shutil.which("claude")``.
            4. Common install locations (``~/.local/bin``, ``/usr/local/bin``).
        """
        # Sprint 08.07: BUMBA_CLAUDE_BINARY is a test-harness override that
        # threads through the real Dispatcher → Executor → ClaudeRunner chain
        # instead of mocking the runner. It must be checked FIRST so e2e
        # harnesses can point ClaudeRunner at fake_claude.py without
        # mutating BridgeConfig (#785). A whitespace-containing value is
        # split into argv tokens for shim-style invocations like
        # "<python> <shim.py>"; a bare path is returned as a string.
        env_override = os.environ.get("BUMBA_CLAUDE_BINARY")
        if env_override:
            return env_override.split() if " " in env_override else env_override
        if self.config.claude_binary:
            return self.config.claude_binary
        found = shutil.which("claude")
        if found:
            return found
        # Common install locations
        for candidate in (
            Path.home() / ".local" / "bin" / "claude",
            Path("/usr/local/bin/claude"),
        ):
            if candidate.is_file():
                return str(candidate)
        raise FileNotFoundError("Claude Code binary not found in PATH")

    def build_command(
        self,
        *,
        message: str,
        session_id: str | None = None,
        system_prompt_file: str | None = None,
        model: str | None = None,
        mcp_config_path: str | None = None,
        permission_mode: str = "bypassPermissions",
        allowed_tools: list[str] | None = None,
        binary: str | list[str] | None = None,
    ) -> list[str]:
        """Build the full `claude -p` argument list.

        ``binary`` overrides the result of ``self.resolve_binary()`` when
        provided. The ``ClaudeRunner._build_command`` wrapper passes its
        own ``self._resolve_binary()`` result through this path so existing
        tests that monkey-patch ``runner._resolve_binary`` continue to work.
        """
        if binary is None:
            binary = self.resolve_binary()
        # ``resolve_binary`` may return ``list[str]`` when
        # ``BUMBA_CLAUDE_BINARY`` is a multi-token invocation (e.g. a shim
        # like ``"<python> <fake_claude.py>"``); flatten so cmd stays a
        # flat argv list, never nested.
        cmd: list[str] = list(binary) if isinstance(binary, list) else [binary]
        cmd.append("-p")

        # Output format
        cmd.extend(["--output-format", self.config.claude_output_format])

        # Verbose for stream events
        cmd.append("--verbose")

        # Resume existing session
        if session_id:
            cmd.extend(["--resume", session_id])

        # Max turns
        cmd.extend(["--max-turns", str(self.config.claude_max_turns)])

        # Permission mode: use native --permission-mode flag when specified,
        # fall back to --dangerously-skip-permissions for bypassPermissions
        # to preserve pre-S05 behaviour across all callers (#630).
        if permission_mode and permission_mode != "bypassPermissions":
            cmd.extend(["--permission-mode", permission_mode])
        else:
            cmd.append("--dangerously-skip-permissions")

        # Model override (e.g. haiku for voice)
        if model:
            cmd.extend(["--model", model])

        # Disallowed tools
        for tool in self.config.security_disallowed_tools:
            cmd.extend(["--disallowedTools", tool])

        # Allowed tools (#2345). Recent Claude Code defers MCP tools behind
        # the ToolSearch surface — they do NOT appear in the init `tools`
        # list and must be discovered, then allowed, before they are
        # callable. Naming the concrete `mcp__<server>__<tool>` identifiers
        # here pre-authorizes them so a one-shot agent (e.g. E2BExecutor)
        # can call the bumba-sandbox tools the moment ToolSearch surfaces
        # them, instead of hitting a permission gate. When None (the default
        # for every other call site) no flag is emitted and behavior is
        # byte-identical to before.
        for tool in allowed_tools or []:
            cmd.extend(["--allowedTools", tool])

        # System prompt file for context injection
        if system_prompt_file:
            cmd.extend(["--append-system-prompt-file", system_prompt_file])

        # Filtered MCP config for write jail (S03). Pair with
        # --strict-mcp-config so Claude uses ONLY the supplied filtered
        # config and ignores any project .mcp.json discovered at cwd.
        #
        # #2345: without --strict-mcp-config, Claude merges the filtered
        # config with the runtime tree's .mcp.json (the daemon's cwd is the
        # runtime root). That .mcp.json is in the kernel-integrity baseline,
        # so Claude normalising/rewriting it mid-run mutated a hashed file →
        # the SessionStart hook's re-hash flagged a violation → halt.flag →
        # the subprocess was killed (exit 143) before the E2B sandbox could
        # finish. Strict mode keeps the filtered config authoritative (which
        # is the write-jail intent anyway) and leaves the baselined
        # .mcp.json untouched. Mirrors the warm path (claude_runner.py
        # WarmClaudeProcess.spawn, Sprint D8.1).
        if mcp_config_path:
            cmd.extend(["--mcp-config", mcp_config_path, "--strict-mcp-config"])

        # Message is passed via stdin, not as a CLI argument.
        # This avoids messages starting with dashes being misread as CLI flags.

        return cmd

    def parse_event(self, line: str) -> StreamEvent | None:
        """Parse a single NDJSON line from Claude Code stdout.

        Thin instance-method wrapper over the module-level
        ``_parse_stream_line`` so callers can hold a backend reference and
        invoke the parser uniformly across implementations.
        """
        return _parse_stream_line(line)

    def parse_cost(self, event: dict[str, Any]) -> CostMeasurement:
        """Parse Claude's per-turn cost into a typed ``CostMeasurement``.

        audit-2026-05-16.D.02 / HI-2 (#2063): replaces the legacy
        ``cost_usd = data.get("cost_usd", 0.0)`` pattern which collapsed
        "field missing" into a real-looking zero. The typed return keeps
        the four cost-knowledge states distinct so downstream budget
        gates can branch on ``source`` rather than guessing.

        Claude's stream-json result events carry ``cost_usd`` reliably,
        so the measured path is the common case. Three branches:

        - ``type == "result"`` with a numeric ``cost_usd`` (including
          ``0.0``, which is a legitimate measured-zero on Claude's
          accounting): ``source='measured'``, ``amount_usd`` set.
        - ``type == "result"`` with ``cost_usd`` absent or non-numeric:
          ``source='unknown'`` (parser saw a result but found no cost).
        - Any other event type (``system``, ``assistant``, ``tool_use``,
          ``tool_result``, or a foreign backend's event shape like
          ``thread.started`` / ``turn.completed``): ``source='not_applicable'``
          — non-result events are not the cost-bearing surface on Claude.
        """
        event_type = event.get("type", "")

        # Only Claude's result events carry per-turn cost. Foreign event
        # shapes (Codex's thread.started / turn.completed / item.completed,
        # or anything else) are not-applicable for this backend's parser.
        if event_type != "result":
            return CostMeasurement(
                amount_usd=None,
                source="not_applicable",
                backend="claude",
                raw_usage_id=None,
            )

        raw = event.get("cost_usd")
        session_id = event.get("session_id") or None

        # ``int``/``float`` are both legitimate — ``isinstance(..., bool)``
        # excludes the True/False edge case (bool is a subclass of int).
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            # ``Decimal(str(float))`` avoids binary-float widening
            # (``Decimal(0.1)`` != ``Decimal('0.1')``).
            return CostMeasurement(
                amount_usd=Decimal(str(raw)),
                source="measured",
                backend="claude",
                raw_usage_id=session_id,
            )

        # Result event with no usable cost field — explicit unknown,
        # NOT a measured zero. This is the HI-2 fix-point.
        return CostMeasurement(
            amount_usd=None,
            source="unknown",
            backend="claude",
            raw_usage_id=session_id,
        )

    def auth_env(self) -> dict[str, str]:
        """Claude flows auth through ``.secrets`` + ``CLAUDE_CODE_OAUTH_TOKEN``.

        ``ClaudeRunner.invoke()`` sets ``CLAUDE_CODE_OAUTH_TOKEN`` directly
        on the subprocess env from ``self._token_provider.access_token`` or
        ``config.claude_oauth_token``; no extra injection is needed here.
        The slot is reserved for backends that ship explicit env vars
        (e.g. ``OPENAI_API_KEY`` for Codex CLI).
        """
        return {}

    def shutdown(self) -> None:
        """No-op for Claude. Subprocess lifecycle is owned by ``ClaudeRunner``."""
        return None

    def supports_tool_calling(self) -> bool:
        """Claude runs tools natively via the Claude Code CLI."""
        return True

    def supports_system_prompt(self) -> bool:
        """Claude honors ``system_prompt_file`` via --append-system-prompt-file."""
        return True

    def supports_mcp_config(self) -> bool:
        """Claude honors ``mcp_config_path`` via --mcp-config --strict-mcp-config."""
        return True

    def supports_tool_preauth(self) -> bool:
        """Claude honors ``allowed_tools`` via --allowedTools."""
        return True
