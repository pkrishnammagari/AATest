"""Compact raw tables for the hypothesis pass (block 1, pass H).

The fresh lens runs as a hypothesis -> verification loop: the model reads the
payload's monthly history as plain numbers, proposes typed hypotheses, and
Python verifies each one (aecb/brief/hypotheses/). These tables are what the
model proposes FROM. They carry raw integers -- no prose, no interpretation --
so the pass is cheap in tokens and the figures the model may quote in a
custom observation are checkable against them verbatim.

Contracts are aliased K1..Kn in payload order. The alias is the model's handle
for a hypothesis parameter and is never shown to the underwriter; every
verified fact names the contract by its full label. The tables are fenced by
the prompt and, like every text the model sees, free text in them is data.

Compact by construction (the model's tokens, not characters, are the
cost, and raw numbers tokenise at about two characters a token): a history
line carries the month and the balance, and adds a cell only where it says
something -- a card's limit when it first shows or changes (utilisation is
then derivable, and a limit change is visible), the minimum-payment flag for
a contract whose history delivers it, the days delayed and the overdue amount
only when they are not both 0. A value not delivered is '-', so a missing
delay is never read as a clean month. Three or more calendar-consecutive
reported months with identical cells are written once ("A..B cells xN"); a
reporting gap always breaks the run.

Depth: the history is emitted at 36 months and trimmed to 24, then 12, when
the whole text exceeds the character budget -- a large book must not push the
hypothesis pass out of the model's context. The chosen depth is reported.

Nothing here is a fact: no table line can be cited, and the figure guard on
findings still runs against the digest. Prohibited fields never appear
(employment rows carry employer, dates and income only; no identity rows).
"""

from __future__ import annotations

from ... import dates
from ...coerce import flag, number
from .. import applications
from ._common import (CAT_CARD, CAT_INSTALLMENT, category, contract_name,
                      history_by_contract, is_active, month, provider_name,
                      text)
from .patterns import month_add

# Characters, not tokens. Ollama counts these tables at about two characters
# a token, so 10k characters is ~5k tokens of tables; the three
# committed fixtures sit between 3k and 8k characters at 36 months.
BUDGET_CHARS = 10000
DEPTHS = (36, 24, 12)

# Calendar-consecutive reported months with identical cells, at least this
# many, are written as one line.
RUN_MIN = 3

_KINDS = {CAT_CARD: "card", CAT_INSTALLMENT: "loan", "S": "service",
          "N": "non-instalment"}


def _num(value) -> str:
    """A raw figure: integers without separators, '-' when not delivered."""
    n = number(value)
    if n is None:
        return "-"
    if n == int(n):
        return str(int(n))
    return "%.2f" % n


def _mon(value) -> str:
    return month(value) or "-"


def _contract_line(ctx, alias, contract) -> str:
    status = ctx.status(contract.get("Current_ContractStatus"))
    return " | ".join((
        alias, contract_name(contract),
        provider_name(ctx, contract.get("ProviderNo")),
        _KINDS.get(category(contract), "other"),
        _mon(contract.get("OpenDate")),
        "active" if is_active(contract) else "closed",
        _num(contract.get("Current_CreditLimit")),
        _num(contract.get("Current_Balance")),
        _num(contract.get("Current_OverdueAmount")),
        _num(contract.get("Current_DaysPaymentDelay")),
        text(status["label"]) if status and status.get("label") else "-",
    ))


def _cutoff(ctx, depth) -> str:
    """The earliest month kept at this depth, as YYYY-MM (lexically sortable)."""
    anchor = ctx.report_date
    if anchor is None:
        return "0000-00"
    start = dates.add_months(anchor, -(depth - 1))
    return start.strftime("%Y-%m")


def _minpay(row) -> str:
    value = flag(row.get("MinimumPaymentFlag"))
    return "-" if value is None else ("1" if value else "0")


def _cells(row, card, minpay, shown):
    """(the line's cells after the month, the (limit, flag) shown so far).

    The card limit and the minimum-payment flag are state: each is written
    where it first shows or changes, and holds until the next one."""
    cells = [_num(row.get("Balance"))]
    limit = _num(row.get("CreditLimit")) if card else None
    if card and limit != shown[0]:
        cells.append("lim " + limit)
    flag_ = _minpay(row) if minpay else None
    if minpay and flag_ != shown[1]:
        cells.append("mp " + flag_)
    dpd = _num(row.get("DaysPaymentDelay"))
    overdue = _num(row.get("OverdueAmount"))
    if (dpd, overdue) != ("0", "0"):
        cells.append("dpd %s od %s" % (dpd, overdue))
    return " ".join(cells), (limit, flag_)


