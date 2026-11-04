# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The app version is `APP_VERSION` in `app/config.py`. The Chrome extension has its own version in `extension/manifest.json`.

## [Unreleased]

Preparation of the public open-source release.

### Added

- **Browser end-to-end suite (`tests/e2e/`, Playwright + real uvicorn server)** covering landing and languages, layout at 390/768/1440 px, guest transcription, sign-up → upload → transcribe → rename → all exports → history → logout, wrong-password login and cross-account job isolation. It is hermetic (outbound requests from the server fail the test) and runs in a new `e2e` CI job that uploads screenshots and traces on failure.
- **Recorded calls with a masked number (Twilio, Apex Pro).** Phone verification by SMS code (Twilio Verify); bridge calls that ring the verified phone first, ask to press 1 and dial the contact from `TWILIO_CALLER_ID`, so the contact never sees the user's number; recording notice to both parties; dual-channel recording with speakers labelled by channel; live notes during the call placed on the timeline; summary, minutes and email when ready; recordings deleted from Twilio after processing. Web card in "Record", `/api/phone*`, `/api/calls*` and signed `/api/twilio/*` webhooks.
- **MCP connector:** `find_meeting` identifies a meeting from a natural-language description (relative dates in Spanish and English, participants, contact number, source, topics); `list_meetings` filters by date, source, speaker and title; new `get_meeting_details`, `get_meeting_notes` (with transcript context), `get_meeting_minutes`, `list_upcoming_meetings` and `list_phone_calls`; `search_meetings` ignores accents, matches all words and searches live notes; transcript filters by speaker and time range; `meeting_id` accepts `latest`.
- Transcription records carry their source (`upload`, `box`, `meeting_bot`, `phone_call`) and speakers.

- MIT license, README, contributing guide, code of conduct, security policy, support guide and this changelog.
- Documentation under `docs/`: architecture, configuration, HTTP API, deployment, MCP connector, Chrome extension and security.
- CI workflow (tests with FFmpeg, ruff syntax check, `node --check`, Docker build), weekly CodeQL, gitleaks secret scanning, Dependabot, issue and PR templates, CODEOWNERS, `.editorconfig` and `.gitattributes`.
- SEO: language-specific title, description, Open Graph and Twitter tags (`?lang=es|en`), `hreflang` and canonical links, JSON-LD, and `/sitemap.xml` referenced from `robots.txt`.

### Changed

- The web interface is fully translated into Spanish and English. The default language follows the device, then the visitor's country. The plan card adapts to the device.
- The Chrome extension (manifest, recorder and badge) and the OAuth consent page are available in Spanish and English.

### Fixed

- Authenticated requests no longer reparse the whole accounts file (about 100 ms per parse at 10k accounts): read paths share a snapshot that is reparsed only when the file changes. Password hashing and the Supabase Auth call no longer run under the global state lock.
- State files (accounts, storage index, voice profiles, results) are replaced atomically. A damaged or missing accounts file now returns 503 and fails `/api/health` instead of being read as empty, which let the next save erase every account. A damaged storage index or voice-profile file is never overwritten.
- The test suite no longer writes to the real `uploads/` and `outputs/` directories and refuses outbound network. The CI JavaScript check now fails on a syntax error in any file, not only the last one, and covers nested extension files.
- `.env` loading no longer searches parent directories (a git worktree picked up the outer checkout's production keys), and the test suite never loads `.env` (`APEX_VOX_SKIP_DOTENV=1`): local test runs were writing test accounts and transcripts to the real Supabase and MEGA S4 and calling Deepgram.
- Supabase sync of `transcriptions` sends only the columns in `supabase/schema.sql` (PostgREST rejected the extra `title` field).
- Deleting an account also removes its meeting bots, calendar events and phone calls.
- Web recorder ("Record"): the block timer, progress bar, counters, live transcript, block list, notes and alerts were wired to element ids that no longer existed after the redesign. They now update while recording.
- Web recorder on phones: blocks are recorded one after another with a single `MediaRecorder` (iPhone does not allow two on the same microphone). Block rotation follows the real clock, so a block still closes after the phone froze timers. The screen wake lock and the audio context are requested on the tap itself. When the system cuts off the microphone (screen locked, another app, a call), the recorded audio is saved as a block and recording pauses, with a warning and a "Continue recording" button that resumes the same meeting. On iPhone, MP4 audio is preferred.

### Security

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
