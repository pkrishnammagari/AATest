# AI Analysis — Model Risk Documentation

**Version 1 · prompt version `p1.0`**

This document describes the AI Analysis for model risk review: what the
model is, what it may do, how its output is controlled and evaluated, and
which changes need review. It describes the first version of the prompts.

| | |
|---|---|
| Model owner | ____ |
| Approver | ____ |
| Model | gpt-oss-120b (open-weight): through Core42 on UAT and production; through Ollama in development (`gpt-oss:20b` on a machine too small for 120b) |
| Prompt version | `p1.0` |
| Evidence | Development measurements on gpt-oss:20b (section 8); gpt-oss-120b validation pending (section 9) |
| Status | **Not live on UAT or production** ("Coming soon"). Live only in development |

## 1. Purpose and stated use

The AI Analysis is a full-width view in the report viewer, opened from the
top-bar button, with four blocks:

| Block | What it does |
|---|---|
| 1 Fresh lens | The model proposes typed hypotheses over raw monthly tables; Python verifies each one; a findings pass writes over the fact table plus the verified results, each finding with a "so what" and a framing. The model's untyped observations render apart, as unverified. |
| 2 Non-obvious risk | Python lenses compute patterns a line-by-line review misses (card cycling, cash-like cards, minimum payments with spend, seasonal delays, pre-enquiry clean-up, lender concentration, non-bank reliance, guarantor exposure, instalments past working age, income trajectory, employer churn, selective default); the model reads them against the context register. Each finding carries a Python-derived basis (payload / payload+context / inferred). |
| 3 Checklist replay | The credit team's ten-step review, performed by the model from step packets Python built, with a tripwire audit. |
| 4 Memo and recommendation | A credit memo and a suggested outcome (Approve / Approve with conditions / Refer / Decline), written only from the validated items of blocks 1-3. |

It runs only on request (a sidebar button), one block at a time; the report
is complete without it.

**Stated use.** The analysis is an additional risk input that the
underwriter reads and weighs. **The model computes nothing**: every figure
comes from a deterministic fact or a validated item. **The underwriter
decides**: the suggested outcome is advisory and labelled, on screen and in
the copied text, *"Suggested from bureau data only; policy and application
context not applied; the underwriter decides."*

**No floor on the recommendation.** A floor ("never Approve a stale report")
is a credit-policy rule; policy is not connected to this tool, and a hidden
rule in the model's output path would be a decision rule without a policy
owner. Instead, the evaluation asserts that the delinquent golden fixture
never yields "Approve", so a change that breaks judgement is caught before
release.

## 2. Model and runtime

### 2.1 Model and environments

| | gpt-oss-120b (target) | gpt-oss-20b (development) |
|---|---|---|
| Parameters | 117B, ~5.1B active per token (mixture of experts) | 21B, ~3.6B active |
| Weights | MXFP4, ~65 GB (Ollama `gpt-oss:120b`) | MXFP4, ~13 GB |
| Context window | 128k tokens | 128k tokens |
| Tokenizer, chat format | o200k_harmony, Harmony | the same |

The same prompt is the same number of tokens to either model (A1). Reply
sizes, latency and failure modes depend on the model.

| Environment | Machine | Provider | Panel by default |
|---|---|---|---|
| Development | Mac, M4 Pro, 24 GB | Ollama `gpt-oss:20b` (`AECB_OLLAMA_MODEL=gpt-oss:20b`) | live |
| Development, final pass | Laptop, M5 Max, 128 GB | Ollama `gpt-oss:120b` (default) | live |
| UAT, production | RHEL, Python 3.9, air-gapped | Core42 (placeholder) | coming soon |

`AECB_ENV` picks the provider (`aecb/brief/providers.py`): `dev` is Ollama,
`uat` and `prod` are Core42. Unset means `prod`; an invalid value falls back
to `prod` with the panel "coming soon" and can never switch the analysis on.
Every provider has one interface (`model()`, `probe()`,
`chat(system, user, schema, effort)`), so prompts, schemas, digest, guards
and reasoning levels are identical whichever model reads the facts.

