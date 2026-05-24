"""
Dr. Aria Voice Gateway
======================
FastAPI server that handles Telnyx webhooks and bidirectional media WebSocket.

Pipeline:
  Telnyx PSTN → WebSocket (PCMA) → VAD → xAI STT → grok-3-mini → xAI TTS → Telnyx
"""
from __future__ import annotations
import asyncio
import base64
import json
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

import config as cfg
from asr import AsrClient
from telephony import (
    pcma_to_pcm16,
    pcmu_to_pcm16,
    pcma_frames_to_wav_16k,
    chunk_pcma_for_telnyx,
    pcm16_to_pcma,
    TELNYX_FRAME_SAMPLES,
)
from tts import TtsClient, text_to_audio_chunks
from session import ActiveCall, create_call, get_call, remove_call

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dr_aria.server")


# ── Telnyx REST helpers ────────────────────────────────────────────────────────

TELNYX_API = "https://api.telnyx.com/v2"


async def telnyx_post(path: str, body: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {cfg.TELNYX_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{TELNYX_API}{path}", headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()


async def answer_call(call_control_id: str) -> None:
    await telnyx_post(f"/calls/{call_control_id}/actions/answer", {})
    logger.info("Answered call %s", call_control_id)


async def start_media_stream(call_control_id: str) -> None:
    """Start bidirectional media stream to our WebSocket endpoint."""
    if not cfg.TELNYX_MEDIA_WS_URL:
        logger.warning("TELNYX_MEDIA_WS_URL not set — cannot start media stream")
        return
    await telnyx_post(
        f"/calls/{call_control_id}/actions/streaming_start",
        {
            "stream_url": cfg.TELNYX_MEDIA_WS_URL,
            "stream_bidirectional_mode": "rtp",
            "stream_bidirectional_codec": cfg.TELNYX_CODEC,
        },
    )
    logger.info("Media stream started for %s → %s", call_control_id, cfg.TELNYX_MEDIA_WS_URL)


async def hangup_call(call_control_id: str) -> None:
    try:
        await telnyx_post(f"/calls/{call_control_id}/actions/hangup", {})
    except Exception:
        pass


# ── App ────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Dr. Aria Voice Gateway starting — model=%s voice=%s codec=%s port=%d",
        cfg.LLM_MODEL, cfg.TTS_VOICE, cfg.TTS_CODEC, cfg.PORT,
    )
    yield
    logger.info("Dr. Aria Voice Gateway shutting down")


app = FastAPI(title="Dr. Aria Voice Gateway", lifespan=lifespan)

_asr = AsrClient()
_tts = TtsClient()


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "model": cfg.LLM_MODEL, "voice": cfg.TTS_VOICE}


# ── Telnyx Webhook ─────────────────────────────────────────────────────────────

@app.post("/telnyx/events")
async def telnyx_events(request: Request):
    """Telnyx Call Control webhook endpoint."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_request"}, status_code=400)

    data = body.get("data", {})
    event_type: str = data.get("event_type", "")
    payload: dict = data.get("payload", {})

    call_control_id: str = payload.get("call_control_id", "")
    call_leg_id: str = payload.get("call_leg_id", "")
    call_session_id: str = payload.get("call_session_id", call_leg_id)
    from_number: str = payload.get("from", "unknown")

    logger.info("Telnyx event: %s | call=%s", event_type, call_session_id or call_control_id)

    if event_type == "call.initiated":
        direction = payload.get("direction", "")
        if direction == "incoming":
            # Create session state immediately
            call_id = call_session_id or call_control_id
            create_call(call_id, from_number)
            # Answer the call
            if call_control_id:
                asyncio.create_task(answer_call(call_control_id))

    elif event_type == "call.answered":
        call_id = call_session_id or call_control_id
        # Start bidirectional media stream
        if call_control_id:
            asyncio.create_task(start_media_stream(call_control_id))

    elif event_type in ("call.hangup", "call.disconnected"):
        call_id = call_session_id or call_control_id
        remove_call(call_id)

    elif event_type == "call.recording.saved":
        logger.info("Recording saved for %s", call_session_id)

    return JSONResponse({"received": True})


# ── Media WebSocket ────────────────────────────────────────────────────────────

async def _send_telnyx_media(ws: WebSocket, stream_id: str, pcma_b64: str) -> None:
    await ws.send_text(json.dumps({
        "event": "media",
        "stream_id": stream_id,
        "media": {"payload": pcma_b64},
    }))


async def _send_telnyx_clear(ws: WebSocket, stream_id: str) -> None:
    await ws.send_text(json.dumps({"event": "clear", "stream_id": stream_id}))


async def _send_telnyx_mark(ws: WebSocket, stream_id: str, name: str) -> None:
    await ws.send_text(json.dumps({
        "event": "mark",
        "stream_id": stream_id,
        "mark": {"name": name},
    }))


async def _play_greeting(call: ActiveCall, ws: WebSocket) -> None:
    """Send Dr. Aria's greeting before caller speaks."""
    greeting_text = []
    async for token in call.session.greeting():
        greeting_text.append(token)

    full_greeting = "".join(greeting_text).strip()
    if not full_greeting:
        full_greeting = "Hello, you've reached Dr. Aria. How can I help you today?"

    call.add_aria_line(full_greeting)
    logger.info("Greeting: %s", full_greeting)

    async def _greeting_token_stream():
        for token in full_greeting.split():
            yield token + " "

    async for audio_chunk in text_to_audio_chunks(
        _greeting_token_stream(), _tts, abort_event=call.tts_abort
    ):
        for frame in chunk_pcma_for_telnyx(audio_chunk):
            b64 = base64.b64encode(frame).decode()
            await _send_telnyx_media(ws, call.stream_id, b64)
            call.frames_sent += 1


