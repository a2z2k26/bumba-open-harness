"""Tests for bridge.background_loops — all five loop functions."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


from bridge import background_loops
from bridge.mcp_monitor import CRASH_LOOP_THRESHOLD, MCPMonitor, MCPServerInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_shutdown(set_after: int = 0) -> asyncio.Event:
    """Return an asyncio.Event that auto-sets after *set_after* loop ticks."""
    return asyncio.Event()


# ---------------------------------------------------------------------------
# heartbeat_loop
# ---------------------------------------------------------------------------


class TestHeartbeatLoop:
    async def test_writes_heartbeat_file(self, tmp_path: Path) -> None:
        """heartbeat_loop writes timestamp to <data_dir>/heartbeat."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        shutdown = asyncio.Event()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(shutdown, config),
            _stop(),
        )

        heartbeat_path = tmp_path / "heartbeat"
        assert heartbeat_path.exists(), "heartbeat file should be written"
        content = heartbeat_path.read_text()
        assert len(content) > 5, "heartbeat file should contain a timestamp"

    async def test_stops_on_shutdown(self, tmp_path: Path) -> None:
        """heartbeat_loop exits promptly when shutdown_event is set."""
        config = MagicMock()
        config.heartbeat_interval = 60  # long interval — should not wait
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        shutdown = asyncio.Event()
        shutdown.set()  # pre-set

        # Should return almost immediately
        await asyncio.wait_for(
            background_loops.heartbeat_loop(shutdown, config),
            timeout=1.0,
        )

    async def test_handles_write_failure_gracefully(self, tmp_path: Path) -> None:
        """heartbeat_loop logs warning and continues if file write fails."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = "/nonexistent/path/that/does/not/exist"
        config.remote_halt_url = None

        shutdown = asyncio.Event()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        # Should not raise even if write fails
        await asyncio.gather(
            background_loops.heartbeat_loop(shutdown, config),
            _stop(),
        )

    async def test_optional_deps_are_none_safe(self, tmp_path: Path) -> None:
        """heartbeat_loop works when all optional kwargs are None."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        shutdown = asyncio.Event()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown,
                config,
                autonomy=None,
                discord=None,
                runbook_engine=None,
                tmux_agents=None,
                mcp_monitor=None,
                security=None,
            ),
            _stop(),
        )


# ---------------------------------------------------------------------------
# decay_loop
# ---------------------------------------------------------------------------


class TestDecayLoop:
    async def test_calls_run_decay_sweep_after_interval(self) -> None:
        """decay_loop calls memory.run_decay_sweep() after DECAY_INTERVAL elapses."""
        memory = MagicMock()
        memory.run_decay_sweep = AsyncMock(return_value={"decayed": 3, "pruned": 1})

        shutdown = asyncio.Event()

        # Patch the interval to near-zero so the test runs fast
        with patch.object(background_loops, "DECAY_INTERVAL", 0.05):
            async def _stop() -> None:
                # Wait long enough for one sweep, then shut down
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                background_loops.decay_loop(shutdown, memory),
                _stop(),
            )

        memory.run_decay_sweep.assert_awaited()

    async def test_stops_on_shutdown_before_sweep(self) -> None:
        """decay_loop exits without calling run_decay_sweep if shutdown fires first."""
        memory = MagicMock()
        memory.run_decay_sweep = AsyncMock()

        shutdown = asyncio.Event()
        shutdown.set()  # pre-set before entering loop

        await asyncio.wait_for(
            background_loops.decay_loop(shutdown, memory),
            timeout=1.0,
        )

        memory.run_decay_sweep.assert_not_awaited()

    async def test_continues_after_sweep_error(self) -> None:
        """decay_loop logs error and continues running if run_decay_sweep raises."""
        call_count = 0

        async def _failing_sweep():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("DB error")
            return {"decayed": 0, "pruned": 0}

        memory = MagicMock()
        memory.run_decay_sweep = _failing_sweep

        shutdown = asyncio.Event()

        with patch.object(background_loops, "DECAY_INTERVAL", 0.05):
            async def _stop() -> None:
                await asyncio.sleep(0.35)
                shutdown.set()

            await asyncio.gather(
                background_loops.decay_loop(shutdown, memory),
                _stop(),
            )

        assert call_count >= 2, "loop should continue after error"


# ---------------------------------------------------------------------------
# backup_loop
# ---------------------------------------------------------------------------


