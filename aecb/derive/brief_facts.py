"""Fact digest for the AI underwriting brief.

The brief's model is a finding selector, never a calculator: every join,
trajectory and aggregate is computed HERE, deterministically, and handed to the
model as a numbered fact table. The model connects facts and cites their IDs;
it is never shown raw payload JSON, so a figure it did not receive is a figure
it cannot legitimately emit -- and aecb.brief.validate drops any claim whose
numbers do not appear verbatim in the facts it cites.

Five lenses:

    trajectory     -- per-contract time series from contractsHistory:
                      utilization slope, delinquency episodes, balance
                      direction, and the month each contract FIRST went
                      overdue (synchrony raw material). The report renders
                      conduct as a heatmap; the digest spells the same months
                      out as numbers a language model can actually read.
    structure      -- portfolio shape the checklist skims past: guarantee
                      tail, maturity runway, file age vs subject age, recent
                      limit grants, and the buried summary counters.
    inconsistency  -- cross-array joins nobody performs by hand: the income
                      story against the employment rows, applications against
                      the contracts they did or did not become, the summary
                      block against its own detail rows, document expiry
                      inside the file, and the dispute/fraud/liability flags
                      scattered across five arrays.
    behavior       -- patterns in conduct: application bursts, the character
                      of returned instruments, what happened to revolving
                      balances after a new loan, dormant lines waking up.
    absence        -- what the file does NOT establish. Absence facts state
                      missing corroboration and reporting gaps plainly so the
                      model can carry them into findings and the unknowns
                      list; an empty heatmap cell must never read as clean.
    background     -- curated macro context from config/macro_context.json,
                      each entry stamped with the file's as-of date. This is
                      the ONLY time-sensitive knowledge the model receives:
                      its own training knowledge is cutoff-frozen and must
                      not supply current conditions, so currency comes from a
                      human-curated file under MRM change control and the
                      model contributes only the connection to this payload.
                      The file is OPTIONAL and, unlike every other config,
                      degrades silently -- the brief works without macro
                      context, so its absence is a feature choice, not the
                      deployment fault a missing status_codes.json is.

Each fact carries the exact payload fields behind it and the NAME of the report
section where the human can verify it. Names, not numbers: displayed section
numbers are assigned positionally in render/sections/__init__.py, and a number
hard-coded here could only drift from that registry. The render layer resolves
the name at draw time.

Facts are prose with plain figures, not JSON: the model reads them better, and
the validator only needs the numeric tokens, which survive either way.

PROHIBITED FIELDS -- policy, not preference: customerInfo.Nationality,
customerInfo.Gender and customerInfo.ResidentFlag must never enter a fact's
text or field list. Nationality and gender are impermissible underwriting
factors; ResidentFlag is nationality-adjacent and is excluded by decision
(3 Sep 2026) -- it may only ever return as an explicit, documented compliance
exception, never as a code default. scripts/check_brief.py and
scripts/eval_brief.py assert this on every digest. DOB-derived age stays.
"""

from __future__ import annotations

import json
import os

from .. import dates
from ..context import CONFIG_DIR
from . import facilities, identity, income

# See the module docstring: these may never appear in a fact. Tests import
# this tuple, so policy and enforcement cannot drift apart.
PROHIBITED_FIELDS = ("Nationality", "Gender", "ResidentFlag")

# The most recent reported months a trajectory fact spells out. Twelve keeps a
# nine-contract digest inside a few thousand tokens while still covering a full
# year of direction -- the window the 24M summary fields compress to one value.
_SERIES_MONTHS = 12

# A contract opened within this many months of the report date counts as a
# recent origination for the limit-granting-velocity fact.
_RECENT_OPEN_MONTHS = 12


