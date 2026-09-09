"""Identity & demographics -- who the applicant is, plus prior identifiers.

Sources: customerInfo, identification, contacts, addresses.

The bureau repeats each fact once per reporting provider and marks superseded
values with a '(Historical)' suffix on the type string. derive.identity collapses
both behaviours into current + prior lists, which map onto the 'N prior' in-cell
expanders this section already had.
"""

from __future__ import annotations

from ... import dates
from ...derive import identity
from .. import components as c

META = {
    "title": "Identity &amp; demographics",
}

_PROVIDER_HINT = (
    "Credit providers each report their own copy of this value, so one fact can "
    "arrive many times. Repeats are collapsed; the badge shows the reporting "
    "provider and how many others reported the same value."
)


def render(ctx, meta) -> str:
    cust = ctx.customer
    if not cust:
        return c.section_card(
            body=c.empty_state("No customer record",
                               "customerInfo is empty in this payload."),
            **meta)

    # Tiles on a six-column grid so the two rows can be split unevenly:
    #
    #   Emirates ID | Passport | Mobile      (three, two columns each)
    #   E-mail      |  Address              (two, three columns each)
    #
    # Row two is sized from what is actually present -- if no e-mail was
    # reported the address takes the whole row rather than sitting at half
    # width beside a gap.
    row_one = [
        _identifier_fact(ctx, "Emirates ID", "EmiratesId", "eidHist", css="c2"),
        _passport_fact(ctx, css="c2"),
        _mobile_fact(ctx, css="c2"),
    ]

    builders = []
    if _has_email(ctx):
        builders.append(_email_fact)
    builders.append(_address_fact)
    span = "c%d" % (6 // len(builders))

    # Two markers the stylesheet cannot work out for itself, both about the
    # shape of row two rather than about any value in it.
    #
    # v-wide: the address is always last and always carries the longest value,
    # so it is the tile that takes the whole row when the grid goes four-up.
    # r2-N: how many tiles row two was built from. Wide enough, row one takes
    # a fourth column by pulling the e-mail up -- but only when there IS an
    # e-mail, or row one would sit at three quarters and leave a hole that
    # does not exist today. CSS could only ask this with :has(), which is
    # Chrome 105, the same floor the fluid scale was written to avoid.
    row_two = []
    for i, build in enumerate(builders):
        last = i == len(builders) - 1
        row_two.append(build(ctx, css=span + (" v-wide" if last else "")))

    body = ('%s<div class="facts id-grid r2-%d">%s</div>'
            % (_name_line(ctx, cust), len(builders),
               "".join(f for f in row_one + row_two if f)))

    return c.section_card(body=body, aside=_residency(cust), **meta)


def _name_line(ctx, cust) -> str:
    """The name, then a quieter line of traits beneath it.

    English and Arabic are the same name in two scripts, so they share a line
    and mirror each other from opposite margins. Gender, age and nationality
    describe that person rather than being part of their name, so they sit on a
    second, smaller line -- which also means a long name in either script
    extends into open space instead of colliding with metadata.
    """
    # The title nests INSIDE the headline span rather than as a flex sibling:
    # .id-name-row carries a 28px gap between children, which would strand the
    # title an inch from the name it belongs to.
    title = cust.get("Title")
    title_html = ('<span class="id-name-ttl">%s</span>' % c.esc(title)
                  ) if title else ""
    name_en = '<span class="id-name-lg">%s%s</span>' % (
        title_html, c.esc(identity.english_name(cust)))
    name_ar = identity.arabic_name(cust)
    ar_html = ('<span class="id-name-ar" dir="rtl" lang="ar">%s</span>'
               % c.esc(name_ar)) if name_ar else ""

    traits = []
    gender = cust.get("Gender")
    if gender:
        traits.append(c.esc(gender))

    dob = cust.get("DOB")
    if dob:
        age = identity.age_at(dob, ctx.report_date)
        traits.append('%s <span class="id-dob">(%s)</span>'
                      % ("%d yrs" % age if age is not None else "age not reported",
                         dates.fmt_short(dob)))

    nationality = _titlecase(cust.get("Nationality"))
    if nationality:
        traits.append(c.esc(nationality))

    traits_html = ""
    if traits:
        traits_html = ('<div class="id-traits">%s</div>'
                       % "".join('<span class="id-trait">%s</span>' % t
                                 for t in traits))

    return ('<div class="id-name-h"><div class="id-name-row">%s%s</div>%s</div>'
            % (name_en, ar_html, traits_html))


def _has_email(ctx) -> bool:
    current, prior = identity.contacts(ctx, "E-mail")
    return bool(current or prior)


def _residency(cust) -> str:
    """UAE residency status.

    Rendered in the brand blue rather than green/amber: on this page red, amber
    and green carry risk meaning, and residency is a fact about the applicant,
    not a risk signal. Colouring it green would imply resident is 'good'.
    """
    resident = cust.get("ResidentFlag")
    if resident is True:
        return c.tag("Resident", "brand")
    if resident is False:
        return c.tag("Non-resident", "brand")
    return c.tag("Residency not reported")


# --- individual cells -------------------------------------------------------

def _split_display(current, prior):
    """(headline entry, everything else, historical-only?).

    The newest-updated CURRENT value is the headline; every other value --
    additional current ones included -- folds behind the chevron. Nothing is
    dropped: a second current passport is exactly the kind of oddity an
    underwriter needs to see, and silently discarding it is information loss.
    """
    if current:
        return current[0], current[1:] + prior, False
    return prior[0], prior[1:], True


def _fold_label(extras) -> str:
    """Chevron caption: 'N prior' only when every folded value is historical."""
    if all(e.historical for e in extras):
        return "%d prior" % len(extras)
    return "%d more" % len(extras)


def _fold_flag(entry) -> str:
    """What a folded value is: superseded, or current but not the newest."""
    return "Historical" if entry.historical else "Also current"


def _identifier_fact(ctx, label, info_type, hist_id, css=""):
    current, prior = identity.identifiers(ctx, info_type)
    if not current and not prior:
        return c.fact(label, '<span class="na">Not reported</span>', css=css)

    entry, extras, hist_only = _split_display(current, prior)
    if hist_only:
        # Only superseded values on file -- say so rather than showing a blank.
        value = ('<span class="mono na">%s</span> <span class="histflag">Historical only</span>'
                 % c.esc(entry.value))
    else:
        value = '<span class="mono">%s</span>%s' % (
            c.esc(entry.value), _provider_badge(entry))

    key = label
    extra = ""
    if extras:
        key += " " + c.chevron(hist_id, _fold_label(extras))
        extra = c.cell_hist(hist_id, [
            c.hist_row(
                '<b>%s</b> <span class="histflag">%s</span>'
                % (c.esc(e.value), _fold_flag(e)),
                _when(e))
            for e in extras
        ])
    return c.fact(key, value, extra, css=css)


def _passport_fact(ctx, css=""):
    """Passport number and its expiry in one tile.

    They were two tiles; the expiry is meaningless without the number it belongs
    to, so it reads as a sub-line rather than as a field of its own.
    """
    current, prior = identity.identifiers(ctx, "Passport")
    if not current and not prior:
        return c.fact("Passport", '<span class="na">Not reported</span>', css=css)

    entry, extras, hist_only = _split_display(current, prior)
    if hist_only:
        value = ('<span class="mono na">%s</span> '
                 '<span class="histflag">Historical only</span>'
                 % c.esc(entry.value))
    else:
        value = '<span class="mono">%s</span>%s' % (
            c.esc(entry.value), _provider_badge(entry))

    key = "Passport"
    if extras:
        key += " " + c.chevron("ppHist", _fold_label(extras))

    sub = _expiry_line(ctx, entry.extra.get("ExpiryDate"))

    extra = ""
    if extras:
        extra = c.cell_hist("ppHist", [
            c.hist_row(
                '<b>%s</b> <span class="histflag">%s</span>%s'
                % (c.esc(e.value), _fold_flag(e),
                   _expiry_note(ctx, e.extra.get("ExpiryDate"))),
                _when(e))
            for e in extras
        ])

    # The expiry sits INSIDE .v, on the value line. It used to be a sibling of
    # .v and .v-sub made it a block, which gave the passport a third line while
    # every other tile on the row has two -- and .facts stretches tiles to the
    # tallest in the row, so one extra line here left dead space in all of them.
    return ('<div class="fact %s"><span class="k">%s</span>'
            '<span class="v">%s%s</span>%s</div>'
            % (css, key, value, sub, extra))


def _expiry_line(ctx, expiry):
    """Sub-line under the passport number."""
    if not expiry:
        return '<span class="v-sub na">Expiry not reported</span>'

    parsed = dates.parse_any(expiry)
    # An expiry behind the report date is a document-validity flag, not decor.
    # The word "Expired" plus a badge also reading "Expired" said it twice, so
    # the line carries the alarm in its own colour instead.
    if parsed and ctx.report_date and parsed < ctx.report_date:
        return ('<span class="v-sub expired">Expired <b>%s</b></span>'
                % dates.fmt_short(expiry))
    return '<span class="v-sub">Expires <b>%s</b></span>' % dates.fmt_short(expiry)


def _expiry_note(ctx, expiry):
    """Folded-row expiry, graded against the report date.

    A folded value can be a CURRENT passport now (see _split_display), so the
    old flat 'expired YYYY' would mislabel a live document. Without a report
    date no claim is made either way -- the year renders neutrally.
    """
    parsed = dates.parse_any(expiry)
    if not parsed:
        return ""
    if ctx.report_date:
        verb = "expired" if parsed < ctx.report_date else "expires"
    else:
        verb = "expiry"
    return " · %s %s" % (verb, parsed.strftime("%Y"))


def _mobile_fact(ctx, css=""):
    current, prior = identity.contacts(ctx, "Mobile Number")
    if not current and not prior:
        return c.fact("Mobile", '<span class="na">Not reported</span>', css=css)

    key = "Mobile " + c.hint(_PROVIDER_HINT)
    if prior:
        key += " " + c.chevron("mobHist", "%d prior" % len(prior))

    rows = "".join(
        '<div class="mob"><span class="num">%s</span>%s<span class="when">%s</span></div>'
        % (c.esc(e.value), _provider_badge(e), _when_short(e))
        for e in current
    ) or '<span class="na">No current number</span>'

    extra = ""
    if prior:
        extra = c.cell_hist("mobHist", [
            c.hist_row(
                '<b>%s</b> <span class="histflag">Historical</span>' % c.esc(e.value),
                _when(e))
            for e in prior
        ])
    return ('<div class="fact %s"><span class="k">%s</span>'
            '<div class="mob-list">%s</div>%s</div>' % (css, key, rows, extra))


def _email_fact(ctx, css=""):
    current, prior = identity.contacts(ctx, "E-mail")
    if not current and not prior:
        return ""

    entry, extras, hist_only = _split_display(current, prior)
    flag = ' <span class="histflag">Historical only</span>' if hist_only else ""

    key = "E-mail"
    extra = ""
    if extras:
        key += " " + c.chevron("mailHist", _fold_label(extras))
        extra = c.cell_hist("mailHist", [
            c.hist_row(
                '<b>%s</b> <span class="histflag">%s</span>'
                % (c.esc(e.value), _fold_flag(e)),
                _when(e))
            for e in extras
        ])
    return c.fact(key,
                  '<span class="mono v-mail">%s</span>%s%s'
                  % (c.esc(entry.value), flag, _provider_badge(entry)),
                  extra, css=css)


def _addr_line(entry) -> str:
    """One address as delivered: what arrived, and a plain statement of what
    did not. entry.value None means the bureau reported a location (emirate,
    PO box, plot) without the address itself -- stated, never blanked.
    """
    if entry.value is not None:
        head = c.esc(entry.value)
    else:
        head = '<span class="na">Address not provided</span>'
    if entry.extra.get("emirate"):
        head += " — " + c.esc(entry.extra["emirate"])
    tail = []
    if entry.extra.get("pobox"):
        tail.append("PO Box %s" % c.esc(entry.extra["pobox"]))
    if entry.extra.get("plot"):
        tail.append("Plot %s" % c.esc(entry.extra["plot"]))
    return head + "".join(" · " + t for t in tail)


def _address_fact(ctx, css=""):
    current, prior = identity.addresses(ctx)
    if not current and not prior:
        return c.fact("Current address", '<span class="na">Not reported</span>',
                      css=css)

    entry = current[0]
    value = ('<span class="v-addr">%s</span>%s'
             % (_addr_line(entry), _provider_badge(entry)))

    key = "Current address " + c.hint(
        "AECB delivers addresses without a type or a historical marker, so the "
        "most recently updated record is shown as current and the rest as prior.")
    extra = ""
    if prior:
        key += " " + c.chevron("addrHist", "%d prior" % len(prior))
        extra = c.cell_hist("addrHist", [
            c.hist_row(_addr_line(e), _when(e))
            for e in prior
        ])
    return ('<div class="fact %s"><span class="k">%s</span>'
            '<span class="v">%s</span>%s</div>' % (css, key, value, extra))


# --- helpers ----------------------------------------------------------------

def _provider_badge(entry):
    badges = c.prov_badges(entry.providers)
    return (" " + badges) if badges else ""


def _when(entry):
    if not entry.updated:
        return ""
    prov = entry.providers[0] if entry.providers else ""
    return "%s · %s" % (prov, dates.fmt_month_year(entry.updated)) if prov \
        else dates.fmt_month_year(entry.updated)


def _when_short(entry):
    return dates.fmt_month_year(entry.updated) if entry.updated else ""


def _titlecase(value):
    """'UNITED ARAB EMIRATES' -> 'United Arab Emirates'."""
    if not value:
        return value
    text = str(value)
    return text.title() if text.isupper() else text
