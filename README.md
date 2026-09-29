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

## Entry points

| Entry point | Role | Deployed |
|---|---|---|
| `app_api.py` | Production/UAT. Takes a CB subject id, fetches the payload from the internal bureau-report API endpoint configured in `config/api.json`, validates it and renders the report. The AI Analysis panel is not included. Each query is audit-logged. | Yes |
| `app.py` | Development harness. Offers a picker for the committed fixtures, a session-scoped uploader, the optional local-model AI brief (Ollama) and a CSS/JS reload button. | No (excluded from the release archive) |

Both entry points use the same pipeline and the same hosting code (`aecb/ui.py`).

## Requirements

- **Server:** CPython **3.9** on Linux x86_64, air-gapped. Any 3.9.x release
  except **3.9.7**, which streamlit 1.50.0 excludes. The server stays on 3.9 by
  decision because it is air-gapped. The known vulnerabilities that follow
  from this are assessed in [docs/DEPENDENCY_RISK.md](docs/DEPENDENCY_RISK.md).
- **Runtime dependency:** `streamlit==1.50.0`, the last release that supports
  Python 3.9. The full dependency tree is pinned with sha256 hashes in
  `requirements.lock`.
- **Development:** a newer Python works locally, but the code, tests and CI
  must pass on Python 3.9. `tests/test_python39.py` parses every shipped module
  with the 3.9 grammar.

