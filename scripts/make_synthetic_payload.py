"""Generate a synthetic, deliberately delinquent AECB payload.

Mirrors the structure of ReferenceJSON/aecb_payload_archive_170623.json exactly,
including its format quirks (three date shapes, trailing spaces on enums, the
two ContractCategory vocabularies) so the loader's normalisation paths are
exercised rather than bypassed.

The subject is severely adverse across multiple facilities, spanning the whole
status-severity range -- write-off, default, service disconnected, settlement,
arrangement -- so every heatmap band and all five DPD buckets appear on one page.
Rollups in `summary` and `contractsTotalSummary` are computed from the contract
rows rather than invented, so the payload does not contradict itself.

Seeded: rerunning reproduces the identical file.
"""

import datetime
import json
import os
import random

SEED = 20260728
rnd = random.Random(SEED)

# Relative to this script, never to whoever happens to run it or wherever the
# repo happens to be checked out.
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                   "ReferenceJSON",
                   "1_SyntheticJSONPayload_Delinquent_MultiFacility.json")

PK = 284917
CB = "B07742318"

# The report is pulled 28 Jul 2026 and the file is read on 19 Aug 2026 -- 22
# days into the configured 30-day window, so section 01 renders the "still
# valid" branch. The reference payload is 2.8 years stale and only ever
# exercises the expired branch.
PULL = "2026-07-28T10:14:22.431"
ARCHIVE = "2026-08-02T09:31:05.118"
REPORT = datetime.date(2026, 7, 28)
REF_ISO = "2026-07-31T00:00:00"
REF_DDMMYY = "310726"          # contracts.ReferenceDate uses this third shape

MONTH_END = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def month_back(n):
    """ISO month-end timestamp n months before the report month (2026-07)."""
    y, m = 2026, 7 - n
    while m <= 0:
        m += 12
        y -= 1
    day = 29 if (m == 2 and y % 4 == 0) else MONTH_END[m]
    return "%04d-%02d-%02dT00:00:00" % (y, m, day)


def longdate(d):
    """'25 July 2016' -- the shape contracts.OpenDate/ClosedDate arrive in."""
    return "%d %s %d" % (d.day, d.strftime("%B"), d.year)


# --- facilities --------------------------------------------------------------
# dpd: {months_ago: (days_past_due, status_display_text)}. Months absent from
# the dict are NOT reported by the bureau -- which the renderer must show as
# "not reported" rather than as a clean month. Gaps below are deliberate.

def ramp(pairs, gaps=()):
    out = {}
    for month, dpd, status in pairs:
        if month in gaps:
            continue
        out[month] = (dpd, status)
    return out


def flat(months, dpd, status, gaps=()):
    return ramp([(m, dpd, status) for m in months], gaps)


def merge(*ds):
    out = {}
    for d in ds:
        out.update(d)
    return out


