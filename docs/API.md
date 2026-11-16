# API

All application routes use `/api/v1`. Interactive schemas: `/docs`; OpenAPI: `/openapi.json`.

| Area | Routes |
| --- | --- |
| Health/config | GET /health, /system/status, /sources; POST /sources/{platform}/test; PATCH /sources/{platform} |
| Auth | GET /auth/status; POST /auth/login (`token`), /auth/logout |
| Discovery | POST /discovery/search (`query`, `platforms`, `limit` 1–50 per platform, `sort`); GET /discovery/searches, /discovery/searches/{id}; POST /discovery/items/{id}/save; POST /discovery/submit (`url`, `title`, `creator_name`) |
| Saved sources | GET /clips (`q`, `platform`, `offset`, `limit`), /clips/{id}; DELETE /clips/{id} (`confirm`) removes from saved library without deleting files |
| Media | POST /media/upload (multipart `file`, `authorization_status`, optional notes/source URL/discovery ID); GET /media, /media/{id}; PATCH /media/{id}; DELETE /media/{id} (`confirm`, `delete_file`); GET /media/{id}/download |
| Jobs | POST /processing/jobs; GET /processing/jobs, /processing/jobs/{id}, /processing/jobs/{id}/events, /processing/jobs/{id}/outputs; POST /processing/jobs/{id}/cancel, /retry |
| Outputs | GET /outputs, /outputs/{id}/download, /outputs/{id}/subtitles; download accepts `preview=true` for inline pre-review video |
| Review | POST /media/{id}/review (`action`: approved/rejected/needs_changes, `notes`); GET /media/{id}/reviews; POST /clips/{media_id}/approve, /reject are compatibility aliases using a media asset UUID |
| Delivery | POST /telegram/test; POST /outputs/{id}/telegram-send (`confirm_resend`); GET /outputs/{id}/deliveries |
| AI | POST /ai/suggest (`context`); POST /media/{id}/transcribe returns draft SRT; UI edits must be saved separately |
| Statistics | GET /stats/overview, /stats/platforms, /stats/processing |

Processing options: media_id, profiles (`original`, `shorts_1080x1920`, `shorts_720x1280`), trim_start_seconds, optional trim_end_seconds, normalize_audio, mute_audio, burn_subtitles, fps (24/30/60), crf (16–35).

Errors use `{error:{code,message,request_id}}`. No raw API exceptions, secrets or storage paths are returned. ProcessingJob responses intentionally include a snapshot of caption text, but no private paths. Output responses include a safe media summary. Pending/failed results never masquerade as completed files.

If an access token is set, use the login cookie or `Authorization: Bearer <token>`. Tokens in URLs are not supported. Health and auth-status/login are public; media, API mutations and downloads are protected. HTTP Range is supported by FileResponse for playback. Public static assets contain no credentials.
