"""One-shot backend spawn helper (Sprint P4.01 — Phase 4 bypass decoupling).

The direct ``claude -p`` spawn sites in ``bridge/factory/triage.py`` and
``bridge/factory/implement.py`` hardcoded ``[str(CLAUDE_BIN), "-p", ...]`` and
ran a fresh synchronous subprocess per call. This helper preserves the
fresh-isolated-process semantics (NOT the warm ``ClaudeRunner`` session) while
routing argv assembly, binary resolution, and auth-env injection through a
``BackendProtocol``. Migrating the bypass sites onto this helper makes the
factory model-agnostic: flipping the backend swaps the CLI without touching
the call sites.

Synchronous by design — the factory pipeline is a serial batch job, mirroring
the ``subprocess.run`` shape the call sites already use. ``subprocess.run``'s
``TimeoutExpired`` propagates to the caller, which the factory maps to a
NEEDS_HUMAN verdict (matching the pre-migration behaviour).
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ._protocol import BackendProtocol


@dataclass(frozen=True)
class OneShotResult:
    """Frozen result of one fresh-subprocess backend invocation."""

    returncode: int
    stdout: str
    stderr: str


def spawn_one_shot(
    backend: BackendProtocol,
    *,
    prompt: str,
    timeout: int,
    permission_mode: str = "bypassPermissions",
    cwd: str | Path | None = None,
    model: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> OneShotResult:
    """Spawn a fresh, isolated one-shot subprocess via ``backend``.

    Argv is assembled by ``backend.build_command`` and the binary by
    ``backend.resolve_binary`` (a ``list[str]`` shim prefix is honoured). The
    prompt is delivered on stdin — never argv — so a dash-leading message does
    not get parsed as a flag and no task text leaks into process listings.

    Auth env from ``backend.auth_env()`` is merged over a copy of
    ``os.environ``; ``extra_env`` (e.g. mailbox vars) is layered last.

    Raises:
        subprocess.TimeoutExpired: propagated from ``subprocess.run`` so the
            caller can map a stuck process to its own terminal state.
    """
    if getattr(backend, "transport", "subprocess") == "http":
        request = getattr(backend, "request", None)
        if not callable(request):
            return OneShotResult(
                returncode=1,
                stdout="",
                stderr="HTTP backend does not expose request()",
            )
        try:
            raw = request(message=prompt, system_prompt=None)
            event = backend.parse_event(json.dumps(raw))
        except Exception as exc:  # noqa: BLE001 — one-shot callers expect rc/stderr
            return OneShotResult(returncode=1, stdout="", stderr=str(exc))
        if event is None or event.is_error:
            return OneShotResult(
                returncode=1,
                stdout=event.text if event is not None else "",
                stderr="HTTP backend returned no parseable completion",
            )
        return OneShotResult(returncode=0, stdout=event.text, stderr="")

    args = backend.build_command(
        message=prompt,
        permission_mode=permission_mode,
        model=model,
    )

    env = os.environ.copy()
    env.update(backend.auth_env())
    if extra_env:
        env.update(extra_env)

    proc = subprocess.run(
        args,
        input=prompt,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
    )
    return OneShotResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
