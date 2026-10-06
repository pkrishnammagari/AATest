"""The credit team's ten-step review as STEP PACKETS for the checklist block.

The model performs each step -- it judges -- but it never does arithmetic:
every day count, expiry delta, window test and ratio-free comparison a step
needs is computed here, deterministically, and handed over as facts the
model can cite. A packet is one step's question plus the ids of the facts
that bear on it: the digest facts already in that step's report section,
and the arithmetic facts added here (theme "step").

Each packet also names its TRIPWIRES: facts that, in the team's own
process, make the step at least "attention". The model's judgement stands;
the checklist block compares it with the tripwires afterwards and flags a
step marked clear despite one as a possible miss.

Step 2 (name, age, country against policy) is deliberately thin: the policy
data is not connected yet, the applicant's name is not sent to the model
(no subject identifier ever is), and nationality, gender and residency never
enter the digest (PROHIBITED_FIELDS). The step carries the age only.

The ten steps and their titles are the team's, verbatim in intent:
 1 enquiry date within 30 days, 2 name/age/country vs policy, 3 Emirates ID,
 passport, phone, e-mail, latest address, 4 AECB score, bands, vintage,
 5 worst statuses, 6 income/employment, 7 cheque returns and DD bounces
 (6-month focus), 8 active facilities: utilisation, overdue, instalments,
 9 36-month conduct: delays, over-limits, adverse statuses, 10 applications
 in the last 90 days requested but not taken up.
"""

from __future__ import annotations

from ... import dates
from ...coerce import number
from .. import applications, facilities, identity, income, returns, scoring
from . import trajectory
from ._common import (CAT_CARD, CAT_INSTALLMENT, RISK, SEC_APPLICATIONS,
                      SEC_DETAIL, SEC_FACILITIES, SEC_IDENTITY, SEC_INCOME,
                      SEC_RETURNS, SEC_SCORE, SEC_WORST, Facts, category,
                      contract_label, fmt, history_by_contract, is_active,
                      month, text)

STEP = "step"

# Over-limit is inferred: the history carries no flag for it.
_OVER_LIMIT_UTIL = 100
# A delay the team treats as a conduct event in its own right.
_DELAY_DAYS = 30


class _Packet:
    """Collects one step's fact ids while its builder runs."""

    def __init__(self, facts, existing_ids):
        self.facts = facts
        self.ids = list(existing_ids)
        self.tripwires = []
        self.reason = ""

    def add(self, text_, fields, section, trip=False) -> str:
        self.facts.add(STEP, text_, fields, section)
        fid = self.facts.rows[-1]["id"]
        self.ids.append(fid)
        if trip:
            self.tripwires.append(fid)
        return fid

    def trip(self, fid) -> None:
        if fid not in self.tripwires:
            self.tripwires.append(fid)


def _date(d) -> str:
    return d.strftime("%Y-%m-%d") if d else "unknown"


# --- the steps ----------------------------------------------------------------

def _validity(ctx, p):
    v = scoring.validity(ctx)
    fields = ['sectionStatus[]."Last EnquiryDate"', "score.DataPullDate"]
    if v["state"] == "unknown":
        p.add("Report validity: no enquiry date or pull date was delivered, "
              "so the report's age cannot be established against the %d-day "
              "validity window." % v["window"], fields, None, trip=True)
        return
    basis = "enquiry date" if v["basis"] == "enquiry" else "data pull date"
    if v["state"] == "future":
        p.add("Report validity: the %s %s is after today, so the report "
              "cannot be graded as valid; treat as not usable until "
              "clarified." % (basis, _date(v["report_date"])), fields, None,
              trip=True)
        return
    verdict = ("within the window" if v["state"] == "valid" else
               "outside the window: the report is stale and a fresh one is "
               "needed")
    p.add("Report validity: the %s %s is %d day(s) old today against the "
          "%d-day validity window -- %s (valid until %s)."
          % (basis, _date(v["report_date"]), v["age_days"], v["window"],
             verdict, _date(v["expires"])), fields, None,
          trip=v["state"] != "valid")


