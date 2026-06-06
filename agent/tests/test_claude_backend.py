"""Direct tests for ``bridge.backends.claude.ClaudeBackend``.

Codex-1 (#1835): exercises the Claude-specific backend implementation in
isolation from ``ClaudeRunner``. Coverage mirrors the relevant slices of
``test_claude_runner.py`` (binary resolution order, command-flag emission,
JSON-event parsing including malformed-JSON repair paths) — but at the
backend layer, not via ``ClaudeRunner.*``. ``test_claude_runner.py`` itself
is the regression guard and remains unmodified.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.backends import ClaudeBackend
from bridge.backends.claude import _parse_stream_line, _try_repair_json


# -- Binary resolution ----------------------------------------------------


class TestResolveBinary:
    """ClaudeBackend.resolve_binary — env override → config → which → fallbacks."""

    @pytest.fixture(autouse=True)
    def _clear_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BUMBA_CLAUDE_BINARY is checked first; clear it for the
        config/which/fallback branches."""
        monkeypatch.delenv("BUMBA_CLAUDE_BINARY", raising=False)

    def test_config_binary_used_when_set(self, sample_config) -> None:
        config = dataclasses.replace(sample_config, claude_binary="/custom/claude")
        backend = ClaudeBackend(config)
        assert backend.resolve_binary() == "/custom/claude"

    def test_which_used_when_no_config_binary(self, sample_config) -> None:
        config = dataclasses.replace(sample_config, claude_binary="")
        backend = ClaudeBackend(config)
        with patch("bridge.backends.claude.shutil.which", return_value="/usr/bin/claude"):
            assert backend.resolve_binary() == "/usr/bin/claude"

    def test_fallback_home_bin(self, sample_config, tmp_path) -> None:
        config = dataclasses.replace(sample_config, claude_binary="")
        fake_binary = tmp_path / ".local" / "bin" / "claude"
        fake_binary.parent.mkdir(parents=True)
        fake_binary.touch()
        backend = ClaudeBackend(config)
        with (
            patch("bridge.backends.claude.shutil.which", return_value=None),
            patch("bridge.backends.claude.Path.home", return_value=tmp_path),
        ):
            binary = backend.resolve_binary()
        assert binary == str(fake_binary)

    def test_raises_when_not_found(self, sample_config) -> None:
        config = dataclasses.replace(sample_config, claude_binary="")
        backend = ClaudeBackend(config)
        with (
            patch("bridge.backends.claude.shutil.which", return_value=None),
            patch.object(Path, "is_file", return_value=False),
        ):
            with pytest.raises(FileNotFoundError, match="Claude Code binary not found"):
                backend.resolve_binary()

    def test_env_override_single_token(
        self, sample_config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUMBA_CLAUDE_BINARY beats config.claude_binary (Sprint 08.07, #785)."""
        config = dataclasses.replace(sample_config, claude_binary="/usr/local/bin/claude")
        backend = ClaudeBackend(config)
        monkeypatch.setenv("BUMBA_CLAUDE_BINARY", "/tmp/shim-claude")
        assert backend.resolve_binary() == "/tmp/shim-claude"

    def test_env_override_multi_token(
        self, sample_config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multi-token override splits into argv list for shim invocations."""
        config = dataclasses.replace(sample_config, claude_binary="/usr/local/bin/claude")
        backend = ClaudeBackend(config)
        monkeypatch.setenv("BUMBA_CLAUDE_BINARY", "/usr/bin/python3 /opt/fake_claude.py")
        result = backend.resolve_binary()
        assert result == ["/usr/bin/python3", "/opt/fake_claude.py"]

    def test_env_unset_falls_back_to_config(
        self, sample_config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = dataclasses.replace(sample_config, claude_binary="/usr/local/bin/claude")
        backend = ClaudeBackend(config)
        monkeypatch.delenv("BUMBA_CLAUDE_BINARY", raising=False)
        assert backend.resolve_binary() == "/usr/local/bin/claude"


# -- Command building -----------------------------------------------------


class TestBuildCommand:
    """ClaudeBackend.build_command — flag emission and argv shape."""

    def _backend(self, sample_config) -> ClaudeBackend:
        return ClaudeBackend(sample_config)

    def test_basic_command_flags(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="Hello", binary="/usr/local/bin/claude")
        assert cmd[0] == "/usr/local/bin/claude"
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--max-turns" in cmd
        assert str(sample_config.claude_max_turns) in cmd
        assert "--verbose" in cmd
        assert "--dangerously-skip-permissions" in cmd
        # message goes via stdin, never argv
        assert "Hello" not in cmd

    def test_with_resume(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", session_id="sess-123", binary="/usr/local/bin/claude"
        )
        assert "--resume" in cmd
        idx = cmd.index("--resume")
        assert cmd[idx + 1] == "sess-123"

    def test_without_resume(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="Hi", binary="/usr/local/bin/claude")
        assert "--resume" not in cmd

    def test_empty_session_id_no_resume(self, sample_config) -> None:
        """Regression: empty/None session_id MUST NOT trigger --resume."""
        backend = self._backend(sample_config)
        for sid in (None, ""):
            cmd = backend.build_command(
                message="Hi", session_id=sid, binary="/usr/local/bin/claude"
            )
            assert "--resume" not in cmd, f"session_id={sid!r} produced --resume"

    def test_disallowed_tools_emitted(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="Hi", binary="/usr/local/bin/claude")
        for tool in sample_config.security_disallowed_tools:
            assert "--disallowedTools" in cmd
            assert tool in cmd

    def test_system_prompt_file(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", system_prompt_file="/tmp/ctx.md", binary="/usr/local/bin/claude"
        )
        assert "--append-system-prompt-file" in cmd
        assert "/tmp/ctx.md" in cmd

    def test_allowed_tools_emitted(self, sample_config) -> None:
        """#2345 — each allowed tool gets its own --allowedTools flag pair."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi",
            allowed_tools=[
                "mcp__bumba-sandbox__sandbox_init",
                "mcp__bumba-sandbox__execute_command",
            ],
            binary="/usr/local/bin/claude",
        )
        assert cmd.count("--allowedTools") == 2
        assert "mcp__bumba-sandbox__sandbox_init" in cmd
        assert "mcp__bumba-sandbox__execute_command" in cmd

    def test_allowed_tools_absent_by_default(self, sample_config) -> None:
        """No allowed_tools → no --allowedTools flag (byte-identical legacy)."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="Hi", binary="/usr/local/bin/claude")
        assert "--allowedTools" not in cmd

    def test_model_flag(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", model="haiku", binary="/usr/local/bin/claude"
        )
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "haiku"

    def test_model_flag_absent_without_model(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="Hi", binary="/usr/local/bin/claude")
        assert "--model" not in cmd

    def test_mcp_config_path(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", mcp_config_path="/tmp/mcp.json", binary="/usr/local/bin/claude"
        )
        assert "--mcp-config" in cmd
        idx = cmd.index("--mcp-config")
        assert cmd[idx + 1] == "/tmp/mcp.json"

    def test_mcp_config_path_pairs_strict_flag(self, sample_config) -> None:
        """#2345: a filtered --mcp-config MUST be paired with
        --strict-mcp-config so Claude ignores the project .mcp.json at cwd.

        The runtime tree's .mcp.json is in the kernel-integrity baseline;
        without strict mode Claude merges/normalises it mid-run, mutating a
        hashed file and tripping the SessionStart-hook integrity check →
        halt.flag → the E2B/subagent subprocess is killed before it finishes.
        Strict mode keeps the baselined .mcp.json untouched.
        """
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", mcp_config_path="/tmp/mcp.json", binary="/usr/local/bin/claude"
        )
        assert "--strict-mcp-config" in cmd

    def test_no_mcp_config_omits_strict_flag(self, sample_config) -> None:
        """No filtered config → neither --mcp-config nor --strict-mcp-config.

        Plain one-shot conversational invocations must still see the project
        .mcp.json (full tool surface); strict mode is only for the filtered,
        write-jailed isolation path (E2B / subagent).
        """
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="Hi", binary="/usr/local/bin/claude")
        assert "--mcp-config" not in cmd
        assert "--strict-mcp-config" not in cmd

    def test_permission_mode_native_flag(self, sample_config) -> None:
        """Non-bypass permission_mode emits --permission-mode, not the
        --dangerously-skip-permissions shortcut."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", permission_mode="acceptEdits", binary="/usr/local/bin/claude"
        )
        assert "--permission-mode" in cmd
        idx = cmd.index("--permission-mode")
        assert cmd[idx + 1] == "acceptEdits"
        assert "--dangerously-skip-permissions" not in cmd

    def test_permission_mode_bypass_uses_shortcut(self, sample_config) -> None:
        """Default bypassPermissions preserves --dangerously-skip-permissions
        for cross-caller back-compat (#630)."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", permission_mode="bypassPermissions", binary="/usr/local/bin/claude"
        )
        assert "--dangerously-skip-permissions" in cmd
        assert "--permission-mode" not in cmd

    def test_binary_as_list_flattened(self, sample_config) -> None:
        """When resolve_binary returns a multi-token list (shim invocation),
        cmd stays a flat argv list."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", binary=["/usr/bin/python3", "/opt/fake_claude.py"]
        )
        assert cmd[0] == "/usr/bin/python3"
        assert cmd[1] == "/opt/fake_claude.py"
        assert cmd[2] == "-p"

    def test_binary_resolved_internally_when_none(self, sample_config) -> None:
        """Without explicit binary, build_command calls resolve_binary itself."""
        config = dataclasses.replace(sample_config, claude_binary="/auto/claude")
        backend = ClaudeBackend(config)
        cmd = backend.build_command(message="Hi")
        assert cmd[0] == "/auto/claude"


