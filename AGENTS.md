# AGENTS.md

For coding agents, and for anyone using an LLM to read this repository. [README.md](README.md) says what the project is and how far it has got. This file says how to read the code and how to check what the README claims.

## Read in this order

1. `README.md`: the state table, then "How a food gets logged".
2. `server/itlogs/session.py`: every decision. Start at `decide`, then `_watch`, then `_bowl_step`.
3. `server/itlogs/providers/meta.py`: the prompts and JSON schemas, the only place the models are told anything.
4. `server/itlogs/models.py`: the wire types, mirrored by `ios/Sources/ItlogsFood/Protocol.swift`.
5. `server/itlogs/app.py`: the socket, and how reads run in the background.
6. `ios/Sources/ItlogsFood/SessionController.swift`: the phone's side of a run.
7. `evals/replay.py` with one file from `evals/traces/`: what real reads look like.

## Module map

| File | What it holds | Start at |
|---|---|---|
| `server/itlogs/session.py` | The loop: weighing mode, bowls, "log it", voice, barcodes. One `Session` per socket | `decide`, `_watch`, `_bowl_step`, `final_look` |
| `server/itlogs/app.py` | FastAPI, `/ws/session`, `/health`, `/log`. Pairs JSON meta with binary frames; at most two reads in flight | `ws_session`, `think` |
| `server/itlogs/frames.py` | Which frame is worth a model call: stillness and sharpness, pixel math on thumbnails | `Stillness` |
| `server/itlogs/models.py` | Pydantic types for the wire and the domain | `EntryRead`, `Entry`, `ServerMessage` |
| `server/itlogs/nutrients.py` | Grams to nutrients from the Canadian Nutrient File: curated map, aliases, careful search | `lookup`, `search` |
| `server/itlogs/providers/base.py` | The seam: `VisionProvider`, `LLMProvider` | both protocols |
| `server/itlogs/providers/meta.py` | Reader and parser on any OpenAI-compatible endpoint; prompts and schemas | `ENTRY_SYSTEM`, `read_entry`, `read_addition`, `make_reader` |
| `server/itlogs/providers/chat.py` | One chat client with JSON-schema output, and a plain-mode fallback | `structured` |
| `server/itlogs/providers/fake.py` | Deterministic providers for tests and replay | `FakeVision` |
| `server/itlogs/barcode.py`, `server/itlogs/providers/openfoodfacts.py` | A frame to a barcode, a barcode to a product's label values | `decode`, `lookup` |
| `server/itlogs/asr.py` | Muse Voice Transcribe, used only when PCM comes up from the phone | `Transcriber` |
| `server/itlogs/record.py`, `telemetry.py` | Optional local recording; optional PostHog events | `Recorder` |
| `ios/Sources/ItlogsFood/GlassesSource.swift` | The toolkit: registration, session, camera stream, speech | `start` |
| `ios/Sources/ItlogsFood/SessionController.swift` | Start, Stop, the message handler, the warnings | `start`, `stop`, `handle`, `warning` |
| `ios/Sources/ItlogsFood/StreamClient.swift` | The one WebSocket: ordered queue, pings, reports a dead socket | `connect`, `lost` |
| `ios/Sources/ItlogsFood/SessionView.swift`, `ReviewView.swift`, `Health.swift` | The weighing screen, the table, the HealthKit write | |
| `evals/replay.py`, `evals/traces/` | Real recorded reads through today's logic | `replay` |
| `evals/recorded-runs.org` | Every recorded session: reads, latency, rows | |
| `evals/run.py`, `evals/sets/` | Accuracy against ground truth. No sets exist yet | |
| `server/scripts/` | `doctor`, `crashes`, `probe_reader`, `rules_check`, `cnf_snapshot` | |
| `site/` | The landing page at itlogs.food; deployed from `main` | |

## Glossary

