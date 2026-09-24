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
    "title": "Identity &amp; Demographics",
}

_PROVIDER_HINT = (
    "Mobile numbers are listed; older mobiles and all landlines fold behind "
    "their own chevrons. Credit providers each report their own copy of a "
    "number, so one fact can arrive many times. Repeats are collapsed -- "
    "including the same number written with a +971, 971 or 0 prefix, whose "
    "other spellings show on hover. The badge shows the most recent reporter "
    "and how many others reported the same number."
)


def render(ctx, meta) -> str:
    # An empty customerInfo empties the name line only. The tiles read
    # identification, contacts and addresses -- separate arrays that can be
    # full when customerInfo is not, and hiding them was information loss.
    cust = ctx.customer

    # Tiles on a six-column grid so the two rows can be split unevenly:
    #
    #   Emirates ID | Passport | Mobile      (three, two columns each)
    #   E-mail      |  Address              (two, three columns each)
    #
    # Row two is always E-mail + Address. The e-mail tile states "Not
    # reported" rather than vanishing (24 Sep 2026): a missing tile hid the
    # fact that the bureau had no e-mail on file.
    row_one = [
        _document_fact(ctx, "Emirates ID", "EmiratesId", "eidHist", css="c2"),
        _document_fact(ctx, "Passport", "Passport", "ppHist", css="c2"),
        _mobile_fact(ctx, css="c2"),
    ]

    builders = [_email_fact, _address_fact]
    span = "c%d" % (6 // len(builders))

    # Two markers the stylesheet cannot work out for itself, both about the
    # shape of row two rather than about any value in it.
    #
    # v-wide: the address is always last and always carries the longest value,
    # so it is the tile that takes the whole row when the grid goes four-up.
    # r2-N: how many tiles row two was built from. Wide enough, row one takes
    # a fourth column by pulling the e-mail up. Row two is always two tiles
    # now, so this is always r2-2; the marker stays so the stylesheet keeps
    # asking the question explicitly rather than assuming the answer.
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
    if not cust:
        return ('<div class="id-name-h"><div class="id-name-row">'
                '<span class="id-name-lg na">No customer record</span></div>'
                '<div class="id-traits"><span class="id-trait na">customerInfo '
                'is empty in this payload</span><span class="id-trait">%s'
                '</span></div></div>' % _subject_trait(ctx))

    # The title nests INSIDE the headline span rather than as a flex sibling:
    # .id-name-row carries a 28px gap between children, which would strand the
    # title an inch from the name it belongs to. So does the name-parts
    # marker, for the same reason.
    title = cust.get("Title")
    title_html = ('<span class="id-name-ttl">%s</span>' % c.esc(title)
                  ) if title else ""
    variant = identity.name_parts_variant(cust)
    variant_html = (' <span class="attn" data-info="%s">!</span>' % c.attr(
        "Name parts reported as: %s (FirstName + LastName). The headline is "
        "FullNameEN as delivered." % variant)) if variant else ""
    name_en = '<span class="id-name-lg">%s%s%s</span>' % (
        title_html, c.esc(identity.english_name(cust)), variant_html)
    name_ar = identity.arabic_name(cust)
    ar_html = ('<span class="id-name-ar" dir="rtl" lang="ar">%s</span>'
               % c.esc(name_ar)) if name_ar else ""
    if not name_ar:
        # An Arabic name that ARRIVED garbled is stated, not hidden: it points
        # at an encoding loss upstream, which silence would disguise as "no
        # Arabic name sent".
        garbled = identity.arabic_name_unreadable(cust)
        if garbled:
            ar_html = ('<span class="id-name-ar id-ar-bad" data-info="%s">'
                       'Arabic name unreadable in payload</span>' % c.attr(
                           'Delivered as "%s" — no Arabic characters, likely '
                           'lost in encoding before it reached this report.'
                           % garbled))

    traits = []
    gender = cust.get("Gender")
    if gender:
        traits.append(c.esc(gender))

    traits.append(_dob_trait(ctx, cust.get("DOB")))

    nationality = _titlecase(cust.get("Nationality"))
    if nationality:
        traits.append(c.esc(nationality))

    traits.append(_subject_trait(ctx))

    traits_html = ('<div class="id-traits">%s</div>'
                   % "".join('<span class="id-trait">%s</span>' % t
                             for t in traits))

    return ('<div class="id-name-h"><div class="id-name-row">%s%s</div>%s</div>'
            % (name_en, ar_html, traits_html))


def _subject_trait(ctx) -> str:
    """The bureau subject id: the one reference that ties this screen (and a
    printed or downloaded copy of it) back to the AECB record. Stated even
    when absent -- a report that cannot name its subject should say so."""
    cb_id = ctx.cb_subject_id
    if cb_id:
        return 'CB Subject ID <b class="mono id-subj">%s</b>' % c.esc(cb_id)
    return '<span class="na">CB Subject ID not reported</span>'


def _dob_trait(ctx, dob) -> str:
    """Age and date of birth, stating exactly which part is missing.

    Age is computed at the report date. "Age not reported" used to cover
    three different facts; each now says its own: no DOB delivered, a DOB
    that cannot be read (shown verbatim), and a readable DOB with no report
    date to age it against.
    """
    if not dob:
        return '<span class="na">DOB not reported</span>'
    if dates.parse_any(dob) is None:
        return ('<span class="na">DOB %s — unreadable date</span>'
                % c.esc(dob))
    shown = '<span class="id-dob">(%s)</span>' % dates.fmt_short(dob)
    if ctx.report_date is None:
        return 'age unknown — no report date %s' % shown
    return '%d yrs %s' % (identity.age_at(dob, ctx.report_date), shown)


def _residency(cust) -> str:
    """UAE residency status.

    Rendered in the brand blue rather than green/amber: on this page red, amber
    and green carry risk meaning, and residency is a fact about the applicant,
    not a risk signal. Colouring it green would imply resident is 'good'.
    """
    resident, raw = identity.resident_flag(cust)
    if resident is True:
        return c.tag("Resident", "brand")
    if resident is False:
        return c.tag("Non-resident", "brand")
    if raw is not None:
        # Something arrived that is not a recognised flag: show it, never
        # claim nothing was reported.
        return ('<span class="tag" data-info="%s">Residency: %s</span>'
                % (c.attr("ResidentFlag delivered as %r — not a recognised "
                          "value." % raw), c.esc(raw)))
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


def _document_fact(ctx, label, info_type, hist_id, css=""):
    """An identity document tile -- Emirates ID or Passport: the number and
    its expiry in one tile.

    Number and expiry were once two tiles; the expiry is meaningless without
    the number it belongs to, so it reads on the value line. Both documents
    use this one builder, so the Emirates ID shows its expiry exactly as the
    passport does (24 Sep 2026 -- it was read and never shown).
    """
    current, prior = identity.identifiers(ctx, info_type)
    if not current and not prior:
        return c.fact(label, '<span class="na">Not reported</span>', css=css)

    entry, extras, hist_only = _split_display(current, prior)
    if hist_only:
        # Only superseded values on file -- say so rather than showing a blank.
        value = ('%s <span class="histflag">Historical only</span>'
                 % _value_html(entry, "mono na"))
    else:
        value = _value_html(entry, "mono") + _provider_badge(entry)

    key = label
    extra = ""
    if extras:
        key += " " + c.chevron(hist_id, _fold_label(extras))
        extra = c.cell_hist(hist_id, [
            c.hist_row(
                '<b>%s</b> <span class="histflag">%s</span>%s%s'
                % (_value_html(e), _fold_flag(e),
                   _expiry_note(ctx, e.extra.get("ExpiryDate")),
                   _expiry_conflict(e)),
                _when(e))
            for e in extras
        ])

    sub = _expiry_line(ctx, entry.extra.get("ExpiryDate"), _expiry_conflict(entry))

    # The expiry sits INSIDE .v, on the value line. It used to be a sibling of
    # .v and .v-sub made it a block, which gave the tile a third line while
    # every other tile on the row has two -- and .facts stretches tiles to the
    # tallest in the row, so one extra line here left dead space in all of them.
    return ('<div class="fact %s"><span class="k">%s</span>'
            '<span class="v">%s%s</span>%s</div>'
            % (css, key, value, sub, extra))


def _value_html(entry, cls=""):
    """A value as most recently reported. Other delivered spellings of the
    same value (document dashes and spacing, mobile +971 / 971 / 0 prefixes)
    ride in the hover -- grouped, never dropped."""
    attrs = ' class="%s"' % cls if cls else ""
    if entry.alt_spellings:
        attrs += ' data-info="%s"' % c.attr(
            "Also reported as: " + ", ".join(entry.alt_spellings))
    return '<span%s>%s</span>' % (attrs, c.esc(entry.value))


def _expiry_conflict(entry):
    """An amber '!' when providers disagree on the expiry date; '' otherwise.

    The date shown is the most recent reporter's; the hover names every other
    date and who reported it, so a contested expiry is never presented as
    settled.
    """
    dated = entry.extra_by_recency("ExpiryDate")
    if len(dated) < 2:
        return ""
    shown, others = dated[0], dated[1:]
    info = ("Providers disagree on this expiry. Shown: %s (%s, most recent). "
            "Also reported: %s." % (
                dates.fmt_short(shown[0]), ", ".join(shown[1]) or "provider not named",
                "; ".join("%s (%s)" % (dates.fmt_short(v), ", ".join(p) or
                                       "provider not named")
                          for v, p in others)))
    return ' <span class="attn" data-info="%s">!</span>' % c.attr(info)


def _expiry_line(ctx, expiry, conflict=""):
    """The expiry on a document tile's value line (+ disagreement mark)."""
    if not expiry:
        return '<span class="v-sub na">Expiry not reported</span>'

    parsed = dates.parse_any(expiry)
    # An expiry behind the report date is a document-validity flag, not decor.
    # The word "Expired" plus a badge also reading "Expired" said it twice, so
    # the line carries the alarm in its own colour instead.
    if parsed and ctx.report_date and parsed < ctx.report_date:
        return ('<span class="v-sub expired">Expired <b>%s</b>%s</span>'
                % (dates.fmt_short(expiry), conflict))
    return ('<span class="v-sub">Expires <b>%s</b>%s</span>'
            % (dates.fmt_short(expiry), conflict))


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
    """The Phone tile: current mobiles listed, prior mobiles and every
    landline folded.

    Landlines (contacts 'Phone Number') joined this tile on 24 Sep 2026 --
    they were the one identity array never shown. They sit behind their own
    chevron so the grid does not change: collapsed, they take no height.
    """
    current, prior = identity.contacts(ctx, "Mobile Number")
    land_cur, land_prior = identity.contacts(ctx, "Phone Number")
    landlines = land_cur + land_prior
    if not current and not prior and not landlines:
        return c.fact("Phone", '<span class="na">Not reported</span>', css=css)

    key = "Phone " + c.hint(_PROVIDER_HINT)
    if prior:
        key += " " + c.chevron("mobHist", "%d prior" % len(prior))
    if landlines:
        key += " " + c.chevron("landHist", "%d landline" % len(landlines))

    if current:
        rows = "".join(
            '<div class="mob">%s%s%s<span class="when">%s</span></div>'
            % (_value_html(e, "num"), _not_mobile_flag(e), _provider_badge(e),
               _when_short(e))
            for e in current)
    elif prior:
        rows = '<span class="na">No current mobile</span>'
    else:
        rows = '<span class="na">Mobile not reported</span>'

    extra = ""
    if prior:
        extra += c.cell_hist("mobHist", [
            c.hist_row(
                '<b>%s</b> <span class="histflag">Historical</span>%s'
                % (_value_html(e), _not_mobile_flag(e)),
                _when(e))
            for e in prior
        ])
    if landlines:
        extra += c.cell_hist("landHist", [
            c.hist_row(
                '<b>%s</b> <span class="histflag">%s</span>%s'
                % (_value_html(e), "Historical" if e.historical else "Current",
                   _landline_flag(e)),
                _when(e))
            for e in landlines
        ])
    return ('<div class="fact %s"><span class="k">%s</span>'
            '<div class="mob-list">%s</div>%s</div>' % (css, key, rows, extra))


def _landline_flag(entry) -> str:
    """What a Phone Number contact really is, when it is not a landline.

    The bureau files some mobiles under Phone Number (archive: 971505141154).
    It stays where the bureau put it, with a note -- moving it silently would
    rewrite the payload.
    """
    if identity.is_uae_landline(entry.value):
        return ""
    if identity.is_uae_mobile(entry.value):
        return (' <span class="histflag" data-info="%s">mobile number</span>'
                % c.attr("Delivered as a Phone Number, but it reads as a UAE "
                         "mobile (5 + 8 digits). Shown where the bureau filed "
                         "it."))
    return (' <span class="histflag" data-info="%s">not a valid UAE number'
            '</span>' % c.attr(
                "Neither a UAE landline (area code + 7 digits) nor a UAE mobile "
                "after a +971, 971 or 0 prefix. This may be a placeholder, a "
                "keying error or a foreign number. Shown exactly as delivered."))


def _not_mobile_flag(entry) -> str:
    """A grey flag on a number that does not read as a UAE mobile.

    Placeholders (971999999999), short keyings (97150000000) and foreign
    numbers otherwise sit in the list looking exactly like real mobiles. The
    number itself is still shown as delivered -- the flag only says what it
    is not.
    """
    if identity.is_uae_mobile(entry.value):
        return ""
    return (' <span class="histflag" data-info="%s">not a valid UAE mobile'
            '</span>' % c.attr(
                "Not a UAE mobile format: after a +971, 971 or 0 prefix a UAE "
                "mobile is 9 digits starting with 5. This may be a "
                "placeholder, a keying error or a foreign number. Shown "
                "exactly as delivered."))


def _email_fact(ctx, css=""):
    current, prior = identity.contacts(ctx, "E-mail")
    if not current and not prior:
        return c.fact("E-mail", '<span class="na">Not reported</span>', css=css)

    entry, extras, hist_only = _split_display(current, prior)
    flag = ' <span class="histflag">Historical only</span>' if hist_only else ""

    key = "E-mail"
    extra = ""
    if extras:
        key += " " + c.chevron("mailHist", _fold_label(extras))
        extra = c.cell_hist("mailHist", [
            c.hist_row(
                '<b>%s</b> <span class="histflag">%s</span>%s'
                % (_value_html(e), _fold_flag(e), _not_email_flag(e)),
                _when(e))
            for e in extras
        ])
    return c.fact(key,
                  '%s%s%s%s'
                  % (_value_html(entry, "mono v-mail"), _not_email_flag(entry),
                     flag, _provider_badge(entry)),
                  extra, css=css)


def _not_email_flag(entry) -> str:
    """A grey flag on a value that is not shaped like an e-mail (NA, NOEMAIL,
    x@x). The value itself is still shown as delivered."""
    if identity.is_email(entry.value):
        return ""
    return (' <span class="histflag" data-info="%s">not a valid e-mail'
            '</span>' % c.attr(
                "Not shaped like an e-mail address (one @ and a dotted "
                "domain). This may be a placeholder or a keying error. Shown "
                "exactly as delivered."))


def _addr_line(entry) -> str:
    """One address as delivered: what arrived, and a plain statement of what
    did not. entry.value None means the bureau reported a location (emirate,
    PO box, plot) without the address itself -- stated, never blanked.

    The hover carries whatever else was delivered for this address: other
    spellings it was grouped from, and the ArabicAddress when it holds real
    Arabic. A delivered AddressType follows as a small tag. Both only when
    delivered.
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
    line = head + "".join(" · " + t for t in tail)

    info = []
    if entry.alt_spellings:
        info.append("Also reported as: " + "; ".join(entry.alt_spellings))
    arabic = entry.extra.get("arabic")
    if arabic and identity.has_arabic(arabic):
        info.append("Arabic address: %s" % arabic)
    if info:
        line = '<span data-info="%s">%s</span>' % (c.attr(" · ".join(info)), line)
    if entry.extra.get("type"):
        line += ' <span class="histflag">%s</span>' % c.esc(entry.extra["type"])
    return line


def _address_fact(ctx, css=""):
    """The latest address. "Latest", not "current": AECB sends no current /
    historical marker for addresses, so the newest DateOfLastUpdate is an
    inference -- the label says only what the payload supports, and the
    date that decided it sits on the value line."""
    current, prior = identity.addresses(ctx)
    if not current and not prior:
        return c.fact("Latest address", '<span class="na">Not reported</span>',
                      css=css)

    entry = current[0]
    when = ('<span class="v-sub">Updated <b>%s</b></span>'
            % dates.fmt_month_year(entry.updated)) if entry.updated else ""
    value = ('<span class="v-addr">%s</span>%s%s'
             % (_addr_line(entry), _provider_badge(entry), when))

    key = "Latest address " + c.hint(
        "AECB delivers addresses without a current or historical marker, so "
        "the most recently updated record is shown as the latest and the rest "
        "as prior. Spellings that differ only in case, punctuation or spacing "
        "count as one address.")
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
    """'B09 · May 2026': the most recent reporter and ITS OWN update date.

    Pairing the first provider in the array with the newest date from any
    provider once named B02 beside a date only T03 had reported.
    """
    prov = entry.providers[0] if entry.providers else ""
    when = (entry.date_of(prov) if prov else None) or entry.updated
    if not when:
        return prov
    return ("%s · %s" % (prov, dates.fmt_month_year(when)) if prov
            else dates.fmt_month_year(when))


def _when_short(entry):
    return dates.fmt_month_year(entry.updated) if entry.updated else ""


_SMALL_WORDS = ("and", "of", "the")


def _titlecase(value):
    """'UNITED ARAB EMIRATES' -> 'United Arab Emirates'.

    Joining words stay lower case after the first word, so 'BOSNIA AND
    HERZEGOVINA' reads 'Bosnia and Herzegovina', not '... And ...'.
    """
    if not value:
        return value
    text = str(value)
    if not text.isupper():
        return text
    words = text.title().split(" ")
    return " ".join(w.lower() if i and w.lower() in _SMALL_WORDS else w
                    for i, w in enumerate(words))
