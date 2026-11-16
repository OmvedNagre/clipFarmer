# Architecture

The production FastAPI server serves the Vite build and `/api/v1` on one loopback address. During development Vite can proxy to FastAPI. Pydantic schemas define requests and safe public records; SQLAlchemy and Alembic own persistence.

Discovery adapters normalize metadata, without downloading platform media. Concurrent source queries isolate failures. Database uniqueness prevents duplicate platform/external IDs; search memberships retain historical result sets. Manual submissions are metadata-only and strip tracking queries.

Upload processing streams to private storage with size/type/signature checks, FFprobe metadata validation and SHA-256 deduplication. File paths are generated internally and resolved beneath the storage root. Authorization is separate from discoverability and is checked before processing/transcription/review.

A single worker thread owns an OS advisory lock. Queued/running/completed/failed/cancelled jobs live in SQLite. The worker invokes FFmpeg using argument arrays, checks cancellation and timeout, records progress/events, validates codecs/dimensions/duration, fully decodes outputs, atomically moves completed files and commits output records. A restart recovers interrupted jobs with bounded attempts. Normal shutdown retains unfinished work. Intermediate files are private; failed work never appears as a completed output.

Review is source-level. A new job or saved edits invalidates approval; downloads require approved media. Preview is allowed before review. Telegram records sending/sent/failed/unknown outcomes and does not automatically retry uncertain delivery. AI is behind an AssistanceProvider interface and only invoked on user request.

Optional access-token authentication uses a timing-safe comparison and signed 12-hour HTTP-only, SameSite=Strict sessions. Production mode requires a 32-character token and Secure cookies, hence HTTPS. Loopback development can run without authentication. This is one trusted operator, not per-user RBAC. Requests have UUIDs, safe error envelopes, size limits, configured origins and in-process rate limiting.
