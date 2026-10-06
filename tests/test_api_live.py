"""Against the REAL bureau-report API -- only where it is reachable.

Skipped unless the service account and a test subject are configured in
the shell or in ~/etc/aecb-analyzer/aecb.env (AECB_API_USERNAME,
AECB_API_DOMAIN, AECB_API_PASSWORD, AECB_TEST_SUBJECT_ID -- aecb/settings.py):

    python -m pytest -m live_api

The endpoint is config/api.json's, as in production. Nothing is archived or logged from the
payload: the response stays in memory for the duration of the test.
"""

from __future__ import annotations

import os

import pytest

import check_report  # scripts/check_report.py -- the verbatim-value gate

from aecb import api, context, runtime, settings
from aecb.render.page import render_page

pytestmark = pytest.mark.live_api

# Read at collection, before conftest points settings.LOCAL_FILE elsewhere
# for every test. The shell wins over the file, as in the app.
try:
    _FILE = settings.read(settings.LOCAL_FILE)
except (settings.SettingsError, OSError):
    _FILE = {}
_KEYS = (api.ENV_USERNAME, api.ENV_DOMAIN, api.ENV_SECRET)


def _setting(name: str) -> str:
    return (os.environ.get(name) or _FILE.get(name) or "").strip()


SUBJECT = _setting("AECB_TEST_SUBJECT_ID")


@pytest.fixture(scope="module")
def live_payload():
    if not (_setting(api.ENV_USERNAME) and SUBJECT):
        pytest.skip("live API not configured: set AECB_API_USERNAME, "
                    "AECB_API_PASSWORD and AECB_TEST_SUBJECT_ID in "
                    "~/etc/aecb-analyzer/aecb.env")
    with pytest.MonkeyPatch.context() as mp:
        for key in _KEYS:
            mp.setenv(key, _setting(key))
        return api.fetch_report(SUBJECT)


@pytest.fixture(scope="module")
def live_context(live_payload):
    return context.require_aecb_payload(
        context.from_bytes(live_payload, source_name="api:%s" % SUBJECT))


def test_live_api_returns_an_aecb_payload(live_context):
    assert live_context.subject_id != "unknown"
    assert not live_context.dropped_rows


def test_live_payload_renders_every_value_verbatim(live_context):
    html = render_page(live_context, ai_mode=runtime.AI_SOON)
    assert check_report.check_page(live_context, html) == []


def test_live_payload_names_the_requested_subject(live_context):
    # Absent is not a mismatch -- the app warns only on a different id.
    delivered = str(live_context.customer.get("CBSubjectId") or "").strip()
    assert not delivered or delivered.casefold() == SUBJECT.casefold()
