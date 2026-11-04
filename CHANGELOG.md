# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The app version is `APP_VERSION` in `app/config.py`. The Chrome extension has its own version in `extension/manifest.json`.

## [Unreleased]

Preparation of the public open-source release.

### Added

- **Retention sweep.** Deletes expired results from the bucket, disk and Supabase, original uploads after `JOB_RETENTION_HOURS`, and files left by restarts, keeping usage totals in an aggregate ledger. It starts in simulation (`RETENTION_DRY_RUN=true`): see `docs/deployment.md`.
- **Browser end-to-end suite (`tests/e2e/`, Playwright + real uvicorn server)** covering landing and languages, layout at 390/768/1440 px, guest transcription, sign-up → upload → transcribe → rename → all exports → history → logout, wrong-password login and cross-account job isolation. It is hermetic (outbound requests from the server fail the test) and runs in a new `e2e` CI job that uploads screenshots and traces on failure.
- **Recorded calls with a masked number (Twilio, Apex Pro).** Phone verification by SMS code (Twilio Verify); bridge calls that ring the verified phone first, ask to press 1 and dial the contact from `TWILIO_CALLER_ID`, so the contact never sees the user's number; recording notice to both parties; dual-channel recording with speakers labelled by channel; live notes during the call placed on the timeline; summary, minutes and email when ready; recordings deleted from Twilio after processing. Web card in "Record", `/api/phone*`, `/api/calls*` and signed `/api/twilio/*` webhooks.
- **MCP connector:** `find_meeting` identifies a meeting from a natural-language description (relative dates in Spanish and English, participants, contact number, source, topics); `list_meetings` filters by date, source, speaker and title; new `get_meeting_details`, `get_meeting_notes` (with transcript context), `get_meeting_minutes`, `list_upcoming_meetings` and `list_phone_calls`; `search_meetings` ignores accents, matches all words and searches live notes; transcript filters by speaker and time range; `meeting_id` accepts `latest`.
- Transcription records carry their source (`upload`, `box`, `meeting_bot`, `phone_call`) and speakers.

- MIT license, README, contributing guide, code of conduct, security policy, support guide and this changelog.
- Documentation under `docs/`: architecture, configuration, HTTP API, deployment, MCP connector, Chrome extension and security.
- CI workflow (tests with FFmpeg, ruff syntax check, `node --check`, Docker build), weekly CodeQL, gitleaks secret scanning, Dependabot, issue and PR templates, CODEOWNERS, `.editorconfig` and `.gitattributes`.
- SEO: language-specific title, description, Open Graph and Twitter tags (`?lang=es|en`), `hreflang` and canonical links, JSON-LD, and `/sitemap.xml` referenced from `robots.txt`.

### Changed

- Long audio is transcribed faster: up to `GROQ_PARALLEL_CHUNKS` chunks are sent at once and assembled in order. Set it to `1` to keep the text of the previous chunk as context.
- The web interface is fully translated into Spanish and English. The default language follows the device, then the visitor's country. The plan card adapts to the device.
- The Chrome extension (manifest, recorder and badge) and the OAuth consent page are available in Spanish and English.

### Fixed

