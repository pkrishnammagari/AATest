"""Concentration lens: where the exposure sits and who gets paid -- lender
concentration, reliance on non-bank lenders, guarantor exposure next to the
subject's own arrears, instalments that outrun working life, the income
trajectory across updates, employer churn, and selective default."""

from __future__ import annotations

from ... import dates
from ...coerce import number
from .. import identity
from ..facilities import Facility
from . import patterns
from ._common import (CAT_INSTALLMENT, F_HIST_DELAY, RISK, SEC_FACILITIES,
                      SEC_INCOME, category, contract_label, fmt, is_active,
                      month, provider_name, text)

TOP_PROVIDER_SHARE = 0.5      # lender concentration
RETIREMENT_AGE = 60           # maturity against age
INCOME_MATERIAL = 0.10        # income trajectory: a material move
CHURN_EMPLOYERS = 3           # employer churn ...
CHURN_YEARS = 5               # ... within this many years
SELECTIVE_MIN_EACH = 2        # selective default by provider: contracts per side
NBFI = "nbfi"


def _active(ctx):
    return [c for c in ctx.rows("contracts") if is_active(c)]


def lender_concentration(ctx, facts):
    active = _active(ctx)
    if len(active) < 2:
        return
    balances = {}
    for c in active:
        code = str(c.get("ProviderNo") or "").strip()
        balances[code] = balances.get(code, 0.0) + (number(c.get("Current_Balance")) or 0)
    total = sum(balances.values())
    if not total or len(balances) < 2:
        return
    code, top = max(balances.items(), key=lambda kv: kv[1])
    share = top / total
    if share < TOP_PROVIDER_SHARE:
        return
    facts.add(RISK,
              "Lender concentration: %d%% of active balances (AED %s of AED %s) "
              "sit with one provider, %s, across %d providers in all. One "
              "lender's decision on this borrower moves most of the book."
              % (int(round(share * 100)), fmt(top), fmt(total),
                 provider_name(ctx, code), len(balances)),
              ["contracts[].ProviderNo", "contracts[].Current_Balance"],
              SEC_FACILITIES)


def nbfi_reliance(ctx, facts):
    active = _active(ctx)
    at_nbfi = [c for c in active if ctx.provider(c.get("ProviderNo"))["kind"] == NBFI]
    if not at_nbfi:
        return
    total = sum(number(c.get("Current_Balance")) or 0 for c in active)
    nbfi_balance = sum(number(c.get("Current_Balance")) or 0 for c in at_nbfi)
    facts.add(RISK,
              "Non-bank reliance: %d of %d active contracts are with non-bank "
              "lenders, carrying AED %s of AED %s active balances: %s. Non-bank "
              "credit is usually priced and collected harder, and a borrower "
              "turning to it may have exhausted bank appetite."
              % (len(at_nbfi), len(active), fmt(nbfi_balance), fmt(total),
                 "; ".join(contract_label(ctx, c) for c in at_nbfi)),
              ["contracts[].ProviderNo", "contracts[].Current_Balance"],
              SEC_FACILITIES)


def guarantor_beside_own(ctx, facts):
    guaranteed_overdue = number(ctx.totals.get("TotalOverdueGuaranteed"))
    if not guaranteed_overdue:
        return
    own = number(ctx.summary.get("Overdueamount")) or 0
    facts.add(RISK,
              "Guarantor exposure crystallising: AED %s of guaranteed balances "
              "is already overdue, beside the subject's own overdue of AED %s. "
              "A called guarantee is a payment the subject's income must also "
              "carry." % (fmt(guaranteed_overdue), fmt(own)),
              ["contractsTotalSummary.TotalOverdueGuaranteed",
               "summary.Overdueamount"],
              SEC_FACILITIES)


def _runs_past_retirement(ctx, contract, age):
    remaining = number(contract.get("NoOfRemainingInstallments"))
    if not remaining or Facility(ctx, contract, []).frequency_code != "M":
        return None
    end_age = age + remaining / 12.0
    return end_age if end_age > RETIREMENT_AGE else None


def maturity_vs_age(ctx, facts):
    dob = ctx.customer.get("DOB")
    age = identity.age_at(dob, ctx.report_date) if dob and ctx.report_date else None
    if age is None:
        return
    rows = []
    for c in _active(ctx):
        if category(c) != CAT_INSTALLMENT:
            continue
        end_age = _runs_past_retirement(ctx, c, age)
        if end_age is not None:
            rows.append("%s: %s instalments remaining, ending at about age %d"
                        % (contract_label(ctx, c),
                           fmt(c.get("NoOfRemainingInstallments")), int(end_age)))
    if not rows:
        return
    facts.add(RISK,
              "Instalments past working age: the subject is %d; %s. Repayment "
              "that runs beyond age %d rests on income the file cannot show."
              % (age, "; ".join(rows), RETIREMENT_AGE),
              ["customerInfo.DOB", "contracts[].NoOfRemainingInstallments",
               "contracts[].PaymentFrequency"],
              SEC_FACILITIES)


