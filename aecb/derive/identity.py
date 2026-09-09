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

Addresses carry neither marker, so "current" there is decided by the latest
DateOfLastUpdate.

Employment does NOT work that way, despite arriving in the same shape. Its rows
carry DateOfEmployment and DateOfTermination, which describe the JOB, where
DateOfLastUpdate only describes the RECORD -- so which employer is current is
settled by the newest start date, and the update date is allowed to qualify that
claim but never to decide it. derive/income.py owns that reading; the extras
merged here are deliberately left raw for it to resolve.
"""

from __future__ import annotations

from .. import dates

HISTORICAL_MARKER = "(historical)"

# Sort anchor for undated entries: they sort last (the tuple's first element
# already guarantees that) while keeping payload order among themselves.
_UNDATED = dates.parse_any("1900-01-01")


def _newest_first_key(entry):
    return (entry.updated is not None, entry.updated or _UNDATED)


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


class Entry:
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
        return sorted(entries, key=_newest_first_key, reverse=True)

    current = newest_first([e for e in order if not e.historical])
    historical = newest_first([e for e in order if e.historical])
    return current, historical


# --- section 01 accessors ----------------------------------------------------

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
    """Deduped addresses, newest first. No partially-filled row is dropped.

    A row contributes nothing only when Address, Emirate, PoBox AND PlotNo are
    all null (decision, 8 Sep 2026). A row with no Address but an Emirate still
    places the subject somewhere and becomes an Entry with value None, which
    the renderer states as "Address not provided — Emirate".

    Two dedup rules, by shape:

      * Addressed rows collapse on (Address, Emirate) wherever they appear --
        the same address repeated by five providers is one entry.
      * Emirate-only rows collapse only when CONSECUTIVE in payload order with
        the same Emirate. A re-appearance after any other entry stays separate:
        it may be a move away and back, and collapsing it would erase that.

    Extras (emirate, pobox, plot) merge first-non-null-wins across a group's
    rows, so a PO box any provider reported survives the dedup.

    The payload carries no historical marker here, so the newest
    DateOfLastUpdate is treated as current and the rest as prior.
    """
    seen = {}
    order = []
    run = None            # the entry of an open emirate-only run, else None
    for row in ctx.rows("addresses"):
        text = row.get("Address")
        emirate = row.get("Emirate")
        pobox = row.get("PoBox")
        plot = row.get("PlotNo")
        if text is None and emirate is None and pobox is None and plot is None:
            continue

        if text is not None:
            key = (text, emirate)
            entry = seen.get(key)
            if entry is None:
                entry = Entry(text)
                seen[key] = entry
                order.append(entry)
            run = None
        elif run is not None and run.extra.get("emirate") == emirate:
            entry = run
        else:
            entry = Entry(None)
            order.append(entry)
            run = entry

        entry.add(row.get("ProviderNo"), row.get("DateOfLastUpdate"),
                  {"emirate": emirate, "pobox": pobox, "plot": plot})

    ranked = sorted(order, key=_newest_first_key, reverse=True)
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

def _has_arabic(text) -> bool:
    """Whether the string carries any actual Arabic codepoints.

    The reference payload delivers '??? ???? ???? ??? ???' -- an encoding loss
    somewhere upstream. Rendering that is worse than rendering nothing, so a
    name with no Arabic codepoints is treated as corrupted and suppressed.
    """
    for ch in text or "":
        # Arabic, Arabic Supplement, Arabic Extended-A, Presentation Forms.
        if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ" \
           or "ﭐ" <= ch <= "﷿" or "ﹰ" <= ch <= "﻿":
            return True
    return False


def _compose(parts):
    """Join whichever name parts arrived. None when none did."""
    present = [str(p).strip() for p in parts if p]
    return " ".join(present) or None


def english_name(customer):
    """The display name: FullNameEN, else composed from its delivered parts.

    The payload can carry FirstName/LastName with FullNameEN null; composing
    what arrived beats rendering a dash beside name parts the bureau sent.
    None only when nothing arrived at all.
    """
    return customer.get("FullNameEN") or _compose(
        (customer.get("FirstName"), customer.get("LastName")))


def arabic_name(customer):
    """The Arabic name, or None when nothing usable arrived.

    FullNameAR wins; when it is absent or corrupted, the name is composed from
    FirstnameAR/LastnameAR instead. The corruption guard applies to whichever
    source wins -- a composed mojibake run is no better than a delivered one.
    """
    text = customer.get("FullNameAR")
    if text and _has_arabic(text):
        return text
    composed = _compose(
        (customer.get("FirstnameAR"), customer.get("LastnameAR")))
    if composed and _has_arabic(composed):
        return composed
    return None


def age_at(dob, on_date):
    """Whole years between dob and on_date. None if either is unparseable.

    A DOB less than a year before on_date yields 0, not None -- None is
    reserved for dates that could not be read at all.
    """
    months = dates.months_between(dob, on_date)
    return None if months is None else months // 12
