# FH AECB Analyzer

FH AECB Analyzer renders an Al Etihad Credit Bureau (AECB) credit-report payload
(JSON) as one self-contained HTML underwriting screen. Streamlit hosts the page.
Its purpose is to shorten the time an underwriter needs to read one customer's
bureau report.

- **Read-only viewer.** The app does not score, approve, decline or write
  anything back to any system. It shows what the bureau delivered, arranged so
  it can be read.
- **Delivered vs derived.** Every figure is either delivered by AECB (shown
  verbatim) or arithmetically derived from delivered values. Figures are tagged
  `delivered` or `derived`. No value is fabricated.
- **Absence never renders as good conduct.** Where the payload carries nothing,
  the page says *not reported*. It never shows a blank, a zero or a green tone.
  "Reported as zero" and "not reported" mean opposite things on a credit screen.

## Running it

There is one entry point, `app.py`, and one command, everywhere:

```bash
streamlit run app.py
```

It takes a CB subject id, fetches the payload from the internal bureau-report
API (`config/api.json`), validates it and renders the report. Each query is
audit-logged. What else it offers depends on `AECB_ENV`:

| `AECB_ENV` | Where | Adds |
|---|---|---|
| `uat`, `prod` (unset means `prod`) | Servers | Nothing. The AI Analysis button shows "Coming soon" until Core42 is onboarded. |
| `dev` | Developer machines | A sample picker (the fixtures in `ReferenceJSON/` and any archived responses), a CSS/JS reload button, and the AI Analysis from the local Ollama model. |

There is no file uploader in any environment.

## Requirements

- **Server (UAT and production):** RHEL Linux x86_64 with CPython **3.9**
  (any 3.9.x except **3.9.7**, which streamlit 1.50.0 excludes). The server
  is air-gapped: no internet (no PyPI, no CDN), and its only outbound
  connection is the internal bureau-report API. Dependencies are therefore
  installed offline from a hash-pinned wheel bundle, and the report page is
  self-contained. The server stays on Python 3.9 by decision; the known
  vulnerabilities that follow are assessed in
  [docs/DEPENDENCY_RISK.md](docs/DEPENDENCY_RISK.md).
- **Runtime dependency:** `streamlit==1.50.0`, the last release that supports
  Python 3.9. The full tree is pinned with sha256 hashes in `requirements.lock`.
- **Development:** a newer Python works locally, but the code and tests must
  pass on Python 3.9; `tests/test_python39.py` parses every shipped module
  with the 3.9 grammar.
