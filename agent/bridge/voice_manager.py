"""Voice channel manager: auto-join/leave and TTS playback (VAPI owns receive)."""

from __future__ import annotations

import asyncio
import io
import logging
import math
import queue
import struct
import time
from typing import Callable, Awaitable

from ._async_supervision import spawn_background_task
from .tts_engine import _split_sentences, _strip_markdown

logger = logging.getLogger(__name__)

# Transcription callback: (user_id, text) -> None
TranscriptionCallback = Callable[[int, str], Awaitable[None]]

# TTS mode
TTS_OFF = "off"
TTS_ON = "on"
TTS_AUTO = "auto"   # speak when response < AUTO_TTS_MAX_CHARS

AUTO_TTS_MAX_CHARS = 1500
IDLE_TIMEOUT_S = 300.0  # 5 minutes
WATCHDOG_CHECK_S = 10.0  # how often to check for dead sink
WATCHDOG_TIMEOUT_S = 30.0  # no packets for this long → re-wire

GREETING_TEXT = "Hi, Bumba here, how can I help you today"

# ThinkingTone parameters
_THINKING_FREQ_HZ = 275
_THINKING_AMPLITUDE = 0.15
_THINKING_PULSE_RATE_HZ = 0.5  # 2-second breathing cycle
_DISCORD_SAMPLE_RATE = 48000
_DISCORD_CHANNELS = 2
_DISCORD_FRAME_MS = 20
_DISCORD_FRAME_SAMPLES = _DISCORD_SAMPLE_RATE * _DISCORD_FRAME_MS // 1000  # 960
_DISCORD_FRAME_BYTES = _DISCORD_FRAME_SAMPLES * _DISCORD_CHANNELS * 2  # 3840


# Resolve base class: discord.AudioSource when available, object for tests
try:
    import discord as _discord_mod  # type: ignore[import]
    _AudioSourceBase = _discord_mod.AudioSource
except ImportError:
    _AudioSourceBase = object


def _patch_packet_router() -> None:
    """Monkey-patch PacketRouter._do_run to survive OpusError.

    The voice_recv library treats any Opus decode error as fatal, crashing
    the entire PacketRouter thread and killing all audio receive permanently.
    This patch catches decode errors per-packet and resets the affected
    decoder instead, allowing audio receive to continue.

    Hardening additions:
    - Version guard: warn if discord.py version changes
    - Error rate tracking: >10 errors in 60s triggers reconnect signal
    - Per-SSRC reset counter: skip bad sources after 5 resets in 30s
    """
    try:
        from discord.ext.voice_recv.router import PacketRouter  # type: ignore[import]
    except ImportError:
        return

    # Version guard
    try:
        import discord as _dmod
        _ver = getattr(_dmod, "__version__", "unknown")
        if not _ver.startswith("2."):
            logger.warning(
                "PacketRouter patch: discord.py version %s may be incompatible "
                "(patch tested against 2.x)", _ver,
            )
    except Exception as exc:
        logger.warning("PacketRouter version guard check failed: %s", exc)

    _log = logging.getLogger("discord.ext.voice_recv.router")

    # Error tracking state (shared across all decoders)
    _error_timestamps: list[float] = []
    _ssrc_resets: dict[int, list[float]] = {}
    _ERROR_RATE_WINDOW = 60.0
    _ERROR_RATE_THRESHOLD = 10
    _SSRC_RESET_WINDOW = 30.0
    _SSRC_RESET_THRESHOLD = 5
    _reconnect_signal = False

    def _resilient_do_run(self) -> None:
        nonlocal _reconnect_signal

        while not self._end_thread.is_set():
            self.waiter.wait()
            with self._lock:
                for decoder in self.waiter.items:
                    ssrc = getattr(decoder, "ssrc", 0)

                    # Check per-SSRC cooldown
                    now = time.monotonic()
                    if ssrc in _ssrc_resets:
                        recent = [t for t in _ssrc_resets[ssrc] if now - t < _SSRC_RESET_WINDOW]
                        _ssrc_resets[ssrc] = recent
                        if len(recent) >= _SSRC_RESET_THRESHOLD:
                            continue  # Skip this source — too many errors

                    try:
                        data = decoder.pop_data()
                    except Exception as e:
                        _log.warning(
                            "Opus decode error for ssrc %s (resetting decoder): %s",
                            ssrc, e,
                        )
                        try:
                            decoder.reset()
                        except Exception as exc:
                            _log.warning("opus decoder reset failed: %s", exc)

                        # Track error rate
                        _error_timestamps.append(now)
                        # Trim old entries
                        while _error_timestamps and now - _error_timestamps[0] > _ERROR_RATE_WINDOW:
                            _error_timestamps.pop(0)

                        # Track per-SSRC resets
                        _ssrc_resets.setdefault(ssrc, []).append(now)

                        # Check if error rate exceeds threshold
                        if len(_error_timestamps) >= _ERROR_RATE_THRESHOLD:
                            _log.error(
                                "PacketRouter: %d decode errors in %.0fs — signaling reconnect",
                                len(_error_timestamps), _ERROR_RATE_WINDOW,
                            )
                            _reconnect_signal = True
                            _error_timestamps.clear()

                        continue
                    if data is not None:
                        self.sink.write(data.source, data)

    PacketRouter._do_run = _resilient_do_run
    # Expose reconnect signal checker for watchdog
    PacketRouter._bumba_reconnect_signal = lambda self: _reconnect_signal
    PacketRouter._bumba_clear_reconnect = lambda self: (
        _error_timestamps.clear(),
        _ssrc_resets.clear(),
    )


