"""Sprint P1.4 — narrow warm MCP config: file shape + wire-up tests.

Covers what `test_claude_runner.py::TestWarmClaudeProcessMcpConfig` does not:

- The committed `agent/config/warm-core-mcp.json` is parseable, has an
  `mcpServers` map, and is strictly narrower than the canonical/template
  20-server `.mcp.json` set. This is the "narrow MCP set defined" task.
- The shipped `agent/config/bridge.toml` enables `warm_mcp_config` by
  default (P1.4 acceptance: warm path no longer inherits full `.mcp.json`).
- `BridgeConfig.warm_mcp_config` round-trips correctly from the shipped
  `bridge.toml` so the value reaches `WarmClaudeProcess.spawn`.
- `WarmClaudeProcess.spawn` emits `--mcp-config <path> --strict-mcp-config`
  when the config resolves, and fails closed (returns False, no subprocess)
  when the configured path is missing.

The fail-closed assertion satisfies the P1.4 acceptance bullet "Missing
config fails closed or falls back only in dev mode" — we picked
fail-closed; the dev-mode override is to set `warm_mcp_config = ""`.
"""

from __future__ import annotations

import dataclasses
import json
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.claude_runner import WarmClaudeProcess


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = REPO_ROOT / "agent"
WARM_CORE_MCP = AGENT_ROOT / "config" / "warm-core-mcp.json"
BRIDGE_TOML = AGENT_ROOT / "config" / "bridge.toml"
FULL_MCP_TEMPLATE = AGENT_ROOT / "config" / "mcp-servers.template.json"
CANONICAL_MCP = AGENT_ROOT / "config" / "mcp-servers.canonical.json"


# ---------------------------------------------------------------------------
# warm-core-mcp.json — file shape + narrow-set discipline
# ---------------------------------------------------------------------------


class TestWarmCoreMcpConfigFile:
    def test_file_exists_at_canonical_path(self) -> None:
        assert WARM_CORE_MCP.is_file(), (
            f"P1.4: {WARM_CORE_MCP} must exist — it is the narrow MCP "
            "config the warm path loads via --mcp-config."
        )

    def test_parses_as_valid_json(self) -> None:
        json.loads(WARM_CORE_MCP.read_text())  # raises on invalid JSON

    def test_has_mcp_servers_map(self) -> None:
        data = json.loads(WARM_CORE_MCP.read_text())
        assert "mcpServers" in data, "missing required 'mcpServers' key"
        assert isinstance(data["mcpServers"], dict)
        assert len(data["mcpServers"]) >= 1, (
            "P1.4: warm-core-mcp.json must declare at least one MCP server "
            "(the empty set would defeat warm conversational chat)."
        )

    def test_narrow_set_strictly_smaller_than_full_template(self) -> None:
        """The whole point of the warm config is to be smaller than the
        full `.mcp.json` set. If they ever match in size, the narrowing
        win disappears."""
        if not FULL_MCP_TEMPLATE.is_file():
            pytest.skip(
                f"{FULL_MCP_TEMPLATE} not present — cannot compare set sizes"
            )
        narrow = json.loads(WARM_CORE_MCP.read_text())["mcpServers"]
        full = json.loads(FULL_MCP_TEMPLATE.read_text())["mcpServers"]
        assert len(narrow) < len(full), (
            f"P1.4: warm set ({len(narrow)} servers) must be strictly "
            f"smaller than full template ({len(full)} servers)."
        )

    def test_each_server_has_command(self) -> None:
        """Every declared server entry needs at minimum a `command`
        (or `url` for HTTP servers) so Claude Code can spawn it."""
        data = json.loads(WARM_CORE_MCP.read_text())
        for name, entry in data["mcpServers"].items():
            assert isinstance(entry, dict), f"server {name!r} entry not a dict"
            assert "command" in entry or "url" in entry, (
                f"server {name!r} missing both 'command' and 'url'"
            )

    def test_warm_bumba_memory_path_matches_canonical_runtime_path(self) -> None:
        """S1.2: warm-path bumba-memory must invoke the same runtime entry
        as the canonical MCP config. Drift between the two means the warm
        process talks to a different (possibly stale) memory server than
        the cold path."""
        warm = json.loads(WARM_CORE_MCP.read_text())["mcpServers"]["bumba-memory"]
        canonical = json.loads(CANONICAL_MCP.read_text())["mcpServers"][
            "bumba-memory"
        ]

        assert warm["command"] == canonical["command"] == "node"
        assert warm["args"] == canonical["args"], (
            f"S1.2: warm bumba-memory args {warm['args']!r} must match "
            f"canonical {canonical['args']!r}"
        )


