"""The checklist replay: step packets, the block validator, the tripwire
audit and the copyable text. Model-free."""

from __future__ import annotations

from aecb import brief, context, dates
from aecb.brief.blocks import checklist
from aecb.brief.prompts import checklist as prompt
from aecb.derive import brief_facts, identity, scoring
from aecb.derive.brief_facts import steps
from conftest import SYNTHETIC, FakeProvider, context_of


def _packets(ctx):
    facts = brief_facts.build(ctx)
    return steps.build_packets(ctx, facts)


def _fact(rows, fid):
    return next(f for f in rows if f["id"] == fid)


def test_ten_packets_in_order_on_every_fixture(fixture_path):
    ctx = context.from_file(fixture_path)
    packets, rows = _packets(ctx)
    assert [p["step"] for p in packets] == list(range(1, 11))
    assert [p["key"] for p in packets] == [s[1] for s in steps.STEPS]
    assert all(p["fact_ids"] for p in packets)           # every step has facts
    ids = [f["id"] for f in rows]
    assert ids == ["F%03d" % (i + 1) for i in range(len(ids))]   # numbering continues
    assert all(fid in ids for p in packets for fid in p["fact_ids"])
    assert all(t in p["fact_ids"] for p in packets for t in p["tripwires"])


def test_step_two_carries_age_only_and_no_prohibited_content():
    ctx = context.from_file(SYNTHETIC)
    packets, rows = _packets(ctx)
    text = " ".join(_fact(rows, fid)["text"] for fid in packets[1]["fact_ids"])
    assert "age 38" in text
    name = identity.english_name(ctx.customer)
    assert name and name.split()[0].lower() not in text.lower()
    for banned in ("nationality", "gender", "resident"):
        assert banned not in text.lower()
    assert brief._prohibited_content(ctx, rows, steps.packets_text(
        packets, brief_facts.by_id(rows))) == ""


def test_arithmetic_facts_match_the_derive_layer():
    ctx = context.from_file(SYNTHETIC)
    packets, rows = _packets(ctx)
    v = scoring.validity(ctx)
    validity = _fact(rows, packets[0]["fact_ids"][0])["text"]
    assert "%d day(s) old" % v["age_days"] in validity
    assert packets[0]["tripwires"] == [packets[0]["fact_ids"][0]]   # stale fixture
    docs = " ".join(_fact(rows, fid)["text"] for fid in packets[2]["fact_ids"])
    eid = identity.identifiers(ctx, "EmiratesId")[0][0]
    expiry = dates.parse_any(eid.extra["ExpiryDate"])
    assert "Emirates ID on file valid until %s, %d day(s) after" % (
        expiry.strftime("%Y-%m-%d"),
        dates.days_between(ctx.report_date, expiry)) in docs
    returns_text = _fact(rows, packets[6]["fact_ids"][-1])["text"]
    assert "returned instrument(s) in the last 6 month(s)" in returns_text


def test_an_expired_emirates_id_is_a_tripwire(synthetic_payload):
    for row in synthetic_payload["identification"]:
        if identity.base_type(row.get("InfoType")) == "EmiratesId":
            row["ExpiryDate"] = "2020-01-15"
    ctx = context_of(synthetic_payload)
    packets, rows = _packets(ctx)
    docs = packets[2]
    expired = [fid for fid in docs["tripwires"]
               if "Emirates ID on file expired on 2020-01-15" in _fact(rows, fid)["text"]]
    assert expired
    assert "day(s) before the report date" in _fact(rows, expired[0])["text"]


_Model = FakeProvider


def _ok_reply(packets, facts_by_id, **overrides):
    reply = {}
    for p in packets:
        fid = p["fact_ids"][-1]
        reply["step_%02d" % p["step"]] = {
            "status": "attention",
            "indicators": [{"bullet": "Checked: %s" % facts_by_id[fid]["text"],
                            "severity": "attention", "cites": [fid]}],
        }
    reply.update(overrides)
    return reply


def test_the_block_runs_end_to_end_with_a_fake_model():
    ctx = context.from_file(SYNTHETIC)
    analysis = brief.new_analysis(ctx, _Model({}))
    provider = _Model(_ok_reply(analysis["packets"], analysis["facts_by_id"]))
    block = brief.generate_block(ctx, provider, analysis, "checklist")
    system, user, schema = provider.calls[0]
    assert system == prompt.SYSTEM and schema is prompt.CHECKLIST_SCHEMA
    assert "BEGIN STEP PACKETS" in user and "STEP 10 --" in user
    assert block["status"] == "ok" and len(block["steps"]) == 10
    assert all(s["status"] == "attention" and len(s["indicators"]) == 1
               for s in block["steps"])
    assert block["dropped"] == []
    assert block["plain_text"].startswith("CHECKLIST REPLAY -- Report date")
    assert "01 Enquiry date and report validity -- ATTENTION" in block["plain_text"]
    assert "- [ATTENTION] Checked:" in block["plain_text"]
    assert "1 high-risk step(s)" not in brief.describe(analysis)


