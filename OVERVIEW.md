# FH AECB Analyser — How It Works

*A non-technical description of the product, the workflow and the pipeline.
For the engineering view, see [ARCHITECTURE.md](ARCHITECTURE.md).*

---

## 1. What this is

Finance House receives credit bureau reports on loan applicants from the
**Al Etihad Credit Bureau (AECB)**, the UAE's national credit bureau. Those
reports arrive as a machine file — a raw data dump of seventeen different lists
covering the customer's identity, employment, income, every credit facility they
hold, three years of month-by-month payment conduct, every recent credit
application, and any bounced cheques.

Read raw, that file is unusable for a decision. It contains hundreds of rows,
repeats the same fact many times over, mixes three different date formats, and
buries the two or three things that actually decide a case among everything
else.

**The AECB Analyser turns that file into one scannable underwriting screen.**
Its single purpose is to collapse the time it takes a Risk & Relationship
Manager (RRM) to reach a decision on one customer.

It is a **read-only viewer**. It does not score, approve, decline, or write
anything back. It presents what the bureau said, arranged so it can be read.

---

## 2. The governing rule

One principle sits above every other decision in this product:

> **No fabricated value ever reaches the screen.**

Everything shown is either a figure AECB delivered, or a figure arithmetically
derived from delivered figures — and the screen always says which. Where the
bureau reported nothing, the screen says *"not reported"* explicitly rather than
showing a blank or a zero.

That distinction is not pedantry. On a credit screen, **"reported as zero" and
"not reported" mean opposite things**. A zero means the customer was checked and
was clean. A blank means nobody looked. A screen that renders both the same way
turns missing data into a clean record — which is the single most dangerous
failure this product could have.

Consequences of this rule that are visible throughout the app:

| Practice | What it means on screen |
|---|---|
| **Provenance marks** | Every figure carries a small `delivered` or `derived` tag with a hover explaining exactly where it came from. |
| **Grey means unknown** | In the 36-month conduct grid, a month the bureau never filed is grey — never green. Green is reserved for a month the bureau actually confirmed as current. |
| **Held-open panels** | Where a number is wanted but the bureau doesn't supply it and the business hasn't decided how to compute it, the panel says *"To be built"* rather than showing a plausible guess. A plausible wrong number is worse than an absent one. |
| **Nothing describes one file** | No sentence on screen may be true only of this particular customer. Notes explain the *rule* ("a trend needs two dated figures"), never the *file* ("3 of 5 rows are null"). |
| **Verbatim delivery** | Where the business instructed that a bureau figure be shown as-is, it is printed exactly as delivered — no rounding, relabelling or translation. |

---

## 3. The workflow — how a report gets made

The whole pipeline runs in a fraction of a second, every time the page loads.

```
   ┌──────────────────┐
   │  1. GET PAYLOAD  │   An archived AECB report (a JSON file).
   └────────┬─────────┘   Either picked from the built-in library,
            │             or uploaded by the user.
            ▼
   ┌──────────────────┐   Trailing spaces stripped, empty values made
   │  2. CLEAN UP     │   consistent, the bureau's two different spellings
   └────────┬─────────┘   of "contract category" reconciled, and every
            │             expected list guaranteed to exist (an absent
            │             section becomes an empty one, not an error).
            ▼
   ┌──────────────────┐   The single most important derived fact: WHEN was
   │  3. ANCHOR       │   the bureau actually queried? Everything on the page
   │     IN TIME      │   — the 36-month window, the 90-day application
   └────────┬─────────┘   window, the 6-month returns window, report validity
            │             — is measured back from this one date.
            ▼
   ┌──────────────────┐   Facts repeated by several banks are collapsed into
   │  4. INTERPRET    │   one entry that remembers who reported it. Contracts
   │                  │   are joined to their monthly payment history. Score
   └────────┬─────────┘   bands, income figures and returns are resolved into
            │             what can honestly be shown.
            ▼
   ┌──────────────────┐   Eight sections are rendered in order, each one
   │  5. ASSEMBLE     │   receiving the same interpreted data. Fonts, colours,
   │     THE PAGE     │   styles and interactive behaviour are all folded into
   └────────┬─────────┘   the same file.
            │
            ▼
   ┌──────────────────┐   ONE self-contained HTML document — no links to the
   │  6. DELIVER      │   internet, no external images or fonts. Displayed in
   └──────────────────┘   the browser, and downloadable as a single file that
                          can be filed against the credit application and
                          opened years later on any machine, offline.
```