async def _handle_caller_utterance(call: ActiveCall, ws: WebSocket, pcm16_audio: bytes) -> None:
    """ASR → LLM → TTS pipeline for one caller utterance."""
    if call.processing_lock.locked():
        logger.debug("Utterance dropped — previous turn still processing")
        return

    async with call.processing_lock:
        call.abort_tts()
        await _send_telnyx_clear(ws, call.stream_id)
        call.reset_tts_abort()

        t0 = time.monotonic()

        # ASR
        from telephony import build_wav, resample_8k_to_16k
        wav = build_wav(resample_8k_to_16k(pcm16_audio), sample_rate=16000)
        transcript = await _asr.transcribe(wav)

        asr_ms = int((time.monotonic() - t0) * 1000)
        logger.info("ASR %.0fms | %r", asr_ms, transcript)

        if not transcript:
            logger.debug("Empty transcript, skipping response")
            return

        call.add_caller_line(transcript)

        # LLM + TTS streaming
        response_tokens: list[str] = []

        async def _token_stream():
            async for token in call.session.respond(transcript):
                response_tokens.append(token)
                yield token

        first_audio_at: float | None = None
        async for audio_chunk in text_to_audio_chunks(
            _token_stream(), _tts, abort_event=call.tts_abort
        ):
            if first_audio_at is None:
                first_audio_at = time.monotonic()
                total_ms = int((first_audio_at - t0) * 1000)
                logger.info(
                    "First audio ready | ASR+LLM+TTS=%dms",
                    total_ms,
                )
            for frame in chunk_pcma_for_telnyx(audio_chunk):
                if call.tts_abort.is_set():
                    break
                b64 = base64.b64encode(frame).decode()
                await _send_telnyx_media(ws, call.stream_id, b64)
                call.frames_sent += 1

        full_response = "".join(response_tokens).strip()
        if full_response:
            call.add_aria_line(full_response)
            logger.info("Response: %s", full_response[:120])


@app.websocket("/ws/media")
async def media_websocket(ws: WebSocket):
    """
    Telnyx bidirectional media WebSocket endpoint.
    Telnyx connects here after streaming_start is called.
    """
    await ws.accept()
    logger.info("Media WebSocket connected")

    call: ActiveCall | None = None
    greeting_sent = False

    try:
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event = msg.get("event")

            if event == "connected":
                logger.info("Telnyx stream connected: %s", msg.get("protocol"))

            elif event == "start":
                start = msg.get("start", {})
                stream_id = start.get("stream_id", "")
                call_session_id = start.get("call_session_id", "")
                custom_params = start.get("custom_parameters", {})

                call = get_call(call_session_id)
                if not call:
                    # Fallback: create session from stream metadata
                    call = create_call(
                        call_session_id or stream_id,
                        custom_params.get("from", "unknown"),
                    )

                call.stream_id = stream_id
                call.codec = start.get("media_format", {}).get("encoding", cfg.TELNYX_CODEC)
                logger.info(
                    "Stream started | id=%s session=%s codec=%s",
                    stream_id, call_session_id, call.codec,
                )

                # Send greeting immediately after stream starts
                if not greeting_sent:
                    greeting_sent = True
                    asyncio.create_task(_play_greeting(call, ws))

            elif event == "media":
                if call is None:
                    continue

                media = msg.get("media", {})
                track = media.get("track", "inbound")
                if track != "inbound":
                    continue

                payload_b64 = media.get("payload", "")
                if not payload_b64:
                    continue

                raw_bytes = base64.b64decode(payload_b64)
                call.frames_received += 1

                # Decode to PCM16 based on codec
                codec = call.codec.upper()
                if codec in ("PCMA", "ALAW", "G711A"):
                    pcm16_frame = pcma_to_pcm16(raw_bytes)
                elif codec in ("PCMU", "MULAW", "G711U", "G711"):
                    pcm16_frame = pcmu_to_pcm16(raw_bytes)
                else:
                    pcm16_frame = raw_bytes  # assume PCM16 already

                # Feed to VAD
                if len(pcm16_frame) == TELNYX_FRAME_SAMPLES * 2:
                    utterance_audio = call.vad.feed(pcm16_frame)
                    if utterance_audio is not None:
                        # Barge-in: if TTS playing, stop it
                        if call.frames_sent > 0:
                            call.abort_tts()
                        asyncio.create_task(
                            _handle_caller_utterance(call, ws, utterance_audio)
                        )

            elif event == "stop":
                logger.info("Stream stopped")
                if call:
                    drained = call.vad.drain()
                    if drained:
                        asyncio.create_task(
                            _handle_caller_utterance(call, ws, drained)
                        )
                break

            elif event == "mark":
                pass  # mark events are acknowledgements, ignore

    except WebSocketDisconnect:
        logger.info("Media WebSocket disconnected")
    except Exception:
        logger.exception("Media WebSocket error")
    finally:
        if call:
            remove_call(call.call_id)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=cfg.HOST,
        port=cfg.PORT,
        log_level=cfg.LOG_LEVEL,
    )
