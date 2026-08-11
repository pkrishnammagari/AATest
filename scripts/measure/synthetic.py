"""Render payload shapes the reference customer does not produce.

    .venv/bin/python scripts/measure/synthetic.py

The reference file exercises exactly one shape of most things: one e-mail, a
short address, a passport with a future expiry, an FH band, an AECB band and a
resolvable vintage code. Every other path is unrendered until something like
this drives it. A change that looks fine on the reference payload can still be
broken for a customer with no e-mail or an expired document.

Assertions here are about STRUCTURE, deliberately not about pixel heights:
different payloads legitimately produce different heights, and pinning numbers
would make this rot. Height regressions are compare.py's job.

Traps met while writing these, so nobody meets them twice:
  * contacts key off `ContactType`, not `Type`, and carry a trailing space
    ("E-mail "). Addresses are their own array keyed on `Address`.
  * A mutation that silently matches nothing gives a green run that proves
    nothing. Each case below asserts the shape it was meant to create.

Python 3.9 compatible.
"""
from __future__ import annotations

import copy
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths                                                   # noqa: E402

JS = """
<script>
window.addEventListener('load', function () {
  setTimeout(function () {
    var q = function (s) { return document.querySelector(s); };
    var s1 = document.getElementById('s1'), s2 = document.getElementById('s2');
    var grid = s1.querySelector('.facts.id-grid');
    var tiles = [].slice.call(grid.children);
    var gw = grid.getBoundingClientRect().width;

    /* Group tiles into visual rows by their top edge, then measure how much of
       the row's width each row actually uses. A row under ~97% has a hole in
       it -- which is what a mis-spanned grid produces. */
    var rows = {};
    tiles.forEach(function (t) {
      var r = t.getBoundingClientRect();
      var k = Math.round(r.top);
      rows[k] = rows[k] || [];
      rows[k].push({w: r.width, clip: t.scrollWidth > t.clientWidth + 1,
                    h: Math.round(r.height)});
    });
    var rowInfo = Object.keys(rows).sort(function (a, b) { return a - b; })
      .map(function (k) {
        var row = rows[k];
        var used = row.reduce(function (s, t) { return s + t.w; }, 0) + 8 * (row.length - 1);
        return {n: row.length, fill: +(100 * used / gw).toFixed(1),
                clip: row.some(function (t) { return t.clip; }),
                equal: row.every(function (t) { return t.h === row[0].h; })};
      });

    var pp = null;
    tiles.forEach(function (t) { if (t.querySelector('.v-sub')) pp = t; });
    var pv = pp ? pp.querySelector('.v') : null;

    /* Section 05 reports its TONE CLASS rather than a computed colour. The
       assertion that matters is "an unrecognised status is left ungraded", and
       a class name states that directly; a colour would only state it once you
       already knew which rgb the green token resolves to. */
    var wsx = [].slice.call(document.querySelectorAll('#s5 .wsx-panel'))
      .map(function (p) {
        var f = p.querySelector('.wsx-worst');
        return {cls: f ? f.className.replace('wsx-worst', '').trim() : null,
                text: f ? f.textContent.trim() : null,
                pending: !!p.querySelector('.empty-state'),
                clip: p.scrollWidth > p.clientWidth + 1};
      });

    /* Section 06: one entry per category card. The chip background is read so
       the "all four chips are one brand colour" rule is asserted rather than
       admired -- it is exactly the kind of thing a stray .fac-cat.C rule would
       silently undo. */
    var fac = [].slice.call(document.querySelectorAll('#s6 .fac')).map(function (f) {
      var chip = f.querySelector('.fac-cat');
      var fill = f.querySelector('.fac-util-fill');
      var val = f.querySelector('.fac-util-h .v');
      return {
        cat: chip ? chip.textContent.trim() : null,
        chipBg: chip ? getComputedStyle(chip).backgroundColor : null,
        empty: f.classList.contains('empty'),
        roles: [].slice.call(f.querySelectorAll('.fac-role'))
                 .map(function (r) { return r.textContent.trim(); }),
        nil: [].slice.call(f.querySelectorAll('.fac-nil'))
               .map(function (r) { return r.textContent.trim(); }),
        od: !!f.querySelector('.val.od, .fac-big.od'),
        util: fill ? {w: fill.style.width,
                      over: fill.className.indexOf('over') >= 0,
                      v: val ? val.textContent.trim() : null} : null,
        clip: f.scrollWidth > f.clientWidth + 1
      };
    });

    var sub = q('#s5 .wsx-sub');
    var subV = q('#s5 .wsx-sub .v');

    /* Section 07's four buckets. Rows inside a collapsed fold are still in the
       DOM, so text and counts read fine; only their geometry would be zero,
       and nothing here measures them. */
    var s7 = document.getElementById('s7');
    var txt = function (n) { return n.textContent.replace(/\\s+/g, ' ').replace(/\\u25be/g, '').trim(); };

    /* Section 07 stacks three separate repeat(36,1fr) grids -- status, DPD,
       utilisation -- and a month must line up with itself down all three. This
       asserts them against EACH OTHER, which is the only way to see it: the
       misalignment that shipped on 7 Aug had every strip internally consistent,
       nothing clipped, nothing overflowed, and the section measured shorter.
       Rows inside a collapsed fold report zeros for all three, so they agree
       trivially rather than failing. */
    var misaligned = 0;
    [].slice.call(s7.querySelectorAll('.hm-row')).forEach(function (row) {
      var st = row.querySelectorAll('.scell'),
          dp = row.querySelectorAll('.cell'),
          ut = row.querySelectorAll('.ucell');
      for (var m = 0; m < dp.length; m++) {
        var b = dp[m].getBoundingClientRect();
        var a = st[m] && st[m].getBoundingClientRect();
        if (a && (Math.abs(a.left - b.left) > 0.5 || Math.abs(a.width - b.width) > 0.5)) misaligned++;
        var u2 = ut.length ? ut[m].getBoundingClientRect() : null;
        if (u2 && (Math.abs(u2.left - b.left) > 0.5 || Math.abs(u2.width - b.width) > 0.5)) misaligned++;
      }
    });
    /* Section 08's timeline. `focus` counts the markers inside the 90-day
       window -- the whole point of the split axis -- and `glyphless` catches a
       contract type that mapped to no category letter, which must render a
       blank marker rather than a guessed one. */
    var s8 = document.getElementById('s8');
    var tl8 = s8.querySelector('.enq-tl');
    var mks = tl8 ? [].slice.call(tl8.querySelectorAll('.mk')) : [];
    var apps = {
      events: mks.length,
      focus: mks.filter(function (m) { return m.classList.contains('focus'); }).length,
      taken: mks.filter(function (m) { return m.classList.contains('taken'); }).length,
      glyphless: mks.filter(function (m) { return !m.textContent.trim(); }).length,
      ticks: tl8 ? tl8.querySelectorAll('.tl-mo').length : 0,
      h: tl8 ? Math.round(tl8.getBoundingClientRect().height) : 0,
      tags: [].slice.call(s8.querySelectorAll('.tag')).map(txt),
      empty: !!s8.querySelector('.empty-state'),
      clip: s8.scrollWidth > s8.clientWidth + 1
    };

    var hm = {
      blocks: [].slice.call(s7.querySelectorAll('.hm-blockhead')).map(txt),
      groups: [].slice.call(s7.querySelectorAll('.hm-grouphead')).map(txt),
      roles: [].slice.call(s7.querySelectorAll('.hm-row .role')).map(txt),
      freqs: s7.querySelectorAll('.hm-row .freq').length,
      undated: s7.querySelectorAll('.closed-on.na').length,
      rows: s7.querySelectorAll('.hm-row').length,
      misaligned: misaligned,
      clip: s7.scrollWidth > s7.clientWidth + 1
    };

    document.title = 'Y<<' + btoa(unescape(encodeURIComponent(JSON.stringify({
      s1: Math.round(s1.getBoundingClientRect().height),
      s2: Math.round(s2.getBoundingClientRect().height),
      wsx: wsx,
      wsxTag: q('#s5 .tag') ? q('#s5 .tag').textContent.trim() : null,
      wsxSub: sub ? sub.textContent.replace(/\\s+/g, ' ').trim() : null,
      wsxSubRed: subV ? subV.className.indexOf('red') >= 0 : null,
      fac: fac,
      hm: hm,
      apps: apps,
      tracks: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
      rows: rowInfo,
      tiles: tiles.length,
      ppLineH: pv ? +pv.getBoundingClientRect().height.toFixed(1) : null,
      ppClip: pv ? (pv.scrollWidth > pv.clientWidth + 1) : null,
      expiry: pp && pp.querySelector('.v-sub')
              ? pp.querySelector('.v-sub').textContent.trim() : null,
      vintage: q('.ss-vint') ? q('.ss-vint').textContent.trim() : null,
      bands: [].slice.call(document.querySelectorAll('.ss-band')).map(function (b) {
        return b.textContent.trim() + ' [' + getComputedStyle(b).backgroundColor + ']';
      }),
      overflow: document.documentElement.scrollWidth >
                document.documentElement.clientWidth
    })))) + '>>Y';
  }, 700);
});
</script>
"""

