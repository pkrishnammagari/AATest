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
from decimal import Decimal, InvalidOperation

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

    Exact decimal arithmetic, never float formatting: '%g' keeps six
    significant digits, which made 1,234,570 match a fact of 1,234,567.
    """
    out = set()
    for token in _NUM_RE.findall(text or ""):
        try:
            value = Decimal(token.replace(",", ""))
        except InvalidOperation:
            continue
        out.add(format(value.normalize(), "f"))
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


def _mentions(haystack: str, token: str) -> bool:
    """Whether `token` occurs in `haystack` as a word (plural allowed).

    A whole-word match, not a substring one: 'ali' must not be vouched for by
    'alignment'.
    """
    return re.search(r"\b%s(?:s|es)?\b" % re.escape(token), haystack) is not None


def _unvouched(text, source_text) -> list:
    """Entities in `text` that `source_text` never mentions."""
    haystack = (source_text or "").lower()
    return sorted(t for t in _entities(text) if not _mentions(haystack, t))


# Drop reasons per channel. The wording is part of the contract: the reasons
# are shown in the brief's provenance and asserted by the test suite.
_FINDING_MSG = {
    "empty": "empty claim",
    "only_refs": "claim was only fact references",
    "no_cites": "no cites",
    "unknown_cites": "cites unknown fact(s) %s",
    "figures": "figures not present in cited facts: %s",
    "names": "names not present in cited facts: %s",
}
_BACKGROUND_MSG = {
    "empty": "empty background note",
    "only_refs": "background note was only fact references",
    "no_cites": "background note has no cites",
    "unknown_cites": "background note cites unknown fact(s) %s",
    "figures": "background note carries figures not in cited facts: %s",
    "names": "background note carries names not in cited facts: %s",
}
_UNKNOWN_MSG = {
    "empty": "empty unknown",
    "only_refs": "unknown was only fact references",
    "figures": "unknown carries figures not in the digest: %s",
    "names": "unknown carries names not in the digest: %s",
}


def _prose(value, msg):
    """(text with fact references stripped, '') or ('', drop reason)."""
    if not isinstance(value, str) or not value.strip():
        return "", msg["empty"]
    text = _strip_fact_refs(value)
    if not text:
        return "", msg["only_refs"]
    return text, ""


def _resolve_cites(cites, facts_by_id, msg):
    """(cleaned cite list, '') or (None, drop reason)."""
    if not isinstance(cites, list) or not cites:
        return None, msg["no_cites"]
    cites = [str(c).strip() for c in cites]
    missing = [c for c in cites if c not in facts_by_id]
    if missing:
        return None, msg["unknown_cites"] % ", ".join(missing)
    return cites, ""


def _vouch(text, source_text, msg) -> str:
    """'' when every figure and name in `text` is in `source_text`; else why."""
    invented = _numbers(text) - _numbers(source_text)
    if invented:
        return msg["figures"] % ", ".join(sorted(invented))
    unvouched = _unvouched(text, source_text)
    if unvouched:
        return msg["names"] % ", ".join(unvouched)
    return ""


def _capped(items, cap, label, dropped):
    """items[:cap], recording one drop reason per item over the cap."""
    dropped.extend("over the %d-%s cap" % (cap, label) for _ in items[cap:])
    return items[:cap]


def _cited_text(cites, facts_by_id) -> str:
    return " ".join(facts_by_id[cite]["text"] for cite in cites)


def _clean_finding(raw, facts_by_id):
    """The validated finding, or (None, reason)."""
    if not isinstance(raw, dict):
        return None, "finding is not an object"
    claim, reason = _prose(raw.get("claim"), _FINDING_MSG)
    if reason:
        return None, reason
    severity = raw.get("severity")
    if severity not in _SEVERITIES:
        return None, "unknown severity %r" % (severity,)
    confidence = raw.get("confidence")
    if confidence not in _CONFIDENCES:
        return None, "unknown confidence %r" % (confidence,)
    cites, reason = _resolve_cites(raw.get("cites"), facts_by_id, _FINDING_MSG)
    if reason:
        return None, reason

    action = raw.get("suggested_action")
    action = _strip_fact_refs(action) if isinstance(action, str) else ""
    reason = _vouch(claim + " " + action, _cited_text(cites, facts_by_id),
                    _FINDING_MSG)
    if reason:
        return None, reason

    # The verify-at pointer comes from the facts, never the model. Cited facts
    # can span sections; the first cite is the finding's primary evidence.
    return {
        "claim": claim.strip(),
        "severity": severity,
        "confidence": confidence,
        "cites": cites,
        "suggested_action": action,
        "section": facts_by_id[cites[0]]["section"],
    }, ""


def _clean_note(raw, facts_by_id):
    """One validated background note, or (None, reason)."""
    if not isinstance(raw, dict):
        return None, "background entry is not an object"
    note, reason = _prose(raw.get("note"), _BACKGROUND_MSG)
    if reason:
        return None, reason
    cites, reason = _resolve_cites(raw.get("cites"), facts_by_id,
                                   _BACKGROUND_MSG)
    if reason:
        return None, reason
    reason = _vouch(note, _cited_text(cites, facts_by_id), _BACKGROUND_MSG)
    if reason:
        return None, reason
    return {"note": note.strip(), "cites": cites}, ""


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
        note, reason = _clean_note(raw, facts_by_id)
        if reason:
            dropped.append(reason)
        else:
            notes.append(note)
    return _capped(notes, _MAX_BACKGROUND, "background", dropped)


def _clean_unknowns(raw_list, facts, dropped):
    """Validated unknowns: free-text, so vouched for by the WHOLE digest."""
    if not isinstance(raw_list, list):
        if raw_list is not None:
            dropped.append("unknowns is not a list")
        return []
    digest_text = " ".join(f["text"] for f in facts)
    unknowns = []
    seen = set()
    for raw in raw_list:
        text, reason = _prose(raw, _UNKNOWN_MSG)
        reason = reason or _vouch(text, digest_text, _UNKNOWN_MSG)
        if not reason and text.lower() in seen:
            reason = "duplicate unknown"
        if reason:
            dropped.append(reason)
            continue
        seen.add(text.lower())
        unknowns.append(text)
    return _capped(unknowns, _MAX_UNKNOWNS, "unknown", dropped)


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
    findings = _capped(findings, _MAX_FINDINGS, "finding", dropped)

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