def _profile(ctx, p):
    dob = ctx.customer.get("DOB")
    age = identity.age_at(dob, ctx.report_date) if dob and ctx.report_date else None
    if age is None:
        head = ("Applicant profile: age cannot be established (date of birth "
                "or report date missing)")
    else:
        head = "Applicant profile: age %d at the report date" % age
    p.add(head + ". The comparison of name, age and country against credit "
          "policy is not available to this analysis (policy data not yet "
          "connected): assess only what the bureau file shows.",
          ["customerInfo.DOB"], SEC_IDENTITY)
    p.reason = ""


def _document(ctx, p, info_type, label, required):
    current, _prior = identity.identifiers(ctx, info_type)
    if not current:
        p.add("%s: none on file." % label, ["identification[].InfoType"],
              SEC_IDENTITY, trip=required)
        return
    for entry in current:
        expiry = dates.parse_any(entry.extra.get("ExpiryDate"))
        if not expiry:
            p.add("%s on file with no readable expiry date." % label,
                  ["identification[].ExpiryDate"], SEC_IDENTITY, trip=required)
        elif expiry < ctx.report_date:
            p.add("%s on file expired on %s, %d day(s) before the report "
                  "date %s." % (label, _date(expiry),
                                dates.days_between(expiry, ctx.report_date),
                                _date(ctx.report_date)),
                  ["identification[].ExpiryDate"], SEC_IDENTITY, trip=True)
        else:
            p.add("%s on file valid until %s, %d day(s) after the report "
                  "date." % (label, _date(expiry),
                             dates.days_between(ctx.report_date, expiry)),
                  ["identification[].ExpiryDate"], SEC_IDENTITY)


def _contacts(ctx, p):
    mobiles, _ = identity.contacts(ctx, "Mobile Number")
    valid_mobiles = sum(1 for e in mobiles if identity.is_uae_mobile(e.value))
    emails, _ = identity.contacts(ctx, "E-mail")
    valid_emails = sum(1 for e in emails if identity.is_email(e.value))
    current_addr, prior_addr = identity.addresses(ctx)
    parts = ["%d current mobile number(s), %d a valid UAE mobile"
             % (len(mobiles), valid_mobiles),
             "%d current e-mail(s), %d valid" % (len(emails), valid_emails)]
    if current_addr:
        age = dates.months_between(current_addr[0].updated, ctx.report_date)
        parts.append("latest address last updated %s%s; %d prior address(es)"
                     % (month(current_addr[0].updated) or "on an unknown date",
                        "" if age is None else " (%d month(s) before the "
                        "report date)" % age, len(prior_addr)))
    else:
        parts.append("no address on file")
    p.add("Contact details: %s." % "; ".join(parts),
          ["contacts[].Contact", "addresses[].DateOfLastUpdate"], SEC_IDENTITY,
          trip=not mobiles or not current_addr)


def _documents(ctx, p):
    if not ctx.report_date:
        p.reason = "no report date to measure document validity against"
        return
    _document(ctx, p, "EmiratesId", "Emirates ID", required=True)
    _document(ctx, p, "Passport", "Passport", required=False)
    _contacts(ctx, p)


def _score(ctx, p):
    value = scoring.score_value(ctx)
    fh, ae = scoring.fh_band(ctx), scoring.aecb_band(ctx)
    vintage = scoring.vintage_band(ctx)
    months = scoring.history_months(ctx)
    parts = ["AECB score %s" % (value if value is not None else "not delivered")]
    if fh:
        parts.append("FH band %s (%s)" % (text(fh["code"]), text(fh["label"])))
    if ae:
        parts.append("AECB range %s (%s)" % (text(ae["code"]), text(ae["label"])))
    if months is not None:
        parts.append("bureau history %d month(s), vintage band %s"
                     % (months, vintage["code"] or "not banded"))
    p.add("Score and history: %s." % "; ".join(parts),
          ["score.DataIndex", "score.FHScoreBand", "score.DataRange",
           "contractsTotalSummary.OldestContractOpenDate"], SEC_SCORE,
          trip=value is None or (fh is not None and fh["tone"] == "bad"))


