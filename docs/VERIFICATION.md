# Release verification — 15 November 2026

See [the four-category test report](TEST_REPORT.md) for the latest pre-repository regression run and authentication fix.

## Verified results

- **48 backend tests passed**, including generated real FFmpeg media. One upstream Starlette deprecation warning about its HTTPX test client remains; no test failure.
- **10 frontend tests passed**: discovery states/save, production empty/failure states, review gating and authentication UI.
- **Production Vite build passed**; the built UI is served by FastAPI on one localhost address.
- **Ruff checks passed**; **pip check** found no broken dependencies; **npm audit reported 0 vulnerabilities**.
- Alembic migrations applied to the existing database. A fresh isolated database completed **upgrade → downgrade → upgrade**, and **alembic check** found no schema drift.
- Shell launch/setup scripts passed `sh -n`. Docker Compose passed `docker compose config --quiet`.

## Real HTTP acceptance

`scripts/acceptance.py` ran against the actual local server and background worker, not the test client. It:

1. Searched all six demo platforms and received six normalized results.
2. Generated and uploaded a synthetic 640×360 video with a sine-wave audio track.
3. Saved source authorization, publishing metadata and SRT captions.
4. Queued a trim from 0.5s to 2.5s with original and 1080×1920 profiles and audio normalization.
5. Waited for the actual worker to complete both outputs.
6. Approved the source and downloaded both MP4s.
7. Verified downloaded SHA-256 hashes and FFprobe metadata: H.264 video, AAC audio, exactly 2 seconds; original 640×360 and vertical 1080×1920.
8. Downloaded captions and confirmed they were shifted/clipped to 0–2 seconds.
9. Confirmed Telegram reports setup required without making an external call.

Machine-readable output: [acceptance-result.json](acceptance-result.json).

Additional real-video tests cover portrait 720×1280, silent/muted video, anamorphic source aspect preservation, timeout retry, queued cancellation and interrupted-job recovery. Import tests cover unsafe filenames, types, signatures, oversized files, hashing, duplicates and authorization. External-service contract tests cover YouTube/Reddit/Twitch/X normalization, quota errors, Telegram success/duplicate prevention/uncertain outcomes, and AI metadata parsing.

## Browser and persistence checks

The dashboard, media import controls and output/review page were inspected in the in-app browser. The vertical output played to completion. A screenshot is saved as [product-preview.png](product-preview.png). The browser's file chooser automation stalled; browser upload interaction was not verified end to end. The actual multipart upload endpoint and subsequent complete production workflow were verified through HTTP and automated tests.

The application was stopped and restarted; the acceptance job, its output files and approvals remained available. The generated fixture is labeled as a synthetic acceptance test and retained locally for inspection.

## Checks not possible here

- No live social API credentials/approvals were supplied. Four live metadata adapters have controlled-response tests; TikTok/Instagram use explicit approval states and manual-submission fallbacks.
- No Telegram delivery to a real chat or paid OpenAI call was made. Their setup states and response contracts were tested; account permissions and quotas remain unverified.
- This host's FFmpeg has no `subtitles`/libass filter. Burn-in is implemented and capability-gated, but not runtime-tested here. Edited/trimmed sidecar SRT is verified.
- Docker's daemon is stopped. Compose syntax is verified, but the image was not built/run. Native macOS Python/Node/FFmpeg is the verified release platform.
- No public deployment, multi-user isolation, stress test or uptime guarantee is claimed. This is a local single-operator product.

## Delivery

Use `Start ClipForge.command` or `./scripts/start.sh`, then open http://127.0.0.1:8000. The release ZIP includes source, dependency locks, migrations, documentation, launcher and prebuilt UI. It excludes secrets, databases, original/output media, installed dependencies and caches. SHA256SUMS.txt records the archive digest.
