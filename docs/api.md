# HTTP API reference

Base URL: your `PUBLIC_BASE_URL` (for example `https://apex-vox.ialabs.app`). JSON in, JSON out, unless noted otherwise.

In development the interactive OpenAPI docs are at `/docs` (Swagger) and `/redoc`, and the schema is at `/openapi.json`. Endpoints marked *hidden* below are left out of the OpenAPI schema.

## Authentication

| Label | Meaning |
| --- | --- |
| **Public** | No credentials. |
| **Optional** | Works as a guest, and as an account when `Authorization: Bearer apx_<token>` is sent. |
| **User** | Requires `Authorization: Bearer apx_<token>`, otherwise 401. |
| **Pro** | User on the Apex Pro plan, otherwise 402. |
| **Owner** | User who owns the resource. Someone else's resource returns 404. |
| **Admin** | Requires `X-Admin-Key: <ADMIN_API_KEY>`. Returns 404 when it is missing, wrong, or `ADMIN_API_KEY` is unset. |
| **Signed** | Webhook verified by a provider signature (see [security.md](security.md)). |
| **MCP token** | `Authorization: Bearer apx_at_<token>` issued by the OAuth flow. |
| **Capability** | No account check. Access relies on knowing an unguessable random ID (`job_<16 hex>` or a 16-hex session id). Treat these URLs as secrets. |

Session tokens come from `POST /api/auth/register`, `/login`, `/password/reset` or `/oauth/exchange` (field `access_token`). Every authenticated request also counts toward the account's monthly network limit (`MAX_IPS_PER_MONTH`). A request from one network too many gets 403.

Error bodies follow FastAPI's format, `{"detail": "..."}`. Messages are often bilingual (Spanish / English).

## UI, metadata and health (`app/main.py`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET, HEAD | `/` | Public | Web UI. Language comes from `?lang=es\|en`, `Accept-Language` or `CF-IPCountry`. Returns service metadata JSON for `?format=json` or `Accept: application/json`. |
| GET | `/legal/{slug}` | Public | `terminos`, `habeas-data`, `privacidad`, `seguridad` (`?lang=es\|en`). *Hidden.* |
| GET | `/.well-known/security.txt` | Public | RFC 9116 contact file. *Hidden.* |
| GET | `/manifest.webmanifest`, `/sw.js` | Public | PWA manifest and minimal service worker. *Hidden.* |
| GET | `/robots.txt`, `/sitemap.xml`, `/favicon.ico` | Public | Crawling and icons. *Hidden.* |
| GET | `/api/info` | Public | App name, version, docs and health URLs. |
| GET | `/api/health` | Public / Admin | 200 `ok` or 503 `degraded` (data directories writable, `ffmpeg` and `ffprobe` present). In production the public response has only `status`, `product` and `version`. With a valid `X-Admin-Key` (or outside production) it also lists configured providers, storage, models and system checks. |