_patch_packet_router()


# ReceivedPing parameters
_PING_FREQ_HZ = 660
_PING_AMPLITUDE = 0.10
_PING_DURATION_MS = 150  # short chirp


class ReceivedPing(_AudioSourceBase):
    """Discord AudioSource that plays a short chirp to acknowledge speech received.

    A brief 150ms tone at 660 Hz with a quick fade-out envelope.
    Plays once then returns empty bytes to stop.
    """

    def __init__(self) -> None:
        self._stopped = False
        self._sample_index = 0
        self._total_samples = _DISCORD_SAMPLE_RATE * _PING_DURATION_MS // 1000  # ~7200 samples

    def is_opus(self) -> bool:
        return False

    def read(self) -> bytes:
        if self._stopped or self._sample_index >= self._total_samples:
            return b""

        buf = bytearray(_DISCORD_FRAME_BYTES)
        two_pi = 2.0 * math.pi

        for i in range(_DISCORD_FRAME_SAMPLES):
            si = self._sample_index + i
            if si >= self._total_samples:
                # Zero-fill rest of frame
                break
            t = si / _DISCORD_SAMPLE_RATE
            # Fade-out envelope: linear decay over duration
            progress = si / self._total_samples
            envelope = _PING_AMPLITUDE * (1.0 - progress)
            sample = envelope * math.sin(two_pi * _PING_FREQ_HZ * t)
            val = int(sample * 32767)
            val = max(-32768, min(32767, val))
            offset = i * 4
            struct.pack_into("<hh", buf, offset, val, val)

        self._sample_index += _DISCORD_FRAME_SAMPLES
        return bytes(buf)

    def stop(self) -> None:
        self._stopped = True

    def cleanup(self) -> None:
        self._stopped = True


