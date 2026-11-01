"""One logging session: the loop that checks every entry twice.

1. The phone streams frames; the server keeps only the latest few.
2. A deliberate trigger (the button, or "log it" by voice) reads the latest frame: food + grams.
3. A second frame, ``second_read_after_ms`` later, is read again.
4. Both reads agree: the entry is logged as *agreed* and spoken back. They differ: the server
   asks, by voice, and the wearer's answer logs the entry as *confirmed* or *corrected*, or
   cancels it.

Every entry therefore carries a label the loop produced for free, which is what the evals and
the open-weight recalibration (issue #4) feed on.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from itlogs import nutrients
from itlogs.models import Entry, EntryRead, Question, Reply, ServerMessage
from itlogs.providers.base import LLMProvider, VisionProvider


def fmt_grams(g: float) -> str:
    return f"{g:g}"


def same_food(a: str, b: str) -> bool:
    return nutrients.canonical(a) == nutrients.canonical(b)


@dataclass
class Session:
    vision: VisionProvider
    llm: LLMProvider
    second_read_after_ms: int = 1500
    grams_tolerance_g: float = 1.0
    entries: list[Entry] = field(default_factory=list)
    _frames: deque[tuple[int, bytes]] = field(default_factory=lambda: deque(maxlen=30))
    _first: tuple[EntryRead, int] | None = None  # waiting for the second look
    _question: tuple[Question, list[EntryRead]] | None = None  # waiting for the wearer

    # frames

    async def on_frame(self, jpeg: bytes, t_ms: int) -> list[ServerMessage]:
        self._frames.append((t_ms, jpeg))
        if self._first is None:
            return []
        first, first_ms = self._first
        if t_ms - first_ms < self.second_read_after_ms:
            return []
        self._first = None
        second = await self.vision.read_entry(jpeg)
        return [ServerMessage(kind="read", read=second), *self._resolve(first, second, t_ms)]

    # the trigger

    async def capture(self, t_ms: int) -> list[ServerMessage]:
        if not self._frames:
            return [ServerMessage(kind="say", say="No picture yet.")]
        if self._question is not None:
            q, _ = self._question
            return [ServerMessage(kind="say", say=q.text)]
        frame_ms, jpeg = self._frames[-1]
        read = await self.vision.read_entry(jpeg)
        if not read.readable:
            return [
                ServerMessage(kind="read", read=read),
                ServerMessage(kind="say", say="I could not read the scale."),
            ]
        self._first = (read, frame_ms)
        return [ServerMessage(kind="read", read=read)]

    # voice

    async def on_voice(self, text: str, t_ms: int = 0) -> list[ServerMessage]:
        context = self._question[0].text if self._question else ""
        reply = await self.llm.parse_reply(text, context)
        if self._question is None:
            if reply.action == "log":
                return await self.capture(t_ms)
            return []
        return self._answer(reply, t_ms)

    # resolution

    def _resolve(self, first: EntryRead, second: EntryRead, t_ms: int) -> list[ServerMessage]:
        if not second.readable:
            # one good look is still a read; ask rather than drop it
            return self._ask(first, second, t_ms)
        foods_agree = same_food(first.food, second.food)
        grams_agree = (
            first.grams is not None
            and second.grams is not None
            and abs(first.grams - second.grams) <= self.grams_tolerance_g
        )
        if foods_agree and grams_agree:
            assert first.grams is not None
            return self._log(first.food, first.grams, "agreed", [first, second], t_ms)
        return self._ask(first, second, t_ms)

    def _ask(self, first: EntryRead, second: EntryRead, t_ms: int) -> list[ServerMessage]:
        foods = [first.food]
        if second.readable and not same_food(first.food, second.food):
            foods.append(second.food)
        grams = [g for g in (first.grams, second.grams) if g is not None]
        grams = sorted(set(grams))
        if len(foods) == 1 and len(grams) > 1:
            text = f"{foods[0]}: {' or '.join(fmt_grams(g) for g in grams)} grams?"
        elif len(foods) > 1 and len(grams) == 1:
            text = f"{fmt_grams(grams[0])} grams: {' or '.join(foods)}?"
        elif len(foods) > 1:
            text = (
                f"{foods[0]} {fmt_grams(first.grams or 0)}, or {foods[1]} "
                f"{fmt_grams(second.grams or 0)} grams?"
            )
        else:
            text = f"{foods[0]}, {fmt_grams(grams[0])} grams?"
        q = Question(text=text, foods=foods, grams=grams)
        self._question = (q, [first, second])
        return [ServerMessage(kind="ask", ask=q), ServerMessage(kind="say", say=text)]

    def _answer(self, reply: Reply, t_ms: int) -> list[ServerMessage]:
        assert self._question is not None
        q, reads = self._question
        first = reads[0]
        if reply.action == "cancel":
            self._question = None
            return [ServerMessage(kind="say", say="Skipped.")]
        if reply.action == "confirm":
            self._question = None
            return self._log(first.food, first.grams or q.grams[0], "confirmed", reads, t_ms)
        if reply.action == "correct" and (reply.food or reply.grams is not None):
            self._question = None
            food = reply.food or first.food
            grams = reply.grams if reply.grams is not None else (first.grams or q.grams[0])
            status = "corrected"
            if (reply.food is None or same_food(food, first.food)) and (
                reply.grams is None or first.grams == reply.grams
            ):
                status = "confirmed"
            return self._log(food, grams, status, reads, t_ms)
        return [ServerMessage(kind="say", say=q.text)]

    def _log(
        self, food: str, grams: float, status: str, reads: list[EntryRead], t_ms: int
    ) -> list[ServerMessage]:
        food = nutrients.canonical(food)
        entry = Entry(
            index=len(self.entries) + 1,
            food=food,
            grams=grams,
            status=status,  # type: ignore[arg-type]
            reads=reads,
            nutrients=nutrients.for_grams(food, grams),
            t_ms=t_ms,
        )
        self.entries.append(entry)
        return [
            ServerMessage(kind="entry", entry=entry),
            ServerMessage(kind="say", say=f"{fmt_grams(grams)} grams of {food}, logged."),
        ]

    async def end_session(self, t_ms: int = 0) -> list[ServerMessage]:
        self._first = None
        self._question = None
        return [ServerMessage(kind="state", entries=list(self.entries))]
