"""Guarded one-message OpenRouter smoke through the bridge message path.

This script does not start the daemon, touch launchd, connect Discord, bind the
API server, or process the production queue. It initializes a temporary
OpenRouter-main ``BridgeApp`` instance, replaces Discord with an in-memory
sink, enqueues one message, and lets the real ``ClaudeRunner`` make exactly one
OpenRouter request after the operator opens the live gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping, Sequence
from unittest.mock import patch

from bridge.app import BridgeApp
from bridge.backends.openrouter import OpenRouterBackend
from bridge.claude_runner import ClaudeResult

DEFAULT_SMOKE_MODEL = "z-ai/glm-4.6"
DEFAULT_PROMPT = "Reply with exactly: BUMBA_OPENROUTER_BRIDGE_MESSAGE_OK"
DEFAULT_MAX_COST_USD = Decimal("0.02")


class _MemoryDiscord:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.alerts: list[str] = []
        self.typing_started: list[str] = []
        self.typing_stopped: list[str] = []

    def _start_typing(self, chat_id: str) -> None:
        self.typing_started.append(chat_id)

    def _stop_typing(self, chat_id: str) -> None:
        self.typing_stopped.append(chat_id)

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to: int | None = None,
    ) -> None:
        self.sent_messages.append(
            {"chat_id": chat_id, "text": text, "reply_to": reply_to}
        )

    async def send_alert(self, text: str) -> None:
        self.alerts.append(text)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL", DEFAULT_SMOKE_MODEL),
        help="OpenRouter model id for the single bridge-message smoke request.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt for the single bridge-message smoke request.",
    )
    parser.add_argument(
        "--max-cost-usd",
        default=str(DEFAULT_MAX_COST_USD),
        help="Fail if a known returned cost exceeds this cap.",
    )
    return parser.parse_args(argv)


def _fail(message: str, *, rc: int = 2) -> int:
    print(message, file=sys.stderr)
    return rc


def _json_cost_amount(amount: float) -> str:
    text = f"{amount:.12f}".rstrip("0").rstrip(".")
    return text or "0"


def _bridge_toml_text(
    *,
    data_dir: Path,
    log_dir: Path,
    working_dir: Path,
    model: str,
) -> str:
    return f"""\
[bridge]
data_dir = "{data_dir}"
log_dir = "{log_dir}"
heartbeat_interval = 60

[discord]

[claude]
timeout = 120
hard_timeout = 600
absolute_timeout = 1800
max_turns = 25
output_format = "stream-json"
working_dir = "{working_dir}"
max_retries = 3

[session]
idle_timeout = 1800
max_file_size = 31457280
max_errors = 3

[memory]
context_window = 20
max_context_tokens = 4000
summary_count = 3

[security]
disallowed_tools = []
tool_failure_threshold = 5
tool_failure_window = 600
crash_loop_threshold = 5
crash_loop_window = 600
db_size_warn = 524288000
db_size_alert = 1073741824

[api]
enabled = false

[checkin]
enabled = false

[briefing]
enabled = false

[fallback]
openrouter_model = "{model}"

[budget]
daily_budget = 0.0

[agents]
max_invocation_depth = 3

[backends]
enabled = true
main = "openrouter"
chiefs_default = "openrouter"
specialists_default = "openrouter"
specialists_overrides = {{}}

[openrouter]
default_model = "{model}"