**UAT and production today.** The button shows "Coming soon" and its view
says the feature is being built; no model is called; `app.py` does not load
`aecb.brief`; the downloaded HTML has no AI control; no model service is
installed; the Core42 connector refuses every call. The server is
air-gapped: no internet, and its only outbound connection is the internal
bureau-report API. Going live needs Core42 onboarded (section 11), one
egress route to Core42 (the single exception to the air gap; still no
general internet) and this document approved. `AECB_AI_BRIEF=live` there is
a model change.

### 2.2 Ollama (development, `aecb/brief/ollama.py`)

- **Model:** a closed allow-list, `MODELS = ("gpt-oss:120b", "gpt-oss:20b")`,
  120b the default; `AECB_OLLAMA_MODEL` selects within it. Any other value
  leaves the panel unavailable with the reason shown -- never a fallback.
- **Endpoint:** `http://127.0.0.1:11434/api/chat`, pinned to loopback in code,
  never read from config or the environment. Proxy variables are ignored,
  redirects refused, responses over 4 MB rejected. `/api/chat`, not
  `/api/generate`, which returns an empty reply when given a JSON schema.
- **Decoding:** temperature 0, fixed seed (moved by one on a retry after an
  empty reply), JSON-schema-constrained output, `num_ctx` 24576,
  `num_predict` 8192, for both models; the reasoning level per pass is sent
  as `think`.
- **Timeout per model:** 300 s for 20b (measured), 600 s for 120b (estimated,
  section 9); not retried.
- **Memory:** 120b needs at least 96 GB of unified memory (comfortable at
  128 GB); with less, part of it runs on the CPU, many times slower.
- **Server:** Ollama 0.34.2; an upgrade is a model change. The digest never
  leaves the machine.

### 2.3 Core42 (UAT and production, `aecb/brief/core42.py`)

A placeholder with no network code (test-enforced): `probe()` reports "not
onboarded yet" and `chat()` refuses. The connector to be built pins its
endpoint and model id in code (never in config or the environment), reads
its API key from `AECB_CORE42_API_KEY` only, uses HTTPS with certificate
verification, refuses redirects, caps response size and times out. It sends
plain system and user messages (Harmony is applied by Core42), the pass
schemas unchanged through `response_format`, and each pass's level through
`reasoning_effort` if offered; reasoning output, if returned, is never
parsed as the answer. Section 11 lists what onboarding must settle.

**Both providers:** analyses are cached in session memory only (key: payload
hash, provider, model, prompt version); nothing is written to disk.

### 2.4 Reasoning level per pass

Declared beside each prompt (`EFFORT` in `aecb/brief/prompts/`). Reasoning
tokens are most of every reply.

| Pass | Level | Why (gpt-oss:20b) |
|---|---|---|
| Lens H, lens W, risk | `low` | Replies 70-90% smaller; every evaluation assertion met on the development runs |
| Checklist | `medium` | At `low` it marked the returns step clear despite its tripwire in two of four runs |
| Memo | `medium` | At `low` its drivers lost their figures |

gpt-oss-120b runs the same levels until its evaluation says otherwise (A4).

## 3. Data flow and the calculation boundary

```
payload -> brief_facts/            numbered fact table (deterministic Python)
        -> brief_facts/steps.py    ten step packets with their arithmetic facts
        -> brief_facts/tables.py   raw monthly tables, contracts aliased K1..Kn
        -> prohibited-field check over every text the model will see
Block 1  pass H: tables + headline index -> typed hypotheses (closed grammar)
         hypotheses/verify.py -> confirmed / not supported become [verified] facts
         pass W: payload lenses + tripwire and validity step facts + verified facts
                 -> findings, validated against exactly that set
Block 2  risk facts + context register + employment facts + headline index -> validated
Block 3  step packets -> validated per step + tripwire audit
Block 4  validated items of blocks 1-3 (V001...) -> memo, re-validated
-> deterministic HTML rendering (aecb/render/analysis.py)
```

