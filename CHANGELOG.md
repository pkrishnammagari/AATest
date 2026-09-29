# Changelog

## Unreleased — UAT hardening (29 Sep 2026)

### Security
- Fixed a stored XSS: provider codes in the §01 identity fold rows are now
  escaped.
- The data blob is embedded as script-safe JSON (`js.json_for_script()`
  escapes `<`, `>`, `&`, U+2028 and U+2029).
- Each page carries a Content-Security-Policy that allows only its own inline
  script, by sha256 hash, and fetches nothing.
- API credentials moved to environment variables (`AECB_API_USERNAME`,
  `AECB_API_DOMAIN`, `AECB_API_PASSWORD`). A `config/api.json` that still
  contains an `auth` block is refused.
- API responses are archived outside the application tree, to
  `AECB_ARCHIVE_DIR`, with folder mode 0700 and file mode 0600. Archiving is
  off when the folder is not configured.
- User-facing error messages no longer carry internal addresses, response
  bodies or tracebacks; details go to the server log.
- Added `.streamlit/config.toml`: headless, no usage statistics, no error
  details in the browser, viewer toolbar, no file watcher, XSRF protection
  on, 10 MB upload cap.
- One audit line per query on the `aecb.audit` logger. It records the
  subject, outcome, user (from the SSO proxy header) and client address.
- The CB subject id is validated before it reaches the API or the logs.
- The development-only controls (fixture picker, uploader, CSS reload) were
  removed from the production entry point, and the AI Analysis panel was
  removed from the production page.

### Correctness
- Added `aecb/coerce.py`, a shared reader for untyped payload values:
  - amounts accept thousands commas;
  - counts and the score must be whole numbers;
  - flags have three states (yes / no / not reported), so a value of `"N"`
    no longer reads as a raised dispute;
  - a zero delivered as text (`"0"`) reads as zero wherever a figure is
    tested for presence (guarantee chips, the guarantor block, the heatmap's
    arrears split).
- The loader handles malformed input: it rejects `NaN`/`Infinity` literals
  and non-object documents, and it drops and counts non-object rows, which
  the sidebar reports.
- Configuration is validated at load. The render stops with an error naming
  the problem for a status code without an integer rank, missing or unordered
  severity cut-offs, a malformed score scale or band list, an unknown band
  tone, or a missing or invalid policy value.
- AI brief digest: missing delay evidence now reads "no delay reported" rather
  than "clean", and reporting gaps are treated as unknowns.

### Maintainability
- No function is above cognitive complexity 15.
- `derive/brief_facts` was split into a package with one module per lens.
- Streamlit hosting shared by both entry points moved into `aecb/ui.py`, and
  logging into `aecb/logsetup.py`.
- `report.js` was restructured into small, single-purpose builders.

### Build and test
- `requirements.lock` pins the full dependency tree with sha256 hashes, and
  installation uses `pip --no-index --require-hashes`.
- The build and install scripts were hardened and moved to `deploy/`.
  `install_offline.sh` now verifies the bundle checksum, refuses any Python
  other than 3.9 (and 3.9.7 exactly), builds a clean virtualenv, and runs
  `pip check` and a smoke render.
- Added release packaging (`deploy/make_release.sh`: a `git archive` of HEAD
  minus development paths), a hardened systemd unit and an environment-file
  template.
- Added a pytest suite (`tests/`, 203 tests, 87% branch coverage of `aecb/`),
  verified on Python 3.9 with streamlit 1.50.0 as well as the development
  interpreter.
- `sonar-project.properties` now scans the production entry point
  `app_api.py` and `deploy/`, which it previously omitted. It treats `tests/`
  as tests, reads coverage from `coverage.xml`, and excludes the developer
  tooling in `scripts/`.

### Developer tooling
- `scripts/local_env.py` loads a local settings file that mirrors the server's
  `/etc/aecb-analyzer/aecb.env` (default `~/etc/aecb-analyzer/aecb.env`, kept
  outside the repository, mode 0600). It runs `app_api.py` or any command
  against the live API from a development machine.
- `tests/test_api_live.py` (marker `live_api`) fetches a configured test
  subject from the real API and runs the report gate on it. It is skipped
  unless credentials and `AECB_TEST_SUBJECT_ID` are set.

### Documentation
- Rewrote the documentation set:
  - README;
  - `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/DECISIONS.md`,
    `docs/LowLevelArchitecture.md`, `docs/OVERVIEW.md`,
    `docs/AI_BRIEF_MRM.md`, `docs/DEPENDENCY_RISK.md` and
    `docs/SECURITY_REVIEW.md`;
  - this changelog.
- `HANDOFF.md` and `PayLoadRead.md` were merged into the new documents and
  removed.