def _num(value):
    """Payload numerics arrive as int, float or string ('110'). None if not."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _fmt(value):
    """A number as compact prose: no trailing .0, thousands separated."""
    n = _num(value)
    if n is None:
        return "?"
    if n == int(n):
        return "{:,}".format(int(n))
    return "{:,.2f}".format(n)


def _month(value):
    d = dates.parse_any(value)
    return d.strftime("%Y-%m") if d else None


def _contract_label(ctx, contract):
    """'Credit Card C41880273 (Bank B01, opened 12 March 2018)' -- enough for
    the model to name the facility without inventing detail."""
    provider = ctx.provider(contract.get("ProviderNo"))
    return "%s %s (%s, opened %s)" % (
        (contract.get("ContractType") or "Contract").strip(),
        contract.get("CBContractId") or "?",
        provider["name"],
        contract.get("OpenDate") or "unknown date",
    )


def _history_by_contract(ctx):
    """contractsHistory grouped by contract, sorted by month, undated rows out."""
    grouped = {}
    for row in ctx.rows("contractsHistory"):
        month = _month(row.get("ReferenceDate"))
        if not month:
            continue
        grouped.setdefault(row.get("CBContractId"), []).append((month, row))
    for rows in grouped.values():
        rows.sort(key=lambda pair: pair[0])
    return grouped


class _Facts:
    """Accumulator that hands out sequential F-ids."""

    def __init__(self):
        self.rows = []

    def add(self, theme, text, fields, section):
        self.rows.append({
            "id": "F%03d" % (len(self.rows) + 1),
            "theme": theme,
            "text": text,
            "fields": list(fields),
            "section": section,
        })


# --- structure facts ---------------------------------------------------------

def _portfolio(ctx, facts):
    contracts = ctx.rows("contracts")
    if not contracts:
        return
    active = [c for c in contracts
              if str(c.get("ActiveFlag", "")).strip().lower() == "active"]
    text = ("Portfolio: %d contracts on file, %d active and %d closed."
            % (len(contracts), len(active), len(contracts) - len(active)))
    exposure = _num(ctx.totals.get("TotalExposure"))
    if exposure is not None:
        text += " Total exposure AED %s." % _fmt(exposure)
    utilization = _num(ctx.totals.get("CreditUtilizationRate"))
    if utilization is not None:
        text += (" Bureau-delivered credit utilization %s%% as of the pull "
                 "date (a snapshot, not a trend)." % _fmt(utilization))
    facts.add("structure", text,
              ["contracts[].ActiveFlag", "contractsTotalSummary.TotalExposure",
               "contractsTotalSummary.CreditUtilizationRate"],
              "facilities")


def _guarantees(ctx, facts):
    balance = _num(ctx.totals.get("TotalBalanceGuaranteed"))
    overdue = _num(ctx.totals.get("TotalOverdueGuaranteed"))
    if not balance and not overdue:
        return
    text = ("Contingent exposure as guarantor: AED %s guaranteed balance"
            % _fmt(balance or 0))
    if overdue:
        text += ", of which AED %s is already overdue" % _fmt(overdue)
    text += ". This appears in no facility row the subject personally pays."
    facts.add("structure", text,
              ["contractsTotalSummary.TotalBalanceGuaranteed",
               "contractsTotalSummary.TotalOverdueGuaranteed"],
              "facilities")


def _buried_counters(ctx, facts):
    """summary fields severity-laden enough to deserve their own fact each."""
    summary = ctx.summary
    counters = (
        ("UnauthorizedOverdraft", "Unauthorized overdraft flag/count %s",
         "worst_status"),
        ("Unauthorised_OD_Amt", "Unauthorized overdraft amount AED %s",
         "worst_status"),
        ("AccountOverLimit", "Account-over-limit flag/count %s", "worst_status"),
        ("Count_Def_6m_30_Total",
         "%s delinquency events of 30+ days in the last 6 months",
         "worst_status"),
        ("Count_Def_12m_60_Total",
         "%s delinquency events of 60+ days in the last 12 months",
         "worst_status"),
        ("Amount_checks_returned_3mon",
         "AED %s of cheques returned in the last 3 months", "returns"),
        ("Amount_DD_returned_3mon",
         "AED %s of direct debits returned in the last 3 months", "returns"),
    )
    for field, template, section in counters:
        value = _num(summary.get(field))
        if not value:
            continue
        facts.add("structure",
                  (template % _fmt(value)) + " (summary block, delivered).",
                  ["summary.%s" % field], section)

    overdue = _num(summary.get("Overdueamount"))
    if overdue:
        facts.add("structure",
                  "Total overdue amount AED %s (summary, delivered)."
                  % _fmt(overdue),
                  ["summary.Overdueamount"], "worst_status")


def _worst_anchor(ctx, facts):
    """The 24-month worst point -- the checklist's own anchor, included so the
    model can connect trajectories to it rather than restate it."""
    worst = ctx.totals.get("WorstStatus24M")
    delay = _num(ctx.totals.get("MaxPaymentDelay24M"))
    if not worst and delay is None:
        return
    parts = []
    if worst:
        parts.append("worst status in 24 months '%s'" % str(worst).strip())
    if delay is not None:
        parts.append("maximum payment delay in 24 months %s days" % _fmt(delay))
    facts.add("structure",
              "Delivered 24-month anchor: %s." % "; ".join(parts),
              ["contractsTotalSummary.WorstStatus24M",
               "contractsTotalSummary.MaxPaymentDelay24M"],
              "worst_status")


def _file_age(ctx, facts):
    oldest = ctx.totals.get("OldestContractOpenDate")
    file_months = dates.months_between(oldest, ctx.report_date)
    dob = ctx.customer.get("DOB")
    age_months = dates.months_between(dob, ctx.report_date)
    if file_months is None and age_months is None:
        return
    parts = []
    fields = []
    if file_months is not None:
        parts.append("credit file is %d months old (oldest contract opened %s)"
                     % (file_months, _month(oldest) or "?"))
        fields.append("contractsTotalSummary.OldestContractOpenDate")
    if age_months is not None:
        parts.append("subject is %d years old (born %s)"
                     % (age_months // 12, _month(dob) or "?"))
        fields.append("customerInfo.DOB")
    facts.add("structure",
              ("File vintage: " + "; ".join(parts) + ".").capitalize(),
              fields, "score")


def _recent_originations(ctx, facts):
    if not ctx.report_date:
        return
    recent = []
    for contract in ctx.rows("contracts"):
        opened_months = dates.months_between(contract.get("OpenDate"),
                                             ctx.report_date)
        if opened_months is None or opened_months > _RECENT_OPEN_MONTHS:
            continue
        amount = _num(contract.get("Current_CreditLimit")) or \
            _num(contract.get("TotalAmount"))
        recent.append((contract, opened_months, amount))
    if not recent:
        return
    granted = sum(amount for _, _, amount in recent if amount)
    text = ("%d contract(s) opened within the last %d months of the report "
            "date" % (len(recent), _RECENT_OPEN_MONTHS))
    if granted:
        text += ", carrying AED %s of limits or amounts granted" % _fmt(granted)
    text += ": " + "; ".join(
        "%s (%d months before the pull)" % (_contract_label(ctx, c), months)
        for c, months, _ in recent) + "."
    facts.add("structure", text,
              ["contracts[].OpenDate", "contracts[].Current_CreditLimit",
               "contracts[].TotalAmount"],
              "facilities")


def _maturity_runway(ctx, facts):
    rows = []
    for contract in ctx.rows("contracts"):
        total = _num(contract.get("NoOfInstallments"))
        remaining = _num(contract.get("NoOfRemainingInstallments"))
        if not total or remaining is None:
            continue
        if str(contract.get("ActiveFlag", "")).strip().lower() != "active":
            continue
        # The tenor-position reading is computed HERE, not left to the model:
        # a 20b model shown '19 of 144 remaining' has narrated it as a LONG
        # runway. Interpretation of a ratio is arithmetic, and arithmetic is
        # this module's job.
        ratio = remaining / total
        if ratio > 2.0 / 3.0:
            position = "early in tenor, payment load largely untested"
        elif ratio < 1.0 / 3.0:
            position = "nearing maturity, capacity frees up when it retires"
        else:
            position = "mid-tenor"
        rows.append("%s: %s of %s installments remaining (%s)"
                    % (_contract_label(ctx, contract), _fmt(remaining),
                       _fmt(total), position))
    if not rows:
        return
    facts.add("structure",
              "Maturity runway on active installment contracts: %s."
              % "; ".join(rows),
              ["contracts[].NoOfInstallments",
               "contracts[].NoOfRemainingInstallments"],
              "facilities")


def _applications_90d(ctx, facts):
    count = _num(ctx.totals.get("Applications90D"))
    if not count:
        return
    facts.add("structure",
              "%s credit application(s) recorded in the 90 days before the "
              "pull date (delivered counter)." % _fmt(count),
              ["contractsTotalSummary.Applications90D"], "applications")


# --- trajectory facts --------------------------------------------------------

def _series_text(pairs, formatter):
    return " ".join("%s:%s" % (month, formatter(row)) for month, row in pairs)


def _utilization_series(ctx, facts, label, history):
    pairs = [(m, r) for m, r in history
             if _num(r.get("UtilizationRate")) is not None]
    if len(pairs) < 2:
        return
    window = pairs[-_SERIES_MONTHS:]

    # A moving credit limit changes utilization with no borrower action at
    # all -- without this note, a lender-side limit cut reads as borrower
    # deterioration, which is exactly backwards.
    limits = [(m, _num(r.get("CreditLimit"))) for m, r in window
              if _num(r.get("CreditLimit")) is not None]
    limit_note = ""
    if limits and limits[0][1] != limits[-1][1]:
        limit_note = (" The credit limit was not constant over this window "
                      "(AED %s in %s, AED %s in %s), so part of the "
                      "utilization movement is mechanical rather than "
                      "borrower spending."
                      % (_fmt(limits[0][1]), limits[0][0],
                         _fmt(limits[-1][1]), limits[-1][0]))

    facts.add("trajectory",
              "%s -- reported monthly utilization%%: %s.%s"
              % (label,
                 _series_text(window,
                              lambda r: _fmt(r.get("UtilizationRate"))),
                 limit_note),
              ["contractsHistory[].UtilizationRate",
               "contractsHistory[].CreditLimit",
               "contractsHistory[].ReferenceDate"],
              "detail")


def _limit_series(ctx, facts, label, history):
    """A decreasing card limit: possibly another institution de-risking this
    borrower -- information no conduct row carries. Observationally identical
    to a customer-requested reduction, so the fact stays neutral and the
    prompt asks the model to treat it as a question for the customer."""
    limits = [(m, _num(r.get("CreditLimit"))) for m, r in history
              if _num(r.get("CreditLimit")) is not None]
    if len(limits) < 2:
        return
    peak_month, peak = max(limits, key=lambda pair: pair[1])
    after = [(m, v) for m, v in limits if m > peak_month]
    if not after:
        return
    low_month, low = min(after, key=lambda pair: pair[1])
    if low >= peak:
        return
    facts.add("trajectory",
              "%s -- the credit limit was reduced: AED %s (%s) down to "
              "AED %s (%s). The payload does not say whether the lender or "
              "the customer initiated the reduction."
              % (label, _fmt(peak), peak_month, _fmt(low), low_month),
              ["contractsHistory[].CreditLimit",
               "contractsHistory[].ReferenceDate"],
              "detail")


def _delay_episodes(history):
    """Consecutive delinquent runs in reported months, with their cure state.

    An episode ends at the first CLEAN reported month after it; an episode
    still delinquent at the last reported month is open, which is the most
    collections-relevant state a contract can be in. Reported months only --
    a reporting gap neither cures nor extends an episode, it just is not
    evidence.
    """
    episodes = []
    current = None
    for month, row in history:
        delay = _num(row.get("DaysPaymentDelay")) or 0
        overdue = _num(row.get("OverdueAmount")) or 0
        if delay > 0:
            if current is None:
                current = {"start": month, "months": 0,
                           "peak_delay": 0.0, "peak_overdue": 0.0}
            current["months"] += 1
            current["end"] = month
            current["last_delay"] = delay
            current["last_overdue"] = overdue
            current["peak_delay"] = max(current["peak_delay"], delay)
            current["peak_overdue"] = max(current["peak_overdue"], overdue)
        elif current is not None:
            current["cured_by"] = month
            episodes.append(current)
            current = None
    if current is not None:
        current["cured_by"] = None
        episodes.append(current)
    return episodes


def _delay_series(ctx, facts, label, history):
    late = [(m, r) for m, r in history if (_num(r.get("DaysPaymentDelay")) or 0) > 0]
    if not late:
        return
    window = late[-_SERIES_MONTHS:]
    peak = max(_num(r.get("DaysPaymentDelay")) for _, r in late)

    # Cure velocity: whether each episode recovered, and how it stands at the
    # last reported month. A borrower who has cured before is collectible; an
    # episode still climbing at the window's edge is the opposite.
    described = []
    for ep in _delay_episodes(history)[-3:]:
        if ep["cured_by"]:
            described.append(
                "%s to %s (%d reported month(s), peak %s days, peak overdue "
                "AED %s) cured by %s"
                % (ep["start"], ep["end"], ep["months"],
                   _fmt(ep["peak_delay"]), _fmt(ep["peak_overdue"]),
                   ep["cured_by"]))
        else:
            described.append(
                "running since %s and NOT cured: %s days delayed and AED %s "
                "overdue at the last reported month %s"
                % (ep["start"], _fmt(ep["last_delay"]),
                   _fmt(ep["last_overdue"]), history[-1][0]))

    text = ("%s -- months reported with payment delay (days): %s. Peak delay "
            "%s days across %d delinquent month(s). Episodes: %s."
            % (label,
               _series_text(window, lambda r: _fmt(r.get("DaysPaymentDelay"))),
               _fmt(peak), len(late), "; ".join(described)))
    facts.add("trajectory", text,
              ["contractsHistory[].DaysPaymentDelay",
               "contractsHistory[].OverdueAmount",
               "contractsHistory[].ReferenceDate"],
              "detail")


def _balance_trend(ctx, facts, label, history):
    pairs = [(m, r) for m, r in history if _num(r.get("Balance")) is not None]
    if len(pairs) < 2:
        return
    window = pairs[-_SERIES_MONTHS:]
    first_month, first_row = window[0]
    last_month, last_row = window[-1]
    first, last = _num(first_row.get("Balance")), _num(last_row.get("Balance"))
    if first == last:
        direction = "flat"
    else:
        direction = "rising" if last > first else "falling"
    facts.add("trajectory",
              "%s -- balance %s over the reported window: AED %s (%s) to "
              "AED %s (%s)."
              % (label, direction, _fmt(first), first_month, _fmt(last),
                 last_month),
              ["contractsHistory[].Balance", "contractsHistory[].ReferenceDate"],
              "detail")


def _overdue_onsets(ctx, facts, labelled_histories):
    """The month each contract FIRST reports an overdue amount -- one combined
    fact, because the signal is the alignment across contracts, and a model
    reading nine separate onset facts tends to narrate them one by one."""
    onsets = []
    for label, history in labelled_histories:
        for month, row in history:
            if (_num(row.get("OverdueAmount")) or 0) > 0:
                onsets.append("%s first overdue in %s" % (label, month))
                break
    if not onsets:
        return
    facts.add("trajectory",
              "Overdue onset by contract: %s." % "; ".join(onsets),
              ["contractsHistory[].OverdueAmount",
               "contractsHistory[].ReferenceDate"],
              "detail")


def _minimum_payment_streaks(ctx, facts, label, history):
    """Longest run of minimum-only months. The synthetic fixture delivers the
    flag as null throughout, so this fact usually stays silent -- absence of
    the flag is not evidence of full payments and must not become a fact."""
    best = run = 0
    for _, row in history:
        flag = row.get("MinimumPaymentFlag")
        truthy = str(flag).strip().upper() in ("1", "Y", "YES", "TRUE")
        run = run + 1 if truthy else 0
        best = max(best, run)
    if best >= 3:
        facts.add("trajectory",
                  "%s -- minimum payment flagged for %d consecutive reported "
                  "months." % (label, best),
                  ["contractsHistory[].MinimumPaymentFlag"],
                  "detail")


# --- inconsistency facts -----------------------------------------------------

def _flag(value) -> bool:
    """Payload booleans arrive as True, 1 or 'Y' variants; None stays False --
    an unreported flag is unknown, and unknown must not become a fact."""
    if value is None:
        return False
    return str(value).strip().upper() in ("1", "Y", "YES", "TRUE")


def _income_story(ctx, facts):
    """B1: the income figures against the employment timeline.

    Reuses derive/income.build -- the same resolution section 03 renders, so
    the brief and the report cannot disagree about which employer is current
    or which figure is usable.
    """
    story = income.build(ctx)
    current = story["current"]

    if current is not None:
        text = ("Current employer (newest undisputed start date): %s, "
                "employment started %s" % (current.name,
                                           _month(current.started) or "?"))
        if current.income is not None:
            text += ", reported gross annual income AED %s" % _fmt(current.income)
            if not current.income_usable:
                text += " (below the placeholder floor -- not a usable figure)"
        else:
            text += ", with no income figure reported for it"
        if current.stale:
            text += ("; the record was last refreshed %s, outside the "
                     "confirmation window" % (_month(current.updated) or "?"))
        facts.add("inconsistency", text + ".",
                  ["employment[].EmploymentName", "employment[].DateOfEmployment",
                   "employment[].GrossAnnualIncome"],
                  "income")

    # Several jobs the bureau never closed is a data-coherence signal in
    # itself: the file cannot say which income stream is real.
    ongoing = [r for r in story["records"] if r.ongoing and r.started]
    if len(ongoing) > 1:
        listed = "; ".join("%s (started %s, income AED %s)"
                           % (r.name, _month(r.started) or "?",
                              _fmt(r.income) if r.income is not None else "?")
                           for r in ongoing)
        facts.add("inconsistency",
                  "%d employment records carry a start date and no "
                  "termination -- the bureau shows them all as open in "
                  "parallel: %s." % (len(ongoing), listed),
                  ["employment[].DateOfEmployment",
                   "employment[].DateOfTermination"],
                  "income")


def _application_reconciliation(ctx, facts):
    """B2 + C1: what the application trail says next to the contract book.

    AECB never labels a decline; a Requested application that no contract
    followed is the nearest observable proxy, and the burst shape (how many,
    how many providers, amounts in date order) is behavioral evidence the
    per-row table hides.
    """
    applications = ctx.rows("applications")
    if not applications:
        return
    contracts = ctx.rows("contracts")

    def matched(app):
        """A contract of the same type opened within ~3 months either side of
        the application's last update -- the loosest join the payload allows,
        since applications carry no contract id. Day arithmetic on parsed
        dates rather than dates.months_between, which clamps a backwards span
        to 0 and would 'match' any OLDER contract of the same type."""
        app_type = str(app.get("ContractType") or "").strip().lower()
        app_when = dates.parse_any(app.get("LastUpdateDate"))
        if not app_type or not app_when:
            return False
        for contract in contracts:
            if str(contract.get("ContractType") or "").strip().lower() != app_type:
                continue
            opened = dates.parse_any(contract.get("OpenDate"))
            if opened and abs((opened - app_when).days) <= 92:
                return True
        return False

    requested = [a for a in applications
                 if str(a.get("Phase") or "").strip().lower() == "requested"]
    unconverted = [a for a in requested if not matched(a)]
    if unconverted:
        ordered = sorted(unconverted,
                         key=lambda a: dates.parse_any(a.get("LastUpdateDate"))
                         or dates.parse_any("1970-01-01"))
        listed = "; ".join(
            "%s for AED %s at provider %s (%s)"
            % (str(a.get("ContractType") or "?").strip(),
               _fmt(a.get("TotalAmount")),
               ctx.provider(a.get("ProviderNo"))["name"],
               _month(a.get("LastUpdateDate")) or "?")
            for a in ordered)
        providers = {str(a.get("ProviderNo") or "").strip()
                     for a in unconverted if a.get("ProviderNo")}
        facts.add("behavior",
                  "%d application(s) in Requested phase across %d provider(s) "
                  "never appear as a contract of the same type within 3 "
                  "months, in date order: %s. AECB does not label declines; "
                  "this is the nearest observable trace."
                  % (len(unconverted), len(providers), listed),
                  ["applications[].Phase", "applications[].ContractType",
                   "applications[].TotalAmount", "applications[].LastUpdateDate",
                   "contracts[].ContractType", "contracts[].OpenDate"],
                  "applications")

    disbursed_unmatched = [
        a for a in applications
        if str(a.get("Phase") or "").strip().lower() == "disbursed"
        and not matched(a)]
    if disbursed_unmatched:
        facts.add("inconsistency",
                  "%d application(s) marked Disbursed have no contract of the "
                  "same type opened within 3 months -- the facility may sit "
                  "outside visible bureau coverage: %s."
                  % (len(disbursed_unmatched),
                     "; ".join("%s for AED %s (%s)"
                               % (str(a.get("ContractType") or "?").strip(),
                                  _fmt(a.get("TotalAmount")),
                                  _month(a.get("LastUpdateDate")) or "?")
                               for a in disbursed_unmatched)),
                  ["applications[].Phase", "applications[].ContractType",
                   "contracts[].OpenDate"],
                  "applications")


def _summary_vs_detail(ctx, facts):
    """B3: the summary block against its own detail rows.

    Strictly a data-quality flag -- the fact states both delivered figures and
    never a corrected one, because reconciling the bureau's aggregates is not
    this product's place.
    """
    delivered = _num(ctx.summary.get("Overdueamount"))
    detail_values = [_num(c.get("Current_OverdueAmount"))
                     for c in ctx.rows("contracts")]
    detail_values = [v for v in detail_values if v is not None]
    if delivered is None or not detail_values:
        return
    total = sum(detail_values)
    if abs(total - delivered) < 1:
        return
    facts.add("inconsistency",
              "The bureau's own aggregates disagree: summary overdue amount "
              "AED %s, while the contract rows sum to AED %s. Treat both with "
              "caution -- this is a bureau data-quality signal, not a "
              "corrected figure." % (_fmt(delivered), _fmt(total)),
              ["summary.Overdueamount", "contracts[].Current_OverdueAmount"],
              "worst_status")


def _document_staleness(ctx, facts):
    """B4: expiry and churn INSIDE the bureau file. The checklist asks whether
    the Emirates ID matches the application; it does not ask whether the file's
    own documents have lapsed."""
    if not ctx.report_date:
        return
    expired = []
    for info_type in ("EmiratesId", "Passport"):
        current, _prior = identity.identifiers(ctx, info_type)
        for entry in current:
            expiry = dates.parse_any(entry.extra.get("ExpiryDate"))
            if expiry and expiry < ctx.report_date:
                expired.append("%s on file expired %s"
                               % (info_type, _month(expiry)))
    if expired:
        facts.add("inconsistency",
                  "Identity documents inside the bureau file have lapsed: %s "
                  "(measured against the report date)." % "; ".join(expired),
                  ["identification[].InfoType", "identification[].ExpiryDate"],
                  "identity")

    current_addr, prior_addr = identity.addresses(ctx)
    entries = current_addr + prior_addr
    if len(entries) >= 4:
        newest = max((e.updated for e in entries if e.updated), default=None)
        age = dates.months_between(newest, ctx.report_date)
        text = ("%d distinct addresses on file" % len(entries))
        if age is not None:
            text += ("; the newest was last updated %d month(s) before the "
                     "report date" % age)
        facts.add("inconsistency", text + ".",
                  ["addresses[].Address", "addresses[].DateOfLastUpdate"],
                  "identity")


def _flag_sweep(ctx, facts):
    """B5: dispute/fraud/liability flags assembled from all five arrays.

    Each array's flags become their own fact so a finding can cite exactly the
    evidence it uses, and the verify-at pointer lands where that flag renders.
    HolderIsNotLiable matters most: it can reverse the meaning of a bad line.
    """
    score_flags = []
    if _flag(ctx.score.get("FraudContractFlag")):
        score_flags.append("FraudContractFlag is set")
    if _flag(ctx.score.get("PaymentOrderFlag")):
        score_flags.append("PaymentOrderFlag is set")
    if score_flags:
        facts.add("inconsistency",
                  "Score-level flags: %s." % "; ".join(score_flags),
                  ["score.FraudContractFlag", "score.PaymentOrderFlag"],
                  "score")

    contract_flags = []
    for contract in ctx.rows("contracts"):
        label = _contract_label(ctx, contract)
        if _flag(contract.get("FraudFlag")):
            contract_flags.append("fraud flag on %s (dated %s)"
                                  % (label,
                                     _month(contract.get("FraudFlagDate"))
                                     or "no date"))
        if _flag(contract.get("FlagOpenDispute")):
            contract_flags.append("open dispute on %s" % label)
        if _flag(contract.get("HolderIsNotLiable")):
            contract_flags.append(
                "holder-is-not-liable on %s -- its conduct may not be the "
                "subject's own" % label)
    if contract_flags:
        facts.add("inconsistency",
                  "Contract-level flags: %s." % "; ".join(contract_flags),
                  ["contracts[].FraudFlag", "contracts[].FlagOpenDispute",
                   "contracts[].HolderIsNotLiable"],
                  "facilities")

    other = []
    if any(_flag(r.get("FlagOpenDispute")) for r in ctx.rows("paymentOrder")):
        other.append("on a returned payment instrument")
    if any(_flag(r.get("FlagOpenDispute")) for r in ctx.rows("employment")):
        other.append("on an employment record")
    if any(_flag(r.get("FlagOpenDispute")) for r in ctx.rows("applications")):
        other.append("on a credit application")
    if other:
        facts.add("inconsistency",
                  "Open disputes are flagged %s -- disputed rows may change "
                  "after resolution." % " and ".join(other),
                  ["paymentOrder[].FlagOpenDispute",
                   "employment[].FlagOpenDispute",
                   "applications[].FlagOpenDispute"],
                  "returns")


# --- payment-waterfall facts -------------------------------------------------
# Where does this borrower rank their obligations? An NBFI is structurally
# junior in the payment waterfall, so conduct SPLIT by provider kind and by
# repayment method says more about the lender's own risk than any aggregate.

_KIND_LABELS = {"bank": "bank", "tel": "telecom", "nbfi": "NBFI"}


def _is_active(contract) -> bool:
    return str(contract.get("ActiveFlag", "")).strip().lower() == "active"


def _worst_delay(contract, history) -> float:
    """The worst delay ever evidenced for a contract: the delivered 24M peak
    or anything larger the monthly history shows."""
    values = [_num(contract.get("MaxDaysPaymentDelay")) or 0]
    values.extend((_num(r.get("DaysPaymentDelay")) or 0) for _, r in history)
    return max(values)


def _waterfall(ctx, facts, by_contract):
    """Conduct and exposure split by provider kind (bank / telecom / NBFI).

    providers.json currently tags every B## code as a bank, so the NBFI split
    stays silent until that registry is curated -- the grouping is by
    ctx.provider()['kind'] and activates on its own when 'nbfi' entries
    appear. Telecom gets its own sentence and no shared aggregate: telecom
    delinquency is noisier than bank delinquency, and the prompt carries that
    asymmetry so the model does not equate the two.
    """
    groups = {}
    for contract in ctx.rows("contracts"):
        if not _is_active(contract):
            continue
        kind = ctx.provider(contract.get("ProviderNo"))["kind"]
        history = by_contract.get(contract.get("CBContractId")) or []
        entry = groups.setdefault(kind, {
            "count": 0, "balance": 0.0, "limit": 0.0, "overdue": 0.0,
            "worst": 0.0, "late_months": 0})
        entry["count"] += 1
        entry["balance"] += _num(contract.get("Current_Balance")) or 0
        entry["limit"] += _num(contract.get("Current_CreditLimit")) or 0
        entry["overdue"] += _num(contract.get("Current_OverdueAmount")) or 0
        entry["worst"] = max(entry["worst"], _worst_delay(contract, history))
        entry["late_months"] += sum(
            1 for _, r in history if (_num(r.get("DaysPaymentDelay")) or 0) > 0)

    if len(groups) < 2:
        # One provider kind is no split; the per-contract facts already
        # cover it.
        return

    def sentence(kind, entry):
        return ("%s providers -- %d active contract(s), worst delay %s days, "
                "%d delinquent reported month(s), current overdue AED %s"
                % (_KIND_LABELS.get(kind, kind), entry["count"],
                   _fmt(entry["worst"]), entry["late_months"],
                   _fmt(entry["overdue"])))

    ordered = sorted(groups.items(),
                     key=lambda kv: _KIND_LABELS.get(kv[0], kv[0]))
    facts.add("behavior",
              "Conduct split by provider kind (active contracts): %s."
              % "; ".join(sentence(k, e) for k, e in ordered),
              ["contracts[].ProviderNo", "contracts[].Current_OverdueAmount",
               "contractsHistory[].DaysPaymentDelay"],
              "facilities")
    facts.add("structure",
              "Exposure split by provider kind (active contracts): %s."
              % "; ".join("%s -- balances AED %s, limits AED %s"
                          % (_KIND_LABELS.get(k, k), _fmt(e["balance"]),
                             _fmt(e["limit"]))
                          for k, e in ordered),
              ["contracts[].ProviderNo", "contracts[].Current_Balance",
               "contracts[].Current_CreditLimit"],
              "facilities")


def _method_of_payment(ctx, facts, by_contract):
    """contracts[].MethodOfPayment, read as waterfall position.

    Salary Transfer repayment is deducted at source: clean conduct there is
    involuntary and says nothing about willingness to pay, while delinquency
    there means the salary stopped or moved -- both readings are computed
    here, per the house rule that interpretation is arithmetic.
    """
    def method(contract):
        return str(contract.get("MethodOfPayment") or "").strip().lower()

    active = [c for c in ctx.rows("contracts") if _is_active(c)]
    st = [c for c in active if method(c) == "salary transfer"]
    dd = [c for c in active if method(c) == "direct debit"]
    if not st and not dd:
        return

    def describe(contract):
        history = by_contract.get(contract.get("CBContractId")) or []
        worst = _worst_delay(contract, history)
        state = ("worst delay %s days" % _fmt(worst)) if worst else "clean"
        return "%s (%s)" % (_contract_label(ctx, contract), state)

    unstated = len(active) - len(st) - len(dd)
    parts = []
    if st:
        parts.append("%d on Salary Transfer: %s"
                     % (len(st), "; ".join(describe(c) for c in st)))
    if dd:
        parts.append("%d on Direct Debit: %s"
                     % (len(dd), "; ".join(describe(c) for c in dd)))
    if unstated:
        parts.append("%d with no method reported" % unstated)
    facts.add("structure",
              "Repayment method on active contracts -- %s. Salary-transfer "
              "repayment is deducted at source, so its conduct is largely "
              "involuntary." % ". ".join(parts),
              ["contracts[].MethodOfPayment"],
              "facilities")

    st_delinquent = [c for c in st
                     if _worst_delay(c, by_contract.get(
                         c.get("CBContractId")) or []) > 0]
    if st_delinquent:
        facts.add("behavior",
                  "Delinquency on salary-transfer contract(s): %s. Delay on "
                  "an at-source deduction is consistent with the salary "
                  "stopping or moving accounts -- a job-loss or "
                  "account-switch signal, not ordinary payment choice."
                  % "; ".join(describe(c) for c in st_delinquent),
                  ["contracts[].MethodOfPayment",
                   "contracts[].MaxDaysPaymentDelay"],
                  "facilities")
    else:
        clean = [c for c in active
                 if _worst_delay(c, by_contract.get(
                     c.get("CBContractId")) or []) == 0]
        if clean and st and all(method(c) == "salary transfer"
                                for c in clean) and len(clean) < len(active):
            facts.add("behavior",
                      "Every clean active contract is on Salary Transfer "
                      "(%d of %d active); conduct on involuntary at-source "
                      "repayment does not demonstrate willingness to pay "
                      "voluntary obligations."
                      % (len(clean), len(active)),
                      ["contracts[].MethodOfPayment"],
                      "facilities")


def _obligation_components(ctx, facts):
    """Delivered obligation components for the underwriter's own DBR work.

    Components ONLY, never a blended total: AECB delivers no payment amount
    for cards, so any single obligation figure would smuggle a card-payment
    methodology into the fact table. The bureau's own role-A aggregates are
    preferred over recomputing (delivered beats derived), and the role split
    keeps guarantor lines out.
    """
    fin = facilities.financial_summary(ctx, "A")
    parts = []
    fields = []
    installment = _num((fin.get("I") or {}).get("PaymentAmount"))
    if installment:
        parts.append("installment payment obligations AED %s per month "
                     "(delivered, main holder)" % _fmt(installment))
        fields.append("contractsFinancialSummary[I/A].PaymentAmount")
    card = fin.get("C") or {}
    card_limit = _num(card.get("CreditLimit"))
    card_balance = _num(card.get("Balance"))
    if card_limit or card_balance:
        parts.append("card limits AED %s with balances AED %s -- AECB "
                     "delivers no payment amount for cards"
                     % (_fmt(card_limit or 0), _fmt(card_balance or 0)))
        fields.append("contractsFinancialSummary[C/A].CreditLimit")
        fields.append("contractsFinancialSummary[C/A].Balance")
    min_pcts = sorted({_fmt(v) for v in
                       (_num(c.get("MinimumPaymentPercentage"))
                        for c in ctx.rows("contracts")) if v})
    if min_pcts:
        parts.append("delivered minimum payment percentage: %s%%"
                     % ", ".join(min_pcts))
        fields.append("contracts[].MinimumPaymentPercentage")
    if not parts:
        return
    facts.add("structure",
              "Obligation components for affordability work -- %s. The "
              "debt-burden calculation itself belongs to the underwriter."
              % "; ".join(parts),
              fields, "facilities")


def _early_tenor_delinquency(ctx, facts, by_contract):
    """First-payment-default pattern: delinquency in a contract's first
    months. Two delivered-field paths, because the ~24-month history window
    cannot see the early tenor of older contracts: the monthly history where
    it covers the opening, else the delivered worst-delay date against the
    open date. One combined fact -- repeat FPD is a pattern, not a list.
    """
    hits = []
    for contract in ctx.rows("contracts"):
        opened = dates.parse_any(contract.get("OpenDate"))
        if not opened:
            continue
        label = _contract_label(ctx, contract)
        history = by_contract.get(contract.get("CBContractId")) or []

        # The history window covers this contract's early tenor only when its
        # first reported month is no later than the opening month.
        start = dates.parse_any(history[0][0] + "-01") if history else None
        covered = start is not None and start <= opened
        first_late = next((m for m, r in history
                           if (_num(r.get("DaysPaymentDelay")) or 0) > 0),
                          None)
        if covered and first_late:
            gap = dates.months_between(opened, first_late + "-01")
            if gap is not None and gap <= 3:
                hits.append("%s: first reported delay in %s, within 3 "
                            "months of opening" % (label, first_late))
                continue
        if not covered:
            peak = _num(contract.get("MaxDaysPaymentDelay")) or 0
            peak_date = dates.parse_any(contract.get("MaxDaysPaymentDelayDate"))
            if peak > 0 and peak_date and 0 <= (peak_date - opened).days <= 90:
                hits.append("%s: the worst delay on record (%s days) is "
                            "dated within 90 days of opening"
                            % (label, _fmt(peak)))
    if not hits:
        return
    facts.add("behavior",
              "Early-tenor delinquency (a first-payment-default pattern is "
              "fraud-adjacent): %s." % "; ".join(hits),
              ["contracts[].OpenDate", "contracts[].MaxDaysPaymentDelayDate",
               "contractsHistory[].DaysPaymentDelay"],
              "detail")


# --- behavior facts ----------------------------------------------------------

def _returned_instruments(ctx, facts):
    """C2: the character of the paymentOrder trail, not just its count.

    One counterparty repeatedly vs many accounts, the stated reasons, and how
    recent the latest event is -- the shape that separates a soured
    relationship from diffuse liquidity failure.
    """
    rows = ctx.rows("paymentOrder")
    if not rows:
        return
    dated = sorted((r for r in rows if dates.parse_any(r.get("ReturnDate"))),
                   key=lambda r: dates.parse_any(r.get("ReturnDate")))
    total = sum(v for v in (_num(r.get("Amount")) for r in rows)
                if v is not None)
    accounts = {str(r.get("IBAN") or "").strip() for r in rows
                if r.get("IBAN")}
    reasons = sorted({str(r.get("Reason") or "").strip()
                      for r in rows if r.get("Reason")})
    types = sorted({str(r.get("Type") or "").strip()
                    for r in rows if r.get("Type")})

    text = ("%d returned instrument(s) totalling AED %s across %d distinct "
            "account(s); types: %s; stated reason(s): %s."
            % (len(rows), _fmt(total), len(accounts),
               ", ".join(types) or "?", ", ".join(reasons) or "?"))
    if dated:
        newest = dates.parse_any(dated[-1].get("ReturnDate"))
        gap = dates.months_between(newest, ctx.report_date)
        recent = [r for r in dated
                  if (dates.months_between(
                      dates.parse_any(r.get("ReturnDate")),
                      ctx.report_date) or 99) <= 3]
        text += (" Timeline: %s. The latest was %s month(s) before the "
                 "report date; %d fell within the 3 months before it."
                 % ("; ".join("%s AED %s in %s"
                              % (str(r.get("Type") or "?").strip(),
                                 _fmt(r.get("Amount")),
                                 _month(r.get("ReturnDate")))
                              for r in dated),
                    gap if gap is not None else "?", len(recent)))
    facts.add("behavior", text,
              ["paymentOrder[].Type", "paymentOrder[].Amount",
               "paymentOrder[].IBAN", "paymentOrder[].Reason",
               "paymentOrder[].ReturnDate"],
              "returns")


def _post_loan_balances(ctx, facts, by_contract):
    """C3, deepened for a consolidation product: for each installment loan,
    what card balances did in the following year.

    The +3-month look answers "did it consolidate at all"; the +6 and +12
    re-checks answer the question that actually predicts consolidation-card
    losses: balances that fell and then RE-STACKED. Every checkpoint the
    history cannot show is named, so a missing +12 never reads as cured --
    the same absence rule the heatmap follows.
    """
    loans = sorted((c for c in ctx.rows("contracts")
                    if str(c.get("ContractCategory", "")).strip().upper() == "I"
                    and dates.parse_any(c.get("OpenDate"))),
                   key=lambda c: dates.parse_any(c.get("OpenDate")),
                   reverse=True)[:3]
    cards = [c for c in ctx.rows("contracts")
             if str(c.get("ContractCategory", "")).strip().upper() == "C"]

    for loan in loans:
        open_month = _month(loan.get("OpenDate"))
        checkpoints = [(0, open_month)] + [
            (offset, _month(dates.add_months(loan.get("OpenDate"), offset)))
            for offset in (3, 6, 12)]

        moves = []
        edge_note = ""
        for card in cards:
            history = dict(by_contract.get(card.get("CBContractId")) or [])
            if not history:
                continue
            last_reported = max(history)
            steps = []
            for offset, month in checkpoints:
                balance = _num((history.get(month) or {}).get("Balance"))
                if balance is None:
                    continue
                steps.append("AED %s (%s)" % (_fmt(balance),
                                              month if offset == 0
                                              else "+%dm %s" % (offset, month)))
            if len(steps) < 2:
                continue
            if checkpoints[-1][1] > last_reported:
                edge_note = (" History for this card set is last reported "
                             "%s; later checkpoints are unreported, not "
                             "cured." % last_reported)
            moves.append("%s: %s" % (_contract_label(ctx, card),
                                     " -> ".join(steps)))
        if not moves:
            continue
        facts.add("behavior",
                  "After %s opened in %s (amount AED %s), card balances "
                  "moved: %s. Sustained falls read as consolidation; "
                  "fell-then-rebounded reads as failed consolidation "
                  "(re-stacking); rising throughout as stacked leverage.%s"
                  % (_contract_label(ctx, loan), open_month,
                     _fmt(_num(loan.get("TotalAmount"))
                          or _num(loan.get("Current_CreditLimit"))),
                     "; ".join(moves), edge_note),
                  ["contracts[].OpenDate", "contracts[].TotalAmount",
                   "contractsHistory[].Balance",
                   "contractsHistory[].ReferenceDate"],
                  "detail")


def _balance_transfer_trace(ctx, facts, by_contract):
    """A card balance collapsing to near-zero in the month a new facility
    opens elsewhere: the balance-transfer shape a consolidation-card
    underwriter looks for and no single row shows."""
    openings = [(c, dates.parse_any(c.get("OpenDate")))
                for c in ctx.rows("contracts")
                if dates.parse_any(c.get("OpenDate"))]
    traces = []
    for card in ctx.rows("contracts"):
        if str(card.get("ContractCategory", "")).strip().upper() != "C":
            continue
        history = by_contract.get(card.get("CBContractId")) or []
        for (prev_month, prev_row), (month, row) in zip(history, history[1:]):
            prev_balance = _num(prev_row.get("Balance")) or 0
            balance = _num(row.get("Balance")) or 0
            if prev_balance < 1000 or balance > 0.05 * prev_balance:
                continue
            collapse_month = dates.parse_any(month + "-01")
            nearby = [c for c, opened in openings
                      if c is not card and collapse_month
                      and abs((opened - collapse_month).days) <= 45]
            if nearby:
                traces.append(
                    "%s balance fell AED %s (%s) to AED %s (%s) while %s "
                    "opened"
                    % (_contract_label(ctx, card), _fmt(prev_balance),
                       prev_month, _fmt(balance), month,
                       "; ".join(_contract_label(ctx, c) for c in nearby)))
    if not traces:
        return
    facts.add("behavior",
              "Balance-transfer shape: %s." % ". ".join(traces),
              ["contractsHistory[].Balance", "contracts[].OpenDate"],
              "detail")


def _card_payment_pattern(ctx, facts, label, history):
    """Revolver-vs-transactor stats for a card, Python-labelled.

    The classification is fundamental card underwriting (a consolidation
    product targets revolvers; a transactor on a promo card is adverse
    selection), and per the house doctrine the LABEL is computed here, not
    left to the model. Both fixtures deliver AmountSpent/BilledAmount as
    null, so where spend evidence is absent the fact carries the stats plus
    an explicit caveat instead of a label -- a carried balance on an
    inactive card is paydown, not revolving, and the payload cannot tell
    the difference without spend fields.

    contractsHistory.PaymentBehaviour is deliberately NOT read: it arrives
    as an undocumented '0'/'1'/null coding, and this codebase's rule for
    unknown vocabularies is a config under MRM (see status_codes.json), not
    a guess.
    """
    pairs = [(m, r) for m, r in history if _num(r.get("Balance")) is not None]
    pairs = pairs[-_SERIES_MONTHS:]
    if len(pairs) < 6:
        return
    carried = sum(1 for _, r in pairs if (_num(r.get("Balance")) or 0) > 0)
    total = len(pairs)
    spend_rows = [(m, r) for m, r in pairs
                  if r.get("AmountSpent") is not None
                  or r.get("BilledAmount") is not None]

    if spend_rows:
        spending = sum(1 for _, r in spend_rows
                       if (_num(r.get("AmountSpent")) or 0) > 0
                       or (_num(r.get("BilledAmount")) or 0) > 0)
        if carried >= 0.75 * total and spending == 0:
            # A balance that persists with zero reported spending is not
            # revolving -- nothing is being added; it is an inactive card
            # being paid down (or not).
            label_text = ("a carried balance with no reported spending -- "
                          "an inactive card paying down, not active "
                          "revolving")
        elif carried >= 0.75 * total and spending >= 0.5 * len(spend_rows):
            label_text = "a revolving pattern"
        elif carried <= 0.25 * total:
            label_text = "a transacting pattern"
        else:
            label_text = "a mixed pattern"
        facts.add("trajectory",
                  "%s -- balance carried in %d of %d reported month(s) with "
                  "spending in %d: %s."
                  % (label, carried, total, spending, label_text),
                  ["contractsHistory[].Balance", "contractsHistory[].AmountSpent",
                   "contractsHistory[].BilledAmount"],
                  "detail")
    elif carried >= 0.75 * total or carried <= 0.25 * total:
        state = ("a balance was carried in %d of %d reported month(s)"
                 % (carried, total))
        facts.add("trajectory",
                  "%s -- %s. Card activity fields (AmountSpent, "
                  "BilledAmount) were not delivered, so a revolving pattern "
                  "cannot be distinguished from an inactive card paying "
                  "down." % (label, state),
                  ["contractsHistory[].Balance"],
                  "detail")


def _dormant_reactivation(ctx, facts, label, history):
    """C4: a card asleep for months that starts spending again. The wake-up
    month matters most next to other contracts' first overdues (A4)."""
    run = 0
    best_run = 0
    wake_month = None
    for month, row in history:
        spent = _num(row.get("AmountSpent"))
        used = _flag(row.get("CardUsedFlag")) or (spent or 0) > 0
        if used:
            if run >= 4:
                best_run, wake_month = run, month
            run = 0
        else:
            run += 1
    if wake_month is None:
        return
    facts.add("behavior",
              "%s -- unused for %d consecutive reported months, then spending "
              "resumes in %s." % (label, best_run, wake_month),
              ["contractsHistory[].CardUsedFlag",
               "contractsHistory[].AmountSpent",
               "contractsHistory[].ReferenceDate"],
              "detail")


