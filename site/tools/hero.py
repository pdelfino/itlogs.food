#!/usr/bin/env python3
"""Make landing-page pictures for itlogs.food with Muse Image (Meta Model API).

Runs from Pedro's terminal with MODEL_API_KEY in the environment; the key never
enters the repo or an agent's context. USD 0.01 per image.

    source ~/.secure_env_vars && python3 site/tools/hero.py            # hero candidates: 4 prompts x 5
    python3 site/tools/hero.py --n 3 --only 2                           # 3 images of hero prompt 2
    python3 site/tools/hero.py --prompt "..." --n 5                     # your own prompt

    python3 site/tools/hero.py --story                                  # the six storyboard frames, 4 each,
                                                                        # same man as site/img/hero.webp (reference)
    python3 site/tools/hero.py --story --only 3 --n 6                   # six more of frame 3
    python3 site/tools/hero.py --story --ref path/to/other.webp         # another reference picture

Hero candidates land in site/img/candidates/, story candidates in
site/img/candidates/story/ (both gitignored), each with a browse.html next to
them: open it, pick, and tell Claude "hero: 2-3" or "story: 1-2, 2-4, 3-1, ...".
Only the chosen files are copied into site/img/ and committed.
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
SIZE = "1536x1024"  # 3:2, the page crops on phones
SITE = Path(__file__).resolve().parents[1]
OUT = SITE / "img" / "candidates"
STORY_OUT = OUT / "story"
DEFAULT_REF = SITE / "img" / "hero.webp"

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

# The storyboard: six frames, the same man, glasses, shirt and kitchen as the
# reference picture (site/img/hero.webp). The caption is the one line under
# each frame on the page; the prompt is what Muse Image gets.
SAME = (
    "Keep the same man, the same black smart glasses, the same beige linen "
    "shirt and the same bright kitchen with the window and the plants as in "
    "the reference picture. New scene: "
)
STORY = {
    1: (
        "Glasses on. Nothing to open.",
        SAME + "he stands at the counter with nothing in his hands, glasses on, "
        "looking down at an empty digital kitchen scale, morning light, calm. " + STYLE,
    ),
    2: (
        "Chicken on the scale.",
        SAME + "he sets a plate with a grilled chicken breast on the kitchen "
        "scale; the display lights up with a three-digit number; seen from the "
        "side at counter height. " + STYLE,
    ),
    3: (
        "Say log it.",
        SAME + "close on his face in three-quarter view, lips parted mid-word as "
        "if speaking quietly to no one, the small camera lens on the glasses "
        "catching the light, the scale soft in the foreground. " + STYLE,
    ),
    4: (
        "142 grams of chicken breast, logged.",
        SAME + "a small satisfied smile as he lifts the plate with the grilled "
        "chicken breast off the scale with one hand, the display behind it still "
        "lit, hands otherwise free. " + STYLE,
    ),
    5: (
        "Rice. Oil. Pumpkin. Three more lines.",
        SAME + "he assembles a bowl on the counter next to the scale: white rice, "
        "the chicken, roasted pumpkin cubes, a drizzle of olive oil from a small "
        "bottle, a wooden spoon, overhead three-quarter view. " + STYLE,
    ),
    6: (
        "Dinner, weighed. The log wrote itself.",
        SAME + "the finished dinner bowl on the counter in warm evening light: "
        "white rice, sliced grilled chicken breast and roasted pumpkin cubes "
        "glossy with olive oil, a wooden spoon, the glasses folded beside it, "
        "the scale switched off, no person in frame. " + STYLE,
    ),
}


def post(path: str, body: dict, key: str) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    delay = 0.5
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            if e.code == 429 and attempt < 5:
                time.sleep(delay + random.random() * 0.5)
                delay *= 2
                continue
            if e.code == 400 and ("size" in body or "output_format" in body):
                # the edits endpoint may not take these; retry bare once
                body = {k: v for k, v in body.items() if k not in ("size", "output_format")}
                req.data = json.dumps(body).encode()
                continue
            sys.exit(f"HTTP {e.code} from {API}{path}: {detail}")
    sys.exit("gave up after repeated 429s")


def decode(payload: dict) -> list[bytes]:
    return [base64.b64decode(item["b64_json"]) for item in payload["data"]]


def generate(prompt: str, n: int, key: str, size: str) -> list[bytes]:
    body = {"model": MODEL, "prompt": prompt, "n": n, "size": size, "output_format": "webp"}
    return decode(post("/images/generations", body, key))


def edit(prompt: str, n: int, key: str, size: str, ref: Path) -> list[bytes]:
    mime = "image/webp" if ref.suffix == ".webp" else "image/jpeg" if ref.suffix in (".jpg", ".jpeg") else "image/png"
    data_uri = f"data:{mime};base64," + base64.b64encode(ref.read_bytes()).decode()
    body = {
        "model": MODEL,
        "prompt": prompt,
        "images": [{"image_url": data_uri}],
        "n": n,
        "size": size,
        "output_format": "webp",
    }
    return decode(post("/images/edits", body, key))


def write_browser(out: Path, title: str, entries: list[tuple[str, int, int, str, str]], say: str) -> Path:
    rows = []
    last = None
    for name, p, i, caption, prompt in entries:
        if p != last:
            rows.append(f"<h2>{p}. {caption}</h2>" if caption else f"<h2>prompt {p}</h2>")
            last = p
        rows.append(
            f'<figure><img src="{name}" loading="lazy"><figcaption>'
            f"<b>{say}: {p}-{i}</b> · {name}<br><small>{prompt}</small></figcaption></figure>"
        )
    html = (
        f"<!doctype html><meta charset=utf-8><title>{title}</title>"
        "<style>body{font:14px/1.5 -apple-system,sans-serif;margin:2rem;background:#fafaf7;color:#111}"
        "figure{margin:0 0 2.5rem;max-width:960px}img{width:100%;border-radius:6px;display:block}"
        "figcaption{margin-top:.5rem}small{color:#555}h2{margin:3rem 0 1rem;font-size:1.1rem}</style>"
        f"<h1>{title}</h1><p>Pick and say the numbers, e.g. “{say}: 1-2”.</p>" + "".join(rows)
    )
    path = out / "browse.html"
    path.write_text(html)
    return path


def run_hero(args, key: str) -> None:
    prompts = {0: args.prompt} if args.prompt else PROMPTS
    if args.only:
        prompts = {k: v for k, v in prompts.items() if k in args.only}
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    entries: list[tuple[str, int, int, str, str]] = []
    total = 0
    for p, prompt in prompts.items():
        print(f"prompt {p}: {args.n} image(s) ...", flush=True)
        for i, data in enumerate(generate(prompt, args.n, key, args.size), 1):
            name = f"hero-{stamp}-p{p}-{i}.webp"
            (OUT / name).write_bytes(data)
            entries.append((name, p, i, "", prompt))
            total += 1
            print(f"  wrote {name} ({len(data) // 1024} KB)")
    for old in sorted(OUT.glob("hero-*.webp")):
        if not any(old.name == e[0] for e in entries):
            entries.append((old.name, 0, 0, "", f"earlier run {old.stem}"))
    browser = write_browser(OUT, "itlogs.food hero candidates", entries, "hero")
    print(f"\n{total} image(s), about USD {total * 0.01:.2f}. Browse: open {browser}")


def run_story(args, key: str) -> None:
    ref = Path(args.ref) if args.ref else DEFAULT_REF
    if not ref.exists():
        sys.exit(f"reference picture not found: {ref}")
    frames = STORY
    if args.only:
        frames = {k: v for k, v in frames.items() if k in args.only}
    STORY_OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    entries: list[tuple[str, int, int, str, str]] = []
    total = 0
    for k, (caption, prompt) in frames.items():
        print(f"frame {k} ({caption}): {args.n} image(s) from {ref.name} ...", flush=True)
        for i, data in enumerate(edit(prompt, args.n, key, args.size, ref), 1):
            name = f"story-{stamp}-f{k}-{i}.webp"
            (STORY_OUT / name).write_bytes(data)
            entries.append((name, k, i, caption, prompt))
            total += 1
            print(f"  wrote {name} ({len(data) // 1024} KB)")
    for old in sorted(STORY_OUT.glob("story-*.webp")):
        if not any(old.name == e[0] for e in entries):
            k = int(old.stem.split("-f")[1].split("-")[0])
            entries.append((old.name, k, 0, STORY[k][0], f"earlier run {old.stem}"))
    entries.sort(key=lambda e: (e[1], e[0]))
    browser = write_browser(STORY_OUT, "itlogs.food storyboard candidates", entries, "story")
    print(f"\n{total} image(s), about USD {total * 0.01:.2f}. Browse: open {browser}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=None, help="images per prompt or frame (1 to 10); default 5 hero, 4 story")
    ap.add_argument("--only", type=int, action="append", help="only this prompt or frame number (repeatable)")
    ap.add_argument("--prompt", help="a custom hero prompt instead of the built-in ones")
    ap.add_argument("--size", default=SIZE, help='aspect as "WxH", default 1536x1024')
    ap.add_argument("--story", action="store_true", help="the six storyboard frames, from the reference picture")
    ap.add_argument("--ref", help="reference picture for --story (default site/img/hero.webp)")
    args = ap.parse_args()

    key = os.environ.get("MODEL_API_KEY") or os.environ.get("ITLOGS_META_API_KEY")
    if not key:
        sys.exit("MODEL_API_KEY is not set: run `source ~/.secure_env_vars` first, in your own terminal")
    if args.n is None:
        args.n = 4 if args.story else 5
    if not 1 <= args.n <= 10:
        sys.exit("--n must be between 1 and 10")
    if args.story:
        run_story(args, key)
    else:
        run_hero(args, key)


if __name__ == "__main__":
    main()
