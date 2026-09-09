"""Worst statuses -- two delivered figures shown verbatim, one derived window.

Sources: contractsTotalSummary.WorstStatus24M and summary.Worststatus
(delivered, verbatim), and for the 36-month panel contractsHistory plus each
contract's dated lifetime worst fields (derived -- see
facilities.worst_in_window).

The card carries three panels because FH policy differs by employer segment:
some segments are assessed over 24 months and some over 36, so an underwriter
needs both windows side by side rather than one figure that answers only half
the book.

AECB delivers the 24-month worst status and the life-time count; it delivers
nothing for 36 months. That panel was held open ("To be built") until RRM
settled the defaults (9 Sep 2026): derive it from the delivered conduct
evidence, whole book including closed contracts, and mark it derived --
ALWAYS, because nothing in it is a bureau figure.

Delivered values are printed VERBATIM. Beyond the 36-month derivation, the
only thing this module derives is the colour, and it grades nothing it cannot
recognise: see _known_status().
"""

from __future__ import annotations

from ... import dates
from ...derive import facilities
from .. import components as c

META = {
    "title": "Worst Statuses",
}


def render(ctx, meta) -> str:
    panels = (_delivered_24m(ctx), _derived_36m(ctx), _lifetime_count(ctx))
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


def _derived_36m(ctx):
    """The window AECB does not deliver, derived from what it does deliver.

    Built 9 Sep 2026 with the RRM defaults: every contract in the window
    counts -- closed ones and every role included -- and evidence is the
    monthly conduct rows plus each contract's dated lifetime worst fields
    (see facilities.worst_in_window). A severe status outranks a raw DPD
    number when naming what happened; the bureau's own severity ranking
    grades the result. The `derived` mark renders ALWAYS (RRM instruction):
    nothing in this panel is a bureau figure.
    """
    label = "Worst status &middot; last 36 months"
    worst = facilities.worst_in_window(ctx, facilities.WINDOW_MONTHS)

    if worst is None:
        return _panel(label, _tag_derived(worst),
                      c.empty_state("Not derivable",
                                    "No monthly conduct row and no dated "
                                    "contract worst falls inside the window."),
                      state="absent")

    status = worst["status"]
    if status is not None:
        headline = c.esc(status["label"])
        tone, state = _grade(status)
    else:
        # Delays may still exist without a single rankable status; the
        # sub-line carries them, and the headline claims nothing.
        headline = "Status not reported"
        tone, state = "", "unknown"

    # A window that looks clean but carries statuses the config cannot rank
    # is not provably clean -- unknown, never green.
    if state == "clean" and worst["unknown"]:
        tone, state = "", "unknown"

    return _panel(label, _tag_derived(worst), headline,
                  sub=_delay_line_36(worst), tone=tone, state=state,
                  info=_event_info(worst))


def _delay_line_36(worst):
    """The window's deepest delay, mirroring the 24-month panel's sub-line.

    None means no delay figure was delivered anywhere in the window -- which
    is "Not reported", never zero. Zero renders only when a zero was reported.
    """
    days = worst["max_dpd"]
    if days is None:
        value = '<span class="na">Not reported</span>'
    else:
        value = ('<span class="v%s">%s days</span>'
                 % (" red" if days else "", c.format_number(days)))
    return ('<div class="wsx-sub"><span class="k">Max payment delay '
            '&middot; 36m</span>%s</div>' % value)


def _event_info(worst):
    """Hover on the figure: the event behind the grade, when there is one."""
    if worst["clean"]:
        text = ("No payment delay and no below-normal status in the evidence "
                "for this window. Unreported months carry no information.")
        # The uncoloured figure needs its reason on hover: the window LOOKS
        # clean but carries statuses the config cannot rank, and an ungraded
        # panel with a clean-sounding hover would contradict itself.
        if worst["unknown"]:
            text += (" However, %d delivered status(es) in the window could "
                     "not be ranked, so the window is not graded clean."
                     % worst["unknown"])
        return text
    parts = []
    if worst["status"] is not None and worst["status"]["rank"] < 100:
        parts.append("Worst status: %s" % worst["status"]["label"])
    if worst["max_dpd"]:
        parts.append("deepest delay %s days" % c.format_number(worst["max_dpd"]))
    fac = worst["facility"]
    if fac is not None:
        where = fac.label
        if fac.provider.get("name"):
            where += " (%s)" % fac.provider["name"]
        if fac.closed:
            where += ", closed"
        parts.append("on %s" % where)
    if worst["when"]:
        parts.append(dates.fmt_month_year(worst["when"]))
    if worst["unknown"]:
        parts.append("%d delivered status(es) in the window could not be "
                     "ranked" % worst["unknown"])
    return "; ".join(parts) + "."


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

    "On file" rather than "delivered": the 36-month panel is derived from
    delivered evidence, so the green claim spans both kinds -- but only when
    every panel resolved. Anything absent or ungradable downgrades the pill
    to "Partly reported", never to green.
    """
    states = [p["state"] for p in panels]
    if "severe" in states:
        return c.tag("Severe status on file", "bad")
    if "adverse" in states:
        return c.tag("Adverse history", "warn")
    if "absent" in states or "unknown" in states:
        return c.tag("Partly reported")
    return c.tag("No adverse status on file", "good")


# --- rendering --------------------------------------------------------------

def _panel(window_label, provenance, headline, sub="", tone="", state="clean",
           info=""):
    """One panel. `headline` is either a figure or a whole empty-state block.

    `info` hangs a hover off the figure group -- the derived panel uses it to
    name the event behind the grade.
    """
    if headline.startswith("<"):
        head_html = headline
    else:
        cls = ("wsx-worst %s" % tone).strip()
        info_attr = (' data-info="%s"' % c.attr(info)) if info else ""
        # The figure and its sub-line centre as ONE group, which is why the
        # auto margins live on the wrapper. On .wsx-worst itself each line
        # would centre independently and the two would drift apart as the
        # panel stretches to the tallest of the row.
        # Callers esc() their headline -- which is also what keeps a payload
        # value from ever starting with '<' and hitting the block branch above.
        head_html = ('<div class="wsx-fig"%s><div class="%s">%s</div>%s</div>'
                     % (info_attr, cls, headline, sub))
    win = ("%s %s" % (window_label, provenance)).strip()
    return {
        "state": state,
        "html": ('<div class="wsx-panel"><div class="wsx-win">%s</div>%s</div>'
                 % (win, head_html)),
    }


def _tag_delivered():
    return c.delivered_mark("Delivered by AECB and shown verbatim. "
                            "Not computed here.")


def _tag_derived(worst):
    """The derived chip, carrying method and coverage. Rendered always --
    even over the not-derivable empty state -- at RRM's instruction: whatever
    this panel shows, none of it is a bureau figure."""
    info = ("Derived here, not delivered: AECB sends no 36-month figure. "
            "Computed from contractsHistory monthly conduct plus each "
            "contract's dated lifetime worst fields, across every contract "
            "whose evidence falls in the window -- closed contracts and all "
            "roles included. Graded by the bureau's own severity ranking; a "
            "severe status outranks a raw delay when naming what happened.")
    if worst is not None:
        info += (" Coverage: %d monthly row(s) across %d of %d contract(s); "
                 "unreported months carry no information."
                 % (worst["reported_months"], worst["facilities_covered"],
                    worst["facilities_total"]))
    return ('<span class="prov-mark derived" data-info="%s">derived</span>'
            % c.attr(info))