- **AI Analysis (development only):** [Ollama](https://ollama.com) 0.34.2
  with `gpt-oss:120b` (the target model; about 65 GB, needs at least 96 GB of
  unified memory) or `gpt-oss:20b` (about 13 GB). Servers run no model: the
  AI Analysis there shows "Coming soon" until Core42 is onboarded, and the
  server stays air-gapped until then
  ([docs/AI_ANALYSIS_MRM.md](docs/AI_ANALYSIS_MRM.md)).

## Setting up a development machine

Once per machine, create the settings file from the template, outside the
repository so it can never be committed:

```bash
mkdir -p ~/etc/aecb-analyzer
install -m 0600 deploy/aecb.env.example ~/etc/aecb-analyzer/aecb.env
# then edit it (see below)
```

Then install and run:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m streamlit run app.py
```

The two development machines differ only in the model:

| Machine | Model | `~/etc/aecb-analyzer/aecb.env` |
|---|---|---|
| Development Mac (M4 Pro, 24 GB) | `gpt-oss:20b` (`ollama pull gpt-oss:20b`) | `AECB_ENV=dev` and `AECB_OLLAMA_MODEL=gpt-oss:20b` |
| Org laptop (M5 Max, 128 GB) | `gpt-oss:120b`, the default (`ollama pull gpt-oss:120b`) | `AECB_ENV=dev` only |

Add the folders as full paths under your home (`AECB_ARCHIVE_DIR`,
`AECB_LOG_DIR`, `AECB_FEEDBACK_DIR`) and, if the machine can reach the
bureau API, the service account and `AECB_TEST_SUBJECT_ID`. After a first
analysis, `ollama ps` should show the model 100% on the GPU. The sidebar
names the reason when the model is missing or the setting is not one of the
two reviewed models.

The org laptop receives the code as a GitHub ZIP (not a git clone). The final
validation on gpt-oss-120b runs there, following
[docs/AI_ANALYSIS_MRM.md](docs/AI_ANALYSIS_MRM.md) section 9.

On a developer machine the app reads `~/etc/aecb-analyzer/aecb.env` itself at
start-up (`aecb/settings.py`); on a server, systemd loads
`/etc/aecb-analyzer/aecb.env`. The file must be private (mode 0600) and
outside the repository, or it is not used and the start screen says why. A
variable already set in your shell overrides the file; restart the app after
editing it. The live-API tests, `scripts/check_corpus.py` and the AI Analysis
scripts read the same file.

## Tests and QA tools

```bash
.venv/bin/python -m pytest                          # full suite (tests/)
.venv/bin/python -m pytest --cov --cov-report=xml   # plus coverage.xml for Sonar
```

Tests marked `browser` need Chrome or Chromium. Tests marked `model` need a
local Ollama. Tests marked `live_api` call the real bureau-report API and need
the credentials and `AECB_TEST_SUBJECT_ID` in your settings file (see above).
Run them with `.venv/bin/python -m pytest -m live_api`. Each group is skipped
when what it needs is missing. `.venv/bin/complexipy aecb app.py` checks that
no shipped function exceeds cognitive complexity 15. Dev dependencies
(`requirements-dev.txt`): pytest 8.4.2, pytest-cov 7.1.0, complexipy 8.0.1 and
coverage 7.10.7, all of which support Python 3.9.

The developer QA tools in `scripts/` are not deployed:

| Tool | Purpose |
|---|---|
| `scripts/check_report.py` | Correctness gate over the fixtures in `ReferenceJSON/`. It fails if a delivered value is missing from the page, if a verbatim figure changed, or if the page has an external reference. |
| `scripts/check_corpus.py` | Runs the same gate, and more, over every archived API response (default folder `$AECB_ARCHIVE_DIR`). Writes `corpus_report/`. `--selftest` proves every check can fire. Triage playbook: [scripts/corpus/TRIAGE.md](scripts/corpus/TRIAGE.md). |
| `scripts/check_brief.py`, `scripts/eval_brief.py` | AI Analysis fast gate (about a minute) and quality harness (every block, three fixtures; about 15 minutes on gpt-oss:20b), against the provider `AECB_ENV` selects (unset: the local Ollama model). Model steps are skipped when the provider cannot serve. `eval_brief.py --effort checklist=low,memo=low` runs named passes at another reasoning level, for development only. |
| `scripts/token_budget.py` | The AI Analysis's prompt tokens per pass on the three fixtures, counted by the local Ollama without generating (about a minute). Run it before and after any prompt or digest change; the budget and pricing are in [docs/AI_ANALYSIS_MRM.md](docs/AI_ANALYSIS_MRM.md) section 12. |
| `scripts/measure/` | Layout (geometry) harness in headless Chrome. Use it for any change to `report.css` or to section markup. See [scripts/measure/README.md](scripts/measure/README.md). |
| `scripts/make_synthetic_payload.py` | Generates the synthetic delinquent fixture; `--patterns` generates the patterns fixture that plants every non-obvious-risk pattern. |
| `scripts/fetch_fonts.py` | Regenerates `assets/fonts/fonts_inline.css`. Needs internet access. |

## Configuration

### Config files (`config/`)

Policy and vocabularies live in JSON with `_comment` blocks. A missing file, or
an invalid required key, stops the render with an error. The app never falls
back to a default.

| File | Kind | Supplies |
|---|---|---|
| `api.json` | Deployment | Bureau-report API `base_url` and `timeout_seconds`, used by `app.py`. It must not contain credentials: a file with an `auth` block is refused. |
| `bands.json` | FH policy | Score scale, the seven FH score bands (cut-off and tone), AECB `DataRange` labels, vintage bands, `validity_days`, `closed_window_months`, `applications_90d_red`/`_amber`. |
| `status_codes.json` | Bureau vocabulary + FH cut-offs | Contract status codes, labels and integer ranks; the `severity` cut-offs that map a rank to severe, adverse or normal; roles; payment frequencies; DPD buckets; application phases. |
| `providers.json` | Registry (stub) | Provider code to display name and badge kind (`bank`, `tel`, `nbfi`, `onus`). Unknown codes are shown as the code itself; `T##` reads as telecom and `N##` as a non-bank lender. The kind also drives the AI analysis's provider-kind lenses. |
| `income.json` | FH policy | Assumed currency, placeholder-income floor, employment confirmation window. |
| `returns.json` | Vocabulary + policy | Returned-instrument types, severity tones, review window. |
| `macro_context.json` | Optional, AI Analysis only | The dated context register: curated macro facts and topic-tagged entries for the AI analysis's background channel, the closed sector vocabulary the risk block may infer into, its owner and review cadence. If the file is absent, the background channel and sector inference are off. |

### Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `AECB_API_USERNAME` | `app.py` (required) | Service account for the bureau-report API (IIS Windows authentication, NTLMv2). |
| `AECB_API_DOMAIN` | `app.py` (optional) | Windows domain for a bare account name. In env files, set this instead of writing `DOMAIN\account`. |
| `AECB_API_PASSWORD` | `app.py` (required) | Service account password. |
| `AECB_ARCHIVE_DIR` | `app.py`, `check_corpus.py` | Folder for archived API responses. Must be outside the app directory. If unset, archiving is off. |
| `AECB_LOG_DIR` | `app.py` | Folder for the rotating `aecb.log`. If unset, logs go to stderr only. |
| `AECB_AUDIT_USER_HEADER` | `app.py` (production) | Name of the request header in which the SSO reverse proxy passes the authenticated user. The user is then recorded in the audit line. |
| `AECB_ENV` | `app.py`, AI Analysis scripts | `dev`, `uat` or `prod`. Picks the AI Analysis's provider (dev: the local Ollama model; uat and prod: Core42) and whether the app offers its development tools. Unset: `app.py` assumes `prod`; the AI Analysis scripts, which never run on a server, assume `dev`. |
| `AECB_OLLAMA_MODEL` | `app.py`, AI Analysis scripts (development only) | The local AI Analysis model: `gpt-oss:120b` (the default when unset) or `gpt-oss:20b` for a machine that cannot hold 120b. Any other value leaves the AI panel unavailable. Servers run no Ollama. |
| `AECB_AI_BRIEF` | `app.py` (optional) | The AI panel: `live`, `coming_soon` or `off`. Unset: `live` in dev, `coming_soon` in uat and prod. `live` on a server is a model change ([docs/AI_ANALYSIS_MRM.md](docs/AI_ANALYSIS_MRM.md)). |
| `AECB_FEEDBACK_DIR` | `app.py` (live panel only) | Folder for the thumbs up/down feedback on AI analyses (`feedback.jsonl`, one JSON line per vote). Must be outside the app directory. If unset, feedback is off. |
| `AECB_CORE42_API_KEY` | reserved | For the Core42 connector once it is onboarded. Unused today. |
| `AECB_TEST_SUBJECT_ID` | `tests/test_api_live.py` | The subject id the live API tests fetch. Development only. |
| `AECB_CHROME`, `AECB_ROOT`, `AECB_WORK`, `AECB_PAYLOAD` | `scripts/measure/`, browser tests | Chrome path, source tree, work folder and payload for the layout harness. Development only. |

On the server, these variables are set in `/etc/aecb-analyzer/aecb.env`; on a
developer machine, in `~/etc/aecb-analyzer/aecb.env` (template for both:
`deploy/aecb.env.example`). See [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Data handling

- **Input.** `app.py` accepts one CB subject id, checked against
  `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$`, and has no file uploader. Only with
  `AECB_ENV=dev` can it also open payload files already on disk (the
  fixtures and the archive). The fetched
  payload is held in the user's Streamlit session.
- **Archive.** Each successful API response is saved verbatim to
  `AECB_ARCHIVE_DIR` (folder mode 0700, file mode 0600, one file per fetch).
  Retention is an operations task.
- **Logs.** Logs contain CB subject ids and audit lines, never payload
  content. API error responses are logged with their status, headers and the
  first part of the body.
- **Output.** The report is one HTML document with no external references,
  guarded by a per-page Content-Security-Policy. It can be downloaded
  (`aecb_<subject>.html`) for filing.
- **Fixtures.** The committed payloads in `ReferenceJSON/` are anonymized or
  synthetic.

## Repository layout

```
app.py                the entry point (every environment)
aecb/                 the package: loader, dates, coerce, context, api, ntlm,
                      archive, logsetup, settings, runtime, ui, feedback;
                      derive/ (payload interpretation, brief_facts/);
                      render/ (HTML, CSS, JS, sections/, analysis view);
                      brief/ (AI Analysis: prompts/, blocks/, providers)
config/               policy and vocabulary JSON (7 files)
assets/fonts/         base64-inlined fonts + OFL licence
resources/            optional logo (see resources/README.md)
ReferenceJSON/        committed anonymized/synthetic fixtures
deploy/               build, release, install scripts; systemd unit; env template
.streamlit/           Streamlit server settings
tests/                pytest suite
scripts/              developer QA tooling (not deployed)
docs/                 documentation
requirements.txt      runtime pin; requirements.lock: hashed full tree
```

## Documentation

| Document | Audience | Contents |
|---|---|---|
| [docs/OVERVIEW.md](docs/OVERVIEW.md) | Business, reviewers | What the product does, in non-technical terms |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Engineering, security | Components, pipeline, security model, design rationale |
| [docs/LowLevelArchitecture.md](docs/LowLevelArchitecture.md) | Engineering, RRM | Label-by-label reference: code, config and payload for every screen element |
| [docs/DECISIONS.md](docs/DECISIONS.md) | All | Settled product and data decisions, payload traps, open items |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Operations | Build, release, install, run (production and UAT), logs, archive retention, troubleshooting |
| [docs/DEPENDENCY_RISK.md](docs/DEPENDENCY_RISK.md) | Security | Dependency vulnerability register for the Python 3.9 runtime |
| [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) | Security | Expected Sonar/Mend findings and their disposition |
| [docs/AI_ANALYSIS_MRM.md](docs/AI_ANALYSIS_MRM.md) | Model risk | AI Analysis model documentation (version 1, prompt `p1.0`): stated use, model and environments, the four blocks and their guards, change control, evaluation, the pending gpt-oss-120b validation, Core42 onboarding, token budget |
| [CHANGELOG.md](CHANGELOG.md) | All | Release notes |
| `docs/BRD.docx` | Business | Business requirements |
