"""xAI TTS WebSocket client — streams PCMA (G.711 a-law) audio for Telnyx."""
from __future__ import annotations
import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator

import websockets
from websockets.exceptions import WebSocketException

import config as cfg

logger = logging.getLogger(__name__)

_TTS_WS_URL = cfg.XAI_TTS_WS_URL
_DELTA_MAX = 15_000  # characters per text.delta message


def _request_url(voice: str = cfg.TTS_VOICE, codec: str = cfg.TTS_CODEC) -> str:
    import urllib.parse
    params = {
        "voice": voice,
        "codec": codec,
        "sample_rate": str(cfg.TTS_SAMPLE_RATE),
        "optimize_streaming_latency": str(cfg.TTS_OPTIMIZE_LATENCY),
        "text_normalization": "false",
        **({"model": cfg.TTS_MODEL} if cfg.TTS_MODEL else {}),
    }
    return f"{_TTS_WS_URL}?{urllib.parse.urlencode(params)}"


def _text_deltas(text: str) -> list[str]:
    """Split text into ≤15 000-char chunks for xAI TTS protocol."""
    deltas = []
    for offset in range(0, len(text), _DELTA_MAX):
        chunk = text[offset : offset + _DELTA_MAX]
        if chunk:
            deltas.append(chunk)
    return deltas


class TtsClient:
    """
    Streams PCMA (or whatever codec is configured) audio from xAI TTS.

    Usage:
        async for chunk in TtsClient().synthesize("Hello, how are you?"):
            # chunk is bytes of PCMA audio
            send_to_telnyx(base64.b64encode(chunk).decode())
    """

    def __init__(
        self,
        api_key: str = cfg.XAI_API_KEY,
        voice: str = cfg.TTS_VOICE,
        codec: str = cfg.TTS_CODEC,
        first_byte_timeout: float = 8.0,
        request_timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._voice = voice
        self._codec = codec
        self._first_byte_timeout = first_byte_timeout
        self._request_timeout = request_timeout

    async def synthesize(
        self,
        text: str,
        abort_event: asyncio.Event | None = None,
    ) -> AsyncIterator[bytes]:
        """Yield raw audio bytes as they arrive from xAI TTS."""
        text = text.strip()
        if not text:
            return

        url = _request_url(self._voice, self._codec)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        deltas = _text_deltas(text)

        try:
            async with websockets.connect(
                url,
                additional_headers=headers,
                open_timeout=10,
                close_timeout=5,
            ) as ws:
                # Send all text deltas then signal done
                for delta in deltas:
                    await ws.send(json.dumps({"type": "text.delta", "delta": delta}))
                await ws.send(json.dumps({"type": "text.done"}))

                first_chunk_seen = False
                deadline = asyncio.get_event_loop().time() + self._request_timeout

                while True:
                    if abort_event and abort_event.is_set():
                        logger.debug("TTS synthesis aborted")
                        break
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        logger.warning("TTS request timeout")
                        break

                    timeout = (
                        min(self._first_byte_timeout, remaining)
                        if not first_chunk_seen
                        else min(5.0, remaining)
                    )
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except asyncio.TimeoutError:
                        if not first_chunk_seen:
                            logger.warning("TTS first byte timeout after %.1fs", self._first_byte_timeout)
                        break
                    except WebSocketException as exc:
                        logger.error("TTS WebSocket error: %s", exc)
                        break

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type")

                    if msg_type == "audio.delta":
                        delta_b64 = msg.get("delta", "")
                        if not delta_b64:
                            continue
                        first_chunk_seen = True
                        yield base64.b64decode(delta_b64)

                    elif msg_type == "audio.done":
                        break

                    elif msg_type == "error":
                        err_msg = msg.get("message") or msg.get("error") or json.dumps(msg)
                        logger.error("TTS error from xAI: %s", err_msg)
                        break

        except WebSocketException as exc:
            logger.error("TTS WebSocket connection failed: %s", exc)
        except Exception:
            logger.exception("TTS unexpected error")


def should_flush_buffer(text: str) -> bool:
    """Return True when buffered text should be sent to TTS."""
    words = len(text.split())
    return (
        any(text.rstrip().endswith(p) for p in (".", "!", "?", "…"))
        or words >= 14
        or len(text) >= 110
    )


async def text_to_audio_chunks(
    text_stream: AsyncIterator[str],
    tts: TtsClient,
    abort_event: asyncio.Event | None = None,
) -> AsyncIterator[bytes]:
    """
    Given an async stream of text tokens, buffer into sentences and
    yield raw PCMA audio chunks.
    """
    buffer = ""
    async for token in text_stream:
        buffer += token
        if should_flush_buffer(buffer):
            chunk_text = buffer.strip()
            buffer = ""
            if chunk_text:
                async for audio in tts.synthesize(chunk_text, abort_event=abort_event):
                    yield audio
    if buffer.strip():
        async for audio in tts.synthesize(buffer.strip(), abort_event=abort_event):
            yield audio