# -- Stream parsing -------------------------------------------------------


class TestParseEvent:
    """ClaudeBackend.parse_event + module-level _parse_stream_line parity."""

    def test_parse_init(self) -> None:
        line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc-123"})
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "system"
        assert ev.subtype == "init"
        assert ev.session_id == "abc-123"

    def test_parse_assistant_text(self) -> None:
        line = json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Hello!"}]},
            }
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "assistant"
        assert ev.text == "Hello!"

    def test_parse_assistant_with_tool_use_blocks(self) -> None:
        """P1.5: assistant.message.content[] may carry tool_use blocks
        whose names must be surfaced in ev.tool_names."""
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Working..."},
                        {"type": "tool_use", "name": "Bash"},
                        {"type": "tool_use", "name": "Read"},
                    ]
                },
            }
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.text == "Working..."
        assert ev.tool_names == ["Bash", "Read"]

    def test_parse_tool_use_event(self) -> None:
        line = json.dumps({"type": "tool_use", "tool_name": "Bash"})
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "tool_use"
        assert ev.tool_name == "Bash"

    def test_parse_result_event(self) -> None:
        line = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "sess-1",
                "cost_usd": 0.0123,
                "num_turns": 2,
                "duration_ms": 1500,
                "is_error": False,
                "result": "Done.",
            }
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "result"
        assert ev.is_error is False
        assert ev.cost_usd == 0.0123
        assert ev.num_turns == 2
        assert ev.duration_ms == 1500
        assert ev.text == "Done."

    def test_parse_empty_line_returns_none(self) -> None:
        assert _parse_stream_line("") is None
        assert _parse_stream_line("   \n") is None

    def test_parse_invalid_json_unrepairable_returns_none(self) -> None:
        assert _parse_stream_line("not json at all $$$$") is None

    def test_backend_parse_event_delegates(self, sample_config) -> None:
        backend = ClaudeBackend(sample_config)
        line = json.dumps({"type": "system", "subtype": "init", "session_id": "x"})
        ev_backend = backend.parse_event(line)
        ev_module = _parse_stream_line(line)
        assert ev_backend is not None and ev_module is not None
        assert ev_backend.session_id == ev_module.session_id == "x"


