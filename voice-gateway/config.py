"""Configuration from environment variables."""
import os
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _required(key: str) -> str:
    value = _env(key)
    if not value:
        raise RuntimeError(f"Required env var {key!r} is not set")
    return value


# ── xAI ────────────────────────────────────────────────────────────────────────
XAI_API_KEY: str = _env("XAI_API_KEY")
XAI_BASE_URL: str = _env("XAI_BASE_URL", "https://api.x.ai/v1")

# ── LLM ────────────────────────────────────────────────────────────────────────
LLM_MODEL: str = _env("LLM_MODEL", "grok-3-mini")
LLM_MAX_TOKENS: int = int(_env("LLM_MAX_TOKENS", "300"))
LLM_TEMPERATURE: float = float(_env("LLM_TEMPERATURE", "0.7"))

# ── ASR ────────────────────────────────────────────────────────────────────────
# Default: xAI STT. Set ASR_BASE_URL to http://host.docker.internal:5092 for local whisper.
ASR_BASE_URL: str = _env("ASR_BASE_URL", XAI_BASE_URL)
ASR_API_KEY: str = _env("ASR_API_KEY", XAI_API_KEY)
ASR_MODEL: str = _env("ASR_MODEL", "whisper-1")  # xAI: whisper-1; parakeet-openai: parakeet-tdt-0.6b-v3-onnx
ASR_LANGUAGE: str = _env("ASR_LANGUAGE", "")  # empty = auto-detect

# ── TTS ────────────────────────────────────────────────────────────────────────
XAI_TTS_WS_URL: str = _env("XAI_TTS_WS_URL", "wss://api.x.ai/v1/tts")
TTS_VOICE: str = _env("TTS_VOICE", "luna")           # female voices: luna, aurora
TTS_CODEC: str = _env("TTS_CODEC", "alaw")           # alaw=PCMA 8kHz — direct Telnyx format
TTS_SAMPLE_RATE: int = int(_env("TTS_SAMPLE_RATE", "8000"))
TTS_MODEL: str = _env("TTS_MODEL", "grok-voice-fast-1.0")
TTS_OPTIMIZE_LATENCY: int = int(_env("TTS_OPTIMIZE_LATENCY", "1"))  # 0 or 1

# ── Telnyx ─────────────────────────────────────────────────────────────────────
TELNYX_API_KEY: str = _env("TELNYX_API_KEY")
TELNYX_PHONE_NUMBER: str = _env("TELNYX_PHONE_NUMBER")   # e.g. +12125551234
TELNYX_WEBHOOK_SECRET: str = _env("TELNYX_WEBHOOK_SECRET", "")
TELNYX_MEDIA_WS_URL: str = _env("TELNYX_MEDIA_WS_URL", "")  # e.g. wss://your-domain/ws/media
TELNYX_AUDIO_CHUNK_MS: int = int(_env("TELNYX_AUDIO_CHUNK_MS", "20"))
TELNYX_CODEC: str = _env("TELNYX_CODEC", "PCMA")  # PCMA or PCMU

# ── Soul ───────────────────────────────────────────────────────────────────────
SOUL_PATH: str = _env("SOUL_PATH", "")

def load_soul() -> str:
    """Load Dr. Aria's soul/system prompt."""
    candidates = [
        SOUL_PATH,
        str(Path.home() / ".hermes" / "SOUL.md"),
        str(Path(__file__).parent.parent / "docker" / "SOUL.md"),
        "/opt/hermes-psychologist/docker/SOUL.md",
    ]
    for path in candidates:
        if path and Path(path).is_file():
            text = Path(path).read_text(encoding="utf-8").strip()
            if text:
                return text
    # Minimal fallback
    return (
        "You are Dr. Aria, a warm and professional psychologist. "
        "You speak in short, empathetic sentences suited for a voice call. "
        "Respond in whatever language the user speaks."
    )

# ── VAD ────────────────────────────────────────────────────────────────────────
VAD_MODE: int = int(_env("VAD_MODE", "2"))          # webrtcvad aggressiveness 0-3
VAD_SILENCE_MS: int = int(_env("VAD_SILENCE_MS", "700"))  # ms of silence = end of utterance
VAD_MIN_SPEECH_MS: int = int(_env("VAD_MIN_SPEECH_MS", "200"))

# ── Server ─────────────────────────────────────────────────────────────────────
HOST: str = _env("VOICE_GATEWAY_HOST", "0.0.0.0")
PORT: int = int(_env("VOICE_GATEWAY_PORT", "8765"))
LOG_LEVEL: str = _env("LOG_LEVEL", "info")
