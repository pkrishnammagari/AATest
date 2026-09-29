"""Every check the corpus harness can raise, in one catalogue.

A check id is stable: the report, the baseline and any triage log refer to it.
Its severity decides the exit code and the report order; its hint is where
whoever triages -- you, or Claude Code -- should look first.

  ERROR  the harness could not finish the payload: it would not load, or the
         page raised while rendering. Fix these first; nothing else about the
         payload was checked.
  FAIL   the rendered page breaks a rule the product promises -- a delivered
         value missing, a figure that contradicts the payload, a Python None
         leaking onto the screen. Presumed a code bug until triage says not.
  WARN   the page copes, but a person should look: a value the config cannot
         read, a date that will not parse, rows the page has nowhere to show,
         a change against the approved baseline.
  INFO   context, not a problem: schema drift, providers missing from the
         stub registry, a payload with no baseline yet.

Python 3.9 compatible.
"""

from __future__ import annotations

ERROR, FAIL, WARN, INFO = "ERROR", "FAIL", "WARN", "INFO"
SEVERITIES = (ERROR, FAIL, WARN, INFO)
RANK = dict((s, i) for i, s in enumerate(SEVERITIES))


class Check(object):
    __slots__ = ("id", "severity", "layer", "title", "hint")

    def __init__(self, id, severity, layer, title, hint):
        self.id = id
        self.severity = severity
        self.layer = layer
        self.title = title
        self.hint = hint

    def as_dict(self):
        return dict((k, getattr(self, k)) for k in self.__slots__)


