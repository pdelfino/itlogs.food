"""Replay real recorded reads through today's decision logic: no key, no glasses, no network.

uv run --project server python evals/replay.py

Each file in evals/traces/ holds what the model said during one real session. This feeds those
reads to Session in order and compares the rows it logs now with the rows the trace expects,
next to what the app logged at the time. It exits 1 on any difference, so CI catches a change that
would bring an old bug back. It tests the decisions made from reads. It does not test the reading:
that needs the photos and a model (make eval-live).
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from itlogs.models import EntryRead
from itlogs.providers.fake import FakeLLM, FakeVision
from itlogs.session import Session

TRACES = Path(__file__).resolve().parent / "traces"


async def replay(trace: dict) -> list[list]:
    session = Session(FakeVision(), FakeLLM())
    session.set_watching(True, 0)
    last_t = 0
    for r in trace["reads"]:
        read = EntryRead(
            food=r["food"],
            grams=r["grams"],
            confidence=r["confidence"],
            raw=r["raw"],
            container=trace["assume_vessel"],
        )
        t = last_t = max(
            r["t_ms"], last_t
        )  # reads can finish out of order; time does not go back
        session._last_read_still = r["still"]
        rows = await session._bowl_step(read, b"frame", t)
        if rows is None:
            session._watch(read, t)
    return [[e.food, e.grams] for e in session.entries]


def latency_line() -> str:
    """Every timed read of every recorded session, not only the sessions kept as traces."""
    runs = json.loads((TRACES.parent / "recorded-latency.json").read_text()).values()
    ms = sorted(m for r in runs if r["reader"] == "Muse Spark" for m in r["read_ms"])
    p90 = ms[int(len(ms) * 0.9)]
    return (
        f"Muse Spark over {len(ms)} timed reads on real runs: "
        f"median {statistics.median(ms) / 1000:.1f} s, 90th percentile {p90 / 1000:.1f} s"
    )


def rows_text(rows: list[list]) -> str:
    return ", ".join(f"{food} {grams:g} g" for food, grams in rows) or "nothing"


async def run_all() -> list[tuple[dict, list[list]]]:
    traces = [json.loads(p.read_text()) for p in sorted(TRACES.glob("*.json"))]
    return [(t, await replay(t)) for t in traces]


def main() -> int:
    failed = 0
    results = asyncio.run(run_all())
    for trace, now in results:
        reads = trace["reads"]
        weighed = sum(1 for r in reads if r["grams"] is not None and r["grams"] > 0)
        ok = now == trace["expect_now"]
        failed += not ok
        print(
            f"{'ok  ' if ok else 'DIFF'} {trace['session']}: {len(reads)} reads, {weighed} weighed"
        )
        print(f"     {trace['why']}")
        print(f"     then: {rows_text(trace['logged_then'])}")
        print(f"     now:  {rows_text(now)}")
        if not ok:
            print(f"     expected: {rows_text(trace['expect_now'])}")
    print(f"\n{latency_line()}")
    print(f"{len(results) - failed} of {len(results)} sessions replay as expected")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
