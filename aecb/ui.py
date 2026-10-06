"""Streamlit host pieces for app.py.

The report itself is a self-contained HTML document (aecb.render.page);
Streamlit only hosts it. The hosting pieces -- page config, chrome, the
report sidebar, the AI Analysis controls -- live here, apart from app.py's
screen flow.

The whole report goes in ONE component iframe rather than one per section --
the sticky top bar, the spine nav and the scrollspy need a single scrolling
context, and iframes cannot share one.
"""

from __future__ import annotations

import logging
import os
import re

import streamlit as st
import streamlit.components.v1 as components

from .render import branding

_LOG = logging.getLogger("aecb.ui")

# Reclaim the space Streamlit reserves for its own chrome and pin the report
# iframe to one viewport height. components.html renders into an iframe with
# its own scrollbar; if the iframe were taller than the window the page would
# have two nested scroll contexts. 100vh leaves one scrolling surface.
#
# Streamlit renders the open-sidebar control INSIDE the hidden stHeader, so
# with the sidebar collapsed there would be no way to reopen it. That one
# button is lifted back out (visibility is re-assertable on a descendant of a
# hidden ancestor) to the bottom-left -- the only region of the report that is
# empty at every scroll position -- and styled as a solid chip in brand blue.
#
# With a banner above the report (app.py's subject-id mismatch warning) the
# pin relaxes so banner and report share the page instead of the banner
# pushing the report off a clipped viewport.
_CHROME_CSS = """
<style>
  .block-container{padding:0 !important; max-width:100%% !important}
  header[data-testid="stHeader"]{height:0; visibility:hidden}
  footer{visibility:hidden}
  div[data-testid="stVerticalBlock"]{gap:0 !important}
  .stApp{overflow:%(overflow)s}
  iframe[title="st.iframe"]{height:%(height)s !important; width:100%% !important;
                            border:none !important; display:block}
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
"""


def configure_page() -> None:
    """st.set_page_config for app.py. Must be the first st call."""
    st.set_page_config(
        page_title=branding.APP_NAME,
        # Always a data URL, which Streamlit accepts for raster and SVG alike.
        page_icon=branding.favicon_data_uri(),
        layout="wide",
        initial_sidebar_state="collapsed",
    )


def hide_streamlit_chrome(banner: bool = False) -> None:
    """Inject the chrome CSS above. banner=True relaxes the viewport pin."""
    st.markdown(
        _CHROME_CSS % {"overflow": "auto" if banner else "hidden",
                       "height": "88vh" if banner else "100vh"},
        unsafe_allow_html=True,
    )


