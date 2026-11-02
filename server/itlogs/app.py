"""FastAPI app: a health check and the per-session WebSocket the phone talks to.

Protocol on /ws/session: the phone sends a JSON ClientMessage; when kind == "frame" the next
binary message is the JPEG, when kind == "audio" the next binary message is a PCM chunk.
The server answers with JSON ServerMessages at any time, including after a transcribed
utterance (speech is transcribed server-side by Muse Voice Transcribe).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from itlogs import telemetry
from itlogs.asr import Transcriber, make_transcriber
from itlogs.config import settings
from itlogs.models import ClientMessage, ServerMessage
from itlogs.providers import make_providers
from itlogs.record import Recorder
from itlogs.session import Session

app = FastAPI(title="itlogs.food")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    telemetry.exception(exc, {"path": request.url.path})
    return JSONResponse(status_code=500, content={"message": str(exc)})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": settings.provider}


class PhoneLine(BaseModel):
    t: float
    line: str


@app.post("/log")
async def phone_log(item: PhoneLine) -> dict[str, str]:
    """Diagnostics from the phone (Diag.swift): printed here so the terminal shows what the
    wearer sees, and appended to .sessions/phone.log. Never photos or audio."""
    stamp = time.strftime("%H:%M:%S", time.localtime(item.t))
    print(f"PHONE {stamp} {item.line}", flush=True)
    telemetry.event("phone_diag", {"line": item.line, "phone_t": item.t}, distinct_id="phone")
    path = Path(".sessions")
    path.mkdir(exist_ok=True)
    with (path / "phone.log").open("a") as f:
        f.write(f"{stamp} {item.line}\n")
    return {"ok": "1"}


@app.websocket("/ws/session")
async def ws_session(ws: WebSocket) -> None:
    await ws.accept()
    vision, llm = make_providers()
    session = Session(
        vision,
        llm,
        second_read_after_ms=settings.second_read_after_ms,
        grams_tolerance_g=settings.grams_tolerance_g,
    )
    recorder = Recorder(settings.record_dir) if settings.record_dir else None
    transcriber: Transcriber | None = None
    send_lock = asyncio.Lock()
    last_frame: tuple[int, bytes] | None = None
    frames = 0

    async def send_all(msgs: list[ServerMessage]) -> None:
        async with send_lock:
            for m in msgs:
                if m.kind == "entry" and m.entry is not None:
                    e = m.entry
                    print(f"ENTRY {e.index} {e.food} {e.grams:g} g {e.status}", flush=True)
                elif m.kind == "ask" and m.ask is not None:
                    print(f"ASK {m.ask.text}", flush=True)
                elif m.kind == "say":
                    print(f"SAY {m.say}", flush=True)
                elif m.kind == "read" and m.read is not None:
                    r = m.read
                    print(f"READ {r.food} {r.grams} g conf={r.confidence:.2f}", flush=True)
                await ws.send_text(m.model_dump_json(exclude_none=True))

    def keep(msgs: list[ServerMessage]) -> None:
        """Only the frames a read was made on are kept, plus every entry and question."""
        for m in msgs:
            if m.kind == "entry" and m.entry is not None:
                telemetry.event(
                    "entry_logged",
                    {
                        "food": m.entry.food,
                        "grams": m.entry.grams,
                        "status": m.entry.status,
                        "provider": settings.provider,
                        "known_food": m.entry.nutrients is not None,
                    },
                )
            if recorder is None:
                continue
            if m.kind == "read" and last_frame is not None:
                recorder.photo(last_frame[1], last_frame[0])
                recorder.event("read", {"t_ms": last_frame[0], **m.read.model_dump()})  # type: ignore[union-attr]
            elif m.kind in ("entry", "ask"):
                recorder.event(m.kind, m.model_dump(exclude_none=True))

    async def on_turn(text: str) -> None:
        if recorder:
            recorder.event("voice", {"text": text})
        out = await session.on_voice(text)
        keep(out)
        await send_all(out)

    try:
        while True:
            msg = ClientMessage.model_validate_json(await ws.receive_text())
            if msg.kind == "frame" and msg.frame:
                jpeg = await ws.receive_bytes()
                last_frame = (msg.frame.t_ms, jpeg)
                frames += 1
                if frames == 1 or frames % 100 == 0:
                    print(f"FRAMES {frames} ({len(jpeg)} bytes, t={msg.frame.t_ms} ms)", flush=True)
                out = await session.on_frame(jpeg, msg.frame.t_ms)
            elif msg.kind == "audio" and msg.audio:
                pcm = await ws.receive_bytes()
                if transcriber is None:
                    transcriber = make_transcriber()
                    await transcriber.start(on_turn)
                await transcriber.feed(pcm)
                out = []
            elif msg.kind == "voice" and msg.voice:
                if recorder:
                    recorder.event("voice", {"t_ms": msg.voice.t_ms, "text": msg.voice.text})
                out = await session.on_voice(msg.voice.text, msg.voice.t_ms)
            elif msg.kind == "capture" and msg.capture:
                out = await session.capture(msg.capture.t_ms)
            elif msg.kind == "watch" and msg.watch:
                out = session.set_watching(msg.watch.on, msg.watch.t_ms, ask=msg.watch.ask)
            else:
                if transcriber is not None:
                    await transcriber.close()
                    transcriber = None
                out = await session.end_session()
                await send_all(out)
                if recorder:
                    recorder.close([e.model_dump() for e in session.entries])
                await ws.close()
                break
            keep(out)
            await send_all(out)
    except WebSocketDisconnect:
        if transcriber is not None:
            await transcriber.close()
        return
