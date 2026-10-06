# Low-Level Architecture — FH AECB Analyzer screen

This is a quick reference that maps each label on the screen to its code,
config and payload source. The AI Analysis panel's content is excluded: on
the production page (`app.py` with `AECB_ENV=uat` or `prod`) the panel is "coming soon" and shows no
customer content. Its top-bar button is listed in the header table.

**Columns:**
- *Renders* is the module that emits the label.
- *Logic* is where any decision about the value is made.
- *Config* is the file or constant that drives it.
- *Payload* is the array and field it reads.

Untyped payload values are read through `aecb/coerce.py`:
- Amounts accept numeric text and thousands commas ("12,500").
- Counts and the score must be whole numbers.
- Flags have three states: true / 1 / Y / yes / T → yes; false / 0 / N / no /
  F → no; anything else or null → not reported.

---

## Header (top bar)

On narrow windows the bar sheds items in this order:

1. the `EnquiryType` chip, below 1440 px;
2. the date fields, below 1280 px;
3. the meter, below 1110 px.

The pill and the `ReportType` chip always stay. If a value is too long to fit,
the strip is cut off at its own edge (`.tb-valid-strip` in `report.css`).
This stops it from running under the AI Analysis button.

| Label | Renders | Logic | Config | Payload | Logic explained | Remarks |
|---|---|---|---|---|---|---|
| **Logo** | `branding.brand_mark()`, called by `shell.topbar()`. Styled by `.brand-mark` in `report.css` | `branding.logo_path()`, `branding.logo_data_uri()` | `resources/logo.svg`. Fallback colours: `fh-blue` / `fh-blue-d` in `tokens.py` | None | Takes the logo file from `resources/` and embeds it in the page as base64, 28 px tall. If no file is found, it shows a blue "FH" tile. The same image is used as the browser-tab icon (`branding.favicon_data_uri()`) | Embedded rather than linked because the server is air-gapped and the report is also downloaded as a single HTML file |
| **Title** | `shell.topbar()`. Styled by `.brand-t` in `report.css` | None (fixed text) | `APP_NAME` in `branding.py`, the single source for every place the name appears | None in the bar. The downloaded report's tab title adds the subject id: `customerInfo.CBSubjectId` → `sectionStatus.CBSubjectId` → `customerInfo.PKSubjectId` → `summary.PKSubjectId` → "unknown" (`ReportContext.subject_id`) | "FH AECB Analyzer" everywhere: the top bar, the browser tab (`ui.configure_page()`), both sidebars, the API landing page, and the downloaded report's tab ("FH AECB Analyzer — *subject id*", `page.py`, escaped) | The downloaded file is named `aecb_<subject id>.html`, with unsafe characters replaced (`ui.safe_filename_part()`). The subject id is shown on screen in §01 |
| **Report validity pill** ("Report valid" / "Report expired" / "Future-dated" / "Validity unknown") | `shell._validity_pill()`, called by `shell._validity_strip()`. Styled by `.tb-valid` (green), `.expired` (red), `.future` (amber) and `.unknown` (grey) in `report.css` | `scoring.validity()` for the state; `ReportContext.enquiry_anchor()` for the report date | `validity_days` in `config/bands.json` (30). Required: a missing, zero, negative or non-integer value stops the render with an error | `sectionStatus[]."Last EnquiryDate"` (the field name contains a space), else `score.DataPullDate` | **Report date:** the latest readable `Last EnquiryDate` across all `sectionStatus` rows (time of day ignored; if two rows share a date, the first in the array wins). If no row has one, `score.DataPullDate`. **Age:** days from the report date to today. **Valid:** age 0–30 days. **Expired:** over 30. **Future-dated:** the report date is after today, so it can't be graded (the end date stays "Valid until" and the meter sits at zero). **Validity unknown:** neither date arrived; the bar adds "No enquiry date or pull date delivered — report age cannot be established". Every state has a hover stating its rule | Age is measured against today, not a payload date. The same report date anchors every time window on the page (customer age and passport expiry in §01, bureau history length in §02, the §03 36-month worst status, the §05 returns window, the §07 heatmap, §08 applications) |
| **Enquiry scope chips** (e.g. "ConsumerLong with Bounced Cheques", "NewApplicationEnquiry") | `shell._scope_chip()`, called by `shell._validity_strip()`. Styled by `.tb-scope` (neutral grey) and `.tb-scope.warn` (amber) in `report.css` | `ReportContext.enquiry_anchor()` picks the row | None (no product names are hard-coded) | `sectionStatus[].ReportType`, `sectionStatus[].EnquiryType`, `sectionStatus[].EnquiryNo` (hover only) | The chips come from the single `sectionStatus` row that dated the report (the one with the latest `Last EnquiryDate`). If no row is dated, they come from the first row. Two chips, shown exactly as delivered: `ReportType` (the product the bureau was asked for) and `EnquiryType`. A blank `ReportType` shows an amber "Report type not reported" chip; a blank `EnquiryType` drops its chip. If `sectionStatus` is empty, one amber chip reads "Enquiry scope not reported". Hovers name the field; the `ReportType` hover adds "Enquiry no. *n*" and "Enquiry type: *…*". When no row was dated, both hovers say the scope came from the first row and the date from `score.DataPullDate` | Shown even when validity is unknown. The `EnquiryType` chip is hidden on windows narrower than 1440 px (its value stays in the `ReportType` hover). Whether the bounced-cheque product was pulled is judged separately in §05 (cheque returns) |
| **Enquiry date / Pull date** (date + relative age, e.g. "Enquiry date 20 Aug 2024 · 2.1 years ago") | `shell._validity_strip()` (`.tv-field`); label from `shell._date_label()`; age text from `shell._age_phrase()` / `shell._days_label()`; hover from `shell._basis_text()`. Styled by `.tv-k`, `.tv-v`, `.tv-rel` in `report.css` | `ReportContext.enquiry_anchor()` (date and basis); `scoring.validity()` (age in days); `dates.months_between()` (months and years) | None | Same report date as the pill: `sectionStatus[]."Last EnquiryDate"`, else `score.DataPullDate` | **Label:** "Enquiry date" when an enquiry dated the report, "Pull date" when the `DataPullDate` fallback did (the meter hover uses the same word). **Date:** "DD Mon YYYY". **Age:** "today"; "N days ago" under 60 days; then calendar months ("N months ago") under 24 months; then years to one decimal ("2.1 years ago", "2 years ago"), whole years from 10 up; "future-dated" for a date after today. **Hover:** which field dated the report | Not shown when validity is unknown. Hidden on windows narrower than 1280 px (the meter hover still carries the date) |
| **Validity meter** (bar between the two dates) | `shell._validity_strip()` (`.tv-meter` with `.tv-track`, `.tv-fill`, `.tv-dot`). Styled in `report.css` | `scoring.validity()` computes the position (`pct`) | `validity_days` in `config/bands.json` (30) | Same report date as the pill | **Position:** age ÷ 30 days, capped at 0–100%, so a lapsed report pins at the right end and a future-dated one sits at the start. **Two colours only:** the fill (days elapsed) and marker are green while the report is valid and red when it is not; the plain grey track is the days remaining. **Hover:** "*Enquiry date / Pull date* DATE · look-back window 30 days · valid until DATE. The report is AGE old" (or "is from today", "date is in the future") followed by which field dated the report | Not shown when validity is unknown. Hidden on windows narrower than 1110 px. No axis labels; the window is the gap between the two flanking dates |
| **Valid until** (e.g. "Valid until 12 Oct 2026"; red when expired) | `shell._validity_strip()` (second `.tv-field`). Styled by `.tv-k`, `.tv-v`, and `.tv-v.lapsed` (red) in `report.css` | `scoring.validity()` computes `expires` | `validity_days` in `config/bands.json` (30) | Same report date as the pill | **Date:** report date + 30 days, as "DD Mon YYYY": the last day the report counts as valid (age 30 is still valid). **Label:** always "Valid until". The date is in normal ink while valid or future-dated, and red when expired. The pill's expired hover uses the same wording ("it was valid until …") | Not shown when validity is unknown. Hidden on windows narrower than 1280 px (the meter hover still carries the date) |
| **AI Analysis button** (with a "Coming soon" badge on UAT and production) | `shell.topbar(ctx, ai_mode)`, from `_BRIEF_BUTTONS`. Styled by `.brief-btn`; `.brief-btn.soon` and `.bb-soon` for the coming-soon variant, in `report.css` | `runtime.resolve()` in `app.py` picks the mode; `render_page(ai_mode=...)` | `AECB_ENV` and `AECB_AI_BRIEF` (server environment). Badge and view text: `render/analysis.py` (`SOON_BADGE`, `coming_soon_body()`) | None | **live** (development default): solid blue button; opens the full-width AI Analysis view in place of the report. **coming_soon** (UAT and production default): muted outline button with an amber "Coming soon" badge on its top-right corner; it opens the same view, which says AI-assisted analysis is being built and will be switched on after validation and approval, and never shows findings. **off**: no button and no view. The page loads on the report | The badge sits out of flow, so the button keeps the live button's size and the strip breakpoints hold. The downloaded HTML on UAT and production has no button. The button is kept on one line below ~775 px |