LONG_ADDRESS = ("VILLA 42B STREET 17 AL QOUZ INDUSTRIAL AREA 3 BEHIND "
                "THE CENTRAL WAREHOUSE COMPLEX")
LONG_EMAIL = "muna.mohammad.essa.hassan.ali@averylongdomainname.example.ae"


def passports(data):
    return [r for r in data["identification"] if r.get("InfoType") == "Passport"]


def mails(data):
    return [r for r in data["contacts"]
            if "mail" in str(r.get("ContactType") or "").lower()]


def build_cases(base):
    cases = {"reference": copy.deepcopy(base)}

    # --- section 01: the grid's density step ---------------------------------
    d = copy.deepcopy(base)
    d["contacts"] = [r for r in d["contacts"] if r not in mails(d)]
    cases["no-email"] = d                     # -> r2-1, row one must stay full

    d = copy.deepcopy(base)
    for r in d["addresses"]:
        r["Address"], r["PoBox"] = LONG_ADDRESS, "294857"
    cases["long-address"] = d

    d = copy.deepcopy(base)
    for r in mails(d):
        r["Contact"] = LONG_EMAIL
    cases["long-email"] = d

    d = copy.deepcopy(base)
    for r in d["addresses"]:
        r["Address"] = LONG_ADDRESS
    for r in mails(d):
        r["Contact"] = LONG_EMAIL
    cases["long-both"] = d

    # --- section 01: the passport tile's value line --------------------------
    d = copy.deepcopy(base)
    for r in passports(d):
        r["ExpiryDate"] = None
    cases["no-expiry"] = d

    d = copy.deepcopy(base)
    for r in passports(d):
        r["ExpiryDate"] = "2019-03-04T00:00:00"        # behind the report date
    cases["expired-passport"] = d

    d = copy.deepcopy(base)
    for r in passports(d):
        r["Info"] = "XKP99887766554433"
    cases["long-passport"] = d

    # --- section 02: the score strip -----------------------------------------
    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["OldestContractOpenDate"] = None             # -> no vintage code
    cases["no-vintage"] = d

    d = copy.deepcopy(base)
    for r in d["score"]:
        r["FHScoreBand"] = r["FHScoreBand1"] = None    # -> neutral chip
    cases["no-fh-band"] = d

    # --- section 05: every tone, and both absences ---------------------------
    # The reference customer is entirely clean, so the only path it renders is
    # the green one. Nothing below is a judgement about this customer; each
    # case exists to drive one branch of s06_worst_status._grade().
    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["WorstStatus24M"] = "Write-off"              # rank 40 -> severe, red
    cases["ws-severe"] = d

    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["WorstStatus24M"] = "Arrangement"            # rank 90 -> adverse, amber
    cases["ws-adverse"] = d

    # The one that must NOT be painted green. ctx.status() hands an unmatched
    # string back at rank 100 -- the clean rank -- so a section grading off it
    # would reassure an underwriter about a status nobody recognises.
    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["WorstStatus24M"] = "Restructured Facility"
    cases["ws-unknown"] = d

    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["WorstStatus24M"] = None                     # -> "Not reported" panel
    cases["ws-absent"] = d

    d = copy.deepcopy(base)
    for r in d["summary"]:
        r["Worststatus"] = 3                           # a count, so amber not red
    cases["ws-count"] = d

    d = copy.deepcopy(base)
    for r in d["summary"]:
        r["Worststatus"] = None                        # -> "Not reported" panel
    cases["ws-count-absent"] = d

    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["MaxPaymentDelay24M"] = 47                   # -> red delay line
    cases["delay-24m"] = d

    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["MaxPaymentDelay24M"] = None                 # -> "Not reported"
    cases["delay-absent"] = d

    # --- section 06: the paths a clean, unguaranteed customer never renders --
    # The reference customer guarantees nothing and owes nothing, so the
    # guarantor rows, the red overdue and the over-limit utilisation line have
    # only ever existed in the code.
    d = copy.deepcopy(base)
    for r in d["contractsFinancialSummary"]:
        if r["ContractCategory"] == "C" and r["ContractRole"] == "G":
            r["CreditLimit"], r["Balance"], r["OverdueAmount"] = 40000, 12500, 0
    for r in d["contractsTotalSummary"]:
        r["TotalBalanceGuaranteed"] = 12500
    cases["guarantor-live"] = d

    d = copy.deepcopy(base)
    for r in d["contractsFinancialSummary"]:
        if r["ContractCategory"] == "I" and r["ContractRole"] == "A":
            r["OverdueAmount"] = 9400                  # -> the .od red path
    cases["overdue"] = d

    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["CreditUtilizationRate"] = "137"             # -> full bar, red
    cases["util-over"] = d

    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["CreditUtilizationRate"] = None              # -> no line at all
    cases["util-absent"] = d

    # --- section 07: the four buckets ---------------------------------------
    # The reference customer has one active service with nothing on it, every
    # closure dated, and every contract held as main holder -- so the arrears
    # split, the undated closure and the role chip are all unrendered.
    d = copy.deepcopy(base)
    for r in d["contracts"]:
        if r["ContractCategory"] == "S":
            r["Current_OverdueAmount"] = 320           # -> stays in Active
    cases["svc-arrears"] = d

    d = copy.deepcopy(base)
    for r in d["contracts"]:
        if r.get("ActiveFlag") == "Closed":
            r["ClosedDate"] = None                     # -> all beyond 6 months
    cases["closed-undated"] = d

    d = copy.deepcopy(base)
    for r in d["contracts"]:
        if r["ContractCategory"] == "C":
            r["Role"] = "Guarantor"                    # -> the role chip shows
    cases["guarantor-role"] = d

    # --- section 08: the timeline's edges ------------------------------------
    d = copy.deepcopy(base)
    d["applications"] = []                             # -> "no applications"
    cases["apps-none"] = d

    d = copy.deepcopy(base)
    for r in d["applications"]:                        # -> nothing to place
        r["LastUpdateDate"] = r["DateOfLastUpdate"] = None
    cases["apps-undated"] = d

    # Every application pushed years back, so the focus window is empty. The
    # axis must still draw, and the split must still be marked -- an empty
    # 90 days is a finding, not a reason to hide the window.
    d = copy.deepcopy(base)
    for i, r in enumerate(d["applications"]):
        r["LastUpdateDate"] = r["DateOfLastUpdate"] = "2019-%02d-14T00:00:00" % (i % 12 + 1)
    for r in d["contractsTotalSummary"]:
        r["Applications90D"] = 0
    cases["apps-quiet"] = d

    # Every application on one day. Pathological rather than realistic, and the
    # point is the lane cap: without it this rendered a 565px chart.
    d = copy.deepcopy(base)
    for r in d["applications"]:
        r["LastUpdateDate"] = r["DateOfLastUpdate"] = "2023-06-14T00:00:00"
    cases["apps-sameday"] = d

    # A contract type outside the glyph map. The marker must render blank
    # rather than being filed under a category nobody chose.
    d = copy.deepcopy(base)
    for r in d["applications"]:
        r["ContractType"] = "Murabaha Facility"
    cases["apps-unknown-type"] = d

    # The delivered 90-day counter disagreeing with the rows beside it.
    d = copy.deepcopy(base)
    for r in d["contractsTotalSummary"]:
        r["Applications90D"] = 9
    cases["apps-conflict"] = d

    return cases


