"""Per-call session state management."""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field

from agent import CallSession, get_agent
from vad import VoiceActivityDetector

logger = logging.getLogger(__name__)


@dataclass
class TranscriptLine:
    speaker: str  # "caller" or "aria"
    text: str
    at_sec: float


@dataclass
class ActiveCall:
    call_id: str
    caller_phone: str
    started_at: float = field(default_factory=time.time)

    # Components
    session: CallSession = field(init=False)
    vad: VoiceActivityDetector = field(init=False)

    # Runtime state
    stream_id: str = ""
    codec: str = "PCMA"
    transcript: list[TranscriptLine] = field(default_factory=list)

    # Concurrency
    tts_abort: asyncio.Event = field(default_factory=asyncio.Event)
    processing_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Stats
    frames_received: int = 0
    frames_sent: int = 0

    def __post_init__(self) -> None:
        self.session = get_agent().new_session()
        self.vad = VoiceActivityDetector()

    def elapsed_sec(self) -> float:
        return time.time() - self.started_at

    def add_caller_line(self, text: str) -> None:
        self.transcript.append(
            TranscriptLine("caller", text, self.elapsed_sec())
        )

    def add_aria_line(self, text: str) -> None:
        self.transcript.append(
            TranscriptLine("aria", text, self.elapsed_sec())
        )

    def abort_tts(self) -> None:
        """Signal any in-progress TTS synthesis to stop (barge-in)."""
        self.tts_abort.set()

    def reset_tts_abort(self) -> None:
        self.tts_abort.clear()


_active_calls: dict[str, ActiveCall] = {}


def create_call(call_id: str, caller_phone: str) -> ActiveCall:
    call = ActiveCall(call_id=call_id, caller_phone=caller_phone)
    _active_calls[call_id] = call
    logger.info("Call created: %s from %s", call_id, caller_phone)
    return call


def get_call(call_id: str) -> ActiveCall | None:
    return _active_calls.get(call_id)


def remove_call(call_id: str) -> None:
    call = _active_calls.pop(call_id, None)
    if call:
        duration = call.elapsed_sec()
        logger.info(
            "Call ended: %s | duration=%.1fs | turns=%d",
            call_id,
            duration,
            len(call.transcript),
        )
