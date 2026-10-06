"""Renders the AI Analysis into its full-width view.

The analysis arrives as validated blocks (aecb.brief) and this module only
draws them -- narrative composition happens nowhere: a sentence that is not a
validated item does not exist on the page.

The view replaces the report when the top-bar AI Analysis button is pressed
(body.analysis-on, toggled by report.js) and lists the blocks in page order:
fresh lens, non-obvious risk, checklist replay, memo and recommendation. A
block that has not been generated renders as a placeholder that says so;
the host generates blocks one at a time and re-renders the page after each.

Three states of the view, and they mean different things:

    coming soon            the deployment's model connector is not onboarded
                           (UAT/production by default, aecb/runtime.py) -- a
                           short note on what is being built, never findings
    no analysis attached   the model service was absent or nothing was
                           generated yet -- every block is a placeholder
    analysis attached      finished blocks draw, the rest are placeholders

Every item that cites facts carries a "Verify at §N" link whose section is
resolved here against the same registry the spine uses, so a reordering of
SECTIONS renumbers the links along with everything else. Copy buttons copy a
plain-text rendering built here from the validated items only (a hidden
<pre> per target), never scraped markup.
"""

from __future__ import annotations

from .. import runtime
from . import components as c
from .sections import flat_sections

# The blocks in page order, and how the page names them. Owned here, not by
# aecb.brief, so that rendering a page never imports the model package: a
# server with the AI panel "coming soon" must not load it (DEP-4).
BLOCKS = ("lens", "risk", "checklist", "memo")
TITLES = {"lens": "Fresh lens", "risk": "Non-obvious risk",
          "checklist": "Checklist replay", "memo": "Memo and recommendation"}

# How a severity reads on the card. The class feeds the wash-triad CSS; the
# label is the word the underwriter sees.
_SEVERITY_LABELS = {
    "severe": "Severe",
    "adverse": "Adverse",
    "watch": "Watch",
    "info": "Context",
}

_FRAMING_LABELS = {
    "story": "Story",
    "capacity_vs_behaviour": "Capacity vs behaviour",
    "who_gets_paid": "Who gets paid",
    "intent": "Intent",
    "absence": "Absence",
}

# Verified-hypothesis statuses: the chip class and the word on it.
_HYP_LABELS = {"confirmed": ("verified", "Confirmed"),
               "not_supported": ("refuted", "Not supported")}
_HYP_SOURCES = {"model": "proposed by the model",
                "fallback": "proposed by the fallback list (the model "
                            "proposed none)",
                "none": "none could be proposed"}

_BASIS_LABELS = {"payload": ("payload", "Payload"),
                 "payload+context": ("context", "Payload + context"),
                 "inferred": ("inferred", "Inferred, verify")}

SECTOR_NOTE = ("Sector read from the employer name alone, from the register's "
               "vocabulary; verify with the customer. Never a decision driver.")

OBSERVATIONS_NOTE = ("The model's own observations that no verifier covers. "
                     "Low confidence; not findings; not used by the memo; "
                     "figures and names checked against the raw tables only.")

_SUBTITLES = {
    "lens": "An independent reading of the file: trajectories, connections, "
            "absences",
    "risk": "Patterns a line-by-line review does not surface",
    "checklist": "The team's ten-step review, performed on this file",
    "memo": "Credit memo and a suggested outcome, for the underwriter to weigh",
}

# The "coming soon" copy, in one place. Deliberately generic about what the
# analysis will contain and silent on dates. The badge rides on the top-bar
# button; the rest fills the view.
SOON_BADGE = "Coming soon"
_SOON_STATUS = "In development"
_SOON_TITLE = "AI-assisted analysis is being built"
_SOON_PARAGRAPHS = (
    "This view will add an AI-assisted reading of the bureau report, "
    "drawing attention to key risk signals and pointing to the evidence for "
    "each on this page.",
    "It will be switched on only after validation and approval under model "
    "risk governance.",
    "Until then, read the sections directly. Every figure on this page is "
    "either delivered by AECB or derived from delivered values, and derived "
    "figures are marked.",
)
SOON_NOTE = ("The AI reading will interpret only — it will not compute "
             "figures or make the credit decision.")

