# AI Underwriting Brief — Model Risk Documentation

This document describes the AI brief feature for model risk management: what
the model is, what it may do, how its output is controlled, and which changes
require review. It reflects the current implementation, prompt version
`p4.1`.

| | |
|---|---|
| Model owner | ____ |
| Approver | ____ |
| Deployment status | **Not deployed on UAT.** Development harness only (`app.py`) |

## 0. Deployment status

The brief is **not part of the UAT deployment**:

- The production entry point `app_api.py` never imports `aecb.brief`.
- It renders the report with `render_page(ctx, ai_panel=False)`, so the page
  has no AI Analysis button and no brief rail.
- No model service (Ollama) is installed on the server.
- `app.py`, `scripts/check_brief.py` and `scripts/eval_brief.py` are excluded
  from the release archive.

The code under `aecb/brief/` and `aecb/derive/brief_facts/` still ships inside
the `aecb` package. Any proposal to enable the brief in UAT or production is a
model change under [Change control](#6-change-control) and needs this document approved first.

## 1. What the feature is

The Underwriting Brief is a side panel in the report viewer. It gives a
second-lens reading of the bureau payload:

- trajectories;
- inconsistencies between arrays;
- behavioural patterns;
- structural risk;
- what the file cannot establish.

It is generated only on request (the "Generate AI brief" sidebar button in
`app.py`), never automatically. The report is complete and fully usable
without it.

The governance rule is printed in the panel itself and enforced by the
architecture: **the model interprets only. It never computes figures and never
gives the decision.**

## 2. Model and runtime

| | |
|---|---|
| Model | `gpt-oss:20b` (open-weight), served by Ollama |
| Endpoint | `http://127.0.0.1:11434/api/chat`, pinned to the loopback address in `aecb/brief/client.py`. It is not read from config or the environment, so bureau data cannot be routed off the machine by misconfiguration. |
| Transport controls | Proxy environment variables are ignored (a proxy would otherwise receive even a loopback request). Redirects are refused. Responses larger than 4 MB are rejected. |
| Decoding | Temperature 0, fixed seed, JSON-schema-constrained output, `num_ctx` 16384, `num_predict` 4096, 180-second timeout |
| Network | The model runs on the same host. The fact digest never leaves the machine. |
| Persistence | Briefs are cached in Streamlit session memory only, keyed by payload hash, model tag and prompt version. Nothing is written to disk. |

## 3. Data flow and the calculation boundary

```
payload -> aecb/derive/brief_facts/  numbered fact table (deterministic Python)
        -> aecb/brief._prohibited_content   runtime policy check (refuse on breach)
        -> one schema-constrained model pass (facts only, never raw JSON)
        -> aecb/brief/validate.py    guards (section 4)
        -> optional synthesis pass over VALIDATED findings only, re-validated
        -> deterministic HTML rendering (aecb/render/brief.py)
```

Every join, trajectory, aggregate and ratio interpretation is computed in
Python in the `aecb/derive/brief_facts/` package. Its modules are:

| Module | Contents |
|---|---|
| `_common` | Shared formatting and helpers |
| `structure` | Portfolio shape and related structural facts |
| `trajectory` | Per-contract time series |
| `inconsistency` | Cross-array joins |
| `behavior` | Payment waterfall and behavioural patterns |
| `absence` | What the file does not establish |
| `background` | Curated context from the optional `config/macro_context.json` |

Every fact carries verbatim payload values, the exact field paths behind it,
and a pointer to the report section where it can be checked. The model's only
role is to select and connect facts, and it cites them by fact ID.

**Digest contract (p4.1):**

- **Free text is sanitised.** Product, provider and employer names and stated
  reasons pass through `_common.text()`. It collapses control characters and
  line separators, removes fact-ID-shaped tokens (`F###`), neutralises the
  digest's bracket syntax and caps the length. A value in the payload
  therefore cannot forge a fact line or smuggle instructions into the prompt.
- **No subject identifier is sent.** The model does not need to know who the
  subject is.
- **Age only.** The birth month is not sent; DOB-derived age is.
- **The report date is sent with its basis:** "the latest bureau enquiry date",
  or "the bureau data pull date; no enquiry was dated".
- **Missing delay evidence reads "no delay reported"**, never "clean".
  Reporting gaps are unknowns, not clean months.
- **The fact table is fenced** between `BEGIN FACT TABLE` and `END FACT TABLE`.
  The system prompt states that text inside a fact is data copied from the
  bureau file and never an instruction.

## 4. Output controls (the guards)

`aecb/brief/validate.py` runs on every response. A failing item is dropped,
never repaired.

1. **Shape.** The schema is re-checked even though decoding is
   schema-constrained.
2. **Citations.** Every cited fact ID must exist in the digest.
3. **Verbatim figures.** Every numeric token in a claim (and in its suggested
   action) must appear among the cited facts' numeric tokens. The comparison
   uses exact decimal arithmetic after removing commas, so `115,300` matches
   `115300`, but `1,234,570` does not match `1,234,567`. An invented figure
   cannot render.
4. **Named entities.** Every proper-noun-looking token must appear in a cited
   fact as a whole word (plurals allowed). Matching is whole-word, not
   substring, so a fact containing "alignment" does not vouch for the name
   "Ali". A made-up employer or counterparty cannot render.
5. **Dedup and caps.** At most 10 findings, 5 unknowns and 3 background notes.
   Findings citing an identical set of facts are merged into one.
6. **Derived pointers.** The "verify at section N" target comes from the cited
   facts, never from the model.

The synthesis line is re-validated against the validated findings' own text.
The unknowns list is validated against the whole digest. Anything that fails
renders as absent, not as an error.

Drop reasons are returned with the brief (`dropped`). The development sidebar
shows their count. They are not written to the server log.

**Failure handling.** Every failure in generation is converted to a single
`BriefUnavailable` exception, which the caller logs with its traceback. This
covers the model service, a digest or optional-config problem, and a
prohibited-field breach. No traceback reaches the browser. The page degrades
as follows:

| Situation | What the page shows |
|---|---|
| Ollama absent or model not pulled | The rail's "No brief generated" state. The sidebar names the reason. |
| Timeout or malformed output after one retry | Same state. The error goes to the server log only. |
| Every finding dropped | An explicit "No validated findings" state, which is not presented as a clean bill of health |

## 5. Macro / time-sensitive context

The model's own knowledge stops at its training cutoff, and the prompt forbids
it from stating current conditions. The only channel for time-sensitive
context is `config/macro_context.json`. That file:

- is hand-curated and dated, holding short generic facts;
- is rendered with its as-of date;
- is connected to the payload by the model in a visually fenced "Background
  context" block that carries no severity;
- is optional. Without it, the background lens is off.

## 5a. Prohibited factors

`customerInfo.Nationality`, `customerInfo.Gender` and
`customerInfo.ResidentFlag` never enter the fact digest, in any form.
Nationality and gender are impermissible underwriting factors. ResidentFlag is
nationality-adjacent and is excluded by decision. It may return only as an
explicit, documented compliance exception, never as a code default.

This is enforced in three places:

- **At runtime, on every brief.** `aecb/brief/__init__._prohibited_content()`
  refuses the brief (raising `BriefUnavailable`) in any of these cases:
  - a fact cites a prohibited field;
  - the prompt names one;
  - the prompt contains the subject's delivered value for one (values longer
    than one character).
