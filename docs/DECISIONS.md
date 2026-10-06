# FH AECB Analyzer — Decision Register

This register records the settled product and data decisions and the payload
traps the code handles. Each entry gives the decision, the reason for it, and
where relevant its consequence. The reason is what prevents a decision from
being reopened by accident. Several behaviours below look like bugs but are
deliberate; treat them as settled unless new evidence (for example a real
payload) contradicts the rationale. In that case raise the entry for review.

Label-level behaviour is in [LowLevelArchitecture.md](LowLevelArchitecture.md).
The open items are at the end of this document.

---

## General rules

**GEN-1 Nothing fabricated.**
*Decision:* every figure on screen is either delivered by AECB (shown
verbatim) or arithmetically derived from delivered values, and each is tagged
`delivered` or `derived`.
*Rationale:* on a credit screen a fabricated figure cannot be told from a
real one.
*Consequence:* `scripts/check_report.py` and `scripts/check_corpus.py` fail
when a delivered value goes missing or a verbatim figure changes.

**GEN-2 Absence never renders as good conduct.**
*Decision:* missing data reads *not reported*. Unreported months are grey,
never green. Unknown statuses are ungraded. An unreadable flag is read as
"not reported", never as `false`.
*Rationale:* "reported as zero" and "not reported" mean opposite things.
Rendering them alike turns missing data into a clean record.

**GEN-3 Delivered beats derived.**
*Decision:* where the bureau delivers a figure, it wins over anything the app
computes. Examples: the FH band (SC-1), the 36-month floor (WS-4) and the
applications pill (APP-3). A disagreement is shown as an amber `!` with both
values in the hover.
*Rationale:* the app's aggregation cannot overrule the bureau's own figure.

