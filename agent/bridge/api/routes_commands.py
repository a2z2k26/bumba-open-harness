"""Commands routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. ``SAFE_COMMANDS`` lives on the
``APIServer`` class itself (it's accessed via ``self.SAFE_COMMANDS``),
so it stays in the main module.
"""
from __future__ import annotations

import json

from aiohttp import web

from ._helpers import _error, _ok


class _CommandsRoutesMixin:
    """Provides /api/commands handlers."""

    def _register_commands_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/commands", self._handle_list_commands)
        app.router.add_post("/api/commands", self._handle_dispatch_command)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _handle_list_commands(
        self, request: web.Request
    ) -> web.Response:
        """List available bridge commands."""
        from ..commands import BRIDGE_COMMANDS, AGENT_COMMANDS

        return _ok({
            "bridge_commands": sorted(BRIDGE_COMMANDS),
            "agent_commands": sorted(AGENT_COMMANDS),
            "safe_commands": sorted(self.SAFE_COMMANDS),
        })

    async def _handle_dispatch_command(
        self, request: web.Request
    ) -> web.Response:
        """Dispatch a bridge command."""
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        command = body.get("command", "")
        args = body.get("args", "")
        if not command:
            return _error("'command' field is required")
        if command not in self.SAFE_COMMANDS:
            return _error(
                f"Command '{command}' is not in the safe command whitelist. "
                f"Allowed: {', '.join(sorted(self.SAFE_COMMANDS))}"
            )
        commands_handler = self._bridge._commands
        if commands_handler is None:
            return _error("Command handler not available", 503)
        try:
            config = self._bridge._config
            chat_id = config.operator_discord_id if config else "api"
            result = await commands_handler.handle(chat_id, command, args)
            return _ok({"command": command, "result": result})
        except Exception as e:
            return _error(str(e), 500)
