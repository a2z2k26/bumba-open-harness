"""Direct tests for ``bridge.backends.codex.CodexBackend``.

Codex-2 (#1836): exercises the Codex CLI backend implementation in
isolation. Mirrors the structure of ``test_claude_backend.py`` — binary
resolution order, command-flag emission, NDJSON event parsing (Codex's
``thread.started``/``item.completed``/``turn.completed`` taxonomy from
discovery comment Q3), and the auth_env/shutdown trivial slots.

Subprocess invocation is fully mocked — no real ``codex`` binary required.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.backends import CodexBackend
from bridge.backends.codex import _parse_stream_line, _try_repair_json


# -- Binary resolution ----------------------------------------------------


class TestResolveBinary:
    """CodexBackend.resolve_binary — env → config → which → fallbacks (Q1)."""

    @pytest.fixture(autouse=True)
    def _clear_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BUMBA_CODEX_BINARY is checked first; clear it for the
        config/which/fallback branches."""
        monkeypatch.delenv("BUMBA_CODEX_BINARY", raising=False)

    def test_config_binary_used_when_set(self, sample_config) -> None:
        config = dataclasses.replace(sample_config, codex_binary="/custom/codex")
        backend = CodexBackend(config)
        assert backend.resolve_binary() == "/custom/codex"

    def test_which_used_when_no_config_binary(self, sample_config) -> None:
        config = dataclasses.replace(sample_config, codex_binary=None)
        backend = CodexBackend(config)
        with patch("bridge.backends.codex.shutil.which", return_value="/usr/bin/codex"):
            assert backend.resolve_binary() == "/usr/bin/codex"

    def test_fallback_homebrew_apple_silicon(self, sample_config) -> None:
        """Per discovery Q1: /opt/homebrew/bin/codex is the primary runtime path
        on Apple Silicon Homebrew installs."""
        config = dataclasses.replace(sample_config, codex_binary=None)
        backend = CodexBackend(config)

        def fake_is_file(p):
            return str(p) == "/opt/homebrew/bin/codex"

        with (
            patch("bridge.backends.codex.shutil.which", return_value=None),
            patch.object(Path, "is_file", autospec=True, side_effect=fake_is_file),
        ):
            assert backend.resolve_binary() == "/opt/homebrew/bin/codex"

    def test_fallback_usr_local_bin(self, sample_config) -> None:
        """Intel/legacy Homebrew + binary-download default path."""
        config = dataclasses.replace(sample_config, codex_binary=None)
        backend = CodexBackend(config)

        def fake_is_file(p):
            return str(p) == "/usr/local/bin/codex"

        with (
            patch("bridge.backends.codex.shutil.which", return_value=None),
            patch.object(Path, "is_file", autospec=True, side_effect=fake_is_file),
        ):
            assert backend.resolve_binary() == "/usr/local/bin/codex"

    def test_fallback_home_local_bin(self, sample_config, tmp_path) -> None:
        """Manual binary placement at ~/.local/bin/codex."""
        config = dataclasses.replace(sample_config, codex_binary=None)
        fake_binary = tmp_path / ".local" / "bin" / "codex"
        fake_binary.parent.mkdir(parents=True)
        fake_binary.touch()
        backend = CodexBackend(config)
        with (
            patch("bridge.backends.codex.shutil.which", return_value=None),
            patch("bridge.backends.codex.Path.home", return_value=tmp_path),
        ):
            binary = backend.resolve_binary()
        assert binary == str(fake_binary)

    def test_fallback_npm_global_bin(self, sample_config, tmp_path) -> None:
        """npm-global install path (~/.npm-global/bin/codex)."""
        config = dataclasses.replace(sample_config, codex_binary=None)
        fake_binary = tmp_path / ".npm-global" / "bin" / "codex"
        fake_binary.parent.mkdir(parents=True)
        fake_binary.touch()
        backend = CodexBackend(config)
        with (
            patch("bridge.backends.codex.shutil.which", return_value=None),
            patch("bridge.backends.codex.Path.home", return_value=tmp_path),
        ):
            binary = backend.resolve_binary()
        assert binary == str(fake_binary)

    def test_raises_when_not_found(self, sample_config) -> None:
        config = dataclasses.replace(sample_config, codex_binary=None)
        backend = CodexBackend(config)
        with (
            patch("bridge.backends.codex.shutil.which", return_value=None),
            patch.object(Path, "is_file", return_value=False),
        ):
            with pytest.raises(FileNotFoundError, match="Codex CLI binary not found"):
                backend.resolve_binary()

    def test_env_override_single_token(
        self, sample_config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUMBA_CODEX_BINARY beats config.codex_binary (test-harness override)."""
        config = dataclasses.replace(sample_config, codex_binary="/opt/homebrew/bin/codex")
        backend = CodexBackend(config)
        monkeypatch.setenv("BUMBA_CODEX_BINARY", "/tmp/shim-codex")
        assert backend.resolve_binary() == "/tmp/shim-codex"

    def test_env_override_multi_token(
        self, sample_config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multi-token override splits into argv list for shim invocations."""
        config = dataclasses.replace(sample_config, codex_binary="/opt/homebrew/bin/codex")
        backend = CodexBackend(config)
        monkeypatch.setenv("BUMBA_CODEX_BINARY", "/usr/bin/python3 /opt/fake_codex.py")
        result = backend.resolve_binary()
        assert result == ["/usr/bin/python3", "/opt/fake_codex.py"]

    def test_env_unset_falls_back_to_config(
        self, sample_config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = dataclasses.replace(sample_config, codex_binary="/opt/homebrew/bin/codex")
        backend = CodexBackend(config)
        monkeypatch.delenv("BUMBA_CODEX_BINARY", raising=False)
        assert backend.resolve_binary() == "/opt/homebrew/bin/codex"


# -- Command building -----------------------------------------------------


class TestBuildCommand:
    """CodexBackend.build_command — argv shape per discovery Q2 + Q3."""

    def _backend(self, sample_config) -> CodexBackend:
        return CodexBackend(sample_config)

    def test_basic_command_shape(self, sample_config) -> None:
        """Base: [binary, exec, --json, "<msg>"]."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="Hello", binary="/opt/homebrew/bin/codex")
        assert cmd[0] == "/opt/homebrew/bin/codex"
        assert cmd[1] == "exec"
        assert "--json" in cmd
        # Message is the LAST positional argument
        assert cmd[-1] == "Hello"

    def test_message_is_positional_not_stdin(self, sample_config) -> None:
        """Per Codex CLI: ``exec`` takes the prompt positionally, not stdin."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="say hi", binary="/opt/homebrew/bin/codex")
        # message IS in argv (unlike Claude which sends via stdin)
        assert "say hi" in cmd

    def test_resume_as_subcommand_not_flag(self, sample_config) -> None:
        """Per discovery Q2: session resume is `exec resume <sid>` subcommand,
        NOT a `--resume <sid>` flag."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", session_id="sess-123", binary="/opt/homebrew/bin/codex"
        )
        # `resume` appears as a positional subcommand
        assert "resume" in cmd
        idx = cmd.index("resume")
        assert cmd[idx + 1] == "sess-123"
        # No `--resume` flag
        assert "--resume" not in cmd

    def test_without_session_id_no_resume(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="Hi", binary="/opt/homebrew/bin/codex")
        assert "resume" not in cmd
        assert "--resume" not in cmd

    def test_empty_session_id_no_resume(self, sample_config) -> None:
        """Empty/None session_id MUST NOT trigger the resume subcommand."""
        backend = self._backend(sample_config)
        for sid in (None, ""):
            cmd = backend.build_command(
                message="Hi", session_id=sid, binary="/opt/homebrew/bin/codex"
            )
            assert "resume" not in cmd, f"session_id={sid!r} produced resume"

    def test_model_flag(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", model="gpt-5-codex", binary="/opt/homebrew/bin/codex"
        )
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "gpt-5-codex"

    def test_model_flag_absent_without_model(self, sample_config) -> None:
        backend = self._backend(sample_config)
        cmd = backend.build_command(message="Hi", binary="/opt/homebrew/bin/codex")
        assert "--model" not in cmd

    def test_mcp_config_path_is_noop(self, sample_config) -> None:
        """Per discovery Q4: Codex has no --mcp-config flag; the param is
        accepted for protocol parity but emits nothing to argv."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi",
            mcp_config_path="/tmp/mcp.json",
            binary="/opt/homebrew/bin/codex",
        )
        assert "--mcp-config" not in cmd
        assert "/tmp/mcp.json" not in cmd

    def test_system_prompt_file_is_noop(self, sample_config) -> None:
        """Codex's exec has no --instructions / equivalent; param accepted
        for protocol parity, no argv emitted."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi",
            system_prompt_file="/tmp/ctx.md",
            binary="/opt/homebrew/bin/codex",
        )
        assert "--instructions" not in cmd
        assert "--append-system-prompt-file" not in cmd
        assert "/tmp/ctx.md" not in cmd

    def test_permission_mode_is_noop(self, sample_config) -> None:
        """Codex's auto-approval flags differ; pre-1.0 we emit nothing."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", permission_mode="acceptEdits", binary="/opt/homebrew/bin/codex"
        )
        # No Claude-style flags leak through
        assert "--permission-mode" not in cmd
        assert "--dangerously-skip-permissions" not in cmd

    def test_combined_flags(self, sample_config) -> None:
        """All knobs together: argv shape stays sane, message is last."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="run analysis",
            session_id="thread-abc",
            model="gpt-5-codex",
            binary="/opt/homebrew/bin/codex",
        )
        assert cmd[0] == "/opt/homebrew/bin/codex"
        assert cmd[1] == "exec"
        assert "--json" in cmd
        assert "--model" in cmd
        assert "resume" in cmd
        assert "thread-abc" in cmd
        # Message is still the LAST positional arg
        assert cmd[-1] == "run analysis"

    def test_binary_as_list_flattened(self, sample_config) -> None:
        """When resolve_binary returns a multi-token list (shim invocation),
        cmd stays a flat argv list."""
        backend = self._backend(sample_config)
        cmd = backend.build_command(
            message="Hi", binary=["/usr/bin/python3", "/opt/fake_codex.py"]
        )
        assert cmd[0] == "/usr/bin/python3"
        assert cmd[1] == "/opt/fake_codex.py"
        assert cmd[2] == "exec"

    def test_binary_resolved_internally_when_none(self, sample_config) -> None:
        """Without explicit binary, build_command calls resolve_binary itself."""
        config = dataclasses.replace(sample_config, codex_binary="/auto/codex")
        backend = CodexBackend(config)
        cmd = backend.build_command(message="Hi")
        assert cmd[0] == "/auto/codex"


# -- Stream parsing -------------------------------------------------------


class TestParseEvent:
    """CodexBackend.parse_event + module-level _parse_stream_line — Codex's
    NDJSON event taxonomy per discovery Q3."""

    def test_parse_thread_started(self) -> None:
        """`thread.started` → StreamEvent(type=system, subtype=init,
        session_id=<thread_id>)."""
        line = json.dumps(
            {"type": "thread.started", "thread_id": "0199a213-81c0-7800-8aa1-bbab2a035a53"}
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "system"
        assert ev.subtype == "init"
        assert ev.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a53"

    def test_parse_turn_started_returns_none(self) -> None:
        """`turn.started` is suppressed (noise reduction parity with Claude)."""
        line = json.dumps({"type": "turn.started"})
        assert _parse_stream_line(line) is None

    def test_parse_item_completed_agent_message(self) -> None:
        """`item.completed` + `item.type==agent_message` → assistant text."""
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_3", "type": "agent_message", "text": "Hello!"},
            }
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "assistant"
        assert ev.text == "Hello!"

    def test_parse_item_completed_command_execution(self) -> None:
        """`item.completed` + `item.type==command_execution` → tool_use[bash]."""
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "command_execution",
                    "command": "bash -lc ls",
                    "status": "completed",
                },
            }
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "tool_use"
        assert ev.tool_name == "bash"

    def test_parse_item_completed_file_change(self) -> None:
        """`item.completed` + `item.type==file_change` → tool_use[edit]."""
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_2", "type": "file_change", "path": "/tmp/foo.py"},
            }
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "tool_use"
        assert ev.tool_name == "edit"

    def test_parse_item_completed_mcp_tool_call(self) -> None:
        """`item.completed` + `item.type==mcp_tool_call` → tool_use[<server>]."""
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_4",
                    "type": "mcp_tool_call",
                    "server": "notion",
                    "tool": "search",
                },
            }
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "tool_use"
        assert ev.tool_name == "notion"

    def test_parse_item_completed_reasoning_returns_none(self) -> None:
        """`reasoning` items are not surfaced (parity with Claude)."""
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "reasoning", "text": "Thinking..."},
            }
        )
        assert _parse_stream_line(line) is None

    def test_parse_turn_completed(self) -> None:
        """`turn.completed` → result with subtype=success, num_turns=1.

        E.04 (#2011): the parser previously emitted ``cost_usd=0.0`` here.
        That value was indistinguishable from a real $0 result and silently
        corrupted any aggregation that summed it. Now the parser emits
        ``cost_usd=None`` + ``cost_unknown=True`` as a fail-loud marker
        until Codex-6 (#1840) wires the per-token pricing model. PR body
        documents this assertion change.
        """
        line = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 24763,
                    "cached_input_tokens": 24448,
                    "output_tokens": 122,
                    "reasoning_output_tokens": 0,
                },
            }
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "result"
        assert ev.subtype == "success"
        assert ev.is_error is False
        assert ev.num_turns == 1
        # E.04 (#2011): fail-loud cost-unknown signal replaces the old 0.0.
        assert ev.cost_usd is None
        assert ev.cost_unknown is True

    def test_parse_turn_failed(self) -> None:
        line = json.dumps({"type": "turn.failed", "message": "context length exceeded"})
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "result"
        assert ev.subtype == "error_during_execution"
        assert ev.is_error is True
        assert "context length exceeded" in ev.text

    def test_parse_error_event(self) -> None:
        line = json.dumps({"type": "error", "error": "rate limited"})
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "result"
        assert ev.subtype == "error_during_execution"
        assert ev.is_error is True
        assert "rate limited" in ev.text

    def test_parse_empty_line_returns_none(self) -> None:
        assert _parse_stream_line("") is None
        assert _parse_stream_line("   \n") is None

    def test_parse_invalid_json_unrepairable_returns_none(self) -> None:
        assert _parse_stream_line("not json at all $$$$") is None

    def test_parse_unknown_event_type_returns_none(self) -> None:
        """Unknown top-level event types log debug and drop."""
        line = json.dumps({"type": "plan.updated", "plan": []})
        assert _parse_stream_line(line) is None

    def test_parse_unknown_item_type_returns_none(self) -> None:
        """Unknown nested item.type values log debug and drop."""
        line = json.dumps(
            {"type": "item.completed", "item": {"type": "web_search", "query": "foo"}}
        )
        assert _parse_stream_line(line) is None

    def test_parse_item_completed_missing_item_returns_none(self) -> None:
        """item.completed with no `item` payload (or malformed payload)
        returns None without raising."""
        line = json.dumps({"type": "item.completed", "item": "not-a-dict"})
        assert _parse_stream_line(line) is None

    def test_backend_parse_event_delegates(self, sample_config) -> None:
        """CodexBackend.parse_event delegates to the module-level helper."""
        backend = CodexBackend(sample_config)
        line = json.dumps({"type": "thread.started", "thread_id": "abc"})
        ev_backend = backend.parse_event(line)
        ev_module = _parse_stream_line(line)
        assert ev_backend is not None and ev_module is not None
        assert ev_backend.session_id == ev_module.session_id == "abc"


class TestRepairJson:
    """_try_repair_json strategies for malformed Codex output."""

    def test_extract_from_surrounding_garbage(self) -> None:
        line = 'log noise {"type": "thread.started", "thread_id": "x"} more noise'
        result = _try_repair_json(line)
        assert result is not None
        assert result["type"] == "thread.started"

    def test_strip_trailing_commas(self) -> None:
        line = '{"type": "thread.started", "thread_id": "x",}'
        result = _try_repair_json(line)
        assert result is not None
        assert result["type"] == "thread.started"

    def test_unrepairable_returns_none(self) -> None:
        assert _try_repair_json("not json at all $$$$") is None

    def test_repair_path_used_when_initial_parse_fails(self) -> None:
        """Malformed-but-repairable JSON round-trips through parse_event."""
        line = '{"type": "thread.started", "thread_id": "x",}'  # trailing comma
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "system"
        assert ev.session_id == "x"


# -- Auth env + shutdown --------------------------------------------------


class TestAuthEnvAndShutdown:
    """Codex auth flows through ~/.codex/auth.json (Codex-4), so auth_env
    returns empty. shutdown is a no-op."""

    def test_auth_env_returns_empty(self, sample_config) -> None:
        """Per Codex-4 amendment: ~/.codex/auth.json is the auth surface;
        no subprocess env-var injection is needed."""
        backend = CodexBackend(sample_config)
        assert backend.auth_env() == {}

    def test_shutdown_is_idempotent_noop(self, sample_config) -> None:
        backend = CodexBackend(sample_config)
        assert backend.shutdown() is None
        assert backend.shutdown() is None


# -- Constructor smoke ----------------------------------------------------


class TestConstructor:
    """CodexBackend constructs cleanly from a real BridgeConfig."""

    def test_construct_with_sample_config(self, sample_config) -> None:
        backend = CodexBackend(sample_config)
        assert backend.config is sample_config

    def test_satisfies_backend_protocol(self, sample_config) -> None:
        """Structural check: CodexBackend quacks like BackendProtocol."""
        from bridge.backends import BackendProtocol

        backend = CodexBackend(sample_config)
        assert isinstance(backend, BackendProtocol)


# -- E.04 (#2011) — fail-loud cost guard ----------------------------------


class TestCostUnknownFailLoud:
    """E.04 (#2011) — the parser must not silently report ``cost_usd=0.0``.

    Two layers of fail-loud:

    1. ``turn.completed`` emits ``cost_usd=None`` + ``cost_unknown=True`` so
       any aggregator that sums cost without gating on ``cost_unknown``
       explodes loudly instead of silently corrupting totals.
    2. ``readiness_for_flip`` refuses to flip ``backends_enabled=True``
       while Codex is in the active backend set and
       ``codex_cost_computable()`` returns False.
    """

    def test_turn_completed_does_not_report_zero_cost(self) -> None:
        """The audit's load-bearing assertion: ``turn.completed`` must NOT
        emit ``cost_usd=0.0``. It MUST emit ``cost_usd=None`` and
        ``cost_unknown=True`` so downstream consumers can branch on the
        explicit unknown signal rather than treating ``0.0`` as a real $0
        spend.
        """
        line = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cached_input_tokens": 0,
                    "reasoning_output_tokens": 0,
                },
            }
        )
        ev = _parse_stream_line(line)
        assert ev is not None
        assert ev.type == "result"
        assert ev.subtype == "success"
        # Fail-loud markers — both must be set together.
        assert ev.cost_usd is None, (
            "Codex parser regression: turn.completed reported cost_usd=0.0 "
            "again. Per audit E.04 (#2011) this site MUST emit cost_usd=None "
            "+ cost_unknown=True until Codex-6 (#1840) wires real pricing."
        )
        assert ev.cost_unknown is True, (
            "Codex parser regression: turn.completed did not set "
            "cost_unknown=True (the fail-loud companion to cost_usd=None)."
        )

    def test_readiness_for_flip_refuses_when_codex_cost_unknown(self) -> None:
        """``readiness_for_flip`` MUST refuse a ``backends_enabled=True``
        flip while ``codex`` is in the active backend set and
        ``codex_cost_computable()`` returns False. The block reason MUST
        name the missing pricing model so the operator gets a one-line
        explanation in the surfaced error.
        """
        from bridge.backends import codex_cost_computable, readiness_for_flip

        # Sanity: until Codex-6 (#1840) wires pricing, this MUST stay False.
        assert codex_cost_computable() is False

        ready, reason = readiness_for_flip(
            backends_enabled=True,
            active_backends=["codex"],
        )
        assert ready is False
        # Reason must mention the missing pricing model surface so operator
        # tooling can surface a one-line block message.
        lower = reason.lower()
        assert "codex" in lower
        assert "pricing" in lower or "cost_computable" in lower
        # Audit issue number surfaced in the block message helps the operator
        # pivot straight to the remediation tracker.
        assert "#2011" in reason or "e.04" in lower

    def test_readiness_for_flip_passes_when_codex_not_active(self) -> None:
        """When ``codex`` is NOT in the active backend set, the guard MUST
        pass even with ``backends_enabled=True`` — the audit gates Codex
        specifically, not the flip itself."""
        from bridge.backends import readiness_for_flip

        ready, reason = readiness_for_flip(
            backends_enabled=True,
            active_backends=["claude"],
        )
        assert ready is True
        assert reason == ""

    def test_readiness_for_flip_passes_when_flip_disabled(self) -> None:
        """When ``backends_enabled=False``, no flip is being attempted and
        the guard MUST pass regardless of which backends are listed."""
        from bridge.backends import readiness_for_flip

        ready, reason = readiness_for_flip(
            backends_enabled=False,
            active_backends=["codex"],
        )
        assert ready is True
        assert reason == ""


# -- audit-2026-05-16.D.02 (HI-2, #2063) — typed cost-measurement parser ---


class TestParseCostCodex:
    """``CodexBackend.parse_cost`` — typed four-state cost contract.

    HI-2 (#2063): the legacy float-extraction site collapsed "Codex did not
    report a cost" into ``0.0``, indistinguishable from a measured zero.
    The typed return surfaces ``source='unknown'`` so downstream budget
    gates can branch on the explicit state.
    """

    def test_codex_parser_returns_cost_measurement_measured(
        self, sample_config
    ) -> None:
        """Usage event with a numeric ``cost_usd`` returns ``source='measured'``
        with the Decimal amount populated.

        Models the post-Codex-6 (#1840) future where per-token pricing is
        wired and ``turn.completed`` carries a real cost float. Today this
        path is dormant on the wire but the parser MUST honor it the
        moment Codex starts emitting the field.
        """
        from decimal import Decimal

        from bridge.cost_tracker import CostMeasurement

        backend = CodexBackend(sample_config)
        event = {
            "type": "turn.completed",
            "thread_id": "thread-abc-123",
            "cost_usd": 0.0042,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
            },
        }
        m = backend.parse_cost(event)
        assert isinstance(m, CostMeasurement)
        assert m.source == "measured"
        # ``Decimal(str(float))`` round-trip — no binary-float widening.
        assert m.amount_usd == Decimal("0.0042")
        assert m.backend == "codex"
        assert m.raw_usage_id == "thread-abc-123"

    def test_codex_parser_returns_unknown_when_cost_field_missing(
        self, sample_config
    ) -> None:
        """Event without ``cost_usd`` returns ``source='unknown'``,
        ``amount_usd=None``. **NOT zero.**

        This is the load-bearing HI-2 assertion. Today's Codex stream
        emits ``turn.completed`` with token usage but no dollar amount;
        the legacy path silently produced ``0.0`` here and corrupted
        any aggregator that summed it. The typed return forces
        downstream code to branch on ``source`` instead.
        """
        from bridge.cost_tracker import CostMeasurement

        backend = CodexBackend(sample_config)
        # Real-world Codex turn.completed shape (per discovery Q3): usage
        # tokens are present but cost_usd is absent until Codex-6 wires
        # the pricing model.
        event = {
            "type": "turn.completed",
            "thread_id": "thread-xyz-789",
            "usage": {
                "input_tokens": 24763,
                "cached_input_tokens": 24448,
                "output_tokens": 122,
                "reasoning_output_tokens": 0,
            },
        }
        m = backend.parse_cost(event)
        assert isinstance(m, CostMeasurement)
        # HI-2: must be source='unknown', NOT 'measured'+0.0.
        assert m.source == "unknown", (
            "Codex parse_cost regression: missing cost_usd collapsed into "
            "a measured zero again. Per audit HI-2 (#2063) this MUST emit "
            "source='unknown' so downstream budget gates can branch on "
            "the explicit unknown state."
        )
        assert m.amount_usd is None, (
            "Codex parse_cost regression: unknown cost reported a numeric "
            "amount instead of None. The four-state contract requires "
            "amount_usd=None whenever source != 'measured'/'estimated'."
        )
        assert m.backend == "codex"
        assert m.raw_usage_id == "thread-xyz-789"

    def test_codex_parser_unknown_equality_distinguishes_from_measured_zero(
        self, sample_config
    ) -> None:
        """The SW-3 / HI-2 invariant: ``unknown`` (None) is NEVER equal
        to a measured ``Decimal('0')``. The legacy float-collapse made
        these states indistinguishable; the typed contract surfaces
        the difference at the equality boundary.
        """
        from decimal import Decimal

        backend = CodexBackend(sample_config)
        unknown = backend.parse_cost({"type": "turn.completed"})
        measured_zero = backend.parse_cost(
            {"type": "turn.completed", "cost_usd": 0.0}
        )
        assert unknown != measured_zero
        assert unknown.source == "unknown"
        assert unknown.amount_usd is None
        assert measured_zero.source == "measured"
        assert measured_zero.amount_usd == Decimal("0.0")


class TestActiveBackendParserRejectsForeignEvent:
    """audit-2026-05-16.D.02 (HI-2, #2063) — cross-backend isolation.

    The legacy code path routed Codex stream events through Claude's
    parser, which read ``cost_usd`` and silently defaulted to ``0.0``
    when the field was absent. ``parse_cost`` is now backend-specific:
    routing a Claude event through Codex's parser (or vice versa)
    must return ``source='not_applicable'``, NOT a fabricated zero.
    """

    def test_codex_parser_rejects_claude_result_event(self, sample_config) -> None:
        """A Claude ``result`` event sent to Codex's parser returns
        ``source='not_applicable'`` — Codex's only cost-bearing event
        is ``turn.completed``; ``result`` is foreign-backend shape.
        """
        from bridge.cost_tracker import CostMeasurement

        backend = CodexBackend(sample_config)
        # Claude's result-event shape with a real cost.
        claude_event = {
            "type": "result",
            "subtype": "success",
            "session_id": "sess-1",
            "cost_usd": 0.0123,
            "num_turns": 2,
            "is_error": False,
        }
        m = backend.parse_cost(claude_event)
        assert isinstance(m, CostMeasurement)
        assert m.source == "not_applicable", (
            "Codex parse_cost mis-handled a foreign Claude result event "
            "as measured — would silently double-count cross-backend "
            "events. Per HI-2 (#2063) foreign events must surface as "
            "'not_applicable' so the active backend's parser is the "
            "single source of truth for its own events."
        )
        assert m.amount_usd is None
        assert m.backend == "codex"

    def test_codex_parser_returns_not_applicable_for_codex_non_cost_events(
        self, sample_config
    ) -> None:
        """Codex's own non-cost-bearing events (``thread.started``,
        ``item.completed``, ``turn.failed``, ``error``) return
        ``source='not_applicable'`` — they aren't cost-bearing on
        Codex's own taxonomy, so coercing them to unknown would
        over-report unknowns.
        """
        from bridge.cost_tracker import CostMeasurement

        backend = CodexBackend(sample_config)
        for event in (
            {"type": "thread.started", "thread_id": "abc"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}},
            {"type": "turn.failed", "message": "context limit"},
            {"type": "error", "error": "rate limited"},
        ):
            m = backend.parse_cost(event)
            assert isinstance(m, CostMeasurement)
            assert m.source == "not_applicable", (
                f"Codex non-cost event {event['type']!r} should be "
                f"not_applicable; got source={m.source!r}"
            )
            assert m.amount_usd is None
            assert m.backend == "codex"