[evaluator]
enabled = false
"""


async def _ensure_smoke_database_connected(app: BridgeApp) -> None:
    """Ensure the temporary smoke database is open before queue operations."""
    if app._db is None:
        raise RuntimeError(
            "bridge smoke database was not initialized; verify PYTHONPATH points "
            "at the checkout containing this script"
        )
    if getattr(app._db, "_conn", None) is not None:
        return

    await app._db.connect()
    await app._db.migrate()


async def _run_live_bridge_message(
    *,
    api_key: str,
    model: str,
    prompt: str,
) -> dict[str, object]:
    with TemporaryDirectory(prefix="bumba-openrouter-bridge-smoke-") as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        log_dir = root / "logs"
        working_dir = root / "agent"
        data_dir.mkdir()
        log_dir.mkdir()
        working_dir.mkdir()
        config_path = root / "bridge.toml"
        config_path.write_text(
            _bridge_toml_text(
                data_dir=data_dir,
                log_dir=log_dir,
                working_dir=working_dir,
                model=model,
            )
        )

        secrets = {
            "discord_bot_token": "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.FAKE.abcdef",
            "operator_discord_id": "7565124764",
            "openrouter_api_key": api_key,
        }

        with patch("bridge.config._load_secrets", return_value=secrets):
            app = BridgeApp(config_path=str(config_path))
            await app._initialize()
            await _ensure_smoke_database_connected(app)

        if not isinstance(app._claude._backend, OpenRouterBackend):
            raise RuntimeError(
                f"expected OpenRouterBackend, got {type(app._claude._backend).__name__}"
            )
        if app._warm_claude is not None:
            raise RuntimeError("warm Claude was constructed for OpenRouter main")

        discord = _MemoryDiscord()
        app._discord = discord
        app._evaluator = None

        results: list[ClaudeResult] = []
        original_invoke = app._claude.invoke

        async def _invoke_spy(*args: object, **kwargs: object) -> ClaudeResult:
            result = await original_invoke(*args, **kwargs)
            results.append(result)
            return result

        app._claude.invoke = _invoke_spy

        request_count = 0
        backend = app._claude._backend
        original_request = backend.request

        def _request_once(*args: object, **kwargs: object) -> object:
            nonlocal request_count
            request_count += 1
            if request_count > 1:
                raise RuntimeError("OpenRouter bridge smoke attempted a second request")
            return original_request(*args, **kwargs)

        backend.request = _request_once

        original_subprocess_exec = asyncio.create_subprocess_exec

        def _fail_subprocess_boundary(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("OpenRouter bridge smoke touched subprocess boundary")

        asyncio.create_subprocess_exec = _fail_subprocess_boundary
        try:
            await app._queue.enqueue(1, "openrouter-bridge-smoke", prompt)
            msg = await app._queue.dequeue()
            if msg is None:
                raise RuntimeError("bridge smoke queue did not return the message")
            await app._process_single_message(msg)

            if not results:
                raise RuntimeError("bridge smoke did not invoke ClaudeRunner")
            result = results[0]
            if result.is_error or not result.response_text:
                detail = result.stderr_output or "Bridge message returned no response text"
                raise RuntimeError(f"{result.error_type or 'empty_response'}: {detail}")
            if request_count != 1:
                raise RuntimeError(
                    f"expected exactly one OpenRouter request, got {request_count}"
                )
            if not discord.sent_messages:
                raise RuntimeError("bridge smoke did not deliver a mocked Discord response")

            status = await app._queue.get_queue_status()
            return {
                "backend": "openrouter",
                "model": model,
                "response_id": result.cost_raw_usage_id or result.session_id or None,
                "session_id": result.session_id or None,
                "cost": {
                    "amount_usd": _json_cost_amount(result.cost_usd),
                    "source": result.cost_source
                    or ("unknown" if result.cost_unknown else "measured_or_estimated"),
                    "unknown": result.cost_unknown,
                },
                "duration_ms": result.duration_ms,
                "text_length": len(result.response_text),
                "text_preview": result.response_text[:240],
                "live_call_count": request_count,
                "queue_completed": status["counts"].get("completed", 0),
                "mocked_discord_messages": len(discord.sent_messages),
                "warm_claude_enabled": False,
                "daemon_started": False,
                "launchd_touched": False,
                "discord_network_connected": False,
                "api_started": False,
            }
        finally:
            asyncio.create_subprocess_exec = original_subprocess_exec
            if app._db:
                await app._db.close()


def _parse_cost_cap(raw: str) -> Decimal:
    try:
        cap = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid --max-cost-usd value: {raw!r}") from exc
    if cap <= 0:
        raise ValueError("--max-cost-usd must be positive")
    return cap


def _known_cost_exceeds_cap(summary: Mapping[str, object], cap: Decimal) -> bool:
    cost = summary.get("cost")
    if not isinstance(cost, Mapping) or bool(cost.get("unknown")):
        return False
    amount = Decimal(str(cost.get("amount_usd", "0") or "0"))
    return amount > cap


async def _run(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    if env.get("BUMBA_ALLOW_LIVE") != "1":
        return _fail(
            "Refusing live OpenRouter bridge-message smoke: set "
            "BUMBA_ALLOW_LIVE=1 only for an operator-approved live validation."
        )

    api_key = str(env.get("OPENROUTER_API_KEY", "") or "")
    if not api_key:
        return _fail(
            "Refusing live OpenRouter bridge-message smoke: "
            "OPENROUTER_API_KEY is required."
        )

    args = _parse_args(argv)
    try:
        max_cost = _parse_cost_cap(args.max_cost_usd)
        summary = await _run_live_bridge_message(
            api_key=api_key,
            model=args.model,
            prompt=args.prompt,
        )
    except Exception as exc:  # noqa: BLE001 - stable CLI failure surface
        print(
            f"OpenRouter bridge-message smoke failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    if _known_cost_exceeds_cap(summary, max_cost):
        amount = summary["cost"]["amount_usd"]  # type: ignore[index]
        print(
            "OpenRouter bridge-message smoke failed: known cost "
            f"{amount} exceeded cap {max_cost}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    return asyncio.run(_run(argv, environ=environ))


if __name__ == "__main__":
    raise SystemExit(main())
