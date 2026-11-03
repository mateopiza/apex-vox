# Contributing to Apex Vox

Thanks for your interest in improving Apex Vox. This guide covers local setup, the pull request workflow and the conventions the code follows. By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

Requirements: Python 3.11, `ffmpeg` and `ffprobe` on your `PATH`, and Git. Node.js 20 is optional (CI uses it to syntax-check the JavaScript).

```bash
git clone https://github.com/mateopiza/apex-vox.git
cd apex-vox

# uv (recommended) or plain venv + pip
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -r requirements-dev.txt
#   python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt

cp .env.example .env          # ENVIRONMENT=development; add a GROQ_API_KEY to transcribe for real
uvicorn app.main:app --reload --port 8000
```

- Open <http://localhost:8000>. API docs are at <http://localhost:8000/docs> in development.
- Every integration except Groq is optional. Without its keys, a feature is disabled or falls back to local behaviour (see [docs/configuration.md](docs/configuration.md)).
- Runtime data is written to `uploads/`, `outputs/` and `temp/`, which are git-ignored. Delete `outputs/supabase_cloud_state.json` to reset local accounts.
- To work on the Chrome extension, load `extension/` unpacked (see [docs/extension.md](docs/extension.md)). It talks to `http://localhost:8000` once you set that as its server.

## Running checks

```bash
python -m pytest -q                                           # full test suite (needs ffmpeg/ffprobe)
python -m pytest tests/test_mcp_oauth.py -q                   # a single file
pip install ruff && ruff check app tests --select E9,F63,F7,F82   # same lint as CI
for f in app/static/js/*.js extension/*.js extension/**/*.js; do node --check "$f"; done
docker build -t apex-vox:dev .                                # image builds

# Browser end-to-end journeys (real server + Chromium); they skip themselves without Playwright
pip install -r requirements-e2e.txt && python -m playwright install chromium
python -m pytest tests/e2e -q                                 # E2E_HEADED=1 to watch the browser
```

External services are mocked in the tests, so you need no real keys. `tests/conftest.py` forces `ENVIRONMENT=development`, sets a placeholder Groq key and sets `APEX_VOX_SKIP_DOTENV=1`, so your `.env` (and its production keys) is never loaded during a test run.

The browser suite in `tests/e2e/` starts the real app with uvicorn on a free port and drives the web UI in Chromium: landing and languages, layout at phone/tablet/desktop widths, guest transcription, sign-up → upload → transcribe → rename speakers → every export → history → logout, wrong-password login, and that one account can never open another account's jobs. Only the Groq transcription is faked; any outbound request from the server to an external host, any console error, uncaught exception or CSP violation fails the test. On failure, a screenshot and a Playwright trace land in `test-results/e2e/` (`python -m playwright show-trace <file>.zip`).

## Branches and pull requests

1. Fork the repository, or create a branch if you have write access. Never commit straight to `main`.
2. Name the branch after the change, for example `feat/box-pause-button`, `fix/srt-timestamps` or `docs/mcp-chatgpt`.
3. Keep each pull request focused on one change. Open it against `main` and fill in the [PR template](.github/PULL_REQUEST_TEMPLATE.md).
4. CI must pass: tests, ruff, JavaScript syntax and the Docker build.
5. A maintainer reviews it. [`.github/CODEOWNERS`](.github/CODEOWNERS) requests the review automatically, and security-sensitive files (auth helpers, OAuth, payments, CI) get extra scrutiny.
6. Use **squash merge** unless the commits are already clean and meaningful.

For larger changes (new integrations, storage or auth changes, UI redesigns), open an issue or a discussion first so we can agree on the approach.

## Code style

**Python**
- Python 3.11, `from __future__ import annotations`, type hints on public functions.
- 4-space indentation, lines up to 120 characters (see `.editorconfig`).
- Routers stay thin. Put logic in `app/services/`, request and response models in `app/models/schemas.py`, and settings in `app/config.py` (and add them to `.env.example` and `docs/configuration.md`).
- Never trust identity, plan or provider keys from the request. Resolve them from the session (`app/api/deps.py`).
- Use `hmac.compare_digest` for secret comparisons, and `secrets` for tokens.
- Keep a single-worker design in mind: shared state goes through `supabase_service` under its lock.

**JavaScript, HTML and CSS**
- Plain browser JavaScript, no build step and no frameworks. It must pass `node --check`.
- No inline `<script>` or `on*=` handlers: the Content-Security-Policy is `script-src 'self'`.
- Use the design tokens in `app/static/css/tokens.css`. No emojis in the UI, and every interactive element needs a visible focus style.

**Text and i18n**
- Every user-facing string ships in **Spanish and English** (web UI, emails, API error messages, extension).
- Keep wording plain and free of jargon.

**General**
- Never commit secrets, real tokens, personal data or real recordings. Use placeholders and the generated test fixtures.
- Update the docs (`README.md`, `docs/`, `.env.example`) when behaviour or configuration changes.

## Tests

- Add or update tests in `tests/` for every behaviour change. Bug fixes should come with a regression test.
- Generate audio with `tests/fixtures/audio_generator.py` (FFmpeg) instead of committing audio files.
- Mock network calls (Groq, Deepgram, Bold, Recall.ai, Resend, Supabase, Telegram). Tests must run offline.
- User-facing flows that change (sign-up, Studio, exports, account) need a journey in `tests/e2e/`.
- Security-sensitive code (auth, payments, webhooks, OAuth, ownership checks) needs tests for the negative cases: bad signatures, foreign IDs, expired tokens.

## Commit messages

- One logical change per commit.
- Subject line: imperative mood, at most 72 characters, no trailing period. Spanish or English is fine (the history uses both). A short area prefix helps, for example `Apex Box: retry failed blocks` or `MCP: validate redirect URIs`.
- Body (optional): explain *why*, not just what. Wrap at 72 characters. Reference issues (`Closes #123`).
- Add a `Co-Authored-By:` trailer when you pair or use an assistant.

## Reporting bugs and security issues

- Bugs and feature requests go in [GitHub issues](https://github.com/mateopiza/apex-vox/issues/new/choose) using the templates.
- Report security vulnerabilities **privately**, as described in [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
