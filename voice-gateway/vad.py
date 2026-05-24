"""Voice Activity Detection using webrtcvad."""
from __future__ import annotations
import webrtcvad

import config as cfg

FRAME_BYTES = 320  # 20ms at 8kHz, 16-bit PCM = 160 samples × 2 bytes


class VoiceActivityDetector:
    """
    Accumulates 20ms PCM16 frames and detects utterance boundaries.

    An utterance is:
      - Started when VAD detects speech for MIN_SPEECH_MS consecutive ms.
      - Ended when VAD detects silence for SILENCE_MS consecutive ms after speech.
    """

    def __init__(
        self,
        mode: int = cfg.VAD_MODE,
        silence_ms: int = cfg.VAD_SILENCE_MS,
        min_speech_ms: int = cfg.VAD_MIN_SPEECH_MS,
        sample_rate: int = 8000,
    ) -> None:
        self._vad = webrtcvad.Vad(mode)
        self._silence_ms = silence_ms
        self._min_speech_ms = min_speech_ms
        self._sample_rate = sample_rate
        self._frame_ms = 20
        self._frame_bytes = FRAME_BYTES

        self._speech_frames: list[bytes] = []
        self._silence_frames_count: int = 0
        self._speech_frames_count: int = 0
        self._triggered: bool = False       # utterance in progress

    def feed(self, pcm16_frame: bytes) -> bytes | None:
        """
        Feed a 20ms 8kHz PCM16 frame.
        Returns accumulated PCM16 audio if utterance ended, else None.
        """
        if len(pcm16_frame) != self._frame_bytes:
            return None

        is_speech = self._vad.is_speech(pcm16_frame, self._sample_rate)

        if not self._triggered:
            if is_speech:
                self._speech_frames_count += 1
                self._speech_frames.append(pcm16_frame)
                if self._speech_frames_count * self._frame_ms >= self._min_speech_ms:
                    self._triggered = True
                    self._silence_frames_count = 0
            else:
                # Pre-speech: keep last few frames as context
                self._speech_frames = self._speech_frames[-3:]
                self._speech_frames_count = 0
        else:
            self._speech_frames.append(pcm16_frame)
            if is_speech:
                self._silence_frames_count = 0
            else:
                self._silence_frames_count += 1
                silence_elapsed_ms = self._silence_frames_count * self._frame_ms
                if silence_elapsed_ms >= self._silence_ms:
                    audio = b"".join(self._speech_frames)
                    self.reset()
                    return audio

        return None

    def reset(self) -> None:
        """Reset state after utterance is consumed."""
        self._speech_frames = []
        self._silence_frames_count = 0
        self._speech_frames_count = 0
        self._triggered = False

    @property
    def is_active(self) -> bool:
        """True if an utterance is currently in progress."""
        return self._triggered

    def drain(self) -> bytes | None:
        """Force-flush any pending speech (e.g. on call end)."""
        if self._triggered and self._speech_frames:
            audio = b"".join(self._speech_frames)
            self.reset()
            return audio
        self.reset()
        return None
