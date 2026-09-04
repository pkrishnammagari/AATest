"""Hallucination guards for the brief.

The model's output is treated the way the loader treats the payload: nothing
reaches the page unchecked. Guards run in order and a failing finding is
DROPPED, never repaired -- a repaired claim is a claim nobody wrote.

Guards:
    1. shape        -- the schema is enforced at decode time by Ollama, but
                       constrained decoding has failed quietly before, so the
                       shape is re-checked here.
    2. cites exist  -- every cited fact ID must be in the digest.
    3. verbatim     -- every numeric token in the claim (and the suggested
                       action) must appear among the cited facts' numeric
                       tokens. This is the load-bearing guard: a figure the
                       model was not given cannot be rendered.
    4. named things -- every proper-noun-looking token in a claim must appear
                       in a cited fact. Small local models confabulate
                       employer and counterparty detail with total fluency;
                       a name the digest never delivered must not render.
                       Titlecase words and long ALLCAPS runs are checked;
                       sentence-initial words and a small vocabulary of
                       generic terms are exempt, so the guard costs plain
                       prose nothing.

Unknowns (the "what this file cannot tell you" list) are free-text and carry
no cites, so they are validated against the WHOLE digest: figures and names
alike must occur somewhere in it. They are deduped and capped separately.

The verify-at section is then DERIVED from the cited facts rather than trusted
from the model, findings are de-duplicated and capped, and the survivors are
sorted most-severe first.
"""

from __future__ import annotations

import re

_SEVERITIES = ("severe", "adverse", "watch", "info")
_CONFIDENCES = ("low", "medium", "high")

# At most this many findings render; the rail is a brief, not a second report.
_MAX_FINDINGS = 10
_MAX_UNKNOWNS = 5
_MAX_BACKGROUND = 3

_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Inline fact references the model sometimes writes into its prose despite
# instruction -- "(F041)", "F014," -- stripped before validation and before
# rendering: they are citation metadata leaking into text, not factual
# content, and left in place the figure guard reads "F014" as the number 14
# and drops an otherwise sound finding.
_FACT_REF_RE = re.compile(r"\(\s*F\d{3}(?:\s*,\s*F\d{3})*\s*\)|\bF\d{3}\b")

# Titlecase word ('Futtaim', 'Telecom') or an ALLCAPS run of 4+ ('TELECOM').
# 2-3 letter ALLCAPS (AED, UAE, DPD, ID) are currency/abbreviation noise, not
# names, and stay out of the guard's reach.
_ENTITY_RE = re.compile(r"\b(?:[A-Z][a-z]{2,}|[A-Z]{4,})\b")

# Generic capitalised vocabulary a finding may use without having been handed
# it: month names (facts date things as 2026-05; the model may well write
# 'May 2026') and a handful of report-domain terms.
_ENTITY_ALLOWLIST = {
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec",
    "emirates", "iban", "aecb", "nbfi",
}


def _numbers(text) -> set:
    """Canonical numeric tokens in a string.

    '34%', '34.0' and '34' all canonicalise to '34'; '115,300' to '115300';
    a date '2025-03' contributes '2025' and '3'. Facts and claims pass through
    the same canonicalisation, so a figure matches however it was punctuated --
    and only actual figures are compared, never wording.
    """
    out = set()
    for token in _NUM_RE.findall(text or ""):
        try:
            value = float(token.replace(",", ""))
        except ValueError:
            continue
        out.add("%g" % value)
    return out


def _strip_fact_refs(text) -> str:
    """Prose with inline F-id references removed and spacing tidied."""
    cleaned = _FACT_REF_RE.sub("", text or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([.,;:)])", r"\1", cleaned)
    return cleaned.strip()


