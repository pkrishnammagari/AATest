"""FH AECB Analyzer -- production entry: CB subject id in, bureau report out.

    streamlit run app_api.py        (see docs/OPERATIONS.md for the service)

Asks for a CB subject id, fetches the payload from the internal bureau-report
API (aecb/api.py; endpoint in config/api.json, service account from the
environment), validates it, and renders it through the standard pipeline
(context.from_bytes -> render_page). The AI brief is not part of this entry:
the report renders without the AI Analysis panel.

The fetched payload lives in this session's memory for rendering. Each
successful response is also archived verbatim outside the application tree
(aecb/archive.py, AECB_ARCHIVE_DIR). Every query writes one line to the
"aecb.audit" log.

app.py is the development harness (fixture picker and uploader) and is not
deployed.
"""

from __future__ import annotations

import logging
import os
import re

import streamlit as st

from aecb import api, archive, context, logsetup, ui
from aecb.render import branding
from aecb.render.page import render_page

logsetup.configure()
_LOG = logging.getLogger("aecb.app_api")
_AUDIT = logging.getLogger("aecb.audit")

# CB subject ids are short alphanumeric references. Anything else is refused
# before it reaches the API or the logs.
_SUBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")

# When the app sits behind an SSO reverse proxy, the header carrying the
# authenticated user name, so the audit line can name who queried whom.
ENV_AUDIT_USER_HEADER = "AECB_AUDIT_USER_HEADER"

_PAYLOAD_KEY = "_api_payload"
_SUBJECT_KEY = "_api_subject"

ui.configure_page()


def _audit(subject_id: str, outcome: str) -> None:
    """One audit line per query: who (when known), from where, which subject."""
    header = (os.environ.get(ENV_AUDIT_USER_HEADER) or "").strip()
    user = st.context.headers.get(header) if header else None
    _AUDIT.info("query subject=%r outcome=%s user=%r client_ip=%s",
                subject_id, outcome, user or "-", st.context.ip_address or "-")


def _validated_context(raw: bytes, subject_id: str):
    """Parse and validate the API response. Raises api.ApiError (user-safe)."""
    try:
        return context.require_aecb_payload(
            context.from_bytes(raw, source_name="api:%s" % subject_id))
    except ValueError as exc:
        _LOG.warning("API response for %r rejected: %s", subject_id, exc)
        raise api.ApiError("The API answered for %r, but the response is not "
                           "a readable AECB payload. Details are in the "
                           "server log." % subject_id) from None


def _reset() -> None:
    st.session_state.pop(_PAYLOAD_KEY, None)
    st.session_state.pop(_SUBJECT_KEY, None)
    st.rerun()


def _fetch(subject_id: str) -> None:
    """Fetch, validate, archive and stash one subject's report."""
    try:
        with st.spinner("Querying the bureau report for %s…" % subject_id):
            raw = api.fetch_report(subject_id)
            _validated_context(raw, subject_id)   # reject before storing
    except api.ApiError as exc:
        _LOG.warning("Bureau API fetch failed for %r: %s", subject_id, exc)
        _audit(subject_id, "failed")
        st.error(str(exc))
        return
    _audit(subject_id, "ok")
    archive.save_response(raw, subject_id)
    st.session_state[_PAYLOAD_KEY] = raw
    st.session_state[_SUBJECT_KEY] = subject_id
    st.rerun()


def _landing() -> None:
    """The first screen: one field, one button. Enter submits too (st.form)."""
    ui.hide_streamlit_chrome()
    st.markdown("<div style='height:18vh'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown(
            "<h2 style='margin-bottom:0'>%s</h2>"
            "<p style='color:#5B6B7C; margin-top:4px'>Enter a CB subject id to "
            "pull the live bureau report and render the underwriting screen.</p>"
            % branding.APP_NAME,
            unsafe_allow_html=True,
        )
        with st.form("subject_form"):
            subject_id = st.text_input("CB Subject ID",
                                       placeholder="CB subject id")
            submitted = st.form_submit_button("Display report", type="primary",
                                              use_container_width=True)
        if not submitted:
            return
        subject_id = subject_id.strip()
        if not subject_id:
            st.error("Enter a CB subject id first.")
        elif not _SUBJECT_ID.match(subject_id):
            st.error("A CB subject id is up to 40 letters, digits, hyphens or "
                     "underscores.")
        else:
            _fetch(subject_id)


def _mismatch(ctx, requested: str):
    """The delivered subject id, when it does not answer the requested one."""
    delivered = str(ctx.customer.get("CBSubjectId") or "").strip()
    if not delivered or delivered.casefold() == requested.strip().casefold():
        return None
    return delivered


def _report() -> None:
    subject = st.session_state[_SUBJECT_KEY]
    try:
        ctx = _validated_context(st.session_state[_PAYLOAD_KEY], subject)
    except api.ApiError as exc:
        # Session bytes were validated before they were stored; if they fail
        # now, recover to the form rather than stranding the user.
        st.error(str(exc))
        if st.button("Query another subject"):
            _reset()
        return

    with st.sidebar:
        st.markdown("### %s" % branding.APP_NAME)
        st.caption("Live bureau report via the history API")
        if st.button("Query another subject", use_container_width=True):
            _reset()
        archive_off = archive.status()
        if archive_off:
            st.caption(archive_off)

    try:
        html = render_page(ctx, ai_panel=False)
    except Exception:  # noqa: BLE001 -- any render fault is reported the same way
        # Full traceback to the server log only -- paths and code lines must
        # not reach the browser (CWE-209).
        _LOG.exception("Failed to render payload %r", ctx.source_name)
        st.error("Failed to render the report for subject `%s`. The payload "
                 "may be malformed; details are in the server log." % subject)
        return

    with st.sidebar:
        ui.report_sidebar(ctx, html, requested=subject)

    delivered = _mismatch(ctx, subject)
    ui.hide_streamlit_chrome(banner=delivered is not None)
    if delivered is not None:
        st.warning(
            "**Subject id mismatch.** You requested `%s`, but the payload the "
            "API returned identifies subject `%s`. The report below renders "
            "the delivered payload — verify you are reading the right "
            "customer before acting on it." % (subject, delivered)
        )
    ui.show_report(html)


if _PAYLOAD_KEY in st.session_state:
    _report()
else:
    _landing()
