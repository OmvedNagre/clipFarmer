# Content workflows

Implemented in the Desktop/Clip workspace, 17 November 2026. Start with `./scripts/start.sh`, then open http://127.0.0.1:8000.

## Daily GTA Gameplay

The feed uses the real YouTube API even while manual Discovery is in demo mode. It runs at 00:00 Asia/Kolkata with the API process and Mac awake. No cloud server or Live Watch process is required. If the app was off, one run for the current date is queued on restart; missed days are not replayed. Run today manually consumes the same daily allowance. Pause and attachment controls are on the feed page.

Three gameplay searches are filtered to finished videos in YouTube's Gaming category, with GTA VI/6 and gameplay terms in the title. Trailers, teasers, news, speculation, leaks, reactions, GTA V mods and common misleading topics are excluded. Remaining candidates are ranked by views. The default publication cutoff is 2026-11-19, based on Rockstar's announced launch date (https://www.rockstargames.com/VI); before that date the feed reports a shortfall without searching. Set DAILY_GAMEPLAY_NOT_BEFORE and restart if the relevant publication window changes.

Up to 60 candidates are inspected using three four-second video samples. A stable edge-position facecam-like detection is classified as face; no detected face as faceless; ambiguous results are skipped. This is a heuristic, not identity recognition or proof of genuine gameplay. Famous creators are not guaranteed. The target is 10 per group, never padded with filler. There may be fewer or no results.

Each day has at most 20 links, up to 20 additional eligible video attachments, and one summary. Sent or uncertain links are not resent on later runs. Existing Telegram messages are untouched. Unknown delivery outcomes are retained and not retried automatically, preventing duplicate messages after network interruption.

Attachments require YouTube's declared Creative Commons license or a channel ID in the authorized-creators list. Popularity does not supply authorization. Attachments must be accessible H.264 MP4s under the configured Telegram ceiling (default 49 MB). Unavailable or oversized files are skipped; the link remains usable. Credits and source links accompany delivery.

## Link Studio

Paste one public YouTube video/Short/finished live recording, Twitch clip, or Twitch VOD URL. Download a video requires source permission. My livestream highlights treats the source as your own recording and has no permission checkbox or approval step, including rendered downloads. Active broadcasts belong in Live Watch.

The worker downloads accessible media, imports and probes it, and offers a source download. For own recordings it ranks chat-replay activity first, platform replay intensity second, and audio-energy suggestions only when engagement is unavailable. Audio suggestions are explicitly labelled and do not claim measured popularity. Twitch replay chat is not guaranteed; audio fallback can be used. No historical concurrent-viewer count is fabricated.

Select suggested moments or enter manual start/end times; render original or vertical MP4s. Completed clips appear in Outputs. No captions or paid AI service is required. Default source limits are six hours, 500 MB, 720p retrieval, and a 30-minute download timeout. Private/login-restricted media, playlists, DRM, and inaccessible sources are unsupported. Upload a local source if retrieval fails.

Temporary samples and chat logs are deleted; imported source videos, exports, and delivery history persist. Storage should be monitored for retained media.

## Configuration

Existing YOUTUBE_API_KEY, TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are used. WORKER_ENABLED must be true. Optional limits: DAILY_CANDIDATE_LIMIT, DAILY_GAMEPLAY_NOT_BEFORE, LINK_MAX_DURATION_SECONDS, LINK_DOWNLOAD_TIMEOUT_SECONDS, MAX_UPLOAD_MB, TELEGRAM_MAX_UPLOAD_MB. Change .env and restart. Keep credentials out of Git.

The always-on cloud deployment and unattended live capture remain optional and on hold. A sleeping or powered-off Mac cannot send the nightly feed.
