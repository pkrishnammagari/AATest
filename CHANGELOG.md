# Changelog

## 1.0.0 — first build

The first build of FH AECB Analyzer: a read-only viewer that renders an AECB
bureau report as one self-contained underwriting screen, with an optional AI
Analysis that is live in development only.

### Report viewer

- One entry point, `app.py` (`streamlit run app.py`): a CB subject id in, the
  bureau report out, fetched from the internal bureau-report API (NTLMv2,
  standard library only) and validated.
- Eight sections — identity, score and bureau history, worst statuses, income
  and employment, cheque and direct-debit returns, active facilities,
  facility detail with 36-month conduct, recent applications — plus a top bar
  with report validity and enquiry scope.
- Every figure is delivered by AECB or derived from delivered values, and
  tagged so; absence reads "not reported", never as good conduct; policy and
  vocabularies live in `config/` and fail loudly when missing or invalid.
- `AECB_ENV=dev` adds a sample picker and a CSS/JS reload button; there is no
  file uploader in any environment.

### Data handling and security

- Every payload string is escaped; the data blob is script-safe JSON; each
  page carries a Content-Security-Policy that allows only its own hashed
  inline script and fetches nothing.
- API credentials come from the environment only; a `config/api.json` with
  an `auth` block is refused.
- Each API response is archived outside the application tree
  (`AECB_ARCHIVE_DIR`, 0700/0600); one audit line per query; logs never
  carry payload content.

### AI Analysis (development only; "Coming soon" on UAT and production)

- Four blocks: a fresh lens (a hypothesis -> verification loop over raw
  monthly tables), non-obvious risk (Python risk lenses read against a dated
  context register), a checklist replay of the team's ten steps with a
  tripwire audit, and a memo with an advisory suggested outcome.
- The model computes nothing: every item is validated against citations,
  verbatim figures and named entities before it renders; prohibited fields
  (Nationality, Gender, ResidentFlag) never reach the model.
- Target model gpt-oss-120b. Development uses Ollama on loopback with a
  closed model list (`gpt-oss:120b` default, `gpt-oss:20b`); UAT and
  production will use Core42, a placeholder until it is onboarded.
- Prompt version `p1.0`. Model documentation, evidence (gpt-oss:20b) and
  the pending gpt-oss-120b validation: `docs/AI_ANALYSIS_MRM.md`.
- One thumbs up/down per analysis, recorded outside the application tree
  (`AECB_FEEDBACK_DIR`).

### Deployment

- RHEL x86_64, Python 3.9, streamlit 1.50.0; the server is air-gapped and
  installs offline from a hash-pinned wheel bundle (`deploy/`).
- `deploy/install_offline.sh` verifies the bundle, builds a clean
  virtualenv, accepts only the known watchdog line from `pip check`, and
  smoke-renders the synthetic fixture.
- Production runs behind a TLS/SSO reverse proxy on 127.0.0.1:8501; UAT is
  served directly on port 8080 (`docs/OPERATIONS.md`).

### Quality and tooling

- pytest suite (Python 3.9 grammar enforced, browser, live-API and model
  tests skipped when their dependency is absent); no shipped function above
  cognitive complexity 15 (`complexipy`).
- Developer tools in `scripts/`: the report gate (`check_report.py`), the
  corpus harness (`check_corpus.py`), the AI Analysis gate, evaluation and
  token budget (`check_brief.py`, `eval_brief.py`, `token_budget.py`), the
  layout harness (`scripts/measure/`), and the fixture generator.

### Documentation

- README, `docs/OVERVIEW.md`, `docs/ARCHITECTURE.md`,
  `docs/LowLevelArchitecture.md`, `docs/DECISIONS.md`, `docs/OPERATIONS.md`,
  `docs/AI_ANALYSIS_MRM.md`, `docs/SECURITY_REVIEW.md`,
  `docs/DEPENDENCY_RISK.md`, and `docs/BRD.docx` (business requirements).