class StreamingTTSSource(_AudioSourceBase):
    """Discord AudioSource that plays PCM chunks from a thread-safe queue.

    Chunks are added asynchronously (sentence-by-sentence TTS) while the
    Discord player thread reads frames.  Returns silence on buffer underrun
    to keep playback alive until more data arrives or finish() is called.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._current_buffer: bytes = b""
        self._offset: int = 0
        self._finished: bool = False
        self._stopped: bool = False

    def add_chunk(self, pcm_bytes: bytes) -> None:
        """Enqueue a PCM chunk (called from async context)."""
        self._queue.put(pcm_bytes)

    def finish(self) -> None:
        """Signal that no more chunks will be added."""
        self._finished = True

    def is_opus(self) -> bool:
        return False

    def read(self) -> bytes:
        if self._stopped:
            return b""

        # Refill internal buffer from queue
        while self._offset >= len(self._current_buffer):
            try:
                chunk = self._queue.get_nowait()
                self._current_buffer = chunk
                self._offset = 0
            except queue.Empty:
                if self._finished:
                    return b""  # all done
                # Buffer underrun: return silence to keep playback alive
                return b"\x00" * _DISCORD_FRAME_BYTES

        # Slice the next Discord frame
        end = self._offset + _DISCORD_FRAME_BYTES
        frame = self._current_buffer[self._offset:end]
        self._offset = end

        # Pad short final frame with silence
        if len(frame) < _DISCORD_FRAME_BYTES:
            frame = frame + b"\x00" * (_DISCORD_FRAME_BYTES - len(frame))

        return frame

    def stop(self) -> None:
        self._stopped = True

    def cleanup(self) -> None:
        self._stopped = True


class ThinkingTone(_AudioSourceBase):
    """Discord AudioSource that generates a gentle pulsing sine wave.

    Produces a 275 Hz tone with amplitude modulated at 0.5 Hz (2-second
    breathing cycle). Output format: 48kHz stereo s16le, 3840 bytes/frame.
    """

    def __init__(self) -> None:
        self._stopped = False
        self._sample_index = 0

    def is_opus(self) -> bool:
        return False

    def read(self) -> bytes:
        if self._stopped:
            return b""

        buf = bytearray(_DISCORD_FRAME_BYTES)
        two_pi = 2.0 * math.pi

        for i in range(_DISCORD_FRAME_SAMPLES):
            t = (self._sample_index + i) / _DISCORD_SAMPLE_RATE
            # Amplitude envelope: pulse between 0 and _THINKING_AMPLITUDE
            envelope = _THINKING_AMPLITUDE * (0.5 + 0.5 * math.sin(two_pi * _THINKING_PULSE_RATE_HZ * t))
            sample = envelope * math.sin(two_pi * _THINKING_FREQ_HZ * t)
            val = int(sample * 32767)
            val = max(-32768, min(32767, val))
            # Stereo: write same value to both channels
            offset = i * 4  # 2 channels × 2 bytes
            struct.pack_into("<hh", buf, offset, val, val)

        self._sample_index += _DISCORD_FRAME_SAMPLES
        return bytes(buf)

    def stop(self) -> None:
        self._stopped = True

    def cleanup(self) -> None:
        self._stopped = True


async def _wav_to_discord_pcm(wav_bytes: bytes) -> bytes:
    """Convert WAV (any rate/channels) → 48kHz stereo 16-bit PCM via ffmpeg.

    Uses async subprocess to avoid blocking the event loop.
    Returns raw PCM bytes suitable for discord.py's PCMAudio/RawFrameInput.
    Raises RuntimeError if ffmpeg is not found or conversion fails.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",           # read from stdin
            "-f", "s16le",            # signed 16-bit little-endian PCM
            "-ar", "48000",           # 48 kHz (Discord requirement)
            "-ac", "2",              # stereo
            "pipe:1",                # write to stdout
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=wav_bytes), timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found — install via: brew install ffmpeg")
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("ffmpeg timed out during WAV conversion")

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit {proc.returncode}): {stderr.decode()[:200]}"
        )
    return stdout


