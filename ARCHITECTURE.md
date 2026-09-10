# FH AECB Analyser — Architecture & Design

*Medium-detail technical companion to [OVERVIEW.md](OVERVIEW.md). Covers the
components, the data flow, the design rules and why they are what they are.
Code-level rationale lives in the module docstrings; this document is the map.*

---

## 1. Shape of the system

A **pure function from payload to document**:

```
render_page(ReportContext) -> str          # one standalone HTML document
```

There is no database, no server-side state, no session, no cache beyond file
reads, and no mutation of the input. Streamlit is a thin host around that
function: choose a payload, display the string, offer it as a download. An
uploaded payload renders through the same function, session-scoped — nothing
is written to disk, no other session can see it. That seam is now **realised**
(9 Sep 2026): `app_api.py` — the production entry — asks for a CB subject id,
POSTs it to the internal bureau-report API (`aecb/api.py`, endpoint in
`config/api.json`), validates the response exactly as the uploader does, and
renders it through the same `context.from_bytes()` path. Each successful API
response is also archived verbatim (10 Sep 2026, `aecb/archive.py`) as a
timestamped reference copy in `ReferenceJSON/api_responses/` — gitignored,
outside the picker's view. `app.py` remains the development harness with the
fixture picker and uploader, unchanged.

Two hard constraints drive nearly every design decision:

| Constraint | Consequence |
|---|---|
| **Air-gapped server** | Zero external references in the output. Fonts base64-inlined, logo base64-inlined, no CDN, no URL of any kind. `check_report.py` and `install_offline.sh` both assert this. |
| **Python 3.9** | `streamlit==1.50.0` is the last release supporting 3.9 (and excludes 3.9.7 exactly). No walrus-in-comprehension tricks, no `match`, no `dict |` merge. `from __future__ import annotations` is used throughout so annotations are strings. |

A third, softer constraint shapes the front end: the downloaded HTML may be
opened years later on an unknown machine, so the CSS floor is roughly Chrome 88
— **no container queries and no `:has()`** (both Chrome 105).

---

## 2. Repository map

```
app_api.py                 PRODUCTION entry — CB subject id → bureau-report
                           API → validate → render; archives each response
                           to ReferenceJSON/api_responses/ (gitignored)
app.py                     dev harness — fixture picker + uploader; renders
                           session-scoped, nothing written to disk
requirements.txt           streamlit==1.50.0, pinned with reasoning
requirements.lock          wheel-bundle manifest, written by build_wheels.sh

aecb/                      the renderer package
├── api.py                 bureau-report API client (http.client; NTLM
│                          handshake on one connection; config/api.json)
├── ntlm.py                NTLMv2 messages + crypto (MS-NLMP, stdlib only,
│                          spec-vector self-test: python3 -m aecb.ntlm)
├── archive.py             saves each successful API response verbatim to
│                          ReferenceJSON/api_responses/ (app_api.py only)
├── loader.py              parse + normalise the payload
├── dates.py               the three date formats, and date arithmetic
├── context.py             ReportContext — the object every section receives
├── derive/                payload interpretation (no HTML here)
│   ├── identity.py        provider-repeat dedup, historical splitting
│   ├── scoring.py         score bands, gauge geometry, vintage, validity
│   ├── income.py          employment + salary → what can be charted
│   ├── returns.py         paymentOrder → Return records + review window
│   ├── facilities.py      contracts × contractsHistory join (the big one)
│   └── applications.py    split-axis positioning for the 90-day window
└── render/                HTML generation (no payload logic here)
    ├── page.py            document template + render_page()
    ├── css.py             fonts + tokens + report.css, cached
    ├── tokens.py          THE colour/type schema — single source of truth
    ├── branding.py        logo/favicon as base64 data URIs
    ├── components.py      shared HTML primitives (section card, tags, esc)
    ├── shell.py           top bar, spine nav, brief rail
    ├── svgtime.py         shared linear time axis for §03 and §04
    ├── js.py              builds window.__AECB, emits the script block
    ├── report.js          client behaviour + the two JS-drawn charts
    ├── report.css         refers only to var(--*), hard-codes no colour
    └── sections/          identity … applications — one module per section
                           + registry (displayed numbers come from position)

config/                    policy and vocabularies (JSON, heavily commented)
├── status_codes.json      AECB status codes/ranks, roles, frequencies, DPD buckets
├── bands.json             score scale, FH bands, AECB ranges, vintage, validity
├── providers.json         provider code → name/kind   (STUB)
├── income.json            currency, placeholder floor, confirmation window
├── returns.json           instrument types, severity tones, review window
└── api.json               bureau-report API endpoint + timeout (app_api.py
                           only; not loaded by ReportContext)

assets/fonts/              vendored woff2 + fonts_inline.css (~930 KB base64)
                           + OFL.txt (font licence and attribution)
resources/                 optional logo (any name; auto-discovered)
ReferenceJSON/             committed anonymized fixtures the sidebar offers
                           (incl. a synthetic delinquent payload);
                           api_responses/ under it holds gitignored live-API
                           captures — real data, invisible to the picker
scripts/
├── check_report.py        the correctness gate
├── make_synthetic_payload.py  seeded generator of the delinquent fixture
├── fetch_fonts.py         one-off, needs internet
├── build_wheels.sh        offline bundle builder (connected machine);
│                          writes requirements.lock
├── install_offline.sh     server installer (--no-index)
└── measure/               headless-Chrome geometry harness (dev only)

sonar-project.properties   Sonar scan configuration (exclusions)
README.md                  architecture + per-section design rules
HANDOFF.md                 state of play, open decisions, next task
OVERVIEW.md                the product, non-technically
```

**Layering rule:** `derive/` never emits HTML; `render/` never re-interprets the
payload. Where a decision is *about the payload* it belongs in `derive/`, even
when its output is drawing coordinates — see §8.3.

---

## 3. The data pipeline