**GEN-4 No on-screen sentence describes a single file.**
*Decision:* explanations state the rule ("a trend needs two figures the bureau
has dated"). They never count this payload's nulls.
*Rationale:* the screen is an underwriting tool, not a defect report, and each
statement must hold for any payload in the same state.

**GEN-5 Red, amber and green mean risk only.**
*Decision:* neutral facts such as residency, vintage and provider kind render
in brand blue or grey. The score band chip is the one exception, because a
score band is a risk grade.
*Rationale:* a green "Resident" would imply that being resident is good.

**GEN-6 Configuration fails loudly.**
*Decision:* each of the following stops the render with an error naming the
problem:
- a missing config file;
- a missing or invalid policy number;
- a status code without an integer rank;
- missing or unordered severity cut-offs;
- a score scale or band list that is not ordered;
- an unknown band tone.

*Rationale:* a silently empty or defaulted configuration renders every status
as clean. A defaulted policy value produces a plausible report whose policy
has quietly gone.

**GEN-7 Unknown vocabulary is shown, never guessed.**
*Decision:* statuses, phases, roles, frequencies, severities and providers that
the configuration does not know are shown as delivered and left ungraded. No
`ReportType` vocabulary is hard-coded.
*Rationale:* a risk colour is a claim. An unknown vocabulary needs a reviewed
configuration entry, not a code default.

**GEN-8 Untyped scalars have one set of reading rules (`aecb/coerce.py`).**
*Decision:*
- Amounts accept numeric text with thousands commas.
- Counts and the score must be whole numbers.
- Flags have three states: true/1/Y/yes/T means yes, false/0/N/no/F means
  no, and anything else means not reported.

*Rationale:* the report and the AI Analysis's fact digest must read the same
field the same way, and `"N"` must never read as a raised dispute. One module
is the only way to guarantee both.

## Payload traps (handled; do not regress)

| ID | Trap | Handling |
|---|---|---|
| TRAP-1 | Trailing spaces on enum values (`"Requested "`, `"E-mail "`) | Loader strips every string. An empty string becomes null. |
| TRAP-2 | `ContractCategory` is a letter in `contracts` but a phrase in `contractsSummary` | Canonicalised to `I`/`C`/`N`/`S` |
| TRAP-3 | Values that are no longer current are marked by a `(Historical)` suffix on the type string, not by a flag | Suffix split off. Current vs historical is decided per provider (ID-2). |
| TRAP-4 | Rows repeat once per reporting provider, not once per fact | Rows deduplicated by value, keeping the set of providers |
| TRAP-5 | Three date formats: ISO, `25 July 2016`, DDMMYY | One parser. Two-digit years are read as 20xx. |
| TRAP-6 | Contract status arrives as display text (`Active Payments`), not a code, and not always spelled as AECB's table (`Write Off` for `Write-off`) | A reverse map from label to code that ignores hyphens, spacing and case. An unmatched status becomes `?`, never an invented letter. |
| TRAP-7 | `ClosedDate` on an **active** instalment is the scheduled maturity date | Closure is decided by `ActiveFlag` alone |
| TRAP-8 | `contractsHistory` is sparse (most contracts have a few months) | Unreported months render grey, as "not reported" |
| TRAP-9 | `WorstStatus24M` exists in two arrays with two vocabularies (display text in `contractsTotalSummary`, letter code in `summary`) | §03 shows `contractsTotalSummary`. `summary`'s value only raises an amber `!` when it names a different status. |
| TRAP-10 | `summary.Worststatus` is an integer | Read as a lifetime count of worst statuses, not as a status code |
| TRAP-11 | `TotalExposure` counts a revolving facility's full credit limit, not its balance (archive fixture: 331,420 instalment balance + 59,600 card limit = 391,020 delivered) | The §06 header total is deliberately not the sum of the balances below it |
| TRAP-12 | `CreditUtilizationRate` on the total-level array is the card utilisation (archive fixture: card balance ÷ card limit rounds to the delivered 57) | Shown only in the Credit cards card |
| TRAP-13 | `contractsFinancialSummary` is effectively active-only (closed instalments carry zero balances) | Supports the "Active" in §06's title |
| TRAP-14 | `paymentOrder.IBAN` is masked with a run of asterisks | The run is collapsed to "…" plus the trailing digits. The verbatim value is in the hover. |
| TRAP-15 | Provider class `C` codes appear on returns and are not in `providers.json` | Shown as the raw code |
| TRAP-16 | The Arabic name can arrive encoding-corrupted (`??? ???`) | Rendered as "Arabic name unreadable in payload", with the raw value in the hover |
| TRAP-17 | One mobile number arrives under several prefix spellings | Grouped by a normalised key (ID-3) |
| TRAP-18 | Malformed documents: `NaN`/`Infinity` literals, non-object rows, a non-object document | Literals and non-object documents are rejected. Non-object rows are dropped, counted and reported in the sidebar. |

## Report date and validity

**DATE-1 One report date, read generically.**
*Decision:* the report date is resolved in this order:
1. the latest parseable `sectionStatus."Last EnquiryDate"` across all rows,
   with array order breaking ties;
2. `score.DataPullDate`, as a fallback only;
3. otherwise no date.

Every window, the age and expiry checks, and validity all use this one date.
`ArchiveDate` is never read.
*Rationale:* the enquiry is the event the underwriter is acting on. Reading
every row generically means that a product the bureau adds later dates the
report without a code change.
*Consequence (accepted):* on stale archive payloads the enquiry date can be
months after the contract data. The archive fixture's enquiry is August 2024
while its pull is October 2023, so every window on that page shifts forward.
Live API pulls carry near-identical dates.

**DATE-2 Scope chips come from a single winning row.**
*Decision:* the top bar shows `ReportType` and `EnquiryType` verbatim from the
row that dated the report (array order breaks ties).
- When no row is dated, the first row names the scope while `DataPullDate`
  dates the report.
- A blank `ReportType` shows an amber "Report type not reported" chip.
- An empty `sectionStatus` shows an amber "Enquiry scope not reported" chip.

*Rationale:* the chips and the date must describe the same enquiry.

**DATE-3 Validity is measured against today.**
*Decision:* the age is the number of days from the report date to today,
against `validity_days` (30). The states are:
- valid, for an age from 0 to 30 days inclusive;
- expired;
- future-dated, which is neutral and ungradable;
- unknown, when no date was delivered.

*Rationale:* the question is whether the report is usable now.

**DATE-4 The validity meter uses two colours only.**
*Decision:* the fill and the marker are green while the report is valid and
red once it is not. A plain grey track shows the days remaining.
*Rationale:* coloured zones inside the window would paint a valid report's
marker red beside a green pill.

## §01 Identity & Demographics

**ID-1 No delivered identity value is dropped.**
*Decision:* the newest current value is the headline. Every other value folds
behind a chevron, flagged *Historical* or *Also current*.
*Rationale:* suppressing a value the bureau sent makes the page look tidier
and hides evidence. `check_report.py` asserts every value is on the page.

**ID-2 Current vs historical is decided per provider.**
*Decision:* each provider's own latest report of a value is its verdict. The
value is current if any provider's verdict is current.
*Rationale:* one bank reformatting or dropping a number must not make another
bank's current record stale.

**ID-3 Mobile numbers group across prefix spellings; nothing else is merged by
guesswork.**
*Decision:* a leading `00`, `971` and a single `0` are removed, and a UAE
mobile (nine digits starting with 5) is keyed as `971…`. Any other value keys
on its exact digits and carries a "not a valid UAE mobile" note. Every
current mobile is listed. Landlines fold inside the same Phone tile, and so
do Additional Mobile Numbers, behind their own "N additional" chevron
(grouped the same way as mobiles).
*Rationale:* one person legitimately holds several numbers, and a merge the
data does not support is a fabrication.

**ID-4 The address tile is labelled "Latest", not "Current".**
*Decision:* the address updated most recently is shown as latest.
- A row counts as empty only when the address, emirate, PO box and plot are
  all blank.
- A row with no address but a location renders as "Address not provided —
  Emirate".
- Emirate-only rows collapse only with the row directly before them in the
  payload, and only when the emirate matches.

*Rationale:* the array carries no current marker. An emirate that reappears
later may be a move away and back.

**ID-5 Age and document expiry are measured at the report date.**
*Rationale:* the question is the customer's state when the bureau was queried.

**ID-6 The CB subject id is shown; the warehouse `PKSubjectId` is not.**
*Rationale:* the on-screen id is the link back to the AECB record.

**ID-7 Residency renders in brand blue.**
*Decision:* the value is read with the three-state flag rules. An
unrecognised value is shown as "Residency: *value*".
*Rationale:* residency is a fact, not a risk signal (GEN-5).

**ID-8 Driving licences are not shown.**
*Decision:* `identification` rows whose type is `DrivingLicense` (current or
historical) stay off the page. This is the one exception to ID-1:
`check_report.py` skips exactly that type, so any other new `InfoType` still
fails the gate until a decision says where it shows. The corpus harness
lists it as an informational `vocab.info_type` warning.

## §02 Score & Bureau History

**SC-1 The delivered FH band is authoritative.**
*Decision:* the chip shows `FHScoreBand`. It is never recomputed from the
score. The configured cut-offs only draw the dial zones. If the zones place
the score in a different band, an amber `!` on the dial names both bands.
*Rationale:* computing the band would silently contradict the bureau whenever
the cut-offs drift.

**SC-2 The FH score bands are configured.**
*Decision:* seven bands in `bands.json`: U 300–631, SPR 632–646, VHR 647–652,
HR 653–684, MR 685–719, LR 720–749, VLR 750–900. The archive fixture's score
falls in LR under both the configuration and the delivered band.

**SC-3 Colour follows the FH bands.**
*Decision:* the dial zones take their configured tone, and the AECB chip takes
the FH band's tone.
*Rationale:* one score has one verdict; two colours would read as two
opinions.
*Consequence:* an unknown band *code* renders neutral. An unknown configured
*tone* stops the render (GEN-6).

**SC-4 The score must be a whole number.**
*Decision:* numeric text such as `"732"` or `"732.0"` is accepted. A value
like `732.9` is not a score and reads "Score not reported", with the bureau's
`ErrorDescription` when one was sent.
*Rationale:* truncating such a value would give a plausible score.

**SC-5 Layout: a half-width card with a 120° arc dial beside §03.**
*Rationale:* the score and the worst conduct read as one risk-at-a-glance row.
A 120° arc makes a larger dial than a semicircle at the same height. A
missing score keeps the card: the chips and the bureau history still render.

**SC-6 Bureau history is derived and the vintage band is configured.**
*Decision:* the history is the number of whole months from
`OldestContractOpenDate` to the report date. `summary.MostOldest_InMonth_Total`
is unread because its meaning is unconfirmed. `score.FraudContractFlag` is
unread.

## §03 Worst Statuses

**WS-1 Three panels.**
*Decision:* the panels are:
- the delivered 24-month worst status, with the maximum payment delay under
  it;
- a derived 36-month worst status, with its own maximum delay;
- the delivered lifetime worst-status count (non-services).

*Rationale:* FH policy assesses some employer segments over 24 months and
others over 36, so both windows must sit side by side.

**WS-2 Delivered panels are verbatim.**
*Decision:* no relabelling, rounding or translation into a code. Only the
colour is derived. `check_report.py` reads each figure back out of its own
element.
*Rationale:* RRM instruction.

**WS-3 The 36-month derivation follows the RRM defaults.**
*Decision:*
- The whole book counts, including closed contracts and every role.
- The evidence is the monthly history rows in the window, plus each
  contract's dated lifetime worst status and worst delay when that date falls
  inside the window.
- A severe status outranks a raw DPD figure when naming the event.
- A status the configuration cannot rank makes the window unknown, never
  clean.
- The `derived` tag always shows.

*Rationale:* a closure inside the window does not erase the conduct before it.
The dated lifetime fields cover months that the monthly rows miss.

**WS-4 The 36-month panel is never milder than the delivered 24 months.**
*Decision:* the 36 months include the 24. When the calculation is milder, or
finds nothing, the delivered status and delay are shown and the calculated
result sits behind an amber `!`.
*Rationale:* GEN-3.

**WS-5 The lifetime count is amber, never red.**
*Rationale:* a count says how many, not how deep. §07 shows depth.

**WS-6 The section pill grades delivered statuses only.**
*Decision:* delays are shown but not cross-checked against the statuses.

**WS-7 A delivered zero delay is a fact.**
*Decision:* it prints "0 days". Only a missing field reads *Not reported*. The
36-month sub-line prints "0 days" only when a zero was actually reported.

## §04 Income & Employment

**INC-1 The chart draws only what the dates allow.**
*Decision:* AECB delivers one `GrossAnnualIncome` per employment row and no
series. The chart state is `trend` (two or more dated figures), `single`,
`spans` (bars only) or `none`.

**INC-2 A figure is placed at `DateOfLastUpdate`.**
*Decision:* when that date is missing, the hire date stands in. The point is
drawn hollow and the chip turns `derived`.
*Rationale:* placing a salary at the hire date claims it was the salary at
hire, which is an inference.

**INC-3 Placeholder figures.**
*Decision:* a figure above zero but below `placeholder_floor` (1,200) is
shown, flagged and kept off the chart scale. Exactly zero is a delivered fact
and is plotted. A negative figure is never plotted.

**INC-4 The current employer is the newest start among unfinished jobs.**
*Decision:* the update date never decides which job is current. The header
follows the current employer and never borrows another employer's figure. It
falls back to "Latest salary", then to "Salary on file".
*Rationale:* employment rows carry no current/prior flag, and the update date
describes the record, not the job.

**INC-5 Confirmation window.**
*Decision:* a row last updated more than `confirmation_window_months` (12)
before the report date is stale, and its bar fades. A row with no update date
is unknown, not stale.
*Rationale:* inventing doubt is as wrong as inventing confidence.

**INC-6 Employers group on the exact name only.**
*Decision:* the suffix is stripped and case is ignored, but similar names stay
separate.
*Rationale:* a merge on similarity would be a guess.

**INC-7 Conflicting figures stay visible.**
*Decision:* the figure with the strongest claim is shown. Its ranking, in
order: a current row beats a historical one, a dated row beats an undated
one, a newer row beats an older one, then payload order. Every outranked
figure that differs is listed behind an amber `!`.

**INC-8 The currency AED is assumed.**
*Decision:* the payload carries no currency. The hovers say that AED is
assumed. This applies to §05, §06 and §08 amounts as well.

## §05 Cheque & Direct-Debit Returns

**RET-1 Built from `paymentOrder` only.**
*Decision:* the `summary` three-month return counters (for example
`Amount_checks_returned_3mon`) are not read by this section.
*Rationale:* their window cannot describe a list reaching back years, and
whether the figure is an amount or a count is unverified.
*Consequence:* the archive fixture's counters read 0 while its returns list is
populated. That is harmless because the counters are unread. Do not wire them
anywhere without resolving it.

**RET-2 Window first, instrument second.**
*Decision:* the 6-month review window (`window_months`) is FH policy. Inside
the window, an instrument with no returns still gets a dashed tile. Inside
the "Earlier" fold, absent instruments are omitted. With no report date, no
split is claimed.
*Rationale:* for an adverse section, absence in the window is a finding.

**RET-3 An empty section is not the same as an unchecked one.**
*Decision:* with no rows, the message depends on `sectionStatus`:
- any row whose `ReportType` mentions "bounced cheque" gives green *Checked ·
  none reported*;
- rows exist but none mentions it gives amber *Section not requested*;
- no rows at all gives *Unverified*.

**RET-4 Severity tones.**
*Decision:* Multiple is red and Single is amber. Reported, and any unknown
severity, render neutral.

**RET-5 `score.PaymentOrderFlag` is read only to flag a contradiction.**
*Decision:* the flag raises an amber `!` when it contradicts the rows.

**RET-6 The archive fixture carries four injected returns.**
*Decision:* the delivered file has no returns. Four synthetic returns are
added so that the populated paths render.
*Consequence:* replace them with a real anonymized adverse payload when one is
available.

## §06 Active Credit Facilities — Overview

**FAC-1 The role split is the point of the section.**
*Decision:* main holder and guarantor always render. Co-holder renders only
when the bureau returns figures or counters for role C.
*Rationale:* they are different liabilities, and an absent guarantor block
would leave the position to be inferred from silence.

**FAC-2 The guarantor block's "No exposure reported" is backed by delivered
zeros.**
*Decision:* it is shown only when both book-wide totals,
`TotalBalanceGuaranteed` and `TotalOverdueGuaranteed`, are delivered as 0.
Otherwise the block reads *Not reported*.
*Rationale:* the inference runs one way only. A book-wide zero implies every
category is zero, but a non-zero total cannot be assigned to a category.

**FAC-3 The utilisation line sits at card level, above the role split.**
*Decision:* the bar fills green below 100% and full red at or above 100%.
There is no 0/100 scale. A value that is not a number (e.g. `NC`) is shown
as delivered, with no % and no bar. The line also shows in an empty Credit
cards card.
*Rationale:* the rate has no role dimension, and the printed percentage
already gives the scale. It is a total-level figure, delivered even when no
card is open, and a bar for a non-number would invent a percentage.

**FAC-4 No volume counts are displayed.**
*Decision:* `TotalNo`, `ActiveNo` and `ClosedNo` are read only to decide
whether a category is empty.
*Rationale:* they span more history than the delivered contract rows, which
invites a comparison with §07 that cannot be made.

**FAC-5 Some surfaces render only when non-zero.**
*Decision:* the Guaranteed and Guaranteed-overdue header chips, and the
declined / rejected / not-taken-up counters per role, appear only when
non-zero.

**FAC-6 `MaxCurrentPaymentDelay` is not shown.**
*Decision:* the field stays off screen until AECB explains it.
*Rationale:* in the archive fixture it reads 1 while every other delay field
reads 0. Showing it would state a contradiction the file cannot resolve.

**FAC-7 The balance is the headline of all four cards, and all category chips
are brand blue.**
*Consequence:* §06 and §07 intentionally use different colours for the same
category.

## §07 Credit Facilities — Detail & 36-Month Conduct

**HM-1 Four blocks, bucketed in Python.**
*Decision:* the blocks are:
- Active;
- Closed within the last `closed_window_months` (6);
- Closed beyond that window;
- Services with no arrears (folded).

*Rationale:* which block a contract belongs to is a payload decision, so it
is made in Python. `report.js` only draws.

**HM-2 An undated closure joins the older bucket.**
*Decision:* the row reads "Closed · date not reported".
*Rationale:* claiming a recency the payload does not support is the worse
error.

**HM-3 "Arrears" is deliberately broad.**
*Decision:* an overdue amount, a current delay, or a current status ranked
below normal (or unrankable) all count as arrears.
*Rationale:* filing a service that is in arrears under "no arrears" is the
failure that matters.

**HM-4 Empty categories and blocks are omitted.**
*Rationale:* §06 is where a category's absence is reported.

**HM-5 The pill uses AECB's words.**
*Decision:* "N Active · M Closed". The archive fixture reads "5 Active · 10
Closed".

**HM-6 An unreported month is not zero.**
*Decision:* a month with a status but no delay figure paints "not reported",
never 0 DPD. Cell tooltips carry that month's own delivered balance and
overdue amount.

**HM-7 Coverage counts only the months each facility was open inside the
window.**
*Rationale:* a young loan reported in full is complete, not thin.

**HM-8 The final status comes from the closing month's own row.**
*Decision:* when that row is missing, the row reads "Final · not reported".
*Rationale:* a lifetime worst status is not the status the loan closed on.

**HM-9 Row chips appear only when meaningful.**
*Decision:*
- Frequency shows only when it is delivered.
- Role shows only when it is not main holder.
- A role the configuration cannot read is shown as delivered, never assumed
  to be main holder.
- A *Worst ever* chip shows only when adverse or unrankable.
- A non-AED `OriginalCurrency` gets an amber chip.

**HM-10 Deliberately unread fields.**
*Decision:* the following are not read:
- `PaymentBehaviour`, which uses an undocumented `0`/`1` coding;
- the card-activity fields `AmountSpent`, `CardUsedFlag`,
  `MinimumPaymentFlag` and `BilledAmount`;
- the contract `FraudFlag`.

*Rationale:* an unknown vocabulary needs a reviewed configuration, not a
guess.

## §08 Recent Applications

**APP-1 A split time axis.**
*Decision:* the last 90 days take 62% of the width, and older applications are
compressed into the rest. The distortion is drawn and stated on screen. When
every application falls inside 90 days, there is no compressed zone.
*Rationale:* on a linear axis the window that matters would take about 9% of
the width.

**APP-2 The row count is strictly under 90 days before the report date.**
*Consequence (accepted):* AECB computes `Applications90D` at its own pull
date, while the rows are counted from the report date (DATE-1). On the
archive fixture AECB delivers 5 and the rows give 0, so an amber "0 rows in
window" tag appears. Its hover explains the gap, because a recount at
`DataPullDate` reproduces AECB's figure.

**APP-3 The pill grades the delivered `Applications90D`.**
*Decision:* 4 or more is red and 2 or more is amber
(`applications_90d_red` / `_amber`). Otherwise it is green.
*Rationale:* one application is not adverse; a cluster is.

**APP-4 Phases are configured.**
*Decision:* the phases are B Disbursed, D Declined, J Rejected, N Not taken up
and R Requested, matched by code or description. Disbursed is drawn filled
and Requested hollow. Every other phase, including an unconfigured one, is
drawn dashed and named in the key ("Other phase" for unconfigured text).
*Rationale:* a declined application must never be passed off as Requested.

**APP-5 Markers.**
*Decision:*
- Markers are brand blue, never a risk colour.
- A marker's letter is the contract category, matched by keyword. An
  unmatched type gets no letter.
- Colliding markers stack upward into at most four lanes, never sideways.
- A dispute ring and a role letter appear only when delivered.

*Rationale:* the cluster is the signal, not a single application. Shifting a
marker sideways would place it at the wrong date.

## Data handling and security

**SEC-1 Read-only viewer.**
*Decision:* nothing is written back to any system. The report is one
self-contained HTML document with no external references, and it can be
downloaded and filed.

**SEC-2 Payload data never becomes markup or script.**
*Decision:* the controls are:
- every payload string is escaped;
- the data blob is script-safe JSON;
- each page carries a Content-Security-Policy that admits only its own
  script, by hash.

**SEC-3 No internals reach the browser.**
*Decision:* tracebacks, response bodies and internal addresses go to the
server log only. The user sees a short message.

**SEC-4 Logs carry subject ids, never payload content.**
*Decision:* one audit line is written per query (subject, outcome, user,
client address).

**SEC-5 The committed fixtures are anonymized or synthetic.**
*Decision:* the archive fixture keeps the genuine AECB structure with an
anonymized subject. The delinquent fixture is generated by
`scripts/make_synthetic_payload.py`.

## AI Analysis

**AI-1 The model computes nothing, and the underwriter decides.**
*Decision:* every figure the model writes must appear verbatim in a cited,
deterministically computed fact or validated item; a failing item is dropped,
never repaired. The model may state a *suggested* outcome (Approve / Approve
with conditions / Refer / Decline) with cited drivers. It is advisory, always
labelled "Suggested from bureau data only; policy and application context not
applied; the underwriter decides", and **no floor or decision rule is applied
in code**.
*Rationale:* the analysis is an additional risk input the underwriter reads
and weighs, not the decision mechanism. A floor is a credit-policy rule;
policy is not connected to this tool, and a hidden rule in the model's output
path would be a decision rule without a policy owner. The evaluation harness,
not the runtime, asserts that the delinquent golden fixture never yields
"Approve".

**AI-2 Prohibited factors are excluded.**
*Decision:* `Nationality`, `Gender` and `ResidentFlag` never enter the fact
digest. A runtime check refuses the analysis if one does.
*Rationale:* nationality and gender are impermissible underwriting factors,
and ResidentFlag is nationality-adjacent.

**AI-3 Opt-in, routed by environment.**
*Decision:* the analysis is generated on request, never automatically, one
block at a time so finished blocks show while the next runs. The view opens
from the top-bar button; the report is complete without it. The model
provider follows `AECB_ENV`: `dev` uses the local open-weight model (Ollama,
loopback only); `uat` and `prod` use Core42 through its API.
*Consequence:* the Core42 connector is a placeholder until Core42 is
onboarded (OPEN-13). The provider map is in `aecb/brief/providers.py`;
changing it changes where bureau-derived data goes, so it is a model change
([AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md) section 7).

**AI-4 The checklist is replayed by the model from step packets, with a
tripwire audit.**
*Decision:* the credit team's ten steps are performed by the model, which
judges each step's status and writes the indicators, but every day count,
expiry comparison, window test and over-limit inference is computed in
Python and handed over as citable facts (`derive/brief_facts/steps.py`). An
indicator may cite only its own step's facts. A step marked clear while its
packet carries a tripwire fact is flagged "possible miss"; the model's status
stands.
*Rationale:* the team wants the AI to follow their process, not a rules
engine; the packets keep its arithmetic honest and the audit makes a missed
tripwire visible instead of silent.

**AI-5 Step 2 carries the age only.**
*Decision:* the name is not sent to the model (no subject identifier ever
is), and nationality, gender and residency never enter any text (AI-2). The
step states that the policy comparison is not available.

**AI-6 The memo reads validated items only.**
*Decision:* the memo and recommendation pass receives the validated findings
and indicators of the other blocks, renumbered, plus each step's status --
never the payload or the digest -- and its output is re-validated against
those items. It cannot introduce a figure or a name the blocks did not carry.

**AI-7 Feedback is an append-only file outside the application.**
*Decision:* one thumbs up/down and an optional comment per analysis, written
as JSON lines to `AECB_FEEDBACK_DIR` (0700/0600, off when unset), each
carrying the analysis's generation id. The comment is never logged; the
verdict is, in the audit log. Review of the file is the model owner's
monitoring task ([AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md) section 8.2).

**AI-8 The AI Analysis is a full-width view.**
*Decision:* while open, the AI Analysis replaces the report (body class
`analysis-on`), with a sticky block nav and "Verify at §N" links back into
the report.
*Rationale:* four blocks and a memo need the page width; hiding the report
rather than reflowing it keeps every measured geometry unchanged.
*Consequence:* `rail-off` stays as the layout-state class every page carries
(`report.css` computes the fluid scale and the density step on it). Folding
it into plain selectors is deferred and needs the geometry harness
(OPEN-15).

**AI-9 The fresh lens is a hypothesis -> verification loop.**
*Decision:* the model proposes typed hypotheses from raw monthly tables
(contracts aliased K1..Kn) in a closed grammar of eight types; Python
verifies each one against the full history and records it as confirmed, not
supported or not assessable; confirmed and refuted results become citable
facts (`[verified]`); the findings pass then writes over the fact table plus
those facts, with a framing per finding. A finding resting only on refuted
facts is held at "watch". The model's free-text ("custom") hypotheses are
never verified: they render apart as "Unverified observations" (figures and
names checked against the tables only), never as findings and never in the
memo. If the model proposes no typed hypothesis, a fixed Python candidate
list is verified instead and the block says so.
*Rationale:* a pattern claim from a model over a 36-month history is either
computed or it is a guess; the loop makes the model's pattern-finding
testable and keeps every figure in a verified fact computed. Recording
refuted hypotheses keeps the loop honest on the page.
*Consequence:* two model passes per lens (hypotheses, findings); the
verifiers' thresholds are part of the digest contract under MRM change
control ([AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md) section 3a).

**AI-10 Non-obvious risk is computed by lenses and read with a basis.**
*Decision:* block 2's patterns (card cycling, cash-like cards, minimum
payments with spend, seasonal delays, pre-enquiry clean-up, lender
concentration, non-bank reliance, guarantor exposure, instalments past
working age, income trajectory, employer churn, selective default) are
deterministic Python lenses with documented thresholds; the model reads
them against the context register and a headline index of the file (not
the full digest) and writes findings whose basis -- payload, payload with
register context, or inferred -- Python derives from the cites. An
employer's sector may be inferred from its name alone, from the register's
closed vocabulary, labelled "inferred, verify", capped at watch; such a
finding reaches the memo as an item the memo may weigh but a driver may not
cite.
*Rationale:* the patterns are arithmetic and belong in Python; the model's
value is connecting them. A sector guessed from a name is useful colour and
never evidence, so it is bounded, labelled and kept out of the decision
path. The compact input keeps the pass at about a third of the findings
pass's tokens.

