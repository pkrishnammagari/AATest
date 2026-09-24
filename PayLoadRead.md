# PayLoadRead — how each screen element reads the AECB payload

*Field-level reference: for every element on the report, which array and node it
comes from, the rules applied to it, and how it is coloured. This describes the
system as built (current as of 9 September 2026), not the history of how it got
here — code-level rationale lives in the module docstrings, the architecture in
[ARCHITECTURE.md](ARCHITECTURE.md).*

The one rule above all others: **no fabricated value ever reaches the screen.**
Everything shown is delivered by AECB or arithmetically derived from delivered
values, and the screen says which (`delivered` / `derived` chips). Where the
bureau reported nothing, the screen says *not reported* — never a blank, never
a zero, never green.

---

## 0. Cross-cutting rules (read these first — every section relies on them)

**The report date** anchors every window on the page. It is the latest
parseable `sectionStatus."Last EnquiryDate"` across all rows, falling back to
`score.DataPullDate` only when no row carries one (full rules under *Top bar*
below). If neither arrives, the top bar says *Validity unknown* and every
date-windowed element degrades to its own unanchored state (no returns-window
split, offset heatmap month labels, no application timeline).

**Normalisation** (before anything is read): every string is stripped and empty
strings become null (the payload carries trailing spaces on enum values —
`"Requested "`, `"E-mail "`); `ContractCategory` is canonicalised to one
letter — **I** instalments, **C** credit cards, **N** non-instalments,
**S** services (`contractsSummary` spells them out as phrases; the letters
win); every expected array exists (absent section → empty list); an array the
renderer does not recognise triggers a sidebar warning rather than being
silently dropped.

**Dates** arrive in three formats — ISO (`2023-10-26T14:39:13`), long text
(`25 July 2016`), DDMMYY (`311023`) — all parsed by one function; two-digit
years read as 20xx.

**Status severity** comes from AECB's published table
([config/status_codes.json](config/status_codes.json)), keyed by letter code
with a display-text→code reverse map (the payload delivers `"Active Payments"`,
the code is `U`):

| rank | tone | codes |
|---|---|---|
| ≤ 60 | red (severe) | D Deceased 10 · L Left country 20 · B Bankrupt 30 · W Write-off 40 · P Court enforcement 45 · X Service disconnected 48 · F Default / S Suspended 50 · N NDDSF 60 |
| 65–95 | amber (adverse) | G Guarantor paying 65 · T Dewan settlement 70 · C Settlement 80 · A Arrangement 90 · E Extended loan 95 |
| 100 | grey/green (normal) | U Active Payments · M / O prepaid states |
| unrecognised | **unknown** — dashed tone, code `?` | never graded, never green, never an invented letter |

**Colour discipline**: red / amber / green mean *risk* and nothing else.
Neutral facts (residency, provider kind) render in brand blue or grey. The one
sanctioned exception is the score band chip — a score band *is* a risk grade.

**Provider codes** (`B01`, `T05`…) resolve through
[config/providers.json](config/providers.json) — currently a stub, so codes
show as names. Unknown codes degrade to the raw code; `T##` infers telecom.

**Money** renders as AED (an assumption — the payload carries no currency field
except per-contract `OriginalCurrency`, which §07 guards; see there).

---

## Top bar — report validity and enquiry scope

**The report date is a ladder, and it dates everything** (since 10 Sep 2026
this ladder *is* `ctx.report_date`: validity, every window, the heatmap month
arithmetic, and age/expiry checks all age the same date). `sectionStatus` is
read **generically** — no `ReportType` vocabulary is hard-coded, so any
product row (*ConsumerLong with Bounced Cheques*, *ConsumerScoreOnly*, plain
*ConsumerLong*, or one the bureau adds later) participates:

1. Every `sectionStatus` row is a candidate; the one with the **latest**
   parseable **`Last EnquiryDate`** wins (array order breaks ties — the
   parse truncates the timestamp to a date).
2. No row with a usable date → `score.DataPullDate` — a last resort only,
   never first. The first row still names the scope chips.
3. Nothing → **Validity unknown** ("no enquiry date or pull date delivered").

