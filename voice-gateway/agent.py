"""Dr. Aria voice conversation agent — LLM with soul/system prompt."""
from __future__ import annotations
import asyncio
import logging
from collections.abc import AsyncIterator

import httpx

import config as cfg

logger = logging.getLogger(__name__)

_VOICE_SYSTEM_ADDENDUM = """

## Voice Call Mode

You are now speaking via a PHONE CALL.
- Keep responses SHORT — 1 to 3 sentences maximum per turn.
- Speak naturally, conversationally. No lists, no headers, no markdown.
- Ask only ONE question at a time.
- Pause often and invite the caller to speak.
- Never reference documents, sessions, or "the text above".
- If you don't catch something, gently ask them to repeat.
"""

Message = dict[str, str]


class ConversationHistory:
    """Maintains a bounded conversation history for a call session."""

    def __init__(self, max_turns: int = 30) -> None:
        self._turns: list[Message] = []
        self._max_turns = max_turns

    def add_user(self, text: str) -> None:
        self._turns.append({"role": "user", "content": text})
        self._prune()

    def add_assistant(self, text: str) -> None:
        self._turns.append({"role": "assistant", "content": text})
        self._prune()

    def messages(self) -> list[Message]:
        return list(self._turns)

    def _prune(self) -> None:
        # Keep at most max_turns pairs (user + assistant = 2 messages)
        max_messages = self._max_turns * 2
        if len(self._turns) > max_messages:
            self._turns = self._turns[-max_messages:]

    def clear(self) -> None:
        self._turns.clear()


class DrAriaAgent:
    """
    Dr. Aria voice agent.

    Loads SOUL.md as the system prompt, maintains per-call conversation history,
    and streams responses from grok-3-mini via the xAI OpenAI-compatible API.
    """

    def __init__(self) -> None:
        self._soul = cfg.load_soul()
        self._system_prompt = self._soul + _VOICE_SYSTEM_ADDENDUM
        logger.info(
            "Dr. Aria agent initialized — soul loaded (%d chars)", len(self._soul)
        )

    def new_session(self) -> "CallSession":
        return CallSession(self._system_prompt)


class CallSession:
    """Per-call conversation state."""

    def __init__(self, system_prompt: str) -> None:
        self._system_prompt = system_prompt
        self.history = ConversationHistory()
        self._api_url = f"{cfg.XAI_BASE_URL.rstrip('/')}/chat/completions"

    async def respond(self, caller_text: str) -> AsyncIterator[str]:
        """
        Given a caller utterance, stream Dr. Aria's response tokens.
        Also updates history with both caller and assistant turns.
        """
        self.history.add_user(caller_text)

        messages: list[Message] = [
            {"role": "system", "content": self._system_prompt},
            *self.history.messages()[:-1],  # history minus the just-added user msg
            {"role": "user", "content": caller_text},
        ]

        headers = {
            "Authorization": f"Bearer {cfg.XAI_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": cfg.LLM_MODEL,
            "stream": True,
            "temperature": cfg.LLM_TEMPERATURE,
            "max_tokens": cfg.LLM_MAX_TOKENS,
            "messages": messages,
        }

        assistant_text_buffer = []

        async def _stream() -> AsyncIterator[str]:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", self._api_url, headers=headers, json=body) as response:
                    response.raise_for_status()
                    buffer = ""
                    async for raw_chunk in response.aiter_bytes():
                        buffer += raw_chunk.decode("utf-8", errors="replace")
                        lines = buffer.split("\n")
                        buffer = lines.pop()
                        for line in lines:
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                return
                            try:
                                import json
                                parsed = json.loads(payload)
                                token = parsed["choices"][0]["delta"].get("content")
                                if token:
                                    yield token
                            except Exception:
                                continue

        full_response = []
        async for token in _stream():
            full_response.append(token)
            assistant_text_buffer.append(token)
            yield token

        self.history.add_assistant("".join(full_response))

    async def greeting(self) -> AsyncIterator[str]:
        """Generate Dr. Aria's opening greeting for a new call."""
        greeting_prompt = (
            "You just picked up a phone call. Introduce yourself very briefly "
            "in one warm sentence and ask how you can help today. "
            "Respond in English unless the caller has indicated another language."
        )
        async for token in self.respond(greeting_prompt):
            yield token
        # Pop the greeting prompt from history — it's synthetic
        if self.history._turns and self.history._turns[-1]["role"] == "assistant":
            greeting_reply = self.history._turns[-1]
            self.history.clear()
            self.history.add_assistant(greeting_reply["content"])


_agent = DrAriaAgent()


def get_agent() -> DrAriaAgent:
    return _agent
