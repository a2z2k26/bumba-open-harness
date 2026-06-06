"""Before/after hook contract for the experiment loop.

Concept-only port of the karpathy/autoresearch (MIT) idea that the
iteration body should be transparent to operators: hooks are shell
scripts the operator drops into a directory, and the orchestrator
runs them with a strict contract — no code changes required to add
observability, pre-flight checks, or post-iteration cleanup.

## Contract

Hooks live in two phase-specific directories::

    agent/scripts/hooks/before-experiment/
    agent/scripts/hooks/after-experiment/

Each hook is an executable shell script (mode 0755). The runner picks
them up in alphabetical order by filename so operators can sequence
hooks with numeric prefixes (``00-``, ``50-``, ``99-``).

For every hook the runner:

1. Encodes the iteration metadata as one-line JSON and pipes it on
   stdin.
2. Captures stdout (combined with stderr) up to ``OUTPUT_CAP_BYTES``
   (8 KB). Anything beyond is dropped and a ``truncated`` flag is set.
3. Enforces a ``HOOK_TIMEOUT_SECONDS`` (30 s) wall-clock cap. A timed
   out hook is killed; ``HookResult.timed_out`` is set.
4. Tries to parse stdout as JSON. If parsing succeeds the value is
   exposed via ``HookResult.directives`` (steering signals); otherwise
   ``HookResult.output`` holds the plain text.
5. Logs but never raises. A non-zero exit, timeout, or unexpected
   exception flows back as a ``HookResult`` so the loop keeps running.

The runner is intentionally tiny and synchronous — the experiment
loop only fires hooks at iteration boundaries, so there is no need
for an event loop or thread pool. Keeping it synchronous also makes
the timeout semantics easy to reason about for operators writing
their first hook.
"""

from __future__ import annotations

import json
import logging
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger("experiment-loop._hook_runner")

# ── Constants ─────────────────────────────────────────────────────

# 8 KB output cap. Anything beyond is truncated; the surplus is
# dropped on the floor (we don't even read it from the pipe — we
# truncate after-the-fact for simplicity).
OUTPUT_CAP_BYTES: int = 8 * 1024

# 30-second wall-clock cap. A hook stuck past this is killed.
HOOK_TIMEOUT_SECONDS: int = 30

HookPhase = Literal["before", "after"]

_PHASE_DIRS: dict[HookPhase, str] = {
    "before": "before-experiment",
    "after": "after-experiment",
}

# Resolve the hooks root to ``agent/scripts/hooks/`` regardless of
# where the runner is imported from. The orchestrator lives in
# ``agent/scripts/`` so the parent of this file is the right anchor.
HOOKS_ROOT: Path = Path(__file__).resolve().parent / "hooks"


# ── Result type ───────────────────────────────────────────────────


@dataclass(frozen=True)
class HookResult:
    """Outcome of a single hook invocation.

    Frozen so the orchestrator cannot retroactively rewrite hook
    history mid-iteration.
    """

    name: str
    phase: HookPhase
    exit_code: int
    output: str
    directives: dict[str, Any] | None = None
    timed_out: bool = False
    truncated: bool = False
    error: str | None = field(default=None)


# ── Discovery ─────────────────────────────────────────────────────


