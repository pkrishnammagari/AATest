"""One deterministic verifier per hypothesis type.

A verifier reads the payload through the same helpers the digest uses and
answers with a status and a sentence that carries the figures:

    confirmed       the pattern holds; the sentence states it with figures
    not_supported   the pattern does not hold; the sentence states what the
                    data shows instead, with figures
    not_assessable  the file cannot test it (no card, no history, no event
                    in the window); the sentence says why; no fact results

Confirmed and refuted results both become facts (theme "verified") so a
finding can rest on a tested pattern -- and so a hypothesis the data refutes
is on the record. The thresholds below are the verifiers' definitions; they
are part of the digest contract and change under model-risk review.
"""

from __future__ import annotations

from ...coerce import number
from ...derive import applications
from ...derive.brief_facts import patterns
from ...derive.brief_facts._common import (CAT_CARD, CAT_INSTALLMENT,
                                           F_HIST_BALANCE, F_HIST_DATE,
                                           F_HIST_DELAY, SEC_APPLICATIONS,
                                           SEC_DETAIL, SEC_FACILITIES,
                                           SEC_INCOME, category, contract_label,
                                           fmt, history_by_contract, month,
                                           provider_name, text)
from ...derive.facilities import closed_date
from . import grammar

CONFIRMED = "confirmed"
NOT_SUPPORTED = "not_supported"
NOT_ASSESSABLE = "not_assessable"
VERIFIED = "verified"

# --- thresholds (the verifiers' definitions) ----------------------------------
RISE_POINTS = 15             # utilisation_rise_after: percentage points
TROUGH_SHARE = 0.5           # balance_oscillation: pay-down to <= 50% of limit
PEAK_SHARE = 0.8             # balance_oscillation: re-use to >= 80% of limit
MIN_SWINGS = 2
MIN_OSCILLATION_MONTHS = 6
CATCH_UP_MONTHS = 6          # limit_increase_then_utilisation
BURST_MIN = 3                # application_burst_then_delay
DELAY_AFTER_BURST_MONTHS = 6
INCOME_DECLINE = 0.10        # income_decline_across_updates
ONSET_SPREAD_MONTHS = 3      # correlated_delays
OVERLAP_SHARE = 0.5
MIN_CLUSTER_YEARS = 2        # delay_cluster: distinct years per listed month
MAX_CLUSTER_MONTHS = 4       # delay_cluster: a season, not a whole year

_MONTH_NAMES = ("January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November",
                "December")

F_HIST_UTIL = "contractsHistory[].UtilizationRate"
F_HIST_LIMIT = "contractsHistory[].CreditLimit"
F_HIST_OVERDUE = "contractsHistory[].OverdueAmount"


_month_add = patterns.month_add
_months_apart = patterns.months_apart
_dpd = patterns.dpd


class _Env:
    """The payload views every verifier shares."""

    def __init__(self, ctx, aliases):
        self.ctx = ctx
        self.aliases = aliases
        self.by_contract = history_by_contract(ctx)
        self.labels = {alias: contract_label(ctx, c)
                       for alias, c in aliases.items()}

    def history(self, alias):
        contract = self.aliases[alias]
        return self.by_contract.get(contract.get("CBContractId")) or []

    def histories(self):
        return [(alias, self.history(alias)) for alias in self.aliases]

    def labelled(self):
        return [(self.labels[alias], self.history(alias)) for alias in self.aliases]


# --- utilisation_rise_after -----------------------------------------------------

def _loan_openings(env, contract):
    return [(month(c.get("OpenDate")), "%s opened" % contract_label(env.ctx, c))
            for c in env.ctx.rows("contracts")
            if c is not contract and category(c) == CAT_INSTALLMENT
            and month(c.get("OpenDate"))]


def _applications(env, _contract):
    return [(month(applications.applied_on(a)),
             "an application for %s at %s"
             % (text(a.get("ContractType") or "?"),
                provider_name(env.ctx, a.get("ProviderNo"))))
            for a in env.ctx.rows("applications")
            if month(applications.applied_on(a))]


def _employment_changes(env, _contract):
    out = []
    for r in env.ctx.rows("employment"):
        name = text(r.get("EmploymentName") or "?")
        if month(r.get("DateOfEmployment")):
            out.append((month(r.get("DateOfEmployment")),
                        "employment at %s started" % name))
        if month(r.get("DateOfTermination")):
            out.append((month(r.get("DateOfTermination")),
                        "employment at %s ended" % name))
    return out