def safe_filename_part(value: str) -> str:
    """A payload/user string reduced to a filesystem-safe token."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", value or "")[:40] or "report"


def report_sidebar(ctx, html: str, requested: str = None) -> None:
    """The sidebar "Report" block: provenance lines, unknown-array warning,
    and the standalone-HTML download."""
    st.divider()
    st.markdown("**Report**")
    if requested is not None:
        st.caption("Requested subject `%s`" % requested)
    st.caption("Subject `%s`" % ctx.subject_id)
    st.caption("Report date `%s`" % (ctx.report_date or "unresolved"))
    st.caption("Source `%s`" % ctx.source_name)
    if ctx.unknown_arrays:
        st.warning(
            "The payload carries %d section(s) this renderer does not know "
            "and does not draw: %s"
            % (len(ctx.unknown_arrays), ", ".join(ctx.unknown_arrays))
        )
    if ctx.dropped_rows:
        st.warning(
            "Rows that are not JSON objects were skipped: %s"
            % ", ".join("%s (%d)" % item for item in sorted(ctx.dropped_rows.items()))
        )
    st.download_button(
        "Download standalone HTML",
        data=html.encode("utf-8"),
        # The subject id is payload data -- keep it out of filesystem
        # semantics.
        file_name="aecb_%s.html" % safe_filename_part(ctx.subject_id),
        mime="text/html",
        use_container_width=True,
        help="A self-contained file with fonts embedded -- opens offline, "
             "suitable for filing against the application.",
    )


# When the app sits behind an SSO reverse proxy, the header carrying the
# authenticated user name, so audit and feedback lines can name who did what.
ENV_AUDIT_USER_HEADER = "AECB_AUDIT_USER_HEADER"

_AUDIT = logging.getLogger("aecb.audit")
_CACHE_KEY = "_analysis_cache"
_RUNNING_KEY = "_analysis_running"


def audit_user() -> "str | None":
    """The authenticated user from the SSO header, when one is configured."""
    header = (os.environ.get(ENV_AUDIT_USER_HEADER) or "").strip()
    return st.context.headers.get(header) if header else None


def analysis_controls(ctx, env: str, subject=None, user=None) -> None:
    """Sidebar controls for the AI analysis; sets ctx.analysis when one exists.

    Called inside `with st.sidebar:`, and only when the AI panel is live
    (aecb/runtime.py). The provider is the environment's (dev: Ollama,
    uat/prod: Core42 -- aecb/brief/providers.py).

    The report always renders immediately WITHOUT the analysis -- a model
    pass takes tens of seconds and must never gate first paint. One click
    starts the analysis; each block is generated on its own rerun and cached
    in session memory (keyed by payload hash + provider + model + prompt
    version), so finished blocks show while the next one runs. A failed
    block stops the run with a warning and is retried on the next click.
    """
    # Imported here, not at module level: app.py imports this module on
    # every deployment, and the brief package must load only where the AI
    # panel is live.
    from . import brief

    st.divider()
    st.markdown("**AI analysis**")

    provider = brief.for_environment(env)
    reason = provider.probe()
    if reason:
        st.caption("Unavailable: %s." % reason)
        return

    cache = st.session_state.setdefault(_CACHE_KEY, {})
    key = brief.cache_key(ctx, provider)
    analysis = cache.get(key)

    help_text = ("Several model passes over a derived fact digest. Every "
                 "item is validated against the payload before anything "
                 "renders; blocks appear one by one.")
    if provider.DATA_NOTE:
        help_text += " " + provider.DATA_NOTE
    # The button keeps the same arguments on every rerun (never disabled):
    # Streamlit identifies a widget by its arguments, and a button that
    # changes while its click is being processed loses the click.
    clicked = False
    if analysis is not None and brief.finished(analysis):
        st.caption("Analysis complete. Open it with the AI Analysis button.")
    else:
        clicked = st.button("Generate AI analysis", help=help_text)
    if clicked and analysis is None:
        try:
            analysis = cache[key] = brief.new_analysis(ctx, provider)
        except brief.BriefUnavailable:
            _LOG.exception("Analysis could not start for %r", ctx.source_name)
            st.warning("The analysis could not start; details are in the "
                       "server log.")
            return
    if analysis is None:
        return
    ctx.analysis = analysis
    if clicked or st.session_state.get(_RUNNING_KEY) == key:
        _generate_next(ctx, provider, analysis, key, subject, user)
    st.caption(brief.describe(analysis))
    if any(b["status"] == "ok" for b in analysis["blocks"].values()):
        _feedback_form(analysis, subject, user)


def _generate_next(ctx, provider, analysis, key, subject, user) -> None:
    """Generate the next missing block, then rerun so it shows."""
    from . import brief

    name = brief.next_missing(analysis)
    if name is None:
        st.session_state.pop(_RUNNING_KEY, None)
        return
    st.session_state[_RUNNING_KEY] = key
    with st.spinner("Generating %s with %s…"
                    % (brief.TITLES[name].lower(),
                       analysis["model"] or provider.NAME)):
        try:
            block = brief.generate_block(ctx, provider, analysis, name)
        except brief.BriefUnavailable:
            st.session_state.pop(_RUNNING_KEY, None)
            _LOG.exception("Block %r failed for %r", name, ctx.source_name)
            st.warning("The model did not return a usable %s; details are "
                       "in the server log. Generate again to retry."
                       % brief.TITLES[name].lower())
            return
    _AUDIT.info("analysis block=%s subject=%r provider=%s model=%s prompt=%s "
                "generation_id=%s outcome=%r user=%r",
                name, subject or "-", analysis["provider"], analysis["model"],
                analysis["prompt_version"], analysis["generation_id"],
                block.get("outcome", "-"), user or "-")
    st.rerun()


def _feedback_form(analysis, subject, user) -> None:
    """One thumbs up/down (and an optional comment) for the whole analysis,
    recorded outside the app tree (aecb/feedback.py) for quality review."""
    from . import feedback

    st.markdown("Was this analysis useful?")
    off = feedback.status()
    if off:
        st.caption(off)
        return
    comment = st.text_input("Comment (optional)", key="_fb_comment",
                            max_chars=1000)
    left, right = st.columns(2)
    up = left.button("👍 Useful", key="_fb_up", use_container_width=True)
    down = right.button("👎 Not useful", key="_fb_down",
                        use_container_width=True)
    if not (up or down):
        return
    verdict = "up" if up else "down"
    line = feedback.entry(analysis, verdict, subject, user, comment)
    recorded = feedback.record(line)
    _AUDIT.info("feedback subject=%r generation_id=%s verdict=%s user=%r",
                subject or "-", analysis["generation_id"], verdict,
                user or "-")
    st.caption("Thanks — recorded." if recorded else
               "Could not record the feedback; details are in the server log.")


def show_report(html: str) -> None:
    """Host the report document. height is a fallback; the chrome CSS pins it."""
    components.html(html, height=900, scrolling=True)
