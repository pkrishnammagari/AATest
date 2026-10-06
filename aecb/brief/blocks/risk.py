"""Block 2 -- the non-obvious risk reading.

One schema-constrained pass over the risk-lens facts (theme "risk"), the
context register, the employment facts and a headline index of the rest;
then the four guards, with the register's sector vocabulary allow-listed for
the name guard, and three block-specific controls:

    basis      derived by Python from the cites, never trusted from the
               model: "payload" (payload facts only), "payload+context" (a
               register fact among the cites), "inferred" (the finding rests
               on an employer-sector inference)
    cap        an inferred finding is at most "watch" (recorded with the
               drop reasons)
    inferences the model's employer -> sector readings: the employer must be
               named in the payload facts, the sector must be in the
               register's vocabulary; capped; shown as "inferred, verify"

Inferred findings reach the memo as items but can never be drivers
(blocks/memo.py). Without any risk fact the block makes no model pass and
says so.
"""

from __future__ import annotations

from ...derive import brief_facts, identity
from ...derive.brief_facts import background
from ...derive.brief_facts._common import BACKGROUND, RISK, text as clean_text
from .. import validate
from ..prompts import risk as prompt

NO_PATTERN = ("No non-obvious risk pattern fired on this file; the lenses "
              "were run and stayed silent.")

INFERRED_CAP = "watch"

_MSG = {
    "empty": "empty claim",
    "only_refs": "claim was only fact references",
    "no_cites": "no cites",
    "unknown_cites": "cites unknown fact(s) %s",
    "figures": "figures not present in cited facts: %s",
    "names": "names not present in cited facts: %s",
}


def _basis(cites, inferred_sector, facts_by_id) -> str:
    if inferred_sector:
        return "inferred"
    if any(facts_by_id[c]["theme"] == BACKGROUND for c in cites):
        return "payload+context"
    return "payload"


def _clean_finding(raw, facts_by_id, vocab, allow):
    if not isinstance(raw, dict):
        return None, "finding is not an object"
    claim, reason = validate.prose(raw.get("claim"), _MSG)
    if reason:
        return None, reason
    severity, confidence = raw.get("severity"), raw.get("confidence")
    if severity not in prompt.SEVERITIES:
        return None, "unknown severity %r" % (severity,)
    if confidence not in prompt.CONFIDENCES:
        return None, "unknown confidence %r" % (confidence,)
    cites, reason = validate.resolve_cites(raw.get("cites"), facts_by_id, _MSG)
    if reason:
        return None, reason
    action = raw.get("suggested_action")
    action = validate.strip_fact_refs(action) if isinstance(action, str) else ""
    so_what = raw.get("so_what")
    so_what = validate.strip_fact_refs(so_what) if isinstance(so_what, str) else ""
    reason = validate.vouch(" ".join((claim, so_what, action)),
                            validate.cited_text(cites, facts_by_id), _MSG, allow)
    if reason:
        return None, reason
    sector = raw.get("inferred_sector")
    sector = sector if sector in vocab else ""
    return {
        "claim": claim.strip(), "so_what": so_what.strip(),
        "severity": severity, "confidence": confidence, "cites": cites,
        "suggested_action": action,
        "inferred_sector": sector,
        "basis": _basis(cites, sector, facts_by_id),
        "section": facts_by_id[cites[0]]["section"],
    }, ""


def _clean_inference(raw, employers, vocab):
    if not isinstance(raw, dict):
        return None, "sector inference is not an object"
    employer = clean_text(raw.get("employer") or "")
    sector = raw.get("sector")
    if employer.lower() not in employers:
        return None, "sector inference names an employer not in the file: %s" % employer
    if sector not in vocab:
        return None, "sector inference uses a sector outside the register: %r" % (sector,)
    return {"employer": employers[employer.lower()], "sector": sector,
            "label": vocab[sector]}, ""