def income_trajectory(ctx, facts):
    dated = patterns.income_sequence(ctx)
    if len(dated) < 2:
        return
    first, last = dated[0][1], dated[-1][1]
    change = (last - first) / first if first else 0
    if abs(change) >= INCOME_MATERIAL:
        direction = "fell" if change < 0 else "rose"
        verdict = "%s by %d%% from the earliest to the latest dated figure" % (
            direction, int(round(abs(change) * 100)))
    else:
        verdict = "held within %d%% from the earliest to the latest dated figure" % (
            int(INCOME_MATERIAL * 100))
    facts.add(RISK,
              "Income trajectory across %d dated records: reported income %s -- "
              "%s. Capacity is assessed on the latest figure; the direction says "
              "whether it is holding." % (
                  len(dated), verdict,
                  "; ".join("AED %s (%s, %s)" % (fmt(v), d.strftime("%Y-%m"), text(name))
                            for d, v, name in dated)),
              ["employment[].GrossAnnualIncome", "employment[].DateOfLastUpdate",
               "employment[].DateOfEmployment"],
              SEC_INCOME)


def employer_churn(ctx, facts):
    if not ctx.report_date:
        return
    current, prior = identity.employers(ctx)
    cutoff = dates.add_months(ctx.report_date, -12 * CHURN_YEARS)
    recent = []
    for entry in current + prior:
        started = dates.parse_any(entry.extra.get("DateOfEmployment"))
        if started and started >= cutoff:
            recent.append((started, text(entry.value)))
    if len(recent) < CHURN_EMPLOYERS:
        return
    recent.sort()
    facts.add(RISK,
              "Employer churn: %d employers started within the last %d years "
              "-- %s. Frequent moves make the current income harder to rely on."
              % (len(recent), CHURN_YEARS,
                 "; ".join("%s (started %s)" % (name, month(started))
                           for started, name in recent)),
              ["employment[].EmploymentName", "employment[].DateOfEmployment"],
              SEC_INCOME)


def _delinquent(contract, history) -> bool:
    if (number(contract.get("Current_DaysPaymentDelay")) or 0) > 0 or \
            (number(contract.get("Current_OverdueAmount")) or 0) > 0:
        return True
    return any((patterns.dpd(r) or 0) > 0 for _, r in history)


def _sides(ctx, contracts, by_kind) -> str:
    if by_kind:
        return ", ".join(sorted({ctx.provider(c.get("ProviderNo"))["kind"] for c in contracts}))
    return ", ".join(sorted({provider_name(ctx, c.get("ProviderNo")) for c in contracts}))


def _split_by(ctx, late, clean):
    """'provider kind', 'provider' or None: how the delinquent and the clean
    active contracts separate, if they do."""
    kinds = lambda rows: {ctx.provider(c.get("ProviderNo"))["kind"] for c in rows}  # noqa: E731
    codes = lambda rows: {str(c.get("ProviderNo") or "") for c in rows}  # noqa: E731
    if not (kinds(late) & kinds(clean)):
        return "provider kind"
    # By provider alone, both sides need enough contracts to be a choice
    # rather than one odd line (a single clean salary-transfer loan is the
    # repayment-method lens's story, not this one's).
    if not (codes(late) & codes(clean)) and min(len(late), len(clean)) >= SELECTIVE_MIN_EACH:
        return "provider"
    return None


def selective_default(ctx, facts, by_contract):
    active = _active(ctx)
    late = [c for c in active
            if _delinquent(c, by_contract.get(c.get("CBContractId")) or [])]
    clean = [c for c in active if c not in late]
    if not late or not clean:
        return
    by = _split_by(ctx, late, clean)
    if by is None:
        return
    by_kind = by == "provider kind"
    facts.add(RISK,
              "Selective default by %s: every delinquent active contract is with "
              "%s (%s) while every clean one is with %s (%s). The borrower is "
              "choosing whom to pay; a new lender should ask where it would "
              "rank." % (by, _sides(ctx, late, by_kind),
                         "; ".join(contract_label(ctx, c) for c in late),
                         _sides(ctx, clean, by_kind),
                         "; ".join(contract_label(ctx, c) for c in clean)),
              ["contracts[].ProviderNo", "contracts[].Current_DaysPaymentDelay",
               "contracts[].Current_OverdueAmount", F_HIST_DELAY],
              SEC_FACILITIES)
