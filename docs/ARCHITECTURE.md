# FH AECB Analyzer — Architecture

This document is the engineering map: the components, how data moves through
them, the security model, and the design rules with the reasons behind them.
Behaviour label by label is in [LowLevelArchitecture.md](LowLevelArchitecture.md).
Product decisions are in [DECISIONS.md](DECISIONS.md). Running the service is
covered in [OPERATIONS.md](OPERATIONS.md). The AI Analysis's model-risk
documentation is [AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md). Code-level
rationale lives in the module docstrings.

---

## 1. Shape of the system

The core is a function from payload to document:

```
render_page(ReportContext, ai_mode=...) -> str      # one standalone HTML document
```

It does not modify its input and keeps no state of its own. Streamlit hosts the
result. The one entry point, `app.py`, does the following in every
environment:

1. Accepts a CB subject id.
2. Fetches the payload from the internal bureau-report API.
3. Validates it and stores the raw bytes in the user's Streamlit session.
4. Archives the response.
5. Renders the page into one component iframe and offers it as a download.

With `AECB_ENV=dev` it can also feed the same function from a payload file
already on disk (the committed fixtures, or the archive), and it shows a
CSS/JS reload button. There is no file uploader. Settings come from the
process environment; on a developer machine `aecb/settings.py` first loads
`~/etc/aecb-analyzer/aecb.env` into it (the shell wins).

Caching exists in two places only: `render/css.py` and `render/js.py` cache
the stylesheet (about 1 MB with fonts) and `report.js`, and a live AI panel
caches analyses (block by block) in session memory.

`aecb/runtime.py` names the environment (`AECB_ENV`: dev, uat or prod) and
the AI panel's state (`AECB_AI_BRIEF`: live, coming_soon or off). Unset or
invalid, the app runs as prod with the panel "coming soon"; dev turns the
panel live and adds the development tools.

### Constraints that drive the design

