"""Inconsistency lens: cross-array joins nobody performs by hand -- the income
story against the employment rows, applications against the contracts they
did or did not become, the summary block against its own detail rows,
document expiry inside the file, and the dispute/fraud/liability flags
scattered across five arrays."""

from __future__ import annotations

from ... import dates
from ...coerce import number
from .. import applications, identity, income
from ._common import (BEHAVIOR, INCONSISTENCY, SEC_APPLICATIONS,
                      SEC_FACILITIES, SEC_IDENTITY, SEC_INCOME, SEC_RETURNS,
                      SEC_SCORE, SEC_WORST, contract_label, fmt, is_set, month,
                      provider_name, text)

# An application "became" a contract when one of the same type opened within
# this many days either side of the application's last update.
_MATCH_DAYS = 92

_UNDATED = dates.parse_any("1970-01-01")


def income_story(ctx, facts):
    """The income figures against the employment timeline.

    Reuses derive/income.build -- the same resolution the income section
    renders, so the brief and the report cannot disagree about which employer
    is current or which figure is usable.
    """
    story = income.build(ctx)
    current = story["current"]

    if current is not None:
        line = ("Current employer (newest start date among records not "
                "marked finished): %s, employment started %s"
                % (text(current.name), month(current.started) or "?"))
        if current.income is not None:
            line += ", reported gross annual income AED %s" % fmt(current.income)
            if not current.income_usable:
                line += " (below the placeholder floor -- not a usable figure)"
        else:
            line += ", with no income figure reported for it"
        if current.stale:
            line += ("; the record was last refreshed %s, outside the "
                     "confirmation window" % (month(current.updated) or "?"))
        facts.add(INCONSISTENCY, line + ".",
                  ["employment[].EmploymentName", "employment[].DateOfEmployment",
                   "employment[].GrossAnnualIncome"],
                  SEC_INCOME)

    # Several jobs the bureau never closed is a data-coherence signal in
    # itself: the file cannot say which income stream is real.
    ongoing = [r for r in story["records"] if r.ongoing and r.started]
    if len(ongoing) > 1:
        listed = "; ".join("%s (started %s, income AED %s)"
                           % (text(r.name), month(r.started) or "?",
                              fmt(r.income) if r.income is not None else "?")
                           for r in ongoing)
        facts.add(INCONSISTENCY,
                  "%d employment records carry a start date and no "
                  "termination -- the bureau shows them all as open in "
                  "parallel: %s." % (len(ongoing), listed),
                  ["employment[].DateOfEmployment",
                   "employment[].DateOfTermination"],
                  SEC_INCOME)


# --- applications against contracts ------------------------------------------

def _matches_contract(app, contracts) -> bool:
    """A contract of the same type opened within ~3 months either side of the
    application's last update -- the loosest join the payload allows, since
    applications carry no contract id. Day arithmetic on parsed dates rather
    than dates.months_between, which clamps a backwards span to 0 and would
    'match' any OLDER contract of the same type."""
    app_type = str(app.get("ContractType") or "").strip().lower()
    app_when = applications.applied_on(app)
    if not app_type or not app_when:
        return False
    for contract in contracts:
        if str(contract.get("ContractType") or "").strip().lower() != app_type:
            continue
        opened = dates.parse_any(contract.get("OpenDate"))
        if opened and abs((opened - app_when).days) <= _MATCH_DAYS:
            return True
    return False


def _by_update_date(apps):
    return sorted(apps, key=lambda a: applications.applied_on(a) or _UNDATED)


def _app_type(app) -> str:
    return text(app.get("ContractType") or "?")


def _app_month(app) -> str:
    """The application's date as the report places it (applied_on)."""
    return month(applications.applied_on(app)) or "?"