LIVE_NOTE = ("The analysis interprets only — it never computes figures, and "
             "any suggested outcome is advisory: the underwriter decides. "
             "Model + prompt under MRM change control.")

_AI_MARK = ('<div class="ai-mark"><svg viewBox="0 0 24 24" fill="none">'
            '<path d="M12 3l1.9 4.5L18.5 9l-4.6 1.5L12 15l-1.9-4.5L5.5 9l4.6-1.5L12 3z" fill="#fff"/>'
            '<circle cx="18" cy="17" r="2" fill="#9DDBDF"/></svg></div>')


def _section_map():
    """section module name -> (anchor id, displayed number, plain title)."""
    out = {}
    for index, module in enumerate(flat_sections(), start=1):
        name = module.__name__.rsplit(".", 1)[-1]
        title = (module.META.get("title", "")
                 .replace("&amp;", "&").replace("&nbsp;", " "))
        out[name] = ("s%d" % index, "%02d" % index, title)
    return out


def _verify_link(section, sections) -> str:
    resolved = sections.get(section)
    if not resolved:
        return ""
    sid, number, title = resolved
    return ('<a class="bf-go" data-to="%s">Verify at §%s %s →</a>'
            % (sid, number, c.esc(title)))


def _chip(label, info) -> str:
    return ('<span class="bf-cite" data-info="%s">%s</span>'
            % (c.attr(info), c.esc(label)))


def _cite_chips(cites, facts_by_id) -> str:
    # Each cite chip carries its fact's text and fields in the hover bubble --
    # the provenance is one tooltip away, not a leap of faith.
    return "".join(
        _chip(cite, "%s — fields: %s" % (facts_by_id[cite]["text"],
                                         ", ".join(facts_by_id[cite]["fields"])))
        for cite in cites if cite in facts_by_id)


def _card(finding, sections, facts_by_id, chips="") -> str:
    severity = finding["severity"]
    label = _SEVERITY_LABELS.get(severity, severity)
    so_what = ""
    if finding.get("so_what"):
        so_what = ('<div class="bf-act bf-sowhat"><span class="bf-act-k">So '
                   'what</span>%s</div>' % c.esc(finding["so_what"]))
    action = ""
    if finding.get("suggested_action"):
        action = ('<div class="bf-act"><span class="bf-act-k">Verify'
                  '</span>%s</div>' % c.esc(finding["suggested_action"]))
    framing = chips
    if finding.get("framing") in _FRAMING_LABELS:
        framing += ('<span class="bf-frame">%s</span>'
                    % _FRAMING_LABELS[finding["framing"]])
    return (
        '<article class="bf-card">'
        '<div class="bf-top">'
        '<span class="bf-sev %s">%s</span>%s'
        '<span class="bf-conf">%s confidence</span>'
        '</div>'
        '<p class="bf-claim">%s</p>'
        '%s%s'
        '<div class="bf-foot">%s%s</div>'
        '</article>'
        % (severity, label, framing, c.esc(finding["confidence"]),
           c.esc(finding["claim"]), so_what, action,
           _cite_chips(finding["cites"], facts_by_id),
           _verify_link(finding.get("section"), sections)))


def _background_block(background) -> str:
    """The fenced context block. Visually and verbally set apart from the
    findings: background carries no severity and is the one part of the
    analysis allowed to lean on curated context and general sector texture,
    so the label says exactly that -- and says it is not from this report."""
    if not background:
        return ""
    items = "".join('<div class="bf-bg-note">%s</div>' % c.esc(b["note"])
                    for b in background)
    return ('<div class="bf-bg">'
            '<div class="bf-bg-t">Background context</div>'
            '%s'
            '<div class="bf-bg-cav">Curated, dated context and general '
            'sector background — framing, not payload evidence, and not a '
            'finding.</div></div>' % items)


