# FH AECB Analyzer — How It Works

*A non-technical description of the product, the workflow and what the screen
shows. For the engineering view, see [ARCHITECTURE.md](ARCHITECTURE.md).*

---

## 1. What this is

Finance House receives credit bureau reports on loan applicants from the
**Al Etihad Credit Bureau (AECB)**, the UAE's national credit bureau. A report
arrives as a machine file: a raw data dump of seventeen lists covering the
customer's:

- identity, employment and income;
- every credit facility they hold;
- three years of month-by-month payment conduct;
- every recent credit application;
- any bounced cheques.

Read raw, that file cannot support a decision. It holds hundreds of rows,
repeats the same fact many times, mixes three date formats, and buries the few
things that decide a case among everything else.

**The AECB Analyzer turns that file into one scannable underwriting screen.**
Its purpose is to shorten the time a Risk & Relationship Manager (RRM) needs to
reach a decision on one customer.

It is a **read-only viewer**. It does not score, approve, decline, or write
anything back. It presents what the bureau said, arranged so it can be read.

---

## 2. The governing rule

One principle sits above every other decision in this product:

> **No fabricated value ever reaches the screen.**

Everything shown is either a figure AECB delivered, or a figure calculated from
delivered figures, and the screen always says which. Where the bureau reported
nothing, the screen says *"not reported"* instead of showing a blank or a zero.

On a credit screen, **"reported as zero" and "not reported" mean opposite
things**. A zero means the customer was checked and was clean. A blank means
nobody looked. A screen that shows both the same way turns missing data into a
clean record, which is the most dangerous failure this product could have.

These practices follow from the rule and are visible throughout the app:

| Practice | What it means on screen |
|---|---|
| **Provenance marks** | Figures carry a small `delivered` or `derived` tag, with a hover explaining where the figure came from. |
| **Grey means unknown** | In the 36-month conduct grid, a month the bureau never reported is grey, never green. Green is reserved for a month the bureau actually confirmed as current. |
| **Derived, and marked so** | Where the business needs a figure the bureau does not supply (the 36-month worst status), the app calculates it from the bureau's own evidence and marks it *derived*. It never lets that figure look better than the bureau's own figure for the shorter period. |
| **The bureau's figure wins** | Where the bureau delivers a figure, such as its risk band, that figure is shown even when the bank's own configured cut-offs would say otherwise. The disagreement is flagged for review. |
| **Nothing describes one file** | No sentence on screen may be true only of this particular customer. Notes explain the *rule* ("a trend needs two dated figures"), never the *file* ("3 of 5 rows are empty"). |
| **Verbatim delivery** | Where the business asked for a bureau figure to be shown as-is, it is printed exactly as delivered, with no rounding, relabelling or translation. |

---

## 3. The workflow: how a report is made

The whole pipeline runs in a fraction of a second.

```
   ┌──────────────────┐   The underwriter enters a CB subject id. The app
   │  1. GET REPORT   │   queries the bank's internal bureau-report service
   └────────┬─────────┘   and checks that the answer really is an AECB report.
            ▼
   ┌──────────────────┐   Stray spaces are removed, empty values are made
   │  2. CLEAN UP     │   consistent, the bureau's two spellings of "contract
   └────────┬─────────┘   category" are reconciled, and every expected list is
            │             guaranteed to exist (an absent one becomes empty).
            ▼
   ┌──────────────────┐   The most important derived fact: WHEN was the bureau
   │  3. ANCHOR       │   queried? Everything on the page is measured back from
   │     IN TIME      │   this one date: the 36-month window, the 90-day
   └────────┬─────────┘   application window, the 6-month returns window and
            │             report validity.
            ▼
   ┌──────────────────┐   Facts repeated by several banks are collapsed into one
   │  4. INTERPRET    │   entry that remembers who reported it. Contracts are
   └────────┬─────────┘   joined to their monthly payment history. Score bands,
            │             income figures and returns are resolved into what can
            │             honestly be shown.
            ▼
   ┌──────────────────┐   Eight sections are built in order, each from the same
   │  5. ASSEMBLE     │   interpreted data. Fonts, colours and interactive
   └────────┬─────────┘   behaviour are all folded into one file.
            ▼
   ┌──────────────────┐   ONE self-contained page: no links to the internet,
   │  6. DELIVER      │   no external images or fonts. It is shown in the
   └──────────────────┘   browser and can be downloaded as a single file to file
                          against the credit application.
```

### Why "self-contained" matters

The server is **air-gapped**: it has no internet connection. The report
therefore cannot fetch a font, a logo or a charting library from anywhere, and
all of these are built into the file itself.

This brings a second benefit. The **Download** button produces one file that is
a faithful record of what the underwriter saw. It needs no companion files, no
network and no software beyond a web browser, and it opens years later on any
machine.

---

## 4. What the user does

The interface is deliberately thin: one input box, then the report filling the
window.

1. **Enter a CB subject id.** The app queries the bureau-report service, checks
   the response, and renders the report. If the returned report identifies a
   different customer from the one requested, the report still renders, under a
   prominent warning that names both ids.
