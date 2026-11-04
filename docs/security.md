# Security

This document covers the threat model, the controls that exist in the code today (with file references), known gaps, and how to rotate credentials. To report a vulnerability, follow [SECURITY.md](../SECURITY.md).

## Threat model summary

| Asset | Threats | Main controls |
| --- | --- | --- |
| Meeting audio and transcripts | Access by other users or the public, leaks through logs or storage | Per-account ownership checks, unguessable IDs, private object storage, guest data deleted after processing, generic errors in production |
| Accounts and sessions | Credential stuffing, token theft, account sharing | PBKDF2 hashes, random 256-bit tokens with expiry, login throttling, monthly network limit |
| Payments and plan state | Forged payment notifications, client-side plan tampering | HMAC-verified Bold webhooks, server-side pricing and plan resolution |
| Webhooks (Recall, Resend, Telegram) | Forged events triggering bots or account changes | Svix signatures with timestamp tolerance, Telegram secret token |
| MCP / OAuth | Malicious clients, code interception, DNS rebinding | PKCE S256 required, single-use short-lived codes, refresh rotation, hashed tokens, Origin allow-list, read-only scope |
| Inbound invitations | Spoofed emails scheduling bots on someone's account | Sender or organizer must own the account, SPF/DKIM check |
| Origin server | Bypassing the CDN, IP spoofing for rate limits and guest quotas | Cloudflare-only ingress, `CF-Connecting-IP` trusted only from Cloudflare ranges |
| Third-party secrets | Exposure in the repo, the browser or logs | Environment-only configuration, server-side keys, placeholder `.env.example`, secret scanning in CI |

Out of scope by design: Apex Vox processes audio through third parties (Groq, Deepgram, Recall.ai), so their handling of data is governed by their own terms.

## Controls in the code

### Authentication and sessions

- **Passwords:** PBKDF2-HMAC-SHA256, 310,000 iterations, 16-byte random salt per user, stored as `pbkdf2_sha256$iterations$salt$hash`. Verification uses `hmac.compare_digest`. Accounts with the legacy unsalted SHA-256 hash are migrated to PBKDF2 on their next login. Minimum length is 8. (`app/services/supabase_service.py`)
- **Session tokens:** `apx_` + `secrets.token_urlsafe(32)`, expiring after `SESSION_TTL_DAYS`, sent as `Authorization: Bearer`. They are revoked on logout, and all of them are revoked on password reset or account deletion. A user id is never accepted as a credential (`get_user_by_token`).
- **Google / GitHub:** Supabase Auth with PKCE. The verifier is kept in an HttpOnly, `SameSite=Lax` cookie scoped to `/api/auth/oauth` (secure when the callback is https). The browser receives only a single-use handoff code valid for 120 s. (`routes_auth.py`, `oauth_service.py`)
- **Password reset:** single-use token valid 60 min, stored as an HMAC. The endpoint always answers `sent_if_exists`, so it cannot be used to tell whether an account exists.
- **Account sharing guard:** an account can be used from at most `MAX_IPS_PER_MONTH` distinct networks per month. Only an HMAC of each IP is stored. (`deps.enforce_ip_limit`)

### Authorization and ownership

- Identity, plan and provider API keys come from the server: `POST /api/transcribe` overwrites `user_id`, `guest_key`, `api_key` and `deepgram_api_key` from the request body.
- Upload sessions are owned by the account id, or by a guest key (an HMAC of the client IP). Reordering, deleting tracks and starting a transcription check ownership.
- Apex Box sessions return 404 to anyone but the owner (`routes_box._owned_session`). Meeting bots can only be cancelled by their owner.
- Voice profiles are filtered by `owner_id`. MCP tools see only the authorized account's transcription index.
- Plan gates: Apex Summa minutes and calendar export (402), meeting bot, Telegram linking and the MCP summary tools require Apex Pro.
- Admin endpoints (`/api/metrics/*`, `/api/telegram/setup`, detailed `/api/health`) need `X-Admin-Key` compared in constant time. They return 404 when the key is missing or wrong, so they are not discoverable.

### Rate limits and throttling

The in-process sliding window (`deps.throttle`) returns 429:

