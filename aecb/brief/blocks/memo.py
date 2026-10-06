"""Block 4 -- the credit memo and suggested outcome.

The last pass: it reads only the validated items the other blocks produced
(lens findings, checklist indicators), numbered V001..., plus each step's
status. Its own output is held to those items: every driver cites V-ids that
exist and its text is vouched against them; every other field -- conditions,
counter-considerations, what would change this, each memo section -- is
vouched against the full item text, so the memo cannot introduce a figure or
a name the blocks did not already carry. Nothing is repaired; a failing
field renders as "not stated".

The outcome is advisory and unbounded in code (no floor, by decision); the
fixed label travels with it. The block refuses to run without the checklist.
"""

from __future__ import annotations

import re

from .. import validate
from ..errors import BriefUnavailable
from ..prompts import memo as prompt
from ..prompts import report_date_line

_MAX_DRIVERS = 6
_MAX_LIST = 6

_ITEM_REF_RE = re.compile(r"\(\s*V\d{3}(?:\s*,\s*V\d{3})*\s*\)|\bV\d{3}\b")

_DRIVER_MSG = {
    "empty": "empty driver",
    "only_refs": "driver was only item references",
    "no_cites": "driver has no cites",
    "unknown_cites": "driver cites unknown item(s) %s",
    "figures": "driver carries figures not in cited items: %s",
    "names": "driver carries names not in cited items: %s",
}
_FIELD_MSG = {
    "empty": "%s is empty",
    "only_refs": "%s was only item references",
    "figures": "%s carries figures not in the items: %s",
    "names": "%s carries names not in the items: %s",
}


def _strip_refs(text) -> str:
    cleaned = _ITEM_REF_RE.sub("", validate.strip_fact_refs(text))
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return re.sub(r"\s+([.,;:)])", r"\1", cleaned).strip()


# --- the items the memo reads ---------------------------------------------------

def _finding_text(f) -> str:
    text = f["claim"]
    if f.get("so_what"):
        text += " (so what: %s)" % f["so_what"]
    return text


def items_from(analysis) -> tuple:
    """(items by V-id, missing block names).

    Items come only from blocks whose status is ok. Each carries the text
    the memo may draw on, its source block, the report section it can be
    verified in, and whether it rests on an inferred employer sector (such
    an item may be weighed, never cited by a driver).
    """
    items, missing = {}, []
    blocks = analysis["blocks"]

    def add(text, source, section, label, inferred=False):
        vid = "V%03d" % (len(items) + 1)
        items[vid] = {"text": text, "source": source, "section": section,
                      "label": label, "inferred": inferred}

    if blocks["lens"]["status"] == "ok":
        for f in blocks["lens"]["findings"]:
            add(_finding_text(f), "lens", f.get("section"), "lens/%s" % f["severity"])
    else:
        missing.append("the fresh-lens findings")
    if blocks["risk"]["status"] == "ok":
        for f in blocks["risk"]["findings"]:
            add(_finding_text(f), "risk", f.get("section"),
                "risk/%s (%s)" % (f["severity"], f["basis"]),
                inferred=f["basis"] == "inferred")
    else:
        missing.append("the non-obvious risk analysis")
    if blocks["checklist"]["status"] == "ok":
        # The step's title and status are in the STEP STATUSES block once;
        # each item carries only its step number.
        for step in blocks["checklist"]["steps"]:
            for ind in step["indicators"]:
                add(ind["bullet"], "checklist", ind.get("section"),
                    "step %02d" % step["step"])
    return items, missing


def _items_text(items) -> str:
    return "\n".join("%s [%s%s] %s" % (vid, item["label"],
                                        "; inferred, not a driver"
                                        if item.get("inferred") else "",
                                        item["text"])
                     for vid, item in items.items())


def _statuses_text(analysis) -> str:
    steps = analysis["blocks"]["checklist"]["steps"]
    return "\n".join("%02d %s: %s%s" % (
        s["step"], s["title"], s["status"].replace("_", " "),
        " (possible miss flagged)" if s.get("possible_miss") else "")
        for s in steps)


# --- validation ---------------------------------------------------------------

def _clean_driver(raw, items):
    if not isinstance(raw, dict):
        return None, "driver is not an object"
    text, reason = validate.prose(raw.get("text"), _DRIVER_MSG)
    text = _strip_refs(text) if not reason else text
    if reason:
        return None, reason
    if not text:
        return None, _DRIVER_MSG["only_refs"]
    cites, reason = validate.resolve_cites(raw.get("cites"), items, _DRIVER_MSG)
    if reason:
        return None, reason
    if any(items[c].get("inferred") for c in cites):
        return None, "driver rests on an inferred item"
    source = " ".join(items[c]["text"] for c in cites)
    reason = validate.vouch(text, source, _DRIVER_MSG)
    if reason:
        return None, reason
    return {"text": text, "cites": cites,
            "section": items[cites[0]]["section"]}, ""


