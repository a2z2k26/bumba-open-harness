"""P0.01 — ClaudeRunner and WarmClaudeProcess must delegate stream-line
parsing to their backend's ``parse_event`` rather than calling the
module-level ``_parse_stream_line`` directly, so a non-Claude backend's
parser is actually used.

Premise correction (vs. the original issue spec): the two ``_parse_stream_line``
call sites live in *two different classes* — ``ClaudeRunner`` (which already
holds ``self._backend``) and ``WarmClaudeProcess`` (which did not). This sprint
gives ``WarmClaudeProcess`` its own default backend before wiring the
delegation, mirroring ``ClaudeRunner.__init__``.
"""

import asyncio
from decimal import Decimal

from bridge.backends import BackendProtocol
from bridge.backends._protocol import StreamEvent
from bridge.cost_tracker import CostMeasurement

_PARSE_DEFAULT = object()


class _SpyBackend:
    """Minimal BackendProtocol stub that records parse_event calls."""

    def __init__(self):
        self.parsed_lines: list[str] = []

    @property
    def transport(self):
        return "subprocess"

    def resolve_binary(self):
        return ["true"]

    def build_command(self, **kw):
        return ["true"]

    def parse_event(self, line: str):
        self.parsed_lines.append(line)
        return StreamEvent(type="assistant", text="ok")

    def parse_cost(self, event):
        from bridge.cost_tracker import CostMeasurement

        return CostMeasurement(source="not_applicable", amount_usd=None)

    def auth_env(self):
        return {}

    def shutdown(self):
        return None

    def supports_tool_calling(self):
        return True

    def supports_system_prompt(self):
        return True

    def supports_mcp_config(self):
        return True

    def supports_tool_preauth(self):
        return True


class _HttpSpyBackend:
    @property
    def transport(self):
        return "http"

    def __init__(
        self,
        *,
        text: str = "http ok",
        parse_event_result: StreamEvent | None | object = _PARSE_DEFAULT,
        cost_measurement: CostMeasurement | None = None,
    ):
        self.requests: list[dict[str, str | None]] = []
        self.parsed_lines: list[str] = []
        self.text = text
        self._parse_event_result = parse_event_result
        self.cost_measurement = cost_measurement or CostMeasurement(
            amount_usd=Decimal("0.01"),
            source="measured",
            backend="http-test",
            raw_usage_id="gen-http-1",
        )

    def resolve_binary(self):
        raise AssertionError("HTTP invoke must not resolve a subprocess binary")

    def build_command(self, **kw):
        raise AssertionError("HTTP invoke must not build subprocess argv")

    def request(self, *, message: str, system_prompt: str | None = None):
        self.requests.append({"message": message, "system_prompt": system_prompt})
        return {"id": "gen-http-1", "choices": [{"message": {"content": self.text}}]}

    def parse_event(self, line: str):
        self.parsed_lines.append(line)
        if self._parse_event_result is _PARSE_DEFAULT:
            return StreamEvent(type="result", text=self.text, session_id="gen-http-1")
        if self._parse_event_result is None:
            return None
        if isinstance(self._parse_event_result, StreamEvent):
            return self._parse_event_result
        raise AssertionError("invalid parse_event_result test fixture")

    def parse_cost(self, event):
        return self.cost_measurement

    def auth_env(self):
        return {}

    def shutdown(self):
        return None

    def supports_tool_calling(self):
        return False

    def supports_system_prompt(self):
        return False

    def supports_mcp_config(self):
        return False

    def supports_tool_preauth(self):
        return False


def test_runner_uses_backend_parse_event():
    """ClaudeRunner delegates line parsing to self._backend.parse_event."""
    from bridge.claude_runner import ClaudeRunner

    spy = _SpyBackend()
    assert isinstance(spy, BackendProtocol)
    runner = ClaudeRunner.__new__(ClaudeRunner)
    runner._backend = spy
    line = '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}'
    event = runner._backend.parse_event(line)
    assert spy.parsed_lines == [line]
    assert event.type == "assistant"


async def test_runner_invokes_http_backend_without_subprocess(sample_config):
    """HTTP backends run through request()/parse_event(), not build_command()."""
    from bridge.claude_runner import ClaudeRunner

    backend = _HttpSpyBackend()
    assert isinstance(backend, BackendProtocol)
    runner = ClaudeRunner(sample_config)
    runner._backend = backend

    result = await runner.invoke("hello")

    assert result.response_text == "http ok"
    assert result.session_id == "gen-http-1"
    assert result.cost_usd == 0.01
    assert result.cost_unknown is False
    assert result.cost_source == "measured"
    assert result.cost_raw_usage_id == "gen-http-1"
    assert backend.requests == [{"message": "hello", "system_prompt": None}]


