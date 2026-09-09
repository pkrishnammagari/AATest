# AECB Analyzer — handoff

**Opening a fresh session? Read `README.md`, then this file. That is the whole
handover — nothing needs pasting.** This is the running state of play: what the
thing is, what is settled, what is still open, and what was being worked on when
the last context ended. Then **stop and wait for direction** — the *Next task*
section at the end says what is next and what is deliberately still undecided
about it.

> **Note (18 August 2026) — the design mockup has been removed.** `Mockup/` and
> every reference to it are gone: the report is now its own reference. Two
> consequences for reading the dated entries below. First, **`check_no_mock.py`
> is now `scripts/check_report.py`** — historical entries still name the old
> file, and mean this one. Second, its forbidden-literal scan (names, providers
> and figures that only ever existed in the mockup) was **dropped** along with
> the mockup; every other assertion it makes — payload values reaching the page,
> delivered figures shown verbatim, no external references — is unchanged and
> still runs after every change.

Last updated: **2 September 2026**, after a documentation-drift audit and the
fix batch that followed it: uploads made session-scoped again (nothing written
to disk), the 36-month history window enforced at derivation, an ungraded
*unknown* tone for statuses the config cannot rank, escaping tightened, a
dead-code sweep, the section modules renamed to plain names, and scan-readiness
files added — see *Recently landed*. Before that, **19 August**: the income
confirmation model, the page-width cap removal (`--page-max:none`), and a
synthetic delinquent fixture with its generator. Before that, **7 August
2026**: §08 rebuilt as **Recent Applications** — one split-axis timeline,
**234 / 234** — which also closed the last open blocker on the page; §07
restructured into four buckets, compressed, and its three conduct strips put
back into pixel register (**574 / 571**); a compression pass took §06 to
**275 / 283** and §05 to **186 / 201**; §06 rebuilt as
**Active Credit Facilities — Overview** (role split, utilisation line, donut and
counts gone) and §05 gained its max-payment-delay line; and earlier still §05
rebuilt as **Worst Statuses**, a prominence pass on §01's passport tile and
§02's score strip, and the geometry harness committed to `scripts/measure/`.
On 6 August: a documentation staleness pass, the fluid type + density scale
rolled out to **all eight sections**, the teal → FH blue token pass, the
§03/§04 chart-width fix, the §02 gauge fix, and the brief rail made
closed-on-load.

**Every section is now designed and wired.** §05's 36-month worst status —
long the one deliberately unbuilt panel — was **built 9 Sep 2026** with the
RRM defaults (see *Next task* at the end of this file, now marked done, for
what was decided and what refinements remain open).

Read `README.md` first — it documents architecture, config, payload traps and
known gaps. Then skim `aecb/render/tokens.py` and one section module
(`aecb/render/sections/income.py`) to absorb the house style.

---

## What this is

A Streamlit-hosted renderer that turns an archived AECB bureau payload into a
single scannable underwriting screen for Finance House RRM. Goal: collapse
time-to-decision on one customer's credit report.

Python builds a SELF-CONTAINED HTML document; Streamlit's job is narrow — pick a
payload, host it in one iframe, offer it as a download. The whole report is ONE
component iframe because the sticky top bar, spine nav and scrollspy need a
single scrolling context.

## Hard constraints (do not break)

- Python 3.9 compatible. `streamlit==1.50.0` is the LAST release supporting 3.9.
- ZERO external references — air-gapped server. No CDN, no font host, no URLs.
  Fonts are vendored as base64 in `assets/fonts/fonts_inline.css`.
- Offline install from a pre-built wheel bundle (`scripts/build_wheels.sh`,
  x86_64 cp39 manylinux, no Docker).

## The governing rule

NO FABRICATED VALUE EVER REACHES THE SCREEN. Where the payload has nothing, show
an explicit empty state distinguishing "reported as zero" from "not reported" —
for a credit screen those mean opposite things. Computed figures are tagged
`derived`, bureau figures `delivered`. Enforced by `scripts/check_report.py`,
which fails if a payload value goes missing, a delivered figure stops being
shown verbatim, or an external reference creeps in. RUN IT AFTER EVERY CHANGE.

A second rule earned the hard way: **no sentence on screen may describe only
this payload.** "DateOfLastUpdate is null on 3 of 5 rows" describes one file and
reads as a defect report; "a trend needs two figures the bureau has dated"
describes the section. Counts of this payload's nulls were removed for exactly
this reason — do not reintroduce them.

## Design language established so far

- `tokens.py` is the ONLY place a colour is defined. Brand blue `#00426A` with
  four derived shades. `report.css` uses `var(--*)` throughout.
- RED/AMBER/GREEN are reserved for RISK. Facts that aren't risk signals (e.g.
  residency, vintage band) use brand blue.
- **There is no teal in the palette** (settled 6 Aug 2026). No `--teal*` token
  any more, so a rule cannot reach for one. Everything it used to dress that
  still exists — the `.sec-toggle` / `.hint` hovers, `.ai-mark`, `.stl-more`
  and the `delivered` provenance mark — resolves through the fh-blue five (the
  rest of the old list — `.cite`, `.fb-b`, `.sec.flash`, `.mk.own`,
  `.phase.own`, `.verify-link` — has since been deleted, in the §08 rewrite
  and the 2 Sep 2026 dead-code sweep). The reason to record:
  a second brand colour beside Finance House blue reads as a distinction the
  page is not drawing, and on `.prov-mark.delivered` it actively competed with
  the amber/red severity tags beside it. **Do not reintroduce a teal token.**
  On a wash use `--fh-blue-ink` for text and `--fh-blue-line` for the hairline;
  `--fh-blue-d` is for pressed/hover fills and gradient feet only.
- The ONE surviving teal hue is `cat-c`, and it is not brand. `cat-i/c/n/s/x`
  are a CATEGORICAL set — five hues told apart at 17px, carrying no ordering —
  and `cat-c` stays teal because it has to stay distinguishable from `cat-i`,
  which is already blue. `.fac-cat` / `.hm-gc` now refer to those tokens
  instead of reaching past them to `--teal` / `--brass`.
- **Tiles are the record vocabulary.** `.rec` / `.rec-h` / `.rec-meta` for a
  delivered record, `.rec-none` (dashed) for a stated absence, `.rec-list` for
  the stack. §03 and §04 both use it; anything new should too.
- **Two halves per card**, `.inc-split`: delivered records left, what can be
  drawn from them right, divided by a hairline. The left half never depends on
  the right — with nothing drawable the records still stand alone.
- Compression is a running theme: §01 validity moved into the top bar; identity
  collapsed onto a name line plus a quieter trait line; score section rebuilt
  277px→160px. (That 160 is the rail-OPEN figure and is still the anchor; §02
  measures 168 in the rail-closed load state now that it is on the fluid scale.
  The status table carries both — read heights there, not from this history.)
- Section numbering and anchors come from POSITION in
  `aecb/render/sections/__init__.py` — never hard-code a section number. Note
  the file names run `s02..s09` while the DISPLAYED numbers run `01..08`,
  because validity moved to the top bar.
- Charts for §03/§04 are **inline SVG built in Python**, not `report.js`:
  whether a chart can be drawn at all depends on which dates the payload
  carries, and that decision belongs beside the data. `report.js` still owns the
  heatmap and the enquiry chart, which read `window.__AECB` from `js.py`. The
  donut and card-utilisation charts went with the §06 rebuild.
- The shared time axis lives in `aecb/render/svgtime.py` — §03 and §04 both use
  it, so the two timelines cannot drift.
- **A chart fills its half side by side, and is capped when stacked.**
  `.inc-svg` was pinned to 560px at every width, so closing the brief rail
  widened the column to ~706px and left the chart short of it — a dead gutter
  with the `delivered` badge stranded over it, which reads as a rendering
  fault rather than a layout choice. It now fills the column above 1180px, and
  the 560px cap moved into the stacked query where the reason for it actually
  holds. The magnification this costs was bounded to about 1.37× by `.wrap`'s
  1572px max-width; since the page cap came off (`--page-max:none`, 19 Aug
  2026) it is bounded only by the viewport — re-cap `--page-max` to bound it
  again. Stacked it would be twice the side-by-side figure even at 1572, which
  is why the stacked cap stays.
- **Whatever is elastic in a row has to absorb everything the row gains.**
  §02's `.ss-gauge` was capped at 660px while `.ss-hist` is pushed right by
  `margin-left:auto`, so every pixel past the cap opened as a hole between the
  band chips and the history block — 396px of it at 1560 with the rail closed.
  The cap is gone. Note the distinction from `.inc-svg` above: capping a
  CSS-drawn element buys nothing, because its bar is flexed divs and its ticks
  are placed by percentage, so no type is magnified when it grows. Only the
  Python-built SVGs pay for width, and only they are capped.
