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

import re

from .. import dates

HISTORICAL_MARKER = "(historical)"

# Sort anchor for undated entries: they sort last (the tuple's first element
# already guarantees that) while keeping payload order among themselves.
_UNDATED = dates.parse_any("1900-01-01")


def _newest_first_key(entry):
    return (entry.updated is not None, entry.updated or _UNDATED)


def _recency(date):
    """Sort key for 'most recently reported first': undated last."""
    return (date is not None, date or _UNDATED)


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
        self.updated = None      # latest DateOfLastUpdate across providers
        self.extra = {}          # e.g. ExpiryDate for passports
        self.alt_spellings = []  # other delivered spellings of this value
        self._providers = []     # payload order
        self._provider_dates = {}  # provider -> its own latest update
        self._reports = []       # (provider, parsed date, extras) per row

    @property
    def providers(self):
        """Reporting providers, the most recent reporter first.

        Ordered by each provider's OWN latest DateOfLastUpdate (undated last,
        payload order breaking ties), so a badge naming providers[0] names
        the provider that vouched for the value most recently -- not merely
        the first row in the array.
        """
        return sorted(self._providers, reverse=True,
                      key=lambda p: _recency(self._provider_dates.get(p)))

    def date_of(self, provider):
        """That provider's own latest DateOfLastUpdate for this value."""
        return self._provider_dates.get(provider)

    def add(self, provider, updated, extra=None):
        parsed = dates.parse_any(updated)
        if provider:
            if provider not in self._providers:
                self._providers.append(provider)
            prev = self._provider_dates.get(provider)
            if parsed and (prev is None or parsed > prev):
                self._provider_dates[provider] = parsed
        if parsed and (self.updated is None or parsed > self.updated):
            self.updated = parsed
        self._reports.append((provider, parsed, dict(extra or {})))
        if extra:
            for key, val in extra.items():
                if val is not None and self.extra.get(key) is None:
                    self.extra[key] = val

    def extra_by_recency(self, key):
        """Distinct delivered values of one extra, most recent report first.

        Returns [(value, [providers])]. Values that parse as the same date
        count as one. Undated reports sort last; payload order breaks ties.
        """
        ranked = sorted(enumerate(self._reports), reverse=True,
                        key=lambda ir: (_recency(ir[1][1]), -ir[0]))
        out, index = [], {}
        for _i, (provider, _date, extras) in ranked:
            val = extras.get(key)
            if val is None:
                continue
            k = dates.parse_any(val) or str(val)
            if k not in index:
                index[k] = len(out)
                out.append((val, []))
            if provider and provider not in out[index[k]][1]:
                out[index[k]][1].append(provider)
        return out

    def __repr__(self):
        return "<Entry %r hist=%s providers=%d>" % (
            self.value, self.historical, len(self.providers))


def dedupe(rows, type_key, value_key, provider_key, updated_key, extra_keys=(),
           key=None):
    """Collapse provider-repeated rows into distinct values.

    Returns (current, historical), each a list of Entry sorted newest first.

    Current vs historical is decided PER PROVIDER (decision, 24 Sep 2026).
    '(Historical)' is the bureau's mark on one provider's copy of one
    spelling -- the archive shows C11 re-submitting 971525881200 as
    +971525881200 on the same day, the old spelling marked historical. So
    each provider's OWN latest report of the value is its verdict (a same-day
    tie counts as current), and the value is current when at least one
    provider's verdict is current. One bank dropping a number never makes
    another bank's current record stale; a provider that later superseded
    its own current report does.

    key, when given, maps a value to its grouping key, so spellings of one
    value group together (identifiers pass _document_key: dashes and spaces
    ignored). The entry then displays the most recently reported spelling
    and keeps the others in alt_spellings -- grouped, never dropped.
    """
    by_value = {}
    order = []
    spellings = {}          # id(entry) -> {spelling: latest date}
    verdicts = {}           # id(entry) -> {provider: (date, is_current)}
    for row in rows or []:
        value = row.get(value_key)
        if value is None:
            continue
        group = key(value) if key else value
        hist = is_historical(row.get(type_key))
        entry = by_value.get(group)
        if entry is None:
            entry = Entry(value, historical=hist)
            by_value[group] = entry
            order.append(entry)
            spellings[id(entry)] = {}
            verdicts[id(entry)] = {}
        _record_verdict(verdicts[id(entry)], row.get(provider_key),
                        dates.parse_any(row.get(updated_key)), not hist)
        entry.add(
            row.get(provider_key),
            row.get(updated_key),
            dict((k, row.get(k)) for k in extra_keys),
        )
        seen = spellings[id(entry)]
        parsed = dates.parse_any(row.get(updated_key))
        if value not in seen or (parsed and (seen[value] is None
                                             or parsed > seen[value])):
            seen[value] = parsed if parsed else seen.get(value)

    for entry in order:
        entry.historical = not any(
            cur for _d, cur in verdicts[id(entry)].values())
        ranked = sorted(spellings[id(entry)].items(), reverse=True,
                        key=lambda item: _recency(item[1]))
        entry.value = ranked[0][0]
        entry.alt_spellings = [s for s, _d in ranked[1:]]

    def newest_first(entries):
        return sorted(entries, key=_newest_first_key, reverse=True)

    current = newest_first([e for e in order if not e.historical])
    historical = newest_first([e for e in order if e.historical])
    return current, historical