### Why "self-contained" matters

The server this runs on is **air-gapped** — it has no internet connection. So
the report cannot fetch a font, a logo, or a charting library from anywhere. All
of that is baked into the file itself.

The same property gives a second benefit for free: the **Download** button
produces one file that is a permanent, faithful record of what the underwriter
saw. It needs no companion assets, no network, and no software beyond a browser.

---

## 4. What the user does

The application interface is deliberately thin — a sidebar of payload controls,
and the report filling the rest of the window.

1. **Choose a payload.** Either select one of the anonymized bureau files
   bundled with the app, or upload a new one. An upload renders only in the
   session that supplied it — nothing is written to disk, and no other session
   can see or list it. (The upload path is also where a direct connection to
   AECB's systems will plug in later; until that exists, the picker and
   uploader stand in for it.)
2. **Read the report.** The full screen is the deliverable.
3. **Download it** as a standalone HTML file, to file against the application.

There is no login, no data entry, no state saved between sessions. Loading a
different payload simply re-renders the page.

---

## 5. What the screen shows

### The frame

- **Top bar** — the Finance House brand, and the *report validity strip*: is
  this report still usable, when was it pulled, how far through its 30-day
  look-back window is it, and when does it lapse. Validity lives here rather
  than in a section because it qualifies everything below it.
- **Left spine** — a numbered rail of dots, one per section. It tracks your
  scroll position, names each section on hover, and jumps you to it on click.
- **Right rail — "Underwriting Brief"** — a panel reserved for an AI narrative
  reading of the payload. It is built but *not enabled*: no language model is
  available on the air-gapped server, so the panel states plainly that no brief
  was generated rather than inventing narrative. It loads closed; the *AI
  Analysis* button in the top bar opens it.

### The eight sections, and the question each answers

| # | Section | The question it answers |
|---|---|---|
| **01** | Identity & demographics | Who is this person, and what identifiers have they used over time? Emirates ID, passport (with expiry), mobile numbers, e-mail, addresses — each showing which banks reported it and what earlier values are on file. |
| **02** | Score & bureau history | How does the bureau grade them, and how long is their credit file? The score, both the AECB and FH risk bands, a proportional gauge showing where the score sits, and how many months of history exist. |
| **03** | Income & employment | What do they earn, where do they work, and how confident can we be in that figure? Employers with their tenure, salaries as delivered, and a timeline plotting the two together — but only where the bureau supplied a date to plot against. |
| **04** | Cheque & direct-debit returns | Have they bounced anything? In the UAE this is a first-order adverse signal. Each returned instrument as delivered, split into a recent 6-month review window and everything earlier, with a matching timeline. |
| **05** | Worst statuses | What is the worst thing on their file? Three windows side by side — the bureau's delivered 24-month worst status with its maximum payment delay, a 36-month window awaiting a business decision, and a lifetime adverse count. |
| **06** | Active credit facilities — overview | What is the total exposure, and how is it split? Four category cards (instalments, credit cards, non-instalments, services), each split between what they hold as *main borrower* and what they *guarantee for someone else* — because Finance House lends against those differently. |
| **07** | Credit facilities — detail & 36-month conduct | How have they actually behaved, month by month? A heatmap of every facility across 36 months, colour-coded by how many days past due, grouped into active facilities, recent closures, older closures and quiet services. |
| **08** | Recent applications | How much credit have they been seeking elsewhere? A timeline where the last 90 days — the window that matters for underwriting — is deliberately stretched to occupy most of the width, and the years behind it are compressed into the remainder. |

Throughout, hovering anything explains it: where the figure came from, what
window it covers, and what an absence means.

---

## 6. Where the knowledge comes from

The bureau payload does not contain everything the screen needs to show. Two
kinds of knowledge are supplied alongside it:

**Bureau vocabularies** — AECB publishes what its status codes mean and how
severe each one is, what its role and payment-frequency codes mean. The app
mirrors that published table; it does not invent severity.

**Finance House policy** — the score cut-offs, the credit-history vintage bands,
how many days a report stays valid, the salary floor below which a figure is
treated as a provider placeholder rather than a real income, and how many months
back the returns review window runs.

All of it lives in editable configuration files, entirely separate from the
code, each documenting *why* its values are what they are. This matters because
policy changes without the product changing: a shifted score cut-off or a
lengthened review window is an edit to a settings file, not a code change.

One configuration file is currently a **stub**: the registry mapping bureau
provider codes (`B08`, `T05`) to real bank names. Until it is filled in, the
screen shows the code itself rather than inventing a name.

---

## 7. Quality controls

Because the risk here is *silently wrong output* rather than a crash, the
controls are built to catch exactly that.

**The no-fabrication check.** An automated check renders the report and fails
the build if a value the payload genuinely carries has gone missing from the
page, or if any external link has appeared in the output. It also confirms that
the figures the business asked to see verbatim really are on screen unchanged,
by reading them back out of the specific elements meant to carry them.

**The geometry harness.** The report has *two* independent layout dimensions —
the window width, and whether the AI brief rail is open — so a change that looks
right in one corner routinely breaks another. A set of development tools renders
the page in headless Chrome at ten widths in both rail states, records the exact
rendered size of every element, and then asserts that a change stayed inside the
sections it was meant to touch. A companion tool feeds through synthetic
payloads shaped differently from the reference customer — no e-mail, an expired
passport, a missing score band — so paths the real file never exercises still
get rendered.

**Install-time verification.** Deploying to the server renders a report as the
final installation step and refuses to declare success if the output contains an
external reference.

---

## 8. Deployment

The target environment is a **Linux server with no internet access**, running an
older Python. Both facts shape the delivery:

1. On a connected machine, a script downloads every dependency in advance as a
   pre-compiled bundle — and **fails loudly** if anything resolved to a form
   that would need compiling or the wrong processor architecture, either of
   which would only surface as a broken install later.
2. The bundle and the source are copied to the server.
3. An install script sets it up with the network explicitly disabled, so a
   missing dependency fails immediately and visibly rather than hanging.
4. The app is started as a web server on the internal network.

Fonts are handled the same way: downloaded once on a connected machine and
embedded permanently into the application's stylesheet.

---

## 9. What is deliberately unfinished

These are open business decisions, not defects. In each case the product holds
the space open rather than guessing:

- **The 36-month worst status.** AECB delivers no such figure, and how the
  window should be measured is undecided. The panel says *To be built*.
- **A contradictory bureau field.** One delivered field claims a current payment
  delay that every other field in the file contradicts. Nothing on screen reads
  it, by decision, until AECB explains the discrepancy — showing it would state
  a contradiction the file cannot resolve.
- **Score cut-offs.** The configured Finance House bands and the band AECB
  actually delivered disagree at the margin for the reference customer. The
  **delivered band wins**, and the cut-offs are flagged as needing reconciliation
  against the FH scorecard.
- **Provider names.** The code-to-name registry is a stub, so provider codes show
  as codes.
- **Debt-service ratio and application context** (product, amount, tenor) have no
  source in a bureau payload at all. They would need a separate input.
- **A real adverse sample payload.** The reference customer is entirely clean —
  no missed payments anywhere. A deliberately delinquent synthetic file is
  bundled alongside it, so every adverse display path (the days-past-due colour
  ramp, severe status colours, dispute flags) renders in the app itself; a
  real — anonymized — adverse report would still be the better test.

---

## 10. In one paragraph

A bureau payload goes in; a single self-contained HTML underwriting screen comes
out. Between the two, the data is cleaned, anchored to the date the bureau was
actually queried, de-duplicated across the banks that reported it, joined to
three years of monthly payment history, and laid out as eight sections that each
answer one underwriting question. Bureau vocabularies and Finance House policy
live in configuration rather than code. Nothing is invented; every figure is
marked as delivered or derived; and an absence of data is always shown as an
absence, never as a zero and never as good news.