**AI-11 The context register has an owner, a cadence and a vocabulary.**
*Decision:* `config/macro_context.json` names an `owner` (today "to be
named (model owner)") and a `review_cadence` (quarterly), carries dated
topic-tagged `register` entries and the closed `sectors` vocabulary, and the
loader refuses a vocabulary without an owner. The register is the only
background channel: the file carries no separate macro `facts` list.
`config/providers.json` tags non-bank lenders `kind: "nbfi"` (N01 for the
patterns fixture; unknown N## codes read as nbfi). Both are model inputs
under MRM change control.
*Rationale:* one channel means one owner and one review for everything
time-sensitive the model sees.
*Consequence:* the model owner's first task is to put a name on the
register ([AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md) section 11).

**AI-12 Reasoning level per pass and compact inputs.**
*Decision:* each pass declares its reasoning level beside its prompt
(`EFFORT` in `aecb/brief/prompts/`): `low` for lens H (hypotheses), lens W
(findings) and the risk pass; `medium` for the checklist and the memo. Every
model input is compact without dropping a figure, a field path, a hard rule
or a guard:
- raw tables carry a card's limit instead of a utilisation column, cells
  only where they carry something and identical consecutive months
  collapsed, within a 10,000-character budget;
- pass H's headline index holds the structure and behaviour facts at 80
  characters each, and the risk block's index is cut to 80 characters;
- contract labels omit the opening date, which one fact states for every
  contract;
- of the checklist's step facts, pass W reads only the tripwires and the
  validity fact, and is validated against exactly what it read;
- memo item labels are short, and the system texts are tight.

*Rationale:* Core42 bills per token, and reasoning is most of every reply.
On gpt-oss:20b, `low` makes the lens and risk replies 70-90% smaller and
meets every evaluation assertion on the development runs; the checklist at
`low` marked a tripwire step clear in two of four runs, and the memo's
drivers lost their figures, so those two run at `medium`
([AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md) sections 2.4 and 8.3).
*Not done, on evidence or by decision:*
- the risk pass is not merged into pass W: its facts in W displaced a golden
  finding, and block 2 would become a by-product of the lens;
- the shared hard rules (`RULES_COMMON`) and the checklist's
  one-status-per-line table are kept word for word: compressed versions cost
  quality at `low` in A/B runs on identical input;
- no positional trajectory series: a misattributed month would pass the
  figure guard;
- the history stays at 36 months.

*Consequence:* the full evaluation (`scripts/eval_brief.py`) on the `p1.0`
prompts with gpt-oss:20b has not been run. At `low`, pass W sometimes loses
the unconverted-applications finding to the figure guard; if the evaluation
fails that golden, the fallback is pass W at `medium` (`p1.1`).
`scripts/token_budget.py` measures the prompt side of a change in about a
minute.

**AI-13 The target model is gpt-oss-120b; the local model comes from a closed list.**
*Decision:* the target model is gpt-oss-120b, the model UAT and production
use through Core42. In development the Ollama client serves one of two
reviewed models, `gpt-oss:120b` (the default) or `gpt-oss:20b`, chosen by
the developer-machine setting `AECB_OLLAMA_MODEL`; any other value leaves
the panel unavailable with the reason shown and never falls back to another
model. The model is read when used (`provider.model()`), not at import, so a
settings file loaded after import still applies. Both models run the same
decoding options and the same per-pass reasoning levels (AI-12); the
timeout is per model (600 s for 120b, an estimate; 300 s for 20b). The AI
Analysis scripts (`check_brief.py`, `eval_brief.py`, `token_budget.py`) read
`~/etc/aecb-analyzer/aecb.env` from `main()`, as the app does;
`scripts/eval_brief.py --effort` runs passes at other levels for
development only. The Core42 placeholder's documented contract names
gpt-oss-120b, `reasoning_effort`, `response_format` with the schema keywords
the passes rely on, reasoning returned separately and Harmony applied
server-side; the placeholder has no network code.
*Rationale:* the evidence should come from the model that will run, so the
org laptop (M5 Max, 128 GB) runs 120b by default, while the 24 GB
development Mac, which cannot hold 120b's ~65 GB, develops on 20b. A closed
list keeps every selectable model reviewed and a mistyped setting harmless,
as `runtime.resolve` does for an invalid environment. Every 20b workaround
is kept: each is a guard or costs nothing, and removing one would be
unverified risk for no token gain. The 20b reasoning levels are the
starting point because their failure modes are known; on a stronger model
`medium` costs tokens, not quality.
*Consequence:* the evidence to date is gpt-oss:20b
([AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md) section 8.3). Every 120b figure
(prompt and reply tokens, latency, memory, timeout, price) is an estimate;
MRM section 9 holds the ten assumptions (A1-A10), the org-laptop validation
plan and its decision rule, and section 12 the 120b planning estimate. The
validation is pending. Core42's own run at onboarding governs UAT and
production (OPEN-13).

## Deployment

**DEP-1 The server stays on Python 3.9.**
*Decision:* the air-gapped server keeps CPython 3.9 with streamlit 1.50.0.
*Rationale:* the runtime is fixed on the air-gapped host.
*Consequence:* Mend findings whose fixes need Python 3.10 or later are handled
through [DEPENDENCY_RISK.md](DEPENDENCY_RISK.md): each is assessed as not
reachable, with compensating controls. The remediation is a Python upgrade.

**DEP-2 API credentials come from environment variables only.**
*Decision:* the credentials are `AECB_API_USERNAME`, `AECB_API_DOMAIN` and
`AECB_API_PASSWORD`, loaded from a 0600 environment file. A
`config/api.json` that carries an `auth` block is refused.
*Rationale:* a password in a file inside the application tree must not keep
working unnoticed.

**DEP-3 API responses are archived outside the application.**
*Decision:* responses go to `AECB_ARCHIVE_DIR` (folder mode 0700, file mode
0600). If the variable is unset, or points inside the app tree, archiving is
off. Retention is an operations task.
*Rationale:* the archive holds real bureau data.

**DEP-4 The AI Analysis is not live on UAT or production.**
*Decision:* on UAT and production the page shows the AI Analysis button
marked "Coming soon". Clicking it opens a view that says the feature is
being built and will be switched on after validation and approval. No model
is called, and `app.py` does not load the `aecb.brief` package in this
state. The downloaded HTML carries no AI control. No model service (Ollama)
is installed. The server stays air-gapped (DEP-10) until Core42 is
onboarded.
*Consequence:* going live means setting `AECB_AI_BRIEF=live`, a model change
that needs Core42 onboarded, the one egress route from the server to Core42
(DEP-10) and MRM approval first ([AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md)
sections 2.1 and 11).

**DEP-5 One entry point, `app.py`, everywhere.**
*Decision:* the app has one entry point, `app.py`, run the same way on every
machine (`streamlit run app.py`). Development tools (a sample picker over the
fixtures and the archive, a CSS/JS reload button) render only with
`AECB_ENV=dev`. There is no file uploader in any environment. On a developer
machine the app reads `~/etc/aecb-analyzer/aecb.env` itself
(`aecb/settings.py`); on a server systemd loads the environment file.
*Rationale:* one way to run the app removes the confusion of several. The
development tools ship in the release but are gated: servers set `uat` or
`prod`, and unset or invalid means `prod` (test-enforced). Having no
uploader keeps the control that no user can submit a payload file.

**DEP-6 Authentication happens in front of the app.**
*Decision:* in production the app binds to 127.0.0.1:8501 and relies on a
TLS-terminating, SSO-authenticating reverse proxy
(`deploy/aecb-analyzer.service`). The proxy can pass the user name for the
audit line. UAT is the one exception (DEP-9).

**DEP-7 The release is exactly what is committed.**
*Decision:* the release is a `git archive` of HEAD, and every dependency is
pinned with a sha256 hash in `requirements.lock`. The installer's
`pip check` accepts only the one known line "streamlit 1.50.0 requires
watchdog, which is not installed." and fails on anything else.
*Rationale:* the lock is resolved on macOS, where streamlit does not need
watchdog; watchdog only watches source files, and file watching is off
(`.streamlit/config.toml`). Any other broken requirement is a real fault.

**DEP-8 The environment is named by `AECB_ENV`.**
*Decision:* `AECB_ENV` is `dev`, `uat` or `prod`; the UAT server sets `uat`.
Unset, `app.py` assumes `prod`; the AI Analysis scripts, which never run on
a server, assume `dev`. `dev` also turns on the development tools (DEP-5).
`AECB_AI_BRIEF` (`live`, `coming_soon` or `off`) sets the AI panel; unset, it
is `live` in dev and `coming_soon` in uat and prod.
*Rationale:* an invalid value must not stop the report, and must never switch
the AI Analysis on. It falls back to `prod` with the panel "coming soon",
logs the error, and shows a sidebar note that does not echo the value.

**DEP-9 UAT is served directly on port 8080.**
*Decision:* the UAT server serves the app at `http://<server>:8080` (bound
to 0.0.0.0:8080) with no reverse proxy and no SSO, a UAT-only exception to
DEP-6. The bind address and port come from a systemd drop-in
(`systemctl edit aecb-analyzer`); the shipped unit is unchanged
([OPERATIONS.md](OPERATIONS.md), "UAT").
*Rationale:* a drop-in keeps the exception on the UAT server: the shipped
unit still binds to loopback, so a production install does not inherit it.
*Consequence:* UAT has no TLS and no sign-on, so its audit lines carry no
user. Production must use the reverse proxy.

**DEP-10 The server is air-gapped.**
*Decision:* the UAT and production server has no internet access (no PyPI,
no CDN). Its only outbound connection is the internal bureau-report API.
The single exception is one egress route to Core42, opened only when the AI
Analysis goes live (DEP-4, OPEN-13); it adds no general internet access.
*Consequence:* the install is offline from a hash-pinned wheel bundle
(`pip --no-index --require-hashes`, DEP-7), and the page is self-contained:
fonts and logo inlined, a Content-Security-Policy and no external references
(SEC-1, SEC-2).

---

## Open items

| ID | Item | Current behaviour |
|---|---|---|
| OPEN-1 | `config/providers.json` is a stub; the meaning of provider class `C` is unknown | Provider codes are shown where names should be (§01, §04, §05, §07, §08) |
| OPEN-2 | `MaxCurrentPaymentDelay` needs an explanation from AECB | Held off screen (FAC-6) |
| OPEN-3 | Returns severity `Reported` needs a business definition | Renders neutral |
| OPEN-4 | §03 refinements: a derived 24-month figure to reconcile against the delivered one; flagging guarantor conduct separately in the 36-month derivation | Not built |
| OPEN-5 | DSR and application context (product, amount, tenor) have no payload source | Not shown; they need a separate input |
| OPEN-6 | A real anonymized adverse payload is wanted | Adverse paths are exercised by the synthetic delinquent fixture |
| OPEN-7 | Field meanings to confirm with AECB: `FHScoreBand1`; `summary.Worststatus` (count or code); `summary.MostOldest_InMonth_Total`; the `aecb_ranges` labels; the `PaymentBehaviour` coding; the unit of the `summary` three-month return counters | Read as described above, or unread |
| OPEN-8 | `YYYYMMDD` dates are not parsed | They render as unreadable or not reported |
| OPEN-9 | The retention period for the API response archive must come from the data-retention policy | No purge until operations schedules one ([OPERATIONS.md](OPERATIONS.md)) |
| OPEN-10 | Upgrade the server's Python to 3.10 or later | Known dependency findings are accepted in [DEPENDENCY_RISK.md](DEPENDENCY_RISK.md) |
| OPEN-11 | AI Analysis, before it goes live on UAT or production: the evaluation golden "delinquent: some finding cites a trajectory fact" is intermittent on gpt-oss:20b; the full evaluation on `p1.0` and the gpt-oss-120b validation are not yet run (AI-12, AI-13); the model owner, the approver and the context register's owner are not yet named (AI-11) | "Coming soon" on UAT and production ([AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md)) |
| OPEN-12 | The bureau-report API is reached over plain HTTP on the internal network. Switch `config/api.json` `base_url` to `https://` when the API team offers TLS | NTLM sends no password, but payloads cross the internal network in clear text. The client supports HTTPS with no code change ([SECURITY_REVIEW.md](SECURITY_REVIEW.md)) |
| OPEN-13 | Core42 onboarding for the AI Analysis on UAT and production: endpoint, authentication, model (gpt-oss-120b; Core42's id pinned at onboarding), JSON-schema output support, the reasoning control, and an egress route from the air-gapped server to Core42, the single exception to the air gap (DEP-10). Checklist in [AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md) section 11 | The Core42 connector is a placeholder that refuses every call; the panel shows "Coming soon" |
| OPEN-14 | RHEL 8's python39 venv ships pip 20.2; `deploy/install_offline.sh` requires pip 20.3 or later | Bootstrap pip from a bundled wheel by hand ([OPERATIONS.md](OPERATIONS.md), "UAT"); the scripts do not yet do it |
| OPEN-15 | Fold the `rail-off` layout-state class into plain selectors (AI-8) | Deferred; needs the `scripts/measure` geometry harness |
