#!/usr/bin/env python3
"""Make hero candidates for itlogs.food with Muse Image (Meta Model API).

Runs from Pedro's terminal with MODEL_API_KEY in the environment; the key never
enters the repo or an agent's context. USD 0.01 per image.

    source ~/.secure_env_vars && python3 site/tools/hero.py            # 4 prompts x 5 = 20 images
    python3 site/tools/hero.py --n 3 --only 2                           # 3 images of prompt 2
    python3 site/tools/hero.py --prompt "..." --n 5                     # your own prompt

Candidates land in site/img/candidates/ (gitignored) with a browse.html next to
them: open it in a browser, pick a number, and tell Claude "hero: 2-3" (prompt 2,
image 3). Only the chosen file is copied to site/img/hero.webp and committed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("ITLOGS_META_API_BASE", "https://api.meta.ai/v1").rstrip("/")
MODEL = "muse-image-1.0"
SIZE = "1536x1024"  # 3:2, the hero is cropped by CSS on phones
OUT = Path(__file__).resolve().parents[1] / "img" / "candidates"

STYLE = (
    "Photoreal editorial photograph, shot on a 35mm lens, natural light, honest "
    "colours, shallow depth of field. No text, no captions, no logos, no watermark."
)

PROMPTS = {
    1: (
        "A person seen from the side at a bright home kitchen counter in the "
        "morning, wearing black Wayfarer-style smart glasses, placing a bowl of "
        "cooked white rice on a slim digital kitchen scale; the scale display is "
        "lit; their hands are relaxed, nothing in them but the bowl; calm, "
        "unposed. " + STYLE
    ),
    2: (
        "Over-the-shoulder close-up of someone wearing black smart glasses "
        "looking down at a digital kitchen scale holding grilled chicken breast "
        "on a plate; the glowing display shows a three-digit number; evening "
        "kitchen, one warm lamp, dark background, the glasses' small camera "
        "lens catching the light. " + STYLE
    ),
    3: (
        "Minimal still life on a paper-white surface: a pair of black "
        "Wayfarer-style smart glasses resting beside a white digital kitchen "
        "scale holding a bowl of oats, a single clementine for colour, soft "
        "studio light, generous empty space in the upper third. " + STYLE
    ),
    4: (
        "A person in a small apartment kitchen wearing black smart glasses, "
        "mid-sentence with a slight smile as if speaking to no one, a pan on the "
        "stove behind them, a digital kitchen scale with chopped vegetables in "
        "the foreground, documentary style, warm late-afternoon light through a "
        "window. " + STYLE
    ),
}


def generate(prompt: str, n: int, key: str, size: str = SIZE) -> list[bytes]:
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "n": n,
            "size": size,
            "output_format": "webp",
        }
    ).encode()
    req = urllib.request.Request(
        f"{API}/images/generations",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    delay = 0.5
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.load(resp)
            return [base64.b64decode(item["b64_json"]) for item in payload["data"]]
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            if e.code == 429 and attempt < 5:
                time.sleep(delay + random.random() * 0.5)
                delay *= 2
                continue
            sys.exit(f"HTTP {e.code} from {API}/images/generations: {detail}")
    sys.exit("gave up after repeated 429s")


def write_browser(out: Path, entries: list[tuple[str, int, int, str]]) -> Path:
    rows = []
    for name, p, i, prompt in entries:
        rows.append(
            f'<figure><img src="{name}" loading="lazy"><figcaption>'
            f"<b>hero: {p}-{i}</b> · {name}<br><small>{prompt}</small></figcaption></figure>"
        )
    html = (
        "<!doctype html><meta charset=utf-8><title>itlogs.food hero candidates</title>"
        "<style>body{font:14px/1.5 -apple-system,sans-serif;margin:2rem;background:#fafaf7;color:#111}"
        "figure{margin:0 0 2.5rem;max-width:960px}img{width:100%;border-radius:6px;display:block}"
        "figcaption{margin-top:.5rem}small{color:#555}</style>"
        "<h1>Pick one and say its number, e.g. “hero: 2-3”</h1>" + "".join(rows)
    )
    path = out / "browse.html"
    path.write_text(html)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=5, help="images per prompt (1 to 10)")
    ap.add_argument("--only", type=int, action="append", help="run only this prompt number (repeatable)")
    ap.add_argument("--prompt", help="a custom prompt instead of the built-in ones")
    ap.add_argument("--size", default=SIZE, help='aspect as "WxH", default 1536x1024')
    args = ap.parse_args()

    key = os.environ.get("MODEL_API_KEY") or os.environ.get("ITLOGS_META_API_KEY")
    if not key:
        sys.exit("MODEL_API_KEY is not set: run `source ~/.secure_env_vars` first, in your own terminal")
    if not 1 <= args.n <= 10:
        sys.exit("--n must be between 1 and 10")

    prompts = {0: args.prompt} if args.prompt else PROMPTS
    if args.only:
        prompts = {k: v for k, v in prompts.items() if k in args.only}
    OUT.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M")
    entries: list[tuple[str, int, int, str]] = []
    total = 0
    for p, prompt in prompts.items():
        print(f"prompt {p}: {args.n} image(s) ...", flush=True)
        images = generate(prompt, args.n, key, args.size)
        for i, data in enumerate(images, 1):
            name = f"hero-{stamp}-p{p}-{i}.webp"
            (OUT / name).write_bytes(data)
            entries.append((name, p, i, prompt))
            total += 1
            print(f"  wrote {name} ({len(data) // 1024} KB)")

    # keep earlier runs in the browser too
    for old in sorted(OUT.glob("hero-*.webp")):
        if not any(old.name == e[0] for e in entries):
            parts = old.stem.split("-p")
            entries.append((old.name, 0, 0, f"earlier run {parts[0].removeprefix('hero-')}"))
    browser = write_browser(OUT, entries)
    print(f"\n{total} image(s), about USD {total * 0.01:.2f}. Browse: open {browser}")


if __name__ == "__main__":
    main()
