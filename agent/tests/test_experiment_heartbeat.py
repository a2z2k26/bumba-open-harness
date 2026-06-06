"""Tests for ``bridge.experiment_heartbeat`` (Sprint 02.13 / #988).

Coverage:
- write/read round-trip
- read defensive paths (missing file, malformed JSON, wrong shape)
- compute_status state machine (alive / stale / unknown)
- PID liveness via os.kill(pid, 0)
- atomic-write semantics (no partial JSON visible to readers)
- /healthz integration: HealthServer surfaces the block
- /health command formatter handles alive / stale / unknown
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bridge.experiment_heartbeat import (
    DEFAULT_STALE_THRESHOLD_SECONDS,
    ExperimentLoopState,
    compute_status,
    healthz_block,
    is_pid_running,
    read_heartbeat,
    write_heartbeat,
)


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def heartbeat_path(tmp_path: Path) -> Path:
    return tmp_path / "experiment-loop-heartbeat.json"


_UNSET: object = object()


def _live_state(
    *,
    pid: int | None = None,
    iter_id: str = "iter-0042",
    started: str | None = None,
    completed: object = _UNSET,
    status: str = "idle",
    fitness: float | None = 11.8,
) -> ExperimentLoopState:
    """Build a synthetic state. ``completed=None`` means in-progress."""
    now = datetime.now(timezone.utc)
    if completed is _UNSET:
        completed_iso: str | None = now.isoformat()
    else:
        completed_iso = completed  # type: ignore[assignment]
    return ExperimentLoopState(
        last_iter_id=iter_id,
        last_started_at_iso=started or now.isoformat(),
        last_completed_at_iso=completed_iso,
        pid=pid if pid is not None else os.getpid(),
        status=status,  # type: ignore[arg-type]
        fitness_value=fitness,
    )


# --- write / read round-trip ------------------------------------------------


class TestWriteRead:
    def test_round_trip(self, heartbeat_path: Path) -> None:
        state = _live_state()
        write_heartbeat(state, path=heartbeat_path)
        loaded = read_heartbeat(path=heartbeat_path)
        assert loaded == state

    def test_round_trip_running_status(self, heartbeat_path: Path) -> None:
        state = _live_state(status="running", completed=None, fitness=None)
        write_heartbeat(state, path=heartbeat_path)
        loaded = read_heartbeat(path=heartbeat_path)
        assert loaded is not None
        assert loaded.last_completed_at_iso is None
        assert loaded.status == "running"
        assert loaded.fitness_value is None

    def test_read_missing_file(self, heartbeat_path: Path) -> None:
        assert not heartbeat_path.exists()
        assert read_heartbeat(path=heartbeat_path) is None

    def test_read_malformed_json(self, heartbeat_path: Path) -> None:
        heartbeat_path.write_text("{not valid json")
        assert read_heartbeat(path=heartbeat_path) is None

    def test_read_wrong_shape(self, heartbeat_path: Path) -> None:
        # Valid JSON but missing required keys.
        heartbeat_path.write_text(json.dumps({"foo": "bar"}))
        assert read_heartbeat(path=heartbeat_path) is None

    def test_read_non_object(self, heartbeat_path: Path) -> None:
        heartbeat_path.write_text(json.dumps([1, 2, 3]))
        assert read_heartbeat(path=heartbeat_path) is None

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "heartbeat.json"
        write_heartbeat(_live_state(), path=nested)
        assert nested.exists()


# --- compute_status state machine ------------------------------------------


class TestComputeStatus:
    def test_alive_recent_heartbeat(self, heartbeat_path: Path) -> None:
        now = datetime.now(timezone.utc)
        state = _live_state(
            started=(now - timedelta(seconds=120)).isoformat(),
            completed=(now - timedelta(seconds=60)).isoformat(),
        )
        write_heartbeat(state, path=heartbeat_path)
        status, age = compute_status(
            stale_threshold_seconds=1200,
            path=heartbeat_path,
        )
        assert status == "alive"
        assert age is not None
        assert 50 <= age <= 120

    def test_stale_old_heartbeat(self, heartbeat_path: Path) -> None:
        now = datetime.now(timezone.utc)
        state = _live_state(
            started=(now - timedelta(seconds=2000)).isoformat(),
            completed=(now - timedelta(seconds=1500)).isoformat(),
        )
        write_heartbeat(state, path=heartbeat_path)
        status, age = compute_status(
            stale_threshold_seconds=1200,
            path=heartbeat_path,
        )
        assert status == "stale"
        assert age is not None
        assert age >= 1200

    def test_unknown_missing_file(self, heartbeat_path: Path) -> None:
        status, age = compute_status(path=heartbeat_path)
        assert status == "unknown"
        assert age is None

    def test_unknown_dead_pid(self, heartbeat_path: Path) -> None:
        # Use a PID very unlikely to exist. 999_999_999 is well above
        # macOS / Linux PID_MAX so os.kill will raise ProcessLookupError.
        state = _live_state(pid=999_999_999)
        write_heartbeat(state, path=heartbeat_path)
        status, age = compute_status(path=heartbeat_path)
        assert status == "unknown"
        assert age is None

    def test_in_progress_uses_started_at(self, heartbeat_path: Path) -> None:
        # Iteration in flight: completed_at is None, age computed
        # against started_at instead.
        now = datetime.now(timezone.utc)
        state = _live_state(
            started=(now - timedelta(seconds=300)).isoformat(),
            completed=None,
            status="running",
        )
        write_heartbeat(state, path=heartbeat_path)
        status, age = compute_status(
            stale_threshold_seconds=1200,
            path=heartbeat_path,
        )
        assert status == "alive"
        assert age is not None
        assert 290 <= age <= 320

    def test_explicit_state_override(self) -> None:
        # Allows testing without writing a file (now_iso path).
        now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        state = ExperimentLoopState(
            last_iter_id="iter-0001",
            last_started_at_iso=(now - timedelta(seconds=600)).isoformat(),
            last_completed_at_iso=(now - timedelta(seconds=60)).isoformat(),
            pid=os.getpid(),
            status="idle",
        )
        status, age = compute_status(
            state=state,
            now_iso=now.isoformat(),
            stale_threshold_seconds=1200,
        )
        assert status == "alive"
        assert age == pytest.approx(60.0, abs=0.5)


# --- PID liveness -----------------------------------------------------------


class TestIsPidRunning:
    def test_self_pid_running(self) -> None:
        assert is_pid_running(os.getpid()) is True

    def test_unlikely_pid_dead(self) -> None:
        # 999_999_999 sits above PID_MAX on every supported OS.
        assert is_pid_running(999_999_999) is False

    def test_zero_pid_returns_false(self) -> None:
        # os.kill(0, 0) targets the whole process group on POSIX —
        # treat it as not-running rather than raising.
        assert is_pid_running(0) is False

    def test_negative_pid_returns_false(self) -> None:
        assert is_pid_running(-1) is False


# --- atomic write -----------------------------------------------------------


class TestAtomicWrite:
    def test_no_partial_json_during_concurrent_read(
        self, heartbeat_path: Path
    ) -> None:
        """A reader that catches mid-write should never see partial JSON.

        We exercise the writer in a tight loop on one thread and the
        reader on another; either ``read_heartbeat`` returns a valid
        ``ExperimentLoopState`` (post-rename) or ``None`` (pre-write or
        rename in progress). It must NEVER raise a JSONDecodeError.
        """
        write_heartbeat(_live_state(iter_id="iter-init"), path=heartbeat_path)

        stop = threading.Event()
        seen_invalid = []

        def writer() -> None:
            i = 0
            while not stop.is_set():
                write_heartbeat(
                    _live_state(iter_id=f"iter-{i:04d}"),
                    path=heartbeat_path,
                )
                i += 1

        def reader() -> None:
            while not stop.is_set():
                try:
                    raw = heartbeat_path.read_text() if heartbeat_path.exists() else "{}"
                    json.loads(raw)
                except json.JSONDecodeError:
                    seen_invalid.append("partial-json")
                except FileNotFoundError:
                    pass

        t_w = threading.Thread(target=writer)
        t_r = threading.Thread(target=reader)
        t_w.start()
        t_r.start()
        time.sleep(0.5)
        stop.set()
        t_w.join(timeout=2)
        t_r.join(timeout=2)

        assert seen_invalid == [], (
            "Atomic-write contract broken: reader observed partial JSON "
            f"{seen_invalid[:3]} times"
        )


# --- /healthz integration ---------------------------------------------------


class TestHealthzBlock:
    def test_block_alive(self, heartbeat_path: Path) -> None:
        write_heartbeat(_live_state(), path=heartbeat_path)
        block = healthz_block(path=heartbeat_path, stale_threshold_seconds=1200)
        assert block["experiment_loop_status"] == "alive"
        assert block["experiment_loop_pid"] == os.getpid()
        assert block["experiment_loop_last_iter_id"] == "iter-0042"

    def test_block_unknown_when_missing(self, heartbeat_path: Path) -> None:
        block = healthz_block(path=heartbeat_path)
        assert block["experiment_loop_status"] == "unknown"
        assert block["experiment_loop_pid"] is None

    def test_block_stale(self, heartbeat_path: Path) -> None:
        now = datetime.now(timezone.utc)
        state = _live_state(
            started=(now - timedelta(seconds=2000)).isoformat(),
            completed=(now - timedelta(seconds=1500)).isoformat(),
        )
        write_heartbeat(state, path=heartbeat_path)
        block = healthz_block(path=heartbeat_path, stale_threshold_seconds=1200)
        assert block["experiment_loop_status"] == "stale"
        assert block["experiment_loop_last_iter_age_seconds"] is not None
        assert block["experiment_loop_last_iter_age_seconds"] >= 1200


# --- HealthServer integration (#988 in /healthz) ---------------------------


class TestHealthServerIntegration:
    @pytest.mark.asyncio
    async def test_healthz_includes_experiment_loop(
        self, tmp_path: Path
    ) -> None:
        """Wire-up smoke test: HealthServer renders the experiment_loop block."""
        from unittest.mock import AsyncMock, MagicMock

        from bridge.health import HealthServer

        # Minimal mock app — only the bits HealthServer needs.
        app = MagicMock()
        bot = MagicMock()
        bot.is_ready.return_value = True
        bot.latency = 0.05
        app._discord = bot
        app._claude = MagicMock(_last_invocation=None)
        db = AsyncMock()
        db.db_path = MagicMock()
        db.db_path.exists.return_value = True
        db.db_path.stat.return_value = MagicMock(st_size=1024)
        db.db_path.with_suffix.return_value = MagicMock(exists=lambda: False)
        db.fetchone = AsyncMock(
            side_effect=[
                MagicMock(__getitem__=lambda s, i: "ok"),
                MagicMock(__getitem__=lambda s, i: 1),
            ]
        )
        db.fetchall = AsyncMock(return_value=[])
        app._db = db
        memory = AsyncMock()
        memory.search_knowledge = AsyncMock(return_value=[])
        app._memory = memory
        refresher = MagicMock()
        refresher._expires_at = time.time() + 7200
        app._token_refresher = refresher
        config = MagicMock()
        config.data_dir = str(tmp_path)
        config.experiment_heartbeat_stale_seconds = 1200
        app._config = config

        # Write a fresh heartbeat into the configured data_dir.
        heartbeat_path = tmp_path / "experiment-loop-heartbeat.json"
        write_heartbeat(_live_state(), path=heartbeat_path)

        server = HealthServer(app)
        health = await server.collect_health()

        assert "experiment_loop" in health["components"]
        block = health["components"]["experiment_loop"]
        assert block["experiment_loop_status"] == "alive"
        assert block["status"] == "up"
        # Loop being detected must not poison overall status.
        assert health["status"] in ("healthy", "degraded")

    @pytest.mark.asyncio
    async def test_healthz_unknown_does_not_poison_overall(
        self, tmp_path: Path
    ) -> None:
        """Missing heartbeat file -> disabled status, not unhealthy."""
        from unittest.mock import AsyncMock, MagicMock

        from bridge.health import HealthServer

        app = MagicMock()
        bot = MagicMock()
        bot.is_ready.return_value = True
        bot.latency = 0.05
        app._discord = bot
        app._claude = MagicMock(_last_invocation=None)
        db = AsyncMock()
        db.db_path = MagicMock()
        db.db_path.exists.return_value = True
        db.db_path.stat.return_value = MagicMock(st_size=1024)
        db.db_path.with_suffix.return_value = MagicMock(exists=lambda: False)
        db.fetchone = AsyncMock(
            side_effect=[
                MagicMock(__getitem__=lambda s, i: "ok"),
                MagicMock(__getitem__=lambda s, i: 1),
            ]
        )
        db.fetchall = AsyncMock(return_value=[])
        app._db = db
        memory = AsyncMock()
        memory.search_knowledge = AsyncMock(return_value=[])
        app._memory = memory
        refresher = MagicMock()
        refresher._expires_at = time.time() + 7200
        app._token_refresher = refresher
        config = MagicMock()
        config.data_dir = str(tmp_path)
        config.experiment_heartbeat_stale_seconds = 1200
        app._config = config

        server = HealthServer(app)
        health = await server.collect_health()

        block = health["components"]["experiment_loop"]
        assert block["experiment_loop_status"] == "unknown"
        assert block["status"] == "disabled"
        assert health["status"] == "healthy"


# --- Config field -----------------------------------------------------------


class TestConfigField:
    def test_default_threshold_in_bridge_config(self) -> None:
        from bridge.config import BridgeConfig

        config = BridgeConfig()
        assert (
            config.experiment_heartbeat_stale_seconds
            == DEFAULT_STALE_THRESHOLD_SECONDS
        )
