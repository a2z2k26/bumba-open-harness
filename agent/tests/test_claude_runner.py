"""Tests for bridge.claude_runner (S51) - expanded coverage.

Coverage:
- _load_secrets_as_env: ANTHROPIC_API_KEY exclusion (auth regression)
- _scan_for_canary: detection, redaction
- _try_repair_json: all repair strategies
- _parse_stream_line: extended event types and edge cases
- _process_events: aggregation, deduplication, error subtypes
- _classify_error: all branches including timeout signals
- ClaudeRunner._resolve_binary: found/not-found paths
- ClaudeRunner._build_command: model flag, verbose flag
- ClaudeRunner.kill_current: no-process guard
- ClaudeRunner.cleanup_stale: missing/invalid pid file
- ClaudeRunner.set_token_provider: wiring
- WarmClaudeProcess: is_alive, session_id, close, cycle
- Regression: bridge UUID must NOT be passed to --resume
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.claude_runner import (
    ClaudeRunner,
    StreamEvent,
    WarmClaudeProcess,
    _classify_error,
    _load_secrets_as_env,
    _parse_stream_line,
    _process_events,
    _scan_for_canary,
    _try_repair_json,
)


class TestCommandBuilder:
    """S46: Command building."""

    def test_basic_command(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hello")
        assert cmd[0] == "/usr/local/bin/claude"
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--max-turns" in cmd
        assert "25" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert "Hello" not in cmd

    def test_with_resume(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hi", session_id="sess-123")
        assert "--resume" in cmd
        idx = cmd.index("--resume")
        assert cmd[idx + 1] == "sess-123"

    def test_without_resume(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hi")
        assert "--resume" not in cmd

    def test_disallowed_tools(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hi")
        assert "--disallowedTools" in cmd
        assert "Bash(sudo *)" in cmd

    def test_system_prompt_file(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hi", system_prompt_file="/tmp/ctx.md")
        assert "--append-system-prompt-file" in cmd
        assert "/tmp/ctx.md" in cmd


class TestStreamParser:
    """S47: Stream-JSON parsing."""

    def test_parse_init(self):
        line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc-123"})
        ev = _parse_stream_line(line)
        assert ev.type == "system"
        assert ev.subtype == "init"
        assert ev.session_id == "abc-123"

    def test_parse_assistant(self):
        line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello!"}]},
        })
        ev = _parse_stream_line(line)
        assert ev.type == "assistant"
        assert ev.text == "Hello!"

    def test_parse_tool_use(self):
        line = json.dumps({"type": "tool_use", "tool_name": "Bash"})
        ev = _parse_stream_line(line)
        assert ev.type == "tool_use"
        assert ev.tool_name == "Bash"

    def test_parse_assistant_nested_tool_use(self):
        """P1.5: assistant.message.content[] may carry tool_use blocks.

        Anthropic's stream-json emits tool calls inside the assistant message's
        content array; the parser must surface them so the conversations audit
        records nested tool calls (not just top-level tool_use events).
        """
        line = json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Read", "id": "toolu_1", "input": {}},
                ],
            },
        })
        ev = _parse_stream_line(line)
        assert ev.type == "assistant"
        assert ev.tool_names == ["Read"]

    def test_parse_assistant_text_and_tool_use_mixed(self):
        """P1.5: text extraction must be preserved when tool_use blocks coexist."""
        line = json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Let me look at the file."},
                    {"type": "tool_use", "name": "Read", "id": "toolu_1", "input": {}},
                    {"type": "tool_use", "name": "Bash", "id": "toolu_2", "input": {}},
                ],
            },
        })
        ev = _parse_stream_line(line)
        assert ev.type == "assistant"
        assert ev.text == "Let me look at the file."
        assert ev.tool_names == ["Read", "Bash"]

    def test_process_events_aggregates_nested_tool_use(self):
        """P1.5: _process_events must include tool names from assistant content blocks."""
        lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Working..."},
                        {"type": "tool_use", "name": "Read", "id": "toolu_1", "input": {}},
                    ],
                },
            }),
            json.dumps({
                "type": "result", "session_id": "s1",
                "cost_usd": 0.01, "num_turns": 1, "is_error": False,
                "result": "Done.",
            }),
        ]
        events = [_parse_stream_line(line) for line in lines]
        events = [e for e in events if e is not None]
        result = _process_events(events)
        assert "Read" in result.tools_used

    def test_parse_result(self):
        line = json.dumps({
            "type": "result", "session_id": "x",
            "cost_usd": 0.05, "num_turns": 3, "is_error": False,
            "result": "Done.",
        })
        ev = _parse_stream_line(line)
        assert ev.type == "result"
        assert ev.cost_usd == 0.05
        assert ev.text == "Done."

    def test_parse_invalid_json(self):
        ev = _parse_stream_line("not json at all")
        assert ev is None

    def test_parse_empty_line(self):
        ev = _parse_stream_line("")
        assert ev is None

    def test_process_events(self, sample_stream_events):
        events = [_parse_stream_line(line) for line in sample_stream_events]
        events = [e for e in events if e is not None]
        result = _process_events(events)
        assert result.session_id == "sess-abc-123"
        assert result.cost_usd == 0.05
        assert result.num_turns == 3
        assert "Read" in result.tools_used
        assert result.response_text == "Final result text."


class TestErrorClassification:
    """S50: Error classification."""

    def test_classify_rate_limit(self):
        assert _classify_error(1, "You've hit your rate limit") == "rate_limit"

    def test_classify_auth(self):
        assert _classify_error(1, "Authentication failed") == "auth"

    def test_classify_content_filter(self):
        assert _classify_error(1, "Content filter triggered") == "content_filter"

    def test_classify_binary_not_found(self):
        assert _classify_error(127, "") == "binary_not_found"

    def test_classify_oom(self):
        assert _classify_error(137, "") == "oom"

    def test_classify_segfault(self):
        assert _classify_error(139, "") == "segfault"

    def test_classify_success(self):
        assert _classify_error(0, "") == "unknown"


class TestLoadSecretsAsEnv:
    """Regression: ANTHROPIC_API_KEY exclusion."""

    def test_loads_normal_keys(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("MY_VAR=hello\nOTHER=world\n")
        secrets.chmod(0o600)  # R6: _load_secrets_as_env now refuses non-0o600 files
        env = _load_secrets_as_env(str(tmp_path))
        assert env["MY_VAR"] == "hello"
        assert env["OTHER"] == "world"

    def test_excludes_anthropic_api_key(self, tmp_path):
        """CRITICAL regression: ANTHROPIC_API_KEY must never be injected.

        If present in subprocess env, Claude Code uses it instead of
        CLAUDE_CODE_OAUTH_TOKEN, causing Invalid API key errors.
        """
        secrets = tmp_path / ".secrets"
        secrets.write_text("ANTHROPIC_API_KEY=sk-test-123\nNOTION_TOKEN=abc\n")
        secrets.chmod(0o600)
        env = _load_secrets_as_env(str(tmp_path))
        assert "ANTHROPIC_API_KEY" not in env
        assert env["NOTION_TOKEN"] == "abc"

    def test_skips_comments_and_empty_lines(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("# comment\n\nVAR=val\n")
        secrets.chmod(0o600)
        env = _load_secrets_as_env(str(tmp_path))
        assert env == {"VAR": "val"}

    def test_skips_lines_without_equals(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("NOEQUALS\nGOOD=value\n")
        secrets.chmod(0o600)
        env = _load_secrets_as_env(str(tmp_path))
        assert env == {"GOOD": "value"}

    def test_value_with_embedded_equals(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("TOKEN=abc=def==\n")
        secrets.chmod(0o600)
        env = _load_secrets_as_env(str(tmp_path))
        assert env["TOKEN"] == "abc=def=="

    def test_missing_secrets_file_returns_empty(self, tmp_path):
        env = _load_secrets_as_env(str(tmp_path))
        assert env == {}

    def test_unreadable_secrets_file_returns_empty(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("VAR=val")
        secrets.chmod(0o000)
        try:
            env = _load_secrets_as_env(str(tmp_path))
            assert env == {}
        finally:
            secrets.chmod(0o644)


class TestScanForCanary:
    def test_no_canary_returns_original(self):
        text = "Hello, this is a safe response."
        cleaned, leaked = _scan_for_canary(text)
        assert cleaned == text
        assert leaked == []

    def test_single_canary_redacted(self):
        text = "Here is CANARY:abc123def456 in the response."
        cleaned, leaked = _scan_for_canary(text)
        assert "CANARY:abc123def456" not in cleaned
        assert "[REDACTED]" in cleaned
        assert "CANARY:abc123def456" in leaked

    def test_multiple_canaries_all_redacted(self):
        text = "First: CANARY:aabbccddeeff and second: CANARY:112233445566."
        cleaned, leaked = _scan_for_canary(text)
        assert len(leaked) == 2
        assert cleaned.count("[REDACTED]") == 2

    def test_partial_canary_not_matched(self):
        text = "CANARY:abc is too short"
        cleaned, leaked = _scan_for_canary(text)
        assert leaked == []

    def test_uppercase_hex_not_matched(self):
        text = "CANARY:AABBCCDDEEFF is uppercase"
        cleaned, leaked = _scan_for_canary(text)
        assert leaked == []


class TestTryRepairJson:
    def test_strategy1_extract_from_garbage(self):
        inner = json.dumps({"type": "assistant", "text": "hi"})
        line = "some garbage " + inner + " more garbage"
        result = _try_repair_json(line)
        assert result is not None
        assert result["type"] == "assistant"

    def test_strategy2_trailing_comma_removal(self):
        line = '{"type": "result", "cost": 0.01,}'
        result = _try_repair_json(line)
        assert result is not None
        assert result["cost"] == 0.01

    def test_completely_invalid_returns_none(self):
        result = _try_repair_json("not json at all $$$$")
        assert result is None


class TestParseStreamLineExtended:
    def test_parse_tool_use_name_fallback(self):
        line = json.dumps({"type": "tool_use", "name": "Write"})
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.tool_name == "Write"

    def test_parse_result_error_max_turns(self):
        line = json.dumps({
            "type": "result", "is_error": True, "subtype": "error_max_turns",
            "session_id": "s", "cost_usd": 0.01, "num_turns": 10, "result": "",
        })
        ev = _parse_stream_line(line)
        assert ev.is_error is True
        assert ev.subtype == "error_max_turns"

    def test_parse_result_error_during_execution(self):
        line = json.dumps({
            "type": "result", "is_error": True, "subtype": "error_during_execution",
            "session_id": "s", "cost_usd": 0.0, "num_turns": 2, "result": "Tool failed",
        })
        ev = _parse_stream_line(line)
        assert ev.subtype == "error_during_execution"
        assert ev.text == "Tool failed"

    def test_parse_assistant_non_text_block_ignored(self):
        line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash"}]},
        })
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.text == ""

    def test_parse_whitespace_only_returns_none(self):
        assert _parse_stream_line("   \n") is None

    def test_parse_result_duration_ms(self):
        line = json.dumps({
            "type": "result", "is_error": False, "session_id": "s",
            "cost_usd": 0.0, "num_turns": 1, "duration_ms": 3500, "result": "ok",
        })
        ev = _parse_stream_line(line)
        assert ev.duration_ms == 3500


class TestProcessEventsExtended:
    def test_empty_events_returns_default(self):
        result = _process_events([])
        assert result.response_text == ""
        assert result.session_id == ""
        assert result.cost_usd == 0.0
        assert result.tools_used == []

    def test_result_session_id_preferred(self):
        events = [
            _parse_stream_line(json.dumps({
                "type": "system", "subtype": "init", "session_id": "init-sess",
            })),
            _parse_stream_line(json.dumps({
                "type": "result", "session_id": "result-sess",
                "cost_usd": 0.01, "num_turns": 1, "is_error": False,
                "duration_ms": 100, "result": "done",
            })),
        ]
        events = [e for e in events if e is not None]
        result = _process_events(events)
        assert result.session_id == "result-sess"

    def test_init_session_id_fallback(self):
        events = [
            _parse_stream_line(json.dumps({
                "type": "system", "subtype": "init", "session_id": "init-sess",
            })),
            _parse_stream_line(json.dumps({
                "type": "result", "session_id": "",
                "cost_usd": 0.01, "num_turns": 1, "is_error": False,
                "duration_ms": 100, "result": "done",
            })),
        ]
        events = [e for e in events if e is not None]
        result = _process_events(events)
        assert result.session_id == "init-sess"

    def test_duplicate_tools_deduplicated(self):
        lines = [
            json.dumps({"type": "tool_use", "tool_name": "Bash"}),
            json.dumps({"type": "tool_use", "tool_name": "Bash"}),
            json.dumps({"type": "tool_use", "tool_name": "Read"}),
        ]
        events = [_parse_stream_line(l) for l in lines]
        events = [e for e in events if e is not None]
        result = _process_events(events)
        assert result.tools_used.count("Bash") == 1
        assert "Read" in result.tools_used

    def test_error_subtype_max_turns(self):
        ev = StreamEvent(
            type="result", is_error=True, subtype="error_max_turns",
            session_id="s", cost_usd=0.0, num_turns=10, duration_ms=0, text="",
        )
        result = _process_events([ev])
        assert result.error_type == "error_max_turns"

    def test_error_subtype_during_execution(self):
        ev = StreamEvent(
            type="result", is_error=True, subtype="error_during_execution",
            session_id="s", cost_usd=0.0, num_turns=2, duration_ms=0, text="fail",
        )
        result = _process_events([ev])
        assert result.error_type == "error_during_execution"

    def test_response_text_is_last_part(self):
        events = [
            StreamEvent(type="assistant", text="First."),
            StreamEvent(type="assistant", text="Second."),
            StreamEvent(
                type="result", text="Final.",
                session_id="s", cost_usd=0.0, num_turns=2, duration_ms=0, is_error=False,
            ),
        ]
        result = _process_events(events)
        assert result.response_text == "Final."


class TestClassifyErrorExtended:
    def test_classify_timeout_sigterm(self):
        assert _classify_error(-15, "") == "timeout"

    def test_classify_timeout_sigkill(self):
        assert _classify_error(-9, "") == "timeout"

    def test_classify_overloaded_stderr(self):
        assert _classify_error(1, "claude is overloaded") == "rate_limit"

    def test_classify_limit_in_stderr(self):
        assert _classify_error(1, "you have hit your daily limit") == "rate_limit"

    def test_classify_content_filter_stderr(self):
        assert _classify_error(1, "content policy violation filter") == "content_filter"

    def test_classify_unknown_exit_code(self):
        assert _classify_error(42, "") == "unknown"

    def test_classify_unknown_unrelated_stderr(self):
        assert _classify_error(2, "usage: claude [options]") == "unknown"


class TestResolveBinary:
    @pytest.fixture(autouse=True)
    def _clear_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sprint 08.07: BUMBA_CLAUDE_BINARY is checked first by
        ``_resolve_binary``. Tests in this class that exercise the
        config/which/fallback branches must run with the env var unset so
        they don't accidentally hit the override branch."""
        monkeypatch.delenv("BUMBA_CLAUDE_BINARY", raising=False)

    def test_config_binary_used_when_set(self, sample_config):
        config = dataclasses.replace(sample_config, claude_binary="/custom/claude")
        runner = ClaudeRunner(config)
        assert runner._resolve_binary() == "/custom/claude"

    def test_which_used_when_no_config_binary(self, sample_config):
        config = dataclasses.replace(sample_config, claude_binary="")
        runner = ClaudeRunner(config)
        with patch("bridge.claude_runner.shutil.which", return_value="/usr/bin/claude"):
            assert runner._resolve_binary() == "/usr/bin/claude"

    def test_fallback_home_bin(self, sample_config, tmp_path):
        config = dataclasses.replace(sample_config, claude_binary="")
        fake_binary = tmp_path / ".local" / "bin" / "claude"
        fake_binary.parent.mkdir(parents=True)
        fake_binary.touch()
        runner = ClaudeRunner(config)
        with (
            patch("bridge.claude_runner.shutil.which", return_value=None),
            patch("bridge.claude_runner.Path.home", return_value=tmp_path),
        ):
            binary = runner._resolve_binary()
        assert binary == str(fake_binary)

    def test_raises_when_not_found(self, sample_config, monkeypatch: pytest.MonkeyPatch):
        # Sprint 08.07: ensure the env-var override branch is not active so
        # the test exercises the real "binary not found" failure path.
        monkeypatch.delenv("BUMBA_CLAUDE_BINARY", raising=False)
        config = dataclasses.replace(sample_config, claude_binary="")
        runner = ClaudeRunner(config)
        with (
            patch("bridge.claude_runner.shutil.which", return_value=None),
            patch.object(Path, "is_file", return_value=False),
        ):
            with pytest.raises(FileNotFoundError, match="Claude Code binary not found"):
                runner._resolve_binary()

    def test_resolve_binary_env_override(
        self, sample_config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sprint 08.07 (#785): BUMBA_CLAUDE_BINARY beats config.claude_binary.

        The env var is the test-harness override that lets e2e harnesses
        thread fake_claude.py through the real Dispatcher → Executor →
        ClaudeRunner chain without mutating BridgeConfig. It MUST take
        precedence over an existing ``config.claude_binary`` so a test that
        loads a real production-style config can still redirect to the shim.
        """
        # Config has a real-looking claude_binary that should be SHADOWED by
        # the env var while it's set.
        config = dataclasses.replace(sample_config, claude_binary="/usr/local/bin/claude")
        runner = ClaudeRunner(config)

        # Single-token override (bare path)
        monkeypatch.setenv("BUMBA_CLAUDE_BINARY", "/tmp/shim-claude")
        assert runner._resolve_binary() == "/tmp/shim-claude"

        # Multi-token override (whitespace → list[str] for shim invocations)
        monkeypatch.setenv("BUMBA_CLAUDE_BINARY", "/usr/bin/python3 /opt/fake_claude.py")
        result = runner._resolve_binary()
        assert result == ["/usr/bin/python3", "/opt/fake_claude.py"]

        # Unset → fallback to config.claude_binary
        monkeypatch.delenv("BUMBA_CLAUDE_BINARY", raising=False)
        assert runner._resolve_binary() == "/usr/local/bin/claude"


class TestBuildCommandModel:
    def test_model_flag_included(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hi", model="haiku")
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "haiku"

    def test_model_flag_absent_without_model(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hi")
        assert "--model" not in cmd

    def test_verbose_always_present(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hi")
        assert "--verbose" in cmd


class TestResumeBugRegression:
    """Regression for bridge-UUID-as-resume bug."""

    def test_none_session_id_no_resume_flag(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hello", session_id=None)
        assert "--resume" not in cmd

    def test_empty_session_id_no_resume_flag(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        cmd = runner._build_command("Hello", session_id="")
        assert "--resume" not in cmd

    def test_valid_claude_session_id_passed_to_resume(self, sample_config):
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        real_session_id = "sess-abc123def456"
        cmd = runner._build_command("Hello", session_id=real_session_id)
        assert "--resume" in cmd
        idx = cmd.index("--resume")
        assert cmd[idx + 1] == real_session_id

    def test_process_events_extracts_claude_session_id(self):
        events = [
            _parse_stream_line(json.dumps({
                "type": "system", "subtype": "init",
                "session_id": "real-claude-session-id",
            })),
            _parse_stream_line(json.dumps({
                "type": "result", "session_id": "real-claude-session-id",
                "cost_usd": 0.01, "num_turns": 1, "is_error": False,
                "duration_ms": 500, "result": "ok",
            })),
        ]
        events = [e for e in events if e is not None]
        result = _process_events(events)
        assert result.session_id == "real-claude-session-id"


class TestTokenProvider:
    def test_set_token_provider_stores_provider(self, sample_config):
        runner = ClaudeRunner(sample_config)
        provider = MagicMock()
        runner.set_token_provider(provider)
        assert runner._token_provider is provider


class TestKillCurrent:
    @pytest.mark.asyncio
    async def test_kill_current_no_process_returns_false(self, sample_config):
        runner = ClaudeRunner(sample_config)
        result = await runner.kill_current()
        assert result is False

    @pytest.mark.asyncio
    async def test_kill_current_with_process_calls_kill(self, sample_config):
        runner = ClaudeRunner(sample_config)
        mock_proc = MagicMock()
        mock_proc.returncode = None
        runner._process = mock_proc

        async def fake_kill():
            pass

        with patch.object(runner, "_kill_process", side_effect=fake_kill):
            result = await runner.kill_current()
        assert result is True


class TestCleanupStale:
    @pytest.mark.asyncio
    async def test_cleanup_stale_no_pid_file(self, sample_config, tmp_dirs):
        config = dataclasses.replace(sample_config, data_dir=str(tmp_dirs["data_dir"]))
        runner = ClaudeRunner(config)
        await runner.cleanup_stale()

    @pytest.mark.asyncio
    async def test_cleanup_stale_invalid_pid_file(self, sample_config, tmp_dirs):
        config = dataclasses.replace(sample_config, data_dir=str(tmp_dirs["data_dir"]))
        runner = ClaudeRunner(config)
        runner._pid_file.write_text("not-a-pid")
        await runner.cleanup_stale()
        assert not runner._pid_file.exists()

    @pytest.mark.asyncio
    async def test_cleanup_stale_nonexistent_process(self, sample_config, tmp_dirs):
        config = dataclasses.replace(sample_config, data_dir=str(tmp_dirs["data_dir"]))
        runner = ClaudeRunner(config)
        runner._pid_file.write_text("9999999")
        await runner.cleanup_stale()
        assert not runner._pid_file.exists()


class TestWarmClaudeProcessProperties:
    def test_is_alive_no_process(self, sample_config):
        warm = WarmClaudeProcess(sample_config)
        assert warm.is_alive is False

    def test_is_alive_with_alive_process(self, sample_config):
        warm = WarmClaudeProcess(sample_config)
        mock_proc = MagicMock()
        mock_proc.returncode = None
        warm._process = mock_proc
        assert warm.is_alive is True

    def test_is_alive_with_exited_process(self, sample_config):
        warm = WarmClaudeProcess(sample_config)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        warm._process = mock_proc
        assert warm.is_alive is False

    def test_session_id_initially_none(self, sample_config):
        warm = WarmClaudeProcess(sample_config)
        assert warm.session_id is None

    def test_session_id_set(self, sample_config):
        warm = WarmClaudeProcess(sample_config)
        warm._session_id = "sess-warm-123"
        assert warm.session_id == "sess-warm-123"

    @pytest.mark.asyncio
    async def test_close_noop_when_no_process(self, sample_config):
        warm = WarmClaudeProcess(sample_config)
        # Pre-condition: no process started yet.
        assert warm._process is None
        await warm.close()
        # Post-condition: still no process and no leftover reader tasks.
        assert warm._process is None
        assert warm._reader_task is None
        assert warm._stderr_task is None

    @pytest.mark.asyncio
    async def test_cycle_returns_false_when_no_working_dir(self, sample_config):
        warm = WarmClaudeProcess(sample_config)
        warm._working_dir = ""
        result = await warm.cycle()
        assert result is False


# ---------------------------------------------------------------------------
# Sprint D8.1 — narrow warm-process MCP set via --mcp-config + --strict-mcp-config
# ---------------------------------------------------------------------------

class TestWarmClaudeProcessMcpConfig:
    """Sprint D8.1: WarmClaudeProcess.spawn() emits --mcp-config flags only
    when warm_mcp_config is set AND the file exists. Empty config preserves
    the legacy behavior (no flags emitted, .mcp.json inherited).
    """

    @staticmethod
    async def _capture_spawn_cmd(config) -> list[str]:
        """Run WarmClaudeProcess.spawn() with create_subprocess_exec mocked
        to capture the cmd and abort before warmup. Returns the captured cmd.
        """
        warm = WarmClaudeProcess(config)
        captured: dict[str, list[str]] = {}

        async def fake_subprocess_exec(*cmd, **_kwargs):
            captured["cmd"] = list(cmd)
            # Abort spawn() before it tries to send a warmup message.
            raise RuntimeError("captured-cmd-stop")

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=fake_subprocess_exec,
        ), patch(
            "bridge.claude_runner.shutil.which",
            return_value="/fake/claude",
        ):
            result = await warm.spawn(working_dir="/tmp/wd", model="haiku")

        # spawn() returns False when subprocess_exec raises — that's fine for
        # our purposes; we only care about the cmd that was assembled.
        assert result is False
        assert "cmd" in captured, "create_subprocess_exec was not invoked"
        return captured["cmd"]

    @pytest.mark.asyncio
    async def test_spawn_cmd_omits_mcp_flags_when_warm_mcp_config_empty(
        self, sample_config
    ):
        """Default (warm_mcp_config = ""): no --mcp-config flag emitted —
        warm process inherits the working-dir .mcp.json byte-for-byte as
        before D8.1.
        """
        cfg = dataclasses.replace(sample_config, warm_mcp_config="")
        cmd = await self._capture_spawn_cmd(cfg)
        assert "--mcp-config" not in cmd
        assert "--strict-mcp-config" not in cmd

    @pytest.mark.asyncio
    async def test_spawn_cmd_includes_mcp_flags_when_warm_mcp_config_set_and_file_exists(
        self, sample_config, tmp_path
    ):
        """When warm_mcp_config points to an existing file, the spawn cmd
        gains --mcp-config <path> and --strict-mcp-config so Claude ignores
        the working-dir .mcp.json.
        """
        mcp_file = tmp_path / "warm-core-mcp.json"
        mcp_file.write_text('{"mcpServers": {}}')
        cfg = dataclasses.replace(sample_config, warm_mcp_config=str(mcp_file))
        cmd = await self._capture_spawn_cmd(cfg)
        assert "--mcp-config" in cmd
        idx = cmd.index("--mcp-config")
        assert cmd[idx + 1] == str(mcp_file)
        assert "--strict-mcp-config" in cmd

    @pytest.mark.asyncio
    async def test_spawn_fails_closed_when_warm_mcp_config_set_but_file_missing(
        self, sample_config, tmp_path
    ):
        """P1.4: missing file is a fail-closed condition. ``spawn`` returns
        ``False`` and the subprocess is never invoked — silent fallback to
        ``.mcp.json`` would defeat the narrowing this config exists to do.
        """
        missing = tmp_path / "does-not-exist.json"
        cfg = dataclasses.replace(sample_config, warm_mcp_config=str(missing))
        warm = WarmClaudeProcess(cfg)

        called: dict[str, bool] = {"subprocess": False}

        async def fake_subprocess_exec(*_cmd, **_kwargs):
            called["subprocess"] = True
            raise RuntimeError("should not be reached")

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=fake_subprocess_exec,
        ), patch(
            "bridge.claude_runner.shutil.which",
            return_value="/fake/claude",
        ):
            result = await warm.spawn(working_dir="/tmp/wd", model="haiku")

        assert result is False
        assert called["subprocess"] is False, (
            "subprocess must not be spawned when warm_mcp_config path missing"
        )


# ---------------------------------------------------------------------------
# Sprint 06.11 — Halt flag polling in streaming loop
# ---------------------------------------------------------------------------

class TestHaltFlagPollDuringStream:
    """ClaudeRunner.invoke() terminates subprocess when halt flag appears mid-run."""

    @pytest.mark.asyncio
    async def test_halt_flag_terminates_subprocess(self, sample_config, tmp_path):
        """When halt.flag appears after 10 stdout lines, subprocess receives SIGTERM.

        Post-P1.2 (audit C2): the halt path signals the *process group* via
        ``os.killpg``, not the parent only via ``send_signal``. This test
        asserts on ``killpg`` to keep the harness honest — a regression that
        narrows back to parent-only termination orphans MCP/tool subprocesses
        and must be caught here.
        """
        import signal as _signal

        # Build a config pointing data_dir at tmp_path (no halt flag initially)
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))

        runner = ClaudeRunner(cfg)

        # Simulate 11 stdout lines followed by EOF; halt flag appears before line 11
        # Lines 1-10 do not trigger halt check; line 11 does (counter resets to 0 at 10)
        lines_sent = []
        halt_flag = tmp_path / "halt.flag"

        async def fake_readline():
            """Feed lines: set halt flag on the 9th line so check fires at counter=10."""
            idx = len(lines_sent)
            # Set halt flag on the 9th line (0-indexed) — counter hits 10 after this line
            # is processed and the halt check fires.
            if idx == 9:
                halt_flag.touch()
            if idx >= 12:
                return b""  # EOF — should not reach here normally
            line = json.dumps({"type": "result", "subtype": "success", "result": "ok"}).encode() + b"\n"
            lines_sent.append(line)
            return line

        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(side_effect=fake_readline)

        mock_stdin = AsyncMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_stdin.close = MagicMock()
        mock_stdin.wait_closed = AsyncMock()

        mock_stderr = AsyncMock()
        mock_stderr.read = AsyncMock(return_value=b"")

        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.stdout = mock_stdout
        mock_proc.stdin = mock_stdin
        mock_proc.stderr = mock_stderr
        # returncode starts None so _terminate_process_group does not
        # early-return; fake_killpg below flips it to a SIGTERM-coded value
        # to simulate the group dying.
        mock_proc.returncode = None
        mock_proc.wait = AsyncMock()
        mock_proc.send_signal = MagicMock()

        killpg_calls: list[tuple[int, int]] = []

        def fake_killpg(pgid, sig):
            killpg_calls.append((pgid, sig))
            # Simulate the group receiving SIGTERM so proc.wait() returns
            # quickly inside _terminate_process_group.
            mock_proc.returncode = -sig

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(runner, "_build_command", return_value=["fake-claude", "-p"]), \
             patch.object(runner, "_watchdog", new_callable=AsyncMock), \
             patch("bridge.claude_runner.os.getpgid", return_value=mock_proc.pid), \
             patch("bridge.claude_runner.os.killpg", side_effect=fake_killpg):
            await runner.invoke("test message")

        assert any(sig == _signal.SIGTERM for _, sig in killpg_calls), (
            "ClaudeRunner should have sent SIGTERM to the process group "
            f"when halt flag was detected; calls={killpg_calls}"
        )
        assert mock_proc.send_signal.call_count == 0, (
            "P1.2: halt path must not call parent-only send_signal — use "
            "killpg to reach MCP/tool subprocesses"
        )

    @pytest.mark.asyncio
    async def test_no_halt_flag_completes_normally(self, sample_config, tmp_path):
        """Without halt flag, invoke() reads all lines and returns normally."""
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))

        runner = ClaudeRunner(cfg)

        lines = [
            json.dumps({"type": "result", "subtype": "success", "result": "hello"}).encode() + b"\n"
            for _ in range(5)
        ] + [b""]

        call_count = [0]

        async def fake_readline():
            idx = call_count[0]
            call_count[0] += 1
            return lines[idx] if idx < len(lines) else b""

        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(side_effect=fake_readline)

        mock_stdin = AsyncMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_stdin.close = MagicMock()
        mock_stdin.wait_closed = AsyncMock()

        mock_stderr = AsyncMock()
        mock_stderr.read = AsyncMock(return_value=b"")

        mock_proc = MagicMock()
        mock_proc.pid = 11111
        mock_proc.stdout = mock_stdout
        mock_proc.stdin = mock_stdin
        mock_proc.stderr = mock_stderr
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock()
        mock_proc.send_signal = MagicMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(runner, "_build_command", return_value=["fake-claude", "-p"]), \
             patch.object(runner, "_watchdog", new_callable=AsyncMock):
            result = await runner.invoke("test message")

        assert mock_proc.send_signal.call_count == 0, "No SIGTERM should be sent without halt flag"


# ---------------------------------------------------------------------------
# Sprint D7.9 #1421 — operator-message interrupt during in-flight tool calls
# ---------------------------------------------------------------------------

class TestOperatorInterruptDuringStream:
    """ClaudeRunner.invoke() yields the in-flight subprocess when a new
    operator message lands mid-stream.

    Mirrors the halt-flag pattern (above) but distinguishes:
      - SIGTERM still fires (graceful yield at next safe boundary)
      - response_text becomes the gate's BLOCK_* message (so the agent
        acknowledges before continuing)
      - is_error is False (the interrupt was the desired outcome, not
        a subprocess failure) and error_type is cleared
    """

    @staticmethod
    def _make_proc_mock(fake_readline, *, sigterm_recorder=None):
        """Build a subprocess MagicMock that streams via fake_readline."""
        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(side_effect=fake_readline)
        mock_stdin = AsyncMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_stdin.close = MagicMock()
        mock_stdin.wait_closed = AsyncMock()
        mock_stderr = AsyncMock()
        mock_stderr.read = AsyncMock(return_value=b"")
        mock_proc = MagicMock()
        mock_proc.pid = 88888
        mock_proc.stdout = mock_stdout
        mock_proc.stdin = mock_stdin
        mock_proc.stderr = mock_stderr
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock()

        def _record(sig):
            if sigterm_recorder is not None:
                sigterm_recorder.append(sig)

        mock_proc.send_signal = MagicMock(side_effect=_record)
        return mock_proc

    @pytest.mark.asyncio
    async def test_operator_interrupt_terminates_subprocess(
        self, sample_config, tmp_path
    ):
        """Operator message arriving mid-stream → SIGTERM + block-message result.

        Acceptance criterion (D7.9): "in-flight tool call yields at next
        safe boundary; no orphaned subprocesses".

        Post-P1.2 (audit C2): "no orphaned subprocesses" is enforced via
        process-group SIGTERM (``os.killpg``). The parent-only ``send_signal``
        path is no longer used here — this test guards against regressions
        that would re-orphan MCP/tool children.
        """
        import signal as _signal

        from bridge.operator_inbox import MessageSeverity, OperatorInbox

        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)

        # Wire an inbox with NO pending messages at start so the pre-spawn
        # gate allows the invoke. The operator message lands AFTER the
        # subprocess starts streaming.
        inbox = OperatorInbox(session_id="sess-d7-9-test")
        runner.set_operator_inbox(inbox)

        lines_sent: list = []

        async def fake_readline():
            """Feed lines: drop a new operator message at line 9 so the
            mid-stream check at line 10 (counter resets after the inverval
            fires) catches it.
            """
            idx = len(lines_sent)
            if idx == 9:
                # Inject an operator message into the inbox right before
                # the next halt-check tick. The mid-stream poll should pick
                # it up on its next interval and SIGTERM the subprocess.
                await inbox.receive(
                    "the operator here — please pause",
                    MessageSeverity.QUESTION,
                )
            if idx >= 25:
                return b""  # safety guard — should break long before this
            line = json.dumps(
                {"type": "result", "subtype": "success", "result": "ok"}
            ).encode() + b"\n"
            lines_sent.append(line)
            return line

        mock_proc = self._make_proc_mock(fake_readline)
        # _terminate_process_group early-returns when returncode is set;
        # flip to None so the killpg path actually runs.
        mock_proc.returncode = None

        killpg_calls: list[tuple[int, int]] = []

        def fake_killpg(pgid, sig):
            killpg_calls.append((pgid, sig))
            mock_proc.returncode = -sig

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(runner, "_build_command", return_value=["fake-claude", "-p"]), \
             patch.object(runner, "_watchdog", new_callable=AsyncMock), \
             patch("bridge.claude_runner.os.getpgid", return_value=mock_proc.pid), \
             patch("bridge.claude_runner.os.killpg", side_effect=fake_killpg):
            result = await runner.invoke("test message", session_id="sess-d7-9-test")

        # Acceptance #1: SIGTERM fired to the process group (P1.2 audit C2)
        assert any(sig == _signal.SIGTERM for _, sig in killpg_calls), (
            "ClaudeRunner should have sent SIGTERM to the process group "
            f"when operator message arrived mid-stream; calls={killpg_calls}"
        )
        assert mock_proc.send_signal.call_count == 0, (
            "P1.2: operator-interrupt path must not call parent-only "
            "send_signal — use killpg to reach MCP/tool subprocesses"
        )
        # Acceptance #2: result carries the gate block message, not the
        # raw stream output. The block message starts with the gate header
        # text from tool_call_gate._format_question_block.
        assert "TOOL CALL BLOCKED" in result.response_text, (
            f"expected block message; got: {result.response_text[:200]}"
        )
        assert "QUESTION" in result.response_text
        # Acceptance #3: no error flag (the interrupt was the goal)
        assert result.is_error is False
        assert result.error_type == ""

    @pytest.mark.asyncio
    async def test_no_inbox_completes_normally(self, sample_config, tmp_path):
        """Without an OperatorInbox wired, the mid-stream check is a no-op
        and the subprocess streams to completion.
        """
        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)
        # Note: NO set_operator_inbox call — runner._operator_inbox is None

        lines = [
            json.dumps({"type": "result", "subtype": "success", "result": "hi"}).encode()
            + b"\n"
            for _ in range(15)
        ] + [b""]
        call_count = [0]

        async def fake_readline():
            idx = call_count[0]
            call_count[0] += 1
            return lines[idx] if idx < len(lines) else b""

        sigterm_sent: list = []
        mock_proc = self._make_proc_mock(fake_readline, sigterm_recorder=sigterm_sent)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(runner, "_build_command", return_value=["fake-claude", "-p"]), \
             patch.object(runner, "_watchdog", new_callable=AsyncMock):
            result = await runner.invoke("test message")

        assert mock_proc.send_signal.call_count == 0, (
            "No SIGTERM should fire when no inbox is wired"
        )
        # Block-message overlay should NOT have been applied
        assert "TOOL CALL BLOCKED" not in (result.response_text or "")

    @pytest.mark.asyncio
    async def test_empty_inbox_completes_normally(self, sample_config, tmp_path):
        """Inbox wired but empty → no interrupt, normal completion."""
        from bridge.operator_inbox import OperatorInbox

        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)
        runner.set_operator_inbox(OperatorInbox(session_id="empty"))

        lines = [
            json.dumps({"type": "result", "subtype": "success", "result": "hi"}).encode()
            + b"\n"
            for _ in range(15)
        ] + [b""]
        call_count = [0]

        async def fake_readline():
            idx = call_count[0]
            call_count[0] += 1
            return lines[idx] if idx < len(lines) else b""

        mock_proc = self._make_proc_mock(fake_readline)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(runner, "_build_command", return_value=["fake-claude", "-p"]), \
             patch.object(runner, "_watchdog", new_callable=AsyncMock):
            result = await runner.invoke("test message")

        assert mock_proc.send_signal.call_count == 0
        assert "TOOL CALL BLOCKED" not in (result.response_text or "")

    @pytest.mark.asyncio
    async def test_ack_latency_is_recorded(self, sample_config, tmp_path):
        """A successful interrupt records an `operator_msg_ack_latency_ms`
        attribute on a tracing span. The span lands in the data-dir JSONL
        so external p50/p95 tooling can compute rollups without a new sink.
        """
        from bridge.operator_inbox import MessageSeverity, OperatorInbox

        cfg = dataclasses.replace(sample_config, data_dir=str(tmp_path))
        runner = ClaudeRunner(cfg)
        inbox = OperatorInbox(session_id="sess-d7-9-latency")
        runner.set_operator_inbox(inbox)

        lines_sent: list = []

        async def fake_readline():
            idx = len(lines_sent)
            if idx == 9:
                await inbox.receive("Pause", MessageSeverity.QUESTION)
            if idx >= 25:
                return b""
            line = json.dumps(
                {"type": "result", "subtype": "success", "result": "ok"}
            ).encode() + b"\n"
            lines_sent.append(line)
            return line

        mock_proc = self._make_proc_mock(fake_readline)
        # _terminate_process_group early-returns when returncode is set;
        # flip to None so the killpg path actually runs.
        mock_proc.returncode = None

        def fake_killpg(pgid, sig):
            mock_proc.returncode = -sig

        # Capture spans by patching Tracer._write_span on this run only.
        from bridge import tracing as _tr
        captured_spans: list = []
        original_write = _tr.Tracer._write_span

        def _capture(self_tracer, span):
            captured_spans.append(span)
            return original_write(self_tracer, span)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(runner, "_build_command", return_value=["fake-claude", "-p"]), \
             patch.object(runner, "_watchdog", new_callable=AsyncMock), \
             patch.object(_tr.Tracer, "_write_span", _capture), \
             patch("bridge.claude_runner.os.getpgid", return_value=mock_proc.pid), \
             patch("bridge.claude_runner.os.killpg", side_effect=fake_killpg):
            await runner.invoke("test message", session_id="sess-d7-9-latency")

        ack_spans = [s for s in captured_spans if s.name == "operator_msg_ack_latency"]
        assert len(ack_spans) == 1, (
            f"expected exactly one ack-latency span; got {[s.name for s in captured_spans]}"
        )
        attrs = ack_spans[0].attributes
        assert "ack_latency_ms" in attrs
        assert isinstance(attrs["ack_latency_ms"], int)
        assert attrs["ack_latency_ms"] >= 0
        # Acceptance bar (D7.9): ack within 5s under normal conditions.
        # In tests with no real network, this is bounded by the read-loop
        # iteration count (~10ms) plus tracing overhead — safely under 5s.
        assert attrs["ack_latency_ms"] < 5000, (
            f"ack latency {attrs['ack_latency_ms']}ms exceeds 5s bar"
        )
        assert attrs["session_id"] == "sess-d7-9-latency"
        assert attrs["pending_count"] == 1


# ---------------------------------------------------------------------------
# Sprint D8.2 — token-refresh double-buffer for WarmClaudeProcess
# ---------------------------------------------------------------------------

class TestTokenRefreshDoubleBuffer:
    """Sprint D8.2: BridgeApp._refresh_warm_claude() pre-spawns the new warm
    process BEFORE closing the old one, then atomically swaps. Eliminates the
    30-120s scheduled cold window the old close-then-spawn cycle introduced
    every ~6h on OAuth token refresh.
    """

    @staticmethod
    def _make_app(sample_config) -> object:
        """Construct a minimal BridgeApp wired with just enough state for
        _refresh_warm_claude to run.

        BridgeApp.__init__ only does attribute assignment so it's safe to
        call with config_path=None.
        """
        from bridge.app import BridgeApp

        app = BridgeApp(config_path=None)
        app._config = sample_config
        app._token_refresher = MagicMock()
        return app

    @pytest.mark.asyncio
    async def test_double_buffer_swaps_in_new_process(self, sample_config):
        """Happy path: new spawn succeeds → self._warm_claude points at new,
        old.close() is scheduled (in a background task) but old was NOT
        closed before the swap.
        """
        app = self._make_app(sample_config)

        # Old: alive, has captured spawn params from a previous spawn().
        old = MagicMock(spec=WarmClaudeProcess)
        old.is_alive = True
        old._working_dir = "/tmp/wd"
        old._model = "haiku"
        old._system_prompt_file = None
        old.close = AsyncMock()
        old.cycle = AsyncMock()
        app._warm_claude = old

        # New: spawn() succeeds.
        new = MagicMock(spec=WarmClaudeProcess)
        new.spawn = AsyncMock(return_value=True)
        new.close = AsyncMock()

        with patch("bridge.app.WarmClaudeProcess", return_value=new):
            await app._refresh_warm_claude()

        # The pointer was swapped to the new process.
        assert app._warm_claude is new

        # New was spawned with the captured params.
        new.spawn.assert_awaited_once_with("/tmp/wd", "haiku", None)

        # Old was NOT closed on the foreground path — close was deferred to a
        # background task. Yield once so the create_task'd coroutine runs and
        # we can confirm it eventually closes.
        await asyncio.sleep(0)
        old.close.assert_awaited()

    @pytest.mark.asyncio
    async def test_double_buffer_keeps_old_when_new_fails_to_spawn(
        self, sample_config
    ):
        """When new.spawn() returns False, the old process is preserved (no
        swap) and is best-effort cycled to pick up the new token.
        """
        app = self._make_app(sample_config)

        old = MagicMock(spec=WarmClaudeProcess)
        old.is_alive = True
        old._working_dir = "/tmp/wd"
        old._model = "haiku"
        old._system_prompt_file = None
        old.close = AsyncMock()
        old.cycle = AsyncMock(return_value=True)
        app._warm_claude = old

        new = MagicMock(spec=WarmClaudeProcess)
        new.spawn = AsyncMock(return_value=False)
        new.close = AsyncMock()

        with patch("bridge.app.WarmClaudeProcess", return_value=new):
            await app._refresh_warm_claude()

        # No swap — old is still the warm process.
        assert app._warm_claude is old

        # Best-effort fallback cycle on the old.
        old.cycle.assert_awaited_once()

        # Old was NOT closed (we kept it).
        old.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_double_buffer_skips_when_warm_never_spawned(
        self, sample_config
    ):
        """If the old process has no captured working_dir (never spawned),
        skip the double-buffer entirely. No new process is constructed.
        """
        app = self._make_app(sample_config)

        old = MagicMock(spec=WarmClaudeProcess)
        old.is_alive = False  # never spawned → not alive
        old._working_dir = ""  # never spawned → empty
        old._model = "haiku"
        old._system_prompt_file = None
        old.close = AsyncMock()
        old.cycle = AsyncMock()
        app._warm_claude = old

        sentinel = MagicMock()  # would-be new instance, must NOT be called
        sentinel.spawn = AsyncMock(return_value=True)

        with patch("bridge.app.WarmClaudeProcess", return_value=sentinel) as mock_cls:
            await app._refresh_warm_claude()

        # No new WarmClaudeProcess was constructed.
        mock_cls.assert_not_called()
        sentinel.spawn.assert_not_awaited()

        # Old still in place; cycle was not called either (old.is_alive == False).
        assert app._warm_claude is old
        old.cycle.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_double_buffer_returns_when_warm_is_none(self, sample_config):
        """When self._warm_claude is None, the refresh callback returns
        without touching anything.
        """
        app = self._make_app(sample_config)
        app._warm_claude = None

        with patch("bridge.app.WarmClaudeProcess") as mock_cls:
            await app._refresh_warm_claude()

        mock_cls.assert_not_called()
        assert app._warm_claude is None


# ---------------------------------------------------------------------------
# Sprint D8.3 — Background respawn on warm-process crash
# ---------------------------------------------------------------------------

class TestBackgroundRespawn:
    """Sprint D8.3: when the warm process dies, _stdout_reader's finally
    block schedules a background respawn so the next operator message
    doesn't pay the cold-spawn cost inline.
    """

    @pytest.mark.asyncio
    async def test_respawn_scheduled_on_reader_exit(self, sample_config):
        """When _stdout_reader exits and _working_dir is set, a respawn
        task is scheduled and _respawn_in_progress flips to True."""
        warm = WarmClaudeProcess(sample_config)
        warm._working_dir = "/tmp/test"
        warm._model = "haiku"
        warm._system_prompt_file = None

        # Mock _background_respawn so we can detect scheduling without
        # actually running the retry loop. Replace with an AsyncMock; the
        # task it produces is awaited by the test loop and exits cleanly.
        background_calls: list[int] = []

        async def fake_background_respawn():
            background_calls.append(1)

        warm._background_respawn = fake_background_respawn  # type: ignore[method-assign]

        # Mock the process: stdout.readline returns EOF immediately, so
        # _stdout_reader falls straight through to the finally block.
        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(return_value=b"")
        mock_proc = MagicMock()
        mock_proc.stdout = mock_stdout
        warm._process = mock_proc

        await warm._stdout_reader()

        # finally block should have set the flag and scheduled the task.
        assert warm._respawn_in_progress is True
        # Yield once so the scheduled task runs.
        await asyncio.sleep(0)
        assert background_calls == [1]

    @pytest.mark.asyncio
    async def test_respawn_skipped_when_never_spawned(self, sample_config):
        """Fresh instance with _working_dir="" must not schedule a respawn —
        there's nothing to respawn."""
        warm = WarmClaudeProcess(sample_config)
        # Default _working_dir is "" from __init__.
        assert warm._working_dir == ""

        scheduled: list[int] = []

        async def fake_background_respawn():
            scheduled.append(1)

        warm._background_respawn = fake_background_respawn  # type: ignore[method-assign]

        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(return_value=b"")
        mock_proc = MagicMock()
        mock_proc.stdout = mock_stdout
        warm._process = mock_proc

        await warm._stdout_reader()

        assert warm._respawn_in_progress is False
        await asyncio.sleep(0)
        assert scheduled == []

    @pytest.mark.asyncio
    async def test_respawn_skipped_when_already_in_progress(self, sample_config):
        """If _respawn_in_progress is already True, the finally block must
        NOT schedule a second respawn task."""
        warm = WarmClaudeProcess(sample_config)
        warm._working_dir = "/tmp/test"
        warm._respawn_in_progress = True

        scheduled: list[int] = []

        async def fake_background_respawn():
            scheduled.append(1)

        warm._background_respawn = fake_background_respawn  # type: ignore[method-assign]

        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(return_value=b"")
        mock_proc = MagicMock()
        mock_proc.stdout = mock_stdout
        warm._process = mock_proc

        await warm._stdout_reader()

        await asyncio.sleep(0)
        assert scheduled == []
        # Flag still True because we didn't run the respawn (its finally
        # block resets it; we didn't go through that path).
        assert warm._respawn_in_progress is True

    @pytest.mark.asyncio
    async def test_background_respawn_succeeds_on_first_attempt(
        self, sample_config, monkeypatch
    ):
        """When spawn() returns True on first try, the respawn task exits
        cleanly and _respawn_in_progress resets to False."""
        warm = WarmClaudeProcess(sample_config)
        warm._working_dir = "/tmp/test"
        warm._model = "haiku"
        warm._respawn_in_progress = True

        # Skip real sleeps — the test should complete in milliseconds.
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        spawn_calls: list[tuple[str, str, str | None]] = []

        async def fake_spawn(working_dir, model="haiku", system_prompt_file=None):
            spawn_calls.append((working_dir, model, system_prompt_file))
            return True

        warm.spawn = fake_spawn  # type: ignore[method-assign]

        await warm._background_respawn()

        # First attempt succeeded — exactly one spawn call.
        assert len(spawn_calls) == 1
        assert spawn_calls[0] == ("/tmp/test", "haiku", None)
        # finally block resets the guard.
        assert warm._respawn_in_progress is False

    @pytest.mark.asyncio
    async def test_background_respawn_gives_up_after_3_failures(
        self, sample_config, monkeypatch
    ):
        """When spawn() returns False three times, the loop bails and
        _respawn_in_progress resets — next message will spawn inline."""
        warm = WarmClaudeProcess(sample_config)
        warm._working_dir = "/tmp/test"
        warm._model = "haiku"
        warm._respawn_in_progress = True

        # Skip real sleeps so the test runs fast.
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        spawn_calls: list[int] = []

        async def fake_spawn(working_dir, model="haiku", system_prompt_file=None):
            spawn_calls.append(1)
            return False

        warm.spawn = fake_spawn  # type: ignore[method-assign]

        await warm._background_respawn()

        assert len(spawn_calls) == 3, "should have tried exactly 3 times"
        assert warm._respawn_in_progress is False


# ---------------------------------------------------------------------------
# HaltPolicy wiring (audit-2026-05-16.C.02, #2057)
# ---------------------------------------------------------------------------


def _make_halt_policy(*, halted: bool, reason: str | None = "operator pressed /halt"):
    """Construct a HaltPolicy for tests with controllable halt state.

    A list cell holds the current halted state so the test can flip it
    mid-stream — useful for the mid-run cancellation test.
    """
    from bridge.halt import HaltPolicy

    state = {"halted": halted}

    def _is_halted() -> bool:
        return state["halted"]

    def _halt_reason() -> str | None:
        return reason if state["halted"] else None

    policy = HaltPolicy(is_halted=_is_halted, halt_reason=_halt_reason)
    # Attach a setter so the test can flip the flag from inside callbacks.
    policy._test_set_halted = lambda v: state.__setitem__("halted", v)  # type: ignore[attr-defined]
    return policy


class TestHaltPolicyWiring:
    """Verifies set_halt_policy + check_start/check_continue wiring (C.02)."""

    def test_set_halt_policy_stores_policy_and_default_surface(self, sample_config):
        runner = ClaudeRunner(sample_config)
        policy = _make_halt_policy(halted=False)
        runner.set_halt_policy(policy)
        assert runner._halt_policy is policy
        assert runner._halt_surface == "claude-runner"

    def test_set_halt_policy_stores_custom_surface(self, sample_config):
        runner = ClaudeRunner(sample_config)
        policy = _make_halt_policy(halted=False)
        runner.set_halt_policy(policy, surface="warm-chief")
        assert runner._halt_policy is policy
        assert runner._halt_surface == "warm-chief"

    @pytest.mark.asyncio
    async def test_halt_before_start_returns_synthetic_no_spawn(
        self, sample_config
    ):
        # When the policy reports halted, invoke() short-circuits BEFORE
        # any subprocess work — no asyncio.create_subprocess_exec call.
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        policy = _make_halt_policy(halted=True, reason="operator pressed /halt")
        runner.set_halt_policy(policy, surface="warm-chief")

        spawned: list[bool] = []

        async def _should_not_spawn(*args, **kwargs):
            spawned.append(True)
            raise AssertionError("subprocess should not be spawned under halt")

        with patch(
            "bridge.claude_runner.asyncio.create_subprocess_exec",
            new=_should_not_spawn,
        ):
            result = await runner.invoke("hello")

        assert spawned == []
        assert result.is_error is False
        assert result.response_text.startswith("HALTED:")
        assert "warm-chief" in result.response_text
        assert "operator pressed /halt" in result.response_text

    @pytest.mark.asyncio
    async def test_mid_stream_halt_terminates_process_group(
        self, sample_config
    ):
        # Halt flag flips mid-stream after some lines have been read.
        # The runner's periodic check sees the policy block at the next
        # interval and calls _terminate_process_group. We assert the
        # group-termination helper was invoked and the process.returncode
        # is set (no zombie).
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        policy = _make_halt_policy(halted=False)
        runner.set_halt_policy(policy, surface="warm-chief")

        # Build a fake stdout that yields enough lines to trip the
        # _HALT_CHECK_INTERVAL (10) — line index 9 flips the halt flag
        # so line 10 triggers the policy check + termination.
        line_count = {"n": 0}

        async def _fake_readline():
            line_count["n"] += 1
            if line_count["n"] == 9:
                policy._test_set_halted(True)  # type: ignore[attr-defined]
            if line_count["n"] > 25:
                return b""  # EOF guard so an unbounded loop fails the test
            # Use an unparseable line so _parse_stream_line returns None
            # and we don't pollute the event list with bogus events.
            return b"PING\n"

        fake_stdin = MagicMock()
        fake_stdin.write = MagicMock()
        async def _drain():
            return None
        async def _wait_closed():
            return None
        fake_stdin.drain = _drain
        fake_stdin.close = MagicMock()
        fake_stdin.wait_closed = _wait_closed

        fake_stdout = MagicMock()
        fake_stdout.readline = _fake_readline

        fake_stderr = MagicMock()
        async def _read():
            return b""
        fake_stderr.read = _read

        fake_proc = MagicMock()
        fake_proc.stdin = fake_stdin
        fake_proc.stdout = fake_stdout
        fake_proc.stderr = fake_stderr
        fake_proc.pid = 9999
        fake_proc.returncode = None

        async def _proc_wait():
            # _terminate_process_group's asyncio.wait_for(proc.wait(),
            # timeout=10) will await this. Mark returncode so the second
            # await call (proc.wait() in the main path after the read
            # loop breaks) returns immediately.
            fake_proc.returncode = -15  # SIGTERM
            return -15

        fake_proc.wait = _proc_wait

        async def _fake_exec(*args, **kwargs):
            return fake_proc

        terminate_calls: list[str] = []

        async def _capture_terminate(reason: str):
            terminate_calls.append(reason)
            fake_proc.returncode = -15

        runner._terminate_process_group = _capture_terminate  # type: ignore[assignment]

        with patch(
            "bridge.claude_runner.asyncio.create_subprocess_exec",
            new=_fake_exec,
        ):
            result = await runner.invoke("hello", session_id=None)

        # The terminate-group helper was called exactly once with the
        # halt_flag reason (shared reason string for both policy-driven
        # and file-driven halt paths).
        assert terminate_calls == ["halt_flag"]
        # The subprocess.returncode is set — no zombie.
        assert fake_proc.returncode is not None
        # The read loop broke before consuming the EOF guard.
        assert line_count["n"] >= 10

    @pytest.mark.asyncio
    async def test_no_policy_wired_falls_back_to_halt_flag_file(
        self, sample_config, tmp_dirs
    ):
        # Back-compat regression: when no policy is wired and the
        # halt.flag file exists, the existing file-based check still
        # terminates the subprocess mid-stream. This is the legacy path.
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        # Do NOT call set_halt_policy.

        halt_flag = tmp_dirs["data_dir"] / "halt.flag"

        line_count = {"n": 0}

        async def _fake_readline():
            line_count["n"] += 1
            if line_count["n"] == 9:
                halt_flag.write_text("halt")
            if line_count["n"] > 25:
                return b""
            return b"PING\n"

        fake_stdin = MagicMock()
        fake_stdin.write = MagicMock()
        async def _drain():
            return None
        async def _wait_closed():
            return None
        fake_stdin.drain = _drain
        fake_stdin.close = MagicMock()
        fake_stdin.wait_closed = _wait_closed

        fake_stdout = MagicMock()
        fake_stdout.readline = _fake_readline

        fake_stderr = MagicMock()
        async def _read():
            return b""
        fake_stderr.read = _read

        fake_proc = MagicMock()
        fake_proc.stdin = fake_stdin
        fake_proc.stdout = fake_stdout
        fake_proc.stderr = fake_stderr
        fake_proc.pid = 9999
        fake_proc.returncode = None

        async def _proc_wait():
            fake_proc.returncode = -15
            return -15

        fake_proc.wait = _proc_wait

        async def _fake_exec(*args, **kwargs):
            return fake_proc

        terminate_calls: list[str] = []

        async def _capture_terminate(reason: str):
            terminate_calls.append(reason)
            fake_proc.returncode = -15

        runner._terminate_process_group = _capture_terminate  # type: ignore[assignment]

        with patch(
            "bridge.claude_runner.asyncio.create_subprocess_exec",
            new=_fake_exec,
        ):
            await runner.invoke("hello", session_id=None)

        assert terminate_calls == ["halt_flag"]

    @pytest.mark.asyncio
    async def test_halt_absent_no_termination(self, sample_config):
        # Regression guard: when neither policy nor file reports halt,
        # the read loop runs to EOF and _terminate_process_group is
        # never called.
        runner = ClaudeRunner(sample_config)
        runner._resolve_binary = lambda: "/usr/local/bin/claude"
        policy = _make_halt_policy(halted=False)
        runner.set_halt_policy(policy)

        line_count = {"n": 0}

        async def _fake_readline():
            line_count["n"] += 1
            if line_count["n"] > 5:
                return b""  # Natural EOF — no halt fires
            return b"PING\n"

        fake_stdin = MagicMock()
        fake_stdin.write = MagicMock()
        async def _drain():
            return None
        async def _wait_closed():
            return None
        fake_stdin.drain = _drain
        fake_stdin.close = MagicMock()
        fake_stdin.wait_closed = _wait_closed

        fake_stdout = MagicMock()
        fake_stdout.readline = _fake_readline

        fake_stderr = MagicMock()
        async def _read():
            return b""
        fake_stderr.read = _read

        fake_proc = MagicMock()
        fake_proc.stdin = fake_stdin
        fake_proc.stdout = fake_stdout
        fake_proc.stderr = fake_stderr
        fake_proc.pid = 9999
        fake_proc.returncode = 0

        async def _proc_wait():
            return 0

        fake_proc.wait = _proc_wait

        async def _fake_exec(*args, **kwargs):
            return fake_proc

        terminate_calls: list[str] = []

        async def _capture_terminate(reason: str):
            terminate_calls.append(reason)

        runner._terminate_process_group = _capture_terminate  # type: ignore[assignment]

        with patch(
            "bridge.claude_runner.asyncio.create_subprocess_exec",
            new=_fake_exec,
        ):
            await runner.invoke("hello", session_id=None)

        # Natural EOF — no halt fired.
        assert terminate_calls == []