def _unknowns_block(unknowns) -> str:
    """'What this file cannot tell you' -- the request list. Rendered apart
    from the findings because absence is a different kind of statement: it
    tells the underwriter what to ask the customer FOR, not what the bureau
    said."""
    if not unknowns:
        return ""
    items = "".join('<li>%s</li>' % c.esc(u) for u in unknowns)
    return ('<div class="bf-unk">'
            '<div class="bf-unk-t">What this file cannot tell you</div>'
            '<ul class="bf-unk-list">%s</ul></div>' % items)


def _sentence(text) -> str:
    return text[:1].upper() + text[1:]


def _hypotheses_head(tested, source) -> str:
    counts = {status: sum(1 for h in tested if h["status"] == status)
              for status in ("confirmed", "not_supported", "not_assessable")}
    return ("%d hypothes%s tested: %d confirmed, %d not supported, %d not "
            "assessable · %s"
            % (len(tested), "is" if len(tested) == 1 else "es",
               counts["confirmed"], counts["not_supported"],
               counts["not_assessable"],
               _HYP_SOURCES.get(source, _HYP_SOURCES["none"])))


def _hypotheses_block(block) -> str:
    """The loop made visible: what was proposed, and what the data said."""
    tested = block.get("hypotheses") or []
    if not tested:
        return ""
    rows = "".join(
        '<li class="an-hyp-i"><span class="bf-sev %s">%s</span>'
        '<span class="an-hyp-t">%s</span></li>'
        % (_HYP_LABELS[h["status"]][0], _HYP_LABELS[h["status"]][1],
           c.esc(_sentence(h["text"])))
        for h in tested if h["status"] in _HYP_LABELS)
    return ('<div class="an-hyp"><div class="an-hyp-h">Hypotheses tested</div>'
            '<div class="an-hyp-sub">%s</div><ul class="an-hyp-l">%s</ul>'
            '<div class="an-hyp-cav">Each hypothesis was proposed from the raw '
            'monthly tables and tested deterministically against the full '
            'history; the figures are computed, not written by the model.'
            '</div></div>'
            % (c.esc(_hypotheses_head(tested, block.get("hypotheses_source"))),
               rows))


def _observations_block(observations) -> str:
    """Custom hypotheses no verifier covers -- set apart, and said to be
    unverified in so many words, because the only guard they passed is that
    their figures and names exist in the tables."""
    if not observations:
        return ""
    items = "".join('<li>%s</li>' % c.esc(o) for o in observations)
    return ('<div class="an-obs"><div class="an-obs-t">Unverified observations'
            '</div><ul class="an-obs-l">%s</ul><div class="an-obs-cav">%s'
            '</div></div>' % (items, c.esc(OBSERVATIONS_NOTE)))


# --- block bodies -------------------------------------------------------------

def _lens_body(block, sections, facts_by_id) -> str:
    findings = block.get("findings") or []
    unknowns = block.get("unknowns") or []
    tail = (_hypotheses_block(block) + _background_block(block.get("background"))
            + _unknowns_block(unknowns)
            + _observations_block(block.get("observations")))
    if not findings and not unknowns and not block.get("background"):
        return _empty("No validated findings",
                      "The model ran but produced no finding that survived "
                      "citation and figure validation. That is a real result "
                      "on a guarded pipeline — not an error, and not a clean "
                      "bill of health.", "Read the sections directly.") + tail
    cards = "".join(_card(f, sections, facts_by_id) for f in findings)
    return ('<div class="bf-intro">%d finding(s), most severe first. Every '
            'figure is validated against the payload; chips name the fields '
            'behind each claim.</div><div class="an-cards">%s</div>%s'
            % (len(findings), cards, tail))


def _plain_findings(findings) -> list:
    lines = []
    for f in findings:
        framing = _FRAMING_LABELS.get(f.get("framing"), "")
        lines.append("- [%s]%s %s" % (
            _SEVERITY_LABELS.get(f["severity"], f["severity"]).upper(),
            " [%s]" % framing if framing else "", f["claim"]))
        if f.get("so_what"):
            lines.append("  So what: %s" % f["so_what"])
        if f.get("suggested_action"):
            lines.append("  Verify: %s" % f["suggested_action"])
    return lines


