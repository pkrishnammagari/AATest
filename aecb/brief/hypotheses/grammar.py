"""The closed hypothesis grammar for pass H.

A hypothesis is a `type` from a fixed enum plus the parameters that type
takes. The schema is one FLAT object with every parameter optional (small
constrained decoders handle flat optional properties better than oneOf), and
parse() enforces per type what the schema cannot: that the required
parameters are present and that every contract alias exists in the tables.

`custom` is the escape hatch: one free-text sentence the model wants to say
that no type covers. It is never verified, never a finding, never memo
input; it renders as an "unverified observation" after its figures and names
are checked against the tables it was proposed from.
"""

from __future__ import annotations

import re

CUSTOM = "custom"

# type -> (required parameters, optional parameters with defaults)
TYPES = {
    "utilisation_rise_after": (("contract", "event"), {"months": 6}),
    "delay_cluster": (("months_of_year",), {}),
    "balance_oscillation": (("contract",), {"window": 12}),
    "limit_increase_then_utilisation": (("contract",), {}),
    "closure_before_enquiry": ((), {"window": 12}),
    "application_burst_then_delay": ((), {"window": 12}),
    "income_decline_across_updates": ((), {}),
    "correlated_delays": (("contracts",), {}),
}

EVENTS = ("loan_opened", "application", "employment_change",
          "returned_instrument", "limit_change")

MAX_TYPED = 12
MAX_CUSTOM = 3

_ALIAS = {"type": "string", "pattern": "^K[0-9]{1,2}$"}

SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "maxItems": MAX_TYPED + MAX_CUSTOM,
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string",
                             "enum": list(TYPES) + [CUSTOM]},
                    "contract": _ALIAS,
                    "contracts": {"type": "array", "items": _ALIAS},
                    "event": {"type": "string", "enum": list(EVENTS)},
                    "months": {"type": "integer", "minimum": 1, "maximum": 12},
                    "window": {"type": "integer", "minimum": 1, "maximum": 36},
                    "months_of_year": {"type": "array",
                                       "items": {"type": "integer",
                                                 "minimum": 1, "maximum": 12}},
                    "text": {"type": "string"},
                },
                "required": ["type"],
            },
        },
    },
    "required": ["hypotheses"],
}

_ALIAS_RE = re.compile(r"^K[0-9]{1,2}$")

_RANGES = {"months": (1, 12), "window": (1, 36)}


def _alias(value, aliases):
    value = str(value or "").strip()
    return value if _ALIAS_RE.match(value) and value in aliases else None


def _aliases(value, aliases):
    if not isinstance(value, list):
        return None
    out = []
    for item in value:
        alias = _alias(item, aliases)
        if alias is None:
            return None
        if alias not in out:
            out.append(alias)
    return out if len(out) >= 2 else None


def _int_in(value, name):
    low, high = _RANGES[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    return value if low <= value <= high else None


def _months_of_year(value):
    if not isinstance(value, list):
        return None
    out = sorted({int(v) for v in value
                  if isinstance(v, (int, float)) and not isinstance(v, bool)
                  and 1 <= int(v) <= 12})
    return out or None


def _param(name, raw, aliases):
    """The normalised parameter value, or None when unusable."""
    if name == "contract":
        return _alias(raw.get("contract"), aliases)
    if name == "contracts":
        return _aliases(raw.get("contracts"), aliases)
    if name == "event":
        event = str(raw.get("event") or "").strip()
        return event if event in EVENTS else None
    if name == "months_of_year":
        return _months_of_year(raw.get("months_of_year"))
    return _int_in(raw.get(name), name)


def _typed(raw, type_, aliases):
    """(hypothesis, '') or (None, reason) for one typed entry."""
    required, optional = TYPES[type_]
    params = {}
    for name in required:
        value = _param(name, raw, aliases)
        if value is None:
            return None, "%s: missing or invalid %s" % (type_, name)
        params[name] = value
    for name, default in optional.items():
        value = _param(name, raw, aliases) if raw.get(name) is not None else None
        params[name] = default if value is None else value
    return {"type": type_, "params": params}, ""


def _key(hypothesis):
    items = []
    for name, value in sorted(hypothesis["params"].items()):
        items.append((name, tuple(value) if isinstance(value, list) else value))
    return (hypothesis["type"], tuple(items))


def _entry(entry, aliases, seen):
    """(typed hypothesis or None, custom text or None, drop reason)."""
    if not isinstance(entry, dict):
        return None, None, "hypothesis is not an object"
    type_ = str(entry.get("type") or "").strip()
    if type_ == CUSTOM:
        text = str(entry.get("text") or "").strip()
        return None, text or None, "" if text else "custom hypothesis without text"
    if type_ not in TYPES:
        return None, None, "unknown hypothesis type %r" % (type_,)
    hypothesis, reason = _typed(entry, type_, aliases)
    if reason:
        return None, None, reason
    if _key(hypothesis) in seen:
        return None, None, "duplicate hypothesis (%s)" % type_
    seen.add(_key(hypothesis))
    return hypothesis, None, ""


def parse(raw, aliases):
    """(typed hypotheses, custom texts, drop reasons) from a pass-H reply.

    A reply that is not a hypotheses object yields nothing with one reason;
    the caller then falls back to the Python candidate list.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("hypotheses"), list):
        return [], [], ["model output is not a hypotheses object"]
    typed, custom, dropped, seen = [], [], [], set()
    for entry in raw["hypotheses"]:
        hypothesis, text, reason = _entry(entry, aliases, seen)
        if reason:
            dropped.append(reason)
        elif hypothesis is not None:
            typed.append(hypothesis)
        else:
            custom.append(text)
    dropped.extend("over the %d-hypothesis cap" % MAX_TYPED
                   for _ in typed[MAX_TYPED:])
    dropped.extend("over the %d-observation cap" % MAX_CUSTOM
                   for _ in custom[MAX_CUSTOM:])
    return typed[:MAX_TYPED], custom[:MAX_CUSTOM], dropped


def describe(hypothesis, labels) -> str:
    """The hypothesis in words, contracts named by label (for the page)."""
    params = hypothesis["params"]
    words = hypothesis["type"].replace("_", " ")
    parts = []
    if "contract" in params:
        parts.append(labels.get(params["contract"], params["contract"]))
    if "contracts" in params:
        parts.append(" and ".join(labels.get(k, k) for k in params["contracts"]))
    if "event" in params:
        parts.append("event: %s" % params["event"].replace("_", " "))
    if "months" in params:
        parts.append("within %d month(s)" % params["months"])
    if "window" in params:
        parts.append("window %d month(s)" % params["window"])
    if "months_of_year" in params:
        parts.append("calendar months %s"
                     % ", ".join(str(m) for m in params["months_of_year"]))
    return words + (": " + "; ".join(parts) if parts else "")
