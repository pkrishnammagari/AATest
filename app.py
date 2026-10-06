"""FH AECB Analyzer -- the application: CB subject id in, bureau report out.

    streamlit run app.py        (the server runs it as a service; see
                                 docs/OPERATIONS.md)

One entry point for every environment. Asks for a CB subject id, fetches the
payload from the internal bureau-report API (aecb/api.py; endpoint in
config/api.json, service account from the environment), validates it, and
renders it through the standard pipeline (context.from_bytes -> render_page).

What else it offers follows AECB_ENV (aecb/runtime.py; unset means prod):

    uat, prod   the subject-id screen only. The AI Analysis button shows
                "Coming soon" (AECB_AI_BRIEF defaults to coming_soon) and the
                brief package is never loaded.
    dev         also a sample picker (the committed fixtures in ReferenceJSON/
                and, when configured, the archived responses), a CSS/JS
                reload button, and the AI Analysis from the local Ollama model.

There is no file uploader in any environment.

Settings come from the process environment: systemd's EnvironmentFile on a
server, ~/etc/aecb-analyzer/aecb.env on a developer machine (aecb/settings.py,
read here at start-up; the shell wins over the file).

The fetched payload lives in this session's memory for rendering. Each
successful API response is also archived verbatim outside the application
tree (aecb/archive.py, AECB_ARCHIVE_DIR). Every API query writes one line to
the "aecb.audit" log, as does every generated AI analysis block and every
feedback vote; samples are not queries and are neither audited nor archived.
"""

from __future__ import annotations

import logging
import os
import re

import streamlit as st

from aecb import settings

# Before anything reads the environment -- logging included (AECB_LOG_DIR).
_SETTINGS_PROBLEM = settings.load_local()

from aecb import api, archive, context, logsetup, runtime, ui  # noqa: E402
from aecb.render import branding  # noqa: E402
from aecb.render.page import clear_cache, render_page  # noqa: E402

logsetup.configure()
_LOG = logging.getLogger("aecb.app")
_AUDIT = logging.getLogger("aecb.audit")
settings.log_once(_SETTINGS_PROBLEM)

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(HERE, "ReferenceJSON")

# CB subject ids are short alphanumeric references. Anything else is refused
# before it reaches the API or the logs.
_SUBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")

_PAYLOAD_KEY = "_payload"
_SOURCE_KEY = "_source"
_SUBJECT_KEY = "_subject"

ui.configure_page()

# Read once per script run, so a changed setting shows on the next rerun.
_ENV, _AI, _AI_PROBLEM = runtime.resolve(runtime.PROD)
_DEV = _ENV == runtime.DEV


def _audit(subject_id: str, outcome: str) -> None:
    """One audit line per query: who (when known), from where, which subject."""
    user = ui.audit_user()
    _AUDIT.info("query subject=%r outcome=%s user=%r client_ip=%s",
                subject_id, outcome, user or "-", st.context.ip_address or "-")


def _validated_context(raw: bytes, source_name: str):
    """Parse and validate a payload. Raises ValueError (logged here)."""
    try:
        return context.require_aecb_payload(
            context.from_bytes(raw, source_name=source_name))
    except ValueError as exc:
        _LOG.warning("Payload %r rejected: %s", source_name, exc)
        raise


def _show(raw: bytes, source_name: str, subject_id) -> None:
    """Stash a validated payload for the report screen."""
    st.session_state[_PAYLOAD_KEY] = raw
    st.session_state[_SOURCE_KEY] = source_name
    st.session_state[_SUBJECT_KEY] = subject_id
    st.rerun()


def _reset() -> None:
    for key in (_PAYLOAD_KEY, _SOURCE_KEY, _SUBJECT_KEY):
        st.session_state.pop(key, None)
    st.rerun()


def _fetch(subject_id: str) -> None:
    """Fetch, validate, archive and stash one subject's report."""
    source_name = "api:%s" % subject_id
    try:
        with st.spinner("Querying the bureau report for %s…" % subject_id):
            raw = api.fetch_report(subject_id)
            try:
                _validated_context(raw, source_name)   # reject before storing
            except ValueError:
                raise api.ApiError(
                    "The API answered for %r, but the response is not a "
                    "readable AECB payload. Details are in the server log."
                    % subject_id) from None
    except api.ApiError as exc:
        _LOG.warning("Bureau API fetch failed for %r: %s", subject_id, exc)
        _audit(subject_id, "failed")
        st.error(str(exc))
        return
    _audit(subject_id, "ok")
    archive.save_response(raw, subject_id)
    _show(raw, source_name, subject_id)


