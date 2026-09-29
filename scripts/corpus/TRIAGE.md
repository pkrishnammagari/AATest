# Triaging a corpus report

This is the playbook for working through `corpus_report/summary.md`, the output
of `scripts/check_corpus.py`. Run it on the machine that holds the archived API
responses. The harness reads `$AECB_ARCHIVE_DIR` by default and falls back to
`ReferenceJSON/api_responses/` when that variable is unset. `--dir <folder>`
points it anywhere else.

The corpus is expected to be masked. If it holds unmasked bureau data, handle
it under the bank's data-handling policy.

## 0. Before trusting a report

```bash
python3 scripts/check_corpus.py --selftest   # every check must be seen to fire
python3 scripts/check_report.py              # the fixture gate must be green
python3 scripts/check_corpus.py              # the corpus run -> corpus_report/
```

If the self-test fails on this machine, stop. The harness is broken here and
its report cannot be trusted. Fix the harness first.

## 1. Work by check, not by file

Section 1 of the report lists each failing check and how many payloads it hit.
One root cause usually fails many payloads, so take the checks in order:
ERROR, then FAIL, then WARN. For each check:

1. Take the first payload listed under it, and rerun just that one:
   `python3 scripts/check_corpus.py --only <file> --browser off`
2. Read the evidence:
   - the finding's details;
   - the payload fields it names, in the corpus folder under `<file>`;
   - the saved page (`corpus_report/pages/<file>.html`, opened in a browser);
   - the module named in the report's *Start at* column.
3. Compare it against the spec.
   [docs/LowLevelArchitecture.md](../../docs/LowLevelArchitecture.md)
   describes the behaviour of every label and which function draws it. Search
   [docs/DECISIONS.md](../../docs/DECISIONS.md) for a recorded decision about
   the behaviour before calling it a bug.
4. Classify it as exactly one of:

| Class | Meaning | What to do |
|---|---|---|
| CODE BUG | The page contradicts the spec, crashes, or drops a delivered value | Fix it in `aecb/`. |
| HARNESS FALSE POSITIVE | The check is wrong; the page follows the spec | Fix the check in `scripts/corpus/` (or `check_report.py`) **and** add or adjust a case in `selftest.py`. |
| CONFIG GAP | A delivered value the config cannot read (`vocab.*`) | Propose the config entry. Do not invent AECB meanings, ranks or tones: ask the product owner. |
| DECISION NEEDED | The spec does not cover it (e.g. `nodrop.contacts_type`, `nodrop.applications_undated`) | Write up the options. Implement nothing until the product owner decides. |
| DATA QUIRK | The payload itself is odd (a bureau inconsistency, a masking artefact) and the page handles it as designed | Record it; no change. |

5. Fix CODE BUGs and HARNESS FALSE POSITIVEs directly. Bring each CONFIG GAP
   and DECISION NEEDED to the product owner with a recommended option, and act
   only after approval.
6. After a fix, rerun `--only` on every payload that check hit, then
   `python3 scripts/check_report.py`, then the full corpus. Nothing that was
   clean may turn red.

Log every check you close in `corpus_report/triage_log.md`, one row each:

| Check | Payloads | Class | Root cause | Action | Status |
|---|---|---|---|---|---|

## 2. Ground rules

- **The doctrine does not bend.**
  - Never render a fabricated value.
  - Absence never renders as good conduct.
  - A delivered value is never dropped silently.
  - Config files fail loudly.
- **Settled decisions are not bugs.** Several behaviours look wrong but were
  decided, with reasons, in [docs/DECISIONS.md](../../docs/DECISIONS.md).
  Examples:
  - scope chips come from the single winning sectionStatus row, with array
    order breaking ties;
  - on a stale archive payload the report date is the later enquiry date, so
    windows shift forward, and §08 can show "0 rows in window" against a
    non-zero `Applications90D`;
  - `ArchiveDate`, `PaymentBehaviour` and `MaxCurrentPaymentDelay` are never
    shown, and neither are the `summary` three-month return counters;
  - `TotalExposure` does not equal the sum of the card balances;
  - the §03 36-month panel is never shown milder than the delivered 24-month
    figure;
  - the validity meter uses two colours only.

  If real data suggests one of these is wrong, raise it as DECISION NEEDED.
