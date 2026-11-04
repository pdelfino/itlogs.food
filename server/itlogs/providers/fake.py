"""Deterministic providers for tests, the evals' replay mode and work without credits."""

from __future__ import annotations

import re

from itlogs.models import Addition, EntryRead, LabelFacts, Reply, WrapperLabel

WORD_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


class FakeVision:
    """Returns the scripted reads in order, then repeats the last one forever."""

    def __init__(self, reads: list[EntryRead] | None = None):
        default = EntryRead(food="cooked white rice", grams=87.0, confidence=0.9)
        self.reads = list(reads or [default])
        self.calls = 0
        self.additions: list[Addition] = []
        self.addition_calls: list[tuple[bytes | None, bytes, str]] = []
        self.wrappers: list[WrapperLabel] = []
        self.facts: LabelFacts | None = None
        self.wrapper_calls: list[bytes] = []
        self.facts_calls = 0
        self.typical: LabelFacts | None = None
        self.typical_calls: list[tuple[str, list[str]]] = []

    async def read_entry(self, jpeg: bytes) -> EntryRead:
        read = self.reads[min(self.calls, len(self.reads) - 1)]
        self.calls += 1
        return read

    async def read_addition(self, before: bytes | None, after: bytes, speech: str) -> Addition:
        self.addition_calls.append((before, after, speech))
        return self.additions.pop(0) if self.additions else Addition()

    async def read_wrapper(self, jpeg: bytes) -> WrapperLabel:
        self.wrapper_calls.append(jpeg)
        return self.wrappers.pop(0) if self.wrappers else WrapperLabel()

    async def find_facts(self, label: WrapperLabel) -> LabelFacts | None:
        self.facts_calls += 1
        return self.facts

    async def find_typical(self, name: str, seen: list[str]) -> LabelFacts | None:
        self.typical_calls.append((name, seen))
        return self.typical


class FakeLLM:
    """A regex stand-in for the reply parser; enough for the loop's tests."""

    async def parse_reply(self, text: str, context: str) -> Reply:
        t = text.strip().lower()
        if re.search(r"\b(done|that's it|that is it|finished|stop weighing)\b", t):
            return Reply(action="stop")
        if re.search(r"\b(weighing|start weighing|stay with me|hold on with me|let's weigh)\b", t):
            return Reply(action="start")
        if re.search(r"\b(log it|log this|log|weigh it|read it)\b", t):
            return Reply(action="log")
        if re.search(r"\b(cancel|skip|forget it|never mind|no)\b", t):
            return Reply(action="cancel")
        if re.search(r"\b(yes|yeah|yep|correct|right|the first)\b", t):
            return Reply(action="confirm")
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|grams?|gram)?\b\s*(?:of\s+)?([a-z][a-z ]*)?", t)
        if m:
            food = (m.group(2) or "").strip() or None
            return Reply(action="correct", food=food, grams=float(m.group(1)))
        if t in WORD_NUMBERS:
            return Reply(action="correct", grams=float(WORD_NUMBERS[t]))
        if t and context:
            return Reply(action="correct", food=t)
        return Reply(action="none")
