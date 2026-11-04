"""Time the configured reader on one recorded frame: the latency number for the README, per
reader (ITLOGS_VISION=meta | baseten | local), from the same photo.

    ITLOGS_VISION=baseten uv run --project server python server/scripts/probe_reader.py PHOTO -n 3

Prints one line per read (food, grams, confidence, ms) and the median. Needs the reader's key in
the environment, so this runs in Pedro's terminal, never from Claude."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from itlogs.config import settings  # noqa: E402
from itlogs.providers.meta import make_reader  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("photo", type=Path)
    ap.add_argument("-n", type=int, default=3, help="how many reads of the same frame")
    args = ap.parse_args()
    jpeg = args.photo.read_bytes()
    reader = make_reader()
    print(f"reader: vision={settings.vision} model={reader.chat.model} photo={args.photo.name}")
    took: list[float] = []
    try:
        for i in range(args.n):
            before = len(reader.chat.latency_ms)
            read = await reader.read_entry(jpeg)
            ms = reader.chat.latency_ms[before:]
            took.extend(ms)
            u = getattr(reader.chat, "last_usage", {}) or {}
            print(
                f"{i + 1}: {read.food!r} {read.grams} g conf={read.confidence:.2f} "
                f"{int(sum(ms))} ms  tokens prompt={u.get('prompt')} "
                f"completion={u.get('completion')} reasoning={u.get('reasoning')}"
            )
    finally:
        await reader.aclose()
    if took:
        print(f"median {int(statistics.median(took))} ms over {len(took)} reads")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
