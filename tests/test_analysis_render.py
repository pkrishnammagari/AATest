"""The AI Analysis view (aecb/render/analysis.py) inside the page."""

from __future__ import annotations

import re

import pytest

import check_report

from aecb import brief, context, runtime
from aecb.render import analysis as render_analysis
from aecb.render.page import render_page
from conftest import SYNTHETIC

# Markup probes, not class names: the stylesheet is inlined, so every class
# name appears in every page whatever the panel state.
_VIEW = 'id="analysis"'
_BACK = 'id="analysisX"'
_SOON = 'class="an-empty an-soon"'
_CARD = 'class="bf-card"'


def _analysis_with_lens(ctx, findings=None):
    """An analysis dict with the lens block already generated (no model)."""
    provider = brief.for_environment(runtime.DEV)
    a = brief.new_analysis(ctx, provider)
    first = a["facts"][0]["id"]
    a["blocks"]["lens"] = {
        "status": "ok", "error": "", "generated_at": "01 Oct 2026 14:02",
        "elapsed_s": 61, "dropped": ["figures not present in cited facts: 9"],
        "findings": findings if findings is not None else [{
            "claim": "Sample claim <b>escaped</b>.", "so_what": "Means X.",
            "severity": "watch", "confidence": "medium", "cites": [first],
            "suggested_action": "Ask the customer.",
            "section": a["facts"][0]["section"]}],
        "background": [], "unknowns": ["Income is not corroborated."],
        "observations": ["The card at 52340 looks <maxed>."],
        "hypotheses": [
            {"type": "balance_oscillation", "params_text": "balance oscillation",
             "status": "confirmed", "text": "balance on the card swung twice."},
            {"type": "closure_before_enquiry", "params_text": "closure",
             "status": "not_supported", "text": "no contract was closed."},
            {"type": "income_decline_across_updates", "params_text": "income",
             "status": "not_assessable", "text": "fewer than 2 dated figures"},
        ],
        "hypotheses_source": "model", "tables_months": 36,
    }
    return a


def test_live_without_an_analysis_shows_placeholders(fixture_path):
    html = render_page(context.from_file(fixture_path))
    assert _VIEW in html and _BACK in html and 'id="briefBtn"' in html
    assert html.count("Not generated yet") == 4
    assert _CARD not in html and _SOON not in html
    assert '<body class="rail-off">' in html


def test_coming_soon_never_shows_an_attached_analysis():
    ctx = context.from_file(SYNTHETIC)
    ctx.analysis = _analysis_with_lens(ctx)
    html = render_page(ctx, ai_mode=runtime.AI_SOON)
    assert _SOON in html and "being built" in html
    assert _CARD not in html and "Sample claim" not in html
    assert "Not generated yet" not in html


def test_off_leaves_the_view_out():
    ctx = context.from_file(SYNTHETIC)
    ctx.analysis = _analysis_with_lens(ctx)
    html = render_page(ctx, ai_mode=runtime.AI_OFF)
    assert _VIEW not in html and _BACK not in html and _CARD not in html
    assert render_page(ctx, ai_mode=runtime.AI_OFF, analysis_open=True) == html


def test_a_generated_block_renders_and_the_rest_stay_placeholders():
    ctx = context.from_file(SYNTHETIC)
    ctx.analysis = _analysis_with_lens(ctx)
    html = render_page(ctx)
    assert html.count(_CARD) == 1
    assert "Sample claim &lt;b&gt;escaped&lt;/b&gt;." in html and "<b>escaped" not in html
    assert "Means X." in html and "Ask the customer." in html
    assert "Income is not corroborated." in html
    # The loop is visible: tested hypotheses listed, not-assessable counted only.
    assert "3 hypotheses tested: 1 confirmed, 1 not supported, 1 not assessable" in html
    assert "Balance on the card swung twice." in html and "No contract was closed." in html
    assert "fewer than 2 dated figures" not in html
    # Observations are set apart, escaped, and labelled unverified.
    assert 'class="an-obs"' in html and "looks &lt;maxed&gt;." in html
    assert render_analysis.OBSERVATIONS_NOTE in html
    assert html.count("Not generated yet") == 3          # risk, checklist, memo
    assert 'class="an-state ready"' in html and html.count('class="an-state pending"') == 3
    assert "1 dropped by validation" in html
    assert "generation %s" % ctx.analysis["generation_id"] in html