class TestBackupLoop:
    async def test_calls_db_backup_after_interval(self, tmp_path: Path) -> None:
        """backup_loop calls db.backup_with_verify() after BACKUP_INTERVAL elapses."""
        from bridge.database import Database

        db = MagicMock()
        db.backup_with_verify = AsyncMock(return_value=(str(tmp_path / "memory-test.db"), True))

        config = MagicMock()
        config.data_dir = str(tmp_path)

        shutdown = asyncio.Event()

        with patch.object(background_loops, "BACKUP_INTERVAL", 0.05), \
             patch.object(Database, "rotate_backups", return_value=0):
            async def _stop() -> None:
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                background_loops.backup_loop(shutdown, db, config),
                _stop(),
            )

        db.backup_with_verify.assert_awaited()

    async def test_stops_on_shutdown_before_backup(self, tmp_path: Path) -> None:
        """backup_loop exits without calling backup if shutdown fires first."""
        db = MagicMock()
        db.backup_with_verify = AsyncMock()

        config = MagicMock()
        config.data_dir = str(tmp_path)

        shutdown = asyncio.Event()
        shutdown.set()

        await asyncio.wait_for(
            background_loops.backup_loop(shutdown, db, config),
            timeout=1.0,
        )

        db.backup_with_verify.assert_not_awaited()

    async def test_logs_error_on_backup_failure(self, tmp_path: Path) -> None:
        """backup_loop logs error and continues if db.backup_with_verify raises."""
        call_count = 0

        async def _failing_backup(dest):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Disk full")
            return (str(dest), True)

        db = MagicMock()
        db.backup_with_verify = _failing_backup

        config = MagicMock()
        config.data_dir = str(tmp_path)

        shutdown = asyncio.Event()

        with patch.object(background_loops, "BACKUP_INTERVAL", 0.05):
            from bridge.database import Database
            with patch.object(Database, "rotate_backups", return_value=0):
                async def _stop() -> None:
                    await asyncio.sleep(0.35)
                    shutdown.set()

                await asyncio.gather(
                    background_loops.backup_loop(shutdown, db, config),
                    _stop(),
                )

        assert call_count >= 2, "loop should continue after backup failure"


# ---------------------------------------------------------------------------
# consolidation_loop
# ---------------------------------------------------------------------------


SAMPLE_ROWS = [
    {
        "key": "k1",
        "value": "Use dark mode",
        "category": "preference",
        "source": "manual",
        "salience": 1.0,
        "access_count": 3,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-10T00:00:00",
    },
    {
        "key": "k2",
        "value": "Operator is in New York",
        "category": "fact",
        "source": "conversation",
        "salience": 0.8,
        "access_count": 1,
        "created_at": "2026-01-02T00:00:00",
        "updated_at": "2026-01-09T00:00:00",
    },
]


