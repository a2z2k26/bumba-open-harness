"""OpenAI-compatible SSE adapter for VAPI voice receptionists.

Translates between OpenAI chat completion format (what VAPI expects) and
the Pydantic AI output of a department manager.

ONE receptionist per department. NOT on the orchestrator. NOT on managers directly.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

log = logging.getLogger(__name__)


def parse_openai_request(body: dict[str, Any]) -> str:
    """Extract the most recent user message from an OpenAI-format chat request."""
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise ValueError("Request missing 'messages' array")

    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content", ""))

    raise ValueError("No user message found")


async def to_openai_sse_chunks(
    text_stream: AsyncIterator[str],
    *,
    model: str = "bumba",
) -> AsyncIterator[str]:
    """Convert an async text stream into OpenAI-format SSE chunks."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    # Initial role chunk
    initial = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(initial)}\n\n"

    async for text in text_stream:
        if not text:
            continue
        chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n"

    # Final chunk
    final = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"


def format_sse_done() -> str:
    """Return the [DONE] sentinel that terminates an OpenAI SSE stream."""
    return "data: [DONE]\n\n"


async def stream_department_as_sse(
    registry: Any,
    department: str,
    task: str,
    deps: Any,
) -> AsyncIterator[str]:
    """Run a department and stream the manager's output as OpenAI SSE.

    Falls back to sentence-chunked non-streaming when run_stream isn't available.
    """
    team = registry.get_team(department)

    try:
        async with team.manager.run_stream(task, deps=deps) as result:
            async def text_iter() -> AsyncIterator[str]:
                async for text in result.stream_text(delta=True):
                    yield text

            async for chunk in to_openai_sse_chunks(text_iter(), model=f"department:{department}"):
                yield chunk

            yield format_sse_done()
            return
    except (AttributeError, Exception):
        pass

    # Fallback: non-streaming
    team_result = await registry.route(department, task, deps)
    output = team_result.manager_output if team_result.success else (team_result.error or "")

    async def fallback_iter() -> AsyncIterator[str]:
        for sentence in output.split(". "):
            if sentence:
                yield sentence + ("." if not sentence.endswith(".") else "") + " "

    async for chunk in to_openai_sse_chunks(fallback_iter(), model=f"department:{department}"):
        yield chunk

    yield format_sse_done()
