"""FastAPI app: a health check and the per-session WebSocket the phone talks to.

Protocol on /ws/session: the phone sends a JSON ClientMessage; when kind == "frame" the next
binary message is the JPEG, when kind == "audio" the next binary message is a PCM chunk.
The server answers with JSON ServerMessages at any time. Speech arrives as text already
recognized on the glasses (kind == "voice"); PCM audio is the fallback, transcribed here by Muse
Voice Transcribe (asr.py).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from itlogs import telemetry
from itlogs.asr import Transcriber, make_transcriber
from itlogs.barcode import decode as decode_barcode
from itlogs.config import settings
from itlogs.models import ClientMessage, EntryRead, ServerMessage
from itlogs.providers import make_providers
from itlogs.providers.openfoodfacts import lookup as lookup_product
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
    frames = 0

    def read_made(jpeg: bytes, t_ms: int, read: EntryRead) -> None:
        """The frame the reader was given, not the newest one when its answer came back."""
        if recorder:
            recorder.photo(jpeg, t_ms)
            recorder.event("read", {"t_ms": t_ms, **read.model_dump()})

    session.on_read = read_made

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
        """Telemetry for each entry; in the recording, every entry and question (the frames and
        the reads are kept by read_made)."""
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
            if m.kind in ("entry", "ask"):
                recorder.event(m.kind, m.model_dump(exclude_none=True))

    async def on_turn(text: str) -> None:
        if recorder:
            recorder.event("voice", {"text": text})
        start_thinking(session.on_voice(text), 0, "voice")

    # The model call runs in the background, two at a time at most, so frames keep arriving (and
    # the still detector keeps seeing them) while the reader thinks (#12 option A).
    thinking: set[asyncio.Task[None]] = set()
    MAX_IN_FLIGHT = 2

    unreachable_said = False

    async def model_unreachable(e: Exception) -> None:
        # the Mac lost the model's endpoint (20:32, 2026-NOVEMBER-03: four ConnectTimeouts in a
        # row while the frames kept arriving), or the endpoint refused the call (a 429 or a 5xx):
        # say it once, so the wearer knows it is not the loop
        nonlocal unreachable_said
        print(f"MODEL unreachable: {type(e).__name__} {e}", flush=True)
        if unreachable_said:
            return
        unreachable_said = True
        msg = ServerMessage(kind="say", say="The model is out of reach. Check the Mac's internet.")
        keep([msg])
        try:
            await send_all([msg])
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def think(coro: Any, t_ms: int) -> None:
        t0 = time.perf_counter()
        try:
            out = await coro
        except httpx.HTTPError as e:
            await model_unreachable(e)
            return
        took_ms = int((time.perf_counter() - t0) * 1000)
        if any(m.kind == "read" for m in out):
            print(f"READ took {took_ms} ms (frame t={t_ms})", flush=True)
            if recorder:
                recorder.event("read_latency", {"t_ms": t_ms, "ms": took_ms})
        keep(out)
        try:
            await send_all(out)
        except (WebSocketDisconnect, RuntimeError) as e:
            # the phone stopped before a slow read came back (20 s on Muse Spark Open, Baseten,
            # 2026-NOVEMBER-03): the read and its entry are already in the recording, the socket
            # is gone, that is all
            print(f"READ after the socket closed, not sent ({type(e).__name__})", flush=True)

    def retrieved(task: asyncio.Task[None]) -> None:
        thinking.discard(task)
        if not task.cancelled() and task.exception() is not None:
            print(f"THINK failed: {task.exception()!r}", flush=True)

    def start_thinking(coro: Any, t_ms: int, kind: str = "read") -> None:
        task = asyncio.create_task(think(coro, t_ms), name=kind)
        thinking.add(task)
        task.add_done_callback(retrieved)

    def busy() -> int:
        return sum(1 for t in thinking if not t.done() and t.get_name() == "read")

    async def finish_thinking(timeout: float = 8.0) -> None:
        pending = [t for t in thinking if not t.done()]
        if pending:
            done, still = await asyncio.wait(pending, timeout=timeout)
            for t in still:
                t.cancel()
        thinking.clear()

    last_code: tuple[str, int] | None = None  # the barcode last decoded and when: not twice

    async def on_barcode(code: str, t_ms: int) -> list[ServerMessage]:
        """A barcode, from the phone's scanner or from a glasses frame: the product it names
        is the next food on the scale (#13)."""
        product = await lookup_product(code)
        print(f"BARCODE {code} -> {product.name if product else 'unknown'}", flush=True)
        if recorder:
            recorder.event(
                "barcode",
                {"t_ms": t_ms, "code": code, "product": product.name if product else None},
            )
        return session.set_product(product, code, t_ms)

    async def on_frame(meta: Any, jpeg: bytes) -> list[ServerMessage]:
        nonlocal frames, last_code
        frames += 1
        if frames == 1 or frames % 100 == 0:
            print(f"FRAMES {frames} ({len(jpeg)} bytes, t={meta.t_ms} ms)", flush=True)
        session.observe(jpeg, meta.t_ms)
        out = session.ready()  # "Ready..." once, on the first frame after Start
        # hands free (#13, option A): every frame is searched for a barcode (18 ms median on the
        # Mac, measured 2026-NOVEMBER-03) while no product is waiting, so a wrapper held up for a
        # second gets seven tries; the same code is not taken twice in 15 s
        if not session.product_pending and (last_code is None or meta.t_ms - last_code[1] > 15000):
            try:
                code = await asyncio.to_thread(decode_barcode, jpeg)
            except Exception as e:  # the decoder must never cost a session
                print(f"BARCODE decoder failed: {e!r}", flush=True)
                code = None
            if code:
                last_code = (code, meta.t_ms)
                out = [*out, *await on_barcode(code, meta.t_ms)]
        if busy() < MAX_IN_FLIGHT:
            start_thinking(session.decide(jpeg, meta.t_ms), meta.t_ms)
        if recorder and frames % 7 == 1:
            # about once a second: how much the picture moved and whether it counts as still
            recorder.event(
                "motion",
                {
                    "t_ms": meta.t_ms,
                    "diff": round(session.stillness.last_diff, 1),
                    "still": session.stillness.still(meta.t_ms),
                },
            )
        return out

    async def on_audio(pcm: bytes) -> None:
        nonlocal transcriber
        if transcriber is None:
            transcriber = make_transcriber()
            await transcriber.start(on_turn)
        await transcriber.feed(pcm)

    try:
        # A frame or an audio chunk is two messages, the JSON meta then the bytes. The phone now
        # sends them back to back from one queue, but a meta can still arrive while another is
        # waiting for its bytes (2026-NOVEMBER-03 09:27 and 09:28: the socket opened seconds
        # after the stream, every frame had queued its meta ahead of its bytes, and the handler
        # died on the second meta; two runs logged nothing). The older meta is dropped, the
        # session goes on.
        pending: ClientMessage | None = None
        resyncs = 0
        while True:
            raw = await ws.receive()
            if raw["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(raw.get("code", 1000))
            blob = raw.get("bytes")
            if blob is not None:
                if pending is None:
                    continue  # bytes whose meta was lost: nothing to pair them with
                msg, pending = pending, None
                if msg.kind == "frame" and msg.frame:
                    out = await on_frame(msg.frame, blob)
                else:
                    await on_audio(blob)
                    out = []
                keep(out)
                await send_all(out)
                continue
            msg = ClientMessage.model_validate_json(raw.get("text") or "")
            if msg.kind in ("frame", "audio") and (msg.frame or msg.audio):
                if pending is not None:
                    resyncs += 1
                    if resyncs == 1:
                        print("RESYNC meta before the previous bytes; older dropped", flush=True)
                pending = msg
                continue
            if msg.kind == "voice" and msg.voice:
                if recorder:
                    recorder.event("voice", {"t_ms": msg.voice.t_ms, "text": msg.voice.text})
                # in the background: parsing a sentence blocked the frame loop for the rest of a
                # run on 2026-NOVEMBER-02 19:26 ("Okay, I put the first food." at 14 s, then
                # nothing)
                start_thinking(
                    session.on_voice(msg.voice.text, msg.voice.t_ms), msg.voice.t_ms, "voice"
                )
                out = []
            elif msg.kind == "capture" and msg.capture:
                await finish_thinking()
                start_thinking(session.capture(msg.capture.t_ms), msg.capture.t_ms)
                out = []
            elif msg.kind == "watch" and msg.watch:
                out = session.set_watching(msg.watch.on, msg.watch.t_ms, ask=msg.watch.ask)
            elif msg.kind == "barcode" and msg.barcode:
                out = await on_barcode(msg.barcode.code, msg.barcode.t_ms)
            else:
                if transcriber is not None:
                    await transcriber.close()
                    transcriber = None
                await finish_thinking()  # the reads in flight land first
                try:
                    out = await session.final_look()  # then whatever is on the scale now
                except httpx.HTTPError as e:
                    await model_unreachable(e)  # the final state still goes out below
                    out = []
                except Exception as e:  # nothing may cost the wearer the final state
                    telemetry.exception(e, {"path": "final_look"})
                    print(f"FINAL LOOK failed: {e!r}", flush=True)
                    out = []
                keep(out)
                await send_all(out)
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
        await finish_thinking(0.0)
        if recorder:
            recorder.close([e.model_dump() for e in session.entries])
        return
