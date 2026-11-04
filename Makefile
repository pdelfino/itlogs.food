# Every loop Claude Code (or a human) needs, runnable from the terminal. No Xcode GUI required
# for the server half; the iOS half needs Xcode installed once (App Store) and a signed-in device.

SHELL := /bin/bash   # the ios recipes need `set -o pipefail` (make 3.81 has no .SHELLFLAGS)
SERVER = uv run --project server
-include server/.env          # ITLOGS_POSTHOG_TOKEN and ITLOGS_POSTHOG_HOST reach the iOS build from here (the file is ignored)
export ITLOGS_POSTHOG_TOKEN ITLOGS_POSTHOG_HOST
SCHEME = ItlogsFood
DEVICE ?= $(shell xcrun xctrace list devices 2>/dev/null | grep -i iphone | grep -v Simulator | head -1 | sed -E 's/.*\(([0-9A-F-]+)\)$$/\1/')
SIM ?= $(shell xcrun simctl list devices available 2>/dev/null | grep -i iphone | head -1 | sed -E 's/^ *(.*) \(([0-9A-F-]+)\).*/\2/')

.PHONY: help setup test lint format doctor run-bg stop run run-live replay demo-log pov test-site waitlist rules-check eval eval-live ci ios-gen ios-build ios-test ios-run ios-logs phone-logs phone-dat-log phone-crashes docker-build

help:             ## this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /  /' | column -t -s '  '

setup:            ## install the server env (uv) and the iOS project generator
	uv sync --project server
	@command -v xcodegen >/dev/null || brew install xcodegen

test:             ## server unit tests
	cd server && uv run pytest -q

lint:             ## ruff lint and format check
	$(SERVER) ruff check server evals && $(SERVER) ruff format --check server evals

format:           ## ruff format
	$(SERVER) ruff check --fix server evals && $(SERVER) ruff format server evals

doctor:           ## one screen: repo, phone, last build, server, the phone's last words, crashes, telemetry
	$(SERVER) python server/scripts/doctor.py

# where live sessions are recorded (the frames a read was made on + session.json): the T7 when it is mounted, else an ignored local dir
RECORD_DIR ?= $(shell [ -d /Volumes/T7 ] && echo /Volumes/T7/itlogs-food-sessions || echo .sessions/record)

run-bg:           ## the server in the background with a persistent log (.sessions/server.log); records sessions to RECORD_DIR; survives the Claude session
	@mkdir -p .sessions; if curl -s --max-time 2 http://localhost:8000/health >/dev/null; then echo "already up on :8000"; else ITLOGS_RECORD_DIR=$(RECORD_DIR) nohup $(SERVER) uvicorn itlogs.app:app --app-dir server --host '::' --port 8000 >> .sessions/server.log 2>&1 & echo $$! > .sessions/server.pid; for i in 1 2 3 4 5 6 7 8 9 10; do sleep 1; curl -s --max-time 2 http://localhost:8000/health >/dev/null && break; done; curl -s --max-time 3 http://localhost:8000/health && echo " (pid $$(cat .sessions/server.pid), log .sessions/server.log)" || echo "did not come up; see .sessions/server.log"; fi

stop:             ## stop the background server
	@pkill -f "uvicorn itlogs.app:app" && echo "stopped" || echo "nothing running"

run:              ## the server on :8000 with the fake provider
	$(SERVER) uvicorn itlogs.app:app --app-dir server --host '::' --port 8000 --reload

run-live:         ## the server with the Meta models and the recorder (MODEL_API_KEY from the env); reloads on server/ changes
	set -o pipefail; mkdir -p .sessions; ITLOGS_PROVIDER=meta ITLOGS_RECORD_DIR=$${ITLOGS_RECORD_DIR:-$(RECORD_DIR)} $(SERVER) uvicorn itlogs.app:app --app-dir server --host '::' --port 8000 --reload --reload-dir server/itlogs 2>&1 | tee -a .sessions/server.log

replay:           ## real recorded reads through today's logic: no key, no glasses, no network
	$(SERVER) python evals/replay.py

demo-log:         ## the server's log for a screen, one plain line per thing that happened (FROM=n TO=n to print old lines)
	$(SERVER) python server/scripts/demo_log.py $(if $(FROM),--from-line $(FROM) --to-line $(TO),)

