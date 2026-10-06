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



def _require_positive(cfg: dict, key: str, fname: str, what: str,
                      integer: bool = True):
    """A policy number with no safe default: present, numeric, above zero.

    A silent fallback would let a deleted validity window read as a default
    and a deleted placeholder floor switch its check off -- the report would
    stay plausible while its policy was gone. Loud, like a missing config
    file.
    """
    value = cfg.get(key)
    ok_type = int if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, ok_type) or value <= 0:
        raise ValueError(
            "config/%s %s must be %s above zero (got %r) -- %s"
            % (fname, key, "a whole number" if integer else "a number",
               value, what))
    return value


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_score_bands(bands: dict) -> None:
    """config/bands.json scale and fh_bands: numeric, ordered, complete.

    A band without a numeric `from`, or bands out of order, would otherwise
    raise mid-render or silently misplace the score on the dial.
    """
    scale = bands.get("scale")
    if (not isinstance(scale, dict) or not _is_number(scale.get("min"))
            or not _is_number(scale.get("max"))
            or scale["min"] >= scale["max"]):
        raise ValueError("config/bands.json scale must be {\"min\": n, "
                         "\"max\": n} with min below max (got %r)." % (scale,))
    previous = None
    for i, band in enumerate(bands.get("fh_bands") or []):
        start = band.get("from") if isinstance(band, dict) else None
        if not band.get("code") or not _is_number(start):
            raise ValueError("config/bands.json fh_bands[%d] needs a code and "
                             "a numeric 'from' (got %r)." % (i, band))
        if previous is not None and start <= previous:
            raise ValueError("config/bands.json fh_bands must be in ascending "
                             "'from' order (fh_bands[%d] from %r)." % (i, start))
        previous = start


def _validate_status_codes(status_codes: dict) -> None:
    """Every configured status code carries a whole-number rank, and the
    severity cut-offs are whole numbers in order.

    Defaulting a missing rank to normal would let a configuration slip
    render an adverse status as clean conduct.
    """
    severity = status_codes.get("severity")
    if (not isinstance(severity, dict)
            or not all(isinstance(severity.get(k), int)
                       and not isinstance(severity.get(k), bool)
                       for k in ("severe_max", "normal_min"))
            or severity["severe_max"] >= severity["normal_min"]):
        raise ValueError("config/status_codes.json severity must be "
                         "{\"severe_max\": n, \"normal_min\": m} with whole "
                         "numbers n < m (got %r)." % (severity,))
    for code, meta in (status_codes.get("codes") or {}).items():
        if code.startswith("_"):
            continue
        rank = meta.get("rank") if isinstance(meta, dict) else None
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise ValueError("config/status_codes.json codes.%s needs a whole-"
                             "number rank (got %r)." % (code, rank))


