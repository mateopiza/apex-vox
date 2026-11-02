"""Test configuration: run the suite against development settings.

Production-only rules (login required, simulator disabled, webhook key mandatory)
are exercised explicitly in tests/test_auth_billing.py by patching `settings`.
"""

import os

os.environ["ENVIRONMENT"] = "development"
os.environ.setdefault("ALLOW_PLAN_SIMULATOR", "true")
os.environ.setdefault("REQUIRE_LOGIN_TO_TRANSCRIBE", "false")
