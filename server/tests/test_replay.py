"""The rows real recorded reads produce today (evals/traces, evals/replay.py). Each trace is a real
session; most are here because they exposed a bug, so a change that brings one back fails here."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))

from replay import run_all  # noqa: E402


async def test_every_recorded_session_gives_the_expected_rows():
    results = await run_all()
    assert len(results) == 7
    for trace, now in results:
        assert now == trace["expect_now"], trace["session"]


async def test_the_bowl_adds_up_to_what_the_scale_showed():
    by_session = {t["session"]: now for t, now in await run_all()}
    assert sum(grams for _, grams in by_session["2026-11-04-080057"]) == 104.0


async def test_the_best_run_is_unchanged():
    by_session = {t["session"]: now for t, now in await run_all()}
    assert by_session["2026-11-03-201500"] == [["apple", 112.0], ["banana", 124.0]]
