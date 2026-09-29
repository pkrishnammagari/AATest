"""Behavior lens: patterns in conduct -- where the borrower ranks this lender
in the payment waterfall, early-tenor delinquency, the character of returned
instruments, what revolving balances did after a new loan, balance-transfer
shapes and dormant lines waking up."""

from __future__ import annotations

from ... import dates
from ...coerce import number
from ._common import (BEHAVIOR, CAT_CARD, CAT_INSTALLMENT, F_HIST_BALANCE,
                      F_HIST_DATE, F_HIST_DELAY, SEC_DETAIL, SEC_FACILITIES,
                      SEC_RETURNS, STRUCTURE, category, contract_label, fmt,
                      is_active, is_set, month, text)

# --- payment waterfall ---------------------------------------------------------
# Where does this borrower rank their obligations? An NBFI is structurally
# junior in the payment waterfall, so conduct SPLIT by provider kind and by
# repayment method says more about the lender's own risk than any aggregate.

_KIND_LABELS = {"bank": "bank", "tel": "telecom", "nbfi": "NBFI"}

_SALARY_TRANSFER = "salary transfer"
_DIRECT_DEBIT = "direct debit"


def _worst_delay(contract, history):
    """The worst delay ever evidenced for a contract: the delivered lifetime
    peak or anything larger the monthly history shows.

    None when neither carries a delay value -- no evidence is not a clean
    record, and must never be described as one.
    """
    values = [number(contract.get("MaxDaysPaymentDelay"))]
    values.extend(number(r.get("DaysPaymentDelay")) for _, r in history)
    values = [v for v in values if v is not None]
    return max(values) if values else None


def _delay_text(delay) -> str:
    if delay is None:
        return "no delay reported"
    return ("worst delay %s days" % fmt(delay)) if delay else "clean"


def _late_months(history) -> int:
    return sum(1 for _, r in history
               if (number(r.get("DaysPaymentDelay")) or 0) > 0)


def _kind_totals(ctx, by_contract) -> dict:
    groups = {}
    for contract in ctx.rows("contracts"):
        if not is_active(contract):
            continue
        kind = ctx.provider(contract.get("ProviderNo"))["kind"]
        history = by_contract.get(contract.get("CBContractId")) or []
        entry = groups.setdefault(kind, {
            "count": 0, "balance": 0.0, "limit": 0.0, "overdue": 0.0,
            "worst": None, "late_months": 0})
        entry["count"] += 1
        entry["balance"] += number(contract.get("Current_Balance")) or 0
        entry["limit"] += number(contract.get("Current_CreditLimit")) or 0
        entry["overdue"] += number(contract.get("Current_OverdueAmount")) or 0
        worst = _worst_delay(contract, history)
        if worst is not None:
            entry["worst"] = max(entry["worst"] or 0.0, worst)
        entry["late_months"] += _late_months(history)
    return groups


def waterfall(ctx, facts, by_contract):
    """Conduct and exposure split by provider kind (bank / telecom / NBFI).

    providers.json currently tags every B## code as a bank, so the NBFI split
    stays silent until that registry is curated -- the grouping is by
    ctx.provider()['kind'] and activates on its own when 'nbfi' entries
    appear. Telecom gets its own sentence and no shared aggregate: telecom
    delinquency is noisier than bank delinquency, and the prompt carries that
    asymmetry so the model does not equate the two.
    """
    groups = _kind_totals(ctx, by_contract)
    if len(groups) < 2:
        # One provider kind is no split; the per-contract facts cover it.
        return

    def sentence(kind, entry):
        worst = ("no delay reported" if entry["worst"] is None
                 else "worst delay %s days" % fmt(entry["worst"]))
        return ("%s providers -- %d active contract(s), %s, "
                "%d delinquent reported month(s), current overdue AED %s"
                % (_KIND_LABELS.get(kind, kind), entry["count"], worst,
                   entry["late_months"], fmt(entry["overdue"])))

    ordered = sorted(groups.items(),
                     key=lambda kv: _KIND_LABELS.get(kv[0], kv[0]))
    facts.add(BEHAVIOR,
              "Conduct split by provider kind (active contracts): %s."
              % "; ".join(sentence(k, e) for k, e in ordered),
              ["contracts[].ProviderNo", "contracts[].Current_OverdueAmount",
               F_HIST_DELAY],
              SEC_FACILITIES)
    facts.add(STRUCTURE,
              "Exposure split by provider kind (active contracts): %s."
              % "; ".join("%s -- balances AED %s, limits AED %s"
                          % (_KIND_LABELS.get(k, k), fmt(e["balance"]),
                             fmt(e["limit"]))
                          for k, e in ordered),
              ["contracts[].ProviderNo", "contracts[].Current_Balance",
               "contracts[].Current_CreditLimit"],
              SEC_FACILITIES)


