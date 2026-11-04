"""Meta models behind the two protocols.

The reader: Muse Spark (muse-spark-1.3) on the Meta Model API, Muse Spark Open on Baseten, or
Muse Glimmer with its vision projector on this Mac through llama-server; the last two are the
open-weight paths. One still in, the food and the display value out, as structured output. For a
bowl, two stills and what was said in, the one ingredient added out. The parser: the same client
on a text prompt.

Docs: docs/meta-model-api-notes.org. Standard-mode model ids only (no "-contributor":
those train on the content, and the content is the wearer's kitchen).
"""

from __future__ import annotations

import asyncio
import io
import time

import httpx
from PIL import Image

from itlogs.config import settings
from itlogs.models import Addition, EntryRead, LabelFacts, Reply, WrapperLabel
from itlogs.providers.chat import ChatModel, json_object

ENTRY_SCHEMA = {
    "name": "entry_read",
    "schema": {
        "type": "object",
        "properties": {
            "food": {"type": "string"},
            "display_value": {"type": ["number", "null"]},
            "unit": {"type": "string", "enum": ["g", "kg", "oz", "lb", "ml", "unknown"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "container": {"type": "boolean"},
        },
        "required": ["food", "display_value", "unit", "confidence", "container"],
    },
}

ENTRY_SYSTEM = (
    "You read a kitchen scale from one photo taken by a camera worn on the head. A food item "
    "sits on the scale and the scale's digital display shows a number. Name the food in two "
    'or three plain lowercase words (for example "cooked white rice", "chicken breast", '
    '"egg whites"), or "none" when nothing is on the scale. Read the number on the display '
    "exactly as shown, digit by digit, with its unit. A kitchen scale shows grams unless the "
    'display says oz, lb, kg or ml; when no unit is visible, the unit is "g". When the display '
    "is not readable (glare, out of frame, blurred, mid-change), display_value is null and "
    "confidence is 0. "
    'A plate, bowl, cup or container with nothing in it is "none": the container is never the '
    "food; when it holds food, name the food. container is true when a bowl, plate, cup or other "
    "vessel sits on the scale, and false when the food sits directly on it. "
    "Never guess a weight from the look of the food. Answer only with the JSON object."
)

REPLY_SCHEMA = {
    "name": "reply",
    "schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "log", "confirm", "correct", "cancel", "none"],
            },
            "food": {"type": ["string", "null"]},
            "grams": {"type": ["number", "null"]},
        },
        "required": ["action", "food", "grams"],
    },
}

REPLY_SYSTEM = (
    "You turn one spoken sentence from a person weighing food in their kitchen into a "
    'structured reply for a hands-free food logger. Actions: "start" when they begin a '
    'weighing session ("I am weighing my food", "stay with me", "let\'s weigh"); "stop" when '
    'they end it ("done", "that\'s it", "finished"); "log" when they ask for one reading '
    '("log it", "weigh this"); "confirm" when they accept what was asked ("yes", '
    '"the first one", "correct"); "correct" when they give the food and/or the grams '
    '("81", "it is quinoa", "rice, 87"); "cancel" when they decline ("no", "skip", '
    '"forget it"); "none" when the sentence is not for the logger. Numbers spoken as words '
    "become digits; grams is a number of grams. Never add commentary."
)

TO_GRAMS = {"g": 1.0, "kg": 1000.0, "oz": 28.349523125, "lb": 453.59237, "ml": 1.0}

MODEL_LONG_SIDE = 1024  # the digits of a scale display are large; fewer image tokens, faster reads


