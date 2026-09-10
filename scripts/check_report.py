"""Fail the build if the rendered report misrepresents the payload.

A fabricated figure on a credit screen is indistinguishable from a real one, so
this check is not cosmetic. It asserts three things about every payload in
ReferenceJSON/:

  - values the payload DOES carry actually reach the page;
  - figures the bureau delivered are shown verbatim, in the element meant to
    carry them -- not relabelled, rounded, or translated into a code;
  - the page has no external reference, so it still works air-gapped.

Run:  python3 scripts/check_report.py
"""

from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aecb import context, dates               # noqa: E402
from aecb.derive import identity as derive_identity  # noqa: E402
from aecb.render.page import render_page      # noqa: E402

def strip_noise(html):
    """Drop the font blob, the stylesheet and comments before scanning.

    Base64 font data contains arbitrary character runs, so a short numeric
    needle can be found inside it by chance. Left in, that would let a figure
    the page never actually displays satisfy a presence check -- which is the
    one way these assertions could pass while the report is wrong.
    """
    html = re.sub(r"<style>.*?</style>", "", html, flags=re.S)
    html = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    return html


def _values_in(block_class, raw):
    """Every .v span inside every <div class="BLOCK">, and nothing outside one.

    Bounded to the block on purpose. A single regex reaching from the opening
    tag to the next '<span class="v...">' would, when that block has no value
    (an unreported figure renders .na instead), happily match a .v belonging to
    a different section further down the page -- and the check would pass on
    another element's number.
    """
    out = []
    for block in re.findall(r'<div class="%s">(.*?)</div>' % block_class, raw, flags=re.S):
        out.extend(re.findall(r'<span class="v[^"]*">(.*?)</span>', block, flags=re.S))
    return out


