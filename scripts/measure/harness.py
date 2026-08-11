"""Capture computed-style + geometry vectors for the report.

Every width in paths.WIDTHS x both rail states, written as one JSON file per
combination. Run it identically before and after a change so the two captures
are comparable; capture the BEFORE from a backup tree, not from memory:

    # before, from a backup extracted somewhere outside the repo
    AECB_ROOT=/tmp/backup/AECBAnalyzerV2_V1 .venv/bin/python \
        scripts/measure/harness.py before

    # after, from the live tree
    .venv/bin/python scripts/measure/harness.py after

    .venv/bin/python scripts/measure/compare.py before after s1,s2

Python 3.9 compatible.
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths                                                   # noqa: E402
import watch                                                   # noqa: E402

# Properties that decide whether an element RENDERS differently. Deliberately
# not colour: a colour pass is verified by reading computed colour directly,
# and including it here would make every capture churn on unrelated work.
PROPS = ["fontSize", "lineHeight", "fontWeight", "letterSpacing", "padding",
         "margin", "gap", "gridTemplateColumns", "width", "height"]

JS = """
<script>
window.addEventListener('load', function () {
  setTimeout(function () {
    var PROPS = __PROPS__;
    var out = {watch: {}, leak: [], meta: {}};

    out.meta.vw = window.innerWidth;
    out.meta.railOff = document.body.classList.contains('rail-off');
    out.meta.colw = getComputedStyle(document.body).getPropertyValue('--colw').trim();
    out.meta.f = getComputedStyle(document.body).getPropertyValue('--f').trim();
    out.meta.bodyH = Math.round(document.body.scrollHeight);
    out.meta.overflowX = document.documentElement.scrollWidth >
                         document.documentElement.clientWidth;
    out.meta.sections = {};
    [].slice.call(document.querySelectorAll('section.sec')).forEach(function (s) {
      out.meta.sections[s.id] = Math.round(s.getBoundingClientRect().height);
    });

    __SEL__.forEach(function (sel) {
      var e;
      try { e = document.querySelector(sel); } catch (err) { e = null; }
      if (!e) { out.watch[sel] = null; return; }
      var cs = getComputedStyle(e), r = e.getBoundingClientRect(), rec = {};
      PROPS.forEach(function (p) { rec[p] = cs[p]; });
      rec.rectW = r.width.toFixed(2);
      rec.rectH = r.height.toFixed(2);
      rec.scrollW = e.scrollWidth;
      rec.clientW = e.clientWidth;
      out.watch[sel] = rec;
    });

    /* EVERY element, tagged with the section it belongs to. The comparator
       keys these PER SECTION, not by this global index -- when a section's
       markup changes, every index after it shifts and an index-keyed compare
       lines up different elements against each other. That mistake once
       produced 17,245 false failures. */
    var all = document.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      var c = getComputedStyle(el), b = el.getBoundingClientRect();
      var sec = el.closest ? el.closest('section.sec') : null;
      out.leak.push(i + '|' + (sec ? sec.id : '-') + '|' + el.tagName + '|' +
                    (el.className || '') + '|' +
                    c.fontSize + '|' + c.padding + '|' + c.gap + '|' +
                    b.width.toFixed(2) + '|' + b.height.toFixed(2));
    }

    document.title = 'P<<' + btoa(unescape(encodeURIComponent(
      JSON.stringify(out)))) + '>>P';
  }, 800);
});
</script>
""".replace("__SEL__", json.dumps(watch.ALL)).replace("__PROPS__", json.dumps(PROPS))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    outdir = sys.argv[1]
    if not os.path.isabs(outdir):
        outdir = paths.work(outdir)
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    html = paths.render()
    for state, doc in sorted(paths.rail_variants(html).items()):
        for width in paths.WIDTHS:
            data = paths.probe(doc, JS, width, sentinel="P")
            target = os.path.join(outdir, "%s_%d.json" % (state, width))
            io.open(target, "w", encoding="utf-8").write(
                json.dumps(data, indent=1, sort_keys=True))
            print("  %-8s %5dpx  bodyH=%-6s sections=%s"
                  % (state, width, data["meta"]["bodyH"],
                     " ".join("%s:%s" % (k, v) for k, v
                              in sorted(data["meta"]["sections"].items(),
                                        key=lambda kv: int(kv[0][1:])))))
    print("wrote %d captures to %s" % (2 * len(paths.WIDTHS), outdir))
    print("tree: %s" % paths.ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
