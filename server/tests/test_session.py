"""The loop on the fake providers: agree, disagree then confirm or correct, cancel, voice."""

import pytest

from itlogs.models import EntryRead
from itlogs.providers.fake import FakeLLM, FakeVision
from itlogs.session import Session

RICE_87 = EntryRead(food="cooked white rice", grams=87.0, confidence=0.9)
RICE_81 = EntryRead(food="cooked white rice", grams=81.0, confidence=0.7)
QUINOA_87 = EntryRead(food="quinoa", grams=87.0, confidence=0.6)
UNREADABLE = EntryRead(food="none", grams=None, confidence=0.0)


def kinds(msgs):
    return [m.kind for m in msgs]


def said(msgs):
    return [m.say for m in msgs if m.kind == "say"]


async def run(reads, t_second=2000):
    s = Session(FakeVision(reads), FakeLLM())
    await s.on_frame(b"a", 0)
    out = await s.capture(0)
    out += await s.on_frame(b"b", 500)  # too early for the second look
    out += await s.on_frame(b"c", t_second)
    return s, out


async def test_two_matching_reads_log_the_entry_as_agreed():
    s, out = await run([RICE_87, RICE_87])
    assert kinds(out) == ["read", "read", "entry", "say"]
    assert said(out) == ["87 grams of cooked white rice, logged."]
    e = s.entries[0]
    assert (e.food, e.grams, e.status, len(e.reads)) == ("cooked white rice", 87.0, "agreed", 2)
    assert e.nutrients is not None and e.nutrients.kcal == pytest.approx(113.1)


async def test_grams_within_tolerance_still_agree():
    s, _ = await run([RICE_87, EntryRead(food="rice", grams=87.5, confidence=0.8)])
    assert s.entries[0].status == "agreed"


async def test_disagreeing_grams_ask_then_a_number_corrects():
    s, out = await run([RICE_87, RICE_81])
    assert kinds(out) == ["read", "read", "ask", "say"]
    assert said(out) == ["cooked white rice: 81 or 87 grams?"]
    assert s.entries == []
    out = await s.on_voice("81", 3000)
    assert kinds(out) == ["entry", "say"]
    assert (s.entries[0].grams, s.entries[0].status) == (81.0, "corrected")


async def test_disagreeing_food_asks_then_yes_confirms_the_first_read():
    s, out = await run([RICE_87, QUINOA_87])
    assert said(out) == ["87 grams: cooked white rice or quinoa?"]
    out = await s.on_voice("yes", 3000)
    assert (s.entries[0].food, s.entries[0].status) == ("cooked white rice", "confirmed")
    assert said(out) == ["87 grams of cooked white rice, logged."]


async def test_a_food_name_corrects_the_food():
    s, _ = await run([RICE_87, QUINOA_87])
    await s.on_voice("quinoa", 3000)
    assert (s.entries[0].food, s.entries[0].status) == ("quinoa", "corrected")
    assert s.entries[0].nutrients is None  # not in the placeholder table


async def test_no_cancels_the_question():
    s, _ = await run([RICE_87, RICE_81])
    out = await s.on_voice("no", 3000)
    assert said(out) == ["Skipped."] and s.entries == []
    # the loop is free again
    assert kinds(await s.capture(4000)) == ["read"]


async def test_unreadable_first_look_says_so_and_does_not_wait():
    s = Session(FakeVision([UNREADABLE]), FakeLLM())
    await s.on_frame(b"a", 0)
    out = await s.capture(0)
    assert said(out) == ["I could not read the scale."]
    assert await s.on_frame(b"b", 5000) == []


async def test_unreadable_second_look_asks_about_the_first():
    s, out = await run([RICE_87, UNREADABLE])
    assert said(out) == ["cooked white rice, 87 grams?"]
    await s.on_voice("yes", 3000)
    assert s.entries[0].status == "confirmed"


async def test_voice_log_it_triggers_the_capture():
    s = Session(FakeVision([RICE_87, RICE_87]), FakeLLM())
    await s.on_frame(b"a", 0)
    out = await s.on_voice("log it", 100)
    assert kinds(out) == ["read"]
    out = await s.on_frame(b"b", 2000)
    assert s.entries[0].status == "agreed"


async def test_capture_before_any_frame():
    s = Session(FakeVision(), FakeLLM())
    assert said(await s.capture(0)) == ["No picture yet."]


async def test_end_session_reports_the_entries():
    s, _ = await run([RICE_87, RICE_87])
    out = await s.end_session()
    assert kinds(out) == ["state"] and len(out[0].entries) == 1
