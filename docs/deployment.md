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

## Retention

The sweep starts in simulation (`RETENTION_DRY_RUN=true`). Look for `Retention sweep (dry run` in the logs, check what it would delete, and only then set `RETENTION_DRY_RUN=false`. **Deletions are permanent**, including from object storage. Expired results stop being served from the first deploy, whether or not anything is deleted.

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

Encrypt backups at rest: the state file contains password hashes, session tokens and email addresses.

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