def _clean_findings(raw_list, facts_by_id, vocab, dropped):
    allow = {w for key, label in vocab.items()
             for w in (key.replace("_", " ") + " " + label).lower().split()}
    order = {s: i for i, s in enumerate(reversed(prompt.SEVERITIES))}
    findings, seen = [], []
    for entry in raw_list:
        finding, reason = _clean_finding(entry, facts_by_id, vocab, allow)
        if finding is None:
            dropped.append(reason)
            continue
        cite_set = frozenset(finding["cites"])
        if cite_set in seen:
            dropped.append("duplicate of an earlier finding (same cites)")
            continue
        seen.append(cite_set)
        if finding["basis"] == "inferred" and order[finding["severity"]] < order[INFERRED_CAP]:
            dropped.append("severity capped at %s: the finding rests on an "
                           "inferred employer sector" % INFERRED_CAP)
            finding["severity"] = INFERRED_CAP
        findings.append(finding)
    findings.sort(key=lambda f: order[f["severity"]])
    return validate.capped(findings, prompt.MAX_FINDINGS, "finding", dropped)


def _clean_inferences(raw_list, employers, vocab, dropped):
    inferences, named = [], set()
    for entry in raw_list or []:
        inference, reason = _clean_inference(entry, employers, vocab)
        if inference is None:
            dropped.append(reason)
        elif inference["employer"] in named:
            dropped.append("duplicate sector inference")
        else:
            named.add(inference["employer"])
            inferences.append(inference)
    return validate.capped(inferences, prompt.MAX_INFERENCES,
                           "sector inference", dropped)


def validate_risk(raw, facts_by_id, vocab, employers):
    """(findings, sector inferences, drop reasons)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("findings"), list):
        return [], [], ["model output is not a findings object"]
    dropped = []
    findings = _clean_findings(raw["findings"], facts_by_id, vocab, dropped)
    inferences = _clean_inferences(raw.get("sector_inferences"), employers,
                                   vocab, dropped)
    return findings, inferences, dropped


def _employers(ctx) -> dict:
    """{lowercased sanitised employer name: that name} for every employer
    the file names, current or prior."""
    current, prior = identity.employers(ctx)
    names = {}
    for entry in current + prior:
        name = clean_text(entry.value)
        names[name.lower()] = name
    return names


def _inputs(facts):
    """The three full-text groups and the index of the rest."""
    risk = [f for f in facts if f["theme"] == RISK]
    register = [f for f in facts if f["theme"] == BACKGROUND]
    employment = [f for f in facts if f["theme"] != RISK
                  and any("employment[" in field for field in f["fields"])]
    shown = {f["id"] for f in risk + register + employment}
    rest = [f for f in facts if f["id"] not in shown]
    return (brief_facts.digest(risk), brief_facts.digest(register),
            brief_facts.digest(employment), brief_facts.index(rest))


def generate(ctx, analysis, provider) -> dict:
    facts = analysis["facts"]
    vocab = background.sector_vocabulary()
    risk_text, register_text, employment_text, index_text = _inputs(facts)
    if not risk_text:
        return {"findings": [], "sector_inferences": [], "note": NO_PATTERN,
                "basis_counts": {}, "dropped": []}
    message = prompt.user_message(ctx, risk_text, register_text,
                                  employment_text, index_text)
    analysis["check_prohibited"](message)
    raw = provider.chat(prompt.SYSTEM, message,
                        prompt.schema(vocab or {"other": "Other"}), prompt.EFFORT)
    findings, inferences, dropped = validate_risk(
        raw, analysis["facts_by_id"], vocab, _employers(ctx))
    counts = {}
    for f in findings:
        counts[f["basis"]] = counts.get(f["basis"], 0) + 1
    return {"findings": findings, "sector_inferences": inferences, "note": "",
            "basis_counts": counts, "dropped": dropped}


def summary(block) -> str:
    inferred = block.get("basis_counts", {}).get("inferred", 0)
    return "%d finding(s), %d inferred, %d dropped" % (
        len(block["findings"]), inferred, len(block["dropped"]))
