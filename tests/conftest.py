"""Test configuration.

- A placeholder Groq key lets the pipeline start; the Groq calls themselves are monkeypatched.
- The daily guest allowance is raised so unrelated tests sharing the TestClient IP do not
  exhaust it; tests/test_auth_billing.py patches the real limits explicitly.
"""

import os

os.environ["ENVIRONMENT"] = "development"
os.environ.setdefault("GROQ_API_KEY", "gsk_test_placeholder")
os.environ.setdefault("GUEST_MAX_AUDIOS_PER_DAY", "1000")
os.environ.setdefault("MAX_IPS_PER_MONTH", "1000")
os.environ.setdefault("RESEND_API_KEY", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
