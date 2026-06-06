"""CodexBackend — OpenAI Codex CLI implementation of ``BackendProtocol``.

Codex-2 (issue #1836): second concrete backend behind ``BackendProtocol``,
landing after Codex-1's ``ClaudeBackend``. Wraps the ``codex exec --json``
subprocess surface so ``ClaudeRunner`` can swap CLI runtimes without caring
which one is on the other side.

Three Codex-specific surfaces it owns:

    - Binary resolution: ``BUMBA_CODEX_BINARY`` env override →
      ``config.codex_binary`` → ``shutil.which("codex")`` → ``/opt/homebrew/bin/codex``
      → ``/usr/local/bin/codex`` → ``~/.local/bin/codex`` → ``~/.npm-global/bin/codex``.
    - Command building: emits ``codex exec --json [resume <session_id>]
      [--model <m>] "<message>"``. Two important deltas from Claude:
        1. **Resume is a subcommand, not a flag** — when ``session_id`` is
           supplied, the argv becomes ``codex exec resume <sid> "<msg>"``
           (positional subcommand form per Codex CLI reference).
        2. **Message is positional, not stdin** — Codex's ``exec`` takes the
           prompt as a positional argv tail, unlike Claude which reads stdin.
           Messages starting with dashes still need care (Codex may treat
           ``-foo`` as a flag); pre-1.0 we accept that risk.
    - Stream parsing: NDJSON event protocol with a fundamentally different
      taxonomy from Claude. Top-level types are ``thread.started``,
      ``turn.started``, ``item.started``, ``item.updated``,
      ``item.completed``, ``turn.completed``, ``turn.failed``, ``error``.
      Items carry their own nested ``type`` discriminator
      (``agent_message``, ``reasoning``, ``command_execution``,
      ``file_change``, ``mcp_tool_call``, ``web_search``, ``plan_update``).
      We normalize to the shared ``StreamEvent`` shape so downstream code
      (``ClaudeRunner._process_events``) stays backend-agnostic.

Discovery findings captured pre-implementation:
    https://github.com/your-org/bumba-open-harness/issues/1836#issuecomment-4435727079

Auth (Codex-4, issue #1838) is intentionally out of scope here:
``auth_env()`` returns ``{}``. Codex CLI reads its own ``~/.codex/auth.json``
which Codex-4 will materialize from the bridge's ``.secrets``. No env-var
injection is needed at the subprocess boundary — keeps this backend's
surface narrow and parallel to ``ClaudeBackend.auth_env``.

MCP support is also out of scope. Codex has no ``--mcp-config`` flag (config
lives in ``~/.codex/config.toml``, declared via ``[mcp_servers.<name>]``
tables). The ``mcp_config_path`` parameter is accepted for protocol parity
but is a no-op for Codex. Path A (dual-render JSON + TOML at boot) is
deferred to a follow-up sprint.
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


# -- Codex-2: NDJSON parser (module-level pure helpers) --

def _try_repair_json(line: str) -> dict | None:
    """Attempt to repair malformed JSON from Codex stdout.

    Codex's ``--json`` output is well-formed in normal operation, but
    we keep the same three-strategy repair surface as the Claude parser
    so a single buffering glitch or progress-to-stderr leak doesn't
    silently drop a result event.

    Returns parsed dict on success, None on failure.
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
    """Parse a single NDJSON line from Codex CLI stdout.

    Maps Codex's event taxonomy to the shared ``StreamEvent`` shape:

    ===================================  =========================================
    Codex event                          StreamEvent
    ===================================  =========================================
    ``thread.started``                   ``type="system"`` ``subtype="init"``
                                         ``session_id=<thread_id>``
    ``turn.started``                     ``None`` (suppressed; reduces noise)
    ``item.completed`` /                 ``type="assistant"`` ``text=<item.text>``
       ``item.type == agent_message``
    ``item.completed`` /                 ``type="tool_use"`` ``tool_name="bash"``
       ``item.type == command_execution``
    ``item.completed`` /                 ``type="tool_use"`` ``tool_name="edit"``
       ``item.type == file_change``
    ``item.completed`` /                 ``type="tool_use"`` ``tool_name=<server>``
       ``item.type == mcp_tool_call``
    ``item.completed`` /                 ``None`` (parity with Claude — inner
       ``item.type == reasoning``         reasoning is not surfaced)
    ``turn.completed``                   ``type="result"`` ``subtype="success"``
                                         ``num_turns=1`` ``cost_usd=None``
                                         ``cost_unknown=True`` (E.04 #2011 —
                                         fail-loud until Codex-6 pricing lands)
    ``turn.failed`` / ``error``          ``type="result"`` ``is_error=True``
                                         ``subtype="error_during_execution"``
    ===================================  =========================================

    Unknown event types log at DEBUG and return ``None``.
    """
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        data = _try_repair_json(line)
        if data is None:
            logger.warning("Invalid JSON from Codex stdout (unrepairable): %s", line[:200])
            return None
        logger.info("Repaired malformed JSON from Codex stdout")

    event_type = data.get("type", "")

    # thread.started — Codex's session-init signal. The thread_id is what
    # the bridge persists as the session id for future `codex exec resume
    # <thread_id>` invocations.
    if event_type == "thread.started":
        return StreamEvent(
            type="system",
            subtype="init",
            session_id=data.get("thread_id", ""),
        )

    # turn.started — fires at the start of every turn; not interesting
    # downstream, so suppressed for parity with Claude's parser (which
    # also returns None on equivalent noise).
    if event_type == "turn.started":
        return None

    # item.* events carry a nested type discriminator.
    if event_type == "item.completed":
        item = data.get("item", {})
        if not isinstance(item, dict):
            return None
        item_type = item.get("type", "")

        if item_type == "agent_message":
            return StreamEvent(
                type="assistant",
                text=item.get("text", ""),
            )

        if item_type == "command_execution":
            # Codex runs bash commands via the command_execution item.
            # Surface as a tool_use event with tool_name="bash".
            return StreamEvent(
                type="tool_use",
                tool_name="bash",
            )

        if item_type == "file_change":
            # File edits/writes map to the "edit" tool name for parity
            # with Claude's Edit/Write tool surface.
            return StreamEvent(
                type="tool_use",
                tool_name="edit",
            )

        if item_type == "mcp_tool_call":
            # MCP tool calls carry the server name in `server`; fall
            # back to the tool name if `server` is absent.
            server = item.get("server", "") or item.get("name", "")
            return StreamEvent(
                type="tool_use",
                tool_name=server,
            )

        if item_type == "reasoning":
            # Inner-reasoning text is not surfaced — matches Claude's
            # parser which doesn't emit a separate event for thinking.
            return None

        # Other item types (web_search, plan_update, item.started/updated
        # variants) — log at debug and drop.
        logger.debug("Unhandled Codex item.type: %s", item_type)
        return None

    # turn.completed — Codex's session-complete signal. usage payload
    # carries token counts; cost computation requires OpenAI per-token
    # pricing constants that aren't wired yet, so cost_usd is None and
    # cost_unknown=True as a fail-loud marker. Audit E.04 (#2011): the
    # prior zero-dollar literal here was indistinguishable from a real $0
    # result and silently corrupted any aggregation that summed it;
    # ``None`` makes any consumer that doesn't gate on ``cost_unknown``
    # explode loudly.
    # The ``codex_cost_computable()`` flip-guard in
    # ``bridge.backends.__init__`` is the deployment-time gate that
    # prevents this from ever flowing through production.
    # TODO(Codex-6, #1840): compute cost_usd from usage.input_tokens +
    # usage.output_tokens × per-model pricing; flip cost_unknown to False
    # and write the real float at the same time.
    if event_type == "turn.completed":
        return StreamEvent(
            type="result",
            subtype="success",
            num_turns=1,
            cost_usd=None,
            cost_unknown=True,
        )

    # turn.failed and error — both map to error-during-execution.
    if event_type in ("turn.failed", "error"):
        # Codex puts error text under different keys depending on shape.
        text = data.get("message", "") or data.get("error", "") or data.get("text", "")
        return StreamEvent(
            type="result",
            subtype="error_during_execution",
            is_error=True,
            text=text,
        )

    # Unknown top-level event type — log at debug and drop.
    logger.debug("Unhandled Codex event type: %s", event_type)
    return None