def _plain_hypotheses(block) -> list:
    tested = block.get("hypotheses") or []
    if not tested:
        return []
    return ["", "Hypotheses tested (%s):"
            % _hypotheses_head(tested, block.get("hypotheses_source"))] + [
        "- [%s] %s" % (_HYP_LABELS[h["status"]][1].upper(), _sentence(h["text"]))
        for h in tested if h["status"] in _HYP_LABELS]


def _plain_lines(title, values) -> list:
    return ["", title] + ["- %s" % v for v in values] if values else []


def _lens_plain(block) -> str:
    lines = _plain_findings(block.get("findings") or [])
    lines += _plain_hypotheses(block)
    lines += _plain_lines("What this file cannot tell you:", block.get("unknowns"))
    lines += _plain_lines("Unverified observations (%s):" % OBSERVATIONS_NOTE,
                          block.get("observations"))
    return "\n".join(lines)


def _basis_chip(finding) -> str:
    cls, label = _BASIS_LABELS.get(finding.get("basis"), ("payload", "Payload"))
    sector = finding.get("inferred_sector")
    if sector and cls == "inferred":
        label += ": " + sector.replace("_", " ")
    return '<span class="bf-basis %s">%s</span>' % (cls, c.esc(label))


def _sector_strip(inferences) -> str:
    if not inferences:
        return ""
    rows = "".join('<li><span class="an-sect-e">%s</span> &rarr; %s</li>'
                   % (c.esc(i["employer"]), c.esc(i["label"])) for i in inferences)
    return ('<div class="an-sect"><div class="an-sect-t">Employer sector '
            '(inferred, verify)</div><ul class="an-sect-l">%s</ul>'
            '<div class="an-sect-cav">%s</div></div>' % (rows, c.esc(SECTOR_NOTE)))


def _risk_body(block, sections, facts_by_id) -> str:
    findings = block.get("findings") or []
    if block.get("note"):
        return _empty("No pattern fired", block["note"],
                      "The lenses ran; read the sections directly.")
    if not findings:
        return _empty("No validated findings",
                      "The model ran but produced no finding that survived "
                      "citation and figure validation. Not an error, and not "
                      "a clean bill of health.", "Read the sections directly.") \
            + _sector_strip(block.get("sector_inferences"))
    counts = block.get("basis_counts") or {}
    intro = ("%d finding(s), most severe first. Basis: %d on payload facts, "
             "%d on payload with register context, %d on an inferred employer "
             "sector (capped at watch, never a driver)."
             % (len(findings), counts.get("payload", 0),
                counts.get("payload+context", 0), counts.get("inferred", 0)))
    cards = "".join(_card(f, sections, facts_by_id, _basis_chip(f)) for f in findings)
    return ('<div class="bf-intro">%s</div><div class="an-cards">%s</div>%s'
            % (c.esc(intro), cards, _sector_strip(block.get("sector_inferences"))))


def _risk_plain(block) -> str:
    if block.get("note"):
        return block["note"]
    lines = []
    for f in block.get("findings") or []:
        lines.append("- [%s] [%s] %s" % (
            _SEVERITY_LABELS.get(f["severity"], f["severity"]).upper(),
            _BASIS_LABELS.get(f.get("basis"), ("", "Payload"))[1].upper(), f["claim"]))
        if f.get("so_what"):
            lines.append("  So what: %s" % f["so_what"])
        if f.get("suggested_action"):
            lines.append("  Verify: %s" % f["suggested_action"])
    lines += _plain_lines("Employer sector (inferred, verify; %s):" % SECTOR_NOTE,
                          ["%s: %s" % (i["employer"], i["label"])
                           for i in block.get("sector_inferences") or []])
    return "\n".join(lines)


_STATUS_LABELS = {"clear": "Clear", "attention": "Attention",
                  "high_risk": "High risk", "not_assessable": "Not assessable"}