- **The brief rail loads CLOSED** (decided 6 Aug 2026, at the user's request).
  The underwriting screen is the deliverable and the AI reading is opt-in; on a
  payload with no model behind it the rail would otherwise open on its own
  "no brief generated" placeholder. The AI Analysis button toggles it back, and
  the rail's own × still closes it. Consequence to remember: **the wide layout
  is now the DEFAULT layout**, so anything calibrated to a column width is
  calibrated to the rail-closed measurement.
- **The page has a FLUID SCALE, and it is anchored** (added 6 Aug 2026; **all
  eight sections are on it**). `--colw` on `body` carries the report column width,
  derived not measured, because `.wrap` is a fixed grid: `100vw` minus 498
  (rail open) or 106 (rail closed). The old 1572px page cap is gone —
  `.wrap`'s max-width is now `:root{--page-max}`, set to `none` with auto
  margins (19 Aug 2026: on a 1728px 16" MacBook the capped page stacked all
  its surplus on the right). Re-cap `--page-max` and these formulas need their
  `min(100vw, cap)` back, or the ramp overstates the column. `--f` is a
  0px→1px progress value along that range, and sizes are written
  `calc(BASE + GAIN * var(--f,0px))` so the current value stays visible as
  `BASE`. The block lives at the END of `report.css` inside an `@supports`
  guard, additively — delete from the `FLUID SCALE` banner to EOF and the px
  design is back, exactly.
  - **`--f` is pinned to `0px` on `body` and only computed on `body.rail-off`.**
    That makes the rail-open state — today's tuned design — exact by
    construction rather than by arithmetic, and removes a would-be type step at
    1180 where the rail stops being a grid track and the column jumps 683→1074.
  - **The range IS the rail**: 1074→1466px, and 392 = 372 rail + its 20px gap.
    Change the rail width in `.wrap` and 392 is visibly wrong. `--f` reaches
    0.9694 at 1560, not 1; full gain needs a viewport of 1572px or wider — the
    ramp clamps there even though the page itself no longer stops.
  - **NO CONTAINER QUERIES, and no `:has()`.** Both are Chrome 105. The
    existing floor is ~Chrome 88 (`aspect-ratio`, flex `gap`) and the download
    gets filed and reopened years later on an unspecified machine. `clamp()` is
    Chrome 79, below the floor we already require.
  - **`--colw` drives type and spacing ONLY** — never a grid track, width or
    flex-basis. That is why `100vw` including the scrollbar gutter is fine:
    worst case ~15px of 392, i.e. 0.31px on the largest figure.
  - **The page chrome is excluded and stays excluded**: the top bar (LOCKED),
    the spine, the brief rail, and the shared card vocabulary `.sec-title` /
    `.sec-no` / `.sec-purpose` / `.tag` / `.na` / `.hint` / `.chevron` /
    `.histflag` / `.prov-badge`. Those are the frame, not the content; growing
    them would scale the page rather than fill it.
  - **`.rec*` gains move Python.** `.rec-t`, `.rec-meta` and `.ret-amt` set the
    rendered height of §04's record tiles, and `sections/returns.py`'s
    `_TILE_BASE` / `_TILE_ENTRY` mirror it. They were re-measured (37/57 →
    39/62) when those sizes went fluid. **Nothing enforces this** — re-measure
    by hand after any change to those rules.
- **An ELEMENT spends its surplus on size or density, never both.** The
  constraint is per element, not per section: §01's tile type gains nothing
  because those tiles get *narrower* at the density step (464→346px), and a
  gain would have to jump downward mid-ramp. Micro mono labels (7–10px) gain
  nothing anywhere: growing them flattens the key/value hierarchy that makes a
  tile scannable.
- **Where the density steps are.** One breakpoint for the whole page,
  `@media (min-width:1510px)` scoped to `body.rail-off`, and only **two**
  sections take it: §01's grid goes 4-up and §07's status-code legend goes
  4-up. Sections with a *data-driven* column count get no density move and
  should not be given one — `.fac-grid` is `repeat(4,1fr)` because AECB has
  four contract categories, `.ret-stats` because there are four counters, the
  heatmap is 36 months, and `.wsx` is `repeat(3,1fr)` because there are three
  delivered windows. §03/§04 already spent their width on `.inc-split`.
  §05 **used** to take a density step (its key/value rows went 2-up); that rule
  and the whole `.wsx-row*` family went with the 7 Aug redesign.
- **§07's cells were half-fluid by accident and are now fluid on purpose.**
  `.cell` used to be `aspect-ratio:1/1` inside `repeat(36,1fr)`, so it grew
  18.7→29.6px on its own while the glyph stayed at 7px — which is why the wide
  heatmap once read as empty squares. Growing the glyph fixed that. The ratio
  itself is **gone** as of 7 Aug 2026 (see the strip-register entry below); the
  band now carries an explicit `calc(20px + 4 * var(--f,0px))`, which is both
  bounded and visible.
- **`.ss-hist` sets §02's whole height, and it had zero slack.** Measured
  82.17 closed / 74.09 open — exactly the strip, because `.score-strip` is
  `align-items:center` and takes its tallest member. `.ss-score` and
  `.ss-gauge` sit ~22–32px under that, and `.ss-bands` had ~13–18px spare.
  **Anything added to the history block grows §02 one-for-one; anything added
  to the band chips up to ~13px is free.** That is not visible in the CSS and
  is the fact to check first before touching §02 again.
- **§02's prominence pass** (7 Aug 2026, at the user's request: make the bands
  impossible to miss, *without the section growing*).
  - The vintage badge is now a **full-width bar across the top of `.ss-hist`**
    reading `VINTAGE … B3`, not a chip beside the figure. It is **paid for, not
    added**: `months` and `Since …` fold into the column beside the figure —
    they fit inside the line the 38–46px figure already occupies — and the
    `Bureau history` caption is gone, its provenance tooltip moved onto the
    figure. Net: the block got *shorter* (82.17→75.98 closed, 74.09→66.89 open).
  - The band chips are **solid fill with white text**, 12px→15px. Solid is
    where the prominence actually comes from; 15px is what the ~13px of slack
    bought, and 16px would have eaten all of it. Red/amber/green is right here
    despite the risk-only rule — a score band *is* a risk grade.
  - `_WASH` / `_INK` are gone from `score.py`; `_FILL` / `_LINE` replace
    them. Both still only map `red` and `amber`, with green as the fallback
    for the green tones. `scoring.fh_band()` no longer defaults an unknown
    band code to green — since 2 Sep 2026 it returns a neutral tone and the
    chip renders uncoloured, because an unrecognised risk band has earned no
    colour.
  - **§02 ended up 6px shorter, not merely not-taller** (168→162 / 160→156).
    `.ss-bands` is now the tallest member at 70, so it — not `.ss-hist` — sets
    the strip height. The zero-slack fact above has moved with it.