- **Never weaken a check just to turn the report green.** If a check is wrong,
  record that in the log, fix it, and prove the fix with a self-test case.
- **Keep the code runnable on the server:** Python 3.9 and no new
  dependencies. The server is air-gapped.
- **Keep the docs current.** Record a new decision in
  [docs/DECISIONS.md](../../docs/DECISIONS.md). Update
  [docs/LowLevelArchitecture.md](../../docs/LowLevelArchitecture.md) (one
  simple table per section), `docs/ARCHITECTURE.md` and `README.md` whenever
  behaviour they describe changes.
- **Commit no corpus data.** Never commit anything from the corpus folder or
  `corpus_report/`, because both hold bureau-derived data.
  `ReferenceJSON/api_responses/` and `corpus_report/` are gitignored, and
  `$AECB_ARCHIVE_DIR` is outside the repository.

## 3. Reading findings by layer

| Layer | Checks | Usually means |
|---|---|---|
| load, render | `load.*`, `render.*` | The payload has a shape the code never met. Harden the function named by the deepest `aecb/` frame. Absence must render as an explicit empty state, never a crash. |
| no-drop | `gate.check_report`, `nodrop.*` | A delivered value never reaches the page. |
| recompute | `recompute.*` | A pill, chip or figure disagrees with the rule restated from `docs/LowLevelArchitecture.md`. Either the code or the restatement is wrong; the spec decides. |
| hygiene | `hygiene.*` | `None`, `NaN`, a blank slot or broken markup reached the page. |
| browser | `browser.*` | The same, but in what `report.js` draws for §07 and §08. Open the saved page with the browser's developer tools. |
| vocabulary | `vocab.*` | The config does not know a delivered value. Report section 3 aggregates these across the corpus. |
| dates | `dates.*` | A date shape `aecb/dates.parse_any` cannot read, or events after the report date. |
| baseline | `baseline.*` | Derived facts moved since `--approve`. Expected after an intentional change; otherwise a regression. |

## 4. Masked data

- The page's own format flags ("not a valid UAE mobile", "not a valid e-mail")
  may fire on masked values. That is the page working, not a finding.
- If masking replaced dates or numbers with placeholders, `dates.unparseable`
  or `vocab.*` can flood. Classify it once as DATA QUIRK (masking) and say
  which fields are affected.
- Long unbroken masked strings can trigger `browser.overflow`. Treat that as
  real, because production data can carry long strings too. The fix is usually
  CSS wrapping.

## 5. When the corpus is clean

1. Open a varied sample of saved pages. Report section 5 shows which payloads
   exercise which variants; pick one for each unusual variant. Rerun with
   `--save-html all` to save every page.
2. When they read correctly, record the baseline:
   `python3 scripts/check_corpus.py --approve`.
3. From then on, every code change is checked against that baseline. Rerun the
   corpus and review every `baseline.changed` diff.

## Optional tooling: prompt for an AI coding assistant

This section is optional. The playbook above is complete without it. A team
that uses an AI coding assistant (for example Claude Code) on the corpus
machine can start a triage session with the prompt below. The assistant's
output is reviewed like any other change, and CONFIG GAPs and DECISIONS NEEDED
still go to the product owner.

> Read `scripts/corpus/TRIAGE.md`, then `corpus_report/summary.md`. Run the
> self-test first. Then triage every ERROR and FAIL check in the order the
> report lists them, following the playbook: classify each, fix CODE BUGs and
> HARNESS FALSE POSITIVEs, and bring CONFIG GAPs and DECISIONS NEEDED to me
> with a recommendation. Log everything in `corpus_report/triage_log.md`. Rerun
> the corpus after each fix and show me the before/after counts.
