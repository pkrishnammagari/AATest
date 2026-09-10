"""ReportContext -- the single object every section renderer receives.

Carries the normalised payload arrays, the resolved report date, and the config
lookups that the payload itself does not supply (provider names, AECB status
code table, score bands). Section renderers take a ReportContext and nothing
else, so adding a data source never changes nine function signatures.
"""

from __future__ import annotations

import json
import os

from . import dates, loader

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(os.path.dirname(_HERE), "config")



def _load_config(name: str) -> dict:
    """Parsed config/<name>. A missing or unreadable file RAISES.

    Degrading to {} here once made a deleted status_codes.json render every
    status as clean -- the report stayed plausible while all its severity
    vocabulary was gone. Config absence is a deployment fault and must be loud.
    """
    path = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Missing config file %s -- the report cannot be rendered "
            "trustworthily without it." % path)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class ReportContext:
    """Everything a section needs to render itself."""

    def __init__(self, data: dict, source_name: str = ""):
        self.data = data
        self.source_name = source_name

        self.providers = _load_config("providers.json")
        self.status_codes = _load_config("status_codes.json")
        self.bands = _load_config("bands.json")
        # How to read GrossAnnualIncome: currency, the placeholder floor and
        # the confirmation window. All three are policy, not payload.
        self.income_cfg = _load_config("income.json")
        # paymentOrder vocabularies: Type text -> instrument kind, Severity
        # text -> display tone. Policy, since AECB delivers bare display text.
        self.returns_cfg = _load_config("returns.json")

        # Reverse map: the payload delivers contract status as display text
        # ('Active Payments') while the heatmap works in letter codes ('U').
        self._status_by_label = {}
        for code, meta in (self.status_codes.get("codes") or {}).items():
            label = (meta.get("label") or "").strip().lower()
            if label:
                self._status_by_label[label] = code

    # --- array accessors ----------------------------------------------------

    def rows(self, name: str) -> list:
        return self.data.get(name) or []

    @property
    def summary(self) -> dict:
        return loader.first(self.rows("summary"))

    @property
    def customer(self) -> dict:
        return loader.first(self.rows("customerInfo"))

    @property
    def score(self) -> dict:
        return loader.first(self.rows("score"))

    @property
    def totals(self) -> dict:
        return loader.first(self.rows("contractsTotalSummary"))

    # --- resolved report date ----------------------------------------------

    def enquiry_anchor(self) -> dict:
        """The report's anchor date, and the enquiry behind it.

        One ladder for the whole page, read generically (user decision,
        10 Sep 2026 -- no hard-coded ReportType vocabulary, so a product the
        bureau adds later, e.g. plain "ConsumerLong", dates the report
        without a code change):

            1. every sectionStatus row is a candidate; the one with the
               LATEST parseable 'Last EnquiryDate' (the field name carries
               the internal space) wins. Array order breaks ties, since
               parse_any truncates the timestamp to a date;
            2. no row with a usable date -> score.DataPullDate, a fallback
               only, never first;
            3. nothing at all -> date None.

        Returns {'date', 'basis' ('enquiry' | 'pull' | None), 'report_type',
                 'enquiry_type'}. The type strings come verbatim from the
        winning row -- or from the first row when rows exist but none is
        dated, so the top bar can still chip the scope while the pull date
        does the dating -- and are "" when sectionStatus is empty.

        On stale archive payloads the enquiry date can post-date the pull by
        months (reference fixture: enquiry 2024-08-20 vs pull 2023-10-26),
        which shifts every window on the page forward accordingly -- accepted
        explicitly as part of the 10 Sep decision.
        """
        rows = self.rows("sectionStatus")
        best_row = best_date = None
        for row in rows:
            parsed = dates.parse_any(row.get("Last EnquiryDate"))
            if parsed and (best_date is None or parsed > best_date):
                best_row, best_date = row, parsed

        scope_row = best_row if best_row is not None else \
            (rows[0] if rows else None)
        out = {
            "date": None, "basis": None,
            "report_type": (str(scope_row.get("ReportType") or "").strip()
                            if scope_row else ""),
            "enquiry_type": (str(scope_row.get("EnquiryType") or "").strip()
                             if scope_row else ""),
        }

        if best_date is not None:
            out["date"], out["basis"] = best_date, "enquiry"
            return out
        parsed = dates.parse_any(self.score.get("DataPullDate"))
        if parsed:
            out["date"], out["basis"] = parsed, "pull"
        return out

    @property
    def report_date(self):
        """The date the report is measured against: enquiry_anchor()'s date.

        The enquiry ladder, everywhere -- windows, heatmap month arithmetic,
        age and expiry checks, and the validity strip all age the same date,
        by decision (10 Sep 2026). None when the ladder is empty: the top bar
        says "Validity unknown" and every windowed section renders its own
        no-report-date state.
        """
        return self.enquiry_anchor()["date"]

    @property
    def unknown_arrays(self) -> list:
        """Top-level payload sections the loader does not recognise.

        Computed by loader.normalise(); surfaced so a new AECB section is a
        visible warning in the app rather than silently unrendered data.
        """
        return self.data.get("_unknownArrays") or []

    @property
    def subject_id(self) -> str:
        return str(
            self.customer.get("CBSubjectId")
            or self.customer.get("PKSubjectId")
            or self.summary.get("PKSubjectId")
            or "unknown"
        )

    # --- config lookups -----------------------------------------------------

    def provider(self, code) -> dict:
        """Display name and badge kind for a provider code.

        Unknown codes fall back to the code itself with a neutral badge, so a
        provider missing from config/providers.json degrades to the raw value
        rather than blanking the row.
        """
        if not code:
            return {"name": "—", "kind": "bank", "code": ""}
        code = str(code).strip()
        entry = (self.providers.get("providers") or {}).get(code)
        if entry:
            return {
                "name": entry.get("name") or code,
                "kind": entry.get("kind") or "bank",
                "code": code,
            }
        # Telecom providers are coded T##, credit providers B##.
        kind = "tel" if code.upper().startswith("T") else "bank"
        return {"name": code, "kind": kind, "code": code}

    def status(self, value) -> dict:
        """Resolve a contract status, given either a letter code or display text.

        Returns {'code', 'label', 'rank'}. Rank drives the colour band:
        <=60 severe, 65-95 adverse, 100 normal. Rank None means the config
        does not know this status -- new AECB vocabulary, or nothing delivered
        at all -- and the renderer paints it as UNKNOWN, never as clean. The
        code for an unknown status is always '?': inventing a letter from the
        text used to collide with real codes ('Closed' -> 'C', which is
        Settlement's glyph).
        """
        codes = self.status_codes.get("codes") or {}
        if not value:
            return {"code": "?", "label": "Not reported", "rank": None}
        text = str(value).strip()

        if text in codes:
            meta = codes[text]
            return {"code": text, "label": meta.get("label", text),
                    "rank": meta.get("rank", 100)}

        code = self._status_by_label.get(text.lower())
        if code:
            meta = codes[code]
            return {"code": code, "label": meta.get("label", text),
                    "rank": meta.get("rank", 100)}

        return {"code": "?", "label": text, "rank": None}


def from_file(path: str) -> ReportContext:
    return ReportContext(loader.load(path), source_name=os.path.basename(path))


def from_bytes(raw, source_name: str = "upload") -> ReportContext:
    return ReportContext(loader.loads(raw), source_name=source_name)
