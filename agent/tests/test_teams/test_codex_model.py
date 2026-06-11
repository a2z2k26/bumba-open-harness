"""Unit tests for ``teams._codex_model.CodexExecModel`` (Z4-17a, #2566).

Covers the three load-bearing pieces of the codex-exec adapter without
needing a real codex install:

    - ``_flatten_messages`` — pydantic-ai message list → single prompt string.
    - ``_usage_from_turn_completed`` — codex usage block → ``RequestUsage``.
    - ``CodexExecModel.request`` — full subprocess turn via a fake codex shim
      pointed at by ``BUMBA_CODEX_BINARY``.

The fake shim emits the codex NDJSON taxonomy (``thread.started`` →
``item.completed``/``agent_message`` → ``turn.completed``) so the parser path
is exercised end-to-end. No network, no real binary.
"""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.usage import RequestUsage

from teams._codex_model import (
    CodexExecModel,
    CodexExecModelError,
    _flatten_messages,
    _usage_from_turn_completed,
)


# -- _flatten_messages --

def test_flatten_messages_orders_system_then_user() -> None:
    messages = [
        ModelRequest(
            parts=[
                SystemPromptPart(content="You are a specialist."),
                UserPromptPart(content="Do the task."),
            ]
        )
    ]
    prompt = _flatten_messages(messages)
    assert "SYSTEM:\nYou are a specialist." in prompt
    assert "USER:\nDo the task." in prompt
    assert prompt.index("SYSTEM:") < prompt.index("USER:")


def test_flatten_messages_skips_empty_and_response_messages() -> None:
    messages = [
        ModelRequest(parts=[SystemPromptPart(content="   ")]),
        ModelResponse(parts=[TextPart(content="prior assistant turn")]),
        ModelRequest(parts=[UserPromptPart(content="real task")]),
    ]
    prompt = _flatten_messages(messages)
    assert prompt == "USER:\nreal task"
    assert "prior assistant turn" not in prompt


def test_flatten_messages_handles_sequence_user_content() -> None:
    messages = [
        ModelRequest(parts=[UserPromptPart(content=["alpha", "beta"])]),
    ]
    prompt = _flatten_messages(messages)
    assert "alpha" in prompt
    assert "beta" in prompt


# -- _usage_from_turn_completed --

def test_usage_from_turn_completed_maps_token_fields() -> None:
    raw = {
        "type": "turn.completed",
        "usage": {
            "input_tokens": 24763,
            "cached_input_tokens": 24448,
            "output_tokens": 122,
            "reasoning_output_tokens": 8,
        },
    }
    usage = _usage_from_turn_completed(raw)
    assert usage.input_tokens == 24763
    assert usage.cache_read_tokens == 24448
    # output + reasoning collapse into output_tokens.
    assert usage.output_tokens == 130


def test_usage_from_turn_completed_missing_usage_is_zeroed() -> None:
    usage = _usage_from_turn_completed({"type": "turn.completed"})
    assert usage == RequestUsage()


# -- CodexExecModel construction --

def test_model_name_and_system() -> None:
    model = CodexExecModel("gpt-5-codex")
    assert model.model_name == "gpt-5-codex"
    assert model.system == "codex-exec"


def test_empty_model_name_falls_back_to_default_label() -> None:
    model = CodexExecModel("")
    assert model.model_name == "codex-exec-default"


# -- CodexExecModel.request via a fake codex shim --

def _write_fake_codex(tmp_path: Path, ndjson_lines: list[str], exit_code: int = 0) -> str:
    """Write an executable python shim that prints NDJSON and exits.

    Returns a ``"<python> <script>"`` string suitable for ``BUMBA_CODEX_BINARY``
    (the multi-token override form ``resolve_binary`` splits on whitespace).
    """
    payload = "\n".join(ndjson_lines)
    script = tmp_path / "fake_codex.py"
    script.write_text(
        "import sys\n"
        f"sys.stdout.write({payload!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return f"{sys.executable} {script}"


@pytest.mark.asyncio
async def test_request_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t-123"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Hello from codex."},
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 0,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 0,
                },
            }
        ),
    ]
    monkeypatch.setenv("BUMBA_CODEX_BINARY", _write_fake_codex(tmp_path, lines))
    model = CodexExecModel("gpt-5-codex")
    messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]

    response = await model.request(messages, None, ModelRequestParameters())

    assert isinstance(response, ModelResponse)
    assert len(response.parts) == 1
    assert isinstance(response.parts[0], TextPart)
    assert response.parts[0].content == "Hello from codex."
    assert response.usage.input_tokens == 100
    assert response.usage.output_tokens == 20
    assert response.model_name == "gpt-5-codex"


@pytest.mark.asyncio
async def test_request_raises_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "BUMBA_CODEX_BINARY", _write_fake_codex(tmp_path, [""], exit_code=3)
    )
    model = CodexExecModel("gpt-5-codex")
    messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    with pytest.raises(CodexExecModelError, match="exited 3"):
        await model.request(messages, None, ModelRequestParameters())


@pytest.mark.asyncio
async def test_request_raises_on_error_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t-1"}),
        json.dumps({"type": "turn.failed", "message": "model unavailable"}),
    ]
    monkeypatch.setenv("BUMBA_CODEX_BINARY", _write_fake_codex(tmp_path, lines))
    model = CodexExecModel("gpt-5-codex")
    messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    with pytest.raises(CodexExecModelError, match="model unavailable"):
        await model.request(messages, None, ModelRequestParameters())


@pytest.mark.asyncio
async def test_request_times_out_and_kills_hung_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung codex subprocess must not block the specialist indefinitely
    (audit-2026-06-11): the request times out, the child is killed, and a
    typed CodexExecModelError surfaces."""
    script = tmp_path / "hung_codex.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("BUMBA_CODEX_BINARY", f"{sys.executable} {script}")
    model = CodexExecModel("gpt-5-codex", timeout_seconds=0.2)
    messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    with pytest.raises(CodexExecModelError, match="timed out"):
        await model.request(messages, None, ModelRequestParameters())


@pytest.mark.asyncio
async def test_request_raises_when_no_assistant_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t-1"}),
        json.dumps({"type": "turn.completed", "usage": {}}),
    ]
    monkeypatch.setenv("BUMBA_CODEX_BINARY", _write_fake_codex(tmp_path, lines))
    model = CodexExecModel("gpt-5-codex")
    messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    with pytest.raises(CodexExecModelError, match="no assistant text"):
        await model.request(messages, None, ModelRequestParameters())
