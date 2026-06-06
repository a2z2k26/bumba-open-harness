"""Tests for MS1.9: MCP Runtime Health Monitoring."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from bridge.mcp_monitor import CRASH_LOOP_THRESHOLD, CRASH_LOOP_WINDOW, MCPMonitor, MCPServerInfo


# -- Sample configs --------------------------------------------------------

SAMPLE_MCP_CONFIG = {
    "mcpServers": {
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        },
        "memory": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
        },
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
        },
    },
    "_mcpServers_disabled": {
        "playwright": {
            "command": "npx",
            "args": ["-y", "@playwright/mcp"],
        },
    },
}

EMPTY_MCP_CONFIG = {"mcpServers": {}}


# -- Helpers ---------------------------------------------------------------

def _write_config(tmp_path, config: dict):
    """Write a config dict as .mcp.json and return the path."""
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(config))
    return path


# -- Tests -----------------------------------------------------------------

class TestLoadExpectedServers:
    """load_expected_servers() tests."""

    def test_load_expected_servers(self, tmp_path):
        """3 enabled, 1 disabled → returns 3 names."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)
        names = monitor.load_expected_servers()

        assert len(names) == 3
        assert set(names) == {"filesystem", "memory", "github"}

    def test_load_empty_config(self, tmp_path):
        """Empty mcpServers → returns []."""
        path = _write_config(tmp_path, EMPTY_MCP_CONFIG)
        monitor = MCPMonitor(path)
        names = monitor.load_expected_servers()

        assert names == []

    def test_load_missing_file(self, tmp_path):
        """Nonexistent path → returns [] gracefully."""
        path = tmp_path / "nonexistent.json"
        monitor = MCPMonitor(path)
        names = monitor.load_expected_servers()

        assert names == []


class TestMCPServerInfoDataclass:
    """MCPServerInfo dataclass tests."""

    def test_server_info_dataclass(self):
        """Create MCPServerInfo and verify all fields."""
        info = MCPServerInfo(
            name="filesystem",
            command="npx",
            pid=12345,
            status="running",
            memory_mb=42.5,
            last_seen="2026-03-13T10:00:00+00:00",
        )

        assert info.name == "filesystem"
        assert info.command == "npx"
        assert info.pid == 12345
        assert info.status == "running"
        assert info.memory_mb == 42.5
        assert info.last_seen == "2026-03-13T10:00:00+00:00"

    def test_server_info_defaults(self):
        """Defaults: pid=None, status=unknown, memory=0.0, last_seen=''."""
        info = MCPServerInfo(name="test", command="node")

        assert info.pid is None
        assert info.status == "unknown"
        assert info.memory_mb == 0.0
        assert info.last_seen == ""


class TestStatusSummary:
    """get_status_summary() tests."""

    def test_status_summary(self, tmp_path):
        """After setting server states, summary reflects counts."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)

        # Manually populate server states
        monitor._server_states = {
            "filesystem": MCPServerInfo(name="filesystem", command="npx", status="running", pid=100),
            "memory": MCPServerInfo(name="memory", command="npx", status="stopped"),
            "github": MCPServerInfo(name="github", command="npx", status="running", pid=200),
        }

        summary = monitor.get_status_summary()

        assert summary["total"] == 3
        assert summary["running"] == 2
        assert summary["stopped"] == 1
        assert summary["crash_loop"] == 0

    def test_status_summary_empty(self, tmp_path):
        """No server states → all zeros."""
        path = _write_config(tmp_path, EMPTY_MCP_CONFIG)
        monitor = MCPMonitor(path)
        summary = monitor.get_status_summary()

        assert summary["total"] == 0
        assert summary["running"] == 0
        assert summary["stopped"] == 0
        assert summary["crash_loop"] == 0


class TestCrashTracking:
    """_track_crash / _is_crash_loop tests."""

    def test_crash_tracking(self, tmp_path):
        """Record >threshold crashes in 1 hour → _is_crash_loop returns True."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)

        for _ in range(CRASH_LOOP_THRESHOLD + 1):
            monitor._track_crash("filesystem")

        assert monitor._is_crash_loop("filesystem") is True

    def test_crash_tracking_below_threshold(self, tmp_path):
        """Fewer crashes than threshold → not a crash loop."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)

        for _ in range(CRASH_LOOP_THRESHOLD):
            monitor._track_crash("filesystem")

        assert monitor._is_crash_loop("filesystem") is False

    def test_crash_tracking_old(self, tmp_path):
        """Crashes older than 1 hour → _is_crash_loop returns False."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)

        # Inject old timestamps (more than CRASH_LOOP_WINDOW ago)
        old_time = time.time() - CRASH_LOOP_WINDOW - 100
        monitor._crash_history["filesystem"] = [
            old_time + i for i in range(CRASH_LOOP_THRESHOLD + 1)
        ]

        assert monitor._is_crash_loop("filesystem") is False