def _load_config(name: str) -> dict:
    """Parsed config/<name>. A missing or unreadable file RAISES.

    Degrading to {} would let a deleted status_codes.json render every
    status as clean -- the report would stay plausible while its severity
    vocabulary was gone. Config absence is a deployment fault and must be loud.
    """
    path = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Missing config file %s -- the report cannot be rendered "
            "trustworthily without it." % path)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_optional_config(name: str):
    """Parsed config/<name>, or None when the file does not exist.

    For the one optional config (macro_context.json): absence is a choice,
    but a file that exists and does not parse still raises.
    """
    path = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class ReportContext:
    """Everything a section needs to render itself."""

    def __init__(self, data: dict, source_name: str = ""):
        self.data = data
        self.source_name = source_name

        self.providers = _load_config("providers.json")
        self.status_codes = _load_config("status_codes.json")
        _validate_status_codes(self.status_codes)
        self.bands = _load_config("bands.json")
        _validate_score_bands(self.bands)
        # Policy numbers with no safe default are validated at load, so a
        # deleted or malformed key stops the render instead of degrading it.
        _require_positive(self.bands, "validity_days", "bands.json",
                          "report validity cannot be graded without it.")
        _require_positive(self.bands, "closed_window_months", "bands.json",
                          "recently closed facilities cannot be told from "
                          "older closures without it.")
        red = _require_positive(self.bands, "applications_90d_red",
                                "bands.json", "the applications pill cannot "
                                "be graded without it.")
        amber = _require_positive(self.bands, "applications_90d_amber",
                                  "bands.json", "the applications pill "
                                  "cannot be graded without it.")
        if amber > red:
            raise ValueError("config/bands.json applications_90d_amber (%d) "
                             "must not exceed applications_90d_red (%d)."
                             % (amber, red))
        # How to read GrossAnnualIncome: currency, the placeholder floor and
        # the confirmation window. All three are policy, not payload.
        self.income_cfg = _load_config("income.json")
        _require_positive(self.income_cfg, "placeholder_floor", "income.json",
                          "placeholder income figures cannot be told from "
                          "real ones without it.", integer=False)
        _require_positive(self.income_cfg, "confirmation_window_months",
                          "income.json", "stale employment records cannot "
                          "be recognised without it.")
        currency = self.income_cfg.get("currency")
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError("config/income.json currency must be a non-empty "
                             "string (got %r)." % (currency,))
        # paymentOrder vocabularies: Type text -> instrument kind, Severity
        # text -> display tone. Policy, since AECB delivers bare display text.
        self.returns_cfg = _load_config("returns.json")
        _require_positive(self.returns_cfg, "window_months", "returns.json",
                          "recent returns cannot be told from earlier ones "
                          "without it.")

        # Reverse map: the payload delivers contract status as display text
        # ('Active Payments') while the heatmap works in letter codes ('U').
        self._status_by_label = {}
        for code, meta in (self.status_codes.get("codes") or {}).items():
            label = _normalize_label(meta.get("label") or "")
            if label:
                self._status_by_label[label] = code

        # Same for application phases: 'Requested ' (sic, trailing space) in
        # the archive, the letter code 'R' from other feeds.
        self._phases = {
            code: label for code, label in
            (self.status_codes.get("application_phases") or {}).items()
            if not code.startswith("_")}
        self._phase_by_label = {label.strip().lower(): code
                                for code, label in self._phases.items()}

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

        One ladder for the whole page, read generically -- no hard-coded
        ReportType vocabulary, so a product the bureau adds later (e.g. plain
        "ConsumerLong") dates the report without a code change:

            1. every sectionStatus row is a candidate; the one with the
               LATEST parseable 'Last EnquiryDate' (the field name carries
               the internal space) wins. Array order breaks ties, since
               parse_any truncates the timestamp to a date;
            2. no row with a usable date -> score.DataPullDate, a fallback
               only, never first;
            3. nothing at all -> date None.

        Returns {'date', 'basis' ('enquiry' | 'pull' | None), 'report_type',
                 'enquiry_type', 'enquiry_no', 'scope_source'}. The type
        strings and EnquiryNo come verbatim from the winning row -- or from
        the first row when rows exist but none is dated, so the top bar can
        still chip the scope while the pull date does the dating -- and are
        "" when sectionStatus is empty. scope_source says which: 'dated'
        (the winning row), 'first' (no row dated) or None (no rows).

        On stale archive payloads the enquiry date can post-date the pull by
        months (reference fixture: enquiry 2024-08-20 vs pull 2023-10-26),
        which shifts every window on the page forward accordingly -- accepted
        by decision (docs/DECISIONS.md).
        """
        rows = self.rows("sectionStatus")
        best_row, best_date = _latest_enquiry(rows)
        if best_row is not None:
            scope_row, scope_source = best_row, "dated"
        elif rows:
            scope_row, scope_source = rows[0], "first"
        else:
            scope_row, scope_source = {}, None
        out = {
            "date": None, "basis": None,
            "report_type": _text(scope_row.get("ReportType")),
            "enquiry_type": _text(scope_row.get("EnquiryType")),
            "enquiry_no": _text(scope_row.get("EnquiryNo")),
            "scope_source": scope_source,
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
        age and expiry checks, and the validity strip all age the same date.
        None when the ladder is empty: the top bar says "Validity unknown" and
        every windowed section renders its own no-report-date state.
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
    def dropped_rows(self) -> dict:
        """{array name: count} of rows the loader could not read as objects."""
        return self.data.get("_droppedRows") or {}

    @property
    def cb_subject_id(self):
        """The bureau's subject id, or None when the payload carries none.

        customerInfo first; sectionStatus rows carry the same bureau id, so
        they stand in when customerInfo omits it. Never a warehouse key --
        callers that display this label it as the CB subject id.
        """
        value = self.customer.get("CBSubjectId")
        if value:
            return str(value)
        for row in self.rows("sectionStatus"):
            if row.get("CBSubjectId"):
                return str(row["CBSubjectId"])
        return None

    @property
    def subject_id(self) -> str:
        """Best available identifier for titles, file names and logs.

        The bureau id when delivered; the warehouse PKSubjectId only as a
        last resort; "unknown" when neither arrived.
        """
        return str(
            self.cb_subject_id
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
        # Telecom providers are coded T##, non-bank lenders N##, banks B##.
        prefix = code.upper()[:1]
        kind = {"T": "tel", "N": "nbfi"}.get(prefix, "bank")
        return {"name": code, "kind": kind, "code": code}

    def status(self, value) -> dict:
        """Resolve a contract status, given either a letter code or display text.

        Returns {'code', 'label', 'rank'}. Rank drives the colour band (see
        severity()). Rank None means the config
        does not know this status -- new AECB vocabulary, or nothing delivered
        at all -- and the renderer paints it as UNKNOWN, never as clean. The
        code for an unknown status is always '?': a letter invented from the
        text could collide with a real code ('Closed' -> 'C', which is
        Settlement's glyph).
        """
        codes = self.status_codes.get("codes") or {}
        if not value:
            return {"code": "?", "label": "Not reported", "rank": None}
        text = str(value).strip()

        # Ranks are validated at load (_validate_status_codes).
        if text in codes:
            meta = codes[text]
            return {"code": text, "label": meta.get("label", text),
                    "rank": meta["rank"]}

        code = self._status_by_label.get(_normalize_label(text))
        if code:
            meta = codes[code]
            return {"code": code, "label": meta.get("label", text),
                    "rank": meta["rank"]}

        return {"code": "?", "label": text, "rank": None}

    def severity(self, rank) -> str:
        """'severe' | 'adverse' | 'normal' for a status rank, 'unknown' for
        None -- by the cut-offs in config/status_codes.json `severity`."""
        if rank is None:
            return "unknown"
        cut = self.status_codes["severity"]
        if rank <= cut["severe_max"]:
            return "severe"
        return "adverse" if rank < cut["normal_min"] else "normal"

    def phase(self, value) -> dict:
        """Resolve an application phase, given either its code or description.

        Returns {'code', 'label'}: code is one of the configured letters
        (B Disbursed, D Declined, J Rejected, N Not taken up, R Requested),
        or None for nothing delivered or a phase the config does not know --
        whose label is then the delivered text, never a guess.
        """
        text = str(value or "").strip()
        if not text:
            return {"code": None, "label": "Not reported"}
        code = (text.upper() if text.upper() in self._phases
                else self._phase_by_label.get(text.lower()))
        if code:
            return {"code": code, "label": self._phases[code]}
        return {"code": None, "label": text}


def _text(value) -> str:
    return str(value or "").strip()


def _normalize_label(text) -> str:
    """A status label reduced for matching: hyphens read as spaces, runs of
    whitespace collapse to one, case ignored. AECB delivers 'Write Off'
    where its published table (and the config) says 'Write-off'."""
    return " ".join(str(text).replace("-", " ").split()).lower()


def _latest_enquiry(rows):
    """(row, date) of the latest parseable 'Last EnquiryDate'; array order
    breaks ties. (None, None) when no row is dated."""
    best_row = best_date = None
    for row in rows:
        parsed = dates.parse_any(row.get("Last EnquiryDate"))
        if parsed and (best_date is None or parsed > best_date):
            best_row, best_date = row, parsed
    return best_row, best_date


_IDENTIFYING_ARRAYS = ("customerInfo", "summary", "score")


def require_aecb_payload(ctx: ReportContext) -> ReportContext:
    """ctx, or ValueError when the document is not an AECB payload.

    loader.normalise() guarantees every array exists, so well-formed JSON that
    is not an AECB payload parses cleanly into an empty report. At least one
    of the arrays that identify the subject must carry a row.
    """
    if not any(ctx.rows(key) for key in _IDENTIFYING_ARRAYS):
        raise ValueError("the document parsed, but carries no customerInfo, "
                         "summary or score -- it does not look like an AECB "
                         "payload")
    return ctx


def from_file(path: str) -> ReportContext:
    return ReportContext(loader.load(path), source_name=os.path.basename(path))


def from_bytes(raw, source_name: str = "upload") -> ReportContext:
    return ReportContext(loader.loads(raw), source_name=source_name)
