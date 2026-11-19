# Live Watch verification — November 16, 2026

Implementation lives in `/Users/omvednagre/Desktop/Clip`. No ZIP was created. Existing SQLite data was backed up under ignored `storage/backups/` before migration 0003 was applied.

## Passed

- Full backend suite: **68 passed**, including the existing localhost HTTP server use-case and 20 new live-watch checks. JUnit: `test-results-backend.xml`.
- Frontend components: **13 passed** across three files. JUnit: `test-results-components.xml`.
- New live-watch checks were rerun after the final reconnect-timeline reset: **20 passed**.
- Real FFmpeg source segment → MP4 extraction → authorized media import → original and vertical renders → review approval → download.
- Real supervisor subprocess: interrupted-session recovery, incomplete-candidate marking, exclusive worker ownership and clean SIGTERM exit.
- YouTube and Twitch adapter contracts use deterministic test responses, including authenticated TLS IRC framing/PING, YouTube paging/minimum polling interval, owner mismatch and ended streams.
- Detection checks cover warm-up, prior-window baseline, spam limits, cooldown, quiet periods and out-of-order events. API checks cover consent, URL restrictions, authentication, duplicates, stop, schedules, allowlists, low-space checks, gaps and bounded retries.
- Ruff checks, production frontend build, Python dependency consistency and npm production audit (0 vulnerabilities).
- Migration 0003 upgrade → downgrade to 0002 → upgrade and Alembic schema check on an isolated database.
- Base and production override Docker Compose configuration validation. This is syntax/config validation, not a running-container test.
- Browser inspection of the rebuilt Live Watch screen at localhost:8001: capture tools installed; YouTube key, Twitch token and caption model correctly shown as missing; permission checkbox gates starting. Temporary verification server was stopped. An older app process already occupied port 8000 and was left running; restart it to load the new backend routes.
- Supplied YouTube URL: public oEmbed metadata resolved and Streamlink 8.6.3 returned playback qualities. No recording was started during this check.

## Still requires external setup

Authenticated YouTube/Twitch live chat, a real overnight capture, Whisper model inference, Docker runtime and public HTTPS deployment remain unverified. Configure credentials locally and select the always-on host before those checks. Token refresh is operator-managed in this release. YouTube polling is subject to API quota and may require a larger allocation for long sessions. Capture/chat alignment is approximate and needs live calibration.

The existing test client emits one upstream Starlette/httpx deprecation warning; tests pass. Native macOS FFmpeg lacks libass, so caption burn-in needs a compatible FFmpeg installation (the local editor exposes this limitation).

## Run again

From the project folder:

```sh
make test
make test-live
make test-usecase
```

Setup and operating details are in [LIVE_WATCH.md](LIVE_WATCH.md).