| Key | Limit |
| --- | --- |
| Login per IP | 20 per 15 min |
| Password forgot per IP / per email | 5 per hour / 1 per minute |
| Password reset per IP | 10 per hour |
| Newsletter per IP / per email | 5 per hour / 1 per 2 min |
| Meeting bot per account | 10 per hour |
| OAuth client registration per IP | 20 per hour |
| OAuth token per IP | 60 per 10 min |
| MCP calls per account | 120 per minute |

Guests are also limited by daily audio count and duration. Counters live in memory, so they reset on restart and are not shared between processes. Add edge rate limiting (Cloudflare) on top.

### Webhook signature verification

| Webhook | Scheme | Code |
| --- | --- | --- |
| Bold | `x-bold-signature` = hex(HMAC-SHA256(secret, base64(raw body))), constant-time compare. In production an unset secret rejects everything (sandbox empty-key mode is allowed only in development). Payments are activated once per reference. | `bold_service.verify_bold_webhook_signature` |
| Recall.ai | Svix: base64(HMAC-SHA256(key, `id.timestamp.body`)) against every `v1,` signature, ±300 s timestamp tolerance, `whsec_` secrets decoded. An empty secret rejects everything. | `recall_service.verify_svix` |
| Resend Inbound | Same Svix check with `RESEND_INBOUND_WEBHOOK_SECRET`. Emails failing both SPF and DKIM are dropped, and an event is accepted only for an account whose email is the sender or the organizer. | `routes_meetings.resend_inbound`, `calendar_invites` |
| Telegram | `X-Telegram-Bot-Api-Secret-Token` compared in constant time. The secret is derived via HMAC from `APP_SECRET_KEY` and the bot token, or set explicitly. Unlinked chats are ignored, and linking needs a single-use code valid 10 min. | `telegram_service.verify_webhook` |

### MCP and OAuth 2.1

- PKCE `S256` is mandatory, and `code_verifier` must be 43-128 characters. Authorization codes are single-use, last 5 minutes, and are bound to the client, the redirect URI and the challenge.
- Redirect URIs must be registered exactly. Only https, or http on loopback, is accepted, and fragments are rejected.
- Access tokens last 1 hour and refresh tokens 30 days. Refresh tokens rotate on every use. Codes and tokens are stored only as HMAC-SHA256 digests.
- **Origin check:** `POST /mcp` rejects requests whose `Origin` is not `https://claude.ai`, `https://chatgpt.com`, `https://chat.openai.com` or the app origin (DNS-rebinding protection). Requests without `Origin` pass.
- Scope `meetings:read` only. The tools cannot write, delete, record or pay.
- Consent requires an existing web session. The decision endpoint re-validates every parameter. (`mcp_oauth.py`, `routes_mcp.py`)

### HTTP security headers (`app/main.py`)

Every response gets:

- `Content-Security-Policy`: `default-src 'self'`, `script-src 'self'` (no inline scripts), styles from self, inline styles and Google Fonts, `connect-src 'self'`, `frame-src`/`form-action` limited to Bold checkout, `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'`. It is skipped on `/docs`, `/redoc` and `/openapi.json`.
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Cross-Origin-Opener-Policy: same-origin-allow-popups`.
- `Permissions-Policy: camera=(), geolocation=(), microphone=(self), display-capture=(self)`.
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` when `ENABLE_HSTS=true`.

Also:

- `TrustedHostMiddleware` is active whenever `ALLOWED_HOSTS` is not `*`.
- CORS never combines credentials with a wildcard origin.
- In production the API docs are hidden and unhandled errors return a generic `Internal server error`.
- Uvicorn runs with `--no-server-header`.

### Client IP and Cloudflare

`deps.client_ip` takes the **last** `X-Forwarded-For` entry, which is the address the reverse proxy saw, because earlier entries are client-controlled. Only if that address is inside Cloudflare's published IPv4 and IPv6 ranges (hard-coded list) does it trust `CF-Connecting-IP`. The origin must accept traffic from Cloudflare only (see [deployment.md](deployment.md#reverse-proxy-traefik)). Otherwise an attacker can reach the origin directly and set arbitrary headers. The resulting IP is used for throttling, guest quotas, the promo cooldown and the network limit, and is stored only as an HMAC.

### Data handling

