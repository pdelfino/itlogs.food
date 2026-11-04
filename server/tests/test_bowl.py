"""A bowl built one ingredient at a time (#22). The real reads of 2026-NOVEMBER-04 08:01 are the
main fixture: macadamia, pumpkin seeds, cashews and walnuts, one tare, about 104 g on the scale,
which the app had logged as 265 g in four rows."""

import json

import httpx

from itlogs.config import settings
from itlogs.models import Addition, EntryRead
from itlogs.providers.fake import FakeLLM, FakeVision
from itlogs.providers.meta import MetaReader
from itlogs.session import Session

# what the reader said at 08:01, from the first weight on: (grams, food)
REAL_READS = [
    (15.0, "chocolate chunks"),
    (None, "none"),
    (16.0, "chocolate cereal"),
    (None, "none"),
    (30.0, "walnuts"),
    (0.0, "ground beef"),
    (16.0, "dog kibble"),
    (16.0, "mixed nuts"),
    (16.0, "cashew nuts"),
    (15.0, "mixed nuts"),
    (15.0, "mixed nuts"),
    (15.0, "coffee grounds"),
    (15.0, "mixed nuts"),
    (66.0, "cashew nuts"),
    (59.0, "mixed nuts"),
    (62.0, "peanuts"),
    (None, "cooked food"),
    (60.0, "mixed nuts"),
    (66.0, "cashew nuts"),
    (66.0, "mixed nuts"),
    (66.0, "mixed nuts"),
    (74.0, "mixed nuts"),
    (74.0, "mixed nuts"),
    (74.0, "mixed nuts"),
]


def in_bowl(grams, food="mixed nuts", confidence=0.6):
    return EntryRead(food=food, grams=grams, confidence=confidence, container=True)


def session(*additions):
    vision = FakeVision()
    vision.additions = list(additions)
    s = Session(vision, FakeLLM())
    s.set_watching(True, 0)
    return s, vision


async def step(s, read, t, final=False):
    out = await s._bowl_step(read, f"frame{t}".encode(), t, final=final)
    return s._watch(read, t) if out is None else out


async def test_real_run_adds_up():
    s, _ = session(*[Addition(food=f, source="image", confidence=0.7) for f in "abcde"])
    for i, (grams, food) in enumerate(REAL_READS):
        await step(s, in_bowl(grams, food), 1000 * i)
    assert [e.grams for e in s.entries] == [16.0, 14.0, 16.0, 50.0, 8.0]
    assert sum(e.grams for e in s.entries) == 104.0  # 30 before the tare, 74 after; it was 265


async def test_speech_names_the_row_once():
    s, vision = session(
        Addition(food="cashews", source="speech", confidence=0.9),
        Addition(food="walnuts", source="image", confidence=0.6),
    )
    await s.on_voice("now the cashews")
    await step(s, in_bowl(50.0), 1000)
    await step(s, in_bowl(50.0), 2000)
    await step(s, in_bowl(58.0), 3000)
    await step(s, in_bowl(58.0), 4000)
    assert [(e.food, e.grams) for e in s.entries] == [("cashew nuts", 50.0), ("walnuts", 8.0)]
    assert vision.addition_calls[0][2] == "now the cashews"
    assert vision.addition_calls[1][2] == ""  # the speech was spent on the first row
    assert vision.addition_calls[1][0] == b"frame2000"  # the bowl before the walnuts
    assert vision.addition_calls[1][1] == b"frame4000"
    assert s.entries[0].nutrients is not None and s.entries[0].nutrients.kcal > 200
    assert "speech" in (s.entries[0].reads[-1].raw or "")


async def test_no_name_uses_the_reader():
    s, _ = session(Addition())
    await step(s, in_bowl(40.0, "almonds"), 1000)
    await step(s, in_bowl(40.0, "almonds"), 2000)
    assert s.entries[-1].food == "almonds"


