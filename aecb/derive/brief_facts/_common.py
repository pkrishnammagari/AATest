"""Helpers shared by every fact lens: formatting, labels, history grouping,
and the accumulator that numbers the facts."""

from __future__ import annotations

import re

from ... import dates
from ...coerce import flag, number
from .. import facilities

# Themes -- the digest's five lenses plus curated background.
STRUCTURE = "structure"
TRAJECTORY = "trajectory"
INCONSISTENCY = "inconsistency"
BEHAVIOR = "behavior"
ABSENCE = "absence"
BACKGROUND = "background"

# Report sections a fact can be verified in, by registry NAME (see
# render/sections/__init__.py). Numbers are assigned positionally there and
# would drift if written here.
SEC_IDENTITY = "identity"
SEC_SCORE = "score"
SEC_WORST = "worst_status"
SEC_INCOME = "income"
SEC_RETURNS = "returns"
SEC_FACILITIES = "facilities"
SEC_DETAIL = "detail"
SEC_APPLICATIONS = "applications"

# Field paths cited by several lenses.
F_HIST_DATE = "contractsHistory[].ReferenceDate"
F_HIST_BALANCE = "contractsHistory[].Balance"
F_HIST_DELAY = "contractsHistory[].DaysPaymentDelay"

# The most recent reported months a trajectory fact spells out. Twelve keeps a
# nine-contract digest inside a few thousand tokens while still covering a full
# year of direction -- the window the 24M summary fields compress to one value.
SERIES_MONTHS = 12

CAT_CARD = "C"
CAT_INSTALLMENT = "I"

# Payload free text (product, provider, employer names, stated reasons) is
# DATA inside the prompt. A newline inside a value could forge a new fact line
# ("F099 [severe] ..."), so text() collapses control characters and
# whitespace, neutralises the digest's own bracket and fact-id syntax, and
# caps the length.
_TEXT_LIMIT = 80
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]+")
_FACT_ID = re.compile(r"\bF\d{3}\b")


def fmt(value):
    """A number as compact prose: no trailing .0, thousands separated."""
    n = number(value)
    if n is None:
        return "?"
    if n == int(n):
        return "{:,}".format(int(n))
    return "{:,.2f}".format(n)


def text(value, limit: int = _TEXT_LIMIT) -> str:
    """Payload free text made safe to place inside a fact line."""
    cleaned = _CONTROL.sub(" ", str(value))
    cleaned = _FACT_ID.sub("", cleaned).replace("[", "(").replace("]", ")")
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "..."
    return cleaned


def month(value):
    d = dates.parse_any(value)
    return d.strftime("%Y-%m") if d else None


def is_set(value) -> bool:
    """A delivered flag that is positively set. Unreported or unreadable is
    not set -- unknown must not become a fact."""
    return flag(value) is True


def is_active(contract) -> bool:
    """Open for the digest exactly when the report treats it as open."""
    return not facilities.is_closed(contract)


def category(contract) -> str:
    return str(contract.get("ContractCategory", "")).strip().upper()


def contract_label(ctx, contract):
    """'Credit Card C41880273 (Bank B01, opened 12 March 2018)' -- enough for
    the model to name the facility without inventing detail."""
    return "%s %s (%s, opened %s)" % (
        text(contract.get("ContractType") or "Contract"),
        text(contract.get("CBContractId") or "?"),
        provider_name(ctx, contract.get("ProviderNo")),
        text(contract.get("OpenDate") or "unknown date"),
    )


def provider_name(ctx, code) -> str:
    """Configured provider name, or the delivered code -- sanitised."""
    return text(ctx.provider(code)["name"])


def history_by_contract(ctx):
    """contractsHistory grouped by contract, sorted by month, undated rows out."""
    grouped = {}
    for row in ctx.rows("contractsHistory"):
        when = month(row.get("ReferenceDate"))
        if not when:
            continue
        grouped.setdefault(row.get("CBContractId"), []).append((when, row))
    for rows in grouped.values():
        rows.sort(key=lambda pair: pair[0])
    return grouped


def series_text(pairs, formatter):
    return " ".join("%s:%s" % (when, formatter(row)) for when, row in pairs)


class Facts:
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