## Auth, portal and quotas (`routes_auth.py`, prefix `/api`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | Public | Create an email/password account (password at least 8 characters). Returns profile and token. Sends the welcome email. |
| POST | `/api/auth/login` | Public | Sign in. Throttled to 20 attempts per 15 min per IP. |
| POST | `/api/auth/logout` | Optional | Revoke the current token. |
| GET | `/api/auth/me` | User | Profile, plan and quota. |
| PATCH | `/api/auth/me/language` | User | Set `preferred_language` (`es`/`en`), used for web, emails and the extension. |
| DELETE | `/api/auth/account` | User | Delete the account, sessions, transcription history, local result files and voice profiles. Unsubscribes from the newsletter. |
| GET | `/api/auth/security` | User | Networks used this month and the monthly limit. |
| GET | `/api/auth/config` | Optional | Public client config: enabled OAuth providers, prices, promo rules, guest limits, guest audios left, flags. |
| POST | `/api/auth/password/forgot` | Public | Email a reset link valid for 60 min. Always returns `sent_if_exists`. Throttled to 5/h per IP and 1/min per email. |
| POST | `/api/auth/password/reset` | Public | Set a new password with the token. Signs out other sessions. Throttled to 10/h per IP. |
| GET | `/api/auth/oauth/{provider}` | Public | Start Google or GitHub sign-in through Supabase (PKCE). *Hidden.* |
| GET | `/api/auth/oauth/callback` | Public | Supabase redirect target. Redirects to `/?auth_code=...`. *Hidden.* |
| POST | `/api/auth/oauth/exchange` | Public | Swap the one-time `code` (valid 120 s) for a session. |
| GET | `/api/auth/quota` | Optional | Daily quota of the account. |
| GET | `/api/portal/summary` | Optional | Portal data: profile, quota, stored objects, transcription history (last 25), product and engine catalogue. |
| POST | `/api/newsletter/subscribe` | Public | Start double opt-in. Throttled to 5/h per IP and 1 per 2 min per email. |
| GET | `/api/newsletter/confirm?token=` | Public | Confirm the subscription. Redirects to `/?newsletter=confirmed\|invalid`. *Hidden.* |
| GET | `/api/newsletter/unsubscribe?email=&token=` | Public | One-click unsubscribe (also sent in the `List-Unsubscribe` header). *Hidden.* |

## Billing (`routes_billing.py`, prefix `/api/billing`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/billing/offer` | User | The price this account would pay now: regular, or with the welcome promo, plus the reason when the promo does not apply. |
| POST | `/api/billing/checkout` | User | Create a Bold payment link (USD) for `PRO_PERIOD_DAYS`. The price is computed on the server. Returns 503 if Bold is not configured. |
| POST | `/api/billing/confirm` | User | Ask Bold for the status of this account's pending links and activate the paid ones. |
| POST | `/api/billing/bold/webhook` | Signed (`x-bold-signature`) | Bold notifications. `SALE_APPROVED` activates Apex Pro. |
| POST | `/api/billing/subscribe` | Public | Retired free trial. Always returns 410. |

## Upload and sessions (`routes_upload.py`, prefix `/api`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/upload` | Optional | Multipart `files[]` (and optional `session_id`). Probes and registers tracks in an upload session owned by the caller. Guests are limited to N audios per day of M minutes each (403/413). |
| GET | `/api/sessions/{session_id}` | Capability | Ordered track list. |
| PUT | `/api/sessions/{session_id}/order` | Owner | Body `{"file_order": ["track_...", ...]}`. |
| DELETE | `/api/sessions/{session_id}/files/{file_id}` | Owner | Remove a track. |
| GET | `/api/sessions/{session_id}/files/{file_id}/audio` | Capability | Stream one uploaded track for preview. |

Accepted extensions: `.mp3 .ogg .wav .m4a .flac .webm .mp4`.

## Transcription, Apex Summa and voice profiles (`routes_transcribe.py`, prefix `/api`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/transcribe` | Optional + session Owner | Start a job. Body: `session_id`, `diarization_engine` (`Mc-Ayrton\|Mc-Lewis\|Mc-Norris\|Mc-Piastri`), `model`, `language`, `num_speakers`, `prompt_hint`. Server-controlled fields (`user_id`, `api_key`, ...) are ignored. `?sync=true` runs inline outside production only. |
| GET | `/api/jobs/{job_id}/status` | Capability | Progress (0-100), current step, chunk counters. |
| GET | `/api/jobs/{job_id}/result` | Capability | Full result: segments, speakers, full text. Returns 202 while still running and 500 if the job failed. |
| PATCH | `/api/jobs/{job_id}/speakers` | Capability | Body `{"speaker_map": {"Hablante 1": "Ana"}}`. Renames speakers and regenerates the report. |
| GET | `/api/jobs/{job_id}/audio` | Capability | Merged MP3 of the job. |
| GET | `/api/jobs/{job_id}/summa?lang=es\|en` | Capability, account plan | Apex Summa report. Guests get 402. On the free plan the report is a locked preview. |
| POST | `/api/jobs/{job_id}/minutes` | Capability + Pro (for free-plan jobs) | Body: `template_type` (`consejo\|comite\|asamblea\|seguimiento\|ejecutiva`), `language`, `organization_name`, `meeting_title`, `custom_notes`. Returns Markdown and HTML. |
| GET | `/api/jobs/{job_id}/calendar.ics` | Capability + Pro (for free-plan jobs) | Upcoming tasks as iCalendar. |
| GET | `/api/voice-profiles` | Optional | Voice profiles of the account (empty for guests). |
| POST | `/api/voice-profiles` | User | Multipart `name`, `role`, `file` (5-30 s sample). Enrolls a voiceprint. |
| DELETE | `/api/voice-profiles/{profile_id}` | User | Delete one of the caller's profiles. |
| GET | `/api/metrics/daily?date=YYYY-MM-DD` | Admin | Usage, estimated cost and revenue. *Hidden.* |
| POST | `/api/metrics/send-report` | Admin | Save the report to `outputs/reports/` and send it to Telegram or a webhook. *Hidden.* |

