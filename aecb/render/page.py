"""Assembles the complete report document.

The output is a standalone HTML file with zero external references -- no CDN,
no webfont host, no image URLs. That is a hard requirement twice over: the
server is air-gapped, and the same string is offered as a download so the page
can be filed against the credit application.

The document carries its own Content-Security-Policy. Nothing may be fetched
(default-src 'none'); fonts, the favicon and images are data: URIs; the one
inline script is allowed by its SHA-256 hash, so any script that payload data
managed to inject into the markup would not run.
"""

from __future__ import annotations

import base64
import hashlib

from . import branding, css, js, shell
from .components import esc
from .sections import render_all

# The brief rail starts CLOSED (body.rail-off). The underwriting screen is the
# deliverable; the AI reading is opt-in, and the AI Analysis button in the top
# bar toggles it. Anything calibrated to the width of a card's right-hand
# column -- sections/returns.py _COL_W -- is calibrated to THIS state, because
# it is the one the page loads in.
_DOC = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="icon" href="{favicon}">
<style>
{styles}
</style>
</head>
<body class="rail-off">
{topbar}
<div class="wrap">
{spine}
  <div class="report">
{sections}
  </div>
{rail}
</div>
<script>{script}</script>
</body>
</html>
"""

_CSP = ("default-src 'none'; script-src '{script_hash}'; "
        "style-src 'unsafe-inline'; img-src data:; font-src data:; "
        "base-uri 'none'; form-action 'none'")


def _csp(script: str) -> str:
    digest = hashlib.sha256(script.encode("utf-8")).digest()
    return _CSP.format(
        script_hash="sha256-" + base64.b64encode(digest).decode("ascii"))


def render_page(ctx, title: str = "", ai_panel: bool = True) -> str:
    """Full standalone HTML document for one AECB report.

    ai_panel=False leaves out the AI Analysis button and the brief rail
    altogether -- for deployments with no language model behind them, where
    the panel could only ever say that no brief was generated.
    """
    if not title:
        title = "%s — %s" % (branding.APP_NAME, ctx.subject_id)
    script = js.script(ctx)
    return _DOC.format(
        csp=_csp(script),
        # The subject id inside the title is payload data -- the ONE payload
        # string that does not pass through a section renderer's esc(), so it
        # is escaped here. Same for the favicon URI, defensively.
        title=esc(title),
        favicon=esc(branding.favicon_data_uri()),
        styles=css.stylesheet(),
        topbar=shell.topbar(ctx, ai_panel=ai_panel),
        spine=shell.spine(),
        sections=render_all(ctx),
        rail=shell.rail(ctx) if ai_panel else "",
        script=script,
    )


def clear_cache() -> None:
    """Drop cached CSS/JS so edits show without restarting Streamlit."""
    css.clear_cache()
    js.clear_cache()
