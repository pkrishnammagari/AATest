# scripts/measure — the geometry harness

Dev tooling, not part of the deployed app. Nothing here is imported by
`aecb/` or `app.py`; it renders the report and measures the result in headless
Chrome.

**Use it for any change to `report.css` or to a section's markup.** The page has
two independent layout axes — viewport width *and* whether the brief rail is
open — and a change that looks right in one corner routinely breaks another.
Measuring is not optional diligence here; it is the only way the four corners
get checked at all.

## Requirements

Chrome or Chromium (found automatically; override with `AECB_CHROME`), and
Pillow for `shots.py` only. Pillow is deliberately **not** in
`requirements.txt` — that file is the air-gapped runtime bundle and must stay
minimal.

Nothing writes inside the repo: the work area defaults to a temp directory
(override with `AECB_WORK`).

## The workflow

```bash
# 0. Back up first. There is no VCS in this tree.
cd .. && tar --exclude=.venv --exclude=wheels --exclude=wheels.tgz \
    -czf ../AECBAnalyzerV2_V1_code_$(date +%Y%m%d-%H%M%S).tar.gz AECBAnalyzerV2_V1
#    Extract it somewhere and `diff -r` against the live tree. An unverified
#    backup is not a backup.

# 1. Capture BEFORE — from the backup tree, so both captures run through
#    identical probe code even after you edit the harness itself.
AECB_ROOT=/path/to/extracted/AECBAnalyzerV2_V1 \
    .venv/bin/python scripts/measure/harness.py before

# 2. Make the change.

# 3. Capture AFTER, from the live tree.
.venv/bin/python scripts/measure/harness.py after

# 4. Assert it stayed where you meant it to. List the sections you MEANT to
#    change; everything else must be identical in both rail states.
.venv/bin/python scripts/measure/compare.py before after s1,s2

# 5. Payload shapes the reference customer does not produce.
.venv/bin/python scripts/measure/synthetic.py

# 6. Look at it. Computed styles can be right while the page looks wrong.
.venv/bin/python scripts/measure/shots.py s1 s2
```

## The files

| file | does |
|---|---|
| `paths.py` | Root/work/Chrome discovery, render, rail variants, the probe and screenshot primitives. Everything derived or overridable — these scripts must run against a backup tree as well as the live one. |
| `watch.py` | Which selectors belong to which section. **Add to this when a section gains a class family**, or the comparator stops watching the thing you just changed. |
| `harness.py` | Captures every width × both rail states to JSON. |
| `compare.py` | Asserts containment, height, and no new clipping; prints the §04 mirror witnesses. |
| `synthetic.py` | Payload variants: no e-mail, long address, expired passport, no vintage band, no FH band… |
| `shots.py` | Per-section rail-closed vs rail-open images. |

## Things that have already gone wrong here

Each of these cost real time once. They are guarded in the code now; the
comments say so at the point they matter.

- **Never key elements by their global DOM index.** When a section's markup
  changes, every index after it shifts and an index-keyed comparison comes back
  with thousands of false failures comparing unrelated elements. `compare.py`
  keys per section.
- **Ancestor height propagation is not a leak.** Growing a section makes
  `html` / `body` / `.wrap` / `.report` taller. Compare height apart from
  typography or every run fails for the wrong reason.
- **Assert rendered *widths*, not just type.** A CSS specificity slip left the
  §01 address tile a quarter of its intended width while every font-size in the
  vector was still correct.
- **`querySelector('.sec-title')` returns §01's.** A single-selector "control"
  for a shared class is not a control. The page-wide sweep in `harness.py` is
  the real containment proof.
- **A mutation that silently matches nothing gives a green run that proves
  nothing.** `synthetic.py` asserts each case produced the shape it intended.
  Contacts key off `ContactType` (with a trailing space, `"E-mail "`), not
  `Type`; addresses are their own array keyed on `Address`.
- **Do not render two trees in one process.** Python caches the first `aecb`
  package it imports, so the second render silently comes from the first tree.
  Use `AECB_ROOT` and separate processes.
- **Some elements legitimately overflow** via absolutely positioned `::after`
  tooltips (`.hint`, `.spine-dot`, `.ss-marker`, `.tv-meter`). Only a
  regression against the baseline is a finding.
- **`aspect-ratio` plus a height constraint silently changes the WIDTH.** §07's
  `.cell` was `aspect-ratio:1/1`. Capping it with `max-height:23px` on
  7 Aug 2026 made the ratio drive the width down to 23px inside a 27.55px track,
  so every DPD block sat inset inside a column the status and utilisation strips
  above and below still filled. **No probe caught it** — heights were right,
  nothing clipped, nothing overflowed, and the section measured shorter, which
  is what the change was for. It took someone looking at the screen. The lesson
  for the harness: when strips are meant to share a column grid, assert their
  cell LEFT EDGES and WIDTHS against each other, not just their own geometry.
  §07's three strips now carry explicit heights and a shared `min-width`.
- **`.hm{min-width}` is tied to the label column width.** The 36 cells need
  `36*16 + 35*2 = 646px` from their shared `min-width:16px`. Widening `.hm-rl`
  from 250 to 320 pushed that past `.hm{min-width:920px}` and the comparator
  caught `.hm-cells` overflowing at 1100, 820, 760 and both 1510/1509 rail-open.
  It is 1000 now. Nothing enforces the pairing.
- **Renaming a section moves something outside that section's scope.**
  `.spine-label` takes its text from `META["title"]` via
  `sections.nav_items()`, so a rename changes its rendered width and
  `compare.py` reports it at every width in both rail states as an
  out-of-scope change. That is the comparator working correctly — the label is
  page chrome, not section markup — and there is nothing to fix. Renaming §05
  to "Worst Statuses" on 7 Aug 2026 produced exactly 16 such lines
  (177.34 → 96.30). Confirm the width delta matches the title you changed, and
  move on. If a rename produces a `.spine-label` change you *cannot* account
  for, that is the finding.