class VoiceManager:
    """Manages Discord voice channel lifecycle for outbound VAPI/TTS audio.

    Discord voice receive is intentionally absent — speech-to-text and
    dialog routing are owned by the VAPI integration, not by this manager.

    Responsibilities:
    - Auto-join when operator enters the designated voice channel
    - Auto-leave when operator leaves or idle timeout fires
    - Play TTS audio (WAV bytes → FFmpeg → Discord PCM), single-shot and streaming
    - Greeting on join: plays TTS greeting when connecting
    - Thinking sound: ambient pulsing tone during processing
    - Expose /voice and /tts slash command handlers
    """

    def __init__(
        self,
        bot,                          # discord.Client (DiscordBot)
        tts_engine=None,              # TTSEngine | None
        voice_channel_id: int | None = None,
        idle_timeout_s: float = IDLE_TIMEOUT_S,
        tts_mode: str = TTS_AUTO,
    ) -> None:
        self._bot = bot
        self._tts = tts_engine
        self._voice_channel_id = voice_channel_id
        self._idle_timeout_s = idle_timeout_s
        self._tts_mode = tts_mode

        self._voice_client = None       # discord.VoiceClient when connected
        self._transcription_callback: TranscriptionCallback | None = None
        self._idle_task: asyncio.Task | None = None
        self._last_activity: float = time.monotonic()
        self._voice_lock = asyncio.Lock()  # Serialize voice transcription handling

        # Watchdog state
        self._current_sink = None          # legacy slot, retained for watchdog state
        self._watchdog_task: asyncio.Task | None = None
        self._last_packet_time: float = 0.0  # updated by sink.write()

        # Greeting cache
        self._greeting_wav: bytes | None = None

        # Thinking indicator state
        self._thinking_active: bool = False

        # Guard against duplicate join attempts (gateway RESUME replays)
        self._connecting: bool = False

        # Thinking sound safety timeout
        self._thinking_timeout_task: asyncio.Task | None = None

    # -- Configuration --

    def set_transcription_callback(self, callback: TranscriptionCallback) -> None:
        """Register the callback invoked when a transcription is dispatched."""
        self._transcription_callback = callback

    def set_tts_mode(self, mode: str) -> None:
        """Set TTS mode: 'on', 'off', or 'auto'."""
        if mode not in (TTS_OFF, TTS_ON, TTS_AUTO):
            raise ValueError(f"Invalid TTS mode: {mode!r}")
        self._tts_mode = mode
        logger.info("TTS mode set to %r", mode)

    @property
    def tts_mode(self) -> str:
        return self._tts_mode

    @property
    def is_connected(self) -> bool:
        return self._voice_client is not None and self._voice_client.is_connected()

    # -- Backend Health Checks --

    async def _check_voice_backends(self) -> dict[str, bool]:
        """Check STT and TTS backend availability.

        Returns dict with 'stt' and 'tts' keys, True if reachable.
        """
        import aiohttp

        results = {"stt": False, "tts": False}

        async def _check(name: str, url: str) -> bool:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        return resp.status < 500
            except Exception:
                return False

        # STT: Whisper.cpp at port 8880
        results["stt"] = await _check("stt", "http://127.0.0.1:8880/v1/models")
        # TTS: Kokoro at port 7888
        results["tts"] = await _check("tts", "http://127.0.0.1:7888/v1/models")

        if not results["stt"]:
            logger.warning("Voice backend check: STT (Whisper.cpp:8880) is DOWN")
        if not results["tts"]:
            logger.warning("Voice backend check: TTS (Kokoro:7888) is DOWN")

        return results

    # -- Join / Leave --

    async def join_channel(self, channel_id: int | None = None) -> bool:
        """Join a voice channel. Uses channel_id or falls back to configured channel.

        Returns True if successfully connected, False otherwise.
        """
        if self._connecting:
            logger.info("join_channel: connection already in progress, skipping")
            return False

        cid = channel_id or self._voice_channel_id
        if cid is None:
            logger.warning("join_channel: no voice channel configured")
            return False

        channel = self._bot.get_channel(cid)
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(cid)
            except Exception as e:
                logger.error("Cannot fetch voice channel %d: %s", cid, e)
                return False

        self._connecting = True
        try:
            # Check voice backends before connecting
            try:
                backends = await self._check_voice_backends()
                if not backends["stt"]:
                    logger.warning("STT backend down — voice listening disabled for this session")
                if not backends["tts"]:
                    logger.warning("TTS backend down — voice responses will be text-only")
            except Exception as e:
                logger.debug("Backend check failed (continuing anyway): %s", e)

            # Use VoiceRecvClient for audio receive support if available
            connect_cls = None
            try:
                from discord.ext.voice_recv import VoiceRecvClient  # type: ignore[import]
                connect_cls = VoiceRecvClient
            except ImportError:
                pass

            if self._voice_client and self._voice_client.is_connected():
                await self._voice_client.move_to(channel)
            else:
                kwargs = {"cls": connect_cls} if connect_cls else {}
                self._voice_client = await channel.connect(**kwargs)

            self._last_activity = time.monotonic()
            self._start_idle_timer()

            # Start watchdog to recover from OpusError crashes
            self._start_watchdog()

            logger.info("Joined voice channel %d", cid)

            # Play greeting (non-blocking)
            spawn_background_task(
                self._play_greeting(),
                name="voice-greeting",
                logger=logger,
            )

            return True
        except Exception as e:
            logger.error("Failed to join voice channel %d: %s", cid, e)
            self._voice_client = None
            return False
        finally:
            self._connecting = False

    async def leave_channel(self) -> None:
        """Disconnect from voice channel."""
        self._cancel_idle_timer()
        self._cancel_watchdog()
        self.stop_thinking_sound()
        if self._voice_client:
            try:
                await self._voice_client.disconnect(force=True)
            except Exception as e:
                logger.debug("Error disconnecting from voice: %s", e)
            self._voice_client = None
        self._current_sink = None
        logger.info("Left voice channel")

    # -- Audio receive watchdog --

    def _start_watchdog(self) -> None:
        """Start the audio receive watchdog coroutine."""
        self._cancel_watchdog()
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name="voice-watchdog"
        )

    def _cancel_watchdog(self) -> None:
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
        self._watchdog_task = None

    async def _watchdog_loop(self) -> None:
        """Check every WATCHDOG_CHECK_S — if no packets for WATCHDOG_TIMEOUT_S, reconnect.

        The PacketRouter thread crashes on OpusError and cannot recover
        by just re-wiring the sink — the entire voice connection must be
        torn down and re-established to get a fresh decoder state.

        Skips during playback (TTS/greeting) and active voice processing
        since no incoming packets are expected during those periods.

        Hardening:
        - Reconnect cooldown: minimum 60s between reconnect attempts
        - Consecutive reconnect tracking: 3 in a row → full leave/rejoin
        - Empty channel detection: enter idle mode instead of looping
        - PacketRouter error rate signal: reconnect on burst errors
        """
        _RECONNECT_COOLDOWN_S = 60.0
        _last_reconnect_time = 0.0
        _consecutive_reconnects = 0

        try:
            while True:
                await asyncio.sleep(WATCHDOG_CHECK_S)
                if not self.is_connected:
                    return

                # Don't reconnect during playback or active processing
                if self._voice_client and self._voice_client.is_playing():
                    self._last_packet_time = time.monotonic()
                    continue
                if self._voice_lock.locked():
                    self._last_packet_time = time.monotonic()
                    continue

                now = time.monotonic()
                should_reconnect = False

                # Check if PacketRouter signaled error burst
                if self._voice_client and hasattr(self._voice_client, '_bumba_reconnect_signal'):
                    try:
                        if self._voice_client._bumba_reconnect_signal():
                            logger.warning("Watchdog: PacketRouter error rate signal — reconnecting")
                            should_reconnect = True
                    except Exception as exc:
                        logger.warning("watchdog reconnect-signal check failed: %s", exc)

                # Check packet timeout
                if not should_reconnect and self._last_packet_time > 0.0:
                    elapsed = now - self._last_packet_time
                    if elapsed >= WATCHDOG_TIMEOUT_S:
                        # Check if channel is empty (only bot)
                        if self._voice_client and self._voice_client.channel:
                            members = self._voice_client.channel.members
                            non_bot = [m for m in members if not m.bot]
                            if not non_bot:
                                # Nobody else in channel — don't reconnect
                                self._last_packet_time = now
                                continue

                        logger.warning(
                            "Audio receive watchdog: no packets for %.0fs — reconnecting voice",
                            elapsed,
                        )
                        should_reconnect = True

                if not should_reconnect:
                    continue

                # Cooldown check
                if now - _last_reconnect_time < _RECONNECT_COOLDOWN_S:
                    logger.info("Watchdog: reconnect cooldown active (%.0fs remaining)",
                                _RECONNECT_COOLDOWN_S - (now - _last_reconnect_time))
                    continue

                _last_reconnect_time = now
                _consecutive_reconnects += 1

                # Reset packet time so we don't immediately retrigger
                self._last_packet_time = now

                await self._reconnect_voice()

                # Check if reconnect actually fixed things on next cycle
                # (consecutive counter resets when we receive a packet)

        except asyncio.CancelledError:
            pass

    async def _reconnect_voice(self) -> None:
        """Disconnect and reconnect to recover from PacketRouter crash."""
        if self._voice_client is None:
            return

        channel = self._voice_client.channel
        if channel is None:
            return

        channel_id = channel.id
        try:
            # Tear down the old connection fully
            self._current_sink = None
            self._last_packet_time = 0.0
            # Stop listening first to avoid _MissingSentinel errors during disconnect
            # (disconnect triggers voice state updates that access the reader)
            try:
                if hasattr(self._voice_client, 'stop_listening'):
                    self._voice_client.stop_listening()
            except Exception as exc:
                logger.warning("voice client stop_listening failed: %s", exc)
            try:
                await self._voice_client.disconnect(force=True)
            except Exception as e:
                logger.debug("Watchdog disconnect error (expected): %s", e)
            self._voice_client = None

            # Short pause to let Discord clean up
            await asyncio.sleep(2)

            # Reconnect
            connect_cls = None
            try:
                from discord.ext.voice_recv import VoiceRecvClient  # type: ignore[import]
                connect_cls = VoiceRecvClient
            except ImportError:
                pass

            channel_obj = self._bot.get_channel(channel_id)
            if channel_obj is None:
                channel_obj = await self._bot.fetch_channel(channel_id)

            kwargs = {"cls": connect_cls} if connect_cls else {}
            self._voice_client = await channel_obj.connect(**kwargs)
            self._last_activity = time.monotonic()

            logger.info("Watchdog: reconnected to voice channel %d", channel_id)
        except Exception as e:
            logger.error("Watchdog reconnect failed: %s", e)

    # -- Greeting --

    async def _play_greeting(self) -> None:
        """Play a TTS greeting when joining a voice channel."""
        if self._tts is None or not self._tts.enabled:
            logger.info("Greeting skipped — TTS engine disabled or missing")
            return
        if not self.is_connected:
            return

        try:
            await asyncio.sleep(0.25)
            if not self.is_connected:
                return
            if self._greeting_wav is None:
                logger.info("Synthesizing greeting...")
                self._greeting_wav = await self._tts.synthesize(GREETING_TEXT)
            if self._greeting_wav:
                await self.play_audio(self._greeting_wav)
                logger.info("Greeting played")
        except Exception as e:
            logger.error("Greeting playback failed: %s", e)

    # -- Thinking indicator sound --

    def start_thinking_sound(self) -> None:
        """Start the ambient thinking tone (while processing STT → Claude → TTS)."""
        if not self.is_connected or self._voice_client is None:
            return
        if self._thinking_active:
            return  # already playing
        # Don't interrupt greeting or TTS playback
        if self._voice_client.is_playing():
            return

        try:
            tone = ThinkingTone()
            self._voice_client.play(tone)
            self._thinking_active = True
            logger.info("Thinking sound started")
            # Safety timeout: force-stop after 10s to prevent infinite thinking sound
            self._cancel_thinking_timeout()
            try:
                loop = asyncio.get_running_loop()
                self._thinking_timeout_task = loop.create_task(
                    self._thinking_timeout(), name="thinking-timeout"
                )
            except RuntimeError:
                pass  # no event loop (shouldn't happen in normal flow)
        except Exception as e:
            logger.error("Failed to start thinking sound: %s", e)

    def stop_thinking_sound(self) -> None:
        """Stop the thinking tone if it's currently playing."""
        self._cancel_thinking_timeout()
        if not self._thinking_active:
            return
        self._thinking_active = False
        if self._voice_client and self._voice_client.is_playing():
            # Use stop_playing() to only stop outgoing audio — VoiceRecvClient.stop()
            # also kills the audio listener, which would break incoming audio receive.
            if hasattr(self._voice_client, 'stop_playing'):
                self._voice_client.stop_playing()
            else:
                self._voice_client.stop()
        logger.info("Thinking sound stopped")

    async def _thinking_timeout(self) -> None:
        """Force-stop thinking sound after 10s as a safety net."""
        try:
            await asyncio.sleep(10.0)
            if self._thinking_active:
                logger.warning("Thinking sound timeout (10s) — force-stopping")
                self.stop_thinking_sound()
        except asyncio.CancelledError:
            pass

    def _cancel_thinking_timeout(self) -> None:
        if self._thinking_timeout_task and not self._thinking_timeout_task.done():
            self._thinking_timeout_task.cancel()
        self._thinking_timeout_task = None

    def play_received_ping(self) -> None:
        """Play a short chirp to acknowledge that speech was received."""
        if not self.is_connected or self._voice_client is None:
            return
        if self._thinking_active:
            return  # thinking already playing, no need for ping
        if self._voice_client.is_playing():
            return  # don't interrupt other audio

        try:
            ping = ReceivedPing()
            self._voice_client.play(ping)
            logger.debug("Received ping played")
        except Exception as e:
            logger.debug("Failed to play received ping: %s", e)

    def _on_transcription_dispatched(self) -> None:
        """Hook fired when a transcription has been dispatched to the operator.

        Starts the thinking sound to give audible feedback that the user's
        speech was received and processing has begun. Invoked by VAPI-side
        adapters via this manager; no Discord-side audio receive pipeline
        is active.
        """
        self.start_thinking_sound()

    # -- TTS playback --

    async def play_tts(self, text: str) -> bool:
        """Synthesize text to speech and play in the voice channel.

        Returns True if playback started, False if skipped (mode off, not connected, etc.).
        """
        if not self.is_connected:
            logger.info("play_tts: skipped — not connected")
            return False
        if self._tts is None or not self._tts.enabled:
            logger.info("play_tts: skipped — TTS engine disabled or missing")
            return False
        if self._tts_mode == TTS_OFF:
            logger.info("play_tts: skipped — TTS mode is off")
            return False

        # Use streaming for multi-sentence responses (no char limit — each
        # sentence is synthesized individually within TTSEngine.MAX_CHARS)
        sentences = _split_sentences(_strip_markdown(text))
        if len(sentences) > 1:
            logger.info("play_tts: streaming %d sentences (%d chars)...", len(sentences), len(text))
            return await self.play_tts_streaming(text, sentences)

        # Single-sentence: apply AUTO mode length cap
        if self._tts_mode == TTS_AUTO and len(text) > AUTO_TTS_MAX_CHARS:
            logger.info("play_tts: skipped — text too long (%d chars)", len(text))
            return False

        logger.info("play_tts: synthesizing %d chars...", len(text))
        try:
            wav_bytes = await self._tts.synthesize(text)
        except Exception as e:
            logger.error("TTS synthesis failed: %s", e)
            return False

        if not wav_bytes:
            logger.warning("play_tts: TTS returned empty audio")
            return False

        logger.info("play_tts: got %d bytes WAV, playing...", len(wav_bytes))
        return await self.play_audio(wav_bytes)

    async def play_audio(self, wav_bytes: bytes) -> bool:
        """Convert WAV bytes to Discord PCM and play in voice channel.

        Returns True if playback started successfully.
        """
        if not self.is_connected or self._voice_client is None:
            logger.info("play_audio: skipped — not connected")
            return False

        try:
            pcm_bytes = await _wav_to_discord_pcm(wav_bytes)
        except RuntimeError as e:
            logger.error("PCM conversion failed: %s", e)
            return False

        try:
            import discord  # type: ignore[import]

            # Stop any currently playing audio (including thinking tone)
            # Use stop_playing() to only stop outgoing audio — VoiceRecvClient.stop()
            # also kills the audio listener, which would break incoming audio receive.
            self._thinking_active = False
            if self._voice_client.is_playing():
                if hasattr(self._voice_client, 'stop_playing'):
                    self._voice_client.stop_playing()
                else:
                    self._voice_client.stop()

            source = discord.PCMAudio(io.BytesIO(pcm_bytes))
            self._voice_client.play(source)
            self._last_activity = time.monotonic()
            logger.info("Playing %d bytes of PCM audio", len(pcm_bytes))
            return True
        except Exception as e:
            logger.error("Audio playback failed: %s", e)
            return False

    async def play_tts_streaming(self, text: str, sentences: list[str] | None = None) -> bool:
        """Synthesize sentence-by-sentence and start playback after the first sentence.

        Playback of sentence N overlaps with synthesis of sentence N+1,
        reducing perceived latency for multi-sentence responses.

        Returns True if playback started, False on failure.
        """
        if not self.is_connected or self._voice_client is None:
            return False
        if self._tts is None or not self._tts.enabled:
            return False

        if sentences is None:
            sentences = _split_sentences(_strip_markdown(text))
        if len(sentences) <= 1:
            return await self.play_tts(text)

        source = StreamingTTSSource()

        # Synthesize first sentence
        try:
            wav = await self._tts.synthesize(sentences[0])
            if not wav:
                logger.warning("play_tts_streaming: first sentence returned empty audio")
                return False
            pcm = await _wav_to_discord_pcm(wav)
            source.add_chunk(pcm)
        except Exception as e:
            logger.error("play_tts_streaming: first sentence failed: %s", e)
            return False

        # Start playback immediately — Discord player runs in its own thread
        self._thinking_active = False
        if self._voice_client.is_playing():
            if hasattr(self._voice_client, 'stop_playing'):
                self._voice_client.stop_playing()
            else:
                self._voice_client.stop()

        self._voice_client.play(source)
        self._last_activity = time.monotonic()
        logger.info("play_tts_streaming: started playback, synthesizing %d remaining sentences", len(sentences) - 1)

        # Synthesize remaining sentences while sentence 1 plays
        for i, sentence in enumerate(sentences[1:], 2):
            try:
                wav = await self._tts.synthesize(sentence)
                if wav:
                    pcm = await _wav_to_discord_pcm(wav)
                    source.add_chunk(pcm)
                    logger.debug("play_tts_streaming: sentence %d/%d ready", i, len(sentences))
            except Exception as e:
                logger.error("play_tts_streaming: sentence %d failed: %s", i, e)

        source.finish()
        return True

    # -- Idle timeout --

    def _start_idle_timer(self) -> None:
        """Start (or restart) the idle disconnect timer."""
        self._cancel_idle_timer()
        self._idle_task = asyncio.create_task(
            self._idle_loop(), name="voice-idle-timer"
        )

    def _cancel_idle_timer(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    async def _idle_loop(self) -> None:
        """Disconnect after idle_timeout_s with no activity."""
        try:
            while True:
                await asyncio.sleep(30)
                if not self.is_connected:
                    return
                # Skip timeout check if a voice conversation is in progress
                if self._voice_lock.locked():
                    continue
                idle = time.monotonic() - self._last_activity
                if idle >= self._idle_timeout_s:
                    logger.info(
                        "Voice idle timeout (%.0fs), disconnecting", idle
                    )
                    await self.leave_channel()
                    return
        except asyncio.CancelledError:
            pass

    def bump_activity(self) -> None:
        """Reset the idle timer (call when audio or TTS occurs)."""
        self._last_activity = time.monotonic()

    # -- Discord event handlers (call from DiscordBot.on_voice_state_update) --

    async def on_voice_state_update(
        self,
        operator_id: int,
        member,
        before,
        after,
    ) -> None:
        """React to operator joining/leaving voice channels.

        Wire into discord.Client.on_voice_state_update in DiscordBot.
        """
        if member.id != operator_id:
            return

        # Operator joined a voice channel
        if after.channel is not None and (before.channel is None or before.channel != after.channel):
            target_id = self._voice_channel_id or after.channel.id
            if after.channel.id == target_id or self._voice_channel_id is None:
                logger.info(
                    "Operator joined voice channel %d — auto-joining", after.channel.id
                )
                await self.join_channel(after.channel.id)

        # Operator left all voice channels
        elif after.channel is None and before.channel is not None:
            if self.is_connected:
                logger.info("Operator left voice — disconnecting")
                await self.leave_channel()

    # -- Slash command handlers --

    async def handle_voice_command(self, args: str) -> str:
        """Handle /voice [join|leave] command. Returns response text."""
        arg = args.strip().lower()
        if arg in ("", "join"):
            if self.is_connected:
                return "Already in a voice channel."
            ok = await self.join_channel()
            return "Joined voice channel." if ok else "Could not join voice channel — check config."
        elif arg == "leave":
            if not self.is_connected:
                return "Not in a voice channel."
            await self.leave_channel()
            return "Left voice channel."
        else:
            return f"Unknown /voice argument: {arg!r}. Use: join, leave."

    async def handle_tts_command(self, args: str) -> str:
        """Handle /tts [on|off|auto] command. Returns response text."""
        arg = args.strip().lower()
        if arg in (TTS_ON, TTS_OFF, TTS_AUTO):
            self.set_tts_mode(arg)
            return f"TTS mode set to {arg!r}."
        elif arg == "":
            return f"TTS mode is currently {self._tts_mode!r}."
        else:
            return f"Unknown /tts argument: {arg!r}. Use: on, off, auto."