class TestProcessMemory:
    """_get_process_memory tests."""

    @pytest.mark.asyncio
    async def test_get_process_memory_nonexistent(self, tmp_path):
        """PID that doesn't exist → returns 0.0."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)

        # Mock asyncio.create_subprocess_exec to simulate a missing process
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await monitor._get_process_memory(99999)

        assert result == 0.0

    @pytest.mark.asyncio
    async def test_get_process_memory_valid(self, tmp_path):
        """Valid PID with RSS output → returns MB value."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)

        # 102400 KB = 100 MB
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"102400\n", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await monitor._get_process_memory(12345)

        assert result == 100.0


class TestCheckServerHealth:
    """check_server_health / _check_server tests."""

    @pytest.mark.asyncio
    async def test_check_server_running(self, tmp_path):
        """Server found by pgrep → status=running with PID and memory."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)

        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            proc = AsyncMock()
            if args[0] == "pgrep":
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"42\n", b""))
            elif args[0] == "ps":
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"51200\n", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            info = await monitor._check_server("filesystem", "npx")

        assert info.status == "running"
        assert info.pid == 42
        assert info.memory_mb == 50.0
        assert info.last_seen != ""

    @pytest.mark.asyncio
    async def test_check_server_stopped(self, tmp_path):
        """Server not found by pgrep → status=stopped."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            info = await monitor._check_server("filesystem", "npx")

        assert info.status == "stopped"
        assert info.pid is None

    @pytest.mark.asyncio
    async def test_check_server_health_full(self, tmp_path):
        """check_server_health returns info for all enabled servers."""
        path = _write_config(tmp_path, SAMPLE_MCP_CONFIG)
        monitor = MCPMonitor(path)

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await monitor.check_server_health()

        assert len(results) == 3
        assert "filesystem" in results
        assert "memory" in results
        assert "github" in results
        # All stopped since pgrep returned 1
        for info in results.values():
            assert info.status == "stopped"

# ---------------------------------------------------------------------------
# D7.7 (#1232) additions: _derive_pgrep_pattern + RECENT_RUN_WINDOW gating
# ---------------------------------------------------------------------------

from bridge.mcp_monitor import _derive_pgrep_pattern, RECENT_RUN_WINDOW
import time as _time


class TestDerivePgrepPattern:
    """D7.7: pgrep pattern derivation for reliable mcp-remote matching."""

    def test_mcp_remote_https_url_returns_host(self):
        cfg = {"command": "node", "args": ["/path/to/mcp-remote", "https://bindings.mcp.cloudflare.com/mcp"]}
        assert _derive_pgrep_pattern("cloudflare", cfg) == "bindings.mcp.cloudflare.com"

    def test_mcp_remote_http_url_returns_host(self):
        cfg = {"args": ["http://localhost:8080/mcp"]}
        assert _derive_pgrep_pattern("local", cfg) == "localhost"

    def test_npx_scoped_package_returns_package(self):
        # Iterates in reverse; package is the last positional arg (no extra path args).
        cfg = {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}
        assert _derive_pgrep_pattern("fs", cfg) == "@modelcontextprotocol/server-filesystem"

    def test_npx_unscoped_with_slash_returns_package(self):
        cfg = {"command": "npx", "args": ["-y", "some/package"]}
        assert _derive_pgrep_pattern("s", cfg) == "some/package"

    def test_fallback_to_name_empty_args(self):
        cfg = {"command": "python", "args": []}
        assert _derive_pgrep_pattern("myserver", cfg) == "myserver"

    def test_missing_args_key_falls_back_to_name(self):
        cfg = {"command": "node"}
        assert _derive_pgrep_pattern("bumba-memory", cfg) == "bumba-memory"

    def test_url_with_path_and_query_extracts_host(self):
        cfg = {"args": ["https://example.com/api/v2/mcp?token=abc"]}
        assert _derive_pgrep_pattern("example", cfg) == "example.com"

    def test_non_string_args_skipped(self):
        cfg = {"args": [None, 42, "https://example.com/mcp"]}
        assert _derive_pgrep_pattern("srv", cfg) == "example.com"


