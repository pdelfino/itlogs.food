"""Tests always run on the fake provider and never send telemetry, whatever server/.env says."""

import os

import pytest

os.environ["ITLOGS_PROVIDER"] = "fake"  # env beats .env in pydantic-settings
os.environ["ITLOGS_POSTHOG_TOKEN"] = ""


@pytest.fixture(autouse=True)
def _facts_stay_out_of_the_real_cache(monkeypatch, tmp_path):
    monkeypatch.setattr("itlogs.facts_cache.CACHE", tmp_path / "facts")
