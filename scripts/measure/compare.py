"""Compare two captures and assert that a change stayed where it was meant to.

    .venv/bin/python scripts/measure/compare.py before after s1,s2

The third argument lists the sections you MEANT to change (ids as rendered:
s1..s8, matching the displayed numbers 01..08). Everything else must be
identical in BOTH rail states -- that is the whole assertion. What changed
inside the named sections is reported, not judged.

Exits non-zero on any violation, so it can gate a change.

Python 3.9 compatible.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths                                                   # noqa: E402

# Leak-row layout, as written by harness.py.
FIELDS = ["idx", "sec", "tag", "class", "fontSize", "padding", "gap",
          "width", "height"]
RENDERED = [4, 5, 6, 7, 8]      # what decides "renders differently"
HEIGHT = 8

SECTION_NAME = {"s1": "01 identity", "s2": "02 score", "s3": "03 income",
                "s4": "04 returns", "s5": "05 worst status",
                "s6": "06 facilities", "s7": "07 detail", "s8": "08 applications"}

# Witnesses for the one place CSS is mirrored by Python constants:
# sections/returns.py _TILE_BASE / _TILE_ENTRY / _TILE_GAP / _COL_W track these boxes.
# Scoped to #s4 because the bare selectors resolve to section 03's, which
# loads collapsed and therefore measures zero.
MIRRORS = ("#s4 .rec", "#s4 .rec-item", "#s4 .rec-list", "#s4 .rec-t",
           "#s4 .ret-amt", "#s4 .inc-vis")


def load(directory, state, width):
    if not os.path.isabs(directory):
        directory = paths.work(directory)
    with open(os.path.join(directory, "%s_%d.json" % (state, width))) as handle:
        return json.load(handle)


def by_section(capture):
    """Leak rows grouped by section, in document order.

    Keyed per section and NOT by the global DOM index: when a section's markup
    changes, every index after it shifts, and an index-keyed comparison lines
    up unrelated elements against each other.
    """
    out = {}
    for row in capture["leak"]:
        parts = row.split("|")
        out.setdefault(parts[1], []).append(parts)
    return out


def differs(before, after, ignore_height=False):
    moved = [i for i in RENDERED if before[i] != after[i]]
    if ignore_height:
        moved = [i for i in moved if i != HEIGHT]
    return moved


def _compare_run(state, width, before, after, changed, fails, moved_props):
    """All assertions for one (rail state, width) capture pair.

    Returns how many elements were compared. A pure extraction from main() --
    same checks, same order.
    """
    compared = 0

    # --- section heights ---------------------------------------------------
    hb = before["meta"].get("sections", {})
    ha = after["meta"].get("sections", {})
    for sid in sorted(set(hb) | set(ha)):
        if sid in changed:
            continue
        if hb.get(sid) != ha.get(sid):
            fails.append("HEIGHT %s@%d: %s %s -> %s but is not listed as changed"
                         % (state, width, sid, hb.get(sid), ha.get(sid)))

    # --- containment, per section ------------------------------------------
    gb, ga = by_section(before), by_section(after)
    for sid in sorted(set(gb) | set(ga)):
        if sid in changed:
            for rb, ra in zip(gb.get(sid, []), ga.get(sid, [])):
                for i in differs(rb, ra, ignore_height=True):
                    moved_props.setdefault(sid, set()).add(FIELDS[i])
            continue
        rows_b, rows_a = gb.get(sid, []), ga.get(sid, [])
        if len(rows_b) != len(rows_a):
            fails.append("SCOPE %s@%d: %s element count %d -> %d"
                         % (state, width, sid, len(rows_b), len(rows_a)))
            continue
        for rb, ra in zip(rows_b, rows_a):
            if rb[2] != ra[2] or rb[3] != ra[3]:
                fails.append("SCOPE %s@%d: %s markup diverged at <%s>"
                             % (state, width, sid, rb[2].lower()))
                break
            moved = differs(rb, ra, ignore_height=True)
            if moved:
                fails.append("SCOPE %s@%d: %s <%s class=%r> %s"
                             % (state, width, sid, rb[2].lower(), rb[3][:28],
                                ", ".join("%s %s->%s" % (FIELDS[i], rb[i], ra[i])
                                          for i in moved)))
            compared += 1

    # --- nothing may clip or overflow WORSE than before ---------------------
    # Several elements legitimately overflow their box via absolutely
    # positioned ::after tooltips (.hint, .spine-dot, .ss-marker,
    # .tv-meter) and always did. Only a regression is a finding.
    if after["meta"]["overflowX"] and not before["meta"]["overflowX"]:
        fails.append("OVERFLOW %s@%d: the page now scrolls horizontally"
                     % (state, width))
    for sel, ra in after["watch"].items():
        rb = before["watch"].get(sel)
        if not ra or not rb:
            continue
        over_a = ra["scrollW"] - ra["clientW"]
        over_b = rb["scrollW"] - rb["clientW"]
        if over_a > 1 and over_a > over_b:
            fails.append("CLIP %s@%d: %s overflows by %d (was %d)"
                         % (state, width, sel, over_a, over_b))
    return compared


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    before_dir, after_dir = sys.argv[1], sys.argv[2]
    changed = set(s for s in (sys.argv[3].split(",") if len(sys.argv) > 3 else [])
                  if s)

    fails, moved_props, compared = [], {}, 0

    for state in paths.STATES:
        for width in paths.WIDTHS:
            before, after = load(before_dir, state, width), load(after_dir, state, width)
            compared += _compare_run(state, width, before, after,
                                     changed, fails, moved_props)

    # --- report ---------------------------------------------------------
    print("=" * 72)
    b1560 = load(before_dir, "railoff", 1560)
    a1560 = load(after_dir, "railoff", 1560)
    print("Section heights at 1560 (rail closed / rail open):")
    bo, ao = b1560["meta"]["sections"], a1560["meta"]["sections"]
    bn = load(before_dir, "railon", 1560)["meta"]["sections"]
    an = load(after_dir, "railon", 1560)["meta"]["sections"]
    for sid in sorted(set(ao), key=lambda s: int(s[1:])):
        mark = "  <- changed" if sid in changed else ""
        arrow = "" if (bo.get(sid) == ao.get(sid) and bn.get(sid) == an.get(sid)) else \
                "   was %s / %s" % (bo.get(sid), bn.get(sid))
        print("   %-16s %4s / %-4s%s%s"
              % (SECTION_NAME.get(sid, sid), ao.get(sid), an.get(sid), arrow, mark))

    print("\nSection 04 mirror witnesses at 1560, rail closed")
    print("   (sections/returns.py _TILE_BASE/_TILE_ENTRY/_TILE_GAP/_COL_W track these):")
    for sel in MIRRORS:
        rb, ra = b1560["watch"].get(sel), a1560["watch"].get(sel)
        if not rb or not ra:
            continue
        print("   %-14s font %-10s pad %-16s rectW %-8s  %s"
              % (sel, ra["fontSize"], ra["padding"], ra["rectW"],
                 "unchanged" if rb == ra else "MOVED -- re-measure the constants"))

    if moved_props:
        print("\nWhat moved inside the sections you named:")
        for sid in sorted(moved_props, key=lambda s: int(s[1:])):
            print("   %-16s %s" % (SECTION_NAME.get(sid, sid),
                                   ", ".join(sorted(moved_props[sid]))))

    print("=" * 72)
    if fails:
        unique = []
        for f in fails:
            if f not in unique:
                unique.append(f)
        print("FAIL  %d violation(s):" % len(unique))
        for f in unique[:30]:
            print("   - " + f)
        if len(unique) > 30:
            print("   ... %d more" % (len(unique) - 30))
    else:
        print("PASS  %d elements compared across %d runs; nothing outside %s moved"
              % (compared, 2 * len(paths.WIDTHS),
                 ", ".join(sorted(changed)) if changed else "any section"))
    print("=" * 72)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