class TestConsolidationLoop:
    async def test_calls_fetch_all_knowledge_rows(self) -> None:
        """consolidation_loop calls memory.fetch_all_knowledge_rows() after interval."""
        memory = MagicMock()
        memory.fetch_all_knowledge_rows = AsyncMock(return_value=[])

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        shutdown = asyncio.Event()

        with patch.object(background_loops, "CONSOLIDATION_INTERVAL", 0.05), \
             patch.object(background_loops, "CONSOLIDATION_WARMUP", 0.01):
            async def _stop() -> None:
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                background_loops.consolidation_loop(shutdown, db, memory),
                _stop(),
            )

        memory.fetch_all_knowledge_rows.assert_awaited()

    async def test_skips_pipeline_when_no_rows(self) -> None:
        """consolidation_loop skips run_pipeline if fetch returns empty list."""
        memory = MagicMock()
        memory.fetch_all_knowledge_rows = AsyncMock(return_value=[])

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        shutdown = asyncio.Event()

        with patch.object(background_loops, "CONSOLIDATION_INTERVAL", 0.05), \
             patch.object(background_loops, "CONSOLIDATION_WARMUP", 0.01), \
             patch("bridge.consolidation.run_pipeline") as mock_pipeline:
            async def _stop() -> None:
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                background_loops.consolidation_loop(shutdown, db, memory),
                _stop(),
            )

        mock_pipeline.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_runs_pipeline_and_writes_decay_results(self) -> None:
        """consolidation_loop calls run_pipeline and writes decay updates to DB."""
        rows = [dict(r) for r in SAMPLE_ROWS]  # mutable copies

        memory = MagicMock()
        memory.fetch_all_knowledge_rows = AsyncMock(return_value=rows)

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        # Simulate decay annotating rows
        def _mock_pipeline(r, mode="standard", **kwargs):
            from bridge.consolidation import ConsolidationReport
            r[0]["_action"] = "decay"
            r[0]["_new_salience"] = 0.9
            r[1]["_action"] = "prune"
            r[1]["_new_salience"] = 0.0
            return ConsolidationReport(
                phase_results={"decay": {"decayed": 1, "pruned": 1}, "merge": None},
                total_duration_ms=42,
                mode=mode,
                timestamp="2026-01-10T00:00:00+00:00",
            )

        shutdown = asyncio.Event()

        with patch.object(background_loops, "CONSOLIDATION_INTERVAL", 0.05), \
             patch.object(background_loops, "CONSOLIDATION_WARMUP", 0.01), \
             patch("bridge.consolidation.run_pipeline", side_effect=_mock_pipeline):
            async def _stop() -> None:
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                background_loops.consolidation_loop(shutdown, db, memory),
                _stop(),
            )

        db.commit.assert_awaited()
        # Two DB updates: one decay, one prune
        assert db.execute.await_count >= 2

    async def test_writes_merge_archive_results(self) -> None:
        """consolidation_loop archives duplicate rows from merge phase."""
        rows = [dict(r) for r in SAMPLE_ROWS]

        memory = MagicMock()
        memory.fetch_all_knowledge_rows = AsyncMock(return_value=rows)

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        def _mock_pipeline(r, mode="standard", **kwargs):
            from bridge.consolidation import ConsolidationReport
            r[1]["_merge_action"] = "archive"
            return ConsolidationReport(
                phase_results={"merge": {"archived": 1}, "decay": None},
                total_duration_ms=10,
                mode=mode,
                timestamp="2026-01-10T00:00:00+00:00",
            )

        shutdown = asyncio.Event()

        with patch.object(background_loops, "CONSOLIDATION_INTERVAL", 0.05), \
             patch.object(background_loops, "CONSOLIDATION_WARMUP", 0.01), \
             patch("bridge.consolidation.run_pipeline", side_effect=_mock_pipeline):
            async def _stop() -> None:
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                background_loops.consolidation_loop(shutdown, db, memory),
                _stop(),
            )

        db.commit.assert_awaited()
        # At least one archive UPDATE
        execute_calls = [str(c) for c in db.execute.call_args_list]
        assert any("archived" in c for c in execute_calls)

    async def test_stops_on_shutdown_before_pipeline(self) -> None:
        """consolidation_loop exits without running pipeline if shutdown fires first."""
        memory = MagicMock()
        memory.fetch_all_knowledge_rows = AsyncMock(return_value=SAMPLE_ROWS)

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        shutdown = asyncio.Event()
        shutdown.set()

        await asyncio.wait_for(
            background_loops.consolidation_loop(shutdown, db, memory),
            timeout=1.0,
        )

        memory.fetch_all_knowledge_rows.assert_not_awaited()

    async def test_continues_after_pipeline_error(self) -> None:
        """consolidation_loop logs error and continues if run_pipeline raises."""
        call_count = 0

        async def _fetch():
            return [dict(r) for r in SAMPLE_ROWS]

        memory = MagicMock()
        memory.fetch_all_knowledge_rows = _fetch

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        def _failing_pipeline(rows, mode="standard", **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("pipeline exploded")
            from bridge.consolidation import ConsolidationReport
            return ConsolidationReport(
                phase_results={},
                total_duration_ms=5,
                mode=mode,
                timestamp="2026-01-10T00:00:00+00:00",
            )

        shutdown = asyncio.Event()

        with patch.object(background_loops, "CONSOLIDATION_INTERVAL", 0.05), \
             patch.object(background_loops, "CONSOLIDATION_WARMUP", 0.01), \
             patch("bridge.consolidation.run_pipeline", side_effect=_failing_pipeline):
            async def _stop() -> None:
                await asyncio.sleep(0.35)
                shutdown.set()

            await asyncio.gather(
                background_loops.consolidation_loop(shutdown, db, memory),
                _stop(),
            )

        assert call_count >= 2, "loop should continue after pipeline error"

    # ─────────────────────────────────────────────────────────────────
    # Sprint 2.2 — startup-prime tests
    # ─────────────────────────────────────────────────────────────────

    async def test_runs_priming_pass_after_warmup_not_after_interval(self) -> None:
        """Sprint 2.2: the loop runs the pipeline ONCE after CONSOLIDATION_WARMUP,
        before the long CONSOLIDATION_INTERVAL kicks in. Previously it sat idle
        for 24 hours after a bridge restart before the first pipeline run.
        """
        memory = MagicMock()
        memory.fetch_all_knowledge_rows = AsyncMock(return_value=[])

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        shutdown = asyncio.Event()

        # Warmup is short; INTERVAL is huge so the test would hang if the
        # priming pass wasn't doing its job.
        with patch.object(background_loops, "CONSOLIDATION_WARMUP", 0.05), \
             patch.object(background_loops, "CONSOLIDATION_INTERVAL", 3600):
            async def _stop() -> None:
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                background_loops.consolidation_loop(shutdown, db, memory),
                _stop(),
            )

        # If this fails, it means the loop did NOT run the priming pass —
        # it sat in the 3600s wait_for and the test would have hit shutdown
        # before fetch was called.
        memory.fetch_all_knowledge_rows.assert_awaited_once()

    async def test_shutdown_during_warmup_exits_cleanly(self) -> None:
        """Sprint 2.2: shutting down during the CONSOLIDATION_WARMUP wait
        exits the loop without running the pipeline.
        """
        memory = MagicMock()
        memory.fetch_all_knowledge_rows = AsyncMock(return_value=SAMPLE_ROWS)

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        shutdown = asyncio.Event()

        # Long warmup; we set shutdown before it elapses
        with patch.object(background_loops, "CONSOLIDATION_WARMUP", 1.0), \
             patch.object(background_loops, "CONSOLIDATION_INTERVAL", 86400):
            async def _stop() -> None:
                await asyncio.sleep(0.05)  # well before warmup elapses
                shutdown.set()

            await asyncio.wait_for(
                asyncio.gather(
                    background_loops.consolidation_loop(shutdown, db, memory),
                    _stop(),
                ),
                timeout=2.0,
            )

        memory.fetch_all_knowledge_rows.assert_not_awaited()

    async def test_run_consolidation_once_can_be_called_directly(self) -> None:
        """Sprint 2.2: _run_consolidation_once is the extracted pipeline body
        and can be invoked independently of the loop. This is the core
        testability win — callers don't need to spin up an event loop just
        to exercise the pipeline once.
        """
        rows = [dict(r) for r in SAMPLE_ROWS]

        memory = MagicMock()
        memory.fetch_all_knowledge_rows = AsyncMock(return_value=rows)

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        def _mock_pipeline(r, mode="standard", **kwargs):
            from bridge.consolidation import ConsolidationReport
            r[0]["_action"] = "decay"
            r[0]["_new_salience"] = 0.5
            return ConsolidationReport(
                phase_results={"decay": {"decayed": 1, "pruned": 0}, "merge": None},
                total_duration_ms=7,
                mode=mode,
                timestamp="2026-01-10T00:00:00+00:00",
            )

        with patch("bridge.consolidation.run_pipeline", side_effect=_mock_pipeline):
            await background_loops._run_consolidation_once(db, memory)

        memory.fetch_all_knowledge_rows.assert_awaited_once()
        db.commit.assert_awaited_once()
        # One decay UPDATE
        assert db.execute.await_count == 1