Every join, trajectory, aggregate, day count, expiry comparison and window
test is computed in Python, one module per lens in `aecb/derive/brief_facts/`.
Every fact carries verbatim payload values, its field paths and the report
section where it can be checked. The model selects, connects and judges
facts, and cites them by id.

- **Step packets** hold, per step, the facts in that step's report section
  and the step's arithmetic (days since enquiry, document expiry, returns in
  6 months, utilisation and over-limit, late months in 36, applications in
  90 days), and name its tripwires.
- **Raw tables** give pass H plain integers: per contract a summary line and
  its reported months (balance; a card's limit where it changes; days delayed
  and overdue only when not both 0; `-` for not delivered, so a missing delay
  is never a clean month; identical consecutive months collapsed). 36 months,
  trimmed to 24 then 12 above 10,000 characters. Nothing in pass H is
  citable.
- **The memo** sees only the validated items, never the payload or digest.
- **Digest contract:** payload free text is sanitised (control characters,
  fact-id tokens and bracket syntax removed, length capped), so it cannot
  forge a fact or carry instructions; every table is fenced and the prompts
  say fenced text is data; no subject identifier is sent; age, not birth
  month; the report date carries its basis; missing delay evidence reads "no
  delay reported", never "clean"; a contract is labelled by product, id and
  provider; each pass reads only its own lenses.

### 3a. The hypothesis grammar (block 1)

Pass H returns up to 12 typed hypotheses and 3 custom sentences
(`aecb/brief/hypotheses/grammar.py`). Each verifier (`verify.py`) answers
confirmed, not supported or not assessable, with the figures:

| Type | Confirmed when |
|---|---|
| `utilisation_rise_after` (card, event, months 1-12) | utilisation rises ≥ 15 points from before the event to the given months after |
| `delay_cluster` (≤ 4 calendar months) | each month carries a delay in ≥ 2 distinct years, and at most half the other months do |
| `balance_oscillation` (card, window ≤ 36) | ≥ 2 swings from ≤ 50% of the limit to ≥ 80% (needs 6 balances and a limit) |
| `limit_increase_then_utilisation` (card) | utilisation returns to its pre-increase level within 6 months |
| `closure_before_enquiry` (window ≤ 36) | a contract closed, or an overdue cleared to zero, within the window before the report date |
| `application_burst_then_delay` (window ≤ 36) | ≥ 3 applications within the window, then a delay began within 6 months |
| `income_decline_across_updates` | ≥ 2 dated usable income figures, the latest ≥ 10% below the earliest |
| `correlated_delays` (≥ 2 contracts) | first delayed months within 3 months of each other, or half the delinquent months overlap |

A hypothesis that fails the grammar is dropped with a reason. If the model
proposes none, a fixed Python candidate list is verified instead and the
block says so. **Custom observations** are never verified and never memo
input; their figures and names are checked against the tables, and they
render as "Unverified observations" (cap 3).

### 3b. The risk lenses (block 2)

Thresholds are module constants, shared with the verifiers (`patterns.py`):
balance cycling (≤ 50% to ≥ 80% twice in 24 months), cash-like card (≥ 90%
of limit for ≥ 6 months), minimum payments with spend (≥ 3 months), seasonal
delays (1-4 calendar months in ≥ 2 years), thin history (< 24 reported months
of 36), pre-enquiry clean-up (within 3 months), lender concentration (≥ 50%
of active balances), non-bank reliance (any active `nbfi` contract),
guarantor exposure (`TotalOverdueGuaranteed` > 0), instalments past age 60,
income trajectory (± 10%), employer churn (≥ 3 employers in 5 years),
selective default (delinquency confined to one provider kind or set).

