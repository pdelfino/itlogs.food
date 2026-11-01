"""Meta models behind the two protocols.

The reader: Muse Spark (muse-spark-1.3) on the Meta Model API, or Muse Glimmer with its vision
projector on this Mac through llama-server (the open-weight path). One still in, the food and
the display value out, as structured output. The parser: the same client on a text prompt.

Docs: hackathon/meta-model-api-notes.org. Standard-mode model ids only (no "-contributor":
those train on the content, and the content is Pedro's kitchen).
"""

from __future__ import annotations

import httpx

from itlogs.config import settings
from itlogs.models import EntryRead, Reply
from itlogs.providers.chat import ChatModel

ENTRY_SCHEMA = {
    "name": "entry_read",
    "schema": {
        "type": "object",
        "properties": {
            "food": {"type": "string"},
            "display_value": {"type": ["number", "null"]},
            "unit": {"type": "string", "enum": ["g", "kg", "oz", "lb", "ml", "unknown"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["food", "display_value", "unit", "confidence"],
    },
}

ENTRY_SYSTEM = (
    "You read a kitchen scale from one photo taken by a camera worn on the head. A food item "
    "sits on the scale and the scale's digital display shows a number. Name the food in two "
    'or three plain lowercase words (for example "cooked white rice", "chicken breast", '
    '"egg whites"), or "none" when nothing is on the scale. Read the number on the display '
    "exactly as shown, digit by digit, with its unit. When the display is not readable "
    "(glare, out of frame, blurred, mid-change), display_value is null and confidence is 0. "
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
        self.chat = ChatModel(base_url, model, api_key, transport, reasoning_effort="low")
        self.usual_foods = list(usual_foods or [])

    async def read_entry(self, jpeg: bytes) -> EntryRead:
        user = "Read the scale."
        if self.usual_foods:
            user += " Foods this person logs often, check these first: " + ", ".join(
                self.usual_foods
            )
        d = await self.chat.structured(ENTRY_SYSTEM, user, ENTRY_SCHEMA, jpeg)
        if not d:
            return EntryRead(food="none", confidence=0.0)
        value, unit = d.get("display_value"), d.get("unit", "unknown")
        grams = None if value is None or unit not in TO_GRAMS else float(value) * TO_GRAMS[unit]
        food = (d.get("food") or "none").strip().lower() or "none"
        return EntryRead(
            food=food, grams=grams, confidence=min(1.0, max(0.0, float(d.get("confidence", 0))))
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
            d = await self.chat.structured(REPLY_SYSTEM, user, REPLY_SCHEMA)
            if d and d.get("action") in Reply.model_fields["action"].annotation.__args__:
                food = d.get("food")
                return Reply(
                    action=d["action"],
                    food=food.strip().lower() if isinstance(food, str) and food.strip() else None,
                    grams=float(d["grams"]) if d.get("grams") is not None else None,
                )
        return Reply(action="none")

    async def aclose(self) -> None:
        await self.chat.aclose()


def make_reader() -> MetaReader:
    """ITLOGS_VISION: meta (Muse Spark on the Meta Model API) or local (Glimmer on llama-server)."""
    if settings.vision == "local":
        return MetaReader(
            settings.llm_local_base,
            settings.llm_local_model,
            settings.llm_local_key,
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
