"""CodexExecModel — a pydantic-ai ``Model`` that shells out to ``codex exec``.

Z4-17a (#2566): the Zone 4 teams factory (``teams._factory._resolve_model``)
returns a pydantic-ai ``Model`` for every department specialist. The
``openrouter:`` / ``openai:`` branches return ``OpenAIChatModel`` — an HTTP
model. Codex is **not** an HTTP endpoint: it is a local CLI subprocess
(``codex exec --json``). There is no off-the-shelf pydantic-ai ``Model`` for
"shell out to a local CLI", so this module supplies one.

Design (Option A from the #2566 plan): a thin ``Model`` subclass that reuses
the already-built + tested pieces of ``bridge.backends.codex.CodexBackend``:

    - ``resolve_binary()`` — locate the codex binary (BUMBA_CODEX_BINARY
      override honoured for tests).
    - ``build_command(...)`` — assemble ``codex exec --json [--model X]
      "<prompt>"``.
    - ``bridge.backends.codex._parse_stream_line`` — NDJSON → ``StreamEvent``.

The crux is message-flattening. ``codex exec`` takes ONE positional prompt
string, whereas pydantic-ai hands the model a ``list[ModelMessage]``
(interleaved system / user / tool messages). ``_flatten_messages`` concatenates
the textual content of every request part into a single prompt, role-labelled
so codex sees the system framing followed by the user turn. This is a
deliberate simplification — see ``_flatten_messages`` for the assumption.

Out of scope (operator-gated, per the #2566 plan): live-smoke against a real
authenticated codex binary, and per-department YAML migration off
``openrouter:``. This module only makes ``codex-exec:*`` *constructable*.

Streaming (``request_stream``) is intentionally NOT implemented: the base
``Model.request_stream`` already raises ``NotImplementedError`` with a clear
message, and the Zone 4 teams path drives agents through the non-streaming
``request`` surface. If streaming is needed later, wire codex's NDJSON
``item.completed``/``agent_message`` deltas into a ``StreamedResponse``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from bridge.backends.codex import CodexBackend, _parse_stream_line

if TYPE_CHECKING:
    from bridge.config import BridgeConfig

log = logging.getLogger(__name__)

_CODEX_SYSTEM = "codex-exec"


class CodexExecModelError(RuntimeError):
    """Raised when a ``codex exec`` subprocess turn fails to produce a result."""


def _stringify_user_content(content: object) -> str:
    """Best-effort flatten of a ``UserPromptPart.content`` into text.

    ``content`` is ``str | Sequence[UserContent]`` in pydantic-ai. For the
    teams path the content is overwhelmingly a plain string (the chief's
    delegated task text). When it is a sequence we keep only the string-like
    items and drop binary/file content — codex's positional prompt is text
    only, and surfacing a partial prompt is safer than crashing the turn.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "\n".join(str(item) for item in content if isinstance(item, str))
    return str(content)


def _flatten_messages(messages: list[ModelMessage]) -> str:
    """Flatten a pydantic-ai message list into a single codex prompt string.

    ASSUMPTION (surfaced for review): ``codex exec`` takes exactly one
    positional prompt argument, so the structured message list must collapse
    to one string. We concatenate the textual content of every ``ModelRequest``
    part — system parts first (role-labelled ``SYSTEM:``) then user parts
    (role-labelled ``USER:``) in the order they appear — joined by blank lines.
    ``ModelResponse`` history and tool parts are NOT replayed into the prompt:
    codex is invoked stateless per turn here (session resume is a backend
    concern not yet plumbed through the teams path), so prior assistant turns
    are out of scope for the flattened prompt. This favours simplicity over
    full conversation fidelity; the teams path issues a single delegated task
    per agent run, so multi-turn replay is not exercised today.
    """
    segments: list[str] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, SystemPromptPart):
                text = part.content.strip()
                if text:
                    segments.append(f"SYSTEM:\n{text}")
            elif isinstance(part, UserPromptPart):
                text = _stringify_user_content(part.content).strip()
                if text:
                    segments.append(f"USER:\n{text}")
    return "\n\n".join(segments)


