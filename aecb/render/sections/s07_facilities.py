"""06 Active credit facilities -- the book at a glance, split by role.

Sources: contractsFinancialSummary (payment / limit / balance / overdue, per
category x role), contractsTotalSummary (exposure, newest facility, card
utilisation, guarantee totals), contractsSummary (counts -- read for the
emptiness test only, never displayed).

Three things worth stating here rather than leaving to be rediscovered:

MAIN HOLDER AND GUARANTOR ARE DIFFERENT LIABILITIES and FH lends against them
differently, so every category renders both. A guarantor block that were simply
absent would leave an underwriter working out whether it means nil or
unexamined; it always renders, and says which.

TOTALEXPOSURE COUNTS A REVOLVING FACILITY'S FULL CREDIT LIMIT, not its drawn
balance. Verified against the reference payload: 331,420 installment balance
plus the 59,600 card LIMIT is exactly the 391,020 delivered, where the card
balance is only 33,714. So the header total is not the sum of the balances on
the cards beneath it, and nothing here should be "fixed" to reconcile them.

MAXCURRENTPAYMENTDELAY IS DELIBERATELY NOT SHOWN (RRM decision, Aug 2026). The
payload delivers 1 while MaxPaymentDelay24M is 0, every contract's
Current_DaysPaymentDelay is 0, and every contractsHistory row is 0 DPD. Putting
it on screen would state a contradiction the file cannot explain. It stays off
until AECB resolves it.
"""

from __future__ import annotations

from ... import dates
from ...derive import facilities
from ...loader import CATEGORY_LABEL
from .. import components as c

META = {
    "title": "Active Credit Facilities — Overview",
}

_ORDER = ("I", "C", "N", "S")

# What each category shows beneath its balance headline. contractsFinancialSummary
# carries exactly four figures, so these are all there is to choose from.
# Balance is not listed because it is the headline in every card -- it is the one
# figure common to all four categories, and promoting it gives the row of cards a
# single scan line.
_ROWS = {
    "I": (("Payment amount", "PaymentAmount"), ("Overdue", "OverdueAmount")),
    "C": (("Credit limit", "CreditLimit"), ("Overdue", "OverdueAmount")),
    # Non-installments are limit-bearing credit, so the limit is the useful
    # second figure. AECB carries no PaymentAmount for them.
    "N": (("Credit limit", "CreditLimit"), ("Overdue", "OverdueAmount")),
    # Services carry neither a limit nor a scheduled instalment -- a telecom
    # account has no credit line to fill. Balance and overdue are the whole story.
    "S": (("Overdue", "OverdueAmount"),),
}

_FIGURES = ("PaymentAmount", "CreditLimit", "Balance", "OverdueAmount")


def render(ctx, meta) -> str:
    main = facilities.financial_summary(ctx, "A")
    gtr = facilities.financial_summary(ctx, "G")
    counts = facilities.count_summary(ctx, "A")
    live = facilities.by_category(
        [f for f in facilities.all_facilities(ctx) if not f.closed])

    cards = "".join(
        _card(ctx, cat, main.get(cat) or {}, gtr.get(cat) or {},
              counts.get(cat) or {}, live.get(cat) or [])
        for cat in _ORDER)

    return c.section_card(body='<div class="fac-grid">%s</div>' % cards,
                          aside=_aside(ctx), **meta)


def _aside(ctx):
    totals = ctx.totals
    parts = []

    exposure = totals.get("TotalExposure")
    if exposure is not None:
        parts.append(c.tag('Total exposure <b style="font-weight:700; margin-left:4px">%s</b>'
                           % c.aed(exposure)))

    # How recently the customer last took on credit. §02 carries the oldest
    # facility as the vintage; this is the other end of the same axis.
    newest = totals.get("NewestContractOpenDate")
    if dates.parse_any(newest):
        parts.append(c.tag('Newest facility <b style="font-weight:700; margin-left:4px">%s</b>'
                           % dates.fmt_short(newest)))

    # Only when there IS guaranteed exposure. A zero here is what backs the
    # per-category "no guaranteed exposure" lines, so showing it as a chip too
    # would state the same fact twice.
    guaranteed = totals.get("TotalBalanceGuaranteed")
    if guaranteed:
        parts.append(c.tag("Guaranteed %s" % c.aed(guaranteed), "warn"))

    return "".join(parts)


# --- one category card ------------------------------------------------------

def _card(ctx, cat, main, gtr, counts, live_rows):
    head = ('<div class="fac-h"><span class="fac-cat">%s</span>'
            '<span class="fac-name">%s</span></div>'
            % (cat, CATEGORY_LABEL.get(cat, cat)))

    # A category with nothing in it says so, rather than showing dashes that
    # could be misread as zero balances on real facilities.
    if _is_empty(main, gtr, counts, live_rows):
        return ('<div class="fac empty">%s%s</div>'
                % (head, c.empty_state("No facilities",
                                       "Nothing reported in this category.")))

    parts = [head]
    if cat == "C":
        parts.append(_utilisation(ctx))
    parts.append(_role_block("Main holder", cat, main))
    parts.append(_guarantor_block(ctx, cat, gtr))
    return '<div class="fac">%s</div>' % "".join(parts)


