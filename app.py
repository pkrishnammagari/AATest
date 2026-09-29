"""FH AECB Analyzer -- development harness. NOT deployed (see app_api.py).

    streamlit run app.py

Renders the committed, anonymized fixtures in ReferenceJSON/ or an uploaded
payload, offers the optional local-model AI brief (Ollama), and can reload
report.css / report.js from disk without restarting the server. Uploads are
session-scoped: nothing is written to disk, and one session's file is never
visible to another.
"""

from __future__ import annotations

import logging
import os

import streamlit as st

from aecb import brief, context, logsetup, ui
from aecb.render import branding
from aecb.render.page import clear_cache, render_page

HERE = os.path.dirname(os.path.abspath(__file__))
PAYLOAD_DIR = os.path.join(HERE, "ReferenceJSON")

logsetup.configure()
_LOG = logging.getLogger("aecb.app")

ui.configure_page()
ui.hide_streamlit_chrome()


def list_payloads():
    if not os.path.isdir(PAYLOAD_DIR):
        return []
    return sorted(f for f in os.listdir(PAYLOAD_DIR) if f.lower().endswith(".json"))


def parse_upload(uploaded):
    """Validate an uploaded payload into a session-scoped ReportContext.

    Returns None (after showing why) when the file is rejected.
    """
    name = os.path.basename(uploaded.name or "").strip() or "upload.json"
    try:
        return context.require_aecb_payload(
            context.from_bytes(uploaded.getvalue(), source_name=name))
    except ValueError as exc:
        st.sidebar.error("Could not read that payload: %s" % exc)
        return None


def load_context():
    """Resolve the ReportContext from the sidebar controls. None if unavailable."""
    uploaded = st.sidebar.file_uploader("Upload an AECB payload", type=["json"])
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
    takes tens of seconds and must never gate first paint. The result is
    cached in session memory only, keyed by payload hash + model + prompt
    version.
    """
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


def main() -> None:
    with st.sidebar:
        st.markdown("### %s" % branding.APP_NAME)
        st.caption("Development harness — fixtures and uploads")
        try:
            ctx = load_context()
        except (OSError, ValueError):
            # A missing or malformed config file raises on purpose (see
            # aecb.context); the traceback belongs in the server log.
            _LOG.exception("Failed to load the payload or configuration")
            st.error("Failed to load the payload or configuration; details "
                     "are in the server log.")
            ctx = None
        if ctx is not None:
            attach_brief(ctx)
        st.divider()
        if st.button("Reload CSS / JS", help="Re-read report.css and report.js "
                                             "from disk without restarting."):
            clear_cache()
            st.rerun()

    if ctx is None:
        return
    try:
        html = render_page(ctx)
    except Exception:  # noqa: BLE001 -- any render fault is reported the same way
        _LOG.exception("Failed to render payload %r", ctx.source_name)
        st.error("Failed to render the report for `%s`. The payload may be "
                 "malformed; details are in the server log." % ctx.source_name)
        return
    with st.sidebar:
        ui.report_sidebar(ctx, html)
    ui.show_report(html)


main()
