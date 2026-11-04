# itlogs.food

**The pain:** logging food means typing every meal, and the typing kills the habit. Photo apps skip the typing but guess the portion: four popular ones logged calories and fat about one-third too low across about 100 meals ([study led by an NIH fellow, presented at the American Society for Nutrition's annual meeting](https://www.westnewsmagazine.com/health/ai-calorie-tracking-apps-may-be-inaccurate-tests-find/article_fd5c470b-6cc5-5240-bdaf-c38366e01239.html)).

**The fix:** wear Ray-Ban Meta glasses and put the food on any digital scale. The glasses read the grams off the display, Muse Spark names the food, and the meal goes to Apple Health with its calories and macros. No typing, hands free, nothing to pair with the scale.

![The view from the glasses: a phone showing 112 grams beside a kitchen scale whose display also shows 112](site/img/real-frame.jpg)

*A real frame from the glasses during a run, cropped. The app and the scale both say 112 g.*

Meta Global AI Developer Hackathon entry, Indie track, problem statement "Build for Your World". Site: https://itlogs.food

![CI](https://github.com/pdelfino/itlogs.food/actions/workflows/ci.yml/badge.svg)

**Reading this with an LLM or an agent?** Start at [AGENTS.md](AGENTS.md): read order, module map, and a command to check each claim below.

## Where it stands (2026-NOVEMBER-04)

| Capability | State | Evidence |
|---|---|---|
| Start, weigh single foods, Stop, review, send to Apple Health | **Works on real glasses in good light** | Best run, tag `best-run-2026-11-03`: apple 112 g, banana 124 g, 37 s from Start to the end, both foods in Health |
| Any digital scale | **Built for any, proven on one so far** | It reads the display and pairs with nothing, so nothing here is specific to one scale. Every recorded run used the same backlit scale |
| One row per food | **Works**, and old bugs are pinned | `make replay` on real recorded reads |
| A dim room | **Fails**: the digits wash out | 102 reads, 1 with a weight ([recorded runs](evals/recorded-runs.org)). The screen and the ear say the display is lost |
| A bowl, one row per ingredient | **Grams proven on real reads; naming not yet run on a real bowl** | Replay gives 104 g where the app had logged 265 g; `server/tests/test_bowl.py` |
| Packaged food by barcode | **Built, not proven on a real wrapper** | Decoder and Open Food Facts lookup pass on test data and one live lookup. From the glasses, a bar on the scale is about 85 px wide and needs about 120. The phone scanner has not run on a device |
| Spoken input | **Heard live, commands not exercised live** | The glasses' recognizer delivered speech in real runs. The parser is tested on mocked responses |
| "Hey Meta, start" launch | **Built, not working yet** | `VoiceInvocations.swift`; needs a Wearables Developer Center release channel |
| Accuracy against ground truth | **Not measured yet** | `evals/sets/` is empty, so `make eval` reports no sets |

## Why this approach

Smart scales weigh correctly, then make you pick the food by hand on a phone. Meta announced food logging by photo for its glasses in 2026: US only, estimated portions, in the Meta AI app. So the glasses read the number on the scale you already own. The scale supplies the grams, the glasses supply the picture, the model supplies the food's name, a table or a barcode supplies the nutrients, and nobody types. [What Meta has said, and the prior art](docs/prior-art.org).

## How a food gets logged

This is the path the app uses from Start to Stop.

1. **Start** opens one WebSocket to the server and starts the glasses' video stream: 720 x 1280 at 7 fps, which the toolkit lowers to 504 x 896 when Bluetooth is tight (`GlassesSource.swift`).
2. **Which frame:** the server compares thumbnails frame by frame. It only spends a model call once the scene has been still for 0.6 s, and it picks the sharpest recent frame (`frames.py`). If the scene never settles, it reads anyway after 4 s.
3. **The read:** Muse Spark gets that frame and a JSON schema, and returns `food`, `display_value`, `unit`, `confidence` and `container` (`MetaReader.read_entry`). A median read takes 3.2 s. Reads run in the background, at most two at a time, so frames keep flowing.
4. **The decision** (`Session._watch`), with nobody asked:
   - One read at confidence 0.8 or above on a still scene logs the food. Otherwise two reads in a row must agree on the food and on the grams within 1 g.
   - A new read of the same food, with no empty scale in between, **corrects** that row instead of adding one.
   - The same grams under another name with no empty scale in between is the same item, because two foods cannot show the same weight without the scale passing through empty.
   - Two empty reads in a row mean a new food can come. One alone is a hand over the display.
5. **A bowl** (`Session._bowl_step`): once the reader sees a vessel, each rise on the scale is one ingredient, with only the grams it added. A tare keeps the count going. One model call names the ingredient from what was said if that names a food, and otherwise by comparing the bowl before and after (`MetaReader.read_addition`).
6. **Nutrients** (`nutrients.py`): grams times a per-100 g row from the Canadian Nutrient File (5,690 foods), through a curated map and then a careful name search. An unknown food shows "?" and never gets a guessed row. A barcode replaces the row with the product's label values.
7. **Stop** reads the scene one last time, so the last food is not lost to the reader's latency. The ear says "Check the meal", the phone shows the table, and one tap writes the meal to Apple Health.

There is also an older deliberate trigger, "Log it now", which takes two looks about 1.5 s apart and asks by voice when they disagree (`Session.capture`, `_resolve`, `_ask`). The agreed, confirmed and corrected statuses come from that path. Weighing mode writes `auto`.

## Meta tooling

| Tool | What it does here | Where | In the demo? |
|---|---|---|---|
| Muse Spark 1.3, vision | Names the food and reads a third-party display from a head-worn camera, as structured output | `providers/meta.py`, `MetaReader.read_entry` | **Yes**: 216 timed reads on real runs |
| Muse Spark 1.3, two images plus speech | Names what was added to a bowl: the wearer's words if useful, else before and after pictures | `MetaReader.read_addition` | Built, not yet run on a real bowl |
| Muse Spark 1.3, text | Turns a spoken sentence into start, stop, log, confirm, correct, cancel or none | `MetaParser.parse_reply` | Runs on whatever the glasses hear; the commands themselves have not run live |
| Wearables Device Access Toolkit | Registration, device session, camera stream | `GlassesSource.swift` | **Yes** |
| Toolkit speech (`MWDATSpeech`) | Recognizes speech on the glasses; only text reaches the server | `GlassesSource.swift` | **Yes** |
| Toolkit voice invocation | "Hey Meta, start" launches the app | `VoiceInvocations.swift` | Not working yet |
| Muse Spark Open on Baseten | The same reader on open weights, one environment variable away (`ITLOGS_VISION=baseten`) | `make_reader` | Ran live: apple 112 g at 0.95 confidence, at 20 to 24 s per read. Too slow for live use |
| Muse Glimmer on llama-server | The same reader on this Mac (`ITLOGS_VISION=local`) | `make_reader` | Wired, not measured |
| Muse Voice Transcribe | Server-side speech, used only when the glasses' recognizer is unavailable | `asr.py` | Fallback, not in the demo |
| Muse Image | The pictures on the site | `site/tools/hero.py` | Site only |

Not used: SAM 3.1, Muse Wonder, the toolkit's motion capability. No model is trained here.

## Architecture

Three machines, one WebSocket, one seam. The glasses see and hear, the phone carries, the Mac on the LAN decides, and the models sit behind one Python protocol pair, so a model can change without touching the loop.

```
 Ray-Ban Meta glasses
   camera stream 720x1280 at 7 fps, on-glasses speech recognition, ear
        |  Bluetooth, Wearables Device Access Toolkit
        v
 iPhone  ios/  Swift, SwiftUI. No model calls, no model keys.
   GlassesSource | PhoneCameraSource   a JPEG plus t_ms, same downstream
   StreamClient                        the one WebSocket; pings; reports a dead socket
   SessionController, SessionView      Start, Stop, warnings, the live number
   ReviewView, Health                  the table, then HealthKit
        |  up:   frame (JSON meta, then JPEG), voice, watch, capture, barcode, end_session
        |  down: read, entry, ask, say, state
        v
 Mac  server/  FastAPI, Python 3.12+
   app.py        /ws/session: background reads, at most two; the barcode check on frames
   session.py    the decisions: weighing, bowl, "log it", voice
   frames.py     stillness and sharpness, pixel math, no model call
   nutrients.py  grams to nutrients
   barcode.py, providers/openfoodfacts.py   a barcode to a label
   record.py     optional: the frames read and the events, to a local folder, never git
   providers/    the seam: VisionProvider (read_entry, read_addition), LLMProvider (parse_reply)
        |
        +-- fake.py   deterministic, for tests, replay and CI
        +-- meta.py   one OpenAI-compatible client with JSON-schema output
                      Muse Spark on api.meta.ai, Muse Spark Open on Baseten, Glimmer on llama-server
```

## Evidence

All numbers come from [every recorded session](evals/recorded-runs.org): 21 sessions from 2026-NOVEMBER-02 to 04, on real glasses and one real scale. 16 of them have at least one read. Across them there are 228 reads, 80 with a weight. Muse Spark 1.3 took a median of 3.2 s and a 90th percentile of 5.0 s over 216 timed reads ([the raw timings](evals/recorded-latency.json), which `make replay` also summarizes).

`make replay` feeds the reads of real sessions to today's logic, with no key, no glasses and no network, and fails on any difference. CI runs it. It tests the decisions made from reads, not the reading itself.

| Session | What it shows | Logged at the time | Today's logic |
|---|---|---|---|
| 2026-11-03-201500 | The best run stays as it was | apple 112 g, banana 124 g | apple 112 g, banana 124 g |
| 2026-11-02-195113 | A re-read corrects its row | apple 108 g, apple 112 g, banana 128 g, whole banana 128 g, whole banana 188 g | apple 112 g, banana 128 g |
| 2026-11-02-194354 | Two names, one banana | banana 129 g, whole banana 129 g | banana 129 g |
| 2026-11-02-195734 | One 0 g read is a hand, not an empty scale | apple 113 g, banana 128 g, banana 128 g | apple 113 g, banana 128 g |
| 2026-11-03-214319 | Same grams under another name is the same item | apple 112 g, banana 124 g, protein bar 43 g, granola bar 43 g | apple 112 g, banana 124 g, protein bar 43 g |
| 2026-11-04-080057 | A bowl: each rise is one row, and the total is what the scale showed. Replay does not name the rows, since naming takes a model call | four rows, 265 g | five rows of 16, 14, 16, 50 and 8 g: 104 g |
| 2026-11-03-215802 | The dim kitchen: 102 reads, 1 weight. Still fails | nothing | nothing |

Tests: 88 server tests (`make test`), plus the iOS tests, on fake providers and mocked HTTP.

**Known limits**
- Dim light is unsolved. In one dim kitchen the digits wash out to a white rectangle on the display. We found no flash or exposure control in the toolkit.
- One scale has been tried, with a backlit display. Reading the display should work on any scale, but only this one is proven.
- There is no accuracy figure against ground truth yet, and no model confidence is calibrated.
- The server trusts its LAN: the WebSocket has no authentication. Run it on your own network.
- One socket is one run. If the socket dies, the phone keeps what was logged, says so and asks you to tap Stop; there is no reconnect within a run.
- The first Start after "Forget and reconnect" can lose voice for that run, because the toolkit's microphone permission fails on the second app switch. The next Start works.
- There is no history screen and no per-row delete yet. Review sends all rows or none, and a row with no nutrient data shows "?" and is left out of the Health write.

## Built during the hackathon

Kickoff was 2026-OCTOBER-26 12:00 ET and the deadline is 2026-NOVEMBER-04 21:00 ET.

| When (ET) | What |
|---|---|
| OCTOBER-23 | Idea notes only, in a README, in a private sibling repo for an earlier gym idea. No code |
| OCTOBER-26 23:18 | First code, after kickoff, in that sibling repo: the WebSocket server, the Meta model clients, the voice path, the iOS client with the glasses source |
| NOVEMBER-01 14:58 | This repo: that transport layer is carried over (first commit, 20 files, 1,009 lines), and the food logic starts here |
| NOVEMBER-01 to 04 | Everything else, commit by commit |

Of the nearly 7,000 lines of Python and Swift here today, about 400 still come from that carried first commit (`make rules-check` counts them with `git blame`). The sibling repo stays private because it holds unrelated plans. [docs/rules-compliance.org](docs/rules-compliance.org) lists its commits, and goes through the rules one by one. Built with Claude Code as a coding assistant, disclosed on every commit.

## Run it

No key and no hardware:

```sh
make setup        # the uv environment and xcodegen
make test replay  # the tests, and real recorded reads through today's logic
make run          # the server on :8000 with the fake provider
```

With the models, `MODEL_API_KEY` in the environment and frames recorded locally:

```sh
make run-live
```

On an iPhone with Ray-Ban Meta glasses: turn on Developer Mode in the Meta AI app (App Info, tap the version five times), then run `DEVELOPMENT_TEAM=<your Apple team id> make ios-run` with the phone unlocked. You will likely need your own bundle id in `ios/project.yml`. In the app's Settings, connect the glasses, turn on the glasses source and set the server address.

## Your data

Frames go from the glasses through the phone to a server you run, and from there to the model provider you configured (the Meta Model API, on standard-mode model ids, or Baseten). The stream is not written to disk. With `ITLOGS_RECORD_DIR` set, the frames that were read and the session's events are kept in that local folder. With a PostHog token set, food names, grams and diagnostic lines go to PostHog. Apple Health gets a meal only when you confirm it. [Privacy](https://itlogs.food/privacy.html).

## Credits

Nutrients: Canadian Nutrient File, Health Canada, contains information licensed under the [Open Government Licence, Canada](https://open.canada.ca/en/open-government-licence-canada). Packaged foods: [Open Food Facts](https://world.openfoodfacts.org), under the Open Database License. Fonts: SIL Open Font License, with the licences in `site/fonts/`. The Wearables Device Access Toolkit is fetched by Swift Package Manager under Meta's terms and is not in this repo.