def _worst(ctx, p):
    delivered = ctx.summary.get("WorstStatus24M")
    if delivered:
        st = ctx.status(delivered)
        p.add("Delivered worst status in 24 months: %s (%s)."
              % (text(st["label"]), ctx.severity(st["rank"])),
              ["summary.WorstStatus24M"], SEC_WORST,
              trip=ctx.severity(st["rank"]) in ("severe", "adverse"))
    derived = facilities.worst_in_window(ctx)
    if derived is None:
        p.add("36-month worst status: no monthly history delivered to derive "
              "it from.", ["contractsHistory[].ContractStatus"], SEC_WORST,
              trip=True)
        return
    if derived["clean"]:
        p.add("36-month worst status derived from monthly history: clean -- "
              "no delay and no below-normal status across %d of %d "
              "facilities." % (derived["facilities_covered"],
                               derived["facilities_total"]),
              ["contractsHistory[].ContractStatus",
               "contractsHistory[].DaysPaymentDelay"], SEC_WORST)
        return
    status = derived["status"]
    severity = ctx.severity(status["rank"]) if status else "unknown"
    p.add("36-month worst status derived from monthly history: %s (%s)%s%s, "
          "maximum delay %s day(s); %d of %d facilities covered."
          % (text(status["label"]) if status else "no status",
             severity,
             " on %s" % derived["facility"].label if derived["facility"] else "",
             " in %s" % derived["when"] if derived["when"] else "",
             derived["max_dpd"] if derived["max_dpd"] is not None else "?",
             derived["facilities_covered"], derived["facilities_total"]),
          ["contractsHistory[].ContractStatus",
           "contractsHistory[].DaysPaymentDelay"], SEC_WORST,
          trip=severity in ("severe", "adverse")
          or (derived["max_dpd"] or 0) >= _DELAY_DAYS)


def _income(ctx, p):
    data = income.build(ctx)
    cur = data["current"]
    if cur is None:
        p.add("Income and employment: no employment row counts as current "
              "(every row is historical or terminated).",
              ["employment[].DateOfTermination"], SEC_INCOME, trip=True)
        return
    parts = ["current employer %s" % text(cur.name)]
    if cur.started:
        parts.append("since %s" % _date(cur.started))
    if cur.income is not None and cur.income_usable:
        parts.append("gross annual income %s %s" % (data["currency"],
                                                   fmt(cur.income)))
    elif cur.income is not None:
        parts.append("stated income %s %s is a placeholder figure (below "
                     "the %s floor)" % (data["currency"], fmt(cur.income),
                                        fmt(data["floor"])))
    else:
        parts.append("no income figure for the current employer")
    if cur.updated:
        age = dates.months_between(cur.updated, ctx.report_date)
        parts.append("last updated %s%s" % (
            _date(cur.updated),
            "" if age is None else " (%d month(s) before the report date; "
            "%s)" % (age, "within the confirmation window"
                     if cur.confirmed else "outside the confirmation window")))
    p.add("Income and employment: %s." % "; ".join(parts),
          ["employment[].EmploymentName", "employment[].GrossAnnualIncome",
           "employment[].DateOfLastUpdate"], SEC_INCOME,
          trip=not (cur.income is not None and cur.income_usable))


def _returns(ctx, p):
    data = returns.build(ctx)
    if not data["records"]:
        p.add("Returned instruments: none on file (no returned cheque or "
              "direct debit).", ["paymentOrder[]"], SEC_RETURNS)
        return
    recent, older = data["recent"], data["older"]
    amount = sum(r.amount or 0 for r in recent)
    latest = data["dated"][0].date if data["dated"] else None
    parts = ["%d returned instrument(s) in the last %d month(s) before the "
             "report date totalling AED %s" % (len(recent),
                                              data["window_months"],
                                              fmt(amount)),
             "%d older" % len(older)]
    if data["undated"]:
        parts.append("%d undated" % len(data["undated"]))
    if latest:
        gap = dates.months_between(latest, ctx.report_date)
        parts.append("latest on %s%s" % (
            _date(latest), "" if gap is None else
            " (%d month(s) before the report date)" % gap))
    p.add("Returned instruments: %s." % "; ".join(parts),
          ["paymentOrder[].ReturnDate", "paymentOrder[].Amount"],
          SEC_RETURNS, trip=bool(recent))


