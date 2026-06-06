"""BackendProtocol — abstraction over subprocess-based agent CLIs.

Codex-1 (issue #1835) extracts Claude-specific subprocess concerns from
``ClaudeRunner`` into a ``BackendProtocol`` interface. ``ClaudeBackend`` is
the in-place default; future backends (Codex CLI, etc.) implement the same
six-method surface so ``ClaudeRunner`` can delegate without caring which
CLI is on the other side.

Surface:
    - ``resolve_binary()`` -> binary path or argv list (shim invocations)
    - ``build_command(*, message, session_id, system_prompt_file, model,
      mcp_config_path, permission_mode)`` -> argv list
    - ``parse_event(line)`` -> ``StreamEvent | None`` from one NDJSON line
    - ``parse_cost(event)`` -> ``CostMeasurement`` four-state cost
      knowledge contract (audit-2026-05-16.D.02, #2063)
    - ``auth_env()`` -> env-var injection for OAuth/API-key auth
    - ``shutdown()`` -> cleanup hook

The ``StreamEvent`` dataclass lives here as the shared event shape every
backend emits. ``bridge.claude_runner`` re-exports it for backwards
compatibility with the historical import path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..cost_tracker import CostMeasurement


# A backend either spawns a CLI subprocess (Claude Code, Codex CLI) or issues
# HTTP requests to an OpenAI-compatible endpoint (OpenRouter, DeepSeek, GLM).
# The discriminator lets ClaudeRunner / the registry branch on transport family
# without an isinstance-by-concrete-class check. (P3.01)
Transport = Literal["subprocess", "http"]


@dataclass
class StreamEvent:
    """A single parsed event from a backend's stream-json output.

    Shared across all backends so ``ClaudeRunner`` event-aggregation logic
    (`_process_events`) stays backend-agnostic. Originated in Sprint S45 as
    the Claude-specific event shape; lifted to the protocol module by
    Codex-1 (issue #1835) without field changes.
    """
    type: str = ""            # "system", "assistant", "tool_use", "tool_result", "result"
    subtype: str = ""         # e.g. "init", "error_max_turns", "error_during_execution"
    text: str = ""
    tool_name: str = ""
    # P1.5: nested tool_use blocks discovered inside assistant.message.content[].
    # Populated only for type == "assistant"; default-empty list keeps existing
    # event types untouched.
    tool_names: list[str] = field(default_factory=list)
    session_id: str = ""
    # E.04 (#2011): ``cost_usd`` is ``float | None`` so a backend that cannot
    # compute cost (e.g. Codex pre-pricing-model) can surface ``None`` as a
    # fail-loud signal instead of silently reporting ``0.0``. Default stays
    # ``0.0`` for back-compat with the Claude path (which always populates a
    # real value). When ``cost_usd`` is ``None``, ``cost_unknown`` MUST be
    # ``True`` so downstream code can branch on the explicit unknown signal.
    cost_usd: float | None = 0.0
    # E.04 (#2011): explicit fail-loud flag set by backends that cannot
    # compute cost. Paired with ``cost_usd=None``. Default ``False`` keeps
    # the Claude path and any backend with a real pricing model unchanged.
    cost_unknown: bool = False
    # VAL-17: preserve the CostMeasurement source and provider usage id for
    # audit summaries. Empty values keep legacy subprocess events unchanged.
    cost_source: str = ""
    cost_raw_usage_id: str | None = None
    num_turns: int = 0
    is_error: bool = False
    duration_ms: int = 0


@runtime_checkable
class BackendProtocol(Protocol):
    """Subprocess-CLI backend interface.

    Implementations wrap a single agent CLI (Claude Code, Codex CLI, etc.)
    and expose the five operations ``ClaudeRunner`` needs to spawn a turn:
    binary resolution, argv assembly, single-line event parsing, auth env
    injection, and shutdown cleanup.

    Implementations are constructed with a ``BridgeConfig`` (or an analogous
    typed config), but the protocol itself is structural — anything that
    quacks like the five methods below satisfies it. Tests use a stub
    backend to exercise the contract without touching subprocess code.
    """

    @property
    def transport(self) -> Transport:
        """Transport family: ``"subprocess"`` (CLI) or ``"http"`` (REST).

        Callers branch on this to decide whether the subprocess surface
        (``resolve_binary``/``build_command``) or the HTTP surface (added by
        the ``HttpBackendProtocol`` sibling in P3.02) applies. CLI backends
        return ``"subprocess"``; OpenAI-compatible HTTP backends return
        ``"http"``.
        """
        ...

    def resolve_binary(self) -> str | list[str]:
        """Return the resolved CLI binary path or a multi-token argv prefix.

        Returns ``str`` for production paths (a single binary on disk) and
        ``list[str]`` for test-harness shim invocations (e.g. ``["python3",
        "/path/to/fake_claude.py"]``).
        """
        ...

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
    ) -> list[str]:
        """Return the full argv list for ``asyncio.create_subprocess_exec``.

        The ``message`` itself is passed via stdin, not argv, to avoid
        CLI-flag parsing issues for messages starting with dashes.

        ``allowed_tools`` (#2345): optional list of tool identifiers to
        pre-authorize via the backend's allow-list flag (Claude:
        ``--allowedTools``). Used to make deferred MCP tools callable for
        one-shot agents (E2BExecutor). Backends that have no allow-list
        concept may ignore it.
        """
        ...

    def parse_event(self, line: str) -> StreamEvent | None:
        """Parse one line of stream output into a ``StreamEvent``.

        Returns ``None`` for empty/whitespace lines and for malformed JSON
        that cannot be repaired. The repair strategy is backend-specific.
        """
        ...

    def parse_cost(self, event: dict[str, Any]) -> "CostMeasurement":
        """Parse the per-turn cost knowledge state from a backend event.

        audit-2026-05-16.D.02 (HI-2, #2063): the legacy path extracted a
        ``float`` from the event dict that silently became ``0.0`` when
        the field was absent, collapsing four distinct knowledge states
        (measured / estimated / unknown / not_applicable) into a single
        zero. This method returns a typed ``CostMeasurement`` so callers
        can branch on the explicit ``source`` state rather than guessing
        what a numeric zero means.

        Contract:

        - Result events with a real per-turn cost from the backend's own
          accounting return ``source='measured'`` with a non-None
          ``Decimal`` amount.
        - Result events whose cost field is absent (the parser has no
          ground truth) return ``source='unknown'`` with
          ``amount_usd=None``. **MUST NOT** be coerced to ``0.0``
          downstream — that is the SW-3 / HI-2 collapse this method
          exists to prevent.
        - Events that are not cost-bearing for this backend (foreign
          backend's event shape, non-result events that simply don't
          carry cost, etc.) return ``source='not_applicable'`` with
          ``amount_usd=None``.

        ``event`` is the already-parsed JSON dict for one stream line.
        Implementations must not consume the line directly — keep parse
        and cost-extraction separable so call sites can mix and match.
        """
        ...

    def auth_env(self) -> dict[str, str]:
        """Return env vars the backend needs injected into the subprocess.

        For Claude, auth flows through ``.secrets`` and ``CLAUDE_CODE_OAUTH_TOKEN``
        is set by ``ClaudeRunner.invoke()`` directly, so the Claude backend
        returns ``{}`` today. Future backends (e.g. CodexBackend) that need
        explicit env injection populate this mapping.
        """
        ...

    def shutdown(self) -> None:
        """Cleanup hook for backend-level resources.

        Claude's implementation is a no-op; backends with persistent
        connections, cached auth, or background threads use this hook.
        """
        ...

    def supports_tool_calling(self) -> bool:
        """True if the backend can execute tools (bash/edit/MCP) during a turn.

        Both Claude and Codex run tools, so both return True today. A
        text-only backend (future) returns False, letting the routing guard
        keep tool-requiring work off it.
        """
        ...

    def supports_system_prompt(self) -> bool:
        """True if ``build_command``'s ``system_prompt_file`` is honored.

        Claude emits ``--append-system-prompt-file``; Codex drops the param
        as a no-op and returns False.
        """
        ...

    def supports_mcp_config(self) -> bool:
        """True if ``build_command``'s ``mcp_config_path`` is honored.

        Claude emits ``--mcp-config`` + ``--strict-mcp-config``; Codex has no
        flag (config lives in ~/.codex/config.toml) and returns False.
        """
        ...

    def supports_tool_preauth(self) -> bool:
        """True if ``build_command``'s ``allowed_tools`` pre-authorizes tools.

        Claude emits ``--allowedTools`` per identifier; Codex has no
        allow-list flag on ``exec`` and returns False.
        """
        ...