def _entities(text) -> set:
    """Proper-noun-looking tokens that must be vouched for by a fact.

    The first alphabetical word of each sentence is exempt -- English
    capitalises it whether or not it names anything -- and so is the
    allowlist. Possessives are stripped ('Telecom's' -> 'telecom') before
    matching.
    """
    out = set()
    for sentence in re.split(r"[.!?]+\s*", text or ""):
        words = _ENTITY_RE.findall(sentence)
        if not words:
            continue
        # Exempt a candidate only when it is literally how the sentence
        # opens; 'The DU TELECOM record' still checks TELECOM.
        if sentence.lstrip().startswith(words[0]):
            words = words[1:]
        for word in words:
            token = word.rstrip("s'’").lower() if word.endswith(("'s", "’s")) \
                else word.lower()
            if token not in _ENTITY_ALLOWLIST:
                out.add(token)
    return out


def _unvouched(text, source_text) -> list:
    """Entities in `text` that `source_text` never mentions."""
    haystack = (source_text or "").lower()
    return sorted(t for t in _entities(text) if t not in haystack)


def _clean_finding(raw, facts_by_id):
    """The validated finding, or (None, reason)."""
    if not isinstance(raw, dict):
        return None, "finding is not an object"

    claim = raw.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        return None, "empty claim"
    claim = _strip_fact_refs(claim)
    if not claim:
        return None, "claim was only fact references"
    severity = raw.get("severity")
    if severity not in _SEVERITIES:
        return None, "unknown severity %r" % (severity,)
    confidence = raw.get("confidence")
    if confidence not in _CONFIDENCES:
        return None, "unknown confidence %r" % (confidence,)

    cites = raw.get("cites")
    if not isinstance(cites, list) or not cites:
        return None, "no cites"
    cites = [str(c).strip() for c in cites]
    missing = [c for c in cites if c not in facts_by_id]
    if missing:
        return None, "cites unknown fact(s) %s" % ", ".join(missing)

    action = raw.get("suggested_action")
    action = _strip_fact_refs(action) if isinstance(action, str) else ""

    cited_text = " ".join(facts_by_id[cite]["text"] for cite in cites)
    cited_numbers = _numbers(cited_text)
    claimed = _numbers(claim) | _numbers(action)
    invented = claimed - cited_numbers
    if invented:
        return None, ("figures not present in cited facts: %s"
                      % ", ".join(sorted(invented)))

    unvouched = _unvouched(claim + " " + action, cited_text)
    if unvouched:
        return None, ("names not present in cited facts: %s"
                      % ", ".join(unvouched))

    # The verify-at pointer comes from the facts, never the model. Cited facts
    # can span sections; the first cite is the finding's primary evidence.
    section = facts_by_id[cites[0]]["section"]

    return {
        "claim": claim.strip(),
        "severity": severity,
        "confidence": confidence,
        "cites": cites,
        "suggested_action": action,
        "section": section,
    }, ""


def _clean_background(raw_list, facts_by_id, dropped):
    """Validated background notes: same cite/figure/name guards as findings,
    no severity -- background frames, it never alarms. The name guard matters
    most here, because this is the one channel invited to use general
    knowledge and therefore the one most likely to confabulate specifics."""
    if not isinstance(raw_list, list):
        if raw_list is not None:
            dropped.append("background is not a list")
        return []
    notes = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            dropped.append("background entry is not an object")
            continue
        note = raw.get("note")
        cites = raw.get("cites")
        if not isinstance(note, str) or not note.strip():
            dropped.append("empty background note")
            continue
        note = _strip_fact_refs(note)
        if not note:
            dropped.append("background note was only fact references")
            continue
        if not isinstance(cites, list) or not cites:
            dropped.append("background note has no cites")
            continue
        cites = [str(c).strip() for c in cites]
        missing = [c for c in cites if c not in facts_by_id]
        if missing:
            dropped.append("background note cites unknown fact(s) %s"
                           % ", ".join(missing))
            continue
        cited_text = " ".join(facts_by_id[c]["text"] for c in cites)
        invented = _numbers(note) - _numbers(cited_text)
        if invented:
            dropped.append("background note carries figures not in cited "
                           "facts: %s" % ", ".join(sorted(invented)))
            continue
        unvouched = _unvouched(note, cited_text)
        if unvouched:
            dropped.append("background note carries names not in cited "
                           "facts: %s" % ", ".join(unvouched))
            continue
        notes.append({"note": note.strip(), "cites": cites})
    if len(notes) > _MAX_BACKGROUND:
        dropped.extend("over the %d-background cap" % _MAX_BACKGROUND
                       for _ in notes[_MAX_BACKGROUND:])
        notes = notes[:_MAX_BACKGROUND]
    return notes


