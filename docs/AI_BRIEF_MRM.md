# AI Underwriting Brief — Model Risk Documentation

This document describes the AI brief feature for model risk management:
what the model is, what it is allowed to do, how its output is controlled,
and what constitutes a change requiring review. It reflects the
implementation as of September 2026 (prompt version `p4.0`).

## 1. What the feature is

The Underwriting Brief is a side panel in the AECB report viewer that offers
a second-lens reading of the bureau payload: trajectories, cross-array
inconsistencies, behavioral patterns, structural risk, and what the file
cannot establish. It is generated on demand (a sidebar button), never
automatically, and the report is complete and fully usable without it.

The governance rule is printed in the panel itself and enforced by
architecture: **the model interprets only — it never computes figures and
never renders the decision.**

## 2. Model and deployment

| | |
|---|---|
| Model | `gpt-oss:20b` (open-weight), served by Ollama |
| Endpoint | `http://localhost:11434/api/chat` — hard-coded in `aecb/brief/client.py`, not configurable, so bureau data cannot be routed off the machine by misconfiguration |
| Decoding | temperature 0, fixed seed, JSON-schema-constrained output |
| Network | none. The model runs in-tenancy; the payload digest never leaves the host |
| Persistence | none. Briefs are cached in Streamlit session memory only, keyed by payload hash + model tag + prompt version; nothing is written to disk |

## 3. Data flow and the calculation boundary

```
payload → aecb/derive/brief_facts.py → numbered fact table (deterministic)
        → one schema-constrained model pass (facts only, never raw JSON)
        → aecb/brief/validate.py (guards below)
        → optional synthesis pass over VALIDATED findings only
        → deterministic HTML rendering (aecb/render/brief.py)
```

Every join, trajectory, aggregate and ratio interpretation is computed in
Python in `aecb/derive/brief_facts.py`. The model receives a numbered fact
table where each fact carries verbatim payload values, exact field paths and
a report-section pointer. The model's entire role is to select and connect
facts; its citations are fact IDs.

## 4. Output controls (the guards)

`aecb/brief/validate.py`, run on every response; a failing item is dropped,
never repaired, and the drop reason is logged server-side:

1. **Shape** — schema re-checked even though decoding is schema-constrained.
2. **Citations** — every cited fact ID must exist in the digest.
3. **Verbatim figures** — every numeric token in a claim must appear among
   its cited facts' values. An invented figure cannot render.
4. **Named entities** — every proper-noun-looking token must appear in a
   cited fact. A confabulated employer or counterparty cannot render.
5. **Dedup + caps** — 10 findings, 5 unknowns, 3 background notes.
6. **Derived pointers** — the "verify at section N" target comes from the
   cited facts, never from the model.

The synthesis line is re-validated against the validated findings' own text;
the unknowns list against the whole digest. Anything failing renders as
absent, not as an error.

Degradation ladder: Ollama absent → the panel's long-standing "no brief
generated" state (the sidebar names the infrastructure reason); model
timeout/malformed output after one retry → same, error to server log only;
all findings dropped → an explicit "no validated findings" state, which is
not presented as a clean bill of health.

## 5. Macro / time-sensitive context

The model's own knowledge is frozen at its training cutoff and the prompt
forbids it from stating current conditions. The only channel for
time-sensitive context is `config/macro_context.json`: a hand-curated, dated
file of short generic facts, rendered with its as-of date, connected to the
payload by the model in a visually fenced "Background context" block that
carries no severity. The file is optional; absent, the lens is off.

## 5a. Prohibited factors

`customerInfo.Nationality`, `customerInfo.Gender` and
`customerInfo.ResidentFlag` never enter the fact digest, in any form — they
are structurally invisible to the model. Nationality and gender are
impermissible underwriting factors; ResidentFlag is nationality-adjacent and
was excluded by decision on 3 September 2026 — it may return only as an
explicit, documented compliance exception, never as a code default.
DOB-derived age is used. The exclusion is enforced by assertions in both
evaluation scripts on every digest, against the `PROHIBITED_FIELDS` tuple in
`aecb/derive/brief_facts.py`, so policy and enforcement cannot drift apart.

## 6. Change control

The following are **model changes** and require review before deployment:

- the prompt text or output schema (`aecb/brief/prompt.py`)
- the fact digest contract (`aecb/derive/brief_facts.py`)
- the model tag or decoding options (`aecb/brief/client.py`)
- the guards (`aecb/brief/validate.py`)
- `config/macro_context.json` content

`PROMPT_VERSION` in `aecb/brief/prompt.py` must be bumped for any change to
the prompt, schema, or digest contract. It renders in the panel's provenance
line (model tag · prompt version · generation time · payload-hash prefix),
participates in the cache key, and is the audit anchor for "which
configuration produced this brief".

## 7. Evaluation

- `scripts/check_brief.py` — the fast gate: the guard test suite
  (model-free), a live run on the delinquent fixture asserting ≥3 validated
  findings, and render checks. Skips the model portion cleanly where Ollama
  is absent.
- `scripts/eval_brief.py` — the quality harness: golden-lens assertions on
  the delinquent fixture (the high-value facts must be cited), silence
  assertions (a lens must not fire without payload evidence), substantive
  stability across re-runs, and a latency budget. `--fast` skips the
  stability re-run.

Both fixtures are committed and anonymized; no real bureau data is used in
evaluation.

## 8. Known limitations

- The guards validate figures, citations and names — not reasoning. A
  finding can cite real facts and still characterise them imperfectly; the
  panel's framing ("verify at section N", field chips) is designed so every
  claim is one click from its payload evidence.
- Guard 4 checks Titlecase words and ALLCAPS runs of 4+ characters;
  2–3-letter all-caps tokens (AED, UAE, DPD) are treated as abbreviations
  and not name-checked.
- `contractsHistory.PaymentBehaviour` is deliberately not read: it arrives
  as an undocumented `'0'/'1'/null` coding, and this codebase's rule for
  unknown vocabularies is a reviewed config (like `status_codes.json`), not
  a guess. It may be adopted later behind such a config.
- The payment-waterfall lens groups by provider kind from
  `config/providers.json`. That registry currently tags every B## code as a
  bank, so the NBFI-vs-bank split stays silent until the registry is
  curated with `kind: "nbfi"` entries — a config change under this
  document's change control.
- Output is not bit-deterministic. Decoding is greedy (temperature 0, pinned
  seed), but GPU inference is not float-stable across calls: measured
  re-runs produce the same substance with different phrasing and ordering.
  The guarantee that one application is assessed against one brief comes
  from the session cache (one generation per payload hash + model + prompt
  version), and the evaluation harness asserts substantive stability — same
  golden facts cited, same severity profile — rather than string equality.
  An Ollama upgrade may still shift output and should be treated as a model
  change.