_IND_LABELS = {"high": "High", "attention": "Attention", "info": "Info"}
# Indicator severities draw the card chips' wash triads.
_IND_CLASS = {"high": "severe", "attention": "watch", "info": "info"}


def _indicator(ind, sections, facts_by_id) -> str:
    return ('<li class="an-ind"><span class="bf-sev %s">%s</span>'
            '<span class="an-ind-t">%s</span>'
            '<span class="an-ind-f">%s%s</span></li>'
            % (_IND_CLASS[ind["severity"]], _IND_LABELS[ind["severity"]],
               c.esc(ind["bullet"]), _cite_chips(ind["cites"], facts_by_id),
               _verify_link(ind.get("section"), sections)))


def _step(step, sections, facts_by_id) -> str:
    status = step["status"]
    body = ""
    if status == "not_assessable" and step.get("not_assessable_reason"):
        body += '<p class="an-step-note">%s</p>' % c.esc(step["not_assessable_reason"])
    if step["indicators"]:
        body += '<ul class="an-inds">%s</ul>' % "".join(
            _indicator(i, sections, facts_by_id) for i in step["indicators"])
    elif status == "clear":
        body += '<p class="an-step-note">Nothing to flag in this step.</p>'
    for miss in step.get("possible_miss") or []:
        body += ('<div class="an-miss"><span class="an-miss-k">Possible miss'
                 '</span>Marked clear, but this fact is a tripwire in the '
                 'team\'s process: %s</div>' % c.esc(miss["text"]))
    plain_id = "an-step-%02d-plain" % step["step"]
    plain = "\n".join(["%02d %s -- %s" % (step["step"], step["title"],
                                         _STATUS_LABELS[status].upper())]
                      + ["- [%s] %s" % (i["severity"].upper(), i["bullet"])
                         for i in step["indicators"]]
                      + ["  Possible miss (marked clear): %s" % m["text"]
                         for m in step.get("possible_miss") or []])
    return ('<div class="an-step st-%s" id="an-step-%02d">'
            '<div class="an-step-h"><span class="an-step-no">%02d</span>'
            '<span class="an-step-t">%s</span>'
            '<span class="an-st an-st-%s">%s</span>'
            '<button class="an-copy an-copy-sm" data-copy="%s">Copy</button>'
            '</div><div class="an-step-b">%s</div>'
            '<pre class="an-plain" id="%s">%s</pre></div>'
            % (status, step["step"], step["step"], c.esc(step["title"]),
               status, _STATUS_LABELS[status], plain_id, body, plain_id,
               c.esc(plain)))


def _checklist_body(block, sections, facts_by_id) -> str:
    steps = block.get("steps") or []
    high = sum(1 for s in steps if s["status"] == "high_risk")
    attention = sum(1 for s in steps if s["status"] == "attention")
    misses = sum(len(s.get("possible_miss") or []) for s in steps)
    intro = ("%d step(s) high risk, %d attention, %d possible miss(es) flagged "
             "by the tripwire audit. Every bullet cites the facts it rests on; "
             "copy a step or the whole checklist into the credit note."
             % (high, attention, misses))
    return ('<div class="bf-intro">%s</div><div class="an-steps">%s</div>'
            % (c.esc(intro), "".join(_step(s, sections, facts_by_id)
                                     for s in steps)))


def _stored_plain(block) -> str:
    """The copyable text the block built from its validated items."""
    return block.get("plain_text") or ""


_OUTCOME_CLASS = {"Approve": "ok", "Approve with conditions": "cond",
                  "Refer": "refer", "Decline": "decline"}
_MEMO_TITLES = {
    "applicant": "Applicant", "bureau_summary": "Bureau summary",
    "capacity": "Capacity", "conduct": "Conduct", "exposures": "Exposures",
    "red_flags": "Red flags", "mitigants": "Mitigants",
    "conditions": "Conditions", "recommendation": "Recommendation",
}


def _item_chips(cites, items) -> str:
    return "".join(_chip(v, "%s — %s" % (items[v]["label"], items[v]["text"]))
                   for v in cites if v in items)