---

## §01 Identity & Demographics

This section reads `customerInfo` (first row only), `identification`,
`contacts` and `addresses`. The first rows below cover the card header, the
name line and the traits line; the tile rows follow. `identification` rows
of type `DrivingLicense` are not shown, by decision (ID-8 in
`DECISIONS.md`), and `check_report.py` does not look for them.

The tiles sit on a six-column grid:
- Row one: Emirates ID, Passport and Phone (two columns each).
- Row two: E-mail and Latest address (three columns each).

On windows 1510 px and wider, with the AI panel closed or absent, the grid
goes four across: E-mail moves up into row one and the address takes row two.

**Shared rules for the identity tiles.** The bureau sends one row per
reporting provider, so the same value arrives many times. The rules are:

1. **Grouping.** Rows are grouped by value (`derive/identity.dedupe()`). For
   document numbers, spellings that differ only in dashes, spaces or case
   count as one value. The most recently reported spelling is shown and the
   others are in its hover ("Also reported as: …"). Each value remembers
   every provider that reported it, with that provider's own latest
   `DateOfLastUpdate`.
2. **Current vs historical, per provider.** A `(Historical)` suffix on the
   type string marks one provider's copy of one spelling as superseded. Each
   provider's own latest report of the value is its verdict (a same-day tie
   counts as current). The value is current if at least one provider's
   verdict is current. So one bank dropping or reformatting a number never
   makes another bank's current record stale.
3. **Headline.** Values sort newest-updated first. The **newest current**
   value is the tile's headline. Its badge is the provider that reported it
   most recently, with the others behind "+N" (the hover lists them, most
   recent first).
4. **Fold.** Every other value folds behind a chevron: "N prior" when all are
   historical, "N more" otherwise. Each folded value is flagged "Historical"
   or "Also current" and shows "provider · Mon YYYY", meaning the most recent
   reporter and that provider's own update date.
5. **Empty states.** If only historical values exist, the newest is shown
   with a "Historical only" flag. "Not reported" shows when no row arrived.