def _blocks(r):
    """Section 07's block labels, without their counts."""
    return [b.split("(")[0].strip() for b in r["hm"]["blocks"]]


# What each case must be true of, beyond the universal checks. Guards against a
# mutation that silently matched nothing.
EXPECT = {
    "no-email": lambda r: r["tiles"] == 4,
    # NOTE: "reference" is the one case that asserts something about every
    # section, so it lives at the BOTTOM of this dict with the section 06
    # checks. Do not add a second "reference" key here -- a duplicate silently
    # shadows the other and the run still goes green.
    "no-expiry": lambda r: "not reported" in (r["expiry"] or "").lower(),
    "expired-passport": lambda r: (r["expiry"] or "").lower().startswith("expired"),
    "no-vintage": lambda r: r["vintage"] is None,
    "no-fh-band": lambda r: len(r["bands"]) == 1,

    # Section 05. Text is asserted alongside the tone because the whole point of
    # the 24-month panel is that the delivered value reaches the screen VERBATIM.
    "ws-severe": lambda r: (r["wsx"][0]["cls"] == "red"
                            and r["wsx"][0]["text"] == "Write-off"
                            and r["wsxTag"] == "Severe status on file"),
    "ws-adverse": lambda r: (r["wsx"][0]["cls"] == "amber"
                             and r["wsx"][0]["text"] == "Arrangement"
                             and r["wsxTag"] == "Adverse history"),
    "ws-unknown": lambda r: (r["wsx"][0]["cls"] == ""
                             and r["wsx"][0]["text"] == "Restructured Facility"
                             and r["wsxTag"] == "Partly reported"),
    "ws-absent": lambda r: (r["wsx"][0]["pending"]
                            and r["wsx"][0]["text"] is None
                            and r["wsxTag"] == "Partly reported"),
    "ws-count": lambda r: (r["wsx"][2]["cls"] == "amber"
                           and r["wsx"][2]["text"] == "3"
                           and r["wsxTag"] == "Adverse history"),
    "ws-count-absent": lambda r: (r["wsx"][2]["pending"]
                                  and r["wsx"][2]["text"] is None
                                  and r["wsxTag"] == "Partly reported"),
    "delay-24m": lambda r: "47 days" in (r["wsxSub"] or "") and r["wsxSubRed"],
    "delay-absent": lambda r: "Not reported" in (r["wsxSub"] or ""),

    # Section 06. A guarantor block always renders, so `roles` is the assertion
    # that the split exists at all; `nil` proves which of the two statements
    # the block chose.
    "reference": lambda r: (_s1(r) and _wsx_ref(r)
                            and r["apps"]["events"] == 15
                            and r["apps"]["focus"] == 5
                            and r["apps"]["taken"] == 6
                            and r["apps"]["glyphless"] == 0
                            and [f["cat"] for f in r["fac"]] == ["I", "C", "N", "S"]
                            and r["fac"][1]["roles"] == ["Main holder", "Guarantor"]
                            and r["fac"][1]["util"]["v"] == "57%"
                            and r["fac"][1]["util"]["w"] == "57%"
                            and not r["fac"][1]["util"]["over"]
                            and r["fac"][2]["empty"]
                            and all("No exposure reported" in (f["nil"] or [""])[0]
                                    for f in r["fac"] if f["nil"])
                            and _blocks(r) == ["Active facilities",
                                               "Closed · last 6 months",
                                               "Closed · beyond 6 months",
                                               "Services — no arrears"]
                            and r["hm"]["rows"] == 15
                            and r["hm"]["roles"] == []),
    "guarantor-live": lambda r: (r["fac"][1]["nil"] == []
                                 and r["fac"][1]["roles"] == ["Main holder", "Guarantor"]),
    "overdue": lambda r: r["fac"][0]["od"],
    "util-over": lambda r: (r["fac"][1]["util"]["over"]
                            and r["fac"][1]["util"]["w"] == "100%"
                            and r["fac"][1]["util"]["v"] == "137%"),
    "util-absent": lambda r: r["fac"][1]["util"] is None,

    # Section 07. The reference customer's one active service is clean, so it
    # leaves the active block and the "no arrears" fold exists.
    "svc-arrears": lambda r: ("Services — no arrears" not in _blocks(r)
                              and "SServices (1)" in r["hm"]["groups"]),
    "closed-undated": lambda r: (r["hm"]["undated"] == 10
                                 and "Closed · last 6 months" not in _blocks(r)),
    "guarantor-role": lambda r: r["hm"]["roles"].count("Guarantor") == 2,

    # Section 08. The reference payload has 15 dated applications, 5 of them
    # inside the window and 6 disbursed.
    "apps-none": lambda r: r["apps"]["events"] == 0 and r["apps"]["empty"],
    "apps-undated": lambda r: r["apps"]["events"] == 0 and r["apps"]["empty"],
    "apps-quiet": lambda r: (r["apps"]["events"] == 15
                             and r["apps"]["focus"] == 0
                             and not r["apps"]["empty"]),
    "apps-unknown-type": lambda r: r["apps"]["glyphless"] == 15,
    "apps-conflict": lambda r: any("row" in t for t in r["apps"]["tags"]),
    "apps-sameday": lambda r: r["apps"]["events"] == 15 and r["apps"]["h"] <= 200,
}


