"""The provider seam. Every model call goes through these two protocols so Muse Spark on the
Meta Model API, Muse Glimmer on this Mac, or any other model can be swapped without touching
the session logic."""

from __future__ import annotations

from typing import Protocol

from itlogs.models import Addition, EntryRead, LabelFacts, Reply, WrapperLabel


class VisionProvider(Protocol):
    async def read_entry(self, jpeg: bytes) -> EntryRead:
        """Name the food on the scale and read the number on its display, from one frame."""
        ...

    async def read_addition(self, before: bytes | None, after: bytes, speech: str) -> Addition:
        """Name what was added to a bowl: from the speech if it names a food, else the images."""
        ...

    async def read_wrapper(self, jpeg: bytes) -> WrapperLabel:
        """Copy what is printed on a packaged food in this frame: brand, product, flavour."""
        ...

    async def find_facts(self, label: WrapperLabel) -> LabelFacts | None:
        """Find that product's printed nutrition facts on the live web."""
        ...

    async def find_typical(self, name: str, seen: list[str]) -> LabelFacts | None:
        """Work out what a food with no wrapper is, and find typical values per 100 g."""
        ...


class LLMProvider(Protocol):
    async def parse_reply(self, text: str, context: str) -> Reply:
        """Turn one spoken sentence into a structured reply, given what was just asked."""
        ...
