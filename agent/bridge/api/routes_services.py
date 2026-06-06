"""Services route (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. The /api/services handler is
heavy enough (launchctl fan-out, state-file enumeration) to own its
own module.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web

from bridge.services.state_inventory import iter_known_service_state_files

from ._helpers import _ok


class _ServicesRoutesMixin:
    """Provides the /api/services handler."""

    def _register_services_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/services", self._handle_services)

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------

    async def _handle_services(self, request: web.Request) -> web.Response:
        """Return LaunchDaemon service states."""
        config = self._bridge._config
        if config is None:
            return _ok({"services": {}})

        service_dir = Path(config.data_dir) / "service_state"
        if not service_dir.exists():
            return _ok({"services": {}})

        services = {}
        for name, state_file in iter_known_service_state_files(service_dir):
            try:
                data = json.loads(state_file.read_text())
                services[name] = data
            except (json.JSONDecodeError, OSError):
                services[name] = {"status": "error", "error": "cannot read state file"}

        # Also check launchd status (async to avoid blocking event loop)
        plist_names = [
            "com.bumba.agent-bridge",
            "com.bumba.agent-briefing",
            "com.bumba.agent-checkin",
            "com.bumba.agent-calendar",
            "com.bumba.agent-email",
            "com.bumba.agent-knowledge-review",
            "com.bumba.agent-retro",
            "com.bumba.agent-weekly-review",
            "com.bumba.agent-job-search",
            "com.bumba.agent-job-execute",
            "com.bumba.agent-monitor",
            "com.bumba.deploy-helper",
        ]

        async def _check_plist(plist: str) -> tuple[str, str]:
            short = plist.replace("com.bumba.agent-", "").replace("com.bumba.", "")
            try:
                proc = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        "launchctl", "print", f"system/{plist}",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    ),
                    timeout=5.0,
                )
                await proc.wait()
                return short, "loaded" if proc.returncode == 0 else "not_loaded"
            except (asyncio.TimeoutError, OSError):
                return short, "unknown"

        results = await asyncio.gather(*[_check_plist(p) for p in plist_names])
        launchd_status = dict(results)

        return _ok({
            "services": services,
            "launchd": launchd_status,
        })