def _s1(r):
    return r["tiles"] == 5


def _wsx_ref(r):
    return (r["wsx"][0]["cls"] == "green"
            and r["wsx"][0]["text"] == "Active Payments"
            and r["wsx"][1]["pending"]
            and r["wsx"][2]["cls"] == "green"
            and r["wsx"][2]["text"] == "0"
            and "0 days" in (r["wsxSub"] or ""))


def _wsx(got) -> str:
    """Section 05's three panels as tones, for the run table."""
    out = []
    for panel in got["wsx"]:
        out.append("pending" if panel["pending"] else (panel["cls"] or "ungraded"))
    # The label and value spans are adjacent in the markup -- the gap is CSS --
    # so textContent runs them together as "... 24m0 days". Split on the label's
    # tail rather than on whitespace.
    delay = (got.get("wsxSub") or "").split("24m")[-1].strip() or "-"
    return "%s · %s" % ("/".join(out), delay)


def _fac(got) -> str:
    """Section 06's utilisation line and what the card guarantor blocks said."""
    cards = got.get("fac") or []
    card = cards[1] if len(cards) > 1 else None
    util = "no line"
    if card and card["util"]:
        util = "%s%s" % (card["util"]["v"], " OVER" if card["util"]["over"] else "")
    nils = sum(1 for f in cards if f["nil"])
    rows = sum(1 for f in cards if f["roles"] and not f["nil"])
    od = " od" if any(f["od"] for f in cards) else ""
    return "%s · %d nil / %d rows%s" % (util, nils, rows, od)