| element | source | rule |
|---|---|---|
| Pill | the ladder date | age = days to **today**. `Report valid` (green) when 0 ≤ age ≤ window; `Report expired` (red) when age > window; `Future-dated` (amber) when the date is after today — ungradable, so the end date stays neutral *Valid until* and the meter sits at zero; `Validity unknown` (grey) when the ladder is empty. Every state carries a hover stating its rule, with the window read from config |
| **Scope chips** | winning row's `ReportType` + `EnquiryType` (+ `EnquiryNo` in the hover) | two neutral chips carrying the values **verbatim** from the single winning row; a blank `ReportType` renders an amber **"Report type not reported"** chip, a blank `EnquiryType` simply drops its chip; amber **"Enquiry scope not reported"** when `sectionStatus` is empty. The `ReportType` hover carries "Enquiry no. *n*" and the EnquiryType when delivered (the EnquiryType chip itself hides below 1440 px; the dates below 1280 px; the meter below 1110 px — measured breakpoints, see report.css); when no row is dated, both hovers say the scope came from the first row while `DataPullDate` dated the report. Render even in the unknown state. §05 still grades the absence of the bounced-cheque product itself |
| Enquiry date (or Pull date) / Valid until | ladder date; + window (the last valid day — always labelled *Valid until*, the date red once expired) | the date field is labelled after its source — *Enquiry date*, or *Pull date* when the DataPullDate fallback dated the report — and its age reads days (< 60), then calendar months (`dates.months_between`), then years; its hover (and the meter's) **names which field dated the report** — the winning enquiry's `Last EnquiryDate`, or the DataPullDate fallback |
| Window | `validity_days` in [config/bands.json](config/bands.json) (30) | FH policy, not payload. **Required**: a missing, zero, negative or non-integer value stops the render with an error — no silent default |
| Meter | age ÷ window | two colours only: fill (days elapsed) and marker green while valid, red when not; plain grey track = days remaining; marker clamped to 0–100% so an expired report pins at the far end and a future-dated one at the start |

The logo is `resources/logo.svg` (base64-inlined; "FH" monogram fallback).
The product name "FH AECB Analyzer" comes from one constant,
`branding.APP_NAME`, for the bar, browser tab, sidebars and document title. Validity lives in the bar, not a section, because it qualifies every
section below it.

---

## §01 Identity & Demographics

**Arrays: `customerInfo` (single row), `identification`, `contacts`,
`addresses`.**

### The name line
- Headline: `customerInfo.FullNameEN`; when absent, composed from
  `FirstName + LastName` (whichever parts arrived). Em dash only when nothing
  arrived at all. When both parts and the full name arrived and the parts
  spell it differently (case/spacing ignored), an amber `!` follows the name:
  hover *Name parts reported as: …*.
- `Title` (MR/MRS…) renders verbatim ahead of the name, de-emphasised, whenever
  delivered.
- Arabic: `FullNameAR`, falling back to `FirstnameAR + LastnameAR`. Either way
  a **mojibake guard** applies: a name with no actual Arabic codepoints (the
  `??? ????…` encoding-loss shape) is never rendered as a name — instead a
  quiet grey *Arabic name unreadable in payload* takes its place, raw value in
  the hover, so an upstream encoding loss is not disguised as "none sent".
- Traits line: `Gender` verbatim · age computed from `DOB` **at the report
  date** (DOB in brackets; *age unknown — no report date*, *DOB x — unreadable
  date* or *DOB not reported* say exactly which part is missing) ·
  `Nationality` titlecased (and/of/the stay lower case) · **CB Subject ID** —
  `customerInfo.CBSubjectId`, else `sectionStatus.CBSubjectId`; never the
  warehouse `PKSubjectId`. Absent → *CB Subject ID not reported*.
- Header pill: `ResidentFlag` (booleans, or true/false · Y/N · yes/no · 1/0
  as text) → *Resident* / *Non-resident* in **brand blue**, because residency
  is a fact, not a risk grade; any other value → grey *Residency: value*;
  nothing → *Residency not reported*.
- Empty `customerInfo` empties the name line only (*No customer record*); the
  tiles below still render from their own arrays.

### Emirates ID, Passport, Mobile, E-mail — the dedupe rules
The bureau repeats each fact once per reporting provider and marks superseded
values with a `(Historical)` suffix on the type string
(`identification.InfoType`, `contacts.ContactType`). For each type:

1. Rows are grouped **by value** (`Info` / `Contact`). Document numbers
   (`Info`) group on letters and digits only — dashes, spaces and case
   ignored — displaying the most recently reported spelling, others in the
   hover (*Also reported as: …*). Each distinct value remembers every
   reporting provider with **that provider's own** latest `DateOfLastUpdate`,
   and extras (document `ExpiryDate` — the most recent reporter's).
2. Current vs historical is decided **per provider** (decision, 24 Sep
   2026): `(Historical)` marks one provider's copy of one spelling — the
   archive shows C11 re-submitting `971525881200` as `+971525881200` on the
   same day, the old spelling marked historical. Each provider's **own
   latest** report is its verdict (same-day tie → current); the value is
   **current** when at least one provider's verdict is current, historical
   only when every provider's latest report says so.
3. Values sort newest-updated first. The newest **current** value is the tile
   headline, with the **most recent reporter** as a chip and the rest behind
   `+N` (hover lists them, most recent first). Folded rows read
   *provider · Mon YYYY* — that provider's own date, never the newest date
   from some other provider (this ordering also applies to §04's employer
   provider badges).
4. **Nothing is dropped.** Every other value — historical ones *and* any
   surplus current ones — folds behind the chevron, flagged `Historical` or
   `Also current`. The chevron reads *N prior* when the fold is entirely
   historical, *N more* otherwise. If only historical values exist, the newest
   is promoted to the headline flagged *Historical only*.
5. Mobile differs in one way: **all** current numbers render in the tile (a
   person legitimately has several); only priors fold.
6. Mobile numbers also group **across prefix spellings**
   (`identity.mobile_key`): digits only, then a leading `00`, `971` and one
   `0` come off; a remaining UAE mobile (9 digits starting `5`) keys as
   `971…`, so `0525881200` / `971525881200` / `+971525881200` / `525881200`
   are one number. Anything else keys on its raw digits — never merged by
   guesswork. The most recently reported spelling shows; the others sit in
   its hover (archive: 15 spellings → 1 current + 10 prior). A number that
   is not a UAE mobile under these rules keeps its delivered form but carries
   a grey *not a valid UAE mobile* flag (archive: `97150000000`,
   `971999999999`).
7. E-mails group **ignoring letter case** and surrounding spaces
   (`identity.email_key`), most recent spelling shown, others in the hover. A
   value not shaped like an e-mail (one `@`, a dotted domain) keeps its
   delivered form with a grey *not a valid e-mail* flag. The E-mail tile is
   **always present** — *Not reported* when no e-mail arrived, rather than
   vanishing (row two is always E-mail + Address).

**Document expiry** — passport **and Emirates ID** (`identification.ExpiryDate`),
one builder for both: on the value line —
*Expires 26 May 2027*, or red *Expired …* when the expiry precedes the
**report date** (the question is whether the document was valid when the bureau
was pulled). No expiry → *Expiry not reported*. Folded passports carry
`· expired 2023` / `· expires 2030` graded the same way (neutral `expiry` when
no report date). When providers disagree on a document's expiry, the most
recent reporter's date is shown with an amber `!` naming the others.

### Addresses
- A row is empty **only when `Address`, `Emirate`, `PoBox` and `PlotNo` are
  all null**; *Not reported* renders only when no row survives.
- A row with no `Address` but a location renders as **"Address not provided —
  Emirate"** (plus PO Box / Plot when present).
- **Two dedup rules by shape**: addressed rows collapse on
  `(address, emirate)` wherever they repeat, the address compared ignoring
  case, punctuation and repeated spaces (single spaces kept, so digit runs
  never fuse); the most recent spelling displays, others in the hover. The
  same address in two emirates stays two addresses. Address-less rows
  collapse only when **consecutive in payload order** with the same emirate —
  the same emirate reappearing after any other entry stays separate (it may be
  a move away and back).
- Extras (emirate, PO Box, plot, `AddressType`, `ArabicAddress`) take the
  **most recent reporter's** non-null value, so a PO Box any provider
  delivered survives.
- The array carries no current/historical marker, so the tile is labelled
  **Latest address**: the newest `DateOfLastUpdate` is latest, shown as
  *Updated Mon YYYY* on the value line, and the rest fold as prior — the
  on-screen hint says so. Display: `ADDRESS — Emirate · PO Box N · Plot N`,
  plus `AddressType` as a small grey tag and a real-Arabic `ArabicAddress` in
  the hover, each only when delivered.

**Landlines** (`contacts` *Phone Number*): in the same tile — now labelled
**Phone** — behind their own *N landline* chevron (collapsed, zero height).
Grouped like mobiles (`identity.phone_key`: the prefix rules, accepting a UAE
landline — area code 2/3/4/6/7/9 + 7 digits — or a mobile), each flagged
*Current* / *Historical*. A Phone Number that reads as a UAE mobile stays where
the bureau filed it with a grey *mobile number* note (archive: all three do);
neither shape → *not a valid UAE number*.
`ArchiveDate` on every row is never read, anywhere.

---

## §02 Score & Bureau History

**Arrays: `score` (single row), `contractsTotalSummary`.** A **half-width
card** sharing a row with §03 Worst statuses (stacked below 1180 px): a
semicircular dial on the left, the chips and bureau history on the right.
**Colour follows the FH bands throughout** (decision, 24 Sep 2026).

| element | source | rule |
|---|---|---|
| Dial | config cut-offs + `score.DataIndex` | a 300–900 semicircle; each FH band is a zone from its `from` to the next band's `from`, coloured by its configured tone; tick values at the scale ends and each boundary; the marker at the score, capped to the ends. Geometry, not verdicts. The zones draw even with no score. Hover lists the real ranges (HR 300–619 · MR 620–678 · LR 679–729 · VLR 730–900) |
| Score figure | `score.DataIndex` | in the dial's centre, verbatim; numeric text counts. No score → *Score not reported*, plus the bureau's own reason under the dial — *Score not returned — `ErrorDescription` (error `ErrorNumber`)* — or *No score and no error reason delivered* |
| Band mismatch `!` | configured zone vs `score.FHScoreBand` | amber, on the dial's shoulder, **only** when the cut-offs put the score in a different band from the delivered one; the hover names both and says to check `bands.json`. The delivered band always wins (the archive shows it today: 732 → configured VLR, delivered LR) |
| FH band chip | `score.FHScoreBand` (fallback `FHScoreBand1`) | the **delivered band is authoritative** — the code is matched to its label/tone in `bands.json` `fh_bands` (HR red / MR amber / LR light green with dark text / VLR green — each chip matches its dial zone); it is *never* recomputed from the number. If `FHScoreBand` and `FHScoreBand1` both arrive and differ, an amber `!` names both. An unconfigured band code renders neutral — an unknown risk band has earned no colour |
| AECB band chip | `score.DataRange` (a letter, A–L) | the delivered **letter first**, then its `aecb_ranges` label (*J · Good*; provisional — the hover says so). Carries the **FH** band's tone — one score, one verdict |
| Vintage bar | bureau-history months → `vintage_bands` | B1 0–11 · B2 12–47 · B3 48–95 · B4 96+ months — configured policy, brand blue |
| Bureau history | `contractsTotalSummary.OldestContractOpenDate` → report date | whole calendar months (day-of-month aware) — **derived**; AECB delivers no file length, and the hover says so. *since Mon YYYY* = that date. Not computable → the line says why (*unknown — no report date (since …)*, *oldest contract date x is unreadable*, or *not reported*). `summary.MostOldest_InMonth_Total` stays unread (meaning unconfirmed; decision 24 Sep 2026) |

A missing score no longer blanks the card — the chips and the bureau history
still render. `score.FraudContractFlag` and `score.PaymentOrderFlag` are
deliberately unread (decision, 24 Sep 2026).

---

## §03 Worst Statuses

Three panels. FH policy assesses some employer segments over 24 months and
some over 36, so both windows sit side by side, plus the lifetime count.

**Panel 1 — Worst status · last 24 months (delivered, verbatim).**
`contractsTotalSummary.WorstStatus24M` — `summary`'s same-named field (a
letter code, other vocabulary) is never displayed, but when it names a
different status an amber `!` after the headline names both. Colour only is derived: the
text resolves strictly against the status table and grades by rank
(≤60 red / <100 amber / 100 green / unresolvable **uncoloured**). Sub-line:
`MaxPaymentDelay24M` — a delivered 0 prints "0 days" (never late — a fact);
missing prints *Not reported*; non-numeric prints as delivered, ungraded.

**Panel 2 — Worst status · last 36 months (derived — always marked so).**
AECB delivers no 36-month figure; this panel computes one from delivered
evidence (`facilities.worst_in_window`):

- **Whole book**: every contract — closed ones and every role included; a
  closure inside the window does not erase the conduct preceding it.
- **Two evidence sources**: `contractsHistory` rows inside the window, plus
  each contract's **dated lifetime worst fields** (`WorstStatus`/
  `WorstStatusDate`, `MaxDaysPaymentDelay`+date) when their date falls inside
  it — so a closure the monthly rows never covered still grades the window.
