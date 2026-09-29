# FH AECB Analyzer — Architecture

This document is the engineering map: the components, how data moves through
them, the security model, and the design rules with the reasons behind them.
Behaviour label by label is in [LowLevelArchitecture.md](LowLevelArchitecture.md).
Product decisions are in [DECISIONS.md](DECISIONS.md). Running the service is
covered in [OPERATIONS.md](OPERATIONS.md). Code-level rationale lives in the
module docstrings.

---

## 1. Shape of the system

The core is a function from payload to document:

```
render_page(ReportContext, ai_panel=...) -> str     # one standalone HTML document
```

It does not modify its input and keeps no state of its own. Streamlit hosts the
result. The production entry point `app_api.py` does the following:

1. Accepts a CB subject id.
2. Fetches the payload from the internal bureau-report API.
3. Validates it and stores the raw bytes in the user's Streamlit session.
4. Archives the response.
5. Renders the page into one component iframe and offers it as a download.

The development harness `app.py` feeds the same function from committed
fixtures or a session-scoped upload.

Caching exists in two places only: `render/css.py` and `render/js.py` cache
the stylesheet (about 1 MB with fonts) and `report.js`, and the development
harness caches AI briefs in session memory.

### Constraints that drive the design

| Constraint | Consequence |
|---|---|
| **Air-gapped server** | The output has no external references. Fonts and the logo are base64-inlined, and no CDN or URL is used. `check_report.py`, the install smoke test and the CSP all enforce this. The API and model clients use the standard library only. |
| **Python 3.9** | `streamlit==1.50.0` is pinned (the last release for 3.9). Code avoids 3.10+ syntax (`match`, `X \| Y` unions, parenthesised context managers), and `tests/test_python39.py` parses every shipped module with the 3.9 grammar. `from __future__ import annotations` is used throughout. |
| **Downloaded file opened years later** | The CSS floor is roughly Chrome 88: no container queries and no `:has()` (both need Chrome 105). |
| **Untrusted payload** | Every payload string is escaped. The data blob is script-safe JSON. The page carries its own CSP. See [Security model](#8-security-model). |

---

## 2. Repository map

```
app_api.py                 production/UAT entry (subject id -> API -> report)
app.py                     development harness (fixtures, upload, AI brief)
aecb/
├── loader.py              parse + normalise the payload
├── dates.py               the payload's date formats; date arithmetic
├── coerce.py              one set of rules for untyped scalars
├── context.py             ReportContext + config loading and validation
├── api.py, ntlm.py        bureau-report API client; NTLMv2 (stdlib)
├── archive.py             verbatim archive of each API response
├── logsetup.py            logging: stderr + optional rotating file
├── ui.py                  Streamlit hosting shared by both entry points
├── derive/                payload interpretation (no HTML)
│   ├── identity.py  scoring.py  income.py  returns.py
│   ├── facilities.py  applications.py
│   └── brief_facts/       AI brief fact digest (package)
├── render/                HTML generation (no payload interpretation)
│   ├── page.py            document template, CSP, render_page()
│   ├── shell.py           top bar, spine nav, brief rail
│   ├── sections/          one module per report section + registry
│   ├── components.py      shared primitives (esc, tags, cards, money)
│   ├── js.py, report.js   data blob + client behaviour and JS-drawn charts
│   ├── css.py, tokens.py, report.css   stylesheet; the only colour source
│   ├── svgtime.py         shared linear time axis (income, returns)
│   ├── branding.py        app name, logo and favicon as data URIs
│   └── brief.py           draws a validated AI brief into the rail
└── brief/                 AI brief pipeline: client, prompt, validate
config/                    7 JSON files (see README)
deploy/                    build_wheels.sh, make_release.sh, install_offline.sh,
                           aecb-analyzer.service, aecb.env.example
.streamlit/config.toml     Streamlit server settings
tests/                     pytest suite
scripts/                   developer QA tooling (not deployed)
```

**Layering rule.** `derive/` never emits HTML, and `render/` never
re-interprets the payload. A decision about the payload belongs in `derive/`
(or `render/js.py`, which assembles derived data for the client), even when
its output is a drawing coordinate.

---

## 3. The data pipeline

```
bytes / file
  └─ loader.normalise()        strip, canonicalise, guarantee arrays
       └─ ReportContext         arrays + validated config + report date + resolvers
            └─ derive/*         what the payload says, as values or None
                 └─ render/sections/*   one card each, via components.section_card
                      └─ render/page.py  shell + sections + CSS + script -> HTML
```

### 3.1 Load and normalise (`loader.py`)

- The document must be a JSON object. `NaN`, `Infinity` and `-Infinity`
  literals are rejected. A UTF-8 byte-order mark is tolerated.
- Every string is stripped recursively, and an empty string becomes `None`.
  Enum values in the payload carry trailing spaces (`"Requested "`), which
  would otherwise break equality checks.
- `ContractCategory` is canonicalised to one letter (`I`/`C`/`N`/`S`).
  `contractsSummary` spells categories out as phrases.
- Every array in `ARRAYS` (17 names) exists after loading, and an absent
  section becomes `[]`. A single object where an array belongs is read as a
  one-row array. A row that is not an object is dropped and counted in
  `_droppedRows`. Top-level arrays the loader does not know are listed in
  `_unknownArrays`. The host sidebar reports both.

### 3.2 Dates (`dates.py`) and scalars (`coerce.py`)

`dates.parse_any()` reads ISO 8601, long text (`25 July 2016`) and DDMMYY
(`311023`), and returns a `date` or `None`. No other module calls `strptime`.
`months_between()` returns `None` for unparseable input, because `0` is
reserved for a real sub-month span.

`coerce.py` is the single reader for untyped payload scalars. It is used by
the derive and render layers and by the brief digest, so the report and the
digest cannot read one field two ways:

| Function | Rule |
|---|---|
| `number()` | A finite float from an int, a float or numeric text. Thousands commas are accepted (`"12,500"`). Booleans, NaN and infinities give `None`. |
| `integer()` | `number()` when it is a whole number, else `None`. Used for counts and the score, so `732.9` is not a score. |
| `truncated()` | `number()` truncated toward zero. Used for day and instalment counts. |
| `flag()` | Three-state. `true`/`1`/`Y`/`yes`/`T` (text, any case) → `True`; `false`/`0`/`N`/`no`/`F` → `False`; any other value or null → `None` ("not reported"). An unreadable flag is never read as `False`. |

### 3.3 `ReportContext` (`context.py`)

`ReportContext` is the only argument a section renderer receives. It carries:

- **The arrays**: `rows(name)`, plus `summary`, `customer`, `score` and
  `totals` for the single-row arrays.
- **Five validated configs**: providers, status_codes, bands, income and
  returns. A missing file raises. The following also raise with a message
  naming the key:
  - a status code without an integer `rank`;
  - `severity` cut-offs (`severe_max` < `normal_min`) that are missing or
    not whole numbers;
  - a `bands.json` scale or `fh_bands` that is not numeric and ascending;
  - a policy number that is missing, zero, negative or of the wrong type
    (`validity_days`, `closed_window_months`, `applications_90d_red` and
    `_amber` with amber ≤ red, `placeholder_floor`,
    `confirmation_window_months`, `window_months`);
  - an empty `currency`.

  The reason: a silently empty or defaulted config once rendered a
  plausible report with its policy gone.
- **Resolvers**:
  - `status(value)` accepts a letter code or display text and returns
    `{code, label, rank}`. An unknown status returns code `?` and rank
    `None`, never an invented letter or the clean rank.
  - `severity(rank)` returns `severe`, `adverse`, `normal` or `unknown`,
    using the configured cut-offs. Every section and the heatmap blob grade
    through it.
  - `phase(value)` accepts a code or a description.
  - `provider(code)` returns the code itself for unknown providers, with
    `T##` read as telecom.
- **Identifiers**:
  - `cb_subject_id` comes from `customerInfo`, then from `sectionStatus`.
  - `subject_id` is used for titles and file names, and falls back to
    `PKSubjectId`, then to `"unknown"`.
- **`unknown_arrays` and `dropped_rows`**, from the loader.

`require_aecb_payload()` rejects well-formed JSON that is not a bureau report.
It requires at least one row in `customerInfo`, `summary` or `score`.

**The report date** (`enquiry_anchor()` / `report_date`) is the most important
derived value. Every window on the page ages it: validity, the 36-month
conduct grid, the 90-day application window, the 6-month returns and closure
windows, age and document-expiry checks, and the right edge of both SVG
timelines.

```
latest parseable sectionStatus "Last EnquiryDate" across all rows (array order breaks ties)
  -> score.DataPullDate   (fallback only)
  -> None                 (top bar: "Validity unknown"; each windowed section shows its own undated state)
```

No `ReportType` vocabulary is hard-coded. The winning row also supplies the
top-bar scope chips. See [DECISIONS.md](DECISIONS.md) for the accepted
consequence on stale archive payloads.

### 3.4 Interpretation (`derive/`)

The contract, from `derive/__init__.py`: nothing in `derive/` invents a value.
Every function returns something delivered, something arithmetically derived
from delivered values, or `None`, and `None` means "not reported".

| Module | Responsibility |
|---|---|
| `identity.py` | Collapses the one-row-per-provider repeats by value. Splits the `(Historical)` suffix and decides current/historical per provider. Groups mobile numbers across prefix spellings and e-mails across case. Applies the address grouping rules. Guards Arabic names against encoding loss. |
| `scoring.py` | Score value, FH/AECB band lookup (the delivered band is authoritative), dial geometry as true proportions of the scale, vintage, validity against today. |
| `income.py` | Employer dedupe and per-field resolution. Picks the current employer. Classifies figures as placeholder or usable. Applies the confirmation window. Chooses the chart state (`trend`/`single`/`spans`/`none`). |
| `returns.py` | Turns `paymentOrder` rows into return events, splits them at the review window and sets the axis span. It does not read the `summary` return counters. |
| `facilities.py` | Joins `contracts` to `contractsHistory` by months-before-report-date. Rows at month 36 or later are dropped at the join. `series()` yields `None` for unreported months, and `final_status` reads the closing month's own row. `worst_in_window()` computes the derived 36-month worst status. |
| `applications.py` | Split-axis positions (the last 90 days take 62% of the width), a strict `< 90` day window, and lane stacking capped at 4. |
| `brief_facts/` | AI brief digest (see [The AI brief](#7-the-ai-brief-component-not-deployed-on-uat)). |

---

## 4. Rendering

### 4.1 Document assembly (`page.py`)

```
<!DOCTYPE html>
<meta http-equiv="Content-Security-Policy" ...>   per-page, with the script's sha256
<style> fonts + :root tokens + report.css </style>
<body class="rail-off">
  topbar       shell.topbar(ctx, ai_panel)
  .wrap: spine | .report (sections.render_all) | rail (only when ai_panel)
<script> window.__AECB = {...}; report.js </script>
```

With `ai_panel=False` (the production entry), the document contains neither
the AI Analysis button nor the brief rail. The rail loads closed
(`body.rail-off`) when it is present, so the wide layout is the default, and
anything calibrated to a column width is calibrated to that state.

### 4.2 Section registry (`sections/__init__.py`)

`SECTIONS` fixes both the order and the displayed numbers. A nested tuple is a
row of half-width cards (`.sec-pair`). Module files carry names, not numbers,
so a filename cannot drift from its position. Anything that numbers sections
walks `flat_sections()`. The spine nav is derived from the same list.

| No. | Module | Title |
|---|---|---|
| 01 | `identity.py` | Identity & Demographics |
| 02 | `score.py` | Score & Bureau History (half-width, paired with 03) |
| 03 | `worst_status.py` | Worst Statuses (half-width) |
| 04 | `income.py` | Income & Employment (loads collapsed) |
| 05 | `returns.py` | Cheque & Direct-Debit Returns |
| 06 | `facilities.py` | Active Credit Facilities — Overview |
| 07 | `detail.py` | Credit Facilities — Detail & 36-Month Conduct |
| 08 | `applications.py` | Recent Applications |

Report validity is not a section. It lives in the top bar because it
qualifies every section.

### 4.3 Shared primitives (`components.py`)

The section-card markup exists only here. Also in this module:

- `esc()` / `attr()`;
- tags, hints and provider badges;
- `aed()` / `format_number()`, which read through `coerce.number`;
- `delivered_mark()` and `dispute_tag()`, each defined once;
- `empty_state()`, which takes a message and a detail so a caller can tell
  "nothing to report" from "section not returned".

### 4.4 Two charting strategies

| Drawn where | Used by | Why |
|---|---|---|
| Inline SVG built in Python | §04 income, §05 returns | Whether a timeline can be drawn at all depends on which dates the payload carries, so the drawing sits beside that decision. They share `svgtime.py` so the two axes cannot drift. |
| JavaScript from `window.__AECB` | §07 heatmap, §08 applications | These charts are large repeated DOM with folds. Python still makes every payload decision (bucketing, positions) and ships the result. `report.js` contains no figures. |

§08 does not use `svgtime.py`: its axis is split (non-linear) by design.

### 4.5 The client blob (`js.py`)

`build_data(ctx)` ships the following:

- `tokens`: exactly the three colours `report.js` reads.
- `reportDate`.
- `heatmap`: the four pre-bucketed blocks, and the status, role, frequency
  and DPD tables.
- `applications`: omitted when nothing can be dated.

Heatmap rows carry only the months the bureau reported, plus:

- `noDpd`: months whose status arrived without a delay figure. These paint as
  not reported, never as 0 DPD.
- `bal` / `od`: each month's own money figures.
- Row flags (`dispute`, `notLiable`, `secured`, `currency`, `worstEver`,
  `asAt`), included only when delivered.

`report.js` returns early when a key is absent rather than inventing a series.
The blob is serialised with `json_for_script()`, described in [Security model](#8-security-model).

### 4.6 Styling (`tokens.py`, `css.py`, `report.css`)

`tokens.py` is the only place a colour is defined. `report.css` uses
`var(--*)` throughout. SVG built in Python reads colours through
`tokens.token()`, which raises on an unknown name.

The palette:

- One brand colour, Finance House blue `#00426A`, with four derived shades.
  There is no teal token.
- Red, amber and green each have solid, wash, hairline and ink variants.
- A 7-step DPD ramp.
- A 5-hue categorical set for contract categories, which carries no ordering.

Red, amber and green mean risk and nothing else. Residency and vintage render
in brand blue. The score band chip is the sanctioned exception: a score band
is a risk grade.

### 4.7 Layout

- **Two axes.** Both the viewport width and the brief-rail state change the
  grid, and every responsive rule must hold in all four combinations.
  `body.rail-off` out-ranks plain `.wrap` rules inside media queries, so those
  rules must be restated there.
- **Fluid scale.** Content sizes are written as
  `calc(BASE + GAIN * var(--f,0px))`, where `--f` is a 0→1 progress value
  over the width the rail gives back (1074→1466px of column). `--f` is pinned
  to 0 on `body`, so the rail-open state is exact by construction. The block
  sits behind `@supports` at the end of `report.css` and only adds to the
  base rules. Page chrome (top bar, spine, rail, card vocabulary) is excluded.
  `--page-max` is `none`, so the page is uncapped.
- **Size or density, never both.** There is one density breakpoint
  (`min-width:1510px` with `rail-off`), and only §01 (grid four-across) and
  §07 (legend four-across) use it. Sections whose column count is set by the
  data (four categories, 36 months, three worst-status windows) get no
  density step.
- **Python constants that mirror CSS.** In `sections/returns.py`,
  `_TILE_BASE`, `_TILE_ENTRY`, `_TILE_GAP` and `_COL_W` mirror rendered box
  sizes in the rail-closed state at 1560px. They must be re-measured with
  `scripts/measure/` after any change to `.rec*` / `.ret-amt`, or to the
  default rail state. Nothing enforces this automatically.
- **§07 strips.** Three `repeat(36,1fr)` grids stay in register only because
  every cell fills its track. Do not reintroduce `aspect-ratio` on `.cell`.
  `.hm{min-width}` is tied to the label-column width.

### 4.8 Hosting (`ui.py`)

Both entry points host the page through `ui.py`, which provides:

- page configuration;
- chrome-hiding CSS;
- the sidebar report block: provenance lines, the unknown-array and
  dropped-row warnings, and the download button;
- `show_report()`.

The whole report sits in one `components.html` iframe, because the sticky top
bar, the spine and the scrollspy need a single scrolling context. The iframe
is pinned to `100vh` so the page does not get two nested scroll areas.

---

## 5. Bureau-report API client (`api.py`, `ntlm.py`)

- The endpoint (`base_url`, `timeout_seconds`) comes from `config/api.json`.
  A missing or malformed file, or one that still carries an `auth` block,
  raises `ApiError`.
- Credentials come only from the process environment (`AECB_API_USERNAME`,
  optional `AECB_API_DOMAIN`, `AECB_API_PASSWORD`).
- The request is `POST {"cbSubjectId": "<id>"}` over `http.client`. NTLMv2
  authenticates the connection rather than the request, so both handshake
  legs run on one socket. `ntlm.py` implements MS-NLMP NTLMv2 (no LM or v1)
  with a pure-Python MD4 fallback. It is tested against the published vectors
  (`python -m aecb.ntlm`, `tests/test_ntlm.py`).
- Responses over 20 MB are refused.
- Every failure becomes an `ApiError` with a user-safe message: status and a
  hint, no internal address, body or traceback. The full error response goes
  to the `aecb.api` logger: status, headers and up to 16,000 characters of
  the body. Successful payloads are never logged.

---

## 6. Data flow: archive, logs, audit

```
user ──subject id──> app_api.py ──validate (regex)──> api.fetch_report ──> bureau API
                          │                                   │
                          │                  errors ──> aecb.api log (full response)
                          │
                          ├─ context.from_bytes + require_aecb_payload   (reject before storing)
                          ├─ aecb.audit: query subject=... outcome=ok|failed user=... client_ip=...
                          ├─ archive.save_response ──> $AECB_ARCHIVE_DIR/<subject>_<YYYYMMDD_HHMMSS>.json
                          ├─ st.session_state (raw bytes, this session only)
                          └─ render_page(ai_panel=False) ──> iframe + download
```

| Stream | Where | Contents |
|---|---|---|
| Logs (`logsetup.py`) | stderr always (journald under systemd); plus `aecb.log` in `AECB_LOG_DIR`, rotated at 10 MB × 10 backups | `aecb.*` loggers: API error dumps, archive results, render tracebacks, audit lines. Subject ids appear; payload content does not. |
| Audit (`aecb.audit`) | same handlers | One line per query, successful or failed. The user name comes from the header named by `AECB_AUDIT_USER_HEADER`. |
| Archive (`archive.py`) | `AECB_ARCHIVE_DIR`, outside the app tree | Verbatim response bytes. Folder mode 0700, file mode 0600. Files are claimed with `O_EXCL`, and a same-second collision gets `_1`, `_2`. If the variable is unset or points inside the app tree, archiving is off and the sidebar says so. A failed save is logged and never blocks the report. |

`app.py` writes nothing to disk. Uploads live only in the uploading session.

---

## 7. The AI brief (component, not deployed on UAT)

The brief is an optional second reading of the payload by a local LLM,
available only in the development harness `app.py`. `app_api.py` never imports
`aecb.brief` and renders with `ai_panel=False`. No model service is part of
the UAT deployment. Model-risk documentation:
[AI_BRIEF_MRM.md](AI_BRIEF_MRM.md).

```
derive/brief_facts.build(ctx)   deterministic, numbered fact table (the model never sees raw JSON)
  -> brief._prohibited_content  runtime policy check; a breach refuses the brief
  -> brief.client.chat          one schema-constrained pass, Ollama on 127.0.0.1:11434
  -> brief.validate             shape, citations, verbatim figures, named entities; failures dropped
  -> optional synthesis pass    over validated findings only, re-validated
  -> render/brief.py            draws the validated dict into the rail
```

`derive/brief_facts/` has one module per lens: `structure`, `trajectory`,
`inconsistency`, `behavior`, `absence` and `background` (the optional
`config/macro_context.json`). `_common` holds shared formatting, the
free-text sanitiser, report-section names and the fact accumulator.
`PROHIBITED_FIELDS` (Nationality, Gender, ResidentFlag) never enter the
digest. Every failure surfaces as `BriefUnavailable`, and the report always
renders without the brief.

---

## 8. Security model

The expected static-analysis findings and their disposition are in
[SECURITY_REVIEW.md](SECURITY_REVIEW.md).

| Threat | Control |
|---|---|
| Payload text becoming markup (CWE-79) | Every payload string passes through `components.esc()` / `attr()` in Python or `esc()` in `report.js`. That includes provider codes in the identity fold rows, the page `<title>` and the favicon. `tests/test_security.py` appends a markup marker to every scalar of a payload and asserts that no marker survives as markup. |
| Payload text breaking out of the inline script | `js.json_for_script()` writes `<`, `>`, `&`, U+2028 and U+2029 as JSON `\u` escapes. A `</script>` or `<!--` sequence inside a value cannot end or alter the script element. |
| Injected script running | Each page carries a CSP: `default-src 'none'; script-src 'sha256-<hash of the one inline script>'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'`. Any other script, including one injected through data, does not run. Nothing is fetched. The policy travels with the downloaded file. |
| Leaking internals (CWE-209) | Streamlit `showErrorDetails = "none"`. Render and API failures log a traceback server-side and show a generic message. `ApiError` messages carry no address, body or traceback. |
| Unexpected input | The subject id must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$` before any request or log line. The production entry has no uploader. Non-JSON-object documents, NaN/Infinity literals and non-object rows are rejected or dropped with a count. Responses over 20 MB are refused. |
| Credentials at rest | Only in the environment file (mode 0600) loaded by systemd. `config/api.json` with credentials is refused. NTLM sends a proof, never the password. |
| Bureau data at rest | Archive outside the app tree with 0700/0600 permissions. Logs never contain payload content. |
| Dev-only surfaces | `app.py` (uploader, CSS reload, AI brief) is excluded from the release. The production page has no AI panel. |
| Authentication | The app has no login of its own. It binds to 127.0.0.1 and must sit behind a TLS-terminating, SSO-authenticating reverse proxy ([OPERATIONS.md](OPERATIONS.md)). |
| Supply chain | `requirements.lock` pins every wheel with sha256. Installation uses `pip --no-index --require-hashes`. See [DEPENDENCY_RISK.md](DEPENDENCY_RISK.md). |

---

## 9. Quality gates

| Gate | What it proves |
|---|---|
| `tests/` (pytest) | Loader, coercion, config validation, API/NTLM against a local NTLM-checking stub, archive permissions, logging, both Streamlit entry points (AppTest), the security fuzz, CSP enforcement in headless Chrome (`browser`), brief guards and policy, the corpus harness self-test, and Python 3.9 syntax. |
| `scripts/check_report.py` | Fixture gate. It checks that every tracked delivered value reaches the page, that verbatim figures sit in the exact element meant to carry them (§03 panels, §06 utilisation), that the report date and scope chips match an independent recomputation, and that there are no external URLs. |
| `scripts/check_corpus.py` | The same gate plus recomputed pills and headline figures, no-drop checks, page hygiene, config vocabulary gaps, date shapes, a headless-Chrome pass, a coverage profile and an approved baseline, run over every archived response. |
| `scripts/measure/` | Geometry across 10 widths × both rail states, containment of changes to the named sections, synthetic payload shapes, screenshots. |
| Install smoke test | `deploy/install_offline.sh` renders the synthetic fixture with `ai_panel=False` and fails on any external reference. |

---

## 10. Extending it

- **Add a section:** create `sections/<name>.py` with `META` and
  `render(ctx, meta)`, and place it in `SECTIONS`. The number, anchor and spine
  entry follow. Add its class family to `scripts/measure/watch.py`.
- **Add a chart:** if drawability depends on which payload fields exist, build
  inline SVG in the section (and share `svgtime.axis()` for a linear calendar
  axis). If it is large repeated DOM, compute everything in `js.py`, add a
  blob key (omitted when there is no data) and draw it in `report.js`.
- **Add a data source:** put the interpretation in `derive/`, reading scalars
  through `coerce`. Expose it on `ReportContext` if several sections need it.
- **Add config:** add a JSON file with a `_comment`, loaded and validated in
  `ReportContext.__init__`. A policy value without a safe default must be
  validated there.
- **Change a colour:** edit `tokens.py` only.

---

## 11. Section design notes

These notes are the technical rationale that is not visible in the code
layout. Product rules are in [DECISIONS.md](DECISIONS.md).

- **§01 Identity.** A six-track grid with a two-row split. At the density
  step it re-maps onto twelve tracks (span 2k of 12 equals span k of 6, so no
  edge moves). The breakpoint 1510px is where a quarter-width tile reaches
  the tuned 334px. Python emits `v-wide` (the address always takes the row)
  and `r2-N` markers because CSS cannot ask about row shape without `:has()`.
  Watch the specificity: `.r2-2 > .fact.c3` out-ranks
  `.id-grid > .fact.v-wide`, so the narrower rule carries `:not(.v-wide)`.
  The passport expiry sits on the value line; between about 1181 and 1370px
  with the rail open it wraps to a second line, which is accepted.
- **§02 Score.** The dial is a 120° arc in inline SVG. A 120° sweep is about
  2.8:1 against a semicircle's 2:1, so the fixed 158px height buys a wider,
  larger-radius dial. The viewBox ratio reaches CSS as `--dial-ratio`. All
  tick labels sit inside the arc, and one that fits neither ring is dropped.
  `_FILL` maps all seven configured band tones, and a tone outside it fails
  the render.
- **§03 Worst statuses.** `.wsx` is `repeat(3,1fr)` with no density step.
  Each figure group is centred with `margin:auto 0` so a short status does
  not float above empty space in a stretched panel.
- **§04 Income / §05 Returns.** Both use the two-half grammar (`.inc-split`):
  delivered records on the left, what can be drawn on the right. The left
  half never depends on the right. The returns chart height mirrors the
  "Last 6 months" tile block and is driven by the in-window count only, so
  opening the "Earlier" fold does not resize it. Returns in the window take
  one lane each; earlier ones pack into the bottom lane.
- **§06 Facilities.** `.fac-grid` has four columns, one per AECB category.
  The utilisation bar is modelled on the top bar's `.tv-meter` (a fill), not
  on a zoned gauge. The role labels sit on the figure line and wrap back
  under it at narrow widths.
- **§07 Detail heatmap.** The markup is static, and rows are built by
  `report.js` from pre-bucketed blocks. Two heading levels (block and
  category group) must stay visually distinct. The label column is 320px so
  the stat line fits on one row.
- **§08 Applications.** Positions are percentages computed in Python, not an
  SVG viewBox, so the 8.5px axis labels do not scale with the chart. The
  distortion is drawn: a wash on the focus window, a dashed rule at the
  split, and ticks in days inside the window and in years outside it.
