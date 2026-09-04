"""AECB Analyzer -- Streamlit host for the bureau report.

The report itself is a self-contained HTML document built by aecb.render.page.
Streamlit's job is narrow on purpose: pick a payload, host the document, and
offer it as a download. All layout, type and interaction live in the HTML.

The whole report goes in ONE component iframe rather than one per section --
the sticky top bar, the spine nav and the scrollspy all need a single scrolling
context, and iframes cannot share one.

Runs on Python 3.9 with streamlit==1.50.0 (the last release supporting 3.9).
"""

from __future__ import annotations

import logging
import os
import re

import streamlit as st
import streamlit.components.v1 as components

from aecb import brief, context
from aecb.render import branding
from aecb.render.page import clear_cache, render_page

HERE = os.path.dirname(os.path.abspath(__file__))
PAYLOAD_DIR = os.path.join(HERE, "ReferenceJSON")

_LOG = logging.getLogger("aecb.app")

st.set_page_config(
    page_title="AECB Analyzer",
    # The supplied resources/ logo, else the blue FH monogram -- always as a
    # data URL, which Streamlit accepts for both raster and SVG. Passing an SVG
    # file path instead would depend on its image loader handling SVG.
    page_icon=branding.favicon_data_uri(),
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Reclaim the vertical space Streamlit reserves for its own chrome, so the
# report iframe starts at the top of the window rather than a third of the way
# down it.
# Reclaim the space Streamlit reserves for its own chrome AND pin the report
# iframe to exactly one viewport height.
#
# The height matters more than it looks: components.html renders into an iframe
# with its own scrollbar. If that iframe is taller than the window, the page ends
# up with two nested scroll contexts -- the outer page moving first, then the
# inner document -- which is what made scrolling feel like it stalled. Forcing
# the iframe to 100vh leaves a single scrolling surface: the report itself.
st.markdown(
    """
    <style>
      .block-container{padding:0 !important; max-width:100% !important}
      header[data-testid="stHeader"]{height:0; visibility:hidden}
      footer{visibility:hidden}
      div[data-testid="stVerticalBlock"]{gap:0 !important}
      .stApp{overflow:hidden}
      iframe[title="st.iframe"]{height:100vh !important; width:100% !important;
                                border:none !important; display:block}

      /* Streamlit renders the open-sidebar control INSIDE stHeader, which the
         rule above hides -- so with the sidebar collapsed there was no way to
         reopen it, and the payload picker, uploader and download button were
         unreachable. Lift just that one button back out: visibility is
         re-assertable on a descendant of a hidden ancestor, and position:fixed
         frees it from the zero-height header box. Streamlit only renders it
         while the sidebar is collapsed, so it vanishes once the sidebar opens.

         Bottom-left, not Streamlit's default top-left: the report's own top bar
         starts with the FH logo at x~20, and the button landed on top of it --
         present, but reading as a smudge against the brand mark rather than as
         a control. The left gutter below the spine rail is the only region of
         the report that is empty at every scroll position.

         It is styled as a solid chip rather than left as Streamlit's bare
         fadedText60 chevron, which was almost invisible on the report's white
         top bar. This is the one affordance for reaching the payload controls;
         it has to look clickable.
      */
      header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"]{
        visibility:visible; position:fixed; z-index:1000;
        top:auto; bottom:1rem; left:1rem; width:2.25rem; height:2.25rem;
        background:#fff; border:1px solid #D7DEE6; border-radius:8px;
        box-shadow:0 2px 10px rgba(20,30,44,.16)}
      header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"]:hover{
        background:#F1F5F9; border-color:#00426A}
      /* fh-blue, so it reads as part of the product rather than browser chrome. */
      header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"] span{
        color:#00426A !important}
    </style>
    """,
    unsafe_allow_html=True,
)


def list_payloads():
    if not os.path.isdir(PAYLOAD_DIR):
        return []
    return sorted(f for f in os.listdir(PAYLOAD_DIR) if f.lower().endswith(".json"))


def parse_upload(uploaded):
    """Validate an uploaded payload and build a session-scoped ReportContext.

    Returns a ReportContext, or None if the file was rejected. Nothing is
    written to disk: an upload renders only in the session that supplied it,
    so one user's bureau file is never listed for, or readable by, any other
    session. The picker below lists only the committed, anonymized fixtures
    in ReferenceJSON/. This is also the seam the planned AECB API integration
    will use -- context.from_bytes() renders a payload wherever the bytes
    came from, so replacing the uploader with an API call changes only this
    function.
    """
    name = os.path.basename(uploaded.name or "").strip() or "upload.json"
    try:
        ctx = context.from_bytes(uploaded.getvalue(), source_name=name)
    except Exception as exc:
        st.sidebar.error("Could not read that payload: %s" % exc)
        return None

    # loader.normalise() guarantees every array exists, so well-formed JSON that
    # is not an AECB payload parses cleanly into an empty report. Insist on at
    # least one of the arrays that identify the subject.
    if not any(ctx.rows(key) for key in ("customerInfo", "summary", "score")):
        st.sidebar.error(
            "That JSON parsed, but carries no customerInfo, summary or score "
            "-- it does not look like an AECB payload."
        )
        return None
    return ctx


def load_context():
    """Resolve the ReportContext from the sidebar controls. None if unavailable."""
    uploaded = st.sidebar.file_uploader("Upload an AECB payload", type=["json"])

    # An upload renders in this session only -- never archived, never listed
    # for other sessions. Clearing the uploader (or refreshing the page) falls
    # back to the committed fixtures below.
    if uploaded is not None:
        ctx = parse_upload(uploaded)
        if ctx is not None:
            st.sidebar.caption("Rendering the uploaded file (this session only).")
            return ctx

    files = list_payloads()
    if not files:
        st.sidebar.warning("No JSON payloads found in ReferenceJSON/.")
        return None
    chosen = st.sidebar.selectbox("Payload", files)
    return context.from_file(os.path.join(PAYLOAD_DIR, chosen))


def attach_brief(ctx):
    """Sidebar controls for the AI brief; sets ctx.brief when one is cached.

    The report always renders immediately WITHOUT the brief -- a model call
    takes tens of seconds and must never gate first paint. Generation is a
    button press; the result is cached in session memory only, keyed by
    payload hash + model + prompt version, so it follows the same guarantee
    as uploads: nothing written to disk, nothing visible to another session.
    """
    st.divider()
    st.markdown("**AI brief**")

    reason = brief.probe()
    if reason:
        # The rail keeps its own "no brief generated" copy; the sidebar says
        # WHY, because that part is infrastructure, not underwriting.
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
                _LOG.exception("Brief generation failed for %r",
                               ctx.source_name)
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


with st.sidebar:
    st.markdown("### AECB Analyzer")
    st.caption("AECB bureau report renderer")

    try:
        ctx = load_context()
    except Exception:
        # A missing config file raises on purpose (see aecb.context) -- but
        # the traceback belongs in the server log, not the browser.
        _LOG.exception("Failed to load the payload or configuration")
        st.error("Failed to load the payload or configuration; details are "
                 "in the server log.")
        ctx = None

    if ctx is not None:
        attach_brief(ctx)

    st.divider()
    if st.button("Reload CSS / JS", help="Re-read report.css and report.js from "
                                         "disk without restarting the server."):
        clear_cache()
        st.rerun()

if ctx is None:
    st.stop()

try:
    html = render_page(ctx)
except Exception:
    # Full traceback to the server log only -- paths and code lines must not
    # reach the browser (CWE-209).
    _LOG.exception("Failed to render payload %r", ctx.source_name)
    st.error(
        "Failed to render the report for `%s`. The payload may be malformed; "
        "details are in the server log." % ctx.source_name
    )
    st.stop()

with st.sidebar:
    st.divider()
    st.markdown("**Report**")
    st.caption("Subject `%s`" % ctx.subject_id)
    st.caption("Report date `%s`" % (ctx.report_date or "unresolved"))
    st.caption("Source `%s`" % ctx.source_name)
    if ctx.unknown_arrays:
        st.warning(
            "The payload carries %d section(s) this renderer does not know "
            "and does not draw: %s"
            % (len(ctx.unknown_arrays), ", ".join(ctx.unknown_arrays))
        )
    # The subject id is payload data -- keep it out of filesystem semantics.
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

# height is a fallback; the injected CSS above pins it to 100vh.
components.html(html, height=900, scrolling=True)
