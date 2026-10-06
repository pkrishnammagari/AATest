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

from .. import runtime
from . import analysis, branding, css, js, shell
from .components import esc
from .sections import render_all

# body.rail-off is the layout-state class every measured geometry is
# calibrated to; report.css computes the fluid scale (--f) and the density
# step on it, so it is always set. The AI Analysis view is a separate
# full-width section that REPLACES the report while body.analysis-on is set
# -- toggled by the top-bar button in report.js, or on load when the host
# asks for it (analysis_open) so a re-render after each generated block
# reopens where the user was.
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
<body class="rail-off{open}">
{topbar}
<div class="wrap">
{spine}
  <div class="report">
{sections}
  </div>
</div>
{analysis}
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


def render_page(ctx, ai_mode: str = runtime.AI_LIVE,
                analysis_open: bool = False) -> str:
    """Full standalone HTML document for one AECB report.

    ai_mode is the AI panel's state (aecb/runtime.py):
      live         the AI Analysis button and the analysis view, drawing
                   ctx.analysis when the host attached one;
      coming_soon  the same button, muted and badged, opening a view that
                   says the analysis is being built -- never findings;
      off          neither the button nor the view.
    analysis_open=True loads the page with the analysis view showing (the
    host sets it while an analysis exists, so a re-render keeps the user in
    the view). An unknown mode raises ValueError rather than guessing.
    """
    if ai_mode not in runtime.AI_MODES:
        raise ValueError("unknown AI panel mode %r" % (ai_mode,))
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
        topbar=shell.topbar(ctx, ai_mode),
        spine=shell.spine(),
        sections=render_all(ctx),
        analysis=analysis.view(ctx, ai_mode),
        open=" analysis-on" if analysis_open and ai_mode != runtime.AI_OFF
        else "",
        script=script,
    )


def clear_cache() -> None:
    """Drop cached CSS/JS so edits show without restarting Streamlit."""
    css.clear_cache()
    js.clear_cache()
