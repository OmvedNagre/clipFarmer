# Content workflow verification — 17 November 2026

## Automated checks

- Full backend suite: **106 passed**, zero failures. Covers units, API functionality, use cases, cancellation/restart recovery, daily caps and deduplication, safe URL parsing, classification, engagement ranking, and real FFmpeg import/render/download.
- React component suite: **16 passed**, zero failures, including own-stream flow without an approval checkbox.
- Frontend production build, Ruff, pip dependency check, Docker Compose configuration, and git diff whitespace checks passed.
- Alembic 0004 upgrade/downgrade/upgrade and schema check passed on an isolated database. User database was backed up before upgrading; current schema check reports no pending operations.
- One upstream Starlette/httpx deprecation warning remains; it does not fail tests.

Machine-readable current results: test-results-backend.xml and test-results-components.xml. Earlier verification documents describe previous releases.

## Actual local and external checks

- Updated API and UI running on 127.0.0.1:8000. Browser verified nightly scheduling, publication cutoff, heartbeat, Link Studio, and own-recording mode without permission controls.
- User-provided YouTube recording Z0CPIt32Ux0 inspected successfully (3451 seconds). Three actual four-second media samples downloaded and decoded (nine frames read).
- Actual replay-chat retrieval for that recording succeeded and produced **10 ranked chat-replay moments**. Temporary replay data was deleted afterwards.
- Real YouTube discovery exposed misleading high-view gameplay titles; filtering was tightened and a configurable publication cutoff added. No discovered result was sent during testing.
- Real local FFmpeg fixture exercised import, clip rendering and downloadable output. External downloads and Telegram delivery are mocked in deterministic full-workflow tests.

## Limits of verification

No real Telegram messages or attachments were sent during validation. Full-length external recording download-to-export was not run; external retrieval and replay parsing were checked separately, with the full processing pipeline checked using local media. No cloud deployment, Docker runtime build, paid AI request, or native libass caption burn-in is claimed. Face grouping and title-based relevance are estimates; genuine GTA VI gameplay and exactly 20 daily results cannot be guaranteed.

The current database backup is under storage/backups/before-content-20261117-105827.db. No ZIP was created and these changes were not pushed to GitHub.