# ---------------------------------------------------------------------------
# reflection_loop
# ---------------------------------------------------------------------------


class TestReflectionLoop:
    async def test_stores_reflection_when_none_exists(self) -> None:
        """reflection_loop generates and stores a reflection if week has none."""
        store = MagicMock()
        store.get_reflection = MagicMock(return_value=None)
        store.store_reflection = MagicMock()

        shutdown = asyncio.Event()

        with patch.object(background_loops, "REFLECTION_INTERVAL", 0.05), \
             patch("bridge.reflection.make_week_key", return_value="reflection-2026-W15"), \
             patch("bridge.reflection.gather_week_data_from_dicts", return_value={}):

            async def _stop() -> None:
                await asyncio.sleep(0.35)
                shutdown.set()

            await asyncio.gather(
                background_loops.reflection_loop(shutdown, store),
                _stop(),
            )

        store.store_reflection.assert_called()

    async def test_skips_when_reflection_already_exists(self) -> None:
        """reflection_loop skips storage if reflection already stored for the week."""
        store = MagicMock()
        store.get_reflection = MagicMock(return_value={"week_key": "reflection-2026-W15"})
        store.store_reflection = MagicMock()

        shutdown = asyncio.Event()

        with patch.object(background_loops, "REFLECTION_INTERVAL", 0.05), \
             patch("bridge.reflection.make_week_key", return_value="reflection-2026-W15"):

            async def _stop() -> None:
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                background_loops.reflection_loop(shutdown, store),
                _stop(),
            )

        store.store_reflection.assert_not_called()

    async def test_stops_on_shutdown_before_reflection(self) -> None:
        """reflection_loop exits without storing if shutdown fires first."""
        store = MagicMock()
        store.get_reflection = MagicMock()
        store.store_reflection = MagicMock()

        shutdown = asyncio.Event()
        shutdown.set()

        await asyncio.wait_for(
            background_loops.reflection_loop(shutdown, store),
            timeout=1.0,
        )

        store.get_reflection.assert_not_called()
        store.store_reflection.assert_not_called()

    async def test_none_store_is_safe(self) -> None:
        """reflection_loop continues without error when reflection_store is None."""
        shutdown = asyncio.Event()

        with patch.object(background_loops, "REFLECTION_INTERVAL", 0.05):
            async def _stop() -> None:
                await asyncio.sleep(0.15)
                shutdown.set()

            await asyncio.gather(
                background_loops.reflection_loop(shutdown, None),
                _stop(),
            )

    async def test_continues_after_reflection_error(self) -> None:
        """reflection_loop catches exception and continues on next iteration."""
        call_count = 0

        def _get_reflection(key):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("store error")
            return {"week_key": key}  # exists on second call

        store = MagicMock()
        store.get_reflection = _get_reflection
        store.store_reflection = MagicMock()

        shutdown = asyncio.Event()

        with patch.object(background_loops, "REFLECTION_INTERVAL", 0.05), \
             patch("bridge.reflection.make_week_key", return_value="reflection-2026-W15"), \
             patch("bridge.reflection.gather_week_data_from_dicts", return_value={}):

            async def _stop() -> None:
                await asyncio.sleep(0.35)
                shutdown.set()

            await asyncio.gather(
                background_loops.reflection_loop(shutdown, store),
                _stop(),
            )

        assert call_count >= 2, "loop should continue after error"


# ---------------------------------------------------------------------------
# heartbeat_loop — MCP observability (#280)
# ---------------------------------------------------------------------------