def _unconverted_requests(ctx, facts, requested, contracts):
    unconverted = [a for a in requested if not _matches_contract(a, contracts)]
    if not unconverted:
        return
    listed = "; ".join(
        "%s for AED %s at provider %s (%s)"
        % (_app_type(a), fmt(a.get("TotalAmount")),
           provider_name(ctx, a.get("ProviderNo")), _app_month(a))
        for a in _by_update_date(unconverted))
    providers = {str(a.get("ProviderNo") or "").strip()
                 for a in unconverted if a.get("ProviderNo")}
    facts.add(BEHAVIOR,
              "%d application(s) in Requested phase across %d provider(s) "
              "never appear as a contract of the same type within 3 "
              "months, in date order: %s. Their phase never moved past "
              "Requested; no Declined, Rejected or Not taken up outcome "
              "is recorded, so this is the nearest observable trace of "
              "what became of them."
              % (len(unconverted), len(providers), listed),
              ["applications[].Phase", "applications[].ContractType",
               "applications[].TotalAmount", "applications[].LastUpdateDate",
               "contracts[].ContractType", "contracts[].OpenDate"],
              SEC_APPLICATIONS)


def _disbursed_unmatched(facts, disbursed, contracts):
    unmatched = [a for a in disbursed if not _matches_contract(a, contracts)]
    if not unmatched:
        return
    facts.add(INCONSISTENCY,
              "%d application(s) marked Disbursed have no contract of the "
              "same type opened within 3 months -- the facility may sit "
              "outside visible bureau coverage: %s."
              % (len(unmatched),
                 "; ".join("%s for AED %s (%s)"
                           % (_app_type(a), fmt(a.get("TotalAmount")),
                              _app_month(a))
                           for a in unmatched)),
              ["applications[].Phase", "applications[].ContractType",
               "contracts[].OpenDate"],
              SEC_APPLICATIONS)


def _refusals(ctx, facts, refused):
    if not refused:
        return
    facts.add(BEHAVIOR,
              "%d application(s) Declined or Rejected by the provider, in "
              "date order: %s."
              % (len(refused), "; ".join(
                  "%s %s for AED %s at provider %s (%s)"
                  % (text(ctx.phase(a.get("Phase"))["label"]), _app_type(a),
                     fmt(a.get("TotalAmount")),
                     provider_name(ctx, a.get("ProviderNo")), _app_month(a))
                  for a in _by_update_date(refused))),
              ["applications[].Phase", "applications[].ContractType",
               "applications[].TotalAmount", "applications[].LastUpdateDate"],
              SEC_APPLICATIONS)


def application_reconciliation(ctx, facts):
    """What the application trail says next to the contract book.

    A Requested application that no contract followed is an unresolved
    trail; Declined / Rejected phases (D / J, config/status_codes.json
    application_phases) are the bureau's own record of a refusal. The burst
    shape (how many, how many providers, amounts in date order) is behavioral
    evidence the per-row table hides.
    """
    applications = ctx.rows("applications")
    if not applications:
        return
    contracts = ctx.rows("contracts")
    by_phase = {}
    for app in applications:
        by_phase.setdefault(ctx.phase(app.get("Phase"))["code"], []).append(app)

    _unconverted_requests(ctx, facts, by_phase.get("R", []), contracts)
    _disbursed_unmatched(facts, by_phase.get("B", []), contracts)
    _refusals(ctx, facts, [a for a in applications
                           if ctx.phase(a.get("Phase"))["code"] in ("D", "J")])


# --- the bureau against itself ------------------------------------------------

def summary_vs_detail(ctx, facts):
    """The summary block against its own detail rows.

    Strictly a data-quality flag -- the fact states both delivered figures and
    never a corrected one, because reconciling the bureau's aggregates is not
    this product's place.
    """
    delivered = number(ctx.summary.get("Overdueamount"))
    detail_values = [number(c.get("Current_OverdueAmount"))
                     for c in ctx.rows("contracts")]
    detail_values = [v for v in detail_values if v is not None]
    if delivered is None or not detail_values:
        return
    total = sum(detail_values)
    if abs(total - delivered) < 1:
        return
    facts.add(INCONSISTENCY,
              "The bureau's own aggregates disagree: summary overdue amount "
              "AED %s, while the contract rows sum to AED %s. Treat both with "
              "caution -- this is a bureau data-quality signal, not a "
              "corrected figure." % (fmt(delivered), fmt(total)),
              ["summary.Overdueamount", "contracts[].Current_OverdueAmount"],
              SEC_WORST)


