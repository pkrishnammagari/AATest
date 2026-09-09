"""Credit facilities -- detail & 36-month conduct heatmap.

Sources: contracts joined to contractsHistory (see derive/facilities.py).

The section markup is static; the rows are built client-side from the blob that
js.py assembles, which is where the contracts/history join lands.

The one thing this section must get right is the difference between a month the
bureau reported as current and a month it did not report at all. Coverage here
is sparse -- one contract has 36 months, most have between one and eight -- so
painting unreported months green would turn missing data into a clean record.
"""

from __future__ import annotations

from ...derive import facilities
from .. import components as c

META = {
    "title": "Credit facilities — detail &amp; 36-month conduct",
}


def render(ctx, meta) -> str:
    rows = facilities.all_facilities(ctx)
    if not rows:
        return c.section_card(
            body=c.empty_state("No contracts reported",
                               "The contracts array is empty in this payload."),
            **meta)

    reported = sum(f.months_reported for f in rows)
    # Only months each facility was actually open count as possible -- a loan
    # open three months reported 3/3 is complete, and counting 36 for it
    # understated every short facility's coverage.
    possible = max(1, sum(f.possible_months for f in rows))
    coverage = ('<span class="hm-note">Coverage: %d of %d facility-months '
                'reported (%d%%), counting only the months each facility was '
                'open inside the window. Unreported months are shown grey — '
                'absence is not a clean record.</span>'
                % (reported, possible, round(reported * 100.0 / possible)))

    body = """
      <div class="hm-wrap">
        <div class="hm-scroll"><div class="hm" id="heatmap"></div></div>
        <div class="hm-legend">
          <span class="lg"><i style="background:var(--dpd0)"></i>Current</span>
          <span class="lg"><i style="background:var(--dpd1)"></i>1–29</span>
          <span class="lg"><i style="background:var(--dpd2)"></i>30–59</span>
          <span class="lg"><i style="background:var(--dpd3)"></i>60–89</span>
          <span class="lg"><i style="background:var(--dpd4)"></i>90+</span>
          <span class="lg"><i style="background:var(--dpd-none)"></i>Not reported / pre-open</span>
          <span class="lg"><i style="background:var(--dpd-closed)"></i>After closure</span>
          <span class="lg" style="border-left:1px solid var(--line); padding-left:13px"><i style="background:var(--green-mid); height:7px"></i>Utilisation ≤ 100%</span>
          <span class="lg"><i style="background:var(--red); height:7px"></i>Over limit &gt; 100%</span>
          {coverage}
        </div>
        <div class="st-legend">
          <div class="stl-head" id="stlHead"></div>
          <div class="stl-all" id="stlAll">
            <div class="stl-grid" id="stlGrid"></div>
            <div class="stl-note">Codes, wording and severity ranking are supplied by AECB. Colour follows the bureau ranking — red at 60 or below, amber above 60 and below 100, grey at 100. A code missing from the table is ringed: its severity is unknown, never assumed clean.</div>
          </div>
        </div>
      </div>
    """.format(coverage=coverage)

    # AECB's own words. ActiveFlag delivers "Active" and "Closed", so the tag
    # says Active and Closed -- not "open", which is ours and does not appear
    # anywhere in the payload.
    active_n = sum(1 for f in rows if not f.closed)
    aside = c.tag("%d Active · %d Closed" % (active_n, len(rows) - active_n))
    return c.section_card(body=body, aside=aside, **meta)
