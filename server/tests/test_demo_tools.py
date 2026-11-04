"""The screen view of the log, and the video of what the glasses saw."""

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from itlogs.app import app

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from demo_log import View  # noqa: E402
from pov_video import concat_list  # noqa: E402


def test_the_real_log_lines_read_plainly():
    view = View()
    assert view.render("READ took 1824 ms (frame t=8862)") is None
    assert "1.8 s   red apple, 111 g, 95% sure" in view.render("READ red apple 111.0 g conf=0.95")
    logged = view.render("ENTRY 1 apple 111 g auto")
    assert "LOGGED" in logged and "apple, 111 g" in logged and "kcal" in logged
    assert "UPDATED" in view.render("ENTRY 1 apple 112 g auto")
    wrapper = view.render("MODEL wrapper='Simply Protein Crispy' net=40.0 p=13.0")
    assert "Simply Protein Crispy, 40 g, 13 g protein" in wrapper
    label = view.render("LABEL Simply Protein kcal=160 protein=13 carbs=17 fat=7 saved")
    assert "160 kcal, 13 g protein, 17 g carbs, 7 g fat" in label
    assert "scale empty" in view.render("READ none 0.0 g conf=1.00")
    assert view.render('PHONE 08:01:32 glasses: heard "cashews" (confidence 0.66)')


def test_noise_and_private_lines_stay_off_the_screen():
    view = View()
    for raw in (
        "INFO:     ::1:59667 - GET /health HTTP/1.1 200 OK",
        "FRAMES 100 (84713 bytes, t=20223 ms)",
        "PHONE 12:48:36 glasses: stream state streaming",
    ):
        assert view.render(raw) is None
    start = "PHONE 12:21:54 start tapped; glasses=true server=ws://some-host.local:8000/ws/session"
    assert "some-host" not in view.render(start)


def test_each_frame_is_held_until_the_next_one(tmp_path):
    frames = [tmp_path / "00001000.jpg", tmp_path / "00001250.jpg"]
    text = concat_list(frames)
    assert "duration 0.250" in text
    assert text.count("file ") == 3  # ffmpeg ignores the last duration unless the frame repeats


def test_the_stream_is_kept_only_when_asked(monkeypatch, tmp_path):
    monkeypatch.setattr("itlogs.app.settings.record_dir", str(tmp_path))

    def run():
        with TestClient(app).websocket_connect("/ws/session") as ws:
            ws.send_text(
                json.dumps({"kind": "frame", "frame": {"t_ms": 40, "width": 1, "height": 1}})
            )
            ws.send_bytes(b"jpeg")
            ws.send_text(json.dumps({"kind": "end_session"}))
            while json.loads(ws.receive_text())["kind"] != "state":
                pass

    run()
    assert not list(tmp_path.glob("*/stream/*.jpg"))
    monkeypatch.setattr("itlogs.app.settings.record_stream", True)
    for old in tmp_path.iterdir():
        old.rename(tmp_path / "older")
    run()
    assert [p.name for p in tmp_path.glob("*/stream/*.jpg")] == ["00000040.jpg"]
