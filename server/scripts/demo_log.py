"""The server's log, for a screen: one plain line per thing that happened, in large type.

    make demo-log                 follow .sessions/server.log live, from now on
    make demo-log FROM=3715 TO=3775     print those lines of the log, for a look

It reads the log and changes nothing, so it can start or stop during a run. Every line it prints
comes from a real line of the log; the calories of a food the table knows are worked out here with
the same table the server uses. Nothing private is shown: no host, no key, no phone log noise.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

from itlogs import nutrients  # noqa: E402

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
GREEN, BLUE, PURPLE, RED = "\033[32m", "\033[36m", "\033[35m", "\033[31m"

READ = re.compile(r"^READ (.+) (None|-?[\d.]+) g conf=([\d.]+)$")
TOOK = re.compile(r"^READ took (\d+) ms")
ENTRY = re.compile(r"^ENTRY (\d+) (.+) ([\d.]+) g (\w+)$")
WRAPPER = re.compile(r"^MODEL wrapper='(.*)' net=(\S+) p=(\S+)$")
SEARCH = re.compile(r"^MODEL facts in ([\d.]+) s:.*cited=\['?(?:https?://(?:www\.)?([^/']+))?")
LABEL = re.compile(r"^LABEL (.+) kcal=(\S+) protein=(\S+) carbs=(\S+) fat=(\S+) (searched|saved)$")
ADDITION = re.compile(r"^MODEL addition='(.*)' source=(\w+) conf=\S+ said=(.*)$")
HEARD = re.compile(r'^PHONE \S+ glasses: heard "(.*)" \(confidence')
SAY = re.compile(r"^SAY (.*)$")
TROUBLE = re.compile(
    r"^(MODEL unreachable|THINK failed|FINAL LOOK failed|WRAPPER failed|FACTS failed)"
)


def line(what: str, text: str, color: str = "") -> str:
    return f"{color}{what:<10}{RESET} {color}{text}{RESET}"


class View:
    def __init__(self) -> None:
        self.took: float | None = None
        self.rows: set[int] = set()

    def render(self, raw: str) -> str | None:
        """One log line in, one screen line out, or None when it is not worth a line."""
        raw = raw.rstrip("\n")
        if m := TOOK.match(raw):
            self.took = int(m.group(1)) / 1000
            return None
        if m := READ.match(raw):
            took = f"{self.took:.1f} s" if self.took is not None else ""
            self.took = None
            food, grams, conf = m.group(1), m.group(2), float(m.group(3))
            if grams == "None":
                seen = "no number in view" if food == "none" else f"{food}, no number in view"
            elif float(grams) <= 0:
                seen = "scale empty"
            else:
                seen = f"{food}, {float(grams):g} g, {conf:.0%} sure"
            return line("read", f"{took:>6}   {seen}", DIM)
        if m := ENTRY.match(raw):
            index, food, grams = int(m.group(1)), m.group(2), float(m.group(3))
            again = index in self.rows
            self.rows.add(index)
            row = nutrients.for_grams(food, grams)
            facts = ""
            if row is not None:
                facts = (
                    f"   {row.kcal:.0f} kcal, {row.protein_g:.0f} g protein, "
                    f"{row.carbs_g:.0f} g carbs, {row.fat_g:.0f} g fat"
                )
            word = "UPDATED" if again else "LOGGED"
            return BOLD + line(word, f"{food}, {grams:g} g{facts}", GREEN)
        if m := WRAPPER.match(raw):
            net, printed = m.group(2), m.group(3)
            bits = [m.group(1)]
            if net != "None":
                bits.append(f"{float(net):g} g")
            if printed != "None":
                bits.append(f"{float(printed):g} g protein")
            return line("wrapper", ", ".join(bits) + "  (read off the frame)", PURPLE)
        if m := SEARCH.match(raw):
            where = f", {m.group(2)}" if m.group(2) else ""
            return line("web search", f"{float(m.group(1)):.0f} s{where}", PURPLE)
        if m := LABEL.match(raw):
            how = "searched now" if m.group(6) == "searched" else "label saved earlier"
            kcal, protein, carbs, fat = (float(m.group(i)) for i in (2, 3, 4, 5))
            text = (
                f"{m.group(1)}: {kcal:.0f} kcal, {protein:.0f} g protein, "
                f"{carbs:.0f} g carbs, {fat:.0f} g fat  ({how})"
            )
            return BOLD + line("LABEL", text, GREEN)
        if m := ADDITION.match(raw):
            source = {"speech": "from what you said", "image": "by comparing the photos"}
            how = source.get(m.group(2), "not named")
            return line("bowl", f"added {m.group(1)}, named {how}", PURPLE)
        if m := HEARD.match(raw):
            return line("heard", f'"{m.group(1)}"', BLUE)
        if "start tapped" in raw:
            return BOLD + line("START", "tapped on the phone", BLUE)
        if "stop tapped" in raw:
            return BOLD + line("STOP", "tapped on the phone", BLUE)
        if m := SAY.match(raw):
            return line("ear", m.group(1), BLUE)
        if TROUBLE.match(raw):
            return line("problem", raw[:90], RED)
        return None


def follow(path: Path):
    with path.open() as f:
        f.seek(0, 2)
        while True:
            text = f.readline()
            if text:
                yield text
            else:
                time.sleep(0.1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(ROOT / ".sessions" / "server.log"))
    ap.add_argument("--from-line", type=int, default=0)
    ap.add_argument("--to-line", type=int, default=0)
    args = ap.parse_args()
    view = View()
    if args.from_line:
        lines = Path(args.log).read_text().splitlines()[args.from_line - 1 : args.to_line or None]
        source = iter(lines)
    else:
        print(f"{BOLD}itlogs.food server{RESET}  {DIM}waiting for a run{RESET}")
        source = follow(Path(args.log))
    started: float | None = None
    for raw in source:
        shown = view.render(raw)
        if shown is None:
            continue
        if "start tapped" in raw:
            started = time.monotonic()
            view = View()
            view.render(raw)
            print("\033[2J\033[H", end="")
            print(
                f"{BOLD}itlogs.food server{RESET}  {DIM}Muse Spark on the Meta Model API{RESET}\n"
            )
        clock = ""
        if started is not None:
            s = int(time.monotonic() - started)
            clock = f"{DIM}{s // 60}:{s % 60:02d}{RESET}  "
        print(clock + shown, flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0) from None