| Constraint | Consequence |
|---|---|
| **Air-gapped server** | The server has no internet (no PyPI, no CDN). Dependencies install offline from a hash-pinned wheel bundle. The page is self-contained: fonts and the logo are base64-inlined and no URL is referenced, which `check_report.py`, the install smoke test and the CSP enforce. The only outbound connection is the bureau-report API; the API and model clients use the standard library only. An egress route to Core42 when the AI Analysis goes live is the single planned exception. |
| **Python 3.9** | `streamlit==1.50.0` is pinned (the last release for 3.9). Code avoids 3.10+ syntax (`match`, `X \| Y` unions, parenthesised context managers), and `tests/test_python39.py` parses every shipped module with the 3.9 grammar. `from __future__ import annotations` is used throughout. |
| **Downloaded file opened years later** | The CSS floor is roughly Chrome 88: no container queries and no `:has()` (both need Chrome 105). |
| **Untrusted payload** | Every payload string is escaped. The data blob is script-safe JSON. The page carries its own CSP. See [Security model](#8-security-model). |

---

## 2. Repository map

```
app.py                     the entry point (subject id -> API -> report; dev tools when AECB_ENV=dev)
aecb/
├── loader.py              parse + normalise the payload
├── dates.py               the payload's date formats; date arithmetic
├── coerce.py              one set of rules for untyped scalars
├── context.py             ReportContext + config loading and validation
├── api.py, ntlm.py        bureau-report API client; NTLMv2 (stdlib)
├── archive.py             verbatim archive of each API response
├── logsetup.py            logging: stderr + optional rotating file
├── settings.py            loads ~/etc/aecb-analyzer/aecb.env on a developer machine
├── ui.py                  Streamlit hosting pieces for app.py
├── runtime.py             AECB_ENV / AECB_AI_BRIEF: environment and AI panel state
├── feedback.py            thumbs up/down on an analysis -> JSON lines outside the tree
├── derive/                payload interpretation (no HTML)
│   ├── identity.py  scoring.py  income.py  returns.py
│   ├── facilities.py  applications.py
│   └── brief_facts/       AI Analysis fact digest (package) + steps.py (checklist packets)
├── render/                HTML generation (no payload interpretation)
│   ├── page.py            document template, CSP, render_page()
│   ├── shell.py           top bar, spine nav
│   ├── sections/          one module per report section + registry
│   ├── components.py      shared primitives (esc, tags, cards, money)
│   ├── js.py, report.js   data blob + client behaviour and JS-drawn charts
│   ├── css.py, tokens.py, report.css   stylesheet; the only colour source
│   ├── svgtime.py         shared linear time axis (income, returns)
│   ├── branding.py        app name, logo and favicon as data URIs
│   └── analysis.py        the full-width AI Analysis view (blocks, placeholders, copy)
└── brief/                 AI Analysis (see §7)
    ├── __init__.py        orchestration: new_analysis, generate_block, cache key
    ├── prompts/           one module per pass, its schema and EFFORT; PROMPT_VERSION
    ├── blocks/            lens, risk, checklist, memo: run the passes, validate
    ├── hypotheses/        grammar, verify, candidates
    ├── validate.py        the shared output guards
    ├── providers.py       AECB_ENV -> provider
    ├── ollama.py          dev provider (loopback Ollama)
    ├── core42.py          uat/prod provider (placeholder, no network code)
    └── errors.py          BriefUnavailable, the one failure type
config/                    7 JSON files (see README)
assets/fonts/              vendored fonts, inlined as fonts_inline.css
resources/logo.svg         the brand logo, inlined by render/branding.py
deploy/                    build_wheels.sh, make_release.sh, install_offline.sh,
                           aecb-analyzer.service, aecb.env.example
.streamlit/config.toml     Streamlit server settings
ReferenceJSON/             committed fixtures: anonymized archive, synthetic
                           delinquent and patterns payloads
tests/                     pytest suite
scripts/                   developer QA tooling (not deployed): check_report,
                           check_corpus + corpus/, measure/, check_brief,
                           eval_brief, token_budget, fetch_fonts,
                           make_synthetic_payload
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
the derive and render layers and by the AI Analysis digest, so the report
and the digest cannot read one field two ways:

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

  The reason: a silently empty or defaulted config would render a
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
    `T##` read as telecom and `N##` as a non-bank lender.
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
| `brief_facts/` | AI Analysis digest and step packets (see [The AI Analysis](#7-the-ai-analysis-component-not-live-on-uat-or-production)). |

---

## 4. Rendering

### 4.1 Document assembly (`page.py`)

```
<!DOCTYPE html>
<meta http-equiv="Content-Security-Policy" ...>   per-page, with the script's sha256
<style> fonts + :root tokens + report.css </style>
<body class="rail-off[ analysis-on]">
  topbar       shell.topbar(ctx, ai_mode)
  .wrap: spine | .report (sections.render_all)
  section#analysis   analysis.view(ctx, ai_mode)   (unless ai_mode is off)
<script> window.__AECB = {...}; report.js </script>
```

`ai_mode` is `live` (the AI Analysis button and the analysis view, drawing
`ctx.analysis` when the host attached one), `coming_soon` (the same button,
muted, with a "Coming soon" badge; the view says the analysis is being built
and never shows findings) or `off` (neither). On UAT and production `app.py`
renders `coming_soon` by default, and the download then uses `off`, so a
filed copy carries no AI control. The view REPLACES the report while
`body.analysis-on` is set (toggled by the top-bar button in `report.js`, or
on load with `analysis_open=True`, which the host passes while an analysis
exists so a rerun reopens the view); the report is only hidden, so its
section ids stay and the "Verify at §N" links switch back and scroll.
`body.rail-off` is the layout-state class every page carries: `report.css`
computes the fluid scale (`--f`) and the density step on it, and every
measured geometry is calibrated to it. The coming-soon badge is positioned
out of flow, so the button's box is the live button's.

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

- **One axis.** The viewport width changes the grid; the AI Analysis view
  hides the report rather than reflowing it. `body.rail-off` is set on every
  page, and its `.wrap` rule out-ranks the plain `.wrap` rules inside media
  queries, so the 820px query restates it (as the fluid block restates
  `--colw` on both `body` and `body.rail-off`). Folding the class into plain
  selectors is deferred; it needs a geometry-harness run.
- **Fluid scale.** Content sizes are written as
  `calc(BASE + GAIN * var(--f,0px))`. `--f` is computed on `body.rail-off`
  and runs 0→1 as the report column (`100vw - 106px`) goes from 1074px to
  1466px, that is, as the viewport goes from 1180px to 1572px. It is clamped
  at both ends, so a wider window gains width but no further type. The block
  sits behind `@supports` at the end of `report.css` and only adds to the
  base rules (each declaration restates a base value as its BASE term).
  Page chrome (top bar, spine, the analysis view, card vocabulary) takes no
  gain. `--page-max` is `none`, so the page is uncapped; capping it means
  capping `--colw` with it.
- **Size or density, never both.** There is one density breakpoint
  (`min-width:1510px` on `body.rail-off`), and only §01 (grid four-across)
  and §07 (legend four-across) use it. Sections whose column count is set by
  the data (four categories, 36 months, three worst-status windows) get no
  density step.
- **Python constants that mirror CSS.** In `sections/returns.py`,
  `_TILE_BASE`, `_TILE_ENTRY`, `_TILE_GAP` and `_COL_W` mirror rendered box
  sizes at the 1560px design viewport. They must be re-measured with
  `scripts/measure/` after any change to `.rec*` / `.ret-amt` or to the
  `.wrap` geometry. Nothing enforces this automatically.
- **§07 strips.** Three `repeat(36,1fr)` grids stay in register only because
  every cell fills its track, so `.cell` has no `aspect-ratio` (its height is
  explicit). `.hm{min-width}` (1000px) is tied to the label-column width:
  label 320 + row padding 24 + 36 cells of 16px with 2px gaps (646).

### 4.8 Hosting (`ui.py`)

The one entry point, `app.py`, hosts the page through `ui.py`, which
provides:

- page configuration;
- chrome-hiding CSS;
- the sidebar report block: provenance lines, the unknown-array and
  dropped-row warnings, and the download button;
- `analysis_controls()`, the AI Analysis sidebar (only where the panel is
  live; see §7);
- `show_report()`.

The whole report sits in one `components.html` iframe, because the sticky top
bar, the spine and the scrollspy need a single scrolling context. The iframe
is pinned to `100vh` so the page does not get two nested scroll areas.

---

## 5. Bureau-report API client (`api.py`, `ntlm.py`)

- The endpoint (`base_url`, `timeout_seconds`) comes from `config/api.json`.
  A missing or malformed file, or one that carries an `auth` block
  (credentials belong in the environment), raises `ApiError`.
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
user ──subject id──> app.py ──validate (regex)──> api.fetch_report ──> bureau API
                          │                                   │
                          │                  errors ──> aecb.api log (full response)
                          │
                          ├─ context.from_bytes + require_aecb_payload   (reject before storing)
                          ├─ aecb.audit: query subject=... outcome=ok|failed user=... client_ip=...
                          ├─ archive.save_response ──> $AECB_ARCHIVE_DIR/<subject>_<YYYYMMDD_HHMMSS>.json
                          ├─ st.session_state (raw bytes, this session only)
                          └─ render_page(ai_mode) ──> iframe (+ download; no AI control while "coming soon")
```

| Stream | Where | Contents |
|---|---|---|
| Logs (`logsetup.py`) | stderr always (journald under systemd); plus `aecb.log` in `AECB_LOG_DIR`, rotated at 10 MB × 10 backups | `aecb.*` loggers: API error dumps, archive results, render tracebacks, audit lines. Subject ids appear; payload content does not. |
| Audit (`aecb.audit`) | same handlers | One line per query, successful or failed; where the AI panel is live, also one per generated block and per feedback vote, with the generation id. The user name comes from the header named by `AECB_AUDIT_USER_HEADER` (set in production; UAT has no sign-on, so its lines carry no user). |
| Archive (`archive.py`) | `AECB_ARCHIVE_DIR`, outside the app tree | Verbatim response bytes. Folder mode 0700, file mode 0600. Files are claimed with `O_EXCL`, and a same-second collision gets `_1`, `_2`. If the variable is unset or points inside the app tree, archiving is off and the sidebar says so. A failed save is logged and never blocks the report. |

Development samples (`AECB_ENV=dev`) are read from disk and are neither archived nor audited.

---

## 7. The AI Analysis (component, not live on UAT or production)

The AI Analysis is an optional reading of the payload by an LLM in four
blocks: fresh lens, non-obvious risk, checklist replay, and memo and
recommendation. The model, its runtime settings, the output guards, the
evaluation and the pending gpt-oss-120b validation are documented in
[AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md). This section maps the code.

On UAT and production the panel is "coming soon" by default and `app.py`
does not import `aecb.brief`. Only `AECB_AI_BRIEF=live` loads it (a model
change), and the sidebar then offers `ui.analysis_controls`, which generates
one block per rerun and offers the feedback vote. No model service is part
of the server deployment.

| Where | Role |
|---|---|
| `aecb/runtime.py` | `AECB_ENV` and `AECB_AI_BRIEF`: the panel state per environment (dev live; uat and prod "coming soon"; an invalid value gives prod, "coming soon") |
| `aecb/brief/__init__.py` | Orchestration: `new_analysis` (facts, packets, prohibited-field check, generation id), `generate_block`, `next_missing`; the cache key (payload hash, provider, model, prompt version) |
| `aecb/brief/providers.py` | `AECB_ENV` to provider: dev → `ollama.py`; uat and prod → `core42.py` |
| `aecb/brief/ollama.py` | Development provider: Ollama pinned to loopback; a closed model list (`gpt-oss:120b`, the default, and `gpt-oss:20b`) chosen by `AECB_OLLAMA_MODEL`, with a timeout per model; an unlisted value leaves the panel unavailable, never falls back |
| `aecb/brief/core42.py` | UAT and production provider: a placeholder with no network code that refuses every call until Core42 is onboarded |
| `aecb/brief/prompts/` | One module per pass (`hypotheses` = pass H, `lens` = pass W, `risk`, `checklist`, `memo`), each with its schema and reasoning level (`EFFORT`); `PROMPT_VERSION` |
| `aecb/brief/blocks/` | One module per block: runs its passes and validates the result |
| `aecb/brief/hypotheses/` | The closed hypothesis grammar, the Python verifiers and the fallback candidates |
| `aecb/brief/validate.py` | The shared guards: shape, citations, verbatim figures, named entities |
| `aecb/brief/errors.py` | `BriefUnavailable`, the one failure type |
| `aecb/derive/brief_facts/` | The deterministic fact digest (below) and `PROHIBITED_FIELDS` |
| `aecb/render/analysis.py` | Draws the validated blocks into the full-width view. It owns the block order and titles, so rendering a page never imports `aecb.brief` |
| `aecb/ui.py` | `analysis_controls`: the sidebar button, the session cache, one block per rerun, the feedback form |
| `aecb/feedback.py` | One vote per analysis, appended to `$AECB_FEEDBACK_DIR/feedback.jsonl` outside the tree |
| `config/macro_context.json` | The optional context register: dated background entries and the sector vocabulary |

**The provider interface.** A provider is a module with `NAME`,
`DATA_NOTE`, `model()` (read when called, so a settings file loaded after
import applies), `probe()` (`''` when ready, otherwise the reason the sidebar
shows) and `chat(system, user, schema, effort)`, which raises
`BriefUnavailable`. `model()` feeds the cache key, the provenance and the
generation id.

```
derive/brief_facts.build(ctx)      deterministic, numbered fact table (the model never sees raw JSON)
  + brief_facts/steps.build_packets  the ten step packets; their arithmetic facts join the table
  -> brief.new_analysis            prohibited-field check over every text; generation id; blocks pending
  + brief_facts/tables.build         raw monthly tables with contract aliases (pass H's input)
  -> brief.generate_block(name)    per block, in page order (memo needs the checklist):
       lens       pass H: provider.chat over the tables + a structure/behaviour headline
                  index -> typed hypotheses (brief/hypotheses/grammar) -> verified by Python
                  (brief/hypotheses/verify; Python candidates when the model proposed none)
                  -> facts [verified]
                  pass W: provider.chat over the payload lenses, the tripwire and validity
                  step facts and the verified facts -> validate against exactly that set
                  (framing, refuted-only cap); custom hypotheses -> unverified observations
       risk       provider.chat over the risk facts + context register + employment facts +
                  headline index -> validate (basis from cites; inferred capped at watch)
       checklist  provider.chat over the step packets -> validate per step -> tripwire audit -> plain text
       memo       provider.chat over the VALIDATED items of lens + risk + checklist -> re-validated
                  (a driver citing an inferred item is dropped) -> label
  -> render/analysis.py            draws the validated blocks into the full-width view
```

**The digest.** `derive/brief_facts/` has one module per lens:
`structure`, `trajectory`, `inconsistency`, `behavior`, `absence`, the risk
lenses `cycling`, `seasonality`, `cleanup` and `concentration` (sharing
`patterns`), and `background` (the context register), plus `steps` for the
checklist's packets and `tables` for pass H's raw tables. `_common` holds
shared formatting, the free-text sanitiser, report-section names and the
fact accumulator. Each pass reads only its own lenses. `PROHIBITED_FIELDS`
(Nationality, Gender, ResidentFlag) never enter the digest.

**Reasoning levels.** Each pass declares `EFFORT` beside its prompt: `low`
for pass H, pass W and the risk pass; `medium` for the checklist and the
memo. The provider maps it to its own control (Ollama's `think`).

**Failure.** Every failure surfaces as `BriefUnavailable` for its block. It
is logged with its traceback; the block shows "Not generated" and is retried
on the next click; the other blocks and the report always render.

**Outcome, feedback and audit.** The suggested outcome is advisory and
unbounded in code (DECISIONS AI-1); "never Approve on the delinquent
fixture" is asserted by the evaluation, not enforced at runtime. Feedback
(`aecb/feedback.py`) is one vote per analysis, written with the analysis's
generation id, which the `aecb.audit` log also carries per generated block.

**Instruments.** `scripts/check_brief.py` (fast gate), `scripts/eval_brief.py`
(quality harness over the three fixtures) and `scripts/token_budget.py`
(every pass's prompt tokens per fixture, counted by the model server). All
three need the local model; see [AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md)
section 8.

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
| Unexpected input | The subject id must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$` before any request or log line. The app has no uploader in any environment. Non-JSON-object documents, NaN/Infinity literals and non-object rows are rejected or dropped with a count. Responses over 20 MB are refused. |
| Credentials at rest | Only in the environment file (mode 0600): loaded by systemd on a server; on a developer machine `~/etc/aecb-analyzer/aecb.env`, refused if other users can read it or it sits inside the repository. `config/api.json` with credentials is refused. NTLM sends a proof, never the password. |
| Bureau data at rest | Archive outside the app tree with 0700/0600 permissions. Logs never contain payload content. |
| Dev-only surfaces | The sample picker and CSS reload ship in `app.py` but render only with `AECB_ENV=dev`; unset or invalid means prod (test-enforced). On UAT and production the AI panel is "coming soon", `aecb.brief` is not imported and no model is called. |
| Bureau data leaving the host | The only outbound connection is the bureau-report API (`config/api.json`). The Ollama client is pinned to loopback in code, ignores proxy variables and refuses redirects; the Core42 connector has no network code (test-enforced). Neither model client is sent raw payload JSON or the subject id. |
| Authentication | The app has no login of its own. In production it binds to 127.0.0.1:8501 (`deploy/aecb-analyzer.service`) and is reached only through a TLS-terminating, SSO-authenticating reverse proxy ([OPERATIONS.md](OPERATIONS.md#reverse-proxy-production)). UAT is the documented exception: a systemd drop-in serves it directly on 0.0.0.0:8080 with no proxy, no TLS and no SSO, so its audit lines carry no user ([OPERATIONS.md "UAT"](OPERATIONS.md#uat)). |
| Supply chain | `requirements.lock` pins every wheel with sha256. Installation uses `pip --no-index --require-hashes`. See [DEPENDENCY_RISK.md](DEPENDENCY_RISK.md). |

---

## 9. Quality gates

| Gate | What it proves |
|---|---|
| `tests/` (pytest) | Loader, coercion, config validation, API/NTLM against a local NTLM-checking stub, archive permissions, logging, settings, the Streamlit entry point in every environment (AppTest), the security fuzz, CSP enforcement in headless Chrome (`browser`), the AI Analysis's deterministic parts (digest, guards, prohibited fields, grammar, verifiers, routing, the Core42 placeholder), feedback, the corpus harness self-test, and Python 3.9 syntax. |
| `scripts/check_report.py` | Fixture gate. It checks that every tracked delivered value reaches the page, that verbatim figures sit in the exact element meant to carry them (§03 panels, §06 utilisation), that the report date and scope chips match an independent recomputation, and that there are no external URLs. |
| `scripts/check_corpus.py` | The same gate plus recomputed pills and headline figures, no-drop checks, page hygiene, config vocabulary gaps, date shapes, a headless-Chrome pass, a coverage profile and an approved baseline, run over every archived response. |
| `complexipy aecb app.py` | No shipped function above cognitive complexity 15 (`requirements-dev.txt`). |
| `scripts/measure/` | Geometry across 10 widths, containment of changes to the named sections (the hidden analysis view is its own scope), synthetic payload shapes, screenshots. |
| Install smoke test | `deploy/install_offline.sh` renders the synthetic fixture as a server ships it (AI panel "coming soon") and fails on any external reference. |
| `scripts/check_brief.py`, `scripts/eval_brief.py`, `scripts/token_budget.py` | The AI Analysis gates, run against the local model: the fast gate, the quality evaluation and the prompt-token budget ([AI_ANALYSIS_MRM.md](AI_ANALYSIS_MRM.md) section 8). |

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
  The passport expiry sits on the value line; in a report column of about
  1074 to 1260px it wraps to a second line, which is accepted.
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
