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


async def test_a_spoken_entry_logs_without_a_camera_read():
    s = Session(FakeVision(), FakeLLM())
    out = await s.on_voice("113 g of apple", 100)
    assert kinds(out) == ["entry", "say"]
    e = s.entries[0]
    assert (e.food, e.grams, e.status) == ("apple", 113.0, "spoken")
    assert said(out) == ["113 grams of apple, logged."]


async def test_a_lone_number_with_no_question_is_ignored():
    s = Session(FakeVision(), FakeLLM())
    assert await s.on_voice("113", 100) == []


APPLE_113 = EntryRead(food="apple", grams=113.0, confidence=0.8)
EMPTY = EntryRead(food="none", grams=0.0, confidence=0.9)


async def feed(s, t0, n, step=1500):
    out = []
    for i in range(n):
        s.observe(b"f", t0 + i * step)
        out += s.ready()
        out += await s.decide(b"f", t0 + i * step)
    return out


async def test_quiet_weighing_logs_settled_foods_and_reads_the_list_back_at_the_end():
    # empty, then apple 113 on a still scene (one confident read logs it), still apple (not
    # logged again), empty, then rice
    reads = [UNREADABLE, APPLE_113, APPLE_113, APPLE_113, UNREADABLE, RICE_87, RICE_87, RICE_87]
    s = Session(FakeVision(reads), FakeLLM())
    out = await s.on_voice("I am weighing my food", 0)
    assert s.watching and said(out) == ["Weighing. One moment, the camera is starting."]
    out = await feed(s, 0, 8)
    assert said(out) == ["Ready. Put the first food on the scale."]  # then quiet per food
    assert [(e.food, e.grams, e.status) for e in s.entries] == [
        ("apple", 113.0, "auto"),
        ("cooked white rice", 87.0, "auto"),
    ]
    out = await s.end_session(20000)
    assert kinds(out) == ["state", "say"]
    # apple 113 g (59 kcal) plus rice 87 g (113 kcal); the list itself is on the phone
    assert said(out) == ["Done. 2 foods, 172 calories."]


async def test_a_doubtful_read_waits_for_a_second_that_agrees():
    doubtful = EntryRead(food="apple", grams=113.0, confidence=0.5)
    s = Session(FakeVision([doubtful, RICE_81, APPLE_113, APPLE_113]), FakeLLM())
    s.set_watching(True)
    await feed(s, 0, 2)
    assert s.entries == []  # 0.5 then a different value: nothing yet
    await feed(s, 3000, 2)
    assert [(e.food, e.grams) for e in s.entries] == [("apple", 113.0)]


async def test_ask_mode_asks_after_the_display_settles_and_yes_confirms():
    s = Session(FakeVision([UNREADABLE, APPLE_113, APPLE_113, APPLE_113]), FakeLLM())
    s.set_watching(True, ask=True)
    out = await feed(s, 0, 4)
    assert said(out) == ["Ready. Put the first food on the scale.", "113 grams of apple, right?"]
    assert s.entries == []
    out = await s.on_voice("yes", 7000)
    assert (s.entries[0].food, s.entries[0].status) == ("apple", "confirmed")
    # the display still shows 113 apple: not asked again
    assert all(m.kind == "read" for m in await feed(s, 8000, 2))


async def test_weighing_mode_another_apple_after_the_scale_was_emptied():
    apple_120 = EntryRead(food="apple", grams=120.0, confidence=0.9)
    reads = [APPLE_113, APPLE_113, UNREADABLE, UNREADABLE, apple_120, apple_120]
    s = Session(FakeVision(reads), FakeLLM())
    s.set_watching(True, ask=True)
    out = await feed(s, 0, 2)
    assert said(out) == ["Ready. Put the first food on the scale.", "113 grams of apple, right?"]
    await s.on_voice("yes", 3000)
    out = await feed(s, 4000, 4)  # two empty reads (one alone is a hand), then a second apple
    assert said(out) == ["120 grams of apple, right?"]


async def test_ask_mode_no_skips_and_done_speaks_the_summary():
    s = Session(FakeVision([RICE_87, RICE_87, RICE_87]), FakeLLM())
    s.set_watching(True, ask=True)
    out = await feed(s, 0, 2)
    assert said(out) == [
        "Ready. Put the first food on the scale.",
        "87 grams of cooked white rice, right?",
    ]
    out = await s.on_voice("no", 3000)
    assert said(out) == ["Skipped."] and s.entries == []
    out = await s.on_voice("done", 4000)
    assert not s.watching and said(out) == ["Done. Nothing logged."]


async def test_done_reads_the_list_after_entries():
    s = Session(FakeVision([RICE_87, RICE_87]), FakeLLM())
    s.set_watching(True, ask=True)
    await feed(s, 0, 2)
    await s.on_voice("yes", 3000)
    out = await s.on_voice("that's it", 4000)
    assert said(out) == ["Done. 1 food, 113 calories."]


async def test_stop_takes_a_final_look_at_what_is_on_the_scale():
    s = Session(FakeVision([UNREADABLE, APPLE_113]), FakeLLM())
    s.set_watching(True)
    await feed(s, 0, 1)  # the empty scale
    assert s.entries == []
    out = await s.final_look(3000)  # Stop with the apple on
    assert kinds(out) == ["read", "entry"]
    assert (s.entries[0].food, s.entries[0].status) == ("apple", "auto")
    out = await s.end_session(3100)
    assert said(out) == ["Done. 1 food, 59 calories."]


async def test_the_same_food_read_again_corrects_the_row_until_the_scale_empties():
    apple_108 = EntryRead(food="red apple", grams=108.0, confidence=0.9)
    reads = [APPLE_113, apple_108, UNREADABLE, UNREADABLE, APPLE_113]
    s = Session(FakeVision(reads), FakeLLM())
    s.set_watching(True)
    out = await feed(s, 0, 5)
    entries = [m.entry for m in out if m.kind == "entry"]
    assert [(e.index, e.grams) for e in entries] == [(1, 113.0), (1, 108.0), (2, 113.0)]
    assert [(e.food, e.grams) for e in s.entries] == [("apple", 108.0), ("apple", 113.0)]
    assert len(s.entries[0].reads) == 2


async def test_one_empty_read_between_two_looks_at_the_same_banana_is_not_a_second_banana():
    banana = EntryRead(food="whole banana", grams=128.0, confidence=0.95)
    s = Session(FakeVision([banana, UNREADABLE, banana, banana]), FakeLLM())
    s.set_watching(True)
    await feed(s, 0, 4)
    assert [(e.food, e.grams) for e in s.entries] == [("banana", 128.0)]


async def test_two_empty_reads_then_the_same_food_is_a_second_item():
    banana = EntryRead(food="banana", grams=128.0, confidence=0.95)
    s = Session(FakeVision([banana, UNREADABLE, UNREADABLE, banana]), FakeLLM(), same_again_ms=0)
    s.set_watching(True)
    await feed(s, 0, 4)
    assert [(e.food, e.grams) for e in s.entries] == [("banana", 128.0), ("banana", 128.0)]
