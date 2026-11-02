# Every loop Claude Code (or a human) needs, runnable from the terminal. No Xcode GUI required
# for the server half; the iOS half needs Xcode installed once (App Store) and a signed-in device.

SHELL := /bin/bash   # the ios recipes need `set -o pipefail` (make 3.81 has no .SHELLFLAGS)
SERVER = uv run --project server
-include server/.env          # ITLOGS_POSTHOG_TOKEN and ITLOGS_POSTHOG_HOST reach the iOS build from here (the file is ignored)
export ITLOGS_POSTHOG_TOKEN ITLOGS_POSTHOG_HOST
SCHEME = ItlogsFood
DEVICE ?= $(shell xcrun xctrace list devices 2>/dev/null | grep -i iphone | grep -v Simulator | head -1 | sed -E 's/.*\(([0-9A-F-]+)\)$$/\1/')
SIM ?= $(shell xcrun simctl list devices available 2>/dev/null | grep -i iphone | head -1 | sed -E 's/^ *(.*) \(([0-9A-F-]+)\).*/\2/')

.PHONY: help setup test lint format doctor run-bg stop run run-live eval eval-live ci ios-gen ios-build ios-test ios-run ios-logs phone-logs phone-crashes docker-build

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

run-bg:           ## the server in the background with a persistent log (.sessions/server.log); survives the Claude session
	@mkdir -p .sessions; if curl -s --max-time 2 http://localhost:8000/health >/dev/null; then echo "already up on :8000"; else nohup $(SERVER) uvicorn itlogs.app:app --app-dir server --host '::' --port 8000 >> .sessions/server.log 2>&1 & echo $$! > .sessions/server.pid; for i in 1 2 3 4 5 6 7 8 9 10; do sleep 1; curl -s --max-time 2 http://localhost:8000/health >/dev/null && break; done; curl -s --max-time 3 http://localhost:8000/health && echo " (pid $$(cat .sessions/server.pid), log .sessions/server.log)" || echo "did not come up; see .sessions/server.log"; fi

stop:             ## stop the background server
	@pkill -f "uvicorn itlogs.app:app" && echo "stopped" || echo "nothing running"

run:              ## the server on :8000 with the fake provider
	$(SERVER) uvicorn itlogs.app:app --app-dir server --host '::' --port 8000 --reload

run-live:         ## the server with the Meta models and the recorder (MODEL_API_KEY from the env)
	ITLOGS_PROVIDER=meta ITLOGS_RECORD_DIR=$${ITLOGS_RECORD_DIR:-/Volumes/T7/itlogs-food-sessions} $(SERVER) uvicorn itlogs.app:app --app-dir server --host '::' --port 8000

eval:             ## replay the recorded reads, no model calls (fast, offline)
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

phone-crashes:    ## pull the app's crash reports off the phone and summarize them (SINCE=HH:MM to filter)
	$(SERVER) python server/scripts/crashes.py --device $(DEVICE) $(if $(SINCE),--since $(SINCE),)