def _driver(d, items, sections) -> str:
    return ('<li class="an-ind an-drv"><span class="an-ind-t">%s</span>'
            '<span class="an-ind-f">%s%s</span></li>'
            % (c.esc(d["text"]), _item_chips(d["cites"], items),
               _verify_link(d.get("section"), sections)))


def _plain_list(title, values) -> str:
    if not values:
        return ""
    return ('<div class="an-reco-t">%s</div><ul class="an-reco-l">%s</ul>'
            % (c.esc(title), "".join("<li>%s</li>" % c.esc(v) for v in values)))


def _memo_body(block, sections, facts_by_id) -> str:
    items = block.get("items") or {}
    reco = (
        '<div class="an-reco an-reco-%s" id="an-reco">'
        '<div class="an-reco-h"><span class="an-reco-k">Suggested outcome</span>'
        '<span class="an-outcome">%s</span>'
        '<span class="bf-conf">%s confidence</span>'
        '<button class="an-copy an-copy-sm" data-copy="an-reco-plain">Copy</button></div>'
        '<div class="an-reco-label">%s</div>'
        '<div class="an-reco-t">Drivers</div><ul class="an-inds">%s</ul>'
        '%s%s%s%s</div>'
        % (_OUTCOME_CLASS.get(block["outcome"], ""), c.esc(block["outcome"]),
           c.esc(block["confidence"]), c.esc(block["label"]),
           "".join(_driver(d, items, sections) for d in block["drivers"])
           or '<li class="an-ind"><span class="an-ind-t an-step-note">No driver '
              'survived validation.</span></li>',
           _plain_list("Conditions", block["conditions"]),
           _plain_list("Counter-considerations", block["counter_considerations"]),
           ('<div class="an-reco-t">What would change this</div><p class="an-reco-p">%s</p>'
            % c.esc(block["what_would_change_this"])) if block["what_would_change_this"] else "",
           ('<div class="an-reco-miss">Not available to this memo: %s.</div>'
            % c.esc(", ".join(block["inputs_missing"]))) if block["inputs_missing"] else ""))
    memo = "".join(
        '<section class="an-memo-s"><h3 class="an-memo-h">%s</h3><p class="an-memo-p%s">%s</p></section>'
        % (c.esc(_MEMO_TITLES[key]), "" if block["sections"][key] else " an-step-note",
           c.esc(block["sections"][key] or "Not stated."))
        for key in _MEMO_TITLES)
    reco_plain = "\n".join(
        ["SUGGESTED OUTCOME: %s (%s confidence)" % (block["outcome"], block["confidence"]),
         block["label"], "Drivers:"] + ["- %s" % d["text"] for d in block["drivers"]])
    return ('%s<div class="an-memo">%s</div>'
            '<pre class="an-plain" id="an-reco-plain">%s</pre>'
            % (reco, memo, c.esc(reco_plain)))


_BODIES = {"lens": _lens_body, "risk": _risk_body,
           "checklist": _checklist_body, "memo": _memo_body}
_PLAINS = {"lens": _lens_plain, "risk": _risk_plain,
           "checklist": _stored_plain, "memo": _stored_plain}


# --- shells -------------------------------------------------------------------

def _empty(title, *paragraphs) -> str:
    body = "".join("<p>%s</p>" % c.esc(p) for p in paragraphs)
    return ('<div class="an-empty"><div class="an-et">%s</div>'
            '<div class="an-eb">%s</div></div>' % (c.esc(title), body))


def _placeholder(block) -> str:
    if block.get("error"):
        return _empty("Not generated",
                      "This block could not be generated; details are in the "
                      "server log. Generate the analysis again from the "
                      "sidebar to retry.")
    return _empty("Not generated yet",
                  "Generate the analysis from the sidebar. Blocks appear in "
                  "order as each one finishes.")


