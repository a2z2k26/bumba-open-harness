"""Tests for bridge.tts_engine (HTTP Kokoro client)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.tts_engine import TTSEngine, _strip_markdown, _split_sentences, DEFAULT_TTS_URL


class TestStripMarkdown:
    """Markdown stripping for TTS input."""

    def test_bold(self):
        assert _strip_markdown("**hello**") == "hello"

    def test_italic(self):
        assert _strip_markdown("*world*") == "world"

    def test_underscore_bold(self):
        assert _strip_markdown("__bold__") == "bold"

    def test_underscore_italic(self):
        assert _strip_markdown("_italic_") == "italic"

    def test_inline_code(self):
        assert _strip_markdown("run `pip install`") == "run"

    def test_fenced_code_block(self):
        text = "Before\n```python\nprint('hi')\n```\nAfter"
        result = _strip_markdown(text)
        assert "print" not in result
        assert "Before" in result
        assert "After" in result

    def test_heading(self):
        assert _strip_markdown("## Title").strip() == "Title"

    def test_link(self):
        assert _strip_markdown("[click here](https://example.com)") == "click here"

    def test_image(self):
        assert _strip_markdown("![alt](https://img.png)") == ""

    def test_blockquote(self):
        result = _strip_markdown("> quoted text")
        assert "quoted" in result

    def test_horizontal_rule(self):
        assert _strip_markdown("---") == ""

    def test_plain_text_unchanged(self):
        assert _strip_markdown("Hello, how are you?") == "Hello, how are you?"

    def test_mixed_formatting(self):
        text = "**Bold** and *italic* with `code`"
        result = _strip_markdown(text)
        assert "Bold" in result
        assert "italic" in result
        assert "code" not in result  # inline code stripped


class TestSplitSentences:
    """Sentence splitting for natural TTS pacing."""

    def test_single_sentence(self):
        assert _split_sentences("Hello world.") == ["Hello world."]

    def test_two_sentences(self):
        result = _split_sentences("Hello. World.")
        assert len(result) == 2
        assert result[0] == "Hello."
        assert result[1] == "World."

    def test_question_and_answer(self):
        result = _split_sentences("How are you? I'm fine!")
        assert len(result) == 2

    def test_empty_string(self):
        assert _split_sentences("") == []

    def test_no_sentence_ending(self):
        result = _split_sentences("No period here")
        assert result == ["No period here"]


class TestTTSEngine:
    """TTSEngine unit tests (HTTP Kokoro client)."""

    def test_default_url(self):
        engine = TTSEngine()
        assert engine._base_url == DEFAULT_TTS_URL

    def test_custom_url(self):
        engine = TTSEngine(base_url="http://myhost:9999")
        assert engine._base_url == "http://myhost:9999"

    def test_trailing_slash_stripped(self):
        engine = TTSEngine(base_url="http://myhost:9999/")
        assert engine._base_url == "http://myhost:9999"

    def test_default_voice(self):
        engine = TTSEngine()
        assert engine._voice == "af_sky"

    def test_custom_voice(self):
        engine = TTSEngine(voice="am_adam")
        assert engine._voice == "am_adam"

    def test_enabled_default(self):
        engine = TTSEngine()
        assert engine.enabled is True

    def test_disabled(self):
        engine = TTSEngine(enabled=False)
        assert engine.enabled is False

    def test_max_chars_default(self):
        engine = TTSEngine()
        assert engine._max_chars == 500

    def test_max_chars_custom(self):
        engine = TTSEngine(max_chars=100)
        assert engine._max_chars == 100

    @pytest.mark.asyncio
    async def test_synthesize_disabled_returns_empty(self):
        engine = TTSEngine(enabled=False)
        result = await engine.synthesize("Hello")
        assert result == b""

    @pytest.mark.asyncio
    async def test_synthesize_empty_text_returns_empty(self):
        engine = TTSEngine()
        result = await engine.synthesize("")
        assert result == b""

    @pytest.mark.asyncio
    async def test_synthesize_whitespace_returns_empty(self):
        engine = TTSEngine()
        result = await engine.synthesize("   ")
        assert result == b""

    @pytest.mark.asyncio
    async def test_synthesize_success(self):
        """HTTP POST returns WAV bytes."""
        engine = TTSEngine(voice="af_sky")
        fake_wav = b"RIFF" + b"\x00" * 40

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=fake_wav)

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        engine._session = mock_session
        result = await engine.synthesize("Hello world")
        assert result == fake_wav

    @pytest.mark.asyncio
    async def test_synthesize_posts_correct_payload(self):
        """Verify JSON payload sent to Kokoro."""
        engine = TTSEngine(voice="af_sky", model="tts-1")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"wav")

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        engine._session = mock_session
        await engine.synthesize("Hello world")

        call_args = mock_session.post.call_args
        assert call_args[0][0] == f"{DEFAULT_TTS_URL}/v1/audio/speech"
        payload = call_args[1]["json"]
        assert payload["input"] == "Hello world"
        assert payload["voice"] == "af_sky"
        assert payload["model"] == "tts-1"
        assert payload["response_format"] == "wav"

    @pytest.mark.asyncio
    async def test_synthesize_strips_markdown(self):
        """Markdown should be stripped before sending to API."""
        engine = TTSEngine()

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"wav")

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        engine._session = mock_session
        await engine.synthesize("**Bold** text")

        payload = mock_session.post.call_args[1]["json"]
        assert "**" not in payload["input"]
        assert "Bold" in payload["input"]

    @pytest.mark.asyncio
    async def test_synthesize_truncates_long_text(self):
        """Text longer than max_chars should be truncated."""
        engine = TTSEngine(max_chars=20)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"wav")

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        engine._session = mock_session
        await engine.synthesize("This is a fairly long text that exceeds the maximum")

        payload = mock_session.post.call_args[1]["json"]
        assert len(payload["input"]) <= 25  # 20 + room for word boundary + "..."

    @pytest.mark.asyncio
    async def test_synthesize_api_error_returns_empty(self):
        """Non-200 response returns empty bytes."""
        engine = TTSEngine()

        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        engine._session = mock_session
        result = await engine.synthesize("Hello")
        assert result == b""

    @pytest.mark.asyncio
    async def test_synthesize_connection_error_returns_empty(self):
        """Connection failure returns empty bytes."""
        import aiohttp
        engine = TTSEngine()

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.post = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))

        engine._session = mock_session
        result = await engine.synthesize("Hello")
        assert result == b""


class TestTTSEngineHealthCheck:
    """Health check endpoint tests."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        engine = TTSEngine()
        mock_resp = AsyncMock()
        mock_resp.status = 200

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        engine._session = mock_session
        assert await engine.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        engine = TTSEngine()
        mock_resp = AsyncMock()
        mock_resp.status = 503

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        engine._session = mock_session
        assert await engine.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        import aiohttp
        engine = TTSEngine()
        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(side_effect=aiohttp.ClientError("refused"))

        engine._session = mock_session
        assert await engine.health_check() is False


