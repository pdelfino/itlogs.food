"""PostHog on the server: unhandled exceptions, one event per logged entry, and the phone's
diagnostic lines (issue #9). Without ITLOGS_POSTHOG_TOKEN everything here is a no-op, loudly
once in debug so a missing key is never silent."""

from __future__ import annotations

import logging
import os
from typing import Any

from itlogs.config import settings

log = logging.getLogger("itlogs.telemetry")

_client: Any = None
_warned = False


def client() -> Any:
    global _client, _warned
    if _client is not None:
        return _client
    token = settings.posthog_token
    if not token:
        if not _warned and os.environ.get("ITLOGS_PROVIDER") == "meta":
            _warned = True
            log.error(
                "ITLOGS_POSTHOG_TOKEN variable required by PostHog is missing or un-configured, "
                "this causes events to be silently missed. This error stops appearing once "
                "ITLOGS_POSTHOG_TOKEN is configured"
            )
        return None
    from posthog import Posthog

    _client = Posthog(
        project_api_key=token, host=settings.posthog_host, enable_exception_autocapture=True
    )
    return _client


def event(name: str, properties: dict[str, Any] | None = None, distinct_id: str = "server") -> None:
    c = client()
    if c is None:
        return
    try:
        c.capture(name, distinct_id=distinct_id, properties=properties or {})
    except Exception as e:  # telemetry never breaks the product
        log.warning("posthog capture failed: %s", e)


def exception(exc: BaseException, properties: dict[str, Any] | None = None) -> None:
    c = client()
    if c is None:
        return
    try:
        c.capture_exception(exc, distinct_id="server", properties=properties or {})
    except Exception as e:
        log.warning("posthog capture_exception failed: %s", e)
