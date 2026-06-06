"""HTTP health endpoint for bridge self-monitoring."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from .staleness import (
    EXEMPT_CATEGORIES,
    KNOWLEDGE_FRESHNESS_THRESHOLDS,
    is_service_stale,
)
from .services.state_inventory import iter_known_service_state_files
from .version import get_running_version

if TYPE_CHECKING:
    from .app import BridgeApp

logger = logging.getLogger(__name__)

_TOKEN_STARTUP_GRACE_SECONDS = 120


class HealthServer:
    """Lightweight HTTP server exposing /healthz on localhost."""

    def __init__(self, app: BridgeApp, port: int = 8199) -> None:
        self._app = app
        self._port = port
        self._start_time = time.monotonic()
        self._runner: web.AppRunner | None = None
        self._cache: dict | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 10.0  # seconds

    async def start(self) -> None:
        """Start the health HTTP server on localhost."""
        app = web.Application()
        app.router.add_get("/healthz", self._handle_health)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self._port)
        await site.start()
        logger.info("Health server started on http://127.0.0.1:%d/healthz", self._port)

    async def stop(self) -> None:
        """Shutdown the health server."""
        if self._runner:
            await self._runner.cleanup()

    async def _handle_health(self, request: web.Request) -> web.Response:
        now = time.monotonic()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            status_code = 200 if self._cache["status"] == "healthy" else 503
            return web.json_response(self._cache, status=status_code)

        health = await self.collect_health()
        self._cache = health
        self._cache_time = now
        status_code = 200 if health["status"] == "healthy" else 503
        return web.json_response(health, status=status_code)

    async def collect_health(self) -> dict:
        """Collect health from all components. Public for reuse by /health command."""
        components = {}
        components["discord"] = await self._check_discord()
        components["claude"] = self._check_claude()
        components["database"] = await self._check_database()
        components["memory"] = await self._check_memory()
        components["voice"] = await self._check_voice()
        components["token"] = self._check_token()
        components["services"] = await self._check_services()
        components["knowledge_freshness"] = await self._check_knowledge_freshness()

        components["daily_log"] = self._check_daily_log()
        components["consolidation_lock"] = await self._check_consolidation_lock()
        components["tick_loop"] = self._check_tick_loop()
        components["memory_file"] = await self._check_memory_file()
        components["embedding_backend"] = self._check_embedding_backend()
        components["primer"] = self._check_primer()
        components["experiment_loop"] = self._check_experiment_loop()

        # Determine overall status
        critical = ["discord", "claude", "database", "token"]
        critical_statuses = [components.get(c, {}).get("status", "down") for c in critical]
        if all(s == "up" for s in critical_statuses):
            status = "healthy"
        elif any(s == "down" for s in critical_statuses):
            status = "unhealthy"
        else:
            status = "degraded"

        return {
            "status": status,
            "version": get_running_version(),
            "uptime_seconds": int(time.monotonic() - self._start_time),
            "components": components,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _check_discord(self) -> dict:
        """Check Discord bot connection."""
        try:
            bot = self._app._discord
            if bot is None:
                return {"status": "down", "error": "not initialized"}
            is_ready = bot.is_ready() if hasattr(bot, "is_ready") else False
            latency_ms = int(bot.latency * 1000) if hasattr(bot, "latency") else None
            return {
                "status": "up" if is_ready else "degraded",
                "latency_ms": latency_ms,
                "connected": is_ready,
            }
        except Exception as e:
            return {"status": "down", "error": str(e)}

    def _check_claude(self) -> dict:
        """Check Claude runner status."""
        try:
            runner = self._app._claude
            if runner is None:
                return {"status": "down", "error": "not initialized"}
            return {
                "status": "up",
                "last_invocation": getattr(runner, "_last_invocation", None),
            }
        except Exception as e:
            return {"status": "down", "error": str(e)}

    async def _check_database(self) -> dict:
        """Check SQLite database health."""
        try:
            db = self._app._db
            if db is None:
                return {"status": "down", "error": "not initialized"}

            db_path = db.db_path
            size_mb = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0
            wal_path = db_path.with_suffix(".db-wal")
            wal_mb = wal_path.stat().st_size / (1024 * 1024) if wal_path.exists() else 0

            row = await db.fetchone("PRAGMA quick_check;")
            integrity_ok = row[0] == "ok" if row else False

            count_row = await db.fetchone("SELECT COUNT(*) FROM knowledge;")
            knowledge_count = count_row[0] if count_row else 0

            return {
                "status": "up" if integrity_ok else "degraded",
                "size_mb": round(size_mb, 1),
                "wal_size_mb": round(wal_mb, 1),
                "knowledge_count": knowledge_count,
                "integrity": "ok" if integrity_ok else "check_failed",
            }
        except Exception as e:
            return {"status": "down", "error": str(e)}

    async def _check_memory(self) -> dict:
        """Check memory system via a test search."""
        try:
            memory = self._app._memory
            if memory is None:
                return {"status": "down", "error": "not initialized"}
            # Quick search to verify FTS5 is functional
            await memory.search_knowledge("test", limit=1)
            return {"status": "up", "search_functional": True}
        except Exception as e:
            return {"status": "degraded", "search_functional": False, "error": str(e)}

    async def _check_voice(self) -> dict:
        """Voice subsystem status (issue #1612).

        Reports the real flag-conditioned state instead of the legacy
        hardcoded "removed". Voice IS supported (VAPI mode, D1.7a-c) when
        `[voice] voice_enabled = true` in bridge.toml. When the flag is off
        the subsystem is intentionally dormant; voice is not critical for
        overall health (see the critical list in collect_health).
        """
        try:
            config = self._app._config
            if config is None:
                return {"status": "disabled", "note": "no config"}
            if not getattr(config, "voice_enabled", False):
                return {
                    "status": "disabled",
                    "voice_enabled": False,
                    "note": "voice_enabled = false in bridge.toml",
                }
            voice = getattr(self._app, "_voice", None)
            vapi = getattr(self._app, "_vapi", None)
            mode = "vapi" if vapi is not None else "manager"
            return {
                "status": "up" if voice is not None else "degraded",
                "voice_enabled": True,
                "mode": mode,
                "vapi_configured": bool(
                    vapi is not None and getattr(vapi, "is_configured", False)
                ),
            }
        except Exception as e:
            return {"status": "degraded", "error": str(e)[:120]}

    def _check_token(self) -> dict:
        """Check OAuth token expiry."""
        try:
            refresher = self._app._token_refresher
            if refresher is None:
                return {"status": "degraded", "error": "refresher not initialized"}
            expires_at = getattr(refresher, "_expires_at", 0)
            remaining = expires_at - time.time()
            if remaining < 0:
                if self._token_startup_grace_applies(refresher):
                    return {
                        "status": "up",
                        "expires_in_seconds": 0,
                        "startup_refresh_pending": True,
                        "startup_grace_seconds": _TOKEN_STARTUP_GRACE_SECONDS,
                    }
                return {"status": "down", "expires_in_seconds": 0, "error": "token expired"}
            if remaining < 3600:
                return {"status": "degraded", "expires_in_seconds": int(remaining)}
            return {"status": "up", "expires_in_seconds": int(remaining)}
        except Exception as e:
            return {"status": "down", "error": str(e)}

    def _token_startup_grace_applies(self, refresher: object) -> bool:
        """Return True while a fresh daemon waits for first OAuth refresh.

        Some deploys boot with a stale/unknown ``_expires_at`` from secrets
        while still holding loaded OAuth access and refresh tokens. During the
        first short startup window, treat that as healthy so `/healthz` does
        not flap 503 before the refresh loop has a chance to run. The grace is
        intentionally time-boxed and requires real string tokens.
        """
        uptime_s = time.monotonic() - self._start_time
        if uptime_s > _TOKEN_STARTUP_GRACE_SECONDS:
            return False
        access_token = getattr(refresher, "_access_token", "")
        refresh_token = getattr(refresher, "_refresh_token", "")
        return (
            isinstance(access_token, str)
            and bool(access_token)
            and isinstance(refresh_token, str)
            and bool(refresh_token)
        )

    async def _check_services(self) -> dict:
        """Read all service state files and aggregate status."""
        try:
            config = self._app._config
            if config is None:
                return {}
            service_dir = Path(config.data_dir) / "service_state"
            if not service_dir.exists():
                return {}

            services = {}
            for name, state_file in iter_known_service_state_files(service_dir):
                try:
                    data = json.loads(state_file.read_text())
                    last_run = data.get("last_run")
                    stale = is_service_stale(last_run, name)
                    entry: dict = {
                        "last_run": last_run,
                        "last_status": data.get("last_status", "unknown"),
                        "last_error": data.get("last_error"),
                        "stale": stale,
                    }
                    if stale:
                        entry["last_skipped_reason"] = data.get("last_skipped_reason")
                        entry["last_skipped_class"] = data.get("last_skipped_class")
                    services[name] = entry
                except (json.JSONDecodeError, OSError) as e:
                    services[name] = {"last_status": "error", "error": str(e)}
            return services
        except Exception as e:
            return {"_error": str(e)}

    async def _check_knowledge_freshness(self) -> dict:
        """Check how fresh each knowledge category is against its threshold."""
        try:
            db = self._app._db
            if db is None:
                return {"status": "unknown", "error": "database not initialized"}

            rows = await db.fetchall(
                "SELECT category, MAX(updated_at) as last_update "
                "FROM knowledge GROUP BY category"
            )

            now = datetime.now(timezone.utc)
            stale_categories: list[str] = []
            total_categories = 0

            for row in rows:
                category = row["category"] if isinstance(row, dict) else row[0]
                last_update = row["last_update"] if isinstance(row, dict) else row[1]

                # Skip exempt categories
                if category in EXEMPT_CATEGORIES:
                    continue

                threshold_days = KNOWLEDGE_FRESHNESS_THRESHOLDS.get(category)
                if threshold_days is None:
                    continue

                total_categories += 1

                if last_update is None:
                    stale_categories.append(category)
                    continue

                try:
                    updated = datetime.fromisoformat(last_update)
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    age_days = (now - updated).total_seconds() / 86400
                    if age_days > threshold_days:
                        stale_categories.append(category)
                except (ValueError, TypeError):
                    stale_categories.append(category)

            return {
                "stale_categories": stale_categories,
                "total_categories": total_categories,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_primer(self) -> dict:
        """Check session-handoff primer.json state (#488)."""
        try:
            from bridge.primer_writer import get_primer_health
            fields = get_primer_health()
            if fields.get("primer_last_write_success"):
                age = fields.get("primer_last_write_age_minutes")
                status = "up"
                if age is not None and age > 60 * 48:  # >48h stale
                    status = "degraded"
                return {
                    "status": status,
                    "last_write_success": True,
                    "last_write_age_minutes": round(age, 1) if age is not None else None,
                }
            return {
                "status": "down",
                "last_write_success": False,
                "last_write_age_minutes": None,
                "note": "no primer.json yet — will be written on next session expire or /reset",
            }
        except Exception as e:
            return {"status": "down", "error": str(e)[:120]}

    def _check_daily_log(self) -> dict:
        """Check daily log writer."""
        try:
            daily_log = getattr(self._app, "_daily_log", None)
            if daily_log is None:
                return {"status": "disabled", "note": "not initialized"}
            config = self._app._config
            if config is None:
                return {"status": "down", "error": "no config"}
            from pathlib import Path
            from datetime import datetime, timezone
            log_dir = Path(config.data_dir) / "logs"
            today = datetime.now(timezone.utc).astimezone()
            today_path = log_dir / f"{today:%Y}" / f"{today:%m}" / f"{today:%Y-%m-%d}.md"
            exists = today_path.exists()
            size_bytes = today_path.stat().st_size if exists else 0
            return {
                "status": "up",
                "today_log_exists": exists,
                "today_log_bytes": size_bytes,
            }
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

    async def _check_consolidation_lock(self) -> dict:
        """Check consolidation lock state."""
        try:
            config = self._app._config
            if config is None:
                return {"status": "unknown", "error": "no config"}
            from pathlib import Path
            import time
            lock_path = Path(config.data_dir) / ".consolidate-lock"
            if not lock_path.exists():
                return {"status": "up", "locked": False}
            mtime = lock_path.stat().st_mtime
            age_s = int(time.time() - mtime)
            stale = age_s > 3600
            pid_text = lock_path.read_text().strip()
            return {
                "status": "degraded" if stale else "up",
                "locked": True,
                "lock_age_seconds": age_s,
                "stale": stale,
                "holder_pid": pid_text,
            }
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

    def _check_tick_loop(self) -> dict:
        """Check proactive tick loop state."""
        try:
            tick_manager = getattr(self._app, "_tick_manager", None)
            if tick_manager is None:
                return {"status": "disabled", "note": "proactive mode not enabled"}
            state = getattr(tick_manager, "_state", None)
            last_tick = getattr(tick_manager, "_last_tick", None)
            return {
                "status": "up",
                "state": state.value if state else "unknown",
                "last_tick": last_tick,
            }
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

    async def _check_memory_file(self) -> dict:
        """Check the MEMORY.md writer (Sprint 05.06: renamed from memory_index).

        Probes attributes that actually exist on ``MemoryFile``:
        - ``exists``: has MEMORY.md been written at least once?
        - ``file_size_bytes``: current on-disk size (0 if never written)
        - ``path``: absolute path for operator visibility
        """
        try:
            memory_file = getattr(self._app, "_memory_file", None)
            if memory_file is None:
                return {"status": "disabled", "note": "memory file not initialized"}
            exists = bool(getattr(memory_file, "exists", False))
            size_bytes = int(getattr(memory_file, "file_size_bytes", 0))
            path = getattr(memory_file, "path", None)
            return {
                "status": "up",
                "exists": exists,
                "file_size_bytes": size_bytes,
                "path": str(path) if path is not None else None,
            }
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

    def _check_experiment_loop(self) -> dict:
        """Surface experiment-loop heartbeat (#988) without raising.

        The loop runs as a separate process and writes
        ``data/experiment-loop-heartbeat.json`` on each iteration boundary.
        This check reads that file and returns a status block compatible
        with the rest of ``components``:

        - ``up`` when the heartbeat is fresh (alive)
        - ``degraded`` when the file is older than the stale threshold
        - ``disabled`` when the heartbeat file is absent or its PID is
          dead — the loop isn't running, which is normal for hosts that
          opted out, so it doesn't trip the overall ``unhealthy`` gate.

        Failures are caught and downgraded to ``disabled`` rather than
        ``down`` so that a missing module / bad state never makes
        /healthz return 503.
        """
        try:
            from bridge.experiment_heartbeat import (
                DEFAULT_STALE_THRESHOLD_SECONDS,
                HEARTBEAT_PATH,
                healthz_block,
            )

            config = self._app._config
            stale_threshold = DEFAULT_STALE_THRESHOLD_SECONDS
            heartbeat_path = HEARTBEAT_PATH
            if config is not None:
                stale_threshold = int(
                    getattr(
                        config,
                        "experiment_heartbeat_stale_seconds",
                        DEFAULT_STALE_THRESHOLD_SECONDS,
                    )
                )
                data_dir = getattr(config, "data_dir", None)
                if data_dir:
                    heartbeat_path = Path(data_dir) / "experiment-loop-heartbeat.json"

            block = healthz_block(
                path=heartbeat_path,
                stale_threshold_seconds=stale_threshold,
            )
            loop_status = block["experiment_loop_status"]
            if loop_status == "alive":
                comp_status = "up"
            elif loop_status == "stale":
                comp_status = "degraded"
            else:
                # ``unknown`` covers absent file or dead PID — the loop
                # simply isn't running; don't fail overall health.
                comp_status = "disabled"
            return {
                "status": comp_status,
                **block,
            }
        except Exception as exc:  # pragma: no cover — defensive
            return {
                "status": "disabled",
                "experiment_loop_status": "unknown",
                "experiment_loop_last_iter_age_seconds": None,
                "experiment_loop_pid": None,
                "experiment_loop_last_iter_id": None,
                "experiment_loop_fitness_value": None,
                "error": str(exc)[:120],
            }

    def _check_embedding_backend(self) -> dict:
        """Report active LocalEmbeddingEngine backend.

        Sprint 05.04 — exposes ``_backend_name`` so operators can verify which
        backend is loaded (``coreml``/``onnx``/``hash``) without Mac-mini shell
        access. ``hash`` means semantic recall is degraded (deterministic
        pseudo-embeddings); see ``docs/runbooks/semantic-search-setup.md`` for
        the model-file deploy path.
        """
        try:
            engine = getattr(self._app, "_embedding_engine", None)
            if engine is None:
                return {
                    "status": "disabled",
                    "note": "embedding engine not initialized",
                }
            # Trigger lazy load via the public property; falls through to
            # `hash` when no model file is present (engine is still functional).
            backend = engine.backend_name
            recall_quality = (
                "real" if backend in ("coreml", "onnx") else "degraded"
            )
            status = "up" if backend in ("coreml", "onnx") else "degraded"
            return {
                "status": status,
                "backend": backend,
                "recall_quality": recall_quality,
                "model_dir": str(getattr(engine, "model_dir", "")),
            }
        except Exception as e:
            return {"status": "degraded", "error": str(e)}
