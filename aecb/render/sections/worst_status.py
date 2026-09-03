"""Worst statuses -- three delivered figures, shown verbatim.

Sources: contractsTotalSummary.WorstStatus24M and summary.Worststatus.

The card carries three panels because FH policy differs by employer segment:
some segments are assessed over 24 months and some over 36, so an underwriter
needs both windows side by side rather than one figure that answers only half
the book.

Only two of the three exist today. AECB delivers a 24-month worst status and a
life-time count; it delivers nothing for 36 months, and how that window should
be computed is an open decision (RRM, Aug 2026). The middle panel therefore
states "To be built" rather than showing a derived figure that might not mean
what the policy means -- on a credit screen a plausible number is worse than an
absent one.

Delivered values are printed VERBATIM. The only thing this module derives from
them is the colour, and it grades nothing it cannot recognise: see
_known_status().
"""

from __future__ import annotations

from .. import components as c

META = {
    "title": "Worst Statuses",
}


def render(ctx, meta) -> str:
    panels = (_delivered_24m(ctx), _pending_36m(), _lifetime_count(ctx))
    body = '<div class="wsx">%s</div>' % "".join(p["html"] for p in panels)
    return c.section_card(body=body, aside=_aside(panels), **meta)


# --- the three panels -------------------------------------------------------

def _delivered_24m(ctx):
    """contractsTotalSummary.WorstStatus24M, printed as delivered.

    contractsTotalSummary only. summary carries a WorstStatus24M too, but in
    the other vocabulary -- a letter code ('U') where this one is display text
    ('Active Payments') -- so falling back to it would make the panel show a
    different kind of value depending on the payload.
    """
    label = "Worst status &middot; last 24 months"
    value = ctx.totals.get("WorstStatus24M")

    if value is None or not str(value).strip():
        return _panel(label, _tag_delivered(),
                      c.empty_state("Not reported",
                                    "contractsTotalSummary carries no 24-month "
                                    "worst status."),
                      state="absent")

    status = _known_status(ctx, value)
    tone, state = _grade(status)
    return _panel(label, _tag_delivered(), c.esc(value), sub=_delay_line(ctx),
                  tone=tone, state=state)


def _delay_line(ctx):
    """contractsTotalSummary.MaxPaymentDelay24M, under the status it qualifies.

    A worst status is a GRADE and carries no magnitude: "Active Payments" says
    the customer is not delinquent, never how late they have ever been. The
    delay answers that, is delivered in the same array, and belongs on the same
    panel rather than a fourth one.

    A delivered 0 is a fact -- never late in the window -- and prints as
    "0 days". Only a missing field is an absence.
    """
    days = ctx.totals.get("MaxPaymentDelay24M")
    if days is None:
        value = '<span class="na">Not reported</span>'
    else:
        try:
            count = int(days)
        except (TypeError, ValueError):
            # Delivered but not a number. Show it as it arrived, ungraded.
            value = '<span class="v">%s</span>' % c.esc(days)
        else:
            value = ('<span class="v%s">%s days</span>'
                     % (" red" if count else "", c.format_number(count)))
    return ('<div class="wsx-sub"><span class="k">Max payment delay '
            '&middot; 24m</span>%s</div>' % value)


def _pending_36m():
    """The window AECB does not deliver, held open rather than filled.

    No provenance mark: neither `delivered` nor `derived` is true of a panel
    that has no figure behind it yet, and marking it either would misstate
    where the number came from once one appears.
    """
    # Kept to one line at the panel's width: this block is the tallest member of
    # the row and therefore sets §05's whole height, so every line it wraps to
    # is a line added to all three panels.
    return _panel("Worst status &middot; last 36 months", "",
                  c.empty_state("To be built",
                                "AECB delivers no 36-month figure. How to "
                                "compute one is undecided."),
                  state="pending")


def _lifetime_count(ctx):
    """summary.Worststatus -- a count over the life of the book.

    Delivered as a number rather than a status code, unlike the 24-month field
    beside it, so it is formatted as a figure and graded on being zero or not.
    A count says how many, never how deep, so a non-zero one cannot be graded
    red here -- it is amber, and §07's per-facility detail carries the depth.
    """
    label = "Life-time worst status count &middot; non-services"
    value = ctx.summary.get("Worststatus")

    if value is None:
        return _panel(label, _tag_delivered(),
                      c.empty_state("Not reported",
                                    "summary carries no life-time worst status "
                                    "count."),
                      state="absent")

    try:
        count = int(value)
    except (TypeError, ValueError):
        # Delivered, but not the number the field is meant to be. Show it as it
        # arrived and grade nothing -- guessing at a tone would be inventing a
        # reading of a value we do not understand.
        return _panel(label, _tag_delivered(), c.esc(value), state="unknown")

    if count:
        return _panel(label, _tag_delivered(), c.format_number(count),
                      tone="amber", state="adverse")
    return _panel(label, _tag_delivered(), c.format_number(count),
                  tone="green", state="clean")


# --- grading ----------------------------------------------------------------

def _known_status(ctx, value):
    """The AECB status this text names, or None when it names none.

    ctx.status() also refuses to grade the unknown (it returns rank None), but
    this panel wants the config row itself and a plain None for "unrecognised",
    so it resolves strictly here -- on code or on label -- and _grade() leaves
    anything unresolved uncoloured. A green tone is a reassurance the bureau
    never gave.
    """
    codes = ctx.status_codes.get("codes") or {}
    text = str(value).strip()
    if text in codes:
        return codes[text]
    for meta in codes.values():
        if (meta.get("label") or "").strip().lower() == text.lower():
            return meta
    return None


def _grade(status):
    """(tone, state) for a resolved status. Unrecognised is left uncoloured."""
    if not status:
        return "", "unknown"
    rank = status.get("rank", 100)
    if rank <= 60:
        return "red", "severe"
    if rank < 100:
        return "amber", "adverse"
    return "green", "clean"


def _aside(panels):
    """The header pill, and it speaks only for the panels that carry a figure.

    The 36-month panel is always pending, so a flat "no delinquency" would
    claim a window nothing has been computed for. The wording is scoped to what
    AECB delivered.
    """
    states = [p["state"] for p in panels]
    if "severe" in states:
        return c.tag("Severe status on file", "bad")
    if "adverse" in states:
        return c.tag("Adverse history", "warn")
    if "absent" in states or "unknown" in states:
        return c.tag("Partly reported")
    return c.tag("No adverse status delivered", "good")


# --- rendering --------------------------------------------------------------

def _panel(window_label, provenance, headline, sub="", tone="", state="clean"):
    """One panel. `headline` is either a figure or a whole empty-state block."""
    if headline.startswith("<"):
        head_html = headline
    else:
        cls = ("wsx-worst %s" % tone).strip()
        # The figure and its sub-line centre as ONE group, which is why the
        # auto margins live on the wrapper. On .wsx-worst itself each line
        # would centre independently and the two would drift apart as the
        # panel stretches to the tallest of the row.
        head_html = ('<div class="wsx-fig"><div class="%s">%s</div>%s</div>'
                     % (cls, headline, sub))
    win = ("%s %s" % (window_label, provenance)).strip()
    return {
        "state": state,
        "html": ('<div class="wsx-panel"><div class="wsx-win">%s</div>%s</div>'
                 % (win, head_html)),
    }


def _tag_delivered():
    return c.delivered_mark("Delivered by AECB and shown verbatim. "
                            "Not computed here.")
