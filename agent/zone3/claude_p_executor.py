"""Z3-02 — Claude Code ``claude -p`` executor contract for engineering specialists.

Premise (per the Z3-00 audit, ``agent/scripts/audit_zone3_engineering.py``):
the real ``claude -p`` subprocess chain already exists as ``SubagentExecutor``
+ ``ClaudeRunner``. This module does **not** add a second production subprocess
runner. It defines the deterministic *contract* the Zone 3 engineering
dispatcher consumes:

  - :func:`build_claude_p_argv`     — pure argv builder (no I/O).
  - :class:`EngineeringRunResult`   — frozen, structured result.
  - :func:`run_claude_p_specialist` — async runner whose process-spawn step is
    an injected callable, so unit tests and local CI never spawn real Claude.

Safety contract:
  - No Anthropic OAuth token or API key is placed in argv or environment by
    this executor. The child inherits the operator's installed Claude Code
    session via the parent environment only.
  - The prompt is delivered on stdin, never on argv (no secret/task leakage in
    process listings).
  - Logs redact argv and stderr snippets via :func:`redact_for_log`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from bridge.backends import BackendProtocol

log = logging.getLogger(__name__)

# Tokens that must never appear in argv, env, or logs surfaced by this module.
_FORBIDDEN_ENV_KEYS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

# Stable error classes — consumers (dispatcher, smoke matrix) match on these.
ERROR_FAILED = "claude_p_failed"
ERROR_MISSING_BINARY = "claude_p_missing_binary"
ERROR_TIMEOUT = "claude_p_timeout"
ERROR_SPAWN = "claude_p_spawn_error"


# A spawned process need only expose ``communicate`` (and optionally ``kill``).
SpawnFn = Callable[..., Awaitable[object]]


@dataclass(frozen=True)
class EngineeringRunResult:
    """Structured result of one engineering specialist Claude ``-p`` run."""

    specialist: str
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    error_class: str | None = None


def build_claude_p_argv(
    *,
    claude_binary: str,
    model: str | None = None,
    backend: BackendProtocol | None = None,
) -> list[str]:
    """Build the one-shot argv. Pure — no I/O, no secrets.

    The prompt is delivered on stdin by the caller, so it never appears here
    (``message=""`` when sourcing from a backend).

    When ``backend`` is provided, argv is sourced from
    ``backend.build_command`` so a non-Claude backend can drive the Z3
    executor. When omitted, the bounded hardcoded ``claude -p`` fallback is
    used — preserving the legacy contract the engineering dispatcher relies
    on today.
    """
    if backend is not None:
        if getattr(backend, "transport", "subprocess") == "http":
            raise ValueError("HTTP backend does not have a subprocess argv")
        return backend.build_command(message="", model=model)
    argv = [claude_binary, "-p"]
    if model:
        argv.extend(["--model", model])
    return argv


def redact_for_log(value: str) -> str:
    """Redact any forbidden auth material from a string before logging."""
    redacted = value
    for key in _FORBIDDEN_ENV_KEYS:
        redacted = redacted.replace(key, "[redacted]")
    return redacted


def _sanitize_env(env: Mapping[str, str] | None) -> dict[str, str]:
    """Return a copy of ``env`` with forbidden auth keys stripped.

    Bumba code never forwards Anthropic OAuth/API material into the child;
    the child relies on the operator's installed Claude Code session.
    """
    base = dict(env or {})
    for key in _FORBIDDEN_ENV_KEYS:
        base.pop(key, None)
    return base


async def _default_spawn(
    argv: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str] | None,
):  # pragma: no cover - exercised only by live smoke, never in unit CI.
    """Default process spawn — real subprocess. Mocked out in all unit tests."""
    return await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=dict(env) if env is not None else None,
    )


async def run_claude_p_specialist(
    *,
    claude_binary: str,
    specialist: str,
    prompt: str,
    cwd: str,
    timeout_seconds: int,
    model: str | None = None,
    env: Mapping[str, str] | None = None,
    spawn: SpawnFn = _default_spawn,
    backend: BackendProtocol | None = None,
) -> EngineeringRunResult:
    """Run one engineering specialist via ``claude -p`` and return a result.

    The ``spawn`` callable is injected so unit tests never start real Claude.
    All failure modes (missing binary, timeout, nonzero exit, spawn error)
    return a deterministic :class:`EngineeringRunResult` with a stable
    ``error_class`` rather than raising.
    """
    if backend is not None and getattr(backend, "transport", "subprocess") == "http":
        start = time.monotonic()
        try:
            request = getattr(backend, "request")
            raw = request(message=prompt, system_prompt=None)
            event = backend.parse_event(json.dumps(raw))
            if event is None or event.is_error:
                return _error_result(specialist, ERROR_FAILED, start, exit_code=1)
            return EngineeringRunResult(
                specialist=specialist,
                success=True,
                stdout=event.text,
                stderr="",
                exit_code=0,
                duration_seconds=time.monotonic() - start,
                error_class=None,
            )
        except Exception as exc:  # noqa: BLE001 — preserve deterministic result contract
            log.warning("HTTP specialist backend error: %s", redact_for_log(str(exc)))
            return _error_result(specialist, ERROR_SPAWN, start, exit_code=1)

    argv = build_claude_p_argv(
        claude_binary=claude_binary, model=model, backend=backend
    )
    safe_env = _sanitize_env(env)
    start = time.monotonic()

    try:
        proc = await spawn(argv, cwd=cwd, env=safe_env)
    except FileNotFoundError:
        log.warning("claude -p binary missing: %s", redact_for_log(claude_binary))
        return _error_result(specialist, ERROR_MISSING_BINARY, start, exit_code=127)
    except OSError as exc:
        log.warning("claude -p spawn error: %s", redact_for_log(str(exc)))
        return _error_result(specialist, ERROR_SPAWN, start, exit_code=1)

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        _best_effort_kill(proc)
        log.warning("claude -p timed out for specialist=%s", specialist)
        return _error_result(specialist, ERROR_TIMEOUT, start, exit_code=124)

    returncode = int(getattr(proc, "returncode", 0) or 0)
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    success = returncode == 0

    if not success:
        log.info(
            "claude -p specialist=%s exit=%s stderr=%s",
            specialist,
            returncode,
            redact_for_log(stderr[:200]),
        )

    return EngineeringRunResult(
        specialist=specialist,
        success=success,
        stdout=stdout,
        stderr=stderr,
        exit_code=returncode,
        duration_seconds=time.monotonic() - start,
        error_class=None if success else ERROR_FAILED,
    )


def _best_effort_kill(proc: object) -> None:
    killer = getattr(proc, "kill", None)
    if callable(killer):
        try:
            killer()
        except ProcessLookupError:  # pragma: no cover - race on already-exited proc
            pass


def _error_result(
    specialist: str,
    error_class: str,
    start: float,
    *,
    exit_code: int,
) -> EngineeringRunResult:
    return EngineeringRunResult(
        specialist=specialist,
        success=False,
        stdout="",
        stderr="",
        exit_code=exit_code,
        duration_seconds=time.monotonic() - start,
        error_class=error_class,
    )


class ClaudePExecutor:
    """Production ``_ExecutorLike`` adapter wrapping :func:`run_claude_p_specialist`.

    The :class:`~zone3.engineering_dispatcher.EngineeringDispatcher` consumes an
    object with an async ``run(*, specialist, prompt, cwd, timeout_seconds)``
    method. This adapter binds the configured ``claude`` binary path and an
    injectable ``spawn`` callable, then forwards each call to the deterministic
    runner. The ``spawn`` seam keeps the adapter unit-testable without a real
    Claude subprocess — the dispatcher + command handler can be driven end to
    end with a fake spawn.
    """

    def __init__(
        self,
        *,
        claude_binary: str = "claude",
        model: str | None = None,
        spawn: SpawnFn = _default_spawn,
        backend: BackendProtocol | None = None,
    ) -> None:
        self._binary = claude_binary
        self._model = model
        self._spawn = spawn
        self._backend = backend

    async def run(
        self,
        *,
        specialist: str,
        prompt: str,
        cwd: Path,
        timeout_seconds: int,
    ) -> EngineeringRunResult:
        return await run_claude_p_specialist(
            claude_binary=self._binary,
            specialist=specialist,
            prompt=prompt,
            cwd=str(cwd),
            timeout_seconds=timeout_seconds,
            model=self._model,
            spawn=self._spawn,
            backend=self._backend,
        )
