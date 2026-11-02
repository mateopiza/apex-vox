# MCP connector (Claude and ChatGPT)

Apex Vox runs a [Model Context Protocol](https://modelcontextprotocol.io) server, so an AI assistant can list, search and read your transcribed meetings on your behalf. Access is **read-only** and is granted per account through OAuth 2.1.

- MCP endpoint: `https://<your-host>/mcp` (on the hosted service: `https://apex-vox.ialabs.app/mcp`)
- Transport: Streamable HTTP. JSON-RPC 2.0 over `POST`, with JSON responses (no SSE stream)
- Auth: OAuth 2.1 authorization code with PKCE (S256), dynamic client registration, public clients
- Scope: `meetings:read`

The MCP URL is also shown in the web app, on the account portal's **Connect with ChatGPT and Claude** card, together with the apps currently connected (`GET /api/mcp/connections`).

## Connecting from Claude

1. In Claude, open **Settings → Connectors** and choose **Add custom connector**.
2. Give it a name (for example "Apex Vox"), paste the MCP URL `https://<your-host>/mcp`, and save.
3. Click **Connect**. Claude registers itself and opens the Apex Vox consent page.
4. If you are not signed in to Apex Vox in that browser, click **Sign in to continue**, sign in, and return to the consent tab.
5. Click **Allow access**. Claude receives the tokens and lists the five tools.

Try prompts such as *"List my last Apex Vox meetings"* or *"What did we agree in yesterday's sales committee?"*.

## Connecting from ChatGPT

1. In ChatGPT, open **Settings → Apps & Connectors** and create a connector (developer mode is required for custom connectors).
2. Create a connector with the MCP server URL `https://<your-host>/mcp` and authentication **OAuth**. Leave the client ID and secret empty: dynamic registration provides them.
3. Complete the Apex Vox consent page as above.

The exact menu names change over time in both products. You need the MCP URL, OAuth authentication, and no static client credentials.

## OAuth flow

| Step | Request | Notes |
| --- | --- | --- |
| 1. Discovery | `POST /mcp` without a token | Returns `401` with `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource", scope="meetings:read"` |
| 2. Resource metadata | `GET /.well-known/oauth-protected-resource` | RFC 9728. Points to this server as the authorization server |
| 3. Server metadata | `GET /.well-known/oauth-authorization-server` | RFC 8414: `authorization_endpoint`, `token_endpoint`, `registration_endpoint`, `revocation_endpoint`. Only `S256`, only `none` client auth |
| 4. Registration | `POST /oauth/register` `{"client_name", "redirect_uris": [...]}` | RFC 7591. 1 to 10 redirect URIs, `https://` (any host) or `http://` on `localhost`/`127.0.0.1`/`::1`, no fragment. Returns `client_id` (`apx_mcp_...`), no secret. Capped at 5,000 registered clients |
| 5. Authorize | `GET /oauth/authorize?response_type=code&client_id&redirect_uri&code_challenge&code_challenge_method=S256&state&resource` | Consent page. The page uses your web session to call `POST /oauth/authorize/decision` |
| 6. Code | Redirect to `redirect_uri?code=...&state=...` | Single use, valid **5 minutes**, bound to the client, the redirect URI and the PKCE challenge |
| 7. Token | `POST /oauth/token` (form) `grant_type=authorization_code&code&client_id&redirect_uri&code_verifier` | Returns `access_token` (`apx_at_...`, **1 hour**) and `refresh_token` (`apx_rt_...`, **30 days**) |
| 8. Refresh | `POST /oauth/token` `grant_type=refresh_token&refresh_token&client_id` | **Rotation**: the old refresh token is consumed and a new pair is issued |
| 9. Call | `POST /mcp` with `Authorization: Bearer apx_at_...` | JSON-RPC requests, single or batched |

Codes and tokens are stored only as HMAC-SHA256 digests keyed with `APP_SECRET_KEY`. The `code_verifier` must be 43-128 characters.

## Tools

Every tool is annotated `readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false`. Each one sees only the transcriptions of the authorized account that are still within their retention period (24 h on the free plan). Results come back as text content plus `structuredContent`.

### `list_meetings`

- Input: `{"limit": 20}` (1-50)
- Output: `{"meetings": [{"meeting_id", "title", "date", "duration", "speakers", "dominant_speaker", "url"}]}`, newest first

### `search_meetings`

- Input: `{"query": "budget", "limit": 15}`. `query` needs at least 2 characters. `limit` is 1-50
- Output: `{"results": [{"meeting_id", "title", "timestamp", "speaker", "text"}]}`. Case-insensitive substring match over segment text

### `get_meeting_transcript`

- Input: `{"meeting_id": "job_..."}`
- Output: text with a header line, then `[HH:MM:SS] Speaker: text` per segment, cut at 60,000 characters. Structured fields: `meeting_id`, `duration`, `speakers`, `truncated`, `url`

### `get_meeting_summary` (Apex Pro)

- Input: `{"meeting_id": "job_..."}`
- Output: `executive_summary`, `dominant_speaker`, `dominant_speaker_pct`, `topics[]`, `objectives[]`, `callouts[]`, `calendar_tasks[]`, `meeting_id`

### `get_action_items` (Apex Pro)

- Input: `{"meeting_id": "job_..."}` for one meeting, or `{"limit_meetings": 5}` (1-20) for the latest meetings
- Output: `{"action_items": [{"meeting_id", "title", "assignee", "due_date", "description"}]}`

On the free plan the two Pro tools return `isError: true` with a message pointing to the upgrade page. Unknown or foreign meeting IDs return `isError: true` too, without revealing whether the meeting exists.

## Example session

```bash
TOKEN=apx_at_...   # obtained through the OAuth flow

curl -s https://<your-host>/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}'

curl -s https://<your-host>/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_meetings","arguments":{"limit":5}}}'
```

## Limits and protections

- `POST /mcp`: 120 requests per minute per account. `/oauth/token`: 60 per 10 minutes per IP. `/oauth/register`: 20 per hour per IP.
- `Origin` check against DNS rebinding: if an `Origin` header is present, it must be `https://claude.ai`, `https://chatgpt.com`, `https://chat.openai.com` or the app's own origin. Otherwise the request gets 403. Requests without `Origin` (server-to-server) are allowed.
- If the account is deleted, its tokens stop working immediately.

## Revoking access

- **From Apex Vox:** on the account portal's MCP card, click **Disconnect all apps**. This calls `DELETE /api/mcp/connections`, which removes every access and refresh token of the account, for all clients.
- **From the client:** remove the connector in Claude or ChatGPT. Well-behaved clients also call `POST /oauth/revoke` with `token=<access or refresh token>`.
- **Server-wide:** rotating `APP_SECRET_KEY` invalidates every OAuth code and token, along with other HMAC-derived values (see [security.md](security.md#rotating-credentials)).