def _method(contract) -> str:
    return str(contract.get("MethodOfPayment") or "").strip().lower()


def _contract_worst(contract, by_contract):
    return _worst_delay(contract,
                        by_contract.get(contract.get("CBContractId")) or [])


def _describe_conduct(ctx, contract, by_contract) -> str:
    return "%s (%s)" % (contract_label(ctx, contract),
                        _delay_text(_contract_worst(contract, by_contract)))


def _method_mix(ctx, facts, active, st, dd, by_contract):
    """The structure fact: which active contracts repay how."""
    parts = []
    if st:
        parts.append("%d on Salary Transfer: %s"
                     % (len(st), "; ".join(_describe_conduct(ctx, c, by_contract)
                                           for c in st)))
    if dd:
        parts.append("%d on Direct Debit: %s"
                     % (len(dd), "; ".join(_describe_conduct(ctx, c, by_contract)
                                           for c in dd)))
    unstated = len(active) - len(st) - len(dd)
    if unstated:
        parts.append("%d with no method reported" % unstated)
    facts.add(STRUCTURE,
              "Repayment method on active contracts -- %s. Salary-transfer "
              "repayment is deducted at source, so its conduct is largely "
              "involuntary." % ". ".join(parts),
              ["contracts[].MethodOfPayment"],
              SEC_FACILITIES)


def _salary_transfer_reading(ctx, facts, active, st, by_contract):
    """The behavior fact: delinquency on an at-source deduction, or clean
    conduct that is entirely at-source."""
    st_delinquent = [c for c in st if (_contract_worst(c, by_contract) or 0) > 0]
    if st_delinquent:
        facts.add(BEHAVIOR,
                  "Delinquency on salary-transfer contract(s): %s. Delay on "
                  "an at-source deduction is consistent with the salary "
                  "stopping or moving accounts -- a job-loss or "
                  "account-switch signal, not ordinary payment choice."
                  % "; ".join(_describe_conduct(ctx, c, by_contract)
                              for c in st_delinquent),
                  ["contracts[].MethodOfPayment",
                   "contracts[].MaxDaysPaymentDelay"],
                  SEC_FACILITIES)
        return
    clean = [c for c in active if _contract_worst(c, by_contract) == 0]
    if (clean and st and len(clean) < len(active)
            and all(_method(c) == _SALARY_TRANSFER for c in clean)):
        facts.add(BEHAVIOR,
                  "Every clean active contract is on Salary Transfer "
                  "(%d of %d active); conduct on involuntary at-source "
                  "repayment does not demonstrate willingness to pay "
                  "voluntary obligations." % (len(clean), len(active)),
                  ["contracts[].MethodOfPayment"],
                  SEC_FACILITIES)


def method_of_payment(ctx, facts, by_contract):
    """contracts[].MethodOfPayment, read as waterfall position.

    Salary Transfer repayment is deducted at source: clean conduct there is
    involuntary and says nothing about willingness to pay, while delinquency
    there means the salary stopped or moved -- both readings are computed
    here, per the house rule that interpretation is arithmetic.
    """
    active = [c for c in ctx.rows("contracts") if is_active(c)]
    st = [c for c in active if _method(c) == _SALARY_TRANSFER]
    dd = [c for c in active if _method(c) == _DIRECT_DEBIT]
    if not st and not dd:
        return
    _method_mix(ctx, facts, active, st, dd, by_contract)
    _salary_transfer_reading(ctx, facts, active, st, by_contract)


# --- early tenor -----------------------------------------------------------------

def _history_hit(label, opened, history):
    """FPD evidence from monthly history that covers the opening, or None."""
    first_late = next((m for m, r in history
                       if (number(r.get("DaysPaymentDelay")) or 0) > 0), None)
    if not first_late:
        return None
    gap = dates.months_between(opened, first_late + "-01")
    if gap is None or gap > 3:
        return None
    return ("%s: first reported delay in %s, within 3 months of opening"
            % (label, first_late))


def _delivered_hit(label, opened, contract):
    """FPD evidence from the delivered worst-delay date, or None."""
    peak = number(contract.get("MaxDaysPaymentDelay")) or 0
    peak_date = dates.parse_any(contract.get("MaxDaysPaymentDelayDate"))
    if peak > 0 and peak_date and 0 <= (peak_date - opened).days <= 90:
        return ("%s: the worst delay on record (%s days) is dated within 90 "
                "days of opening" % (label, fmt(peak)))
    return None