def test_an_omitted_step_is_restored_as_not_assessable():
    ctx = context.from_file(SYNTHETIC)
    analysis = brief.new_analysis(ctx, _Model({}))
    reply = _ok_reply(analysis["packets"], analysis["facts_by_id"])
    del reply["step_05"]
    reply["step_06"]["status"] = "sideways"
    stepped, dropped = checklist.validate_checklist(reply, analysis["packets"],
                                                    analysis["facts_by_id"])
    assert len(stepped) == 10
    assert stepped[4]["status"] == "not_assessable"
    assert stepped[4]["not_assessable_reason"] == "model omitted the step"
    assert stepped[5]["status"] == "not_assessable"
    assert any("omitted" in d for d in dropped) and any("unknown status" in d for d in dropped)


def test_indicators_are_held_to_their_own_step_and_the_figure_guard():
    ctx = context.from_file(SYNTHETIC)
    analysis = brief.new_analysis(ctx, _Model({}))
    packets, facts_by_id = analysis["packets"], analysis["facts_by_id"]
    reply = _ok_reply(packets, facts_by_id)
    other = packets[6]["fact_ids"][-1]                       # a returns fact
    reply["step_01"]["indicators"] = [
        {"bullet": "Cites another step.", "severity": "high", "cites": [other]},
        {"bullet": "Invents AED 123,456,789 of overdue.", "severity": "high",
         "cites": [packets[0]["fact_ids"][0]]},
        {"bullet": "Report is outside the 30-day window.", "severity": "high",
         "cites": [packets[0]["fact_ids"][0]]},
        {"bullet": "report is outside the 30-day window.", "severity": "info",
         "cites": [packets[0]["fact_ids"][0]]},
    ]
    stepped, dropped = checklist.validate_checklist(reply, packets, facts_by_id)
    kept = stepped[0]["indicators"]
    assert [i["bullet"] for i in kept] == ["Report is outside the 30-day window."]
    assert any("outside its step" in d for d in dropped)
    assert any("figures" in d for d in dropped)
    assert any("duplicate" in d for d in dropped)
    assert kept[0]["section"] is None                        # validity has no section


def test_the_tripwire_audit_flags_a_clear_step_but_keeps_the_judgement():
    ctx = context.from_file(SYNTHETIC)
    analysis = brief.new_analysis(ctx, _Model({}))
    packets, facts_by_id = analysis["packets"], analysis["facts_by_id"]
    assert packets[6]["tripwires"]                           # returns on file
    reply = _ok_reply(packets, facts_by_id,
                      step_07={"status": "clear", "indicators": []},
                      step_02={"status": "clear", "indicators": []})
    stepped, _ = checklist.validate_checklist(reply, packets, facts_by_id)
    assert stepped[6]["status"] == "clear"
    assert [m["fact_id"] for m in stepped[6]["possible_miss"]] == packets[6]["tripwires"]
    assert stepped[1]["possible_miss"] == []                 # no tripwire, no flag
    reply["step_07"]["status"] = "attention"
    stepped, _ = checklist.validate_checklist(reply, packets, facts_by_id)
    assert stepped[6]["possible_miss"] == []
    text = checklist.plain_text(stepped, "Report date x.")
    assert "07 Cheque returns and direct-debit bounces -- ATTENTION" in text


def test_memo_waits_for_the_checklist():
    ctx = context.from_file(SYNTHETIC)
    analysis = brief.new_analysis(ctx, _Model({}))
    assert brief.next_missing(analysis) == "lens"
    analysis["blocks"]["lens"]["status"] = "ok"
    assert brief.next_missing(analysis) == "risk"
    analysis["blocks"]["risk"]["status"] = "ok"
    assert brief.next_missing(analysis) == "checklist"


def test_a_quoted_fact_text_in_cites_resolves_to_its_id():
    from aecb.brief import validate
    ctx = context.from_file(SYNTHETIC)
    analysis = brief.new_analysis(ctx, _Model({}))
    packets, facts_by_id = analysis["packets"], analysis["facts_by_id"]
    fid = packets[0]["fact_ids"][0]
    quoted = facts_by_id[fid]["text"][10:60]
    assert validate.coerce_cite(quoted, facts_by_id) == fid
    assert validate.coerce_cite("F999", facts_by_id) == "F999"
    assert validate.coerce_cite("day(s)", facts_by_id) == "day(s)"   # too short / ambiguous
    reply = _ok_reply(packets, facts_by_id)
    reply["step_01"]["indicators"] = [{"bullet": "Stale report.", "severity": "high",
                                       "cites": [quoted]}]
    stepped, dropped = checklist.validate_checklist(reply, packets, facts_by_id)
    assert stepped[0]["indicators"][0]["cites"] == [fid] and not dropped


def test_a_model_judged_not_assessable_step_carries_a_reason():
    from aecb.brief.blocks import checklist as block
    ctx = context.from_file(SYNTHETIC)
    analysis = brief.new_analysis(ctx, _Model({}))
    packets, facts_by_id = analysis["packets"], analysis["facts_by_id"]
    raw = {"step_%02d" % p["step"]: {"status": "clear", "indicators": []} for p in packets}
    raw["step_02"] = {"status": "not_assessable", "indicators": []}
    steps, dropped = block.validate_checklist(raw, packets, facts_by_id)
    assert steps[1]["status"] == "not_assessable"
    assert steps[1]["not_assessable_reason"] == "the model judged the step not assessable"
    assert not dropped
