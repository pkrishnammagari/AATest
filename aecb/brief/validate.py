"""Hallucination guards for the AI analysis.

The model's output is treated the way the loader treats the payload: nothing
reaches the page unchecked. Guards run in order and a failing item is
DROPPED, never repaired -- a repaired claim is a claim nobody wrote.

validate() is the lens block's validator; the toolkit it is built from
(numbers, entities, vouch, prose, resolve_cites, capped, strip_fact_refs) is
public so every block validator (aecb/brief/blocks/) holds its output to the
same guards.

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
_FRAMINGS = ("story", "capacity_vs_behaviour", "who_gets_paid", "intent",
             "absence")
# A finding resting ONLY on refuted hypotheses is capped here.
_REFUTED = "not_supported"
_REFUTED_CAP = "watch"

# At most this many findings render; the analysis is a reading, not a second report.
_MAX_FINDINGS = 10
_MAX_UNKNOWNS = 5
_MAX_BACKGROUND = 3
_MAX_OBSERVATIONS = 3

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


def _entities(text, allow=()) -> set:
    """Proper-noun-looking tokens that must be vouched for by a fact.

    The first alphabetical word of each sentence is exempt -- English
    capitalises it whether or not it names anything -- and so is the
    allowlist (plus any block-specific `allow` words, such as the register's
    sector vocabulary for the risk block). Possessives are stripped
    ('Telecom's' -> 'telecom') before matching.
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
            if token not in _ENTITY_ALLOWLIST and token not in allow:
                out.add(token)
    return out


def _mentions(haystack: str, token: str) -> bool:
    """Whether `token` occurs in `haystack` as a word (plural allowed).

    A whole-word match, not a substring one: 'ali' must not be vouched for by
    'alignment'.
    """
    return re.search(r"\b%s(?:s|es)?\b" % re.escape(token), haystack) is not None


def _unvouched(text, source_text, allow=()) -> list:
    """Entities in `text` that `source_text` never mentions."""
    haystack = (source_text or "").lower()
    return sorted(t for t in _entities(text, allow) if not _mentions(haystack, t))


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
_OBSERVATION_MSG = {
    "empty": "empty observation",
    "only_refs": "observation was only fact references",
    "figures": "observation carries figures not in the tables: %s",
    "names": "observation carries names not in the tables: %s",
}


def _prose(value, msg):
    """(text with fact references stripped, '') or ('', drop reason)."""
    if not isinstance(value, str) or not value.strip():
        return "", msg["empty"]
    text = _strip_fact_refs(value)
    if not text:
        return "", msg["only_refs"]
    return text, ""


def coerce_cite(cite, facts_by_id) -> str:
    """A cite as an id: the id itself, or the ONE fact whose text the model
    quoted instead of its id.

    gpt-oss has filled "cites" with the fact's wording rather than its id
    (two runs in three, on gpt-oss:20b). That is still the model's own
    evidence, so a quote that matches exactly one fact's text -- as a
    whole, or as a substring of it -- resolves to that fact. Anything
    ambiguous or unmatched is returned unchanged and fails the cite check.
    """
    cite = str(cite).strip()
    if cite in facts_by_id or len(cite) < 12:
        return cite
    needle = cite.lower().rstrip(".")
    hits = [fid for fid, fact in facts_by_id.items()
            if needle in fact["text"].lower()]
    return hits[0] if len(hits) == 1 else cite


def _resolve_cites(cites, facts_by_id, msg):
    """(cleaned cite list, '') or (None, drop reason)."""
    if not isinstance(cites, list) or not cites:
        return None, msg["no_cites"]
    cites = [coerce_cite(c, facts_by_id) for c in cites]
    missing = [c for c in cites if c not in facts_by_id]
    if missing:
        return None, msg["unknown_cites"] % ", ".join(missing)
    return cites, ""


def _vouch(text, source_text, msg, allow=()) -> str:
    """'' when every figure and name in `text` is in `source_text`; else why."""
    invented = _numbers(text) - _numbers(source_text)
    if invented:
        return msg["figures"] % ", ".join(sorted(invented))
    unvouched = _unvouched(text, source_text, allow)
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
    so_what = raw.get("so_what")
    so_what = _strip_fact_refs(so_what) if isinstance(so_what, str) else ""
    reason = _vouch(" ".join((claim, action, so_what)),
                    _cited_text(cites, facts_by_id), _FINDING_MSG)
    if reason:
        return None, reason

    severity, capped = _cap_refuted(severity, cites, facts_by_id)
    framing = raw.get("framing")
    # The verify-at pointer comes from the facts, never the model. Cited facts
    # can span sections; the first cite is the finding's primary evidence.
    return {
        "claim": claim.strip(),
        "so_what": so_what.strip(),
        "severity": severity,
        "confidence": confidence,
        "framing": framing if framing in _FRAMINGS else "",
        "cites": cites,
        "suggested_action": action,
        "section": facts_by_id[cites[0]]["section"],
        "capped": capped,
    }, ""


def _cap_refuted(severity, cites, facts_by_id):
    """(severity, note): a finding whose every cite is a refuted hypothesis
    is at most _REFUTED_CAP. The text stands; only the severity is held
    down, and the cap is recorded with the drop reasons so it is visible."""
    statuses = [facts_by_id[c].get("status") for c in cites]
    if all(status == _REFUTED for status in statuses) and \
            _SEVERITIES.index(severity) < _SEVERITIES.index(_REFUTED_CAP):
        return _REFUTED_CAP, ("severity capped at %s: the finding rests only "
                              "on refuted hypotheses" % _REFUTED_CAP)
    return severity, ""


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
        note = finding.pop("capped")
        if note:
            dropped.append(note)
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


_ALIAS_RE = re.compile(r"\bK\d{1,2}\b")


def _resolve_aliases(text, labels) -> str:
    """Contract aliases (K1, K2 ...) replaced by the labels they stand for.

    `labels` maps an alias to (label, contract id). The alias is a handle
    Python minted for the tables; the underwriter never sees the tables, so
    an alias in prose would name nothing. This is resolution of our own
    identifier, like a cite id to its fact -- not a repair of the model's
    content. Where the model already wrote the contract id right after the
    alias ("K1 Credit Card C418..."), the alias is simply removed rather
    than doubled. An alias outside the tables stays as it is and reads as
    what it is: unresolved.
    """
    def resolve(match):
        entry = labels.get(match.group(0))
        if entry is None:
            return match.group(0)
        label, contract_id = entry
        following = text[match.end():match.end() + 80]
        if contract_id and contract_id in following:
            return ""
        return label
    resolved = _ALIAS_RE.sub(resolve, text)
    return re.sub(r"\s{2,}", " ", resolved).strip()


def validate_observations(texts, source_text, labels=None):
    """(observations, drop reasons): the model's custom hypotheses, vouched
    against the text they were proposed from -- the raw tables and the
    headline index, plus the labels the contract aliases resolve to --
    never against the digest. They render apart as
    unverified: figures and names must still be real, but nothing has been
    tested, so they are never findings and never reach the memo."""
    out, seen, dropped = [], set(), []
    for raw in texts or []:
        text, reason = _prose(raw, _OBSERVATION_MSG)
        text = _resolve_aliases(text, labels or {})
        reason = reason or _vouch(text, source_text, _OBSERVATION_MSG)
        if not reason and text.lower() in seen:
            reason = "duplicate observation"
        if reason:
            dropped.append(reason)
            continue
        seen.add(text.lower())
        out.append(text.strip())
    return _capped(out, _MAX_OBSERVATIONS, "observation", dropped), dropped


# The public toolkit for the other block validators.
numbers = _numbers
unvouched = _unvouched
vouch = _vouch
prose = _prose
resolve_cites = _resolve_cites
capped = _capped
strip_fact_refs = _strip_fact_refs
cited_text = _cited_text