def _clean_unknowns(raw_list, facts, dropped):
    """Validated unknowns: free-text, so vouched for by the WHOLE digest."""
    if not isinstance(raw_list, list):
        if raw_list is not None:
            dropped.append("unknowns is not a list")
        return []
    digest_text = " ".join(f["text"] for f in facts)
    digest_numbers = _numbers(digest_text)

    unknowns = []
    seen = set()
    for raw in raw_list:
        if not isinstance(raw, str) or not raw.strip():
            dropped.append("empty unknown")
            continue
        text = _strip_fact_refs(raw)
        if not text:
            dropped.append("unknown was only fact references")
            continue
        invented = _numbers(text) - digest_numbers
        if invented:
            dropped.append("unknown carries figures not in the digest: %s"
                           % ", ".join(sorted(invented)))
            continue
        unvouched = _unvouched(text, digest_text)
        if unvouched:
            dropped.append("unknown carries names not in the digest: %s"
                           % ", ".join(unvouched))
            continue
        key = text.lower()
        if key in seen:
            dropped.append("duplicate unknown")
            continue
        seen.add(key)
        unknowns.append(text)
    if len(unknowns) > _MAX_UNKNOWNS:
        dropped.extend("over the %d-unknown cap" % _MAX_UNKNOWNS
                       for _ in unknowns[_MAX_UNKNOWNS:])
        unknowns = unknowns[:_MAX_UNKNOWNS]
    return unknowns


def validate(raw_output, facts):
    """(findings, background notes, unknowns, drop reasons) for one model
    response -- each channel validated, deduped and capped.

    `facts` is the list aecb.derive.brief_facts.build produced -- the same
    digest the model read, which is what makes citation checking meaningful.
    """
    facts_by_id = {f["id"]: f for f in facts}
    dropped = []

    if not isinstance(raw_output, dict) or \
            not isinstance(raw_output.get("findings"), list):
        return [], [], [], ["model output is not a findings object"]

    findings = []
    seen_cite_sets = []
    for raw in raw_output["findings"]:
        finding, reason = _clean_finding(raw, facts_by_id)
        if finding is None:
            dropped.append(reason)
            continue
        # Two findings over the same cite set are one finding said twice.
        cite_set = frozenset(finding["cites"])
        if cite_set in seen_cite_sets:
            dropped.append("duplicate of an earlier finding (same cites)")
            continue
        seen_cite_sets.append(cite_set)
        findings.append(finding)

    findings.sort(key=lambda f: _SEVERITIES.index(f["severity"]))
    if len(findings) > _MAX_FINDINGS:
        dropped.extend("over the %d-finding cap" % _MAX_FINDINGS
                       for _ in findings[_MAX_FINDINGS:])
        findings = findings[:_MAX_FINDINGS]

    background = _clean_background(raw_output.get("background"), facts_by_id,
                                   dropped)
    unknowns = _clean_unknowns(raw_output.get("unknowns"), facts, dropped)
    return findings, background, unknowns, dropped


def validate_synthesis(text, findings) -> str:
    """The synthesis line, or '' when it cannot be vouched for.

    The synthesis pass reads only validated findings, and this check holds it
    to that: every figure and name in the sentence must already appear in a
    finding. A synthesis that fails simply does not render -- the brief is
    complete without it, so there is nothing to repair and nobody to warn.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    text = _strip_fact_refs(text)
    if not text:
        return ""
    source = " ".join(f["claim"] + " " + f.get("suggested_action", "")
                      for f in findings)
    if _numbers(text) - _numbers(source):
        return ""
    if _unvouched(text, source):
        return ""
    return text.strip()
