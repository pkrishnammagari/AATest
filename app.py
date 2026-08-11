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

import os
import traceback

import streamlit as st
import streamlit.components.v1 as components

from aecb import context
from aecb.render import branding
from aecb.render.page import clear_cache, render_page

HERE = os.path.dirname(os.path.abspath(__file__))
PAYLOAD_DIR = os.path.join(HERE, "ReferenceJSON")

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
    </style>
    """,
    unsafe_allow_html=True,
)


def list_payloads():
    if not os.path.isdir(PAYLOAD_DIR):
        return []
    return sorted(f for f in os.listdir(PAYLOAD_DIR) if f.lower().endswith(".json"))


def load_context():
    """Resolve the ReportContext from the sidebar controls. None if unavailable."""
    files = list_payloads()

    uploaded = st.sidebar.file_uploader("Upload an AECB payload", type=["json"])
    if uploaded is not None:
        return context.from_bytes(uploaded.getvalue(), source_name=uploaded.name)

    if not files:
        st.sidebar.warning("No JSON payloads found in ReferenceJSON/.")
        return None

    chosen = st.sidebar.selectbox("Payload", files, index=0)
    return context.from_file(os.path.join(PAYLOAD_DIR, chosen))


with st.sidebar:
    st.markdown("### AECB Analyzer")
    st.caption("AECB bureau report renderer")

    ctx = load_context()

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
    st.error("Failed to render the report.")
    st.code(traceback.format_exc())
    st.stop()

with st.sidebar:
    st.divider()
    st.markdown("**Report**")
    st.caption("Subject `%s`" % ctx.subject_id)
    st.caption("Report date `%s`" % (ctx.report_date or "unresolved"))
    st.caption("Source `%s`" % ctx.source_name)
    st.download_button(
        "Download standalone HTML",
        data=html.encode("utf-8"),
        file_name="aecb_%s.html" % ctx.subject_id,
        mime="text/html",
        use_container_width=True,
        help="A self-contained file with fonts embedded -- opens offline, "
             "suitable for filing against the application.",
    )

# height is a fallback; the injected CSS above pins it to 100vh.
components.html(html, height=900, scrolling=True)