## Export (`routes_export.py`, prefix `/api`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/jobs/{job_id}/export/{fmt}` | Capability | Download the transcript as `txt`, `srt`, `vtt`, `json`, `csv` or `md`. |

## Apex Box (`routes_box.py`, prefix `/api/box`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/box/optimal-config` | Public | Block size and memory estimate for `target_hours`, `bitrate_bps`, `block_seconds`. |
| POST | `/api/box/sessions` | User | Create a recording session (`title`, `mode` `presencial\|virtual`, `platform`, `meeting_url`, `block_duration_sec`, `language`, `diarization_engine`, `device_type`). Owner and plan come from the token. Free users with no quota left get 402. |
| GET | `/api/box/sessions` | User | The caller's recent sessions (up to 25). |
| GET | `/api/box/sessions/{id}` | Owner | Live state: blocks, segments, notes. |
| PATCH | `/api/box/sessions/{id}/status?status=recording\|paused` | Owner | Pause or resume. |
| POST | `/api/box/sessions/{id}/blocks` | Owner | Multipart `file`, `block_index`, `duration_hint_sec`, `transcribe_immediately`. Consumes quota (402 when exhausted) and returns the new segments. |
| POST | `/api/box/sessions/{id}/notes` | Owner | Body `{"text", "tag", "timestamp_sec", "speaker"}`. Tags: `nota, acuerdo, tarea, alerta, idea, pregunta`. |
| PUT / DELETE | `/api/box/sessions/{id}/notes/{note_id}` | Owner | Edit or delete a note. |
| POST | `/api/box/sessions/{id}/finalize` | Owner | Body `{"generate_minutes": true, "generate_minutes_template": "ejecutiva", "organization_name": ...}`. Returns `job_id`, the full result and the minutes. |
| GET | `/api/box/extension/download` | Public | The current extension ZIP (served from object storage when configured, otherwise built on the fly). |
| GET | `/api/box/extension.zip` | Public | The extension ZIP, always built on the fly. |

## Meeting bot and invitations (`routes_meetings.py`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/meetings` | User | `invites_address`, `bot_enabled`, `bot_allowed`, the caller's bots (last 20) and upcoming calendar events. |
| POST | `/api/meetings/bot` | Pro | Body `{"meeting_url", "title"}` (Zoom, Meet, Teams or Webex). Throttled to 10/h per account. |
| DELETE | `/api/meetings/bot/{bot_id}` | Owner | Cancel a scheduled bot or remove it from the call. |
| POST | `/api/recall/webhook` | Signed (Svix) | Recall.ai bot status events. `bot.done` starts processing. *Hidden.* |
| POST | `/api/inbound/resend` | Signed (Svix) | Resend `email.received` events. The email's `.ics` is processed in the background. *Hidden.* |