def _over_limit(ctx, contract):
    """'<card> at 116% of a 45,000 limit (balance 52,340)' when a card is
    over its limit (inferred: the payload carries no flag), else None."""
    if category(contract) != CAT_CARD:
        return None
    util = number(contract.get("Current_UtilizationRate"))
    bal = number(contract.get("Current_Balance"))
    lim = number(contract.get("Current_CreditLimit"))
    over = (util is not None and util > _OVER_LIMIT_UTIL) or \
        (bal is not None and lim and bal > lim)
    if not over:
        return None
    return "%s at %s%% of a %s limit (balance %s)" % (
        contract_label(ctx, contract), fmt(util) if util is not None else "?",
        fmt(lim), fmt(bal))


def _facilities(ctx, p):
    active = [c for c in ctx.rows("contracts") if is_active(c)]
    overdue_total, over_limit, instalments = 0, [], 0
    for c in active:
        overdue_total += number(c.get("Current_OverdueAmount")) or 0
        if category(c) == CAT_INSTALLMENT:
            instalments += number(c.get("PaymentAmount")) or 0
        text_ = _over_limit(ctx, c)
        if text_:
            over_limit.append(text_)
    p.add("Active facilities: %d; current overdue across them AED %s; monthly "
          "instalments on loans AED %s." % (len(active), fmt(overdue_total),
                                             fmt(instalments)),
          ["contracts[].ActiveFlag", "contracts[].Current_OverdueAmount",
           "contracts[].PaymentAmount"], SEC_FACILITIES,
          trip=overdue_total > 0)
    if over_limit:
        p.add("Cards over limit (inferred from utilisation above %d%% or "
              "balance above limit): %s." % (_OVER_LIMIT_UTIL,
                                              "; ".join(over_limit)),
              ["contracts[].Current_UtilizationRate",
               "contracts[].Current_CreditLimit"], SEC_FACILITIES, trip=True)


def _conduct_of(contract, history):
    """(late months, deepest delay, over-limit months, open episode) for one
    contract's in-window history."""
    late, deepest, over_limit = 0, 0, 0
    is_card = category(contract) == CAT_CARD
    for _when, row in history:
        dpd = number(row.get("DaysPaymentDelay")) or 0
        if dpd > 0:
            late += 1
            deepest = max(deepest, dpd)
        util = number(row.get("UtilizationRate"))
        if is_card and util is not None and util > _OVER_LIMIT_UTIL:
            over_limit += 1
    episodes = trajectory.delay_episodes(history)
    open_episode = bool(episodes) and episodes[-1]["cured_by"] is None
    return late, deepest, over_limit, open_episode


def _conduct(ctx, p):
    by_contract = history_by_contract(ctx)
    late_months, deepest, over_limit_months, open_episodes, facs = 0, 0, 0, [], 0
    for contract in ctx.rows("contracts"):
        history = by_contract.get(contract.get("CBContractId"))
        if not history:
            continue
        facs += 1
        late, deep, over, open_episode = _conduct_of(contract, history)
        late_months += late
        deepest = max(deepest, deep)
        over_limit_months += over
        if open_episode:
            open_episodes.append(contract_label(ctx, contract))
    if not facs:
        p.add("36-month conduct: no monthly history delivered.",
              ["contractsHistory[]"], SEC_DETAIL, trip=True)
        return
    p.add("36-month conduct across %d facilities with history: %d late "
          "month(s), deepest delay %s day(s); %d over-limit month(s) on "
          "cards; %d delinquency episode(s) not cured at the last reported "
          "month%s." % (facs, late_months, fmt(deepest), over_limit_months,
                         len(open_episodes),
                         " (%s)" % "; ".join(open_episodes)
                         if open_episodes else ""),
          ["contractsHistory[].DaysPaymentDelay",
           "contractsHistory[].UtilizationRate"], SEC_DETAIL,
          trip=bool(open_episodes) or deepest >= _DELAY_DAYS
          or over_limit_months > 0)