- Guests: uploaded files are deleted after transcription. The result stays in memory for `GUEST_RESULT_TTL_MINUTES`, then it and the merged audio are deleted. Guests get no Apex Summa report and no storage.
- Free plan: transcriptions are listed for `FREE_RETENTION_HOURS`.
- Account deletion removes the user, their sessions, transcription records, local result and audio files, voice profiles and daily usage. Payment records are kept but unlinked (`user_id = "deleted"`).
- The Supabase schema enables Row Level Security and revokes privileges from public roles. Only the service-role key, held by the server, writes. (`supabase/migrations/`)

### Secrets handling

- All credentials come from environment variables. `.env` is git- and docker-ignored, and `.env.example` contains placeholders only.
- Provider keys are used server-side only. The browser never sees the Groq, Deepgram, Bold, Recall, Resend, Supabase service-role or object-storage keys. Objects are fetched by the server, and the extension ZIP is proxied so clients never see storage URLs.
- `APP_SECRET_KEY` keys every HMAC. If it is unset, a random key is generated and stored in `outputs/.app_secret` with mode `600`.
- CI runs gitleaks on every push and pull request, and CodeQL weekly (`.github/workflows/`).

## Known gaps

These are present in the current code. Plan around them or contribute fixes.

- **Capability-style job endpoints.** `GET /api/jobs/{id}/status|result|audio|summa|export/*|calendar.ics`, `PATCH /api/jobs/{id}/speakers`, `POST /api/jobs/{id}/minutes`, `GET /api/sessions/{id}` and the track audio stream do not check the account. Their only protection is the random ID (`job_` + 16 hex characters, or 10 for Box-finalized jobs). Do not share result links you want to keep private. The plan gates still apply.
- **Throttle and state** are per process (see the scaling notes in [architecture.md](architecture.md)).
- Account deletion does not remove objects already uploaded to remote object storage.

## Rotating credentials

Rotate immediately if a secret might have leaked (committed, logged, shared), and periodically otherwise. Update `.env` (or your secret store), then restart with `docker compose up -d`.

| Secret | How to rotate | Side effects |
| --- | --- | --- |
| `APP_SECRET_KEY` | Generate a new one with `python -c "import secrets; print(secrets.token_hex(32))"` and restart. If you relied on `outputs/.app_secret`, delete that file instead. | Invalidates every MCP code and token (users reconnect), pending password-reset and newsletter links, Telegram link codes, guest keys and IP hashes (monthly network counts and promo cooldowns reset). Re-register the Telegram webhook (automatic at startup). Session tokens are **not** affected. |
| Session tokens (all users) | Remove the `tokens` map from `outputs/supabase_cloud_state.json` while the app is stopped. | Everyone signs in again. |
| `ADMIN_API_KEY` | Set a new random value and restart. | Update monitoring that calls the detailed health check. |
| `GROQ_API_KEY`, `DEEPGRAM_API_KEY` | Create a new key in the provider console, deploy it, then revoke the old one. | None. |
| `MEGA_S4_ACCESS_KEY_ID` / `MEGA_S4_SECRET_ACCESS_KEY` | Create a new access key scoped to the bucket, deploy it, then delete the old key. | None. |
| `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY` | Rotate the JWT secret or API keys in the Supabase dashboard, then update both values. | OAuth sign-ins in progress fail once. |
| `BOLD_API_KEY`, `BOLD_SECRET_KEY`, `BOLD_WEBHOOK_SECRET` | Regenerate in the Bold panel and update the values together. | Webhooks signed with the old key are rejected. Users can run `POST /api/billing/confirm` to recover a payment. |
| `RECALL_API_KEY`, `RECALL_WEBHOOK_SECRET` | Rotate in the Recall.ai dashboard (rotating the webhook endpoint secret gives a new `whsec_`). | Status events for bots in progress may be rejected during the switch. |
| `RESEND_API_KEY`, `RESEND_INBOUND_API_KEY`, `RESEND_INBOUND_WEBHOOK_SECRET` | Create new keys (sending-only for `RESEND_API_KEY`, read access for inbound), and rotate the webhook signing secret in Resend. | None. |
| `TELEGRAM_BOT_TOKEN` | `/revoke` in BotFather, set the new token, restart. The webhook is re-registered at startup. | Linked chats keep working (they are tied to the chat id). |

If a secret was committed to git, rotating it is mandatory. Rewriting history does not undo the exposure.
