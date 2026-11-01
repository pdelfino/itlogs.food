"""Score the reader on the eval sets: for each set, two photos of the same food on the scale
and the truth. Prints food top-1, grams exact (within 1 g), and what the loop would have done
(agreed, asked), plus latency per read.

uv run --project server python evals/run.py [--sets evals/sets] [--from-reads]

--from-reads replays reads.json (the live run's model output) instead of calling the model,
so the loop can be re-scored offline, deterministically, in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from itlogs.models import EntryRead
from itlogs.nutrients import canonical
from itlogs.providers import make_providers
from itlogs.providers.fake import FakeLLM, FakeVision
from itlogs.session import Session

TOLERANCE_G = 1.0


async def score_set(folder: Path, from_reads: bool) -> dict | None:
    truth = json.loads((folder / "truth.json").read_text())
    photos = sorted(folder.glob("*.jpg"))
    latencies: list[float] = []
    if from_reads:
        if not (folder / "reads.json").exists():
            return None
        reads = [
            EntryRead(**r) for r in json.loads((folder / "reads.json").read_text())
        ]
        vision = FakeVision(reads)
    else:
        if len(photos) < 2:
            return None
        vision, _ = make_providers()
    session = Session(vision, FakeLLM())
    t0 = time.perf_counter()
    await session.on_frame(photos[0].read_bytes() if photos else b"a", 0)
    out = await session.capture(0)
    latencies.append((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    out += await session.on_frame(
        photos[1].read_bytes() if len(photos) > 1 else b"b", 5000
    )
    latencies.append((time.perf_counter() - t0) * 1000)
    reads = [m.read for m in out if m.kind == "read" and m.read is not None]
    first = reads[0] if reads else EntryRead(food="none", confidence=0)
    if not from_reads:
        (folder / "reads.json").write_text(json.dumps([r.model_dump() for r in reads]))
    outcome = (
        "agreed"
        if session.entries
        else ("asked" if any(m.kind == "ask" for m in out) else "unreadable")
    )
    return {
        "set": folder.name,
        "food_ok": canonical(first.food) == canonical(truth["food"]),
        "grams_ok": first.grams is not None
        and abs(first.grams - truth["grams"]) <= TOLERANCE_G,
        "outcome": outcome,
        "read": first.model_dump(),
        "truth": truth,
        "latency_ms": latencies,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default=str(Path(__file__).parent / "sets"))
    ap.add_argument("--from-reads", action="store_true")
    args = ap.parse_args()
    folders = sorted(
        p for p in Path(args.sets).iterdir() if (p / "truth.json").exists()
    )
    rows = [r for r in [await score_set(f, args.from_reads) for f in folders] if r]
    if not rows:
        print("no eval sets with photos (or reads.json) yet; see evals/README.org")
        return 0
    n = len(rows)
    food = sum(r["food_ok"] for r in rows)
    grams = sum(r["grams_ok"] for r in rows)
    both = sum(r["food_ok"] and r["grams_ok"] for r in rows)
    agreed = sum(r["outcome"] == "agreed" for r in rows)
    lat = [x for r in rows for x in r["latency_ms"]]
    for r in rows:
        mark = "ok" if r["food_ok"] and r["grams_ok"] else "MISS"
        print(
            f"{mark:4} {r['set']:40} read {r['read']['food']} {r['read']['grams']} g"
            f"  truth {r['truth']['food']} {r['truth']['grams']} g  {r['outcome']}"
        )
    print(
        f"\n{n} sets: food top-1 {food}/{n} ({100 * food / n:.0f}%), grams within {TOLERANCE_G:g} g "
        f"{grams}/{n} ({100 * grams / n:.0f}%), both {both}/{n} ({100 * both / n:.0f}%), "
        f"loop agreed without asking {agreed}/{n}"
    )
    if lat:
        print(
            f"latency per read: p50 {statistics.median(lat):.0f} ms, "
            f"max {max(lat):.0f} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