**Provider kinds** come from `config/providers.json` (unknown `N##` reads as
non-bank, `T##` as telecom); a registry change is a digest change. **Sector
inference:** the model may infer an employer's sector from its name, only
into the register's closed vocabulary; the finding's basis is derived by
Python from its cites, an inferred finding is capped at watch, labelled
"inferred, verify", and can never be cited by a memo driver.

## 4. Output controls (the guards)

`aecb/brief/validate.py` runs on every response. A failing item is dropped,
never repaired.

1. **Shape** -- the schema is re-checked.
2. **Citations** -- every cited id must exist in what the block was given (a
   cite quoting one fact's exact wording resolves to that fact).
3. **Verbatim figures** -- every number in an item must appear in its cited
   texts (exact decimal comparison after removing commas). An invented
   figure cannot render.
4. **Named entities** -- every proper-noun-looking token must appear in a
   cited text. An invented employer or counterparty cannot render.

| Block | Vouched against | Further controls |
|---|---|---|
| 1 | the facts pass W read; observations against the pass-H text | grammar and alias checks; caps (10 findings, 5 unknowns, 3 background, 3 observations); a finding resting only on refuted hypotheses is held at watch; framing enum |
| 2 | the cited facts, with the sector vocabulary allowed | basis from cites; inferred capped at watch; sector only for an employer the payload names; caps (8 findings, 3 inferences); no risk fact ⇒ no model pass |
| 3 | the cited facts of the indicator's own step only | all ten steps required; status and severity enums; cap 6 per step; **tripwire audit**: a step marked clear whose packet holds a tripwire is flagged "possible miss" (the model's status stands) |
| 4 | drivers against their items; every other field against all item text | outcome and confidence enums (no outcome = block unavailable); cap 6 drivers; a driver citing an inferred item is dropped; the advisory label is added by Python |

Drop reasons are counted in each block's footer. Any failure becomes one
`BriefUnavailable` for that block, logged with its traceback; the block
shows "Not generated" and is retried on the next click; no traceback reaches
the browser. If every finding is dropped, the block says "No validated
findings", never a clean bill of health.

## 5. The context register

The model's knowledge stops at its training cutoff, and the prompts forbid
it from stating current conditions. Time-sensitive context comes only from
`config/macro_context.json`: dated (`as_of`), short, generic, topic-tagged
entries that become background facts, plus the closed sector vocabulary. It
names an owner (today "to be named (model owner)") and a quarterly review
cadence; the loader refuses a vocabulary without them. It is optional:
without it there is no background channel and no sector inference.

## 6. Prohibited factors

`customerInfo.Nationality`, `Gender` and `ResidentFlag` never enter the
digest. Nationality and gender are impermissible underwriting factors;
ResidentFlag is excluded as nationality-adjacent and may return only as a
documented compliance exception. Age (from the date of birth) is used.
Enforced against the one `PROHIBITED_FIELDS` tuple
(`aecb/derive/brief_facts/__init__.py`) at runtime on every analysis and
every user turn (a fact citing the field, the prompt naming it, or the
subject's delivered value in the prompt refuses the analysis; one-letter
and yes/no flag values are not grepped), in the unit tests and in both
evaluation scripts.

## 7. Change control

These are **model changes** and need review before deployment:

- prompt text, output schemas and the hypothesis grammar
  (`aecb/brief/prompts/`, `aecb/brief/hypotheses/`), the verifiers, their
  thresholds and the fallback candidates;
- the fact digest, the raw tables, the risk lenses and their thresholds, the
  step packets and tripwires (`aecb/derive/brief_facts/`);
- `config/providers.json` and `config/macro_context.json`;
- the block validators and guards (`aecb/brief/blocks/`,
  `aecb/brief/validate.py`) and the prohibited-field check;
- the model list, default, timeouts, endpoints, decoding options, reasoning
  levels (`EFFORT`) and the model server's version (choosing between the
  reviewed models with `AECB_OLLAMA_MODEL` is not a change; adding one is);
