"""TTS engine: HTTP client for Kokoro ONNX container (OpenAI-compatible API)."""

from __future__ import annotations

import logging
import re
import time

import aiohttp

logger = logging.getLogger(__name__)

# Default Kokoro container endpoint
DEFAULT_TTS_URL = "http://127.0.0.1:7888"
DEFAULT_VOICE = "af_sky"
DEFAULT_MODEL = "tts-1"

# Markdown patterns to strip before TTS synthesis
_MD_STRIP = re.compile(
    r"```.*?```"           # fenced code blocks
    r"|`[^`]*`"            # inline code
    r"|\*\*(.+?)\*\*"      # **bold** → keep inner text (captured in group 1)
    r"|\*(.+?)\*"          # *italic* → keep inner
    r"|__(.+?)__"          # __bold__
    r"|_(.+?)_"            # _italic_
    r"|#+\s+"              # ATX headings
    r"|\[([^\]]+)\]\([^)]+\)"  # [text](url) → keep text
    r"|!\[.*?\]\([^)]+\)"  # images → drop
    r"|>\s+"               # blockquotes
    r"|\|[^\n]*\|"         # table rows
    r"|-{3,}"              # horizontal rules
    ,
    re.DOTALL,
)

# Sentence splitting: split on . ! ? followed by space or end
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _strip_markdown(text: str) -> str:
    """Remove markdown syntax, keeping readable prose."""
    def _replace(m: re.Match) -> str:
        for g in m.groups():
            if g is not None:
                return g
        return ""
    return _MD_STRIP.sub(_replace, text).strip()


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for natural TTS pacing."""
    parts = _SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


class TTSEngine:
    """HTTP-based TTS engine calling a Kokoro ONNX container.

    Strips markdown, truncates long text, then POSTs to the Kokoro
    container's OpenAI-compatible /v1/audio/speech endpoint.
    Returns WAV bytes suitable for Discord audio playback.
    """

    MAX_CHARS = 500

    def __init__(
        self,
        base_url: str | None = None,
        voice: str | None = None,
        model: str | None = None,
        max_chars: int | None = None,
        enabled: bool = True,
        timeout_s: float = 30.0,
    ) -> None:
        self._base_url = (base_url or DEFAULT_TTS_URL).rstrip("/")
        self._voice = voice or DEFAULT_VOICE
        self._model = model or DEFAULT_MODEL
        self._max_chars = max_chars or self.MAX_CHARS
        self._enabled = enabled
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._session: aiohttp.ClientSession | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=5, keepalive_timeout=30, ttl_dns_cache=300,
            )
            self._session = aiohttp.ClientSession(
                connector=connector, timeout=self._timeout,
            )
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def health_check(self) -> bool:
        """Check if the Kokoro container is reachable."""
        try:
            session = await self._get_session()
            async with session.get(f"{self._base_url}/health") as resp:
                return resp.status == 200
        except Exception:
            return False

    async def synthesize(self, text: str) -> bytes:
        """Convert text to WAV bytes via Kokoro HTTP API.

        Strips markdown, truncates to max_chars, then synthesizes.
        Returns WAV bytes suitable for Discord audio playback.
        """
        if not self._enabled:
            return b""

        if not text.strip():
            return b""

        clean = _strip_markdown(text)
        if not clean:
            return b""

        # Truncate at word boundary up to max_chars
        if len(clean) > self._max_chars:
            clean = clean[: self._max_chars].rsplit(" ", 1)[0] + "..."

        t0 = time.monotonic()

        for attempt in range(2):
            try:
                session = await self._get_session()
                payload = {
                    "input": clean,
                    "voice": self._voice,
                    "model": self._model,
                    "response_format": "wav",
                }

                url = f"{self._base_url}/v1/audio/speech"
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error("TTS API error %d: %s", resp.status, body[:200])
                        return b""

                    wav_bytes = await resp.read()

                break  # success

            except aiohttp.ServerDisconnectedError as e:
                if attempt == 0:
                    logger.warning("TTS server disconnected, retrying: %s", e)
                    await self.close()  # force new session
                    continue
                logger.error("TTS request failed after retry: %s", e)
                return b""
            except aiohttp.ClientError as e:
                logger.error("TTS request failed: %s", e)
                return b""
            except Exception as e:
                logger.error("TTS unexpected error: %s", e)
                return b""
        else:
            return b""

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.debug("TTS synthesized %d chars in %dms (%d bytes WAV)",
                      len(clean), elapsed_ms, len(wav_bytes))
        return wav_bytes