# ---------------------------------------------------------------------------
# bridge.toml — warm_mcp_config enabled by default
# ---------------------------------------------------------------------------


class TestBridgeTomlWiresWarmMcpConfig:
    def test_bridge_toml_has_warm_mcp_config_set(self) -> None:
        """P1.4 acceptance: warm_mcp_config is no longer commented out —
        the shipped default narrows the warm MCP surface."""
        data = tomllib.loads(BRIDGE_TOML.read_text())
        claude_section = data.get("claude", {})
        assert "warm_mcp_config" in claude_section, (
            "P1.4: [claude].warm_mcp_config must be set in bridge.toml "
            "(it ships uncommented as of P1.4)."
        )
        value = claude_section["warm_mcp_config"]
        assert value, (
            "P1.4: warm_mcp_config must be a non-empty path; empty string "
            "is the dev-override that disables narrowing."
        )

    def test_bridge_toml_points_at_canonical_warm_config(self) -> None:
        data = tomllib.loads(BRIDGE_TOML.read_text())
        value = data["claude"]["warm_mcp_config"]
        # The shipped value is a path relative to agent root.
        assert value.endswith("warm-core-mcp.json"), (
            f"P1.4: warm_mcp_config should reference warm-core-mcp.json, "
            f"got {value!r}"
        )

    def test_warm_mcp_config_path_resolves_to_existing_file(self) -> None:
        """If the bridge.toml path is relative, it resolves against
        agent root (data_dir.parent / 'agent' in production). At repo
        check-time we resolve against AGENT_ROOT."""
        data = tomllib.loads(BRIDGE_TOML.read_text())
        value = data["claude"]["warm_mcp_config"]
        path = Path(value)
        if not path.is_absolute():
            path = AGENT_ROOT / value
        assert path.is_file(), (
            f"P1.4: warm_mcp_config path {value!r} (resolved {path}) "
            "must point at an existing file or the warm process will "
            "fail closed on spawn."
        )


# ---------------------------------------------------------------------------
# WarmClaudeProcess.spawn() — strict-mcp-config flag + fail-closed
# ---------------------------------------------------------------------------


async def _capture_spawn_cmd(config) -> tuple[list[str] | None, bool]:
    """Run WarmClaudeProcess.spawn() with create_subprocess_exec mocked.

    Returns (cmd, subprocess_called). ``cmd`` is None when spawn aborted
    before reaching subprocess (fail-closed path).
    """
    warm = WarmClaudeProcess(config)
    captured: dict[str, list[str]] = {}
    flag: dict[str, bool] = {"subprocess": False}

    async def fake_subprocess_exec(*cmd, **_kwargs):
        flag["subprocess"] = True
        captured["cmd"] = list(cmd)
        raise RuntimeError("captured-cmd-stop")

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=fake_subprocess_exec,
    ), patch(
        "bridge.claude_runner.shutil.which",
        return_value="/fake/claude",
    ):
        result = await warm.spawn(working_dir="/tmp/wd", model="haiku")

    # spawn() returns False in both cases we exercise here.
    assert result is False
    return (captured.get("cmd"), flag["subprocess"])


class TestSpawnEmitsStrictMcpConfig:
    @pytest.mark.asyncio
    async def test_spawn_emits_strict_mcp_config_flag_when_file_present(
        self, sample_config, tmp_path
    ):
        """P1.4 task: 'Test command construction includes
        --strict-mcp-config.'"""
        mcp_file = tmp_path / "warm-core-mcp.json"
        mcp_file.write_text('{"mcpServers": {"bumba-memory": {"command": "x"}}}')
        cfg = dataclasses.replace(sample_config, warm_mcp_config=str(mcp_file))

        cmd, subprocess_called = await _capture_spawn_cmd(cfg)

        assert subprocess_called, "subprocess must spawn when config valid"
        assert cmd is not None
        assert "--strict-mcp-config" in cmd
        assert "--mcp-config" in cmd
        idx = cmd.index("--mcp-config")
        assert cmd[idx + 1] == str(mcp_file)

    @pytest.mark.asyncio
    async def test_spawn_fails_closed_when_warm_mcp_config_file_missing(
        self, sample_config, tmp_path
    ):
        """P1.4 acceptance: 'Missing config fails closed or falls back
        only in dev mode.' We chose fail-closed: spawn returns False and
        the subprocess is never launched."""
        missing = tmp_path / "does-not-exist.json"
        cfg = dataclasses.replace(sample_config, warm_mcp_config=str(missing))

        cmd, subprocess_called = await _capture_spawn_cmd(cfg)

        assert subprocess_called is False, (
            "P1.4: subprocess must NOT spawn when warm_mcp_config path "
            "is missing — silent fallback to .mcp.json is forbidden."
        )
        assert cmd is None

    @pytest.mark.asyncio
    async def test_spawn_skips_mcp_flags_when_warm_mcp_config_empty(
        self, sample_config
    ):
        """Dev-override path: warm_mcp_config = "" disables narrowing
        and falls back to the working-dir .mcp.json (legacy behaviour)."""
        cfg = dataclasses.replace(sample_config, warm_mcp_config="")

        cmd, subprocess_called = await _capture_spawn_cmd(cfg)

        assert subprocess_called, (
            "empty warm_mcp_config must not block spawn — it is the "
            "documented dev-mode override."
        )
        assert cmd is not None
        assert "--mcp-config" not in cmd
        assert "--strict-mcp-config" not in cmd


