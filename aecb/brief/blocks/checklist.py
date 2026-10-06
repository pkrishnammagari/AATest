"""Block 3 -- the checklist replay.

One schema-constrained model pass over the ten step packets, then a
validator that holds every indicator to the citation, verbatim-figure and
named-entity guards against its own step's facts, restores any step the
model omitted as not assessable, and runs the tripwire audit: a step the
model marked clear while its packet carries a tripwire fact is flagged as a
possible miss. The model's judgement stands either way -- the underwriter
sees both.

The copyable plain text is built here from validated bullets only.
"""

from __future__ import annotations

from ...derive.brief_facts import steps as steps_mod
from .. import validate
from ..prompts import checklist as prompt
from ..prompts import report_date_line

_MAX_INDICATORS = 6
_SEVERITY_ORDER = {"high": 0, "attention": 1, "info": 2}

_MSG = {
    "empty": "empty indicator",
    "only_refs": "indicator was only fact references",
    "no_cites": "indicator has no cites",
    "unknown_cites": "indicator cites fact(s) outside its step: %s",
    "figures": "indicator carries figures not in cited facts: %s",
    "names": "indicator carries names not in cited facts: %s",
}


def _clean_indicator(raw, packet_facts, facts_by_id):
    if not isinstance(raw, dict):
        return None, "indicator is not an object"
    bullet, reason = validate.prose(raw.get("bullet"), _MSG)
    if reason:
        return None, reason
    severity = raw.get("severity")
    if severity not in prompt.SEVERITIES:
        return None, "unknown indicator severity %r" % (severity,)
    cites, reason = validate.resolve_cites(raw.get("cites"), packet_facts, _MSG)
    if reason:
        return None, reason
    reason = validate.vouch(bullet, validate.cited_text(cites, facts_by_id), _MSG)
    if reason:
        return None, reason
    return {"bullet": bullet.strip(), "severity": severity, "cites": cites,
            "section": facts_by_id[cites[0]]["section"]}, ""


def _clean_indicators(raw_list, label, packet_facts, facts_by_id, dropped):
    seen, indicators = set(), []
    for raw in raw_list or []:
        indicator, reason = _clean_indicator(raw, packet_facts, facts_by_id)
        if indicator is None:
            dropped.append("%s: %s" % (label, reason))
            continue
        if indicator["bullet"].lower() in seen:
            dropped.append("%s: duplicate indicator" % label)
            continue
        seen.add(indicator["bullet"].lower())
        indicators.append(indicator)
    indicators.sort(key=lambda i: _SEVERITY_ORDER[i["severity"]])
    return validate.capped(indicators, _MAX_INDICATORS, "indicator", dropped)


def _clean_step(packet, raw_step, facts_by_id, dropped):
    label = "step %02d" % packet["step"]
    packet_facts = {fid: facts_by_id[fid] for fid in packet["fact_ids"]
                    if fid in facts_by_id}
    out = {"step": packet["step"], "key": packet["key"],
           "title": packet["title"], "status": "not_assessable",
           "indicators": [], "possible_miss": [],
           "not_assessable_reason": packet["not_assessable_reason"]}
    if not isinstance(raw_step, dict):
        out["not_assessable_reason"] = "model omitted the step"
        dropped.append("%s: omitted by the model" % label)
        return out
    status = raw_step.get("status")
    if status not in prompt.STATUSES:
        out["not_assessable_reason"] = "model gave an unknown status"
        dropped.append("%s: unknown status %r" % (label, status))
        return out
    out["status"] = status
    if status == "not_assessable" and not out["not_assessable_reason"]:
        out["not_assessable_reason"] = "the model judged the step not assessable"
    out["indicators"] = _clean_indicators(raw_step.get("indicators"), label,
                                          packet_facts, facts_by_id, dropped)
    # The tripwire audit: judgement stands, the disagreement is shown.
    if status == "clear":
        out["possible_miss"] = [{"fact_id": fid, "text": facts_by_id[fid]["text"]}
                                for fid in packet["tripwires"]
                                if fid in facts_by_id]
    return out


def validate_checklist(raw, packets, facts_by_id):
    """(steps, dropped): every step present, every indicator guarded."""
    dropped = []
    if not isinstance(raw, dict):
        raw, dropped = {}, ["model output is not a checklist object"]
    steps = [_clean_step(packet, raw.get("step_%02d" % packet["step"]),
                         facts_by_id, dropped) for packet in packets]
    return steps, dropped


_STATUS_WORDS = {"clear": "CLEAR", "attention": "ATTENTION",
                 "high_risk": "HIGH RISK", "not_assessable": "NOT ASSESSABLE"}


def plain_text(steps, report_date_line: str) -> str:
    """The copyable rendering: one block per step, validated bullets only."""
    lines = ["CHECKLIST REPLAY -- %s" % report_date_line, ""]
    for step in steps:
        lines.append("%02d %s -- %s" % (step["step"], step["title"],
                                        _STATUS_WORDS[step["status"]]))
        if step["status"] == "not_assessable" and step["not_assessable_reason"]:
            lines.append("   (%s)" % step["not_assessable_reason"])
        for ind in step["indicators"]:
            lines.append("- [%s] %s" % (ind["severity"].upper(), ind["bullet"]))
        for miss in step["possible_miss"]:
            lines.append("  Possible miss (marked clear): %s" % miss["text"])
        lines.append("")
    return "\n".join(lines).rstrip()


def generate(ctx, analysis, provider) -> dict:
    packets = analysis["packets"]
    facts_by_id = analysis["facts_by_id"]
    message = prompt.user_message(
        ctx, steps_mod.packets_text(packets, facts_by_id))
    analysis["check_prohibited"](message)
    raw = provider.chat(prompt.SYSTEM, message, prompt.CHECKLIST_SCHEMA,
                        prompt.EFFORT)
    steps, dropped = validate_checklist(raw, packets, facts_by_id)
    return {
        "steps": steps,
        "plain_text": plain_text(steps, report_date_line(ctx)),
        "dropped": dropped,
    }


def summary(block) -> str:
    high = sum(1 for s in block["steps"] if s["status"] == "high_risk")
    misses = sum(len(s["possible_miss"]) for s in block["steps"])
    return "%d high-risk step(s), %d possible miss(es)" % (high, misses)
