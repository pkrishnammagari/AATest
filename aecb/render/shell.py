"""Page chrome: the sticky top bar, the left spine nav, and the brief rail.

Report validity lives in the top bar rather than in a section card. It is one
status and two dates -- a whole card was spending a screenful on a single line
of information, and the status matters on every section, not just at the top of
the scroll.

The bar reads left to right as one sentence: is it valid, when was it pulled,
how far through the window is it, when does it lapse.

Customer identity belongs to section 01 and the score to section 02, so neither
is repeated here. Application context (product, amount, tenor, DSR) has no
source in an AECB payload at all.
"""

from __future__ import annotations

import datetime

from .. import dates
from ..derive import scoring
from . import branding
from . import brief as render_brief
from . import components as c
from .sections import nav_items


def topbar(ctx) -> str:
    return """
<header class="topbar">
  <div class="brand">
    {mark}
    <div class="brand-t">{name}</div>
  </div>
  <div class="tb-sep"></div>
  {validity}
  <div class="tb-spacer"></div>
  <button class="brief-btn" id="briefBtn"><span class="bb-ic">◧</span> AI Analysis</button>
</header>
""".format(mark=branding.brand_mark(), name=branding.APP_NAME,validity=_validity_strip(ctx))


def _date_label(v) -> str:
    """The name of the date that dated the report, as the bar labels it.

    Named after its source rather than a generic "Generated": the pull date
    is the ladder's weaker fallback, and the reader should see that without
    hovering. The meter hover uses the same word.
    """
    return "Pull date" if v["basis"] == "pull" else "Enquiry date"


def _basis_text(v):
    """What dated the report, for the date-field and meter hovers.

    The ladder (10 Sep 2026): the latest-dated sectionStatus enquiry first,
    the warehouse pull date as a last resort only.
    """
    if v["basis"] == "enquiry":
        return ("Dated by the latest sectionStatus enquiry — %s, Last "
                "EnquiryDate." % (v["report_type"] or "type not reported"))
    if v["basis"] == "pull":
        return ("Dated by score.DataPullDate — sectionStatus delivered no "
                "usable enquiry date, so the warehouse pull date is the last "
                "resort.")
    return ""


def _scope_chip(v):
    """The enquiry scope, always stated: what the bureau was actually asked.

    The latest-dated sectionStatus row's ReportType and EnquiryType render
    verbatim as chips -- no hard-coded product vocabulary (10 Sep 2026), so
    a product the bureau adds later reaches the bar without a code change.
    An empty sectionStatus still warns: which products were pulled cannot be
    established, and the absence of a bounced-cheque product is graded by
    the returns section, not here. So does a row with a blank ReportType -- the one
    fact that says what kind of report this is. A blank EnquiryType simply
    drops its chip.

    The ReportType hover carries the delivered EnquiryNo, the bureau's own
    reference for the enquiry. When no row was dated, both hovers say the
    scope came from the first row while DataPullDate dated the report --
    the chips and the date may then describe different events.
    """
    if v["scope_source"] is None:
        return ('<span class="tb-scope warn" data-info="sectionStatus is '
                'empty — which products were pulled cannot be established.">'
                'Enquiry scope not reported</span>')

    # Which row the chips describe: the latest-dated enquiry, or -- when no
    # row is dated -- the first row, while DataPullDate dates the report.
    which, note = "the latest enquiry", ""
    if v["scope_source"] == "first":
        which = "the first sectionStatus row"
        note = (" No enquiry was dated, so the report is dated by "
                "score.DataPullDate instead.")

    # The EnquiryType chip is the first thing the bar sheds on a laptop-width
    # window (report.css), so its value also rides in the ReportType hover --
    # hidden from the bar, never lost from the page.
    chips = []
    if v["report_type"]:
        ref = (" Enquiry no. %s." % v["enquiry_no"]) if v["enquiry_no"] else ""
        etype = (" Enquiry type: %s." % v["enquiry_type"]) \
            if v["enquiry_type"] else ""
        chips.append('<span class="tb-scope" data-info="%s">%s</span>' % (
            c.attr("sectionStatus ReportType of %s — the product the "
                   "bureau was asked for.%s%s%s" % (which, ref, etype, note)),
            c.esc(v["report_type"])))
    else:
        chips.append('<span class="tb-scope warn" data-info="%s">Report type '
                     'not reported</span>' % c.attr(
                         "sectionStatus delivered an enquiry with no "
                         "ReportType — which product was pulled cannot be "
                         "established." + note))
    if v["enquiry_type"]:
        chips.append('<span class="tb-scope tb-scope-et" data-info="%s">%s</span>' % (
            c.attr("sectionStatus EnquiryType of %s.%s" % (which, note)),
            c.esc(v["enquiry_type"])))
    return "".join(chips)


