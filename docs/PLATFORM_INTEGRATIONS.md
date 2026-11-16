# Integrations and official references

Documentation reviewed on 15 November 2026. External credentials and account approvals were not supplied, so live account connectivity is not claimed. Demo search remains available for every platform regardless of paid API access.

| Platform | Implementation / scope |
| --- | --- |
| YouTube | Data API search.list + videos.list metadata, API key, title/channel/duration/statistics. Up to 50 results per query. No media downloading. |
| Reddit | Application-only OAuth, official public post search, identifying User-Agent. Score retained as score, not fabricated video views. Requires approved Data API access. |
| Twitch | App-token flow; query searches game/category names, then gets clips for the first matched category. This is not global clip keyword search. |
| X | Bearer-authenticated recent post search with author expansion and available metrics; access depends on plan and scopes. |
| TikTok | Approval-required interface and manual URL/upload fallback. Research API eligibility is not assumed for a creator application. No unrestricted live discovery implementation. |
| Instagram | Approval-required interface and manual URL/upload fallback. Business/Creator permissions and reviewed hashtag access are not assumed. No unrestricted live discovery implementation. |

Connectors expose configured/not_configured/connected/approval_required/rate_limited/error states. A configuration check is not a successful network connection. Explicit Test connector performs a small metadata query and can consume quota. Transient metadata requests have three bounded attempts with exponential jitter; quota and credential failures are not blindly retried. Searches cap results and timeouts; deep pagination and persistent monitoring schedules are not implemented in this local release.

Official API references:

- [YouTube search](https://developers.google.com/youtube/data/reference/rest/v3/search/list) and [videos](https://developers.google.com/youtube/v3/docs/videos/list).
- [Reddit API](https://www.reddit.com/dev/api/) and [Reddit data access](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data).
- [Twitch API](https://dev.twitch.tv/docs/api/reference/) and [clips](https://dev.twitch.tv/docs/api/clips/).
- [X recent search](https://docs.x.com/x-api/posts/search-recent-posts).
- [TikTok research query and required scope](https://developers.tiktok.com/docs/en/research-api-specs-query-videos).
- [Instagram hashtag discovery and limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/hashtag-search).
- [Telegram Bot API](https://core.telegram.org/bots/api#sendvideo). The app conservatively caps uploads at 49 MB by default, reports errors and avoids automatic replay after an uncertain send.
- [OpenAI Responses](https://developers.openai.com/api/reference/resources/responses/methods/create) and [transcription](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create). AI_MODEL is deliberately user-configured; transcription defaults to the SRT-capable whisper-1 model. The interface sends only explicit user context/audio; generated copy is editable and never auto-published.

No platform passwords, session cookies, browser bypasses, scraper credentials or paid API keys are bundled.
