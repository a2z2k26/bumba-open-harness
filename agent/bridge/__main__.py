"""Entry point for the Bumba bridge process: python -m bridge"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .log_format import CorrelationFilter, JSONFormatter


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="bridge",
        description="Bumba Autonomous Agent — Discord-Claude Bridge",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to bridge.toml (default: resolved via bridge.config._resolve_config_path — env var, cwd, or post-D6-bis canonical /opt/bumba-harness/agent-flat/agent/config/bridge.toml)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="bumba-bridge 0.1.0",
    )
    return parser.parse_args(argv)


def setup_logging(
    level: str,
    log_dir: str = "/opt/bumba-harness/logs",
    *,
    json_enabled: bool = False,
) -> None:
    """Configure stderr StreamHandler + RotatingFileHandler.

    Sprint 07.11 — installs ``CorrelationFilter`` on the root logger
    unconditionally so ``session_id`` / ``message_id`` fields are populated
    for whichever formatter is active. When ``json_enabled`` is True, every
    handler attached here uses ``JSONFormatter`` (one JSON line per record);
    otherwise the existing plain-text format is preserved.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Always install CorrelationFilter — cheap, populates fields both formats
    # share so downstream tooling sees consistent correlation IDs whether the
    # operator is reading plain text or piping JSON to a parser.
    root.addFilter(CorrelationFilter())

    formatter: logging.Formatter
    if json_enabled:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    # File handler (rotating, 10MB, 5 backups)
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path / "bridge.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def _peek_log_json_flag(config_path: str | None) -> bool:
    """Read just the ``logging.json_enabled`` flag from bridge.toml.

    Logging is set up before BridgeApp loads the full config (which also
    requires Discord secrets and would fail under tests / fresh installs).
    This peek is best-effort: any failure (missing file, malformed TOML,
    permission error) silently returns ``False`` so the bridge always boots
    with the existing plain-text format.
    """
    try:
        import tomllib

        from bridge.paths import agent_root

        if config_path:
            path = Path(config_path)
        else:
            path = agent_root() / "config" / "bridge.toml"
        if not path.is_file():
            return False
        with path.open("rb") as f:
            data = tomllib.load(f)
        return bool(data.get("logging", {}).get("json_enabled", False))
    except Exception:
        return False


def main(argv: list[str] | None = None) -> None:
    """Entry point: parse args, setup logging, run BridgeApp."""
    args = parse_args(argv)
    json_enabled = _peek_log_json_flag(args.config)
    setup_logging(args.log_level, json_enabled=json_enabled)

    logger = logging.getLogger(__name__)
    logger.info("Starting Bumba bridge...")

    from .app import BridgeApp

    app = BridgeApp(config_path=args.config)

    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
