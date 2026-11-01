# itlogs.food

The food product of the itlogs family: Ray-Ban Meta glasses look at the kitchen scale, the server names the food and reads the grams off the display, looks again, asks by voice when the two looks disagree, and the entry goes to Apple Health. Any scale works: the display is read, not the scale's radio. Built as a real product from day one and as the Meta Global AI Developer Hackathon entry (submission 2026-NOVEMBER-04 21:00 ET; everything about the competition in `hackathon/`).

## Architecture
- **Thin phone client** (`ios/`, Swift, SwiftUI): pairs the glasses, streams JPEG frames and the microphone up a WebSocket, sends the deliberate trigger (the Log it button, or "log it" by voice), plays the server's `say` text with AVSpeechSynthesizer. No model calls on the phone. Apple Health is written from the phone (issue #3).
- **Server** (`server/`, Python 3.12+, FastAPI): `itlogs/session.py` is the loop (capture, second look, agree or ask, log), `itlogs/nutrients.py` turns grams into nutrients, `itlogs/providers/` is the seam. The server never knows an endpoint outside `providers/`.
- **Provider seam**: every model call goes through `VisionProvider.read_entry` and `LLMProvider.parse_reply` (`providers/base.py`). `fake.py` is deterministic and is what tests and `make eval` use. `providers/chat.py` is one OpenAI-compatible client with JSON-schema output; `providers/meta.py` puts Muse Spark (Meta Model API) or Muse Glimmer (llama-server on the Mac, the open-weight path) behind the protocols. Adding another model is a new file, nothing else.
- **Evals** (`evals/`): two photos per weighing plus the truth; `make eval` prints food top-1, grams within 1 g, and how often the loop logged without asking. The number in the README is the number this prints.
- **The label comes free**: every entry ends as agreed, confirmed or corrected. That is the eval set and the recalibration data (issue #4); no separate labeling session.

## Loops (all from the terminal; see `make help`)
- `make test`, `make lint`, `make format`, `make run`, `make eval`. Run `make lint test eval` before every commit.
- `make run-live` is the real thing (Meta models, the recorder). It needs `MODEL_API_KEY` in the environment, which lives in Pedro's `~/.secure_env_vars`: Pedro runs it in his own terminal; Claude never holds the key.
- `make ci` runs the GitHub workflow locally with act before any push (drafts skip Actions).
- iOS: `make ios-gen` regenerates the Xcode project from `ios/project.yml` (never edit a .xcodeproj by hand; it is not committed). `make ios-build`, `make ios-test` (simulator), `DEVELOPMENT_TEAM=6X8G2S2P89 make ios-run` (device; that is Pedro's personal team id, the certificate id SAZGZ8NBNB is not it; the phone must be unlocked), `make ios-logs`. From Claude Code the build and install need the sandbox off.
- The glasses only work on a physical iPhone paired in the Meta AI app. The simulator covers UI and the WebSocket client with `PhoneCameraSource`.

## Meta facts (details in hackathon/meta-model-api-notes.org and hackathon/wearables-toolkit-notes.org)
- Base URL `https://api.meta.ai/v1`, OpenAI-compatible; key in `MODEL_API_KEY` / `ITLOGS_META_API_KEY`, never on the phone.
- Models: `muse-spark-1.3` (stills and text, structured output via `response_format` json_schema), `muse-voice-transcribe-1.0` (realtime WebSocket, PCM 24 kHz, ENDPOINTING mode), Muse Glimmer 30B GGUF plus its vision projector on the Mac via llama-server.
- Standard-mode ids only (no `-contributor`): those train on the content, and the content is Pedro's kitchen.
- Glasses: video stream at most 720 x 1280, compressed over Bluetooth Classic; `capturePhoto()` stills, full resolution in the dev and beta channels only. Stream and photo cannot run at once.

## Rules
- Secrets come from the environment (`ITLOGS_*`, see `server/.env.example`); never in the repo, never echoed.
- Photos and adapter weights never enter git (`.gitignore`); they live on the T7. Only the frames a read was made on are kept, never the stream: "narrow purpose, short retention, obvious to bystanders" is Meta's design principle for glasses apps and ours.
- The Wearables Device Access Toolkit sample app goes in `ios/vendor/` (ignored) so the API is read from source, not guessed.
- This repo goes public at submission and stays public. Before any commit ask: would I mind Meta reading this? If yes, it does not belong here.
- Positioning: this is a hands-free logger, never a coach. The guide's anti-project list has "AI Nutrition Coach" and "Simple Image Analyzers". Never write coach, advice, diet plan, what to eat or healthy anywhere; the second look and the voice check are what make it more than an image analyzer.
- Everything built is new work from kickoff day 2026-OCTOBER-26 onward (the transport layer came from itlogs.fit, written OCTOBER-26 to 27 during the hackathon); the commit history is the proof, so keep commits honest and small.
- Org-mode for docs, no em-dashes, dates as 2026-OCTOBER-26 in prose.
- Design choices: 2 to 3 options with one Recommended on the GitHub issue; Pedro picks before code.