class TestRepairJson:
    """_try_repair_json strategies — extract-from-garbage, trailing-comma, truncation."""

    def test_extract_from_surrounding_garbage(self) -> None:
        line = 'log noise {"type": "system", "subtype": "init"} more noise'
        result = _try_repair_json(line)
        assert result is not None
        assert result["type"] == "system"

    def test_strip_trailing_commas(self) -> None:
        line = '{"type": "system", "subtype": "init",}'
        result = _try_repair_json(line)
        assert result is not None
        assert result["type"] == "system"

    def test_unrepairable_returns_none(self) -> None:
        assert _try_repair_json("not json at all $$$$") is None

    def test_repair_path_used_when_initial_parse_fails(self) -> None:
        """Malformed-but-repairable JSON should round-trip through the
        parser via the repair fallback."""
        line = '{"type": "system", "subtype": "init",}'  # trailing comma
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "system"
        assert ev.subtype == "init"


# -- Auth env + shutdown --------------------------------------------------


class TestAuthEnvAndShutdown:
    """ClaudeBackend wraps trivial implementations for the auth_env and
    shutdown protocol slots — but those slots are part of the contract."""

    def test_auth_env_returns_empty(self, sample_config) -> None:
        backend = ClaudeBackend(sample_config)
        assert backend.auth_env() == {}

    def test_shutdown_is_idempotent_noop(self, sample_config) -> None:
        backend = ClaudeBackend(sample_config)
        assert backend.shutdown() is None
        assert backend.shutdown() is None


# -- StreamEvent shared shape --------------------------------------------


class TestStreamEventReexport:
    """Sanity: ``StreamEvent`` is importable from both the package root and
    ``bridge.claude_runner`` (back-compat re-export) and is the same class."""

    def test_stream_event_import_paths_identical(self) -> None:
        from bridge.backends import StreamEvent as A
        from bridge.backends._protocol import StreamEvent as B
        from bridge.claude_runner import StreamEvent as C
        assert A is B is C