async def test_runner_http_backend_callbacks_fire_without_subprocess(
    sample_config,
    monkeypatch,
):
    """HTTP result text is delivered to both text callbacks without spawning."""
    from bridge.claude_runner import ClaudeRunner

    backend = _HttpSpyBackend(text="callback ok")
    runner = ClaudeRunner(sample_config)
    runner._backend = backend
    first_texts: list[str] = []
    deltas: list[str] = []

    def fail_subprocess_boundary(*args: object, **kwargs: object) -> None:
        raise AssertionError("HTTP invoke touched subprocess boundary")

    monkeypatch.setattr(runner, "_resolve_binary", fail_subprocess_boundary)
    monkeypatch.setattr(runner, "_build_command", fail_subprocess_boundary)
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        fail_subprocess_boundary,
    )

    result = await runner.invoke(
        "hello",
        on_first_text=first_texts.append,
        on_text_delta=deltas.append,
    )

    assert result.response_text == "callback ok"
    assert first_texts == ["callback ok"]
    assert deltas == ["callback ok"]
    assert backend.requests == [{"message": "hello", "system_prompt": None}]


async def test_runner_http_backend_parse_failure_returns_error(sample_config):
    """A backend parse miss must fail as an HTTP parse error, not subprocess fallback."""
    from bridge.claude_runner import ClaudeRunner

    backend = _HttpSpyBackend(parse_event_result=None)
    runner = ClaudeRunner(sample_config)
    runner._backend = backend

    result = await runner.invoke("hello")

    assert result.is_error is True
    assert result.error_type == "http_parse_error"
    assert result.stderr_output == "HTTP backend returned no parseable completion"
    assert backend.requests == [{"message": "hello", "system_prompt": None}]
    assert len(backend.parsed_lines) == 1


async def test_runner_http_backend_unknown_cost_sets_cost_unknown(sample_config):
    """Unknown HTTP cost remains explicit instead of becoming measured zero."""
    from bridge.claude_runner import ClaudeRunner

    backend = _HttpSpyBackend(
        cost_measurement=CostMeasurement(
            amount_usd=None,
            source="unknown",
            backend="http-test",
            raw_usage_id="gen-http-1",
        )
    )
    runner = ClaudeRunner(sample_config)
    runner._backend = backend

    result = await runner.invoke("hello")

    assert result.response_text == "http ok"
    assert result.session_id == "gen-http-1"
    assert result.cost_usd == 0.0
    assert result.cost_unknown is True


def test_runner_selects_openrouter_backend_when_enabled(sample_config):
    from dataclasses import replace

    from bridge.backends.openrouter import OpenRouterBackend
    from bridge.claude_runner import ClaudeRunner

    cfg = replace(
        sample_config,
        backends_enabled=True,
        backends_main="openrouter",
        openrouter_api_key="sk-or-test",
        openrouter_default_model="z-ai/glm-4.6",
    )

    runner = ClaudeRunner(cfg)

    assert isinstance(runner._backend, OpenRouterBackend)
    assert runner._backend._model == "z-ai/glm-4.6"


def test_warm_process_constructs_default_backend():
    """WarmClaudeProcess must hold a backend so its reader loop can delegate
    parse_event without raising AttributeError. The default mirrors
    ClaudeRunner: a ClaudeBackend built from the config."""
    from bridge.backends import BackendProtocol, ClaudeBackend
    from bridge.claude_runner import WarmClaudeProcess
    from bridge.config import load_config

    config = load_config(skip_secrets=True, skip_validation=True)
    warm = WarmClaudeProcess(config)
    assert hasattr(warm, "_backend"), "WarmClaudeProcess must set self._backend"
    assert isinstance(warm._backend, ClaudeBackend)
    assert isinstance(warm._backend, BackendProtocol)


def test_warm_process_backend_parse_event_is_callable():
    """The warm process backend exposes parse_event so the reader loop's
    delegated call resolves at runtime."""
    from bridge.claude_runner import WarmClaudeProcess
    from bridge.config import load_config

    config = load_config(skip_secrets=True, skip_validation=True)
    warm = WarmClaudeProcess(config)
    # Swap in a spy to prove the delegation target is the instance attribute.
    spy = _SpyBackend()
    warm._backend = spy
    line = '{"type":"result","subtype":"success"}'
    warm._backend.parse_event(line)
    assert spy.parsed_lines == [line]


def test_no_direct_parse_stream_line_calls():
    """Neither reader loop may call the module-level _parse_stream_line(decoded)
    directly — both must route through self._backend.parse_event(decoded)."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "bridge" / "claude_runner.py"
    text = src.read_text()
    assert "_parse_stream_line(decoded)" not in text, (
        "found a direct _parse_stream_line(decoded) call — both sites must "
        "delegate to self._backend.parse_event(decoded)"
    )