def check(path):
    ctx = context.from_file(path)
    raw = render_page(ctx)
    html = strip_noise(raw)

    problems = []

    # Values the payload genuinely carries must reach the page.
    expected = [
        (ctx.customer.get("FullNameEN"), "customer name"),
        (str(ctx.score.get("DataIndex") or ""), "score"),
        (ctx.subject_id, "subject id"),
    ]
    for value, label in expected:
        if value and value not in raw:
            problems.append("payload value missing from page: %s (%r)" % (label, value))

    # The delivered honorific must render too -- checked against the
    # noise-stripped html, not raw: a 3-character token like 'MRS' can occur
    # by chance inside the base64 font block and would false-pass there.
    title = ctx.customer.get("Title")
    if title and title not in html:
        problems.append("payload value missing from page: customer title (%r)" % title)

    # Every delivered identification value must reach the page -- the newest
    # current one as the tile headline, everything else (superseded values AND
    # surplus current ones) inside the expander. Dropping one is information
    # loss the page would never reveal (decision, 8 Sep 2026).
    for row in ctx.rows("identification"):
        info = row.get("Info")
        if info and str(info) not in html:
            problems.append("payload value missing from page: identification "
                            "%s (%r)" % (row.get("InfoType"), info))

    # Every delivered address text must reach the page too, and a row that
    # carried a location without the address itself (emirate / PO box / plot
    # only) must surface as the "Address not provided" statement rather than
    # vanish. Emirate names alone are too repetitive to assert on.
    partial = False
    for row in ctx.rows("addresses"):
        text = row.get("Address")
        if text and str(text) not in html:
            problems.append("payload value missing from page: address (%r)" % text)
        if text is None and any(row.get(f) is not None
                                for f in ("Emirate", "PoBox", "PlotNo")):
            partial = True
    if partial and "Address not provided" not in html:
        problems.append("payload delivers an address row without an Address "
                        "but the page shows no 'Address not provided' entry")

    # Likewise every mobile number and e-mail. Phone Number contacts have no
    # tile yet (open item), so only the two rendered types are asserted.
    for row in ctx.rows("contacts"):
        base = derive_identity.base_type(row.get("ContactType")).lower()
        if base not in ("mobile number", "e-mail"):
            continue
        value = row.get("Contact")
        if value and str(value) not in html:
            problems.append("payload value missing from page: contact "
                            "%s (%r)" % (row.get("ContactType"), value))

    # Every delivered income figure must be on the page -- including the ones
    # section 04 keeps off the chart as placeholders. Suppressing a figure the
    # bureau sent is precisely the failure this script exists to catch, and it
    # would be invisible otherwise: the page would simply look tidier.
    for row in ctx.rows("employment"):
        amount = row.get("GrossAnnualIncome")
        if amount is None:
            continue
        shown = "{:,.0f}".format(float(amount))
        if not re.search(r"(?<![\d.,])%s(?![\d])" % re.escape(shown), html):
            problems.append("payload value missing from page: employment income "
                            "(%r, reported by %s)" % (shown, row.get("ProviderNo")))

    # Likewise every returned-instrument amount: section 05's claim is that the
    # returns themselves are on screen, so a dropped one must fail the build.
    for row in ctx.rows("paymentOrder"):
        amount = row.get("Amount")
        if amount is None:
            continue
        shown = "{:,.0f}".format(float(amount))
        if not re.search(r"(?<![\d.,])%s(?![\d])" % re.escape(shown), html):
            problems.append("payload value missing from page: return amount "
                            "(%r, reported by %s)" % (shown, row.get("ProviderNo")))

    # Section 06's only-when-non-zero surfaces: a delivered guaranteed-overdue
    # total and any delivered application-outcome counter must reach the page.
    # Vacuous on fixtures that deliver zeros, but exactly the values that must
    # not go missing when a payload does carry them.
    if ctx.totals.get("TotalOverdueGuaranteed") and "Guaranteed overdue" not in html:
        problems.append("payload value missing from page: TotalOverdueGuaranteed "
                        "(%r)" % ctx.totals.get("TotalOverdueGuaranteed"))
    for field, label in (("DeclinedNo", "declined"), ("RejectedNo", "rejected"),
                         ("NotTakenUpNo", "not taken up")):
        if any(row.get(field) for row in ctx.rows("contractsSummary")) \
                and label not in html:
            problems.append("payload value missing from page: contractsSummary."
                            "%s is non-zero but %r never renders" % (field, label))

    # The top bar must always state the enquiry scope: the latest-dated
    # sectionStatus row's ReportType and EnquiryType render verbatim as chips
    # (no hard-coded product vocabulary), an empty array as the amber
    # not-reported chip. The winner is recomputed here independently --
    # latest parseable 'Last EnquiryDate' first, array order breaking ties,
    # first row standing in when no row is dated.
    ss_rows = ctx.rows("sectionStatus")
    winner = winner_date = None
    for r in ss_rows:
        parsed = dates.parse_any(r.get("Last EnquiryDate"))
        if parsed and (winner_date is None or parsed > winner_date):
            winner, winner_date = r, parsed
    scope_row = winner if winner is not None else \
        (ss_rows[0] if ss_rows else None)
    if scope_row is not None:
        for field in ("ReportType", "EnquiryType"):
            value = str(scope_row.get(field) or "").strip()
            if value and value not in html:
                problems.append("top bar scope chip missing: sectionStatus."
                                "%s %r never renders" % (field, value))
    elif "Enquiry scope not reported" not in html:
        problems.append("top bar does not state that the enquiry scope is "
                        "unreported")

    # ctx.report_date is the enquiry ladder (decision, 10 Sep 2026): the
    # latest-dated sectionStatus row's 'Last EnquiryDate', else
    # score.DataPullDate. Recomputed above from the raw arrays -- not via
    # ctx.report_date -- so a regression in context.py cannot certify itself.
    # Asserted against the __AECB blob's reportDate (json.dumps writes
    # '"reportDate": "YYYY-MM-DD"'), which is what report.js actually anchors
    # to. On the archive fixture this only passes at the enquiry date, never
    # at the ten-months-earlier pull date.
    expected = winner_date
    if expected is None:
        expected = dates.parse_any(ctx.score.get("DataPullDate"))
    if expected is not None:
        needle = '"reportDate": "%s"' % expected.isoformat()
        if needle not in html:
            problems.append("report date is not the enquiry-ladder date: "
                            "expected %s in the __AECB blob" % needle)

    # Section 07's rows are drawn client-side, so its only-when-delivered
    # signals are asserted against the window.__AECB blob rather than markup
    # (the chip wording lives verbatim in report.js and would always match).
    # json.dumps writes '"key": value', which is what these needles rely on.
    from aecb.render.js import _truthy_flag  # local import: test helper only
    contracts = ctx.rows("contracts")
    blob_wants = []
    if any(_truthy_flag(r.get("FlagOpenDispute")) for r in contracts):
        blob_wants.append(('"dispute": true', "a contract's open dispute"))
    if any(r.get("SecurityType") or _truthy_flag(r.get("SecuredContractFlag"))
           for r in contracts):
        blob_wants.append(('"secured":', "a contract's security"))
    if any(str(r.get("OriginalCurrency") or "").strip() not in ("", "AED")
           for r in contracts):
        blob_wants.append(('"currency":', "a non-AED contract currency"))

    # Section 08's exception marks, same blob-level reasoning.
    applications = ctx.rows("applications")
    if any(_truthy_flag(r.get("FlagOpenDispute")) for r in applications):
        blob_wants.append(('"disp": true', "a disputed application"))
    role_map = ctx.status_codes.get("role_labels") or {}
    if any(role_map.get(str(r.get("Role") or "").strip(), "A") != "A"
           for r in applications):
        blob_wants.append(('"role":', "a non-main-holder application role"))

    def _adverse_lifetime(r):
        value = r.get("WorstStatus")
        if value is not None:
            rank = ctx.status(value)["rank"]
            if rank is None or rank < 100:
                return True
        try:
            return float(r.get("MaxDaysPaymentDelay") or 0) > 0
        except (TypeError, ValueError):
            return False
    if any(_adverse_lifetime(r) for r in contracts):
        blob_wants.append(('"worstEver":', "a contract's adverse lifetime worst"))
    for needle, label in blob_wants:
        if needle not in raw:
            problems.append("payload value missing from the heatmap blob: %s "
                            "(%r not found)" % (label, needle))

    # Section 05 shows two delivered figures VERBATIM, at RRM's instruction --
    # no relabelling, no rounding, no translation into a letter code. A plain
    # substring search cannot prove that: the life-time count is 0, and "0"
    # appears all over the page. So this reads the figures out of the panels
    # themselves. It is coupled to .wsx-worst on purpose; that coupling is the
    # only thing that makes the assertion mean anything, and if the markup
    # moves, this check SHOULD be the thing that notices.
    panels = re.findall(r'<div class="wsx-worst[^"]*">(.*?)</div>', raw, flags=re.S)
    delay = _values_in("wsx-sub", raw)
    util = _values_in("fac-util-h", raw)

    # Each figure is checked against the element that is supposed to carry it
    # and nowhere else. Searching the whole page would prove nothing: the
    # life-time count is 0, "0" appears everywhere, and an assertion that
    # cannot fail is not an assertion. The unit ("days", "%") is part of the
    # expected string so a figure cannot satisfy the check from the wrong slot.
    verbatim = [
        (ctx.totals.get("WorstStatus24M"), "%s", panels,
         "§05 24-month worst status"),
        (ctx.summary.get("Worststatus"), "%s", panels,
         "§05 life-time worst status count"),
        (ctx.totals.get("MaxPaymentDelay24M"), "%s days", delay,
         "§05 24-month max payment delay"),
        (ctx.totals.get("CreditUtilizationRate"), "%s%%", util,
         "§06 card utilisation rate"),
    ]
    for value, shape, found, label in verbatim:
        if value is None:
            continue
        text = "{:,.0f}".format(value) if isinstance(value, (int, float)) else str(value)
        wanted = shape % text
        if wanted not in found:
            problems.append("a delivered figure is not shown verbatim: %s -- "
                            "expected %r, that element carries %r"
                            % (label, wanted, found))

    if "http://" in raw or "https://" in raw:
        problems.append("external reference in output -- will break offline")

    return problems


def main():
    payloads = sorted(glob.glob(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ReferenceJSON", "*.json")))
    if not payloads:
        print("no payloads found in ReferenceJSON/")
        return 1

    failed = False
    for path in payloads:
        problems = check(path)
        name = os.path.basename(path)
        if problems:
            failed = True
            print("FAIL %s" % name)
            for p in problems:
                print("    %s" % p)
        else:
            print("ok   %s -- payload values present and verbatim, no external refs"
                  % name)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