- A clean book names no facility; a **severe status outranks a raw DPD
  number** when naming what happened; a status the config cannot rank makes
  the window **unknown, never clean** (uncoloured, reason on hover).
- Headline: the worst ranked status's label, graded by rank. Sub-line: *Max
  payment delay · 36m* — "0 days" only when a zero was actually reported;
  no delay figure anywhere → *Not reported*.
- **Never milder than the delivered 24 months** (decision, 24 Sep 2026): the
  36 months include the 24, so when the calculation comes out milder than
  `WorstStatus24M` / `MaxPaymentDelay24M` (or finds no evidence), the
  **delivered** figure is shown and the calculated one sits behind an amber
  `!` on hover. Delivered wins; the calculation never overrules it.
- The `derived` chip renders **always** — even over the *Not derivable* empty
  state — with method and coverage (rows across N of K contracts) in its
  hover; the figure's hover names the worst event (facility, provider, month,
  closed or not).

**Panel 3 — Life-time worst status count · non-services (delivered,
verbatim).** `summary.Worststatus` — a *count*, not a status: 0 → green;
non-zero → **amber, never red** (a count says how many, never how deep — depth
is §07's job); non-numeric → verbatim, ungraded.

**Header pill**: red *Severe status on file* / amber *Adverse history* /
*Partly reported* when anything is absent or ungradable / green *No adverse
status on file* only when all three panels resolved clean. It grades the
delivered **statuses** only — delays are shown, not cross-checked against
them (decision, 24 Sep 2026).

---

## §04 Income & Employment

**Arrays: `employment`, `incomes`.** Left half: the records verbatim. Right
half: what can honestly be drawn. AECB delivers **one `GrossAnnualIncome` per
employment row, never a series**, so the chart draws only what the row's own
dates allow.

### Dedupe and field resolution (two stages)
Employers dedupe by name (suffix-stripped, exact match — `MASHREQBANK` and
`MASHREQ BANK PSC` stay separate; merging on similarity would be a guess).
`(Historical)` on the name is the only current/prior marker. Then each field is
re-resolved across the raw rows with its own direction:

| field | rule | why |
|---|---|---|
| `DateOfLastUpdate` | **latest** | freshness = newest time anyone vouched |
| `DateOfEmployment` | **earliest** | the job started once; later starts are providers joining mid-employment |
| `DateOfTermination` | **latest** | if one says 2022 and another 2023, it demonstrably ran to 2023 |
| `FlagOpenDispute` | OR | one provider's dispute is a dispute; all-null stays unknown |
| `GrossAnnualIncome` | strongest claim wins: current-marked row > historical, dated > undated, newer refresh > older, then payload order | outranked figures that **differ** stay on screen in a `!` disagreement marker naming them (hover) — a contested number is never presented as settled |

### The rules that shape the section
- **Current employer** = newest `DateOfEmployment` among jobs not marked
  finished (no `(Historical)` name, no termination). The update date *never*
  decides this — it only breaks a same-day tie. Exactly one row wears
  *Current*; ended/historical rows wear *Prior*; an ongoing-but-not-newest row
  wears **nothing** (neither claim is honest).
- **Header figure** follows the current employer (*Current salary* /
  *Current employer* when it has no usable figure) → falls back to the newest
  bureau-dated figure (*Latest salary*) → then any usable one (*Salary on
  file*). It never borrows another employer's figure. When that employer's
  record is disputed, the header line carries an amber *Open dispute* tag —
  the section loads folded, so the header is all a reader sees at first.
- **Chart states**: ≥2 datable figures → `trend` (line); 1 → `single`
  (marker + "a trend needs two"); 0 but dated employment → `spans` (bars only,
  with a reason line that is true of the payload that produced it); nothing →
  `none`.
- **Point placement**: a figure sits at `DateOfLastUpdate`; when null, the
  **hire date stands in** — those points draw **hollow** and flip the chart's
  chip from `delivered` to `derived` (placing a salary at hire asserts it was
  the salary *at hire*).
- **Placeholder floor** (`income.json`, AED 1,200/yr): a figure above zero but
  below it is shown, flagged *not a usable figure*, and kept off the chart
  scale. **Exactly zero is a delivered fact and is plotted** ("reported as
  zero"). Negatives are never plotted. The chart scale is set by *plotted*
  points only.
- **Confirmation window** (`income.json`, 12 months): a row whose update date
  falls outside it is **stale** — bar fades, header adds "last confirmed …".
  A row with **no** update date is *unknown, not stale* (inventing doubt is as
  wrong as inventing confidence). An update date before the job began marks it
  unconfirmed.
- **Employment bars**: ended → solid bar between dates; prior with no end →
  **fades out** (unknown extent — asserts neither a leaving date nor a
  continuation); ongoing → runs to the report date with an arrow;
  **termination before hire** → no bar at all, both dates shown with a `!`
  (a data error must not draw as a plausible short job).
- Undated/unusable figures list in a *Not on the chart* tray with the reason.
- **Other income**: every `incomes` row carrying a `Source` **or** an amount
  renders as a line (source or *Source not reported*, provider, date, amount;
  a delivered 0 reads *AED 0/yr · reported as zero*; a missing amount reads
  *Amount not reported*). check_report asserts every delivered amount.
- **Currency**: AED is **assumed** (`income.json`) — the payload carries no
  currency field; the header figure's and the chart unit label's hovers say so.
- The `delivered` chip on the employers list covers names, dates and figures;
  its hover says the *Current* / *Prior* badges and *last confirmed* notes are
  inferred from the dates.

---

## §05 Cheque & Direct-Debit Returns

**Array: `paymentOrder` — and deliberately nothing else.** Each row is one
returned instrument — an event, not a balance — so there is **no dedupe and no
aggregation**; every count on screen is a count of the rows beneath it. The
`summary` block's 3-month return counters are deliberately not read (window
mismatch; amount-vs-count unverified — RRM, Aug 2026).

| element | source | rule |
|---|---|---|
| Instrument kind | `Type` (display text) | resolved via [config/returns.json](config/returns.json): exact label match, then containment ("Bounced Cheque" still lands); unmatched → shown verbatim under *Other instruments* with a `?` marker |
| Severity tag | `Severity` | configured tones: Multiple → red, Single → amber, Reported → neutral (pending a business definition); unknown → neutral — a risk colour is a claim |
| Window split | `ReturnDate` vs report date − `window_months` (6) | *Last 6 months* open, *Earlier* folded. **No report date → no split claimed** — one flat "On file" section |
| Entry line | `Amount`, `ReturnDate`, `Reason`, `BeneficiaryName`, `IBAN` (mask runs collapsed to `…9801`, verbatim in hover), `Number`, `ProviderNo`, `FlagOpenDispute` | reason keeps an explicit *not reported* (it bears on the decision); secondary identifiers are simply absent when absent |

Asymmetry by design: inside the open window group, an instrument with nothing
still gets a dashed tile ("none in the last 6 months") — **for an adverse
section, absence is a finding**. Inside the fold, absent instruments are
omitted — "none earlier" is not one.

**Empty ≠ unchecked**: with `paymentOrder` empty, `sectionStatus.ReportType`
decides the message — contains "bounced cheque" → green *Checked · none
reported* (a positive finding; its hover names the confirming row's report
type, enquiry number and date, since any row counts — not only the top bar's
winning one); doesn't → amber *Section not requested* (a gap in the file);
`sectionStatus` absent → *Unverified*.

**`score.PaymentOrderFlag`** is read for one thing only: an amber `!` on the
pill when it **contradicts** the rows — flag true with no `paymentOrder` rows,
or false with rows. Silent when they agree or the flag is absent.

**Currency**: amounts render as AED, **assumed** — `paymentOrder` carries no
currency; the `delivered` chips' hovers and each timeline marker's hover say
so.

The timeline (Python SVG) plots each dated return as a C/D/? marker filled in
its severity tone; the amber window band draws **only when the window holds
something**; undated returns list beside the chart, never plotted. Header pill:
recent count red → "on file · none in 6m" amber → *Checked* green.

---

## §06 Active Credit Facilities — Overview

**Arrays: `contractsFinancialSummary` (figures, per category × role),
`contractsSummary` (emptiness test + outcome counters), `contractsTotalSummary`
(top chips + card utilisation), `contracts` (live-facility emptiness test).**

### Top chips (`contractsTotalSummary`)
- **Total exposure** ← `TotalExposure`. Semantics: counts a revolving
  facility's **full credit limit**, not its drawn balance (verified: 331,420
  instalment balance + 59,600 card *limit* = the delivered 391,020) — so the
  header total is not the sum of the balances beneath it, deliberately.
  The chip's hover says so (and that the currency is assumed AED); a missing
  figure reads *Total exposure not reported* rather than vanishing.
