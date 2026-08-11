"""Loads an AECB payload and normalises it into something safe to compare against.

Two problems the raw payload has, both of which cause silent wrong answers
rather than loud errors:

  1. Trailing spaces on enum values -- 'Requested ', 'Mobile Number ', 'Other ',
     'E-mail '. Any `phase == "Requested"` check fails without a strip.
  2. ContractCategory is a single letter in `contracts` and
     `contractsFinancialSummary` (I/C/N/S) but a full phrase in
     `contractsSummary` ('Installments', 'Not Installments', 'Credit Cards',
     'Services'). Joining the two needs one canonical form.

load() returns a plain dict of arrays. Every array named in ARRAYS is present
even when the payload omits it, so callers never have to guard on KeyError --
an absent section is an empty list, which is the same thing the bureau means.
"""

from __future__ import annotations

import json

# Every top-level array the payload can carry, in report order.
ARRAYS = (
    "summary",
    "customerInfo",
    "sectionStatus",
    "identification",
    "addresses",
    "employment",
    "contacts",
    "incomes",
    "contractsSummary",
    "contractsTotalSummary",
    "contractsFinancialSummary",
    "contracts",
    "contractsHistory",
    "applications",
    "paymentOrder",
    "score",
    "link",
)

# Canonical single-letter category codes.
CAT_INSTALLMENT = "I"
CAT_CREDIT_CARD = "C"
CAT_NON_INSTALLMENT = "N"
CAT_SERVICE = "S"

CATEGORY_CANON = {
    "I": CAT_INSTALLMENT,
    "INSTALLMENTS": CAT_INSTALLMENT,
    "INSTALMENTS": CAT_INSTALLMENT,
    "C": CAT_CREDIT_CARD,
    "CREDIT CARDS": CAT_CREDIT_CARD,
    "CREDIT CARD": CAT_CREDIT_CARD,
    "N": CAT_NON_INSTALLMENT,
    "NOT INSTALLMENTS": CAT_NON_INSTALLMENT,
    "NON INSTALLMENTS": CAT_NON_INSTALLMENT,
    "S": CAT_SERVICE,
    "SERVICES": CAT_SERVICE,
}

CATEGORY_LABEL = {
    CAT_INSTALLMENT: "Installments",
    CAT_CREDIT_CARD: "Credit cards",
    CAT_NON_INSTALLMENT: "Non-installments",
    CAT_SERVICE: "Services",
}

# Fields carrying a category value, wherever they appear.
_CATEGORY_FIELDS = ("ContractCategory",)


def canon_category(value):
    """Map any spelling of a contract category to its single-letter code."""
    if value is None:
        return None
    key = str(value).strip().upper()
    return CATEGORY_CANON.get(key, str(value).strip() or None)


def _clean(value):
    """Strip strings, recursively. Empty strings become None.

    Empty-vs-None matters: the payload uses both for 'not reported', and the
    renderer should only have to test one.
    """
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    if isinstance(value, dict):
        return {k.strip(): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def normalise(payload: dict) -> dict:
    """Clean strings, canonicalise categories, guarantee every array exists."""
    data = {}
    for name in ARRAYS:
        rows = payload.get(name) or []
        if not isinstance(rows, list):
            rows = [rows]
        cleaned = []
        for row in rows:
            row = _clean(row)
            if isinstance(row, dict):
                for field in _CATEGORY_FIELDS:
                    if field in row:
                        row[field] = canon_category(row[field])
            cleaned.append(row)
        data[name] = cleaned

    # Surface anything the payload carries that we do not know about, rather
    # than dropping it silently -- a new AECB section should be visible.
    unknown = sorted(set(payload) - set(ARRAYS))
    data["_unknownArrays"] = unknown
    return data


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return normalise(json.load(fh))


def loads(raw) -> dict:
    """Parse from a string or bytes -- used by the Streamlit file uploader."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return normalise(json.loads(raw))


def first(rows, default=None):
    """First row of a single-row array (summary, customerInfo, score, ...)."""
    if not rows:
        return default if default is not None else {}
    return rows[0] or {}
