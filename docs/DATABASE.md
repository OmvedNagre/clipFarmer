# Database

Alembic `0001` creates platform sources, searches, discovered items and search memberships. `0002` adds media_assets, processing_jobs, video_outputs, job_events, review_actions and delivery_records. UUID primary keys, UTC datetime handling, foreign keys and relevant indexes are used throughout. SHA-256 media hashes and platform/external identifiers are unique.

Run migration commands from backend. Application startup seeds missing connectors but never creates tables implicitly. Tests use isolated databases. The database and storage root belong together: back them up while the app is stopped. Do not delete jobs/outputs independently; their audit history and file records are intentionally retained. Archive media with job history instead of deleting it. Deleting an unprocessed media record preserves the source file unless delete_file is explicitly selected in the API.

Job options snapshot captions and processing settings. Each retry adds events and increments attempt_count. A source can have multiple jobs and outputs; all share the source's review status. Delivery records retain safe errors and Telegram message IDs, never bot tokens.