# --- development only ---------------------------------------------------------

def _samples() -> dict:
    """label -> path: the committed fixtures, then the archived responses."""
    found = {}
    folders = [("", SAMPLE_DIR)]
    archived = archive.configured_dir()
    if archived:
        folders.append(("archive/", archived))
    for prefix, folder in folders:
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith(".json"):
                    found[prefix + name] = os.path.join(folder, name)
    return found


def _sample_picker() -> None:
    """Open a payload from disk instead of the API (AECB_ENV=dev only)."""
    st.markdown("**Development:** or open a sample payload")
    samples = _samples()
    if not samples:
        st.caption("No sample payloads found.")
        return
    label = st.selectbox("Sample payload", list(samples))
    if not st.button("Open sample", use_container_width=True):
        return
    try:
        with open(samples[label], "rb") as fh:
            raw = fh.read()
        _validated_context(raw, "sample:%s" % label)
    except (OSError, ValueError):
        st.error("That sample could not be read as an AECB payload; details "
                 "are in the server log.")
        return
    _show(raw, "sample:%s" % label, None)


def _dev_sidebar() -> None:
    st.divider()
    st.caption("Environment `%s` · AI panel `%s`" % (_ENV, _AI))
    if st.button("Reload CSS / JS", help="Re-read report.css and report.js "
                                         "from disk without restarting."):
        clear_cache()
        st.rerun()


# --- screens ------------------------------------------------------------------

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
        if _SETTINGS_PROBLEM:
            st.warning(_SETTINGS_PROBLEM)
        with st.form("subject_form"):
            subject_id = st.text_input("CB Subject ID",
                                       placeholder="CB subject id")
            submitted = st.form_submit_button("Display report", type="primary",
                                              use_container_width=True)
        if submitted:
            _submit(subject_id.strip())
        if _DEV:
            _sample_picker()


def _submit(subject_id: str) -> None:
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


def _sidebar_head(ctx, subject) -> None:
    """The sidebar above the report block: title, reset, setting notices,
    development tools, and the AI Analysis controls when the panel is live."""
    st.markdown("### %s" % branding.APP_NAME)
    st.caption("Live bureau report via the history API" if subject
               else "Development sample — not fetched from the API")
    if st.button("Query another subject", use_container_width=True):
        _reset()
    archive_off = archive.status()
    if archive_off:
        st.caption(archive_off)
    for problem in (_AI_PROBLEM, _SETTINGS_PROBLEM):
        if problem:
            st.caption(problem)
    if _DEV:
        _dev_sidebar()
    if _AI == runtime.AI_LIVE:
        ui.analysis_controls(ctx, _ENV, subject=subject, user=ui.audit_user())


def _render(ctx) -> tuple:
    """(screen HTML, download HTML).

    The same document, except: while the AI panel is "coming soon" the
    downloaded file is filed against the credit application, and a record
    should not advertise a feature, so it carries no AI control at all; and
    while an analysis exists the screen reopens in the analysis view after
    every rerun, whereas the filed copy opens on the report.
    """
    if _AI == runtime.AI_SOON:
        return render_page(ctx, ai_mode=_AI), render_page(ctx, ai_mode=runtime.AI_OFF)
    html = render_page(ctx, ai_mode=_AI)
    if getattr(ctx, "analysis", None) is None:
        return html, html
    return render_page(ctx, ai_mode=_AI, analysis_open=True), html


def _report() -> None:
    subject = st.session_state.get(_SUBJECT_KEY)
    try:
        ctx = _validated_context(st.session_state[_PAYLOAD_KEY],
                                 st.session_state[_SOURCE_KEY])
    except ValueError:
        # Session bytes were validated before they were stored; if they fail
        # now, recover to the form rather than stranding the user.
        st.error("The stored report could not be read again. Details are in "
                 "the server log.")
        if st.button("Query another subject"):
            _reset()
        return

    with st.sidebar:
        _sidebar_head(ctx, subject)

    try:
        html, download = _render(ctx)
    except Exception:  # noqa: BLE001 -- any render fault is reported the same way
        # Full traceback to the server log only -- paths and code lines must
        # not reach the browser (CWE-209).
        _LOG.exception("Failed to render payload %r", ctx.source_name)
        st.error("Failed to render the report for `%s`. The payload may be "
                 "malformed; details are in the server log."
                 % (subject or ctx.source_name))
        return

    with st.sidebar:
        ui.report_sidebar(ctx, download, requested=subject)

    delivered = _mismatch(ctx, subject) if subject else None
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