def main() -> int:
    base = json.load(io.open(paths.PAYLOAD, encoding="utf-8"))
    cases = build_cases(base)
    tmp = paths.work("_synthetic_payload.json")
    fails = []

    print("%-16s %-9s %-5s %-22s %-9s %-24s %s"
          % ("case", "s1/s2", "grid", "rows (tiles, fill%)", "vintage",
             "05 panels", "06 util / guarantor"))
    for name, data in cases.items():
        io.open(tmp, "w", encoding="utf-8").write(json.dumps(data))
        html = paths.render(tmp)
        for width in (1560, 1509):
            got = paths.probe(html, JS, width, sentinel="Y")
            if width == 1560:
                rows = " ".join("%dx%.0f%%" % (r["n"], r["fill"]) for r in got["rows"])
                print("%-16s %-9s %-5s %-22s %-9s %-24s %s"
                      % (name, "%d/%d" % (got["s1"], got["s2"]),
                         "%dtr" % got["tracks"], rows,
                         got["vintage"] or "(none)", _wsx(got), _fac(got)))

            # Section 05's frame: three panels, always, whatever the payload
            # carries. A missing figure becomes a stated absence in its panel;
            # it never removes the panel, because a window that vanishes reads
            # as a window with nothing adverse in it.
            if len(got["wsx"]) != 3:
                fails.append("%s@%d: section 05 rendered %d panels, not 3"
                             % (name, width, len(got["wsx"])))
            for panel in got["wsx"]:
                if panel["clip"]:
                    fails.append("%s@%d: a worst-status panel clips" % (name, width))

            # Section 06's frame: four category cards, always, and every one of
            # them either empty or carrying BOTH role blocks. A card that shows
            # only the main holder would leave a reader to infer the guarantor
            # position from silence, which is the thing the split exists to stop.
            if len(got["fac"]) != 4:
                fails.append("%s@%d: section 06 rendered %d cards, not 4"
                             % (name, width, len(got["fac"])))
            chips = set(f["chipBg"] for f in got["fac"] if f["chipBg"])
            if len(chips) > 1:
                fails.append("%s@%d: category chips are not one colour (%s)"
                             % (name, width, ", ".join(sorted(chips))))
            for card in got["fac"]:
                if card["clip"]:
                    fails.append("%s@%d: facility card %s clips"
                                 % (name, width, card["cat"]))

            # Section 07: every facility reaches exactly one bucket. A row that
            # falls out of all four would simply vanish from the report, which
            # is the one failure mode this restructure could introduce.
            if got["hm"]["rows"] != 15:
                fails.append("%s@%d: section 07 lists %d facilities, not 15"
                             % (name, width, got["hm"]["rows"]))
            if got["hm"]["clip"]:
                fails.append("%s@%d: section 07 clips" % (name, width))
            # Section 08: every dated application reaches the axis. A marker
            # that falls off it vanishes from the report entirely.
            if not got["apps"]["empty"] and got["apps"]["events"] != 15:
                fails.append("%s@%d: section 08 plotted %d applications, not 15"
                             % (name, width, got["apps"]["events"]))
            if got["apps"]["clip"]:
                fails.append("%s@%d: section 08 clips" % (name, width))
            # The lane cap is what keeps this bounded. Without it the chart's
            # height is a function of how many applications share a date.
            if got["apps"]["h"] > 200:
                fails.append("%s@%d: section 08's chart is %dpx tall -- the lane "
                             "cap is not holding" % (name, width, got["apps"]["h"]))

            if got["hm"]["misaligned"]:
                fails.append("%s@%d: section 07's strips are out of register in "
                             "%d cell(s) -- a month does not line up with itself "
                             "across status / DPD / utilisation"
                             % (name, width, got["hm"]["misaligned"]))
                if not card["empty"] and card["roles"] != ["Main holder", "Guarantor"]:
                    fails.append("%s@%d: card %s has roles %r, not both"
                                 % (name, width, card["cat"], card["roles"]))

            for row in got["rows"]:
                if row["clip"]:
                    fails.append("%s@%d: a tile clips" % (name, width))
                if row["fill"] < 97.0:
                    fails.append("%s@%d: row only %.1f%% full -- hole in the grid"
                                 % (name, width, row["fill"]))
                if not row["equal"]:
                    fails.append("%s@%d: tiles in a row are unequal heights"
                                 % (name, width))
            if got["ppClip"]:
                fails.append("%s@%d: the passport value line clips" % (name, width))
            if got["overflow"]:
                fails.append("%s@%d: horizontal overflow" % (name, width))
        check = EXPECT.get(name)
        if check and not check(got):
            fails.append("%s: the mutation did not take -- this case proved nothing"
                         % name)

    print()
    if fails:
        seen = []
        for f in fails:
            if f not in seen:
                seen.append(f)
        print("FAIL %d:" % len(seen))
        for f in seen[:20]:
            print("   - " + f)
        return 1
    print("PASS  every row full and equal-height, nothing clips or overflows, "
          "and every mutation took effect")
    return 0


if __name__ == "__main__":
    sys.exit(main())
