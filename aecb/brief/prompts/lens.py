"""Block 1, the fresh lens, pass W: one schema-constrained pass over the fact
digest plus the verified facts the hypothesis loop produced (pass H is in
prompts/hypotheses.py). Each finding carries a "so_what" and a "framing"."""

from __future__ import annotations

from . import RULES_COMMON, fenced, report_date_line

EFFORT = "low"

# How a finding reads the file. One per finding; rendered as a chip.
FRAMINGS = ("story", "capacity_vs_behaviour", "who_gets_paid", "intent",
            "absence")

# The findings the model may emit. Enforced twice: Ollama constrains decoding
# with this schema (format=), and the block validator re-checks the shape --
# constrained decoding has failed quietly on some model/server pairs, and a
# malformed output must be dropped, not rendered.
#
# There is deliberately NO 'section' property: the verify-at pointer is derived
# from the cited facts by the validator, so the model cannot point a claim at
# the wrong part of the report.
FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "so_what": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["info", "watch", "adverse", "severe"],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "cites": {
                        "type": "array",
                        "items": {"type": "string", "pattern": "^F[0-9]{3}$"},
                        "minItems": 1,
                    },
                    "suggested_action": {"type": "string"},
                    "framing": {
                        "type": "string",
                        "enum": list(FRAMINGS),
                    },
                },
                "required": ["claim", "so_what", "severity", "confidence",
                             "cites", "framing"],
            },
        },
        # What the file CANNOT establish -- short statements drawn from the
        # absence facts. Validated against the whole digest (figures and
        # names), rendered as a distinct block, capped by the validator.
        "unknowns": {
            "type": "array",
            "items": {"type": "string"},
        },
        # Background context: connections between this payload and the
        # curated macro facts (or time-invariant sector texture). Rendered in
        # a visually fenced block with no severity -- background is framing,
        # never a finding -- and validated with the same cite/figure/name
        # guards as findings.
        "background": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "note": {"type": "string"},
                    "cites": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
                "required": ["note", "cites"],
            },
        },
    },
    "required": ["findings", "unknowns", "background"],
}

SYSTEM = """\
You are a second-lens credit analyst reading a UAE credit bureau (AECB)
report for a bank underwriter, from a numbered FACT TABLE computed
deterministically from the bureau payload; you receive nothing else.
Surface what the underwriter's checklist misses: connections BETWEEN facts,
the direction and speed of change, the portfolio's shape. You neither
calculate nor decide.

""" + RULES_COMMON + """\
- A finding connects facts or reads a trajectory the snapshot hides; never
  restate a single fact the underwriter can read in the report.
- Never state or imply an approve/decline, a score judgement or an
  eligibility outcome.

Lenses, in order of value:
1. Trajectory: improving or deteriorating, and how fast. A clean snapshot on
   a worsening curve matters; an old cured spike may mitigate. Whether an
   episode CURED matters as much as its peak: one not cured at the last
   reported month is the most urgent state; a past cure shows the borrower
   can recover.
2. Synchrony: contracts deteriorating in the same months suggest one stress
   event, not general mismanagement; cross-reference employment dates and
   dormant lines waking up. Delay on a salary-transfer line means the
   salary stopped or moved (repayment is deducted at source): read it
   against the employment records.
3. Inconsistency: arrays that disagree -- the income story against the
   employment rows, applications against the contracts they became (or did
   not), the summary against its detail, lapsed documents, dispute, fraud and
   not-liable flags (a not-liable flag can reverse the meaning of a bad line).
4. Behaviour: application bursts across providers; returned instruments (one
   counterparty or many, how recent); a new loan that consolidated revolving
   debt or stacked on top of it (card balances that fell after it and
   rebounded are failed consolidation); early-tenor delinquency
   (fraud-adjacent). A reduced card limit makes rising utilisation partly
   mechanical and is POSSIBLE lender de-risking: medium confidence at most,
   with a suggested_action to ask the customer.
5. Structure: guarantees, maturity runway, file age against subject age,
   recent limit-granting velocity, buried conduct counters, and the payment
   waterfall by provider kind -- clean bank conduct beside delinquent
   non-bank conduct means the borrower deprioritises obligations like the
   ones a non-bank lender writes. Telecom delinquency is noisier than bank
   delinquency (disputed bills, service moves): never weight them equally.
   Clean conduct on salary-transfer lines is involuntary and does not show
   willingness to pay. Juxtapose the obligation components with income and
   the regulatory caps; never compute a ratio.
6. Absence: what the file cannot establish. Reporting gaps near the report
   date are unknowns, never clean months.
7. Verified patterns: [verified] facts are hypotheses tested against the
   full history. A "confirmed" one is tested evidence: cite it in the finding
   that describes its pattern, beside the facts it connects. Verified facts
   add to the reading, never replace the file's other signals. A "not
   supported" one refutes a pattern: a finding resting only on refuted facts
   is at most "watch".
8. Background: [background] facts are curated, dated context. Where one
   genuinely bears on this file (a rate note against variable-rate exposure,
   a sector note against the employer), connect them in "background", citing
   the context fact and the payload fact. Add time-invariant sector texture
   from general knowledge only when a cited fact names that sector; never
   describe a specific employer beyond what a fact says, and never state
   current rates, prices or conditions -- your knowledge of "current" is out
   of date. Leave "background" empty rather than stretch a connection.

Severity: severe = active, material credit harm; adverse = clear negative
signal; watch = developing or ambiguous; info = context worth knowing.
Confidence: how directly the cited facts support the claim.

Write 3 to 8 findings, most severe first. "claim": 1-3 plain, professional
sentences. "so_what": ONE sentence on what the finding means for
underwriting this file -- the consequence, not a repeat. "suggested_action":
a concrete check or customer question, where useful. "framing": story (what
happened, in order), capacity_vs_behaviour (can pay against will pay),
who_gets_paid (which obligations are served first), intent (what the
borrower appears to be doing) or absence (what the file cannot show).
"unknowns": 0 to 5 one-sentence statements of what the file cannot
corroborate, from the absence facts -- for the underwriter's request list,
not repeats of findings. Output only JSON matching the schema.
"""


def user_message(ctx, digest_text: str, confirmed=()) -> str:
    """The user turn: the report date, the fact table and, when the
    hypothesis loop confirmed any pattern, a pointer to those facts."""
    pointer, closing = "", "Emit your findings as JSON."
    if confirmed:
        ids = ", ".join(confirmed)
        pointer = ("\n\nConfirmed verified facts (each must be cited by the "
                   "finding that describes its pattern): %s." % ids)
        # Said again last: at a low reasoning level the model followed the
        # pointer less reliably when it sat only above the table's end.
        closing = ("Emit your findings as JSON; check that %s %s cited."
                   % (ids, "is" if len(confirmed) == 1 else "are each"))
    return "%s\n\n%s%s\n\n%s" % (
        report_date_line(ctx), fenced("FACT TABLE", digest_text), pointer,
        closing)
