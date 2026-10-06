"""The rendered report: the verbatim-value gate, and the page contract."""

from __future__ import annotations

import re

import pytest

import check_report  # scripts/check_report.py -- the verbatim-value gate

from aecb import context, runtime
from aecb.render.page import render_page
from conftest import SYNTHETIC


def test_every_delivered_value_is_shown_verbatim(fixture_path):
    ctx = context.from_file(fixture_path)
    assert check_report.check_page(ctx, render_page(ctx)) == []


def test_page_has_no_external_references(fixture_path):
    html = render_page(context.from_file(fixture_path))
    assert "http://" not in html and "https://" not in html


# Markup probes, not class names: the stylesheet is inlined, so .bb-soon and
# .an-soon appear in every page whatever the panel state.
_SOON_BUTTON = 'class="brief-btn soon" id="briefBtn"'
_SOON_BADGE = 'class="bb-soon"'
_SOON_VIEW = 'class="an-empty an-soon"'


def test_ai_mode_off_leaves_the_panel_out(fixture_path):
    ctx = context.from_file(fixture_path)
    with_panel = render_page(ctx)
    without = render_page(ctx, ai_mode=runtime.AI_OFF)
    assert 'id="briefBtn"' in with_panel and 'id="analysis"' in with_panel
    assert _SOON_BADGE not in with_panel and _SOON_VIEW not in with_panel
    assert 'id="briefBtn"' not in without and 'id="analysis"' not in without
    # The layout state the rest of the page is calibrated to is unchanged.
    assert '<body class="rail-off">' in without


def test_coming_soon_keeps_the_button_and_says_what_is_coming(fixture_path):
    ctx = context.from_file(fixture_path)
    html = render_page(ctx, ai_mode=runtime.AI_SOON)
    assert _SOON_BUTTON in html and _SOON_BADGE in html
    assert 'id="analysis"' in html and 'id="analysisX"' in html
    assert _SOON_VIEW in html and "being built" in html
    assert "Not generated yet" not in html       # not the placeholder copy
    assert '<body class="rail-off">' in html     # loads on the report
    assert check_report.check_page(ctx, html) == []


def test_an_unknown_ai_mode_is_refused():
    with pytest.raises(ValueError, match="unknown AI panel mode"):
        render_page(context.from_file(SYNTHETIC), ai_mode="maybe")
    with pytest.raises(TypeError):
        render_page(context.from_file(SYNTHETIC), ai_panel=False)


def test_title_escapes_the_subject_id(synthetic_payload):
    from conftest import context_of
    synthetic_payload["customerInfo"][0]["CBSubjectId"] = "<b>X</b>"
    html = render_page(context_of(synthetic_payload))
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    assert "<b>" not in title and "&lt;b&gt;" in title


def test_a_zero_delivered_as_text_is_still_zero(archive_payload):
    """ "0" must read as zero wherever a figure is tested for presence."""
    from conftest import context_of
    totals = archive_payload["contractsTotalSummary"][0]
    totals["TotalBalanceGuaranteed"] = "0"
    totals["TotalOverdueGuaranteed"] = "0"
    for row in archive_payload["contractsFinancialSummary"]:
        if row.get("ContractRole") == "G":
            for field in ("PaymentAmount", "CreditLimit", "Balance", "OverdueAmount"):
                row[field] = "0"
    for contract in archive_payload["contracts"]:
        contract["Current_OverdueAmount"] = "0"
        contract["Current_DaysPaymentDelay"] = "0"
    html = render_page(context_of(archive_payload))
    assert "Guaranteed <span class=\"aed\">AED</span>0" not in html
    assert '"overdueNow"' not in html
