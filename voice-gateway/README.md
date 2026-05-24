# Dr. Aria Voice Gateway

Real-time phone call interface for the Dr. Aria personal psychologist agent.

## Architecture

```
PSTN Caller → Telnyx → WebSocket → voice-gateway
                                       ↓
                              webrtcvad (VAD)
                                       ↓
                         xAI STT /audio/transcriptions
                                       ↓
                     grok-3-mini + Dr. Aria soul (SOUL.md)
                                       ↓
                       xAI TTS wss://api.x.ai/v1/tts (PCMA)
                                       ↓
                              Telnyx → Caller
```

## Quick Start

### 1. Install dependencies

```bash
cd voice-gateway
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Patch webrtcvad for modern setuptools:
python patch_webrtcvad.py
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your keys:
#   XAI_API_KEY — from console.x.ai
#   TELNYX_API_KEY — from telnyx.com
#   TELNYX_PHONE_NUMBER — your Telnyx number
#   TELNYX_MEDIA_WS_URL — public WSS URL for this server (e.g. via Cloudflare Tunnel or ngrok)
```

### 3. Expose the server publicly

Dr. Aria needs a public HTTPS/WSS URL for Telnyx to reach it. Options:

**Cloudflare Tunnel (recommended — permanent, free)**
```bash
# Install cloudflared and authenticate once:
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
cloudflared tunnel login

# Create tunnel:
cloudflared tunnel create dr-aria-voice
cloudflared tunnel route dns dr-aria-voice voice.your-domain.com

# Run:
cloudflared tunnel run --url http://localhost:8765 dr-aria-voice
```

**ngrok (for development)**
```bash
ngrok http 8765
# Use the https URL from ngrok as TELNYX_MEDIA_WS_URL (replace https:// with wss://)
```

### 4. Configure Telnyx

1. Go to [portal.telnyx.com](https://portal.telnyx.com)
2. Create a Messaging Profile → Call Control Application
3. Set webhook URL to `https://your-domain.com/telnyx/events`
4. Assign your phone number to the application

### 5. Run the gateway

```bash
python server.py
```

Or with systemd (see `voice-gateway.service` installed by `install.sh`).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `XAI_API_KEY` | — | xAI API key (required) |
| `TELNYX_API_KEY` | — | Telnyx API key (required) |
| `TELNYX_PHONE_NUMBER` | — | Your Telnyx number |
| `TELNYX_MEDIA_WS_URL` | — | Public WSS URL for media stream |
| `LLM_MODEL` | `grok-3-mini` | xAI model for conversation |
| `TTS_VOICE` | `luna` | xAI TTS voice (luna, aurora, …) |
| `ASR_BASE_URL` | xAI | Override ASR endpoint (e.g. local whisper) |
| `VAD_SILENCE_MS` | `700` | ms of silence to end an utterance |
| `VOICE_GATEWAY_PORT` | `8765` | Listening port |

## Testing Without a Phone

You can test ASR → LLM → TTS locally without Telnyx:

```bash
python -c "
import asyncio
from agent import get_agent
async def main():
    s = get_agent().new_session()
    async for t in s.respond('Hello, I have been feeling very anxious lately.'):
        print(t, end='', flush=True)
    print()
asyncio.run(main())
"
```

## Latency Budget

Typical latency breakdown on a 1 Gbps connection to xAI:

| Stage | Expected |
|---|---|
| VAD endpoint detection | 700ms (silence threshold) |
| xAI STT | ~300–600ms |
| grok-3-mini first token | ~200–400ms |
| xAI TTS first audio | ~300–500ms |
| **Total to first audio** | **~1.5–2.2s** |

To reduce latency: lower `VAD_SILENCE_MS` to 400–500ms, or use a local whisper ASR.