def _returned_instruments(env, _contract):
    return [(month(r.get("ReturnDate")),
             "a returned %s of AED %s" % (text(r.get("Type") or "instrument"),
                                          fmt(r.get("Amount"))))
            for r in env.ctx.rows("paymentOrder") if month(r.get("ReturnDate"))]


def _limit_changes(env, contract):
    history = env.by_contract.get(contract.get("CBContractId")) or []
    limits = [(m, number(r.get("CreditLimit"))) for m, r in history
              if number(r.get("CreditLimit")) is not None]
    return [(m, "the credit limit moved from AED %s to AED %s"
             % (fmt(prev), fmt(cur)))
            for (_pm, prev), (m, cur) in zip(limits, limits[1:]) if cur != prev]


_EVENTS = {
    "loan_opened": (_loan_openings, "contracts[].OpenDate"),
    "application": (_applications, "applications[].LastUpdateDate"),
    "employment_change": (_employment_changes,
                          "employment[].DateOfEmployment"),
    "returned_instrument": (_returned_instruments, "paymentOrder[].ReturnDate"),
    "limit_change": (_limit_changes, F_HIST_LIMIT),
}


def _best_rise(pairs, events, horizon):
    """The event with the largest utilisation change over the horizon."""
    best = None
    for when, desc in events:
        before = [p for p in pairs if p[0] <= when]
        after = [p for p in pairs if p[0] >= _month_add(when, horizon)]
        if not before or not after:
            continue
        delta = after[0][1] - before[-1][1]
        if best is None or delta > best[0]:
            best = (delta, before[-1], after[0], when, desc)
    return best


def _utilisation_rise_after(env, params):
    alias, kind, horizon = params["contract"], params["event"], params["months"]
    contract, label = env.aliases[alias], env.labels[alias]
    if category(contract) != CAT_CARD:
        return NOT_ASSESSABLE, "%s is not a card" % label
    pairs = [(m, number(r.get("UtilizationRate"))) for m, r in env.history(alias)
             if number(r.get("UtilizationRate")) is not None]
    if len(pairs) < 2:
        return NOT_ASSESSABLE, "fewer than 2 reported utilisation values on %s" % label
    events = sorted(e for e in _EVENTS[kind][0](env, contract)
                    if pairs[0][0] <= e[0] <= pairs[-1][0])
    if not events:
        return NOT_ASSESSABLE, ("no %s event inside the reported window of %s"
                                % (kind.replace("_", " "), label))
    best = _best_rise(pairs, events, horizon)
    if best is None:
        return NOT_ASSESSABLE, ("no utilisation reported %d month(s) after any %s "
                                "event on %s" % (horizon, kind.replace("_", " "),
                                                 label))
    delta, before, after, when, desc = best
    sentence = ("utilisation on %s %s from %s%% (%s) to %s%% (%s), %d month(s) "
                "after %s (%s)" % (label, "rose" if delta > 0 else "moved",
                                   fmt(before[1]), before[0], fmt(after[1]),
                                   after[0], horizon, desc, when))
    if delta >= RISE_POINTS:
        return CONFIRMED, sentence + "."
    return NOT_SUPPORTED, sentence + ("; no rise of %d points or more."
                                      % RISE_POINTS)


# --- delay_cluster ---------------------------------------------------------------

def _delay_cluster(env, params):
    years_by_month, years = patterns.delayed_years(env.histories())
    if len(years) < MIN_CLUSTER_YEARS:
        return NOT_ASSESSABLE, ("the monthly history spans fewer than %d years"
                                % MIN_CLUSTER_YEARS)
    listed = params["months_of_year"]
    names = ", ".join(_MONTH_NAMES[m - 1] for m in listed)
    if len(listed) > MAX_CLUSTER_MONTHS:
        return NOT_SUPPORTED, ("%d calendar months were named (%s); a seasonal "
                               "cluster is at most %d -- delays across most of "
                               "the year are chronic lateness, not a season."
                               % (len(listed), names, MAX_CLUSTER_MONTHS))
    parts = ["%s: %s" % (_MONTH_NAMES[m - 1],
                         ", ".join(str(y) for y in sorted(years_by_month.get(m, ())))
                         or "no year")
             for m in listed]
    # Recurring in every listed month, AND distinctive: a file late in most
    # months of most years recurs in every calendar month and clusters in none.
    recurring = all(len(years_by_month.get(m, ())) >= MIN_CLUSTER_YEARS
                    for m in listed)
    others = sum(1 for m, ys in years_by_month.items()
                 if m not in listed and len(ys) >= MIN_CLUSTER_YEARS)
    detail = ("delayed months by calendar month -- %s; %d other calendar "
              "month(s) also carry delays in %d or more years"
              % ("; ".join(parts), others, MIN_CLUSTER_YEARS))
    if recurring and others <= (12 - len(listed)) // 2:
        return CONFIRMED, "delays cluster in %s: %s." % (names, detail)
    why = ("they recur there but in most other months too" if recurring
           else "not recurring across %d or more years" % MIN_CLUSTER_YEARS)
    return NOT_SUPPORTED, "delays do not cluster in %s (%s): %s." % (names, why, detail)


