"""Trajectory lens: per-contract time series from contractsHistory --
utilization slope, limit cuts, delinquency episodes and their cure state,
balance direction, the month each contract first went overdue, and the
revolver/transactor pattern of cards. The report renders conduct as a heatmap;
the digest spells the same months out as numbers a language model can read."""

from __future__ import annotations

from ...coerce import number
from ._common import (F_HIST_BALANCE, F_HIST_DATE, F_HIST_DELAY, SEC_DETAIL,
                      SERIES_MONTHS, TRAJECTORY, fmt, is_set, series_text)


def utilization_series(facts, label, history):
    pairs = [(m, r) for m, r in history
             if number(r.get("UtilizationRate")) is not None]
    if len(pairs) < 2:
        return
    window = pairs[-SERIES_MONTHS:]

    # A moving credit limit changes utilization with no borrower action at
    # all -- without this note, a lender-side limit cut reads as borrower
    # deterioration, which is exactly backwards.
    limits = [(m, number(r.get("CreditLimit"))) for m, r in window
              if number(r.get("CreditLimit")) is not None]
    limit_note = ""
    if limits and limits[0][1] != limits[-1][1]:
        limit_note = (" The credit limit was not constant over this window "
                      "(AED %s in %s, AED %s in %s), so part of the "
                      "utilization movement is mechanical rather than "
                      "borrower spending."
                      % (fmt(limits[0][1]), limits[0][0],
                         fmt(limits[-1][1]), limits[-1][0]))

    facts.add(TRAJECTORY,
              "%s -- reported monthly utilization%%: %s.%s"
              % (label,
                 series_text(window, lambda r: fmt(r.get("UtilizationRate"))),
                 limit_note),
              ["contractsHistory[].UtilizationRate",
               "contractsHistory[].CreditLimit", F_HIST_DATE],
              SEC_DETAIL)


def limit_series(facts, label, history):
    """A decreasing card limit: possibly another institution de-risking this
    borrower -- information no conduct row carries. Observationally identical
    to a customer-requested reduction, so the fact stays neutral and the
    prompt asks the model to treat it as a question for the customer."""
    limits = [(m, number(r.get("CreditLimit"))) for m, r in history
              if number(r.get("CreditLimit")) is not None]
    if len(limits) < 2:
        return
    peak_month, peak = max(limits, key=lambda pair: pair[1])
    after = [(m, v) for m, v in limits if m > peak_month]
    if not after:
        return
    low_month, low = min(after, key=lambda pair: pair[1])
    if low >= peak:
        return
    facts.add(TRAJECTORY,
              "%s -- the credit limit was reduced: AED %s (%s) down to "
              "AED %s (%s). The payload does not say whether the lender or "
              "the customer initiated the reduction."
              % (label, fmt(peak), peak_month, fmt(low), low_month),
              ["contractsHistory[].CreditLimit", F_HIST_DATE],
              SEC_DETAIL)


def delay_episodes(history):
    """Consecutive delinquent runs in reported months, with their cure state.

    An episode ends at the first CLEAN reported month after it; an episode
    still delinquent at the last reported month is open, which is the most
    collections-relevant state a contract can be in. Reported months only --
    a reporting gap neither cures nor extends an episode, it just is not
    evidence. The same holds for a reported month that carries no delay
    value: it is skipped, never read as a clean month that cures.
    """
    episodes = []
    current = None
    for when, row in history:
        delay = number(row.get("DaysPaymentDelay"))
        if delay is None:
            continue
        overdue = number(row.get("OverdueAmount")) or 0
        if delay > 0:
            if current is None:
                current = {"start": when, "months": 0,
                           "peak_delay": 0.0, "peak_overdue": 0.0}
            current["months"] += 1
            current["end"] = when
            current["last_delay"] = delay
            current["last_overdue"] = overdue
            current["peak_delay"] = max(current["peak_delay"], delay)
            current["peak_overdue"] = max(current["peak_overdue"], overdue)
        elif current is not None:
            current["cured_by"] = when
            episodes.append(current)
            current = None
    if current is not None:
        current["cured_by"] = None
        episodes.append(current)
    return episodes


def _describe_episode(ep, last_month) -> str:
    if ep["cured_by"]:
        return ("%s to %s (%d reported month(s), peak %s days, peak overdue "
                "AED %s) cured by %s"
                % (ep["start"], ep["end"], ep["months"],
                   fmt(ep["peak_delay"]), fmt(ep["peak_overdue"]),
                   ep["cured_by"]))
    return ("running since %s and NOT cured: %s days delayed and AED %s "
            "overdue at the last reported month %s"
            % (ep["start"], fmt(ep["last_delay"]), fmt(ep["last_overdue"]),
               last_month))


def delay_series(facts, label, history):
    late = [(m, r) for m, r in history
            if (number(r.get("DaysPaymentDelay")) or 0) > 0]
    if not late:
        return
    window = late[-SERIES_MONTHS:]
    peak = max(number(r.get("DaysPaymentDelay")) for _, r in late)

    # Cure velocity: whether each episode recovered, and how it stands at the
    # last reported month. A borrower who has cured before is collectible; an
    # episode still climbing at the window's edge is the opposite.
    described = [_describe_episode(ep, history[-1][0])
                 for ep in delay_episodes(history)[-3:]]

    text = ("%s -- months reported with payment delay (days): %s. Peak delay "
            "%s days across %d delinquent month(s). Episodes: %s."
            % (label,
               series_text(window, lambda r: fmt(r.get("DaysPaymentDelay"))),
               fmt(peak), len(late), "; ".join(described)))
    facts.add(TRAJECTORY, text,
              [F_HIST_DELAY, "contractsHistory[].OverdueAmount", F_HIST_DATE],
              SEC_DETAIL)