def _applications(ctx, p):
    rows = applications.in_window(ctx, ctx.rows("applications"))
    by_phase = {}
    requested = 0
    for row in rows:
        phase = ctx.phase(row.get("Phase"))
        by_phase[phase["label"]] = by_phase.get(phase["label"], 0) + 1
        if phase.get("code") == "R":
            requested += 1
    if not rows:
        p.add("Applications in the last 90 days before the report date: none.",
              ["applications[].LastUpdateDate"], SEC_APPLICATIONS)
        return
    listed = ", ".join("%d %s" % (n, text(label))
                       for label, n in sorted(by_phase.items()))
    p.add("Applications in the last 90 days before the report date: %d (%s). "
          "%d in Requested phase: the team asks the customer for proof of "
          "closure (taken or not taken) and, if taken, includes it in the "
          "DBR." % (len(rows), listed, requested),
          ["applications[].Phase", "applications[].LastUpdateDate"],
          SEC_APPLICATIONS, trip=requested > 0)


STEPS = (
    (1, "validity", "Enquiry date and report validity",
     "Was the report enquired or generated within the last 30 days? A stale "
     "report goes back to sales for a fresh pull.", (), _validity),
    (2, "profile", "Applicant profile",
     "Name, age and country against policy -- policy data is not connected "
     "yet; note only what the file shows about age.", (), _profile),
    (3, "documents", "Identity documents and contact details",
     "Is the Emirates ID valid and the passport unexpired; are the phone "
     "number, e-mail and latest address sound from an underwriting and risk "
     "sense?", (SEC_IDENTITY,), _documents),
    (4, "score", "AECB score, bands and vintage",
     "What do the score, the FH and AECB bands and the bureau vintage say?",
     (SEC_SCORE,), _score),
    (5, "worst", "Worst statuses",
     "Any adverse status, with instalments, credit cards and other financial "
     "facilities as the focus?", (SEC_WORST,), _worst),
    (6, "income", "Income and employment",
     "Is the income and employment picture sound from an underwriting "
     "perspective?", (SEC_INCOME,), _income),
    (7, "returns", "Cheque returns and direct-debit bounces",
     "Returned instruments, with the last 6 months in focus and older ones "
     "still weighed for the risk view.", (SEC_RETURNS,), _returns),
    (8, "facilities", "Active credit facilities",
     "Utilisation, overdue amounts and instalments on the active facilities, "
     "through an underwriting lens.", (SEC_FACILITIES,), _facilities),
    (9, "conduct", "36-month conduct",
     "Payment delays, over-limits on cards, adverse statuses and any other "
     "underwriting-relevant behaviour the monthly data shows.",
     (SEC_DETAIL,), _conduct),
    (10, "applications", "Recent applications",
     "Any enquiries in the last 90 days requested but not taken up? If so, "
     "the customer is asked for proof of closure; a taken facility joins the "
     "DBR.", (SEC_APPLICATIONS,), _applications),
)


def build_packets(ctx, fact_rows):
    """(packets, all fact rows): the ten step packets, with the arithmetic
    facts they add appended to the digest after the existing rows."""
    facts = Facts()
    facts.rows = list(fact_rows)
    packets = []
    for number_, key, title, question, sections, builder in STEPS:
        # The team's facts for the team's steps: the non-obvious-risk lenses
        # (theme "risk") belong to block 2, which reads them in full.
        existing = [f["id"] for f in fact_rows
                    if f["section"] in sections and f["theme"] != RISK]
        packet = _Packet(facts, existing)
        builder(ctx, packet)
        packets.append({
            "step": number_,
            "key": key,
            "title": title,
            "question": question,
            "fact_ids": packet.ids,
            "tripwires": packet.tripwires,
            "not_assessable_reason": packet.reason,
        })
    return packets, facts.rows


def packets_text(packets, facts_by_id) -> str:
    """The step packets as the model reads them."""
    out = []
    for p in packets:
        out.append("STEP %02d -- %s" % (p["step"], p["title"]))
        out.append("Question: %s" % p["question"])
        if p["not_assessable_reason"]:
            out.append("Not assessable: %s" % p["not_assessable_reason"])
        out.append("Facts:")
        out.extend("  %s %s" % (fid, facts_by_id[fid]["text"])
                   for fid in p["fact_ids"] if fid in facts_by_id)
        out.append("")
    return "\n".join(out).rstrip()
