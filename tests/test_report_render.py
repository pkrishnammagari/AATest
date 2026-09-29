"""The rendered report: the verbatim-value gate, and the page contract."""

from __future__ import annotations

import re

import check_report  # scripts/check_report.py -- the verbatim-value gate

from aecb import context
from aecb.render.page import render_page


def test_every_delivered_value_is_shown_verbatim(fixture_path):
    ctx = context.from_file(fixture_path)
    assert check_report.check_page(ctx, render_page(ctx)) == []


def test_page_has_no_external_references(fixture_path):
    html = render_page(context.from_file(fixture_path))
    assert "http://" not in html and "https://" not in html


def test_ai_panel_can_be_left_out(fixture_path):
    ctx = context.from_file(fixture_path)
    with_panel = render_page(ctx)
    without = render_page(ctx, ai_panel=False)
    assert 'id="briefBtn"' in with_panel and 'id="rail"' in with_panel
    assert 'id="briefBtn"' not in without and 'id="rail"' not in without
    # The layout state the rest of the page is calibrated to is unchanged.
    assert '<body class="rail-off">' in without


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