def number(value: object) -> float | None:
    """A model's number, or None when it sent something else ("112g"): an unreadable read."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def shrink(jpeg: bytes) -> bytes:
    """The copy the model sees: at most MODEL_LONG_SIDE on the long side. The recording keeps the
    original. Bytes that are not an image (tests) pass through."""
    try:
        im = Image.open(io.BytesIO(jpeg))
        im.load()
    except Exception:
        return jpeg
    w, h = im.size
    if max(w, h) <= MODEL_LONG_SIDE:
        return jpeg
    scale = MODEL_LONG_SIDE / max(w, h)
    im = im.convert("RGB").resize((round(w * scale), round(h * scale)))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=85)
    return out.getvalue()


ADDITION_SCHEMA = {
    "name": "addition",
    "schema": {
        "type": "object",
        "properties": {
            "food": {"type": "string"},
            "source": {"type": "string", "enum": ["speech", "image", "none"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["food", "source", "confidence"],
    },
}

ADDITION_SYSTEM = (
    "A person is building a bowl of food on a kitchen scale, one ingredient at a time, wearing a "
    "head-worn camera. Name the one ingredient just added, in one to three plain lowercase words. "
    "If what the person said names a food, use that name and source is speech. Speech may be empty "
    "or about something else; then ignore it. Otherwise compare the photos, name what is new in "
    "the bowl, and source is image. Jars and packages beside the scale are not in the bowl. If you "
    "cannot tell, food is unknown and source is none. Answer only with the JSON object."
)


WRAPPER_SCHEMA = {
    "name": "wrapper",
    "schema": {
        "type": "object",
        "properties": {
            "brand": {"type": ["string", "null"]},
            "product": {"type": ["string", "null"]},
            "flavour": {"type": ["string", "null"]},
            "net_grams": {"type": ["number", "null"]},
            "protein_g": {"type": ["number", "null"]},
        },
        "required": ["brand", "product", "flavour", "net_grams", "protein_g"],
    },
}

WRAPPER_SYSTEM = (
    "A packaged food sits on a kitchen scale, seen from a head-worn camera. Copy only what is "
    "printed on the wrapper: the brand, the product line, the flavour, the net weight in grams "
    "and the grams of protein if the front states them. Use null for anything you cannot read, "
    "and for every field when the food has no wrapper or its printed side faces away. Never "
    "guess, and never fill in from what you know about the brand."
)

FACTS_PROMPT = (
    "Find the printed nutrition facts for this exact packaged food: {name}{net}. Answer with one "
    "JSON object and nothing else, with the values per serving as printed: "
    '{{"serving_g": 0, "kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0, '
    '"sodium_mg": 0}}. Use null for a value no source gives.'
)


TYPICAL_PROMPT = (
    'A person weighed a food on a kitchen scale. It was called "{name}", which may be a misheard '
    "word. A camera thought it looked like: {seen}. Work out the most likely food, then find "
    "typical nutrition values for it per 100 g. Answer with one JSON object and nothing else: "
    '{{"name": "the usual name of the food, lowercase", "kcal": 0, "protein_g": 0, "carbs_g": 0, '
    '"fat_g": 0, "fiber_g": 0, "sodium_mg": 0}}. All values are per 100 g. Use null for a value '
    "no source gives."
)


class MetaReader:
    """VisionProvider on any OpenAI-compatible vision endpoint (Muse Spark or Muse Glimmer)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        usual_foods: list[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # minimal: the read is "name the food, copy the digits"; low took 3.3 to 5.3 s per frame
        # on 2026-NOVEMBER-02 (muse-spark-1.3)
        self.chat = ChatModel(base_url, model, api_key, transport, reasoning_effort="minimal")
        self.usual_foods = list(usual_foods or [])

    async def read_entry(self, jpeg: bytes) -> EntryRead:
        jpeg = shrink(jpeg)
        user = "Read the scale."
        if self.usual_foods:
            user += " Foods this person logs often, check these first: " + ", ".join(
                self.usual_foods
            )
        d = await self.chat.structured(ENTRY_SYSTEM, user, ENTRY_SCHEMA, jpeg)
        if not d:
            return EntryRead(food="none", confidence=0.0)
        value, unit = number(d.get("display_value")), d.get("unit", "unknown")
        if unit == "unknown" and value is not None and 0 < value < 10000:
            # a kitchen scale with no unit on the display is in grams (the apple read as
            # "113, unknown" on 2026-NOVEMBER-02 and was thrown away)
            unit = "g"
        grams = None if value is None or unit not in TO_GRAMS else value * TO_GRAMS[unit]
        food = (d.get("food") or "none").strip().lower() or "none"
        raw = f"{value} {d.get('unit', 'unknown')}"
        print(f"MODEL food={food!r} display={raw} conf={d.get('confidence')}", flush=True)
        return EntryRead(
            food=food,
            grams=grams,
            confidence=min(1.0, max(0.0, number(d.get("confidence")) or 0.0)),
            raw=raw,
            container=bool(d.get("container", False)),
        )

    async def read_addition(self, before: bytes | None, after: bytes, speech: str) -> Addition:
        """One call for #22: the speech if it names a food, otherwise the two pictures."""
        said = speech.strip() or "(nothing)"
        images = [shrink(before), shrink(after)] if before else [shrink(after)]
        which = "The first photo is BEFORE, the second is AFTER." if before else "One photo: AFTER."
        user = f"{which} What the person said meanwhile: {said}"
        d = await self.chat.structured(ADDITION_SYSTEM, user, ADDITION_SCHEMA, images)
        if not d:
            return Addition()
        food = (d.get("food") or "unknown").strip().lower() or "unknown"
        source = d.get("source") if d.get("source") in ("speech", "image") else "none"
        conf = min(1.0, max(0.0, number(d.get("confidence")) or 0.0))
        print(f"MODEL addition={food!r} source={source} conf={conf} said={said!r}", flush=True)
        return Addition(food=food, source=source, confidence=conf)

    async def read_wrapper(self, jpeg: bytes) -> WrapperLabel:
        """The full frame, not the reader's smaller copy: this text is small."""
        d = await self.chat.structured(WRAPPER_SYSTEM, "Read the wrapper.", WRAPPER_SCHEMA, jpeg)
        label = WrapperLabel(
            brand=(d or {}).get("brand"),
            product=(d or {}).get("product"),
            flavour=(d or {}).get("flavour"),
            net_grams=number((d or {}).get("net_grams")),
            protein_g=number((d or {}).get("protein_g")),
        )
        print(f"MODEL wrapper={label.name!r} net={label.net_grams} p={label.protein_g}", flush=True)
        return label

    async def find_facts(self, label: WrapperLabel) -> LabelFacts | None:
        """Muse Spark's own web search (#13): the wearer needs no barcode and no other service."""
        net = f", {label.net_grams:g} g" if label.net_grams else ""
        prompt = FACTS_PROMPT.format(name=label.name, net=net)
        t0 = time.perf_counter()
        text, urls = await self.chat.grounded(prompt)
        took = time.perf_counter() - t0
        print(f"MODEL facts in {took:.1f} s: {text[:200]!r} cited={urls[:2]}", flush=True)
        d = json_object(text)
        if not d:
            return None
        return LabelFacts(
            serving_g=number(d.get("serving_g")),
            kcal=number(d.get("kcal")),
            protein_g=number(d.get("protein_g")),
            carbs_g=number(d.get("carbs_g")),
            fat_g=number(d.get("fat_g")),
            fiber_g=number(d.get("fiber_g")),
            sodium_mg=number(d.get("sodium_mg")),
            source=urls[0] if urls else None,
        )

    async def find_typical(self, name: str, seen: list[str]) -> LabelFacts | None:
        """A food the table does not know and with no wrapper: an esfiha on a plate, 13:52 on
        2026-NOVEMBER-04. The grams are the scale's; these are typical values per 100 g, as a
        table row is."""
        prompt = TYPICAL_PROMPT.format(name=name, seen=", ".join(seen) or "nothing useful")
        t0 = time.perf_counter()
        text, urls = await self.chat.grounded(prompt)
        took = time.perf_counter() - t0
        print(f"MODEL facts in {took:.1f} s: {text[:200]!r} cited={urls[:2]}", flush=True)
        d = json_object(text)
        if not d:
            return None
        found = d.get("name")
        return LabelFacts(
            name=found.strip().lower() if isinstance(found, str) and found.strip() else None,
            serving_g=100.0,
            kcal=number(d.get("kcal")),
            protein_g=number(d.get("protein_g")),
            carbs_g=number(d.get("carbs_g")),
            fat_g=number(d.get("fat_g")),
            fiber_g=number(d.get("fiber_g")),
            sodium_mg=number(d.get("sodium_mg")),
            source=urls[0] if urls else None,
        )

    async def aclose(self) -> None:
        await self.chat.aclose()


class MetaParser:
    """LLMProvider on any OpenAI-compatible text endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        reasoning_effort: str | None = "minimal",
    ) -> None:
        self.chat = ChatModel(base_url, model, api_key, transport, reasoning_effort)

    async def parse_reply(self, text: str, context: str) -> Reply:
        user = f"What was asked: {context or 'nothing'}\nSentence: {text}"
        for _attempt in (1, 2):  # a reasoning runaway occasionally truncates the JSON
            try:
                d = await asyncio.wait_for(
                    self.chat.structured(REPLY_SYSTEM, user, REPLY_SCHEMA), timeout=8.0
                )
            except TimeoutError:
                return Reply(action="none")  # a sentence is never worth stalling the loop for
            if d and d.get("action") in Reply.model_fields["action"].annotation.__args__:
                food = d.get("food")
                return Reply(
                    action=d["action"],
                    food=food.strip().lower() if isinstance(food, str) and food.strip() else None,
                    grams=number(d.get("grams")),
                )
        return Reply(action="none")

    async def aclose(self) -> None:
        await self.chat.aclose()


def make_reader() -> MetaReader:
    """ITLOGS_VISION: meta (Muse Spark on the Meta Model API), baseten (Muse Spark Open on
    Baseten, the open-weight model on partner inference, #16) or local (Glimmer on llama-server)."""
    if settings.vision == "local":
        return MetaReader(
            settings.llm_local_base,
            settings.llm_local_model,
            settings.llm_local_key,
            settings.usual_food_list,
        )
    if settings.vision == "baseten":
        if not settings.baseten_api_key:
            raise RuntimeError("BASETEN_API_KEY (or ITLOGS_BASETEN_API_KEY) must be set")
        return MetaReader(
            settings.baseten_base,
            settings.baseten_model,
            settings.baseten_api_key,
            settings.usual_food_list,
        )
    if not settings.meta_api_key:
        raise RuntimeError("MODEL_API_KEY (or ITLOGS_META_API_KEY) must be set")
    return MetaReader(
        settings.meta_api_base,
        settings.vision_model,
        settings.meta_api_key,
        settings.usual_food_list,
    )


def make_parser() -> MetaParser:
    """ITLOGS_LLM: local (llama-server, Glimmer), baseten (Muse Spark Open) or meta (Muse Spark)."""
    if settings.llm == "local":
        return MetaParser(
            settings.llm_local_base, settings.llm_local_model, settings.llm_local_key, None, None
        )
    if settings.llm == "baseten":
        return MetaParser(
            settings.baseten_base, settings.baseten_model, settings.baseten_api_key, None, None
        )
    if not settings.meta_api_key:
        raise RuntimeError("MODEL_API_KEY (or ITLOGS_META_API_KEY) must be set")
    return MetaParser(settings.meta_api_base, "muse-spark-1.3", settings.meta_api_key)
