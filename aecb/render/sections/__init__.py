"""Section registry -- the one list that defines the report.

Position in SECTIONS determines both the anchor id and the displayed number, so
adding, removing or reordering a section renumbers the report and the spine nav
together. Nothing carries a hard-coded '03' -- which is also why the module
files carry NAMES, not numbers: a numbered filename can only drift from the
position this tuple assigns it.

A nested tuple is a ROW: its sections render side by side as half-width cards
(.sec-pair), numbered in order like any other. Score and worst statuses share
one (user decision, 24 Sep 2026) -- the score dial and the worst conduct read
as one risk-at-a-glance row and measure about the same height; income stays
full width because it loads collapsed and its chart needs the width.

Each module supplies META (title, purpose) and a render(ctx, meta) that passes
meta straight through to components.section_card.
"""

from __future__ import annotations

from . import (
    applications,
    detail,
    facilities,
    identity,
    income,
    returns,
    score,
    worst_status,
)

# Report validity is not here: it lives in the top bar, where a single pill and
# two dates say everything a full section card was spending a card on.
SECTIONS = (
    identity,
    (score, worst_status),
    income,
    returns,
    facilities,
    detail,
    applications,
)


def flat_sections():
    """Every section module in display order, rows unpacked -- the order that
    assigns numbers. Anything numbering sections must walk this, never
    SECTIONS itself (a row is a tuple)."""
    out = []
    for item in SECTIONS:
        out.extend(item if isinstance(item, tuple) else (item,))
    return out


def _meta(index, module):
    """META for a section, with its anchor and number set by position."""
    meta = dict(module.META)
    meta["sid"] = "s%d" % index
    meta["no"] = "%02d" % index
    return meta


def render_all(ctx) -> str:
    """Every section card, in order; a row's cards wrapped side by side."""
    parts, index = [], 1
    for item in SECTIONS:
        if isinstance(item, tuple):
            cards = []
            for module in item:
                cards.append(module.render(ctx, _meta(index, module)))
                index += 1
            parts.append('<div class="sec-pair">%s</div>' % "".join(cards))
        else:
            parts.append(item.render(ctx, _meta(index, item)))
            index += 1
    return "\n".join(parts)


def nav_items():
    """(sid, no, title) for the spine -- same derivation as the cards.

    The title travels with the marker so the spine can name each section on
    hover instead of leaving the reader to decode a number.
    """
    return [("s%d" % i, "%02d" % i, _plain_title(m))
            for i, m in enumerate(flat_sections(), start=1)]


def _plain_title(module) -> str:
    """Section title as plain text -- META carries HTML entities for the card."""
    return (module.META.get("title", "")
            .replace("&amp;", "&").replace("&nbsp;", " "))