def _early_tenor_hit(ctx, contract, history):
    """One contract's first-payment-default evidence as text, or None.

    Two delivered-field paths, because the history window cannot see the
    early tenor of older contracts: the monthly history where it covers the
    opening (its first reported month is no later than the opening month),
    else the delivered worst-delay date against the open date.
    """
    opened = dates.parse_any(contract.get("OpenDate"))
    if not opened:
        return None
    label = contract_label(ctx, contract)
    start = dates.parse_any(history[0][0] + "-01") if history else None
    if start is not None and start <= opened:
        return _history_hit(label, opened, history)
    return _delivered_hit(label, opened, contract)


def early_tenor_delinquency(ctx, facts, by_contract):
    """First-payment-default pattern: delinquency in a contract's first
    months. One combined fact -- repeat FPD is a pattern, not a list."""
    hits = [hit for hit in (
        _early_tenor_hit(ctx, contract,
                         by_contract.get(contract.get("CBContractId")) or [])
        for contract in ctx.rows("contracts")) if hit]
    if not hits:
        return
    facts.add(BEHAVIOR,
              "Early-tenor delinquency (a first-payment-default pattern is "
              "fraud-adjacent): %s." % "; ".join(hits),
              ["contracts[].OpenDate", "contracts[].MaxDaysPaymentDelayDate",
               F_HIST_DELAY],
              SEC_DETAIL)


# --- returned instruments --------------------------------------------------------

def _distinct_text(rows, field):
    return sorted({text(r.get(field)) for r in rows if r.get(field)})


def _returns_timeline(ctx, dated) -> str:
    newest = dates.parse_any(dated[-1].get("ReturnDate"))
    gap = dates.months_between(newest, ctx.report_date)
    ages = [dates.months_between(dates.parse_any(r.get("ReturnDate")),
                                 ctx.report_date) for r in dated]
    # 0 is a real age (a return in the report month), not a missing one.
    recent = [age for age in ages if age is not None and age <= 3]
    return (" Timeline: %s. The latest was %s month(s) before the report "
            "date; %d fell within the 3 months before it."
            % ("; ".join("%s AED %s in %s"
                         % (text(r.get("Type") or "?"),
                            fmt(r.get("Amount")), month(r.get("ReturnDate")))
                         for r in dated),
               gap if gap is not None else "?", len(recent)))


def returned_instruments(ctx, facts):
    """The character of the paymentOrder trail, not just its count.

    One counterparty repeatedly vs many accounts, the stated reasons, and how
    recent the latest event is -- the shape that separates a soured
    relationship from diffuse liquidity failure.
    """
    rows = ctx.rows("paymentOrder")
    if not rows:
        return
    dated = sorted((r for r in rows if dates.parse_any(r.get("ReturnDate"))),
                   key=lambda r: dates.parse_any(r.get("ReturnDate")))
    total = sum(v for v in (number(r.get("Amount")) for r in rows)
                if v is not None)
    accounts = {str(r.get("IBAN") or "").strip() for r in rows if r.get("IBAN")}
    text = ("%d returned instrument(s) totalling AED %s across %d distinct "
            "account(s); types: %s; stated reason(s): %s."
            % (len(rows), fmt(total), len(accounts),
               ", ".join(_distinct_text(rows, "Type")) or "?",
               ", ".join(_distinct_text(rows, "Reason")) or "?"))
    if dated:
        text += _returns_timeline(ctx, dated)
    facts.add(BEHAVIOR, text,
              ["paymentOrder[].Type", "paymentOrder[].Amount",
               "paymentOrder[].IBAN", "paymentOrder[].Reason",
               "paymentOrder[].ReturnDate"],
              SEC_RETURNS)


# --- balances after a new loan ---------------------------------------------------

def _card_steps(card_history, checkpoints):
    """'AED 12,000 (2024-01) -> AED 9,500 (+3m 2024-04) ...' for one card."""
    steps = []
    for offset, when in checkpoints:
        balance = number((card_history.get(when) or {}).get("Balance"))
        if balance is None:
            continue
        steps.append("AED %s (%s)" % (fmt(balance),
                                      when if offset == 0
                                      else "+%dm %s" % (offset, when)))
    return steps


def _loan_card_moves(ctx, loan, cards, by_contract):
    """(one move per card with at least two checkpoints, edge note)."""
    open_month = month(loan.get("OpenDate"))
    checkpoints = [(0, open_month)] + [
        (offset, month(dates.add_months(loan.get("OpenDate"), offset)))
        for offset in (3, 6, 12)]
    moves = []
    ends = []
    for card in cards:
        history = dict(by_contract.get(card.get("CBContractId")) or [])
        if not history:
            continue
        steps = _card_steps(history, checkpoints)
        if len(steps) < 2:
            continue
        last_reported = max(history)
        if checkpoints[-1][1] > last_reported:
            ends.append(last_reported)
        moves.append("%s: %s" % (contract_label(ctx, card), " -> ".join(steps)))
    edge_note = ""
    if ends:
        edge_note = (" History for at least one of these cards ends %s; later "
                     "checkpoints are unreported, not cured." % min(ends))
    return moves, edge_note


