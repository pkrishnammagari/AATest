"""Section registry -- the one list that defines the report.

Position in SECTIONS determines both the anchor id and the displayed number, so
adding, removing or reordering a section renumbers the report and the spine nav
together. Nothing carries a hard-coded '03' -- which is also why the module
files carry NAMES, not numbers: a numbered filename can only drift from the
position this tuple assigns it.

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
    score,
    income,
    returns,
    worst_status,
    facilities,
    detail,
    applications,
)


def _meta(index, module):
    """META for a section, with its anchor and number set by position."""
    meta = dict(module.META)
    meta["sid"] = "s%d" % index
    meta["no"] = "%02d" % index
    return meta


def render_all(ctx) -> str:
    """Every section card, in order."""
    return "\n".join(module.render(ctx, _meta(i, module))
                     for i, module in enumerate(SECTIONS, start=1))


def nav_items():
    """(sid, no, title) for the spine -- same derivation as the cards.

    The title travels with the marker so the spine can name each section on
    hover instead of leaving the reader to decode a number.
    """
    return [("s%d" % i, "%02d" % i, _plain_title(m))
            for i, m in enumerate(SECTIONS, start=1)]


def _plain_title(module) -> str:
    """Section title as plain text -- META carries HTML entities for the card."""
    return (module.META.get("title", "")
            .replace("&amp;", "&").replace("&nbsp;", " "))