# -- audit-2026-05-16.D.02 (HI-2, #2063) — typed cost-measurement parser ---


class TestParseCostClaude:
    """``ClaudeBackend.parse_cost`` — typed four-state cost contract.

    HI-2 (#2063): Claude's measured-cost path is the well-behaved baseline
    (the legacy ``cost_usd = data.get("cost_usd", 0.0)`` collapse mostly
    bit Codex). The regression check below ensures wrapping the value in
    ``CostMeasurement`` preserves the underlying numeric measurement for
    Claude's existing result-event shape.
    """

    def test_claude_parser_unchanged_measured_path(self, sample_config) -> None:
        """Regression: Claude's measured-cost path still returns the same
        numeric value (now wrapped in ``CostMeasurement``).

        The pre-HI-2 site read ``data.get("cost_usd", 0.0)`` and produced
        a float. The new ``parse_cost`` surface wraps that same value in
        ``CostMeasurement(source='measured')`` — round-tripping via
        ``to_legacy_float()`` must produce the original number.
        """
        from decimal import Decimal

        from bridge.backends.claude import ClaudeBackend
        from bridge.cost_tracker import CostMeasurement, to_legacy_float

        backend = ClaudeBackend(sample_config)
        event = {
            "type": "result",
            "subtype": "success",
            "session_id": "sess-1",
            "cost_usd": 0.0123,
            "num_turns": 2,
            "duration_ms": 1500,
            "is_error": False,
            "result": "Done.",
        }
        m = backend.parse_cost(event)
        assert isinstance(m, CostMeasurement)
        assert m.source == "measured"
        assert m.amount_usd == Decimal("0.0123")
        assert m.backend == "claude"
        assert m.raw_usage_id == "sess-1"
        # Legacy round-trip preserves the original numeric value within
        # binary-float precision.
        assert to_legacy_float(m) == pytest.approx(0.0123)

    def test_claude_parser_returns_unknown_when_cost_field_missing(
        self, sample_config
    ) -> None:
        """A Claude ``result`` event without ``cost_usd`` returns
        ``source='unknown'`` — NOT a measured zero.

        Less common on Claude than Codex (Claude reliably emits
        ``cost_usd``), but the contract must still hold so a corrupt
        or partial result event never silently aggregates to zero.
        """
        from bridge.backends.claude import ClaudeBackend
        from bridge.cost_tracker import CostMeasurement

        backend = ClaudeBackend(sample_config)
        event = {
            "type": "result",
            "subtype": "success",
            "session_id": "sess-2",
            "num_turns": 1,
            "is_error": False,
        }
        m = backend.parse_cost(event)
        assert isinstance(m, CostMeasurement)
        assert m.source == "unknown"
        assert m.amount_usd is None
        assert m.backend == "claude"

    def test_claude_parser_rejects_codex_event_as_not_applicable(
        self, sample_config
    ) -> None:
        """A Codex ``turn.completed`` event sent to Claude's parser
        returns ``source='not_applicable'`` — Claude's only cost-bearing
        event is ``result``; foreign-backend shapes must not be coerced.
        """
        from bridge.backends.claude import ClaudeBackend
        from bridge.cost_tracker import CostMeasurement

        backend = ClaudeBackend(sample_config)
        codex_event = {
            "type": "turn.completed",
            "thread_id": "thread-xyz",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        m = backend.parse_cost(codex_event)
        assert isinstance(m, CostMeasurement)
        assert m.source == "not_applicable", (
            "Claude parse_cost mis-handled a foreign Codex turn.completed "
            "event. Per HI-2 (#2063) foreign events must surface as "
            "'not_applicable' so the active backend's parser is the "
            "single source of truth for its own events."
        )
        assert m.amount_usd is None
        assert m.backend == "claude"

    def test_claude_parser_returns_not_applicable_for_non_result_events(
        self, sample_config
    ) -> None:
        """Claude's non-result events (``system``, ``assistant``,
        ``tool_use``, ``tool_result``) are not cost-bearing, so
        ``parse_cost`` returns ``source='not_applicable'``.
        """
        from bridge.backends.claude import ClaudeBackend
        from bridge.cost_tracker import CostMeasurement

        backend = ClaudeBackend(sample_config)
        for event in (
            {"type": "system", "subtype": "init", "session_id": "s"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
            {"type": "tool_use", "tool_name": "Bash"},
            {"type": "tool_result"},
        ):
            m = backend.parse_cost(event)
            assert isinstance(m, CostMeasurement)
            assert m.source == "not_applicable", (
                f"Claude non-cost event {event['type']!r} should be "
                f"not_applicable; got source={m.source!r}"
            )
            assert m.amount_usd is None
            assert m.backend == "claude"
