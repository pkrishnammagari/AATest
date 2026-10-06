"""The memo and recommendation block: items, validator, label. Model-free."""

from __future__ import annotations

import pytest

from aecb import brief, context
from aecb.brief.blocks import memo
from aecb.brief.prompts import memo as prompt
from conftest import SYNTHETIC, FakeProvider


_Model = FakeProvider


def _analysis_with_blocks(ctx, lens=True):
    """An analysis with a canned checklist (and lens) already validated."""
    a = brief.new_analysis(ctx, _Model({}))
    packets, facts = a["packets"], a["facts_by_id"]
    reply = {}
    for p in packets:
        fid = p["fact_ids"][-1]
        reply["step_%02d" % p["step"]] = {
            "status": "high_risk" if p["tripwires"] else "clear",
            "indicators": [{"bullet": "Step note: %s" % facts[fid]["text"],
                            "severity": "high", "cites": [fid]}]
            if p["tripwires"] else []}
    brief.generate_block(ctx, _Model(reply), a, "checklist")
    if lens:
        first = a["facts"][0]
        brief.generate_block(ctx, _Model({
            "findings": [{"claim": "Lens claim about %s." % first["text"][:30],
                          "so_what": "It matters.", "severity": "adverse",
                          "confidence": "high", "cites": [first["id"]]}],
            "unknowns": [], "background": []}), a, "lens")
    return a


def _reply(items, outcome="Refer", **overrides):
    vids = list(items)
    base = {
        "outcome": outcome, "confidence": "medium",
        "drivers": [{"text": "Because: %s" % items[vids[0]]["text"],
                     "cites": [vids[0]]}],
        "conditions": ["Obtain proof of closure of the requested applications."],
        "counter_considerations": ["Long bureau history."],
        "what_would_change_this": "A fresh report inside the window.",
        "sections": {key: "Section %s text." % key for key in prompt.SECTIONS},
    }
    base.update(overrides)
    return base


def test_items_come_only_from_ok_blocks():
    ctx = context.from_file(SYNTHETIC)
    a = _analysis_with_blocks(ctx, lens=False)
    items, missing = memo.items_from(a)
    assert items and all(v["source"] == "checklist" for v in items.values())
    assert list(items)[0] == "V001"
    assert "the fresh-lens findings" in missing
    assert "the non-obvious risk analysis" in missing      # risk not generated here
    a = _analysis_with_blocks(ctx, lens=True)
    items, missing = memo.items_from(a)
    assert items["V001"]["source"] == "lens" and "so what: It matters." in items["V001"]["text"]
    assert missing == ["the non-obvious risk analysis"]


def test_the_block_runs_end_to_end_and_labels_the_outcome():
    ctx = context.from_file(SYNTHETIC)
    a = _analysis_with_blocks(ctx)
    items, _ = memo.items_from(a)
    provider = _Model(_reply(items))
    block = brief.generate_block(ctx, provider, a, "memo")
    system, user, schema = provider.calls[0]
    assert system == prompt.SYSTEM and schema is prompt.MEMO_SCHEMA
    assert "BEGIN VALIDATED ITEMS" in user and "BEGIN STEP STATUSES" in user
    assert "Not available to this memo: the non-obvious risk analysis" in user
    assert block["outcome"] == "Refer" and block["label"] == prompt.ADVISORY_LABEL
    assert block["drivers"][0]["cites"] == ["V001"]
    assert block["drivers"][0]["section"] == items["V001"]["section"]
    assert block["sections"]["recommendation"] == "Section recommendation text."
    assert block["dropped"] == []
    assert "SUGGESTED OUTCOME: Refer (medium confidence)" in block["plain_text"]
    assert prompt.ADVISORY_LABEL in block["plain_text"]
    assert brief.describe(a).endswith("memo ok (suggested Refer, medium confidence, 1 driver(s))")
    assert brief.next_missing(a) == "risk" and not brief.finished(a)   # risk still pending
    a["blocks"]["risk"]["status"] = "ok"
    assert brief.finished(a)


def test_drivers_and_prose_cannot_introduce_figures_or_names():
    ctx = context.from_file(SYNTHETIC)
    a = _analysis_with_blocks(ctx)
    items, _ = memo.items_from(a)
    reply = _reply(items, drivers=[
        {"text": "Cites nothing real.", "cites": ["V999"]},
        {"text": "Invents AED 987,654,321 of exposure.", "cites": ["V001"]},
        {"text": "Names Falcon Trading as the employer.", "cites": ["V001"]},
        {"text": "Because: %s" % items["V001"]["text"], "cites": ["V001"]},
    ])
    reply["sections"]["capacity"] = "Income of AED 123,456,789 supports it."
    reply["conditions"] = ["Verify with Falcon Trading.", "Valid condition."]
    result, dropped = memo.validate_memo(reply, items)
    assert len(result["drivers"]) == 1
    assert any("unknown item" in d for d in dropped)
    assert any("driver carries figures" in d for d in dropped)
    assert any("driver carries names" in d for d in dropped)
    assert result["sections"]["capacity"] == ""
    assert any("section capacity carries figures" in d for d in dropped)
    assert result["conditions"] == ["Valid condition."]


def test_outcome_is_required_and_unbounded():
    ctx = context.from_file(SYNTHETIC)
    a = _analysis_with_blocks(ctx)
    items, _ = memo.items_from(a)
    with pytest.raises(brief.BriefUnavailable, match="no usable outcome"):
        memo.validate_memo(_reply(items, outcome="Maybe"), items)
    # No floor in code: an Approve on a delinquent file passes validation
    # (the eval harness, not the runtime, asserts the golden expectation).
    result, _ = memo.validate_memo(_reply(items, outcome="Approve"), items)
    assert result["outcome"] == "Approve"


def test_the_memo_refuses_without_the_checklist():
    ctx = context.from_file(SYNTHETIC)
    a = brief.new_analysis(ctx, _Model({}))
    assert brief.next_missing(a) == "lens"
    with pytest.raises(brief.BriefUnavailable, match="cannot be generated"):
        brief.generate_block(ctx, _Model({}), a, "memo")
