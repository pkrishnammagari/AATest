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
    path = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class ReportContext(object):
    """Everything a section needs to render itself."""

    def __init__(self, data: dict, source_name: str = ""):
        self.data = data
        self.source_name = source_name

        self.providers = _load_config("providers.json")
        self.status_codes = _load_config("status_codes.json")
        self.bands = _load_config("bands.json")
        # How to read GrossAnnualIncome: currency, the placeholder floor and the
        # provider-disagreement ratio. All three are policy, not payload.
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

    @property
    def report_date(self):
        """The date the report is measured against.

        score.DataPullDate -- when AECB was actually queried. Chosen over
        ArchiveDate (a warehouse write timestamp) and sectionStatus's
        'Last EnquiryDate' (which can post-date the contract data by months)
        because it is the only one consistent with contracts.ReferenceDate and
        the newest contractsHistory month.
        """
        for candidate in (
            self.score.get("DataPullDate"),
            self.score.get("ArchiveDate"),
            self.customer.get("ArchiveDate"),
        ):
            parsed = dates.parse_any(candidate)
            if parsed:
                return parsed
        return None

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
        <=60 severe, 65-95 adverse, 100 normal.
        """
        codes = self.status_codes.get("codes") or {}
        if not value:
            return {"code": "?", "label": "Not reported", "rank": 100}
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

        return {"code": text[:1].upper() or "?", "label": text, "rank": 100}


def from_file(path: str) -> ReportContext:
    return ReportContext(loader.load(path), source_name=os.path.basename(path))


def from_bytes(raw, source_name: str = "upload") -> ReportContext:
    return ReportContext(loader.loads(raw), source_name=source_name)
