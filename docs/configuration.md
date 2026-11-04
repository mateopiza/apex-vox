# Configuration

Apex Vox reads its settings from environment variables when the process starts (`app/config.py`). If a `.env` file exists in the project root it is loaded with `python-dotenv`. Variables already set in the environment take precedence over `.env`.

[`.env.example`](../.env.example) is the reference list. Copy it and fill in your own values:

```bash
cp .env.example .env
```

Notes on the columns below:

- **Default** is the value the code uses when the variable is unset. A variable that is set but empty usually counts as "disabled" (see the notes).
- **Required** is *Yes* only when the app cannot work without the variable. *Prod* means the variable is strongly recommended for any public deployment.
- `docker-compose.yml` passes some variables explicitly, with its own fallbacks (for example `ENVIRONMENT` falls back to `production` there). All other variables reach the container through `env_file: .env`.

## Core / server

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `ENVIRONMENT` | `development` | Prod | `development` or `production`. Production hides `/docs`, `/redoc` and `/openapi.json`, returns generic 500 errors, forces async jobs, trims `/api/health`, and refuses Bold webhooks when no signing secret is set. |
| `LOG_LEVEL` | `INFO` | No | Python log level (`debug`, `info`, `warning`, `error`; case-insensitive). |
| `HOST_PORT` | `8000` | No | Host port published by `docker-compose.yml`. Not read by the app. |
| `PUBLIC_BASE_URL` | empty (derived from the request) | Prod | Public origin, e.g. `https://apexvox.example.com`. Used for OAuth callbacks, the Telegram webhook, email links, MCP metadata, the PWA manifest and the sitemap. Bold callbacks require `https://`. |
| `ALLOWED_HOSTS` | `*` | Prod | Comma-separated hostnames accepted in the `Host` header (`TrustedHostMiddleware`). `*` disables the check. Never use `*` in production. |
| `CORS_ORIGINS` | `*` | Prod | Comma-separated allowed origins. With `*`, CORS credentials are disabled. |
| `ENABLE_DOCS` | empty (on in development, off in production) | No | Force the interactive API docs on (`true`) or off (`false`). |
| `ENABLE_HSTS` | `false` | Prod | Sends `Strict-Transport-Security: max-age=31536000; includeSubDomains`. Enable only when served over HTTPS. |
| `APP_SECRET_KEY` | empty (a key is generated and stored in `outputs/.app_secret`) | Prod | Server secret for HMACs: IP hashes, guest keys, OAuth codes and tokens, password-reset and Telegram link codes, and the derived Telegram webhook secret. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`. Changing it invalidates every value above. |
| `ADMIN_API_KEY` | empty (admin endpoints disabled) | Prod | Value expected in the `X-Admin-Key` header for `/api/metrics/*`, `/api/telegram/setup` and the detailed `/api/health`. Without it those endpoints return 404. |

## Transcription and diarization

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `GROQ_API_KEY` | empty | **Yes** | Groq key for Whisper and the LLM. Without it the UI loads, but `POST /api/transcribe` returns 503 (except Mc-Ayrton when `DEEPGRAM_API_KEY` is set). |
| `DEFAULT_MODEL` | `whisper-large-v3` | No | Default Groq speech model. |
| `DEFAULT_LLM_MODEL` | `llama-3.3-70b-versatile` | No | Groq LLM for diarization and Apex Summa. |
| `DEFAULT_DIARIZATION_ENGINE` | `hybrid_deepgram_groq` | No | Default engine: `hybrid_deepgram_groq` (Mc-Lewis), `deepgram` (Mc-Ayrton), `acoustic_local` (Mc-Norris), `groq_llm` (Mc-Piastri), or one of the `Mc-*` aliases. |
| `DEEPGRAM_API_KEY` | empty | No | Turns on Deepgram for Mc-Ayrton and Mc-Lewis. Without it those presets fall back to local voiceprint clustering. |

## Audio processing

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `MAX_FILE_SIZE_MB` | `100` | No | Largest file accepted by `/api/upload`. Above it the app answers 413. Also keep the limit of your proxy and Cloudflare (100 MB on its base plans) in mind. |
| `MAX_TOTAL_UPLOAD_SIZE_MB` | `500` | No | Largest request to `/api/upload`, and total size of one upload session. |
| `MAX_FILES_PER_UPLOAD` | `20` | No | Most files in one `/api/upload` request. |
| `MAX_BOX_BLOCK_MB` | `50` | No | Largest Apex Box recording block. |
| `MAX_VOICE_SAMPLE_MB` | `25` | No | Largest voice-profile sample. |
| `MAX_REQUEST_BODY_MB` | `10` | No | Largest request body on every other endpoint. |
| `HEAVY_ROUTE_CONCURRENCY` | `8` | No | Requests that may run long work (ffmpeg, Groq, an LLM) at the same time. Others wait without using a thread. |
| `JOB_CONCURRENCY` | `2` | No | Recordings processed at the same time. Others wait with status `queued`. |
| `JOB_TIMEOUT_SECONDS` | `1800` | No | A job over this time fails and gives back its quota. Measured from when it starts running, not while queued. |
| `CHUNK_DURATION_MINUTES` | `10` | No | Target chunk length. Used only if `CHUNK_TARGET_DURATION_SEC` is unset. |
| `CHUNK_MAX_BYTES` | `26214400` (25 MiB) | No | Maximum bytes per chunk sent to Groq (Groq's hard limit is 25 MB). Used only if `GROQ_PAYLOAD_LIMIT_BYTES` is unset. `.env.example` uses `25000000`. |
| `SILENCE_THRESHOLD_DB` | `-30` | No | Silence threshold for chunk splitting. Used only if `SILENCE_NOISE_THRESHOLD_DB` is unset. |
| `SILENCE_MIN_DURATION_SEC` | `0.5` | No | Minimum silence length that counts as a split point. |
| `APP_UID` / `APP_GID` | `1000` / `1000` | No | Build args and container user in Docker. Match your host `id -u` / `id -g` so bind-mounted volumes stay writable. Not read by the app. |

## Object storage (S3-compatible)

The variable names keep the `MEGA_S4_` prefix for historical reasons, but any provider that speaks SigV4 with path-style URLs (`{endpoint}/{bucket}/{key}`) works.

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `MEGA_S4_ENDPOINT_URL` | the original provider's global endpoint | No | Endpoint URL. A bare host is accepted (`https://` is added). Always set it explicitly. |
| `MEGA_S4_REGION` | `eu-central-1` | No | SigV4 region. For some provider hostnames it is derived from the endpoint automatically. Otherwise set it to match your endpoint. |
| `MEGA_S4_BUCKET_NAME` | `apex-vox-storage` | No | Bucket name. |
| `MEGA_S4_ACCESS_KEY_ID` | empty | No | Access key. Without both keys, objects are only written to the local mirror `outputs/mega_s4_bucket/`. |
| `MEGA_S4_SECRET_ACCESS_KEY` | empty | No | Secret key. |

## Supabase

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `SUPABASE_URL` | empty | No | Project URL. Needed for Google/GitHub sign-in and table sync. |
| `SUPABASE_ANON_KEY` | empty | No | Public key, used for Supabase Auth (OAuth with PKCE). The sign-in buttons appear only for providers enabled in Supabase Auth. |
| `SUPABASE_SERVICE_ROLE_KEY` | empty | No | Server-side key, used to push `profiles` and `transcriptions` rows. Never expose it to the browser. |
| `SUPABASE_DATABASE_PASSWORD` | empty | No | Not read by the app. Kept for the Supabase CLI and migrations (`supabase/`). |

## Plans and payments (Bold)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `BOLD_API_KEY` | empty | No | Bold identity key (`x-api-key`) for the payment-link API. Without it `POST /api/billing/checkout` returns 503 and `/api/auth/config` reports `billing_configured: false`. |
| `BOLD_SECRET_KEY` | empty | No | Bold secret key. Used for the integrity hash, and as the webhook signing key when `BOLD_WEBHOOK_SECRET` is empty. |
| `BOLD_WEBHOOK_SECRET` | empty | Prod (if Bold is used) | Key for verifying `x-bold-signature`. If neither this nor `BOLD_SECRET_KEY` is set, development accepts Bold's sandbox (empty-key) signatures and production rejects every webhook. |
| `FREE_DAILY_HOURS` | `2.0` | No | Free-plan audio per day, in hours. |
| `FREE_RETENTION_HOURS` | `24` | No | How long free-plan transcriptions stay listed and stored. |
| `PRO_PRICE_USD` | `10` | No | Apex Pro price per period, in USD. |
| `PRO_PERIOD_DAYS` | `30` | No | Days of Apex Pro granted per approved payment. Renewal is manual. |
| `PROMO_DISCOUNT_PCT` | `20` | No | Welcome discount on the first payment. |
| `PROMO_WINDOW_HOURS` | `24` | No | The discount applies if the account pays within this many hours of sign-up. |
| `PROMO_IP_COOLDOWN_DAYS` | `90` | No | One promo per network (hashed IP) within this many days. |
| `RENEWAL_REMINDER_DAYS` | `3` | No | Send the renewal reminder email this many days before Apex Pro expires. |

### Accounts and limits

These are commented out in `.env.example`. Uncomment them to override the defaults.

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `GUEST_MAX_AUDIOS_PER_DAY` | `3` | No | Audios per day without an account (per hashed IP). |
| `GUEST_MAX_AUDIO_MINUTES` | `30` | No | Maximum length of each guest audio. |
| `GUEST_RESULT_TTL_MINUTES` | `60` | No | Guest results are deleted from memory and disk after this time. |
| `MAX_IPS_PER_MONTH` | `3` | No | Distinct networks an account may use per calendar month. Beyond that, requests get 403. |
| `SESSION_TTL_DAYS` | `30` | No | Lifetime of `apx_...` session tokens. |

## Email (Resend)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `RESEND_API_KEY` | empty | No | Sending key. Without it no email is sent (a warning is logged at startup) and `/api/auth/config` reports `newsletter_enabled: false`. |
| `EMAIL_FROM` | `Apex Vox <hola@ialabs.app>` | Prod (if email is used) | Sender address, on a domain verified in Resend. |
| `EMAIL_REPLY_TO` | empty | No | Optional `Reply-To`. |
| `RESEND_NEWSLETTER_SEGMENT_ID` | an ID from the original deployment | No | Resend segment that confirmed subscribers are added to. **Set your own.** |
| `RESEND_NEWSLETTER_TOPIC_ID` | an ID from the original deployment | No | Resend topic for subscriptions. **Set your own.** |
| `INVITES_ADDRESS` | `agenda@apexbox.ialabs.app` when unset | No | Inbound address users invite to meetings. Set it to an empty value to hide the feature in the UI. |
| `RESEND_INBOUND_API_KEY` | empty (falls back to `RESEND_API_KEY`) | No | Resend key allowed to **read** received emails. A sending-only key cannot. |
| `RESEND_INBOUND_WEBHOOK_SECRET` | empty | Yes, for invitations | Svix signing secret (`whsec_...`) of the Resend inbound webhook. When empty, `/api/inbound/resend` rejects every request. |

## Meeting bot (Recall.ai)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `RECALL_API_KEY` | empty | No | Turns the meeting bot on (Apex Pro only). |
| `RECALL_REGION` | `us-west-2` | No | Recall.ai region, giving the API base `https://{region}.recall.ai/api/v1`. |
| `RECALL_WEBHOOK_SECRET` | empty | Yes, for the bot | Svix signing secret (`whsec_...`) of the Recall webhook endpoint. When empty, `/api/recall/webhook` rejects every request and bots never finish processing. |
| `BOT_NAME` | `Apex Vox · notas` | No | Display name of the bot in the meeting (up to 100 characters). |

## Recorded calls with a masked number (Twilio)

Apex Pro only. Calling is on when `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID`, a valid `TWILIO_CALLER_ID` **and an `https://` `PUBLIC_BASE_URL`** are set. Every Twilio URL (TwiML, status callbacks, signature check) is built only from `PUBLIC_BASE_URL`, never from the request's `Host` header, so a client cannot point Twilio at its own server and dial arbitrary numbers.

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `TWILIO_ACCOUNT_SID` | empty | Yes, for calls | Account SID (`AC...`). |
| `TWILIO_AUTH_TOKEN` | empty | Yes, for calls | Auth token. Always used to validate `X-Twilio-Signature` on webhooks, and for the REST API unless an API key is set. |
| `TWILIO_API_KEY_SID` / `TWILIO_API_KEY_SECRET` | empty | No | API key (`SK...`) used for the REST API instead of the auth token. |
| `TWILIO_VERIFY_SERVICE_SID` | empty | Yes, for calls | Verify service (`VA...`) that sends the SMS code to verify the user's phone. |
| `TWILIO_CALLER_ID` | empty | Yes, for calls | Twilio number in E.164 (`+1...`) that contacts see. The user's own number is never shown to the contact. |
| `CALL_ALLOWED_PREFIXES` | `+57,+1,+52` | No | Country prefixes allowed for the user's phone and for destinations. Also restrict Geo Permissions in the Twilio console to avoid toll fraud. |
| `CALL_BLOCKED_PREFIXES` | NANP high-cost ranges (`+1900`, `+1976`, Caribbean area codes such as `+1876`, `+1809`, `+1284`…) | No | Refused even inside an allowed prefix, for the user's phone and for destinations. Blocks the usual toll-fraud and SMS-pumping ranges inside `+1`. |
| `CALL_MAX_MINUTES` | `90` | No | Maximum length of a call. |
| `CALLS_PER_DAY` | `30` | No | Calls per account in 24 hours. |
| `CALL_RECORDING_NOTICE` | `true` | No | Both parties hear that the call is recorded. Keep it on unless you have legal advice for your jurisdiction. |
| `TWILIO_DELETE_RECORDINGS` | `true` | No | Delete the recording from Twilio once Apex Vox has copied and processed it. |
| `APP_TIMEZONE` | `America/Bogota` | No | Time zone used by the MCP tools to show dates and understand "yesterday", "on Monday"... |

## Telegram bot

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | empty | No | Bot token from BotFather. Turns on chat linking and voice-note transcription (Apex Pro). |
| `TELEGRAM_BOT_USERNAME` | empty (fetched with `getMe`) | No | Used to build the `t.me/<bot>?start=<code>` deep link. |
| `TELEGRAM_CHAT_ID` | empty | No | Chat that receives the daily usage report at 23:55 UTC-5. |

## Legal and contact

Shown on `/legal/*`, in emails and in `/.well-known/security.txt`.

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `LEGAL_ENTITY_NAME` | `IA Labs (ialabs.app)` | Prod | Data controller / operator name. **Set your own.** |
| `LEGAL_ENTITY_ID` | empty | No | Tax or ID number (shown in the Habeas Data policy when set). |
| `LEGAL_ADDRESS` | empty | No | Postal address. |
| `LEGAL_CITY` | `Colombia` | No | City or country. |
| `LEGAL_PHONE` | empty | No | Phone number. |
| `CONTACT_EMAIL` | `hola@ialabs.app` | Prod | Contact for privacy and data requests. **Set your own.** |
| `SECURITY_EMAIL` | `seguridad@ialabs.app` | Prod | Vulnerability reports (security policy and `security.txt`). **Set your own.** |

The legal texts in `app/services/legal_content.py` are written for Colombian law (Ley 1581 de 2012, Ley 1480 de 2011). If you run your own instance, review them with counsel.

## Advanced (not in `.env.example`)

These are read by the code but rarely need changing.

| Variable | Default | Description |
| --- | --- | --- |
| `TELEGRAM_WEBHOOK_SECRET` | derived from `APP_SECRET_KEY` and the bot token | Explicit secret for `X-Telegram-Bot-Api-Secret-Token`. |
| `BOLD_API_BASE_URL` | `https://integrations.api.bold.co` | Bold API base URL. |
| `STATIC_CACHE_SECONDS` | `604800` | `Cache-Control` max-age for versioned static assets (`?v=`). |
| `UPLOAD_DIR` / `OUTPUT_DIR` / `TEMP_DIR` | `uploads/`, `outputs/`, `temp/` under the project root | Data directories. |
| `GROQ_BASE_URL` | Groq SDK default | Custom Groq-compatible base URL. |
| `GROQ_TIMEOUT_SECONDS` / `GROQ_MAX_RETRIES` | `120` / `3` | Groq client timeout and retries. |
| `DEEPGRAM_MODEL` | `nova-2` | Deepgram model. |
| `FALLBACK_LLM_MODEL` | `llama-3.1-8b-instant` | LLM used when the default LLM call fails. |
| `CHUNK_TARGET_DURATION_SEC` | `600` | Takes precedence over `CHUNK_DURATION_MINUTES`. |
| `GROQ_PAYLOAD_LIMIT_BYTES` | `26214400` | Takes precedence over `CHUNK_MAX_BYTES`. |
| `SILENCE_NOISE_THRESHOLD_DB` | `-30` | Takes precedence over `SILENCE_THRESHOLD_DB`. |
| `CHUNK_SEARCH_WINDOW_SEC` / `CHUNK_MAX_SEARCH_WINDOW_SEC` | `45` / `90` | Window around the target split point searched for silence. |
| `ACOUSTIC_PAUSE_THRESHOLD_SEC` | `0.5` | Pause length used by acoustic diarization. |
| `AUDIO_SAMPLE_RATE` / `AUDIO_CHANNELS` / `AUDIO_BITRATE` / `AUDIO_OUTPUT_FORMAT` | `16000` / `1` / `64k` / `mp3` | Chunk encoding. |
| `CLEANUP_TEMP_FILES` | `true` | Delete per-job temp directories when a job finishes. |
| `COST_GROQ_WHISPER_PER_MIN_USD`, `COST_GROQ_LLM_PER_MIN_USD`, `COST_DEEPGRAM_PER_MIN_USD`, `REVENUE_PER_MIN_USD` | `0.00185`, `0.0002`, `0.0063`, `0.05` | Unit prices for the daily usage report. |
| `REPORT_WEBHOOK_URL` | empty | Extra webhook (Slack, Discord, n8n...) for the usage report. |

`DEBUG`, `HOST`, `PORT`, `JOB_RETENTION_HOURS`, `FALLBACK_MODEL` and `DIARIZATION_MAX_SPEAKERS` are defined in `Settings` but not used by any code path today.

## Minimal production `.env`

```dotenv
ENVIRONMENT=production
PUBLIC_BASE_URL=https://apexvox.example.com
ALLOWED_HOSTS=apexvox.example.com
CORS_ORIGINS=https://apexvox.example.com
ENABLE_HSTS=true
APP_SECRET_KEY=<64 hex chars>
ADMIN_API_KEY=<long random string>
GROQ_API_KEY=gsk_<your key>
MEGA_S4_ENDPOINT_URL=https://s3.<region>.<provider>.example
MEGA_S4_REGION=<region>
MEGA_S4_BUCKET_NAME=<bucket>
MEGA_S4_ACCESS_KEY_ID=<key id>
MEGA_S4_SECRET_ACCESS_KEY=<secret>
LEGAL_ENTITY_NAME=<Your Company>
CONTACT_EMAIL=<hello@your-domain>
SECURITY_EMAIL=<security@your-domain>
```
