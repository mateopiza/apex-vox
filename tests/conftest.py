"""Test configuration.

- `.env` is never loaded: a developer's real keys (Supabase, storage, Deepgram, ...) must not
  turn a test run into writes against production services. Keys exported in the shell are
  blanked for the same reason.
- `uploads/`, `outputs/` and `temp/` point at a throwaway directory, so a test run never touches
  a developer's accounts, audio or results.
- Outbound network is refused below httpx and requests (loopback and `httpx.MockTransport` pass).
- A placeholder Groq key lets the pipeline start; the Groq calls themselves are monkeypatched.
- The daily guest allowance is raised so unrelated tests sharing the TestClient IP do not
  exhaust it; tests/test_auth_billing.py patches the real limits explicitly.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import httpx
import requests

os.environ["APEX_VOX_SKIP_DOTENV"] = "1"
os.environ["ENVIRONMENT"] = "development"
os.environ["GROQ_API_KEY"] = "gsk_test_placeholder"
os.environ.setdefault("GUEST_MAX_AUDIOS_PER_DAY", "1000")
os.environ.setdefault("MAX_IPS_PER_MONTH", "1000")
os.environ.setdefault("GROQ_PARALLEL_CHUNKS", "1")  # tests/test_provider_retries.py covers parallel mode

for _name in (
    "ADMIN_API_KEY", "APP_SECRET_KEY", "BOLD_API_KEY", "BOLD_SECRET_KEY", "BOLD_WEBHOOK_SECRET", "DEEPGRAM_API_KEY",
    "MEGA_S4_ACCESS_KEY_ID", "MEGA_S4_SECRET_ACCESS_KEY", "PUBLIC_BASE_URL", "RECALL_API_KEY", "RECALL_WEBHOOK_SECRET",
    "REPORT_WEBHOOK_URL", "RESEND_API_KEY", "RESEND_INBOUND_API_KEY", "RESEND_INBOUND_WEBHOOK_SECRET",
    "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "TELEGRAM_WEBHOOK_SECRET", "TWILIO_ACCOUNT_SID", "TWILIO_API_KEY_SECRET", "TWILIO_API_KEY_SID",
    "TWILIO_AUTH_TOKEN", "TWILIO_CALLER_ID", "TWILIO_VERIFY_SERVICE_SID",
):
    os.environ[_name] = ""

# Set before anything imports `app`: the settings and service singletons read these at import.
_DATA_ROOT = Path(tempfile.mkdtemp(prefix="apex-vox-tests-"))
atexit.register(shutil.rmtree, _DATA_ROOT, ignore_errors=True)
for _name, _sub in (("UPLOAD_DIR", "uploads"), ("OUTPUT_DIR", "outputs"), ("TEMP_DIR", "temp")):
    os.environ[_name] = str(_DATA_ROOT / _sub)

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _refuse_external(url: object, error: type[Exception]) -> None:
    host = httpx.URL(str(url)).host
    if host not in _LOOPBACK:
        raise error(f"outbound network is blocked in tests: {host}")


_real_transport = httpx.HTTPTransport.handle_request
_real_async_transport = httpx.AsyncHTTPTransport.handle_async_request
_real_adapter = requests.adapters.HTTPAdapter.send


def _guarded_transport(self, request):
    _refuse_external(request.url, httpx.ConnectError)
    return _real_transport(self, request)


async def _guarded_async_transport(self, request):
    _refuse_external(request.url, httpx.ConnectError)
    return await _real_async_transport(self, request)


def _guarded_adapter(self, request, *args, **kwargs):
    _refuse_external(request.url, requests.ConnectionError)
    return _real_adapter(self, request, *args, **kwargs)


httpx.HTTPTransport.handle_request = _guarded_transport
httpx.AsyncHTTPTransport.handle_async_request = _guarded_async_transport
requests.adapters.HTTPAdapter.send = _guarded_adapter