## Quick start (development)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m streamlit run app.py       # fixture picker + uploader
```

### Calling the live API from a development machine

On the server, systemd loads `/etc/aecb-analyzer/aecb.env` into the app's
environment. `scripts/local_env.py` does the same job locally. It uses a
settings file with the same variables, under your home folder by default:
`~/etc/aecb-analyzer/aecb.env`. That keeps it outside the repository, so it
cannot be committed, and needs no administrator rights. It needs network
access to the bureau-report API.

```bash
.venv/bin/python scripts/local_env.py init    # create ~/etc/aecb-analyzer/aecb.env (mode 0600)
# edit it: AECB_API_USERNAME, AECB_API_DOMAIN, AECB_API_PASSWORD, AECB_TEST_SUBJECT_ID
.venv/bin/python scripts/local_env.py check   # show the settings, password hidden
.venv/bin/python scripts/local_env.py run     # start app_api.py with them
.venv/bin/python scripts/local_env.py exec -- .venv/bin/python -m pytest -m live_api
```

- Responses fetched through `run` are archived to `~/var/lib/aecb-analyzer/api_responses/`.
- `exec -- .venv/bin/python scripts/check_corpus.py` checks the archived responses.
- A variable already set in your shell overrides the file.
- `--env-file PATH` (or `AECB_ENV_FILE`) selects a different file, such as the real `/etc` one.

## Tests and QA tools

```bash
.venv/bin/python -m pytest                          # full suite (tests/)
.venv/bin/python -m pytest --cov --cov-report=xml   # plus coverage.xml for Sonar
```

Tests marked `browser` need Chrome or Chromium. Tests marked `model` need a
local Ollama. Tests marked `live_api` call the real bureau-report API and need
the credentials and `AECB_TEST_SUBJECT_ID` (see above). Each group is skipped
when what it needs is missing. Dev
dependencies (`requirements-dev.txt`): pytest 8.4.2, pytest-cov 7.1.0 and
coverage 7.10.7, all of which support Python 3.9.

The developer QA tools in `scripts/` are not deployed:

| Tool | Purpose |
|---|---|
| `scripts/check_report.py` | Correctness gate over the fixtures in `ReferenceJSON/`. It fails if a delivered value is missing from the page, if a verbatim figure changed, or if the page has an external reference. |
| `scripts/check_corpus.py` | Runs the same gate, and more, over every archived API response (default folder `$AECB_ARCHIVE_DIR`). Writes `corpus_report/`. `--selftest` proves every check can fire. Triage playbook: [scripts/corpus/TRIAGE.md](scripts/corpus/TRIAGE.md). |
| `scripts/check_brief.py`, `scripts/eval_brief.py` | AI brief gate and quality harness. They need a local Ollama with the model. The model steps are skipped without it. |
| `scripts/measure/` | Layout (geometry) harness in headless Chrome. Use it for any change to `report.css` or to section markup. See [scripts/measure/README.md](scripts/measure/README.md). |
| `scripts/local_env.py` | Loads the local settings file (`~/etc/aecb-analyzer/aecb.env`) and runs `app_api.py` or any command with it. |
| `scripts/make_synthetic_payload.py` | Generates the synthetic delinquent fixture. |
| `scripts/fetch_fonts.py` | Regenerates `assets/fonts/fonts_inline.css`. Needs internet access. |

## Configuration

### Config files (`config/`)

Policy and vocabularies live in JSON with `_comment` blocks. A missing file, or
an invalid required key, stops the render with an error. The app never falls
back to a default.

| File | Kind | Supplies |
|---|---|---|
| `api.json` | Deployment | Bureau-report API `base_url` and `timeout_seconds`, used by `app_api.py` only. It must not contain credentials: a file with an `auth` block is refused. |
| `bands.json` | FH policy | Score scale, the seven FH score bands (cut-off and tone), AECB `DataRange` labels, vintage bands, `validity_days`, `closed_window_months`, `applications_90d_red`/`_amber`. |
| `status_codes.json` | Bureau vocabulary + FH cut-offs | Contract status codes, labels and integer ranks; the `severity` cut-offs that map a rank to severe, adverse or normal; roles; payment frequencies; DPD buckets; application phases. |
| `providers.json` | Registry (stub) | Provider code to display name and badge kind. Unknown codes are shown as the code itself. |
| `income.json` | FH policy | Assumed currency, placeholder-income floor, employment confirmation window. |
| `returns.json` | Vocabulary + policy | Returned-instrument types, severity tones, review window. |
| `macro_context.json` | Optional, AI brief only | Curated, dated macro facts for the brief's background lens. If the file is absent, the lens is off. |

### Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `AECB_API_USERNAME` | `app_api.py` (required) | Service account for the bureau-report API (IIS Windows authentication, NTLMv2). |
| `AECB_API_DOMAIN` | `app_api.py` (optional) | Windows domain for a bare account name. In env files, set this instead of writing `DOMAIN\account`. |
| `AECB_API_PASSWORD` | `app_api.py` (required) | Service account password. |
| `AECB_ARCHIVE_DIR` | `app_api.py`, `check_corpus.py` | Folder for archived API responses. Must be outside the app directory. If unset, archiving is off. |
| `AECB_LOG_DIR` | both entry points | Folder for the rotating `aecb.log`. If unset, logs go to stderr only. |
| `AECB_AUDIT_USER_HEADER` | `app_api.py` (optional) | Name of the request header in which the SSO reverse proxy passes the authenticated user. The user is then recorded in the audit line. |
| `AECB_ENV_FILE`, `AECB_TEST_SUBJECT_ID` | `scripts/local_env.py`, `tests/test_api_live.py` | The local settings file to load, and the subject id the live API tests fetch. Development only. |
| `AECB_CHROME`, `AECB_ROOT`, `AECB_WORK`, `AECB_PAYLOAD` | `scripts/measure/`, browser tests | Chrome path, source tree, work folder and payload for the layout harness. Development only. |

On the server, these variables are set in `/etc/aecb-analyzer/aecb.env`
(template: `deploy/aecb.env.example`). See [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Data handling

- **Input.** `app_api.py` accepts one CB subject id, checked against
  `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$`, and has no file uploader. The fetched
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
app_api.py            production/UAT entry point
app.py                development harness (not deployed)
aecb/                 the package: loader, dates, coerce, context, api, ntlm,
                      archive, logsetup, ui; derive/ (payload interpretation);
                      render/ (HTML, CSS, JS, sections/); brief/ (AI brief)
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
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Operations | Build, release, install, run, logs, archive retention, troubleshooting |
| [docs/DEPENDENCY_RISK.md](docs/DEPENDENCY_RISK.md) | Security | Dependency vulnerability register for the Python 3.9 runtime |
| [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) | Security | Expected Sonar/Mend findings and their disposition |
| [docs/AI_BRIEF_MRM.md](docs/AI_BRIEF_MRM.md) | Model risk | AI brief model documentation (development harness only) |
| [CHANGELOG.md](CHANGELOG.md) | All | Release history |
| `docs/BRD.docx` | Business | Business requirements |
