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

from .. import dates
from ..derive import scoring
from . import branding
from . import brief as render_brief
from . import components as c
from .sections import nav_items

APP_NAME = "FH AECB Analyser"


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
""".format(mark=branding.brand_mark(), name=APP_NAME, validity=_validity_strip(ctx))


# What dated the validity verdict, for the Generated and meter hovers. The
# ladder is RRM policy (9 Sep 2026): the full enquiry's own date first, the
# score-only enquiry's second, the warehouse pull date as a last resort only.
_BASIS_TEXT = {
    "bounced": "Dated by the bounced-cheque enquiry — sectionStatus "
               "'ConsumerLong with Bounced Cheques', Last EnquiryDate.",
    "score_only": "Dated by the ConsumerScoreOnly enquiry's Last EnquiryDate "
                  "— the bounced-cheque row delivered no date of its own.",
    "pull": "Dated by score.DataPullDate — sectionStatus delivered no usable "
            "enquiry date, so the warehouse pull date is the last resort.",
}


def _scope_chip(v):
    """The enquiry scope, always stated: what the bureau was actually asked.

    A score-only pull is a materially thinner file -- section 04 can only say
    'unchecked' -- and an RRM must see that before reading anything below.
    """
    if v["bc_present"]:
        return ('<span class="tb-scope" data-info="sectionStatus lists the '
                'ConsumerLong with Bounced Cheques product — the bounced-cheque '
                'section was pulled with this enquiry.">Full file · incl. '
                'bounced cheques</span>')
    if v["so_present"]:
        return ('<span class="tb-scope warn" data-info="sectionStatus carries '
                'no bounced-cheque product for this enquiry, so the absence of '
                'returns is not evidence of a clean record — section 04 grades '
                'the same gap.">Score-only · bounced cheques not requested</span>')
    return ('<span class="tb-scope warn" data-info="sectionStatus is empty — '
            'which products were pulled cannot be established.">Enquiry scope '
            'not reported</span>')


def _validity_strip(ctx):
    """Status pill, enquiry scope, enquiry date, window meter, lapse date."""
    v = scoring.validity(ctx)
    scope = _scope_chip(v)

    if v["report_date"] is None:
        return ('<div class="tb-valid-strip">'
                '<span class="tb-valid unknown"><span class="pd"></span>'
                'Validity unknown</span>%s'
                '<span class="tv-note">No enquiry date or pull date delivered '
                '— report age cannot be established</span></div>' % scope)

    valid = v["valid"]
    age, window = v["age_days"], v["window"]
    basis = _BASIS_TEXT.get(v["basis"], "")

    pill = ('<span class="tb-valid"><span class="pd"></span>Report valid</span>'
            if valid else
            '<span class="tb-valid expired"><span class="pd"></span>Report expired</span>')

    # Marker position. scoring.validity clamps pct to 100, so a long-expired
    # report pins at the end of the track instead of running off it.
    pct = v["pct"]
    fill_cls = "tv-fill" if valid else "tv-fill over"
    marker = ('<span class="tv-dot%s" style="left:%.1f%%"></span>'
              % ("" if valid else " over", pct))

    # The window length is not labelled on the meter -- it is exactly the gap
    # between the two dates flanking it, so a '0 .. 30d' axis would only repeat
    # what the row already says, in the one place with no vertical room for it.
    return """
  <div class="tb-valid-strip">
    {pill}
    {scope}
    <div class="tv-field" data-info="{basis}">
      <span class="tv-k">Generated</span>
      <span class="tv-v">{generated}</span>
      <span class="tv-rel">{age}</span>
    </div>
    <div class="tv-meter" data-info="{tip}">
      <span class="tv-track"></span>
      <span class="{fill_cls}" style="width:{pct:.1f}%"></span>
      {marker}
    </div>
    <div class="tv-field">
      <span class="tv-k">{lapse_label}</span>
      <span class="tv-v{lapse_cls}">{expires}</span>
    </div>
  </div>
""".format(pill=pill, scope=scope,
           basis=c.attr(basis),
           generated=dates.fmt_short(v["report_date"]),
           age=_age_phrase(age),
           fill_cls=fill_cls, pct=pct, marker=marker,
           lapse_label="Valid until" if valid else "Lapsed",
           lapse_cls="" if valid else " lapsed",
           expires=dates.fmt_short(v["expires"]),
           tip=c.attr(
               "Enquiry date %s · look-back window %d days · %s %s · report "
               "is %s old. %s"
               % (dates.fmt_short(v["report_date"]), window,
                  "valid until" if valid else "lapsed",
                  dates.fmt_short(v["expires"]), _days_label(age), basis)))


def _age_phrase(n) -> str:
    """'today' reads better than '0 days ago'; everything else takes 'ago'."""
    label = _days_label(n)
    return label if label in ("today", "future-dated", "unknown") else label + " ago"


def _days_label(n) -> str:
    """Compact age: days under two months, then months, then years."""
    if n is None:
        return "unknown"
    if n < 0:
        return "future-dated"
    if n == 0:
        return "today"
    if n < 60:
        return "%d day%s" % (n, "" if n == 1 else "s")
    if n < 730:
        return "%d months" % (n // 30)
    years = n / 365.0
    return "%.1f years" % years if years < 10 else "%d years" % int(years)


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
