"""Tests always run on the fake provider, whatever server/.env says."""

import os

os.environ["ITLOGS_PROVIDER"] = "fake"  # env beats .env in pydantic-settings