- the environment-to-provider map and the default panel per environment
  (`aecb/brief/providers.py`, `aecb/runtime.py`);
- switching the analysis on in UAT or production (`AECB_AI_BRIEF=live`).

**Prompt version.** `PROMPT_VERSION` (`aecb/brief/prompts/__init__.py`) is
`p1.0`, the configuration this document describes. Every model change bumps
it (`p1.1`, ...). It is part of the cache key and appears in the provenance
line (provider · model · prompt version · time · payload hash · generation
id). Each analysis has a **generation id**, written to the `aecb.audit` log
per block and to every feedback line, so a memo can be traced to its run.

## 8. Evaluation

### 8.1 The harness

The scripts read `AECB_ENV` and `AECB_OLLAMA_MODEL` from
`~/etc/aecb-analyzer/aecb.env` as the app does and print the model first;
`AECB_ENV=uat` evaluates Core42 (the onboarding evidence).

- `scripts/check_brief.py` -- fast gate: the model-free guard suite, then a
  live fresh lens (≥ 3 validated findings) and risk block on the delinquent
  fixture, and render checks.
- `scripts/eval_brief.py` -- quality harness over the three committed
  fixtures, a stability re-run and an expired-Emirates-ID variant. It
  asserts: the golden facts are cited; lenses stay silent without evidence;
  the model (not the fallback) proposed hypotheses and a finding cites a
  verified fact; every planted risk pattern yields its fact (and none on the
  archive fixture), with a Python basis and nothing inferred above watch;
  all ten steps judged and the tripwire steps not clear on the delinquent
  fixture, the documents step high risk on the expired-ID variant; a memo
  with at least two cited drivers and seven of nine sections, and **never
  "Approve" on the delinquent fixture**;
  stable re-runs; each block within 400 s and each analysis within 1,200 s.
  It prints per-pass tokens, levels, retries and the memo drivers.
  `--effort checklist=low,memo=low` tries other levels for one run only.
- `scripts/token_budget.py` -- every pass's prompt tokens on the three
  fixtures, counted by the model server without generating (about a minute).
- Unit tests cover the deterministic parts: digest, guards, prohibited
  fields, packets, grammar, verifiers, lenses, audit, memo validation,
  transport controls, routing and the Core42 placeholder.

Fixtures are anonymized or synthetic; no real bureau data is used.

### 8.2 Feedback and monitoring

Where the panel is live, the sidebar takes one thumbs up / down and an
optional comment per analysis, appended to `$AECB_FEEDBACK_DIR/feedback.jsonl`
(0700/0600, outside the application tree) with the generation id, model and
prompt version; the verdict is also audit-logged, the comment never. The
model owner reviews the down-vote rate per prompt version and the outcomes
against actual decisions; a rising rate triggers change control (section 7),
not a runtime change.

### 8.3 Development evidence -- measured with gpt-oss:20b on these prompts

Development Mac (M4 Pro, 24 GB), Ollama 0.34.2, `gpt-oss:20b`, `p1.0`
prompts. Ollama's own counts; replies include reasoning.

**Run so far:** the unit suite, `check_brief.py`, and one generation of all
four blocks per fixture checked with the evaluation's assertions (all
passed). **The full evaluation (`eval_brief.py`, about 15 minutes) has not
been run on these prompts with gpt-oss:20b.**

| Pass (level) | Prompt tokens: delinquent / patterns / archive | Delinquent run: reply tokens, time |
|---|---|---|
| Lens H (low) | 4,862 / 2,779 / 2,842 | 169, 4 s |
| Lens W (low) | 6,519 / 5,566 / 4,359 | 907, 29 s |
| Risk (low) | 2,265 / 2,570 / 1,554 | 643, 17 s |
| Checklist (medium) | 5,299 / 4,246 / 3,807 | 2,053, 43 s |
| Memo (medium) | 2,044 / 2,135 / 1,625 | 3,229, 68 s |
| Whole analysis | 20,989 / 17,296 / 14,187 | 7.0k, 2.7 min |