- **§05 is now "Worst Statuses": three delivered panels** (7 Aug 2026, at the
  user's request, replacing the old delivered-24m / derived-36m pair).
  - The reason to record, because it is what the section is *for*: **FH policy
    differs by employer segment**, some assessed over 24 months and some over
    36, so an underwriter needs both windows side by side rather than one
    figure that answers half the book.
  - Panels: `contractsTotalSummary.WorstStatus24M` · **derived 36-month
    window** (9 Sep 2026, `facilities.worst_in_window()`, always marked
    `derived`) · `summary.Worststatus`. Both delivered values print
    **VERBATIM** — no
    relabelling, no rounding, no translating display text into a letter code.
    That is an explicit instruction, and `check_no_mock.py` now reads the
    figures back out of `.wsx-worst` and fails the build if either stops
    matching its field. A substring search could not do it: the life-time count
    is `0`.
  - **The old 24m panel read `summary.WorstStatus24M` as a fallback. It no
    longer does.** That field is the same name in the *other* vocabulary — a
    letter code (`U`) where `contractsTotalSummary` carries display text
    (`Active Payments`) — so the fallback made the panel show a different kind
    of value depending on the payload.
  - **`_known_status()` resolves strictly on code or label and returns None
    otherwise**; ungraded renders uncoloured with a *Partly reported* pill.
    When this entry was written, `ctx.status()` returned rank 100 — the clean
    rank — with an invented first-letter code for anything it could not match,
    and grading off it would have painted an unrecognised status green. Since
    2 Sep 2026 `ctx.status()` refuses too (unknown comes back as code `?` with
    rank `None`, drawn as the `.su` unknown tone), but this panel wants the
    config row itself and a plain None, so the strict resolver stays.
  - The life-time figure is a **count**, so non-zero is amber, not red. A count
    says how many, never how deep; depth is §07's.
  - The pending panel takes **no provenance mark** — neither `delivered` nor
    `derived` is true of a panel with no figure behind it.
  - `.wsx-panel` is a flex column and `.wsx-worst` carries `margin:auto 0`.
    Panels stretch to the tallest of the row, which today is the pending one;
    without it a one-word status floats above ~90px of void and reads as
    broken. §05 went **246 / 292 → 234 / 234**.
  - Removed as orphans: `.wsx-rows`, `.wsx-row`, `.wsx-row .k/.v`, `.stcode`,
    and the `body.rail-off .wsx-rows` density rule. `watch.py` was updated to
    match.
  - **The max-payment-delay line** (added later the same day) sits UNDER the
    24-month status, not in a fourth panel: a worst status is a grade and
    carries no magnitude, so `MaxPaymentDelay24M` is the thing that completes
    it. A delivered `0` prints as `0 days` — only a missing field is an
    absence. `.wsx-worst`'s `margin:auto 0` had to move to a `.wsx-fig`
    wrapper, or the figure and the sub-line centre independently and drift
    apart as the panel stretches. It cost **no height**: the figure group is
    62px inside the 80px pending panel that still sets the row.
- **§08 is one split-axis timeline** (7 Aug 2026, at the user's request:
  "a visual representation... enhanced focus on the last 90 days").
  - **The axis is SPLIT and that is the whole idea.** Last 90 days take 62% of
    the width; everything older is compressed into the rest. Linear within each
    zone, continuous at the boundary. On a linear axis the focus window is 90
    of 990 days — 9% — and the cluster that matters is crushed into it.
  - **The distortion is DRAWN, not just stated**: a wash on the focus window, a
    dashed rule at the break, and the two zones labelled in different units
    (`30d`/`60d`/`90d` vs calendar years). Plus a legend line in words. An axis
    that is not linear but looks linear is a lie.
  - **Positions are percentages computed in `derive/applications.py`.** Same
    rule as §07's bucketing: what counts as the focus window is a business fact
    about the payload, not a drawing detail. Percentages rather than an SVG
    viewBox because the chart scales across two rail states and ten widths and
    a viewBox would magnify the 8.5px labels with it. **`render/svgtime.py` is
    deliberately NOT used** — §03/§04 share it so their timelines cannot drift,
    and this one is non-linear by design.
  - **The phase block is closed** (open item 5). AECB's two states are a hollow
    marker (Requested) and a filled one (Disbursed). The mockup's
    NTU/Approved/Rejected are not in the payload and are not invented.
  - **The window is `< 90` days, not `<= 90`.** That is what reconciles the rows
    against the delivered `Applications90D` EXACTLY — five, not six, because one
    application sits on day 90. The inclusive bound was displaying a conflict
    with the bureau that was our own off-by-one. The detector survives as a
    second pill for a payload that genuinely disagrees.
  - **Lane stacking is capped at 4.** Applications close in time are lifted to a
    lane above, never nudged along the axis (that would put them at the wrong
    date). Without a cap the section's height is a function of how many
    applications share a day — a synthetic payload with fifteen on one date
    produced a **565px** chart. Caught by looking at a screenshot of a synthetic
    case, not by an assertion; there is an assertion now.
  - Markers are brand blue, never a risk colour: one application is a fact, and
    it is the CLUSTER that is the signal. The letter is the AECB category
    (I/C/S) matched on a keyword; an unmatched type renders BLANK and says so on
    hover rather than being filed under a guess.
  - Deleted as orphans: `.ret-stats` / `.rs*` (and `components.kpi()`),
    `.enq-tbl*`, `.er-date`, `.enq-divider`, `.inc-conflict`, the whole
    `.phase.*` vocabulary and the `.mk.ntu/.appr/.rej/.own` variants.
    `.phantom-callout` / `.pc-*` were pre-existing orphans in the same block;
    left alone at the time, and deleted on 18 Aug 2026.
  - §08 went **310 / 323 → 234 / 234**.
- **§07 is four buckets, not one list** (7 Aug 2026, at the user's request).
  Every facility lands in exactly one of: **Active facilities** (open),
  **Closed · last 6 months**, **Closed · beyond 6 months**, **Services — no
  arrears** (all three folded). Inside each, facilities group by AECB category.
  - **Which bucket is a PAYLOAD decision, so it is made in `js.py`** — closure
    dates and arrears — and `report.js` only draws what it is handed. That is
    the same rule §03/§04 follow for their charts.
  - **Two heading levels, and they must stay visually distinct.**
    `.hm-blockhead` is the bucket and carries the fold; `.hm-grouphead` is the
    category. If they read alike, four buckets look like eight categories.
  - **An active service with nothing on it is context, not a finding** — which
    is why the active block is not simply "everything not closed". `_in_arrears()`
    is deliberately broad: overdue balance OR current delay OR a current status
    the bureau ranks below normal. Filing a service that IS in arrears under
    "no arrears" is the failure that matters, so every signal counts.
  - **An undated closure joins the OLDER bucket** and the row says *Closed ·
    date not reported*. Claiming a recency the payload cannot support is the
    worse of the two errors, and a blank where a date should be reads as "closed
    but not recently".
  - **Empty categories and empty blocks are omitted, not stated.** §06 is where
    a category's absence is a finding; repeating it here costs up to sixteen
    headings across four blocks to say nothing.
  - Two chips left every row. **Frequency** shows only when AECB delivers one —
    the old *Frequency n/a* was not reporting a missing value, since frequency
    is not in the card or service schema at all. **Role** shows only when it is
    NOT main holder, which is the default across the book; the exception is what
    changes who is liable. `.role.main` and `.freq.na` were deleted as orphans.
  - The header tag is **`5 Active · 10 Closed`** — AECB's own `ActiveFlag`
    words. "Open" was ours and appears nowhere in the payload.
  - **§07 went 652 / 673 → 571 / 564**, and the height was in the LABEL column,
    not the heatmap: at 250px the stat line wrapped to three rows while the 36
    cells needed only 51px. Label to 320px + the two dead chips gone = one line.
  - **THREE STRIPS, ONE COLUMN GRID — this is the constraint to know.** A row
    stacks a status strip, a DPD strip and (cards only) a utilisation strip:
    three separate `repeat(36,1fr)` grids. The only thing keeping their columns
    in register is every cell filling its own track, so all three share
    `grid-template-columns`, `gap` and `min-width:16px`, and each carries an
    explicit height. **`aspect-ratio` must not come back.** It filled the track
    by accident until it was given a `max-height` in the compression pass — the
    ratio then drove the WIDTH down to 23px inside a 27.55px track and every DPD
    block sat inset inside a column the other two still filled. A square cell
    and a shared column cannot both hold at an arbitrary width, and the shared
    column is the one that matters. **The user spotted this on screen; no probe
    did** — heights were right, nothing clipped, nothing overflowed, and the
    section measured shorter, which is what the change was for. `synthetic.py`
    now asserts the three strips' left edges and widths against EACH OTHER, and
    that check was verified to fail (216 cells) with the bug reintroduced.
  - **`.hm{min-width}` is TIED to the label width** and moved 920 → 1000 with
    it. The 36 cells need `36*16 + 35*2 = 646px` from their shared `min-width`.
    Nothing enforces the pairing and the failure only shows at 1100 and below —
    the comparator caught that one, which is what the comparator is for.
- **The §05/§06 compression pass** (7 Aug 2026, at the user's request: "compact
  as possible without looking cluttered"). §06 **378 / 387 → 275 / 283**, a 27%
  cut; §05 **222 / 222 → 186 / 201**. Nothing shrank below its legible size —
  row text is still 11.5px, the balance still 19px, the status still 26px.
  What actually cost the height, because it was not where it looked:
  - **60px of `.fac` row-gap** across seven children, on a 292px card whose
    figures accounted for only 101px. The gap is now 5px, because `.fac-role`
    already carried its own 7px top padding and a hairline — the two were doing
    the same job and a 19px trough before every role heading is what made a
    card of seven short lines read as tall. **Look at the gaps before the type.**
  - **Two role headings at 23.5px each**, where a 9px caption needs nine. The
    default leading on a 9px font adds 4.5px above and below; `line-height:1`
    took it back.
  - The role label then moved ONTO the figure line (`.fac-block`, a wrapping
    flex row). It is that figure's caption, so a line of its own said the same
    thing twice. It wraps back to the old stacked layout at narrow widths, so
    the degradation path is the design we already had.
  - The utilisation bar's `0`/`100%` scale went, reversing the reasoning that
    added it — see the design entry above.
  - §05's pending panel is the tallest member and sets the section on its own,
    so its padding and its detail sentence were the only things worth touching.
    The sentence is now one line at the panel's width; every line it wraps to
    is a line added to all three panels.
- **§01's passport expiry is on the value line**, inside `.v`, not a `.v-sub`
  block after it. It gave the tile a third line while its neighbours had two,
  and `.facts` stretches every tile to the tallest in its row, so that one line
  put dead space in all of them. §01 went 326→305 / 322→301.
  Known limit, measured and accepted: the value line needs ~240px of tile, and
  in **rail-open between 1181 and ~1370px** the tile is only 179–232px, so it
  wraps and the expiry drops to a second line, right-aligned. Everywhere else —
  including the whole rail-closed load state and everything ≤1180 where the
  grid goes 2-up — it is one line. Forcing a block there would restore exactly
  the look this change removed, so it is left to wrap.
- **§06 is now "Active Credit Facilities — Overview", split by role**
  (7 Aug 2026, at the user's request; supersedes the 6 Aug "cards stay
  asymmetric" entry, which described the donut layout that has now gone).
  - **The role split is the point.** Main holder and guarantor are different
    liabilities and FH lends against them differently, so every category
    renders both. A guarantor block that were simply absent would leave an
    underwriter inferring the guarantor position from silence.
  - **The empty guarantor block is backed by a DELIVERED figure, not by empty
    cells.** `TotalBalanceGuaranteed` and `TotalOverdueGuaranteed` both zero →
    *No exposure reported*, tagged `delivered`. The inference runs
    one way only: a book-wide zero means every category is zero, but a non-zero
    total cannot be attributed to a category, so that case falls back to *Not
    reported as guarantor*, untagged. The reference payload's `G` rows are a
    MIX of delivered zeros and nulls, which is why inferring from them would
    have broken the reported-zero/not-reported rule.
  - **The utilisation line sits at CARD level, above the role split**, because
    `CreditUtilizationRate` is delivered once for the category and has no role
    dimension. It reads as book-wide from where it lives and is not:
    33,714 / 59,600 = 56.57%, which is the delivered `"57"`. Verified, not
    assumed.
  - Modelled on `.tv-meter` (a track with a fill), **not** `.ss-gauge` (a zoned
    scale with a marker). `.tv-meter` itself is untouched — the top bar is
    locked. Below 100 the fill is green and proportional; at or above 100 it is
    full and red, so the figure beside the label is the only thing separating
    101% from 300%. It carries **no `0`/`100%` scale**: one was added and then
    removed in the compression pass, because the printed figure beside a track
    filled just over halfway already says the track's full width is 100%.
  - **Balance is the headline in all four cards.** It is the one figure common
    to every category, so promoting it gives the row of cards a single scan
    line. That was a recommendation, not an instruction — revert it to a flat
    row list if it ever reads wrong.
  - **No counts anywhere on the card.** `contractsSummary.TotalNo` spans more
    history than the delivered contract rows, so showing it beside §07's
    per-facility list invites a comparison that cannot be made. `count_summary()`
    is still CALLED — as the emptiness test only, so a category empty now but
    not always does not claim nothing was ever reported. Do not delete it.
  - **All four `.fac-cat` chips are FH blue.** `--cat-i/c/n/s` survive for §07's
    `.hm-gc`, so §06 and §07 no longer agree on a category's colour. That is the
    instruction, not a slip.
  - Gone: the donut, the folded *Card utilisation* chart, `.card-behaviour`,
    the whole `.cb-*` family, `.donut*`, `.overlimit-flag`, `.fac-count`,
    `.fac-note`, `js.py`'s `utilisation` and `donut` keys, `report.js`'s
    `utilChart()` and `donut()`, and `facilities.card_utilisation_windows()`.
    **`utilisation_series()` stays** — §07's heatmap sub-strip reads it, and so
    does `.sub-wrap`, which §04 shares.
  - §06 went 357 / 363 → 378 / 387 on the rebuild, then **275 / 283** after
    the compression pass below.
- Prefer removing orphaned CSS over leaving dead rules.

## Status

Displayed numbers, heights at a 1560 viewport as **rail closed / rail open** —
closed is the state the page loads in. The two differ because the whole page is
now on a fluid scale. The rail-open column was byte-identical to the pre-fluid
design when the fluid pass landed (6 Aug), and was the anchor proving nothing
regressed — but the 19 Aug and 2 Sep batches changed §03's markup and swept
dead CSS since, so **treat the heights below as indicative and re-measure with
`scripts/measure/` before relying on them** (§03's especially: its header
gained the confirmation states after these numbers were captured).

| § | module | state |
|---|---|---|
| top bar | `shell.py` | brand, validity strip, AI Analysis button — **LOCKED, don't change** |
| 01 Identity & demographics | `identity.py` | done · 305 / 301 · size + **density** (4-up row) |
| 02 Score & Bureau History | `score.py` | done · 162 / 156 · size |
| 03 Income & employment | `income.py` | done · 560 / 502 open (loads collapsed) · size · heights predate the confirmation model — re-measure |
| 04 Cheque & direct-debit returns | `returns.py` | done · 357 / 344 · size |
| 05 Worst Statuses | `worst_status.py` | **36-month panel built 9 Sep** · heights not re-measured since · two panels delivered verbatim, the 36-month one derived (`worst_in_window`, always marked `derived`) |
| 06 Active Credit Facilities — overview | `facilities.py` | **rebuilt 7 Aug** · 275 / 283 · size · role split, utilisation line, no counts |
| 07 Credit facilities — detail | `detail.py` | **row signals + honesty fixes 9 Sep** (worst-ever/dispute/secured/currency chips, monthly money in tooltips, noDpd cells, open-months coverage) · heights not re-measured since · four buckets, grouped by category |
| 08 Recent Applications | `applications.py` | **rebuilt 7 Aug** · 234 / 234 · one split-axis timeline · no gain by construction |

(The modules were renamed 2 Sep 2026 — numbers stripped, `s09_enquiries` →
`applications.py`. Positions in `sections/__init__.py` still assign the
displayed numbers; a numbered filename could only drift from them.)

**Every section is on the fluid scale** — that pass is finished, and the
"not yet in the tile language" question is now closed too. **No section adopted
`.rec` / `.rec-none` / `.inc-split` beyond §03 and §04, and that was right.** A
tile is a *record*; §05 shows three delivered figures, §06 four category
aggregates and §07 a per-facility conduct grid. None of them has records to
tile. Do not reopen this as a consistency exercise.

### §01 Identity — the density step

At ≥1510px with the rail closed the six-track grid is re-mapped onto **twelve**:
row one carries four tiles instead of three (the e-mail is pulled up) and the
address takes the row beneath at full width. A span of `2k`-of-12 equals a span
of `k`-of-6 at the same gap, so the re-map only makes halves of the existing
columns addressable — it cannot move an edge it shouldn't. The narrow state
keeps its six tracks untouched.

`1510` is derived: a span-3-of-12 tile is `W/4 − 6`, the tuned three-up tile is
334px, so the fourth column only appears once it is at least as wide as the tile
the layout was tuned around. There is no second step — the density query is the
only re-map, so on the now-uncapped page extra width goes to the four tiles,
never a fifth column.

Two markers come from Python because CSS cannot ask without `:has()`:
`v-wide` (the address always takes the whole row) and `r2-N` (how many tiles row
two was built from). **Without `r2-N` the no-e-mail payload leaves row one at 9
of 12 tracks** — a hole that does not exist today; with it, row one spans 4-wide
and stays full. `auto-fit`/`minmax()` is deliberately not used: an unnameable
track count against an explicit `span 3` produces orphan holes, and `c2/c3/c6`
encode meaning ("half a row"), which `auto-fit` cannot express.

Watch the specificity. `.r2-2 > .fact.c3` is (0,6,1) and out-ranks
`.id-grid > .fact.v-wide` at (0,5,1) — that shipped once and left the address a
quarter wide with three empty tracks beside it, invisible in a font-size vector.
The fix is `:not(.v-wide)` on the narrower rule, not more specificity on the
other. The harness now asserts the address's rendered width against the grid's.

### §03 Income & employment — how it works

AECB delivers one `GrossAnnualIncome` per employment row and no series, so
`aecb/derive/income.py` decides between four chart states: `trend` (≥2 datable
figures), `single`, `spans` (dates but no usable figure), `none`. A figure is
positioned by `DateOfLastUpdate`, falling back to the hire date — those points
are drawn **hollow** and the badge flips to `derived`, because placing a salary
at the hire date asserts it was the salary at hire. Incomes below
`placeholder_floor` are shown, flagged with an amber `!`, and kept out of the
chart scale; negative figures are never plotted.

**Which employer is CURRENT is settled by the newest start date** among the
jobs the bureau has not marked finished (19 Aug 2026) — employment carries no
current/prior flag, and `DateOfLastUpdate` describes the *record*, not the
*job*, so it may qualify the claim but never decide it (otherwise any bank
re-touching a 2019 row would promote it over a 2025 job). The header follows
that employer — *Current salary* / *Current employer* — falling back to
*Latest salary* (the newest dated figure) and then *Salary on file* only when
nothing qualifies as current, and it never borrows another employer's figure.
`confirmation_window_months` in `config/income.json` (12) decides whether an
open-ended employment claim still counts as confirmed: a row whose update date
falls outside the window is **stale** and its timeline bar fades like an
undated prior employer's, because running it to the report date would assert
years nobody vouched for. A row with no update date at all is unknown, not
stale — inventing doubt is as wrong as inventing confidence. Since 2 Sep 2026
the window maths uses `dates.months_between` (day back-off; None on
unparseable input) — income's private `_months_before` was deleted, a small
intentional behaviour change.

### §04 Cheque & direct-debit returns — how it works

Built from `paymentOrder` alone. **The `summary` three-month counters are
deliberately not read** (RRM decision, Aug 2026): their window cannot describe a
list reaching back years, and whether the figure is an amount or a count is
unverified. Left half: a "Last 6 months" section holding one tile per instrument
(Bounced cheques, Unpaid direct debits) — an instrument with nothing still gets
a dashed tile, because for an adverse section that absence is a finding — then a
folded "Earlier" section with the same tile arrangement. Right half: the same
events on a timeline, marker letter = instrument, marker colour = severity tone.
The chart's height mirrors the tile block and is driven by the window count
only, so opening "Earlier" never resizes it.

`_COL_W = 706.0` in `sections/returns.py` is the width that mirroring is calibrated
to — the right half at 1560 **with the brief rail closed**, which is how the
page loads. It was `503.0` while the rail loaded open, and **it has to move
whenever that default moves**; get the new number by measuring `.inc-vis`'s
content width, not by reasoning about it. It is a design width, not a
measurement of the live column, and it cannot be anything else: the SVG is
static, so its eventual rendered width is not knowable in Python. Open the rail
and the chart scales down and stops short of the tiles. The halves still END
level — `.inc-split` stretches both cells to the row — so what shows is a short
tail on one side. Making it exact in both states means generating the chart at
runtime, which moves the drawing away from the payload decisions it is built
from. Deliberately not done.

The residual in the calibrated state is about **−14px** (chart block just under
the tile block), intrinsic because `_TILE_BASE` / `_TILE_ENTRY` / `_TILE_GAP`
approximate the CSS box model rather than reproduce it. If it grows, the tile
rules changed and those constants need re-measuring.

**`_TILE_BASE` and `_TILE_ENTRY` are the one place the fluid scale broke the
anchor, and it was unavoidable.** They are *render-time* constants baked into
the SVG's height, while the tile heights they mirror are now fluid — one static
number cannot mirror two different tile heights. Recalibrating them for the
load state therefore moved the chart in the rail-OPEN state too. It is an
improvement in both (residual −17→−14 closed, −73→−62 open) and it does not
change §04's section height in either, because `.inc-split` takes its height
from the taller tile column. Recorded rather than hidden: it is the only
documented exception to "rail open is byte-identical".

## Payload traps (all handled — don't regress them)

- Version state is a "(Historical)" SUFFIX on the type string, not a flag.
- Rows repeat per REPORTING PROVIDER — dedup by value, keep the provider set.
  `components.prov_badges()` renders the set (chip + "+N" with an "Also reported
  by" hover); §01 and §03 share it.
- Three date formats: ISO, "25 July 2016", "311023" (DDMMYY).
- Trailing spaces on enums ("Requested ", "Bounced Cheques ", "Other ").
- `ContractCategory`: letters in `contracts`, words in `contractsSummary`.
- Status arrives as text ("Active Payments"), not the letter code.
- `ClosedDate` on an ACTIVE contract is the MATURITY date, not a closure.
  Only `ActiveFlag=='Closed'` means closed.
- `contractsHistory` is SPARSE — unreported months must render grey, never
  green. Absence is not a clean payment record.
- `paymentOrder` masks the IBAN with a long asterisk run; it is collapsed to
  `…9801` on screen with the verbatim value on hover.
- Provider class **C** (e.g. `C04`, seen on returns) is not a bank or telecom
  code and is not in `config/providers.json`; it degrades to the raw code.
- **`WorstStatus24M` exists in TWO arrays, in two vocabularies.**
  `contractsTotalSummary` carries display text (`Active Payments`);
  `summary` carries the letter code (`U`). They are not interchangeable, and
  §05 reads `contractsTotalSummary` only — see the design entry above.
- **`summary.Worststatus` is an integer (`0`), not a status code**, unlike the
  `WorstStatus24M` beside it. RRM reads it as a life-time worst-status *count*
  covering non-services, which is how §05 labels and formats it. Worth
  confirming against AECB's field dictionary if one surfaces: nothing in the
  payload distinguishes a count of 0 from a status code of 0.
- **The payload contradicts itself on the current delay.**
  `contractsTotalSummary.MaxCurrentPaymentDelay` is `1`, while
  `MaxPaymentDelay24M` is `0`, every contract's `Current_DaysPaymentDelay` is
  `0`, and all 99 `contractsHistory` rows are 0 DPD. **Nothing reads it, by
  decision** — it was in the original §06 instruction and the user pulled it
  once shown the conflict, because §05 now prints the 24-month `0` two cards
  above where the `1` would sit. Do not wire it anywhere until AECB explains it.
- **`TotalExposure` counts a revolving facility's full credit LIMIT**, not its
  drawn balance: 331,420 (installment balance) + 59,600 (card *limit*) is
  exactly the 391,020 delivered, against a card balance of 33,714. §06's header
  total is therefore NOT the sum of the balances on its own cards. Verified
  arithmetic, not a guess; do not "fix" it.
- **`CreditUtilizationRate` is the CARD utilisation**, despite living on the
  total-level array: 33,714 / 59,600 = 56.57%, which is the delivered `"57"`.
  That is what makes it correct for §06 to show it inside the Credit cards card.
- **`contractsFinancialSummary` is effectively active-only.** All ten closed
  installments carry a zero balance, so the I/A balance of 331,420 is exactly
  the two active staff loans. That is what makes the "Active" in §06's title
  honest.
- **Roles in the summary arrays are `A` and `G` only** — main holder and
  guarantor, for all four categories. There are no `C` (co-holder) rows, which
  is why §06's split is two-way and not three.
- `contractsHistory.PaymentBehaviour` (values `1`/`0`, null on 61 of 99 rows)
  and `MinimumPaymentFlag` are **read by nothing**, and no config defines what
  they grade. Possible input to the 36-month window if AECB documents them.

## ⚠ The reference payload has been edited

`ReferenceJSON/aecb_payload_archive_170623.json` shipped with `paymentOrder: []`.
**Four synthetic returns were added on 6 Aug 2026 at the user's request** so §04
renders visibly when the app runs: a cheque and a direct debit inside the
6-month window (15 Aug 2023 / 30 Sep 2023) and one of each outside it (12 Sep
2021 / 5 Nov 2022). They carry this file's own subject id and archive date.
Everything else in the file follows the genuine AECB payload structure, with
the subject **fully anonymized** (confirmed 2 Sep 2026) — names, identifiers
and contact details do not belong to a real person, so the file is safe to
commit as a fixture. If a real (anonymized) adverse payload arrives, prefer it
and drop these.

Note the file's `summary` counters still read `Amount_checks_returned_3mon: 0`,
which now disagrees with the injected September return. Nothing on screen
contradicts, because §04 does not read those counters — but do not wire them
elsewhere without resolving it.

## Open items needing USER decisions

0. **§05's 36-month worst status — RESOLVED 9 Sep 2026.** The user directed it
   be built with the defaults on record: whole book including closed contracts
   and all roles; evidence = monthly history plus each contract's dated
   lifetime worst fields; status outranks DPD for naming; always marked
   `derived`; max-delay sub-line included. Still open as refinements: a
   derived 24-month reconciliation against the delivered figure (question 1)
   and flagging guarantor conduct distinctly (question 2's second half).
1. `config/bands.json` cut-offs put 732 in VLR but AECB delivers LR. Delivered
   band wins (comment in `sections/score.py` explains why) — reconcile against
   the FH scorecard.
2. `config/providers.json` is a STUB — the sections that name a reporting
   provider show its code instead: §01, §03, §04 and §07's heatmap (B08, T05,
   C04). §05, §06 and §08 carry no provider codes at all. Also: what is
   provider class C?
3. DSR and application context (product/amount/tenor) have no payload source.
3a. **`MaxCurrentPaymentDelay` needs AECB.** It says `1`; nothing else in the
   file supports it. Held off screen until that is resolved — see the payload
   trap above for the full picture and why the user pulled it from §06.
4. Severity `Reported` renders neutral pending a business definition of what it
   grades (`config/returns.json` says so in a comment).
5. ~~§08 phase pills.~~ **CLOSED 7 Aug 2026.** There was never a mapping to
   make, only a vocabulary to stop expecting: AECB delivers `Requested` and
   `Disbursed`, and they are now a hollow and a filled marker. The mockup's
   NTU / Approved / Rejected states are not in the payload and are not
   invented.
6. A REAL adverse sample payload is still wanted. The reference customer is
   entirely clean (0 DPD everywhere). Since 19 Aug 2026 the committed fixture
   `ReferenceJSON/1_SyntheticJSONPayload_Delinquent_MultiFacility.json`
   (generated by `scripts/make_synthetic_payload.py` — seeded, rollups computed
   from its own contract rows) exercises the adverse paths in the app itself:
   every heatmap band and all five DPD buckets on one page, not just harness
   cases. It is still synthetic — prefer a real (anonymized) adverse payload
   when one arrives. §05's red/amber/ungraded paths also have named cases in
   `synthetic.py`.

## How to verify (do this after every change)

```bash
.venv/bin/python scripts/check_report.py
node --check aecb/render/report.js
.venv/bin/python -c "
import ast,pathlib
for p in pathlib.Path('.').rglob('*.py'):
    if '.venv' in p.parts: continue
    ast.parse(p.read_text(), filename=str(p), feature_version=(3,9))
print('py39 ok')"
.venv/bin/python -m streamlit run app.py
```

Plus headless Chrome for geometry — measure, don't eyeball. Test at
**1572 / 1560 / 1510 / 1509 / 1400 / 1181 / 1180 / 1100 / 820 / 760**, each with
the brief rail open AND closed (toggle `body.rail-off`).

Those widths are not arbitrary and a shorter list will step straight over a
boundary: 1572 is where `--f` first reaches 1 (the page itself is uncapped
since 19 Aug 2026 — wider viewports add width, not type); 1560 is the
design viewport; **1510/1509 straddles the density step**; 1181/1180 straddles
the point where the rail stops being a grid track and the column jumps 683→1074;
820 is where the spine disappears. That is two axes, not one, and the rail axis
is the one that gets forgotten: `body.rail-off .wrap` is a two-column rule that outranks the
single-column `.wrap` inside the 820px query on specificity, so with the rail
closed it put back a spine column the spine had already vacated
(`display:none`), the report landed in that 52px column, and the whole page
squeezed to ~112px. Fixed 6 Aug 2026 by restating the rule inside the query.
Note what did NOT catch it: `scrollWidth > clientWidth` was false throughout —
the grid squeezed rather than overflowed. **Measure column widths, not just
overflow.** A 760px bug once collapsed the report to 0px in the same way.

```
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless
```

Headless Chrome here has no devtools driver, so the way to get numbers OUT of
it is `--dump-dom` plus a script appended before `</body>` that writes its
results into `document.title` between two sentinels, then grep the sentinels
out of the dumped DOM. Render the page first with `render_page(ctx)` to a file
and inject into a copy — never into the repo. The same trick reads computed
styles, which is how a colour change gets verified rather than admired: walk
every element, collect `getComputedStyle` for the properties in question, and
assert which selectors still carry the old value. Remove `.closed` from
`.sec.coll` before measuring if you want the open heights in the table above.

**Classes the reference payload never renders can still be verified** — append
a `<div>` carrying the classes, read its computed style, and you have exercised
a rule the payload cannot reach. The old examples are all gone, though: the
LLM brief rail's scaffolding (`.cite`, `.verify-link`, `.fb-*`,
`.rail-verdict`, `.bsec*`) went in the 2 Sep 2026 dead-code sweep — the rail
falls back to `.rail-empty` with no model, and that is now the only rail rule
there is — and §08's `.phase.*` / `.mk.*` pill vocabulary was deleted with the
7 Aug rewrite (the section encodes its two delivered states as a filled and a
hollow marker). The technique still applies to whatever unreachable class
comes next.

**The geometry harness is committed at `scripts/measure/` — use it, do not
rebuild one.** It used to live in a session scratchpad and be rewritten from
prose every handover, which was 843 lines of rework each time. Its own
[README](scripts/measure/README.md) carries the workflow, the flags and the
list of things that have already gone wrong in it; that file is the single
source of truth for all of it, so do not restate it here and let the two drift.

    .venv/bin/python scripts/measure/harness.py before   # AECB_ROOT=<backup>
    .venv/bin/python scripts/measure/harness.py after
    .venv/bin/python scripts/measure/compare.py before after s1,s2
    .venv/bin/python scripts/measure/synthetic.py
    .venv/bin/python scripts/measure/shots.py s1 s2

Two standing obligations, so it does not decay: **add to `watch.py`** when a
section gains a class family, or the comparator silently stops watching what
you changed; and **add a case to `synthetic.py`** whenever you touch a path the
reference customer does not exercise. Older synthetic sets worth re-adding as
cases when those sections are next touched: income (trend / single / spans /
none / empty) and returns (window / four / quiet / single / mixed / odd /
empty).

**Commit before touching shared CSS.** The tree has been a git repository
since 19 Aug 2026, so a bad edit to a 900-line stylesheet is one checkout away
from gone — but the harness's before-capture still needs a **second tree**,
not a stash: `harness.py before` must execute the pre-change code via
`AECB_ROOT`, and Python caches the first `aecb` package it imports. Put the
baseline in a `git worktree`; the harness README carries the commands.

## Where things live

```
aecb/loader.py        strip strings, canonicalise categories
aecb/dates.py         the three date formats
aecb/context.py       ReportContext: arrays + report date + 5 configs
aecb/derive/          identity · scoring · facilities · income · returns ·
                      applications
aecb/render/page.py   render_page(ctx) -> one standalone HTML string
    css.py  shell.py  components.py  svgtime.py  tokens.py  js.py
    sections/         identity · score · income · returns · worst_status ·
                      facilities · detail · applications (numbered by position)
config/               providers · status_codes · bands · income · returns
scripts/              check_report · make_synthetic_payload · fetch_fonts ·
                      build_wheels (writes requirements.lock) ·
                      install_offline · measure/
docs/BRD.docx         business requirements, written in RRM's voice
sonar-project.properties    Sonar scan exclusions
assets/fonts/OFL.txt        font licence and attribution
```

## Recently landed

Nothing in flight.

**2 September 2026 — the documentation-drift audit fix batch.** An external
audit read all four documents against the code; the findings were fixed, code
first, documents after. What landed:

- **Uploads are session-scoped again.** The 19 Aug upload flow archived
  uploaded bureau files into `ReferenceJSON/`; it was reworked so **nothing is
  written to disk** — `context.from_bytes()` (no longer dead code) renders an
  upload only in the session that supplied it, no other session can see or
  list it, and the picker offers only the committed anonymized fixtures. This
  is deliberately the seam the future AECB API integration will plug into
  (`from_bytes()` renders a payload wherever the bytes came from); the picker
  and uploader stay until that exists. Render failures now log server-side and
  the browser gets a generic error, not a traceback; the download filename is
  sanitized.
- **The 36-month window is enforced at derivation.**
  `facilities.history_by_contract()` drops rows at/after month 36, so
  `months_reported` / `max_dpd` honour the window instead of counting whatever
  the payload carried.
- **Unknown statuses are ungraded, everywhere.** `ctx.status()` returns code
  `?` / rank `None` for anything the config cannot rank — no more invented
  first-letter codes (`Closed` → `C` collided with Settlement's glyph) — and
  the heatmap paints a new `.su` tone (dashed ring), never green.
  `scoring.fh_band()` likewise returns a neutral tone for an unknown band
  code. `Facility.final_status` returns None when the closing month has no
  history row — the lifetime `WorstStatus` is no longer a stand-in — and the
  heatmap chip says *Final · not reported*.
- **Deleted at the user's decision:** `facilities.worst_in_window()` (git
  history preserves it; its two rules are restated under *Next task*) and the
  uncalled `Facility.worst_status` property.
- **`_load_config()` raises on a missing config file** instead of silently
  loading `{}`. `dates.months_between` returns None for unparseable input (0
  is reserved for a real sub-month span); `scoring.history_months` and
  `identity.age_at` follow, and income's private `_months_before` went — the
  confirmation window now uses `dates.months_between` with its day back-off, a
  small intentional behaviour change.
- **Type guards:** `DaysPaymentDelay` is coerced to int at derivation;
  `Applications90D`, application amounts and installment counts are
  type-guarded; negative incomes are not plotted. The application timeline
  emits `split: 0` when everything sits inside 90 days, so no compressed zone
  is drawn with nothing in it.
- **Escaping:** the page `<title>` and favicon are escaped; DPD and other
  numerics are escaped in `report.js`; the currency is escaped consistently in
  the income section.
- **Dead-code sweep:** `report.js` lost `genU()`, `utilCurrent`, the
  contact/dash checks and `citations()`; `report.css` lost the rail
  scaffolding (`.rail-verdict`, `.validator`, `.bsec*`, `.cite`, `.probe`,
  `.fb*`), `.sec.flash`, `.timeline`, `.fact.w2`, `.fact .v .age`,
  `.histflag.exp`, `.ustrip-tag` and the `.empty` family (`.fac.empty` now
  carries its own dashed treatment); the duplicate `.fact .v .mono` rules were
  merged. `window.__AECB.tokens` now ships exactly three tokens (`red`,
  `green-mid`, `ink`). `components.mono()` / `stat()`,
  `branding.favicon_bytes` / `clear_cache` and `measure/watch.allowed` went
  too. New `components.delivered_mark(info)` and
  `components.dispute_tag(disputed)` replace eight inline `delivered` chips
  and a duplicated `_dispute()`.
- **Section modules renamed** — numbers stripped: `sections/identity.py`,
  `score.py`, `income.py`, `returns.py`, `worst_status.py`, `facilities.py`,
  `detail.py`, `applications.py` (was `s02..s09`; `s09_enquiries` →
  `applications.py`). Displayed numbers stay positional in
  `sections/__init__.py`; a numbered filename could only drift from the
  position the registry assigns it — which is exactly what had happened to
  the documentation.
- **Config:** `providers.json` lost the unused `onus_code` key (`kind:"onus"`
  remains the mechanism); `bands.json`'s `fh_bands` no longer carry `to`
  (a zone's end derives from the next band's `from` — the `_comment` says so)
  and its `_validity_comment` points at the top bar rather than "section 01".
- **Measure harness:** `synthetic.py`'s guarantor-roles assertion was
  misindented and ran once instead of per card — fixed, it now runs per card
  via `_assert_frames`; `compare.py`'s main was decomposed; `io.open` →
  `open`; Chrome subprocess calls now check return codes.
  `make_synthetic_payload.py`'s output path is `__file__`-derived and its
  module-level body is wrapped in `main()`.
- **Scan-readiness files:** `sonar-project.properties` (Sonar exclusions),
  `assets/fonts/OFL.txt` (font licence and attribution), and
  `build_wheels.sh` now writes a `requirements.lock` manifest of the wheel
  bundle on each build.
- **Documentation governance:** all four Markdown documents are enrolled in
  the keep-current rule — see README's *Keeping the documentation current*.
- The user confirmed `ReferenceJSON/aecb_payload_archive_170623.json` is
  **fully anonymized** — genuine AECB structure, no real person's data.

**19 August 2026 — the income confirmation model, and the page cap came off.**

- `config/income.json` gained `confirmation_window_months: 12`.
  `derive/income.py` now resolves which employer is CURRENT by the newest
  start date among jobs not marked finished — `DateOfLastUpdate` may qualify
  that claim (a row last touched outside the window is *stale*, and its
  timeline bar fades like an undated prior employer's) but never decide it.
  Records gained `confirmed` / `stale` / `contradictory` (ends-before-starts
  rows are excluded from the chart outright, both dates left visible). The
  §03 header follows the current employer — *Current salary* / *Current
  employer* — falling back to *Latest salary* and *Salary on file*, and never
  borrows another employer's figure. See the §03 design entry above.
- `.wrap`'s 1572px max-width became `:root{--page-max:none}` with auto
  margins: on anything wider than the old cap (a 16" MacBook is 1728 CSS px)
  the whole surplus stacked on the right while the full-bleed top bar spanned
  the window. The fluid formulas dropped their `min(100vw,1572px)`; `--f`
  still clamps at 1, so past 1572 the page gains width but no further type.
  Re-cap `--page-max` and the formulas need the `min()` back.
- `ReferenceJSON/1_SyntheticJSONPayload_Delinquent_MultiFacility.json` was
  committed, generated by the new `scripts/make_synthetic_payload.py` — a
  seeded, severely adverse subject whose rollups are computed from its own
  contract rows, so every heatmap band and all five DPD buckets render in the
  app itself.
- The tree became a git repository (initial commit, 19 Aug).
- This batch also archived uploads into `ReferenceJSON/`; that flow was
  reworked on 2 Sep — see above.

**7 August 2026 — §08 rebuilt as "Recent Applications"** (310 / 323 → 234 / 234).
Every decision is in the design entry above. Alongside it:

- `derive/applications.py` is new and holds the split-axis maths, the window
  rule and the lane packing. `js.py` emits an `applications` key;
  `report.js`'s `enquiryTimeline()` became `applicationTimeline()` and now only
  places what it is handed.
- `synthetic.py` gained **six §08 cases**: `apps-none`, `apps-undated`,
  `apps-quiet` (nothing in 90 days — the window must still draw, because an
  empty focus window is a finding), `apps-sameday` (the lane cap),
  `apps-unknown-type` (blank glyph), `apps-conflict` (the counter disagreeing
  with the rows). Universal checks now assert every dated application reaches
  the axis and that the chart stays under 200px.
- **A bug found by screenshotting a synthetic case, not by an assertion**: with
  every application on one date the lane stack grew to fifteen and the chart to
  565px. Capped at four lanes, and the guard was verified to fail with the cap
  raised. Same lesson as §07's strips — measuring a thing against itself proves
  nothing about whether it is sane.

**7 August 2026 — §07 restructured into four buckets and compressed**
(652 / 673 → 571 / 564). Every decision and its reason is in the design entry
above. What landed alongside it:

- `js.py`'s `_heatmap()` now emits `blocks`, replacing `groups` / `services` /
  `closed` / `closedLabel`. `report.js` renders them generically — it no longer
  knows what a bucket means, only how to draw one.
- `synthetic.py` gained **three §07 cases**: `svc-arrears` (a service with an
  overdue balance stays in Active and the no-arrears fold disappears),
  `closed-undated` (every closure loses its date and all ten land in the older
  bucket with the marker), `guarantor-role` (the role chip renders, which it
  never does on the reference payload now that main holder is silent). A
  universal check asserts **all 15 facilities reach exactly one bucket** — a row
  falling out of all four would simply vanish, which is the one failure mode
  this restructure could introduce.
- The comparator caught a real regression: widening the label column pushed the
  cells past `.hm`'s min-width and `.hm-cells` overflowed at 1100 / 820 / 760
  and both 1510/1509 rail-open. Fixed, and the trap is in the harness README.
- **A second regression it did NOT catch**, found by the user looking at the
  screen: capping `.cell` with `max-height` while it still had `aspect-ratio`
  drove its width down and knocked all three conduct strips out of register.
  Fixed by dropping the ratio for explicit heights; `synthetic.py` now asserts
  the strips against each other, verified to fail with the bug reintroduced.
  Register confirmed at all 16 width × rail combinations.
  **Final run: zero violations.**

**7 August 2026 — §05 and §06 compressed.** §06 **378 / 387 → 275 / 283**, §05
**222 / 222 → 186 / 201**, on the instruction "compact as possible without
looking cluttered". Every lever and the reason for it is in the design entry
above; the short version is that the height was in gaps and leading, not in type,
and no type shrank. Re-measured across 10 widths × 2 rail states: **zero
violations** — every other section byte-identical, nothing clips or overflows,
and all 22 synthetic cases still pass. `watch.py` lost `.fac-util-scale` and
gained `.fac-block`; `synthetic.py`'s guarantor assertion follows the shortened
wording.

**7 August 2026 — §06 rebuilt as "Active Credit Facilities — Overview", and
§05 gained its delay line.** Every decision and its reason is in the design
entry above. What landed alongside the sections:

- `check_no_mock.py`'s verbatim assertion now covers **four** delivered figures
  and reads each one out of **its own element** — `.wsx-worst`, `.wsx-sub .v`,
  `.fac-util-h .v` — with the unit in the expected string. The first attempt
  searched the whole page and **silently passed a tamper test**, because the
  life-time count is `0` and `0` is everywhere. Rewritten and re-proved: three
  separate tampers (delay off by one, utilisation rounded, status upper-cased)
  each fail it now. `_values_in()` is bounded to the block on purpose — an
  unbounded regex matched a `.v` from a different section when the block had
  none.
- `synthetic.py` gained **six more cases**: `delay-24m`, `delay-absent`,
  `guarantor-live`, `overdue`, `util-over`, `util-absent`. The `.od` red path
  and the guarantor rows had **never rendered** — the reference customer is
  clean and guarantees nothing. Universal checks now assert four cards, both
  role blocks on every non-empty card, and that all four chips resolve to one
  colour. A duplicate `"reference"` key was caught while writing these; a
  shadowed EXPECT entry runs green and proves nothing, so there is a note in
  the file.
- Measured before/after across 10 widths × 2 rail states from a verified backup.
  §05 **222 / 222 unchanged** (the delay line fits inside the pending panel's
  slack), §06 **357 / 363 → 378 / 387**. Both were compressed further the same
  day — see the entry above. Every other section byte-identical.
  Only `.spine-label` flagged, from the §06 rename.

**7 August 2026 — §05 rebuilt as "Worst Statuses".** Renamed, and rebuilt from
two panels to three: `contractsTotalSummary.WorstStatus24M` verbatim, a *To be
built* 36-month panel, and `summary.Worststatus` verbatim. The design entry
above carries every decision and the reasons; what landed alongside the section
itself:

- `check_no_mock.py` gained a **verbatim assertion** that reads both figures
  back out of the `.wsx-worst` panels. Verified to actually fail by temporarily
  upper-casing the delivered status — a check that has never been seen to fail
  is not a check.
- `synthetic.py` gained **six §05 cases** — `ws-severe`, `ws-adverse`,
  `ws-unknown`, `ws-absent`, `ws-count`, `ws-count-absent` — because the
  reference customer only ever renders the green path. `ws-unknown` is the one
  that matters: it asserts an unrecognised status is left **ungraded**, not
  green. The probe reports the tone **class**, not a computed colour; a class
  states the intent directly, where an rgb only states it if you already know
  which value the green token resolves to.
- `worst_in_window()` in `derive/facilities.py` was at this point **uncalled
  and kept**, with the reason at its docstring. *(Deleted outright on 2 Sep
  2026 at the user's decision — git history preserves it.)*
- Measured before/after across 10 widths × 2 rail states from a verified backup
  tree. §05: 246 / 292 → **234 / 234**. Every other section is byte-identical in
  both rail states at every width. The comparator's only flags were
  `.spine-label`'s width, which is the rename itself — see the harness README.

Five pieces landed on 6 August 2026:

0. **The fluid scale, on ALL EIGHT sections.** See the design-language entry
   above for the mechanism and the rules for extending it. Order matters:
   §01/§02 first as a proof, then §05, §06, §07, §08 independently, then
   **§03 and §04 as one unit** — they share the `.inc-split` frame and the
   `.rec*` vocabulary and cannot be converted separately.

   Verified by a purpose-built harness against a 20-run anchor capture
   (10 widths × 2 rail states) taken from the **backup tree**, so before and
   after ran through identical probe code. Result: every section's rail-open
   height is byte-identical to the pre-fluid design (322/160/502/344/292/363/
   673/323), nothing clips or overflows anywhere, and the only anchor exception
   is §04's chart height, documented above. Four synthetic §01 payloads
   (no e-mail, long address, long e-mail, both) fill every row with no clipping.

   That harness is now **committed at `scripts/measure/`** (7 Aug 2026) — it
   used to live in a session scratchpad and be rebuilt from prose each time,
   which was 843 lines of rework per handover. Do not rebuild an equivalent;
   use it, and extend it. See `scripts/measure/README.md`.

Earlier the same day:

1. The teal → Finance House blue token pass: `report.css`, `report.js`,
   `js.py` and `tokens.py`, with the four `--teal*` tokens deleted outright so
   the old palette cannot come back by accident. No geometry moved.
2. The §03/§04 charts now fill their half instead of stopping at 560px, and the
   `body.rail-off` × 820px page-squeeze found while measuring it is fixed.
3. §02's gauge cap removed, closing the 396px hole between the band chips and
   the history block.
4. The brief rail loads closed, and `_COL_W` was recalibrated 503→706 to follow
   it.

Measured after all four, at 1560/1400/1180/1100/900/760 × rail closed and open:
no horizontal overflow anywhere, no squeezed column anywhere, §02's gap is the
strip's own 26px in every combination, and side by side the chart width equals
its column width exactly in every combination. The rail toggle was exercised
from the new default — loads closed, button opens, × closes, button reopens.

## Next task — §05's 36-month worst status — DONE 9 Sep 2026

**Built at the user's direction with reasonable RRM defaults** in
`derive/facilities.worst_in_window()` + `sections/worst_status._derived_36m()`:
whole book (closed contracts and all roles included), monthly history plus the
dated contract lifetime worst fields, severe status outranking raw DPD for
naming, unrankable statuses blocking a clean grade, coverage in the `derived`
chip's hover — which renders always. The six questions below are kept for the
record; 1 (a derived 24M reconciliation) and the role-flagging half of 2
remain open as refinements.

1. **Symmetry versus the bureau's own figure.** Derive both windows from
   `contractsHistory` so 24 and 36 are like-for-like, and keep AECB's delivered
   `WorstStatus24M` as a visible cross-check? Today's 24-month panel is AECB's
   number and any 36-month panel is ours, so a difference between them is
   ambiguous: a real month-25-to-36 event, or just our aggregation differing
   from theirs. Recommended: derive both, keep the delivered one as a
   reconciliation, never drop it silently.
2. **Scope.** The deleted `worst_in_window()` (2 Sep 2026, in git history)
   walked *every* contract — including **closed** ones and ones where the
   customer is only **Guarantor** or **Co-holder** (`Role` is on each
   contract). A 90 DPD on a guaranteed facility is a materially different
   fact. Whole book, main-holder only, or whole book with the role flagged?
3. **Coverage.** `contractsHistory` is sparse. In the reference payload:
   **69 facility-months across 13 contracts** inside 24 months, **95 across 15**
   inside 36, report date 2023-10-26 (`score.DataPullDate`). A clean window over
   69 months is a much stronger claim than one over four. State it as raw
   facility-months, as "N of 15 facilities / M of 24 months", or as a
   completeness ratio against how long each facility was open (computable — the
   open/close dates are there)?
4. **Precedence.** Worst status and max DPD are tracked independently and can
   point at different contracts in different months. Should the bureau's
   **status** always lead, with DPD supporting, or does a DPD bucket lead
   whenever there is any delay (today's behaviour)?
5. **Which aggregates.** Derivable per window, so computable identically at 24
   and 36: count of delinquent months (one slip vs chronic lateness — arguably
   the most valuable single addition); how many facilities went past due;
   months since the worst event / since the last delinquency; the DPD bucket
   distribution; max overdue amount. Delivered but on **fixed windows we cannot
   change**, and read by nothing today: `summary.Count_Def_6m_30_Total`,
   `Count_Def_12m_60_Total`, `No_Delin_Currnt_Total`, `Overdueamount`,
   `AccountOverLimit`, `Unauthorised_OD_Amt`. Their 6m/12m windows do not match
   24/36, so they need their own labelled strip rather than folding into a panel.
6. **What "repayments" means.** AECB gives monthly conduct snapshots, not
   repayment transactions, so "all repayments in 24 months" resolves to "all
   reported months". `PaymentBehaviour` may be the actual repayment signal —
   see the payload-traps entry — but nothing defines what it grades.

One more input worth knowing: each contract carries a **life-time** `WorstStatus`
with a `WorstStatusDate`, and a `MaxDaysPaymentDelay` with its own date. Because
they are dated, a contract's life-time worst can be tested for falling *inside*
24m or 36m even where monthly history does not cover that month — a real way to
beat the sparse coverage. Caveat: in the reference payload `WorstStatusDate` is
populated on all 15 contracts but `MaxDaysPaymentDelay` is **null** on all 15.

## Then — nothing is queued

Every section is designed, wired and measured. What remains is not layout work:

1. **§05's 36-month worst status** — built 9 Sep 2026 (see *Next task*, now
   marked done). Remaining refinements only: the derived 24M reconciliation
   and distinct guarantor flagging.
2. **`config/providers.json` is still a stub** (open item 2) and is now the most
   visible unfinished tell: §01, §03, §04, §07's heatmap and §08's timeline all
   show a provider CODE where a name should be. §08 made this more prominent,
   not less — the codes are the story on that chart, since four different
   lenders in ninety days is exactly what an underwriter reads.
3. **A real adverse sample payload** (open item 6). The reference customer is
   entirely clean; the committed synthetic delinquent fixture now renders the
   adverse paths in the app itself, but a real (anonymized) adverse report is
   still the better test.
4. *(closed 18 Aug 2026)* The `.phantom-callout` / `.pc-*` orphans have been
   deleted from `report.css`.