## Telegram (`routes_telegram.py`, prefix `/api/telegram`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/telegram/webhook` | Signed (`X-Telegram-Bot-Api-Secret-Token`) | Bot updates. *Hidden.* |
| GET | `/api/telegram/link` | User | Link status of the account. |
| POST | `/api/telegram/link-code` | User (Pro) | One-time code (10 min) to send as `/start <code>`. 403 on the free plan or when a chat is already linked. |
| DELETE | `/api/telegram/link` | User | Unlink the chat. |
| POST | `/api/telegram/setup` | Admin | Register the webhook with Telegram. *Hidden.* |

Bot commands: `/start <code>`, `/estado`, `/desvincular`, `/ayuda` (or `/help`). Voice notes, audio files and audio documents up to 20 MB are transcribed.

## MCP and OAuth (`routes_mcp.py`)

All hidden from OpenAPI. See [mcp.md](mcp.md) for the full flow.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/.well-known/oauth-protected-resource` (also `/mcp` suffix) | Public | RFC 9728 resource metadata (`resource`, `authorization_servers`, `scopes_supported: ["meetings:read"]`). |
| GET | `/.well-known/oauth-authorization-server` (also `/.well-known/openid-configuration`) | Public | RFC 8414 server metadata: S256 only, public clients (`token_endpoint_auth_methods_supported: ["none"]`). |
| POST | `/oauth/register` | Public | RFC 7591 dynamic client registration. Requires 1-10 `redirect_uris` (https, or http on loopback). Throttled to 20/h per IP. |
| GET | `/oauth/authorize` | Public | Consent page (ES/EN). Requires `response_type=code`, `code_challenge_method=S256` and a registered `redirect_uri`. |
| POST | `/oauth/authorize/decision` | User | Sent by the consent page with the web session. Returns `{"redirect_to": ...}` with `code` or `error=access_denied`. |
| POST | `/oauth/token` | Public client | Form-encoded. `grant_type=authorization_code` (`code`, `client_id`, `redirect_uri`, `code_verifier`) or `refresh_token`. Throttled to 60 per 10 min per IP. |
| POST | `/oauth/revoke` | Public | RFC 7009. Form field `token`. Always returns 200. |
| POST | `/mcp` | MCP token | JSON-RPC 2.0 over Streamable HTTP (JSON responses, batches allowed). Throttled to 120/min per account. Origins other than Claude, ChatGPT and the app itself get 403. |
| GET, DELETE | `/mcp` | - | 405 (only POST is supported). |
| GET | `/api/mcp/connections` | User | The MCP URL and connected apps (clients holding a live refresh token). |
| DELETE | `/api/mcp/connections` | User | Revoke every MCP token of the account. |

### MCP tools

All tools are read-only (`readOnlyHint: true`) and limited to the authenticated account's transcriptions.

| Tool | Input | Plan | Output |
| --- | --- | --- | --- |
| `list_meetings` | `limit` (1-50, default 20) | Any | `meetings[]`: `meeting_id`, `title`, `date`, `duration`, `speakers`, `dominant_speaker`, `url` |
| `search_meetings` | `query` (at least 2 characters), `limit` (1-50, default 15) | Any | `results[]`: `meeting_id`, `title`, `timestamp`, `speaker`, `text` (case-insensitive substring match) |
| `get_meeting_transcript` | `meeting_id` | Any | Text `[HH:MM:SS] Speaker: text` (cut at 60,000 characters) plus `duration`, `speakers`, `truncated`, `url` |
| `get_meeting_summary` | `meeting_id` | Apex Pro | `executive_summary`, `dominant_speaker`, `dominant_speaker_pct`, `topics`, `objectives`, `callouts`, `calendar_tasks` |
| `get_action_items` | `meeting_id` (optional), `limit_meetings` (1-20, default 5) | Apex Pro | `action_items[]`: `meeting_id`, `title`, `assignee`, `due_date`, `description` |

Supported JSON-RPC methods: `initialize` (protocol versions `2025-06-18`, `2025-03-26`, `2024-11-05`), `ping`, `tools/list`, `tools/call`, `resources/list` and `prompts/list` (both empty). Notifications get `202`.