def _runs(rows) -> list:
    """[(months, cells)]: calendar-consecutive months with identical cells
    grouped, so a reporting gap or any changed value starts a new group."""
    groups = []
    for when, cells in rows:
        last = groups[-1] if groups else None
        if last and last[1] == cells and month_add(last[0][-1], 1) == when:
            last[0].append(when)
        else:
            groups.append(([when], cells))
    return groups


def _history_lines(contract, history, cutoff) -> list:
    card = category(contract) == CAT_CARD
    minpay = any(row.get("MinimumPaymentFlag") is not None for _, row in history)
    rows, shown = [], (None, None)
    for when, row in history:
        if when < cutoff:
            continue
        cells, shown = _cells(row, card, minpay, shown)
        rows.append((when, cells))
    lines = []
    for months, cells in _runs(rows):
        if len(months) >= RUN_MIN:
            lines.append("%s..%s %s x%d" % (months[0], months[-1], cells,
                                             len(months)))
        else:
            lines.extend("%s %s" % (when, cells) for when in months)
    return lines


def _applications_lines(ctx) -> list:
    rows = sorted(ctx.rows("applications"),
                  key=lambda r: applications.applied_on(r)
                  or dates.parse_any("1970-01-01"))
    return [" | ".join((
        _mon(applications.applied_on(r)), text(r.get("ContractType") or "?"),
        provider_name(ctx, r.get("ProviderNo")),
        text(ctx.phase(r.get("Phase"))["label"]), _num(r.get("TotalAmount"))))
        for r in rows]


def _employment_lines(ctx) -> list:
    return [" | ".join((
        text(r.get("EmploymentName") or "?"), _mon(r.get("DateOfEmployment")),
        _mon(r.get("DateOfTermination")), _mon(r.get("DateOfLastUpdate")),
        _num(r.get("GrossAnnualIncome"))))
        for r in ctx.rows("employment")]


def _returns_lines(ctx) -> list:
    rows = sorted(ctx.rows("paymentOrder"),
                  key=lambda r: dates.parse_any(r.get("ReturnDate"))
                  or dates.parse_any("1970-01-01"))
    return [" | ".join((
        _mon(r.get("ReturnDate")), text(r.get("Type") or "?"),
        _num(r.get("Amount")), text(r.get("Reason") or "?")))
        for r in rows]


def _section(title, header, lines) -> list:
    if not lines:
        return ["%s: none" % title, ""]
    return [title, header] + lines + [""]


def _history_header(depth, minpay) -> list:
    return [
        "HISTORY (last %d months; reported months only: a month not listed "
        "was not reported)" % depth,
        "Line: month balance, then lim = the card's credit limit%s, each "
        "where it first shows or changes; dpd = days delayed and od = overdue "
        "amount, shown only when not both 0; - = not delivered; A..B ... xN = "
        "N consecutive months with the same values"
        % (" and mp = the minimum-payment flag (1/0)" if minpay else ""),
    ]


def _text(ctx, aliases, by_contract, depth, minpay) -> str:
    cutoff = _cutoff(ctx, depth)
    out = _section(
        "CONTRACTS",
        "alias | contract | provider | kind | opened | state | limit | "
        "balance | overdue | dpd | status",
        [_contract_line(ctx, alias, c) for alias, c in aliases.items()])
    out.extend(_history_header(depth, minpay))
    for alias, contract in aliases.items():
        history = by_contract.get(contract.get("CBContractId")) or []
        lines = _history_lines(contract, history, cutoff)
        out.append("%s%s" % (alias, "" if lines else ": no history"))
        out.extend(lines)
    out.append("")
    out += _section("APPLICATIONS", "month | type | provider | phase | amount",
                    _applications_lines(ctx))
    out += _section("EMPLOYMENT",
                    "employer | started | ended | updated | annual income",
                    _employment_lines(ctx))
    out += _section("RETURNS", "month | type | amount | reason",
                    _returns_lines(ctx))
    return "\n".join(out).rstrip()


def build(ctx, budget_chars: int = BUDGET_CHARS) -> dict:
    """{"text", "aliases": {alias: contract row}, "months": depth}."""
    aliases = {"K%d" % (i + 1): contract
               for i, contract in enumerate(ctx.rows("contracts"))}
    by_contract = history_by_contract(ctx)
    minpay = any(r.get("MinimumPaymentFlag") is not None
                 for r in ctx.rows("contractsHistory"))
    text_ = ""
    depth = DEPTHS[0]
    for depth in DEPTHS:
        text_ = _text(ctx, aliases, by_contract, depth, minpay)
        if len(text_) <= budget_chars:
            break
    return {"text": text_, "aliases": aliases, "months": depth}