def balance_trend(facts, label, history):
    pairs = [(m, r) for m, r in history if number(r.get("Balance")) is not None]
    if len(pairs) < 2:
        return
    window = pairs[-SERIES_MONTHS:]
    first_month, first_row = window[0]
    last_month, last_row = window[-1]
    first, last = number(first_row.get("Balance")), number(last_row.get("Balance"))
    if first == last:
        direction = "flat"
    else:
        direction = "rising" if last > first else "falling"
    facts.add(TRAJECTORY,
              "%s -- balance %s over the reported window: AED %s (%s) to "
              "AED %s (%s)."
              % (label, direction, fmt(first), first_month, fmt(last),
                 last_month),
              [F_HIST_BALANCE, F_HIST_DATE],
              SEC_DETAIL)


def overdue_onsets(facts, labelled_histories):
    """The month each contract FIRST reports an overdue amount -- one combined
    fact, because the signal is the alignment across contracts, and a model
    reading nine separate onset facts tends to narrate them one by one."""
    onsets = []
    for label, history in labelled_histories:
        for when, row in history:
            if (number(row.get("OverdueAmount")) or 0) > 0:
                onsets.append("%s first overdue in %s" % (label, when))
                break
    if not onsets:
        return
    facts.add(TRAJECTORY,
              "Overdue onset by contract: %s." % "; ".join(onsets),
              ["contractsHistory[].OverdueAmount", F_HIST_DATE],
              SEC_DETAIL)


def minimum_payment_streaks(facts, label, history):
    """Longest run of minimum-only months. The synthetic fixture delivers the
    flag as null throughout, so this fact usually stays silent -- absence of
    the flag is not evidence of full payments and must not become a fact."""
    best = run = 0
    for _, row in history:
        run = run + 1 if is_set(row.get("MinimumPaymentFlag")) else 0
        best = max(best, run)
    if best >= 3:
        facts.add(TRAJECTORY,
                  "%s -- minimum payment flagged for %d consecutive reported "
                  "months." % (label, best),
                  ["contractsHistory[].MinimumPaymentFlag"],
                  SEC_DETAIL)


def _spend_label(carried, total, spending, spend_months) -> str:
    """Revolver / transactor label once spend evidence exists."""
    if carried >= 0.75 * total and spending == 0:
        # A balance that persists with zero reported spending is not
        # revolving -- nothing is being added; it is an inactive card being
        # paid down (or not).
        return ("a carried balance with no reported spending -- an inactive "
                "card paying down, not active revolving")
    if carried >= 0.75 * total and spending >= 0.5 * spend_months:
        return "a revolving pattern"
    if carried <= 0.25 * total:
        return "a transacting pattern"
    return "a mixed pattern"


def _spent(row) -> bool:
    return ((number(row.get("AmountSpent")) or 0) > 0
            or (number(row.get("BilledAmount")) or 0) > 0)


def card_payment_pattern(facts, label, history):
    """Revolver-vs-transactor stats for a card, Python-labelled.

    The classification is fundamental card underwriting (a consolidation
    product targets revolvers; a transactor on a promo card is adverse
    selection), and per the house doctrine the LABEL is computed here, not
    left to the model. Where spend evidence is absent (both fixtures deliver
    AmountSpent/BilledAmount as null) the fact carries the stats plus an
    explicit caveat instead of a label -- a carried balance on an inactive
    card is paydown, not revolving, and the payload cannot tell the
    difference without spend fields.

    contractsHistory.PaymentBehaviour is deliberately NOT read: it arrives
    as an undocumented '0'/'1'/null coding, and this codebase's rule for
    unknown vocabularies is a config under MRM (see status_codes.json), not
    a guess.
    """
    pairs = [(m, r) for m, r in history if number(r.get("Balance")) is not None]
    pairs = pairs[-SERIES_MONTHS:]
    if len(pairs) < 6:
        return
    carried = sum(1 for _, r in pairs if (number(r.get("Balance")) or 0) > 0)
    total = len(pairs)
    spend_rows = [r for _, r in pairs
                  if r.get("AmountSpent") is not None
                  or r.get("BilledAmount") is not None]

    if spend_rows:
        spending = sum(1 for r in spend_rows if _spent(r))
        facts.add(TRAJECTORY,
                  "%s -- balance carried in %d of %d reported month(s) with "
                  "spending in %d: %s."
                  % (label, carried, total, spending,
                     _spend_label(carried, total, spending, len(spend_rows))),
                  [F_HIST_BALANCE, "contractsHistory[].AmountSpent",
                   "contractsHistory[].BilledAmount"],
                  SEC_DETAIL)
    elif carried >= 0.75 * total or carried <= 0.25 * total:
        facts.add(TRAJECTORY,
                  "%s -- a balance was carried in %d of %d reported month(s); "
                  "AmountSpent and BilledAmount not delivered, so revolving "
                  "and paying down cannot be told apart."
                  % (label, carried, total),
                  [F_HIST_BALANCE],
                  SEC_DETAIL)
