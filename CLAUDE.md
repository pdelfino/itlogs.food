# itlogs.food

Read [AGENTS.md](AGENTS.md) first: what this is, the module map, the glossary, the invariants and how to check each claim. This file only adds the working loops.

## Loops (see `make help`)
- `make lint test replay` before every commit. `make rules-check` for the hackathon rules.
- `make run` is the server on the fake provider. `make run-live` is the real thing and needs `MODEL_API_KEY` in the environment; a person runs it in their own terminal, an agent never holds a key. It reloads on any edit under `server/itlogs`, which cuts a live run, so check `.sessions/phone.log` for a Start with no Stop before editing there.
- iOS: `make ios-gen` regenerates the Xcode project from `ios/project.yml` (never edit a .xcodeproj by hand; it is not committed). `make ios-test` runs on the simulator. `DEVELOPMENT_TEAM=<team id> make ios-run` installs on a phone, which must be unlocked. A build number on the phone is the commit count at build time.
- Glasses only work on a physical iPhone paired in the Meta AI app. The simulator covers the UI and the WebSocket client.

## Reading what went wrong, in this order
1. The server's terminal, or `make phone-logs`: every `Diag.send` from the phone arrives as `PHONE hh:mm:ss ...`.
2. `make phone-crashes` (phone on USB, unlocked): the app's crash reports, one line each.
3. `make phone-dat-log` (phone on USB, unlocked; about a minute): the toolkit's own log, with the real reason behind what the SDK reports to the app.
4. PostHog, when a token is set: `phone_diag`, `$exception`, `entry_logged`. An OS kill leaves no `$exception`, only a crash report.

## Rules
- Secrets come from the environment (`ITLOGS_*`, see `server/.env.example`); never in the repo, never echoed.
- Photos and model weights never enter git, apart from the one approved frame: `site/img/real-frame.jpg` and its link-preview crop `site/img/og-real-frame.jpg`. Recordings stay in a local folder.
- Only standard-mode model ids (no `-contributor`).
- Org-mode for docs (`README.md` and `AGENTS.md` are the two exceptions), no em-dashes, dates as 2026-OCTOBER-26 in prose.
- Keep commits honest and small: the commit history is how this project shows what was built when.
