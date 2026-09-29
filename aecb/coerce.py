"""Reading untyped payload scalars -- one set of rules for every module.

The AECB payload is untrusted input: an amount may arrive as 12500, 12500.0,
"12500" or "12,500"; a flag as true, 1, "Y" or "N"; any field as null. Before
this module each derive and render module parsed these on its own, and the
report and the AI digest could read the same field differently. Every reader
now goes through here.

Rules:
  * number()  -- a finite float, or None. Thousands commas and surrounding
                 whitespace are accepted; booleans, NaN and infinities are not
                 numbers.
  * integer() -- number() when it is a whole number, else None. For counts
                 and scores, where 732.9 is not a score.
  * truncated() -- number() truncated toward zero. For day counts and
                 instalment counts, which have always been read that way.
  * flag()    -- True / False / None. None means "not reported" -- and an
                 unrecognised value is also None, never False: absence must
                 not render as good conduct.
  * nonzero() -- whether a delivered value says something: not null, not
                 blank, not a zero (0, "0", "0.00"). Non-numeric text counts,
                 so it is shown as delivered rather than dropped. Use it
                 wherever a payload number is tested for "anything there":
                 plain truthiness reads the text "0" as non-zero.
"""

from __future__ import annotations

import math
from typing import Optional

_TRUE = frozenset(("1", "Y", "YES", "TRUE", "T"))
_FALSE = frozenset(("0", "N", "NO", "FALSE", "F"))


def number(value) -> Optional[float]:
    """A finite float from an int, float or numeric text; None otherwise."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value).replace(",", "").strip()
        if not text:
            return None
        try:
            result = float(text)
        except ValueError:
            return None
    return result if math.isfinite(result) else None


def integer(value) -> Optional[int]:
    """The value as an int when it is a whole number; None otherwise."""
    result = number(value)
    if result is None or not result.is_integer():
        return None
    return int(result)


def truncated(value) -> Optional[int]:
    """number() truncated toward zero, or None."""
    result = number(value)
    return None if result is None else int(result)


def nonzero(value) -> bool:
    """A delivered value other than zero or blank (see the module docstring)."""
    if value is None or isinstance(value, bool):
        return bool(value)
    result = number(value)
    if result is not None:
        return result != 0
    return bool(str(value).strip())


def flag(value) -> Optional[bool]:
    """A payload flag as True / False, or None when not reported or unreadable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().upper()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None