def _pill(cls, label, info):
    return ('<span class="tb-valid%s" data-info="%s"><span class="pd"></span>'
            '%s</span>' % (" " + cls if cls else "", c.attr(info), label))


def _validity_pill(v):
    """The status pill and its hover, one per scoring.validity state.

    The window in the hover is read from config, never typed in, so the
    explanation cannot drift from the rule it explains.
    """
    state, window = v["state"], v["window"]
    source = "config/bands.json validity_days"
    if state == "valid":
        return _pill("", "Report valid",
                     "Valid for %d days from the report date (%s). %s"
                     % (window, source, _age_sentence(v)))
    if state == "expired":
        return _pill("expired", "Report expired",
                     "Older than the %d-day validity window (%s) — it was "
                     "valid until %s." % (window, source,
                                         dates.fmt_short(v["expires"])))
    if state == "future":
        return _pill("future", "Future-dated",
                     "The report date (%s) is after today, so its age cannot "
                     "be graded. Check the enquiry date the bureau delivered."
                     % dates.fmt_short(v["report_date"]))
    return _pill("unknown", "Validity unknown",
                 "No enquiry date or pull date delivered, so the report's age "
                 "cannot be established.")


def _validity_strip(ctx):
    """Status pill, enquiry scope, enquiry date, window meter, lapse date."""
    v = scoring.validity(ctx)
    scope = _scope_chip(v)
    pill = _validity_pill(v)

    if v["report_date"] is None:
        return ('<div class="tb-valid-strip">%s%s'
                '<span class="tv-note">No enquiry date or pull date delivered '
                '— report age cannot be established</span></div>'
                % (pill, scope))

    # The meter has two colours (user decision, 24 Sep 2026): green while the
    # report is valid, red otherwise -- expired pins the marker at the far
    # end, future-dated sits at zero (scoring clamps pct to 0..100). The end
    # date always reads "Valid until" -- it is the last valid day (age ==
    # window is still valid), so calling it the day the report "lapsed" was
    # a day early. Only an expired report paints that date red; a
    # future-dated one is ungradable, not lapsed, so it stays neutral.
    expired = v["state"] == "expired"
    red = v["state"] != "valid"
    window = v["window"]
    basis = _basis_text(v)
    date_label = _date_label(v)

    pct = v["pct"]
    fill_cls = "tv-fill over" if red else "tv-fill"
    marker = ('<span class="tv-dot%s" style="left:%.1f%%"></span>'
              % (" over" if red else "", pct))

    # The window length is not labelled on the meter -- it is exactly the gap
    # between the two dates flanking it, so a '0 .. 30d' axis would only repeat
    # what the row already says, in the one place with no vertical room for it.
    return """
  <div class="tb-valid-strip">
    {pill}
    {scope}
    <div class="tv-field" data-info="{basis}">
      <span class="tv-k">{date_label}</span>
      <span class="tv-v">{generated}</span>
      <span class="tv-rel">{age}</span>
    </div>
    <div class="tv-meter" data-info="{tip}">
      <span class="tv-track"></span>
      <span class="{fill_cls}" style="width:{pct:.1f}%"></span>
      {marker}
    </div>
    <div class="tv-field">
      <span class="tv-k">Valid until</span>
      <span class="tv-v{lapse_cls}">{expires}</span>
    </div>
  </div>
""".format(pill=pill, scope=scope,
           basis=c.attr(basis), date_label=date_label,
           generated=dates.fmt_short(v["report_date"]),
           age=_age_phrase(v),
           fill_cls=fill_cls, pct=pct, marker=marker,
           lapse_cls=" lapsed" if expired else "",
           expires=dates.fmt_short(v["expires"]),
           tip=c.attr(
               "%s %s · look-back window %d days · valid until %s. %s %s"
               % (date_label, dates.fmt_short(v["report_date"]), window,
                  dates.fmt_short(v["expires"]), _age_sentence(v), basis)))


