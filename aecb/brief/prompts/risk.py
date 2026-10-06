"""Block 2, the non-obvious risk reading: one schema-constrained pass over
the risk-lens facts, the context register, the employment facts and a
headline index of the rest. The patterns are computed by Python
(derive/brief_facts/{cycling,seasonality,cleanup,concentration}); the model
connects, weighs and says what to verify. It may infer an employer's sector
from the employer name alone, into a labelled field, from the register's
vocabulary; such a finding is capped and never a decision driver."""

from __future__ import annotations

from . import RULES_COMMON, fenced, report_date_line

SEVERITIES = ("info", "watch", "adverse", "severe")
CONFIDENCES = ("low", "medium", "high")

MAX_FINDINGS = 8
MAX_INFERENCES = 3

EFFORT = "low"


def schema(sectors) -> dict:
    """The output contract; the sector enum comes from the register, so a
    register change is a schema change (both under MRM change control)."""
    sector = {"type": "string", "enum": sorted(sectors)}
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "maxItems": MAX_FINDINGS + 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "so_what": {"type": "string"},
                        "severity": {"type": "string", "enum": list(SEVERITIES)},
                        "confidence": {"type": "string", "enum": list(CONFIDENCES)},
                        "cites": {"type": "array",
                                  "items": {"type": "string", "pattern": "^F[0-9]{3}$"},
                                  "minItems": 1},
                        "suggested_action": {"type": "string"},
                        "inferred_sector": sector,
                    },
                    "required": ["claim", "so_what", "severity", "confidence",
                                 "cites"],
                },
            },
            "sector_inferences": {
                "type": "array",
                "maxItems": MAX_INFERENCES + 1,
                "items": {
                    "type": "object",
                    "properties": {"employer": {"type": "string"},
                                   "sector": sector},
                    "required": ["employer", "sector"],
                },
            },
        },
        "required": ["findings", "sector_inferences"],
    }


SYSTEM = """\
You are a credit analyst reading the NON-OBVIOUS risk in a UAE credit bureau
(AECB) file for a bank underwriter: patterns a line-by-line review does not
surface. You receive RISK FACTS (patterns Python computed from the payload),
a dated CONTEXT REGISTER curated by the model owner, the EMPLOYMENT FACTS and
a HEADLINE INDEX of the other facts; every fact is numbered and citable. You
compute nothing and decide nothing.

""" + RULES_COMMON + """\
- Your knowledge of current conditions (rates, prices, sectors under stress)
  is out of date: time-sensitive context comes ONLY from the register facts,
  cited when used.
- Sector inference: the file names employers, never their sector. You MAY
  infer a named employer's sector from its name alone, from the register's
  vocabulary, in "sector_inferences" (the employer exactly as a fact names
  it) and, for a finding that rests on it, in "inferred_sector". Such a
  finding is shown as "inferred, verify", is at most "watch" and is never a
  reason to decide. Leave the field out otherwise.

Write 2 to 8 findings, most severe first, each connecting a risk fact to the
rest of the file (cite index facts by id when you use them): say what it
means beside the rest, never restate a risk fact alone. "claim": 1-3 plain
sentences; "so_what": ONE sentence on what it means for underwriting;
"suggested_action": a concrete check or customer question where one exists.
Severity: severe = active, material credit harm; adverse = clear negative
signal; watch = developing or ambiguous; info = context worth knowing.
Never state or imply an approve/decline recommendation. Output only JSON
matching the schema.
"""


def user_message(ctx, risk_text, register_text, employment_text,
                 index_text) -> str:
    return "%s\n\n%s\n\n%s\n\n%s\n\n%s\n\nEmit your findings as JSON." % (
        report_date_line(ctx), fenced("RISK FACTS", risk_text or "(none)"),
        fenced("CONTEXT REGISTER", register_text or "(none)"),
        fenced("EMPLOYMENT FACTS", employment_text or "(none)"),
        fenced("HEADLINE INDEX", index_text or "(none)"))
