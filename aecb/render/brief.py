"""Renders the AI underwriting brief into the rail.

The brief arrives as validated findings (aecb.brief.generate_brief) and this
module only draws them -- narrative composition happens nowhere: a sentence
that is not a validated claim does not exist on the page.

Three rail states, and they mean different things:

    no brief attached      the model service was absent or failed -- the rail
                           keeps its long-standing "no brief generated" copy
    brief, zero findings   the model ran but nothing survived validation --
                           said plainly, because "no findings" from a guarded
                           pipeline is information, not an error
    brief with findings    the cards below

Findings carry section NAMES (worst_status, detail, ...); the displayed number
and anchor id are resolved here against the same registry the spine uses, so a
reordering of SECTIONS renumbers the verify-at links along with everything
else.
"""

from __future__ import annotations

from .sections import SECTIONS
from . import components as c

# How a severity reads on the card. The class feeds the wash-triad CSS; the
# label is the word the underwriter sees.
_SEVERITY_LABELS = {
    "severe": "Severe",
    "adverse": "Adverse",
    "watch": "Watch",
    "info": "Context",
}


def _section_map():
    """section module name -> (anchor id, displayed number, plain title)."""
    out = {}
    for index, module in enumerate(SECTIONS, start=1):
        name = module.__name__.rsplit(".", 1)[-1]
        title = (module.META.get("title", "")
                 .replace("&amp;", "&").replace("&nbsp;", " "))
        out[name] = ("s%d" % index, "%02d" % index, title)
    return out


def _card(finding, sections, facts_by_id) -> str:
    severity = finding["severity"]
    label = _SEVERITY_LABELS.get(severity, severity)

    action_html = ""
    if finding.get("suggested_action"):
        action_html = ('<div class="bf-act"><span class="bf-act-k">Verify'
                       '</span>%s</div>' % c.esc(finding["suggested_action"]))

    # Each cite chip carries its fact's text and fields in the hover bubble --
    # the provenance is one tooltip away, not a leap of faith.
    cites = "".join(
        '<span class="bf-cite" data-info="%s">%s</span>'
        % (c.attr("%s — fields: %s"
                  % (facts_by_id[cite]["text"],
                     ", ".join(facts_by_id[cite]["fields"]))), c.esc(cite))
        for cite in finding["cites"] if cite in facts_by_id)

    go_html = ""
    resolved = sections.get(finding.get("section"))
    if resolved:
        sid, number, title = resolved
        go_html = ('<a class="bf-go" data-to="%s">Verify at §%s %s →</a>'
                   % (sid, number, c.esc(title)))

    return (
        '<article class="bf-card">'
        '<div class="bf-top">'
        '<span class="bf-sev %s">%s</span>'
        '<span class="bf-conf">%s confidence</span>'
        '</div>'
        '<p class="bf-claim">%s</p>'
        '%s'
        '<div class="bf-foot">%s%s</div>'
        '</article>'
        % (severity, label, c.esc(finding["confidence"]),
           c.esc(finding["claim"]), action_html, cites, go_html))


def _background_block(background) -> str:
    """The fenced context block. Visually and verbally set apart from the
    findings: background carries no severity and is the one part of the brief
    allowed to lean on curated context and general sector texture, so the
    label says exactly that -- and says it is not from this report."""
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


def body(brief) -> str:
    """The .rail-body inner HTML for a generated brief."""
    findings = brief.get("findings") or []
    unknowns = brief.get("unknowns") or []
    if not findings and not unknowns and not brief.get("background"):
        return (
            '<div class="rail-empty">'
            '<div class="re-title">No validated findings</div>'
            '<div class="re-body">'
            '<p>The model ran but produced no finding that survived '
            'citation and figure validation. That is a real result on a '
            'guarded pipeline — not an error, and not a clean bill of '
            'health.</p>'
            '<p>Read the sections directly.</p>'
            '</div></div>')

    sections = _section_map()
    facts_by_id = brief.get("facts_by_id") or {}
    cards = "".join(_card(f, sections, facts_by_id) for f in findings)

    synthesis_html = ""
    if brief.get("synthesis"):
        synthesis_html = ('<p class="bf-syn">%s</p>'
                          % c.esc(brief["synthesis"]))

    return ('<div class="bf-list">'
            '%s'
            '<div class="bf-intro">%d finding(s), most severe first. Every '
            'figure is validated against the payload; chips name the fields '
            'behind each claim.</div>%s%s%s</div>'
            % (synthesis_html, len(findings), cards,
               _background_block(brief.get("background")),
               _unknowns_block(unknowns)))


def provenance(brief) -> str:
    """The audit line for the rail foot: what produced this brief, when."""
    return ('<div class="bf-prov">%s · prompt %s · %s · payload %s</div>'
            % (c.esc(brief.get("model")),
               c.esc(brief.get("prompt_version")),
               c.esc(brief.get("generated_at")),
               c.esc(brief.get("payload_hash"))))