class TestLastSeenRunningInit:
    """D7.7: _last_seen_running initialised empty on construction."""

    def test_last_seen_running_initialised_empty(self, tmp_path):
        cfg = tmp_path / ".mcp.json"
        cfg.write_text("{}")
        mon = MCPMonitor(cfg)
        assert mon._last_seen_running == {}

    def test_ever_seen_running_initialised_empty(self, tmp_path):
        cfg = tmp_path / ".mcp.json"
        cfg.write_text("{}")
        mon = MCPMonitor(cfg)
        assert mon._ever_seen_running == set()


class TestRecentRunWindowGating:
    """D7.7: crash tracking gated by RECENT_RUN_WINDOW for on-demand MCPs."""

    def _make_monitor(self, tmp_path):
        cfg = tmp_path / ".mcp.json"
        cfg.write_text("{}")
        return MCPMonitor(cfg)

    def _fake_stopped_proc(self):
        from unittest.mock import AsyncMock, MagicMock
        p = MagicMock()
        p.returncode = 1
        p.communicate = AsyncMock(return_value=(b"", b""))
        return p

    @pytest.mark.asyncio
    async def test_stopped_never_seen_no_crash_entry(self, tmp_path):
        """Server never ran — stopped must NOT accumulate crash entries."""
        from unittest.mock import patch
        mon = self._make_monitor(tmp_path)
        with patch("bridge.mcp_monitor.asyncio.create_subprocess_exec", return_value=self._fake_stopped_proc()):
            await mon._check_server("fresh", {"command": "node", "args": []})
        assert mon._crash_history.get("fresh", []) == []

    @pytest.mark.asyncio
    async def test_stopped_within_window_tracks_crash(self, tmp_path):
        """Server stopped but was last seen 30s ago — within RECENT_RUN_WINDOW."""
        from unittest.mock import patch
        mon = self._make_monitor(tmp_path)
        mon._ever_seen_running.add("cloudflare")
        mon._last_seen_running["cloudflare"] = _time.time() - 30

        with patch("bridge.mcp_monitor.asyncio.create_subprocess_exec", return_value=self._fake_stopped_proc()):
            await mon._check_server("cloudflare", {"command": "node", "args": []})

        assert len(mon._crash_history.get("cloudflare", [])) == 1

    @pytest.mark.asyncio
    async def test_stopped_outside_window_no_crash_entry(self, tmp_path):
        """Server stopped and last seen > RECENT_RUN_WINDOW ago — on-demand MCP, no false crash."""
        from unittest.mock import patch
        mon = self._make_monitor(tmp_path)
        mon._ever_seen_running.add("cloudflare")
        mon._last_seen_running["cloudflare"] = _time.time() - (RECENT_RUN_WINDOW + 60)

        with patch("bridge.mcp_monitor.asyncio.create_subprocess_exec", return_value=self._fake_stopped_proc()):
            await mon._check_server("cloudflare", {"command": "node", "args": []})

        assert mon._crash_history.get("cloudflare", []) == []

    @pytest.mark.asyncio
    async def test_running_server_updates_last_seen_running(self, tmp_path):
        """Running server updates _last_seen_running timestamp."""
        from unittest.mock import AsyncMock, MagicMock, patch
        mon = self._make_monitor(tmp_path)
        before = _time.time()

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.communicate = AsyncMock(return_value=(b"1234\n", b""))
        mon._get_process_memory = AsyncMock(return_value=42.0)

        with patch("bridge.mcp_monitor.asyncio.create_subprocess_exec", return_value=fake_proc):
            info = await mon._check_server("cloudflare", {"command": "node", "args": ["https://bindings.mcp.cloudflare.com/mcp"]})

        assert info.status == "running"
        assert mon._last_seen_running.get("cloudflare", 0) >= before