def _list_hook_scripts(phase: HookPhase) -> list[Path]:
    """Return executable hook scripts for ``phase`` in alphabetical order.

    Non-executable files, hidden dotfiles, and ``.gitkeep`` are
    skipped silently — those are operator-facing markers, not hooks.
    """
    phase_dir = HOOKS_ROOT / _PHASE_DIRS[phase]
    if not phase_dir.is_dir():
        return []

    candidates: list[Path] = []
    for entry in sorted(phase_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_file():
            continue
        if entry.name.startswith(".") or entry.name == ".gitkeep":
            continue
        try:
            mode = entry.stat().st_mode
        except OSError:
            continue
        # Require any execute bit so operators can disable a hook by
        # `chmod -x` without renaming/moving the file.
        if not (mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
            continue
        candidates.append(entry)
    return candidates


# ── Single-hook execution ────────────────────────────────────────


def _execute_hook(
    script: Path,
    phase: HookPhase,
    metadata: dict[str, Any],
) -> HookResult:
    """Run ``script`` once and translate its outcome into a ``HookResult``.

    Never raises. The orchestrator must be free to fan out hooks
    knowing one bad script cannot tear down the loop.
    """
    try:
        stdin_payload = json.dumps(metadata, default=str)
    except (TypeError, ValueError) as exc:
        log.warning(
            "Could not encode hook metadata for %s: %s — using empty payload",
            script.name,
            exc,
        )
        stdin_payload = "{}"

    try:
        completed = subprocess.run(
            [str(script)],
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=HOOK_TIMEOUT_SECONDS,
            cwd=str(script.parent),
        )
    except subprocess.TimeoutExpired as exc:
        # ``exc.output`` may be bytes or str depending on subprocess version.
        partial_raw = exc.output or ""
        partial = (
            partial_raw.decode("utf-8", errors="replace")
            if isinstance(partial_raw, (bytes, bytearray))
            else str(partial_raw)
        )
        truncated_partial, was_truncated = _cap_output(partial)
        log.warning(
            "Hook %s/%s exceeded %ds timeout — killed",
            phase,
            script.name,
            HOOK_TIMEOUT_SECONDS,
        )
        return HookResult(
            name=script.name,
            phase=phase,
            exit_code=-1,
            output=truncated_partial,
            directives=None,
            timed_out=True,
            truncated=was_truncated,
            error=f"timeout after {HOOK_TIMEOUT_SECONDS}s",
        )
    except (OSError, ValueError) as exc:
        log.warning("Hook %s/%s failed to launch: %s", phase, script.name, exc)
        return HookResult(
            name=script.name,
            phase=phase,
            exit_code=-1,
            output="",
            directives=None,
            timed_out=False,
            truncated=False,
            error=str(exc),
        )

    raw_stdout = completed.stdout or ""
    if completed.stderr:
        raw_stdout = f"{raw_stdout}\n[stderr]\n{completed.stderr}"

    output, truncated = _cap_output(raw_stdout)
    if truncated:
        log.warning(
            "Hook %s/%s output exceeded %d bytes — truncated",
            phase,
            script.name,
            OUTPUT_CAP_BYTES,
        )

    directives = _maybe_parse_directives(output)

    if completed.returncode != 0:
        log.warning(
            "Hook %s/%s exited with code %d (loop continues)",
            phase,
            script.name,
            completed.returncode,
        )

    return HookResult(
        name=script.name,
        phase=phase,
        exit_code=completed.returncode,
        output=output,
        directives=directives,
        timed_out=False,
        truncated=truncated,
        error=None,
    )


def _cap_output(text: str) -> tuple[str, bool]:
    """Truncate ``text`` to ``OUTPUT_CAP_BYTES`` UTF-8 bytes.

    Returns ``(capped_text, was_truncated)``. Truncation is byte-aware
    (we re-decode after the cut so we never split a multi-byte codepoint).
    """
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= OUTPUT_CAP_BYTES:
        return text, False
    cut = encoded[:OUTPUT_CAP_BYTES].decode("utf-8", errors="replace")
    return cut, True


def _maybe_parse_directives(text: str) -> dict[str, Any] | None:
    """Return parsed directives if ``text`` is a JSON object, else ``None``.

    The contract requires a JSON object specifically — a bare list,
    string, or number on stdout is treated as plain log output. This
    keeps "I just echoed a message" hooks distinguishable from
    "I'm steering the loop" hooks.
    """
    stripped = text.strip()
    if not stripped or not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ── Public entry point ────────────────────────────────────────────


def run_hooks(
    phase: HookPhase,
    metadata: dict[str, Any],
) -> list[HookResult]:
    """Run every hook for ``phase`` in alphabetical order.

    Returns a list of ``HookResult`` — one per hook fired. An empty
    or missing hook directory yields an empty list with no error.

    Never raises. A misbehaving hook (timeout, crash, non-zero exit)
    is logged and surfaced via its ``HookResult`` so callers can
    record outcomes without taking down the loop.
    """
    if phase not in _PHASE_DIRS:
        log.warning("Unknown hook phase %r — skipping", phase)
        return []

    scripts = _list_hook_scripts(phase)
    if not scripts:
        return []

    # Pass operators a defensive copy + the phase tag — hooks should
    # not be able to mutate the orchestrator's metadata dict, and a
    # phase tag means a single hook script can serve both directories
    # if the operator symlinks it.
    payload = dict(metadata)
    payload.setdefault("phase", phase)

    results: list[HookResult] = []
    for script in scripts:
        results.append(_execute_hook(script, phase, payload))
    return results


def summarize_results(results: list[HookResult]) -> str:
    """One-line summary suitable for the daily log / Discord blob."""
    if not results:
        return "no hooks fired"
    parts: list[str] = []
    for r in results:
        if r.timed_out:
            parts.append(f"{r.name}=timeout")
        elif r.exit_code != 0:
            parts.append(f"{r.name}=exit{r.exit_code}")
        elif r.directives:
            parts.append(f"{r.name}=ok+directives")
        else:
            parts.append(f"{r.name}=ok")
    return ", ".join(parts)


# ── First-run scaffolding ─────────────────────────────────────────


def ensure_hook_dirs() -> None:
    """Create the two hook directories if they don't already exist.

    Safe to call at every iteration start — ``mkdir(parents=True,
    exist_ok=True)`` is a no-op when the directories are present.
    """
    for phase_dir in _PHASE_DIRS.values():
        try:
            (HOOKS_ROOT / phase_dir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Could not create hook dir %s: %s", phase_dir, exc)


# Backward-compat helper: file-system permissions on hook scripts. We
# never re-permission an operator-supplied file, but if a future helper
# wants to scaffold one we expose the canonical bits here.
HOOK_SCRIPT_MODE = 0o755


def is_executable(script: Path) -> bool:
    """Return ``True`` when ``script`` has at least one execute bit set."""
    try:
        return bool(script.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    except OSError:
        return False


__all__ = [
    "HOOKS_ROOT",
    "HOOK_SCRIPT_MODE",
    "HOOK_TIMEOUT_SECONDS",
    "HookResult",
    "OUTPUT_CAP_BYTES",
    "ensure_hook_dirs",
    "is_executable",
    "run_hooks",
    "summarize_results",
]