Prompt tokens are from `token_budget.py` (pass W reads the fallback's
verified facts and the memo canned items, so the input is fixed); the
delinquent run's actual prompts totalled 20.3k. Other fixtures, whole
analysis: patterns 7.4k reply tokens (2.8 min), archive 5.9k (2.1 min). The
`medium` passes vary run to run (memo 1.4k-3.2k, checklist 2.0k-2.5k).

**Kept on evidence.** `RULES_COMMON` is kept word for word (a compressed
version lost three findings to the figure guard at `low`); the checklist's
one-status-per-line table is kept (as a paragraph it made `low` mark tripwire
steps clear); the risk pass stays separate from pass W (its facts in W
displaced a golden finding).

**Pass W at `low`.** In two of seven distinct decodes the model attached a
figure it did not cite ("90 days") to the unconverted applications, and the
figure guard correctly dropped the finding. If the full evaluation fails
that golden, the fallback is pass W at `medium` (`p1.1`, about 3k-6k more
reply tokens per analysis).

## 9. Validation on gpt-oss-120b (pending)

No 120b run has been made (the development Mac cannot load it). It runs on
the org laptop (M5 Max, 128 GB, Ollama 0.34.2) and, at onboarding, on
Core42. Results go in the last column; section 12's estimate is then
replaced.

| # | Assumption | Check (org laptop) | If refuted | Result |
|---|---|---|---|---|
| A1 | Prompt tokens equal 20b's (same tokenizer and template) | `token_budget.py` within ±5 of section 8.3 | Re-baseline sections 8.3 and 12 | pending |
| A2 | The 20b workarounds are harmless on 120b and stay (seed-moving retries, 8,192 cap, quoted cites, confirmed-facts pointer line, guards) | `eval_brief.py` passes with few or no retries | Fix a guard that rejects correct output under change control | pending |
| A3 | The reasoning levels work on 120b (one template) | `low` passes reply in hundreds of tokens, `medium` in thousands | Raise with Ollama before any 120b conclusion | pending |
| A4 | The current levels are safe on 120b; `low` everywhere is unproven | Optional `--effort checklist=low,memo=low`, twice, decision rule below | Keep the levels | pending |
| A5 | Replies no longer than 20b's 7.0k per analysis | The eval's whole-analysis reply tokens | Replace section 12's figure; revisit `k` | pending |
| A6 | 2-4 minutes per analysis, plus 20-60 s first load | The eval's timings; `ollama ps` 100% GPU | Check for a CPU split; else take the 120b evidence from Core42 | pending |
| A7 | 600 s covers the worst single call | No timeout in any run | Raise the timeout (model change) | pending |
| A8 | `num_ctx` 24576 and `num_predict` 8192 suffice | No empty reply after three attempts; `ollama ps` shows 24576 | Raise both (model change) | pending |
| A9 | 120b clears every assertion, the pass-W applications golden at `low` included | The eval's assertions | Pass W at `medium` (`p1.1`) | pending |
| A10 | Core42 behaves like local Ollama | `AECB_ENV=uat scripts/eval_brief.py` at onboarding | Core42's run governs UAT and production | pending |

**The estimate.** Generation on unified memory is bound by bytes read per
token: 120b reads about 1.4x what 20b reads (5.1B vs 3.6B active). 20b runs
at 40-50 tokens a second on the M4 Pro (273 GB/s); the M5 Max is assumed at
about 600 GB/s (to confirm), giving 120b 40-70 tokens a second. A 7.0k-token
reply then takes 100-175 s, plus under 40 s of prompt processing: **2-4
minutes per analysis**, plus 20-60 s to load ~65 GB on a first call. Memory:
~65 GB of weights, ~1-2 GB of KV cache at 24k, a few GB of buffers -- about
70 GB against the ~96 GB macOS lets the GPU use of 128 GB. **Timeout:** the
worst legitimate call -- first load, the 6.5k-token pass W prompt and a
reply to the 8,192 cap -- is about 280 s at 40 tokens a second and 450-500 s
on a 96 GB laptop at ~25; hence 600 s. Run times: `token_budget.py` 1-3 min,
`check_brief.py` 1-2 min, `eval_brief.py` 12-20 min.

