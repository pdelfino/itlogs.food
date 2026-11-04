"""What can be checked about the hackathon rules from a clone: uv run --project server python
server/scripts/rules_check.py, or make rules-check. It reads git and the installed packages and
calls nothing. docs/rules-compliance.org goes through the rules one by one."""

from __future__ import annotations

import importlib.metadata as md
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KICKOFF = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)  # 12:00 ET
DEADLINE = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)  # 21:00 ET
MEDIA = re.compile(r"\.(jpe?g|png|webp|heic|mp4|mov|wav|pcm|m4a)$", re.I)
ALLOWED_MEDIA = ("docs/brand/", "site/brand/", "site/img/", "ios/Sources/", "docs/frame-")
SECRET = re.compile(
    r"(phc_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|LLM_[A-Za-z0-9_]{20,})"
)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True).stdout


def main() -> int:
    bad = 0

    def report(ok: bool, line: str) -> None:
        nonlocal bad
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {line}")

    stamps = [datetime.fromtimestamp(int(t), UTC) for t in git("log", "--format=%ct").split()]
    report(
        min(stamps) >= KICKOFF,
        f"oldest of {len(stamps)} commits is {min(stamps):%Y-%m-%d %H:%M} UTC, after kickoff",
    )
    report(
        max(stamps) <= DEADLINE,
        f"newest commit is {max(stamps):%Y-%m-%d %H:%M} UTC, before the deadline",
    )
    authors = sorted(set(git("log", "--format=%an").splitlines()))
    report(len(authors) == 1, f"one author: {authors}")
    helpers = sorted(
        {m for m in re.findall(r"Co-Authored-By: ([^<]+)<", git("log", "--format=%b"))}
    )
    print(f"info assistants disclosed in commit trailers: {[h.strip() for h in helpers]}")

    tracked = git("ls-files").splitlines()
    report(not [f for f in tracked if re.search(r"(^|/)\.env$", f)], "no .env file is tracked")
    stray = [f for f in tracked if MEDIA.search(f) and not f.startswith(ALLOWED_MEDIA)]
    report(
        not stray, f"no photo, video or audio outside the brand and site assets: {stray or 'none'}"
    )
    leaks = [
        f
        for f in tracked
        if (ROOT / f).is_file() and SECRET.search((ROOT / f).read_text(errors="ignore"))
    ]
    report(not leaks, f"no key shape in the tracked files: {leaks or 'none'}")

    code = "\n".join(
        (ROOT / f).read_text()
        for f in tracked
        if f.startswith("server/itlogs/") and f.endswith(".py")
    )
    models = sorted(
        set(re.findall(r"muse-[a-z]+(?:-[a-z]+)*(?:-[0-9.]+)?|meta-models/[a-z-]+", code))
    )
    report(bool(models), f"Meta models named in the server: {models}")

    root = git("rev-list", "--max-parents=0", "HEAD").split()[0]
    sources = [
        f
        for f in tracked
        if f.endswith((".py", ".swift")) and f.startswith(("server/", "ios/", "evals/"))
    ]
    blamed = [git("blame", "-l", "HEAD", "--", f).splitlines() for f in sources]
    all_lines = sum(len(b) for b in blamed)
    carried = sum(line.lstrip("^").startswith(root[:12]) for b in blamed for line in b)
    print(
        f"info {carried} of {all_lines} lines of Python and Swift still come from the first commit, "
        f"the part carried from the sibling repo; every other line was written in this repo"
    )

    deps = tomllib.loads((ROOT / "server/pyproject.toml").read_text())["project"]["dependencies"]
    print("info direct server dependencies and their licences:")
    for dep in deps:
        name = re.split(r"[\[<>=~ ]", dep)[0]
        meta = md.metadata(name)
        classifier = [
            c.split(" :: ")[-1] for c in meta.get_all("Classifier", []) if c.startswith("License")
        ]
        licence = meta.get("License-Expression") or (
            classifier[0] if classifier else meta.get("License", "?")
        )
        print(f"       {name} {md.version(name)}: {str(licence).splitlines()[0][:50]}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
