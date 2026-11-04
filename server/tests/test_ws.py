"""The WebSocket on the fake providers: a capture, a second frame, an entry, the final state;
and audio chunks that the fake transcriber turns into a voice trigger."""

import json

import httpx
from fastapi.testclient import TestClient

from itlogs.app import app
from itlogs.providers.fake import FakeLLM, FakeVision


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


def test_model_out_of_reach_is_said_once_and_stop_still_answers(monkeypatch):
    """2026-NOVEMBER-03 20:32: four ConnectTimeouts in a row (the Mac lost the model's endpoint,
    the frames kept arriving), the wearer heard nothing, and Stop crashed the handler on the final
    look. Now the ear says it once and the final state still comes."""
    import json

    import httpx

    from itlogs import app as app_module
    from itlogs.providers.fake import FakeLLM

    class Unreachable:
        async def read_entry(self, jpeg: bytes):
            raise httpx.ConnectTimeout("")

    monkeypatch.setattr(app_module, "make_providers", lambda: (Unreachable(), FakeLLM()))
    with TestClient(app).websocket_connect("/ws/session") as ws:
        meta = {"width": 720, "height": 1280}
        send(ws, "frame", "frame", {"t_ms": 0, **meta}, b"jpeg")
        send(ws, "capture", "capture", {"t_ms": 10})
        _, said = drain_until(ws, "say")
        assert "out of reach" in said["say"]
        send(ws, "capture", "capture", {"t_ms": 20})  # a second failure is not said again
        send(ws, "end_session")
        msgs = []
        while True:
            m = json.loads(ws.receive_text())
            msgs.append(m)
            if m["kind"] == "state":
                break
        assert "entries" in msgs[-1]
        assert not any("out of reach" in m.get("say", "") for m in msgs)


def _status_error(code):
    req = httpx.Request("POST", "https://x.test/v1/chat/completions")
    return httpx.HTTPStatusError(str(code), request=req, response=httpx.Response(code, request=req))


class _Refused(FakeVision):
    async def read_entry(self, jpeg):
        raise _status_error(429)


def test_a_refused_model_call_at_stop_still_sends_the_final_state(monkeypatch):
    """A 429 or 5xx on the final look killed the handler: the phone never got the final state."""
    monkeypatch.setattr("itlogs.app.make_providers", lambda: (_Refused(), FakeLLM()))
    with TestClient(app).websocket_connect("/ws/session") as ws:
        send(ws, "watch", "watch", {"on": True, "t_ms": 0})
        send(ws, "frame", "frame", {"t_ms": 100, "width": 1, "height": 1}, b"jpeg")
        send(ws, "end_session")
        said, seen = [], None
        while seen is None or seen.get("watching") is not False:
            m = json.loads(ws.receive_text())
            said.append(m.get("say"))
            seen = m if m["kind"] == "state" else seen
        assert seen["watching"] is False
        assert "The model is out of reach. Check the Mac's internet." in said


def test_the_recording_keeps_the_frame_that_was_read(monkeypatch, tmp_path):
    """It kept the newest frame when the answer came back, seconds later than the one read."""
    monkeypatch.setattr("itlogs.app.settings.record_dir", str(tmp_path))
    with TestClient(app).websocket_connect("/ws/session") as ws:
        send(ws, "frame", "frame", {"t_ms": 0, "width": 720, "height": 1280}, b"the frame read")
        send(ws, "capture", "capture", {"t_ms": 10})
        drain_until(ws, "read")
        send(ws, "frame", "frame", {"t_ms": 2000, "width": 720, "height": 1280}, b"second look")
        drain_until(ws, "entry")
        send(ws, "end_session")
        drain_until(ws, "state")
    folder = next(tmp_path.iterdir())
    kept = {p.name: p.read_bytes() for p in (folder / "photos").iterdir()}
    assert kept["00000000.jpg"] == b"the frame read"
    events = json.loads((folder / "session.json").read_text())["events"]
    assert [e["t_ms"] for e in events if e["kind"] == "read"] == [0, 2000]