def _record_verdict(verdicts, provider, date, is_current):
    """Fold one row into its provider's verdict: that provider's latest
    report wins; on the same date (or both undated) current wins. Rows with
    no provider share one anonymous verdict."""
    prev = verdicts.get(provider)
    if prev is None or _recency(date) > _recency(prev[0]):
        verdicts[provider] = (date, is_current)
    elif _recency(date) == _recency(prev[0]) and is_current:
        verdicts[provider] = (prev[0], True)


# --- section 01 accessors ----------------------------------------------------

def _document_key(value):
    """Grouping key for a document number: letters and digits only, upper
    case -- '784-1987-4419023-6' and '784198744190236' are one Emirates ID."""
    return re.sub(r"[^0-9A-Za-z]", "", str(value)).upper() or str(value)


def identifiers(ctx, info_type: str):
    """Deduped identification rows for one base type ('EmiratesId', 'Passport').

    Spelling variants of one number group together (_document_key). The
    ExpiryDate carried on each entry is the most recent reporter's -- every
    consumer (section 01, the AI digest) reads that one value; disagreeing
    dates stay available through entry.extra_by_recency('ExpiryDate').
    """
    rows = [r for r in ctx.rows("identification")
            if base_type(r.get("InfoType")).lower() == info_type.lower()]
    current, prior = dedupe(rows, "InfoType", "Info", "ProviderNO",
                            "DateOfLastUpdate", extra_keys=("ExpiryDate",),
                            key=_document_key)
    for entry in current + prior:
        expiries = entry.extra_by_recency("ExpiryDate")
        entry.extra["ExpiryDate"] = expiries[0][0] if expiries else None
    return current, prior


_UAE_MOBILE = re.compile(r"5\d{8}")


def mobile_key(value):
    """Grouping key for a UAE mobile number, whatever prefix it arrived with.

    Digits only; then a leading 00, then 971, then ONE leading 0 come off.
    What remains, if it is a UAE mobile (9 digits starting 5), keys as
    '971' + those digits -- so 0525881200, 971525881200, +971525881200 and
    525881200 are one number. Anything else (a foreign number, a placeholder
    like 971999999999) keys on its raw digits: it still groups with exact
    repeats of itself, but is never merged with a real number by guesswork.
    """
    digits = re.sub(r"\D", "", str(value))
    national = digits[2:] if digits.startswith("00") else digits
    if national.startswith("971"):
        national = national[3:]
    if national.startswith("0"):
        national = national[1:]
    if _UAE_MOBILE.fullmatch(national):
        return "971" + national
    return digits or str(value)


_UAE_LANDLINE = re.compile(r"[234679]\d{7}")