def _block(index, name, block, sections, facts_by_id) -> str:
    if block.get("status") == "ok":
        body = _BODIES[name](block, sections, facts_by_id)
        plain = _PLAINS[name](block)
        copy = ('<button class="an-copy" data-copy="an-%s-plain">Copy</button>'
                '<pre class="an-plain" id="an-%s-plain">%s</pre>'
                % (name, name, c.esc(plain)))
        foot = ('<footer class="an-bf">generated %s · %ss · %d dropped by '
                'validation</footer>'
                % (c.esc(block.get("generated_at", "")),
                   block.get("elapsed_s", 0), len(block.get("dropped") or [])))
    else:
        body, copy, foot = _placeholder(block), "", ""
    return ('<article class="an-block" id="an-%s">'
            '<header class="an-bh"><span class="an-no">%d</span>'
            '<div><h2 class="an-bt">%s</h2><div class="an-bsub">%s</div></div>'
            '%s</header>'
            '<div class="an-bc">%s</div>%s</article>'
            % (name, index, c.esc(TITLES[name]),
               c.esc(_SUBTITLES[name]), copy, body, foot))


def _nav(analysis) -> str:
    items = []
    for index, name in enumerate(BLOCKS, start=1):
        block = analysis["blocks"][name] if analysis else {"status": "pending"}
        state = "ready" if block.get("status") == "ok" else "pending"
        items.append('<a data-to="an-%s"><span class="an-nn">%d</span>%s'
                     '<span class="an-state %s">%s</span></a>'
                     % (name, index, c.esc(TITLES[name]), state,
                        state))
    return '<nav class="an-nav" aria-label="Analysis blocks">%s</nav>' % "".join(items)


def _provenance(analysis) -> str:
    if not analysis:
        return ""
    return ('<div class="bf-prov">%s · %s · prompt %s · %s · payload %s · '
            'generation %s</div>'
            % tuple(c.esc(analysis.get(k, "")) for k in
                    ("provider", "model", "prompt_version", "started_at",
                     "payload_hash", "generation_id")))


def _shell(sub, inner, note, prov="") -> str:
    return """
<section class="analysis" id="analysis" aria-label="AI Analysis">
  <div class="an-head">
    {mark}
    <div><div class="an-title">AI Analysis</div><div class="an-sub">{sub}</div></div>
    <button class="an-x" id="analysisX" title="Back to the report">‹ Report</button>
  </div>
  {inner}
  <div class="an-foot">{prov}<div class="an-note">{note}</div></div>
</section>
""".format(mark=_AI_MARK, sub=c.esc(sub), inner=inner, note=c.esc(note),
           prov=prov)


def coming_soon_body() -> str:
    """The inner HTML while the analysis is not yet offered here."""
    paragraphs = "".join("<p>%s</p>" % c.esc(p) for p in _SOON_PARAGRAPHS)
    return ('<div class="an-empty an-soon">'
            '<div class="rs-status">%s</div>'
            '<div class="an-et">%s</div>'
            '<div class="an-eb">%s</div></div>'
            % (c.esc(_SOON_STATUS), c.esc(_SOON_TITLE), paragraphs))


def view(ctx, ai_mode: str = runtime.AI_LIVE) -> str:
    """The analysis view, or '' when the AI panel is off.

    Coming soon says what is being built and nothing about this customer,
    even if a host attached an analysis. Live draws ctx.analysis (set by the
    Streamlit host after validated model runs -- see aecb.brief) and falls
    back to placeholders when none is attached: the model may be unavailable,
    and the report must not carry narrative about a customer it cannot
    describe.
    """
    if ai_mode == runtime.AI_OFF:
        return ""
    if ai_mode == runtime.AI_SOON:
        return _shell("AI reading of the bureau payload · coming soon",
                      coming_soon_body(), SOON_NOTE)
    analysis = getattr(ctx, "analysis", None)
    sections = _section_map()
    facts_by_id = analysis["facts_by_id"] if analysis else {}
    blocks = "".join(
        _block(index, name,
               analysis["blocks"][name] if analysis else {"status": "pending"},
               sections, facts_by_id)
        for index, name in enumerate(BLOCKS, start=1))
    inner = _nav(analysis) + '<div class="an-body">%s</div>' % blocks
    return _shell("AI reading of the bureau payload", inner, LIVE_NOTE,
                  _provenance(analysis))
