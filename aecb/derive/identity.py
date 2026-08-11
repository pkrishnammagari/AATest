"""Identity, contact, address and employment reduction.

Two payload behaviours drive everything here:

  1. Version state is a SUFFIX on the type string, not a flag:
       'Passport' vs 'Passport(Historical)'
       'Mobile Number' vs 'Mobile Number (Historical)'
       'MASHREQBANK(Historical)'
     is_historical()/base_type() split that apart.

  2. Rows repeat once per REPORTING PROVIDER, not once per fact. The reference
     payload carries the same Emirates ID twelve times and the same passport
     five. Deduping by value collapses those into one entry that remembers which
     providers reported it.

Addresses and employment carry neither marker, so "current" there is decided by
the latest DateOfLastUpdate.
"""

from __future__ import annotations

from .. import dates

HISTORICAL_MARKER = "(historical)"


def is_historical(value) -> bool:
    return HISTORICAL_MARKER in str(value or "").lower()


def base_type(value) -> str:
    """'Passport(Historical)' -> 'Passport'. Also strips the trailing space
    variants the payload uses ('Mobile Number ')."""
    text = str(value or "")
    low = text.lower()
    idx = low.find(HISTORICAL_MARKER)
    if idx >= 0:
        text = text[:idx]
    return text.strip()


class Entry(object):
    """One distinct value, with every provider that reported it."""

    def __init__(self, value, historical=False):
        self.value = value
        self.historical = historical
        self.providers = []
        self.updated = None      # latest DateOfLastUpdate across providers
        self.extra = {}          # e.g. ExpiryDate for passports

    def add(self, provider, updated, extra=None):
        if provider and provider not in self.providers:
            self.providers.append(provider)
        parsed = dates.parse_any(updated)
        if parsed and (self.updated is None or parsed > self.updated):
            self.updated = parsed
        if extra:
            for key, val in extra.items():
                if val is not None and self.extra.get(key) is None:
                    self.extra[key] = val

    def __repr__(self):
        return "<Entry %r hist=%s providers=%d>" % (
            self.value, self.historical, len(self.providers))


def dedupe(rows, type_key, value_key, provider_key, updated_key, extra_keys=()):
    """Collapse provider-repeated rows into distinct values.

    Returns (current, historical), each a list of Entry sorted newest first.
    A value that appears both current and historical is treated as current --
    a later provider re-confirming it outranks an older supersede.
    """
    by_value = {}
    order = []
    for row in rows or []:
        value = row.get(value_key)
        if value is None:
            continue
        hist = is_historical(row.get(type_key))
        entry = by_value.get(value)
        if entry is None:
            entry = Entry(value, historical=hist)
            by_value[value] = entry
            order.append(entry)
        elif not hist:
            entry.historical = False
        entry.add(
            row.get(provider_key),
            row.get(updated_key),
            dict((k, row.get(k)) for k in extra_keys),
        )

    def newest_first(entries):
        # Entries with no date sort last but keep payload order among themselves.
        return sorted(
            entries,
            key=lambda e: (e.updated is not None, e.updated or dates.parse_any("1900-01-01")),
            reverse=True,
        )

    current = newest_first([e for e in order if not e.historical])
    historical = newest_first([e for e in order if e.historical])
    return current, historical


# --- section 02 accessors ---------------------------------------------------

def identifiers(ctx, info_type: str):
    """Deduped identification rows for one base type ('EmiratesId', 'Passport')."""
    rows = [r for r in ctx.rows("identification")
            if base_type(r.get("InfoType")).lower() == info_type.lower()]
    return dedupe(rows, "InfoType", "Info", "ProviderNO", "DateOfLastUpdate",
                  extra_keys=("ExpiryDate",))


def contacts(ctx, contact_type: str):
    """Deduped contacts for one base type ('Mobile Number', 'E-mail')."""
    rows = [r for r in ctx.rows("contacts")
            if base_type(r.get("ContactType")).lower() == contact_type.lower()]
    return dedupe(rows, "ContactType", "Contact", "ProviderNo", "DateOfLastUpdate")


def addresses(ctx):
    """Deduped addresses, newest first.

    The payload carries no AddressType and no historical marker, so the newest
    DateOfLastUpdate is treated as current and the rest as prior.
    """
    seen = {}
    order = []
    for row in ctx.rows("addresses"):
        text = row.get("Address")
        if not text:
            continue
        key = (text, row.get("Emirate"))
        entry = seen.get(key)
        if entry is None:
            entry = Entry(text)
            entry.extra["emirate"] = row.get("Emirate")
            entry.extra["pobox"] = row.get("PoBox")
            seen[key] = entry
            order.append(entry)
        entry.add(row.get("ProviderNo"), row.get("DateOfLastUpdate"))

    ranked = sorted(
        order,
        key=lambda e: (e.updated is not None, e.updated or dates.parse_any("1900-01-01")),
        reverse=True,
    )
    return (ranked[:1], ranked[1:]) if ranked else ([], [])


def employers(ctx):
    """Deduped employment rows, newest first.

    Employer names carry the '(Historical)' suffix, so that split applies here
    even though the row has no dedicated flag.
    """
    seen = {}
    order = []
    for row in ctx.rows("employment"):
        name = row.get("EmploymentName")
        if not name:
            continue
        key = base_type(name).upper()
        entry = seen.get(key)
        if entry is None:
            entry = Entry(base_type(name), historical=is_historical(name))
            seen[key] = entry
            order.append(entry)
        elif not is_historical(name):
            entry.historical = False
        entry.add(row.get("ProviderNo"), row.get("DateOfLastUpdate") or row.get("DateOfEmployment"))
        for field in ("EmploymentType", "GrossAnnualIncome",
                      "DateOfEmployment", "DateOfTermination"):
            if row.get(field) is not None and entry.extra.get(field) is None:
                entry.extra[field] = row.get(field)

    current = [e for e in order if not e.historical]
    prior = [e for e in order if e.historical]
    return current, prior


# --- name handling ----------------------------------------------------------

def arabic_name(customer):
    """The Arabic name, or None when it arrived corrupted.

    The reference payload delivers '??? ???? ???? ??? ???' -- an encoding loss
    somewhere upstream. Rendering that is worse than rendering nothing, so a
    string with no actual Arabic codepoints is suppressed.
    """
    text = customer.get("FullNameAR")
    if not text:
        return None
    for ch in text:
        # Arabic, Arabic Supplement, Arabic Extended-A, Presentation Forms.
        if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ" \
           or "ﭐ" <= ch <= "﷿" or "ﹰ" <= ch <= "﻿":
            return text
    return None


def age_at(dob, on_date):
    """Whole years between dob and on_date. None if either is unparseable."""
    months = dates.months_between(dob, on_date)
    if not months:
        return None
    return months // 12