def phone_key(value):
    """Grouping key for a Phone Number (landline) contact: mobile_key's
    prefix rules, accepting a UAE landline (area code 2/3/4/6/7/9 + 7 digits)
    as well as a UAE mobile -- the bureau files some mobiles under Phone
    Number. Anything else keys on its raw digits, as with mobiles."""
    digits = re.sub(r"\D", "", str(value))
    national = digits[2:] if digits.startswith("00") else digits
    if national.startswith("971"):
        national = national[3:]
    if national.startswith("0"):
        national = national[1:]
    if _UAE_MOBILE.fullmatch(national) or _UAE_LANDLINE.fullmatch(national):
        return "971" + national
    return digits or str(value)


def is_uae_landline(value) -> bool:
    """Whether a delivered number reads as a UAE landline under phone_key."""
    key = phone_key(value)
    return key.startswith("971") and bool(_UAE_LANDLINE.fullmatch(key[3:]))


def is_uae_mobile(value) -> bool:
    """Whether a delivered number reads as a UAE mobile under mobile_key's
    prefix rules (9 digits starting 5 once 00 / 971 / 0 come off)."""
    key = mobile_key(value)
    return key.startswith("971") and bool(_UAE_MOBILE.fullmatch(key[3:]))


def email_key(value):
    """Grouping key for an e-mail: trimmed, case ignored. Addresses are not
    case-sensitive in practice, so MUNAMO@MARSHEQ.COM and munamo@marsheq.com
    are one address."""
    return str(value).strip().lower()


_EMAIL = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")


def is_email(value) -> bool:
    """Whether a value is shaped like an e-mail: one @, a dotted domain.
    Deliberately loose -- it catches placeholders (NA, NOEMAIL, x@x), it does
    not police address syntax."""
    return bool(_EMAIL.fullmatch(str(value).strip()))


def contacts(ctx, contact_type: str):
    """Deduped contacts for one base type ('Mobile Number', 'E-mail').

    Mobile numbers group across prefix spellings (mobile_key), landlines the
    same way (phone_key), e-mails across letter case (email_key); the entry shows the most recently reported
    spelling, the others in alt_spellings.
    """
    rows = [r for r in ctx.rows("contacts")
            if base_type(r.get("ContactType")).lower() == contact_type.lower()]
    key = {"mobile number": mobile_key,
           "phone number": phone_key,
           "e-mail": email_key}.get(contact_type.lower())
    return dedupe(rows, "ContactType", "Contact", "ProviderNo",
                  "DateOfLastUpdate", key=key)


def _address_key(text):
    """Grouping key for an address text: case, punctuation and repeated
    spaces ignored -- 'AL QOUZ,' and 'Al Qouz' are one address. Single
    spaces are KEPT, so '2641 14DUBAI' and '264114 DUBAI' never merge."""
    return " ".join(re.sub(r"[^\w\s]", " ", str(text)).split()).upper()


def _emirate_key(emirate):
    return " ".join(str(emirate).split()).upper() if emirate else None


_ADDRESS_EXTRAS = ("emirate", "pobox", "plot", "type", "arabic")