- **read**: what the model said about one frame (`EntryRead`). Not yet a logged food.
- **entry** or **row**: one logged food (`Entry`). Its `status` says what produced it: `auto` (weighing mode, nobody asked), `agreed`, `confirmed` and `corrected` ("Log it now" and a voice answer), `spoken` (the wearer said the food and the grams).
- **weighing mode** or **watching**: the server reads on its own from Start to Stop. This is the demo path.
- **still**: the thumbnail difference has stayed below a threshold for 0.6 s (`Stillness`).
- **empty**: the scale reads 0 or less, or nothing is on it. Two in a row mean a new food can come.
- **bowl**: from the first read that sees a vessel until the scale is empty, each rise is one row.
- **final look**: one last read at Stop.
- **A time in a comment, like 21:58 or "2026-NOVEMBER-03 19:26"**: a real recorded session where this code path mattered. Many are in `evals/recorded-runs.org`.
- **`#12` and the like**: an issue number in the project's private tracker. The code and the commit message carry the reasoning, so nothing depends on reading it.

## Invariants and what pins them

| Invariant | Test |
|---|---|
| Real recorded sessions give the expected rows | `server/tests/test_replay.py`, `evals/replay.py` |
| A bowl adds up to what the scale showed, across a tare | `test_real_run_adds_up`, `test_the_bowl_adds_up_to_what_the_scale_showed` |
| Foods outside a bowl keep the whole number | `test_foods_outside_a_bowl_keep_the_whole_number` |
| A spoken amount in a bowl counts once | `test_saying_the_food_and_the_grams_does_not_count_it_twice` |
| A failed name never loses a row | `test_failed_naming_keeps_the_row` |
| A refused model call at Stop still sends the final state | `test_a_refused_model_call_at_stop_still_sends_the_final_state` |
| A recording keeps the frame that was read | `test_the_recording_keeps_the_frame_that_was_read` |
| A model number that is not a number is an unreadable read | `test_a_display_value_that_is_not_a_number_is_an_unreadable_read` |
| A dead socket is reported, and our own disconnect is not | `ios/Tests/ItlogsFoodTests/StreamClientTests.swift`, with `ITLOGS_WS_TEST_URL` set |

## Check the claims yourself

| Claim | Command | Expect |
|---|---|---|
| The tests pass | `make test` | all passed, on fake providers and mocked HTTP |
| Real reads give the rows in the README | `make replay` | `7 of 7 sessions replay as expected` |
| The dates, the author, no media or keys, the licences | `make rules-check` | every line `ok` or `info` |
| The phone holds no model key and calls no model | `grep -rnE 'MODEL_API_KEY\|api\.meta\.ai\|BASETEN' ios/Sources` | no output |
| Only standard-mode model ids | `grep -rn 'contributor' server/itlogs` | only the comment that rules them out |
| The latency figures | `make replay`, from `evals/recorded-latency.json` | 216 timed reads, median 3.2 s, 90th percentile 5.0 s |
| How much was carried from before this repo | `make rules-check` | about 400 lines of nearly 7,000 |

Works on real hardware only, so a clone cannot prove it: the glasses path and the Apple Health write. The evidence for those is the demo video and the recorded sessions.

## Not built, so do not assume it

Model training or recalibration. A history screen. Per-row delete on the review screen. Android. Authentication on the server. Reconnecting within a run. Any accuracy number against ground truth. The product logs what was weighed and gives no recommendation: its only model outputs are the fields in the schemas in `providers/meta.py`.

## If you change the code

- `make lint test replay` before every commit.
- A change to what `_watch` or `_bowl_step` logs shows up as a `DIFF` in replay. If the new rows are right, update `expect_now` in that trace and say why in the commit.
- Keep `models.py` and `Protocol.swift` in step: the phone decodes strictly.
- Models are reached only through `providers/`. Nothing else knows an endpoint.
- Do not add a recommendation path, and never commit photos, recordings or keys. The one exception is `site/img/real-frame.jpg`, a single frame approved by hand.