class CodexBackend:
    """OpenAI Codex CLI backend.

    Wraps the three Codex-specific surfaces (binary resolution, command
    building, stream parsing) behind the ``BackendProtocol`` interface.
    Construction takes a ``BridgeConfig`` so the backend can read
    ``codex_binary`` without an extra wiring step.

    Auth is intentionally not handled here — see the module docstring +
    Codex-4 (#1838) for the ``~/.codex/auth.json`` materialization path.
    """

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config

    @property
    def transport(self) -> str:
        """Codex CLI is a subprocess-CLI backend."""
        return "subprocess"

    def resolve_binary(self) -> str | list[str]:
        """Find the Codex CLI binary.

        Returns either the resolved binary path (``str``) or a multi-token
        invocation (``list[str]``) for test-harness shim invocations. The
        list form is reserved for ``BUMBA_CODEX_BINARY`` overrides like
        ``"<python> <fake_codex.py>"``; production code paths always
        return ``str``.

        Resolution order (mirrors ``ClaudeBackend`` precedent, paths
        sourced from Codex-2 discovery comment Q1):

            1. ``BUMBA_CODEX_BINARY`` env var (test-harness override).
               Whitespace-containing values split into argv tokens.
            2. ``self.config.codex_binary`` (operator-set TOML/env).
            3. ``shutil.which("codex")``.
            4. ``/opt/homebrew/bin/codex`` (Apple Silicon Homebrew).
            5. ``/usr/local/bin/codex`` (Intel/legacy Homebrew).
            6. ``~/.local/bin/codex`` (manual binary placement).
            7. ``~/.npm-global/bin/codex`` (npm-global install).
            8. raise ``FileNotFoundError``.
        """
        env_override = os.environ.get("BUMBA_CODEX_BINARY")
        if env_override:
            return env_override.split() if " " in env_override else env_override
        if self.config.codex_binary:
            return self.config.codex_binary
        found = shutil.which("codex")
        if found:
            return found
        # Common install locations (per discovery Q1)
        for candidate in (
            Path("/opt/homebrew/bin/codex"),
            Path("/usr/local/bin/codex"),
            Path.home() / ".local" / "bin" / "codex",
            Path.home() / ".npm-global" / "bin" / "codex",
        ):
            if candidate.is_file():
                return str(candidate)
        raise FileNotFoundError("Codex CLI binary not found in PATH")

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
        """Build the full ``codex exec`` argument list.

        Per Codex-2 discovery Q2: when ``session_id`` is supplied, the
        argv shape is ``[binary, exec, resume, <sid>, "<msg>"]`` —
        ``resume`` is a positional subcommand, NOT a ``--resume`` flag.
        When ``session_id`` is None/empty, the argv is the plain
        ``[binary, exec, "<msg>"]`` with ``--json`` injected.

        ``binary`` overrides ``self.resolve_binary()`` when provided.

        Per-parameter semantic notes:

        - ``message`` is appended as the final positional arg. Unlike
          Claude (stdin), Codex's ``exec`` takes the prompt positionally.
          Messages starting with dashes are a known risk — pre-1.0 we
          accept it; post-1.0 should add ``--`` separator handling.
        - ``system_prompt_file``: Codex does not currently expose a
          ``--instructions`` or equivalent on ``exec``; param is accepted
          for protocol parity but no flag is emitted.
        - ``model``: Codex accepts ``--model <name>`` on ``exec``. Flag
          is emitted only when ``model`` is truthy.
        - ``mcp_config_path``: Codex has NO ``--mcp-config`` flag (config
          lives in ``~/.codex/config.toml``; see discovery Q4). Param is
          accepted for protocol parity but is a no-op. Path A (dual-
          render JSON + TOML at bridge boot) is deferred to a follow-up.
        - ``permission_mode``: Codex's auto-approval surface differs.
          Pre-1.0 we accept the default and emit nothing; post-1.0
          should map ``bypassPermissions`` to Codex's equivalent.
        - ``allowed_tools`` (#2345): Codex has no ``--allowedTools``
          equivalent on ``exec``; param is accepted for protocol parity
          but is a no-op.
        """
        if binary is None:
            binary = self.resolve_binary()
        # `resolve_binary` may return list[str] when BUMBA_CODEX_BINARY is
        # a multi-token shim invocation; flatten so cmd stays flat argv.
        cmd: list[str] = list(binary) if isinstance(binary, list) else [binary]
        cmd.append("exec")

        # NDJSON output mode (per discovery Q3 — `--json` is the
        # post-v0.44 stable flag; older `--experimental-json` is aliased
        # but we use the stable name).
        cmd.append("--json")

        # Model override (e.g. for cost-tiered backends). Codex's
        # `exec --help` lists `--model`; verified via discovery Q3
        # references.
        if model:
            cmd.extend(["--model", model])

        # Session resume: Codex uses a positional `resume <sid>`
        # subcommand instead of a flag. Per discovery Q2.
        if session_id:
            cmd.extend(["resume", session_id])

        # system_prompt_file: no-op for Codex (no equivalent flag on
        # `exec`). Accepted for protocol parity. Tracking follow-up
        # via Codex-6 (#1840) for cost/observability work.
        _ = system_prompt_file

        # mcp_config_path: no-op for Codex (semantic mismatch — Codex
        # reads ~/.codex/config.toml directly, no CLI flag). Path A
        # (dual-render at bridge boot) is deferred per discovery Q4.
        _ = mcp_config_path

        # permission_mode: no-op for Codex pre-1.0. Codex's auto-approval
        # flags differ from Claude's; mapping deferred.
        _ = permission_mode

        # Message is positional (NOT stdin, unlike Claude). Appended last
        # so it's never confused with a flag value.
        cmd.append(message)

        return cmd

    def parse_event(self, line: str) -> StreamEvent | None:
        """Parse a single NDJSON line from Codex CLI stdout.

        Thin instance-method wrapper over the module-level
        ``_parse_stream_line`` so callers can hold a backend reference
        and invoke the parser uniformly across implementations.
        """
        return _parse_stream_line(line)

    def parse_cost(self, event: dict[str, Any]) -> CostMeasurement:
        """Parse Codex's per-turn cost into a typed ``CostMeasurement``.

        audit-2026-05-16.D.02 / HI-2 (#2063): the legacy path either
        routed Codex events through Claude's parser (which read
        ``cost_usd`` and silently defaulted to ``0.0`` on Codex events
        that never carried it), or extracted a raw float that collapsed
        unknowns into a real-looking zero. Both lost the distinction
        between "Codex turn that genuinely cost no incremental USD" and
        "Codex turn whose cost we never measured." The typed return
        surfaces ``source='unknown'`` instead of fabricating a zero.

        Three branches:

        - ``type == "turn.completed"`` with a numeric ``cost_usd`` field
          (post-Codex-6 pricing wired): ``source='measured'``,
          ``amount_usd`` set.
        - ``type == "turn.completed"`` with no usable ``cost_usd``
          (today's reality — Codex emits usage tokens but not cost
          until Codex-6 / #1840 wires per-token pricing):
          ``source='unknown'``. **NOT zero.** This is the HI-2 fix.
        - Any other event type (``thread.started``, ``turn.started``,
          ``item.*``, ``turn.failed``, ``error``, or a foreign
          backend's event shape like Claude's ``result``):
          ``source='not_applicable'`` — those events are not the
          cost-bearing surface for Codex.
        """
        event_type = event.get("type", "")

        # Codex's only cost-bearing event is ``turn.completed``. Anything
        # else (including a Claude-style ``result`` event mis-routed
        # here, or Codex's other event types) is structurally off-meter
        # for the Codex cost parser.
        if event_type != "turn.completed":
            return CostMeasurement(
                amount_usd=None,
                source="not_applicable",
                backend="codex",
                raw_usage_id=None,
            )

        # ``thread_id`` is Codex's session correlator; surfaced as the
        # forensic ``raw_usage_id`` when present so downstream aggregation
        # can trace the unknown back to a specific Codex thread.
        thread_id = event.get("thread_id") or None
        raw = event.get("cost_usd")

        # Numeric cost field present (post-Codex-6 pricing) — measured.
        # ``int``/``float`` both accepted; ``bool`` filtered (it's a
        # subclass of int in Python).
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return CostMeasurement(
                amount_usd=Decimal(str(raw)),
                source="measured",
                backend="codex",
                raw_usage_id=thread_id,
            )

        # turn.completed with no usable cost field — explicit unknown.
        # NOT a measured zero. This is the HI-2 collapse-prevention
        # point. Codex emits usage tokens here without a dollar amount
        # until Codex-6 (#1840) wires the OpenAI per-token pricing
        # model; until then any consumer that wants a number MUST
        # branch on ``source`` rather than treating None as zero.
        return CostMeasurement(
            amount_usd=None,
            source="unknown",
            backend="codex",
            raw_usage_id=thread_id,
        )

    def auth_env(self) -> dict[str, str]:
        """Codex flows auth through ``~/.codex/auth.json`` (Codex-4).

        Returns ``{}`` — no env-var injection is needed at the subprocess
        boundary. Codex CLI reads its own ``~/.codex/auth.json`` (or
        ``$CODEX_HOME/auth.json``) which Codex-4 (issue #1838) will
        materialize from the bridge's ``.secrets``. Both ChatGPT-OAuth
        and ``CODEX_API_KEY`` auth modes resolve through that file, so
        the protocol slot stays empty regardless of auth mode chosen.

        See discovery comment "Auth mechanism choice (Codex-4 dependency)"
        section for the deferred decision.
        """
        return {}

    def shutdown(self) -> None:
        """No-op for Codex. Subprocess lifecycle is owned by ``ClaudeRunner``."""
        return None

    def supports_tool_calling(self) -> bool:
        """Codex runs tools (bash/edit/mcp_tool_call surface in its parser)."""
        return True

    def supports_system_prompt(self) -> bool:
        """False — build_command drops ``system_prompt_file`` as a no-op
        (no equivalent Codex flag)."""
        return False

    def supports_mcp_config(self) -> bool:
        """False — Codex has no --mcp-config flag; config lives in
        ~/.codex/config.toml, so build_command drops ``mcp_config_path``."""
        return False

    def supports_tool_preauth(self) -> bool:
        """False — Codex ``exec`` has no --allowedTools allow-list flag;
        build_command drops ``allowed_tools``."""
        return False
