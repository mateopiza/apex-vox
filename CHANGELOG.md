# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The app version is `APP_VERSION` in `app/config.py`. The Chrome extension has its own version in `extension/manifest.json`.

## [Unreleased]

Preparation of the public open-source release.

### Added

- MIT license, README, contributing guide, code of conduct, security policy, support guide and this changelog.
- Documentation under `docs/`: architecture, configuration, HTTP API, deployment, MCP connector, Chrome extension and security.
- CI workflow (tests with FFmpeg, ruff syntax check, `node --check`, Docker build), weekly CodeQL, gitleaks secret scanning, Dependabot, issue and PR templates, CODEOWNERS, `.editorconfig` and `.gitattributes`.
- SEO: language-specific title, description, Open Graph and Twitter tags (`?lang=es|en`), `hreflang` and canonical links, JSON-LD, and `/sitemap.xml` referenced from `robots.txt`.

### Changed

- The web interface is fully translated into Spanish and English. The default language follows the device, then the visitor's country. The plan card adapts to the device.
- The Chrome extension (manifest, recorder and badge) and the OAuth consent page are available in Spanish and English.

### Security

- `.env.example` now contains placeholder values only.

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
