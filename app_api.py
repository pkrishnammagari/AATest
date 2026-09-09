"""AECB Analyzer -- API entry: subject id in, rendered bureau report out.

The production entrypoint (run: streamlit run app_api.py). It asks for a CB
subject id, fetches the payload from the internal bureau-report API
(aecb/api.py, endpoint in config/api.json), validates it exactly the way the
dev uploader does, and renders it through the unchanged pipeline
(context.from_bytes -> render_page). app.py remains the development harness
with the fixture picker and uploader; nothing in it or in the renderer is
modified by this entry.

Session guarantees match the uploader's: the fetched payload lives in this
session's memory only -- never written to disk, never visible to another
session. Fetch happens once per Display click; reruns (brief generation,
downloads) reuse the cached bytes.
"""

from __future__ import annotations

import logging
import re

import streamlit as st
import streamlit.components.v1 as components

from aecb import api, brief, context
from aecb.render import branding
from aecb.render.page import clear_cache, render_page

_LOG = logging.getLogger("aecb.app_api")

st.set_page_config(
    page_title="AECB Analyzer",
    page_icon=branding.favicon_data_uri(),
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Chrome CSS mirrored from app.py (which must stay untouched): reclaim
# Streamlit's own chrome, pin the report iframe to one viewport so there is a
# single scrolling surface, and lift the collapsed-sidebar chip out of the
# hidden header. The one difference: when a subject-id mismatch banner has to
# sit above the report, the pin relaxes so the banner and the report share the
# page instead of the banner pushing the report off a clipped viewport.
def _chrome_css(banner: bool) -> None:
    iframe_rule = (
        'iframe[title="st.iframe"]{height:88vh !important; width:100% !important;'
        ' border:none !important; display:block}'
        if banner else
        'iframe[title="st.iframe"]{height:100vh !important; width:100% !important;'
        ' border:none !important; display:block}'
    )
    overflow_rule = ".stApp{overflow:auto}" if banner else ".stApp{overflow:hidden}"
    st.markdown(
        """
        <style>
          .block-container{padding:0 !important; max-width:100%% !important}
          header[data-testid="stHeader"]{height:0; visibility:hidden}
          footer{visibility:hidden}
          div[data-testid="stVerticalBlock"]{gap:0 !important}
          %s
          %s
          header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"]{
            visibility:visible; position:fixed; z-index:1000;
            top:auto; bottom:1rem; left:1rem; width:2.25rem; height:2.25rem;
            background:#fff; border:1px solid #D7DEE6; border-radius:8px;
            box-shadow:0 2px 10px rgba(20,30,44,.16)}
          header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"]:hover{
            background:#F1F5F9; border-color:#00426A}
          header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"] span{
            color:#00426A !important}
        </style>
        """ % (overflow_rule, iframe_rule),
        unsafe_allow_html=True,
    )


def _validated_context(raw: bytes, subject_id: str):
    """Parse and validate the API response the way app.py validates uploads.

    Returns a ReportContext or raises api.ApiError with a user-safe message.
    loader.normalise() guarantees every array exists, so well-formed JSON that
    is not an AECB payload parses cleanly into an empty report -- insist on at
    least one of the arrays that identify the subject.
    """
    try:
        ctx = context.from_bytes(raw, source_name="api:%s" % subject_id)
    except Exception as exc:
        raise api.ApiError("The API response for %r could not be read as a "
                           "payload: %s" % (subject_id, exc))
    if not any(ctx.rows(key) for key in ("customerInfo", "summary", "score")):
        raise api.ApiError("The API answered for %r, but the response carries "
                           "no customerInfo, summary or score -- it does not "
                           "look like an AECB payload." % subject_id)
    return ctx


def _landing() -> None:
    """The first screen: one field, one button. Enter submits too (st.form)."""
    _chrome_css(banner=False)
    st.markdown("<div style='height:18vh'></div>", unsafe_allow_html=True)
    left, mid, right = st.columns([1, 2, 1])
    with mid:
        st.markdown(
            "<h2 style='margin-bottom:0'>FH AECB Analyser</h2>"
            "<p style='color:#5B6B7C; margin-top:4px'>Enter a CB subject id to "
            "pull the live bureau report and render the underwriting screen.</p>",
            unsafe_allow_html=True,
        )
        with st.form("subject_form"):
            subject_id = st.text_input("CB Subject ID", placeholder="e.g. G03929019")
            submitted = st.form_submit_button("Display report", type="primary",
                                              use_container_width=True)
        if submitted:
            subject_id = subject_id.strip()
            if not subject_id:
                st.error("Enter a CB subject id first.")
                return
            try:
                with st.spinner("Querying the bureau report for %s…" % subject_id):
                    raw = api.fetch_report(subject_id)
                    _validated_context(raw, subject_id)  # reject before storing
            except api.ApiError as exc:
                _LOG.warning("Bureau API fetch failed for %r: %s", subject_id, exc)
                st.error(str(exc))
                return
            st.session_state["_api_payload"] = raw
            st.session_state["_api_subject"] = subject_id
            st.rerun()


def _attach_brief(ctx) -> None:
    """Sidebar AI-brief controls; mirrors app.py's attach_brief unchanged."""
    st.divider()
    st.markdown("**AI brief**")

    reason = brief.probe()
    if reason:
        st.caption("Unavailable: %s." % reason)
        return

    cache = st.session_state.setdefault("_brief_cache", {})
    key = brief.cache_key(ctx)

    if st.button("Generate AI brief",
                 help="One local-model pass over a derived fact digest. "
                      "Findings are validated against the payload before "
                      "anything renders; nothing leaves this machine."):
        with st.spinner("Reading the payload with %s…" % brief.MODEL):
            try:
                cache[key] = brief.generate_brief(ctx)
            except brief.BriefUnavailable:
                _LOG.exception("Brief generation failed for %r", ctx.source_name)
                st.warning("The model did not return a usable brief; "
                           "details are in the server log.")

    cached = cache.get(key)
    if cached is not None:
        ctx.brief = cached
        st.caption("Brief attached — %d finding(s), %d unknown(s), %d "
                   "dropped by validation. Open it with the AI Analysis "
                   "button."
                   % (len(cached["findings"]), len(cached["unknowns"]),
                      len(cached["dropped"])))


def _mismatch(ctx, requested: str):
    """The delivered subject id, when it does not answer the requested one."""
    delivered = str(ctx.customer.get("CBSubjectId") or "").strip()
    if not delivered:
        return None
    if delivered.casefold() == requested.strip().casefold():
        return None
    return delivered


# --- flow --------------------------------------------------------------------

if "_api_payload" not in st.session_state:
    _landing()
    st.stop()

subject = st.session_state["_api_subject"]

try:
    ctx = _validated_context(st.session_state["_api_payload"], subject)
except api.ApiError as exc:
    # Session bytes should already be validated; if they fail now, recover to
    # the form rather than stranding the user on an error.
    _LOG.exception("Cached payload for %r failed validation", subject)
    st.error(str(exc))
    if st.button("Query another subject"):
        st.session_state.pop("_api_payload", None)
        st.session_state.pop("_api_subject", None)
        st.rerun()
    st.stop()

with st.sidebar:
    st.markdown("### AECB Analyzer")
    st.caption("Live bureau report via the history API")
    if st.button("Query another subject", use_container_width=True):
        st.session_state.pop("_api_payload", None)
        st.session_state.pop("_api_subject", None)
        st.rerun()

    _attach_brief(ctx)

    st.divider()
    if st.button("Reload CSS / JS", help="Re-read report.css and report.js from "
                                         "disk without restarting the server."):
        clear_cache()
        st.rerun()

try:
    html = render_page(ctx)
except Exception:
    # Full traceback to the server log only -- paths and code lines must not
    # reach the browser (CWE-209).
    _LOG.exception("Failed to render payload %r", ctx.source_name)
    st.error("Failed to render the report for subject `%s`. The payload may "
             "be malformed; details are in the server log." % subject)
    st.stop()

with st.sidebar:
    st.divider()
    st.markdown("**Report**")
    st.caption("Requested subject `%s`" % subject)
    st.caption("Subject `%s`" % ctx.subject_id)
    st.caption("Report date `%s`" % (ctx.report_date or "unresolved"))
    st.caption("Source `%s`" % ctx.source_name)
    if ctx.unknown_arrays:
        st.warning(
            "The payload carries %d section(s) this renderer does not know "
            "and does not draw: %s"
            % (len(ctx.unknown_arrays), ", ".join(ctx.unknown_arrays))
        )
    safe_subject = re.sub(r"[^A-Za-z0-9_-]", "_", ctx.subject_id)[:40] or "report"
    st.download_button(
        "Download standalone HTML",
        data=html.encode("utf-8"),
        file_name="aecb_%s.html" % safe_subject,
        mime="text/html",
        use_container_width=True,
        help="A self-contained file with fonts embedded -- opens offline, "
             "suitable for filing against the application.",
    )

delivered = _mismatch(ctx, subject)
_chrome_css(banner=delivered is not None)
if delivered is not None:
    st.warning(
        "**Subject id mismatch.** You requested `%s`, but the payload the API "
        "returned identifies subject `%s`. The report below renders the "
        "delivered payload — verify you are reading the right customer before "
        "acting on it." % (subject, delivered)
    )

components.html(html, height=900, scrolling=True)
