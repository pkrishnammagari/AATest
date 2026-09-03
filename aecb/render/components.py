"""Shared HTML primitives.

The section-card markup exists here and nowhere else, so the nine sections
cannot drift apart. Everything returns an HTML string.

esc() is applied to any value that could come from the payload. Bureau data is
not trusted input for markup purposes -- a stray '<' in a provider name or an
Arabic mojibake run should render as text, not break the document.
"""

from __future__ import annotations

_ESCAPES = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
)


def esc(value, dash: str = "—") -> str:
    """Escape a payload value for use in markup. None becomes an em dash."""
    if value is None:
        return dash
    text = str(value)
    if not text.strip():
        return dash
    for a, b in _ESCAPES:
        text = text.replace(a, b)
    return text


def attr(value) -> str:
    """Escape for an HTML attribute (data-hint, data-info, title)."""
    return esc(value, dash="").replace("'", "&#39;")


# --- section card -----------------------------------------------------------

def section_card(sid, no, title, purpose="", body="", aside="",
                 collapsible=False, closed=False) -> str:
    """One numbered report section.

    collapsible adds the fold toggle and wraps `body` in .sec-body, which is
    what the JS in js.py hooks. closed starts it folded.
    """
    classes = ["sec"]
    if collapsible:
        classes.append("coll")
        if closed:
            classes.append("closed")

    purpose_html = ('<p class="sec-purpose">%s</p>' % purpose) if purpose else ""

    aside_parts = []
    if aside:
        aside_parts.append(aside)
    if collapsible:
        aside_parts.append(
            '<button class="sec-toggle" aria-expanded="%s">▾</button>'
            % ("false" if closed else "true")
        )
    aside_html = (
        '<div class="sec-aside">%s</div>' % "".join(aside_parts)
    ) if aside_parts else ""

    inner = ('<div class="sec-body">%s</div>' % body) if collapsible else body

    return (
        '<section class="{cls}" id="{sid}">'
        '<div class="sec-head">'
        '<span class="sec-no">{no}</span>'
        '<div class="sec-htxt"><h2 class="sec-title">{title}</h2>{purpose}</div>'
        '{aside}'
        '</div>'
        '{inner}'
        '</section>'
    ).format(cls=" ".join(classes), sid=sid, no=no, title=title,
             purpose=purpose_html, aside=aside_html, inner=inner)


# --- small pieces -----------------------------------------------------------

def tag(text, kind="") -> str:
    """Status pill for a section header. kind: '' | 'good' | 'warn' | 'bad'."""
    cls = "tag %s" % kind if kind else "tag"
    return '<span class="%s">%s</span>' % (cls.strip(), text)


def hint(text) -> str:
    """The small 'i' bubble with a hover explanation."""
    return '<span class="hint" data-hint="%s">i</span>' % attr(text)


def fact(key, value, extra="", css="") -> str:
    """A labelled cell in the .facts grid (section 01, identity).

    extra is appended inside the cell, after the value -- used for the
    in-cell history expanders.
    """
    cls = "fact %s" % css if css else "fact"
    return (
        '<div class="%s"><span class="k">%s</span>'
        '<span class="v">%s</span>%s</div>'
    ) % (cls.strip(), key, value, extra)


def chevron(target_id, label) -> str:
    """The 'N prior ▾' in-cell expander toggle. Pairs with cell_hist()."""
    return '<span class="chevron" data-exp="%s">%s ▾</span>' % (target_id, label)


def cell_hist(target_id, rows) -> str:
    """Hidden history block revealed by the matching chevron."""
    return '<div class="cell-hist" id="%s">%s</div>' % (target_id, "".join(rows))


def hist_row(text, when="") -> str:
    when_html = ('<span class="when">%s</span>' % when) if when else ""
    return '<div class="hist-row"><span>%s</span>%s</div>' % (text, when_html)


def prov_badge(code, kind="bank") -> str:
    """Provider chip. kind: 'bank' | 'tel' | 'onus'."""
    cls = "prov-badge" if kind == "bank" else "prov-badge %s" % kind
    return '<span class="%s">%s</span>' % (cls, esc(code, dash="?"))


def prov_badges(codes) -> str:
    """The reporting providers for one fact: first as a chip, rest behind '+N'.

    The payload repeats a fact once per provider, so most values arrive with a
    set rather than a single source. Naming them all inline would bury the
    value; the count carries that they exist and the hover names them.

    Shared by sections 01 and 03 so a provider set looks the same wherever it
    appears. Empty when nothing was reported -- the caller decides what to show
    in its place, since 'no provider' is not the same fact everywhere.
    """
    codes = [c for c in (codes or []) if c]
    if not codes:
        return ""
    first = str(codes[0])
    badge = prov_badge(first, "tel" if first.upper().startswith("T") else "bank")
    if len(codes) > 1:
        badge += ('<span class="prov-more" data-info="%s">+%d</span>'
                  % (attr("Also reported by: " + ", ".join(str(x) for x in codes[1:])),
                     len(codes) - 1))
    return badge


def aed(amount, decimals=0) -> str:
    """'AED 12,345' with the currency mark styled down."""
    if amount is None:
        return "—"
    try:
        number = float(amount)
    except (TypeError, ValueError):
        return esc(amount)
    return '<span class="aed">AED</span>%s' % format_number(number, decimals)


def format_number(value, decimals=0) -> str:
    """Thousands-separated, fixed decimals. '—' when there is no value."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return esc(value)
    return "{:,.{d}f}".format(number, d=decimals)


def delivered_mark(info) -> str:
    """The 'delivered' provenance chip, shared by every section that shows one.

    `info` states exactly WHAT was delivered -- the claim is only as good as
    its scope, so every call site writes its own wording.
    """
    return ('<span class="prov-mark delivered" data-info="%s">delivered</span>'
            % attr(info))


def dispute_tag(disputed) -> str:
    """FlagOpenDispute as a tag; '' when the bureau did not report the flag.

    Silence must not be read as 'no dispute' -- the tag renders only when
    there is something to render. `disputed` is True / False / None.
    """
    if disputed is None:
        return ""
    return tag("Open dispute", "bad") if disputed else tag("No dispute")


def empty_state(message, detail="") -> str:
    """Shown when a section has no rows to render.

    Deliberately distinguishes 'nothing to report' from 'section not returned' --
    the caller passes whichever is true, because the two mean opposite things to
    an underwriter.
    """
    detail_html = ('<div class="es-detail">%s</div>' % detail) if detail else ""
    return ('<div class="empty-state"><div class="es-msg">%s</div>%s</div>'
            % (message, detail_html))