class TestHeartbeatMCPObservability:
    """Tests for the MCP crash-loop alerting in heartbeat_loop, including
    the #280 fix that reports specific unhealthy server names."""

    async def test_mcp_alert_includes_server_names(self, tmp_path: Path) -> None:
        """Discord alert includes the names of crash-looping servers."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None
        config.operator_discord_id = "12345"

        mcp_monitor = MagicMock()
        mcp_monitor.check_server_health = AsyncMock()
        mcp_monitor.get_status_summary = MagicMock(return_value={
            "total": 3, "running": 1, "stopped": 2, "crash_loop": 2,
        })
        mcp_monitor.get_unhealthy_servers = MagicMock(
            return_value=["bumba-memory", "figma-context"]
        )

        discord = MagicMock()
        discord.send_alert = AsyncMock()

        shutdown = asyncio.Event()

        # Reset the module-level throttle so the alert fires
        background_loops._last_mcp_alert_time = 0.0

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, mcp_monitor=mcp_monitor, discord=discord,
            ),
            _stop(),
        )

        discord.send_alert.assert_awaited()
        alert_msg = discord.send_alert.call_args[0][0]
        assert "bumba-memory" in alert_msg
        assert "figma-context" in alert_msg
        assert "2 server(s)" in alert_msg

    async def test_mcp_alert_throttled(self, tmp_path: Path) -> None:
        """Discord alert is throttled — second alert within cooldown is suppressed."""
        import time

        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None
        config.operator_discord_id = "12345"

        mcp_monitor = MagicMock()
        mcp_monitor.check_server_health = AsyncMock()
        mcp_monitor.get_status_summary = MagicMock(return_value={
            "total": 2, "running": 0, "stopped": 2, "crash_loop": 1,
        })
        mcp_monitor.get_unhealthy_servers = MagicMock(return_value=["memory"])

        discord = MagicMock()
        discord.send_alert = AsyncMock()

        shutdown = asyncio.Event()

        # Pretend alert was sent recently
        background_loops._last_mcp_alert_time = time.time()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, mcp_monitor=mcp_monitor, discord=discord,
            ),
            _stop(),
        )

        # Alert should be suppressed due to cooldown
        discord.send_alert.assert_not_awaited()

        # Reset for other tests
        background_loops._last_mcp_alert_time = 0.0

    async def test_mcp_no_crash_loops_resets_throttle(self, tmp_path: Path) -> None:
        """When crash_loop count is 0, the alert throttle resets."""
        import time

        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        mcp_monitor = MagicMock()
        mcp_monitor.check_server_health = AsyncMock()
        mcp_monitor.get_status_summary = MagicMock(return_value={
            "total": 3, "running": 3, "stopped": 0, "crash_loop": 0,
        })

        shutdown = asyncio.Event()

        # Set a non-zero throttle time
        background_loops._last_mcp_alert_time = time.time()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, mcp_monitor=mcp_monitor,
            ),
            _stop(),
        )

        assert background_loops._last_mcp_alert_time == 0.0

    async def test_mcp_health_check_exception_handled(self, tmp_path: Path) -> None:
        """MCP health check exception is caught and doesn't crash the loop."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        mcp_monitor = MagicMock()
        mcp_monitor.check_server_health = AsyncMock(side_effect=RuntimeError("connection refused"))

        shutdown = asyncio.Event()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        # Should not raise
        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, mcp_monitor=mcp_monitor,
            ),
            _stop(),
        )