pov:              ## a video of what the glasses saw, from a run recorded with ITLOGS_RECORD_STREAM=1
	$(SERVER) python server/scripts/pov_video.py $(RECORD_DIR)

test-site:        ## the waitlist function, against a stand-in for its database
	node --test tests/

waitlist:         ## who joined the waitlist (needs a wrangler login on the itlogs.food Cloudflare account)
	CLOUDFLARE_ACCOUNT_ID=e76fd6e2d96bb78e17e0dbfd2212c970 npx --yes wrangler@4 d1 execute itlogs-food --remote --command "SELECT email, source, created_at FROM waitlist ORDER BY created_at"

rules-check:      ## what can be checked about the hackathon rules from a clone: dates, author, media, keys, licences
	$(SERVER) python server/scripts/rules_check.py

eval:             ## score the eval sets from their recorded reads, no model calls (fast, offline)
	$(SERVER) python evals/run.py --from-reads

eval-live:        ## run the photos through the configured provider; prints latency too
	$(SERVER) python evals/run.py

ci:               ## what GitHub Actions runs, locally (act) before any push
	act -W .github/workflows/ci.yml

site:             ## preview the landing page (site/) on http://localhost:8787
	python3 -m http.server 8787 -d site

docker-build:     ## the server image
	docker build -t itlogs-food-server server

ios-gen:          ## regenerate ios/ItlogsFood.xcodeproj from ios/project.yml (the .xcodeproj is not committed); build number = commit count, sha into Info.plist
	cd ios && BUILD_NUMBER=$$(git rev-list --count HEAD) GIT_SHA=$$(git rev-parse --short HEAD) POSTHOG_PROJECT_TOKEN="$${ITLOGS_POSTHOG_TOKEN:-}" POSTHOG_HOST="$${ITLOGS_POSTHOG_HOST:-https://us.i.posthog.com}" xcodegen generate

ios-build: ios-gen ## build for a connected iPhone, no install (DEVELOPMENT_TEAM=<team id>, as for ios-run)
	set -o pipefail; cd ios && xcodebuild -scheme $(SCHEME) -destination 'generic/platform=iOS' -configuration Debug build | tail -20

ios-test: ios-gen ## unit tests on the simulator (the glasses path needs a device)
	set -o pipefail; cd ios && xcodebuild -scheme $(SCHEME) -destination 'id=$(SIM)' test 2>&1 | grep -E "error:|Test run|✘|TEST (SUCCEEDED|FAILED)" | tail -10

ios-run: ios-gen  ## install and launch on the first connected iPhone (DEVELOPMENT_TEAM=<team id>, phone unlocked)
	set -o pipefail; cd ios && xcodebuild -scheme $(SCHEME) -destination 'id=$(DEVICE)' -configuration Debug -derivedDataPath build -allowProvisioningUpdates -allowProvisioningDeviceRegistration build | tail -5
	xcrun devicectl device install app --device $(DEVICE) ios/build/Build/Products/Debug-iphoneos/$(SCHEME).app
	xcrun devicectl device process launch --device $(DEVICE) food.itlogs.app

ios-logs:         ## stream the app's log lines from the device (idevicesyslog from brew libimobiledevice)
	idevicesyslog -u $(DEVICE) -p ItlogsFood

phone-logs:       ## what the phone reported to the server (Diag.send lines), newest last
	@tail -n $${N:-40} .sessions/phone.log 2>/dev/null || echo "no phone lines yet (server not started with ITLOGS_RECORD_DIR? the file is .sessions/phone.log)"

phone-dat-log:    ## pull the Meta toolkit's own error log out of the app on the phone (unredacted; the reason behind every refusal)
	mkdir -p .sessions/dat && rm -rf .sessions/dat/MetaWearablesDAT && xcrun devicectl device copy from --device $(DEVICE) --domain-type appDataContainer --domain-identifier food.itlogs.app --source Library/Caches/MetaWearablesDAT --destination .sessions/dat >/dev/null && tail -n $${N:-40} .sessions/dat/MetaWearablesDAT/Logs/MetaWearablesDAT.log | cut -c1-240

phone-crashes:    ## pull the app's crash reports off the phone and summarize them (SINCE=HH:MM to filter)
	$(SERVER) python server/scripts/crashes.py --device $(DEVICE) $(if $(SINCE),--since $(SINCE),)
