"""Structure lens: portfolio shape the checklist skims past -- guarantee tail,
maturity runway, file age against subject age, recent limit grants, the
buried summary counters and the delivered obligation components."""

from __future__ import annotations

from ... import dates
from ...coerce import number
from .. import facilities
from ._common import (SEC_APPLICATIONS, SEC_FACILITIES, SEC_SCORE, SEC_WORST,
                      STRUCTURE, contract_label, fmt, is_active, month, text)

# A contract opened within this many months of the report date counts as a
# recent origination for the limit-granting-velocity fact.
_RECENT_OPEN_MONTHS = 12

# summary counters severe enough to deserve a fact each:
# (field, sentence template, section where it is verified -- None when the
# report deliberately does not show the field).
_COUNTERS = (
    ("UnauthorizedOverdraft", "Unauthorized overdraft flag/count %s", SEC_WORST),
    ("Unauthorised_OD_Amt", "Unauthorized overdraft amount AED %s", SEC_WORST),
    ("AccountOverLimit", "Account-over-limit flag/count %s", SEC_WORST),
    ("Count_Def_6m_30_Total",
     "%s delinquency events of 30+ days in the last 6 months", SEC_WORST),
    ("Count_Def_12m_60_Total",
     "%s delinquency events of 60+ days in the last 12 months", SEC_WORST),
    # Whether these two are amounts or counts is unverified, and the returns
    # section deliberately does not show them (derive/returns.py) -- so the
    # value is stated with its field name and no unit, and no verify-at link.
    ("Amount_checks_returned_3mon",
     "Returned-cheque counter for the last 3 months: %s (unit not verified "
     "-- amount or count)", None),
    ("Amount_DD_returned_3mon",
     "Returned-direct-debit counter for the last 3 months: %s (unit not "
     "verified -- amount or count)", None),
)


def portfolio(ctx, facts):
    contracts = ctx.rows("contracts")
    if not contracts:
        return
    active = [c for c in contracts if is_active(c)]
    text = ("Portfolio: %d contracts on file, %d active and %d closed."
            % (len(contracts), len(active), len(contracts) - len(active)))
    exposure = number(ctx.totals.get("TotalExposure"))
    if exposure is not None:
        text += " Total exposure AED %s." % fmt(exposure)
    utilization = number(ctx.totals.get("CreditUtilizationRate"))
    if utilization is not None:
        text += (" Bureau-delivered credit utilization %s%% as of the pull "
                 "date (a snapshot, not a trend)." % fmt(utilization))
    facts.add(STRUCTURE, text,
              ["contracts[].ActiveFlag", "contractsTotalSummary.TotalExposure",
               "contractsTotalSummary.CreditUtilizationRate"],
              SEC_FACILITIES)


def opening_dates(ctx, facts):
    """Each contract with its opening date as delivered -- the one place the
    digest states them (contract labels carry type, id and provider only)."""
    contracts = ctx.rows("contracts")
    if not contracts:
        return
    facts.add(STRUCTURE,
              "Contracts on file and their opening dates: %s."
              % "; ".join("%s opened %s" % (contract_label(ctx, c),
                                            text(c.get("OpenDate") or "unknown date"))
                          for c in contracts),
              ["contracts[].ContractType", "contracts[].CBContractId",
               "contracts[].ProviderNo", "contracts[].OpenDate"],
              SEC_FACILITIES)


def guarantees(ctx, facts):
    balance = number(ctx.totals.get("TotalBalanceGuaranteed"))
    overdue = number(ctx.totals.get("TotalOverdueGuaranteed"))
    if not balance and not overdue:
        return
    text = ("Contingent exposure as guarantor: AED %s guaranteed balance"
            % fmt(balance or 0))
    if overdue:
        text += ", of which AED %s is already overdue" % fmt(overdue)
    text += ". This appears in no facility row the subject personally pays."
    facts.add(STRUCTURE, text,
              ["contractsTotalSummary.TotalBalanceGuaranteed",
               "contractsTotalSummary.TotalOverdueGuaranteed"],
              SEC_FACILITIES)


def buried_counters(ctx, facts):
    """summary fields severity-laden enough to deserve their own fact each."""
    summary = ctx.summary
    for field, template, section in _COUNTERS:
        value = number(summary.get(field))
        if not value:
            continue
        facts.add(STRUCTURE,
                  (template % fmt(value)) + " (summary block, delivered).",
                  ["summary.%s" % field], section)

    overdue = number(summary.get("Overdueamount"))
    if overdue:
        facts.add(STRUCTURE,
                  "Total overdue amount AED %s (summary, delivered)."
                  % fmt(overdue),
                  ["summary.Overdueamount"], SEC_WORST)