def _usage_from_turn_completed(raw: dict) -> RequestUsage:
    """Extract token usage from a codex ``turn.completed`` event payload.

    Codex's ``usage`` block carries ``input_tokens``, ``cached_input_tokens``,
    ``output_tokens``, ``reasoning_output_tokens`` (verified shape, see
    ``tests/test_codex_backend.py::test_parse_turn_completed``). We map:

        - ``input_tokens``           → ``RequestUsage.input_tokens``
        - ``cached_input_tokens``    → ``RequestUsage.cache_read_tokens``
        - ``output_tokens`` +        → ``RequestUsage.output_tokens``
          ``reasoning_output_tokens``

    Missing/absent fields default to 0 — the teams cost layer estimates from
    ``total_tokens`` and tolerates undercounting (it never crashes on zero).
    """
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return RequestUsage()
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    cached = int(usage.get("cached_input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    reasoning = int(usage.get("reasoning_output_tokens", 0) or 0)
    return RequestUsage(
        input_tokens=input_tokens,
        cache_read_tokens=cached,
        output_tokens=output_tokens + reasoning,
    )


class CodexExecModel(Model):
    """pydantic-ai ``Model`` backed by the ``codex exec --json`` CLI.

    Constructed by ``teams._factory._resolve_codex_model`` for any specialist
    whose ``model:`` starts with ``codex-exec:``. The model name passed to
    codex is the substring after the prefix (e.g. ``codex-exec:gpt-5-codex``
    → ``gpt-5-codex``); an empty model name lets codex pick its default.

    Only the non-streaming ``request`` surface is implemented — see the module
    docstring for why streaming is deferred.
    """

    # Matches the Constraints.timeout_seconds default (teams/_types.py) so a
    # hung codex child can never outlive the team-level run budget by much.
    DEFAULT_TIMEOUT_SECONDS: float = 600.0

    def __init__(
        self,
        model_name: str,
        *,
        config: BridgeConfig | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._backend = CodexBackend(config) if config is not None else CodexBackend(_load_config_best_effort())

    @property
    def model_name(self) -> str:
        return self._model_name or "codex-exec-default"

    @property
    def system(self) -> str:
        return _CODEX_SYSTEM

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Run one ``codex exec`` turn and return a ``ModelResponse``.

        Flattens ``messages`` to a single prompt, builds the codex argv via
        ``CodexBackend.build_command``, runs the subprocess, parses NDJSON
        stdout line-by-line, accumulates assistant text, and extracts token
        usage from the ``turn.completed`` event. Raises ``CodexExecModelError``
        if codex reports an error event or produces no assistant text.
        """
        prompt = _flatten_messages(messages)
        model_arg = self._model_name or None
        cmd = self._backend.build_command(message=prompt, model=model_arg)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout_seconds
            )
        except TimeoutError:
            # audit-2026-06-11: cancelling communicate() does NOT kill the
            # child — without this, a hung codex process leaks past the
            # team-level run timeout. Kill, reap, surface a typed error.
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            raise CodexExecModelError(
                f"codex exec timed out after {self._timeout_seconds:.0f}s"
            ) from None
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            raise CodexExecModelError(
                f"codex exec exited {proc.returncode}: {stderr.strip()[:500]}"
            )

        text_segments: list[str] = []
        usage = RequestUsage()
        error_text: str | None = None

        for line in stdout.splitlines():
            event = _parse_stream_line(line)
            if event is None:
                continue
            if event.type == "assistant" and event.text:
                text_segments.append(event.text)
            elif event.type == "result":
                if event.is_error:
                    error_text = event.text or "codex reported an error event"
                else:
                    # turn.completed carries usage; re-parse the raw line to
                    # reach the token block the StreamEvent does not expose.
                    usage = _extract_usage_from_line(line)

        if error_text is not None:
            raise CodexExecModelError(f"codex exec error: {error_text[:500]}")

        text = "\n".join(text_segments).strip()
        if not text:
            raise CodexExecModelError(
                "codex exec produced no assistant text "
                f"(stderr: {stderr.strip()[:300]})"
            )

        return ModelResponse(
            parts=[TextPart(content=text)],
            usage=usage,
            model_name=self.model_name,
        )


def _extract_usage_from_line(line: str) -> RequestUsage:
    """Parse a raw NDJSON line as a ``turn.completed`` usage block.

    ``_parse_stream_line`` deliberately drops the usage payload (it surfaces
    ``cost_unknown`` instead), so the model re-parses the raw line to recover
    token counts for pydantic-ai's run-level usage aggregation. Malformed JSON
    yields empty usage rather than raising — usage is best-effort telemetry.
    """
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return RequestUsage()
    if not isinstance(raw, dict) or raw.get("type") != "turn.completed":
        return RequestUsage()
    return _usage_from_turn_completed(raw)


def _load_config_best_effort() -> BridgeConfig:
    """Load ``BridgeConfig`` for the backend without secrets/validation.

    ``CodexBackend`` only reads ``config.codex_binary`` (binary resolution),
    so a CLI/teams-context config (no secret loading, no validation) is
    sufficient. Mirrors the lightweight-config pattern used elsewhere in the
    teams factory. Falls back to a default-constructed config if the
    skip-flags signature is unavailable.
    """
    from bridge.config import load_config

    try:
        return load_config(skip_secrets=True, skip_validation=True)
    except TypeError:
        return load_config()