class TestCheckServerBackwardCompat:
    """D7.7: backward compat — bare string cfg uses server name as pgrep pattern."""

    @pytest.mark.asyncio
    async def test_bare_string_cfg_uses_name_as_pattern(self, tmp_path):
        from unittest.mock import AsyncMock, MagicMock, patch
        cfg = tmp_path / ".mcp.json"
        cfg.write_text("{}")
        mon = MCPMonitor(cfg)

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.communicate = AsyncMock(return_value=(b"999\n", b""))
        mon._get_process_memory = AsyncMock(return_value=0.0)

        with patch("bridge.mcp_monitor.asyncio.create_subprocess_exec", return_value=fake_proc) as mock_exec:
            await mon._check_server("myserver", "node /path/myserver")

        call_args = mock_exec.call_args[0]
        assert "myserver" in call_args


# ---------------------------------------------------------------------------
# Issue #1543: EscalationEngine tie-in — record_health_state state file
# ---------------------------------------------------------------------------


class TestRecordHealthState:
    """Issue #1543: ``record_health_state`` emits a state file matching the
    EscalationEngine's scheduled-service contract so consecutive failures
    progress through CASUAL (1) → NUDGE (3) → URGENT (5)."""

    def _monitor(self, tmp_path):
        cfg = tmp_path / ".mcp.json"
        cfg.write_text(json.dumps(EMPTY_MCP_CONFIG))
        state_dir = tmp_path / "service_state"
        return MCPMonitor(cfg, state_dir=state_dir), state_dir

    def test_no_op_without_state_dir(self, tmp_path):
        """When constructed without state_dir, record_health_state writes
        nothing — preserves legacy callers that don't opt in."""
        cfg = tmp_path / ".mcp.json"
        cfg.write_text(json.dumps(EMPTY_MCP_CONFIG))
        mon = MCPMonitor(cfg)  # no state_dir
        mon.record_health_state()
        # No file should have been written anywhere.
        assert list(tmp_path.glob("*-state.json")) == []

    def test_writes_state_file_with_zero_failures_when_healthy(self, tmp_path):
        mon, state_dir = self._monitor(tmp_path)
        # No crash-looped servers — should write success state.
        mon.record_health_state()

        path = state_dir / "mcp_monitor-state.json"
        assert path.exists()
        state = json.loads(path.read_text())
        assert state["consecutive_failures"] == 0
        assert state["last_error"] is None
        assert state["last_run"] is not None
        assert state["unhealthy_servers"] == []

    def test_writes_state_file_with_one_failure_when_crash_loop(self, tmp_path):
        mon, state_dir = self._monitor(tmp_path)

        # Force a crash-loop state for "memory" without running pgrep.
        now = _time.time()
        mon._server_states = {
            "memory": MCPServerInfo(name="memory", command="npx", status="stopped"),
        }
        mon._crash_history["memory"] = [now] * (CRASH_LOOP_THRESHOLD + 2)

        mon.record_health_state()

        state = json.loads((state_dir / "mcp_monitor-state.json").read_text())
        assert state["consecutive_failures"] == 1
        assert state["last_error"] is not None
        assert "memory" in state["last_error"]
        assert "memory" in state["unhealthy_servers"]

    def test_consecutive_failures_increment_across_calls(self, tmp_path):
        """Three crash-loop ticks should advance consecutive_failures from
        0 → 1 → 2 → 3 (which matches the engine's NUDGE threshold)."""
        mon, state_dir = self._monitor(tmp_path)

        # Set the monitor to "crash-looping memory" for all three ticks.
        now = _time.time()
        mon._server_states = {
            "memory": MCPServerInfo(name="memory", command="npx", status="stopped"),
        }
        mon._crash_history["memory"] = [now] * (CRASH_LOOP_THRESHOLD + 2)

        for _ in range(3):
            mon.record_health_state()

        state = json.loads((state_dir / "mcp_monitor-state.json").read_text())
        assert state["consecutive_failures"] == 3

    def test_success_resets_consecutive_failures(self, tmp_path):
        """After a recovery tick (no crash-loops), the counter resets so
        EscalationEngine.check_de_escalation can clear the active alert."""
        mon, state_dir = self._monitor(tmp_path)

        # First: simulate 2 consecutive failures.
        now = _time.time()
        mon._server_states = {
            "memory": MCPServerInfo(name="memory", command="npx", status="stopped"),
        }
        mon._crash_history["memory"] = [now] * (CRASH_LOOP_THRESHOLD + 2)
        mon.record_health_state()
        mon.record_health_state()

        state = json.loads((state_dir / "mcp_monitor-state.json").read_text())
        assert state["consecutive_failures"] == 2

        # Then: clear the crash loop and re-record. Counter must reset.
        mon._crash_history["memory"] = []
        mon.record_health_state()

        state = json.loads((state_dir / "mcp_monitor-state.json").read_text())
        assert state["consecutive_failures"] == 0
        assert state["last_error"] is None

    def test_state_filename_matches_escalation_contract(self, tmp_path):
        """EscalationEngine reads ``<state_dir>/<service>-state.json`` and
        derives ``source`` from the filename. The monitor's filename must
        therefore be ``mcp_monitor-state.json`` so the existing trigger
        matrix routes alerts under the ``mcp_monitor`` source key."""
        mon, state_dir = self._monitor(tmp_path)
        mon.record_health_state()
        assert (state_dir / MCPMonitor.STATE_FILENAME).exists()
        assert MCPMonitor.STATE_FILENAME == "mcp_monitor-state.json"

    def test_engine_sees_state_and_fires_casual_at_one_failure(self, tmp_path):
        """End-to-end: write a 1-failure state file, ask the engine to
        scan it, expect a CASUAL alert with source ``mcp_monitor_casual``."""
        from bridge.escalation import EscalationEngine, EscalationLevel

        mon, state_dir = self._monitor(tmp_path)
        now = _time.time()
        mon._server_states = {
            "memory": MCPServerInfo(name="memory", command="npx", status="stopped"),
        }
        mon._crash_history["memory"] = [now] * (CRASH_LOOP_THRESHOLD + 2)
        mon.record_health_state()

        engine = EscalationEngine(state_dir=state_dir)
        states = engine.scan_service_states()
        alerts = engine.evaluate_triggers(states)

        casual_alerts = [a for a in alerts if a.level == EscalationLevel.CASUAL]
        # Engine renders the source as "<service>_casual" for the 1-failure case.
        assert any(a.source == "mcp_monitor_casual" for a in casual_alerts)

    def test_engine_fires_nudge_at_three_failures(self, tmp_path):
        from bridge.escalation import EscalationEngine, EscalationLevel

        mon, state_dir = self._monitor(tmp_path)
        now = _time.time()
        mon._server_states = {
            "memory": MCPServerInfo(name="memory", command="npx", status="stopped"),
        }
        mon._crash_history["memory"] = [now] * (CRASH_LOOP_THRESHOLD + 2)
        for _ in range(3):
            mon.record_health_state()

        engine = EscalationEngine(state_dir=state_dir)
        states = engine.scan_service_states()
        alerts = engine.evaluate_triggers(states)

        nudge_alerts = [a for a in alerts if a.level == EscalationLevel.NUDGE]
        assert any(a.source == "mcp_monitor" for a in nudge_alerts)

    def test_engine_fires_urgent_at_five_failures(self, tmp_path):
        from bridge.escalation import EscalationEngine, EscalationLevel

        mon, state_dir = self._monitor(tmp_path)
        now = _time.time()
        mon._server_states = {
            "memory": MCPServerInfo(name="memory", command="npx", status="stopped"),
        }
        mon._crash_history["memory"] = [now] * (CRASH_LOOP_THRESHOLD + 2)
        for _ in range(5):
            mon.record_health_state()

        engine = EscalationEngine(state_dir=state_dir)
        states = engine.scan_service_states()
        alerts = engine.evaluate_triggers(states)

        urgent_alerts = [a for a in alerts if a.level == EscalationLevel.URGENT]
        assert any(a.source == "mcp_monitor" for a in urgent_alerts)
