# VI ClipForge 1.0

A locally runnable GTA VI research and video-production workspace. Discover metadata, collect sources, import authorized footage, produce original and vertical MP4s, review the results, and download or deliver approved assets.

## Open the installed product

Double-click **Start ClipForge.command**, or run:

```sh
cd /Users/omvednagre/Documents/ChatGPT/Clip
./scripts/start.sh
```

Open **http://127.0.0.1:8000**. The built interface and API run together; no separate frontend server is needed. Keep the terminal open; Ctrl+C stops the app safely. Database records, original files, output files and job history persist.

## Install on another machine

Requires macOS or Linux, Python 3.11+, Node 20.19+ (Node 22 recommended), and FFmpeg/FFprobe on PATH. Native Windows is not supported by the POSIX worker lock; use Docker or WSL.

```sh
./scripts/setup.sh
./scripts/start.sh
```

Setup creates a virtual environment, installs locked dependencies, builds the UI, copies `.env.example` only if `.env` is absent, and applies database migrations. FFmpeg must include H.264/AAC encoders. Subtitle burn-in additionally requires the `subtitles` filter/libass; the UI detects support.

## What works

- Six deterministic, visibly labeled demo connectors; no credentials needed.
- Official metadata adapters for YouTube, Reddit, Twitch and X when approved credentials are supplied. TikTok and Instagram are explicitly approval-gated; manual source URL submission works for all six platforms.
- Persistent discovery, duplicate detection, search history, sorting, result paging, saved library and source details.
- MP4/MOV/M4V/WebM/MKV imports with size/type/signature checks, FFprobe validation, SHA-256 deduplication, safe filenames and provenance/authorization records.
- Durable local processing queue: original aspect ratio, 1080×1920 and 720×1280 outputs; trim; 24/30/60 FPS; CRF quality; mute or normalize audio. H.264/AAC MP4 output.
- Cancellation, bounded retry attempts, interrupted-job recovery and persistent attempt history. Outputs appear only after FFprobe and full decode validation.
- Editable SRT, trimmed sidecar captions, optional libass burn-in. Optional OpenAI transcription and editable publishing-copy suggestions.
- Video previews, source-level approval/rejection, approved downloads, metadata JSON, optional Telegram delivery with history and duplicate-send protection.
- Optional single-operator access-token authentication, protected API/download routes, HTTP-only sessions, origin checks, request size limits and local rate limits.

## Try the workflow

1. Search `GTA VI` in Discovery. Demo metrics and sources are explicitly marked; their links visit platform homepages, not invented posts.
2. Save an item, or add a public source URL manually. Metadata never grants reuse permission.
3. Open **Media & processing**, upload authorized footage and describe its provenance.
4. Select the imported asset. Edit captions/copy, choose profiles and trim times, and select **Save & create outputs**.
5. Watch the queue. Open **Outputs**, play both versions and approve or reject the source. Approval applies to all outputs belonging to that source; edits/new processing reset it to pending.
6. Download approved MP4s, captions and publishing metadata. Telegram sends only when explicitly requested and configured.

The installed workspace includes a clearly named synthetic acceptance-test video and its two exports; these are generated test patterns, not gameplay or user footage.

## Configuration

Copy `.env.example` to `.env` if needed. Secrets remain on the backend; restart after changing configuration.

| Feature | Configuration |
| --- | --- |
| Demo/live discovery | `PLATFORM_MODE=mock` or `live` |
| YouTube | `YOUTUBE_API_KEY` |
| Reddit | Approved `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, identifying `REDDIT_USER_AGENT` |
| Twitch | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`; search uses game/category names |
| X | `X_BEARER_TOKEN` and an API plan permitting recent search |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Optional AI copy | `OPENAI_API_KEY`, `AI_MODEL` available to your API project |
| Optional transcription | `OPENAI_API_KEY`; default `TRANSCRIPTION_MODEL=whisper-1` for SRT |
| Workspace protection | `APP_ACCESS_TOKEN` (32+ characters required with `APP_ENV=production`) |

API credentials do not imply platform approval, quota or entitlement. Live accounts were not available during verification. See [integration status and official references](docs/PLATFORM_INTEGRATIONS.md).

## Checks

Latest pre-repository run: **58 tests passed** across unit, component, use-case and functionality categories. See [TEST_REPORT.md](docs/TEST_REPORT.md).

```sh
make test
cd backend
.venv/bin/ruff check app tests
.venv/bin/alembic check
```

With the local app running in demo mode and external services unconfigured:

```sh
backend/.venv/bin/python scripts/acceptance.py
```

This generates synthetic footage, exercises the real HTTP/worker pipeline, verifies downloaded hashes and FFprobe metadata, and leaves a named test asset in the local workspace. See [verification report](docs/VERIFICATION.md).

## Storage, operation and limitations

- Database: `backend/vi_clipforge.db`; files: `storage/`. Keep them together when backing up. Paths are relative to the backend working directory used by the launcher.
- Default binding is loopback. For public deployment, use HTTPS, a strong access token, origin restrictions and your own operational review. This is a single-operator local product, not a multi-tenant hosted service.
- One worker owns the storage lock. SQLite persists the queue; no Redis is required. Use one application process and one storage root per database. Rate limits are in-process.
- Live discovery is capped at 50 results per selected platform per search. There is no unrestricted social scraping, automatic media downloading, automatic publishing or background monitoring schedule.
- Native subtitle burn-in is disabled on this machine because its FFmpeg lacks libass. SRT sidecars work. A libass-capable FFmpeg enables the implemented burn-in path, which was not exercised on this host.
- Telegram and AI are optional outbound actions and may incur provider costs. No live messages or paid AI calls were made during verification.
- Docker Compose is supplied and its configuration validates, but a container build/run was not tested because the Docker daemon is stopped.

## Docker (optional)

```sh
docker compose up --build
```

Compose binds port 8000 to localhost, runs as an unprivileged user and stores data in a named volume. The image installs Debian FFmpeg (including libass support). The native installation is the verified delivery path.
