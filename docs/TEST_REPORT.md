> Historical report. For the 17 November content workflows, see [current verification](CONTENT_VERIFICATION.md).

# Pre-repository test report

All four requested categories were executed. Final result: **58 passing tests, zero failures**. The initial new authentication tests found a real bug, which was fixed before this result.

| Category | Passed | What was exercised |
| --- | ---: | --- |
| Unit | 15 | Caption trimming/retiming and markup stripping; malformed captions; invalid trim/FPS/CRF/profile inputs; metadata limits; production-token requirements; signed-session tampering/expiry/clock skew; Unicode authentication input |
| Component | 10 | React discovery loading/empty/error/success/save; processing empty and failure states; review gating; successful and rejected workspace login; failed upload recovery |
| Use case | 1 full scenario | Fresh migrations → real server → login → six-source discovery/dedup/save → actual multipart upload → real background-worker trim/encode → reject/approve → verified MP4 and caption downloads → metadata edit invalidates approval → process restart → persistence → logout protects downloads |
| Functionality | 32 | Health/database/config; six mock adapters; failure isolation/history; source submission; upload validation/hash/dedup/path safety; authorization; real original/1080×1920/720×1280 output; portrait/silent/anamorphic video; cancellation/retry/recovery; archive; origin/auth rules; official API response contracts; Telegram success/duplicate/uncertain states; optional AI parsing/setup errors |

The full use case is one automated test with many assertions, not a claim that every possible user workflow has been exhaustively tested. Component tests use jsdom and mocked HTTP responses. Functionality tests use real SQLite and FFmpeg where applicable; social, Telegram and AI responses are controlled mocks. The use-case test runs a real subprocess HTTP server and worker with an isolated temporary database and storage, including a real process restart. It does not alter the user's saved media or contact external services.

## Defect found and fixed

Incorrect non-ASCII authentication input (for example an emoji) caused Python's string `hmac.compare_digest` to raise TypeError, producing a server error rather than rejecting authentication. Login and bearer comparisons now use UTF-8 bytes and retain constant-time comparison. Added both unit and API regression tests. Incorrect Unicode input now fails authentication normally; no token is echoed.

Test fixtures also explicitly clear external service credentials, preventing configured user accounts from accidentally affecting test behavior.

## Commands

From the repository root:

```sh
make test-unit
make test-component
make test-usecase
make test-functionality
```

The use-case test requires permission to bind a localhost port; it starts and stops its own server. No user server is required.

Also passed: Ruff static checks and the production frontend build.

Machine-readable evidence:

- `test-results-backend.xml`: 47 tests (15 unit + 32 functionality).
- `test-results-components.xml`: 10 tests.
- `test-results-usecase.xml`: 1 complete real-server scenario.

## Limits

No live external account credentials were used. Real Telegram delivery, paid AI requests, platform entitlements, Docker runtime and libass subtitle burn-in remain unverified as described in VERIFICATION.md. The earlier native browser file-chooser automation limitation is not reclassified as a successful browser-upload test. One upstream Starlette/HTTPX test-client deprecation warning remains; it does not fail the tests.

No repository was connected, no commit was made and no code was pushed. The release ZIP was regenerated to include the authentication fix, new tests and this report.


Live Watch update (November 16, 2026): 68 backend and 13 component tests passed. See [the current live-watch verification report](LIVE_WATCH_VERIFICATION.md) for coverage and external setup limits. Earlier counts above describe the prior release.
