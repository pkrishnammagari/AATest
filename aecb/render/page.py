"""Assembles the complete report document.

The output is a standalone HTML file with zero external references -- no CDN,
no webfont host, no image URLs. That is a hard requirement twice over: the
server is air-gapped, and the same string is offered as a download so the page
can be filed against the credit application.
"""

from __future__ import annotations

from . import branding, css, js, shell
from .components import esc
from .sections import render_all

_DOC = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="icon" href="{favicon}">
<style>
{styles}
</style>
</head>
<!-- The brief rail starts CLOSED. The underwriting screen is the deliverable;
     the AI reading is opt-in, and on a payload with no model behind it the rail
     would otherwise open on its own "no brief generated" placeholder. The
     AI Analysis button in the top bar toggles it back. Anything calibrated to
     the width of a card's right-hand column -- sections/returns.py _COL_W -- is
     calibrated to THIS state, because it is the one the page loads in. -->
<body class="rail-off">
{topbar}
<div class="wrap">
{spine}
  <div class="report">
{sections}
  </div>
{rail}
</div>
<script>
{script}
</script>
</body>
</html>
"""


def render_page(ctx, title: str = "") -> str:
    """Full standalone HTML document for one AECB report."""
    if not title:
        title = "AECB Analyzer — %s" % (ctx.subject_id or "report")
    return _DOC.format(
        # The subject id inside the title is payload data -- the ONE payload
        # string that does not pass through a section renderer's esc(), so it
        # is escaped here. Same for the favicon URI, defensively.
        title=esc(title),
        favicon=esc(branding.favicon_data_uri()),
        styles=css.stylesheet(),
        topbar=shell.topbar(ctx),
        spine=shell.spine(ctx),
        sections=render_all(ctx),
        rail=shell.rail(ctx),
        script=js.script(ctx),
    )


def clear_cache() -> None:
    """Drop cached CSS/JS so edits show without restarting Streamlit."""
    css.clear_cache()
    js.clear_cache()
