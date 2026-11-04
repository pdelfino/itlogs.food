"""A barcode names the next food (#13): the Open Food Facts row, the session that uses it, and
the WebSocket message from the phone. No network: canned JSON through MockTransport."""

import json

import httpx
import pytest

from itlogs.models import EntryRead
from itlogs.providers import openfoodfacts as off
from itlogs.providers.fake import FakeLLM, FakeVision
from itlogs.session import Session

QUEST = {
    "status": 1,
    "product": {
        "product_name": "Protein Bar, Cookies & Cream",
        "brands": "Quest, Quest Nutrition",
        "serving_quantity": "60",
        "nutriments": {
            "energy-kcal_100g": 333,
            "proteins_100g": 35,
            "carbohydrates_100g": 36.7,
            "fat_100g": 13.3,
            "fiber_100g": 23.3,
            "sodium_100g": 0.483,
        },
    },
}


def test_parse_builds_the_label_row_per_100g():
    p = off.parse("00888849000104", QUEST)
    assert p is not None
    assert p.name == "Quest Protein Bar, Cookies & Cream"  # the brand prefixed once
    assert p.brand == "Quest"
    assert p.per100g == (333.0, 35.0, 36.7, 13.3, 23.3, 483.0)
    assert p.serving_g == 60.0


def test_parse_unknown_or_no_energy_is_none():
    assert off.parse("1", {"status": 0, "status_verbose": "product not found"}) is None
    assert off.parse("2", {"status": 1, "product": {"nutriments": {"fat_100g": 1}}}) is None


def test_parse_salt_and_kilojoules_fallbacks():
    n = {"energy_100g": 418.4, "salt_100g": 1.0}
    data = {"status": 1, "product": {"product_name": "x", "nutriments": n}}
    p = off.parse("3", data)
    assert p is not None
    assert p.per100g[0] == 100.0 and p.per100g[5] == 400.0


async def test_lookup_hits_the_api_once_and_the_cache_after(tmp_path, monkeypatch):
    monkeypatch.setattr(off, "CACHE", tmp_path)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=QUEST)

    t = httpx.MockTransport(handler)
    p = await off.lookup("0 0888849 000104", transport=t)
    assert p is not None and p.name.startswith("Quest")
    assert "00888849000104" in calls[0] and "User-Agent" not in calls[0]
    assert (tmp_path / "00888849000104.json").exists()
    p2 = await off.lookup("00888849000104", transport=t)
    assert p2 == p and len(calls) == 1


async def test_lookup_404_and_unreachable_are_none(tmp_path, monkeypatch):
    monkeypatch.setattr(off, "CACHE", tmp_path)
    gone = httpx.MockTransport(lambda r: httpx.Response(404))
    assert await off.lookup("9", transport=gone) is None

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("")

    assert await off.lookup("9", transport=httpx.MockTransport(down)) is None


async def test_scanned_product_names_the_next_entry_and_only_the_grams_must_agree():
    """The wrapper was read as "protein bar" then "granola bar" (2026-NOVEMBER-03 21:09) and
    never logged; with the barcode the name is known and the label's row comes with it."""
    product = off.parse("00888849000104", QUEST)
    reads = [
        EntryRead(food="protein bar", grams=63.0, confidence=0.7),
        EntryRead(food="granola bar", grams=63.0, confidence=0.7),
    ]
    s = Session(FakeVision(reads), FakeLLM())
    s.set_watching(True, 0)
    said = s.set_product(product)
    assert said[0].say.startswith("Quest Protein Bar")
    out = await s.on_frame(b"a", 1000)
    out += await s.on_frame(b"b", 6000)
    entries = [m.entry for m in out if m.kind == "entry" and m.entry]
    assert len(entries) == 1
    e = entries[0]
    assert e.food == "Quest Protein Bar, Cookies & Cream" and e.grams == 63.0
    assert e.product == "00888849000104"
    assert e.nutrients is not None and round(e.nutrients.kcal) == 210
    assert round(e.nutrients.protein_g, 1) == 22.1
    # the product is spent: the next food is read as usual
    assert s._product is None


def test_scan_after_weighing_relabels_the_fresh_unknown_entry_only():
    """21:23: the bar was weighed first ("protein bar", 42 g, no nutrient row), the wrapper
    shown after. The scan relabels that row; an apple (a known row) is never relabeled."""
    product = off.parse("00888849000104", QUEST)
    s = Session(FakeVision(), FakeLLM())
    s._log("protein bar", 42.0, "auto", [], 30_000, speak=False)
    assert s.entries[-1].nutrients is None
    out = s.set_product(product, t_ms=40_000)
    assert [m.kind for m in out] == ["entry", "say"]
    e = s.entries[-1]
    assert e.food.startswith("Quest Protein Bar") and e.grams == 42.0
    assert e.product == "00888849000104" and e.nutrients is not None
    assert round(e.nutrients.kcal) == 140
    assert "42 grams, logged" in out[1].say
    assert not s.product_pending
    # a known food is left alone: the product waits for the next one
    s._log("apple", 111.0, "auto", [], 50_000, speak=False)
    out = s.set_product(product, t_ms=55_000)
    assert out[0].kind == "say" and "Put it on the scale" in out[0].say
    assert s.entries[-1].food == "apple" and s.product_pending
    # too old: not relabeled either
    s2 = Session(FakeVision(), FakeLLM())
    s2._log("protein bar", 42.0, "auto", [], 0, speak=False)
    assert s2.set_product(product, t_ms=90_000)[0].kind == "say" and s2.product_pending