def _is_empty(main, gtr, counts, live_rows) -> bool:
    """Whether the screen should say this category holds nothing.

    Keyed off the bureau count as well as the figures. contractsSummary's
    TotalNo spans more history than the delivered contract rows, so a category
    that is empty NOW but was not always must not claim nothing was ever
    reported. This is the ONLY thing the counts are read for -- they are no
    longer displayed anywhere on the card.
    """
    if live_rows or counts.get("TotalNo"):
        return False
    return not _has_figures(main) and not _has_figures(gtr)


def _has_figures(fin) -> bool:
    """True when a role carries anything at all beyond zeros and nulls."""
    return any(fin.get(field) for field in _FIGURES)


# --- the two role blocks ----------------------------------------------------

def _role_block(title, cat, fin):
    # The role label sits ON the balance line rather than above it. It is the
    # caption for that figure, so a line of its own said the same thing twice
    # and cost one per block. .fac-block wraps at narrow widths, which puts the
    # figure back underneath -- the old layout, reached only when it is needed.
    return ('<div class="fac-block"><span class="fac-role">%s</span>%s</div>%s'
            % (title, _headline(fin), _rows(cat, fin)))


def _guarantor_block(ctx, cat, fin):
    head = '<span class="fac-role">Guarantor</span>'
    if _has_figures(fin):
        return ('<div class="fac-block">%s%s</div>%s'
                % (head, _headline(fin), _rows(cat, fin)))

    # Nothing in the category's guarantor row. AECB delivers its own book-wide
    # guarantee totals, and a total of zero means every category's is zero --
    # so the statement is carried by a delivered figure rather than inferred
    # from empty cells. The inference runs in this direction only: a NON-zero
    # total cannot be attributed to any one category, so no claim is made.
    totals = ctx.totals
    if totals.get("TotalBalanceGuaranteed") == 0 and totals.get("TotalOverdueGuaranteed") == 0:
        return ('<div class="fac-block">%s<span class="fac-nil">No exposure '
                'reported%s</span></div>' % (head, _tag_delivered()))
    return ('<div class="fac-block">%s<span class="fac-nil"><span class="na">'
            'Not reported</span></span></div>' % head)


def _headline(fin):
    """The balance, as the card's one large figure."""
    balance = fin.get("Balance")
    if balance is None:
        return '<span class="fac-big"><span class="na">Not reported</span></span>'
    css = " od" if fin.get("OverdueAmount") else ""
    return '<span class="fac-big%s">%s</span>' % (css, c.aed(balance))


def _rows(cat, fin):
    rows = []
    for label, field in _ROWS.get(cat, ()):
        value = fin.get(field)
        if value is None:
            rows.append((label, '<span class="na">Not reported</span>', ""))
        elif field == "OverdueAmount":
            # A reported zero overdue is a fact and stays in ink; only a real
            # overdue takes the red.
            rows.append((label, c.aed(value) if value else "0",
                         " od" if value else ""))
        else:
            rows.append((label, c.aed(value), ""))

    if not rows:
        return ""
    return '<div class="fac-rows">%s</div>' % "".join(
        '<div class="fac-row"><span class="k">%s</span>'
        '<span class="val%s">%s</span></div>' % (k, css, v)
        for k, v, css in rows)


# --- the utilisation line ---------------------------------------------------

def _utilisation(ctx):
    """Delivered card utilisation, drawn as a line rather than a donut.

    contractsTotalSummary.CreditUtilizationRate is delivered ONCE for the
    category and carries no role dimension, so it sits above the role split
    where it is true rather than inside main holder's rows.

    It reads as a book-wide ratio from where it lives, and is not: verified
    against the reference payload, 33,714 balance over a 59,600 limit is
    56.57%, which is the delivered "57". Shown verbatim.

    Below 100 the line fills to the percentage in green. At or above 100 it
    fills completely in red -- so the figure beside the label is what tells
    101% from 300%, since the bar cannot. That figure is also why there is no
    0/100% scale under the bar: "57%" printed above a track filled just over
    halfway already says the track's full width is 100%.
    """
    raw = ctx.totals.get("CreditUtilizationRate")
    if raw is None or not str(raw).strip():
        return ""
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return ""

    over = pct >= 100
    fill = 100.0 if over else max(0.0, pct)
    css = " over" if over else ""
    return (
        '<div class="fac-util">'
        '<div class="fac-util-h"><span class="k">Utilisation</span>'
        '<span class="v%s">%s%%</span>%s</div>'
        '<div class="fac-util-bar"><i class="fac-util-fill%s" style="width:%.2f%%"></i></div>'
        '</div>'
    ) % (css, c.esc(raw), _tag_delivered(), css, fill)


def _tag_delivered():
    return ('<span class="prov-mark delivered" data-info="Delivered by AECB in '
            'contractsTotalSummary and shown verbatim.">delivered</span>')