# ---------------------------------------------------------------------------
# Relative-path resolution (#1980 — D6-bis layout fix)
# ---------------------------------------------------------------------------


class TestRelativePathResolvesAgainstCwd:
    """The bridge daemon's launchd plist sets WorkingDirectory to the agent
    root (post-D6-bis: ``/opt/bumba-harness/agent-flat/agent``). The pre-fix
    code resolved relative paths via ``data_dir.parent / "agent" / warm_mcp``,
    which assumed the D5 sibling layout (``~/data`` next to ``~/agent``)
    and silently broke when D6-bis moved the runtime into ``~/agent-flat/``.

    Fix (#1980): resolve relative paths against ``Path.cwd()``. The daemon's
    WorkingDirectory is the agent root in both pre- and post-D6-bis layouts,
    so cwd is the durable anchor.
    """

    @pytest.mark.asyncio
    async def test_relative_warm_mcp_resolves_against_cwd_not_data_dir_sibling(
        self, sample_config, tmp_path, monkeypatch
    ):
        """Set up a tmp agent root with the warm config under
        ``./config/warm-core-mcp.json``, point cwd at it, and assert spawn
        finds the file via cwd resolution. The data_dir is deliberately
        somewhere unrelated so the pre-fix ``data_dir.parent / "agent"``
        path would NOT find the file."""
        agent_root = tmp_path / "agent-flat-fake" / "agent"
        agent_root.mkdir(parents=True)
        config_dir = agent_root / "config"
        config_dir.mkdir()
        mcp_file = config_dir / "warm-core-mcp.json"
        mcp_file.write_text('{"mcpServers": {"bumba-memory": {"command": "x"}}}')

        # data_dir lives somewhere that has no "agent" sibling — proves the
        # fix is no longer using the data_dir-parent fallback.
        unrelated_data_dir = tmp_path / "unrelated-data-tree" / "data"
        unrelated_data_dir.mkdir(parents=True)

        cfg = dataclasses.replace(
            sample_config,
            data_dir=str(unrelated_data_dir),
            warm_mcp_config="config/warm-core-mcp.json",  # RELATIVE
        )

        # cwd is the agent root, matching the runtime's launchd
        # WorkingDirectory contract.
        monkeypatch.chdir(agent_root)

        cmd, subprocess_called = await _capture_spawn_cmd(cfg)

        assert subprocess_called, (
            "spawn must succeed when cwd-resolved relative warm_mcp_config "
            "points at a real file (#1980)"
        )
        assert cmd is not None
        idx = cmd.index("--mcp-config")
        resolved = Path(cmd[idx + 1])
        assert resolved == mcp_file, (
            f"--mcp-config must resolve via cwd; expected {mcp_file}, "
            f"got {resolved}"
        )

    @pytest.mark.asyncio
    async def test_absolute_warm_mcp_passes_through_unchanged(
        self, sample_config, tmp_path
    ):
        """Absolute paths must NOT be re-resolved (the cwd join only fires
        for relative paths). Pinned so a future refactor cannot
        accidentally double-prepend cwd to an operator-declared absolute
        path."""
        mcp_file = tmp_path / "abs" / "warm-core-mcp.json"
        mcp_file.parent.mkdir()
        mcp_file.write_text('{"mcpServers": {"bumba-memory": {"command": "x"}}}')
        assert mcp_file.is_absolute()

        cfg = dataclasses.replace(
            sample_config, warm_mcp_config=str(mcp_file)
        )

        cmd, subprocess_called = await _capture_spawn_cmd(cfg)

        assert subprocess_called
        assert cmd is not None
        idx = cmd.index("--mcp-config")
        assert cmd[idx + 1] == str(mcp_file), (
            "absolute warm_mcp_config must pass through verbatim — "
            "no cwd join (#1980)"
        )