- **Newest facility** ← `NewestContractOpenDate` (an unreadable value reads
  *unreadable date x*).
- **Guaranteed** (amber) ← `TotalBalanceGuaranteed`, only when non-zero.
- **Guaranteed overdue** (red) ← `TotalOverdueGuaranteed`, only when non-zero
  — guaranteed exposure already overdue is the guarantee being called.

### The four category cards (I · C · N · S)
Each card reads its category's `contractsFinancialSummary` rows. Headline =
`Balance` (the one figure common to all four). Second row by category:
Instalments → `PaymentAmount`; Cards & Non-instalments → `CreditLimit`;
Services → overdue only. `OverdueAmount` renders red only when non-zero (a
reported 0 stays in ink). The Cards card carries the **utilisation line**:
`contractsTotalSummary.CreditUtilizationRate` verbatim (it has no role
dimension) — fill green below 100, full-red at ≥100 with the figure telling
101 from 300.

**Role blocks** — three roles in the AECB vocabulary (A / C / G):
- **Main holder** — always renders.
- **Co-holder** — renders **only when** the bureau returns figures or counters
  for role C (an absent C row is the bureau not returning the split; a
  permanent "Not reported" block would be noise).
- **Guarantor** — always renders, picking one of three statements: figures →
  same rows as main; empty row + book-wide `TotalBalanceGuaranteed` **and**
  `TotalOverdueGuaranteed` both 0 → *No exposure reported* tagged `delivered`
  (a book-wide zero implies every category's zero — the inference runs that
  one direction only); otherwise → *Not reported*, untagged.