# --- absence facts -----------------------------------------------------------

def _reporting_gaps(ctx, facts, labelled_active):
    """E1: months the bureau did NOT report on active contracts. On the
    heatmap these cells read as calm; here they are named as blind spots --
    above all the months nearest the pull date, which is exactly where the
    freshest conduct should be."""
    if not ctx.report_date:
        return
    pull_month = ctx.report_date.strftime("%Y-%m")
    stale = []
    for label, history in labelled_active:
        last_month = history[-1][0]
        gap = dates.months_between(last_month + "-01", ctx.report_date)
        if gap is not None and gap >= 2:
            stale.append("%s last reported %s, %d month(s) before the pull "
                         "month %s" % (label, last_month, gap, pull_month))
    if stale:
        facts.add("absence",
                  "Reporting blind spots on active contracts (absent months "
                  "are unreported, not clean): %s." % "; ".join(stale),
                  ["contractsHistory[].ReferenceDate", "contracts[].ActiveFlag",
                   "score.DataPullDate"],
                  "detail")


def _income_corroboration(ctx, facts):
    """E2: can this file support an income figure at all? Reuses the same
    income resolution as section 03, so 'no usable figure' here means exactly
    what the income section shows."""
    story = income.build(ctx)
    latest = story["latest"]
    have_usable = latest is not None and latest["record"].income_usable

    income_rows = ctx.rows("incomes")
    row_note = "no rows in the incomes array"
    if income_rows:
        row = income_rows[0]
        age = dates.months_between(row.get("DateOfLastUpdate"),
                                   ctx.report_date)
        row_note = ("the single incomes row carries source '%s'%s and no "
                    "usable amount"
                    % (str(row.get("Source") or "?").strip(),
                       (", last updated %d month(s) before the report date"
                        % age) if age is not None else ""))
        if _num(row.get("GrossAnnualIncome")):
            row_note = ("the incomes row reports AED %s (source '%s')"
                        % (_fmt(row.get("GrossAnnualIncome")),
                           str(row.get("Source") or "?").strip()))

    if not have_usable:
        facts.add("absence",
                  "The file cannot corroborate current income: %s, and no "
                  "employment record carries a usable figure for a current "
                  "employer. Income evidence must come from outside this "
                  "report." % row_note,
                  ["incomes[].Source", "incomes[].DateOfLastUpdate",
                   "employment[].GrossAnnualIncome"],
                  "income")

    if story["current"] is None:
        facts.add("absence",
                  "No employment record qualifies as visibly current -- every "
                  "row is terminated, marked historical, or carries no start "
                  "date. The file does not establish a present employer.",
                  ["employment[].DateOfEmployment",
                   "employment[].DateOfTermination"],
                  "income")


