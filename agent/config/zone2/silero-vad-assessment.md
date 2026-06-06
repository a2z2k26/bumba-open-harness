# Silero VAD Integration Assessment

**Date:** March 2026
**Status:** Deferred — webrtcvad is sufficient for current use case

## Current State

- **Primary VAD:** `webrtcvad` library, aggressiveness mode 2, runs in-process (<1ms per frame)
- **Fallback:** RMS energy threshold at -40 dBFS
- **Silero VAD:** Docker container exists at `docs/voice-patches/Dockerfile.silero-vad`, runs FastAPI on port 8200

## Assessment Criteria

### 1. Latency

| Backend | Latency per 20ms frame | Method |
|---------|----------------------|--------|
| webrtcvad | <0.1ms | In-process C library |
| Silero HTTP | ~5-20ms | HTTP POST to localhost container |

**Verdict:** webrtcvad is 50-200x faster. For real-time VAD at 48kHz (50 frames/sec), the HTTP round-trip adds measurable latency. VAD must run on every audio frame — this is the most latency-sensitive part of the pipeline.

### 2. Accuracy

webrtcvad at mode 2 performs well for:
- Single speaker in quiet room (Discord voice channel)
- Clear speech detection with <1s onset delay
- Silence detection at 1.25s threshold

Known limitations:
- Can false-trigger on background noise (music, TV)
- Misses very quiet speech at -40 dBFS threshold

Silero would be better for:
- Noisy environments (cafes, outdoor)
- Multi-speaker differentiation
- Confidence scores for adaptive thresholds

**Verdict:** For the operator's use case (home office, single speaker, quiet environment), webrtcvad is adequate. Silero's accuracy advantages apply mainly to noisy environments we don't expect.

### 3. Resource Usage

| Backend | CPU | Memory | Dependency |
|---------|-----|--------|-----------|
| webrtcvad | Negligible | ~1MB | pip package |
| Silero | Continuous Docker container | ~200MB | Docker + PyTorch |

**Verdict:** webrtcvad wins on resource efficiency by a wide margin.

## Decision

**Do not integrate Silero VAD at this time.**

Reasons:
1. webrtcvad latency is 50-200x better for the real-time VAD use case
2. Single-speaker quiet environment doesn't need Silero's accuracy
3. Docker container overhead is unnecessary for a pip-installable alternative
4. Adding an HTTP dependency to the most latency-sensitive pipeline stage is risky

## When to Revisit

- If the operator frequently uses voice in noisy environments
- If false triggers become a recurring problem
- If we add multi-speaker support (Zone 4 departments)
- If Silero releases a lightweight in-process Python API (no HTTP)

## Fallback Chain (current, keep as-is)

1. webrtcvad (if installed) → primary, in-process
2. RMS energy threshold → fallback, always available