def test_unknown_barcode_is_said_and_changes_nothing():
    s = Session(FakeVision(), FakeLLM())
    out = s.set_product(None, "123")
    assert out[0].kind == "say" and "don't know" in out[0].say
    assert s._product is None


def test_ws_barcode_message_is_looked_up_and_said(monkeypatch):
    from fastapi.testclient import TestClient

    from itlogs import app as app_module
    from itlogs.app import app

    async def fake_lookup(code, **kw):
        return off.parse(code, QUEST) if code == "00888849000104" else None

    monkeypatch.setattr(app_module, "lookup_product", fake_lookup)
    with TestClient(app).websocket_connect("/ws/session") as ws:
        known = {"kind": "barcode", "barcode": {"t_ms": 5, "code": "00888849000104"}}
        ws.send_text(json.dumps(known))
        m = json.loads(ws.receive_text())
        assert m["kind"] == "say"
        assert m["say"].startswith("Quest Protein Bar")
        ws.send_text(json.dumps({"kind": "barcode", "barcode": {"t_ms": 6, "code": "1"}}))
        m = json.loads(ws.receive_text())
        assert m["kind"] == "say" and "don't know" in m["say"]


@pytest.mark.parametrize("code", ["", "abc"])
async def test_lookup_without_digits_is_none(code):
    assert await off.lookup(code) is None


def test_decode_reads_an_ean13_from_a_jpeg_and_ignores_other_bytes():
    """Option A: the barcode is decoded from the frame itself, on the Mac."""
    from itlogs import barcode

    jpeg = barcode.encode_for_test("0888849000104")
    assert barcode.decode(jpeg) == "0888849000104"
    assert barcode.decode(b"not a jpeg") is None
    # the frame the glasses send: the code somewhere in a 720 x 1280 picture, a bit tilted
    from PIL import Image

    page = Image.new("L", (720, 1280), 235)
    code = Image.open(__import__("io").BytesIO(jpeg)).rotate(6, expand=True, fillcolor=235)
    page.paste(code, (150, 500))
    buf = __import__("io").BytesIO()
    page.save(buf, format="JPEG", quality=85)
    assert barcode.decode(buf.getvalue()) == "0888849000104"


def test_ws_frame_with_a_barcode_names_the_next_food(monkeypatch):
    """Hands free: a frame that shows the wrapper sets the product, the ear says its name."""
    from fastapi.testclient import TestClient

    from itlogs import app as app_module
    from itlogs.app import app
    from itlogs.barcode import encode_for_test

    async def fake_lookup(code, **kw):
        return off.parse(code, QUEST) if code == "0888849000104" else None

    monkeypatch.setattr(app_module, "lookup_product", fake_lookup)
    with TestClient(app).websocket_connect("/ws/session") as ws:
        meta = {"width": 720, "height": 1280}
        ws.send_text(json.dumps({"kind": "watch", "watch": {"on": True, "t_ms": 0}}))
        ws.send_text(json.dumps({"kind": "frame", "frame": {"t_ms": 100, **meta}}))
        ws.send_bytes(encode_for_test("0888849000104"))
        kinds = []
        while True:
            m = json.loads(ws.receive_text())
            kinds.append(m["kind"])
            if m["kind"] == "say" and m["say"].startswith("Quest Protein Bar"):
                break
            assert len(kinds) < 8, kinds


def test_a_scan_waits_one_minute_for_its_food():
    """A scan nobody weighs must not name a banana weighed much later."""
    product = off.parse("00888849000104", QUEST)
    s = Session(FakeVision([EntryRead(food="banana", grams=124.0, confidence=0.95)]), FakeLLM())
    s.set_watching(True, 0)
    s.observe(b"a", 1000)
    s.set_product(product, t_ms=1000)
    assert s.product_pending
    s.observe(b"b", 62_000)
    assert not s.product_pending


async def test_an_expired_scan_does_not_name_the_next_food():
    product = off.parse("00888849000104", QUEST)
    s = Session(FakeVision([EntryRead(food="banana", grams=124.0, confidence=0.95)]), FakeLLM())
    s.set_watching(True, 0)
    s.set_product(product, t_ms=0)
    out = await s.on_frame(b"a", 70_000)
    entries = [m.entry for m in out if m.kind == "entry" and m.entry]
    assert [e.food for e in entries] == ["banana"] and entries[0].product is None
