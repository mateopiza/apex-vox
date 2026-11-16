# Deployment

The reference production setup is one Docker container behind Traefik, with Cloudflare in front:

```text
Browser ──HTTPS──▶ Cloudflare (proxy, WAF, rate limiting)
                       │  HTTPS (Full strict)
                       ▼
                Traefik (TLS, allow only Cloudflare IPs)
                       │  HTTP
                       ▼
          apex-vox container :8000 (Uvicorn, 1 worker)
                       │
                volumes: uploads/  outputs/
```

## Docker image

`Dockerfile` builds from `python:3.11-slim`. It:

- installs `ffmpeg` (which includes `ffprobe`) and `curl` for the healthcheck;
- installs Pango, HarfBuzz and the DejaVu fonts that WeasyPrint needs for the PDF export (without them the app runs and `/export/pdf` answers 503);
- copies the Deno binary, which yt-dlp needs to solve YouTube's JavaScript challenge (with `yt-dlp[default]`, which brings `yt-dlp-ejs`). Without it yt-dlp warns that YouTube extraction is deprecated and some formats may be missing;
- creates a non-root user whose UID/GID come from the `APP_UID`/`APP_GID` build args (default 1000);
- installs `requirements.txt` into `/opt/venv`. Pass `--build-arg INSTALL_DEV_DEPS=true` to add pytest;
- sets `ENVIRONMENT=production` by default;
- runs `uvicorn app.main:app --workers 1 --proxy-headers --forwarded-allow-ips "*" --no-server-header`;
- declares `HEALTHCHECK curl -f http://localhost:8000/api/health`.

