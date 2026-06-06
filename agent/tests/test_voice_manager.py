"""Tests for bridge.voice_manager (Phase 7)."""

from __future__ import annotations

import asyncio
import struct
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.voice_manager import (
    VoiceManager,
    ThinkingTone,
    ReceivedPing,
    StreamingTTSSource,
    TTS_OFF,
    TTS_ON,
    TTS_AUTO,
    AUTO_TTS_MAX_CHARS,
    _DISCORD_FRAME_BYTES,
)


@pytest.fixture
def mock_bot():
    """Mock Discord bot."""
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    bot.fetch_channel = AsyncMock(return_value=MagicMock())
    return bot


@pytest.fixture
def mock_tts():
    """Mock TTSEngine."""
    tts = MagicMock()
    tts.enabled = True
    tts.synthesize = AsyncMock(return_value=b"RIFF" + b"\x00" * 100)
    return tts


@pytest.fixture
def voice_mgr(mock_bot, mock_tts):
    """VoiceManager with mocked dependencies."""
    return VoiceManager(
        bot=mock_bot,
        tts_engine=mock_tts,
        voice_channel_id=123456,
    )


class TestVoiceManagerInit:
    """Basic VoiceManager configuration."""

    def test_default_tts_mode(self, voice_mgr):
        assert voice_mgr.tts_mode == TTS_AUTO

    def test_not_connected_initially(self, voice_mgr):
        assert voice_mgr.is_connected is False

    def test_set_tts_mode_on(self, voice_mgr):
        voice_mgr.set_tts_mode(TTS_ON)
        assert voice_mgr.tts_mode == TTS_ON

    def test_set_tts_mode_off(self, voice_mgr):
        voice_mgr.set_tts_mode(TTS_OFF)
        assert voice_mgr.tts_mode == TTS_OFF

    def test_set_tts_mode_invalid(self, voice_mgr):
        with pytest.raises(ValueError, match="Invalid TTS mode"):
            voice_mgr.set_tts_mode("invalid")

    def test_init_watchdog_state(self, voice_mgr):
        assert voice_mgr._current_sink is None
        assert voice_mgr._watchdog_task is None
        assert voice_mgr._last_packet_time == 0.0

    def test_init_greeting_cache(self, voice_mgr):
        assert voice_mgr._greeting_wav is None

    def test_init_thinking_state(self, voice_mgr):
        assert voice_mgr._thinking_active is False

    def test_voicemanager_has_no_pipeline_attribute_or_method(self, voice_mgr):
        """Guard against re-introduction of the deleted AudioPipeline plumbing.

        Discord voice receive is intentionally absent — VoiceManager only owns
        VAPI/TTS. The dead `_pipeline` attribute and its wiring methods were
        removed in audit-2026-05-15.E.02; this test prevents drift.
        """
        # No `_pipeline` attribute on instances.
        assert not hasattr(voice_mgr, "_pipeline")

        # No pipeline-flavored public or private API on the class.
        forbidden = (
            "_pipeline",
            "_wire_audio_receive",
            "_install_dave_decryption",
            "audio_pipeline",
        )
        for name in forbidden:
            assert not hasattr(voice_mgr, name), (
                f"VoiceManager unexpectedly exposes {name!r}; "
                "AudioPipeline was retired in PR #1773 and pruned in E.02."
            )


class TestVoiceCommands:
    """Slash command handlers for /voice and /tts."""

    @pytest.mark.asyncio
    async def test_voice_join_not_connected(self, voice_mgr):
        # join_channel will fail because mock bot returns None for get_channel
        # and fetch_channel returns a mock that can't connect
        result = await voice_mgr.handle_voice_command("join")
        assert "Could not join" in result or "Joined" in result

    @pytest.mark.asyncio
    async def test_voice_leave_not_connected(self, voice_mgr):
        result = await voice_mgr.handle_voice_command("leave")
        assert "Not in a voice channel" in result

    @pytest.mark.asyncio
    async def test_voice_unknown_arg(self, voice_mgr):
        result = await voice_mgr.handle_voice_command("dance")
        assert "Unknown" in result

    @pytest.mark.asyncio
    async def test_tts_set_on(self, voice_mgr):
        result = await voice_mgr.handle_tts_command("on")
        assert "on" in result

    @pytest.mark.asyncio
    async def test_tts_set_off(self, voice_mgr):
        result = await voice_mgr.handle_tts_command("off")
        assert "off" in result

    @pytest.mark.asyncio
    async def test_tts_set_auto(self, voice_mgr):
        result = await voice_mgr.handle_tts_command("auto")
        assert "auto" in result

    @pytest.mark.asyncio
    async def test_tts_status(self, voice_mgr):
        result = await voice_mgr.handle_tts_command("")
        assert "currently" in result

    @pytest.mark.asyncio
    async def test_tts_unknown_arg(self, voice_mgr):
        result = await voice_mgr.handle_tts_command("loud")
        assert "Unknown" in result


