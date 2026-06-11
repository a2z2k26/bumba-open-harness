"""Claude Code subprocess management: spawn, stream-parse, watchdog, error classification."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import BridgeConfig
from . import log_format
from .context_pressure import format_handoff_message
from .compaction_checkpoint import capture_checkpoint
# Codex-1 (#1835): subprocess concerns extracted behind BackendProtocol.
# ClaudeBackend is the in-place default; future backends register here.
from .backends import BackendProtocol, ClaudeBackend
from .backends._errors import CapabilityError
from .backends._protocol import StreamEvent
from .backends.claude import _parse_stream_line, _try_repair_json  # noqa: F401 — _try_repair_json re-exported for test_claude_runner.py
# E1.5 — tool-call gate + operator inbox (optional, wired via set_operator_inbox)
# audit-2026-05-16.C.02 — HaltPolicy (optional, wired via set_halt_policy)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .operator_inbox import OperatorInbox
    from .halt import HaltPolicy

logger = logging.getLogger(__name__)


def _select_backend_for_main(config: BridgeConfig) -> BackendProtocol:
    """Return the active backend for main-runner dispatch.

    ``backends_enabled=False`` preserves the legacy Claude-only path. When the
    flag is enabled, the configured ``backends_main`` name is resolved through
    the backend instance factory so OpenRouter/Codex can drive ``invoke()``.
    """
    if not getattr(config, "backends_enabled", False):
        return ClaudeBackend(config)

    from .backends.factory import build_backend_instances

    instances = build_backend_instances(config)
    backend_name = getattr(config, "backends_main", "claude")
    try:
        return instances[backend_name]
    except KeyError as exc:
        raise ValueError(
            f"Backend {backend_name!r} configured for main dispatch is not "
            f"registered; available backends: {sorted(instances)}"
        ) from exc


# -- E1.1: Context pressure hard-stop helpers --

# Hard-stop threshold: mirrors CompactionConfig.auto_trigger_threshold default.
_HARD_STOP_THRESHOLD: float = 0.75


def should_hard_stop_from_float(
    pressure: float,
    *,
    hard_stop_enabled: bool = True,
    threshold: float = _HARD_STOP_THRESHOLD,
) -> bool:
    """Return True if the float pressure score warrants a hard-stop.

    Surgical option (b) from E1.1 issue #1233: operates on the float from
    session_manager.context_pressure() rather than ContextPressureMonitor,
    applying the same threshold logic without requiring a monitor instance
    on the invoke() hot path.

    Args:
        pressure: Composite pressure float 0.0–1.0 from session_manager.
        hard_stop_enabled: Pass BridgeConfig.context_pressure_hard_stop_enabled.
        threshold: Defaults to CompactionConfig.auto_trigger_threshold (0.75).
    """
    if not hard_stop_enabled:
        return False
    return pressure >= threshold

# Canary token detection — sentinel strings embedded in bootstrap files.
# If these appear in Claude's output, the system prompt has been leaked.
CANARY_PATTERN = re.compile(r"CANARY:[a-f0-9]{12}")


def _load_secrets_as_env(data_dir: str) -> dict[str, str]:
    """Load all key=value pairs from .secrets for subprocess env injection.

    This allows MCP servers to resolve ${VAR} references in .mcp.json
    from the same secrets file used for bridge credentials.

    Sprint audit-2026-05-16.B.02 (#2051, M-1) — thin wrapper around
    :class:`bridge.runtime_secrets.RuntimeSecrets`. The canonical parse
    + permission guard live in the helper module; the signature
    (``data_dir: str`` → ``dict[str, str]``) is preserved so existing
    call sites at ``ClaudeRunner.invoke`` keep working.
    """
    from bridge.runtime_secrets import RuntimeSecrets
    from bridge.config import ConfigError

    secrets_path = Path(data_dir) / ".secrets"
    rs = RuntimeSecrets(secrets_path=secrets_path)
    try:
        return rs.as_env_dict()
    except ConfigError as exc:
        # Pre-B.02 behaviour raised RuntimeError on bad perms. Re-raise as
        # RuntimeError to keep ``ClaudeRunner.invoke``'s exception contract
        # unchanged; the underlying ConfigError message is preserved.
        raise RuntimeError(f"unsafe permissions: {exc}") from exc
    except OSError:
        # Mirrors the pre-B.02 soft-fail on unreadable files.
        return {}


def _scan_for_canary(text: str) -> tuple[str, list[str]]:
    """Scan response text for canary token leakage.

    Returns (cleaned_text, list_of_matched_tokens).
    If no canary found, returns (original_text, []).
    """
    matches = CANARY_PATTERN.findall(text)
    if matches:
        cleaned = CANARY_PATTERN.sub("[REDACTED]", text)
        return cleaned, matches
    return text, []


# -- S45: Dataclasses --
#
# Codex-1 (#1835): ``StreamEvent`` now lives in ``backends._protocol`` so all
# backends share the event shape. Re-exported above via
# ``from .backends._protocol import StreamEvent`` to keep the historical
# ``from bridge.claude_runner import StreamEvent`` import path stable.


@dataclass
class ClaudeResult:
    """Result of a Claude Code invocation."""
    response_text: str = ""
    session_id: str = ""
    cost_usd: float = 0.0
    # P0.03: True when the backend could not report a cost (cost_usd is then a
    # placeholder 0.0, NOT a measured free turn). Lets budget gates refuse to
    # treat an unknown cost as zero — the SW-3 collapse this flag prevents.
    cost_unknown: bool = False
    cost_source: str = ""
    cost_raw_usage_id: str | None = None
    num_turns: int = 0
    tools_used: list[str] = field(default_factory=list)
    is_error: bool = False
    error_type: str = ""      # "auth", "rate_limit", "content_filter", "max_turns", etc.
    duration_ms: int = 0
    exit_code: int = 0
    stderr_output: str = ""


_INVOKE_CAPABILITY_METHODS = {
    "tool_calling": "supports_tool_calling",
    "mcp_config": "supports_mcp_config",
    "tool_preauth": "supports_tool_preauth",
}


def _unique_capabilities(capabilities: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for capability in capabilities:
        if capability in seen:
            continue
        seen.add(capability)
        unique.append(capability)
    return unique


def _configured_backend_name(config: BridgeConfig, backend: BackendProtocol) -> str:
    if getattr(config, "backends_enabled", False):
        return str(getattr(config, "backends_main", "") or type(backend).__name__)
    return type(backend).__name__


def _capability_misroute_result(
    *,
    config: BridgeConfig,
    backend: BackendProtocol,
    mcp_config_path: str | None,
    allowed_tools: list[str] | None,
    start_time: float,
) -> ClaudeResult | None:
    """Fail before dispatch when the caller supplied unsupported tool surfaces."""
    required: list[str] = []
    if mcp_config_path:
        required.extend(["tool_calling", "mcp_config"])
    if allowed_tools:
        required.extend(["tool_calling", "tool_preauth"])
    required = _unique_capabilities(required)
    if not required:
        return None

    missing = [
        capability
        for capability in required
        if not getattr(backend, _INVOKE_CAPABILITY_METHODS[capability])()
    ]
    if not missing:
        return None

    backend_name = _configured_backend_name(config, backend)
    error = CapabilityError(
        agent_role="main",
        backend_name=backend_name,
        missing=missing,
        required=required,
    )
    logger.error(
        "CAPABILITY MISROUTE BLOCKED: backend %r (role=%r) missing %s — "
        "required %s. Refusing dispatch before model/tool execution.",
        error.backend_name,
        error.agent_role,
        sorted(error.missing),
        sorted(error.required),
    )
    return ClaudeResult(
        is_error=True,
        error_type="capability_misroute",
        stderr_output=str(error),
        duration_ms=int((time.monotonic() - start_time) * 1000),
        exit_code=1,
    )


# -- S47: Stream-JSON parser --
#
# Codex-1 (#1835): ``_try_repair_json`` and ``_parse_stream_line`` now live in
# ``backends.claude`` so other backends can share the repair strategy where
# applicable. Re-exported above via
# ``from .backends.claude import _parse_stream_line, _try_repair_json`` to
# keep the historical import path stable for tests and any consumers.


def _process_events(events: list[StreamEvent]) -> ClaudeResult:
    """Aggregate parsed stream events into a ClaudeResult."""
    result = ClaudeResult()
    text_parts: list[str] = []
    tools: list[str] = []

    for ev in events:
        if ev.type == "system" and ev.subtype == "init" and ev.session_id:
            result.session_id = ev.session_id

        elif ev.type == "assistant":
            if ev.text:
                text_parts.append(ev.text)
            # P1.5: aggregate nested tool_use names from assistant content blocks.
            for name in ev.tool_names:
                if name and name not in tools:
                    tools.append(name)

        elif ev.type == "tool_use" and ev.tool_name:
            if ev.tool_name not in tools:
                tools.append(ev.tool_name)

        elif ev.type == "result":
            if ev.session_id:
                result.session_id = ev.session_id
            # P0.03: branch on the unknown state instead of letting a None
            # cost coerce into the float field. An unknown cost keeps the
            # numeric placeholder 0.0 but flips cost_unknown so downstream
            # budget gates never read it as a measured free turn.
            if ev.cost_unknown or ev.cost_usd is None:
                result.cost_unknown = True
                result.cost_usd = 0.0
            else:
                result.cost_usd = ev.cost_usd
            result.cost_source = ev.cost_source
            result.cost_raw_usage_id = ev.cost_raw_usage_id
            result.num_turns = ev.num_turns
            result.is_error = ev.is_error
            result.duration_ms = ev.duration_ms
            if ev.text:
                text_parts.append(ev.text)
            if ev.subtype in ("error_max_turns", "error_during_execution"):
                result.error_type = ev.subtype

    result.response_text = text_parts[-1] if text_parts else ""
    result.tools_used = tools
    return result


def _apply_cost_measurement_to_event(
    event: StreamEvent,
    measurement: object,
) -> None:
    """Project a CostMeasurement-like object onto a StreamEvent."""
    amount = getattr(measurement, "amount_usd", None)
    source = getattr(measurement, "source", "")
    event.cost_source = str(source or "")
    raw_usage_id = getattr(measurement, "raw_usage_id", None)
    event.cost_raw_usage_id = str(raw_usage_id) if raw_usage_id else None
    if source in ("measured", "estimated") and amount is not None:
        event.cost_usd = float(amount)
        event.cost_unknown = False
    elif source == "unknown":
        event.cost_usd = None
        event.cost_unknown = True
    else:
        event.cost_usd = 0.0
        event.cost_unknown = False


# ---------------------------------------------------------------------------
# E1.5 — ForcePauseAlerter: concrete implementation of the ForcePauseAlerter
# Protocol defined in dialogue_delay_monitor.py.
#
# When a pending operator message ages past the force-pause threshold, the
# DialogueDelayMonitor calls ``alerter.alert(pending)``. This implementation:
#   (a) posts a Discord alert via a pluggable ``_notify_fn`` callback; and
#   (b) sets an internal ``_paused`` flag that ClaudeRunner checks at the
#       top of invoke() to short-circuit subprocess spawning.
#
# The ``_notify_fn`` is injected at wiring time (e.g. in BridgeApp._initialize
# or in session_manager); it must be a sync or async callable that accepts a
# string. When ``None``, the alert is logged only — no Discord post — so
# callers that haven't wired Discord yet still get safety semantics.
# ---------------------------------------------------------------------------

class DiscordForcePauseAlerter:
    """Concrete ForcePauseAlerter that posts to Discord and sets a pause flag.

    This class satisfies the ``ForcePauseAlerter`` Protocol from
    ``bridge.dialogue_delay_monitor`` (Sprint 4.13).

    The ``paused`` property is read by ``ClaudeRunner.invoke()`` so that
    a force-pause from a background monitor prevents the next subprocess
    spawn without any inter-task coordination beyond a simple bool flag.
    """

    def __init__(self, notify_fn=None) -> None:
        """
        Args:
            notify_fn: Optional async callable ``(message: str) -> None``
                used to post alerts. Typically the Discord bot's ``send``
                method or a thin wrapper. When ``None``, alerts are
                logger.error-only — no Discord post.
        """
        self._notify_fn = notify_fn
        self._paused: bool = False

    @property
    def paused(self) -> bool:
        """True once force-pause has been triggered at least once."""
        return self._paused

    def clear_pause(self) -> None:
        """Clear the pause flag (operator resume)."""
        self._paused = False

    async def alert(self, pending: list) -> None:
        """Implement ForcePauseAlerter.alert: set pause flag + notify."""
        self._paused = True
        ids = ", ".join(m.id for m in pending)
        msg = (
            f"[FORCE-PAUSE] {len(pending)} operator message(s) pending "
            f"for >{len(pending) and pending[0].age_seconds:.0f}s without "
            f"acknowledgment: {ids}. Subprocess spawn suspended until messages "
            "are acknowledged."
        )
        logger.error("force_pause_alerter: %s", msg)
        if self._notify_fn is not None:
            try:
                import asyncio
                result = self._notify_fn(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("force_pause_alerter: notify_fn failed")


class _NullInvocationTracker:
    """No-op context manager — used when InvocationController isn't wired.

    Lets the call site write a single ``async with self._track_invocation(...)``
    line without branching on whether the controller exists.
    """

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class ClaudeRunner:
    """Manages Claude Code subprocess lifecycle."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        # Codex-1 (#1835): subprocess concerns live on the backend. The
        # ClaudeBackend is in-place default; ``_resolve_binary`` and
        # ``_build_command`` delegate here so tests that monkey-patch the
        # instance methods still work.
        self._backend: BackendProtocol = _select_backend_for_main(config)
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._last_activity: float = 0.0
        self._pid_file = Path(config.data_dir) / "claude.pid"
        self._token_provider: object | None = None  # TokenRefresher, if set
        # E1.5 — optional OperatorInbox for gate checks before subprocess spawn.
        # Wired via set_operator_inbox(); default None disables the gate.
        self._operator_inbox: "OperatorInbox | None" = None
        # E1.5 — optional DiscordForcePauseAlerter; when set, ClaudeRunner
        # checks alerter.paused before spawning to honour a force-pause.
        self._force_pause_alerter: "DiscordForcePauseAlerter | None" = None
        # P1.1 (audit C1) — optional InvocationController for unified
        # one-shot/warm in-flight state. Set via set_invocation_controller();
        # when present, invoke() wraps its work in controller.track().
        self._invocation_controller: object | None = None
        # audit-2026-05-16.C.02 — optional HaltPolicy for unified halt
        # contract. Set via set_halt_policy(); when present, invoke()
        # consults check_start() before spawn and check_continue() during
        # the stream-read loop in place of the direct halt.flag file read.
        # When None (default), the existing direct file check remains the
        # halt source — back-compat preserved.
        self._halt_policy: "HaltPolicy | None" = None
        self._halt_surface: str = "claude-runner"

    @property
    def is_active(self) -> bool:
        """True iff a Claude subprocess is currently running (#2207).

        Consulted by the DialogueDelayMonitor to suppress force-pause
        alerts during idle conversational sessions — there's nothing to
        interrupt when no subprocess is in flight. A subprocess is
        considered active if `self._process` is set AND has not yet
        exited (`returncode is None`).
        """
        proc = self._process
        return proc is not None and proc.returncode is None

    def set_invocation_controller(self, controller: object) -> None:
        """Wire an InvocationController for unified in-flight state (P1.1).

        When set, ``invoke()`` calls ``controller.track(path="one_shot", ...)``
        around its work so app-level interrupt detection can see the
        invocation regardless of which path is in flight. Backwards-compat:
        if no controller is wired, ``invoke()`` behaves exactly as before.
        """
        self._invocation_controller = controller

    def _track_invocation(
        self,
        path: str,
        session_id: str | None = None,
        chat_id: str | None = None,
    ):
        """Return a context manager that records invocation state.

        When ``self._invocation_controller`` is set, returns the real
        ``track()`` context. When None, returns a no-op so the call site
        stays readable in both cases.
        """
        if self._invocation_controller is None:
            return _NullInvocationTracker()
        return self._invocation_controller.track(
            path=path,
            session_id=session_id,
            chat_id=chat_id,
        )

    def set_token_provider(self, provider: object) -> None:
        """Set a token provider (TokenRefresher) for dynamic OAuth tokens."""
        self._token_provider = provider

    def set_operator_inbox(self, inbox: "OperatorInbox") -> None:
        """Wire an OperatorInbox for gate evaluation before subprocess spawn (E1.5).

        When set and ``config.universal_tool_gate_enabled`` is True, each call
        to ``invoke()`` will first run ``evaluate_gate(inbox)``. A BLOCK_*
        decision short-circuits spawn and returns a synthetic ``ClaudeResult``
        whose ``response_text`` is the gate's ``block_message``.
        """
        self._operator_inbox = inbox

    def set_force_pause_alerter(self, alerter: "DiscordForcePauseAlerter") -> None:
        """Wire a DiscordForcePauseAlerter for force-pause enforcement (E1.5).

        When set and the alerter's ``paused`` flag is True, ``invoke()`` will
        short-circuit and return a synthetic result without spawning the
        subprocess.
        """
        self._force_pause_alerter = alerter

    def set_halt_policy(
        self,
        policy: "HaltPolicy",
        *,
        surface: str = "claude-runner",
    ) -> None:
        """Wire a shared HaltPolicy for unified start/continue checks (C.02).

        When set, ``invoke()`` consults:
          - ``policy.check_start(surface)`` BEFORE spawning the subprocess.
            On block, returns a synthetic ``ClaudeResult`` carrying the
            policy's reason as ``response_text``; no subprocess is spawned.
          - ``policy.check_continue(surface)`` inside the stream-read loop
            at the existing periodic-check interval. On block, the running
            subprocess group is terminated (SIGTERM → wait → SIGKILL via
            ``_terminate_process_group``) and the stream-read loop exits.

        Back-compat: when no policy is wired (the default), the existing
        direct ``halt.flag`` file check remains in place. ``surface`` is
        kept as an instance attribute and propagated into log lines and
        the policy's reason strings so operator logs grep cleanly.
        """
        self._halt_policy = policy
        self._halt_surface = surface

    # -- S46: Command builder --
    #
    # Codex-1 (#1835): subprocess concerns extracted to ``ClaudeBackend``.
    # The two methods below are thin instance-method wrappers that delegate
    # to ``self._backend`` so existing tests that monkey-patch them
    # (``runner._resolve_binary = lambda: ...`` or ``patch.object(runner,
    # "_build_command", ...)``) continue to work without modification.

    def _resolve_binary(self) -> str | list[str]:
        """Delegate to ``self._backend.resolve_binary`` (Codex-1)."""
        return self._backend.resolve_binary()

    def _build_command(
        self,
        message: str,
        session_id: str | None = None,
        system_prompt_file: str | None = None,
        model: str | None = None,
        mcp_config_path: str | None = None,
        permission_mode: str = "bypassPermissions",
        allowed_tools: list[str] | None = None,
    ) -> list[str]:
        """Delegate to ``self._backend.build_command`` (Codex-1).

        Signature preserved (positional ``message`` + the historical kwargs)
        so existing call sites in ``invoke()`` and the test sweep remain
        byte-identical. The backend's ``build_command`` uses keyword-only
        args internally to keep future backends from collapsing the kwargs.
        """
        # Resolve via the wrapper so test monkey-patches on
        # ``runner._resolve_binary`` propagate into the assembled argv.
        return self._backend.build_command(
            message=message,
            session_id=session_id,
            system_prompt_file=system_prompt_file,
            model=model,
            mcp_config_path=mcp_config_path,
            permission_mode=permission_mode,
            allowed_tools=allowed_tools,
            binary=self._resolve_binary(),
        )

    async def _invoke_http_backend(
        self,
        *,
        message: str,
        system_prompt_file: str | None,
        on_first_text: Callable[[str], None] | None,
        on_text_delta: Callable[[str], None] | None,
        start_time: float,
    ) -> ClaudeResult:
        """Run one non-streaming HTTP backend request and adapt to ClaudeResult."""
        request = getattr(self._backend, "request", None)
        if not callable(request):
            return ClaudeResult(
                is_error=True,
                error_type="http_backend_error",
                stderr_output="HTTP backend does not expose request()",
            )

        system_prompt: str | None = None
        if system_prompt_file:
            try:
                system_prompt = await asyncio.to_thread(
                    Path(system_prompt_file).read_text
                )
            except OSError as exc:
                return ClaudeResult(
                    is_error=True,
                    error_type="http_system_prompt_error",
                    stderr_output=str(exc),
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

        try:
            raw = await asyncio.to_thread(
                lambda: request(message=message, system_prompt=system_prompt)
            )
            event = self._backend.parse_event(json.dumps(raw))
            if event is None:
                return ClaudeResult(
                    is_error=True,
                    error_type="http_parse_error",
                    stderr_output="HTTP backend returned no parseable completion",
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            measurement = self._backend.parse_cost(raw)
            _apply_cost_measurement_to_event(event, measurement)
            event.num_turns = 1
            event.duration_ms = int((time.monotonic() - start_time) * 1000)

            if event.text:
                for callback in (on_first_text, on_text_delta):
                    if callback is None:
                        continue
                    try:
                        callback(event.text)
                    except Exception as cb_err:
                        logger.debug("HTTP text callback error: %s", cb_err)

            result = _process_events([event])
            result.exit_code = 0
            result.duration_ms = event.duration_ms
            return result
        except Exception as exc:  # noqa: BLE001 — adapt backend failures to ClaudeResult
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error("HTTP backend invoke error: %s: %s", type(exc).__name__, exc)
            return ClaudeResult(
                is_error=True,
                error_type="http_backend_error",
                stderr_output=str(exc),
                duration_ms=elapsed_ms,
                exit_code=1,
            )

    # -- S48: Subprocess spawn and stdout reading --

    async def invoke(
        self,
        message: str,
        session_id: str | None = None,
        system_prompt_file: str | None = None,
        on_first_text: Callable[[str], None] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        working_dir: str | None = None,
        model: str | None = None,
        mcp_config_path: str | None = None,
        env_vars: dict[str, str] | None = None,
        permission_mode: str = "bypassPermissions",
        allowed_tools: list[str] | None = None,
    ) -> ClaudeResult:
        """Spawn Claude Code, read stream output, return result.

        Args:
            mcp_config_path: Optional path to a filtered .mcp.json for this invocation.
                             When provided, passed as ``--mcp-config <path>`` to Claude.
            allowed_tools: Optional list of tool identifiers to pre-authorize
                           via ``--allowedTools`` (#2345). Recent Claude Code
                           defers MCP tools behind ToolSearch; naming the
                           concrete ``mcp__<server>__<tool>`` ids makes them
                           callable for a one-shot agent (E2BExecutor) once
                           surfaced. None (default) emits no flag.
            env_vars: Optional dict of extra environment variables to inject into the
                     subprocess environment (merged after secrets are loaded).
            on_text_delta: Sprint 07.13 — optional sync callback fired once for
                           every assistant text event observed in the stream.
                           When non-None, it is called with the text payload of
                           each ``assistant`` event so callers can route deltas
                           through StreamCoalescer (or any other batcher) before
                           they reach Discord. The callback is sync and must not
                           block; exceptions are logged at DEBUG and swallowed.
        """
        async with self._lock, self._track_invocation("one_shot", session_id=session_id):
            # Sprint 07.11 — bind correlation context for the duration of
            # this invocation so every log record emitted inside the
            # subprocess spawn / stream-read carries the session_id. The
            # caller's prior message_id (if any) is preserved; we save the
            # token here and reset it in the existing ``finally`` block at
            # the bottom of this method so a failed invocation cannot leak
            # its session_id into the next handler's logs.
            # E1.5 — universal tool-call gate + force-pause check.
            # These run BEFORE any subprocess work so blocked invocations
            # never touch the OAuth token, the session_id ContextVar, or
            # the Claude binary. Both checks are no-ops when the respective
            # objects are not wired in (backward-compatible).
            #
            # Force-pause check: if the background DialogueDelayMonitor has
            # fired (message pending > 300s), refuse to spawn until the
            # operator acknowledges.
            if (
                self._force_pause_alerter is not None
                and self._force_pause_alerter.paused
            ):
                logger.warning(
                    "invoke: blocked — force-pause active "
                    "(pending operator message not acknowledged)"
                )
                return ClaudeResult(
                    response_text=(
                        "BLOCKED: A force-pause is active because an operator "
                        "message has been pending without acknowledgment for too "
                        "long. Acknowledge the pending message(s) before sending "
                        "new work."
                    ),
                    is_error=False,
                )

            # audit-2026-05-16.C.02 — HaltPolicy pre-spawn check.
            # When a HaltPolicy is wired, consult check_start(surface)
            # before any subprocess work. On block, return a synthetic
            # ClaudeResult carrying the reason; the subprocess is never
            # spawned, so MCP servers/tool processes never come up. No-op
            # when no policy is wired (the direct halt.flag fallback in
            # the stream loop still applies).
            if self._halt_policy is not None:
                start_decision = self._halt_policy.check_start(
                    self._halt_surface
                )
                if start_decision.blocked:
                    logger.warning(
                        "invoke: blocked pre-spawn by HaltPolicy "
                        "(surface=%s reason=%s session=%s)",
                        self._halt_surface,
                        start_decision.reason,
                        session_id,
                    )
                    return ClaudeResult(
                        response_text=(
                            f"HALTED: {start_decision.reason or 'halt flag set'}"
                        ),
                        is_error=False,
                    )

            # Gate check: if an OperatorInbox is wired and the gate flag is
            # on, evaluate the gate and short-circuit on any BLOCK_* decision.
            if (
                self._operator_inbox is not None
                and getattr(self.config, "universal_tool_gate_enabled", True)
            ):
                try:
                    from .tool_call_gate import evaluate_gate, GateDecision
                    gate_result = await evaluate_gate(
                        self._operator_inbox,
                        min_pending=getattr(self.config, "min_pending_to_gate", 1),
                    )
                    if gate_result.decision != GateDecision.ALLOW:
                        logger.warning(
                            "invoke: gate blocked — decision=%s session=%s",
                            gate_result.decision.value,
                            session_id,
                        )
                        return ClaudeResult(
                            response_text=gate_result.block_message,
                            is_error=False,
                        )
                except Exception:
                    # Fail closed (audit-2026-06-11): a broken gate must not
                    # silently disable operator-priority enforcement — that is
                    # the silent-degradation anti-pattern the wiring doctrine
                    # exists to eliminate. Block this turn loudly; the operator
                    # can set interrupts.tool_call_gate_enabled = false to
                    # bypass a persistent gate bug.
                    logger.exception(
                        "invoke: gate evaluation raised unexpectedly — "
                        "failing closed and blocking this turn"
                    )
                    return ClaudeResult(
                        response_text=(
                            "BLOCKED: the operator-message gate failed to "
                            "evaluate, so this turn was stopped rather than "
                            "run unenforced. Check the bridge logs for the "
                            "gate error; set interrupts.tool_call_gate_enabled "
                            "= false to bypass while it is being fixed."
                        ),
                        is_error=False,
                    )

            _sess_token = log_format._session_id.set(session_id or "")

            # -- E1.1: Hard-stop pre-flight on context pressure overflow --
            # Fires BEFORE subprocess spawn so the agent always finishes its
            # current turn before stopping (tool_call_gate.py invariant).
            # Uses a float pressure proxy from _session_pressure_for_hard_stop()
            # (session_manager not imported here; callers may set it via
            # _hard_stop_pressure_override for testability — see below).
            if session_id and getattr(self.config, "context_pressure_hard_stop_enabled", False):
                try:
                    _hs_pressure = getattr(self, "_hard_stop_pressure_override", None)
                    if _hs_pressure is not None and should_hard_stop_from_float(
                        _hs_pressure, hard_stop_enabled=True
                    ):
                        handoff_text = format_handoff_message(capsule_id=session_id)
                        logger.warning(
                            "Context pressure hard-stop (pressure=%.2f, session=%s). "
                            "Emitting handoff and capturing checkpoint.",
                            _hs_pressure, session_id,
                        )
                        try:
                            capture_checkpoint(
                                session_id=session_id,
                                message_count=0,
                                estimated_tokens=0,
                                active_task_titles=[],
                                workflow_state={"hard_stop_pressure": _hs_pressure},
                                checkpoint_dir=str(
                                    Path(self.config.data_dir) / "checkpoints"
                                ),
                            )
                        except Exception as _cp_err:
                            logger.warning(
                                "capture_checkpoint failed at hard-stop (non-fatal): %s",
                                _cp_err,
                            )
                        # D7.8 — operator-visible signal on every compaction.
                        # Daily log entry so the operator can correlate quality
                        # shifts with compaction events. Best-effort; never
                        # blocks the hard-stop return path.
                        try:
                            from .daily_log import DailyLogWriter
                            DailyLogWriter(self.config).append(
                                f"context compaction fired "
                                f"(pressure={_hs_pressure:.2f}, session={session_id[:8]})",
                                category="event",
                            )
                        except Exception as _dl_err:
                            logger.debug(
                                "daily_log append failed at hard-stop (non-fatal): %s",
                                _dl_err,
                            )
                        log_format._session_id.reset(_sess_token)
                        return ClaudeResult(
                            response_text=handoff_text,
                            session_id=session_id,
                            is_error=False,
                        )
                except Exception as _hs_err:
                    logger.warning(
                        "Hard-stop check failed (non-fatal, falling through): %s", _hs_err
                    )

            start_time = time.monotonic()
            self._last_activity = start_time

            capability_misroute = _capability_misroute_result(
                config=self.config,
                backend=self._backend,
                mcp_config_path=mcp_config_path,
                allowed_tools=allowed_tools,
                start_time=start_time,
            )
            if capability_misroute is not None:
                try:
                    log_format._session_id.reset(_sess_token)
                except (LookupError, ValueError):
                    log_format._session_id.set("")
                return capability_misroute

            if getattr(self._backend, "transport", "subprocess") == "http":
                try:
                    return await self._invoke_http_backend(
                        message=message,
                        system_prompt_file=system_prompt_file,
                        on_first_text=on_first_text,
                        on_text_delta=on_text_delta,
                        start_time=start_time,
                    )
                finally:
                    try:
                        log_format._session_id.reset(_sess_token)
                    except (LookupError, ValueError):
                        pass

            cmd = self._build_command(
                message, session_id, system_prompt_file, model=model,
                mcp_config_path=mcp_config_path,
                permission_mode=permission_mode,
                allowed_tools=allowed_tools,
            )
            events: list[StreamEvent] = []

            cwd = working_dir or self.config.claude_working_dir
            logger.info("Claude cmd: %s", " ".join(cmd))
            logger.info("Claude cwd: %s, session_id: %s", cwd, session_id)

            # Build environment: inherit parent + inject secrets for MCP ${VAR} resolution
            env = os.environ.copy()
            env.update(_load_secrets_as_env(self.config.data_dir))
            # Merge caller-supplied env vars (e.g. BUMBA_AGENT_DEPTH for write jail)
            if env_vars:
                env.update(env_vars)
            oauth_token = ""
            if self._token_provider and hasattr(self._token_provider, "access_token"):
                oauth_token = self._token_provider.access_token
            if not oauth_token:
                oauth_token = self.config.claude_oauth_token
            if oauth_token:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
                logger.info("Claude auth: CLAUDE_CODE_OAUTH_TOKEN set (%d chars)", len(oauth_token))

            # Backend-supplied auth env (no-op for Claude which returns {};
            # populated by HTTP/codex backends that inject their own creds).
            if self._backend is not None:
                env.update(self._backend.auth_env())

            try:
                self._process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                    start_new_session=True,
                    limit=1024 * 1024,  # 1MB line buffer (init event with MCP tools exceeds 64KB default)
                )

                # Feed the message via stdin to avoid CLI argument parsing issues
                if self._process.stdin:
                    self._process.stdin.write(message.encode())
                    await self._process.stdin.drain()
                    self._process.stdin.close()
                    await self._process.stdin.wait_closed()

                # Write PID file
                if self._process.pid:
                    self._pid_file.write_text(str(self._process.pid))

                # Start watchdog
                watchdog_task = asyncio.create_task(self._watchdog())

                # Read stdout line by line
                if self._process.stdout is None:
                    raise RuntimeError("Claude subprocess stdout is None — subprocess created without stdout=PIPE")
                halt_flag = Path(self.config.data_dir) / "halt.flag"
                _halt_check_counter = 0
                _HALT_CHECK_INTERVAL = 10  # check every 10 lines
                # D7.9 #1421 — mid-stream operator-message interrupt.
                # When set, operator_interrupt_acked_at records when the bridge
                # decided to yield the in-flight tool call so the operator
                # message can be addressed at the next turn boundary. The
                # difference from the message's received_at is the ack
                # latency — exposed via the result for tracing.
                operator_interrupt_pending: list = []
                operator_interrupt_acked_at: float | None = None
                while True:
                    line = await self._process.stdout.readline()
                    if not line:
                        break
                    self._last_activity = time.monotonic()

                    # Periodic halt flag + operator-inbox checks — terminate
                    # mid-run if operator halts OR if a new operator message
                    # has landed since the last check (D7.9 #1421).
                    _halt_check_counter += 1
                    if _halt_check_counter >= _HALT_CHECK_INTERVAL:
                        _halt_check_counter = 0
                        # audit-2026-05-16.C.02 — HaltPolicy mid-stream check.
                        # When a policy is wired, it is the unified halt
                        # source; the direct file check is the back-compat
                        # fallback. Either path drives the same group
                        # termination so MCP servers/tool subprocesses die
                        # with the parent (P1.2 / audit C2).
                        halt_continue_blocked: bool = False
                        halt_reason: str | None = None
                        if self._halt_policy is not None:
                            cont_decision = self._halt_policy.check_continue(
                                self._halt_surface
                            )
                            if cont_decision.blocked:
                                halt_continue_blocked = True
                                halt_reason = cont_decision.reason
                        elif halt_flag.exists():
                            halt_continue_blocked = True
                            halt_reason = "halt flag set"

                        if halt_continue_blocked:
                            logger.warning(
                                "Halt detected mid-run — terminating Claude "
                                "subprocess (pid=%s surface=%s reason=%s)",
                                self._process.pid,
                                self._halt_surface,
                                halt_reason,
                            )
                            await self._terminate_process_group("halt_flag")
                            break
                        # D7.9 — operator-message interrupt. Mirrors the halt
                        # path but yields gracefully: SIGTERM the subprocess,
                        # capture the pending list + ack timestamp, then break
                        # out so the post-stream return path can return the
                        # block message via the existing tool_call_gate
                        # plumbing. The next-turn boundary's gate evaluation
                        # (already wired at lines 535-559) re-asserts the
                        # block until the agent emits [ACK:msg_id] markers.
                        if self._operator_inbox is not None:
                            try:
                                pending_now = await self._operator_inbox.pending()
                            except Exception:
                                logger.exception(
                                    "invoke: mid-stream pending() raised — "
                                    "continuing without interrupt check"
                                )
                                pending_now = []
                            if pending_now:
                                operator_interrupt_pending = pending_now
                                operator_interrupt_acked_at = time.time()
                                logger.warning(
                                    "Operator message detected mid-run — yielding "
                                    "Claude subprocess (pid=%s, pending=%d)",
                                    self._process.pid,
                                    len(pending_now),
                                )
                                # P1.2 (audit C2): group termination — same
                                # rationale as the halt-flag path above. Tool
                                # subprocesses spawned by Claude during the
                                # in-flight turn must not survive the yield.
                                await self._terminate_process_group(
                                    "operator_interrupt"
                                )
                                break

                    decoded = line.decode("utf-8", errors="replace")
                    event = self._backend.parse_event(decoded)
                    if event:
                        events.append(event)
                        # Fire on_first_text as soon as first assistant text arrives
                        if on_first_text and event.type == "assistant" and event.text:
                            try:
                                on_first_text(event.text)
                            except Exception as cb_err:
                                logger.debug("on_first_text callback error: %s", cb_err)
                            on_first_text = None  # fire once only
                        # Sprint 07.13 — route every assistant text event
                        # through the on_text_delta callback so the bridge
                        # can hand off to StreamCoalescer for batching. Sync,
                        # best-effort: a misbehaving callback must not crash
                        # the stream-read loop.
                        if on_text_delta and event.type == "assistant" and event.text:
                            try:
                                on_text_delta(event.text)
                            except Exception as cb_err:
                                logger.debug("on_text_delta callback error: %s", cb_err)

                # Wait for process exit
                await self._process.wait()
                watchdog_task.cancel()
                try:
                    await watchdog_task
                except asyncio.CancelledError:
                    pass

                # Read stderr
                stderr = ""
                if self._process.stderr:
                    stderr_bytes = await self._process.stderr.read()
                    stderr = stderr_bytes.decode("utf-8", errors="replace")

                exit_code = self._process.returncode or 0
                elapsed_ms = int((time.monotonic() - start_time) * 1000)

                logger.info(
                    "Claude exit=%d, events=%d, stderr=%r, elapsed=%dms",
                    exit_code, len(events), stderr[:500], elapsed_ms,
                )

                # Build result from events
                result = _process_events(events)
                result.exit_code = exit_code
                result.stderr_output = stderr
                result.duration_ms = elapsed_ms

                # Classify errors if exit code non-zero
                if exit_code != 0 and not result.error_type:
                    result.error_type = _classify_error(exit_code, stderr)
                    result.is_error = True

                # D7.9 #1421 — operator-message interrupt overlay.
                # If the read-loop broke because a new operator message
                # arrived mid-stream, replace the response_text with the
                # gate's block message so the agent acknowledges before
                # continuing, and record ack latency for tracing.
                if operator_interrupt_pending:
                    try:
                        from .tool_call_gate import evaluate_gate
                        gate_result = await evaluate_gate(
                            self._operator_inbox,
                            min_pending=getattr(self.config, "min_pending_to_gate", 1),
                        )
                        result.response_text = gate_result.block_message
                        result.is_error = False
                        # SIGTERM exit codes are not bridge errors here —
                        # the interrupt was the desired outcome. Clear the
                        # error_type that may have been set by the
                        # exit-code classifier above.
                        result.error_type = ""
                    except Exception:
                        logger.exception(
                            "invoke: post-interrupt gate evaluation raised — "
                            "returning pending-message summary instead"
                        )
                        ids = ", ".join(m.id for m in operator_interrupt_pending)
                        result.response_text = (
                            f"INTERRUPTED: {len(operator_interrupt_pending)} "
                            f"operator message(s) pending ({ids}). Acknowledge "
                            "before continuing work."
                        )
                        result.is_error = False
                        result.error_type = ""

                    # Compute ack latency from the oldest pending message's
                    # received_at — that's the earliest the bridge could
                    # have observed the interrupt. Logged as a `ack_latency_ms`
                    # attribute on a tracing span so p50/p95 rollups derive
                    # from the existing JSONL surface (no new sink). The
                    # span's literal start/end times are point-in-time;
                    # callers reading the JSONL should use the attribute.
                    if operator_interrupt_acked_at is not None:
                        try:
                            oldest = min(
                                operator_interrupt_pending,
                                key=lambda m: m.received_at,
                            )
                            received_ts = oldest.received_at.timestamp()
                            ack_latency_ms = int(
                                (operator_interrupt_acked_at - received_ts) * 1000
                            )
                            from .tracing import get_tracer
                            tracer = get_tracer("bridge.operator_interrupt")
                            with tracer.context_span(
                                "operator_msg_ack_latency",
                                attributes={
                                    "session_id": session_id or "",
                                    "msg_id": oldest.id,
                                    "pending_count": len(
                                        operator_interrupt_pending
                                    ),
                                    "ack_latency_ms": ack_latency_ms,
                                },
                            ):
                                pass
                            logger.info(
                                "operator_msg_ack_latency_ms=%d session=%s "
                                "pending=%d",
                                ack_latency_ms,
                                session_id,
                                len(operator_interrupt_pending),
                            )
                        except Exception:
                            logger.exception(
                                "invoke: ack latency telemetry failed (non-fatal)"
                            )

                # Scan for canary token leakage
                if result.response_text:
                    cleaned, leaked_tokens = _scan_for_canary(result.response_text)
                    if leaked_tokens:
                        logger.warning(
                            "SECURITY: Canary token leaked in Claude response: %s",
                            leaked_tokens,
                        )
                        result.response_text = cleaned

                logger.info(
                    "Claude result: is_error=%s, error_type=%r, response=%r",
                    result.is_error, result.error_type, result.response_text[:200] if result.response_text else "",
                )

                return result

            except Exception as e:
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                logger.error("Claude spawn_error: %s: %s", type(e).__name__, e)
                return ClaudeResult(
                    is_error=True,
                    error_type="spawn_error",
                    stderr_output=str(e),
                    duration_ms=elapsed_ms,
                )
            finally:
                self._process = None
                if self._pid_file.exists():
                    self._pid_file.unlink(missing_ok=True)
                # Sprint 07.11 — restore caller's session_id context. Reset
                # always fires (even on exception) so a failed invocation
                # cannot leak its session_id into the next handler's logs.
                # The token was set just outside ``async with self._lock``;
                # ``ContextVar.reset`` is robust to any path through the
                # locked body, including the early-return on success and
                # the spawn_error fallback.
                try:
                    log_format._session_id.reset(_sess_token)
                except (LookupError, ValueError):
                    # Token was set in a different context (defensive — should
                    # not happen since we set in the same coroutine); fall
                    # back to clearing rather than crashing the cleanup path.
                    log_format._session_id.set("")

    # -- S49: Watchdog timer --

    async def _watchdog(self) -> None:
        """Monitor Claude subprocess for timeout conditions."""
        start = self._last_activity
        hard_warned = False

        while True:
            await asyncio.sleep(5)

            if self._process is None:
                return

            now = time.monotonic()
            idle = now - self._last_activity
            elapsed = now - start

            # Absolute timeout: force kill
            if elapsed >= self.config.claude_absolute_timeout:
                logger.error(
                    "Absolute timeout (%ds) reached, killing Claude",
                    self.config.claude_absolute_timeout,
                )
                await self._kill_process()
                return

            # Soft timeout: no output for claude_timeout seconds
            if idle >= self.config.claude_timeout:
                logger.warning(
                    "Soft timeout (%ds idle), killing Claude", self.config.claude_timeout
                )
                await self._kill_process()
                return

            # Hard timeout warning (but don't kill)
            if elapsed >= self.config.claude_hard_timeout and not hard_warned:
                logger.warning(
                    "Hard timeout (%ds elapsed), Claude still running",
                    self.config.claude_hard_timeout,
                )
                hard_warned = True

    async def _terminate_process_group(self, reason: str) -> None:
        """SIGTERM → wait 10s → SIGKILL the process group.

        P1.2 (audit C2): the subprocess is spawned with
        ``start_new_session=True`` (see ``invoke()`` and
        ``WarmClaudeProcess.spawn()``), which puts the Claude parent into a
        new session/process group as the child *after* fork — never the
        bridge daemon itself. Signaling the group via ``killpg`` therefore
        reaches Claude AND every child it forked (MCP servers, tool
        subprocesses) without ever touching the bridge.

        Used by the watchdog timeout path, the mid-run halt-flag path
        (``invoke()`` stream loop), and the operator-message interrupt path
        (D7.9 #1421). All three must reach the whole process group or
        orphan tool subprocesses survive past the bridge's "halted" /
        "blocked" report.
        """
        proc = self._process
        if proc is None or proc.returncode is not None:
            return

        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            return

        logger.info(
            "Process-group SIGTERM sent (reason=%s, pid=%s, pgid=%s)",
            reason, proc.pid, pgid,
        )

        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
                logger.warning(
                    "Process-group SIGKILL escalation (reason=%s, pid=%s, pgid=%s)",
                    reason, proc.pid, pgid,
                )
            except (ProcessLookupError, OSError):
                pass

    async def _kill_process(self) -> None:
        """Backwards-compat alias for the watchdog and ``kill_current``.

        Delegates to ``_terminate_process_group`` so all three teardown
        paths (watchdog, halt, operator interrupt) share one implementation.
        """
        await self._terminate_process_group("watchdog_or_kill_current")

    # -- S50: Error classification and stale cleanup --

    async def kill_current(self) -> bool:
        """Kill the currently running Claude process (for /cancel)."""
        if self._process is None:
            return False
        await self._kill_process()
        return True

    async def cleanup_stale(self) -> None:
        """Kill orphan Claude processes from a previous bridge run."""
        if not self._pid_file.exists():
            return
        try:
            pid = int(self._pid_file.read_text().strip())
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            logger.info("Killed stale Claude process (PID %d)", pid)
        except (ValueError, ProcessLookupError, OSError):
            pass
        finally:
            self._pid_file.unlink(missing_ok=True)


    async def invoke_haiku_for_decomposition(
        self,
        prompt: str,
        *,
        max_tokens: int = 2000,
    ) -> "ClaudeResult":
        """One-shot Haiku invocation for WorkOrder decomposition.

        Runs the full prompt as a stateless (no session-resume) Haiku
        call. Sprint D1.6 -- called only from make_haiku_decomposer.
        """
        return await self.invoke(
            message=prompt,
            session_id=None,
            model="haiku",
            working_dir=self.config.claude_working_dir,
        )


# -- Warm persistent process for voice --

class WarmClaudeProcess:
    """Persistent Claude process that stays alive across messages.

    Uses --input-format stream-json to accept NDJSON messages on stdin,
    eliminating per-message subprocess spawn and MCP server initialization
    overhead (~5-10s savings per message).

    Used as the default text message path for haiku/sonnet. Opus messages
    fall back to one-shot ClaudeRunner.invoke() for isolation.
    """

    def __init__(self, config: BridgeConfig, token_provider: object | None = None) -> None:
        self._config = config
        self._token_provider = token_provider
        # Backend default mirrors ClaudeRunner.__init__ (P0.01): the warm
        # reader loop delegates stream parsing to self._backend.parse_event,
        # so the warm process needs its own backend instance. ClaudeBackend is
        # the in-place default; future backends register via the same seam.
        self._backend: BackendProtocol = ClaudeBackend(config)
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._response_queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._session_id: str | None = None
        # Stored for auto-respawn
        self._working_dir: str = ""
        self._model: str = "haiku"
        self._system_prompt_file: str | None = None
        # P1.1 (audit C1) — optional InvocationController for unified
        # one-shot/warm in-flight state. See ClaudeRunner._track_invocation.
        self._invocation_controller: object | None = None
        # Sprint D8.3 — background respawn guard (set True while a respawn task
        # is in flight, prevents double-spawn if reader exits twice in quick
        # succession).
        self._respawn_in_progress: bool = False

    def set_invocation_controller(self, controller: object) -> None:
        """Wire an InvocationController for unified in-flight state (P1.1).

        When set, ``send_message()`` calls ``controller.track(path="warm", ...)``
        around its work so app-level interrupt detection can see the
        invocation regardless of which path is in flight.
        """
        self._invocation_controller = controller

    def _track_invocation(self):
        """Return a context manager that records warm invocation state."""
        if self._invocation_controller is None:
            return _NullInvocationTracker()
        return self._invocation_controller.track(
            path="warm",
            session_id=self._session_id,
        )

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def spawn(
        self,
        working_dir: str,
        model: str = "haiku",
        system_prompt_file: str | None = None,
    ) -> bool:
        """Start the persistent Claude process. Returns True on success."""
        if self.is_alive:
            return True

        self._working_dir = working_dir
        self._model = model
        self._system_prompt_file = system_prompt_file

        # Find binary
        binary = shutil.which("claude")
        if not binary:
            for candidate in (
                Path.home() / ".local" / "bin" / "claude",
                Path("/usr/local/bin/claude"),
            ):
                if candidate.is_file():
                    binary = str(candidate)
                    break
        if self._config.claude_binary:
            binary = self._config.claude_binary
        if not binary:
            logger.error(
                "WarmClaudeProcess: claude binary not found. "
                "Searched PATH and common locations. "
                "Install Claude Code or set claude_binary in bridge.toml."
            )
            return False

        cmd = [
            binary, "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", "10",
            "--dangerously-skip-permissions",
            "--model", model,
        ]

        # Sprint D8.1 / P1.4 — narrow warm-process MCP set when configured.
        # Drops spawn time from 30-120s to 3-8s by skipping init of the ~19
        # MCP servers warm-path conversational chat does not need.
        # `--strict-mcp-config` tells Claude to use ONLY the listed servers,
        # ignoring `.mcp.json` in the working directory.
        #
        # P1.4 fail-closed contract: when `warm_mcp_config` is explicitly set
        # but the resolved path does not exist on disk, refuse to spawn. The
        # alternative — silently inheriting `.mcp.json` — re-introduces the
        # 30-120s spawn we are trying to eliminate AND quietly broadens the
        # warm process's tool surface beyond what the operator approved. To
        # disable narrowing in a dev override, set `warm_mcp_config = ""`.
        warm_mcp = self._config.warm_mcp_config
        if warm_mcp:
            mcp_path = Path(warm_mcp)
            if not mcp_path.is_absolute():
                # Resolve relative paths against the agent root (current
                # working directory). The bridge's launchd plist sets
                # WorkingDirectory = /opt/bumba-harness/agent-flat/agent
                # (post-D6-bis canonical layout), so Path.cwd() is the
                # agent root for the daemon. Workstation invocations
                # (`python -m bridge` from agent/) also satisfy this
                # contract — both paths resolve `config/warm-core-mcp.json`
                # to a real file. The pre-D6-bis convention
                # `data_dir.parent / "agent" / warm_mcp` assumed
                # `~/data` and `~/agent` were siblings (D5 layout); under
                # D6-bis the runtime tree is `~/agent-flat/agent` so the
                # sibling math no longer resolves.
                mcp_path = Path.cwd() / warm_mcp
            if mcp_path.exists():
                cmd.extend(["--mcp-config", str(mcp_path), "--strict-mcp-config"])
                logger.info(
                    "WarmClaudeProcess: using narrow MCP config %s "
                    "(--strict-mcp-config enabled)",
                    mcp_path,
                )
            else:
                logger.error(
                    "WarmClaudeProcess: warm_mcp_config %s not found; "
                    "refusing to spawn (fail-closed). Set warm_mcp_config "
                    "to an existing file, or to \"\" to disable narrowing.",
                    mcp_path,
                )
                return False

        # Apply same security restrictions as one-shot
        for tool in self._config.security_disallowed_tools:
            cmd.extend(["--disallowedTools", tool])

        if system_prompt_file:
            cmd.extend(["--append-system-prompt-file", system_prompt_file])

        # Build environment with secrets + OAuth token
        env = os.environ.copy()
        env.update(_load_secrets_as_env(self._config.data_dir))
        oauth_token = ""
        if self._token_provider and hasattr(self._token_provider, "access_token"):
            oauth_token = self._token_provider.access_token
        if not oauth_token:
            oauth_token = self._config.claude_oauth_token
        if oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token

        logger.info("WarmClaudeProcess: spawning %s (model=%s, cwd=%s)", binary, model, working_dir)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env,
                start_new_session=True,
                limit=1024 * 1024,  # 1MB line buffer (init event with MCP tools exceeds 64KB default)
            )
            self._reader_task = asyncio.create_task(
                self._stdout_reader(), name="warm-claude-reader"
            )
            self._stderr_task = asyncio.create_task(
                self._stderr_reader(), name="warm-claude-stderr"
            )
            logger.info("WarmClaudeProcess: spawned PID %d", self._process.pid)

            # Send a warm-up message. Allow 120s for MCP server initialization
            # (16 servers can take 30-60s on first spawn) plus SessionStart hook.
            warmup_result = await self.send_message("hi", timeout_s=120.0)
            if warmup_result.is_error:
                logger.warning(
                    "WarmClaudeProcess: warmup failed: error_type=%s, response=%r, session=%s",
                    warmup_result.error_type,
                    warmup_result.response_text[:200] if warmup_result.response_text else "",
                    warmup_result.session_id,
                )
                await self.close()
                return False
            logger.info("WarmClaudeProcess: warmup complete, session_id=%s", self._session_id)

            return True
        except Exception as e:
            logger.error(
                "WarmClaudeProcess: spawn failed: %s. "
                "Check claude binary permissions and OAuth token validity.", e
            )
            self._process = None
            return False

    async def send_message(
        self,
        text: str,
        on_first_text: Callable[[str], None] | None = None,
        timeout_s: float = 30.0,
    ) -> ClaudeResult:
        """Send a message and wait for the result. Thread-safe via lock."""
        if not self.is_alive and self._working_dir:
            logger.info("WarmClaudeProcess: auto-respawning dead process")
            ok = await self.spawn(self._working_dir, self._model, self._system_prompt_file)
            if not ok:
                return ClaudeResult(is_error=True, error_type="respawn_failed")

        async with self._lock, self._track_invocation():
            start_time = time.monotonic()

            # Drain any stale events from previous turn
            while not self._response_queue.empty():
                try:
                    self._response_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            # Build NDJSON user message
            msg = json.dumps({
                "type": "user",
                "message": {"role": "user", "content": text},
            })

            try:
                if self._process is None or self._process.stdin is None:
                    raise RuntimeError("WarmClaudeProcess: process or stdin is None — process not spawned or already closed")
                self._process.stdin.write((msg + "\n").encode())
                await self._process.stdin.drain()
            except Exception as e:
                logger.error(
                    "WarmClaudeProcess: stdin write failed: %s. "
                    "The Claude subprocess may have crashed — will respawn.", e
                )
                return ClaudeResult(
                    is_error=True,
                    error_type="stdin_error",
                    stderr_output=str(e),
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            # Collect events until we get a result event or timeout
            events: list[StreamEvent] = []
            first_text_fired = False

            try:
                while True:
                    remaining = timeout_s - (time.monotonic() - start_time)
                    if remaining <= 0:
                        logger.warning("WarmClaudeProcess: timeout waiting for result")
                        return ClaudeResult(
                            is_error=True,
                            error_type="timeout",
                            duration_ms=int((time.monotonic() - start_time) * 1000),
                        )

                    event = await asyncio.wait_for(
                        self._response_queue.get(), timeout=remaining
                    )

                    if event is None:
                        # Process died
                        logger.warning("WarmClaudeProcess: process died mid-message")
                        result = _process_events(events)
                        result.is_error = True
                        result.error_type = "process_died"
                        result.duration_ms = int((time.monotonic() - start_time) * 1000)
                        return result

                    events.append(event)

                    # Capture session_id from init event
                    if event.type == "system" and event.subtype == "init" and event.session_id:
                        self._session_id = event.session_id

                    # Fire on_first_text callback
                    if (on_first_text and not first_text_fired
                            and event.type == "assistant" and event.text):
                        try:
                            on_first_text(event.text)
                        except Exception as cb_err:
                            logger.debug("on_first_text callback error: %s", cb_err)
                        first_text_fired = True

                    # Result event means this turn is complete
                    if event.type == "result":
                        result = _process_events(events)
                        result.duration_ms = int((time.monotonic() - start_time) * 1000)
                        logger.info(
                            "WarmClaudeProcess: response in %dms, cost=$%.4f, is_error=%s, error_type=%s, subtype=%s, response=%r",
                            result.duration_ms, result.cost_usd, result.is_error,
                            result.error_type, event.subtype,
                            result.response_text[:200] if result.response_text else "",
                        )
                        return result

            except asyncio.TimeoutError:
                logger.warning("WarmClaudeProcess: timeout waiting for events")
                result = _process_events(events)
                result.is_error = True
                result.error_type = "timeout"
                result.duration_ms = int((time.monotonic() - start_time) * 1000)
                return result

    async def _stderr_reader(self) -> None:
        """Background task: log stderr lines from Claude process."""
        if self._process is None or self._process.stderr is None:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    logger.warning("WarmClaudeProcess stderr: %s", decoded)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug("WarmClaudeProcess: stderr reader error: %s", e)

    async def _stdout_reader(self) -> None:
        """Background task: read stdout lines and push parsed events to queue."""
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("WarmClaudeProcess: cannot start reader — process or stdout is None")

        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break  # EOF — process exited
                decoded = line.decode("utf-8", errors="replace")
                event = self._backend.parse_event(decoded)
                if event:
                    if event.type == "result":
                        logger.debug("WarmClaudeProcess: raw result event: %s", decoded.strip()[:500])
                    await self._response_queue.put(event)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("WarmClaudeProcess: reader error: %s", e)
        finally:
            # Signal that the process is done
            await self._response_queue.put(None)
            self._process = None
            logger.info("WarmClaudeProcess: reader exited")

            # Sprint D8.3 — schedule background respawn so the next message
            # doesn't pay the cold-spawn cost inline. Only respawn if we have
            # a working_dir (i.e. the process was previously spawned, not a
            # fresh instance that was never started). Guard against
            # double-respawn via a flag.
            if self._working_dir and not getattr(self, "_respawn_in_progress", False):
                self._respawn_in_progress = True
                asyncio.create_task(
                    self._background_respawn(), name="warm-claude-respawn"
                )

    async def _background_respawn(self) -> None:
        """Respawn the warm process in the background after unexpected death.

        Sprint D8.3 — heals crashes between messages so the next operator
        message doesn't pay the cold-spawn cost inline. Bounded retry: 3
        attempts with exponential backoff (2s, 4s, 8s); after that, give up —
        the next message will fall through to one-shot.
        """
        try:
            for attempt in range(3):
                await asyncio.sleep(2 ** (attempt + 1))  # 2s, 4s, 8s
                if self.is_alive:
                    logger.info(
                        "Background respawn: process became alive on its own "
                        "(attempt %d), bailing",
                        attempt + 1,
                    )
                    return
                logger.info(
                    "Background respawn attempt %d for warm Claude process",
                    attempt + 1,
                )
                try:
                    ok = await self.spawn(
                        self._working_dir,
                        self._model,
                        self._system_prompt_file,
                    )
                    if ok:
                        logger.info(
                            "Background respawn succeeded on attempt %d",
                            attempt + 1,
                        )
                        return
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Background respawn attempt %d raised: %s",
                        attempt + 1,
                        exc,
                    )
            logger.error(
                "Background respawn: gave up after 3 attempts; "
                "next message will spawn inline"
            )
        finally:
            self._respawn_in_progress = False

    async def close(self) -> None:
        """Shut down the persistent process gracefully."""
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._reader_task = None
        self._stderr_task = None

        proc = self._process
        if proc is None or proc.returncode is not None:
            self._process = None
            return

        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            self._process = None
            return

        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

        self._process = None
        logger.info("WarmClaudeProcess: closed")

    async def cycle(self) -> bool:
        """Close and respawn the process (e.g. on session reset).

        Returns True if the new process spawned successfully.
        """
        logger.info("WarmClaudeProcess: cycling (close + respawn)")
        await self.close()
        if self._working_dir:
            return await self.spawn(self._working_dir, self._model, self._system_prompt_file)
        return False


# -- S50: Error classification (module-level) --

def _classify_error(exit_code: int, stderr: str) -> str:
    """Classify Claude Code error from exit code and stderr."""
    stderr_lower = stderr.lower()

    if exit_code == 127:
        return "binary_not_found"
    if exit_code == 137:
        return "oom"
    if exit_code == 139:
        return "segfault"
    if exit_code in (-15, -9):
        return "timeout"
    if exit_code == 1:
        if "auth" in stderr_lower:
            return "auth"
        if "rate" in stderr_lower or "overloaded" in stderr_lower or "limit" in stderr_lower:
            return "rate_limit"
        if "content" in stderr_lower or "filter" in stderr_lower:
            return "content_filter"
    return "unknown"
