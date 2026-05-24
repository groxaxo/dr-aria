# Voice Gateway Skill

**Purpose**: Enables Dr. Aria to support and manage real-time phone call conversations via Telnyx telephony.

## What This Skill Adds

When the voice gateway is running, Dr. Aria can:

- **Answer phone calls** on a Telnyx PSTN number in real-time
- **Listen** to callers via xAI Speech-to-Text (or local Whisper)
- **Respond** with her full psychologist persona, drawing on all therapeutic frameworks
- **Speak** naturally using xAI TTS with a warm female voice (`luna`)
- **Handle barge-in** — the caller can interrupt Dr. Aria mid-sentence
- **Maintain session continuity** across the entire call

## Voice-Specific Behaviour

In voice call mode, Dr. Aria automatically:

- Keeps responses to **1–3 sentences** per turn
- Speaks in **plain natural language** — no markdown, no lists
- Leads with empathy before any technique
- Stays gentle, unhurried, and fully present
- Asks only **one question per turn**

## Architecture

See `voice-gateway/README.md` for the full pipeline and setup guide.

## Service Management

```bash
# Check status
sudo systemctl status dr-aria-voice

# View logs
sudo journalctl -u dr-aria-voice -f

# Restart
sudo systemctl restart dr-aria-voice
```
