"""A packaged food by its wrapper (#13). The numbers are the real bar's, as Pedro read them off the
label on 2026-NOVEMBER-04: Simply Protein Crispy, Dark Chocolate Almond, 40 g, 160 kcal, 13 g
protein, on a scale that shows 42 g because it also weighs the wrapper."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from itlogs.app import app
from itlogs.config import settings
from itlogs.models import EntryRead, LabelFacts, WrapperLabel
from itlogs.providers.fake import FakeLLM, FakeVision
from itlogs.providers.meta import MetaReader
from itlogs.session import Session, row_from_facts

BAR = WrapperLabel(
    brand="Simply Protein",
    product="Crispy",
    flavour="Dark Chocolate Almond",
    net_grams=40,
    protein_g=13,
)
FACTS = LabelFacts(
    serving_g=40,
    kcal=160,
    protein_g=13,
    carbs_g=16,
    fat_g=7,
    fiber_g=7,
    sodium_mg=200,
    source="https://example.test/bar",
)


def weighing(*reads, wrappers=(BAR,), facts=FACTS):
    vision = FakeVision(list(reads))
    vision.wrappers = list(wrappers)
    vision.facts = facts
    s = Session(vision, FakeLLM())
    s.set_watching(True, 0)
    return s, vision


async def settle(s):
    """Runs what the app would run in the background: wrapper reads, then their searches."""
    out = []
    for index, frame in s.take_labels():
        out += await s.identify(index, frame)
    for index, label in s.take_lookups():
        out += await s.look_up(index, label)
    return out


def bar(grams=42.0):
    return EntryRead(food="protein bar", grams=grams, confidence=0.95)


async def test_the_wrapper_names_the_row_and_brings_the_label():
    s, vision = weighing(bar())
    await s.on_frame(b"frame", 1000)
    assert [(e.food, e.nutrients) for e in s.entries] == [("protein bar", None)]
    [(index, frame)] = s.take_labels()
    assert (index, frame) == (1, b"frame")
    first = await s.identify(index, frame)
    assert first[0].entry.food == "Simply Protein Crispy Dark Chocolate Almond"
    assert first[0].entry.nutrients is None  # the name lands now, the search takes longer
    [(index, label)] = s.take_lookups()
    out = await s.look_up(index, label)
    entry = s.entries[0]
    assert entry.food == "Simply Protein Crispy Dark Chocolate Almond"
    assert entry.grams == 42.0  # the row keeps what the scale showed
    assert entry.nutrients.kcal == 160.0  # the label's bar: the wrapper is not food
    assert entry.nutrients.protein_g == 13.0
    assert (entry.product, entry.source) == ("wrapper", "https://example.test/bar")
    assert [m.kind for m in out] == ["entry", "say"]
    assert out[0].entry.index == 1  # the phone replaces the row
    assert out[1].say == "Simply Protein Crispy Dark Chocolate Almond, 160 calories."


async def test_a_food_part_of_a_pack_counts_what_is_on_the_scale():
    s, _ = weighing(bar(20.0))
    await s.on_frame(b"frame", 1000)
    await settle(s)
    assert s.entries[0].nutrients.kcal == 80.0


async def test_foods_the_table_knows_are_never_looked_up():
    s, vision = weighing(EntryRead(food="banana", grams=122.0, confidence=0.95))
    await s.on_frame(b"frame", 1000)
    assert s.entries[0].nutrients is not None
    assert s.take_labels() == []


@pytest.mark.parametrize(
    "facts",
    [
        FACTS.model_copy(update={"protein_g": 15.0}),  # disagrees with the printed 13 g
        FACTS.model_copy(update={"kcal": 500.0}),  # does not fit its macros
        FACTS.model_copy(update={"serving_g": None}),
        FACTS.model_copy(update={"carbs_g": None}),
        LabelFacts(serving_g=100, kcal=150, protein_g=15, carbs_g=14, fat_g=4.5),  # the OFF row
    ],
)
def test_numbers_that_cannot_be_trusted_are_refused(facts):
    assert row_from_facts(BAR, facts) is None


def test_the_protein_printed_on_the_wrapper_wins():
    """The second real search said 12 g, within the check; the wrapper prints 13 g."""
    row = row_from_facts(BAR, FACTS.model_copy(update={"protein_g": 12.0}))
    assert round(row[1] * 40 / 100, 2) == 13.0


async def test_refused_numbers_keep_the_name_and_the_question_mark():
    s, _ = weighing(bar(), facts=FACTS.model_copy(update={"protein_g": 15.0}))
    await s.on_frame(b"frame", 1000)
    out = await settle(s)
    assert s.entries[0].food == "Simply Protein Crispy Dark Chocolate Almond"
    assert s.entries[0].nutrients is None
    assert [m.kind for m in out] == ["entry"]  # the name, and no numbers after it


async def test_a_failed_search_keeps_the_row():
    s, vision = weighing(bar())

    async def boom(label):
        raise httpx.ConnectTimeout("")

    vision.find_facts = boom
    await s.on_frame(b"frame", 1000)
    await settle(s)
    assert (s.entries[0].grams, s.entries[0].nutrients) == (42.0, None)


async def test_a_failed_read_keeps_the_row():
    s, vision = weighing(bar())

    async def boom(jpeg):
        raise httpx.ReadTimeout("")

    vision.read_wrapper = boom
    await s.on_frame(b"frame", 1000)
    assert await s.identify(*s.take_labels()[0]) == []
    assert s.entries[0].food == "protein bar"


async def test_the_back_of_the_wrapper_gets_one_more_look():
    s, _ = weighing(bar(), wrappers=(WrapperLabel(), BAR))
    await s.on_frame(b"back", 1000)
    assert await s.identify(*s.take_labels()[0]) == []
    await s.on_frame(b"front", 3000)  # the wrapper was turned over: a new scene, a new read
    assert s._label_queue[0][1] == b"front"
    await settle(s)
    assert s.entries[0].nutrients.kcal == 160.0
    await s.on_frame(b"again", 5000)
    assert s.take_labels() == []


async def test_a_new_reading_of_the_bar_keeps_the_label():
    s, _ = weighing(bar(42.0), bar(45.0))
    await s.on_frame(b"frame", 1000)
    await settle(s)
    await s.on_frame(b"frame2", 3000)
    assert len(s.entries) == 1  # the reader still says "protein bar": the same row
    assert s.entries[0].grams == 45.0
    assert s.entries[0].food == "Simply Protein Crispy Dark Chocolate Almond"
    assert s.entries[0].nutrients.kcal == 160.0


async def test_a_lookup_that_lands_after_the_next_food_finds_its_own_row():
    s, _ = weighing(bar(), EntryRead(food="none", grams=0.0, confidence=0.9))
    await s.on_frame(b"frame", 1000)
    queued = s.take_labels()[0]
    s.vision.reads = [
        EntryRead(food="none", grams=0.0, confidence=0.9),
        EntryRead(food="none", grams=0.0, confidence=0.9),
        EntryRead(food="apple", grams=112.0, confidence=0.95),
    ]
    s.vision.calls = 0
    for t in (3000, 5000, 7000):
        await s.on_frame(b"x", t)
    assert [e.food for e in s.entries] == ["protein bar", "apple"]
    await s.identify(*queued)
    await s.look_up(*s.take_lookups()[0])
    assert s.entries[0].food.startswith("Simply Protein")
    assert s.entries[1].food == "apple"


async def test_a_look_still_running_is_not_queued_again():
    """12:48: a later read of the same bar started a second look and a second search."""
    s, vision = weighing(bar(), bar())
    await s.on_frame(b"one", 1000)
    queued = s.take_labels()
    s._last_watch_ms = -1_000_000
    await s.on_frame(b"two", 3000)
    assert s.take_labels() == []
    await s.identify(*queued[0])
    assert len(s.take_lookups()) == 1
    assert len(vision.wrapper_calls) == 1


async def test_the_same_product_is_found_only_once():
    """The search took 32 s on the real bar; the label does not change between meals. The reader
    worded the same bar two ways at 12:48, so the key is the brand and the flavour."""
    s, vision = weighing(bar())
    await s.on_frame(b"frame", 1000)
    await settle(s)
    assert vision.facts_calls == 1
    again, vision2 = weighing(bar(), wrappers=(BAR.model_copy(update={"product": "Snack Bar"}),))
    await again.on_frame(b"frame", 1000)
    await settle(again)
    assert vision2.facts_calls == 0
    assert again.entries[0].nutrients.kcal == 160.0


async def test_refused_numbers_are_not_kept():
    s, vision = weighing(bar(), facts=FACTS.model_copy(update={"protein_g": 15.0}))
    await s.on_frame(b"frame", 1000)
    await settle(s)
    again, vision2 = weighing(bar())
    await again.on_frame(b"frame", 1000)
    await settle(again)
    assert vision2.facts_calls == 1
    assert again.entries[0].nutrients.kcal == 160.0


async def test_the_switch_turns_it_off(monkeypatch):
    monkeypatch.setattr(settings, "label_search", False)
    s, _ = weighing(bar())
    await s.on_frame(b"frame", 1000)
    assert s.take_labels() == []


async def test_a_bowl_row_is_not_a_wrapper():
    s, _ = weighing(EntryRead(food="mixed nuts", grams=30.0, confidence=0.9, container=True))
    await s.on_frame(b"a", 1000)
    await s.on_frame(b"b", 3000)
    assert s.take_labels() == []


def test_the_socket_waits_for_the_lookup_before_the_final_state(monkeypatch):
    vision = FakeVision([bar()])
    vision.wrappers = [BAR]
    vision.facts = FACTS
    monkeypatch.setattr("itlogs.app.make_providers", lambda: (vision, FakeLLM()))
    with TestClient(app).websocket_connect("/ws/session") as ws:
        ws.send_text(json.dumps({"kind": "watch", "watch": {"on": True, "t_ms": 0}}))
        ws.send_text(
            json.dumps({"kind": "frame", "frame": {"t_ms": 1000, "width": 720, "height": 1280}})
        )
        ws.send_bytes(b"frame")
        ws.send_text(json.dumps({"kind": "end_session"}))
        final = None
        while final is None:
            m = json.loads(ws.receive_text())
            if m["kind"] == "state" and m.get("watching") is False:
                final = m
    assert final["entries"][0]["food"].startswith("Simply Protein")
    assert final["entries"][0]["nutrients"]["kcal"] == 160.0


async def test_the_reader_calls_the_responses_api_with_web_search():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path.endswith("/responses"):
            text = json.dumps(FACTS.model_dump(exclude={"source"}))
            output = [
                {"type": "web_search_call"},
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Here it is: " + text,
                            "annotations": [{"type": "url_citation", "url": "https://x.test/p"}],
                        }
                    ],
                },
            ]
            return httpx.Response(200, json={"output": output})
        content = json.dumps(BAR.model_dump())
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    r = MetaReader("https://x.test/v1", "muse-spark-1.3", transport=httpx.MockTransport(handler))
    label = await r.read_wrapper(b"jpeg")
    assert label == BAR
    facts = await r.find_facts(label)
    assert facts.kcal == 160.0
    assert facts.source == "https://x.test/p"
    path, body = seen[1]
    assert path.endswith("/responses")
    assert body["tools"] == [{"type": "web_search"}]
    assert "Simply Protein Crispy Dark Chocolate Almond, 40 g" in body["input"]
    assert seen[0][1]["response_format"]["json_schema"]["name"] == "wrapper"