| Label | Renders | Logic | Config | Payload | Logic explained | Remarks |
|---|---|---|---|---|---|---|
| **Section heading** ("01 Identity & Demographics") | `components.section_card()`, called by `sections/identity.render()`. The number comes from `sections/__init__._meta()`; the spine nav marker from `shell.spine()` | Position in `SECTIONS` (`sections/__init__.py`) sets the number | `META["title"]` in `sections/identity.py` | None | The section's position in the `SECTIONS` list sets its number ("01") and anchor (`#s1`); the title is fixed text. If `customerInfo` is empty, only the name line changes ("No customer record — customerInfo is empty in this payload", with the CB Subject ID still shown). The tiles always render, because they read other arrays | Hovering the spine marker shows the section name |
| **Residency tag** (top right: "Resident" / "Non-resident" / "Residency not reported") | `identity._residency()` → `components.tag()`. Styled by `.tag.brand` (blue) and `.tag` (grey) in `report.css` | `derive/identity.resident_flag()` → `coerce.flag()` | None | `customerInfo.ResidentFlag` | Read with the shared three-state flag rules: yes (true / 1 / Y / yes / T) → "Resident"; no (false / 0 / N / no / F) → "Non-resident", both in brand blue. Any other delivered value → grey "Residency: *value*" with a hover saying it isn't a recognised value. Nothing delivered → grey "Residency not reported" | Blue, not green or amber: residency is a fact about the applicant, not a risk signal |
| **Title** (e.g. "MRS", small, before the name) | `identity._name_line()` (`.id-name-ttl`) | None | None | `customerInfo.Title` | Shown exactly as delivered; left out when blank | Checked by `check_report.py` |
| **English name** (headline) | `identity._name_line()` (`.id-name-lg`) | `derive/identity.english_name()` | None | `customerInfo.FullNameEN`, else `FirstName` + `LastName` | `FullNameEN` exactly as delivered. If it's blank, whichever of `FirstName` / `LastName` arrived, joined with a space. "—" if none arrived. When `FirstName` + `LastName` spell the name differently from `FullNameEN` (ignoring case and spacing), an amber "!" follows the name, with the hover "Name parts reported as: …" (`derive/identity.name_parts_variant()`) | Checked by `check_report.py`, including the "!" when a variant exists. The archive payload's full name and name parts differ by one letter, so the "!" shows there |
| **Arabic name** (right-aligned, right-to-left) | `identity._name_line()` (`.id-name-ar`, `dir="rtl"`) | `derive/identity.arabic_name()` and `has_arabic()` | None | `customerInfo.FullNameAR`, else `FirstnameAR` + `LastnameAR` | Shown only if the text contains real Arabic characters; otherwise the name parts are tried. If what arrived is garbled (e.g. "??? ????", lost encoding), a grey italic "Arabic name unreadable in payload" takes its place, with the raw value in the hover (`derive/identity.arabic_name_unreadable()`). Left out when nothing arrived at all | The archive payload's Arabic name is garbled; the synthetic payload's is null. Checked by `check_report.py` |
| **Gender** (first trait) | `identity._name_line()` (`.id-trait`) | None | None | `customerInfo.Gender` | Shown exactly as delivered; left out when blank | |
| **Age and date of birth** (e.g. "32 yrs (09 Jul 1992)") | `identity._dob_trait()` (`.id-trait`, `.id-dob`) | `derive/identity.age_at()` → `dates.months_between()` | None | `customerInfo.DOB` | Age = whole years from DOB to the **report date** (not today), with the DOB as "DD Mon YYYY" in brackets. No report date → "age unknown — no report date (DOB)". Unreadable DOB → "DOB *value* — unreadable date". No DOB → grey "DOB not reported" | On an old report the age is the age at the time of the report |
| **Nationality** | `identity._name_line()` (`.id-trait`) | `identity._titlecase()` | None | `customerInfo.Nationality` | All-capitals values are title-cased, keeping "and", "of" and "the" lower case after the first word ("BOSNIA AND HERZEGOVINA" → "Bosnia and Herzegovina"); anything else is shown as delivered. Left out when blank | |
| **CB Subject ID** (last trait) | `identity._subject_trait()` (`.id-trait`, `.id-subj`) | `ReportContext.cb_subject_id` | None | `customerInfo.CBSubjectId`, else `sectionStatus[].CBSubjectId` | The bureau's subject id, never the warehouse `PKSubjectId`. "CB Subject ID not reported" when neither arrived | The only on-screen link from the report back to the AECB record. Checked by `check_report.py` |
| **Emirates ID** tile (number + expiry) | `identity._document_fact()` → `components.fact()`, `chevron()`, `cell_hist()`, `prov_badges()`; expiry as for Passport. Styled by `.fact`, `.mono`, `.prov-badge`, `.prov-more`, `.chevron`, `.cell-hist`, `.histflag` in `report.css` | `derive/identity.identifiers(ctx, "EmiratesId")` → `dedupe()` | None | `identification[]` rows whose `InfoType` is `EmiratesId` or `EmiratesId(Historical)`: `Info` (the number), `ProviderNO`, `DateOfLastUpdate`, `ExpiryDate` | Shared rules above. Expiry exactly as for Passport. Provider codes and dates in the folded rows are escaped like every other payload value | The archive payload delivers no Emirates ID expiry ("Expiry not reported"); the synthetic one does. Every delivered value is checked by `check_report.py` |
| **Passport** tile (number + expiry) | `identity._document_fact()`; expiry from `identity._expiry_line()` (headline) and `identity._expiry_note()` (folded rows); disagreement mark from `identity._expiry_conflict()`. Styled as above plus `.v-sub`, `.v-sub.expired` (red) | `derive/identity.identifiers(ctx, "Passport")` → `dedupe()` | None | `identification[]` rows whose `InfoType` is `Passport` or `Passport(Historical)`: `Info`, `ProviderNO`, `DateOfLastUpdate`, `ExpiryDate` | Shared rules above. **Expiry** (on the same line, right side): "Expires DD Mon YYYY", or red "Expired DD Mon YYYY" when it is before the **report date**; "Expiry not reported" when blank. Folded rows add "· expires YYYY" / "· expired YYYY" (just "· expiry YYYY" with no report date). The expiry shown is the most recent reporter's (`derive/identity.identifiers()`). When providers send different expiry dates for one document, an amber "!" follows it, with the hover naming each other date and its provider | Every delivered value is checked by `check_report.py` |
| **Phone** tile (current mobiles listed; older mobiles, all landlines and all additional mobiles folded) | `identity._mobile_fact()`, with an "i" hint (`_PROVIDER_HINT`); landline and additional folds from `identity._status_fold()`; flags from `identity._not_mobile_flag()` and `identity._landline_flag()`. Styled by `.mob-list`, `.mob`, `.num`, `.when`, `.histflag` in `report.css` | `derive/identity.contacts()` with "Mobile Number" and "Additional Mobile Number" (both grouped by `mobile_key()`) and "Phone Number" (grouped by `phone_key()`) | None | `contacts[]` rows whose `ContactType` is "Mobile Number", "Phone Number", "Additional Mobile Number", or any of them with "(Historical)": `Contact`, `ProviderNo`, `DateOfLastUpdate` | **Grouping:** digits only; a leading 00, then 971, then one leading 0 are removed. A UAE mobile (9 digits starting with 5), or for landlines also a UAE landline (area code 2/3/4/6/7/9 + 7 digits), groups as 971 + those digits, so the local (0…), 971…, +971… and bare 9-digit spellings of one number group together. Anything else groups only on its exact digits. The most recently reported spelling is shown; the others are in its hover. **Mobiles:** every current mobile is listed in the tile (newest first), each with its most recent reporter and "Mon YYYY"; historical ones fold behind "N prior". "No current mobile" when only historical ones exist; "Mobile not reported" when none arrived but landlines did. A mobile that isn't a UAE mobile gets a grey "not a valid UAE mobile" flag. **Landlines:** all of them fold behind "N landline", each flagged "Current" or "Historical" with its most recent reporter and date. A Phone Number that reads as a UAE mobile stays in the landline list with a grey "mobile number" note; one that is neither gets "not a valid UAE number". **Additional mobiles:** all of them fold behind "N additional", laid out like the landline fold ("Current" or "Historical", most recent reporter and date), with the grey "not a valid UAE mobile" flag where it applies. They never become the headline, so "Mobile not reported" can sit beside an "N additional" chevron. "Not reported" when no mobiles, landlines or additional mobiles arrived | Archive payload: 15 mobile spellings → 1 current + 10 prior (two flagged invalid); its 3 Phone Numbers all read as mobiles and carry the note. Synthetic: 3 genuine landlines. Neither fixture delivers an additional mobile. Every delivered mobile, landline and additional mobile is checked by `check_report.py` |
| **E-mail** tile | `identity._email_fact()`, flag from `identity._not_email_flag()`. Styled by `.fact`, `.mono`, `.v-mail`, plus the shared chevron and badge styles | `derive/identity.contacts(ctx, "E-mail")` → `dedupe()` | None | `contacts[]` rows whose `ContactType` is "E-mail" or "E-mail (Historical)" (the payload's trailing space is stripped on load): `Contact`, `ProviderNo`, `DateOfLastUpdate` | Shared rules above: the newest current address is the headline, and every other address folds behind "N more" / "N prior", each flagged "Also current" or "Historical". Addresses group ignoring letter case and surrounding spaces (`derive/identity.email_key()`); the most recently reported spelling is shown, the others in its hover. A value not shaped like an e-mail (one @ and a dotted domain) is shown as delivered with a grey "not a valid e-mail" flag (`derive/identity.is_email()`). "Not reported" when none arrived; the tile is always present | Synthetic payload: 4 current addresses → 1 headline + "3 more". Every delivered address is checked by `check_report.py` |
| **Latest address** tile | `identity._address_fact()`; each line from `identity._addr_line()`; "i" hint on the label. Styled by `.fact`, `.v-addr` (larger when the tile has the row to itself), `.v-sub` (update date), `.histflag` (address type), plus the shared chevron and badge styles | `derive/identity.addresses()` | None | `addresses[]`: `Address`, `Emirate`, `PoBox`, `PlotNo`, `AddressType`, `ArabicAddress`, `ProviderNo`, `DateOfLastUpdate` | **Which rows count:** a row is ignored only when `Address`, `Emirate`, `PoBox` and `PlotNo` are all blank. **Grouping:** rows with an address group on (address, emirate), with the address compared ignoring case, punctuation and repeated spaces; single spaces still count, so digit runs never fuse, and the same address in two emirates stays two addresses. The most recent spelling is shown, the others in the hover. Rows with no address (location only) group only with the row directly before them in the array when the emirate matches, so a move away and back stays visible. **Fields:** emirate, PO Box, plot, address type and Arabic address each take the most recent reporter's non-blank value. **Latest:** the array has no current/historical marker, so the group with the newest `DateOfLastUpdate` is shown as latest (ties: array order), with "Updated Mon YYYY" on the right; all others fold behind "N prior". **Line:** "ADDRESS — Emirate · PO Box N · Plot N", then the address type as a small grey tag when delivered; "Address not provided — Emirate" for a location-only row; "Not reported" when nothing usable arrived. The hover adds other spellings and the Arabic address (only when it contains real Arabic) | Labelled "Latest", not "Current", because the payload carries no current marker; the hint explains the inference. `AddressType` and `ArabicAddress` are null in both payloads, so neither shows today. Every delivered address, and the "Address not provided" statement, is checked by `check_report.py` |

---

## §02 Score & Bureau History

This section reads `score` (first row only) and `contractsTotalSummary` (first
row only). It is a **half-width card** that shares a row with §03 Worst
statuses; the two stack below 1180 px.

- **Left:** the dial, the section's hero, a 120° arc filling all the width the
  chips leave.
- **Right, against the card's edge:** the FH chip, the AECB chip and the
  vintage bar as one stack, only as wide as the widest tile, then the
  bureau-history line.

The dial is held at 158 px tall. Its width cap is 158.4 px × the viewBox
ratio, which `score.py` passes to the CSS as `--dial-ratio`. **Colour follows
the FH bands throughout:** the dial zones use their configured tone, and both
chips use the delivered FH band's tone.

| Label | Renders | Logic | Config | Payload | Logic explained | Remarks |
|---|---|---|---|---|---|---|
| **Section heading** ("02 Score & Bureau History") | `components.section_card()`, called by `sections/score.render()`; the row wrapper (`.sec-pair`) comes from `sections/__init__.render_all()` | A nested tuple in `SECTIONS` makes the row; position sets the number | `META["title"]` in `sections/score.py` | None | Fixed title. The card always renders: a missing score does not hide the chips or the bureau history | |
| **Score dial** (120° arc with FH zones, tick values, marker) | `score._dial_block()` builds inline SVG (`.sp-dial`, `.sp-svg`, `.sp-mark`, `.sp-ticks`); zone colours from `tokens.py` at `_ZONE_OPACITY` | `scoring.gauge()`; `scoring.scale_geometry()` when there is no score | `bands.json`: `scale` (300–900) and `fh_bands` (each band's `from` and `tone`). Validated at load: numeric scale with min below max, bands in ascending `from` order; a tone outside the seven the dial can draw stops the render | `score.DataIndex` | The arc runs from 300 (left) to 900 (right). Each FH band is a zone from its `from` to the next band's `from`, coloured by its configured tone (U dark red, SPR red, VHR orange-red, HR amber, MR yellow, LR light green, VLR green). All tick values sit inside the arc: 300 and 900 at the feet, and each band boundary at its true angle on an outer ring, or an inner ring when the outer one is full. A value that fits neither is left off so labels never overprint: 653 today, which sits too close to 632 and 647. The marker sits at the score, capped to the ends. **Hover:** the FH band ranges ("U 300–631 · SPR 632–646 · VHR 647–652 · HR 653–684 · MR 685–719 · LR 720–749 · VLR 750–900") and that the chip shows the delivered band | Geometry only: the dial never decides the band |
| **Score figure** (in the dial's centre, captioned "SCORE") | `score._dial_block()` (`.sp-val`, `.sp-k`) | `scoring.score_value()` → `coerce.integer()` | None | `score.DataIndex` | The delivered number when it is a whole number; numeric text counts ("732", "732.0", thousands commas accepted). A non-whole value (e.g. 732.9) or non-numeric value is not a score: the centre reads "Score not reported", and under the dial "Score not returned — *ErrorDescription* (error *ErrorNumber*)" when the bureau sent a reason, or "No score and no error reason delivered" | Checked by `check_report.py` |
| **Band mismatch "!"** (amber, on the dial's shoulder) | `score._mismatch_mark()` (`.attn`, `.sp-attn`) | `scoring.configured_band()` vs `scoring.fh_band()` | `bands.json` `fh_bands` | `score.DataIndex`, `score.FHScoreBand` | Shown only when the configured cut-offs place the score in a different band from the one AECB delivered. **Hover:** "The configured cut-offs place *score* in *band*, but AECB delivered *band*. The delivered band is authoritative — check the cut-offs…" | Not shown on the archive payload (its score is LR under both). The delivered band always wins |
| **FH band chip** (e.g. "LR", or "U · UA", captioned "FH") | `score._band_block()` → `_band_chip()`; conflict mark from `_fh_field_conflict()`. Styled by `.ss-band` with a solid fill | `scoring.fh_band()` | `bands.json` `fh_bands`: code → label and tone | `score.FHScoreBand`, else `score.FHScoreBand1` | The **delivered** band code with its configured label (shown once when the label equals the code, which is every band except U · UA), filled in its configured colour, matching its dial zone (MR's yellow and LR's light green take dark text for legibility). A code the config doesn't know shows as delivered, in neutral grey. When `FHScoreBand` and `FHScoreBand1` both arrive and differ, an amber "!" names both | Red/amber/green is allowed here because a score band is a risk grade. What `FHScoreBand1` means is to be confirmed with AECB |
| **AECB band chip** (e.g. "J · Good", captioned "AECB") | `score._band_block()` → `_band_chip()` | `scoring.aecb_band()` | `bands.json` `aecb_ranges`: letter → label (provisional) | `score.DataRange` (a letter A–L) | The delivered letter, then its configured label. Coloured by the **FH** band's tone (one score, one verdict); neutral when there is no FH band. "Band not reported" when neither band arrived. **Hover:** the label is a provisional mapping pending the AECB scorecard spec | |
| **Vintage bar** (e.g. "Vintage B4") | `score._vintage_bar()`, in the chip stack (`.ss-bands`); hover from `_vintage_tip()`. Styled by `.ss-vint` (brand blue) | `scoring.vintage_band()` | `bands.json` `vintage_bands`: B1 0–11, B2 12–47, B3 48–95, B4 96+ months | Via bureau history below | The bureau-history month count mapped to its configured band. Hidden when the month count can't be worked out. **Hover:** the band ranges | A configured policy mapping; AECB does not deliver a vintage band. Brand blue, because file length is a fact, not a risk grade |
| **Bureau history** (e.g. "96 months since Jul 2016") | `score._history_block()`. Styled by `.ss-hline`, `.ss-hv`, `.ss-hu`, `.ss-hs` | `scoring.history_months()` → `dates.months_between()` | None | `contractsTotalSummary.OldestContractOpenDate` | Whole calendar months from the oldest contract's open date to the **report date**; "since Mon YYYY" is that open date. When the months can't be worked out, the line says why: "Bureau history unknown — no report date (since Mon YYYY)", "…oldest contract date *x* is unreadable", or "Bureau history not reported" when no date arrived. **Hover:** says it is computed, not delivered | Derived, not delivered. `summary.MostOldest_InMonth_Total` is deliberately not read (its meaning is unconfirmed). `score.FraudContractFlag` is not read |

---

## §03 Worst Statuses

This section reads `contractsTotalSummary` and `summary` (first row of each),
plus `contracts` and `contractsHistory` for the derived 36-month panel. It is a
**half-width card** beside §02, with three panels side by side (stacked below
1180 px). FH policy assesses some employer segments over 24 months and some
over 36, so both windows sit together, with the lifetime count.

Status colours come from the bureau's ranks in `config/status_codes.json`,
graded by its `severity` cut-offs (`ReportContext.severity()`):
- rank ≤ 60: red (severe);
- above 60 and below 100: amber (adverse);
- 100 and above: green (normal).

A status the config doesn't know is never coloured.

| Label | Renders | Logic | Config | Payload | Logic explained | Remarks |
|---|---|---|---|---|---|---|
| **Section heading and pill** ("03 Worst Statuses"; pill "Severe status on file" / "Adverse history" / "Partly reported" / "No adverse status on file") | `components.section_card()` via `worst_status.render()`; pill from `worst_status._aside()` (`.tag.bad` red, `.tag.warn` amber, `.tag` grey, `.tag.good` green) | `worst_status._aside()` reads each panel's state | None | Via the three panels | Red if any panel is severe; else amber if any is adverse; else grey "Partly reported" if any panel is missing or can't be graded; green only when all three resolved clean | The pill grades the delivered **statuses** only; delays are shown but not cross-checked |
| **Worst status · last 24 months** (e.g. "Active Payments", tagged `delivered`) | `worst_status._delivered_24m()` → `_panel()`; conflict mark from `_summary_conflict()`. Styled by `.wsx-panel`, `.wsx-win`, `.wsx-worst` (+ `.red` / `.amber` / `.green`), `.prov-mark.delivered` | `worst_status._known_status()`, `_grade()` → `ReportContext.severity()` | `status_codes.json` `codes` (label ↔ code, rank) and `severity` | `contractsTotalSummary.WorstStatus24M` (display text) | Shown **exactly as delivered**. The colour comes from matching the text (or a code) to the status table and grading its rank; an unmatched value stays uncoloured. Text matching goes through `ReportContext.status()`, which ignores hyphens, spacing and case ("Write Off" matches "Write-off"). "Not reported" when blank | `summary.WorstStatus24M` carries the same fact as a letter code (e.g. "U"). It isn't displayed, but when it names a different status, an amber "!" after the headline names both |
| **Max payment delay · 24m** (sub-line, e.g. "0 days") | `worst_status._delay_line()` (`.wsx-sub`) | `coerce.integer()` | None | `contractsTotalSummary.MaxPaymentDelay24M` | A delivered whole number prints as "N days", red when above zero; a delivered 0 prints "0 days" (never late is a fact); any other value prints as delivered, uncoloured; missing → "Not reported" | |
| **Worst status · last 36 months** (e.g. "Write-off", tagged `derived`) | `worst_status._derived_36m()`; hover from `_event_info()`; the `derived` tag from `_tag_derived()` (`.prov-mark.derived`) | `derive/facilities.worst_in_window()` | `status_codes.json` (`codes`, `severity`); the window is `WINDOW_MONTHS` (36) in `facilities.py` | `contractsHistory[]` (`ContractStatus`, `DaysPaymentDelay`, `ReferenceDate`) and `contracts[]` (`WorstStatus` + `WorstStatusDate`, `MaxDaysPaymentDelay` + `MaxDaysPaymentDelayDate`) | AECB sends no 36-month figure, so it's **derived**: every contract counts (closed ones and all roles). Evidence is each monthly row in the 36 months before the report date, plus each contract's dated lifetime worst status / worst delay when that date falls inside the window. The worst **ranked** status is the headline, coloured by rank; statuses the config can't rank make a clean-looking window uncoloured. "Status not reported" when only delays exist; "Not derivable" when nothing falls in the window. **Never milder than the delivered 24 months:** the 36 months include the 24, so when the calculation comes out milder than `contractsTotalSummary.WorstStatus24M` (or finds nothing), the delivered status is shown with an amber "!" whose hover gives the calculated result. **Hover:** the event behind the grade (facility, provider, month, closed or not). **Tag hover:** method and coverage ("N monthly rows across X of Y contracts") | The `derived` tag always shows (RRM instruction) |
| **Max payment delay · 36m** (sub-line) | `worst_status._delay_line_36()` | `facilities.worst_in_window()` | None | As above, plus `contractsTotalSummary.MaxPaymentDelay24M` | The deepest delay found; red when above zero; "0 days" only when a zero was actually reported; "Not reported" when no delay figure exists in the window. Same floor: if `MaxPaymentDelay24M` is deeper, the delivered figure shows with an amber "!" giving the calculated one | |
| **Life-time worst status count · non-services** (e.g. "0", tagged `delivered`) | `worst_status._lifetime_count()` | `coerce.integer()` | None | `summary.Worststatus` | A **count**, not a status. 0 → green; above 0 → amber (a count says how many, never how deep; §07 shows the depth); any other value → as delivered, uncoloured; missing → "Not reported" | Whether this field is a count or a code is to be confirmed with AECB |

---

## §04 Income & Employment

This section reads `employment` and `incomes`. It is a full-width card that
**loads collapsed**, and its header carries the salary line. When opened, it
shows the employers and other income on the left (as delivered) and a chart on
the right (what can be drawn from their dates).

Config is `config/income.json`: currency, placeholder floor and confirmation
window. All three are required; a missing, zero or invalid value stops the
render with an error naming the key. Figures are read through
`coerce.number()`, so "12,500" is 12,500.

**How employers are resolved** (`derive/identity.employers()` then
`derive/income._records()`):

1. **Grouping.** Rows group by employer name with the "(Historical)" suffix
   removed. The match is on the exact name with case ignored, so similar names
   (e.g. "ACME BANK" and "ACME BANK PSC") stay separate by decision.
2. **Field resolution** across a group's rows:
   - latest `DateOfLastUpdate`;
   - **earliest** `DateOfEmployment`;
   - **latest** `DateOfTermination`;
   - a dispute if any provider's readable flag says yes (unreadable flags are
     ignored).
3. **Income.** `GrossAnnualIncome` comes from the strongest row: not-historical
   beats historical, dated beats undated, newer beats older, then array order.
   Figures it outranks are kept behind an amber "!".

| Label | Renders | Logic | Config | Payload | Logic explained | Remarks |
|---|---|---|---|---|---|---|
| **Section heading** ("04 Income & Employment", with a fold toggle) | `components.section_card(collapsible=True, closed=True)` via `income.render()` | Position in `SECTIONS` | `META["title"]` in `sections/income.py` | None | Loads folded; click the heading to open. "No employment reported" (and that AECB doesn't say whether it was requested) when `employment` is empty | |
| **Header salary line** (e.g. "Current salary AED 18,450/yr · EMPLOYER NAME · since Apr 2017") | `income._latest_label()` with `_latest_basis()`, `_latest_value()`, `_tenure_bits()`. Styled by `.inc-latest`, `.inc-latest-k/-v/-s` | `derive/income._current()`, `_latest()` | `income.json` `currency`, `confirmation_window_months` | `employment[]`: `EmploymentName`, `GrossAnnualIncome`, `DateOfEmployment`, `DateOfTermination`, `DateOfLastUpdate`, `ProviderNo`, `FlagOpenDispute` | **Current employer:** the newest start date among jobs not marked historical and with no end date. **Label:** "Current salary" (its own usable figure) or "Current employer" (no usable figure: "No usable figure" / "Salary not reported"; never borrows another employer's figure). With no current employer: "Latest salary" (newest bureau-dated figure), else "Salary on file". **Tail:** employer (30 characters), "since Mon YYYY" / "Mon YYYY to Mon YYYY" / "ended …" / "as at …", plus "last confirmed Mon YYYY" when stale, plus an amber "Open dispute" tag when that employer's record is disputed. **Hover:** employer, providers, and how it was chosen; the figure's own hover says the currency is assumed AED | Visible while the card is folded |
| **Employers list** (one row per employer) | `income._records()` → `_employer()`, `_dates_cell()`, `_income_cell()`, `_conflict_mark()`. Styled by `.rec`, `.emp-name`, `.emp-cur`, `.histflag`, `.emp-prov` | `derive/income._records()`, `_order()`, `_classify_income()`, `_confirm()` | `income.json` `placeholder_floor` (1,200), `confirmation_window_months` (12) | `employment[]` (all fields above, plus `EmploymentType`) | **Order:** newest job first (by start, else end); undated rows last. **Badge:** exactly one "Current"; "Prior" for historical or ended jobs; nothing for an ongoing job that isn't the newest. **Dispute tag:** "Open dispute" / "No dispute" only when a readable flag arrived; an unreadable value counts as not reported and shows no tag. **Dates:** "Since Mon YYYY", "Mon YYYY to Mon YYYY", "From … · end not reported" (historical), "Since … · last confirmed …" (stale: update older than 12 months before the report date, or before the start), "Start not reported · ended …", "Dates not reported"; an end before the start shows both with an amber "!". **Income:** "AED N/yr"; above 0 but below 1,200 greyed with "!" ("not a usable figure"); exactly 0 as "AED 0/yr · reported as zero"; "Income not reported". **Also:** employment type and provider badges. Header chip `delivered`, whose hover says names, dates and figures are as delivered while the Current / Prior badges and "last confirmed" notes are inferred | Every delivered income figure, including outranked ones, is checked by `check_report.py` |
| **Other income** (e.g. "Other · B02 · Aug 2023 · Amount not reported") | `income._other_income()` → `_other_income_line()`, `_other_income_amount()`. Styled by `.other-inc`, `.oi-line` | Same functions | `income.json` `currency` | `incomes[]`: `Source`, `GrossAnnualIncome`, `ProviderNo`, `DateOfLastUpdate` | One line per row that carries a source or an amount: the source (or "Source not reported"), provider · Mon YYYY, then "AED N/yr", "AED 0/yr · reported as zero", or "Amount not reported". Not shown when no row carries either | Every delivered amount is checked by `check_report.py` |
| **Chart** ("Income & employment over time", tagged `delivered` or `derived`) | `income._chart_block()` → `_svg()`, `_grid()`, `_axis()` (`svgtime.axis`), `_lane()`, `_points()`, `_legend()`, `_chart_note()`, `_undated()` | `derive/income.build()` picks the state (`_chart_kind()`) and scales | `income.json` | `employment[]` dates and figures | **States:** "trend" (2+ datable figures, joined), "single" (one marker; "a trend needs two"), "spans" (bars only, with a reason line), "none" ("Nothing can be placed in time"). **Points:** a usable figure placed at its `DateOfLastUpdate` (solid), or at the hire date when that's missing (hollow, and the chip turns `derived`); the y-scale is set by plotted points only. **Bars (one lane per employer with a start):** ended → solid between dates; historical with no end, or stale → fades out ("end not reported" / "not refreshed since"); ongoing → runs to the report date with an arrow; end-before-start → no bar. **Tray "Not on the chart":** figures that aren't drawn, each with why ("not a usable figure" / "no date to place it") | The x-axis runs from the earliest date to the report date. The "AED /yr" unit label's hover says the currency is assumed (`income.json`); the payload carries none |

---

## §05 Cheque & Direct-Debit Returns

This section reads `paymentOrder` only. One row is one returned instrument,
and nothing is aggregated. It also reads `sectionStatus`, to tell "checked and
clean" from "not requested". The `summary` three-month return counters are
deliberately not read (RRM decision).

Config is `config/returns.json`: review window, instrument type labels and
severity colours. `window_months` must be a positive whole number or the
render stops.

Amounts are shown in AED, **assumed** because the payload carries no currency;
the `delivered` chips and marker hovers say so. Amounts are read through
`coerce.number()`.

The left half shows the returns as delivered, grouped by window, then by
instrument. The right half shows the same events on a timeline.

| Label | Renders | Logic | Config | Payload | Logic explained | Remarks |
|---|---|---|---|---|---|---|
| **Section heading and pill** (e.g. "4 returns · last 6m", "4 on file · none in 6m", "Checked · none reported", "Section not requested", "Unverified") | `returns.render()`, pill from `returns._aside()` / `_pill()`; contradiction mark from `_flag_conflict()` | `returns._section_requested()`, `derive/returns.build()` | `returns.json` `window_months` (6) | `paymentOrder[]`, `sectionStatus[].ReportType`, `score.PaymentOrderFlag` | With returns: red "N returns · last 6m" when any fall in the last 6 months before the report date, otherwise amber "N on file · none in 6m" (red "N returns on file" with no report date). With none: green "Checked · none reported" if any `sectionStatus` row's `ReportType` contains "bounced cheque"; amber "Section not requested" if none does; amber "Unverified" if `sectionStatus` is empty. The empty card carries a matching explanation. The green pill's hover names the confirming row (report type, enquiry number, date). **Amber "!"** on the pill when `score.PaymentOrderFlag`, read with the three-state flag rules, contradicts the rows (yes with none delivered, or no with rows); silent when they agree or the flag is unreadable or absent | Reads **every** `sectionStatus` row, unlike the top bar's single winning row (deliberate). `PaymentOrderFlag` is read only for that contradiction |
| **Last 6 months** group (a tile per instrument: "Bounced cheques · N", "Unpaid direct debits · N") | `returns._records()` → `_tiles()`, `_tile()`, `_entry()`. Styled by `.ret-grp`, `.rec`, `.rec-t`, `.rec-item`, `.rec-none` | `derive/returns.build()` (window split), `_kind()` (instrument) | `returns.json` `window_months`, `types` | `paymentOrder[].ReturnDate`, `Type` | Returns dated within the window, newest first. Instrument from `Type`: exact match to the configured labels, else containing "cheque"/"check" or "direct debit"; anything else goes to "Other instruments" with its delivered type shown. An instrument with none in the window still gets a dashed tile ("none in the last 6 months"). Tagged `delivered`. With no report date: one flat "On file" group | For an adverse section, absence in the window is a finding |
| **Return entry** (e.g. "AED 4,200 · 15 Aug 2023 · Multiple · Insufficient Funds · IBAN …nnnn · No. nnnnnn · via C04") | `returns._entry()`, `_amount_cell()`, `_date_cell()`, `_severity_tag()`, `_reason_cell()`, `_collapse_mask()` | `derive/returns.Return` | `returns.json` `severity_tones` (Multiple red, Single amber, Reported neutral; unknown neutral) | `paymentOrder[]`: `Amount`, `ReturnDate`, `Severity`, `FlagOpenDispute`, `Reason`, `BeneficiaryName`, `IBAN`, `Number`, `ProviderNo` | Amount as "AED N" (or "Amount not reported"); date; severity as delivered in its configured colour; "Open dispute" / "No dispute" only when a readable flag arrived. Second line: reason (or "Reason not reported"), beneficiary, IBAN with the asterisk run collapsed to "…" (full value on hover), number, provider badge. Missing beneficiary / IBAN / number are simply left out | Every delivered amount is checked by `check_report.py` |
| **Earlier fold** ("Earlier · N", "Undated · N" or "Earlier & undated · N") | `returns._fold()` | `derive/returns.build()` | `returns.json` `window_months` | As above | Returns before the window (and undated ones), folded; the same tiles inside, but only instruments that have returns | |
| **Timeline** ("Returns over time", tagged `delivered`) | `returns._chart_block()` → `_svg()`, `_window_band()`, `_stem()`, `_event()`, `_legend()` / `_tone_legend()`, `_window_note()`, `_undated()` | `derive/returns.build()` (axis range, `_axis_span()`) | `returns.json` | `paymentOrder[]` | Each dated return is a marker at its `ReturnDate`: "C" (cheque), "D" (direct debit), "?" (other), filled in its severity colour, with the amount beside it. Returns inside the window get a lane each; earlier ones share the bottom lane unless they'd collide. An amber band marks the window only when it holds returns; otherwise a note says none fall in it. The legend lists only the kinds present and, per tone, the delivered severity texts behind it. "Not on the timeline" lists undated returns. "Nothing can be placed in time" when none is dated | The chart height is matched to the "Last 6 months" tiles beside it |

---

## §06 Active Credit Facilities — Overview

This section reads four arrays:
- `contractsFinancialSummary`: figures per category × role;
- `contractsSummary`: the emptiness test and the application-outcome
  counters;
- `contractsTotalSummary`: the header chips and card utilisation;
- `contracts`: whether any facility is still open.

It shows four category cards in a row: **I** Installments, **C** Credit cards,
**N** Non-installments, **S** Services. The roles are **A** main holder, **C**
co-holder and **G** guarantor. `MaxCurrentPaymentDelay` is deliberately not
shown: it contradicts every other delay field in the archive payload (RRM
decision).

| Label | Renders | Logic | Config | Payload | Logic explained | Remarks |
|---|---|---|---|---|---|---|
| **Header chips** ("Total exposure AED 391,020", "Newest facility 09 Oct 2023", amber "Guaranteed AED N", red "Guaranteed overdue AED N") | `facilities._aside()` → `components.tag()` | Same function | None | `contractsTotalSummary`: `TotalExposure`, `NewestContractOpenDate`, `TotalBalanceGuaranteed`, `TotalOverdueGuaranteed` | Each value as delivered. **Total exposure** is always shown ("Total exposure not reported" when missing); its hover explains that it counts full card limits and that the currency is assumed AED. **Newest facility:** the date, or "unreadable date *x*" when it can't be read. The two guarantee chips show only when the delivered value is non-zero (a zero is stated in each card's guarantor block instead) | `TotalExposure` counts each revolving facility's **full credit limit**, not its drawn balance (archive: 331,420 + card limit 59,600 = 391,020), so it won't equal the balances below. By design. A zero delivered as text ("0") still shows a guarantee chip (see Known gaps) |
| **Category card** (code letter + name) | `facilities._card()`. Styled by `.fac`, `.fac-h`, `.fac-cat`, `.fac-name` | `facilities._is_empty()`, `_has_figures()` | None | All four arrays above | "No facilities · Nothing reported in this category" only when there's no open facility, no `TotalNo`, no outcome counter and no non-zero figure for any role. Otherwise the card shows its role blocks | All four category chips are brand blue |
| **Utilisation line** (Credit cards card only, e.g. "Utilisation 57%", tagged `delivered`) | `facilities._utilisation()` (`.fac-util`, `.fac-util-bar`, `.fac-util-fill`) | `coerce.number()` | None | `contractsTotalSummary.CreditUtilizationRate` | The delivered percentage as text. The bar fills green to that percentage below 100; at 100 or more it fills fully in red and the number tells how far over. A delivered value that isn't a number (e.g. "NC") is shown as delivered, with no % and no bar. Hidden only when missing or blank. Also shown in an empty Credit cards card ("No facilities"), because the rate comes from the total-level array, not from any contract | Book-wide for cards, no role split, so it sits above the role blocks. Checked verbatim by `check_report.py`, which also fails a bar drawn for a non-numeric value |
| **Main holder block** (balance headline, then rows) | `facilities._role_block()` → `_headline()`, `_rows()`, `_outcomes()`. Styled by `.fac-block`, `.fac-role`, `.fac-big` (+ `.od`), `.fac-rows`, `.fac-row` | `derive/facilities.financial_summary(ctx, "A")` | None | `contractsFinancialSummary[]` role A: `Balance`, `PaymentAmount`, `CreditLimit`, `OverdueAmount` | **Headline:** `Balance`, in red when there's an overdue amount. **Rows by category:** Installments → Payment amount, Overdue; Cards and Non-installments → Credit limit, Overdue; Services → Overdue only. A non-zero overdue shows in red; a reported 0 prints "0" in ink; missing → "Not reported" | Always shown |
| **Co-holder block** | `facilities._coholder_block()` | `financial_summary(ctx, "C")` | None | `contractsFinancialSummary[]` / `contractsSummary[]` role C | Same layout as main holder, shown **only** when the bureau returned figures or outcome counters for role C | Neither payload has role C rows |
| **Guarantor block** | `facilities._guarantor_block()` | `financial_summary(ctx, "G")` | None | `contractsFinancialSummary[]` role G; `contractsTotalSummary.TotalBalanceGuaranteed`, `TotalOverdueGuaranteed` | Always shown, as one of three things: figures (same layout as main holder); "No exposure reported" tagged `delivered` when the role row is empty and both book-wide guarantee totals are delivered as the number 0; otherwise "Not reported" | The "no exposure" statement rests on the delivered book-wide zeros |
| **Application outcomes** (inside a role block, e.g. "2 declined · 1 rejected") | `facilities._outcomes()` (`.fac-outcomes`) | Same function | None | `contractsSummary[]`: `DeclinedNo`, `RejectedNo`, `NotTakenUpNo` per category × role | Shown only when non-zero. **Hover:** delivered per category and role; individual applications and their phase are in §08 | `TotalNo` / `ActiveNo` / `ClosedNo` are read for the emptiness test only, never displayed |

---

## §07 Credit Facilities — Detail & 36-Month Conduct

This section reads `contracts` joined to `contractsHistory` on `CBContractId`.
History rows 36 or more months before the report date are dropped at the join.
The card markup is fixed in `sections/detail.py`. The rows are drawn in the
browser by `report.js` `heatmap()`, from data prepared in `render/js.py`
`_heatmap()` / `_facility_row()`.

- **Status colours** come from the bureau ranks in `status_codes.json`, graded
  by its `severity` cut-offs: ≤ 60 red, above 60 and below 100 amber, 100 and
  above grey, unknown shown as a ringed "?".
- **Delay colours** come from its `dpd_buckets`: 0 · 1–29 · 30–59 · 60–89 ·
  90+.
- `PaymentBehaviour`, the card-activity fields and the contract `FraudFlag`
  are deliberately not read.

| Label | Renders | Logic | Config | Payload | Logic explained | Remarks |
|---|---|---|---|---|---|---|
| **Section heading and pill** (e.g. "5 Active · 10 Closed") | `detail.render()` | `derive/facilities.is_closed()` | None | `contracts[].ActiveFlag` | Counts contracts by `ActiveFlag` ("Closed" = closed; everything else active). "No contracts reported" when `contracts` is empty | AECB's own words: Active / Closed. Archive payload: "5 Active · 10 Closed" |
| **Blocks** ("Active facilities", "Closed · last 6 months", "Closed · beyond 6 months", "Services — no arrears") | `report.js` `heatmap()` → `blockHtml()`, `groupHtml()`; bucketing in `js._heatmap()`, `_block()` | `js._in_arrears()`, `_closed_recently()` | `bands.json` `closed_window_months` (6; required, validated at load); `status_codes.json` `severity` | `contracts[]`: `ActiveFlag`, `ClosedDate`, `ContractCategory`, `Current_OverdueAmount`, `Current_DaysPaymentDelay`, `Current_ContractStatus` | **Active:** not closed, except services with nothing adverse. **Closed · last 6 months:** `ClosedDate` within 6 months of the report date. **Closed · beyond:** the rest, including closures with no date ("Closed · date not reported"). **Services — no arrears** (folded): open services with no overdue, no current delay and a normal current status (an unrankable status counts as adverse). Within a block, rows group by category (I, C, N, S); empty groups and blocks are left out. Closed blocks load folded | On an active instalment loan, `ClosedDate` is the scheduled maturity, so closure is decided by `ActiveFlag` alone. A zero overdue or delay delivered as text ("0") currently counts as arrears (see Known gaps) |
| **Row label** (e.g. "Staff Loan B08") | `report.js` `rowLabel()`, called by `rowHtml()` (`.hm-rl-t`, `.hm-name`, `.prov-badge`) | `derive/facilities.Facility.label`; `ReportContext.provider()` | `providers.json` (code → name, stub) | `contracts[]`: `ContractType`, `ProviderNo`, `CBContractId`, `ProviderContractNo` | Contract type (else the category name), then the provider code badge, then the provider name only when it differs from the code. **Hover on the name:** "AECB contract *CBContractId* · lender contract no. *ProviderContractNo*" (whichever arrived) | |
| **Row stats and chips** (Limit, OS, Amount, Payment, Tenor, Util, method, Secured, Max DPD, Worst ever, Open dispute, Holder not liable, non-AED currency, Reported n/m, Closed date, Final status, frequency, role, OVER LIMIT, Overdue now) | `report.js` `rowStats()` with `basicStats()`, `worstEverChip()`, `warningChips()`, `coverageChip()`, `closureChips()` / `finalStatusChip()`, `frequencyChip()`, `roleChip()`, `exposureChips()` (`.stat`, `.final-st`, `.hm-warn`, `.freq`, `.role`, `.ovl`, `.closed-on`) | `js._facility_row()`, `_row_flags()`, `_worst_ever()`, `_tenor()`; `Facility.max_dpd`, `final_status`, `possible_months`, `role_code`, `frequency_code` | `status_codes.json` (`codes`, `severity`, `roles`, `role_labels`, `frequency`) | `contracts[]`: `Current_CreditLimit`, `Current_Balance` (hover: as at `Current_ReferenceDate`), `TotalAmount`, `PaymentAmount`, `NoOfInstallments` / `NoOfRemainingInstallments` (tenor "paid / total"), `Current_UtilizationRate`, `MethodOfPayment`, `SecuredContractFlag` / `SecurityType`, `WorstStatus` + date, `MaxDaysPaymentDelay` + date, `MaxOverdueAmount` + date, `FlagOpenDispute`, `HolderIsNotLiable`, `OriginalCurrency`, `ClosedDate`, `PaymentFrequency`, `Role`, `Current_OverdueAmount` | Each item shows **only when delivered**. **Max DPD:** deepest monthly delay in the window (red). **Worst ever:** the contract's dated lifetime worst, only when adverse or unrankable; the hover says it can predate the window. **Amber chips:** open dispute and holder not liable (each only when its flag reads yes under the three-state rules), currency other than AED. **Secured:** when `SecuredContractFlag` reads yes or a `SecurityType` is delivered. **Reported n/m:** months filed ÷ months the facility was open in the window; "thin" when under 6 and incomplete. **Closed:** the date and "Final · *status*" from the closing month's own history row, or "Final · not reported". **Frequency:** matched to its config letter; an unmatched delivered text is shown as delivered. **Role:** shown only when not main holder; a delivered role the config doesn't know shows as delivered in a grey chip (a missing Role still reads as main holder). **OVER LIMIT** above 100% utilisation; **Overdue now** from `Current_OverdueAmount` | Money figures are read through `coerce.number()` (thousands commas accepted) |
| **Status strip** (36 cells, newest month on the left) | `report.js` `statusCell()` (`.scell` `.ss` / `.sa` / `.sn` / `.su`, `.sx`, `.sc`) | `Facility.series()`; `ReportContext.status()` | `status_codes.json` `codes`, `severity` (shipped in the blob as `severeMax` / `normalMin`) | `contractsHistory[]`: `ContractStatus`, `ReferenceDate` | One status code per reported month, coloured by rank; unknown or missing codes show as a ringed "?" (never defaulted to a clean status). Months before opening are blank; months after closure are grey; unreported months are grey with "no status reported" | |
| **Days-past-due strip** | `report.js` `dpdCell()` / `reportedDpdCell()` (`.cell` `.d0`–`.d4`, `.dn`, `.dc`) | Same; delays read with `coerce.truncated()` | `status_codes.json` `dpd_buckets` | `contractsHistory[]`: `DaysPaymentDelay`, `Balance`, `OverdueAmount` | Each reported month coloured by its delay bucket, the day count printed in adverse cells. Before opening, after closure, not reported, and "status but no delay delivered" are grey, each with its own hover (never shown as 0 DPD). **Hover:** month, delay, and that month's own balance and overdue | |
| **Utilisation strip** (cards / overdrafts only) | `report.js` `utilStrip()` (`.hm-ustrip`, `.ucell`) | `Facility.utilisation_series()` | None | `contractsHistory[].UtilizationRate` | Green up to 100%, red above, grey when unreported. Omitted entirely for contracts that never report utilisation | |
| **Month axis, legends and coverage line** | `report.js` `monthAxis()`, `statusLegend()`; `detail.render()` (colour legend, coverage, status-table note) | `Facility.months_reported`, `possible_months` | `status_codes.json` (the note states the configured cut-offs) | As above | Month labels every 6 months from the report date (offsets like "m−6" with no report date). **Status legend:** only the codes that occur in this report, then the full table behind "all status codes ▾". **Coverage:** "N of M facility-months reported (x%), counting only the months each facility was open… absence is not a clean record" | |

---

## §08 Recent Applications

This section reads `applications` and `contractsTotalSummary.Applications90D`.
It shows one chart on a **split time axis**:
- The last 90 days before the report date take 62% of the width.
- Everything older is compressed into the rest.
- Both parts are linear and meet at the 90-day mark, and the note under the
  chart says so.

Positions are computed in `derive/applications.py`. `report.js`
`applicationTimeline()` only places them.

| Label | Renders | Logic | Config | Payload | Logic explained | Remarks |
|---|---|---|---|---|---|---|
| **Section heading and pill** (e.g. "5 in 90 days" tagged `delivered`, plus amber "0 rows in window" on a mismatch) | `applications._aside()`, `_as_count()`; hover from `_mismatch_reason()` | `derive/applications.in_window()`, `in_window_at()` | `bands.json` `applications_90d_red` (4), `applications_90d_amber` (2); required, amber no higher than red | `contractsTotalSummary.Applications90D`; `applications[]` dates | The delivered 90-day count (read as a whole number), graded 4+ red, 2+ amber, else green. The rows are also counted (strictly under 90 days before the report date); if that count differs, an amber "N rows in window" follows. Its hover explains the difference when a recount at `score.DataPullDate` reproduces AECB's figure ("AECB counted at its data pull date…"); otherwise it says the payload doesn't explain it. With no delivered count: an ungraded "N in 90 days" from the rows | Archive: AECB says 5, the rows give 0, because AECB counted at its pull date (Oct 2023) and the report is dated by the enquiry (Aug 2024); the hover says exactly that |
| **Timeline markers** (one per dated application) | `report.js` `timelineEvent()`, called by `applicationTimeline()` (`.tl-event`, `.mk`, `.amt`, `.stem`) | `derive/applications.timeline()`, `applied_on()`, `_glyph()`, `_role_letter()`, `_assign_lane()` | `status_codes.json` `role_labels`, `roles`, `application_phases` | `applications[]`: `LastUpdateDate` (else `DateOfLastUpdate`), `Phase`, `ContractType`, `ProviderNo`, `Role`, `FlagOpenDispute` | **Position:** days before the report date on the split axis. **Fill:** `Phase` is matched by code or description to `application_phases` (B Disbursed, D Declined, J Rejected, N Not taken up, R Requested). Filled = Disbursed, hollow = Requested, dashed = Declined, Rejected, Not taken up or an unconfigured phase. The key names the dashed phases present ("Other phase" for unconfigured text), and the hover shows each marker's phase. **Letter inside:** I / C / S matched from `ContractType` keywords (loan, finance → I; card → C; communication, service → S); none if unmatched. **Label above:** provider code, plus " · C" / " · G" when the role isn't main holder, or " · ?" for a delivered role the config doesn't know (never assumed to be main holder). **Amber ring:** open dispute (flag reads yes). Markers close together stack upward into lanes (at most 4) instead of shifting sideways | |
| **Marker hover** | `derive/applications._info()` | Same | None | `applications[]`: plus `TotalAmount`, `CreditLimit`, `NoOfInstallments`, `CBApplicationId`, `ProviderApplicationNo` | "Date · N days ago · contract type · Provider … · Phase: … · Role (if not main holder; an unrecognised one shown as delivered) · Open dispute / No dispute (only when the flag is readable) · Amount AED … (currency assumed) · Limit sought AED … · N installments · AECB application … · lender application no. …" — each part only when delivered | |
| **Axis, ticks and key** | `report.js` `applicationTimeline()` (`.tl-axis`, `.tl-mo`, `.enq-focus`, `.enq-split`); key from `applications._chart()` (`.enq-key`) | `derive/applications._ticks()`, `_year_ticks()` | `FOCUS_DAYS` (90), `FOCUS_FRACTION` (0.62), `MAX_LANES` (4) in `applications.py` | As above | Ticks: "report", 30d, 60d, 90d inside the focus zone; calendar years (1 Jan) in the compressed zone, dropped when they'd collide. The break and shaded zone are drawn only when older applications exist. **Key:** Disbursed / Requested always; the dashed phases present; "Open dispute" and role letters only when present; the note says the axis is split (or that everything falls inside 90 days) | "No applications reported" when the array is empty; "Applications cannot be placed in time" when no row has a usable date |

---

## Cross-cutting rules

| Rule | Detail |
|---|---|
| Report date | The latest parseable `sectionStatus."Last EnquiryDate"` across all rows (array order breaks ties), else `score.DataPullDate`, else none. It anchors every window on the page. With none, the top bar says *Validity unknown*. Each windowed element then shows its own undated state: no returns-window split, offset heatmap month labels, no application timeline |
| Normalisation | Every string is stripped, and empty strings become null. `ContractCategory` becomes one letter (I, C, N, S). Every expected array exists, and an absent one becomes an empty list. A row that is not an object is dropped and counted. An unknown top-level array is listed. The sidebar reports both. `NaN` / `Infinity` literals are rejected |
| Dates | ISO (`2023-10-26T14:39:13`), long text (`25 July 2016`) and DDMMYY (`311023`) are parsed by `dates.parse_any()`. Two-digit years read as 20xx |
| Scalars | `coerce.number()` for amounts (commas accepted). `coerce.integer()` for counts and the score (whole numbers only). `coerce.truncated()` for day and instalment counts. `coerce.flag()` for flags (three-state; unreadable means not reported) |
| Absence | Where the bureau reported nothing, the screen says *not reported*, never a blank, a zero or green |
| Colour | Red, amber and green mean risk and nothing else. Neutral facts are brand blue or grey. The score band chip is the one exception |
| Unknown vocabulary | Statuses, phases, roles, frequencies, severities and providers the config does not know are shown as delivered and never graded. No `ReportType` vocabulary is hard-coded |
| Providers | Codes (`B01`, `T05`, …) resolve through `providers.json` (a stub). Unknown codes show as the code; `T##` is treated as telecom and `N##` as a non-bank lender |
| Money | Rendered as AED, which is **assumed** (the payload carries no currency). A contract's non-AED `OriginalCurrency` is flagged in §07 |
| Provenance | Bureau figures are tagged `delivered` and computed figures `derived`. Where both exist, the delivered figure wins, and a disagreement shows an amber "!" |
| Escaping | Every payload value is escaped before it reaches markup. The page's data blob is script-safe JSON. The page carries a CSP that runs only its own script |
| Never read | `ArchiveDate`, `MaxCurrentPaymentDelay`, `PaymentBehaviour`, the card-activity fields (`AmountSpent`, `CardUsedFlag`, `MinimumPaymentFlag`, `BilledAmount`), contract `FraudFlag`, `score.FraudContractFlag`, `summary.MostOldest_InMonth_Total`, and the `summary` three-month return counters |

## Status ranks

Ranks come from AECB's published table (`status_codes.json` `codes`). The
bands come from `severity` (`severe_max` 60, `normal_min` 100).

| Rank | Severity | Colour | Codes |
|---|---|---|---|
| ≤ 60 | Severe | Red | D Deceased 10 · L Left country 20 · B Bankrupt 30 · W Write-off 40 · P Court enforcement 45 · X Service disconnected 48 · F Default 50 · S Suspended 50 · N NDDSF 60 |
| 61–99 | Adverse | Amber | G Guarantor paying 65 · T Dewan settlement 70 · C Settlement 80 · A Arrangement 90 · E Extended individual loan 95 |
| ≥ 100 | Normal | Grey / green | U Active Payments · M Prepaid service suspended · O Prepaid service disconnected (all 100) |
| Not in the table | Unknown | Ringed "?", uncoloured | Never graded, never green, never given an invented letter |

## Configuration

| File | Drives | Required keys (a missing or invalid value stops the render) |
|---|---|---|
| `bands.json` | Score scale and FH bands (§02), AECB letter labels (§02), vintage bands (§02), validity window (top bar), closed window (§07), applications pill (§08) | `scale` (numeric min < max); `fh_bands` (code + numeric `from`, ascending; tone one of the seven the dial draws); `validity_days`, `closed_window_months`, `applications_90d_red`, `applications_90d_amber` (whole numbers above zero; amber ≤ red) |
| `status_codes.json` | Status codes, labels and ranks (§03, §07), severity cut-offs, roles (§06–§08), payment frequencies (§07), DPD buckets (§07), application phases (§08) | Every code's `rank` (whole number); `severity.severe_max` < `severity.normal_min` (whole numbers) |
| `income.json` | Currency label, placeholder floor, confirmation window (§04) | `currency` (non-empty), `placeholder_floor` (number above zero), `confirmation_window_months` (whole number above zero) |
| `returns.json` | Instrument types, severity tones, review window (§05) | `window_months` (whole number above zero) |
| `providers.json` | Provider code → name and badge kind (every section that names a provider) | The file must exist |
| `api.json` | Bureau-report API endpoint and timeout (`app.py`) | `base_url`; the file must not carry an `auth` block |
| `macro_context.json` | AI Analysis context register: background facts and the sector vocabulary (live AI panel only) | Optional; `owner` and `review_cadence` are required when `sectors` is present |

## Known gaps

| Gap | Where | Current behaviour |
|---|---|---|
| `providers.json` is a stub | §01, §04, §05, §07, §08 | Provider codes are shown where names should be. Provider class `C` is not configured |
| `MaxCurrentPaymentDelay` contradicts the other delay fields | §06 | Not shown until AECB explains it |
| Severity `Reported` has no business definition | §05 | Renders neutral |
| §03 refinements | §03 | No derived 24-month reconciliation. Guarantor conduct is not flagged separately in the 36-month derivation |
| `YYYYMMDD` dates are not parsed | All date fields | Such a date renders as unreadable or not reported |
| DSR and application context (product, amount, tenor) | Top bar | No payload source |
| Field meanings to confirm with AECB | §02, §03, §05 | `FHScoreBand1`, `summary.Worststatus` (count or code), the `aecb_ranges` labels, and the unit of the `summary` return counters |
