"""The reader and the parser against canned HTTP responses (no key, no credits)."""

import json

import httpx
import pytest

from itlogs.providers.meta import MetaParser, MetaReader


def canned(payload: dict, seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    return httpx.MockTransport(handler)


async def test_reader_converts_units_and_passes_the_usual_foods():
    seen: list = []
    r = MetaReader(
        "https://x.test/v1",
        "muse-spark-1.3",
        "LLM_test",
        usual_foods=["rice", "chicken"],
        transport=canned(
            {"food": "Chicken Breast", "display_value": 4.0, "unit": "oz", "confidence": 0.8},
            seen,
        ),
    )
    read = await r.read_entry(b"jpeg")
    assert read.food == "chicken breast"
    assert read.grams is not None and round(read.grams, 1) == 113.4
    body = seen[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][1]["content"][1]["type"] == "image_url"
    assert "rice, chicken" in body["messages"][1]["content"][0]["text"]


async def test_reader_unreadable_display():
    r = MetaReader(
        "https://x.test/v1",
        "m",
        transport=canned(
            {"food": "none", "display_value": None, "unit": "unknown", "confidence": 0}, []
        ),
    )
    read = await r.read_entry(b"jpeg")
    assert not read.readable


async def test_reader_survives_empty_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": None}, "finish_reason": "length"}]}
        )

    r = MetaReader("https://x.test/v1", "m", transport=httpx.MockTransport(handler))
    assert not (await r.read_entry(b"jpeg")).readable


async def test_parser_structured_reply():
    p = MetaParser(
        "https://x.test/v1",
        "m",
        transport=canned({"action": "correct", "food": " Quinoa ", "grams": 81}, []),
    )
    reply = await p.parse_reply("it is quinoa, 81", "rice: 81 or 87 grams?")
    assert (reply.action, reply.food, reply.grams) == ("correct", "quinoa", 81.0)


async def test_parser_bad_action_becomes_none():
    p = MetaParser(
        "https://x.test/v1",
        "m",
        transport=canned({"action": "dance", "food": None, "grams": None}, []),
    )
    assert (await p.parse_reply("hi", "")).action == "none"


def test_reader_prompt_tells_containers_from_food():
    """A bowl on the scale before the tare is not a food row (2026-NOVEMBER-03, the powder)."""
    from itlogs.providers.meta import ENTRY_SYSTEM

    assert "container" in ENTRY_SYSTEM and "name the food" in ENTRY_SYSTEM


def test_make_reader_on_baseten_needs_its_key_and_uses_the_open_model(monkeypatch):
    """#16: ITLOGS_VISION=baseten puts Muse Spark Open (partner inference) behind the same
    reader; no key, no reader."""
    from itlogs.config import settings
    from itlogs.providers.meta import MetaReader, make_reader

    monkeypatch.setattr(settings, "vision", "baseten")
    monkeypatch.setattr(settings, "baseten_api_key", "")
    with pytest.raises(RuntimeError, match="BASETEN"):
        make_reader()
    monkeypatch.setattr(settings, "baseten_api_key", "k")
    reader = make_reader()
    assert isinstance(reader, MetaReader)
    assert reader.chat.model == settings.baseten_model