def document_staleness(ctx, facts):
    """Expiry and churn INSIDE the bureau file. The checklist asks whether the
    Emirates ID matches the application; it does not ask whether the file's
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
                               % (info_type, month(expiry)))
    if expired:
        facts.add(INCONSISTENCY,
                  "Identity documents inside the bureau file have lapsed: %s "
                  "(measured against the report date)." % "; ".join(expired),
                  ["identification[].InfoType", "identification[].ExpiryDate"],
                  SEC_IDENTITY)

    current_addr, prior_addr = identity.addresses(ctx)
    entries = current_addr + prior_addr
    if len(entries) >= 4:
        newest = max((e.updated for e in entries if e.updated), default=None)
        age = dates.months_between(newest, ctx.report_date)
        text = ("%d distinct addresses on file" % len(entries))
        if age is not None:
            text += ("; the newest was last updated %d month(s) before the "
                     "report date" % age)
        facts.add(INCONSISTENCY, text + ".",
                  ["addresses[].Address", "addresses[].DateOfLastUpdate"],
                  SEC_IDENTITY)


# --- flags across the arrays ---------------------------------------------------

def _score_flags(ctx, facts):
    found = []
    if is_set(ctx.score.get("FraudContractFlag")):
        found.append("FraudContractFlag is set")
    if is_set(ctx.score.get("PaymentOrderFlag")):
        found.append("PaymentOrderFlag is set")
    if found:
        facts.add(INCONSISTENCY,
                  "Score-level flags: %s." % "; ".join(found),
                  ["score.FraudContractFlag", "score.PaymentOrderFlag"],
                  SEC_SCORE)


def _contract_flags(ctx, facts):
    found = []
    for contract in ctx.rows("contracts"):
        label = contract_label(ctx, contract)
        if is_set(contract.get("FraudFlag")):
            found.append("fraud flag on %s (dated %s)"
                         % (label, month(contract.get("FraudFlagDate"))
                            or "no date"))
        if is_set(contract.get("FlagOpenDispute")):
            found.append("open dispute on %s" % label)
        if is_set(contract.get("HolderIsNotLiable")):
            found.append("holder-is-not-liable on %s -- its conduct may not be "
                         "the subject's own" % label)
    if found:
        facts.add(INCONSISTENCY,
                  "Contract-level flags: %s." % "; ".join(found),
                  ["contracts[].FraudFlag", "contracts[].FlagOpenDispute",
                   "contracts[].HolderIsNotLiable"],
                  SEC_FACILITIES)


_DISPUTE_ARRAYS = (
    ("paymentOrder", "on a returned payment instrument"),
    ("employment", "on an employment record"),
    ("applications", "on a credit application"),
)


def _other_disputes(ctx, facts):
    found = [where for array, where in _DISPUTE_ARRAYS
             if any(is_set(r.get("FlagOpenDispute")) for r in ctx.rows(array))]
    if found:
        facts.add(INCONSISTENCY,
                  "Open disputes are flagged %s -- disputed rows may change "
                  "after resolution." % " and ".join(found),
                  ["%s[].FlagOpenDispute" % array for array, _ in _DISPUTE_ARRAYS],
                  SEC_RETURNS)


def flag_sweep(ctx, facts):
    """Dispute/fraud/liability flags assembled from all five arrays.

    Each array's flags become their own fact so a finding can cite exactly the
    evidence it uses, and the verify-at pointer lands where that flag renders.
    HolderIsNotLiable matters most: it can reverse the meaning of a bad line.
    """
    _score_flags(ctx, facts)
    _contract_flags(ctx, facts)
    _other_disputes(ctx, facts)