# --- balance_oscillation ---------------------------------------------------------

def _balance_oscillation(env, params):
    alias, window = params["contract"], params["window"]
    contract, label = env.aliases[alias], env.labels[alias]
    if category(contract) != CAT_CARD:
        return NOT_ASSESSABLE, "%s is not a card" % label
    history = env.history(alias)
    if not history:
        return NOT_ASSESSABLE, "%s has no monthly history" % label
    pairs = patterns.balances_with_limit(
        contract, history, _month_add(history[-1][0], -(window - 1)))
    if len(pairs) < MIN_OSCILLATION_MONTHS:
        return NOT_ASSESSABLE, ("fewer than %d reported balances on %s in the "
                                "last %d months" % (MIN_OSCILLATION_MONTHS,
                                                    label, window))
    if any(not limit for _, _, limit in pairs):
        return NOT_ASSESSABLE, "no credit limit delivered for %s" % label
    swings = patterns.swings(pairs, TROUGH_SHARE, PEAK_SHARE)
    limit = pairs[-1][2]
    if len(swings) >= MIN_SWINGS:
        return CONFIRMED, (
            "balance on %s swung between pay-down and re-use against a limit "
            "of AED %s: %s (%d swing(s) in the last %d months)."
            % (label, fmt(limit),
               "; ".join("AED %s (%s) to AED %s (%s)"
                         % (fmt(t[1]), t[0], fmt(p[1]), p[0]) for t, p in swings),
               len(swings), window))
    low = min(pairs, key=lambda p: p[1])
    high = max(pairs, key=lambda p: p[1])
    return NOT_SUPPORTED, (
        "balance on %s shows %d pay-down-and-re-use swing(s) in the last %d "
        "months (threshold %d) against a limit of AED %s; it ranged from AED "
        "%s (%s) to AED %s (%s)."
        % (label, len(swings), window, MIN_SWINGS, fmt(limit), fmt(low[1]),
           low[0], fmt(high[1]), high[0]))


# --- limit_increase_then_utilisation ---------------------------------------------

def _first_increase(limits):
    for (_pm, prev), (when, cur) in zip(limits, limits[1:]):
        if cur > prev:
            return when, prev, cur
    return None


def _limit_increase_then_utilisation(env, params):
    alias = params["contract"]
    contract, label = env.aliases[alias], env.labels[alias]
    if category(contract) != CAT_CARD:
        return NOT_ASSESSABLE, "%s is not a card" % label
    history = env.history(alias)
    limits = [(m, number(r.get("CreditLimit"))) for m, r in history
              if number(r.get("CreditLimit")) is not None]
    increase = _first_increase(limits)
    if increase is None:
        return NOT_ASSESSABLE, ("no credit-limit increase in the reported "
                                "history of %s" % label)
    when, old, new = increase
    utils = [(m, number(r.get("UtilizationRate"))) for m, r in history
             if number(r.get("UtilizationRate")) is not None]
    before = [u for u in utils if u[0] < when]
    after = [u for u in utils if when <= u[0] <= _month_add(when, CATCH_UP_MONTHS)]
    if not before or not after:
        return NOT_ASSESSABLE, ("utilisation on %s is not reported on both sides "
                                "of the limit increase in %s" % (label, when))
    base = ("the limit on %s rose from AED %s to AED %s in %s; utilisation was "
            "%s%% (%s) before" % (label, fmt(old), fmt(new), when,
                                   fmt(before[-1][1]), before[-1][0]))
    caught = next((u for u in after if u[1] >= before[-1][1]), None)
    if caught is not None:
        return CONFIRMED, ("%s and was back at %s%% by %s (within %d months) -- "
                           "the extra limit was absorbed."
                           % (base, fmt(caught[1]), caught[0], CATCH_UP_MONTHS))
    peak = max(after, key=lambda u: u[1])
    return NOT_SUPPORTED, ("%s and reached at most %s%% (%s) in the %d months "
                           "after -- the extra limit was not absorbed."
                           % (base, fmt(peak[1]), peak[0], CATCH_UP_MONTHS))