def main():
    # Everything below runs only when the script is executed -- importing
    # this module must not write a file.
    ACTIVE = "Active Payments"

    FACILITIES = [
        # 1 -- card pushed past its limit and defaulted. Carries the whole DPD ramp.
        dict(id="C41880273", cat="C", type="Credit Card", prov="B01", active="Active",
             opened=datetime.date(2018, 3, 12), closed=None,
             limit=45000, balance=52340, overdue=12480, util="116",
             dpd=214, status="F", worst="Default",
             worst_date=datetime.date(2026, 7, 31), max_overdue=12480,
             max_overdue_date=datetime.date(2026, 7, 31), islamic="0", secured="0",
             minpct=5, dispute=None,
             hist=merge(flat(range(25, 36), 0, ACTIVE, gaps=(28, 31)),
                        flat(range(14, 25), 0, ACTIVE, gaps=(19,)),
                        ramp([(13, 8, ACTIVE), (12, 22, ACTIVE),
                              (11, 35, ACTIVE), (10, 48, ACTIVE),
                              (9, 66, "Arrangement"), (8, 78, "Arrangement"),
                              (7, 95, "Arrangement"), (6, 112, "Default"),
                              (5, 128, "Default"), (4, 145, "Default"),
                              (3, 160, "Default"), (2, 178, "Default"),
                              (1, 196, "Default"), (0, 214, "Default")]))),

        # 2 -- written off and disputed. The deepest status on the book.
        dict(id="L52913744", cat="I", type="Personal Loan", prov="B04", active="Active",
             opened=datetime.date(2021, 9, 5), closed=datetime.date(2027, 9, 5),
             limit=None, balance=88400, overdue=88400, util=None,
             dpd=203, status="W", worst="Write-off",
             worst_date=datetime.date(2026, 6, 30), max_overdue=88400,
             max_overdue_date=datetime.date(2026, 7, 31), islamic="1", secured="0",
             minpct=None, dispute=True,
             total=150000, installments=72, remaining=48, payment=2810,
             freq="monthly instalments-30 days", method="Direct Debit",
             hist=merge(flat(range(20, 36), 0, ACTIVE, gaps=(22, 27, 33)),
                        ramp([(19, 0, ACTIVE), (18, 0, ACTIVE), (17, 14, ACTIVE),
                              (16, 31, ACTIVE), (15, 44, ACTIVE),
                              (14, 58, "Arrangement"), (13, 71, "Arrangement"),
                              (12, 86, "Arrangement"), (11, 99, "Default"),
                              (10, 113, "Default"), (9, 127, "Default"),
                              (8, 141, "Default"), (7, 148, "Default"),
                              (6, 155, "Write-off"), (5, 162, "Write-off"),
                              (4, 169, "Write-off"), (3, 182, "Write-off"),
                              (2, 189, "Write-off"), (1, 196, "Write-off"),
                              (0, 203, "Write-off")]))),

        # 3 -- auto loan holding in the 60-89 band under a formal arrangement.
        dict(id="A33471902", cat="I", type="Auto Loan", prov="B09", active="Active",
             opened=datetime.date(2023, 2, 19), closed=datetime.date(2028, 2, 19),
             limit=None, balance=63500, overdue=9820, util=None,
             dpd=72, status="A", worst="Arrangement",
             worst_date=datetime.date(2026, 5, 31), max_overdue=9820,
             max_overdue_date=datetime.date(2026, 7, 31), islamic="0", secured="1",
             security="Vehicle", minpct=None, dispute=None,
             total=120000, installments=60, remaining=31, payment=2240,
             freq="monthly instalments-30 days", method="Direct Debit",
             hist=merge(flat(range(30, 36), None, None),   # pre-open, never reported
                        flat(range(12, 30), 0, ACTIVE, gaps=(15, 21, 26)),
                        ramp([(11, 0, ACTIVE), (10, 11, ACTIVE), (9, 26, ACTIVE),
                              (8, 33, ACTIVE), (7, 41, ACTIVE),
                              (6, 55, "Arrangement"), (5, 61, "Arrangement"),
                              (4, 64, "Arrangement"), (3, 67, "Arrangement"),
                              (2, 69, "Arrangement"), (1, 70, "Arrangement"),
                              (0, 72, "Arrangement")]))),

        # 4 -- late but never re-graded: 30-59 DPD while status stays Active
        # Payments. The case where DPD and status disagree.
        dict(id="C29065518", cat="C", type="Credit Card", prov="B02", active="Active",
             opened=datetime.date(2019, 11, 4), closed=None,
             limit=20000, balance=18960, overdue=1420, util="95",
             dpd=45, status="U", worst=ACTIVE,
             worst_date=datetime.date(2026, 7, 31), max_overdue=1420,
             max_overdue_date=datetime.date(2026, 7, 31), islamic="0", secured="0",
             minpct=5, dispute=None,
             hist=merge(flat(range(9, 36), 0, ACTIVE, gaps=(13, 18, 24, 29, 34)),
                        ramp([(8, 6, ACTIVE), (7, 12, ACTIVE), (6, 19, ACTIVE),
                              (5, 24, ACTIVE), (4, 29, ACTIVE), (3, 34, ACTIVE),
                              (2, 38, ACTIVE), (1, 41, ACTIVE), (0, 45, ACTIVE)]))),

        # 5 -- recovering: 90+ a year ago, current now, still flagged Arrangement.
        # Proves the heatmap reads left-to-right rather than collapsing to a grade.
        dict(id="L61224087", cat="I", type="Salary Loan", prov="B07", active="Active",
             opened=datetime.date(2022, 6, 14), closed=datetime.date(2027, 6, 14),
             limit=None, balance=41200, overdue=0, util=None,
             dpd=0, status="A", worst="Arrangement",
             worst_date=datetime.date(2025, 8, 31), max_overdue=15600,
             max_overdue_date=datetime.date(2025, 8, 31), islamic="1", secured="0",
             minpct=None, dispute=None,
             total=90000, installments=60, remaining=23, payment=1680,
             freq="monthly instalments-30 days", method="Direct Debit",
             hist=merge(flat(range(25, 36), 0, ACTIVE, gaps=(30,)),
                        ramp([(24, 18, ACTIVE), (23, 37, ACTIVE), (22, 52, ACTIVE),
                              (21, 68, "Arrangement"), (20, 84, "Arrangement"),
                              (19, 97, "Arrangement"), (18, 104, "Arrangement"),
                              (17, 91, "Arrangement"), (16, 77, "Arrangement"),
                              (15, 63, "Arrangement"), (14, 48, "Arrangement"),
                              (13, 32, "Arrangement"), (12, 17, "Arrangement")]),
                        flat(range(0, 12), 0, "Arrangement", gaps=(6,)))),

        # 6 -- telecom cut off. Services rank severe but sit outside the
        # non-services life-time count, which is why that count is not 7.
        dict(id="T18830461", cat="S", type="Communication Services", prov="T03",
             active="Active", opened=datetime.date(2020, 1, 22), closed=None,
             limit=None, balance=3180, overdue=3180, util=None,
             dpd=124, status="X", worst="Service disconnected",
             worst_date=datetime.date(2026, 4, 30), max_overdue=3180,
             max_overdue_date=datetime.date(2026, 7, 31), islamic="0", secured="0",
             minpct=None, dispute=None, mobile=2, fixed=1, other=0,
             comm="Postpaid",
             hist=merge(flat(range(8, 36), 0, ACTIVE, gaps=(11, 16, 23, 31)),
                        ramp([(7, 21, ACTIVE), (6, 39, ACTIVE), (5, 58, ACTIVE),
                              (4, 74, "Service disconnected"),
                              (3, 91, "Service disconnected"),
                              (2, 103, "Service disconnected"),
                              (1, 114, "Service disconnected"),
                              (0, 124, "Service disconnected")]))),

        # 7 -- the one facility kept clean throughout, so the normal band is on the
        # page for contrast rather than the page reading uniformly red.
        dict(id="L47716630", cat="I", type="Staff Loan", prov="B08", active="Active",
             opened=datetime.date(2015, 5, 18), closed=datetime.date(2027, 5, 18),
             limit=None, balance=22750, overdue=0, util=None,
             dpd=0, status="U", worst=ACTIVE,
             worst_date=datetime.date(2026, 7, 31), max_overdue=0,
             max_overdue_date=None, islamic="1", secured="0",
             minpct=None, dispute=None,
             total=180000, installments=144, remaining=19, payment=1250,
             freq="monthly instalments-30 days", method="Salary Transfer",
             hist=flat(range(0, 36), 0, ACTIVE, gaps=(9, 17, 26))),

        # 8 -- closed on a settlement rather than in full. Exercises final_status
        # on a closed row and the adverse band.
        dict(id="C15503388", cat="C", type="Credit Card", prov="B10", active="Closed",
             opened=datetime.date(2017, 8, 30), closed=datetime.date(2025, 11, 30),
             limit=15000, balance=0, overdue=0, util="0",
             dpd=0, status="C", worst="Settlement",
             worst_date=datetime.date(2025, 11, 30), max_overdue=8940,
             max_overdue_date=datetime.date(2025, 6, 30), islamic="0", secured="0",
             minpct=5, dispute=None,
             hist=merge(flat(range(16, 36), 0, ACTIVE, gaps=(20, 28)),
                        ramp([(15, 12, ACTIVE), (14, 29, ACTIVE), (13, 46, ACTIVE),
                              (12, 63, "Arrangement"), (11, 79, "Arrangement"),
                              (10, 88, "Arrangement"), (9, 94, "Settlement"),
                              (8, 0, "Settlement")]))),

        # 9 -- closed clean, years ago.
        dict(id="L09947213", cat="I", type="Personal Loan", prov="B12", active="Closed",
             opened=datetime.date(2016, 2, 8), closed=datetime.date(2024, 10, 31),
             limit=None, balance=0, overdue=0, util=None,
             dpd=0, status="U", worst=ACTIVE,
             worst_date=datetime.date(2024, 10, 31), max_overdue=0,
             max_overdue_date=None, islamic="0", secured="0",
             minpct=None, dispute=None,
             total=60000, installments=48, remaining=0, payment=1420,
             freq="monthly instalments-30 days", method="Direct Debit",
             hist=flat(range(21, 36), 0, ACTIVE, gaps=(25, 32))),
    ]


    # --- build the arrays --------------------------------------------------------

    contracts, history = [], []
    for i, f in enumerate(FACILITIES, start=1):
        contracts.append({
            "SNO": i,
            "PKSubjectId": PK,
            "ContractCategory": f["cat"],
            "CBContractId": f["id"],
            "ProviderNo": f["prov"],
            "ProviderContractNo": None,
            "OriginalCurrency": "AED",
            "ReferenceDate": REF_DDMMYY,
            "ContractType": f["type"],
            "ActiveFlag": f["active"],
            "Role": "Main Contract Holder",
            "OpenDate": longdate(f["opened"]),
            "ClosedDate": longdate(f["closed"]) if f["closed"] else None,
            "WorstStatus": f["worst"],
            "WorstStatusDate": longdate(f["worst_date"]) if f["worst_date"] else None,
            "MaxOverdueAmount": f["max_overdue"],
            "MaxOverdueAmountDate": (longdate(f["max_overdue_date"])
                                     if f.get("max_overdue_date") else None),
            "FlagOpenDispute": f["dispute"],
            "TotalAmount": f.get("total"),
            "NoOfInstallments": f.get("installments"),
            "NoOfRemainingInstallments": f.get("remaining"),
            "PaymentAmount": f.get("payment"),
            "PaymentFrequency": f.get("freq"),
            "MethodOfPayment": f.get("method"),
            "IslamicContractFlag": f["islamic"],
            "SecuredContractFlag": f["secured"],
            "SecurityType": f.get("security"),
            "MaxDaysPaymentDelay": max([v[0] for v in f["hist"].values()
                                        if v[0] is not None] or [None]),
            "MaxDaysPaymentDelayDate": (longdate(f["worst_date"])
                                        if f["worst_date"] else None),
            "MinimumPaymentPercentage": f.get("minpct"),
            "HolderIsNotLiable": None,
            "NoOfServicesMobile": f.get("mobile"),
            "NoOfServicesFixedLine": f.get("fixed"),
            "NoOfServicesOther": f.get("other"),
            "CommunicationType": f.get("comm"),
            "Current_ReferenceDate": REF_ISO,
            "Current_CreditLimit": f["limit"],
            "Current_Balance": f["balance"],
            "Current_OverdueAmount": f["overdue"],
            "Current_UtilizationRate": f["util"],
            "Current_DaysPaymentDelay": f["dpd"],
            "Current_ContractStatus": f["status"],
            "FraudFlag": None,
            "FraudFlagDate": None,
        })

        # Monthly conduct. Balance amortises backwards from the current figure so
        # the series is coherent with Current_Balance rather than noise.
        for m, (dpd, status) in sorted(f["hist"].items()):
            if dpd is None:
                continue
            drift = 1.0 + (m * rnd.uniform(0.006, 0.02))
            bal = int(round((f["balance"] or 0) * drift)) if f["balance"] else 0
            if f["active"] == "Closed" and m <= 8:
                bal = 0
            util = None
            if f["limit"]:
                util = str(min(999, int(round(bal * 100.0 / f["limit"]))))
            history.append({
                "PKSubjectId": PK,
                "CBContractId": f["id"],
                "ContractCategory": f["cat"],
                "ReferenceDate": month_back(m),
                "CreditLimit": f["limit"],
                "Balance": bal,
                "OverdueAmount": (int(round(f["overdue"] * (0.4 + 0.6 * (36 - m) / 36.0)))
                                  if f["overdue"] and dpd else 0),
                "UtilizationRate": util,
                "PaymentBehaviour": None,
                "MinimumPaymentFlag": None,
                "CardUsedFlag": None,
                "AmountSpent": None,
                "DaysPaymentDelay": dpd,
                "ContractStatus": status,
                "BilledAmount": None,
            })

    history.sort(key=lambda r: (r["CBContractId"], r["ReferenceDate"]))

    # --- returns -----------------------------------------------------------------
    # The configured RRM window is the 6 months before the report date (from
    # 2026-01-28), so the first four sit inside it and the last three fold away.
    RETURNS = [
        ("B01", "Bounced Cheques ",      "000418", 18500, "2026-07-12", "Multiple", True),
        ("B04", "Bounced Cheques ",      "000419",  9750, "2026-06-03", "Multiple", None),
        ("B02", "Unpaid Direct Debits ", "DD88214", 1420, "2026-05-21", "Multiple", None),
        ("B09", "Bounced Cheques ",      "000421", 22400, "2026-03-09", "Single",   None),
        ("B07", "Unpaid Direct Debits ", "DD77903", 1680, "2025-11-18", "Single",   None),
        ("B01", "Bounced Cheques ",      "000392",  6300, "2025-07-04", "Reported", None),
        ("B10", "Unpaid Direct Debits ", "DD61550",  940, "2025-02-27", "Reported", None),
    ]
    payment_order = [{
        "PKSubjectId": PK,
        "ProviderNo": prov,
        "Type": kind,
        "BeneficiaryName": None,
        "IBAN": "*********************%s" % rnd.randint(1000, 9999),
        "Number": num,
        "Amount": amt,
        "Reason": "Insufficient Funds ",
        "ReturnDate": "%sT00:00:00" % day,
        "Severity": sev,
        "DateOfLastUpdate": "%sT00:00:00" % day,
        "FlagOpenDispute": disp,
        "ArchiveDate": ARCHIVE,
        "DataPullDate": None,
    } for prov, kind, num, amt, day, sev, disp in RETURNS]

    # --- applications ------------------------------------------------------------
    APP_TYPES = ["Personal Loan", "Credit Card", "Auto Loan", "Salary Loan",
                 "Communication Services"]
    applications = []
    for i in range(14):
        days = rnd.randint(3, 320)
        when = REPORT - datetime.timedelta(days=days)
        taken = rnd.random() < 0.3
        applications.append({
            "PKSubjectId": PK,
            "CBApplicationId": str(rnd.randint(140000000, 149999999)),
            "ProviderNo": rnd.choice(["B01", "B02", "B04", "B07", "B08", "B09",
                                      "B10", "B12", "T03"]),
            "ContractType": rnd.choice(APP_TYPES),
            "Phase": "Disbursed" if taken else "Requested ",
            "Role": "Main Contract Holder",
            "LastUpdateDate": "%sT00:00:00" % when.isoformat(),
            "FlagOpenDispute": True if i == 2 else None,
            "TotalAmount": rnd.choice([5000, 10000, 15000, 25000, 40000, 75000, None]),
            "NoOfInstallments": rnd.choice([12, 24, 36, 48, 60, None]),
            "CreditLimit": rnd.choice([None, None, 15000, 30000]),
            "DateOfLastUpdate": "%sT00:00:00" % when.isoformat(),
            "ProviderApplicationNo": str(rnd.randint(1000000, 1999999)),
        })
    applications.sort(key=lambda a: a["LastUpdateDate"], reverse=True)
    apps_90d = sum(1 for a in applications
                   if (REPORT - datetime.date(*map(int, a["LastUpdateDate"][:10].split("-")))).days <= 90)

    # --- identity ----------------------------------------------------------------
    # InfoType uses AECB's own spellings -- 'EmiratesId', and 'Passport' with its
    # '(Historical)' variant, which derive/identity.py folds back to the base type.
    # The same document is repeated by many providers, exactly as the bureau
    # delivers it, so the dedupe path has something to collapse.
    EID = "784-1987-4419023-6"
    identification = []
    for prov in ["B01", "B02", "B04", "B07", "B08", "B09", "B10", "B12", "T03"]:
        identification.append({
            "InfoType": "EmiratesId", "Info": EID,
            "ExpiryDate": "2028-03-02T00:00:00", "ProviderNO": prov,
            "DateOfLastUpdate": "%sT00:00:00" % (REPORT - datetime.timedelta(
                days=rnd.randint(30, 900))).isoformat(),
            "ArchiveDate": ARCHIVE})
    for prov, doc, exp in [("B01", "PSA318842", "2029-11-14T00:00:00"),
                           ("B04", "PSA318842", "2029-11-14T00:00:00"),
                           ("B09", "PSA318842", "2029-11-14T00:00:00"),
                           ("B02", "K7714209", "2024-06-30T00:00:00"),
                           ("B07", "K7714209", "2024-06-30T00:00:00"),
                           ("T03", "K7714209", "2024-06-30T00:00:00")]:
        identification.append({
            "InfoType": "Passport" if exp.startswith("2029") else "Passport(Historical)",
            "Info": doc, "ExpiryDate": exp, "ProviderNO": prov,
            "DateOfLastUpdate": "%sT00:00:00" % (REPORT - datetime.timedelta(
                days=rnd.randint(30, 1200))).isoformat(),
            "ArchiveDate": ARCHIVE})

    EMIRATES = ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah"]
    STREETS = ["AL BARSHA SOUTH", "MIRDIF UPTOWN", "AL NAHDA 2", "JUMEIRAH VILLAGE",
               "AL QUSAIS IND 3", "KHALIFA CITY A", "AL MAJAZ 3"]
    addresses = [{
        "AddressType": None,
        "Address": rnd.choice(STREETS),
        "ArabicAddress": None,
        "Emirate": rnd.choice(EMIRATES),
        "PoBox": rnd.choice([None, str(rnd.randint(10000, 99999))]),
        "PlotNo": None,
        "ProviderNo": rnd.choice(["B01", "B02", "B04", "B07", "B09", "T03"]),
        "DateOfLastUpdate": "%sT00:00:00" % (REPORT - datetime.timedelta(
            days=rnd.randint(20, 1400))).isoformat(),
    } for _ in range(9)]

    EMPLOYERS = ["EMIRATES NBD", "DU TELECOM", "GULF LOGISTICS LLC",
                 "AL FUTTAIM GROUP", "DUBAI HOLDING"]
    # Employment is written out explicitly rather than generated, because the point
    # of these rows is WHICH OF THE THREE DATES each one carries. §03 reads
    # DateOfEmployment (S), DateOfTermination (E) and DateOfLastUpdate (U), and its
    # whole reading turns on the combination -- S and E describe the job, U only
    # describes the record, so U may qualify a claim but never establish one.
    #
    # Neither real payload populates U on a single employment row, which left every
    # U-dependent branch untested by any fixture. The table below carries five of
    # the eight combinations, keyed to that reading:
    #
    #   S-U  fresh  DU TELECOM      newest start, recently refreshed -> Current
    #   S--         EMIRATES NBD    ongoing, never refreshed -> no badge, no doubt
    #   S-U  stale  AL FUTTAIM      ongoing on paper, untouched since Feb 2024, so
    #                               its chart bar fades instead of running to the
    #                               report date. This is the case U exists for.
    #   SEU         GULF LOGISTICS  closed, plus a placeholder income below the floor
    #   SE-         DUBAI HOLDING   closed, income not reported at all
    #   -EU         MASHREQ AL ISL. ended with no start date -- still placeable in
    #                               time, so it sorts by E rather than sinking
    #   --U         ARABTEC         nothing but a refresh stamp; orders the tail
    #
    # E-before-S is deliberately NOT here: it is a data error, not a bureau state,
    # and baking a permanent error marker into the demo payload would misrepresent
    # it. That path is covered by the date-combination test instead.
    #
    # The configured confirmation window is 12 months and the report is pulled
    # 28 Jul 2026, so "fresh" means after Jul 2025.
    EMPLOYMENT = [
        # name,                        income,  S,            E,            U
        ("DU TELECOM",                  24800, "2025-09-27", None,         "2026-05-12"),
        ("EMIRATES NBD",                26400, "2024-07-28", None,          None),
        ("AL FUTTAIM GROUP",            27500, "2023-10-04", None,         "2024-02-15"),
        ("GULF LOGISTICS LLC",              1, "2019-06-17", "2020-04-08", "2021-03-01"),
        ("DUBAI HOLDING",                None, "2021-05-15", "2022-07-21",  None),
        ("MASHREQ AL ISLAMI(Historical)",19200, None,        "2023-08-31", "2026-02-01"),
        ("ARABTEC HOLDING(Historical)",  15400, None,         None,        "2025-01-20"),
    ]
    employment = [{
        "EmploymentName": name,
        "EmploymentType": kind,
        "GrossAnnualIncome": income,
        "DateOfEmployment": S and "%sT00:00:00" % S,
        "DateOfTermination": E and "%sT00:00:00" % E,
        "ProviderNo": prov,
        "DateOfLastUpdate": U and "%sT00:00:00" % U,
        # Reported by one provider only -- §03 must still surface it, since a
        # dispute raised with any single provider is a dispute.
        "FlagOpenDispute": True if name == "DU TELECOM" else None,
    } for (name, income, S, E, U), kind, prov in zip(
        EMPLOYMENT,
        ["Full Time", "Full Time", "Part Time", "Full Time", "Part Time",
         "Full Time", "Full Time"],
        ["B02", "B01", "B09", "B04", "T03", "B07", "B08"])]

    contacts = []
    for _ in range(22):
        # AECB's own ContactType spellings, trailing spaces and all -- the current
        # value carries one, the historical variant does not.
        kind = rnd.choice(["Mobile Number ", "Mobile Number (Historical)",
                           "Mobile Number (Historical)", "E-mail ",
                           "Phone Number ", "Phone Number (Historical)"])
        if "Mobile" in kind:
            value = "05%d%s" % (rnd.choice([0, 2, 4, 5, 6]),
                                "".join(str(rnd.randint(0, 9)) for _ in range(7)))
        elif "mail" in kind:
            value = "O.ALSUWAIDI%d@MAILHOST.AE" % rnd.randint(1, 99)
        else:
            value = "04%s" % "".join(str(rnd.randint(0, 9)) for _ in range(7))
        contacts.append({
            "ContactType": kind,
            "Contact": value,
            "ProviderNo": rnd.choice(["B01", "B02", "B04", "B07", "B08", "B09", "T03"]),
            "DateOfLastUpdate": "%sT00:00:00" % (REPORT - datetime.timedelta(
                days=rnd.randint(10, 1600))).isoformat(),
        })

    # --- rollups -----------------------------------------------------------------
    # Computed from the contract rows above rather than asserted independently, so
    # the payload cannot contradict the page rendered from it.
    active = [f for f in FACILITIES if f["active"] == "Active"]
    total_exposure = sum(f["balance"] or 0 for f in active)
    total_overdue = sum(f["overdue"] or 0 for f in active)
    max_dpd_now = max(f["dpd"] or 0 for f in FACILITIES)

    dpd24 = [v[0] for f in FACILITIES for m, v in f["hist"].items()
             if m < 24 and v[0] is not None]
    max_dpd_24 = max(dpd24)

    RANK = {"Write-off": 40, "Service disconnected": 48, "Default": 50,
            "Settlement": 80, "Arrangement": 90, ACTIVE: 100}
    worst24 = min((v[1] for f in FACILITIES for m, v in f["hist"].items()
                   if m < 24 and v[1]), key=lambda s: RANK[s])

    # Life-time worst status count, NON-SERVICES -- the label on the panel says so,
    # which is why the disconnected telecom line is excluded.
    lifetime_worst_count = sum(1 for f in FACILITIES
                               if f["cat"] != "S" and RANK.get(f["worst"], 100) < 100)

    def_6m_30 = sum(1 for f in FACILITIES
                    if any(m < 6 and v[0] is not None and v[0] >= 30
                           for m, v in f["hist"].items()))
    def_12m_60 = sum(1 for f in FACILITIES
                     if any(m < 12 and v[0] is not None and v[0] >= 60
                            for m, v in f["hist"].items()))
    delinq_now = sum(1 for f in FACILITIES if (f["dpd"] or 0) > 0)

    cutoff3 = REPORT - datetime.timedelta(days=92)
    checks_3m = sum(a for _, k, _, a, d, _, _ in RETURNS
                    if "Cheque" in k
                    and datetime.date(*map(int, d.split("-"))) >= cutoff3)
    dd_3m = sum(a for _, k, _, a, d, _, _ in RETURNS
                if "Direct" in k
                and datetime.date(*map(int, d.split("-"))) >= cutoff3)

    opens = [f["opened"] for f in FACILITIES]
    oldest, newest = min(opens), max(opens)
    months_oldest = (REPORT.year - oldest.year) * 12 + (REPORT.month - oldest.month)

    # Card utilisation across the book: balances over limits, cards only.
    card_bal = sum(f["balance"] for f in active if f["cat"] == "C")
    card_lim = sum(f["limit"] for f in active if f["cat"] == "C" and f["limit"])
    util_rate = str(int(round(card_bal * 100.0 / card_lim)))

    # --- category rollups --------------------------------------------------------
    CAT_LONG = {"I": "Installments", "C": "Credit Cards",
                "N": "Not Installments", "S": "Services"}
    contracts_summary, fin_summary = [], []
    for code in ("I", "C", "N", "S"):
        for role in ("A", "G"):
            rows = [f for f in FACILITIES if f["cat"] == code] if role == "A" else []
            contracts_summary.append({
                "ContractCategory": CAT_LONG[code],      # long form here...
                "ContractRole": role,
                "TotalNo": len(rows),
                "DataProvidersNo": len(set(f["prov"] for f in rows)),
                "RequestNo": sum(1 for a in applications
                                 if a["Phase"].strip() == "Requested") if role == "A" and code == "I" else 0,
                "DeclinedNo": 0,
                "RejectedNo": 0,
                "NotTakenUpNo": 0,
                "ActiveNo": sum(1 for f in rows if f["active"] == "Active"),
                "ClosedNo": sum(1 for f in rows if f["active"] == "Closed"),
            })
            act = [f for f in rows if f["active"] == "Active"]
            fin_summary.append({
                "ContractCategory": code,                # ...letter code here
                "ContractRole": role,
                "PaymentAmount": (sum(f.get("payment") or 0 for f in act) or None),
                "CreditLimit": (sum(f["limit"] or 0 for f in act) or None),
                "Balance": sum(f["balance"] or 0 for f in act),
                "OverdueAmount": sum(f["overdue"] or 0 for f in act),
                "ArchiveDate": ARCHIVE,
                "DataPullDate": PULL,
            })

    payload = {
        "summary": [{
            "Amount_DD_returned_3mon": dd_3m,
            "Amount_checks_returned_3mon": checks_3m,
            "Overdueamount": total_overdue,
            "UnauthorizedOverdraft": 1,
            "Worststatus": lifetime_worst_count,
            "WorstStatus24M": "W",              # letter code in this array
            "PKSubjectId": PK,
            "MostOldest_InMonth_Total": str(months_oldest),
            "Count_Def_6m_30_Total": def_6m_30,
            "Count_Def_12m_60_Total": def_12m_60,
            "No_Delin_Currnt_Total": delinq_now,
            "Unauthorised_OD_Amt": 7650,
            "AccountOverLimit": 1,
        }],
        "customerInfo": [{
            "PKSubjectId": PK,
            "CBSubjectId": CB,
            "ProviderSubjectNo": None,
            "Title": "MR",
            "FirstName": "OMAR",
            "LastName": "ABDULLA KHALFAN AL SUWAIDI",
            "FullNameEN": "OMAR ABDULLA KHALFAN AL SUWAIDI",
            "FirstnameAR": None,
            "LastnameAR": None,
            "FullNameAR": None,
            "Gender": "Male",
            "DOB": "1987-11-23T00:00:00",
            "Nationality": "UNITED ARAB EMIRATES",
            "ResidentFlag": True,
            "ArchiveDate": ARCHIVE,
        }],
        "sectionStatus": [
            {"CBSubjectId": CB, "ReportType": "ConsumerLong with Bounced Cheques",
             "EnquiryType": "NewApplicationEnquiry", "EnquiryNo": 811460,
             "Last EnquiryDate": "2026-07-28T10:14:22.431"},
            {"CBSubjectId": CB, "ReportType": "ConsumerScoreOnly",
             "EnquiryType": "NewApplicationEnquiry", "EnquiryNo": 811459,
             "Last EnquiryDate": "2026-07-28T10:13:58.204"},
        ],
        "identification": identification,
        "addresses": addresses,
        "employment": employment,
        "contacts": contacts,
        "incomes": [{
            "Source": "Other ",
            "GrossAnnualIncome": None,
            "ProviderNo": "B02",
            "DateOfLastUpdate": "2026-05-19T00:00:00",
        }],
        "contractsSummary": contracts_summary,
        "contractsTotalSummary": [{
            "TotalExposure": total_exposure,
            "CreditUtilizationRate": util_rate,
            "MaxCurrentPaymentDelay": max_dpd_now,
            "MaxPaymentDelay24M": max_dpd_24,
            "WorstStatus24M": worst24,          # display text in this array
            "OldestContractOpenDate": "%sT00:00:00" % oldest.isoformat(),
            "NewestContractOpenDate": "%sT00:00:00" % newest.isoformat(),
            "Applications90D": apps_90d,
            "TotalBalanceGuaranteed": 0,
            "TotalOverdueGuaranteed": 0,
        }],
        "contractsFinancialSummary": fin_summary,
        "contracts": contracts,
        "contractsHistory": history,
        "applications": applications,
        "paymentOrder": payment_order,
        "score": [{
            "PKSubjectId": PK,
            "DataIndex": 381,
            "DataRange": "B",                   # 'Poor' per config/bands.json
            "ErrorNumber": None,
            "ErrorDescription": None,
            "PaymentOrderFlag": True,
            "FraudContractFlag": None,
            "FHScoreBand": "HR",
            "FHScoreBand1": "HR",
            "DataPullDate": PULL,
            "ArchiveDate": ARCHIVE,
        }],
        "link": [],
    }

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)

    print("wrote %s" % OUT)
    print("  contracts=%d  history=%d  returns=%d  applications=%d"
          % (len(contracts), len(history), len(payment_order), len(applications)))
    print("  worst24=%r  maxDPD24=%s  currentMaxDPD=%s  util=%s%%"
          % (worst24, max_dpd_24, max_dpd_now, util_rate))
    print("  lifetime worst count (non-services)=%d  exposure=%d  overdue=%d"
          % (lifetime_worst_count, total_exposure, total_overdue))
    print("  def_6m_30=%d  def_12m_60=%d  delinquent_now=%d  apps90d=%d"
          % (def_6m_30, def_12m_60, delinq_now, apps_90d))
    print("  cheques_3m=%d  dd_3m=%d" % (checks_3m, dd_3m))


if __name__ == "__main__":
    main()
