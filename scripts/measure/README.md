# scripts/measure — the geometry harness

This is development tooling and is not part of the deployed app. Nothing here
is imported by `aecb/` or `app.py`. The tools render the report
and measure the result in headless Chrome.

**Use it for any change to `report.css` or to a section's markup.** The
viewport width changes the grid at several breakpoints, and a change that
looks right at one width often breaks another. Measuring is the only way
every corner gets checked. (The AI Analysis view hides the report rather than
reflowing it, so it is captured as its own scope, not as a layout state.)

## Requirements

- Chrome or Chromium. It is found automatically; override the path with
  `AECB_CHROME`.
- Pillow, for `shots.py` only. Pillow is deliberately **not** in
  `requirements.txt`, which is the air-gapped runtime bundle and must stay
  minimal.

Nothing is written inside the repository. The work area defaults to a temp
directory; override it with `AECB_WORK`. `AECB_ROOT` selects the source tree
to render and `AECB_PAYLOAD` the payload.

## The workflow

```bash
# 0. Commit, then put the BASELINE in a second checkout. A stash is not
#    enough: harness.py must execute the pre-change code in its own tree via
#    AECB_ROOT (Python caches the first `aecb` package it imports; see the
#    traps below).
git worktree add ../AECB_baseline HEAD

# 1. Capture BEFORE from the baseline worktree, so both captures run through
#    identical probe code even after you edit the harness itself.
AECB_ROOT=../AECB_baseline \
    .venv/bin/python scripts/measure/harness.py before

# 2. Make the change.

# 3. Capture AFTER, from the live tree.
.venv/bin/python scripts/measure/harness.py after

# 4. Check that the change stayed where you meant it. List the sections you
#    MEANT to change (s1..s8, or `analysis` for the AI view); everything
#    else must be identical.
.venv/bin/python scripts/measure/compare.py before after s1,s2

# 5. Payload shapes the reference customer does not produce.
.venv/bin/python scripts/measure/synthetic.py

# 6. Look at it. Computed styles can be right while the page looks wrong.
.venv/bin/python scripts/measure/shots.py s1 s2

# 7. When done, remove the baseline worktree.
git worktree remove ../AECB_baseline
```

## The files

| File | Does |
|---|---|
| `paths.py` | Root, work-folder and Chrome discovery; rendering; layout-state variants; the probe and screenshot primitives; `without_csp()`. Every path is derived or overridable, because these scripts must run against a baseline worktree as well as the live tree. |
| `watch.py` | Maps selectors to sections. **Add to this when a section gains a class family**, or the comparator stops watching what you just changed. |
| `harness.py` | Captures every width × every layout state (one, the report) to JSON. |
| `compare.py` | Checks containment, height and no new clipping. Prints the Returns (§05) mirror witnesses: the rendered boxes that `sections/returns.py` `_TILE_BASE` / `_TILE_ENTRY` / `_TILE_GAP` / `_COL_W` must match. |
| `synthetic.py` | Payload variants: no e-mail, long address, expired passport, no vintage band, no FH band, and more. Each case checks that it produced the shape it intended. |
| `shots.py` | Per-section images of the report. |

The ten widths straddle the layout boundaries:

| Width | Boundary |
|---|---|
| 1572 | Where `--f` first reaches 1 |
| 1560 | The design viewport |
| 1510 / 1509 | The density step |
| 1181 / 1180 | The report column's media-query step |
| 820 | Where the spine disappears |

The remaining widths (1400, 1100 and 760) fill the gaps between them.

## Traps

The code guards each of these, and the comments say so at the point where
they matter.

- **The report's CSP blocks injected probes.** The page allows exactly one
  inline script, by hash. Every probe injection therefore goes through
  `paths.without_csp()`, which removes the CSP `<meta>` from the copy being
  measured. The test suite checks separately that the unmodified page runs
  under its own policy.
- **Never key elements by their global DOM index.** When a section's markup
  changes, every index after it shifts, and an index-keyed comparison reports
  thousands of false failures between unrelated elements. `compare.py` keys
  per section.
- **Ancestor height propagation is not a leak.** Growing a section makes
  `html`, `body`, `.wrap` and `.report` taller. Compare height separately from
  typography, or every run fails for the wrong reason.
- **Check rendered *widths*, not just type.** A CSS specificity slip can leave
  a tile (the §01 address tile, say) a quarter of its intended width while
  every font size is still correct.
- **`querySelector('.sec-title')` returns §01's.** A single-selector "control"
  for a shared class proves nothing. The page-wide sweep in `harness.py` is
  the real proof of containment.
- **A mutation that silently matches nothing gives a green run that proves
  nothing.** `synthetic.py` checks that each case produced the shape it
  intended. Contacts are keyed by `ContactType` (with a trailing space,
  `"E-mail "`), not `Type`. Addresses are their own array, keyed by `Address`.
- **An assertion indented into the wrong loop runs once and proves nothing
  about the rest.** The guarantor-roles check must run per card, via
  `_assert_frames`; one level too deep it runs for a single card. This is the
  same family as the trap above: a green run is evidence only if the check
  demonstrably ran everywhere it claims to.
- **Do not render two trees in one process.** Python caches the first `aecb`
  package it imports, so the second render silently comes from the first
  tree. Use `AECB_ROOT` and separate processes.
- **Some elements legitimately overflow** through absolutely positioned
  `::after` tooltips (`.hint`, `.spine-dot`, `.tv-meter`). Only a regression
  against the baseline is a finding.
- **`aspect-ratio` plus a height constraint silently changes the WIDTH.**
  On §07's `.cell`, `aspect-ratio:1/1` capped with `max-height:23px` lets the
  ratio drive the width down to 23px inside a 27.55px track, so every DPD
  block sits inset in a column that the status and utilisation strips above
  and below still fill. **No probe catches it.** Heights are right, nothing
  clips, nothing overflows, and the section measures shorter. So `.cell`
  carries no `aspect-ratio`; §07's three strips carry explicit heights and a
  shared `min-width`. When strips are meant to share a column grid, check
  their cell left edges and widths against each other, not just each strip's
  own geometry.
- **`.hm{min-width}` is tied to the label column width.** The 36 cells need
  `36*16 + 35*2 = 646px` from their shared `min-width:16px`. With `.hm-rl` at
  320px, `.hm` needs `min-width:1000px`; a narrower `.hm` lets `.hm-cells`
  overflow at 1100, 820 and 760, which the comparator catches. Nothing
  enforces the pairing.
- **Renaming a section moves something outside that section's scope.**
  `.spine-label` takes its text from `META["title"]` via
  `sections.nav_items()`, so a rename changes its rendered width. `compare.py`
  reports that at every width as an out-of-scope change.
  The comparator is working correctly (the label is page chrome, not section
  markup), and there is nothing to fix. Confirm that the width change matches
  the title you changed, and move on. A `.spine-label` change you *cannot*
  account for is the finding.