# --- closure_before_enquiry ------------------------------------------------------

def _closure_before_enquiry(env, params):
    if env.ctx.report_date is None:
        return NOT_ASSESSABLE, "no report date to measure the window from"
    window = params["window"]
    report_month = env.ctx.report_date.strftime("%Y-%m")
    cutoff = _month_add(report_month, -window)
    closed = ["%s closed %s" % (env.labels[alias], month(c.get("ClosedDate")))
              for alias, c in env.aliases.items()
              if closed_date(c) and cutoff <= month(c.get("ClosedDate")) <= report_month]
    found = closed + ["%s overdue AED %s (%s) cleared to 0 by %s"
                      % (label, fmt(amount), last, cleared)
                      for label, amount, last, cleared
                      in patterns.clearances(env.labelled(), cutoff)]
    if found:
        return CONFIRMED, ("in the %d months before the report date %s: %s."
                           % (window, report_month, "; ".join(found)))
    return NOT_SUPPORTED, ("no contract was closed and no overdue amount was "
                           "cleared in the %d months before the report date %s."
                           % (window, report_month))


# --- application_burst_then_delay ------------------------------------------------

def _burst(months, window):
    """(count, first, last) of the densest run inside a window of months."""
    best = (0, None, None)
    for i, start in enumerate(months):
        j = i
        while j + 1 < len(months) and _months_apart(start, months[j + 1]) < window:
            j += 1
        if j - i + 1 > best[0]:
            best = (j - i + 1, start, months[j])
    return best


def _application_burst_then_delay(env, params):
    months = sorted(m for m in (month(applications.applied_on(a))
                                for a in env.ctx.rows("applications")) if m)
    if not months:
        return NOT_ASSESSABLE, "no dated applications on file"
    if not any(history for _, history in env.histories()):
        return NOT_ASSESSABLE, "no monthly history to look for a delay in"
    window = params["window"]
    count, first, last = _burst(months, window)
    if count < BURST_MIN:
        return NOT_SUPPORTED, ("at most %d application(s) fell within any %d-month "
                               "span (%d dated applications in all); no burst of "
                               "%d or more." % (count, window, len(months),
                                                BURST_MIN))
    base = "%d applications between %s and %s" % (count, first, last)
    horizon = _month_add(last, DELAY_AFTER_BURST_MONTHS)
    followed = [o for o in patterns.delay_onsets(env.labelled())
                if last < o[0] <= horizon]
    if followed:
        when, label = followed[0]
        return CONFIRMED, ("%s; a new payment delay then began on %s in %s (%d "
                           "month(s) after the last of them)."
                           % (base, label, when, _months_apart(last, when)))
    return NOT_SUPPORTED, ("%s; no new payment delay began on any contract in "
                           "the %d months after." % (base,
                                                     DELAY_AFTER_BURST_MONTHS))


# --- income_decline_across_updates -----------------------------------------------

def _income_decline_across_updates(env, _params):
    dated = [(d, v, text(name)) for d, v, name in patterns.income_sequence(env.ctx)]
    if len(dated) < 2:
        return NOT_ASSESSABLE, "fewer than 2 dated, usable income figures"
    sequence = "; ".join("AED %s (%s, %s)" % (fmt(v), d.strftime("%Y-%m"), name)
                         for d, v, name in dated)
    first, last = dated[0][1], dated[-1][1]
    if last <= first * (1 - INCOME_DECLINE):
        return CONFIRMED, ("reported income fell from AED %s to AED %s across %d "
                           "dated records: %s." % (fmt(first), fmt(last),
                                                   len(dated), sequence))
    return NOT_SUPPORTED, ("reported income did not fall by %d%% or more across "
                           "%d dated records: %s." % (int(INCOME_DECLINE * 100),
                                                      len(dated), sequence))