2. **Read the report.** The full screen is the deliverable.
3. **Download it** as a standalone file to keep with the application.

The application has no login of its own. In production it sits behind the
bank's secure single-sign-on gateway; UAT, the test installation, is opened
directly on the internal network without sign-on. Every query is recorded in
an audit log: which subject was queried, by whom (the signed-on user, in
production) and with what outcome.

Each report the service returns is also kept as a reference copy in a
restricted folder on the server, outside the application. How long these
copies are kept is set by the bank's data-retention policy.

---

## 5. What the screen shows

### The frame

- **Top bar**: the Finance House brand, and the *report validity strip*. It
  shows whether the report is still usable, when the bureau was queried, how
  far through its 30-day validity window it is, and when it lapses. It also
  shows which bureau product was requested. Validity lives here, not in a
  section, because it qualifies everything below it.
- **Left spine**: a numbered column of dots, one per section. It tracks your
  scroll position, names each section on hover, and jumps to it on click.

### The eight sections, and the question each answers

| # | Section | The question it answers |
|---|---|---|
| **01** | Identity & Demographics | Who is this person, and what identifiers have they used over time? Emirates ID, passport (with expiry), phone numbers, e-mail and addresses. Each shows which banks reported it and what earlier values are on file. |
| **02** | Score & Bureau History | How does the bureau grade them, and how long is their credit file? The score on a curved dial showing where it sits within the bank's risk bands, the delivered FH and AECB bands, and how many months of credit history exist. |
| **03** | Worst Statuses | What is the worst thing on their file? Three windows side by side: the bureau's 24-month worst status with its maximum payment delay; a 36-month window calculated from the bureau's conduct evidence (marked as derived); and a lifetime count of adverse statuses. |
| **04** | Income & Employment | What do they earn, where do they work, and how far can that figure be trusted? Employers with their tenure, salaries as delivered, and a timeline plotting the two together, but only where the bureau supplied a date to plot against. |
| **05** | Cheque & Direct-Debit Returns | Have they bounced anything? In the UAE this is a first-order adverse signal. Each returned instrument as delivered, split into a recent 6-month review window and everything earlier, with a matching timeline. |
| **06** | Active Credit Facilities — Overview | What is the total exposure, and how is it split? Four category cards (instalment loans, credit cards, non-instalment credit, services), each split between what the customer holds as *main borrower*, any *co-held* share, and what they *guarantee for someone else*, because the bank lends against these differently. |
| **07** | Credit Facilities — Detail & 36-Month Conduct | How have they actually behaved, month by month? A grid of every facility across 36 months, coloured by how late payments were, grouped into active facilities, recent closures, older closures and quiet services. |
| **08** | Recent Applications | How much credit have they been seeking elsewhere? A timeline in which the last 90 days, the window that matters for underwriting, is stretched to fill most of the width, and the years before it are compressed into the rest. |

Sections 02 and 03 share one row: the score beside the worst statuses.

Throughout, hovering over anything explains it: where the figure came from,
what period it covers, and what a missing value means.

### The AI Analysis (coming soon on UAT and production)

The app has an *AI Analysis* view: a reading of the report produced by a
language model. It replaces the report on screen while it is open, and it
has four blocks:

| Block | What it gives the underwriter |
|---|---|
| **Fresh lens** | An independent reading of the file. The model suggests patterns worth testing in the month-by-month figures; the app tests each one with its own arithmetic, and the findings are written from the facts and those test results. Remarks the app could not test are shown apart, marked as unverified. |
| **Non-obvious risk** | Patterns a line-by-line review tends to miss, found by the app's own calculations: for example a card that swings repeatedly between half-used and nearly full, late payments that recur at the same time of year, accounts closed or arrears cleared just before the bureau was queried, most of the debt sitting with one lender, or borrowing from a non-bank lender. The model reads them against a short, dated note on current conditions that the bank maintains. A finding that rests on the model's own inference is marked "verify" and never drives the recommendation. |
| **Checklist replay** | The credit team's ten-step review, step by step, with indicators that can be copied into the credit file. A step marked clear while its own warning sign is present is flagged as a possible miss. |
| **Memo and recommendation** | A credit memo and a suggested outcome (Approve, Approve with conditions, Refer or Decline), written only from the checked findings of the first three blocks. |

It only connects facts that the app has already computed; it never
calculates figures. Every sentence is checked before it is shown: each
figure and each name must appear in the facts it cites, and anything that
fails is dropped rather than corrected. The suggested outcome is advisory and
labelled as such: the underwriter decides, and every finding links back to
the evidence on the report.

In development it uses an open-source model running on the developer's own
machine. On UAT and production it will use Core42, which is still being
onboarded. Until then the screen there shows the *AI Analysis* button marked
**Coming soon**; clicking it explains that the feature is being built and
will be switched on only after validation and approval. No model is called.
The servers have no internet access; switching the AI Analysis on would add
one approved connection, to Core42, and nothing else (see Deployment).

---

## 6. Where the knowledge comes from

The bureau file does not contain everything the screen needs. Two kinds of
knowledge are supplied alongside it:

**Bureau vocabularies.** AECB publishes what its status codes mean and how
severe each one is, and what its role and payment-frequency codes mean. The app
mirrors that published table and does not invent severity.

**Finance House policy.** This covers:
- the score bands and their cut-offs;
- the credit-history vintage bands;
- how many days a report stays valid;
- the salary floor below which a figure is treated as a placeholder rather
  than a real income;
- the length of the review windows.

All of this lives in configuration files separate from the code, and each file
documents *why* its values are what they are. Policy can therefore change
without the product changing: a moved cut-off is an edit to a settings file,
not to the program. If a required setting is missing, the report refuses to
render rather than guess.

One configuration file is still a **stub**: the list that maps bureau provider
codes (such as `B08` or `T05`) to bank names. Until it is filled in, the screen
shows the code rather than inventing a name.

---

## 7. Quality controls

The risk here is *silently wrong output* rather than a crash, so the controls
are built to catch exactly that.

**The no-fabrication check.** An automated check renders the reference reports
and fails if a value the report carries has gone missing from the page, or if
any external link has appeared. It also confirms that the figures the business
asked to see verbatim appear unchanged, by reading them back from the exact
place on the page that is meant to show them.

**The automated test suite.** Automated tests cover how the report is read and
checked, the connection to the bureau service, the security protections (no
report content can turn into active page content), the AI Analysis's checks,
and the app's screens in every environment. The tests must pass on the same
Python version the server runs.

**The layout harness.** The page's layout changes with the window width, and
a change that looks right at one width can break another. A set of
development tools renders the page at ten widths, measures every element, and
confirms that a change stayed inside the sections it was meant to touch. (The
AI Analysis view hides the report rather than reflowing it, so it does not
disturb those measurements.)

**The real-report corpus check.** Each report the service returns is kept as
a reference copy in the archive folder of the machine that fetched it, never
in the code repository. A second automated check runs on a machine that holds
a collection of these copies, with customer details masked. It runs every one
through the report and verifies for each that:

- nothing crashed, and no delivered value went missing;
- the headline figures and status labels agree with the rules, recalculated
  from the raw report;
- nothing like "None" or a blank slot reached the screen;
- no bureau value arrived that the configuration cannot interpret.

**Install-time verification.** The installation on the server finishes by
rendering a sample report. It refuses to declare success if the output
contains an external reference.

---

## 8. Deployment

The target is a **Linux server with no internet access**, running Python 3.9.
Its only connection out is to the bank's internal bureau-report service. The
missing internet access and the Python version shape delivery:

1. On a connected machine, a script downloads every dependency in advance as a
   ready-built bundle. Each file is checked against a recorded fingerprint, and
   the script fails if anything would need compiling or targets the wrong
   processor type.
2. A release package is made from the approved version of the code only. It
   leaves out development tools, tests and documentation.
3. The package and the bundle are copied to the server and installed from
   the bundle alone, with no network access. A missing or altered file
   therefore fails at once.
4. The application runs as a system service. In production it is reachable
   only through the bank's secure single-sign-on gateway. UAT is reached
   directly on the internal network, without sign-on, for testing.

The AI Analysis would add one approved connection out, to Core42, when it
goes live; nothing else on the server reaches outside the bank.

Fonts are handled the same way: they are downloaded once on a connected
machine and built permanently into the application's stylesheet.

---

## 9. What is deliberately unfinished

These are open business decisions or missing inputs, not defects. In each case
the product leaves the gap visible rather than guessing:

- **36-month worst status refinements.** The panel is calculated from the
  bureau's own conduct evidence (the whole book, closed contracts included)
  and marked as derived. Two questions are still open: whether to also
  calculate a like-for-like 24-month figure as a cross-check against the
  bureau's own, and whether a guarantor's missed payments should be flagged
  separately.
- **A contradictory bureau field.** One field claims a current payment delay
  that every other field in the file contradicts. By decision nothing on
  screen shows it until AECB explains the discrepancy.
- **Provider names.** The code-to-name list is a stub, so provider codes show
  as codes.
- **Debt-service ratio and application context** (product, amount, tenor).
  These have no source in a bureau report and would need a separate input.
- **A real adverse sample report.** The one real (anonymized) reference
  report has a clean payment record; the few returned cheques and debits it
  shows were added for testing. Two synthetic files are bundled: a
  deliberately delinquent one, so every adverse display (the late-payment
  colours, severe statuses, dispute flags) can be seen in the app, and one
  that plants the patterns the AI Analysis looks for. A real, anonymized
  adverse report would still be the better test.

---

## 10. In one paragraph

A CB subject id goes in, and a single self-contained underwriting screen comes
out. Between the two, the bureau's report is:

- cleaned;
- anchored to the date the bureau was queried;
- de-duplicated across the banks that reported it;
- joined to three years of monthly payment history;
- laid out as eight sections, each answering one underwriting question.

Bureau vocabularies and Finance House policy live in configuration, not code.
Nothing is invented, every figure is marked as delivered or derived, and a
missing value is always shown as missing, never as a zero and never as good
news.