# --- background facts --------------------------------------------------------

def _macro_facts(ctx, facts):
    """config/macro_context.json entries as citable facts, as-of stamped.

    Loaded here rather than through context._load_config on purpose: that
    loader RAISES on absence because the report is untrustworthy without its
    vocabularies, while macro context is optional by design. A malformed file
    is still a loud failure -- silence is reserved for absence alone.
    """
    path = os.path.join(CONFIG_DIR, "macro_context.json")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        macro = json.load(fh)
    as_of = str(macro.get("as_of") or "undated").strip()
    for entry in macro.get("facts") or []:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        facts.add("background",
                  "[curated context, as of %s] %s" % (as_of, text),
                  ["config/macro_context.json"],
                  None)


# --- entry points ------------------------------------------------------------

def build(ctx):
    """The full fact list for one payload, in stable order."""
    facts = _Facts()

    _portfolio(ctx, facts)
    _guarantees(ctx, facts)
    _worst_anchor(ctx, facts)
    _buried_counters(ctx, facts)
    _file_age(ctx, facts)
    _recent_originations(ctx, facts)
    _maturity_runway(ctx, facts)
    _applications_90d(ctx, facts)

    by_contract = _history_by_contract(ctx)
    labelled = []
    labelled_active = []
    for contract in ctx.rows("contracts"):
        history = by_contract.get(contract.get("CBContractId"))
        if not history:
            continue
        label = _contract_label(ctx, contract)
        labelled.append((label, history))
        if str(contract.get("ActiveFlag", "")).strip().lower() == "active":
            labelled_active.append((label, history))
        if str(contract.get("ContractCategory", "")).strip().upper() == "C":
            _utilization_series(ctx, facts, label, history)
            _limit_series(ctx, facts, label, history)
            _card_payment_pattern(ctx, facts, label, history)
            _dormant_reactivation(ctx, facts, label, history)
        _delay_series(ctx, facts, label, history)
        _balance_trend(ctx, facts, label, history)
        _minimum_payment_streaks(ctx, facts, label, history)
    _overdue_onsets(ctx, facts, labelled)

    _waterfall(ctx, facts, by_contract)
    _method_of_payment(ctx, facts, by_contract)
    _obligation_components(ctx, facts)
    _early_tenor_delinquency(ctx, facts, by_contract)

    _income_story(ctx, facts)
    _application_reconciliation(ctx, facts)
    _summary_vs_detail(ctx, facts)
    _document_staleness(ctx, facts)
    _flag_sweep(ctx, facts)
    _returned_instruments(ctx, facts)
    _post_loan_balances(ctx, facts, by_contract)
    _balance_transfer_trace(ctx, facts, by_contract)
    _reporting_gaps(ctx, facts, labelled_active)
    _income_corroboration(ctx, facts)

    _macro_facts(ctx, facts)

    return facts.rows


def digest(facts) -> str:
    """The fact table as the model sees it: one line per fact, id first."""
    return "\n".join("%s [%s] %s" % (f["id"], f["theme"], f["text"])
                     for f in facts)


def by_id(facts) -> dict:
    return {f["id"]: f for f in facts}