# --- correlated_delays -----------------------------------------------------------

def _correlated_delays(env, params):
    delayed, firsts = {}, {}
    for alias in params["contracts"]:
        history = env.history(alias)
        if not history:
            return NOT_ASSESSABLE, "%s has no monthly history" % env.labels[alias]
        months = [m for m, r in history if (_dpd(r) or 0) > 0]
        if not months:
            return NOT_SUPPORTED, ("%s has no delayed month, so its delays "
                                   "cannot correlate with another contract's."
                                   % env.labels[alias])
        delayed[alias], firsts[alias] = set(months), months[0]
    spread = _months_apart(min(firsts.values()), max(firsts.values()))
    overlap = len(set.intersection(*delayed.values()))
    smallest = min(len(s) for s in delayed.values())
    detail = ("first delayed months: %s (%d month(s) apart); %d delinquent "
              "month(s) in common"
              % ("; ".join("%s %s" % (env.labels[a], firsts[a])
                           for a in params["contracts"]), spread, overlap))
    if spread <= ONSET_SPREAD_MONTHS or overlap >= OVERLAP_SHARE * smallest:
        return CONFIRMED, "delays on these contracts are correlated -- %s." % detail
    return NOT_SUPPORTED, "delays on these contracts are not correlated -- %s." % detail


# --- the registry ------------------------------------------------------------------

_VERIFIERS = {
    "utilisation_rise_after": (_utilisation_rise_after, SEC_DETAIL,
                               [F_HIST_UTIL, F_HIST_DATE]),
    "delay_cluster": (_delay_cluster, SEC_DETAIL, [F_HIST_DELAY, F_HIST_DATE]),
    "balance_oscillation": (_balance_oscillation, SEC_DETAIL,
                            [F_HIST_BALANCE, F_HIST_LIMIT, F_HIST_DATE]),
    "limit_increase_then_utilisation": (_limit_increase_then_utilisation,
                                        SEC_DETAIL,
                                        [F_HIST_LIMIT, F_HIST_UTIL, F_HIST_DATE]),
    "closure_before_enquiry": (_closure_before_enquiry, SEC_FACILITIES,
                               ["contracts[].ClosedDate", F_HIST_OVERDUE,
                                F_HIST_DATE]),
    "application_burst_then_delay": (_application_burst_then_delay,
                                     SEC_APPLICATIONS,
                                     ["applications[].LastUpdateDate",
                                      F_HIST_DELAY, F_HIST_DATE]),
    "income_decline_across_updates": (_income_decline_across_updates, SEC_INCOME,
                                      ["employment[].GrossAnnualIncome",
                                       "employment[].DateOfLastUpdate",
                                       "employment[].DateOfEmployment"]),
    "correlated_delays": (_correlated_delays, SEC_DETAIL,
                          [F_HIST_DELAY, F_HIST_DATE]),
}

_PREFIX = {CONFIRMED: "Verified hypothesis (confirmed): ",
           NOT_SUPPORTED: "Verified hypothesis (not supported): "}


def run(ctx, typed, aliases) -> list:
    """Every typed hypothesis verified, in order: {type, params, params_text,
    status, text, fields, section}."""
    env = _Env(ctx, aliases)
    out = []
    for hypothesis in typed:
        verifier, section, fields = _VERIFIERS[hypothesis["type"]]
        status, sentence = verifier(env, hypothesis["params"])
        event = hypothesis["params"].get("event")
        extra = [_EVENTS[event][1]] if event else []
        out.append({
            "type": hypothesis["type"],
            "params": hypothesis["params"],
            "params_text": grammar.describe(hypothesis, env.labels),
            "status": status,
            "text": sentence,
            "fields": fields + extra,
            "section": section,
        })
    return out


def as_facts(results, next_number: int) -> list:
    """Facts for the confirmed and refuted results, numbered from next_number.

    Each carries its status and the hypothesis it answers, so the validator
    can cap a finding that rests only on refuted facts and the page can show
    the loop.
    """
    facts = []
    for result in results:
        if result["status"] not in _PREFIX:
            continue
        facts.append({
            "id": "F%03d" % (next_number + len(facts)),
            "theme": VERIFIED,
            "text": _PREFIX[result["status"]] + result["text"],
            "fields": list(result["fields"]),
            "section": result["section"],
            "status": result["status"],
            "hypothesis": result["params_text"],
        })
    return facts