class TestMCPHealthCheckIntervalKnob:
    """Issue #1543 — ``mcp_health_check_interval_seconds`` throttles
    the MCP check inside heartbeat_loop independently of the broader
    heartbeat tick rate."""

    async def test_mcp_check_throttled_by_interval(self, tmp_path: Path) -> None:
        """Heartbeat ticks at 0.02s but the MCP check is gated to 5s, so
        only a single ``check_server_health`` call lands within 0.10s."""
        config = MagicMock()
        config.heartbeat_interval = 0.02
        config.mcp_health_check_interval_seconds = 5  # large interval
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        mcp_monitor = MagicMock()
        mcp_monitor.check_server_health = AsyncMock()
        mcp_monitor.record_health_state = MagicMock()
        mcp_monitor.get_status_summary = MagicMock(return_value={
            "total": 1, "running": 1, "stopped": 0, "crash_loop": 0,
        })

        shutdown = asyncio.Event()
        background_loops._last_mcp_alert_time = 0.0

        async def _stop() -> None:
            await asyncio.sleep(0.10)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, mcp_monitor=mcp_monitor,
            ),
            _stop(),
        )

        # 0.10s window with 5s gate → exactly one MCP check.
        assert mcp_monitor.check_server_health.await_count == 1

    async def test_mcp_check_fires_on_first_tick(self, tmp_path: Path) -> None:
        """First tick of heartbeat_loop must fire the MCP check — the
        startup-warmup case shouldn't sit silent for ``interval_seconds``
        before any health data is collected."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.mcp_health_check_interval_seconds = 300
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        mcp_monitor = MagicMock()
        mcp_monitor.check_server_health = AsyncMock()
        mcp_monitor.record_health_state = MagicMock()
        mcp_monitor.get_status_summary = MagicMock(return_value={
            "total": 1, "running": 1, "stopped": 0, "crash_loop": 0,
        })

        shutdown = asyncio.Event()
        background_loops._last_mcp_alert_time = 0.0

        async def _stop() -> None:
            await asyncio.sleep(0.08)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, mcp_monitor=mcp_monitor,
            ),
            _stop(),
        )

        assert mcp_monitor.check_server_health.await_count == 1
        # And we wrote the EscalationEngine-readable state file once.
        assert mcp_monitor.record_health_state.call_count == 1

    async def test_mcp_check_fires_every_tick_when_interval_zero(
        self, tmp_path: Path
    ) -> None:
        """With interval=0, MCP check fires every heartbeat tick — useful
        for diagnostics or tight smoke tests."""
        config = MagicMock()
        config.heartbeat_interval = 0.02
        config.mcp_health_check_interval_seconds = 0
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        mcp_monitor = MagicMock()
        mcp_monitor.check_server_health = AsyncMock()
        mcp_monitor.record_health_state = MagicMock()
        mcp_monitor.get_status_summary = MagicMock(return_value={
            "total": 1, "running": 1, "stopped": 0, "crash_loop": 0,
        })

        shutdown = asyncio.Event()
        background_loops._last_mcp_alert_time = 0.0

        async def _stop() -> None:
            await asyncio.sleep(0.10)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, mcp_monitor=mcp_monitor,
            ),
            _stop(),
        )

        # 0.10s / 0.02s ≈ 5 ticks — call count should be ≥ 3 (allowing for
        # scheduling jitter). The key signal is "more than one".
        assert mcp_monitor.check_server_health.await_count >= 3


# ---------------------------------------------------------------------------
# heartbeat_loop — escalation scan
# ---------------------------------------------------------------------------


class TestHeartbeatEscalation:
    async def test_escalation_scan_sends_alerts(self, tmp_path: Path) -> None:
        """heartbeat_loop runs escalation scan and sends formatted alerts."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None
        config.operator_discord_id = "12345"

        alert_obj = MagicMock()
        alert_obj.source = "test_service"

        autonomy = MagicMock()
        autonomy.escalation.scan_service_states.return_value = {"test_service": {"status": "degraded"}}
        autonomy.escalation.evaluate_triggers.return_value = [alert_obj]
        autonomy.escalation.check_de_escalation.return_value = None
        autonomy.escalation.apply_quiet_hours.return_value = ([alert_obj], [])
        autonomy.escalation.format_alert.return_value = "Service degraded: test_service"

        discord = MagicMock()
        discord.send_message = AsyncMock()

        shutdown = asyncio.Event()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, autonomy=autonomy, discord=discord,
            ),
            _stop(),
        )

        discord.send_message.assert_awaited()
        msg = discord.send_message.call_args[0][1]
        assert "Service degraded" in msg

    async def test_escalation_scan_exception_handled(self, tmp_path: Path) -> None:
        """Escalation scan exception is caught and doesn't crash the loop."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        autonomy = MagicMock()
        autonomy.escalation.scan_service_states.side_effect = RuntimeError("scan failed")

        discord = MagicMock()

        shutdown = asyncio.Event()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, autonomy=autonomy, discord=discord,
            ),
            _stop(),
        )


# ---------------------------------------------------------------------------
# heartbeat_loop — tmux agent monitoring
# ---------------------------------------------------------------------------


class TestHeartbeatTmuxAgents:
    async def test_monitors_tmux_agents(self, tmp_path: Path) -> None:
        """heartbeat_loop calls tmux_agents.monitor_agents()."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        tmux_agents = MagicMock()
        tmux_agents.monitor_agents = AsyncMock(return_value=["agent-1 started"])

        shutdown = asyncio.Event()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, tmux_agents=tmux_agents,
            ),
            _stop(),
        )

        tmux_agents.monitor_agents.assert_awaited()

    async def test_tmux_agent_monitor_exception_handled(self, tmp_path: Path) -> None:
        """tmux agent monitor exception is caught and doesn't crash the loop."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None

        tmux_agents = MagicMock()
        tmux_agents.monitor_agents = AsyncMock(side_effect=RuntimeError("tmux error"))

        shutdown = asyncio.Event()

        async def _stop() -> None:
            await asyncio.sleep(0.12)
            shutdown.set()

        await asyncio.gather(
            background_loops.heartbeat_loop(
                shutdown, config, tmux_agents=tmux_agents,
            ),
            _stop(),
        )


# ---------------------------------------------------------------------------
# heartbeat_loop — resource management
# ---------------------------------------------------------------------------


class TestHeartbeatResourceManagement:
    async def test_disk_usage_alert(self, tmp_path: Path) -> None:
        """heartbeat_loop sends disk usage alert when usage >= 90%."""
        config = MagicMock()
        config.heartbeat_interval = 0.01
        config.data_dir = str(tmp_path)
        config.remote_halt_url = None
        config.log_dir = str(tmp_path / "logs")
        (tmp_path / "logs").mkdir()

        discord = MagicMock()
        discord.send_alert = AsyncMock()

        shutdown = asyncio.Event()
        heartbeat_count = [0]

        with patch("bridge.resource_manager.rotate_logs", return_value={"rotated": 0, "deleted": 0}), \
             patch("bridge.resource_manager.check_disk_usage", return_value={
                 "used_pct": 95.0, "free_gb": 5.0, "total_gb": 100.0,
             }):

            async def _stop() -> None:
                # Wait long enough for 10+ heartbeats to trigger resource check
                await asyncio.sleep(0.3)
                shutdown.set()

            await asyncio.gather(
                background_loops.heartbeat_loop(
                    shutdown, config, discord=discord,
                ),
                _stop(),
            )

        discord.send_alert.assert_awaited()
        alert_msg = discord.send_alert.call_args[0][0]
        assert "Disk usage critical" in alert_msg


# ---------------------------------------------------------------------------
# heartbeat_loop — remote halt via security manager
# ---------------------------------------------------------------------------


class TestHeartbeatRemoteHalt:
    async def test_remote_halt_activates(self, tmp_path: Path) -> None:
        """heartbeat_loop activates halt when security.check_remote_halt returns True."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = "https://example.com/halt"
        config.remote_halt_check_interval = 0  # check every time
        config.operator_discord_id = "12345"

        security = MagicMock()
        security.check_remote_halt = AsyncMock(return_value=True)
        security.set_halt = MagicMock()

        discord = MagicMock()
        discord.send_message = AsyncMock()

        shutdown = asyncio.Event()

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            async def _stop() -> None:
                await asyncio.sleep(0.12)
                shutdown.set()

            await asyncio.gather(
                background_loops.heartbeat_loop(
                    shutdown, config, security=security, discord=discord,
                ),
                _stop(),
            )

        security.set_halt.assert_called()

    async def test_remote_halt_exception_handled(self, tmp_path: Path) -> None:
        """Remote halt check exception is caught and doesn't crash the loop."""
        config = MagicMock()
        config.heartbeat_interval = 0.05
        config.data_dir = str(tmp_path)
        config.remote_halt_url = "https://example.com/halt"
        config.remote_halt_check_interval = 0

        security = MagicMock()
        security.check_remote_halt = AsyncMock(side_effect=RuntimeError("network error"))

        shutdown = asyncio.Event()

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            async def _stop() -> None:
                await asyncio.sleep(0.12)
                shutdown.set()

            await asyncio.gather(
                background_loops.heartbeat_loop(
                    shutdown, config, security=security,
                ),
                _stop(),
            )