### 3.1 Load and normalise — `loader.py`

The payload is a dict of seventeen top-level arrays. `normalise()`:

- **Strips every string recursively**, mapping empty strings to `None`. The
  payload carries trailing spaces on enum values (`"Requested "`, `"E-mail "`,
  `"Mobile Number "`), which silently break equality checks.
- **Canonicalises `ContractCategory`.** It is a single letter (`I`/`C`/`N`/`S`)
  in `contracts` and `contractsFinancialSummary`, but a phrase (`"Installments"`,
  `"Credit Cards"`) in `contractsSummary`. Joining the two needs one form; the
  letters win.
- **Guarantees every array in `ARRAYS` exists**, so no caller guards on
  `KeyError`. An absent section becomes `[]` — which is what the bureau means.
- **Surfaces unknown arrays** under `_unknownArrays` rather than dropping them,
  so a new AECB section is visible rather than silently ignored.

Canonical categories: `I` instalments, `C` credit cards, `N` non-instalments,
`S` services.

### 3.2 Dates — `dates.py`

The payload mixes three formats, all of which appear in rendered fields:

| Format | Example | Where |
|---|---|---|
| ISO 8601 | `2023-10-26T14:39:13.057` | `score.DataPullDate`, `contractsHistory.ReferenceDate` |
| Long text | `25 July 2016` | `contracts.OpenDate`, `ClosedDate`, `WorstStatusDate` |
| DDMMYY | `311023` | `contracts.ReferenceDate` |

`parse_any()` handles all three (plus junk and `None`) and returns a `date` or
`None`. **Nothing in the renderer calls `strptime` directly.** Two-digit years
are read as `20xx` deliberately: reading `99` as 2099 fails louder than reading
it as 1999.

Also here: `months_between` (counts boundaries crossed, then backs off one if
the day-of-month hasn't come round; returns `None` when either input cannot be
parsed — `0` is reserved for a real sub-month span), `days_between`,
`add_months` (clamps to month-end), and the three display formatters.

### 3.3 The context object — `context.py`

`ReportContext` is the single argument every section renderer receives. Adding a
data source therefore never changes nine function signatures.

It carries:

- **the normalised arrays**, via `ctx.rows(name)` and convenience properties for
  the single-row arrays (`summary`, `customer`, `score`, `totals`);
- **the five config files**, loaded once at construction — a missing config
  file **raises** rather than loading `{}`, because a silently empty config
  renders a wrong page instead of failing;
- **`ctx.report_date`** — the anchor for the whole page;
- **`ctx.subject_id`**;
- **`ctx.unknown_arrays`** — top-level arrays the loader did not recognise,
  surfaced by `loader.normalise()` rather than dropped; `app.py` lists them in
  a sidebar warning so a new AECB section is visible;