class TestTTSEngineClose:
    """Session cleanup."""

    @pytest.mark.asyncio
    async def test_close_session(self):
        engine = TTSEngine()
        mock_session = AsyncMock()
        mock_session.closed = False
        engine._session = mock_session

        await engine.close()
        mock_session.close.assert_called_once()
        assert engine._session is None

    @pytest.mark.asyncio
    async def test_close_no_session(self):
        engine = TTSEngine()
        await engine.close()  # Should not raise


class TestVoiceBootPath:
    """Guard the app_init voice-construction path offline (issue #2546-2548).

    The bridge runs voice-off in production, so the voice branch of
    ``BridgeApp._initialize()`` was never exercised in CI. A stale kwarg
    (``TTSEngine(tts_url=...)`` instead of ``base_url=``) sat undetected until
    a live boot with ``voice_enabled = true`` crashed at app_init.py:419 with
    ``TypeError: __init__() got an unexpected keyword argument 'tts_url'``.

    These tests pin the construction contract so a regression fails in CI
    even when the daemon never turns voice on.
    """

    def test_construct_like_app_init(self):
        """TTSEngine builds with the exact kwargs app_init passes.

        Mirrors ``self._tts = TTSEngine(base_url=config.voice_tts_url,
        voice=config.voice_tts_voice)`` in bridge/app_init.py. Must not raise
        TypeError.
        """
        engine = TTSEngine(
            base_url="http://127.0.0.1:7888",
            voice="af_sky",
        )
        assert engine is not None
        assert engine._base_url == "http://127.0.0.1:7888"
        assert engine._voice == "af_sky"

    def test_app_init_tts_kwargs_match_signature(self):
        """Every kwarg app_init passes to TTSEngine is a real parameter.

        Static guard: parse the TTSEngine(...) call in app_init.py and assert
        each keyword maps to a TTSEngine.__init__ parameter. This is the check
        that would have caught the ``tts_url=`` typo before voice was enabled.
        """
        import ast
        import inspect

        from bridge import app_init

        valid_params = set(inspect.signature(TTSEngine.__init__).parameters) - {"self"}

        source = inspect.getsource(app_init)
        tree = ast.parse(source)

        tts_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "TTSEngine"
        ]
        assert tts_calls, "expected at least one TTSEngine(...) call in app_init"

        for call in tts_calls:
            for kw in call.keywords:
                assert kw.arg in valid_params, (
                    f"app_init passes TTSEngine({kw.arg}=...), "
                    f"but TTSEngine.__init__ has no such parameter "
                    f"(valid: {sorted(valid_params)})"
                )