# ---------------------------------------------------------------------------
# decay_loop — edge cases
# ---------------------------------------------------------------------------


class TestDecayLoopEdgeCases:
    async def test_memory_none_is_safe(self) -> None:
        """decay_loop runs without error when memory is None."""
        shutdown = asyncio.Event()

        with patch.object(background_loops, "DECAY_INTERVAL", 0.05):
            async def _stop() -> None:
                await asyncio.sleep(0.15)
                shutdown.set()

            await asyncio.gather(
                background_loops.decay_loop(shutdown, None),
                _stop(),
            )


# ---------------------------------------------------------------------------
# backup_loop — edge cases
# ---------------------------------------------------------------------------


class TestBackupLoopEdgeCases:
    async def test_db_none_is_safe(self) -> None:
        """backup_loop runs without error when db is None."""
        config = MagicMock()
        config.data_dir = "/tmp"

        shutdown = asyncio.Event()

        with patch.object(background_loops, "BACKUP_INTERVAL", 0.05):
            async def _stop() -> None:
                await asyncio.sleep(0.15)
                shutdown.set()

            await asyncio.gather(
                background_loops.backup_loop(shutdown, None, config),
                _stop(),
            )

    async def test_backup_integrity_failure_logged(self, tmp_path: Path) -> None:
        """backup_loop logs error when backup integrity check fails (ok=False)."""
        from bridge.database import Database

        db = MagicMock()
        db.backup_with_verify = AsyncMock(
            return_value=(str(tmp_path / "memory-test.db"), False)
        )

        config = MagicMock()
        config.data_dir = str(tmp_path)

        shutdown = asyncio.Event()

        with patch.object(background_loops, "BACKUP_INTERVAL", 0.05), \
             patch.object(Database, "rotate_backups", return_value=0):
            async def _stop() -> None:
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                background_loops.backup_loop(shutdown, db, config),
                _stop(),
            )

        db.backup_with_verify.assert_awaited()


# ---------------------------------------------------------------------------
# get_unhealthy_servers (#280)
# ---------------------------------------------------------------------------


class TestGetUnhealthyServers:
    def test_returns_crash_looping_server_names(self, tmp_path: Path) -> None:
        """get_unhealthy_servers returns names of servers in crash loop."""
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {
            "a": {"command": "x"}, "b": {"command": "y"}, "c": {"command": "z"},
        }}))
        monitor = MCPMonitor(path)

        monitor._server_states = {
            "a": MCPServerInfo(name="a", command="x", status="stopped"),
            "b": MCPServerInfo(name="b", command="y", status="stopped"),
            "c": MCPServerInfo(name="c", command="z", status="running", pid=1),
        }

        # Push "a" past the crash threshold
        for _ in range(CRASH_LOOP_THRESHOLD + 1):
            monitor._track_crash("a")

        unhealthy = monitor.get_unhealthy_servers()
        assert unhealthy == ["a"]

    def test_returns_empty_when_no_crash_loops(self, tmp_path: Path) -> None:
        """get_unhealthy_servers returns empty list when nothing is crashing."""
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {"a": {"command": "x"}}}))
        monitor = MCPMonitor(path)

        monitor._server_states = {
            "a": MCPServerInfo(name="a", command="x", status="running", pid=1),
        }

        assert monitor.get_unhealthy_servers() == []

    def test_returns_multiple_crash_looping_servers(self, tmp_path: Path) -> None:
        """get_unhealthy_servers returns all servers in crash loop."""
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {
            "bumba-memory": {"command": "x"},
            "figma-context": {"command": "y"},
            "github": {"command": "z"},
        }}))
        monitor = MCPMonitor(path)

        monitor._server_states = {
            "bumba-memory": MCPServerInfo(name="bumba-memory", command="x", status="stopped"),
            "figma-context": MCPServerInfo(name="figma-context", command="y", status="stopped"),
            "github": MCPServerInfo(name="github", command="z", status="running", pid=1),
        }

        for name in ["bumba-memory", "figma-context"]:
            for _ in range(CRASH_LOOP_THRESHOLD + 1):
                monitor._track_crash(name)

        unhealthy = monitor.get_unhealthy_servers()
        assert set(unhealthy) == {"bumba-memory", "figma-context"}


# ---------------------------------------------------------------------------
# warm_claude_health_loop (Sprint D8.4)
# ---------------------------------------------------------------------------