**Validation plan (org laptop).**

1. Download the repository ZIP from GitHub and unpack it in
   `/Users/prabhu.krishna/FH/Projects/AI-REPO/AECB_Analyser`.
2. Install Ollama 0.34.2; `ollama pull gpt-oss:120b` (~65 GB).
3. `~/etc/aecb-analyzer/aecb.env` (mode 0600) with `AECB_ENV=dev` only.
4. `/usr/bin/python3 scripts/token_budget.py` -- A1. Green: header names
   `gpt-oss:120b` and `p1.0`; every cell within ±5 of section 8.3.
5. `ollama ps` within 5 minutes -- A6, A8. Green: `gpt-oss:120b`, 100% GPU,
   context 24576.
6. `/usr/bin/python3 scripts/check_brief.py`. Green: `OK`, ≥ 3 findings.
7. `/usr/bin/python3 scripts/eval_brief.py`, once -- A2, A3, A5-A9. Green:
   `OK`, no retries, delinquent reply ≤ ~7.0k tokens, blocks within budget.
8. Optional -- A4: `/usr/bin/python3 scripts/eval_brief.py --effort
   checklist=low,memo=low`, twice.
9. Record results here and in section 12; note the outcome in DECISIONS
   AI-13 and the changelog. Any resulting change is a model change.

**Decision rule for checklist or memo at `low`.** Across both runs of step 8:
every delinquent run (six in all) has step 05 (returns) not clear; every
memo driver carries its figures and no item-id residue; every other
assertion passes. If all hold, the model owner chooses `low` for both models
or a map per model (a model change); otherwise the current levels stay.

## 10. Known limitations

**[20b]** marks behaviour observed on gpt-oss:20b; it may not hold on 120b,
and its safeguards stay until section 9 shows otherwise (A2).

- **The guards check figures, citations and names, not reasoning.** A
  finding can cite real facts and describe them imperfectly; every claim is
  one click from its evidence ("Verify at §N").
- **The name guard checks Titlecase words and ALLCAPS runs of 4+.** Shorter
  capitals (AED, UAE, DPD), sentence-initial words and a small allowlist are
  not checked.
- **Unread or stub inputs.** `PaymentBehaviour` is unread (undocumented
  coding). `providers.json` is a stub: a non-bank lender under a code not
  tagged `nbfi` is not separated by the provider-kind lenses.
- **Not bit-identical between runs** [20b; any GPU serving]. Greedy decoding
  is not float-stable; the session cache keeps one analysis per payload, and
  the evaluation asserts substantive stability.
- **Wording is load-bearing at `low`** [20b]. A prompt's exact words steer
  the `low` passes; any prompt edit needs the evaluation, not only unit
  tests. The model sometimes borrows an uncited figure; the guard drops the
  finding (nothing wrong renders, but the finding is lost).
- **The suggested outcome can flip between Refer and Decline** on a
  borderline file [20b], with identical findings. The evaluation asserts
  only Approve / not-Approve agreement.
- **Empty replies** [20b] under constrained decoding, reproducible on an
  identical request: up to three attempts, each with the seed moved, then
  the block is retried on the next click.
- **Cites as quotes** [20b]: resolved to the id only when the quote matches
  exactly one fact.
- **Step 2 is thin by design** (age only; policy not connected).
  **Verified facts** are only as good as the definitions in section 3a; "not
  supported" means the defined test failed. **Sector inferences** are guesses
  from a name, bounded by the vocabulary. **Risk lenses** state patterns, not
  causes. **Unverified observations** passed only the figure and name checks.
  **The memo** names any block it did not have.