**Run exactly one worker and one replica.** Jobs, Apex Box sessions and rate-limit counters are in process memory, and the JSON state file is only protected by an in-process lock (see [architecture.md](architecture.md#scaling-notes)).

`--forwarded-allow-ips "*"` trusts `X-Forwarded-*` from any peer. That is safe only when the container port is reachable from the proxy and nowhere else. Do not publish port 8000 to the internet.

```bash
docker build -t apex-vox:latest --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g) .
```

## Docker Compose

`docker-compose.yml` defines one `web` service:

- builds the image and runs it as `${APP_UID}:${APP_GID}`;
- publishes `${HOST_PORT:-8000}:8000` (behind a proxy, bind it to localhost or drop `ports` and use the proxy network);
- loads `.env` through `env_file` and passes the core variables explicitly;
- mounts `./uploads` and `./outputs`;
- sets `init: true`, `no-new-privileges`, JSON log rotation (10 MB × 5) and the same healthcheck as the image.

```bash
cp .env.example .env     # fill in production values, see configuration.md
docker compose up -d --build
docker compose logs -f web
```

`temp/` is not mounted: it holds scratch data only and is cleaned after each job.

## Reverse proxy (Traefik)

Apex Vox expects a proxy that terminates TLS and **appends** the peer address to `X-Forwarded-For`. The app reads the **last** entry as the proxy's view of the client (`app/api/deps.py:client_ip`). If that address is in Cloudflare's published ranges, the app uses `CF-Connecting-IP` instead.

Example labels for the `web` service (adapt the router name, host and certificate resolver):

```yaml
services:
  web:
    # ...
    labels:
      - traefik.enable=true
      - traefik.http.routers.apexvox.rule=Host(`apexvox.example.com`)
      - traefik.http.routers.apexvox.entrypoints=websecure
      - traefik.http.routers.apexvox.tls.certresolver=letsencrypt
      - traefik.http.services.apexvox.loadbalancer.server.port=8000
      # Only Cloudflare may reach the origin (keep in sync with https://www.cloudflare.com/ips/)
      - traefik.http.middlewares.apexvox-cf.ipallowlist.sourcerange=173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,141.101.64.0/18,108.162.192.0/18,190.93.240.0/20,188.114.96.0/20,197.234.240.0/22,198.41.128.0/17,162.158.0.0/15,104.16.0.0/13,104.24.0.0/14,172.64.0.0/13,131.0.72.0/22,2400:cb00::/32,2606:4700::/32,2803:f800::/32,2405:b500::/32,2405:8100::/32,2a06:98c0::/29,2c0f:f248::/32
      # The app enforces its own limits (MAX_*_MB); this also stops oversized bodies at the proxy
      - traefik.http.middlewares.apexvox-body.buffering.maxRequestBodyBytes=524288000
      - traefik.http.routers.apexvox.middlewares=apexvox-cf,apexvox-body
```

Set the app to match:

```dotenv
ENVIRONMENT=production
PUBLIC_BASE_URL=https://apexvox.example.com
ALLOWED_HOSTS=apexvox.example.com   # localhost is always allowed, for the container health check
CORS_ORIGINS=https://apexvox.example.com
ENABLE_HSTS=true
```

Other proxies (nginx, Caddy) work the same way, as long as they append the real peer to `X-Forwarded-For` and drop direct traffic that does not come from Cloudflare.

## Cloudflare in front

| Setting | Value | Why |
| --- | --- | --- |
| DNS record | Proxied (orange cloud) | Hides the origin IP. The app trusts `CF-Connecting-IP` only from Cloudflare ranges. |
| SSL/TLS mode | **Full (strict)** | Cloudflare checks the origin certificate (Let's Encrypt via Traefik, or a Cloudflare Origin CA certificate). |
| Always Use HTTPS, HSTS | On | Pair with `ENABLE_HSTS=true` at the origin. |
| WAF | Managed rules on | Generic attack filtering. |
| Rate limiting rules | e.g. `/api/auth/*`, `/api/newsletter/*`, `/oauth/*`, `/api/upload` | The app's own throttle is per process and in memory. An edge limit protects across restarts. |
| Origin firewall | Allow 80/443 only from Cloudflare IPs (Traefik `ipallowlist` above, or a host firewall) | Without it, attackers could bypass Cloudflare and spoof `CF-Connecting-IP`. |
| Upload size | Cloudflare plans cap request bodies (100 MB on Free/Pro) | Long recordings should go through Apex Box blocks rather than one large upload. |
| `CF-IPCountry` header | On (default) | Picks the default UI language when the browser asks for neither Spanish nor English. |

Do not cache `/api/*`, `/oauth/*` or `/mcp`. Static assets under `/static/` are versioned (`?v=<hash>`) and sent with long `Cache-Control` headers.

## YouTube links (residential proxy)

`POST /api/upload/url` reads YouTube videos with yt-dlp. YouTube refuses data-centre IPs, the production VPS included ("Sign in to confirm you're not a bot"; other yt-dlp clients and IPv4 were tried and fail too). Without a residential proxy, YouTube links fail in production with a 502; direct links to audio files work without it. The proxy carries only YouTube traffic.

### Local development

From a home connection YouTube usually works without a proxy: leave `URL_INGEST_PROXY` empty. The Docker image already has Deno; outside Docker, install it (`curl -fsSL https://deno.land/install.sh | sh`) so yt-dlp can solve YouTube's JavaScript challenge, and `pip install -r requirements.txt` brings `yt-dlp[default]`.

### Decodo setup

1. In the Decodo dashboard, open **Residential → Proxy setup**. Choose **Authentication: User:pass**, **Location: Random** (or the country of your users), **Session type: Sticky, 10 minutes**, **Protocol: HTTP**. Note the username and password it shows (the proxy user, not your Decodo login).
2. Build the value. Replace the session id the generator shows with `{session}`, so each pasted link gets its own sticky IP:

   ```text
   URL_INGEST_PROXY=http://user-USERNAME-session-{session}-sessionduration-10:PASSWORD@gate.decodo.com:7000
   ```

   - Keep whatever extra parts the generator adds to the username (for example `-country-co`).
   - If the password has `@`, `:`, `/` or `#`, URL-encode it (`@` → `%40`, `:` → `%3A`, `/` → `%2F`, `#` → `%23`).
   - `sessionduration-10` keeps the IP for 10 minutes, enough for one link. A link larger than what downloads in 10 minutes would change IP mid-download; raise it (up to 1440) if that happens.
   - Without `{session}` the gateway rotates on every request and YouTube refuses the audio URLs, because it ties them to the IP that read the video.
3. In Dokploy, open the **apex-vox** application → **Environment**, add `URL_INGEST_PROXY` with that value and save. Optional: `URL_INGEST_MAX_MINUTES` (default 240) and `URL_INGEST_TIMEOUT_SECONDS` (default 300) bound what one link can spend.
4. **Deploy** the application (environment changes apply only after a redeploy).

### Check it

From the server, inside the running container (reads metadata only, downloads nothing):

```bash
C=$(docker ps -q -f name=apex-vox-k7wpck | head -1)
docker exec $C python -c "
from app.services import url_ingest
info = url_ingest.youtube_info('https://www.youtube.com/watch?v=jNQXAC9IVRw', url_ingest.proxy_for_request())
print('OK', info['title'], info['duration'], 's')
"
```

`OK Me at the zoo 19 s` means the proxy works. Then paste a short video in the web app ("Paste link") and transcribe it. Errors:

| Message | Cause |
| --- | --- |
| `407 Proxy Authentication Required` | Wrong proxy user or password, or a special character not URL-encoded. |
| Still "Sign in to confirm you're not a bot" | The value did not reach the container (redeploy), or the plan is not residential. Try another location. |
| `403` while downloading the audio | The IP changed between reading and downloading: check that `{session}` is in the value. |
| Connection refused / timeout | Host or port wrong (`gate.decodo.com:7000`), or the plan has no traffic left. |

### Cost and monitoring

- YouTube audio is about 60 MB per hour of video (plus about 1-2 MB of metadata per link), so roughly 0.06 GB per hour of video. Check Decodo's current price per GB on your plan.
- Only YouTube links use traffic. Pasted links are limited to 20 per hour per account or guest, and to `URL_INGEST_MAX_MINUTES` each, checked before downloading.
- Watch usage in the Decodo dashboard and set a usage alert there. When the traffic runs out, YouTube links fail with a 502 and everything else keeps working.

### Security

- The value contains the proxy password: keep it only in Dokploy's environment. It is never logged or returned by the API, and `.env.example` holds a placeholder only.
- Rotate it from the Decodo dashboard (new password), update the variable in Dokploy and redeploy.
- The proxy is used only by yt-dlp for YouTube hosts. Direct links are fetched by the server itself with the SSRF checks in [security.md](security.md#links-fetched-by-the-server-appservicesurl_ingestpy), never through the proxy.

## Retention

The sweep starts in simulation (`RETENTION_DRY_RUN=true`). Look for `Retention sweep (dry run` in the logs, check what it would delete, and only then set `RETENTION_DRY_RUN=false`. **Deletions are permanent**, including from object storage. Expired results stop being served from the first deploy, whether or not anything is deleted.

## Postgres replica of the account state (optional)

With `STATE_BACKEND=postgres`, each save of `outputs/supabase_cloud_state.json` is also sent to Supabase, and the app restores the file from there at start-up if the volume is lost.

- **What it is:** an asynchronous copy. Reads stay local and the local file is what counts.
- **What it is not:** a move to Postgres. Losing the volume loses up to `STATE_PG_FLUSH_SECONDS` of changes, which can include a payment. It does not allow a second replica of the app, and writes cost the same. If two copies do run, the older one stops replicating and fails `/api/health`.

**This has only been tested against a fake Supabase.** Try it on a Supabase branch before production.

**Cutover**

1. Apply `supabase/migrations/20261104120000_app_state.sql`.
2. Back up `outputs/`.
3. Set a fixed `APP_SECRET_KEY` if you do not have one: the replica holds digests made with it, so restoring on a new volume without the same key signs everyone out.
4. `python scripts/import_state_to_postgres.py --dry-run` and check the counts.
5. Stop the app, and run the import without `--dry-run`.
6. Set `STATE_BACKEND=postgres` and start the app.
7. Check `/api/health` with `X-Admin-Key`: `state_replica_healthy` must be `true`.

**Rollback:** unset `STATE_BACKEND`. The local file is complete, so nothing is lost. To turn the replica on again later, repeat from step 4 with `--force`.

## Volumes and backups

Everything that matters lives in `outputs/`:

| Path | Contents | Back up |
| --- | --- | --- |
| `outputs/supabase_cloud_state.json` | Accounts, sessions, payments, OAuth clients and tokens, bots, events, transcription index | **Yes, frequently** |
| `outputs/.app_secret` | HMAC secret, if `APP_SECRET_KEY` is unset | **Yes** (or set `APP_SECRET_KEY`) |
| `outputs/voice_profiles.json` | Voice profiles | Yes |
| `outputs/*_result.json`, `outputs/*_merged.mp3` | Job results and audio | Yes (also stored in object storage when configured) |
| `outputs/mega_s4_bucket/` | The retention index, plus objects that have not reached remote storage (all of them when none is configured) | Yes |
| `temp/` | Decoded audio while a job runs (about 230 MB per hour of audio) and block files. Plan disk space for your longest recordings | No |
| `outputs/reports/` | Daily usage reports | Optional |
| `uploads/` | Audio of open upload sessions | No (transient) |

A consistent backup is easiest with the service briefly stopped, or by copying the state file atomically:

```bash
# hot copy of the state file (rewritten whole, under a lock, by the app)
docker compose exec web sh -c 'cp outputs/supabase_cloud_state.json /tmp/state.json'
docker compose cp web:/tmp/state.json ./backup/state-$(date +%F).json

# full outputs/ snapshot
tar -czf backup/outputs-$(date +%F).tgz outputs/
```

Encrypt backups at rest: the state file contains password hashes, session digests and email addresses.

## Healthcheck

- `GET /api/health` returns **200** when `uploads/`, `outputs/` and `temp/` are writable and `ffmpeg` and `ffprobe` are present, and **503** otherwise. The Docker healthcheck uses it.
- In production the public body is minimal:

  ```json
  {"status": "ok", "product": "Apex Vox", "version": "2.0.0"}
  ```

- Add `X-Admin-Key` to see which providers are configured, the storage endpoint and bucket, default models and system checks:

  ```bash
  curl -s -H "X-Admin-Key: $ADMIN_API_KEY" https://apexvox.example.com/api/health | jq
  ```

## Webhooks to configure

| Provider | URL | Secret / auth | Events |
| --- | --- | --- | --- |
| Bold | `https://<host>/api/billing/bold/webhook` | `BOLD_WEBHOOK_SECRET` (or `BOLD_SECRET_KEY`). Header `x-bold-signature` = hex HMAC-SHA256 of the base64 body | `SALE_APPROVED` (others are ignored) |
| Recall.ai | `https://<host>/api/recall/webhook` | `RECALL_WEBHOOK_SECRET` (`whsec_...`, Svix) | Bot status changes, including `bot.done` |
| Resend (inbound) | `https://<host>/api/inbound/resend` | `RESEND_INBOUND_WEBHOOK_SECRET` (`whsec_...`, Svix) | `email.received`. Also configure an inbound domain or address that matches `INVITES_ADDRESS` |
| Telegram | `https://<host>/api/telegram/webhook` | Secret token derived from `APP_SECRET_KEY` and the bot token (or `TELEGRAM_WEBHOOK_SECRET`) | Registered automatically at startup when `TELEGRAM_BOT_TOKEN` and `PUBLIC_BASE_URL` are set. Re-register with `POST /api/telegram/setup` (admin) |

Also configure these provider-side settings:

- **Supabase Auth:** enable Google and/or GitHub, and add `https://<host>/api/auth/oauth/callback` to the allowed redirect URLs. Apply `supabase/migrations/*.sql` if you use table sync.
- **Resend:** verify the sending domain used in `EMAIL_FROM`, and create the newsletter segment and topic (`RESEND_NEWSLETTER_*`).
- **Bold:** payment links send the payer back to `https://<host>/?billing=return`. Bold requires https. Without an https `PUBLIC_BASE_URL` the code falls back to the original deployment's URL.

## Release checklist

1. `python -m pytest -q` passes, and CI is green.
2. Bump `APP_VERSION` in `app/config.py` and, if the extension changed, `version` in `extension/manifest.json`.
3. Back up `outputs/`.
4. `docker compose up -d --build`, then watch `docker compose logs -f web`.
5. `curl -f https://<host>/api/health`.
