"""Block 3, the checklist replay: the model performs the credit team's ten
steps from step packets Python built (derive/brief_facts/steps.py)."""

from __future__ import annotations

from . import RULES_COMMON, fenced, report_date_line

STATUSES = ("clear", "attention", "high_risk", "not_assessable")
SEVERITIES = ("info", "attention", "high")
STEP_KEYS = tuple("step_%02d" % n for n in range(1, 11))

# Medium, not low: at "low" the pass marked the returns step clear in two of
# four runs on the delinquent fixture despite its tripwire; at "medium" it
# held in three of three (gpt-oss:20b).
EFFORT = "medium"

_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES)},
        "indicators": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bullet": {"type": "string"},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "cites": {"type": "array",
                              "items": {"type": "string", "pattern": "^F[0-9]{3}$"},
                              "minItems": 1},
                },
                "required": ["bullet", "severity", "cites"],
            },
        },
    },
    "required": ["status", "indicators"],
}

# Ten REQUIRED step keys: constrained decoding then cannot omit a step, and
# the block validator restores any that still goes missing as not_assessable.
CHECKLIST_SCHEMA = {
    "type": "object",
    "properties": {key: _STEP_SCHEMA for key in STEP_KEYS},
    "required": list(STEP_KEYS),
}

# The status and severity meanings stay one per line: with the same words run
# together as a paragraph, the pass at the "low" reasoning level marked two
# tripwire steps clear (reproduced on gpt-oss:20b); as a table it matched the
# medium level's statuses. Do not reflow it.
SYSTEM = """\
You are a credit underwriter performing the credit team's ten-step review of
a UAE credit bureau (AECB) report. You receive STEP PACKETS: for each step,
the question the team asks and the numbered facts that bear on it, computed
deterministically from the bureau payload (every day count, expiry
comparison and window test included). You receive nothing else and compute
nothing.

""" + RULES_COMMON + """\
- "cites" holds fact IDs ONLY, exactly as listed (["F057"]), never the
  fact's wording. Each step may cite ONLY the facts listed under that step.
- Judge every step. Use "not_assessable" only when the packet says the step
  cannot be assessed or lists no fact that answers its question.

For each step give a status:
  clear          nothing in the step's facts needs attention
  attention      something must be checked or explained before proceeding
  high_risk      the facts show what would normally stop or refer the case
  not_assessable the file does not allow the step to be performed

Then list the indicators, 0 to 6 per step, most severe first. An indicator
is ONE sentence written for the credit note -- the risk indicator with its
figure, in plain professional language -- with severity "high" (would
normally stop or refer), "attention" (must be checked) or "info" (worth
noting). A clear step usually has no indicators; it may carry one "info"
line stating what was checked. Output only JSON matching the schema.
"""


def user_message(ctx, packets_text: str) -> str:
    return "%s\n\n%s\n\nPerform the ten steps and emit JSON." % (
        report_date_line(ctx), fenced("STEP PACKETS", packets_text))
