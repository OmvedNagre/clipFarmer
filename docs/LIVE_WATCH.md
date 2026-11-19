# Live Watch and scheduled discovery

Changes are maintained directly in `/Users/omvednagre/Desktop/Clip`. No release ZIP is required.

## Run locally

Run `./scripts/start.sh` in one terminal and `./scripts/watch.sh` in another. The first serves the UI and processes queued renders; the second runs capture/chat sessions and scheduled discovery. Both use the same database and storage. Open Live Watch in the sidebar. The moved environment has been reinstalled and launch scripts use `python -m` to avoid stale command shebangs. Run `./scripts/setup.sh` if you move machines or rebuild the environment.

The watcher is independent of the browser. A sleeping laptop still interrupts it; use an always-on Linux host for unattended operation. No server has been chosen or deployed yet.

## Connections requiring your input

Copy `.env.example` to `.env` if it does not exist, and edit it locally. Never send tokens in chat or commit `.env`.

- YouTube: set `YOUTUBE_API_KEY` for a Google project with YouTube Data API enabled. Supply the stream owner's `UC…` channel ID and permission record. The watcher compares that ID with the video owner before capture. Live chat must be available. Quota exhaustion or denied access stops the session with a visible diagnostic.
- Twitch: set `TWITCH_CLIENT_ID`, `TWITCH_USER_TOKEN` and `TWITCH_CHAT_LOGIN`. The token must belong to that login and include `chat:read` for authenticated IRC. Supply the broadcaster's numeric user ID. Tokens are configured by the operator; OAuth onboarding and automatic token refresh are not implemented. An expired/revoked token requires replacement and a new watch. Scheduled Twitch discovery additionally requires `TWITCH_CLIENT_SECRET` for its existing app-token adapter.
- Captions: install whisper.cpp, download a compatible model, and set `WHISPER_BINARY` and `WHISPER_MODEL_PATH`. Automatic local captions are opt-in. The pipeline converts extracted audio to 16-bit mono 16 kHz WAV and requests SRT. Caption failure leaves a reviewable clip with a diagnostic. Burn-in uses the existing media editor and needs an FFmpeg build with libass; the current Mac FFmpeg lacks that filter.
- Always-on deployment: select a Linux server and domain; configure HTTPS and persistent disk backups. `docker-compose.server.yml` requires production authentication, live discovery mode and the exact public origin. It keeps the API bound to loopback for an HTTPS reverse proxy. It does not provision a host, domain or TLS. Do not scale replicas: this release is single-host and uses SQLite and OS worker locks.

Supplied test URL: https://www.youtube.com/watch?v=Z0CPIt32Ux0 . On November 16, 2026, YouTube oEmbed returned “The Baby IN Yellow horror gameplay #horrorgaming #games”, by “dig's gaming”. Streamlink resolved the YouTube plugin and available qualities successfully. These checks did not record media or verify live chat/live status. API credentials are still needed for that proof.

## Behavior and boundaries

A session validates the platform URL and creator consent, waits for live status, captures publicly accessible platform media using Streamlink, and records segments through FFmpeg. There is no bypass for private, restricted, DRM-protected or unavailable streams and no arbitrary URL fetch. A source link does not itself prove permission.

YouTube chat uses the documented REST list endpoint, preserving its next-page token and honoring `pollingIntervalMillis`. Initial historical chat is discarded. Twitch uses authenticated IRC over TLS with PING/PONG and reconnect handling; Twitch recommends EventSub for newer integrations, which remains a future transport upgrade. Neither path posts chat messages.

The detector counts 10-second buckets against the preceding five minutes, excludes the current bucket from its baseline, requires a minimum message count and distinct chatters, caps each user's contribution at three per bucket, and suppresses same-user repeated text. Default detection is 3× baseline, at least 10 messages and 5 people. A 45-second cooldown suppresses nearby spikes. There is a five-minute warm-up after each capture start/reconnect. Message text and user identifiers are only held in bounded in-memory buckets, never stored in the database; the UI retains the last 180 aggregate buckets.

Default extraction includes 30 seconds before the start of the reaction bucket, the 10-second bucket itself, and 15 seconds after: up to 55 seconds. Capture timestamps are approximate, anchored to the first completed media segment. The adjustable chat-delay setting accommodates observed latency. They are not original broadcast timestamps, frame-perfect synchronization, or a guarantee of recording from the stream's first second. Review boundaries in Media & processing before publishing.

Extraction runs separately from chat reads. Completed segments retain a rolling ~10-minute buffer; segments required by pending clips remain pinned. Captured clips are re-encoded, probed and imported into the existing authorized-media pipeline, then optionally queued for original and vertical render. Provenance includes creator credit, source URL, capture offset and detection reason. Review approval is required before final download/delivery. Automatic publishing is not enabled.

One supervisor supports up to `LIVE_MAX_SESSIONS` concurrent watches, defaults to 2. Heartbeats expose stopped/stale workers. At most five reconnect retries occur with exponential backoff; reconnects use a fresh timeline and detector. Pending clips interrupted by a crash/reconnect are marked incomplete, never silently stitched over gaps. A worker restart requeues active watches and clears ephemeral buffers; graceful shutdown preserves watches for resume unless the user stopped them. Each new run has a configured maximum duration. Render jobs retain their existing recovery behavior.

`LIVE_STORAGE_GB` counts all files under storage, default 10 GB. `LIVE_MIN_FREE_GB` reserves 2 GB of disk. Exceeding either stops capture; originals and published outputs are never automatically removed. Retained media needs operator cleanup/backups. The budget is checked during capture, not a filesystem hard quota. Use container resource/disk limits for strict enforcement. Compose uses a 20-minute graceful shutdown window to let bounded extraction/transcription finish. Docker supervises the worker process tree; native force-killing a process requires checking for orphaned capture processes.

Scheduled discovery runs real API searches at intervals of at least 15 minutes and automatically saves only results matching the supplied creator allowlist. Creator IDs mean YouTube channel ID, Twitch broadcaster ID, Reddit username or X author ID. Search remains subject to the existing adapter's scope (Twitch searches category clips) and platform quotas; it is not an exhaustive scan of every creator upload. Results are deduplicated by platform/external ID. Metadata-only results require an authorized source file for editing. The scheduler reserves the next run before the network call to prevent crash-driven rapid retries.

## Verification

`make test-live` covers detector logic, permission and URL validation, session API/authentication, YouTube and Twitch adapter contracts, minimum polling intervals, bounded retries, low disk, creator allowlists, media gaps, and real FFmpeg segment extraction through rendering/review/download. Existing unit, component, use-case and functionality suites remain available. See LIVE_WATCH_VERIFICATION.md for the last actual run.

No authenticated live chat, overnight stream capture, real local Whisper inference, Docker runtime or public HTTPS deployment is claimed without exercising those paths.

## Primary documentation

- [YouTube live chat list API](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/list)
- [Twitch authenticated IRC](https://dev.twitch.tv/docs/chat/irc/)
- [Twitch migration recommendation](https://dev.twitch.tv/docs/chat/irc-migration/)
- [Streamlink CLI](https://streamlink.github.io/cli.html)
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
