# Development and operation

## Local development

Run `make backend` and `make frontend` in separate terminals. Run backend commands from backend; npm commands use --prefix frontend from the root. Use `./scripts/start.sh` for the built one-server product. Python dependencies are pinned in backend/requirements.lock.txt; npm uses package-lock.json.

`make test` runs backend tests, frontend tests and the production build. Ruff: `backend/.venv/bin/ruff check backend/app backend/tests`. Alembic drift check: `cd backend && .venv/bin/alembic check`. `scripts/acceptance.py` tests the real localhost pipeline using generated video, leaves a synthetic test asset, and writes its evidence to docs/acceptance-result.json. It must not be used to send external messages.

## Operations

- Use a single API process for this local edition. Worker locking prevents simultaneous consumers for the same storage root; API rate limits remain process-local.
- Healthy API: GET /api/v1/health. More detailed checks: /system/status, /stats/processing. Job events provide persistent, safe audit messages.
- Back up the SQLite database and storage directory together while stopped. Never put storage under frontend/dist.
- A normal stop requests worker shutdown; queued inputs remain available. Interrupted running jobs are recovered with a maximum of three attempts. Permanent failures need corrected source/options; transient failures allow manual retry.
- Telegram uncertain outcomes require checking the destination before explicit resend. Never automatically retry sendVideo after a timeout.
- The service does not manage storage retention, disk quotas or multi-user permissions. Archive is non-destructive. Remove source files only with explicit operator intent.
- Local without auth: bind only 127.0.0.1. Public hosting is an operator-managed deployment: require APP_ENV=production, a strong access token, HTTPS/reverse-proxy limits, allowed origins and routine backup/update procedures. This app has no multi-tenant account system.
- FFmpeg subprocesses have timeouts and no shell interpolation. Only local file protocols are permitted for source inspection/encoding. Subtitle burn-in requires libass; otherwise use sidecar SRT.
- Secrets, databases, real uploads, virtual environments and build artifacts are ignored by Git. Release packaging intentionally excludes all local runtime data.

Docker Compose parses successfully but was not built/run on this host because the Docker daemon was unavailable. Native Python/Node/FFmpeg is the verified platform.