- two resolvers that absorb payload vocabulary drift:
  - **`ctx.provider(code)`** → `{name, kind, code}`. Unknown codes fall back to
    the raw code, inferring `kind` from the prefix (`T##` telecom, else bank), so
    a missing registry entry degrades rather than blanking a row.
  - **`ctx.status(value)`** → `{code, label, rank}`, accepting **either** the
    letter code or the display text. The payload delivers `"Active Payments"`;
    the heatmap works in `"U"`. A reverse label→code map is built at
    construction. An unrecognised or missing status comes back as code `?`
    with rank `None` — never an invented letter (deriving one from the text
    collided with real codes: `Closed` → `C`, Settlement's glyph) and never
    the clean rank — and the renderer paints it as a distinct *unknown* tone.

#### `report_date` — the most load-bearing derived value

```python
sectionStatus BC row 'Last EnquiryDate'   # bounced-cheque product first
-> ConsumerScoreOnly row's date           # then the score-only enquiry
-> score.DataPullDate                     # last resort, never first
-> None                                   # nothing delivered
```

**One ladder, everywhere** (user decision, 10 Sep 2026 — supersedes both the
8 Sep "`DataPullDate` only" rule and the 9 Sep split that reserved the ladder
for the validity strip). The ladder lives on `ReportContext.enquiry_anchor()`
(`context.py`); `scoring.enquiry_anchor()` delegates to it, so the validity
verdict, the windows, and the `__AECB` blob's `reportDate` all age the same
date. The bar still states the **enquiry scope** (full file / score-only /
not reported) plus, on hover, which field dated the report. The former
`ArchiveDate` fallbacks stay removed. When the whole ladder is empty the top
bar shows *Validity unknown* and every windowed section falls back to its own
no-report-date state (unanchored returns window, offset heatmap month labels,
no application timeline).

Accepted consequence, decided explicitly: on stale archive payloads the
enquiry date can post-date the contract data (reference fixture: enquiry
2024-08-20 vs pull 2023-10-26), shifting every window forward — on live API
pulls the two dates are effectively the same. `check_report.py` gates the
blob's `reportDate` against an independently recomputed ladder.

Everything windowed hangs off it: the 36-month conduct grid, the 90-day
application window, the 6-month returns window and closure window, report
validity, and the right-hand edge of both SVG timelines.

### 3.4 Interpretation — `derive/`

`derive/__init__.py` states the contract: *nothing here invents a value; every
function returns something delivered, something arithmetically derived from
delivered values, or `None` — and `None` means "not reported", which the
renderer must show as such rather than as a zero.*

#### `identity.py` — collapsing provider repeats

Two payload behaviours drive the whole module:

1. **Version state is a suffix, not a flag** — `Passport` vs
   `Passport(Historical)`, `MASHREQBANK(Historical)`. `is_historical()` /
   `base_type()` split it.
2. **Rows repeat once per reporting provider, not once per fact.** The reference
   payload carries the same Emirates ID twelve times and the same passport five.

`dedupe()` collapses rows by value into `Entry` objects that remember the
provider set, the latest `DateOfLastUpdate`, and extra fields (e.g. passport
`ExpiryDate`), returning `(current, historical)` newest-first. A value appearing
both current and historical is treated as **current** — a later provider
re-confirming it outranks an older supersede.

**No delivered value is dropped** (decision, 8 Sep 2026): the newest-updated
current value is the tile headline, and *everything* else — historical values
and any surplus current ones — folds behind the chevron, flagged `Historical`
or `Also current`. The chevron says "N prior" only when the fold is entirely
historical, "N more" otherwise. Applies to Emirates ID, passport and e-mail;
`check_report.py` asserts every delivered identification value and every
mobile/e-mail contact is on the page. `Phone Number` contacts still have no
tile (open item).

Addresses carry neither a type nor a historical marker, so "current" there is
decided by latest update date, and the section says so on screen. A row is
empty only when `Address`, `Emirate`, `PoBox` **and** `PlotNo` are all null
(decision, 8 Sep 2026): an address-less row with an emirate renders as
*"Address not provided — Emirate"*. Addressed rows dedup on
`(Address, Emirate)` wherever they repeat; emirate-only rows collapse only
when **consecutive** in payload order with the same emirate — a re-appearance
after any other entry may be a move back, and stays separate. Extras
(emirate, PO box, plot) merge first-non-null-wins, and PO box / plot render
whenever delivered.

`arabic_name()` suppresses the Arabic name when it arrived encoding-corrupted
(the reference payload delivers `??? ???? ...`): rendering that is worse than
rendering nothing. When `FullNameAR` is absent or corrupted it falls back to
composing `FirstnameAR + LastnameAR`, under the same corruption guard.
`english_name()` mirrors that on the Latin side — `FullNameEN`, else
`FirstName + LastName` — and `customerInfo.Title` renders verbatim ahead of
the name whenever it is delivered (8 Sep 2026).

#### `facilities.py` — the contracts × history join

The core of §07 and §06, and the module with the highest correctness stakes.

- **`Facility`** wraps one `contracts` row plus a `{months_ago: history_row}`
  map built by `history_by_contract()` (indexed relative to `report_date`,
  index 0 = report month). Rows at or beyond month 36 are dropped **here**, so
  everything downstream — `months_reported`, `max_dpd` — honours the window by
  construction rather than counting whatever the payload carried.
- **`series()` yields `None` for unreported months.** `contractsHistory` is
  sparse — one contract has all 36 months, most have between one and eight. A
  month with no row means *the bureau reported nothing*, which is **not** the
  same as reporting zero days past due. This distinction propagates all the way
  to a grey cell in the heatmap.
- **Closure is `ActiveFlag`'s business alone**, never inferred from a populated
  `ClosedDate`. On an active instalment, `ClosedDate` is the *scheduled
  maturity* — the reference payload has Active contracts with `ClosedDate`
  25 Oct 2024 and 25 Aug 2027.
- `open_months` clamps to the window so pre-open cells render as pre-open rather
  than as missing data; `closed_at_month` places the closure on the grid.
- `final_status` is the status in the closing month — and **`None` when that
  month carries no history row** (which includes every closure outside the
  36-month window). The lifetime `WorstStatus` is not an acceptable stand-in:
  presenting a years-old arrangement as the status a loan closed on mislabels
  a cured contract, so the heatmap chip says *Final · not reported* instead.
- `financial_summary(ctx, role)` / `count_summary(ctx, role)` key
  `contractsFinancialSummary` / `contractsSummary` by category for one role
  (`A` main holder, `G` guarantor) — §06's data source.

`worst_in_window()` — deleted 2 Sep 2026 while the window was an open business
decision, **reinstated 9 Sep 2026** with the RRM defaults: every contract
counts (closed ones and every role included), evidence is the in-window
`contractsHistory` rows **plus each contract's dated lifetime worst fields**
(`WorstStatus`/`WorstStatusDate`, `MaxDaysPaymentDelay` and its date), and the
two original rules survive — a clean book must not attribute a "worst" to
whichever contract iterated first, and a severe *status* outranks a raw DPD
number when naming what happened. A status the config cannot rank is counted
separately and keeps the window from grading clean. §05's 36-month panel is
its caller, always marked `derived`.

#### `scoring.py` — bands, gauge, vintage, validity

**The delivered band is authoritative.** The bureau sends the score
(`DataIndex`), its own band letter (`DataRange`) and the FH band code
(`FHScoreBand`). This module looks up labels and positions a marker; it never
recomputes a band from the number. For the reference payload the configured
cut-offs would put 732 in `VLR` while the bureau delivers `LR` — computing it
would silently contradict the bureau. A band code the config does not know
renders with a **neutral** tone: green is the best-case colour, and an
unrecognised risk band has earned no colour.

`gauge()` returns marker position, zone widths and tick positions **all as true
proportions of the score scale**. Ticks carry their own percentage rather than
being evenly spaced: five ticks at 0/25/50/75/100 put the "730" label at 75%
while a score of 732 sat at 72%, making the marker look like it fell *below* a
boundary it was actually above.

`validity()` measures report age against **today**, not against anything in the
payload — the question is whether the report is usable *now* — and clamps the
meter position to 100% so a long-expired report pins at the end of the track.

#### `income.py` — what can honestly be drawn

AECB delivers **one `GrossAnnualIncome` per employment row, never a series**, so
what can be plotted depends entirely on which of the row's dates arrived. This
module resolves rows into `Record`s and returns one of four chart states:

| State | Condition | Rendered as |
|---|---|---|
| `trend` | ≥2 datable figures | points joined by a line |
| `single` | exactly 1 | a marker, plus a note that a trend needs two |
| `spans` | 0 datable figures, ≥1 dated employment | employment bars only, no income axis |
| `none` | nothing datable | no chart, and why in general terms |

Three payload behaviours it encodes:

- A figure is positioned by `DateOfLastUpdate`; when that is null the **hire
  date stands in**, and `point_basis` records which was used — because placing a
  salary at the hire date asserts it was *the salary at hire*. Those points are
  drawn hollow and the section says so. **The reference payload is entirely in
  this state.**
- `GrossAnnualIncome` arrives as `1` on rows a provider didn't really fill in. A
  figure between zero and the configured floor (1,200) is **kept and shown,
  flagged, but excluded from the chart scale**, where it would flatten every
  real point onto the axis. **Exactly zero is a delivered fact and is plotted.**
  A negative figure is never plotted.
- Providers repeat an employer and their **figures can disagree**. The shown
  figure is the one with the strongest claim to be current — a row not marked
  historical beats a superseded one, a dated row beats an undated one, a newer
  refresh beats an older — and every outranked figure that differs stays on
  screen in a disagreement marker on the row (8 Sep 2026; it was first-non-null
  in payload order, which could present a superseded figure as the current
  salary).
- Which employer is **current** is settled by the newest start date among rows
  the bureau has not marked finished — `DateOfLastUpdate` describes the record,
  not the job, so it *qualifies* the claim but never decides it. A row whose
  update date falls outside the configured `confirmation_window_months` is
  **stale**, and its bar fades like an undated prior employer's; a row with no
  update date at all stays unknown, not stale. The header follows the current
  employer (*Current salary* / *Current employer*), falls back to the newest
  dated figure and then to any usable one, and never borrows another
  employer's figure.
- Employment carries no current/prior flag beyond the `(Historical)` suffix, and
  `DateOfTermination` is routinely null even on prior employers — an *unknown
  extent*, not an open-ended one. Drawn as a fading bar, which asserts neither a
  leaving date nor a continuation.

The chart scale is set by the **plotted** points alone, so an undated 153,900
cannot pin a plotted 18,450 to the axis.

#### `returns.py` — cheque and DD returns

Thin by design: each `paymentOrder` row is one returned instrument — an event,
not a balance — so nothing is aggregated and any count on screen is a count of
the rows beneath it.

It **deliberately does not read** `summary`'s three-month return counters: their
window cannot describe a list reaching back years, and whether the figure is an
amount or a count is unverified (RRM decision, Aug 2026).

`Type` and `Severity` arrive as bare display text, so both resolve through
`config/returns.json`. The **review window** (6 months back from the report
date) is presentation policy, not payload: when the report date can't be
resolved, `window_start` is `None` and **no split is claimed** — an "outside the
window" heading over a window we could not anchor would be an invention.

#### `applications.py` — the split time axis

AECB delivers applications spanning years while the underwriting question is
about the last 90 days. On a linear axis, 90 days of a 990-day file is 9% of the
width, and the cluster that matters most is crushed into it.

So the axis is **split**: the last 90 days take a fixed 62% of the width;
everything older is compressed into the remaining 38%. Both zones are linear
within themselves and meet exactly at the boundary, so a marker never jumps.
When every application already falls inside the window, `split` is emitted as
0 and the focus takes the whole axis — no compressed zone is drawn with
nothing in it.
This is a deliberate distortion and **the section states it on screen** — an
axis that is not linear but looks linear is a lie, not a simplification. Ticks
are labelled in *days* inside the window and in *calendar years* outside it,
precisely to signal that the two zones are not the same scale.

`in_window()` counts **strictly** less than 90 days old. That reconciles the
rows with the delivered `contractsTotalSummary.Applications90D` exactly on the
reference payload (five, not six — one application sits on day 90 itself); an
inclusive bound made the section report a conflict with the bureau that was our
own off-by-one.

Collision handling: markers within 3% of the axis width lift to the next lane
(stacking upward, never shifting along the axis, which would put a marker at the
wrong date), capped at 4 lanes — without a cap, a payload with fifteen
applications on one day produced a 565px chart.

---

## 4. Rendering

### 4.1 Document assembly — `page.py`

```
<!DOCTYPE html>
  <style>  fonts (base64) + :root tokens + report.css  </style>
  <body class="rail-off">
    topbar          shell.topbar(ctx)
    .wrap
      spine         shell.spine(ctx)
      .report       sections.render_all(ctx)
      rail          shell.rail(ctx)
  <script>  window.__AECB = {...};  report.js  </script>
```

`<body class="rail-off">` — **the brief rail loads closed**, so the wide layout
is the default layout. Anything calibrated to a column width (notably
`sections/returns.py`'s `_COL_W`) is calibrated to *this* state.

### 4.2 The section registry — `sections/__init__.py`

`SECTIONS` is a tuple of eight modules. **Position determines both the anchor id
and the displayed number**, so adding, removing or reordering a section
renumbers the report and the spine nav together. Nothing hard-codes `03`.

> **Numbering.** Report validity moved into the top bar, so the report shows
> eight sections. The module files carry **names, not numbers** (renamed
> 2 Sep 2026 — the old `s02..s09` filenames could only drift from the position
> the registry assigns, and had). Docstrings inside the section modules use
> the *displayed* number. The mapping:
>
> | module | displayed | dev id |
> |---|---|---|
> | `identity.py` | 01 | `s1` |
> | `score.py` | 02 | `s2` |
> | `income.py` | 03 | `s3` |
> | `returns.py` | 04 | `s4` |
> | `worst_status.py` | 05 | `s5` |
> | `facilities.py` | 06 | `s6` |
> | `detail.py` | 07 | `s7` |
> | `applications.py` | 08 | `s8` |

Each module supplies `META = {"title": ...}` and `render(ctx, meta) -> str`,
passing `meta` straight through to `components.section_card()`.

### 4.3 Shared primitives — `components.py`

The section-card markup exists here and nowhere else, so eight sections cannot
drift apart. Also here: `esc()` / `attr()` (**bureau data is not trusted input
for markup purposes** — a stray `<` in a provider name must render as text),
tags, hint bubbles, provider badges, `aed()` money formatting,
`delivered_mark()` and `dispute_tag()` — one definition each of the
`delivered` provenance chip and the dispute tag, where eight sections used to
inline their own — and `empty_state()`, which deliberately takes both a
message and a detail so the caller can distinguish *nothing to report* from
*section not returned*.

### 4.4 Two charting strategies, and the rule that picks between them

| Drawn where | Used by | Why |
|---|---|---|
| **Inline SVG built in Python** | §03 income, §04 returns | Whether a timeline can be drawn *at all* depends on which dates the payload carries. That decision belongs beside the data it is made from. |
| **JS from `window.__AECB`** | §07 heatmap, §08 applications | Large repeated DOM (36 cells × 3 strips × N facilities) and interactive folds. Python still makes every payload decision — bucketing, positioning — and ships the result. |

**`report.js` contains no figures.** Wiring a chart means changing what `js.py`
puts in the blob, not the JavaScript. Where the payload has no data the key is
**omitted** and `report.js` returns early, leaving the chart empty rather than
inventing a series.

`svgtime.py` holds the shared linear axis for §03 and §04 so their two timelines
cannot drift. §08 deliberately does **not** use it — its scale is split by
design and could not share it without becoming linear again.

### 4.5 The client blob — `js.py`

`build_data(ctx)` assembles:

```
tokens        exactly the three values report.js reads (red, green-mid, ink)
reportDate    ISO
heatmap       { months, reportDate, blocks[], statusCodes, roles,
                frequency, dpdBuckets }
applications  (omitted entirely when nothing can be dated)
```

Heatmap rows carry `status` and `delays` keyed by months-ago containing **only
months the bureau actually reported**, plus an explicit `reported` list, the
month's own money in `bal`/`od` maps (for the cell tooltips), and a `noDpd`
list for months whose status arrived without a delivered `DaysPaymentDelay` —
painted not-reported, never as an implied zero. `report.js` paints every other
in-window month as *not reported* — which is why unreported months must never
be filled with defaults here. Row flags (`dispute`, `notLiable`, `secured`,
`currency`, `worstEver`, `asAt`) are omitted entirely when the payload does
not deliver them.

The four blocks are bucketed in Python because what goes in which is a *payload*
decision:

1. **Active facilities** — the book being lent against
2. **Closed · last 6 months**
3. **Closed · beyond 6 months** — including closures AECB never dated, because
   claiming a recency the payload doesn't support is the worse error; the row
   says the date was not reported
4. **Services — no arrears** — context rather than a finding

`_in_arrears()` is deliberately broad: an overdue balance, a current delay, **or**
a current status the bureau ranks below normal. Filing an in-arrears service
under "no arrears" is the failure that matters in this split.

`</script>` inside the JSON is escaped to `<\/script>` before embedding.

### 4.6 Styling — `tokens.py`, `css.py`, `report.css`

`tokens.py` is **the only place a colour is defined**. It emits a `:root` block
of custom properties; `report.css` refers to `var(--*)` and hard-codes no colour;
Python-generated SVG reads raw values via `tokens.token(name)`, which raises on
an unknown name rather than emitting an empty attribute.

Palette structure:

- **One brand colour: Finance House blue `#00426A`**, plus four derived shades.
  There is deliberately no second brand colour; another would read as a meaning
  the page isn't carrying.
- **Semantic triads** — red / amber / green each as solid + wash + hairline + on-wash ink.
- **A 7-step DPD severity ramp** for the heatmap, including distinct
  *not-reported* and *after-closure* greys.
- **A 5-hue categorical set** for contract categories — explicitly *not* brand
  and *not* risk, carrying no ordering.

Colour discipline on screen: red/amber/green mean **risk only**. Residency
status renders in brand blue, because colouring "Resident" green would imply
resident is *good*. The one sanctioned exception is the score band chip — a
score band *is* a risk grade.

`css.py` concatenates fonts + tokens + report.css and **caches**, because the
font block alone is ~930 KB and the page re-renders on every Streamlit
interaction. `page.clear_cache()` (wired to a sidebar button) drops it so CSS/JS
edits show without restarting the server.

### 4.7 Layout — two axes, not one

**Viewport width *and* whether the brief rail is open** both change the grid, and
every responsive rule has to hold in all four corners.

- `body.rail-off` is a *higher-specificity* selector than the plain `.wrap` rules
  inside media queries, so it wins inside them unless restated — which is how the
  rail-closed page once squeezed itself to ~112px below 820px.
- **The content is on a fluid scale; the page chrome is not.** `--colw` carries
  the report column width (derived, not measured), `--f` is a 0→1 progress value
  across the width the rail gives back, and sizes read
  `calc(BASE + GAIN * var(--f,0px))` so the current value stays visible as
  `BASE`. The whole block sits behind an `@supports` guard at the end of
  `report.css` and is purely additive — deleting it restores the px design.
- **The page itself is uncapped.** `.wrap`'s max-width is `:root{--page-max}`,
  set to `none` (the old 1572px cap stacked everything past it to the right on
  wide monitors). `--f` still clamps at 1 from 1572 up, so extra viewport buys
  width, not type. Re-cap `--page-max` and the `--colw` formulas need their
  `min(100vw, cap)` back.
- `--f` is **pinned to 0 on `body`**, so the rail-open state is exact by
  construction and the rail-open column is byte-identical to the pre-fluid
  design. That makes it the anchor proving nothing regressed.
- An element spends surplus width on **either size or density, never both**.
  Density lives at one breakpoint for the whole page (`min-width:1510px`, scoped
  to `body.rail-off`), and only §01 (grid 4-up) and §07 (legend 4-up) take it. A
  section whose column count is *data-driven* — four categories, 36 months,
  three worst-status windows — gets no density move by design.

### 4.8 One iframe, not nine

`app.py` renders the whole report into a single `components.html` iframe. The
sticky top bar, the spine nav and the scrollspy all need one scrolling context,
and iframes cannot share one. The injected CSS pins that iframe to exactly
`100vh`: taller, and the page ends up with two nested scroll contexts — the
outer page moving first, then the inner document — which is what made scrolling
feel like it stalled.

A render failure is logged server-side; the browser gets a generic error
rather than a traceback, which would leak paths and payload fragments to the
screen.

---

## 5. Configuration

All five files carry `_comment` blocks explaining what they are and why.

| File | Kind | Contents |
|---|---|---|
| `status_codes.json` | **Bureau-published** | 17 status codes with labels and severity ranks; roles (A/C/G) and the display-text→code map; 11 payment frequencies with long descriptions matched against the payload; 5 DPD buckets. |
| `bands.json` | **FH policy** | Score scale 300–900; four FH bands with lower cut-offs and tones (a zone's end derives from the next band's `from`); AECB `DataRange` letter → descriptive label; four vintage bands (B1–B4) over file length in months; `validity_days: 30`. |
| `providers.json` | **Registry (STUB)** | Provider code → `{name, kind}`. Names are currently the codes themselves. `kind` drives the badge: `bank` / `tel` / `onus` (set `onus` for FH's own code to mark our facilities). |
| `income.json` | **FH policy** | `currency: AED` (assumed — the payload carries none); `placeholder_floor: 1200`; `confirmation_window_months: 12` — how recently a provider must have touched an employment row for an open-ended "still employed" claim to count as confirmed rather than unrefreshed. |
| `returns.json` | **Vocabulary + policy** | `window_months: 6`; instrument type labels; severity → tone (Single→amber, Multiple→red, Reported→neutral pending a business definition). |
| `api.json` | **Deployment** | Bureau-report API `base_url` + `timeout_seconds` + the `auth` service account (IIS Windows authentication, NTLMv2 — committed as DUMMY values, replaced on the deployment server), for `app_api.py` only. The single source of the endpoint; no environment override. Not loaded by `ReportContext`; missing → the API entry fails loud on screen. |

The **rank thresholds** are the load-bearing part of `status_codes.json`:
`rank ≤ 60` severe (red), `65–95` adverse (amber), `100` normal (grey/green),
`None` unknown (the `.su` dashed tone). Both the heatmap and §05's grading
read them.

One subtlety: `ctx.status()` refuses to grade what the config cannot rank —
an unknown or missing status comes back as code `?` with rank `None`, and the
heatmap draws it in a distinct *unknown* tone (`.su`), never green and never
under an invented letter. §05 still carries its own **strict** resolver
(`_known_status()`), because that panel wants the config row itself and a
plain `None` for "unrecognised"; anything unresolved renders uncoloured — a
green tone is a reassurance the bureau never gave.

---

## 6. Section notes worth knowing

**§01 Identity** — a six-column grid with an uneven two-row split. Row two is
sized from what is actually present: with no e-mail reported, the address takes
the whole row rather than sitting at half width beside a gap. Two marker classes
(`v-wide`, `r2-N`) exist because CSS could only ask this with `:has()`, which is
above the browser floor.

**§02 Score** — one horizontal strip: score → gauge → delivered bands → history.
Both band chips carry **one** tone (taken from the FH band, which is what FH
policy acts on) because two colours against a single position would read as two
opinions.

**§03 Income** — two halves over one card: delivered records left, what can be
drawn right. The left half never depends on the right. Loads collapsed; the
header line therefore has to carry the figure, whose it is, and since when, and
is **qualified rather than asserted** — it follows the *current* employer
(newest start date among jobs not marked finished), headed "Current salary" /
"Current employer"; only when no employer qualifies does it fall back to
"Latest salary" (the newest figure the bureau dated) and then "Salary on
file", and it never borrows another employer's figure.

**§04 Returns** — window first, instrument second. In the open "Last 6 months"
section an instrument with nothing still gets a dashed tile saying so; **for an
adverse section that absence is a finding**. Inside the "Earlier" fold, absent
instruments are omitted — "none earlier" is not a finding.

The chart height mirrors the record tiles beside it via Python constants
(`_TILE_BASE`, `_TILE_ENTRY`, `_TILE_GAP`, `_COL_W`) that **mirror CSS box
models measured in the rendered page**. These must be re-measured, never
reasoned about, if `.rec-t` / `.rec-meta` / `.ret-amt` change. `compare.py`
prints them as witnesses on every run.

Also: `sectionStatus.ReportType` distinguishes *"requested, came back clean"*
(a positive finding) from *"never requested"* (a gap in the file). An empty
`paymentOrder` is not the same as an unchecked one.

**§05 Worst statuses** — three panels because FH policy differs by employer
segment (some assessed over 24 months, some over 36). The 24-month and
lifetime panels are delivered figures shown verbatim; the 36-month panel is
**derived** via `facilities.worst_in_window()` (9 Sep 2026, RRM defaults) and
carries the `derived` chip **always** — even over its not-derivable empty
state — with method and coverage in the chip's hover and the worst event named
in the figure's. Its max-delay sub-line prints `0 days` only when a zero was
reported; no delay figure at all renders *Not reported*. The 24-month panel
reads `contractsTotalSummary.WorstStatus24M` only, never `summary`'s field of
the same name — that one is in the *other* vocabulary (a letter code), so
falling back would change the kind of value shown depending on the payload.

**§06 Facilities overview** — every category renders **both** main holder and
guarantor, because they are different liabilities. A guarantor block that were
simply absent would leave an underwriter working out whether it means nil or
unexamined. A **Co-holder** block (role `C`) renders between them **only when
the bureau returns something for it** — figures or counters — since an absent
C row is the bureau not returning the split, not an ambiguity (9 Sep 2026).
Three only-when-non-zero surfaces added the same day: a red **Guaranteed
overdue** top chip (`TotalOverdueGuaranteed` — previously read only for the
zero-inference, so a non-zero value never reached the screen), and per-role
**declined / rejected / not-taken-up** lines from `contractsSummary`'s
delivered counters — the payload's only record of application outcomes. Those
counters also keep a category card alive in the emptiness test.

`TotalExposure` counts a revolving facility's **full credit limit**, not its
drawn balance — verified: 331,420 instalment balance + the 59,600 card *limit*
is exactly the delivered 391,020, where the card balance is only 33,714. The
header total is therefore not the sum of the balances beneath it, and nothing
should be "fixed" to reconcile them.

**§07 Detail heatmap** — markup is static; rows are built client-side. Three
aligned strips per facility: monthly status code, DPD, and (cards/overdrafts
only) utilisation. A coverage line states how many facility-months were
actually reported, in words: *"absence is not a clean record"* — and since
9 Sep 2026 both it and the per-row `Reported n/m` chip count **only the months
each facility was open inside the window** (`Facility.possible_months`), so a
3-month-old loan reported 3/3 reads complete rather than thin. A closed row's
*Final* chip comes from the closing month's own history row; when none was
reported it says *Final · not reported* rather than borrowing the lifetime
worst.

Row additions (9 Sep 2026, all only-when-delivered): a **Worst ever** chip
from the contract's dated lifetime fields (`WorstStatus`, `MaxDaysPaymentDelay`,
`MaxOverdueAmount`, each with its date) — rendered only when adverse or
unrankable, severity-toned, its hover stating it can predate the window;
amber chips for **Open dispute**, **Holder not liable** and a **non-AED
`OriginalCurrency`**; stats for the original `TotalAmount`, `MethodOfPayment`
and `SecurityType`; and an *as at* hover on the OS stat
(`Current_ReferenceDate` — the "current" snapshot can lag the report date).
Two honesty fixes the same day: a history month whose status arrived with a
**null `DaysPaymentDelay`** ships as a `noDpd` month and paints not-reported
rather than "current (0 DPD)" — a zero the bureau never sent; and DPD-cell
tooltips carry the month's **own** delivered `Balance`/`OverdueAmount`
(shipped as `bal`/`od` maps) instead of repeating the row's current balance
in all 36 cells.

Frequency and role chips render **only when meaningful** — frequency only when
AECB delivers one (it isn't part of the card/service schema at all, so there is
no gap to report), role only when it is *not* main holder (the exception that
changes who is liable).

**§08 Applications** — one chart. `Phase` has exactly two delivered states,
`Requested` and `Disbursed`, encoded as hollow and filled markers. No
NTU/Approved/Rejected vocabulary is invented; it is not in the payload. When
the delivered `Applications90D` counter and the rows disagree, that is surfaced
as a finding — one line, not a banner. Two exception marks (9 Sep 2026,
delivered-only): a `FlagOpenDispute` rings the marker amber, and a
non-main-holder `Role` letters the provider label (`B04 · G`, §07's A/C/G
vocabulary) — each with a legend entry that renders only when the payload has
the exception, and both states named in the hover (a delivered `False` says
*No dispute*).

---

## 7. Quality gates

### 7.1 `scripts/check_report.py` — run after every change

```bash
.venv/bin/python scripts/check_report.py
```

Renders every payload in `ReferenceJSON/` and fails on:

- a **payload value missing from the page** — customer name, title, score,
  subject id, **every** delivered identification value, **every** mobile and
  e-mail contact, **every** delivered address (address-less location rows must
  surface as *"Address not provided"*), **every** delivered employment income
  (including placeholders
  §03 keeps off the chart) and **every** returned-instrument amount.
  Suppressing a figure the bureau sent is exactly the failure this exists to
  catch, and it would otherwise be invisible: the page would simply look
  tidier;
- a **delivered figure not shown verbatim** — the 24-month worst status,
  lifetime count, max payment delay and card utilisation are read back out of
  the *specific elements* meant to carry them. A whole-page substring search
  would prove nothing (the lifetime count is `0`, and `0` appears everywhere).
  This is coupled to `.wsx-worst` / `.wsx-sub` / `.fac-util-h` **on purpose** —
  that coupling is what makes the assertion mean anything;
- any `http://` or `https://` in the output.

The font block and comments are stripped before scanning, since base64 contains
arbitrary character runs.

### 7.2 `scripts/measure/` — the geometry harness (dev only)

Not imported by `aecb/` or `app.py`. Renders the report and measures the result
in headless Chrome. **Use it for any change to `report.css` or a section's
markup.**

| file | does |
|---|---|
| `paths.py` | Root/work/Chrome discovery, render, rail variants, probe and screenshot primitives. Everything derived or overridable via `AECB_ROOT` / `AECB_WORK` / `AECB_PAYLOAD` / `AECB_CHROME`. |
| `watch.py` | Which selectors belong to which section. **Add to this when a section gains a class family**, or the comparator silently stops watching what you changed. |
| `harness.py` | Captures 10 widths × both rail states to JSON: computed styles, rendered geometry, and a page-wide sweep of every element tagged with its section. |
| `compare.py` | Asserts a change stayed inside the sections you named; everything else must be identical in both rail states. Prints the §04 mirror witnesses. |
| `synthetic.py` | Payload variants the reference customer doesn't produce — no e-mail, long address, expired passport, no vintage band, no FH band. Each case asserts the shape it meant to create. |
| `shots.py` | Per-section rail-closed vs rail-open images. Needs Pillow (deliberately *not* in `requirements.txt`, which is the air-gapped runtime bundle). |

The ten widths are chosen to straddle boundaries: 1572 (where `--f` first
reaches 1 — the page itself is uncapped, so wider viewports add width, not
type), 1560 (design viewport), 1510/1509 (density step), 1181/1180 (the rail
stops being a grid track), 820 (spine disappears).

The README in that directory carries a *"Things that have already gone wrong
here"* list — each entry cost real time once. The most instructive:
`aspect-ratio` plus a height constraint silently changed a cell's **width**, and
**no probe caught it** (heights right, nothing clipped, section measured
shorter — which is what the change was for). It took someone looking at the
screen. Hence `shots.py`.

Two traps worth restating: **never key elements by global DOM index** (a markup
change shifts every index after it — that mistake once produced 17,245 false
failures, so `compare.py` keys per section), and **never render two trees in one
process** (Python caches the first `aecb` package it imports, so the second
render silently comes from the first tree — use `AECB_ROOT` and separate
processes).

---

## 8. Deployment

```bash
# On a CONNECTED machine
bash scripts/build_wheels.sh          # cp39 / manylinux / x86_64, ~103 MB
                                      # PLAT_ARCH=aarch64 for ARM

# Copy wheels.tgz + source to the server, then
tar xzf wheels.tgz
bash scripts/install_offline.sh
.venv/bin/python -m streamlit run app_api.py \
    --server.address 0.0.0.0 --server.headless true \
    --browser.gatherUsageStats false
# app.py remains runnable the same way as the fixture/upload dev harness
```

`build_wheels.sh` uses `--only-binary=:all:` (a source archive would try to
compile on a server with no toolchain and no internet) across several manylinux
generations plus `any` for the pure-Python tree. It then **verifies before
packaging**: fails if any source archive is present, and fails if any
extension-carrying package (pyarrow, numpy, pandas, pillow, protobuf, tornado)
resolved to the wrong ABI or architecture — either would surface only as a
runtime import failure long after the install appeared to succeed. Each build
also writes `requirements.lock`, a committed manifest of the wheels in the
bundle, so a deployment is auditable without unpacking `wheels.tgz`.

`install_offline.sh` uses `--no-index` so pip can never reach PyPI, checks for
the excluded Python 3.9.7 explicitly, and finishes by **rendering a report and
asserting the output contains no external reference**.

Fonts (`scripts/fetch_fonts.py`) are a one-off on a connected machine: it fetches
Archivo, IBM Plex Sans, IBM Plex Mono and IBM Plex Sans Arabic and writes
`assets/fonts/fonts_inline.css` with every face as a base64 data URI. The woff2
files are gitignored (kept for auditing); **the generated CSS is committed**,
because the server cannot regenerate it. Without the file the page still renders
— every family in `tokens.py` carries a system fallback. `assets/fonts/OFL.txt`
carries the SIL Open Font License text and attribution for all four families.

---

## 9. Extending it

**Add a section:** create `sections/<name>.py` (a name, not a number) with
`META` and `render(ctx, meta)`, add it to `SECTIONS` in the registry at the
right position.
Numbering, the anchor id and the spine entry follow automatically. Add its class
family to `scripts/measure/watch.py`.

**Add a chart:**

- Does whether it can be drawn at all depend on which fields the payload
  carries? → inline SVG in the section module (like §03/§04), sharing
  `svgtime.axis()` if it is a linear calendar axis.
- Is it large repeated DOM or interactive? → compute everything in `js.py`, add
  a key to the blob, draw it in `report.js`. **Omit the key** when there is no
  data, and return early on the JS side.

**Add a data source:** put the interpretation in `derive/`, expose it on
`ReportContext` if more than one section needs it. Never re-interpret the
payload inside `render/`.

**Add config:** a new JSON file in `config/` loaded in `ReportContext.__init__`,
with a `_comment` block stating what it is and why it is policy rather than
payload.

**Change a colour:** `tokens.py` only.

---

## 10. Open technical items

| Item | Status |
|---|---|
| §05 36-month worst status | **Built 9 Sep 2026** (RRM defaults: whole book, closed contracts and all roles; monthly history + dated contract lifetime worst fields; status outranks DPD; always marked `derived`). Remaining refinements from the original six questions: a derived 24-month reconciliation against the delivered figure, and flagging guarantor conduct distinctly. |
| `MaxCurrentPaymentDelay` | Delivered as `1` while `MaxPaymentDelay24M` is `0`, every `Current_DaysPaymentDelay` is `0`, and all 99 `contractsHistory` rows are 0 DPD. **Held off screen** until AECB explains it. |
| `config/bands.json` cut-offs | Place 732 in `VLR`; AECB delivered `LR`. Delivered band wins. Needs reconciling against the FH scorecard. |
| `config/providers.json` | Stub — §01, §03, §04, §07's heatmap and §08's timeline show codes. |
| DSR / application context | No payload source at all; needs a separate input path. |
| Severity `Reported` | Renders neutral pending a business definition of what it grades. |
| Adverse sample payload | The reference customer is entirely clean. The committed synthetic delinquent fixture (`ReferenceJSON/1_SyntheticJSONPayload_Delinquent_MultiFacility.json`, from `scripts/make_synthetic_payload.py`) now renders the DPD ramp, worst-status colours and `FlagOpenDispute` paths in the app itself; a real (anonymized) adverse payload is still the better test. |

**Note on the reference payload:** `ReferenceJSON/aecb_payload_archive_170623.json`
shipped with `paymentOrder: []`. Four synthetic returns were added (6 Aug 2026)
so §04 renders visibly. Everything else follows the genuine AECB payload
structure with a **fully anonymized** subject — no real person's data. The
file's `summary` return counters still read `0` and disagree with the injected
data — harmless today because §04 does not read those counters, but do not
wire them elsewhere without resolving it.

---

## 11. Companion documents

| File | Holds |
|---|---|
| `PayLoadRead.md` | Field-level reference: for every screen element, the array/node it reads, the rules applied, and the colouring — the final behaviour, not the history. |
| `README.md` | Per-section design rules in full, configuration reference, payload traps, deployment. |
| `HANDOFF.md` | State of play — what is done, measured section heights, open decisions **with their reasons**, what was last worked on, what is next. |
| `OVERVIEW.md` | The product described non-technically — what it is, the workflow, what the screen shows. |
| `scripts/measure/README.md` | The measurement workflow, and the running list of traps already met. |

All four Markdown documents are treated as part of the deliverable: a change
that leaves any of them stale is treated as unfinished work, in the same way
as a change that fails `check_report.py`.
