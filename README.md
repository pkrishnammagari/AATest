# AECB Analyzer V2

Renders an archived AECB bureau payload as a single scannable underwriting
screen, to collapse time-to-decision on an individual customer report.

**Status: wired to the payload, and on a fluid scale.** All eight sections
render the real customer. Section 05's 36-month panel is **derived** (built
9 Sep 2026 to RRM defaults — see *§05 worst statuses* below): AECB delivers no
36-month worst status, so it is computed from the delivered conduct evidence
and always marked `derived`. All eight sections grow and shrink with the space
available; every section has also been through a design pass.

> **Picking this up mid-stream?** Read [HANDOFF.md](HANDOFF.md) — it carries the
> current state of play, the decisions already taken, and what was being worked
> on last. Keeping it current is a standing instruction; see
> *[Keeping the documentation current](#keeping-the-documentation-current)*.

**Every figure on screen comes from the payload.** That is enforced, not
assumed: `python3 scripts/check_report.py` fails the build if a payload value
goes missing from the page, if a delivered figure stops being shown verbatim, or
if an external reference creeps in.

**Governing rule: no fabricated value ever reaches the screen.** Where the
payload carries nothing, the element renders an explicit empty state that
distinguishes *reported as zero* from *not reported* — for a credit screen those
mean opposite things, and a blank that could be read as "clean" is a hazard.
Figures we computed are tagged `derived`; bureau figures are tagged `delivered`.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m streamlit run app_api.py   # production entry: CB subject id -> live API -> report
.venv/bin/python -m streamlit run app.py       # dev harness: fixture picker + uploader
```

`app_api.py` asks for a CB subject id, POSTs it to the bureau-report API
(endpoint in `config/api.json` — the URL from the integration Postman
collection, and the only place it lives), validates the response exactly as
the uploader does, and renders through the same pipeline. The payload lives
in session memory only. A subject-id mismatch between request and response
renders the report under a prominent warning naming both ids.

The API sits behind **IIS Windows authentication**, so requests authenticate
as a service account over **NTLMv2** — implemented in `aecb/ntlm.py` from the
MS-NLMP spec, stdlib only (no wheels added to the offline bundle), self-tested
against the official vectors (`python3 -m aecb.ntlm`). The account lives in
`config/api.json` under `auth` as **DUMMY values — replace them on the
deployment server** (`DOMAIN\\account` form; NTLM sends a challenge proof,
never the password itself). API failures are logged in full — status, every
header, untruncated body — to `aecb_api.log` beside the app (gitignored;
successful payloads are never logged). Off the bank network the entry screen
still renders; a Display click reports the API as not reachable, which is the
expected result there.

## How it fits together

The report is a **self-contained HTML document** built by Python. Streamlit's job
is deliberately narrow — pick a payload, host the document, offer it as a
download. All layout, type and interaction live in the HTML.

```
payload JSON
   │
   ├─ aecb/loader.py      strip strings, canonicalise categories, fill gaps
   ├─ aecb/dates.py       parse the three date formats the payload mixes
   ├─ aecb/context.py     ReportContext: arrays + report date + 5 configs
   └─ aecb/derive/        identity dedup · contracts×history join · score bands
                          income · returns · applications: what can be drawn
                              │
                              ▼
   aecb/render/page.py ── render_page(ctx) -> one standalone HTML string
        ├─ css.py         fonts (base64) + tokens + report.css
        ├─ shell.py       top bar, spine nav, brief rail
        ├─ sections/      identity … applications, each render(ctx) -> str
        │                 (numbered 01..08 by position — see Section numbering)
        └─ js.py          window.__AECB data blob + report.js
                              │
                              ▼
   app.py ── components.html(...)  +  "Download standalone HTML"
```

Design decisions worth knowing before changing anything:

- **One iframe, not nine.** The sticky top bar, spine nav and scrollspy need a
  single scrolling context, and iframes cannot share one.
- **The layout has two axes, not one.** Viewport width and whether the brief
  rail is open both change the grid, and every responsive rule has to hold for
  all four corners. `body.rail-off` is a *higher-specificity* selector than the
  plain `.wrap` rules inside the media queries, so it wins inside them unless
  restated — which is how the rail-closed page once squeezed itself to ~112px
  below 820px. Test both states at every breakpoint.
- **The whole page is on a fluid scale, and the page chrome is not.** All eight
  sections grow and shrink with the space available; the top bar, spine, brief
  rail and the shared card vocabulary (`.sec-title`, `.tag`, `.na`, `.hint`)
  stay fixed, because they are the frame rather than the content — scaling them
  too would zoom the page instead of filling it.
  `--colw` on `body` carries the report column width,
  *derived* rather than measured (`.wrap` is a fixed grid, so it is
  `100vw` less 498 with the rail open or 106 with it closed), and
  `--f` is a 0→1 progress value along the 1074→1466px range that the rail gives
  back, clamped — full gain arrives at a 1572px viewport and stays there.
  The page itself is no longer capped: `.wrap`'s old 1572px max-width is now
  `:root{--page-max}`, set to `none` with auto margins so the grid takes the
  whole window (on a 16" MacBook, 1728 CSS px, the capped page read as pinned
  to the left while the full-bleed top bar spanned it). Re-cap `--page-max`
  and the `--colw` formulas need their `min(100vw, cap)` back, or the type
  ramp overstates the column.
  Sizes read `calc(BASE + GAIN * var(--f,0px))`, so the current value stays
  visible as `BASE`. The whole block sits at the end of `report.css` behind an
  `@supports` guard and is purely additive: deleting it restores the px design.
  Three rules govern extending it — `--f` is **pinned to 0 on `body`** so the
  rail-open state is exact by construction; **no container queries and no
  `:has()`** (both Chrome 105, above the ~Chrome 88 floor the code already
  requires, and the downloaded file is opened years later on an unknown
  machine); and **`.rec-t` / `.rec-meta` / `.ret-amt` move Python** — they set
  §04's record-tile heights, which `sections/returns.py`'s `_TILE_BASE` /
  `_TILE_ENTRY` mirror, so those constants must be re-measured (not reasoned
  about) after any change to them. An *element* spends its surplus on either size or density,
  never both: §01's tiles get narrower at the density step, so their type gains
  nothing. Density lives at one breakpoint for the whole page,
  `min-width:1510px` scoped to `body.rail-off`, and only **§01** (grid 4-up) and
  **§07** (legend 4-up) take it. A section whose column count is *data-driven*
  gets no density move by design — four AECB categories, four counters, 36
  months, and since 7 August 2026 §05's three delivered windows.
- **The brief rail loads closed**, so the wide layout is the *default* layout.
  The underwriting screen is the deliverable and the AI reading is opt-in; with
  no model wired, an open rail would greet every user with its own "no brief
  generated" placeholder. `<body class="rail-off">` in `page.py` sets it; the
  top bar's AI Analysis button and the rail's own × toggle it. Anything
  calibrated against a column width — `sections/returns.py`'s `_COL_W` — is
  calibrated to this state and has to be re-measured if the default ever
  changes.
- **Charts never carry literals.** The heatmap and enquiry charts read
  `window.__AECB`, assembled in `js.py`, so wiring them means changing what
  Python puts in the blob, not the JavaScript. §03 and
  §04 instead build their timelines as inline SVG in the section module,
  because whether a timeline can be drawn at all depends on which dates the
  payload carries — see those sections below. Their shared time axis lives in
  `aecb/render/svgtime.py`.
- **Section numbering comes from position** in `sections/__init__.py`. Report
  validity moved into the top bar, so the report shows eight sections numbered
  `01..08`. The module files carry names, not numbers (`identity.py` …
  `applications.py`), precisely so a filename cannot drift from the position
  the registry assigns it. Never hard-code a number.
- **The top-bar validity ages the enquiry, not the pull** (9 Sep 2026):
  `sectionStatus`'s bounced-cheque `Last EnquiryDate` → the ConsumerScoreOnly
  date → `score.DataPullDate` as last resort, with an always-on scope chip
  (*Full file · incl. bounced cheques* / amber *Score-only* / amber *scope not
  reported*) and the dating field disclosed on hover. `ctx.report_date` — the
  window anchor — stays on `DataPullDate`. See `PayLoadRead.md`.
- **`tokens.py` is the only place a colour is defined.** `report.css` refers to
  `var(--*)` throughout; `js.py` passes the few tokens the SVG charts need.
- **One brand colour, and it is Finance House blue.** Every branded element
  resolves through the five `--fh-blue*` tokens, and no teal token is defined,
  so a rule cannot reach for one. Two rules govern the rest:
  red/amber/green mean RISK and nothing else, and a fact that is not a risk
  signal takes brand blue. The single exception is the contract-category accent
  set (`--cat-i/c/n/s/x`), which is categorical rather than brand or risk — five
  hues chosen to be told apart at 17px, carrying no ordering. `--cat-c` is still
  a teal, because it has to stay distinguishable from `--cat-i`, which is blue.
- **Zero external references.** No CDN, no font host, no image URLs. Enforced by
  a check in `scripts/install_offline.sh`.
- **Sections register once.** `aecb/render/sections/__init__.py` drives both the
  card order and the spine dots, so the two cannot drift.

## Configuration

The payload does not carry everything the screen shows. These fill the gaps:

| File | Supplies |
|---|---|
| `config/providers.json` | Provider code → display name and badge kind. **Stub** — the payload carries codes only (`B01`, `T05`), so provider names come entirely from here. Unknown codes fall back to the code itself. |
| `config/status_codes.json` | AECB contract status codes, labels and severity ranks; roles; payment frequencies; DPD buckets. |
| `config/bands.json` | FH score bands and gauge geometry, AECB `DataRange` letter → label, vintage bands, validity window. |
| `config/income.json` | How to read `GrossAnnualIncome`: the assumed currency (the payload carries none), the floor below which a figure is a provider placeholder rather than an income, and `confirmation_window_months` (12) — how recently a provider must have touched an employment row for "still employed there" to count as a confirmed claim rather than an unrefreshed one. |
| `config/returns.json` | `paymentOrder` vocabularies: `Type` text → instrument kind (Bounced Cheques / Unpaid Direct Debits), and `Severity` text → display tone (Single→amber, Multiple→red, Reported→neutral pending a business definition). Unknown values render neutral, never guessed into a risk colour. |

Still with no source at all, and needing an input path rather than config: **DSR**
and the **application context** (product, amount, tenor) shown in the top bar.
Both render as explicit `n/a` rather than blank.

### Known gaps — decisions still needed

| What | Why it's blocked |
|---|---|
| §05 36-month worst status — refinements | **Built 9 Sep 2026** to RRM defaults (whole book, closed contracts and all roles; monthly history + dated contract lifetime worst fields; status outranks DPD). Still open from the original six questions: whether to derive a like-for-like 24-month figure as a reconciliation against AECB's delivered one, and whether guarantor conduct should be flagged rather than merely included. |
| `MaxCurrentPaymentDelay` | The payload delivers `1` while `MaxPaymentDelay24M` is `0`, every contract's `Current_DaysPaymentDelay` is `0` and all 99 `contractsHistory` rows are 0 DPD. **Nothing on screen reads it**, by decision, until AECB explains the discrepancy — showing it would state a contradiction the file cannot resolve. |
| §02 score cut-offs | `config/bands.json` places 732 in **VLR**, but AECB delivered **LR**. The delivered band wins and the screen shows a warning. The configured cut-offs are provisional and need reconciling against the FH scorecard. |
| Provider names | `config/providers.json` is a stub, so the sections that name a reporting provider show its code instead: **§01, §03, §04, §07's heatmap and §08's timeline** (`B08`, `T05`, `C04`). §05 and §06 carry no provider codes at all. |

### §02 score — the strip's height is set by one member

`.score-strip` is `align-items:center`, so its height is its tallest child, and
that child is **`.ss-hist`** (the bureau-history block). Measured at 1560 it was
82.17 closed / 74.09 open — *exactly* the strip, i.e. zero slack — while
`.ss-score` and `.ss-gauge` sat 22–32px under it and `.ss-bands` had 13–18px
spare. Anything added to the history block grows the section one-for-one;
anything added to the band chips, up to that slack, is free. None of that is
visible in the CSS, so measure before changing §02.

That is why the **vintage bar** (a full-width `VINTAGE … B3` band across the top
of the block) is *paid for* rather than added: `months` and `Since …` fold into
the column beside the figure, where they fit inside the line the 38–46px figure
already occupies, and the `Bureau history` caption goes, its provenance tooltip
moving onto the figure. The block ends up shorter than before.

The **band chips** are filled solid with white text rather than the old pale
wash, at 15px rather than 12px. Solid is where the prominence comes from — 15px
is simply what the slack allowed. `_FILL` / `_LINE` in `score.py` map only
`red` and `amber`, with green as the fallback for the green tones.
`scoring.fh_band()` returns a **neutral** tone for a band code the config does
not know, and the chip renders uncoloured — green is the best-case colour, and
an unrecognised risk band has earned no colour.

### §01 identity — the density step

The identity tiles are the one place the fluid scale buys a **column** rather
than size. At ≥1510px with the brief rail closed, the six-track grid is re-mapped
onto **twelve**: row one carries four tiles instead of three (the e-mail is
pulled up from row two) and the address takes the row beneath at full width.

A span of `2k`-of-12 is exactly a span of `k`-of-6 at the same gap, so the re-map
only makes halves of the existing columns addressable — it cannot move an edge it
should not. The narrow state keeps its six tracks untouched. `1510` is derived,
not chosen: a span-3-of-12 tile is `W/4 − 6` and the tuned three-up tile is 334px,
so the fourth column appears only once it is at least as wide as the tile the
layout was already tuned around. There is no second step — the density query is
the only re-map, so on the now-uncapped page a wider viewport buys the four
tiles width, never a fifth column.

Two markers come from Python, because CSS cannot ask these questions without
`:has()` (Chrome 105, above the floor this page targets):

- **`v-wide`** on the address tile — it always carries the longest value, so it
  always takes the whole row.
- **`r2-N`** on the grid — how many tiles row two was built from. Without it, a
  payload with no e-mail leaves row one at 9 of 12 tracks: a hole that does not
  exist today. With it, that payload spans row one 4-wide and stays full.

`auto-fit`/`minmax()` is deliberately not used: an unnameable track count against
an explicit `span 3` produces orphan holes at some widths, and `c2`/`c3`/`c6`
encode *meaning* ("half a row"), which `auto-fit` cannot express.

**Watch the specificity.** `.r2-2 > .fact.c3` is (0,6,1) and out-ranks
`.id-grid > .fact.v-wide` at (0,5,1). That shipped once and left the address a
quarter wide with three empty tracks beside it — invisible in a font-size vector,
obvious in a screenshot. The fix is `:not(.v-wide)` on the narrower rule, never
more specificity on the other.

**The passport expiry lives on the value line**, inside `.v`, not as a `.v-sub`
block after it. `.facts` stretches every tile to the tallest in its row, so the
passport's third line put dead space in all of its neighbours. It needs about
240px of tile width; in **rail-open between 1181 and ~1370px** the tile is only
179–232px and it wraps to a second right-aligned line. That is accepted rather
than fixed — forcing it back to a block at those widths would reinstate exactly
the layout this change removed, and every tile is cramped at that size anyway.

### §03 income & employment — what gets drawn, and why

The card is two halves: **what the bureau delivered**, verbatim, on the left;
**what can be drawn from it** on the right. The left half never depends on the
right, so when nothing is drawable the records still stand on their own. The
header follows the **current employer** — settled by the newest start date
among the jobs the bureau has not marked finished, because employment carries
no current/prior flag and the start dates are the only evidence of which job is
the live one. It is headed *Current salary* (or *Current employer*, when that
row carries no usable figure); only when no employer qualifies as current does
it fall back to *Latest salary* — the newest figure the bureau dated — and then
to *Salary on file*, when nothing establishes which is newest. It never borrows
a different employer's figure to fill the slot.

AECB delivers one `GrossAnnualIncome` per employment row and **no series**, so
what §03 can draw depends entirely on which of that row's dates arrived.
`derive/income.py` decides between four states and the section renders the
decision; it never fills a gap to reach a nicer one.

| state | when | drawn |
|---|---|---|
| `trend` | ≥2 datable figures | employment spans, income points, line |
| `single` | exactly 1 | spans and one marker, plus why there is no trend |
| `spans` | no datable figure | employment bars only, no income axis |
| `none` | nothing datable | no chart, and why in general terms |

Three rules make it honest rather than merely tolerant:

- **A figure is dated by `DateOfLastUpdate`.** When that is null the hire date
  stands in, the point is drawn **hollow**, and the section is badged `derived` —
  putting a salary at the hire date claims it was the salary *at hire*, which is
  our inference, not the bureau's. The reference payload is entirely in this
  state: `DateOfLastUpdate` is null on all five rows.
- **A prior employer with no `DateOfTermination` has an unknown extent**, so its
  bar fades out rather than stopping at an invented date or running to the edge.
  A **stale** row fades the same way: when `DateOfLastUpdate` arrived but falls
  outside `confirmation_window_months` (`config/income.json`), running the bar
  to the report date would assert years nobody vouched for. Absence of an
  update date is *not* this case — unknown is not unconfirmed, and inventing
  doubt is as wrong as inventing confidence.
- **`GrossAnnualIncome` of 1 is a placeholder**, not an income. It is shown,
  flagged, and kept out of the chart scale — where a sentinel flattens every
  real point onto the axis. Exactly zero is *not* a placeholder: a reported zero
  is a delivered fact.

**No sentence on the screen counts this payload's null fields.** Every statement
has to hold for any payload that lands in the same state — a note reading "null
on 3 of 5 rows" describes one file rather than the section, and turns an
underwriting screen into a defect report. The reasons given are structural
("a trend needs two figures the bureau has dated"), and the per-record facts
carry the specifics.

The reference payload disagrees with itself — **18,450** (ADCB) against
**153,900** (Mashreq, historical), and AECB carries no monthly-or-annual marker
to reconcile them with. Every delivered figure is shown side by side rather than
reconciled, and `check_report.py` asserts each one reaches the page,
placeholders included.

The chart is built as **inline SVG in Python** rather than by `report.js`:
whether it can be drawn at all is a question about the payload's dates, and
that decision belongs next to the data it is made from rather than split
across two languages.

### §04 returns — built from the returns themselves

`paymentOrder` rows are events (one returned instrument each), reaching back
years. The `summary` block's three-month counters are **deliberately not
read** — their window cannot describe the list, and whether their figure is an
amount or a count is unverified (RRM decision, Aug 2026). Every count on the
card is a count of the rows on it.

Same two-half grammar as §03, **window first, instrument second**: a *"Last 6
months"* section holding one tile per instrument (Bounced cheques, Unpaid
direct debits), then a folded *"Earlier"* section with the same tile
arrangement inside. In the open section an instrument with nothing still gets
a dashed tile saying so — for an adverse section that absence is a finding;
inside the fold only instruments with records appear. Entries carry amount,
date and severity tag, then a meta line of only what was delivered — reason
keeps an explicit "not reported", the secondary identifiers (beneficiary,
masked IBAN collapsed to its digits, instrument number) simply drop out when
absent. An *"Other instruments"* tile appears only when the payload delivers a
`Type` outside the two known kinds, with the delivered text per entry. The
right half plots the same events on a shared-axis timeline, marker letter =
instrument, marker colour = severity tone from `config/returns.json`; a return
without a `ReturnDate` is listed but never plotted. The whole-array empty
state still distinguishes *requested and clean* / *not requested* /
*unverified* via `sectionStatus.ReportType`, and the axis is shared with §03
(`aecb/render/svgtime.py`) so the two timelines cannot drift.

The **review window** (`window_months`, 6) is ours, not AECB's. On the
timeline it is a shaded band drawn only when it actually holds a return; a
quiet half-year over an adverse history is stated in words on both halves
rather than left as blank space. When the report date cannot be resolved, no
window is claimed and the section renders one flat "On file" set of tiles.

The **chart is sized to the "Last 6 months" tiles beside it**, so the two
halves of the card end level: its height mirrors the tile box model (a tile
base, a gap, and one entry per return in the window), and the constants in
`sections/returns.py` name the `.rec` / `.rec-item` / `.rec-list` rules they
track.

Those tile rules are now **fluid**, so `_TILE_BASE` and `_TILE_ENTRY` are the
rail-closed measurements (39 and 62; they were 37 and 57 before the fluid
scale). Re-measure them rather than reasoning about them: render, then read
`.rec`'s rendered height and `.rec-item`'s at 1560 with the rail closed —
`_TILE_ENTRY` is `.rec-item`'s height plus its 7px `margin-top`, `_TILE_BASE`
is `.rec`'s height minus one entry. Nothing enforces this. Because they are
render-time constants mirroring a height that is now fluid, one value cannot
serve both rail states; they are calibrated to the load state, which leaves the
chart marginally better in both (residual −17→−14 closed, −73→−62 open).

`_COL_W` is the width that conversion is calibrated to — the right half at 1560
with the brief rail **closed**, the state the page loads in. It is a design
width rather than a measurement, and cannot be otherwise: the SVG is static, so
what width it will be rendered at is not knowable in Python. It therefore has to
be re-measured whenever the load-state layout changes; it moved from 503 to 706
when the rail was made closed-on-load. Opening the rail narrows the half back to
~503px, and the chart then scales down and stops short of the tile block. The
halves still *end* level, because `.inc-split` stretches both cells to the row —
what shows is a short tail on one side. The alternative is generating the chart
at runtime, which would move the drawing out of Python and away from the payload
decisions it is built from.

Only the window count feeds it — opening the "Earlier" fold lengthens the
record column and leaves the chart exactly as it was. Each return in the window
takes its own stem lane, spread evenly over the height and centred; lanes are
necessary as well as tidy, since the window is a narrow slice of an axis that
can span years and four returns inside it would otherwise draw on top of one
another. Returns outside the window pack into the bottom lane. Stems stay
hairlines however tall they grow: a heavier line would read as a bar, as though
height encoded the amount, and it does not — the amount is the text beside the
marker.

The reference payload's `paymentOrder` shipped **empty**; it now carries four
injected returns (see *[The reference payload has been
edited](#the-reference-payload-has-been-edited)*), so the populated states are
exercised by the reference file itself rather than only by synthetic variants —
the window, earlier-fold, both-instrument and outside-window paths all render.
The quiet and whole-array-empty states are still synthetic-only, and the first
real adverse payload should be reviewed against this section. Provider class `C`
(seen on the injected returns) is not named in `config/providers.json` and falls
back to its code.

### §05 worst statuses — three windows, two of them delivered

FH policy differs by employer segment: some segments are assessed over 24 months
and some over 36. The card carries both windows side by side so an underwriter
applies the right one rather than reading a single figure that answers half the
book. A third panel carries the life-time count.

| panel | source | state |
|---|---|---|
| Worst status · last 24 months | `contractsTotalSummary.WorstStatus24M` | delivered, shown **verbatim** |
| ↳ Max payment delay · 24m | `contractsTotalSummary.MaxPaymentDelay24M` | delivered, shown **verbatim** |
| Worst status · last 36 months | `contractsHistory` + each contract's dated `WorstStatus`/`MaxDaysPaymentDelay` | **derived** (9 Sep 2026, RRM defaults) |
| ↳ Max payment delay · 36m | same evidence | **derived** |
| Life-time worst status count · non-services | `summary.Worststatus` | delivered, shown **verbatim** |

The delay sits **under the status it qualifies**, not in a fourth panel. A worst
status is a grade and carries no magnitude — *Active Payments* says the customer
is not delinquent, never how late they have ever been — so the two belong
together. A delivered `0` is a fact (never late in the window) and prints as
`0 days`; only a missing field is an absence. It cost §05 nothing in height —
the pending panel is the tallest member and sets the row on its own, which is
also why compressing the other two panels does nothing until that one comes
down. §05 is 186 / 201.

**Verbatim is the requirement, not a shortcut** (RRM, Aug 2026). The delivered
text is printed as it arrived — no relabelling, no rounding, no translating
display text into a letter code. `check_report.py` reads the figures back out
of the `.wsx-worst` panels and fails the build if either stops matching its
payload field; a plain substring search could not do that, because the life-time
count is `0` and `0` appears all over the page.

The **only** thing the module derives is the colour, and it grades nothing it
cannot recognise. `ReportContext.status()` refuses to grade the unknown too:
anything it cannot match comes back as code `?` with rank `None`, and the
heatmap paints it in a distinct *unknown* tone (`.su`, a dashed ring) — never
green, and never under an invented letter (deriving a code from the first
letter of the text used to collide with real codes: `Closed` → `C`, which is
Settlement's glyph). `_known_status()` still resolves strictly on code or on
label and returns `None` otherwise, because this panel wants the config row
itself rather than a resolver result; an unrecognised status renders uncoloured
with a *Partly reported* header pill. The life-time figure is
a count, so a non-zero one is amber rather than red — a count says how many,
never how deep, and the depth is §07's job.

The 36-month panel is **derived and always marked so** (RRM instruction, 9 Sep
2026 — the chip renders even over the not-derivable empty state, because
nothing in that panel is ever a bureau figure). The derivation is
`derive/facilities.worst_in_window()`, reinstated from git with the RRM
defaults: **every contract counts** — closed ones and every role included — and
evidence is the monthly `contractsHistory` rows in the window **plus each
contract's dated lifetime worst fields** (`WorstStatus`/`WorstStatusDate`,
`MaxDaysPaymentDelay`/`MaxDaysPaymentDelayDate`) whenever their date falls
inside it, which lets a closure the monthly rows never covered still grade the
window. The two hard-won rules from the original implementation survive: a
clean book must not attribute a "worst" to whichever contract iterated first,
and a severe status outranks a raw DPD number when naming what happened. A
status the config cannot rank makes the window **unknown, never clean**; the
`derived` chip's hover carries the method and the coverage figures; the
figure's own hover names the worst event (facility, provider, month, closed or
not). Its max-delay sub-line prints `0 days` only when a zero was actually
reported somewhere in the window — with no delay figure delivered at all it
says *Not reported*.

`.wsx` is `repeat(3,1fr)` and takes **no density step**: three windows is the
data, exactly as `.fac-grid`'s four categories are. The panels stretch to the
tallest of the row, and the figure carries `margin:auto 0` to sit centred in
the space rather than floating above a void.

Coverage note: in the reference payload `contractsHistory` gives **69
facility-months across 13 contracts** inside 24 months and **95 across 15**
inside 36, against a report date of 2023-10-26 — every row `Active Payments`
at 0 DPD, so the derived panel reads clean there and adverse on the synthetic
fixture (Write-off · 214 days, matching the delivered 24M anchor). The
section's adverse paths are also exercised by `scripts/measure/synthetic.py`
(`ws-severe`, `ws-adverse`, `ws-unknown`, `ws-absent`, `ws-count`,
`ws-count-absent`).

### §06 active credit facilities — split by role

Four cards, one per AECB category, each split into **Main holder** and
**Guarantor**. That split is the section's reason to exist: they are different
liabilities and FH lends against them differently, so a guarantor block that
were simply absent would leave an underwriter inferring the guarantor position
from silence. It always renders, and says which of three things is true.

Three only-when-non-zero surfaces (9 Sep 2026): a red **Guaranteed overdue**
top chip from `TotalOverdueGuaranteed` (a non-zero one is the guarantee being
called; it previously never reached the screen); per-role **declined /
rejected / not-taken-up** lines from `contractsSummary`'s delivered counters —
the payload's only record of an application outcome — which also keep a card
alive in the emptiness test; and a **Co-holder** block (role `C`) that renders
between the other two only when the bureau returns figures or counters for it.
An absent C row is the bureau not returning the split, so no permanent
"Not reported" third block is shown — the guarantor rationale does not
transfer.

| category | headline | rows |
|---|---|---|
| I Installments | Balance | Payment amount · Overdue |
| C Credit cards | Balance | Credit limit · Overdue |
| N Non-installments | Balance | Credit limit · Overdue |
| S Services | Balance | Overdue |

`contractsFinancialSummary` carries exactly four figures per category × role, so
those are all there is to choose from. Balance is the headline in every card
because it is the one figure common to all four, which gives the row of cards a
single scan line. N is limit-bearing credit and carries no `PaymentAmount`; S
carries neither a limit nor a scheduled instalment, because a telecom account
has no credit line to fill.

**The guarantor block picks between three statements**, and the first two are
backed by delivered figures:

1. The category's `G` row carries a non-zero figure → the same rows as the main
   holder.
2. Nothing in the `G` row, and `TotalBalanceGuaranteed` **and**
   `TotalOverdueGuaranteed` are both `0` → *No exposure reported*, tagged
   `delivered`. The inference runs one way only: a book-wide guaranteed total
   of zero means every category's is zero.
3. Nothing in the `G` row but the totals are non-zero or absent → *Not
   reported*, untagged. A non-zero book total cannot be attributed to one
   category, so no delivered claim is made.

Both role labels sit **on** the figure line rather than above it, in a
`.fac-block` flex row: the label is that figure's caption, so a line of its own
said the same thing twice and cost one per block. The row wraps at narrow
widths, which puts the figure back underneath — the old layout, reached only
when it is actually needed.

**The utilisation line replaced the donut**, and sits above the role split
rather than inside main holder's rows, because `CreditUtilizationRate` is
delivered once for the category and carries no role dimension. It reads like a
book-wide ratio from where it lives in `contractsTotalSummary`, and is not:
33,714 balance over a 59,600 limit is 56.57%, which is the delivered `"57"`.
Below 100 the bar fills green in proportion; at or above 100 it fills red
completely, so the figure beside the label is the only thing separating 101%
from 300%. It is modelled on the top bar's `.tv-meter`, **not** on `.ss-gauge`,
which is a zoned scale with a marker rather than a fill; `.tv-meter` itself is
untouched because the top bar is locked.

The bar carries **no `0`/`100%` scale**. One was added and then removed in the
compression pass, so the reasoning is worth recording: it was justified as "a
bar with no reference point cannot be read", but the percentage is printed
beside the label, and a track filled just over halfway next to the figure *57%*
already establishes that its full width is 100%. The scale restated what the
figure said, and cost a 13px row on the tallest card in the section.

**`TotalExposure` counts a revolving facility's full credit LIMIT, not its drawn
balance.** 331,420 installment balance plus the 59,600 card *limit* is exactly
the 391,020 delivered, where the card balance is only 33,714. The header total
is therefore not the sum of the balances on the cards beneath it, and nothing
here should be "fixed" to reconcile them.

Deliberately **not** shown: bureau counts, anywhere. `contractsSummary`'s
`TotalNo` spans more history than the delivered contract rows, so putting it
beside §07's per-facility list invites a comparison that cannot be made. It is
still *read* — as the emptiness test, so a category that is empty now but was
not always does not claim nothing was ever reported — just never displayed.

All four `.fac-cat` chips are Finance House blue. The categorical
`--cat-i/c/n/s` set survives for §07's heatmap group headers, so **§06 and §07
no longer agree on a category's colour**. That is the instruction, not a slip.

**Where §06's height went** (378 → 275 in the compression pass, a 27% cut). The
card was 292px and only 101 of those were figures. The rest was structure, and
the two biggest items were not obvious: **60px of `.fac` row-gap** across seven
children, and **two role headings at 23.5px each** where a 9px caption needs
nine. The gap is now 5px because `.fac-role`'s own top padding and hairline were
already doing that job — a 19px trough before every role heading is what made a
card of seven short lines read as tall. Nothing shrank below its legible size:
row text is still 11.5px and the balance is still 19px.

### §07 credit facilities — four buckets, not one list

Every facility lands in exactly one of four blocks, and which one is a payload
decision — closure dates and arrears — so it is made in `js.py` and arrives
already bucketed. `report.js` only draws what it is handed.

| block | holds | state |
|---|---|---|
| Active facilities | everything AECB flags Active, **except** quiet services | open |
| Closed · last 6 months | `ClosedDate` inside the window | folded |
| Closed · beyond 6 months | everything else closed | folded |
| Services — no arrears | active services carrying nothing adverse | folded |

Inside each block the facilities are grouped by AECB category (I / C / N / S).
There are two levels of heading and they must stay visually distinct: the
**block** is the bucket and carries the fold, the **group** is the category. If
they read alike, four buckets look like eight categories in a row.

**An active service with nothing on it is context, not a finding**, which is why
the active block is not simply "everything not closed". *Arrears* is deliberately
broad — an overdue balance, a current delay, **or** a current contract status the
bureau ranks below normal. Filing a service that is in arrears under *no arrears*
is the failure that matters in this split, so every signal counts and not just
the money one.

**A closure AECB did not date** cannot be placed in a window. It joins the older
bucket, because claiming a recency the payload does not support is the worse of
the two errors, and the row says *Closed · date not reported* rather than leaving
the blank where a date would be — which reads as "closed, but not recently".

An empty category is **omitted**, and an empty block with it. §06 is where a
category's absence is a finding; repeating it here would cost up to sixteen
headings across four blocks to say nothing.

Two chips were dropped from every row, and both are judgement calls worth
knowing about. **Frequency** now shows only when AECB delivers one: the old
*Frequency n/a* appeared on every card and service row, and it was not reporting
a missing value — frequency is not part of those schemas at all, so there is no
gap to surface. **Role** shows only when it is *not* main holder: that is the
default across the book, and a co-holder or guarantor is the exception that
changes who is liable, which marking every row "Main holder" buried.

The header tag reads **`5 Active · 10 Closed`** — AECB's own words. `ActiveFlag`
delivers `Active` and `Closed`; "open" was ours and appears nowhere in the
payload.

**Row signals added 9 Sep 2026, every one only-when-delivered.** A severity-
toned **Worst ever** chip from the contract's dated lifetime fields
(`WorstStatus`/`MaxDaysPaymentDelay`/`MaxOverdueAmount` with their dates),
rendered only when adverse or unrankable — its hover says it can predate the
36-month window, which is exactly why it exists. Amber chips for **Open
dispute** (`FlagOpenDispute`), **Holder not liable** and a **non-AED
`OriginalCurrency`** (the page otherwise renders everything as AED). Stats for
the original **`TotalAmount`** (paydown context beside OS), **`MethodOfPayment`**
(salary-transfer conduct is largely involuntary) and **`SecurityType`**. The OS
stat hovers its **as-at date** (`Current_ReferenceDate` — the "current"
snapshot can lag the report date). Three honesty fixes travelled with them: a
month whose status arrived with a null `DaysPaymentDelay` paints **not
reported, never "0 DPD"** (the `noDpd` list in the blob); DPD-cell tooltips
carry that **month's own** delivered balance/overdue (`bal`/`od` maps) instead
of repeating the current balance in all 36 cells; and coverage — the section
line and the per-row `Reported n/m` chip — counts **only months the facility
was open** (`possible_months`), so a fully-reported short loan is complete,
not thin. Deliberately still unread: `PaymentBehaviour` (undocumented coding)
and the sparse card-activity fields (`AmountSpent`, `CardUsedFlag`,
`MinimumPaymentFlag`, `BilledAmount`), which feed the AI brief instead.

**Where §07's height went** (652 → 571). The rows were driven by the *label*
column, not the heatmap: at 250px the stat line wrapped to three rows while the
36 cells beside it needed only 51px. Widening the label to 320px and dropping
the two dead chips put every stat line back on one row. The DPD band is also
explicitly 20px now rather than square — see below.

**Three strips, one column grid, and that is the constraint.** A row stacks a
status strip, a DPD strip and (for cards) a utilisation strip: three separate
`repeat(36,1fr)` grids, one above the other. The only thing keeping their
columns in register is **every cell filling its own track**, so all three share
`grid-template-columns`, `gap` and `min-width`, and each has an explicit height.

`.cell` used to be `aspect-ratio:1/1`, which filled the track by accident. Giving
it a `max-height` during the compression pass broke that: the ratio drove the
*width* down to match the capped height — 23px inside a 27.55px track — and every
DPD block sat inset inside a column the strips above and below still filled.
**Do not reintroduce `aspect-ratio` here.** A square cell and a shared column
cannot both hold at an arbitrary width, and the shared column is the one that
matters: a month has to line up with itself across all three strips. The band is
`calc(20px + 4 * var(--f,0px))`, which also bounds a growth the ratio never did
(it reached 29.5px).

**`.hm`'s `min-width` is tied to the label width.** The three strips share a
`min-width:16px` per cell, so the 36 cells need `36*16 + 35*2 = 646px` before
they overflow. `.hm`'s floor is `320 + 24 + 646` rounded up to 1000. Move the
label column and this must move with it; change one cell's `min-width` and the
other two must follow, or the strips stop overflowing together at narrow widths
and the register breaks exactly where nobody looks.

### §08 recent applications — a split time axis

One chart, and nothing else. The four counter tiles it used to lead with
(5 / 6 / 4 / 15) answered a question nobody was asking, while the thing an
underwriter actually needs — *when* the customer went looking, and how the
recent weeks compare to the years behind them — was not on the screen at all.

**Two exception marks, delivered-only** (9 Sep 2026). A `FlagOpenDispute`
rings its marker amber; a non-main-holder `Role` puts the letter beside the
provider code above the marker (`B04 · G` — §07's A/C/G vocabulary) and the
full role name in the hover. Main holder is the default and earns nothing;
each mark's legend entry renders only when the payload actually has the
exception, so a clean file's legend promises nothing the chart does not show.
The hover names the dispute state in both directions — a delivered `False`
reads *No dispute*, an absent flag says nothing.

**The axis is split.** AECB delivers applications spanning years while the
underwriting question is about the last 90 days: in the reference payload that
window is 90 of 990 days, so on a linear axis the cluster that matters most
would be crushed into 9% of the width. The last 90 days therefore take **62%**
of the axis and everything older is compressed into the rest. Both zones are
linear within themselves and meet exactly at the boundary, so a marker never
jumps. When every application already sits inside the window there is nothing
to compress: the split lands at 0% and the focus takes the whole axis, rather
than reserving a compressed zone with nothing in it.

**The distortion is drawn, not just stated** — the focus window carries a wash,
the boundary a dashed rule, and the two zones are labelled in different units
(`30d` / `60d` / `90d` against calendar years). A legend line says it in words
too. An axis that is not linear but looks linear is a lie, not a simplification.

**Positions are percentages computed in `derive/applications.py`**, not in
`report.js`: what counts as the focus window is a business fact about the
payload, not a drawing detail, so the same rule that puts §07's bucketing in
Python applies. Percentages rather than an SVG viewBox because the chart has to
scale across two rail states and ten widths — a viewBox would magnify the 8.5px
axis labels along with it. The shared axis in `render/svgtime.py` is
deliberately **not** used: §03 and §04 share it so their timelines cannot drift,
and this one is non-linear by design.

**The phase vocabulary is settled, and the block is closed.** AECB delivers two
states here — `Requested` and `Disbursed` — encoded as a **hollow** and a
**filled** marker. A not-taken-up / approved / rejected vocabulary is not in the
payload and is not invented, so there is no mapping to make. The marker letter is the AECB category the
rest of the page uses (I / C / S), matched on a keyword so a new wording still
lands somewhere sensible; an unmatched type renders a **blank** marker and says
so on hover rather than being filed under a category nobody chose.

Markers are brand blue and never a risk colour. One application is a fact; it is
the *cluster* that an underwriter reads as a signal, and the focus wash already
carries that. The header pill grades the delivered `Applications90D`.

**The 90-day window is `< 90` days, not `<= 90`.** That is what reconciles the
rows against the delivered `Applications90D` exactly — five, not six, because
one application sits on day 90 itself. The inclusive bound made the section
display a conflict with the bureau that was our own off-by-one. The mismatch
detector is still there and still fires, as a second pill, if a payload really
does disagree.

**Lane stacking is capped at four.** Applications close in time are lifted to a
lane above rather than nudged along the axis, which would put them at the wrong
date. Without a cap the section's height becomes a function of how many
applications share a day — a payload with fifteen on one date produced a 565px
chart. Beyond the cap markers overlap; the pill still counts them all.

## Offline deployment (Python 3.9, air-gapped Linux)

`streamlit==1.50.0` is pinned because it is the **last release supporting Python
3.9** — 1.51.0 and later require ≥3.10. It also excludes Python 3.9.7 exactly
(`!=3.9.7,>=3.9`); `install_offline.sh` checks for this.

On a connected machine:

```bash
bash scripts/build_wheels.sh          # cross-downloads cp39 manylinux x86_64
```

This produces `wheels/` and `wheels.tgz` (~103 MB, 36 wheels) and **fails loudly**
if any dependency resolved to a source archive or the wrong architecture — either
would only surface as a broken install on the server. Each build also writes
`requirements.lock`, a committed manifest of exactly which wheels went into the
bundle, so a deployment is auditable without unpacking the archive.

For a different architecture:

```bash
PLAT_ARCH=aarch64 bash scripts/build_wheels.sh
```

Copy `wheels.tgz` and the source tree to the server, then:

```bash
tar xzf wheels.tgz
bash scripts/install_offline.sh       # --no-index; never touches the network
.venv/bin/python -m streamlit run app_api.py --server.address 0.0.0.0 --server.headless true
```

### Fonts

`assets/fonts/fonts_inline.css` holds Archivo, IBM Plex Sans, IBM Plex Mono and
IBM Plex Sans Arabic as base64 `@font-face` rules (~930 KB), generated by
`scripts/fetch_fonts.py`. **That script needs the internet and must be re-run on
a connected machine** if the font set ever changes. Without the file the page
still renders, but in system fallback fonts. The licences travel with the
faces: `assets/fonts/OFL.txt` carries the SIL Open Font License text and
attribution for all four families.

## Payload notes

Traits of the AECB format that the loader normalises, and that will matter when
wiring sections:

- **Version state is a suffix, not a flag** — `Passport` vs
  `Passport(Historical)`, `Mobile Number` vs `Mobile Number (Historical)`.
- **Rows repeat per reporting provider**, not per fact — one passport appears
  five times. Dedup by value, keeping the provider set.
- **Three date formats**: ISO, `25 July 2016`, and `311023` (DDMMYY).
- **Trailing spaces on enum values** (`"Requested "`, `"Other "`) — stripped on
  load, since they silently break equality checks.
- **`ContractCategory` has two spellings** — single letters in `contracts`,
  full phrases in `contractsSummary`. Canonicalised to letters.
- **Status arrives as display text** (`Active Payments`), not the letter code the
  heatmap draws. `ReportContext.status()` resolves either.
- **History coverage is uneven.** In the reference payload only one contract has
  a full 36 months; the median is about five. "Not reported" must never render
  as "current".

### The reference payload has been edited

`ReferenceJSON/aecb_payload_archive_170623.json` shipped with `paymentOrder: []`.
**Four synthetic returns were added on 6 August 2026** so §04 renders visibly
when the app runs — a cheque and a direct debit inside the six-month window and
one of each outside it, carrying this file's own subject id and archive date.
Everything else in the file follows the genuine AECB payload structure, but the
subject is **fully anonymized** — names, identifiers and contact details do not
belong to a real person, so the file is safe to commit and share as the
reference fixture. Prefer a real (anonymized) adverse payload if one arrives,
and drop these. Note the file's `summary` counters still
read `Amount_checks_returned_3mon: 0`, which disagrees with the injected
September return — harmless today because §04 does not read those counters, but
do not wire them elsewhere without resolving it.

## Keeping the documentation current

Four documents describe this project, and **all four are part of the
deliverable**:

| file | holds | audience |
|---|---|---|
| `README.md` | how the thing works — architecture, config, payload traps, per-section design rules | anyone reading the code |
| `HANDOFF.md` | the state of play — what is done, what is open, what was last worked on, what comes next | an AI or engineer starting a fresh session |
| `ARCHITECTURE.md` | the technical map — components, data flow, and why the design rules are what they are | an engineer orienting in the code |
| `OVERVIEW.md` | the product, non-technically — what it is, the workflow, what the screen shows | stakeholders, and anyone before the code |

### Standing instruction for an AI working on this repo

The user switches context windows. `HANDOFF.md` is what the next session reads
to pick up, so it has to be true at the moment it is read — not true as of some
earlier week.

**Start every session by reading `README.md` then `HANDOFF.md`.** That is the
whole handover. Do not ask the user to paste either file, and do not start work
on the next task until they have given you direction on it — `HANDOFF.md`'s
*Next task* section says what is next and what is still undecided about it.
(`ARCHITECTURE.md` and `OVERVIEW.md` are reference companions — read them when
orienting, and keep them current like the other two.)

**Use `scripts/measure/` for any change to `report.css` or to a section's
markup — do not rebuild an equivalent by hand.** It is committed precisely so
that no session has to. The workflow is in
[scripts/measure/README.md](scripts/measure/README.md): commit, capture a
baseline *from a git worktree of the pre-change commit*, change, capture
again, `compare.py`, `synthetic.py`, `shots.py`. Keeping it working is part of
the job:

- **Add to `scripts/measure/watch.py`** when a section gains a class family,
  or the comparator silently stops watching the thing you changed.
- **Add a case to `scripts/measure/synthetic.py`** when you touch a path the
  reference customer does not exercise — an empty category, an adverse value,
  a missing date. Every case must assert the shape it meant to create.
- **Record any new trap** in `scripts/measure/README.md` under *Things that
  have already gone wrong here*, so the next session pays for it once.

**After completing any piece of work, before reporting back, update both files
if the work changed anything they assert.** Specifically:

- **Always update `HANDOFF.md`** when you: finish or start a section; change a
  design rule, class vocabulary or house pattern; add, remove or rename a
  module, config file or CSS family; edit `ReferenceJSON/`; discover a payload
  trap; resolve an open item, or open a new one; or receive a decision from the
  user (record the decision *and its reason* — the reason is what stops it being
  relitigated).
- **Always update `README.md`** when the change affects how the code works:
  architecture, configuration, the per-section design rules, or the known-gaps
  table.
- **Update `ARCHITECTURE.md` and `OVERVIEW.md`** when a change moves what they
  map: a module added, removed or renamed; the pipeline reshaped; a
  user-visible behaviour changed. Most changes touch neither; a rename or a
  new file always does. They drifted once precisely because they sat outside
  this rule.
- **Refresh the "Last updated" line and the "Next task" section of
  `HANDOFF.md` every time**, even when nothing else moved. "Nothing in flight"
  is a valid and useful answer.
- Keep the section table in `HANDOFF.md` honest, including measured heights —
  they are how the next session knows where the compression work stands.
- Say so in your reply when you have updated them, so the user can see the
  documentation kept pace with the code.

Treat a change that leaves any of the four documents stale as unfinished work,
in the same way that a change failing `scripts/check_report.py` is unfinished.
