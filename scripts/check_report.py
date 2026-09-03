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

from aecb import context                      # noqa: E402
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
