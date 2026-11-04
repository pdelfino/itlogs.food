"""One logging session: the loop that checks every entry twice.

Two ways in:

- **Log it** (the button, or "log it" by voice): read the latest frame, read the frame about
  ``second_read_after_ms`` later, log when the two agree, ask when they differ.
- **Weighing mode** (on from Start, or "I'm weighing my food"): the server reads a frame every
  ``watch_every_ms`` on its own. When the display settles on a new value (two reads in a row
  with the same food and grams, different from what was last logged) the food is logged
  quietly (status ``auto``; the phone ticks). Stop, or "done", reads the whole list back:
  "cooked white rice, 87 grams. apple, 113 grams." With ``ask`` on, the ear instead asks
  "113 grams of apple, right?" after each food and nothing is logged without the wearer's word.

Every entry carries a label the loop produced for free (agreed, confirmed, corrected,
spoken), which is what the evals and the open-weight recalibration (issue #4) feed on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from itlogs import nutrients
from itlogs.frames import Settle, difference, thumbnail
from itlogs.models import Entry, EntryRead, Question, Reply, ServerMessage
from itlogs.providers.base import LLMProvider, VisionProvider
from itlogs.providers.openfoodfacts import Product

DISPLAY_HINT = "I can see the food but not the display. Look down at the scale."


def fmt_grams(g: float) -> str:
    return f"{g:g}"


def same_food(a: str, b: str) -> bool:
    return nutrients.canonical(a) == nutrients.canonical(b)


def same_item(a: str, b: str) -> bool:
    """The same thing on the scale under two names: "banana" and "whole banana", "apple" and
    "red apple". Canonical names equal, or one name's words inside the other's."""
    if same_food(a, b):
        return True
    wa, wb = set(nutrients.canonical(a).split()), set(nutrients.canonical(b).split())
    return bool(wa) and bool(wb) and (wa <= wb or wb <= wa)


@dataclass
class Session:
    vision: VisionProvider
    llm: LLMProvider
    second_read_after_ms: int = 1500
    grams_tolerance_g: float = 1.0
    watch_every_ms: int = 1500
    entries: list[Entry] = field(default_factory=list)
    watching: bool = False
    ask: bool = False  # weighing mode: ask after each food, or log quietly and read back at the end
    # the recent frames, and whether the scene is still: the reader sees the sharpest frame of a
    # still second, not whatever arrived last (the first live read, 2026-NOVEMBER-02 18:15, was a
    # hand on the apple and a display at 0)
    settle: Settle = field(default_factory=Settle)
    _first: tuple[EntryRead, int] | None = None  # "log it": waiting for the second look
    _question: tuple[Question, list[EntryRead]] | None = None  # waiting for the wearer
    _last_watch_ms: int = -1_000_000
    _watch_prev: EntryRead | None = None  # the previous read in weighing mode
    _watch_logged: EntryRead | None = None  # what the display showed when last asked
    _said_negative: bool = False  # the tare hint, once per session
    _last_read_thumb: list[int] | None = None  # the scene the reader last saw (weighing mode)
    _emptied: bool = True  # the scale read empty since the last logged food (a new food can come)
    _empty_streak: int = 0  # consecutive empty reads; one alone can be a hand over the display
    same_again_ms: int = 30000  # the same food at the same grams within this: one item, not two
    _ready_said: bool = False  # "Ready" is said on the first frame after Start, not at Start
    max_wait_ms: int = 4000  # weighing mode: read anyway after this long without a still second
    # weighing mode logs on one confident read of a still scene: the model takes 3 to 5 s per read
    # and at a normal pace the food is gone before a second look (19:18, "red apple 112 g" read
    # once, then the empty scale). A read taken without stillness still needs a second that agrees.
    single_read_confidence: float = 0.8
    _last_read_still: bool = False
    _last_frame_ms: int | None = None
    _watch_started_ms: int = -1_000_000
    # a scanned product (#13): names the next food and brings the label's nutrients; the reads
    # then only have to agree on the grams. _last_product keeps the row for a quiet correction.
    # the reader names a food but cannot read the display (21:58: 64 reads named a food, 1 had
    # a weight, and the ear said nothing for four and a half minutes): say so
    _no_display_reads: int = 0
    _last_hint_ms: int = -1_000_000
    display_hint_every_ms: int = 30_000
    _product: Product | None = None
    _product_ms: int = 0
    _last_product: Product | None = None
    product_ttl_ms: int = 60_000  # a scan nobody weighs must not name a food much later

    # a barcode

    @property
    def product_pending(self) -> bool:
        """A scanned product is waiting for its food to land on the scale."""
        return self._live_product() is not None

    def _live_product(self) -> Product | None:
        now = self._last_frame_ms
        if self._product is not None and now is not None:
            if now - self._product_ms > self.product_ttl_ms:
                self._product = None
        return self._product

    def set_product(
        self, product: Product | None, code: str = "", t_ms: int = 0
    ) -> list[ServerMessage]:
        """A barcode was decoded. Known: the product is the next food on the scale, or, when a
        food the table did not know was logged in the last half minute (21:23: "protein bar",
        42 g, no row, then the wrapper shown), that food. Unknown: say so; the scale and the
        reader go on as usual."""
        if product is None:
            return [ServerMessage(kind="say", say="I don't know that barcode.")]
        if self.entries:
            last = self.entries[-1]
            fresh = t_ms - last.t_ms < self.same_again_ms
            if last.product is None and last.nutrients is None and fresh:
                relabeled = last.model_copy(
                    update={
                        "food": product.name,
                        "nutrients": nutrients.scale(product.per100g, last.grams),
                        "product": product.ean,
                    }
                )
                self.entries[-1] = relabeled
                self._last_product = product
                line = f"{product.name}, {fmt_grams(last.grams)} grams, logged."
                return [
                    ServerMessage(kind="entry", entry=relabeled),  # same index: replaced
                    ServerMessage(kind="say", say=line),
                ]
        self._product = product
        self._product_ms = t_ms
        self._emptied = True  # the product is a new food even if the scale never read empty
        return [ServerMessage(kind="say", say=f"{product.name}. Put it on the scale.")]

    # frames

    async def on_frame(self, jpeg: bytes, t_ms: int) -> list[ServerMessage]:
        """Observe the frame, then decide; one call, as the tests and evals drive it."""
        self.observe(jpeg, t_ms)
        return await self.decide(jpeg, t_ms)

    def observe(self, jpeg: bytes, t_ms: int) -> None:
        """Cheap, for every frame: keeps the recent frames and whether the scene is still."""
        self.settle.observe(jpeg, t_ms)
        self._last_frame_ms = t_ms

    def ready(self) -> list[ServerMessage]:
        """Said once, on the first frame after Start: the stream takes about six seconds to begin,
        and on 2026-NOVEMBER-02 19:12 the weighing was done before the camera was on."""
        if self._ready_said or not self.watching:
            return []
        self._ready_said = True
        return [ServerMessage(kind="say", say="Ready. Put the first food on the scale.")]

    async def decide(self, jpeg: bytes, t_ms: int) -> list[ServerMessage]:
        """The model call, when one is due. The app runs this in the background, one at a time,
        so the frames keep flowing while the reader thinks (#12)."""
        if self._first is not None:
            first, first_ms = self._first
            if t_ms - first_ms < self.second_read_after_ms:
                return []
            self._first = None
            _, best = self.settle.sharpest(t_ms - 700, t_ms) or (t_ms, jpeg)
            second = await self.vision.read_entry(best)
            return [ServerMessage(kind="read", read=second), *self._resolve(first, second, t_ms)]
        if self.watching and self._question is None:
            if t_ms - self._last_watch_ms < self.watch_every_ms:
                return []
            waited = t_ms - max(self._last_watch_ms, self._watch_started_ms)
            if not self.settle.still(t_ms) and waited < self.max_wait_ms:
                return []  # a hand, a moving plate: not worth a model call (but never wait forever)
            since = max(self.settle.still_since() or t_ms, t_ms - 1000)
            _, best = self.settle.sharpest(since, t_ms) or (t_ms, jpeg)
            thumb = thumbnail(best)
            if (
                self._watch_logged is not None
                and thumb is not None
                and self._last_read_thumb is not None
                and difference(self._last_read_thumb, thumb) <= self.settle.move
            ):
                return []  # the same scene the logged value came from: no new model call
            self._last_watch_ms = t_ms
            self._last_read_thumb = thumb
            self._last_read_still = self.settle.still(t_ms)
            read = await self.vision.read_entry(best)
            return [ServerMessage(kind="read", read=read), *self._watch(read, t_ms)]
        return []

    # the trigger

    async def capture(self, t_ms: int) -> list[ServerMessage]:
        if self.settle.latest is None:
            return [ServerMessage(kind="say", say="No picture yet.")]
        if self._question is not None:
            q, _ = self._question
            return [ServerMessage(kind="say", say=q.text)]
        latest_ms = self.settle.latest[0]
        frame_ms, jpeg = self.settle.sharpest(latest_ms - 1000, latest_ms) or self.settle.latest
        read = await self.vision.read_entry(jpeg)
        if not read.readable:
            return [
                ServerMessage(kind="read", read=read),
                ServerMessage(kind="say", say="I could not read the scale."),
            ]
        self._first = (read, frame_ms)
        return [ServerMessage(kind="read", read=read)]

    # weighing mode

    def set_watching(self, on: bool, t_ms: int = 0, ask: bool | None = None) -> list[ServerMessage]:
        if ask is not None:
            self.ask = ask
        if on and not self.watching:
            self.watching = True
            self._watch_prev = None
            self._watch_logged = None
            self._last_watch_ms = -1_000_000
            self._watch_started_ms = t_ms
            self._ready_said = False
            out = [ServerMessage(kind="state", entries=list(self.entries), watching=True)]
            if self._last_frame_ms is None:
                out.append(
                    ServerMessage(kind="say", say="Weighing. One moment, the camera is starting.")
                )
            else:
                out.extend(self.ready())
            return out
        if not on and self.watching:
            self.watching = False
            self._question = None
            return [
                ServerMessage(kind="state", entries=list(self.entries), watching=False),
                ServerMessage(kind="say", say=self.summary()),
            ]
        return []

    def _watch(self, read: EntryRead, t_ms: int) -> list[ServerMessage]:
        prev, self._watch_prev = self._watch_prev, read
        if read.grams is not None:
            self._no_display_reads = 0
        elif read.food != "none":
            self._no_display_reads += 1
        if not read.readable:
            # the scale is empty or tared: the next value, even the same one, is a new food.
            # Two empties in a row, though: one alone was a hand over the display (19:57, the
            # banana logged twice around a single "0 g").
            self._empty_streak += 1
            if self._empty_streak >= 2:
                self._watch_logged = None
                self._emptied = True
            if read.grams is not None and read.grams < 0 and not self._said_negative:
                self._said_negative = True
                hint = "The scale shows a negative number. Lift everything off and tare it."
                return [ServerMessage(kind="say", say=hint)]
            return self._display_hint(t_ms)
        self._empty_streak = 0
        if self._watch_logged is not None and self._agree(read, self._watch_logged):
            return []  # still showing what was already asked about
        if self.entries and self._same_item_again(read, t_ms):
            self._watch_logged = read
            return []  # the banana again, same grams, seconds later: one banana
        confident_still = self._last_read_still and read.confidence >= self.single_read_confidence
        agrees_with_prev = prev is not None and prev.readable and self._agree(read, prev)
        if not confident_still and not agrees_with_prev:
            return []  # the display may still be changing; wait for two reads in a row
        if not self._emptied and self.entries and self._still_the_same(read):
            # the same food, still on the scale, read again with another number or another name
            # (19:51: "apple 108" then "apple 112", "banana 128" then "whole banana 128"; 21:43:
            # "protein bar 43" then "granola bar 43"): this corrects the last row instead of
            # adding one
            return self._correct_last(read, t_ms)
        self._watch_logged = read
        self._emptied = False
        if self.ask:
            return self._ask(read, read, t_ms, confirm_only=True)
        assert read.grams is not None
        # quiet: log it, the phone ticks, the list is read back at the end
        reads = [read] if prev is None or not prev.readable else [prev, read]
        return self._log(read.food, read.grams, "auto", reads, t_ms, speak=False)

    def _same_item_again(self, read: EntryRead, t_ms: int) -> bool:
        last = self.entries[-1]
        return (
            read.grams is not None
            and same_item(read.food, last.food)
            and abs(read.grams - last.grams) <= self.grams_tolerance_g
            and t_ms - last.t_ms < self.same_again_ms
        )

    def _display_hint(self, t_ms: int) -> list[ServerMessage]:
        """Two reads named a food with no weight since the last number: one sentence in the ear,
        at most every half minute. One such read alone is a hand passing over the display."""
        if self._no_display_reads < 2 or t_ms - self._last_hint_ms < self.display_hint_every_ms:
            return []
        self._last_hint_ms = t_ms
        return [ServerMessage(kind="say", say=DISPLAY_HINT)]

    def _still_the_same(self, read: EntryRead) -> bool:
        """The last food never left the scale (no empty read since), so a new read is the same
        item: under a kindred name, or under any name at the same grams. Two different foods
        cannot show the same weight without the scale passing through empty."""
        last = self.entries[-1]
        if same_item(read.food, last.food):
            return True
        return read.grams is not None and abs(read.grams - last.grams) <= self.grams_tolerance_g

    def _correct_last(self, read: EntryRead, t_ms: int) -> list[ServerMessage]:
        last = self.entries[-1]
        if last.status != "auto" or read.grams is None:
            return []  # the wearer's word stands; only quiet entries are corrected quietly
        if last.product and self._last_product is not None:
            # a scanned product keeps its name and its label's row, at the new grams
            food = last.food
            row = nutrients.scale(self._last_product.per100g, read.grams)
        else:
            keep_name = nutrients.lookup(last.food) or not nutrients.lookup(read.food)
            food = nutrients.canonical(last.food if keep_name else read.food)
            row = nutrients.for_grams(food, read.grams)
        corrected = last.model_copy(
            update={
                "food": food,
                "grams": read.grams,
                "reads": [*last.reads, read],
                "nutrients": row,
            }
        )
        self.entries[-1] = corrected
        self._watch_logged = read
        return [ServerMessage(kind="entry", entry=corrected)]  # same index: the phone replaces

    def _agree(self, a: EntryRead, b: EntryRead) -> bool:
        # with a scanned product the name is known: the reads only have to agree on the grams
        # (a wrapper read as "protein bar" then "granola bar", 2026-NOVEMBER-03 21:09)
        return (
            (self._live_product() is not None or same_food(a.food, b.food))
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
        self,
        food: str,
        grams: float,
        status: str,
        reads: list[EntryRead],
        t_ms: int,
        speak: bool = True,
    ) -> list[ServerMessage]:
        product, self._product = self._live_product(), None
        self._last_product = product
        if product is not None:
            food = product.name  # the label's name, as printed
            row = nutrients.scale(product.per100g, grams)
        else:
            food = nutrients.canonical(food)
            row = nutrients.for_grams(food, grams)
        entry = Entry(
            index=len(self.entries) + 1,
            food=food,
            grams=grams,
            status=status,  # type: ignore[arg-type]
            reads=reads,
            nutrients=row,
            t_ms=t_ms,
            product=product.ean if product else None,
        )
        self.entries.append(entry)
        self._emptied = False
        out = [ServerMessage(kind="entry", entry=entry)]
        if speak:
            line = f"{fmt_grams(grams)} grams of {food}, logged."
            out.append(ServerMessage(kind="say", say=line))
        return out

    def summary(self) -> str:
        """What the ear hears at the end: the count and the calories. The list itself is on the
        phone (the review table); reading it out was too much (Pedro, 2026-NOVEMBER-02)."""
        if not self.entries:
            return "Done. Nothing logged."
        return "Check the meal."  # the table is on the phone; Pedro: "just say check the meal"

    async def final_look(self, t_ms: int = 0) -> list[ServerMessage]:
        """At Stop: read whatever is on the scale now, so the last food is never lost to the
        reader's latency (19:18: the second food went on after the apple and Stop came first)."""
        if not self.watching or self.settle.latest is None or self._question is not None:
            return []
        latest_ms = self.settle.latest[0]
        _, best = self.settle.sharpest(latest_ms - 2000, latest_ms) or self.settle.latest
        thumb = thumbnail(best)
        if (
            self._watch_logged is not None
            and thumb is not None
            and self._last_read_thumb is not None
            and difference(self._last_read_thumb, thumb) <= self.settle.move
        ):
            return []  # the same scene the last logged value came from
        self._last_read_thumb = thumb
        self._last_read_still = True  # the wearer is done moving; one confident read is enough
        self._last_hint_ms = t_ms or latest_ms  # no instruction once the wearer pressed Stop
        read = await self.vision.read_entry(best)
        return [ServerMessage(kind="read", read=read), *self._watch(read, t_ms or latest_ms)]

    async def end_session(self, t_ms: int = 0) -> list[ServerMessage]:
        self._first = None
        self._question = None
        was_watching = self.watching
        self.watching = False
        out = [ServerMessage(kind="state", entries=list(self.entries), watching=False)]
        if was_watching:
            out.append(ServerMessage(kind="say", say=self.summary()))
        return out
