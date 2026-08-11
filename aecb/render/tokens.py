"""Colour and type schema -- the single source of truth for the report's look.

Started as the mockup's :root block; the illustrative teal brand has since been
replaced throughout by the Finance House blue below, so the palette is now the
product's rather than the mockup's. Every value here is emitted as a CSS custom
property by root_block(); report.css refers to them only as var(--name) and
hard-codes no colour of its own.

Anything that needs a colour from Python (chart series, SVG fills, the heatmap
DPD ramp) reads it from TOKENS rather than repeating the hex.
"""

from __future__ import annotations

TOKENS = {
    # --- surfaces -----------------------------------------------------------
    "canvas": "#EDF0F4",
    "surface": "#FFFFFF",
    "surface-2": "#F5F7FA",
    "surface-3": "#EDF1F5",

    # --- ink / rules --------------------------------------------------------
    "ink": "#141E2C",
    "ink-2": "#57697C",
    "ink-3": "#93A1AF",
    "ink-4": "#B4BFCA",
    "line": "#DCE2E9",
    "line-2": "#C7D0DA",

    # --- Finance House brand ------------------------------------------------
    # #00426A is the Finance House corporate blue. The other four are derived
    # from it -- darkened for pressed states, mixed with white for the wash and
    # hairline. Everything blue on the page resolves through these five tokens.
    #
    # Measured contrast: white on brand 10.6:1, white on dark 14.5:1, brand as
    # ink on wash 8.7:1 -- all comfortably past WCAG AA.
    "fh-blue": "#00426A",
    "fh-blue-d": "#002C46",       # gradient foot / hover / pressed state
    # The brand is dark enough to serve as its own text colour on the wash, so
    # ink and brand are deliberately the same value rather than a second shade.
    "fh-blue-ink": "#00426A",
    "fh-blue-wash": "#E3EAEF",
    "fh-blue-line": "#B2C6D2",

    # --- brand + semantic ---------------------------------------------------
    # The mockup's teal is deliberately GONE. It was the illustrative brand, and
    # everything it dressed -- the section-toggle and hint hovers, .cite,
    # .ai-mark, .stl-more, the delivered provenance mark -- now resolves through
    # the fh-blue five above. Do not reintroduce a teal token: a second brand
    # colour beside Finance House blue reads as a meaning the page is not
    # carrying. The one surviving teal HUE is cat-c below, which is a member of
    # the categorical accent set rather than a brand.
    "brass": "#9A7B3F",
    "brass-wash": "#F1EADA",
    "red": "#B02430",
    "red-wash": "#F8E6E7",
    "amber": "#B37516",
    "amber-wash": "#FBEEDB",
    "green": "#1F7A52",
    "green-wash": "#E4F1EA",
    "green-mid": "#4FA37D",

    # --- semantic wash triads -----------------------------------------------
    # Each status colour is used as a set: solid, pale wash, hairline border and
    # a darkened on-wash text colour. Tags, chips, phase pills, severity badges
    # and status cells all draw from these, so they belong in the palette.
    "green-line": "#C6E3D3", "green-ink": "#155e3f",
    "amber-line": "#EBD3A6", "amber-ink": "#8a5610",
    "red-line": "#E6C4C7",   "red-ink": "#8f1a24",
    # The brand's own triad is fh-blue-wash / fh-blue-line / fh-blue-ink above.

    # --- DPD severity ramp (section 08 heatmap) -----------------------------
    "dpd0": "#3D9C74",   # current, 0 DPD
    "dpd1": "#E7B84B",   # 1-29
    "dpd2": "#DE8C3A",   # 30-59
    "dpd3": "#C85C33",   # 60-89
    "dpd4": "#A81F28",   # 90+
    "dpd-none": "#E9EEF2",    # pre-open / not reported
    "dpd-closed": "#AEB9C4",  # after closure

    # --- contract-category accents ------------------------------------------
    # Promoted out of .fac-cat / .hm-gc so category colour is addressable from
    # Python when building the facility cards and heatmap group heads. Those
    # rules now refer to these tokens rather than reaching past them, which is
    # what the promotion was for.
    #
    # This is a CATEGORICAL set, not brand and not risk: five hues chosen to be
    # told apart at 17px, carrying no ordering. It is the one place a colour on
    # this page is neither Finance House blue nor red/amber/green -- and the
    # reason cat-c stays teal rather than following the brand pass is that it
    # has to stay distinguishable from cat-i, which is already blue.
    "cat-i": "#3f6d8c",   # Installments
    "cat-c": "#0C6B73",   # Credit cards
    "cat-n": "#7a5ea0",   # Non-installments
    "cat-s": "#9A7B3F",   # Services (same hue as brass)
    "cat-x": "#8a97a4",   # Closed

    # --- elevation ----------------------------------------------------------
    "shadow": "0 1px 2px rgba(20,30,44,.03),0 1px 3px rgba(20,30,44,.05)",
    "shadow-lg": "0 10px 34px rgba(20,30,44,.13)",

    # --- geometry -----------------------------------------------------------
    "r": "12px",
    "r-sm": "8px",
    "spine-w": "52px",
}

# Font stacks. Every family falls back to a system face so the page stays
# legible if the vendored woff2 bundle is ever missing.
FALLBACK = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
FONT_DISPLAY = "'Archivo', %s" % FALLBACK       # headings, figures  500-800
FONT_BODY = "'IBM Plex Sans', %s" % FALLBACK    # body               400-700
FONT_MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
FONT_ARABIC = "'IBM Plex Sans Arabic', %s" % FALLBACK

TOKENS["font-display"] = FONT_DISPLAY
TOKENS["font-body"] = FONT_BODY
TOKENS["font-mono"] = FONT_MONO
TOKENS["font-arabic"] = FONT_ARABIC


def root_block() -> str:
    """TOKENS rendered as the :root custom-property block."""
    lines = ["  --%s: %s;" % (name, value) for name, value in TOKENS.items()]
    return ":root{\n%s\n}" % "\n".join(lines)


def token(name: str) -> str:
    """Raw value for use in Python-generated SVG/inline styles.

    Prefer var(--name) in CSS; use this only where a literal is required
    (SVG stroke/fill attributes, which do not accept custom properties in all
    rendering paths).
    """
    try:
        return TOKENS[name]
    except KeyError:
        raise KeyError("unknown design token %r -- add it to tokens.TOKENS" % name)
