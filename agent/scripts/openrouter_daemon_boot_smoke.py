"""Guarded OpenRouter daemon boot smoke preflight.

Default mode is intentionally offline: it loads the requested bridge config,
runs the same startup validators used by ``BridgeAppInit``, and verifies that
OpenRouter main routing disables warm Claude startup. It does not start the
daemon, touch launchd, connect Discord, bind APIs, process queued messages, or
make live model calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping, Sequence
from unittest.mock import patch

from bridge.app_init import (
    _validate_backend_readiness,
    _validate_claude_oauth_required,
    _validate_codex_cost_readiness,
    _validate_codex_oauth,
    _validate_openrouter_api_key_required,
    _warm_claude_enabled_for_config,
)
from bridge.config import load_config

DAEMON_GATE_ENV = "BUMBA_ALLOW_DAEMON_SMOKE"
LIVE_GATE_ENV = "BUMBA_ALLOW_LIVE"
CHILD_GATE_ENV = "BUMBA_DAEMON_SMOKE_CHILD"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the staging bridge.toml to inspect.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Reserved timeout for the later operator-gated daemon run.",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        default=True,
        help="Compatibility flag; this preflight never makes live calls.",
    )
    parser.add_argument(
        "--start-daemon",
        action="store_true",
        help="Run the operator-gated local daemon lifecycle smoke.",
    )
    parser.add_argument(
        "--_child-daemon",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def _fail(message: str, *, rc: int = 2) -> int:
    print(message, file=sys.stderr)
    return rc


def _backend_name(config: object, attr: str) -> str:
    return str(getattr(config, attr, "") or "").strip().lower()


def _run_startup_validators(config: object) -> None:
    """Run startup validators that precede daemon side effects."""
    _validate_codex_oauth(config)
    _validate_openrouter_api_key_required(config)
    _validate_backend_readiness(config)
    _validate_claude_oauth_required(config)
    _validate_codex_cost_readiness(config)


def _build_report(
    *,
    config_path: Path,
    config: object,
    timeout_seconds: float,
    start_requested: bool,
) -> dict[str, object]:
    warm_claude_enabled = _warm_claude_enabled_for_config(config)
    return {
        "status": "preflight_passed",
        "mode": "offline_preflight",
        "config_path": str(config_path),
        "timeout_seconds": timeout_seconds,
        "backends_enabled": bool(getattr(config, "backends_enabled", False)),
        "main_backend": _backend_name(config, "backends_main"),
        "chiefs_backend": _backend_name(config, "backends_chiefs_default"),
        "specialists_backend": _backend_name(
            config, "backends_specialists_default"
        ),
        "openrouter_default_model": str(
            getattr(config, "openrouter_default_model", "") or ""
        ),
        "openrouter_key_present": bool(
            str(getattr(config, "openrouter_api_key", "") or "")
        ),
        "warm_claude_enabled": warm_claude_enabled,
        "would_construct_warm_claude": warm_claude_enabled,
        "would_start_daemon": start_requested,
        "launchd_touched": False,
        "live_model_calls": False,
        "discord_started": False,
        "api_started": False,
        "message_processing_started": False,
    }


def _preflight_errors(report: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if report["backends_enabled"] is not True:
        errors.append("[backends].enabled must be true for OpenRouter staging")
    if report["main_backend"] != "openrouter":
        errors.append("[backends].main must be 'openrouter'")
    if report["openrouter_key_present"] is not True:
        errors.append("openrouter_api_key must be present via .secrets")
    if report["warm_claude_enabled"] is not False:
        errors.append("warm Claude must be disabled for OpenRouter main")
    if report["would_construct_warm_claude"] is not False:
        errors.append("preflight would construct warm Claude")
    return errors


def _redact_secrets(text: str) -> str:
    text = re.sub(r"sk-or-[A-Za-z0-9._-]+", "sk-or-REDACTED", text)
    text = re.sub(
        r"(OPENROUTER_API_KEY\s*=\s*)\S+",
        r"\1REDACTED",
        text,
    )
    return text


def _bounded_text(text: str, *, limit: int = 4000) -> str:
    redacted = _redact_secrets(text)
    if len(redacted) <= limit:
        return redacted
    return redacted[:limit] + "\n...[truncated]"


async def _noop_async(*_args: object, **_kwargs: object) -> None:
    return None


async def _no_message_processing(self: object) -> None:
    shutdown_event = getattr(self, "_shutdown_event")
    await shutdown_event.wait()


async def _run_child_daemon_cycle(
    *,
    config_path: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    from bridge.app import APIServer, BridgeApp, DiscordBot, HealthServer
    from bridge.backends.http_base import HttpBackend

    def _fail_live_http(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("VAL-07 daemon smoke attempted a live HTTP backend call")

    def _fail_subprocess(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("VAL-07 daemon smoke attempted a subprocess boundary")

    started_at = time.monotonic()
    app = BridgeApp(config_path=str(config_path))
    task: asyncio.Task[None] | None = None
    with (
        patch.object(DiscordBot, "start", _noop_async),
        patch.object(DiscordBot, "send_message", _noop_async),
        patch.object(DiscordBot, "send_alert", _noop_async),
        patch.object(DiscordBot, "stop", _noop_async),
        patch.object(HealthServer, "start", _noop_async),
        patch.object(HealthServer, "stop", _noop_async),
        patch.object(APIServer, "start", _noop_async),
        patch.object(APIServer, "stop", _noop_async),
        patch.object(BridgeApp, "_process_messages", _no_message_processing),
        patch.object(HttpBackend, "request", _fail_live_http),
        patch.object(asyncio, "create_subprocess_exec", _fail_subprocess),
    ):
        task = asyncio.create_task(app.start())
        try:
            while time.monotonic() - started_at < timeout_seconds:
                if task.done():
                    await task
                    raise RuntimeError(
                        "BridgeApp.start() exited before reaching steady state"
                    )
                if getattr(app, "_processing_task", None) is not None:
                    warm_claude_enabled = bool(getattr(app, "_warm_claude", None))
                    if warm_claude_enabled:
                        raise RuntimeError(
                            "VAL-07 daemon smoke constructed warm Claude"
                        )
                    app._shutdown_event.set()
                    await asyncio.wait_for(task, timeout=max(1.0, timeout_seconds))
                    elapsed = time.monotonic() - started_at
                    return {
                        "status": "lifecycle_passed",
                        "mode": "local_no_connect_child",
                        "pid": os.getpid(),
                        "elapsed_seconds": round(elapsed, 3),
                        "config_path": str(config_path),
                        "steady_state_reached": True,
                        "warm_claude_enabled": warm_claude_enabled,
                        "processing_task_started": True,
                        "discord_network_connected": False,
                        "api_started": False,
                        "health_server_bound": False,
                        "message_processing_started": False,
                        "live_model_calls": False,
                        "launchd_touched": False,
                    }
                await asyncio.sleep(0.05)
            raise TimeoutError(
                f"BridgeApp did not reach steady state within {timeout_seconds}s"
            )
        finally:
            if task is not None and not task.done():
                app._shutdown_event.set()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    task.cancel()


def _run_child_daemon_entry(*, config_path: Path, timeout_seconds: float) -> int:
    if os.environ.get(CHILD_GATE_ENV) != "1":
        return _fail("Refusing internal daemon child without child gate.")
    try:
        report = asyncio.run(
            _run_child_daemon_cycle(
                config_path=config_path,
                timeout_seconds=timeout_seconds,
            )
        )
    except Exception as exc:  # noqa: BLE001 - stable child failure surface
        return _fail(
            "OpenRouter daemon lifecycle child failed: "
            f"{type(exc).__name__}: {_redact_secrets(str(exc))}",
            rc=1,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _run_daemon_lifecycle_smoke(
    *,
    config_path: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    env = os.environ.copy()
    env.pop("BUMBA_ALLOW_LIVE", None)
    env.pop("OPENROUTER_API_KEY", None)
    env[CHILD_GATE_ENV] = "1"
    command = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "--config",
        str(config_path),
        "--timeout",
        str(timeout_seconds),
        "--_child-daemon",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        env=env,
        text=True,
        timeout=timeout_seconds + 5.0,
        check=False,
    )
    stdout = _bounded_text(result.stdout)
    stderr = _bounded_text(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            "daemon lifecycle child exited "
            f"{result.returncode}; stdout={stdout!r}; stderr={stderr!r}"
        )
    try:
        child_report = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"daemon lifecycle child did not emit JSON: {stdout!r}"
        ) from exc
    return {
        "status": "lifecycle_passed",
        "mode": "guarded_daemon_lifecycle",
        "config_path": str(config_path),
        "timeout_seconds": timeout_seconds,
        "child_returncode": result.returncode,
        "child_report": child_report,
        "daemon_started": True,
        "daemon_stopped": True,
        "launchd_touched": False,
        "live_model_calls": False,
        "discord_network_connected": False,
        "api_started": False,
        "message_processing_started": False,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    args = _parse_args(argv)

    if env.get(LIVE_GATE_ENV) == "1":
        return _fail(
            f"Refusing daemon boot smoke while {LIVE_GATE_ENV}=1 is set; "
            "VAL-07 must not make live model calls."
        )

    if args._child_daemon:
        config_path = Path(args.config).expanduser()
        return _run_child_daemon_entry(
            config_path=config_path,
            timeout_seconds=args.timeout,
        )

    config_path = Path(args.config).expanduser()
    try:
        config = load_config(config_path)
        _run_startup_validators(config)
        report = _build_report(
            config_path=config_path,
            config=config,
            timeout_seconds=args.timeout,
            start_requested=bool(args.start_daemon),
        )
    except Exception as exc:  # noqa: BLE001 - stable CLI failure surface
        return _fail(
            "OpenRouter daemon boot preflight failed while loading startup "
            f"state: {type(exc).__name__}: {exc}",
            rc=1,
        )

    errors = _preflight_errors(report)
    if errors:
        for error in errors:
            print(f"OpenRouter daemon boot preflight failed: {error}", file=sys.stderr)
        return 1

    if args.start_daemon:
        if env.get(DAEMON_GATE_ENV) != "1":
            return _fail(
                "Refusing to start the daemon: set "
                f"{DAEMON_GATE_ENV}=1 only after operator approval for "
                "the VAL-07 daemon lifecycle gate."
            )
        try:
            lifecycle_report = _run_daemon_lifecycle_smoke(
                config_path=config_path,
                timeout_seconds=args.timeout,
            )
        except Exception as exc:  # noqa: BLE001 - stable CLI failure surface
            return _fail(
                "OpenRouter daemon lifecycle smoke failed: "
                f"{type(exc).__name__}: {_redact_secrets(str(exc))}",
                rc=1,
            )
        print(json.dumps(lifecycle_report, indent=2, sort_keys=True))
        return 0

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
