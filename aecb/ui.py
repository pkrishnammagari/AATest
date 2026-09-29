"""Streamlit host pieces shared by app_api.py (UAT/production) and app.py (dev).

The report itself is a self-contained HTML document (aecb.render.page);
Streamlit only hosts it. Everything both entry points need to host it the same
way lives here, so the two cannot drift apart.

The whole report goes in ONE component iframe rather than one per section --
the sticky top bar, the spine nav and the scrollspy need a single scrolling
context, and iframes cannot share one.
"""

from __future__ import annotations

import re

import streamlit as st
import streamlit.components.v1 as components

from .render import branding

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
# With a banner above the report (app_api's subject-id mismatch warning) the
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
    """st.set_page_config for either entry point. Must be the first st call."""
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


def show_report(html: str) -> None:
    """Host the report document. height is a fallback; the chrome CSS pins it."""
    components.html(html, height=900, scrolling=True)
