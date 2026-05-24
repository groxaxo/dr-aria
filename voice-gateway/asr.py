"""xAI STT (speech-to-text) client — OpenAI-compatible /audio/transcriptions."""
from __future__ import annotations
import io
import logging

import httpx

import config as cfg

logger = logging.getLogger(__name__)


class AsrClient:
    """Batch ASR client using OpenAI-compatible /v1/audio/transcriptions."""

    def __init__(
        self,
        base_url: str = cfg.ASR_BASE_URL,
        api_key: str = cfg.ASR_API_KEY,
        model: str = cfg.ASR_MODEL,
        language: str = cfg.ASR_LANGUAGE,
        timeout: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._language = language
        self._timeout = timeout

    async def transcribe(self, wav_bytes: bytes, prompt: str = "") -> str:
        """
        Transcribe WAV audio.  Returns transcript text or empty string.
        wav_bytes: full WAV file (44-byte header + PCM16 data).
        """
        url = f"{self._base_url}/audio/transcriptions"
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        files: dict = {
            "file": ("audio.wav", io.BytesIO(wav_bytes), "audio/wav"),
            "model": (None, self._model),
        }
        if self._language:
            files["language"] = (None, self._language)
        if prompt:
            files["prompt"] = (None, prompt)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, headers=headers, files=files)
                response.raise_for_status()
                data = response.json()

            text: str = ""
            if isinstance(data, dict):
                text = data.get("text") or data.get("transcript") or ""
                if not text and "segments" in data:
                    text = " ".join(
                        seg.get("text", "") for seg in data["segments"] if seg.get("text")
                    )
            elif isinstance(data, str):
                text = data

            transcript = text.strip()
            logger.debug("ASR transcript: %r", transcript)
            return transcript

        except Exception:
            logger.exception("ASR transcription failed")
            return ""
