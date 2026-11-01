"""One logging session: the loop that checks every entry twice.

Two ways in:

- **Log it** (the button, or "log it" by voice): read the latest frame, read the frame about
  ``second_read_after_ms`` later, log when the two agree, ask when they differ.
- **Weighing mode** ("I'm weighing my food", or the button): the server reads a frame every
  ``watch_every_ms`` on its own. When the display settles on a new value (two reads in a row
  with the same food and grams, different from what was last logged) it asks "113 grams of
  apple, right?" and the wearer answers yes, a correction, or no. "Done" ends the mode and
  the ear hears the totals. Nothing is logged without the wearer's word in this mode.

Every entry carries a label the loop produced for free (agreed, confirmed, corrected,
spoken), which is what the evals and the open-weight recalibration (issue #4) feed on.
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
    watch_every_ms: int = 1500
    entries: list[Entry] = field(default_factory=list)
    watching: bool = False
    _frames: deque[tuple[int, bytes]] = field(default_factory=lambda: deque(maxlen=30))
    _first: tuple[EntryRead, int] | None = None  # "log it": waiting for the second look
    _question: tuple[Question, list[EntryRead]] | None = None  # waiting for the wearer
    _last_watch_ms: int = -1_000_000
    _watch_prev: EntryRead | None = None  # the previous read in weighing mode
    _watch_logged: EntryRead | None = None  # what the display showed when last asked

    # frames

    async def on_frame(self, jpeg: bytes, t_ms: int) -> list[ServerMessage]:
        self._frames.append((t_ms, jpeg))
        if self._first is not None:
            first, first_ms = self._first
            if t_ms - first_ms < self.second_read_after_ms:
                return []
            self._first = None
            second = await self.vision.read_entry(jpeg)
            return [ServerMessage(kind="read", read=second), *self._resolve(first, second, t_ms)]
        if self.watching and self._question is None:
            if t_ms - self._last_watch_ms < self.watch_every_ms:
                return []
            self._last_watch_ms = t_ms
            read = await self.vision.read_entry(jpeg)
            return [ServerMessage(kind="read", read=read), *self._watch(read, t_ms)]
        return []

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

    # weighing mode

    def set_watching(self, on: bool, t_ms: int = 0) -> list[ServerMessage]:
        if on and not self.watching:
            self.watching = True
            self._watch_prev = None
            self._watch_logged = None
            self._last_watch_ms = -1_000_000
            return [
                ServerMessage(kind="state", entries=list(self.entries), watching=True),
                ServerMessage(kind="say", say="Weighing. Put the first food on the scale."),
            ]
        if not on and self.watching:
            self.watching = False
            self._question = None
            return [
                ServerMessage(kind="state", entries=list(self.entries), watching=False),
                ServerMessage(kind="say", say=self._totals_line()),
            ]
        return []

    def _watch(self, read: EntryRead, t_ms: int) -> list[ServerMessage]:
        prev, self._watch_prev = self._watch_prev, read
        if not read.readable:
            # the scale is empty or tared: the next value, even the same one, is a new food
            self._watch_logged = None
            return []
        if self._watch_logged is not None and self._agree(read, self._watch_logged):
            return []  # still showing what was already asked about
        if prev is None or not prev.readable or not self._agree(read, prev):
            return []  # the display is still changing; wait for two reads in a row
        self._watch_logged = read
        return self._ask(read, read, t_ms, confirm_only=True)

    def _agree(self, a: EntryRead, b: EntryRead) -> bool:
        return (
            same_food(a.food, b.food)
            and a.grams is not None
            and b.grams is not None
            and abs(a.grams - b.grams) <= self.grams_tolerance_g
        )

    # voice

    async def on_voice(self, text: str, t_ms: int = 0) -> list[ServerMessage]:
        context = self._question[0].text if self._question else ""
        reply = await self.llm.parse_reply(text, context)
        if reply.action == "start":
            return self.set_watching(True, t_ms)
        if reply.action == "stop":
            return self.set_watching(False, t_ms)
        if self._question is None:
            if reply.action == "log":
                return await self.capture(t_ms)
            if reply.action == "correct" and reply.food and reply.grams is not None:
                # "113 grams of apple": the wearer logged it by voice, no camera read
                self._first = None
                return self._log(reply.food, reply.grams, "spoken", [], t_ms)
            return []
        return self._answer(reply, t_ms)

    # resolution

    def _resolve(self, first: EntryRead, second: EntryRead, t_ms: int) -> list[ServerMessage]:
        if not second.readable:
            # one good look is still a read; ask rather than drop it
            return self._ask(first, second, t_ms)
        if self._agree(first, second):
            assert first.grams is not None
            return self._log(first.food, first.grams, "agreed", [first, second], t_ms)
        return self._ask(first, second, t_ms)

    def _ask(
        self, first: EntryRead, second: EntryRead, t_ms: int, confirm_only: bool = False
    ) -> list[ServerMessage]:
        foods = [first.food]
        if second.readable and not same_food(first.food, second.food):
            foods.append(second.food)
        grams = [g for g in (first.grams, second.grams) if g is not None]
        grams = sorted(set(grams))
        if confirm_only:
            text = f"{fmt_grams(grams[0])} grams of {foods[0]}, right?"
        elif len(foods) == 1 and len(grams) > 1:
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
        self._question = (q, [first] if second is first else [first, second])
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

    def _totals_line(self) -> str:
        n = len(self.entries)
        if n == 0:
            return "Done. Nothing logged."
        known = [e.nutrients for e in self.entries if e.nutrients]
        foods = "food" if n == 1 else "foods"
        if not known:
            return f"Done. {n} {foods} logged."
        kcal = round(sum(k.kcal for k in known))
        protein = round(sum(k.protein_g for k in known))
        return f"Done. {n} {foods}, {kcal} calories, {protein} grams of protein."

    async def end_session(self, t_ms: int = 0) -> list[ServerMessage]:
        self._first = None
        self._question = None
        self.watching = False
        return [ServerMessage(kind="state", entries=list(self.entries), watching=False)]