- Apex Summa reads the whole meeting. It only saw the first 10,000 characters (some 10-15 minutes of speech) and missed Apex Box notes. Long meetings are now summarized in parts and combined, and failures are logged instead of silently falling back; `analysis_source` says how each report was made.
- The report is generated once per language and kept: minutes, calendar and screen agree, no LLM call is paid for twice, and renaming speakers keeps the analysis and the live notes, which were being lost. No LLM call is made for a locked report. Without active Apex Pro, the result and report show the preview, also for reports saved earlier.
- Expired results stop being served, with 410 on the result, exports, calendar and audio, including through download links. The 24-hour limit only hid them from the history before. When Pro lapses, files get a grace period (`RETENTION_PRO_LAPSE_GRACE_DAYS`) and then Free retention; paying keeps them.
- Large audio reaches object storage: uploads are streamed with retries instead of read fully into memory, and failures can be retried later and are counted in the admin health check. Apex Box recordings now upload their audio, which was recorded as stored but never sent. Objects that reached the bucket are no longer kept twice on local disk.
- Long audio no longer needs gigabytes of RAM. A job decoded the whole recording up to four times into memory (about 230 MB per hour each) with a 60 s limit that could fail it; it now decodes once to a temporary file under `temp/`, and estimating the number of speakers no longer grows with the square of the segments.
- Groq and Deepgram calls no longer retry requests that cannot succeed (such as a bad key), respect `Retry-After`, and no longer multiply retries with the SDK's own. Deepgram response text stays out of error messages.
- Job status survives a restart: finished jobs keep answering, and jobs a restart interrupted fail with a clear message and give back their quota, instead of vanishing. Calls and meeting bots being processed are retried up to 3 times at start-up, and a repeated `bot.done` webhook no longer processes a recording twice.
- Recordings processed at once are limited by `JOB_CONCURRENCY`, jobs fail after `JOB_TIMEOUT_SECONDS`, and finished results, job statuses, Box sessions and rate-limit entries are freed from memory.
- The documented `ALLOWED_HOSTS` value no longer makes the container health check fail: `localhost` and `127.0.0.1` are always allowed. Production logs a warning while `ALLOWED_HOSTS` or `CORS_ORIGINS` are `*`.
- API errors no longer show messages wrapped in stray quotes.
- One slow request no longer freezes the whole server. Upload, Apex Box, login, minutes, webhooks and other routes ran ffmpeg, Groq calls, password hashing or file reads on the only event loop. They now run in worker threads, with long work limited by `HEAVY_ROUTE_CONCURRENCY`.
- A failed transcription gives back the plan or guest quota it used, on the day it was charged. An Apex Box block with no real transcript is not charged. A failed guest job no longer leaves its audio on disk.
- Apex Box: free accounts get the Summa preview and no minutes, as on normal uploads and as documented; finalizing twice returns the same result; a failed finalize can be retried instead of staying stuck; blocks and status changes are refused once a recording is closed; audio and transcript follow the timeline even when blocks finish out of order.
- Authenticated requests no longer reparse the whole accounts file (about 100 ms per parse at 10k accounts): read paths share a snapshot that is reparsed only when the file changes. Password hashing and the Supabase Auth call no longer run under the global state lock.
- State files (accounts, storage index, voice profiles, results) are replaced atomically. A damaged or missing accounts file now returns 503 and fails `/api/health` instead of being read as empty, which let the next save erase every account. A damaged storage index or voice-profile file is never overwritten.
- The test suite no longer writes to the real `uploads/` and `outputs/` directories and refuses outbound network. The CI JavaScript check now fails on a syntax error in any file, not only the last one, and covers nested extension files.
- `.env` loading no longer searches parent directories (a git worktree picked up the outer checkout's production keys), and the test suite never loads `.env` (`APEX_VOX_SKIP_DOTENV=1`): local test runs were writing test accounts and transcripts to the real Supabase and MEGA S4 and calling Deepgram.
- Supabase sync of `transcriptions` sends only the columns in `supabase/schema.sql` (PostgREST rejected the extra `title` field).
- Deleting an account also removes its meeting bots, calendar events and phone calls.
- Web recorder ("Record"): the block timer, progress bar, counters, live transcript, block list, notes and alerts were wired to element ids that no longer existed after the redesign. They now update while recording.
- Web recorder on phones: blocks are recorded one after another with a single `MediaRecorder` (iPhone does not allow two on the same microphone). Block rotation follows the real clock, so a block still closes after the phone froze timers. The screen wake lock and the audio context are requested on the tap itself. When the system cuts off the microphone (screen locked, another app, a call), the recorded audio is saved as a block and recording pauses, with a warning and a "Continue recording" button that resumes the same meeting. On iPhone, MP4 audio is preferred.

### Security

- Deleting an account now reaches everything: objects in the bucket, the local mirror, Supabase rows and the Auth user, OAuth tokens, hand-off and link codes, reset tokens, the newsletter entry, uploads and memory. Whatever a provider cannot confirm is retried by the sweep. A job or recording still running when its account is deleted saves nothing.
- Exception text no longer reaches clients: job status, API errors, Telegram replies, stored call and bot errors and MCP results could include server paths, ffprobe output and provider messages. They now show messages written for users, and the details go to the logs.
- Apex Box charges the plan from the measured duration of each block. Before, the client chose the charge: leaving out `duration_hint_sec` made recording free, and the hint could also shorten the timeline. A retried block is no longer charged twice. `api_key` is no longer accepted from Box clients.
- Upload limits are enforced: `MAX_FILE_SIZE_MB`, `MAX_TOTAL_UPLOAD_SIZE_MB` and `MAX_FILES_PER_UPLOAD` were never applied. New limits cover Apex Box blocks, voice samples and every other request body. Oversized requests get 413 before the body is stored, and uploads go to disk instead of memory.
- Session tokens and OAuth hand-off codes are stored as keyed digests, so the state file and its backups hold no usable session. Existing sessions are migrated at start-up and keep working. Changing `APP_SECRET_KEY` (or losing `outputs/.app_secret`) signs everyone out.
- Supabase Auth login requires a confirmed e-mail and an account linked by id. Before, signing up to Supabase with someone's address could replace the password of their local account.
- Twilio webhooks and TwiML are built only from `PUBLIC_BASE_URL` (an `https://` origin is now required to enable calls). Before, an unset `PUBLIC_BASE_URL` let a client's `Host` header point Twilio at an attacker's server that could dial any number.
- High-cost `+1` ranges (Caribbean area codes, `+1900`, `+1976`) are blocked by default (`CALL_BLOCKED_PREFIXES`) for verification SMS and calls.
- MCP: batches capped at 10 messages and 256 KB, each message counted by the rate limit, tools run outside the event loop, and `search_meetings` scans at most the 200 most recent meetings. The consent page lists calls and calendar access.
- Deleting an account hangs up its active calls, and a call still being processed is discarded if the account no longer exists. `record_extra` can no longer override owner fields of a transcription record.
- Code scanning: the origin taken from the `Host` header is validated (reflected XSS in legal pages and SEO tags), the admin report endpoint no longer accepts a destination URL or bot token (SSRF), error details are no longer returned to clients, client-supplied values are cleaned before logging, email subjects are no longer logged, Recall paths and region are validated, meeting platforms are detected by hostname, the newsletter email check cannot backtrack (ReDoS), and the extension only accepts `https://` (or local `http://`) server URLs.
- `.env.example` now contains placeholder values only.
- Transcription jobs can only be read or changed by their owner (account, or visitor by network). Audio, exports, `.ics` files and upload previews accept a signed read-only token (`?t=`) that expires after 6 hours and is only given to the owner.

## [2.0.0] - 2026-11-02

First production release of the Apex Vox suite.

### Added

- **Transcription core:** multi-file upload and ordering, silence-aware chunking under Groq's 25 MB limit on one global timeline, Groq Whisper transcription, and the `Mc-Ayrton`, `Mc-Lewis`, `Mc-Norris` and `Mc-Piastri` diarization presets (optional Deepgram, local voiceprints, LLM attribution). Also hallucination filtering, speaker renaming, voice profiles, and export to TXT, SRT, VTT, JSON, CSV and Markdown.
- **Apex Summa:** who spoke most, topics, objectives, callouts, calendar tasks with `.ics` export, charts, and minutes in five templates (ES/EN).
- **Apex Box:** 3-minute block recording with incremental transcription and live timestamped notes, in the web app and in a Chrome MV3 extension. The extension records from a pinned tab, signs in through a session bridge, captures the meeting tab with `tabCapture`, and connects to the cloud server by default. It has live sound waves and a no-sound warning. The extension ZIP is served from object storage.
- **Accounts:** email and password sign-up and sign-in, Google and GitHub sign-in through Supabase (PKCE), password reset, account deletion, a monthly network limit per account, and guest mode with daily limits and results that are not kept.
- **Billing:** Apex Pro for USD 10 per 30 days through Bold payment links, renewed by hand. A 20% welcome promo applies within 24 hours of sign-up, once per network every 90 days. Signed Bold webhooks plus on-demand link confirmation. Promo, renewal and expiry reminder emails.
- **Email (Resend):** welcome, receipt, password reset and meeting-ready emails, and a double opt-in newsletter.
- **Telegram bot:** link one chat per Apex Pro account and transcribe voice notes. Daily usage report.
- **Meeting bot (Recall.ai)** for Zoom, Google Meet, Microsoft Teams and Webex, and **calendar invitations by email** (Resend Inbound) that schedule the bot automatically.
- **MCP connector** for ChatGPT and Claude: OAuth 2.1 with PKCE and dynamic client registration, and five read-only tools.
- **Installable web app (PWA)**, legal pages (terms, Habeas Data, privacy, security) and `/.well-known/security.txt`.
- **Supabase** schema and hardening migration (Row Level Security, revoked public privileges), plus branded Auth email templates.
- **Groq Web design system** (tokens and components) and brand assets.

### Changed

- The 3-day free trial was removed (`POST /api/billing/subscribe` returns 410). Apex Pro is activated only by payment.
- User-facing texts were simplified ("Studio", "Record"), and the storage provider is no longer named in the UI.
- The meeting-invitation address stays hidden until inbound email is configured. Inbound email reading uses a dedicated Resend key (`RESEND_INBOUND_API_KEY`).
- The language is chosen in the account settings and no longer in the header.

### Security

- Bold webhook signatures are verified before any upgrade. Webhooks are rejected in production when no secret is configured.
- Hardening: PBKDF2 password hashing, expiring session tokens, ownership checks on sessions and Box recordings, throttling of sensitive endpoints, security headers (CSP, HSTS, X-Frame-Options and more), trusted hosts, generic production errors, and a minimal public health check.
- The real client IP is taken from `CF-Connecting-IP` only when the request comes from Cloudflare ranges.
- Apex Box recording requires a signed-in session.

[Unreleased]: https://github.com/mateopiza/apex-vox/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/mateopiza/apex-vox/releases/tag/v2.0.0