- **All timings, reply sizes and failure rates are 20b's** [20b]; the 120b
  figures in sections 9 and 12 are estimates.

## 11. Core42 onboarding checklist

The analysis goes live on UAT or production only after every item is
settled and this document is approved.

| Item | Status |
|---|---|
| Endpoint URL and hosting region | Open |
| Authentication scheme and key rotation | Open |
| Model id and version for gpt-oss-120b, pinned as `MODEL` in `aecb/brief/core42.py`; weights and precision served | Open |
| Structured output via `response_format` / `json_schema` for every keyword used (`enum`, `pattern`, `minItems`, `maxItems`, integer `minimum`/`maximum`, optional properties without `additionalProperties`); a strict mode that rejects one needs a reviewed schema decision | Open |
| Harmony applied server-side; plain system and user messages accepted | Open |
| Context and output limits: at least 16k tokens per call (6.5k prompt + 8,192 reply) | Open |
| Decoding options (temperature, seed) | Open |
| Reasoning control (`reasoning_effort` or equivalent) so each pass's level is honoured; otherwise section 12's budget does not hold | Open |
| Reasoning output field (never parsed as the answer); billing of reasoning tokens; prompt-cache discount | Open |
| **Egress route** from the air-gapped server to Core42 (firewall rule, proxy if required): the single exception to the air gap, opened only for go-live | Open |
| **TLS**: certificate verification against Core42's chain; a CA bundle if the estate re-signs certificates | Open |
| Data residency, retention and no-training terms; the `DATA_NOTE` shown to users | Open |
| An `aecb.audit` line per generation (subject, provider, model, user) | Open |
| `AECB_ENV=uat scripts/eval_brief.py` against Core42; results in section 8, compared with sections 9 and 12 (A10) | Open |
| Model owner and approver named and signed off | Open |
| Context register owner named; first quarterly review dated | Open |
| The placeholder's no-network test in `tests/test_brief.py` removed when the connector is built | Open |

## 12. Token budget and pricing

Per analysis, delinquent fixture (the largest input), gpt-oss:20b measured
(section 8.3): **20,349 tokens in, 7,001 out** (reasoning included). Range
across the fixtures: 13.9k-20.3k in, 5.9k-7.4k out. Each call needs at least
16k tokens of context; 24,576 is configured locally.

    tokens in  = N x 20,349 x k        tokens out = N x 7,001 x k
    cost       = tokens in / 1e6 x price in  +  tokens out / 1e6 x price out

`N` is analyses a month; prices are Core42's per million tokens (not yet
known). `k` = 1.2 is an assumed contingency for retried passes,
regenerations and the spread of the `medium` passes; the audit and feedback
logs give the real rate once live.

| Analyses a month (k = 1.2) | Tokens in | Tokens out |
|---|---|---|
| 500 | 12.2 million | 4.2 million |
| 2,000 | 48.8 million | 16.8 million |

**gpt-oss-120b planning estimate:** the same figures -- about 20,349 tokens
in (A1) and at most about 7,000 out (A5) -- so at `k` = 1.2:

    cost per analysis  =  0.0244 x price in  +  0.0084 x price out

To be replaced by the org-laptop measurement (section 9), then by Core42's
own counts. Caveats:

- **Reasoning control.** If Core42 cannot honour the per-pass levels and
  every pass runs at `medium`, output approaches the 15.2k tokens per analysis
  measured on gpt-oss:20b with every pass at `medium`: about 36.5 million
  output tokens a month at 2,000 analyses, and `0.0244 x price in + 0.0182 x
  price out` per analysis -- the planning upper bound.
- **Reply length is model-dependent**; a longer 120b measurement replaces
  the 7.0k.
- **Billing follows Core42's counts**, including whether reasoning tokens are
  billed as output.