def addresses(ctx):
    """Deduped addresses, newest first. No partially-filled row is dropped.

    A row contributes nothing only when Address, Emirate, PoBox AND PlotNo are
    all null (decision, 8 Sep 2026). A row with no Address but an Emirate still
    places the subject somewhere and becomes an Entry with value None, which
    the renderer states as "Address not provided — Emirate".

    Two dedup rules, by shape:

      * Addressed rows collapse on (address, emirate) wherever they appear --
        the same address repeated by five providers is one entry. The
        address compares with case, punctuation and repeated spaces ignored
        (_address_key, 24 Sep 2026); the entry shows the most recently
        reported spelling, the others in alt_spellings. The same address in
        two emirates stays two entries -- which one is right is unknowable.
      * Emirate-only rows collapse only when CONSECUTIVE in payload order with
        the same Emirate. A re-appearance after any other entry stays separate:
        it may be a move away and back, and collapsing it would erase that.

    Extras (emirate, pobox, plot, AddressType as 'type', ArabicAddress as
    'arabic') resolve to the MOST RECENT reporter's non-null value -- the
    same rule as document expiry -- so a PO box any provider reported still
    survives the dedup.

    The payload carries no historical marker here, so the newest
    DateOfLastUpdate is treated as the latest address and the rest as prior.
    """
    seen = {}
    order = []
    spellings = {}        # id(entry) -> {spelling: latest date}
    run = None            # the entry of an open emirate-only run, else None
    run_emirate = None
    for row in ctx.rows("addresses"):
        text = row.get("Address")
        emirate = row.get("Emirate")
        pobox = row.get("PoBox")
        plot = row.get("PlotNo")
        if text is None and emirate is None and pobox is None and plot is None:
            continue

        if text is not None:
            key = (_address_key(text), _emirate_key(emirate))
            entry = seen.get(key)
            if entry is None:
                entry = Entry(text)
                seen[key] = entry
                order.append(entry)
                spellings[id(entry)] = {}
            sp = spellings[id(entry)]
            parsed = dates.parse_any(row.get("DateOfLastUpdate"))
            if text not in sp or (parsed and (sp[text] is None
                                              or parsed > sp[text])):
                sp[text] = parsed if parsed else sp.get(text)
            run = None
        elif run is not None and _emirate_key(run_emirate) == _emirate_key(emirate):
            entry = run
        else:
            entry = Entry(None)
            order.append(entry)
            run, run_emirate = entry, emirate

        entry.add(row.get("ProviderNo"), row.get("DateOfLastUpdate"),
                  {"emirate": emirate, "pobox": pobox, "plot": plot,
                   "type": row.get("AddressType"),
                   "arabic": row.get("ArabicAddress")})

    for entry in order:
        if id(entry) in spellings:
            ranked = sorted(spellings[id(entry)].items(), reverse=True,
                            key=lambda item: _recency(item[1]))
            entry.value = ranked[0][0]
            entry.alt_spellings = [t for t, _d in ranked[1:]]
        for k in _ADDRESS_EXTRAS:
            vals = entry.extra_by_recency(k)
            entry.extra[k] = vals[0][0] if vals else None

    ranked = sorted(order, key=_newest_first_key, reverse=True)
    return (ranked[:1], ranked[1:]) if ranked else ([], [])


def has_arabic(text) -> bool:
    """Public face of the mojibake guard, for other Arabic fields."""
    return _has_arabic(text)


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


def name_parts_variant(customer):
    """FirstName + LastName when they spell the name differently from
    FullNameEN, else None.

    Only compared when both parts AND the full name arrived (a lone part is
    not a variant, just less of the name), ignoring case and spacing. The
    reference archive carries 'MOHAMMAD' in the full name and 'MOHAMMED' in
    the parts -- a spelling the screen must not settle silently.
    """
    full = customer.get("FullNameEN")
    first, last = customer.get("FirstName"), customer.get("LastName")
    if not (full and first and last):
        return None
    composed = _compose((first, last))

    def norm(text):
        return " ".join(str(text).upper().split())
    return composed if norm(composed) != norm(full) else None


def arabic_name_unreadable(customer):
    """The raw Arabic name when one was DELIVERED but none is usable.

    arabic_name() suppresses mojibake ('??? ????'); this returns what was
    suppressed, so the screen can say an Arabic name arrived unreadable
    rather than look as if none was sent. None when a usable name exists or
    nothing arrived at all.
    """
    if arabic_name(customer):
        return None
    return customer.get("FullNameAR") or _compose(
        (customer.get("FirstnameAR"), customer.get("LastnameAR")))


_RESIDENT_TRUE = ("true", "y", "yes", "1")
_RESIDENT_FALSE = ("false", "n", "no", "0")


def resident_flag(customer):
    """ResidentFlag read as (True | False | None, raw value).

    Booleans pass through; the common text and numeric spellings (true/false,
    Y/N, yes/no, 1/0) are read as the same fact. Anything else is None with
    the raw value kept, so the screen can show what arrived instead of
    claiming nothing did.
    """
    raw = customer.get("ResidentFlag")
    if isinstance(raw, bool):
        return raw, raw
    if raw is None:
        return None, None
    text = str(raw).strip().lower()
    if text in _RESIDENT_TRUE:
        return True, raw
    if text in _RESIDENT_FALSE:
        return False, raw
    return None, raw


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