- **In the test suite** (`tests/test_brief.py`).
- **In both evaluation scripts**, on every digest.

All three check against the one `PROHIBITED_FIELDS` tuple in
`aecb/derive/brief_facts/__init__.py`, so policy and enforcement cannot drift.
DOB-derived age is used.

## 6. Change control

The following are **model changes** and require review before deployment:

- the prompt text or output schema (`aecb/brief/prompt.py`);
- the fact digest contract (`aecb/derive/brief_facts/`);
- the model tag, endpoint or decoding options (`aecb/brief/client.py`);
- the guards (`aecb/brief/validate.py`) and the prohibited-field check
  (`aecb/brief/__init__.py`);
- the content of `config/macro_context.json`;
- enabling the brief in any deployed entry point.

`PROMPT_VERSION` in `aecb/brief/prompt.py` must be bumped for any change to
the prompt, schema or digest contract. The version:

- renders in the panel's provenance line (model tag · prompt version ·
  generation time · payload-hash prefix);
- is part of the cache key;
- is the audit anchor for "which configuration produced this brief".

The current version is `p4.1`. It covers the digest sanitisation,
identifier and birth-month removal, date-basis labelling and table fencing
described in [section 3](#3-data-flow-and-the-calculation-boundary).

## 7. Evaluation

- `scripts/check_brief.py` is the fast gate. It runs the guard test suite
  (model-free), a live run on the delinquent fixture that requires at least 3
  validated findings, and render checks. The model portion is skipped where
  Ollama is absent.
- `scripts/eval_brief.py` is the quality harness. It makes four kinds of
  assertion:
  - golden-lens: the high-value facts on the delinquent fixture must be
    cited;
  - silence: a lens must not fire without payload evidence;
  - stability: re-runs must be substantively the same;
  - latency: each generation must fit the interactive budget.

  `--fast` skips the stability re-run.
- `tests/test_brief.py` covers the deterministic parts: the digest, the
  guards, the prohibited-field policy and the client's transport controls.

**Latest result (p4.1):** `scripts/eval_brief.py` passes every assertion
except one: "delinquent: some finding cites a trajectory fact". That
assertion also fails on the previous prompt version (p4.0). It is existing
model behaviour, not a regression introduced by p4.1.

Both fixtures are committed and anonymized or synthetic. No real bureau data
is used in evaluation.

## 8. Known limitations

- **The guards check figures, citations and names, not reasoning.** A finding
  can cite real facts and still describe them imperfectly. The panel's
  framing ("verify at section N", field chips) keeps every claim one click
  from its payload evidence.
- **Guard 4 has limits.** It checks Titlecase words and ALLCAPS runs of 4 or
  more characters. All-caps tokens of 2–3 letters (AED, UAE, DPD) are treated
  as abbreviations and not name-checked. The first word of each sentence and
  a small allowlist (month names and a few report terms) are exempt.
- **`contractsHistory.PaymentBehaviour` is not read.** It arrives as an
  undocumented `'0'/'1'/null` coding. The codebase's rule for unknown
  vocabularies is a reviewed config (like `status_codes.json`), not a guess.
- **The payment-waterfall lens stays silent for now.** It groups by provider
  kind from `config/providers.json`, and that registry currently tags every
  B## code as a bank. The lens therefore cannot separate non-bank lenders
  from banks until the registry is curated with `kind: "nbfi"` entries. That
  curation is a config change under this document's change control.
- **Output is not bit-identical between runs.** Decoding is greedy
  (temperature 0, pinned seed), but GPU inference is not float-stable across
  calls, so measured re-runs give the same substance with different phrasing
  and ordering. The session cache guarantees that one application is
  assessed against one brief: one generation per payload hash, model and
  prompt version. The evaluation harness asserts substantive stability, not
  string equality. An Ollama upgrade may still shift output and should be
  treated as a model change.