def _clean_text(value, name, all_text, dropped) -> str:
    """A free-text field vouched against every item; '' when it fails."""
    if not isinstance(value, str) or not value.strip():
        return ""
    text = _strip_refs(value)
    if not text:
        dropped.append(_FIELD_MSG["only_refs"] % name)
        return ""
    invented = validate.numbers(text) - validate.numbers(all_text)
    if invented:
        dropped.append(_FIELD_MSG["figures"] % (name, ", ".join(sorted(invented))))
        return ""
    unvouched = validate.unvouched(text, all_text)
    if unvouched:
        dropped.append(_FIELD_MSG["names"] % (name, ", ".join(unvouched)))
        return ""
    return text


def _clean_list(raw_list, name, all_text, dropped) -> list:
    if not isinstance(raw_list, list):
        return []
    out, seen = [], set()
    for i, raw in enumerate(raw_list, start=1):
        text = _clean_text(raw, "%s %d" % (name, i), all_text, dropped)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return validate.capped(out, _MAX_LIST, name, dropped)


def validate_memo(raw, items) -> tuple:
    """(memo dict, dropped reasons). Raises BriefUnavailable when the output
    carries no usable outcome -- a memo without one is not a memo."""
    dropped = []
    if not isinstance(raw, dict):
        raise BriefUnavailable("model output is not a memo object")
    outcome = raw.get("outcome")
    if outcome not in prompt.OUTCOMES:
        raise BriefUnavailable("model gave no usable outcome (%r)" % (outcome,))
    confidence = raw.get("confidence")
    if confidence not in prompt.CONFIDENCES:
        dropped.append("unknown confidence %r; shown as low" % (confidence,))
        confidence = "low"
    all_text = " ".join(item["text"] for item in items.values())

    drivers, seen = [], set()
    for raw_driver in raw.get("drivers") or []:
        driver, reason = _clean_driver(raw_driver, items)
        if driver is None:
            dropped.append(reason)
            continue
        if driver["text"].lower() in seen:
            dropped.append("duplicate driver")
            continue
        seen.add(driver["text"].lower())
        drivers.append(driver)
    drivers = validate.capped(drivers, _MAX_DRIVERS, "driver", dropped)

    raw_sections = raw.get("sections") if isinstance(raw.get("sections"), dict) else {}
    sections = {key: _clean_text(raw_sections.get(key), "section %s" % key,
                                 all_text, dropped) for key in prompt.SECTIONS}
    return {
        "outcome": outcome,
        "confidence": confidence,
        "drivers": drivers,
        "conditions": _clean_list(raw.get("conditions"), "condition",
                                  all_text, dropped),
        "counter_considerations": _clean_list(raw.get("counter_considerations"),
                                              "counter-consideration",
                                              all_text, dropped),
        "what_would_change_this": _clean_text(raw.get("what_would_change_this"),
                                              "what would change this",
                                              all_text, dropped),
        "sections": sections,
        "label": prompt.ADVISORY_LABEL,
    }, dropped


# --- plain text ---------------------------------------------------------------

def plain_text(memo, date_line: str, missing: list) -> str:
    lines = ["CREDIT MEMO -- %s" % date_line, ""]
    for key in prompt.SECTIONS:
        lines.append(prompt.SECTION_TITLES[key].upper())
        lines.append(memo["sections"][key] or "(not stated)")
        lines.append("")
    lines.append("SUGGESTED OUTCOME: %s (%s confidence)"
                 % (memo["outcome"], memo["confidence"]))
    lines.append(memo["label"])
    lines.append("Drivers:")
    lines.extend("- %s" % d["text"] for d in memo["drivers"])
    if memo["conditions"]:
        lines.append("Conditions:")
        lines.extend("- %s" % c for c in memo["conditions"])
    if memo["counter_considerations"]:
        lines.append("Counter-considerations:")
        lines.extend("- %s" % c for c in memo["counter_considerations"])
    if memo["what_would_change_this"]:
        lines.append("What would change this: %s" % memo["what_would_change_this"])
    if missing:
        lines.append("Not available to this memo: %s." % ", ".join(missing))
    return "\n".join(lines).rstrip()


def generate(ctx, analysis, provider) -> dict:
    if analysis["blocks"]["checklist"]["status"] != "ok":
        raise BriefUnavailable("the memo needs the checklist block first")
    items, missing = items_from(analysis)
    if not items:
        raise BriefUnavailable("no validated items to write a memo from")
    inferred = any(item.get("inferred") for item in items.values())
    message = prompt.user_message(ctx, _items_text(items),
                                  _statuses_text(analysis), missing, inferred)
    analysis["check_prohibited"](message)
    raw = provider.chat(prompt.SYSTEM, message, prompt.MEMO_SCHEMA,
                        prompt.EFFORT)
    memo, dropped = validate_memo(raw, items)
    memo.update({
        "items": items,
        "inputs_missing": missing,
        "plain_text": plain_text(memo, report_date_line(ctx), missing),
        "dropped": dropped,
    })
    return memo


def summary(block) -> str:
    return "suggested %s, %s confidence, %d driver(s)" % (
        block["outcome"], block["confidence"], len(block["drivers"]))
