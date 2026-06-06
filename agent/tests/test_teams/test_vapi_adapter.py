"""Tests for teams._vapi — OpenAI-compatible SSE adapter for VAPI."""

from __future__ import annotations

import json

import pytest

from teams._vapi import format_sse_done, parse_openai_request, to_openai_sse_chunks


class TestParseOpenAIRequest:
    def test_extracts_user_message(self):
        body = {
            "model": "department:qa",
            "messages": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "run the tests"},
            ],
            "stream": True,
        }
        assert parse_openai_request(body) == "run the tests"

    def test_multi_turn_uses_last_user_message(self):
        body = {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "what's next"},
            ]
        }
        assert parse_openai_request(body) == "what's next"

    def test_missing_messages_raises(self):
        with pytest.raises(ValueError):
            parse_openai_request({})

    def test_no_user_message_raises(self):
        with pytest.raises(ValueError):
            parse_openai_request({"messages": [{"role": "system", "content": "hi"}]})


class TestFormatSSEChunks:
    @pytest.mark.asyncio
    async def test_chunks_format(self):
        async def text_stream():
            yield "Hello "
            yield "world"

        chunks = []
        async for chunk in to_openai_sse_chunks(text_stream(), model="department:qa"):
            chunks.append(chunk)

        assert len(chunks) >= 3  # role chunk + 2 content chunks + final
        assert all(c.startswith("data: ") for c in chunks)
        assert all(c.endswith("\n\n") for c in chunks)

        # Parse content chunks (skip role chunk and final)
        payloads = [json.loads(c[len("data: "):-2]) for c in chunks]
        contents = [p["choices"][0]["delta"].get("content", "") for p in payloads]
        assert "Hello " in contents
        assert "world" in contents

    @pytest.mark.asyncio
    async def test_model_field_set(self):
        async def text_stream():
            yield "test"

        chunks = []
        async for chunk in to_openai_sse_chunks(text_stream(), model="department:strategy"):
            chunks.append(chunk)

        payload = json.loads(chunks[0][len("data: "):-2])
        assert payload["model"] == "department:strategy"

    @pytest.mark.asyncio
    async def test_finish_reason_stop_on_final(self):
        async def text_stream():
            yield "done"

        chunks = []
        async for chunk in to_openai_sse_chunks(text_stream(), model="test"):
            chunks.append(chunk)

        final_payload = json.loads(chunks[-1][len("data: "):-2])
        assert final_payload["choices"][0]["finish_reason"] == "stop"

    def test_done_format(self):
        assert format_sse_done() == "data: [DONE]\n\n"