def test_verify_links_resolve_to_the_section_registry():
    ctx = context.from_file(SYNTHETIC)
    ctx.analysis = _analysis_with_lens(ctx)
    html = render_page(ctx)
    link = re.search(r'<a class="bf-go" data-to="(s\d+)">Verify at §(\d\d) ', html)
    assert link and link.group(1) == "s" + str(int(link.group(2)))
    assert 'id="%s"' % link.group(1) in html                   # the section exists


def test_copy_targets_hold_the_validated_text_only():
    ctx = context.from_file(SYNTHETIC)
    ctx.analysis = _analysis_with_lens(ctx)
    html = render_page(ctx)
    pre = re.search(r'<pre class="an-plain" id="an-lens-plain">(.*?)</pre>', html,
                    re.S).group(1)
    assert "[WATCH] Sample claim &lt;b&gt;escaped&lt;/b&gt;." in pre
    assert "So what: Means X." in pre and "Verify: Ask the customer." in pre
    assert "Hypotheses tested" in pre and "[CONFIRMED] Balance on the card" in pre
    assert "Unverified observations" in pre and "<" not in pre.replace("&lt;", "")
    assert 'data-copy="an-lens-plain"' in html


def test_analysis_open_sets_the_body_class():
    ctx = context.from_file(SYNTHETIC)
    assert '<body class="rail-off analysis-on">' in render_page(ctx, analysis_open=True)
    assert '<body class="rail-off">' in render_page(ctx)


def test_the_verbatim_gate_passes_with_an_analysis_attached():
    ctx = context.from_file(SYNTHETIC)
    ctx.analysis = _analysis_with_lens(ctx)
    assert check_report.check_page(ctx, render_page(ctx, analysis_open=True)) == []


def test_zero_findings_is_said_plainly():
    ctx = context.from_file(SYNTHETIC)
    ctx.analysis = _analysis_with_lens(ctx, findings=[])
    ctx.analysis["blocks"]["lens"]["unknowns"] = []
    html = render_page(ctx)
    assert "No validated findings" in html and _CARD not in html
    # The hypotheses the verifier answered still show under the empty state.
    assert "Hypotheses tested" in html


def test_framing_chip_renders_only_for_a_known_framing():
    ctx = context.from_file(SYNTHETIC)
    ctx.analysis = _analysis_with_lens(ctx)
    ctx.analysis["blocks"]["lens"]["findings"][0]["framing"] = "who_gets_paid"
    html = render_page(ctx)
    assert '<span class="bf-frame">Who gets paid</span>' in html
    ctx.analysis["blocks"]["lens"]["findings"][0]["framing"] = "bogus"
    assert 'class="bf-frame"' not in render_page(ctx)


def test_no_hypotheses_and_no_observations_render_nothing_extra():
    ctx = context.from_file(SYNTHETIC)
    ctx.analysis = _analysis_with_lens(ctx)
    ctx.analysis["blocks"]["lens"].update({"hypotheses": [], "observations": []})
    html = render_page(ctx)
    assert 'class="an-hyp"' not in html and 'class="an-obs"' not in html


@pytest.mark.parametrize("mode", runtime.AI_MODES)
def test_every_mode_keeps_exactly_one_script(fixture_path, mode):
    html = render_page(context.from_file(fixture_path), ai_mode=mode)
    assert html.count("<script>") == 1 and not re.search(r"\son[a-z]+=", html)


def test_soon_copy_lives_in_one_place():
    assert render_analysis.SOON_BADGE == "Coming soon"
    assert "coming soon" in render_page(context.from_file(SYNTHETIC),
                                        ai_mode=runtime.AI_SOON).lower()