def worst_anchor(ctx, facts):
    """The 24-month worst point -- the checklist's own anchor, included so the
    model can connect trajectories to it rather than restate it."""
    worst = ctx.totals.get("WorstStatus24M")
    delay = number(ctx.totals.get("MaxPaymentDelay24M"))
    if not worst and delay is None:
        return
    parts = []
    if worst:
        parts.append("worst status in 24 months '%s'" % text(worst))
    if delay is not None:
        parts.append("maximum payment delay in 24 months %s days" % fmt(delay))
    facts.add(STRUCTURE,
              "Delivered 24-month anchor: %s." % "; ".join(parts),
              ["contractsTotalSummary.WorstStatus24M",
               "contractsTotalSummary.MaxPaymentDelay24M"],
              SEC_WORST)


def file_age(ctx, facts):
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
                     % (file_months, month(oldest) or "?"))
        fields.append("contractsTotalSummary.OldestContractOpenDate")
    if age_months is not None:
        # Age only: the birth month adds nothing to underwriting and is
        # personal data the model does not need.
        parts.append("subject is %d years old" % (age_months // 12))
        fields.append("customerInfo.DOB")
    facts.add(STRUCTURE,
              ("File vintage: " + "; ".join(parts) + ".").capitalize(),
              fields, SEC_SCORE)


def recent_originations(ctx, facts):
    if not ctx.report_date:
        return
    recent = []
    for contract in ctx.rows("contracts"):
        opened_months = dates.months_between(contract.get("OpenDate"),
                                             ctx.report_date)
        if opened_months is None or opened_months > _RECENT_OPEN_MONTHS:
            continue
        amount = number(contract.get("Current_CreditLimit")) or \
            number(contract.get("TotalAmount"))
        recent.append((contract, opened_months, amount))
    if not recent:
        return
    granted = sum(amount for _, _, amount in recent if amount)
    text = ("%d contract(s) opened within the last %d months of the report "
            "date" % (len(recent), _RECENT_OPEN_MONTHS))
    if granted:
        text += ", carrying AED %s of limits or amounts granted" % fmt(granted)
    text += ": " + "; ".join(
        "%s (%d months before the report date)" % (contract_label(ctx, c),
                                                    months)
        for c, months, _ in recent) + "."
    facts.add(STRUCTURE, text,
              ["contracts[].OpenDate", "contracts[].Current_CreditLimit",
               "contracts[].TotalAmount"],
              SEC_FACILITIES)


def _tenor_position(ratio) -> str:
    """The tenor-position reading, computed here rather than left to the
    model: a 20b model shown '19 of 144 remaining' has narrated it as a LONG
    runway. Interpreting a ratio is arithmetic, and arithmetic is this
    module's job."""
    if ratio > 2.0 / 3.0:
        return "early in tenor, payment load largely untested"
    if ratio < 1.0 / 3.0:
        return "nearing maturity, capacity frees up when it retires"
    return "mid-tenor"


def maturity_runway(ctx, facts):
    rows = []
    for contract in ctx.rows("contracts"):
        total = number(contract.get("NoOfInstallments"))
        remaining = number(contract.get("NoOfRemainingInstallments"))
        if not total or remaining is None or not is_active(contract):
            continue
        rows.append("%s: %s of %s installments remaining (%s)"
                    % (contract_label(ctx, contract), fmt(remaining),
                       fmt(total), _tenor_position(remaining / total)))
    if not rows:
        return
    facts.add(STRUCTURE,
              "Maturity runway on active installment contracts: %s."
              % "; ".join(rows),
              ["contracts[].NoOfInstallments",
               "contracts[].NoOfRemainingInstallments"],
              SEC_FACILITIES)


def applications_90d(ctx, facts):
    count = number(ctx.totals.get("Applications90D"))
    if not count:
        return
    facts.add(STRUCTURE,
              "%s credit application(s) recorded in the 90 days before the "
              "pull date (delivered counter)." % fmt(count),
              ["contractsTotalSummary.Applications90D"], SEC_APPLICATIONS)


def obligation_components(ctx, facts):
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
    installment = number((fin.get("I") or {}).get("PaymentAmount"))
    if installment:
        parts.append("installment payment obligations AED %s per month "
                     "(delivered, main holder)" % fmt(installment))
        fields.append("contractsFinancialSummary[I/A].PaymentAmount")
    card = fin.get("C") or {}
    card_limit = number(card.get("CreditLimit"))
    card_balance = number(card.get("Balance"))
    if card_limit or card_balance:
        parts.append("card limits AED %s with balances AED %s -- AECB "
                     "delivers no payment amount for cards"
                     % (fmt(card_limit or 0), fmt(card_balance or 0)))
        fields.append("contractsFinancialSummary[C/A].CreditLimit")
        fields.append("contractsFinancialSummary[C/A].Balance")
    min_pcts = sorted({fmt(v) for v in
                       (number(c.get("MinimumPaymentPercentage"))
                        for c in ctx.rows("contracts")) if v})
    if min_pcts:
        parts.append("delivered minimum payment percentage: %s%%"
                     % ", ".join(min_pcts))
        fields.append("contracts[].MinimumPaymentPercentage")
    if not parts:
        return
    facts.add(STRUCTURE,
              "Obligation components for affordability work -- %s. The "
              "debt-burden calculation itself belongs to the underwriter."
              % "; ".join(parts),
              fields, SEC_FACILITIES)
