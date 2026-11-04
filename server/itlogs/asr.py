"""Speech in: the phone streams raw PCM (24 kHz, 16-bit, mono) up our WebSocket; the server
holds one Muse Voice Transcribe realtime session per logging session and turns each
completed utterance into the existing voice-text path. The key never leaves the server.

Docs: docs/meta-model-api-notes.org (realtime handshake, events, close codes).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

import websockets

from itlogs.config import settings

log = logging.getLogger("itlogs.asr")

ASR_MODEL = "muse-voice-transcribe-1.0"
ASR_URL = "wss://api.meta.ai/v1/asr/realtime"
KEYWORDS = ["log it", "grams", "yes", "no", "cancel", "rice", "chicken"]

OnTurn = Callable[[str], Awaitable[None]]


class Transcriber(Protocol):
    async def start(self, on_turn: OnTurn) -> None: ...

    async def feed(self, pcm: bytes) -> None: ...

    async def close(self) -> None: ...


class FakeTranscriber:
    """Tests and key-less runs: every chunk that decodes as UTF-8 text is a finished turn."""

    def __init__(self) -> None:
        self._on_turn: OnTurn | None = None
        self.fed = 0

    async def start(self, on_turn: OnTurn) -> None:
        self._on_turn = on_turn

    async def feed(self, pcm: bytes) -> None:
        self.fed += len(pcm)
        try:
            text = pcm.decode("utf-8")
        except UnicodeDecodeError:
            return
        if text.strip() and self._on_turn:
            await self._on_turn(text.strip())

    async def close(self) -> None:
        self._on_turn = None


class MetaTranscriber:
    """One realtime session; ENDPOINTING mode so the model finds the utterance boundaries."""

    def __init__(self, language_bias: list[str] | None = None) -> None:
        if not settings.meta_api_key:
            raise RuntimeError("MODEL_API_KEY must be set for the Meta transcriber")
        self.language_bias = language_bias or ["English", "Portuguese"]
        self._ws: websockets.ClientConnection | None = None
        self._rx: asyncio.Task[None] | None = None
        self.session_id = f"itlogs-{uuid.uuid4()}"

    async def start(self, on_turn: OnTurn) -> None:
        ws = await websockets.connect(f"{ASR_URL}?sessionId={self.session_id}", open_timeout=30)
        await ws.send(
            json.dumps(
                {
                    "authorization": {"accessToken": f"Bearer {settings.meta_api_key}"},
                    "audioEncoding": "PCM_24KHZ",
                    "model": ASR_MODEL,
                    "mode": "ENDPOINTING",
                    "languageBias": self.language_bias,
                    "keywords": KEYWORDS,
                }
            )
        )
        handshake = json.loads(await ws.recv())
        if "sessionId" not in handshake:
            await ws.close()
            raise RuntimeError(f"ASR handshake failed: {handshake}")
        self._ws = ws
        self._rx = asyncio.create_task(self._receive(ws, on_turn))
        log.info("asr session %s open", self.session_id)

    async def feed(self, pcm: bytes) -> None:
        if self._ws is not None:
            await self._ws.send(pcm)

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is None:
            return
        try:
            await ws.send(json.dumps({"type": "endStream"}))
            if self._rx:
                await asyncio.wait_for(self._rx, timeout=10)
        except (TimeoutError, websockets.ConnectionClosed):
            pass
        finally:
            await ws.close()

    async def _receive(self, ws: websockets.ClientConnection, on_turn: OnTurn) -> None:
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    continue
                event = json.loads(message)
                kind = event.get("type")
                if kind == "speechComplete":
                    text = (event.get("transcript") or "").strip()
                    if text:
                        await on_turn(text)
                elif kind == "error":
                    log.error("asr error: %s", event.get("message"))
        except websockets.ConnectionClosed as e:
            if e.code not in (1000, None):
                log.warning("asr closed with %s: %s", e.code, e.reason)


def make_transcriber() -> Transcriber:
    if settings.provider == "meta" and settings.meta_api_key:
        return MetaTranscriber()
    return FakeTranscriber()
