"""Pull the iPhone's crash reports for the app and print one line each: time, build, exception,
and the first frames of the faulting thread. The raw .ips files stay in .sessions/crashes/.

uv run --project server python server/scripts/crashes.py [--device UDID] [--since HH:MM]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

OUT = Path(".sessions/crashes")


def summarize(path: Path) -> str:
    raw = path.read_text(errors="replace").split("\n", 1)
    if len(raw) < 2:
        return f"{path.name}: unreadable"
    try:
        d = json.loads(raw[1])
    except json.JSONDecodeError:
        return f"{path.name}: not JSON"
    thread = d["threads"][d.get("faultingThread", 0)]
    frames = " <- ".join(f.get("symbol", "?") for f in thread.get("frames", [])[:6])
    exc = d.get("exception", {})
    term = d.get("termination", {})
    build = d.get("bundleInfo", {}).get("CFBundleVersion", "?")
    when = path.stem.split("-", 1)[1]
    kind = f"{exc.get('type', '?')}/{exc.get('signal', '?')}"
    where = thread.get("queue", thread.get("name", "?"))
    return f"{when}  build {build}  {kind}  by {term.get('byProc', '?')}  queue {where}\n    {frames}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="")
    ap.add_argument("--since", default="", help="HH:MM today; print only newer reports")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = ["idevicecrashreport", "-k", "-f", "ItlogsFood", str(OUT)]
    if args.device:
        cmd[1:1] = ["-u", args.device]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(
            r.stderr.strip()
            or "idevicecrashreport failed (brew install libimobiledevice; phone unlocked, trusted)"
        )
        return 1
    files = sorted(OUT.glob("ItlogsFood-*.ips"))
    if args.since:
        files = [f for f in files if f.stem.split("-")[-1][:4] >= args.since.replace(":", "")]
    if not files:
        print("no crash reports")
        return 0
    for f in files:
        print(summarize(f))
    return 0


if __name__ == "__main__":
    sys.exit(main())
