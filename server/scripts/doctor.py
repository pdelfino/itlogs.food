"""One screen for whoever opens this repo (Claude or Pedro): what is connected, what is running,
what the phone said last, what crashed, what PostHog has. Read-only.

uv run --project server python server/scripts/doctor.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = ROOT / ".sessions"


def sh(cmd: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return f"({e.__class__.__name__})"


def line(label: str, value: str) -> None:
    print(f"{label:<14} {value}")


def main() -> int:
    print(f"itlogs.food doctor · {datetime.now():%Y-%m-%d %H:%M:%S}\n")

    # repo
    head = sh(["git", "-C", str(ROOT), "log", "--oneline", "-1"])
    dirty = sh(["git", "-C", str(ROOT), "status", "--short"])
    state = f"(dirty: {len(dirty.splitlines())} files)" if dirty else "(clean)"
    line("repo", f"{head}  {state}")
    count = sh(["git", "-C", str(ROOT), "rev-list", "--count", "HEAD"])
    line("next build", f"{count} (CFBundleVersion = commits on main)")

    # phone
    devices = sh(["xcrun", "xctrace", "list", "devices"])
    phones = [d for d in devices.splitlines() if "iPhone" in d and "Simulator" not in d]
    line("iphone", phones[0].strip() if phones else "not connected over USB")
    if phones and shutil.which("xcrun"):
        udid = phones[0].rsplit("(", 1)[-1].rstrip(")")
        procs = sh(["xcrun", "devicectl", "device", "info", "processes", "--device", udid], 30)
        running = [p for p in ("ItlogsFood", "MetaAI") if p + ".app" in procs]
        apps = ", ".join(running) + " running" if running else "itlogs.food not running on the phone"
        line("phone apps", apps)
    built = ROOT / "ios/build/Build/Products/Debug-iphoneos/ItlogsFood.app/Info.plist"
    if built.exists():
        v = sh(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleVersion", str(built)])
        sha = sh(["/usr/libexec/PlistBuddy", "-c", "Print :ItlogsGitSHA", str(built)])
        line("last build", f"{v} · {sha} (what make ios-run installed last)")

    # server
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as r:
            h = json.load(r)
            line("server", f"up on :8000, provider={h.get('provider')}")
    except Exception:
        line("server", "DOWN (make run-bg)")
    log = SESSIONS / "server.log"
    if log.exists():
        tail = log.read_text().splitlines()[-3:]
        line("server.log", " | ".join(t[:70] for t in tail) if tail else "empty")

    # the phone's own words
    phone = SESSIONS / "phone.log"
    if phone.exists():
        lines = phone.read_text().splitlines()
        print(f"\nphone.log, last {min(8, len(lines))} of {len(lines)} lines:")
        for t in lines[-8:]:
            print("   ", t[:120])
        glasses = [t for t in lines if "device '" in t and "link=" in t]
        if glasses:
            line("\nglasses", glasses[-1].split("device ", 1)[1][:60])
    else:
        print("\nphone.log: nothing yet (the phone reports to the server's /log)")

    # crashes
    crash_dir = SESSIONS / "crashes"
    crashes = sorted(crash_dir.glob("ItlogsFood-*.ips")) if crash_dir.exists() else []
    newest = crashes[-1].stem[-15:] if crashes else "none"
    line("crashes", f"{len(crashes)} pulled so far, newest {newest} (make phone-crashes pulls new ones)")

    # telemetry
    env = ROOT / "server/.env"
    env_lines = env.read_text().splitlines() if env.exists() else []
    tok = any(t.startswith("ITLOGS_POSTHOG_TOKEN=") and len(t) > 25 for t in env_lines)
    where = "token in server/.env; project itlogs.food 703736 (Claude: execute-sql on events)"
    line("posthog", where if tok else "no token: telemetry off")

    print("\nnext: gh issue list · make phone-logs · make phone-crashes · DEVELOPMENT_TEAM=6X8G2S2P89 make ios-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