def _age_sentence(v) -> str:
    """The report's age as a sentence, for the pill and meter hovers.

    Its own function because _days_label's special words do not fit a
    "report is N old" frame ("report is today old").
    """
    label = _days_label(v)
    if label == "today":
        return "The report is from today."
    if label == "future-dated":
        return "The report date is in the future."
    if label == "unknown":
        return "The report's age is unknown."
    return "The report is %s old." % label


def _age_phrase(v) -> str:
    """'today' reads better than '0 days ago'; everything else takes 'ago'."""
    label = _days_label(v)
    return label if label in ("today", "future-dated", "unknown") else label + " ago"


def _days_label(v) -> str:
    """Compact age of a scoring.validity() result: days under 60, then
    calendar months, then years.

    Months and years come from dates.months_between -- the project's only
    month arithmetic -- so "N months" is calendar months, not days / 30.
    """
    n = v["age_days"]
    if n is None:
        return "unknown"
    if n < 0:
        return "future-dated"
    if n == 0:
        return "today"
    if n < 60:
        return "%d day%s" % (n, "" if n == 1 else "s")
    months = dates.months_between(v["report_date"], datetime.date.today()) or 0
    if months < 24:
        return "%d month%s" % (months, "" if months == 1 else "s")
    years = months / 12.0
    if years >= 10:
        return "%d years" % int(years)
    # "2 years", not "2.0 years".
    return ("%.1f" % years).rstrip("0").rstrip(".") + " years"


def spine(ctx) -> str:
    """Left rail of numbered markers, one per section.

    A sticky column in the grid rather than a fixed overlay. Fixed positioning
    pinned the rail to the iframe's own viewport, which is taller than the
    browser window, so it drifted away from the content as the outer page
    scrolled. Sticky keeps it in one scroll context -- the same approach the
    brief rail on the right already uses.

    The number stays as the spoken reference ("look at section 6") and the
    section name slides out on hover.
    """
    dots = "".join(
        '<a class="spine-dot" data-to="{sid}" aria-label="{title}">'
        '<span class="n">{no}</span>'
        '<span class="spine-label">{title}</span></a>'.format(
            sid=sid, no=no, title=c.esc(title))
        for sid, no, title in nav_items())
    return ('<nav class="spine" id="spine" aria-label="Report sections">'
            '<div class="spine-inner"><div class="spine-line"></div>%s</div></nav>'
            % dots)


def rail(ctx) -> str:
    """The underwriting brief panel.

    Renders the AI brief when one is attached to the context (ctx.brief, set
    by the Streamlit host after a validated model run -- see aecb.brief) and
    falls back to the long-standing "no brief generated" shell when none is:
    the target server may have no model available, and the report must not
    carry narrative about a customer it cannot describe.
    """
    brief = getattr(ctx, "brief", None)
    if brief is not None:
        body = render_brief.body(brief)
        foot_extra = render_brief.provenance(brief)
    else:
        body = """
      <div class="rail-empty">
        <div class="re-title">No brief generated</div>
        <div class="re-body">
          <p>This panel summarises the payload in narrative form and cites the
          field behind every claim. It requires a language model, which is not
          available on this deployment.</p>
          <p>Read the sections directly. Every figure on this page is either
          delivered by AECB or derived from delivered values, and derived
          figures are marked.</p>
        </div>
      </div>
"""
        foot_extra = ""
    return """
  <aside class="rail" id="rail">
    <div class="rail-head">
      <div class="rail-ht">
        <div class="ai-mark"><svg viewBox="0 0 24 24" fill="none"><path d="M12 3l1.9 4.5L18.5 9l-4.6 1.5L12 15l-1.9-4.5L5.5 9l4.6-1.5L12 3z" fill="#fff"/><circle cx="18" cy="17" r="2" fill="#9DDBDF"/></svg></div>
        <div><div class="rail-title">Underwriting Brief</div><div class="rail-sub">AI reading of the bureau payload</div></div>
        <button class="rail-x" id="railX" title="Hide">›</button>
      </div>
    </div>
    <div class="rail-body">{body}</div>
    <div class="rail-foot">{foot_extra}
      <div class="rail-note">The brief interprets only — it never computes figures and never renders the decision. In-tenancy · model + prompt under MRM change control.</div>
    </div>
  </aside>
""".format(body=body, foot_extra=foot_extra)