class TestWarmClaudeHealthLoop:
    """Sprint D8.4 — proactive warm-process health monitor."""

    @staticmethod
    def _short_interval(monkeypatch) -> None:
        """Patch the 30s interval down to 50ms so tests don't wait."""
        monkeypatch.setattr(background_loops, "WARM_CLAUDE_HEALTH_INTERVAL", 0.05)

    @staticmethod
    async def _run_for(coro_factory, ticks: float = 0.18) -> None:
        """Drive the loop for *ticks* seconds, then signal shutdown and join."""
        shutdown = asyncio.Event()
        task = asyncio.create_task(coro_factory(shutdown))
        try:
            await asyncio.sleep(ticks)
        finally:
            shutdown.set()
            await asyncio.wait_for(task, timeout=1.0)

    async def test_health_loop_does_nothing_when_warm_alive(
        self, monkeypatch
    ) -> None:
        """Provider returns a live warm process — no respawn scheduled."""
        self._short_interval(monkeypatch)

        warm = MagicMock()
        warm.is_alive = True
        warm._respawn_in_progress = False
        warm._working_dir = "/tmp/test"
        warm._background_respawn = AsyncMock()
        warm.spawn = AsyncMock()

        await self._run_for(
            lambda sd: background_loops.warm_claude_health_loop(sd, lambda: warm)
        )

        warm._background_respawn.assert_not_called()
        warm.spawn.assert_not_called()

    async def test_health_loop_schedules_respawn_when_dead(
        self, monkeypatch
    ) -> None:
        """Dead warm process with no respawn-in-progress → _background_respawn fires."""
        self._short_interval(monkeypatch)

        warm = MagicMock()
        warm.is_alive = False
        warm._respawn_in_progress = False
        warm._working_dir = "/tmp/test"
        warm._background_respawn = AsyncMock()

        await self._run_for(
            lambda sd: background_loops.warm_claude_health_loop(sd, lambda: warm)
        )

        # _background_respawn should have been called at least once. The loop
        # also flips _respawn_in_progress=True on the warm mock, but the mock
        # doesn't reflect that into is_alive — so multiple ticks may schedule
        # multiple respawns. We only assert "was called", not "called once".
        assert warm._background_respawn.await_count >= 1

    async def test_health_loop_skips_when_respawn_in_progress(
        self, monkeypatch
    ) -> None:
        """Dead warm process but respawn already in progress → skip."""
        self._short_interval(monkeypatch)

        warm = MagicMock()
        warm.is_alive = False
        warm._respawn_in_progress = True
        warm._working_dir = "/tmp/test"
        warm._background_respawn = AsyncMock()
        warm.spawn = AsyncMock()

        await self._run_for(
            lambda sd: background_loops.warm_claude_health_loop(sd, lambda: warm)
        )

        warm._background_respawn.assert_not_called()
        warm.spawn.assert_not_called()

    async def test_health_loop_skips_when_provider_returns_none(
        self, monkeypatch
    ) -> None:
        """Provider returns None — loop tolerates it without raising."""
        self._short_interval(monkeypatch)

        # Just running the loop without a warm process should not raise.
        await self._run_for(
            lambda sd: background_loops.warm_claude_health_loop(sd, lambda: None)
        )

    async def test_health_loop_exits_on_shutdown(self, monkeypatch) -> None:
        """Loop returns within 1s once shutdown_event is set, even on long interval."""
        # Use the real 30s interval — shutdown should still preempt the wait.
        shutdown = asyncio.Event()
        shutdown.set()  # pre-set

        warm = MagicMock()
        warm.is_alive = True

        await asyncio.wait_for(
            background_loops.warm_claude_health_loop(shutdown, lambda: warm),
            timeout=1.0,
        )

    async def test_health_loop_skips_when_working_dir_empty(
        self, monkeypatch
    ) -> None:
        """Dead warm process with no working_dir (never spawned) → skip."""
        self._short_interval(monkeypatch)

        warm = MagicMock()
        warm.is_alive = False
        warm._respawn_in_progress = False
        warm._working_dir = ""  # never spawned
        warm._background_respawn = AsyncMock()
        warm.spawn = AsyncMock()

        await self._run_for(
            lambda sd: background_loops.warm_claude_health_loop(sd, lambda: warm)
        )

        warm._background_respawn.assert_not_called()
        warm.spawn.assert_not_called()

    async def test_health_loop_falls_back_to_spawn_when_d8_3_absent(
        self, monkeypatch
    ) -> None:
        """When _background_respawn is missing (D8.3 not merged), fall back to spawn()."""
        self._short_interval(monkeypatch)

        # Use a plain object (not MagicMock) so attribute access for
        # _background_respawn raises AttributeError instead of auto-creating.
        class _BareWarm:
            is_alive = False
            _respawn_in_progress = False
            _working_dir = "/tmp/test"
            _model = "haiku"
            _system_prompt_file = None

            def __init__(self) -> None:
                self.spawn = AsyncMock(return_value=True)

        warm = _BareWarm()

        await self._run_for(
            lambda sd: background_loops.warm_claude_health_loop(sd, lambda: warm)
        )

        # The fallback path should have called spawn() at least once.
        assert warm.spawn.await_count >= 1
        # And it should have passed the stored working_dir + model.
        first_call = warm.spawn.await_args_list[0]
        assert first_call.args[0] == "/tmp/test"
        assert first_call.args[1] == "haiku"
        assert first_call.args[2] is None

    async def test_health_loop_tolerates_provider_exception(
        self, monkeypatch
    ) -> None:
        """Provider raising an exception is logged and the loop continues."""
        self._short_interval(monkeypatch)

        def _bad_provider():
            raise RuntimeError("provider boom")

        # Should not raise — just log and continue until shutdown.
        await self._run_for(
            lambda sd: background_loops.warm_claude_health_loop(sd, _bad_provider)
        )