class TestPlayTTS:
    """TTS playback logic."""

    @pytest.mark.asyncio
    async def test_play_tts_not_connected(self, voice_mgr):
        result = await voice_mgr.play_tts("Hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_play_tts_mode_off(self, voice_mgr):
        voice_mgr.set_tts_mode(TTS_OFF)
        result = await voice_mgr.play_tts("Hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_play_tts_no_engine(self, mock_bot):
        mgr = VoiceManager(bot=mock_bot, tts_engine=None)
        result = await mgr.play_tts("Hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_play_tts_auto_long_text_skipped(self, voice_mgr):
        long_text = "x" * (AUTO_TTS_MAX_CHARS + 1)
        result = await voice_mgr.play_tts(long_text)
        assert result is False


class TestAutoJoin:
    """Auto-join/leave on voice state changes."""

    @pytest.mark.asyncio
    async def test_ignores_non_operator(self, voice_mgr):
        member = MagicMock()
        member.id = 999
        before = MagicMock()
        before.channel = None
        after = MagicMock()
        after.channel = MagicMock()
        after.channel.id = 123456

        with patch.object(
            voice_mgr, "join_channel", new_callable=AsyncMock
        ) as mock_join, patch.object(
            voice_mgr, "leave_channel", new_callable=AsyncMock
        ) as mock_leave:
            await voice_mgr.on_voice_state_update(12345, member, before, after)
            # Should not have tried to join or leave — non-operator id is filtered
            mock_join.assert_not_called()
            mock_leave.assert_not_called()

    @pytest.mark.asyncio
    async def test_operator_leave(self, voice_mgr):
        member = MagicMock()
        member.id = 12345
        before = MagicMock()
        before.channel = MagicMock()
        after = MagicMock()
        after.channel = None

        # Not connected, so leave is a no-op
        assert voice_mgr.is_connected is False
        with patch.object(
            voice_mgr, "leave_channel", new_callable=AsyncMock
        ) as mock_leave:
            await voice_mgr.on_voice_state_update(12345, member, before, after)
            # leave_channel must not be called when not connected
            mock_leave.assert_not_called()


class TestLeaveChannel:
    """Channel disconnect."""

    @pytest.mark.asyncio
    async def test_leave_cancels_watchdog(self, voice_mgr):
        voice_mgr._voice_client = MagicMock()
        voice_mgr._voice_client.is_connected.return_value = True
        voice_mgr._voice_client.disconnect = AsyncMock()
        # Create a mock watchdog task
        mock_task = MagicMock()
        mock_task.done.return_value = False
        voice_mgr._watchdog_task = mock_task
        await voice_mgr.leave_channel()
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_leave_clears_sink_reference(self, voice_mgr):
        voice_mgr._voice_client = MagicMock()
        voice_mgr._voice_client.is_connected.return_value = True
        voice_mgr._voice_client.disconnect = AsyncMock()
        voice_mgr._current_sink = MagicMock()
        await voice_mgr.leave_channel()
        assert voice_mgr._current_sink is None

    @pytest.mark.asyncio
    async def test_leave_stops_thinking_sound(self, voice_mgr):
        voice_mgr._voice_client = MagicMock()
        voice_mgr._voice_client.is_connected.return_value = True
        voice_mgr._voice_client.disconnect = AsyncMock()
        voice_mgr._thinking_active = True
        await voice_mgr.leave_channel()
        assert voice_mgr._thinking_active is False


class TestThinkingTone:
    """ThinkingTone AudioSource."""

    def test_is_not_opus(self):
        tone = ThinkingTone()
        assert tone.is_opus() is False

    def test_read_returns_correct_size(self):
        tone = ThinkingTone()
        frame = tone.read()
        assert len(frame) == _DISCORD_FRAME_BYTES

    def test_read_returns_bytes(self):
        tone = ThinkingTone()
        frame = tone.read()
        assert isinstance(frame, bytes)

    def test_stop_causes_empty_read(self):
        tone = ThinkingTone()
        tone.stop()
        assert tone.read() == b""

    def test_cleanup_causes_empty_read(self):
        tone = ThinkingTone()
        tone.cleanup()
        assert tone.read() == b""

    def test_output_is_not_silence(self):
        tone = ThinkingTone()
        frame = tone.read()
        # Unpack as int16 samples and verify not all zero
        n = len(frame) // 2
        samples = struct.unpack(f"<{n}h", frame)
        assert any(s != 0 for s in samples)

    def test_amplitude_within_bounds(self):
        """Samples should not exceed the configured amplitude."""
        tone = ThinkingTone()
        # Read multiple frames to cover a full pulse cycle
        for _ in range(100):
            frame = tone.read()
            n = len(frame) // 2
            samples = struct.unpack(f"<{n}h", frame)
            for s in samples:
                # With amplitude 0.15, max should be ~4915 (0.15 * 32767)
                assert abs(s) <= 5000, f"Sample {s} exceeds expected amplitude"

    def test_successive_reads_produce_different_data(self):
        """Consecutive frames should differ (sine wave progresses)."""
        tone = ThinkingTone()
        frame1 = tone.read()
        frame2 = tone.read()
        # Very unlikely to be identical for a sine wave
        assert frame1 != frame2


class TestReceivedPing:
    """ReceivedPing AudioSource — short chirp."""

    def test_is_not_opus(self):
        ping = ReceivedPing()
        assert ping.is_opus() is False

    def test_first_read_returns_correct_size(self):
        ping = ReceivedPing()
        frame = ping.read()
        assert len(frame) == _DISCORD_FRAME_BYTES

    def test_finishes_after_duration(self):
        ping = ReceivedPing()
        frames = 0
        while True:
            data = ping.read()
            if not data:
                break
            frames += 1
            if frames > 100:
                break  # safety
        # 150ms at 20ms/frame = ~8 frames
        assert 5 <= frames <= 15

    def test_stop_causes_empty_read(self):
        ping = ReceivedPing()
        ping.stop()
        assert ping.read() == b""

    def test_output_is_not_silence(self):
        ping = ReceivedPing()
        frame = ping.read()
        n = len(frame) // 2
        samples = struct.unpack(f"<{n}h", frame)
        assert any(s != 0 for s in samples)


class TestThinkingSound:
    """VoiceManager thinking sound start/stop."""

    def test_start_thinking_not_connected(self, voice_mgr):
        voice_mgr.start_thinking_sound()
        assert voice_mgr._thinking_active is False

    def test_start_thinking_when_connected(self, voice_mgr):
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        voice_mgr._voice_client = vc
        voice_mgr.start_thinking_sound()
        assert voice_mgr._thinking_active is True
        vc.play.assert_called_once()
        # Verify it's a ThinkingTone instance
        arg = vc.play.call_args[0][0]
        assert isinstance(arg, ThinkingTone)

    def test_start_thinking_skips_when_audio_playing(self, voice_mgr):
        """Don't interrupt greeting/TTS with thinking tone."""
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = True
        voice_mgr._voice_client = vc
        voice_mgr.start_thinking_sound()
        assert voice_mgr._thinking_active is False
        vc.play.assert_not_called()

    def test_start_thinking_idempotent(self, voice_mgr):
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        voice_mgr._voice_client = vc
        voice_mgr.start_thinking_sound()
        voice_mgr.start_thinking_sound()  # second call should be no-op
        assert vc.play.call_count == 1

    def test_stop_thinking_when_active(self, voice_mgr):
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = True
        voice_mgr._voice_client = vc
        voice_mgr._thinking_active = True
        voice_mgr.stop_thinking_sound()
        assert voice_mgr._thinking_active is False
        # Uses stop_playing() to avoid killing the audio listener
        vc.stop_playing.assert_called_once()

    def test_stop_thinking_when_not_active(self, voice_mgr):
        vc = MagicMock()
        voice_mgr._voice_client = vc
        voice_mgr.stop_thinking_sound()  # should be no-op
        vc.stop.assert_not_called()

    def test_on_transcription_dispatched_starts_thinking(self, voice_mgr):
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        voice_mgr._voice_client = vc
        voice_mgr._on_transcription_dispatched()
        assert voice_mgr._thinking_active is True


class TestGreeting:
    """Voice greeting on join."""

    @pytest.mark.asyncio
    async def test_greeting_skipped_without_tts(self, mock_bot):
        mgr = VoiceManager(bot=mock_bot, tts_engine=None)
        with patch.object(mgr, "play_audio", new_callable=AsyncMock) as mock_play:
            await mgr._play_greeting()
            # No TTS engine — must not attempt audio playback or cache a greeting
            mock_play.assert_not_called()
            assert mgr._greeting_wav is None

    @pytest.mark.asyncio
    async def test_greeting_caches_wav(self, voice_mgr, mock_tts):
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        voice_mgr._voice_client = vc

        with patch.object(voice_mgr, "play_audio", new_callable=AsyncMock, return_value=True):
            await voice_mgr._play_greeting()
            assert voice_mgr._greeting_wav is not None

            # Second call should not re-synthesize
            mock_tts.synthesize.reset_mock()
            await voice_mgr._play_greeting()
            mock_tts.synthesize.assert_not_called()

    @pytest.mark.asyncio
    async def test_greeting_calls_play_audio(self, voice_mgr, mock_tts):
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        voice_mgr._voice_client = vc

        with patch.object(voice_mgr, "play_audio", new_callable=AsyncMock, return_value=True) as mock_play:
            await voice_mgr._play_greeting()
            mock_play.assert_called_once()


class TestIdleLockCheck:
    """Idle loop skips timeout when voice_lock is held."""

    @pytest.mark.asyncio
    async def test_idle_loop_skips_when_locked(self, voice_mgr):
        """When voice_lock is held, idle loop should not disconnect."""
        vc = MagicMock()
        vc.is_connected.return_value = True
        voice_mgr._voice_client = vc

        # Set activity far in the past (would normally trigger timeout)
        voice_mgr._last_activity = time.monotonic() - 1000
        voice_mgr._idle_timeout_s = 1.0  # short timeout

        # Acquire the lock to simulate in-progress processing
        async with voice_mgr._voice_lock:
            # Run one iteration of idle loop by calling it with a very short sleep
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # Make sleep raise after first call to exit loop
                call_count = 0

                async def limited_sleep(duration):
                    nonlocal call_count
                    call_count += 1
                    if call_count >= 2:
                        raise asyncio.CancelledError()

                mock_sleep.side_effect = limited_sleep
                await voice_mgr._idle_loop()

        # Should NOT have called leave_channel (lock was held)
        vc.disconnect.assert_not_called()


class TestWatchdog:
    """Audio receive watchdog."""

    @pytest.mark.asyncio
    async def test_start_watchdog_creates_task(self, voice_mgr):
        voice_mgr._start_watchdog()
        assert voice_mgr._watchdog_task is not None
        voice_mgr._cancel_watchdog()

    @pytest.mark.asyncio
    async def test_cancel_watchdog(self, voice_mgr):
        voice_mgr._start_watchdog()
        task = voice_mgr._watchdog_task
        voice_mgr._cancel_watchdog()
        assert voice_mgr._watchdog_task is None
        # Let the cancellation propagate
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.cancelled()


class TestStreamingTTSSource:
    """StreamingTTSSource: queue-based audio source."""

    def test_is_not_opus(self):
        source = StreamingTTSSource()
        assert source.is_opus() is False

    def test_read_silence_when_empty_and_not_finished(self):
        source = StreamingTTSSource()
        frame = source.read()
        assert len(frame) == _DISCORD_FRAME_BYTES
        assert frame == b"\x00" * _DISCORD_FRAME_BYTES

    def test_read_empty_when_finished_and_empty(self):
        source = StreamingTTSSource()
        source.finish()
        frame = source.read()
        assert frame == b""

    def test_add_chunk_and_read(self):
        source = StreamingTTSSource()
        # Add exactly one Discord frame of data
        pcm = b"\x01" * _DISCORD_FRAME_BYTES
        source.add_chunk(pcm)
        frame = source.read()
        assert frame == pcm

    def test_reads_multiple_frames_from_chunk(self):
        source = StreamingTTSSource()
        # Add two frames worth of data
        pcm = b"\x02" * (_DISCORD_FRAME_BYTES * 2)
        source.add_chunk(pcm)
        frame1 = source.read()
        frame2 = source.read()
        assert len(frame1) == _DISCORD_FRAME_BYTES
        assert len(frame2) == _DISCORD_FRAME_BYTES
        assert frame1 == b"\x02" * _DISCORD_FRAME_BYTES

    def test_reads_across_chunks(self):
        source = StreamingTTSSource()
        source.add_chunk(b"\x01" * _DISCORD_FRAME_BYTES)
        source.add_chunk(b"\x02" * _DISCORD_FRAME_BYTES)
        frame1 = source.read()
        frame2 = source.read()
        assert frame1 == b"\x01" * _DISCORD_FRAME_BYTES
        assert frame2 == b"\x02" * _DISCORD_FRAME_BYTES

    def test_finish_after_all_data_read(self):
        source = StreamingTTSSource()
        source.add_chunk(b"\x01" * _DISCORD_FRAME_BYTES)
        source.finish()
        frame1 = source.read()
        assert len(frame1) == _DISCORD_FRAME_BYTES
        # Now should return empty (finished and no more data)
        frame2 = source.read()
        assert frame2 == b""

    def test_short_final_chunk_padded(self):
        source = StreamingTTSSource()
        # Add less than one frame
        source.add_chunk(b"\x03" * 100)
        source.finish()
        frame = source.read()
        assert len(frame) == _DISCORD_FRAME_BYTES
        assert frame[:100] == b"\x03" * 100
        assert frame[100:] == b"\x00" * (_DISCORD_FRAME_BYTES - 100)

    def test_stop_causes_empty_read(self):
        source = StreamingTTSSource()
        source.add_chunk(b"\x01" * _DISCORD_FRAME_BYTES)
        source.stop()
        assert source.read() == b""

    def test_cleanup_causes_empty_read(self):
        source = StreamingTTSSource()
        source.add_chunk(b"\x01" * _DISCORD_FRAME_BYTES)
        source.cleanup()
        assert source.read() == b""


class TestPlayTTSStreaming:
    """VoiceManager.play_tts_streaming()."""

    @pytest.mark.asyncio
    async def test_streaming_not_connected(self, voice_mgr):
        result = await voice_mgr.play_tts_streaming("Hello. World.")
        assert result is False

    @pytest.mark.asyncio
    async def test_streaming_no_tts_engine(self, mock_bot):
        mgr = VoiceManager(bot=mock_bot, tts_engine=None)
        result = await mgr.play_tts_streaming("Hello. World.")
        assert result is False

    @pytest.mark.asyncio
    async def test_streaming_single_sentence_falls_back(self, voice_mgr, mock_tts):
        """Single sentence should fall back to regular play_tts."""
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        voice_mgr._voice_client = vc

        with patch.object(voice_mgr, "play_tts", new_callable=AsyncMock, return_value=True) as mock_play:
            result = await voice_mgr.play_tts_streaming("Just one sentence", sentences=["Just one sentence"])
            mock_play.assert_called_once_with("Just one sentence")

    @pytest.mark.asyncio
    async def test_streaming_starts_playback_after_first_sentence(self, voice_mgr, mock_tts):
        """Should start playing after first sentence is synthesized."""
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        voice_mgr._voice_client = vc

        # Mock _wav_to_discord_pcm to return some PCM data
        with patch("bridge.voice_manager._wav_to_discord_pcm", new_callable=AsyncMock) as mock_pcm:
            mock_pcm.return_value = b"\x00" * _DISCORD_FRAME_BYTES
            result = await voice_mgr.play_tts_streaming(
                "Hello world. How are you.",
                sentences=["Hello world.", "How are you."],
            )
            assert result is True
            vc.play.assert_called_once()
            # The source should be a StreamingTTSSource
            played_source = vc.play.call_args[0][0]
            assert isinstance(played_source, StreamingTTSSource)

    @pytest.mark.asyncio
    async def test_streaming_stops_thinking_sound(self, voice_mgr, mock_tts):
        """Should clear _thinking_active when streaming starts."""
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        voice_mgr._voice_client = vc
        voice_mgr._thinking_active = True

        with patch("bridge.voice_manager._wav_to_discord_pcm", new_callable=AsyncMock) as mock_pcm:
            mock_pcm.return_value = b"\x00" * _DISCORD_FRAME_BYTES
            await voice_mgr.play_tts_streaming(
                "Hello. World.",
                sentences=["Hello.", "World."],
            )
            assert voice_mgr._thinking_active is False

    @pytest.mark.asyncio
    async def test_play_tts_uses_streaming_for_multi_sentence(self, voice_mgr, mock_tts):
        """play_tts should delegate to play_tts_streaming for multi-sentence text."""
        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        voice_mgr._voice_client = vc

        with patch.object(voice_mgr, "play_tts_streaming", new_callable=AsyncMock, return_value=True) as mock_stream:
            result = await voice_mgr.play_tts("Hello world. How are you today.")
            mock_stream.assert_called_once()