def post_loan_balances(ctx, facts, by_contract):
    """For each recent installment loan, what card balances did in the
    following year.

    The +3-month look answers "did it consolidate at all"; the +6 and +12
    re-checks answer the question that actually predicts consolidation-card
    losses: balances that fell and then RE-STACKED. Every checkpoint the
    history cannot show is named, so a missing +12 never reads as cured --
    the same absence rule the heatmap follows.
    """
    loans = sorted((c for c in ctx.rows("contracts")
                    if category(c) == CAT_INSTALLMENT
                    and dates.parse_any(c.get("OpenDate"))),
                   key=lambda c: dates.parse_any(c.get("OpenDate")),
                   reverse=True)[:3]
    cards = [c for c in ctx.rows("contracts") if category(c) == CAT_CARD]

    for loan in loans:
        moves, edge_note = _loan_card_moves(ctx, loan, cards, by_contract)
        if not moves:
            continue
        facts.add(BEHAVIOR,
                  "After %s opened in %s (amount AED %s), card balances "
                  "moved: %s. Sustained falls read as consolidation; "
                  "fell-then-rebounded reads as failed consolidation "
                  "(re-stacking); rising throughout as stacked leverage.%s"
                  % (contract_label(ctx, loan), month(loan.get("OpenDate")),
                     fmt(number(loan.get("TotalAmount"))
                         or number(loan.get("Current_CreditLimit"))),
                     "; ".join(moves), edge_note),
                  ["contracts[].OpenDate", "contracts[].TotalAmount",
                   F_HIST_BALANCE, F_HIST_DATE],
                  SEC_DETAIL)


def _collapses(ctx, card, history, openings):
    """Months a card balance collapsed to near zero while another facility
    opened within 45 days, as text."""
    traces = []
    for (prev_month, prev_row), (when, row) in zip(history, history[1:]):
        prev_balance = number(prev_row.get("Balance")) or 0
        balance = number(row.get("Balance")) or 0
        if prev_balance < 1000 or balance > 0.05 * prev_balance:
            continue
        collapse_month = dates.parse_any(when + "-01")
        nearby = [c for c, opened in openings
                  if c is not card and collapse_month
                  and abs((opened - collapse_month).days) <= 45]
        if nearby:
            traces.append(
                "%s balance fell AED %s (%s) to AED %s (%s) while %s opened"
                % (contract_label(ctx, card), fmt(prev_balance), prev_month,
                   fmt(balance), when,
                   "; ".join(contract_label(ctx, c) for c in nearby)))
    return traces


def balance_transfer_trace(ctx, facts, by_contract):
    """A card balance collapsing to near-zero in the month a new facility
    opens elsewhere: the balance-transfer shape a consolidation-card
    underwriter looks for and no single row shows."""
    openings = [(c, dates.parse_any(c.get("OpenDate")))
                for c in ctx.rows("contracts")
                if dates.parse_any(c.get("OpenDate"))]
    traces = []
    for card in ctx.rows("contracts"):
        if category(card) != CAT_CARD:
            continue
        history = by_contract.get(card.get("CBContractId")) or []
        traces.extend(_collapses(ctx, card, history, openings))
    if not traces:
        return
    facts.add(BEHAVIOR,
              "Balance-transfer shape: %s." % ". ".join(traces),
              [F_HIST_BALANCE, "contracts[].OpenDate"],
              SEC_DETAIL)


def dormant_reactivation(facts, label, history):
    """A card asleep for months that starts spending again. The wake-up month
    matters most next to other contracts' first overdues."""
    run = 0
    dormant_run = 0
    wake_month = None
    for when, row in history:
        spent = number(row.get("AmountSpent"))
        used = is_set(row.get("CardUsedFlag")) or (spent or 0) > 0
        if used:
            if run >= 4:
                # The LATEST wake-up is reported, with the dormant run
                # that preceded it.
                dormant_run, wake_month = run, when
            run = 0
        else:
            run += 1
    if wake_month is None:
        return
    facts.add(BEHAVIOR,
              "%s -- unused for %d consecutive reported months, then spending "
              "resumes in %s." % (label, dormant_run, wake_month),
              ["contractsHistory[].CardUsedFlag",
               "contractsHistory[].AmountSpent", F_HIST_DATE],
              SEC_DETAIL)