**Application-outcome lines**: `contractsSummary.DeclinedNo / RejectedNo /
NotTakenUpNo` per category × role render as "2 declined · 1 rejected" inside
the role block **only when non-zero** — the payload's only delivered record of
an application outcome (§08's rows carry no such vocabulary). These counters
also keep a card alive in the emptiness test: a category holding only declined
applications is not "nothing reported". The volume counts
(`TotalNo`/`ActiveNo`/`ClosedNo`) are read for the emptiness test only, never
displayed.

**Deliberately off screen**: `MaxCurrentPaymentDelay` — delivered as `1` while
every other field in the reference file contradicts it; held until AECB
explains (RRM, Aug 2026).

---

## §07 Credit Facilities — Detail & 36-Month Conduct

**Arrays: `contracts` × `contractsHistory`, joined by `CBContractId`.** History
rows index by months-before-report-date; anything at month 36+ is dropped at
the join, so the window holds by construction.

### The four blocks (bucketing is a payload decision, made in Python)
1. **Active facilities** — everything `ActiveFlag: Active` except quiet
   services. Closure is **`ActiveFlag`'s business alone** — on an active
   instalment, `ClosedDate` is the *scheduled maturity*.
2. **Closed · last 6 months** — `ClosedDate` inside the window (`bands.json`
   `closed_window_months`, required).
3. **Closed · beyond 6 months** — the rest, **including undated closures**
   (claiming recency the payload doesn't support is the worse error; the row
   says *Closed · date not reported*).
4. **Services — no arrears** — context, folded. *Arrears* is deliberately
   broad: overdue money, a current delay, **or** a current status ranked below
   normal (unrankable counts as adverse for this split).

Within a block, facilities group by category. Empty categories and blocks are
omitted — §06 is where absence is a finding.

### The three strips (36 cells each, newest month at the left)
| strip | source | cell states |
|---|---|---|
| Status | `contractsHistory.ContractStatus` per month | letter code coloured by rank (red ≤60 / amber <100 / grey-green 100 / **ringed unknown** for `?`); pre-open blank; closed-after grey; unreported grey with "no status reported" |
| DPD | `contractsHistory.DaysPaymentDelay` | bucket colours d0–d4: 0 · 1–29 · 30–59 · 60–89 · 90+. Pre-open / after-closure / **not reported** are three distinct grey states with explicit tooltips ("NOT REPORTED — … not a record of on-time payment"). A month whose status arrived with a **null delay** paints not-reported, never "0 DPD" — a zero the bureau never sent |
| Utilisation (cards/overdrafts only) | `contractsHistory.UtilizationRate` | green ≤100, red over, grey unreported; strip omitted entirely when the contract never reports one (it isn't part of the instalment/service schema) |

**Cell tooltips** carry that **month's own** delivered `Balance` and
`OverdueAmount` (never the row-level current balance).

### The row label — stats and chips (each renders only when delivered)
| item | source |
|---|---|
| Name · provider badge | `ContractType`, `ProviderNo` — the provider name prints only when it differs from the code; the name's hover carries `CBContractId` and `ProviderContractNo` when delivered |
| Limit / OS / Payment | `Current_CreditLimit`, `Current_Balance` (hover: **as at** `Current_ReferenceDate` — the snapshot can lag the report date), `PaymentAmount` |
| Amount | `TotalAmount` — original principal, paydown context beside OS |
| Tenor `paid/total` | `NoOfInstallments` − `NoOfRemainingInstallments` |
| Util | `Current_UtilizationRate` (green/red at 100) |
| Method / Secured | `MethodOfPayment`; `SecuredContractFlag`/`SecurityType` |
| Max DPD | deepest `DaysPaymentDelay` in the window (red) |
| **Worst ever** chip | the contract's dated lifetime fields (`WorstStatus`+date, `MaxDaysPaymentDelay`+date, `MaxOverdueAmount`+date) — only when adverse or unrankable; severity-toned; hover states it can predate the window |
| **Open dispute / Holder not liable / non-AED currency** | `FlagOpenDispute`, `HolderIsNotLiable`, `OriginalCurrency` ≠ AED — amber chips |
| Reported n/m | n = months filed; **m = months the facility was open inside the window** (closure-aware), so a 3-month-old loan reported 3/3 is complete; flagged thin only when n < 6 *and* n < m |
| Closed · Final | `ClosedDate`; Final status from **the closing month's own history row** — none reported → *Final · not reported* (the lifetime worst is not a stand-in) |
| Frequency / Role | `PaymentFrequency` matched to its config letter, only when delivered (cards/services carry none — no gap to report); `Role` only when **not** main holder. A delivered frequency or role the config cannot read shows **as delivered** (role in a grey chip) — an unknown role is never assumed to be main holder |
| OVER LIMIT / Overdue now | utilisation > 100; `Current_OverdueAmount` |

**Coverage line**: facility-months reported over months-open (same honest
denominator), with *"absence is not a clean record."* **Status legend**: only
codes present in this report, full table behind an expander; `?` joins only
when an unknown status actually occurred. A reported month with no status code
paints `?`, never a clean default.

**Deliberately unread**: `PaymentBehaviour` (undocumented `'0'/'1'` coding —
unknown vocabularies need a config under MRM, not a guess) and the sparse
card-activity fields (`AmountSpent`, `CardUsedFlag`, `MinimumPaymentFlag`,
`BilledAmount`), which feed the AI brief's fact digest instead.

---

## §08 Recent Applications

**Arrays: `applications`; `contractsTotalSummary.Applications90D` for the
pill.** One chart.

- **Position**: `LastUpdateDate` (AECB's movement date), falling back to
  `DateOfLastUpdate`.
- **The split axis**: the last 90 days take a fixed **62%** of the width;
  everything older compresses into the rest. Both zones are linear internally
  and meet at the boundary. The distortion is stated on screen, and the ticks
  change units at the break — *days* inside the window, *calendar years*
  outside — to signal the scales differ. When everything falls inside 90 days
  there is no compressed zone and no break is drawn.
- **Markers**: hollow = `Requested`, filled = `Disbursed` — the only two
  delivered phases; no approved/rejected/NTU vocabulary is invented. Any
  other delivered phase draws **dashed** (text in the hover; an *Other phase*
  key entry only when present) — never passed off as Requested. Glyph
  I/C/S keyword-matched from `ContractType`; unmatched types get no glyph
  rather than a guessed one. Colliding markers stack **upward** into lanes
  (max 4), never sideways.
- **Exception marks, delivered-only**: a truthy `FlagOpenDispute` rings the
  marker amber; a non-main-holder `Role` letters the provider label
  (`B04 · G`, the A/C/G vocabulary; a delivered role the config cannot read
  letters `?` and is named in the hover — never assumed main holder). Each has a legend entry that renders only
  when the payload contains the exception. Hover names the dispute state both
  ways (a delivered `False` reads *No dispute*; absent says nothing).
- **Hover line**: date + days-ago, contract type, provider, phase, and — when
  delivered — amount, limit sought (both marked *currency assumed*),
  instalment count, role, dispute, and the `CBApplicationId` /
  `ProviderApplicationNo` numbers.
- **Header pill**: the delivered `Applications90D` graded ≥ `bands.json`
  `applications_90d_red` (4) red / ≥ `applications_90d_amber` (2) amber /
  else green (one application is not adverse; a cluster is). The section also
  counts rows itself — **strictly** under 90 days, which reconciles exactly
  with AECB's own counter — and a mismatch surfaces as a second small tag
  ("N rows in window"): one line, not a banner. Its hover explains the
  difference when a recount at `score.DataPullDate` reproduces AECB's figure
  — AECB computes the counter at its own pull date while the report is dated
  by the enquiry (archive: 5 at 26 Oct 2023, 0 at 20 Aug 2024).
- **Empty states** distinguish "no applications reported" (empty array) from
  "cannot be placed in time" (rows exist, none datable).

---

## Configuration quick reference

| file | kind | drives |
|---|---|---|
| `status_codes.json` | bureau-published | status codes/labels/ranks (§03, §07), roles A/C/G (§06, §07, §08), payment frequencies (§07), DPD buckets (§07) |
| `bands.json` | FH policy | score scale + FH band cut-offs and tones (§02), AECB letter→label map (§02), vintage bands (§02), `validity_days` (top bar), `closed_window_months` (§07), `applications_90d_red` / `_amber` (§08) |
| `providers.json` | registry (stub) | provider code → name/kind everywhere a provider shows |
| `income.json` | FH policy | currency label, placeholder floor 1,200, confirmation window 12m (§04) |
| `returns.json` | vocabulary + policy | instrument type labels, severity tones, review window 6m (§05) |

Policy changes are config edits, not code changes. A missing config file
**raises** — a silently empty one once rendered every status as clean. So do
the policy numbers with no safe default (validated when the report context
loads, 24 Sep 2026): `bands.json` `validity_days`, `income.json`
`placeholder_floor`, `confirmation_window_months` and `currency`,
`returns.json` `window_months`, and `bands.json` `closed_window_months` and
`applications_90d_red` / `_amber` (amber no higher than red) — missing, zero, negative or the wrong type
stops the render with an error naming the key.

## Known gaps (open, by decision or awaiting data)

- `providers.json` is a stub — codes render as names.
- `MaxCurrentPaymentDelay` held off screen until AECB explains it (§06).
- Severity `Reported` renders neutral pending a business definition (§05).
- §03 refinements: a derived 24-month reconciliation against the delivered
  figure; flagging guarantor conduct distinctly in the 36-month derivation.
- Score cut-offs need reconciling against the FH scorecard (§02).

## The quality gate

`scripts/check_report.py` renders every payload in `ReferenceJSON/` and fails
if: any delivered value it tracks is missing from the page (name, title, score,
the CB subject id — visible in §01, not merely in `<title>` — every
identification value, mobile/landline/e-mail contact, address —
including the *Address not provided* statement — employment income, return
amount, non-zero guaranteed-overdue or outcome counter, and §07/§08's
only-when-delivered blob keys); if a verbatim figure is not in the exact
element meant to carry it (§03's delivered panels, §06's utilisation); or if
any external URL appears in the output. Run it after every change.
