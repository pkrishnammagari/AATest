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


def _normalise_rows(rows) -> tuple:
    """(cleaned object rows, count of rows dropped because they are not objects).

    A single object where an array belongs is accepted as a one-row array.
    Anything that is not an object (null, a number, a nested list) cannot be
    read as a row; it is dropped and COUNTED, so the host can say so rather
    than every row.get() downstream failing on it.
    """
    if not isinstance(rows, list):
        rows = [rows]
    cleaned, dropped = [], 0
    for raw in rows:
        row = _clean(raw)
        if not isinstance(row, dict):
            dropped += 1
            continue
        for field in _CATEGORY_FIELDS:
            if field in row:
                row[field] = canon_category(row[field])
        cleaned.append(row)
    return cleaned, dropped


def normalise(payload) -> dict:
    """Clean strings, canonicalise categories, guarantee every array exists.

    Raises ValueError when the document is not a JSON object at all.
    """
    if not isinstance(payload, dict):
        raise ValueError("the payload is not a JSON object")
    data, dropped = {}, {}
    for name in ARRAYS:
        data[name], n = _normalise_rows(payload.get(name) or [])
        if n:
            dropped[name] = n

    # Surface anything the payload carries that we do not know about, rather
    # than dropping it silently -- a new AECB section should be visible. Read
    # back through ReportContext.unknown_arrays / dropped_rows; the Streamlit
    # host warns in the sidebar.
    data["_unknownArrays"] = sorted(set(payload) - set(ARRAYS))
    data["_droppedRows"] = dropped
    return data


def _reject_constant(name):
    raise ValueError("the payload carries %s, which is not a number" % name)


def _parse(text: str):
    """json.loads that refuses NaN / Infinity / -Infinity.

    Python's json accepts those non-standard literals by default; downstream
    they become floats that break int() and date arithmetic mid-render.
    """
    return json.loads(text, parse_constant=_reject_constant)


def load(path: str) -> dict:
    # utf-8-sig: tolerate a byte-order mark some Windows tools prepend.
    with open(path, encoding="utf-8-sig") as fh:
        return normalise(_parse(fh.read()))


def loads(raw) -> dict:
    """Parse from a string or bytes -- the API response or an upload."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    return normalise(_parse(raw))


def first(rows) -> dict:
    """First row of a single-row array (summary, customerInfo, score, ...)."""
    return rows[0] if rows else {}