_CHECKS = (
    # --- load & render -------------------------------------------------------
    ("load.json", ERROR, "load",
     "File is not readable JSON",
     "The file is not UTF-8 JSON. app_api.py only archives responses that "
     "parsed, so suspect the copy onto this machine before the code."),
    ("load.shape", ERROR, "load",
     "Not an AECB payload",
     "No customerInfo, summary or score row -- app_api._validated_context "
     "would have rejected it. Check the file really is a report."),
    ("load.context", ERROR, "load",
     "ReportContext could not be built",
     "aecb/context.py or aecb/loader.py raised. The traceback names the "
     "frame; a config file problem affects every payload at once."),
    ("render.page", ERROR, "render",
     "render_page raised",
     "The whole page failed. The render.section findings beside it name the "
     "section that raised; start from the deepest aecb/ frame in the "
     "traceback."),
    ("render.section", ERROR, "render",
     "A section (or the top bar / page blob) raised on its own",
     "Rendered alone to localise a render.page crash. The traceback's aecb/ "
     "frames point at the derive or render function to harden."),
    ("perf.slow", WARN, "render",
     "Render took unusually long",
     "Over the --slow threshold. Profile the payload; large contractsHistory "
     "arrays are the usual suspect."),

    # --- the existing gate ---------------------------------------------------
    ("gate.check_report", FAIL, "no-drop",
     "scripts/check_report.py assertion failed",
     "The same assertions the fast gate runs on the committed fixtures, run "
     "on this payload. The message names the element; the assertion lives "
     "in scripts/check_report.py check_page()."),

    # --- no-drop ---------------------------------------------------------------
    ("nodrop.heatmap_contracts", FAIL, "no-drop",
     "Contracts missing from (or duplicated in) the section 07 heatmap",
     "render/js.py _heatmap/_block: rows are grouped by ContractCategory and "
     "only I/C/N/S are iterated, so a contract in any other category never "
     "reaches the page."),
    ("nodrop.applications_events", FAIL, "no-drop",
     "Timeline events do not match the datable application rows",
     "derive/applications.py timeline(): every row with a usable date should "
     "become one event."),
    ("nodrop.applications_undated", WARN, "no-drop",
     "Some application rows have no usable date and are not on the timeline",
     "sections/applications.py states 'cannot be placed in time' only when "
     "NO row is dated; a partial loss is silent. Decide whether the section "
     "should say so."),
    ("nodrop.history_orphan", WARN, "no-drop",
     "contractsHistory rows for a contract that is not in contracts",
     "derive/facilities.history_by_contract joins on CBContractId; rows with "
     "no matching contract are never drawn. Payload quirk or a join key "
     "mismatch (type, spacing)?"),
    ("nodrop.history_duplicate_month", WARN, "no-drop",
     "Two different history rows for one contract and month",
     "history_by_contract keeps the LAST row per month, so the other is "
     "dropped silently. Check whether they are two reports of one month or "
     "a date-parsing collision."),
    ("nodrop.history_future", WARN, "no-drop",
     "History rows dated after the report month are dropped",
     "history_by_contract discards months < 0. Usually the report date "
     "(enquiry ladder) predates the data pull; see docs/LowLevelArchitecture.md "
     "(top bar)."),
    ("nodrop.contacts_type", WARN, "no-drop",
     "Contacts of a type the page never shows",
     "sections/identity.py renders Mobile Number, Phone Number and E-mail "
     "only. Any other base ContactType is dropped -- needs a decision."),
    ("nodrop.fin_summary_role", FAIL, "no-drop",
     "Section 06 summary rows with a role or category the page never reads",
     "derive/facilities.financial_summary/count_summary match ContractRole "
     "exactly against A/C/G, and the cards iterate I/C/N/S. Other values "
     "vanish from the page."),
    ("nodrop.unknown_arrays", WARN, "no-drop",
     "Top-level arrays the loader does not know",
     "aecb/loader.py ARRAYS. The page does not render them (app.py only "
     "warns in its sidebar). A new AECB section needs a decision."),

    # --- recomputed from the raw payload -------------------------------------
    ("recompute.validity", FAIL, "recompute",
     "Top-bar validity pill disagrees with the enquiry ladder",
     "Recomputed: latest parseable sectionStatus 'Last EnquiryDate', else "
     "score.DataPullDate, aged against today and bands.json validity_days. "
     "See derive/scoring.validity and render/shell.py."),
    ("recompute.age", FAIL, "recompute",
     "Section 01 age disagrees with DOB at the report date",
     "sections/identity._dob_trait -> derive/identity.age_at."),
    ("recompute.residency", FAIL, "recompute",
     "Section 01 residency pill disagrees with ResidentFlag",
     "sections/identity._residency -> derive/identity.resident_flag."),
    ("recompute.score", FAIL, "recompute",
     "Section 02 score, band chips or mismatch mark disagree with the payload",
     "sections/score.py: the dial figure, the delivered FHScoreBand / "
     "DataRange chips, and the '!' shown only when the configured cut-offs "
     "put the score in another band."),
    ("recompute.vintage", FAIL, "recompute",
     "Section 02 vintage band disagrees with the file length",
     "derive/scoring.vintage_band over OldestContractOpenDate -> report date."),
    ("recompute.worst_panels", FAIL, "recompute",
     "Section 03 panel colours or the header pill contradict the statuses",
     "sections/worst_status.py _grade/_aside: rank <=60 red, <100 amber, 100 "
     "green, unknown uncoloured; the pill follows the worst panel."),
    ("recompute.worst_floor", FAIL, "recompute",
     "Section 03 36-month panel is milder than the delivered 24 months",
     "User decision 24 Sep 2026: the 36 months include the 24, so the "
     "delivered figure shows whenever the derivation comes out milder. "
     "sections/worst_status._derived_36m / _delay_line_36."),
    ("recompute.income_current", FAIL, "recompute",
     "Section 04 marks more than one employer Current",
     "sections/income._employer: exactly one row may wear Current."),
    ("recompute.returns_pill", FAIL, "recompute",
     "Section 05 pill disagrees with paymentOrder and sectionStatus",
     "sections/returns._aside/_section_requested/_flag_conflict."),
    ("recompute.facility_chips", FAIL, "recompute",
     "Section 06 header chips disagree with contractsTotalSummary",
     "sections/facilities._aside: Total exposure always stated, Guaranteed "
     "chips only when non-zero, Newest facility date."),
    ("recompute.facility_cards", FAIL, "recompute",
     "Section 06 category card headline disagrees with its summary row",
     "sections/facilities._card/_headline: main-holder Balance from "
     "contractsFinancialSummary role A; a card may say 'No facilities' only "
     "when the category is genuinely empty."),
    ("recompute.contract_counts", FAIL, "recompute",
     "Section 07 'N Active · M Closed' disagrees with ActiveFlag",
     "sections/detail.render; closure is ActiveFlag's business alone."),
    ("recompute.heatmap_bucket", FAIL, "recompute",
     "A contract sits in the wrong section 07 block",
     "render/js.py _heatmap/_in_arrears/_closed_recently: Active, Closed in "
     "window, Closed beyond (incl. undated), quiet Services."),
    ("recompute.applications_pill", FAIL, "recompute",
     "Section 08 pill or row-count tag disagrees with the payload",
     "sections/applications._aside: delivered Applications90D graded by "
     "bands.json, plus the 'N rows in window' tag only on a mismatch "
     "(strictly under 90 days)."),

    # --- page hygiene --------------------------------------------------------
    ("hygiene.structure", FAIL, "hygiene",
     "Sections missing, repeated or out of order",
     "render/sections/__init__.py SECTIONS and render_all."),
    ("hygiene.token", FAIL, "hygiene",
     "Visible text or a hover leaks None / NaN / undefined / a format code",
     "A value reached the page unformatted. The finding names the section "
     "and the text around it; search the section module for the label."),
    ("hygiene.empty_value", FAIL, "hygiene",
     "A value slot rendered empty",
     "An empty <span class=\"v\">, <b> or pill. Absence must be stated "
     "('Not reported'), never a blank."),
    ("hygiene.negative", FAIL, "hygiene",
     "A negative duration or age on screen",
     "Usually a date after the report date fed into an age/months "
     "calculation. dates.months_between clamps; days arithmetic does not."),
    ("hygiene.sci_notation", FAIL, "hygiene",
     "A number printed in scientific notation",
     "A float reached the page through str() instead of format_number()."),
    ("hygiene.markup", FAIL, "hygiene",
     "Unbalanced tags or duplicate element ids",
     "Broken nesting shifts every section below it; a duplicate id breaks "
     "report.js lookups. The finding names the first offending tag."),
    ("hygiene.blob", FAIL, "hygiene",
     "The window.__AECB blob is missing, invalid, or carries NaN/None",
     "render/js.py build_data. json.dumps writes NaN for a float nan, which "
     "report.js then prints."),

    # --- vocabulary / config gaps --------------------------------------------
    ("vocab.status", WARN, "vocabulary",
     "Contract status not in config/status_codes.json",
     "Renders as the unknown '?' (never clean). Add the code if AECB "
     "publishes it; it may also be new bureau vocabulary."),
    ("vocab.role", WARN, "vocabulary",
     "Role text not in status_codes.json role_labels",
     "Shown as delivered, never assumed main holder."),
    ("vocab.frequency", WARN, "vocabulary",
     "PaymentFrequency not in status_codes.json frequency",
     "Shown as delivered text in section 07."),
    ("vocab.phase", WARN, "vocabulary",
     "Application Phase not in status_codes.json application_phases",
     "Drawn dashed as 'Other phase' in section 08."),
    ("vocab.category", WARN, "vocabulary",
     "ContractCategory outside I / C / N / S",
     "aecb/loader.py CATEGORY_CANON. Section 06 and 07 only know the four "
     "letters -- see nodrop.* findings for what that loses."),
    ("vocab.active_flag", WARN, "vocabulary",
     "ActiveFlag other than Active / Closed",
     "derive/facilities.is_closed treats anything but 'Closed' as open."),
    ("vocab.returns", WARN, "vocabulary",
     "paymentOrder Type or Severity not in config/returns.json",
     "Unknown Type lands under 'Other instruments'; unknown Severity renders "
     "neutral."),
    ("vocab.score_band", WARN, "vocabulary",
     "FH band or AECB range letter not in config/bands.json",
     "The chip shows the delivered code, uncoloured."),
    ("vocab.resident", WARN, "vocabulary",
     "ResidentFlag not a recognised spelling",
     "Section 01 shows 'Residency: <value>' in grey."),
    ("vocab.info_type", WARN, "vocabulary",
     "identification InfoType other than EmiratesId / Passport",
     "Section 01 has tiles for those two only; check_report will FAIL if the "
     "value never reaches the page."),
    ("vocab.provider", INFO, "vocabulary",
     "Provider codes not in config/providers.json",
     "providers.json is a stub by decision; codes show as names."),

    # --- dates ---------------------------------------------------------------
    ("dates.unparseable", WARN, "dates",
     "A date the code reads does not parse",
     "aecb/dates.parse_any knows ISO, 'DD Month YYYY', DD/MM/YYYY, "
     "DD-MM-YYYY and DDMMYY. A new shape means the field silently reads as "
     "absent."),
    ("dates.future", WARN, "dates",
     "Event dated after the report date",
     "Timelines clamp or extend around it. Often the enquiry-dated report on "
     "a stale pull; otherwise a bureau data error."),
    ("dates.no_report_date", WARN, "dates",
     "No enquiry date and no pull date: nothing anchors the page",
     "Every windowed element degrades to its unanchored state by design. "
     "Confirm the API really delivered neither."),

    # --- browser -------------------------------------------------------------
    ("browser.js_error", FAIL, "browser",
     "report.js raised while drawing the page",
     "Sections 07/08 are drawn client-side from the blob. The message is the "
     "browser's; reproduce by opening the saved page with devtools."),
    ("browser.token", FAIL, "browser",
     "Client-drawn text leaks undefined / NaN / null / [object Object]",
     "report.js rowHtml/applicationTimeline printed a blob key that was "
     "missing or not the type it expects."),
    ("browser.counts", FAIL, "browser",
     "The browser drew a different number of rows/markers than the blob holds",
     "report.js heatmap()/applicationTimeline()."),
    ("browser.overflow", WARN, "browser",
     "The page scrolls sideways at the design width",
     "A long value pushed a fixed-width element. Check report.css for the "
     "section the widest element sits in."),

    # --- baseline ------------------------------------------------------------
    ("baseline.changed", WARN, "baseline",
     "Derived facts changed since the approved baseline",
     "Expected after an intentional change: review the diff and re-approve "
     "with --approve. Unexpected: a regression."),
    ("baseline.new", INFO, "baseline",
     "No approved baseline for this payload yet",
     "Review the page, then run with --approve to record it."),
)

CHECKS = dict((row[0], Check(*row)) for row in _CHECKS)


def get(check_id):
    return CHECKS[check_id]


def listing():
    """Human-readable catalogue for --list-checks."""
    lines = []
    for sev in SEVERITIES:
        for chk in (c for c in CHECKS.values() if c.severity == sev):
            lines.append("%-5s %-32s %s" % (sev, chk.id, chk.title))
    return "\n".join(lines)
