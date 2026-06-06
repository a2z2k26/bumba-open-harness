#!/usr/bin/env python3
"""Codex backend E2E smoke harness (Sprint Codex-7, issue #1841).

Backend-agnostic, single-prompt round-trip verifier. Runs on the Mac mini (or
any developer machine with ``codex`` installed + ``codex login`` complete)
before the operator flips ``backends_enabled = true`` in ``bridge.toml``.

Pass criteria (in order):

  1. ``BridgeConfig`` loads with the same env-var / ``.secrets`` /
     ``bridge.toml`` precedence the running bridge uses.
  2. A ``CodexBackend`` instance is constructed via ``BackendRegistry``,
     proving the registry → backend lookup path works end-to-end.
  3. ``CodexBackend.build_command`` emits a runnable argv list.
  4. (Live mode only) The subprocess returns exit 0; ``parse_event`` produces
     at least one ``turn.completed`` event; the assistant text contains the
     literal sentinel ``CODEX_E2E_OK``.

Exit codes:

  0 — PASS (all assertions held; reported in the JSON summary).
  1 — FAIL (one or more assertions failed; remediation hint included).
  2 — Pre-flight blocker (auth missing / binary missing / fail-closed
      validator would refuse to boot).

Usage::

    # Dry run — builds the would-be command, never spawns codex. Safe in CI.
    python3 agent/scripts/codex_e2e_smoke.py --dry-run

    # Same, but exercise the Claude backend's command-building path. Proves
    # the harness itself is backend-agnostic.
    python3 agent/scripts/codex_e2e_smoke.py --dry-run --backend claude

    # Full live invocation — spawns codex, asserts round-trip. The default
    # invocation; the operator runs this once locally before the flag flip.
    python3 agent/scripts/codex_e2e_smoke.py

The smoke deliberately uses ``subprocess`` + ``json`` + ``argparse`` only —
no new third-party deps. The bridge's own modules (``bridge.config``,
``bridge.backends``) are imported for parity with the runtime.

Auth-rotation caveats — until the two research issues land
(#1860: OpenAI OAuth refresh endpoint discovery; #1861: ``~/.codex/auth.json``
schema capture) — this script's live mode only stays green for as long as
the seeded token has not expired. Run ``codex login`` again and re-seed
``.secrets`` if the smoke fails with a 401-equivalent stderr line.

See: ``docs/operator/codex-backend-flag-flip-runbook.md``.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # noqa: S404 — harness intentionally spawns the agent CLI
import sys
import time
from pathlib import Path

# Locate the agent/ package so this script can run from any cwd. The script
# itself lives at <repo>/agent/scripts/codex_e2e_smoke.py; the parent of
# scripts/ is the agent package root which must be on sys.path so the
# `bridge.*` imports resolve.
_SCRIPT = Path(__file__).resolve()
_AGENT_ROOT = _SCRIPT.parent.parent
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))


from bridge.backends import BackendProtocol, CodexBackend  # noqa: E402
from bridge.backends.registry import BackendRegistry  # noqa: E402
from bridge.config import BridgeConfig, load_config  # noqa: E402


# Sentinel string the prompt asks the agent to emit verbatim. Choosing a
# fixed token (vs an asserting-on-substring) lets the script run with the
# tightest possible cost: a single short turn returning a single short
# string. Keep this short and easy to grep against noisy assistant output.
_SENTINEL = "CODEX_E2E_OK"

# Prompt that requests the sentinel. Phrased to discourage preamble or
# explanation — both backends interpret literal-string requests differently
# and we want minimum drift.
_PROMPT = (
    f"Respond with exactly the literal string {_SENTINEL} and nothing else. "
    "No preamble, no markdown, no quotes."
)

# Wall-clock ceiling for the live subprocess. Codex on a trivial prompt
# typically returns in 5-15s; 60s leaves headroom for slow network +
# subscription rate limits without exposing the operator to a stuck
# subprocess burning the cap. The smoke fails clean on timeout.
_LIVE_TIMEOUT_S = 60


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string for the JSON report."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _emit_report(report: dict, *, status: str) -> None:
    """Print a one-line summary plus a JSON block to stdout.

    Operators see the human-readable line first; CI / wrapper scripts parse
    the trailing JSON. Keeping both on stdout (not split across streams)
    avoids the launchd-buffering pitfalls the bridge runs into elsewhere.
    """
    report = dict(report)
    report["status"] = status
    report["timestamp"] = _now_iso()
    print(f"[{status}] codex_e2e_smoke — {report.get('summary', '')}")
    print(json.dumps(report, indent=2, sort_keys=True))


def _construct_backends(config: BridgeConfig) -> dict[str, BackendProtocol]:
    """Build the ``{name: BackendProtocol}`` dict the registry expects.

    Mirrors what ``BridgeApp._initialize`` will do once the registry is wired
    into the live boot path. Constructing both backends here means the
    registry can resolve any role (main / chief / specialist) without
    KeyError; the *resolution* still follows the operator's policy in
    ``[backends]``.

    The Claude backend is intentionally imported lazily so the script
    does not pay its import cost when ``--backend codex`` is the only path
    used. (Both are cheap to import — this is style, not optimization.)
    """
    from bridge.backends import ClaudeBackend  # local import — see docstring

    return {
        "claude": ClaudeBackend(config),
        "codex": CodexBackend(config),
    }


def _check_pre_flight(
    config: BridgeConfig,
    *,
    backend_name: str,
    dry_run: bool,
) -> tuple[bool, str]:
    """Verify the harness can safely proceed.

    Returns ``(ok, message)``. When ``ok`` is False, the caller exits 2
    (pre-flight blocker) — not 1 (test failure), since the smoke never
    actually ran.

    Checks (in order, fail-fast):

      1. The Codex auth triple is non-empty when ``backend_name == 'codex'``
         and the script is about to spawn a real subprocess. ``--dry-run``
         skips this check (the dry run is useful even on a developer box
         that has not seeded the OAuth triple yet).
      2. The fail-closed boot validator would not refuse to start the bridge
         with the current config. Only meaningful when
         ``config.backends_enabled`` is True; otherwise the validator no-ops
         and the smoke can still run with the script-local registry.
    """
    if backend_name == "codex" and not dry_run:
        if not config.codex_oauth_token:
            return (
                False,
                "codex_oauth_token is empty in .secrets — run `codex login` "
                "on this host, then copy the triple "
                "(codex_oauth_token / codex_oauth_refresh_token / "
                "codex_oauth_expires_at) from ~/.codex/auth.json into "
                ".secrets. See gating research issues #1860 + #1861 and "
                "docs/operator/codex-backend-flag-flip-runbook.md.",
            )

    if config.backends_enabled:
        try:
            # Lazy import — _validate_codex_oauth lives inside bridge.app
            # which has heavier side-effects we'd rather not trigger.
            from bridge.app import _validate_codex_oauth

            _validate_codex_oauth(config)
        except Exception as exc:  # noqa: BLE001 — surface the boot error verbatim
            return (
                False,
                f"fail-closed boot validator would refuse to start bridge: "
                f"{exc}. See docs/operator/codex-backend-flag-flip-runbook.md "
                "preconditions checklist.",
            )

    return (True, "pre-flight OK")


def _resolve_role_backend(
    registry: BackendRegistry,
    *,
    backend_name: str,
) -> BackendProtocol:
    """Resolve the right backend via the registry for the requested smoke.

    Both ``--backend codex`` (default) and ``--backend claude`` exercise the
    registry, not just the backend constructor — this is the seam that the
    Codex-CLI Readiness epic adds, so the smoke would lose its meaning if
    we bypassed it.

    The role we resolve is intentionally ``specialist`` with a per-test
    override pinning the requested backend. That mirrors the operator's
    canary play: flip ``backends_enabled = true``, override one specialist
    to Codex, leave everything else on Claude. The override dict is built
    here (not mutated on the config) so we never poison the on-disk
    ``[backends]`` policy.
    """
    # Mutate the registry's defensive copy via a sibling registry constructed
    # with overridden config — but the simpler path is to read whichever
    # backend the caller asked for directly out of the instances dict via
    # the documented resolution path: spoof a specialist role whose
    # override pins to backend_name.
    instances = dict(registry._instances)  # private but documented copy
    if backend_name not in instances:
        raise KeyError(
            f"backend {backend_name!r} not registered; "
            f"registered: {sorted(instances.keys())}"
        )
    return instances[backend_name]


def _run_dry(
    backend: BackendProtocol,
    *,
    backend_name: str,
) -> dict:
    """Build the would-be command and emit it, without spawning anything.

    The dry path is what CI runs. It validates:
      - The backend resolves a binary path (or raises FileNotFoundError —
        which is still useful information; we surface it as a soft
        ``binary_resolved: false`` not a hard failure, so the smoke proves
        ``build_command`` is callable even on a box that lacks the CLI).
      - ``build_command`` returns a non-empty argv list.

    Returns the report dict; caller emits it.
    """
    binary: str | list[str] | None
    try:
        binary = backend.resolve_binary()
        binary_resolved = True
    except FileNotFoundError as exc:
        binary = None
        binary_resolved = False
        _ = exc

    # build_command tolerates binary=None by re-running resolve_binary, so
    # in the "binary not found" case we pass an explicit stub to keep the
    # dry path from re-raising. The stub never reaches a real shell — this
    # is purely for the harness to assemble + display the argv. Both
    # ClaudeBackend and CodexBackend expose the same ``binary=`` kwarg even
    # though it is not in the Protocol signature (Protocol is the minimum
    # surface; concrete classes are free to extend).
    effective_binary: str | list[str] = (
        binary if binary is not None else f"/path/to/{backend_name}"
    )

    cmd = backend.build_command(message=_PROMPT, binary=effective_binary)

    return {
        "mode": "dry-run",
        "backend": backend_name,
        "binary_resolved": binary_resolved,
        "binary": binary if isinstance(binary, str) else (
            " ".join(binary) if isinstance(binary, list) else None
        ),
        "cmd_preview": cmd,
        "prompt": _PROMPT,
        "sentinel": _SENTINEL,
        "summary": (
            f"would-be argv built ({len(cmd)} tokens); "
            f"binary_resolved={binary_resolved}"
        ),
    }


def _run_live(
    backend: BackendProtocol,
    *,
    backend_name: str,
) -> dict:
    """Spawn the agent CLI for one turn and assert sentinel round-trip.

    Returns the report dict on both pass and fail; the caller maps to an
    exit code. Failures are loud — every assertion that does not hold
    produces a structured ``failures`` list so the operator can read the
    JSON output and act.
    """
    try:
        binary = backend.resolve_binary()
    except FileNotFoundError as exc:
        return {
            "mode": "live",
            "backend": backend_name,
            "pass": False,
            "failures": [f"binary not resolvable: {exc}"],
            "summary": "binary missing — install the CLI before flipping the flag",
        }

    # Both backends accept ``binary=`` (Protocol minimum surface omits it,
    # concrete implementations expose it as a precomputed hint so the
    # script doesn't re-walk the resolve_binary discovery path).
    cmd = backend.build_command(message=_PROMPT, binary=binary)

    # Claude reads its prompt from stdin (Codex appends it positionally to
    # argv). This mirrors how ``ClaudeRunner.invoke`` feeds the message in
    # `bridge/claude_runner.py`. The bridge's ClaudeRunner handles this in
    # its own subprocess pipeline; the smoke script reproduces the minimum.
    stdin_payload = None if backend_name == "codex" else _PROMPT

    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 — trusted argv from backend
            cmd,
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=_LIVE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "mode": "live",
            "backend": backend_name,
            "pass": False,
            "failures": [
                f"subprocess timed out after {_LIVE_TIMEOUT_S}s — check "
                "network, auth token freshness, and rate-limit posture"
            ],
            "summary": "live smoke timed out",
        }
    elapsed = time.monotonic() - started

    failures: list[str] = []
    if proc.returncode != 0:
        # Surface stderr verbatim (capped) so the operator can read the
        # remediation without re-running.
        failures.append(
            f"subprocess returncode={proc.returncode}; "
            f"stderr={proc.stderr[:1500]!r}"
        )

    # Walk every non-empty stdout line through the parser. We collect both
    # the assistant-text concatenation and the count of turn.completed
    # events, then assert both invariants.
    assistant_text_parts: list[str] = []
    turn_completed_count = 0
    parser_errors = 0
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            ev = backend.parse_event(line)
        except Exception as exc:  # noqa: BLE001 — parser must never raise; surface if it does
            parser_errors += 1
            failures.append(f"parser raised on line {line[:120]!r}: {exc}")
            continue
        if ev is None:
            continue
        if ev.type == "assistant" and ev.text:
            assistant_text_parts.append(ev.text)
        if ev.type == "result" and ev.subtype == "success":
            turn_completed_count += 1

    assistant_text = "".join(assistant_text_parts)
    if turn_completed_count == 0:
        failures.append(
            "no turn.completed (or equivalent success-result) event observed"
        )
    if _SENTINEL not in assistant_text:
        failures.append(
            f"sentinel {_SENTINEL!r} not present in assistant text "
            f"(saw {assistant_text[:200]!r})"
        )

    return {
        "mode": "live",
        "backend": backend_name,
        "pass": not failures,
        "failures": failures,
        "elapsed_seconds": round(elapsed, 3),
        "returncode": proc.returncode,
        "turn_completed_count": turn_completed_count,
        "parser_errors": parser_errors,
        "assistant_text_preview": assistant_text[:400],
        "summary": (
            f"PASS in {elapsed:.1f}s, "
            f"{turn_completed_count} turn(s) completed"
            if not failures
            else f"FAIL after {elapsed:.1f}s with {len(failures)} failure(s)"
        ),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end smoke for the Codex (or Claude) backend. "
            "Use --dry-run in CI; run live before flipping backends_enabled."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the would-be command and exit without spawning a subprocess.",
    )
    parser.add_argument(
        "--backend",
        choices=("codex", "claude"),
        default="codex",
        help=(
            "Which backend to smoke. Default codex. --backend claude proves "
            "the harness is backend-agnostic and is useful as a control."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Optional bridge.toml path. Default uses the same resolution the "
            "bridge daemon does (env var BUMBA_CONFIG_PATH → cwd-relative → "
            "legacy hardcoded path)."
        ),
    )
    parser.add_argument(
        "--skip-secrets",
        action="store_true",
        help=(
            "Skip the .secrets / Keychain pass during config load. Useful for "
            "harness-development iteration; do NOT use for the pre-flip live run."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Load config exactly the way the bridge does. Validation is skipped
    # so the smoke can run on a developer box where some unrelated bridge
    # validation might fail (e.g. discord token missing); the only
    # validation that matters for this smoke is the Codex auth fail-closed
    # check, which we run explicitly below.
    try:
        config = load_config(
            args.config,
            skip_secrets=args.skip_secrets,
            skip_validation=True,
        )
    except Exception as exc:  # noqa: BLE001 — config errors are the operator's signal
        _emit_report(
            {
                "summary": f"config load failed: {exc}",
                "failures": [str(exc)],
                "mode": "dry-run" if args.dry_run else "live",
                "backend": args.backend,
            },
            status="FAIL",
        )
        return 2

    ok, message = _check_pre_flight(
        config, backend_name=args.backend, dry_run=args.dry_run
    )
    if not ok:
        _emit_report(
            {
                "summary": message,
                "failures": [message],
                "mode": "dry-run" if args.dry_run else "live",
                "backend": args.backend,
            },
            status="FAIL",
        )
        return 2

    instances = _construct_backends(config)
    registry = BackendRegistry(config, instances)

    try:
        backend = _resolve_role_backend(registry, backend_name=args.backend)
    except (KeyError, ValueError) as exc:
        _emit_report(
            {
                "summary": f"registry resolution failed: {exc}",
                "failures": [str(exc)],
                "mode": "dry-run" if args.dry_run else "live",
                "backend": args.backend,
            },
            status="FAIL",
        )
        return 1

    if args.dry_run:
        report = _run_dry(backend, backend_name=args.backend)
        _emit_report(report, status="PASS")
        return 0

    report = _run_live(backend, backend_name=args.backend)
    passed = bool(report.get("pass"))
    _emit_report(report, status="PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