async def test_failed_naming_keeps_the_row():
    s, vision = session()

    async def boom(before, after, speech):
        raise httpx.ConnectTimeout("")

    vision.read_addition = boom
    await step(s, in_bowl(40.0, "almonds"), 1000)
    await step(s, in_bowl(40.0, "almonds"), 2000)
    assert [(e.food, e.grams) for e in s.entries] == [("almonds", 40.0)]


async def test_empty_bowl_sets_the_start():
    s, _ = session(Addition(food="walnuts", source="image"))
    await step(s, in_bowl(120.0, "none"), 1000)
    assert s.entries == []
    await step(s, in_bowl(150.0), 2000)
    await step(s, in_bowl(150.0), 3000)
    assert [e.grams for e in s.entries] == [30.0]


async def test_stop_commits_unsettled():
    s, _ = session(Addition(food="walnuts", source="image"))
    await step(s, in_bowl(30.0), 1000)
    assert s.entries == []
    await step(s, in_bowl(30.0), 2000, final=True)
    assert [e.grams for e in s.entries] == [30.0]


async def test_late_read_is_ignored():
    s, _ = session(Addition(food="walnuts", source="image"))
    await step(s, in_bowl(30.0), 5000)
    assert await step(s, in_bowl(99.0), 1000) == []
    await step(s, in_bowl(30.0), 6000)
    assert [e.grams for e in s.entries] == [30.0]


async def test_foods_outside_a_bowl_keep_the_whole_number():
    """The best run (tag best-run-2026-11-03) went apple 112, banana 124 with no zero between."""
    reads = [
        EntryRead(food="apple", grams=112.0, confidence=0.95),
        EntryRead(food="banana", grams=124.0, confidence=0.92),
    ]
    vision = FakeVision(reads)
    s = Session(vision, FakeLLM())
    s.set_watching(True, 0)
    await s.on_frame(b"a", 1000)
    await s.on_frame(b"b", 6000)
    assert [(e.food, e.grams) for e in s.entries] == [("apple", 112.0), ("banana", 124.0)]
    assert vision.addition_calls == []


async def test_empty_scale_ends_the_bowl():
    s, _ = session(Addition(food="walnuts", source="image"))
    await step(s, in_bowl(30.0), 1000)
    await step(s, in_bowl(30.0), 2000)
    for t in (3000, 4000):
        await step(s, EntryRead(food="none", grams=0.0, confidence=0.9), t)
    assert s._bowl_active is False
    s._last_read_still = True
    await step(s, EntryRead(food="apple", grams=112.0, confidence=0.95), 5000)
    assert [(e.food, e.grams) for e in s.entries] == [("walnuts", 30.0), ("apple", 112.0)]


async def test_switch_turns_it_off(monkeypatch):
    monkeypatch.setattr(settings, "bowl", False)
    s, _ = session()
    assert await s._bowl_step(in_bowl(30.0), b"f", 1000) is None
    assert s._bowl_active is False


async def test_provider_sends_both_pictures():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if body["response_format"]["json_schema"]["name"] == "addition":
            payload = {"food": " Cashews ", "source": "speech", "confidence": 0.9}
        else:
            payload = {
                "food": "nuts",
                "display_value": 16,
                "unit": "g",
                "confidence": 0.8,
                "container": True,
            }
        content = json.dumps(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    r = MetaReader("https://x.test/v1", "m", transport=httpx.MockTransport(handler))
    assert (await r.read_entry(b"jpeg")).container is True
    add = await r.read_addition(b"before", b"after", "now the cashews")
    assert (add.food, add.source) == ("cashews", "speech")
    content = seen[1]["messages"][1]["content"]
    assert [c["type"] for c in content] == ["text", "image_url", "image_url"]
    assert "now the cashews" in content[0]["text"]
    await r.read_addition(None, b"after", "")
    assert [c["type"] for c in seen[2]["messages"][1]["content"]] == ["text", "image_url"]
