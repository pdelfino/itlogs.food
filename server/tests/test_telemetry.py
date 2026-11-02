"""Telemetry is a no-op without a token, and never raises."""

from itlogs import telemetry
from itlogs.config import settings


def test_no_token_means_no_client(monkeypatch):
    monkeypatch.setattr(settings, "posthog_token", "")
    telemetry._client = None
    assert telemetry.client() is None
    telemetry.event("x", {"a": 1})
    telemetry.exception(RuntimeError("boom"))


def test_with_token_builds_a_client_and_captures(monkeypatch):
    monkeypatch.setattr(settings, "posthog_token", "phc_test")
    telemetry._client = None
    c = telemetry.client()
    assert c is not None
    c.disabled = True  # never send from a test
    telemetry.event("entry_logged", {"food": "rice"})
    telemetry.exception(RuntimeError("boom"))
    telemetry._client = None
