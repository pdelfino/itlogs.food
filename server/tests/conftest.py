"""Tests always run on the fake provider and never send telemetry, whatever server/.env says."""

import os

os.environ["ITLOGS_PROVIDER"] = "fake"  # env beats .env in pydantic-settings
os.environ["ITLOGS_POSTHOG_TOKEN"] = ""
