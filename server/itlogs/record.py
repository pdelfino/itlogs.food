"""Keep a live session for the eval sets: the frames the reads were made on, as JPEG, and the
entries with their labels, under ITLOGS_RECORD_DIR/<YYYY-MM-DD-HHMMSS>/. Off unless the env
var is set. Photos never enter git; they live on the T7. Short retention is the rule: only
the frames that were read are kept, never the stream."""

from __future__ import annotations

import json
import time
from pathlib import Path


class Recorder:
    def __init__(self, root: str | Path) -> None:
        self.dir = Path(root) / time.strftime("%Y-%m-%d-%H%M%S")
        (self.dir / "photos").mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []

    def photo(self, jpeg: bytes, t_ms: int) -> None:
        (self.dir / "photos" / f"{t_ms:08d}.jpg").write_bytes(jpeg)

    def event(self, kind: str, payload: dict) -> None:
        self.events.append({"kind": kind, **payload})

    def close(self, entries: list[dict]) -> Path:
        (self.dir / "session.json").write_text(
            json.dumps({"entries": entries, "events": self.events}, indent=1)
        )
        return self.dir
