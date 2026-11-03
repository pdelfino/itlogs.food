"""The WebSocket on the fake providers: a capture, a second frame, an entry, the final state;
and audio chunks that the fake transcriber turns into a voice trigger."""

import json

from fastapi.testclient import TestClient

from itlogs.app import app


def send(ws, kind, key=None, meta=None, blob=None):
    body = {"kind": kind}
    if key:
        body[key] = meta
    ws.send_text(json.dumps(body))
    if blob is not None:
        ws.send_bytes(blob)


def drain_until(ws, kind):
    kinds = []
    while True:
        m = json.loads(ws.receive_text())
        kinds.append(m["kind"])
        if m["kind"] == kind:
            return kinds, m


def test_health():
    assert TestClient(app).get("/health").json()["status"] == "ok"


def test_second_frame_after_a_capture_logs_an_entry():
    with TestClient(app).websocket_connect("/ws/session") as ws:
        send(ws, "frame", "frame", {"t_ms": 0, "width": 720, "height": 1280}, b"jpeg")
        send(ws, "capture", "capture", {"t_ms": 10})
        kinds, _ = drain_until(ws, "read")
        send(ws, "frame", "frame", {"t_ms": 2000, "width": 720, "height": 1280}, b"jpeg")
        kinds, entry = drain_until(ws, "entry")
        assert kinds == ["read", "entry"]
        assert entry["entry"]["status"] == "agreed"
        send(ws, "end_session")
        kinds, state = drain_until(ws, "state")
        assert len(state["entries"]) == 1


def test_audio_chunks_become_a_voice_trigger_via_the_fake_transcriber():
    with TestClient(app).websocket_connect("/ws/session") as ws:
        send(ws, "frame", "frame", {"t_ms": 0, "width": 720, "height": 1280}, b"jpeg")
        send(ws, "audio", "audio", {"t_ms": 100}, b"log it")
        kinds, _ = drain_until(ws, "read")
        assert kinds == ["read"]
        send(ws, "end_session")
        drain_until(ws, "state")


def test_two_metas_back_to_back_do_not_end_the_session():
    """2026-NOVEMBER-03 09:27: the phone's frame tasks queued every meta ahead of its bytes while
    the socket was still opening; the server read a meta where it expected bytes and the session
    died. Now the older meta is dropped and end_session is still answered."""
    import json

    with TestClient(app).websocket_connect("/ws/session") as ws:
        meta = {"width": 720, "height": 1280}
        ws.send_text(json.dumps({"kind": "frame", "frame": {"t_ms": 0, **meta}}))
        ws.send_text(json.dumps({"kind": "frame", "frame": {"t_ms": 140, **meta}}))
        ws.send_bytes(b"jpeg")
        ws.send_bytes(b"jpeg")  # no meta left for these: dropped, not fatal
        send(ws, "end_session")
        _, state = drain_until(ws, "state")
        assert "entries" in state
