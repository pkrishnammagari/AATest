"""Date parsing for AECB payloads.

The payload mixes three formats, and all three appear in fields the report
renders:

    ISO 8601   '2023-10-26T14:39:13.057'  score.DataPullDate, ArchiveDate,
                                          contractsHistory.ReferenceDate
    long text  '25 July 2016'             contracts.OpenDate / ClosedDate /
                                          WorstStatusDate
    DDMMYY     '311023'                   contracts.ReferenceDate

parse_any() takes any of them (or None, or junk) and returns a date or None.
Nothing in the renderer should call strptime directly.
"""

from __future__ import annotations

import datetime
import re

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DDMMYY_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})$")

_LONG_FORMATS = (
    "%d %B %Y",   # 25 July 2016
    "%d %b %Y",   # 25 Jul 2016
    "%d/%m/%Y",
    "%d-%m-%Y",
)

# Two-digit years in the DDMMYY form. AECB reports cover recent history, so
# treat everything as 20xx -- a bureau file will not carry a 1970s reference
# date, and reading '99' as 2099 is a louder failure than reading it as 1999.
_CENTURY = 2000


def parse_any(value):
    """Best-effort parse of any date shape the payload uses. None if unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    text = str(value).strip()
    if not text:
        return None

    m = _ISO_RE.match(text)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    m = _DDMMYY_RE.match(text)
    if m:
        day, month, year = (int(g) for g in m.groups())
        try:
            return datetime.date(_CENTURY + year, month, day)
        except ValueError:
            return None

    for fmt in _LONG_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def fmt_short(value, dash: str = "—") -> str:
    """'26 Oct 2023'. Returns an em dash when there is no date."""
    d = parse_any(value)
    return d.strftime("%d %b %Y") if d else dash


def fmt_mon(value, dash: str = "—") -> str:
    """\"Oct '23\" -- the heatmap and timeline axis label."""
    d = parse_any(value)
    return d.strftime("%b '%y") if d else dash


def fmt_month_year(value, dash: str = "—") -> str:
    """'Oct 2023'."""
    d = parse_any(value)
    return d.strftime("%b %Y") if d else dash


def months_between(start, end) -> int:
    """Whole calendar months from start to end. 0 if either is unparseable.

    Counts month boundaries crossed, then backs off one if the day-of-month has
    not yet come round -- so 25 Jul 2016 to 24 Jul 2017 is 11 months, not 12.
    """
    a, b = parse_any(start), parse_any(end)
    if not a or not b:
        return 0
    months = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        months -= 1
    return max(0, months)


def days_between(start, end) -> int:
    """Whole days from start to end. 0 if either is unparseable."""
    a, b = parse_any(start), parse_any(end)
    if not a or not b:
        return 0
    return (b - a).days


def add_months(value, delta: int):
    """Shift a date by whole months, clamping the day to the target month's end."""
    d = parse_any(value)
    if not d:
        return None
    total = d.month - 1 + delta
    year = d.year + total // 12
    month = total % 12 + 1
    # Clamp: 31 Mar minus one month is 28/29 Feb, not an invalid date.
    if month == 12:
        next_month_start = datetime.date(year + 1, 1, 1)
    else:
        next_month_start = datetime.date(year, month + 1, 1)
    last_day = (next_month_start - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(d.day, last_day))
