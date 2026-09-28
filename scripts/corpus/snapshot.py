"""Derived facts per payload, and the diff against an approved baseline.

With no answer key for real reports, "the right output" can only mean output
a person has looked at and accepted. So the first run records, per payload, a
small set of facts the page is built from -- report date, score and bands,
the 36-month worst, the income and returns models, where every contract sits
on the heatmap, the pills, a fingerprint of each section's text -- and
`--approve` stores them. Every later run diffs against that: a change you
meant shows up as expected, a change you did not is a regression.

Nothing here depends on today's date (the validity pill is left out on
purpose), so a baseline does not drift by itself.

Python 3.9 compatible.
"""

from __future__ import annotations

import hashlib
import json

from aecb.derive import applications as d_app
from aecb.derive import identity as d_id
from aecb.derive import scoring

from . import pagetext


def _iso(value):
    return value.isoformat() if value else None


def _sha(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _safe(fn):
    try:
        return fn()
    except Exception as exc:   # noqa: BLE001 -- a fact that cannot be built says so
        return "error: %s" % type(exc).__name__


def facts(env):
    """The snapshot for one payload (a plain JSON-able dict)."""
    ctx = env.ctx
    anchor = ctx.enquiry_anchor()
    out = {
        "report_date": _iso(anchor["date"]),
        "report_basis": anchor["basis"],
        "report_type": anchor["report_type"],
        "enquiry_type": anchor["enquiry_type"],
        "score": _safe(lambda: scoring.score_value(ctx)),
        "fh_band": _safe(lambda: (scoring.fh_band(ctx) or {}).get("code")),
        "configured_band": _safe(lambda: scoring.configured_band(ctx)),
        "aecb_band": _safe(lambda: (scoring.aecb_band(ctx) or {}).get("code")),
        "vintage": _safe(lambda: scoring.vintage_band(ctx)["code"]),
        "history_months": _safe(lambda: scoring.history_months(ctx)),
        "worst36": _safe(lambda: _worst(env)),
        "income": _safe(lambda: _income(env)),
        "returns": _safe(lambda: _returns(env)),
        "identity": _safe(lambda: _identity(env)),
    }
    if env.page is not None:
        out["heatmap"] = _safe(lambda: _heatmap(env))
        out["applications"] = _safe(lambda: _applications(env))
        out["pills"] = dict((name, pagetext.text(pagetext.aside(html)))
                            for name, html in sorted(env.page.secs.items()))
        out["section_text"] = dict((name, _sha(pagetext.text(html)))
                                   for name, html in sorted(env.page.secs.items()))
        out["blob"] = _sha(json.dumps(env.blob, sort_keys=True)) \
            if env.blob is not None else None
    return out


def _worst(env):
    w = env.worst
    if w is None:
        return None
    fac = w["facility"]
    return {
        "status": w["status"]["code"] if w["status"] else None,
        "max_dpd": w["max_dpd"],
        "clean": w["clean"],
        "unknown": w["unknown"],
        "facility": fac.id if fac is not None else None,
        "when": _iso(w["when"]),
        "rows": w["reported_months"],
        "covered": "%d/%d" % (w["facilities_covered"], w["facilities_total"]),
    }


def _income(env):
    m = env.income
    latest = m["latest"]
    return {
        "chart": m["chart"],
        "records": len(m["records"]),
        "current": m["current"].name if m["current"] is not None else None,
        "latest_basis": latest["basis"] if latest else None,
        "latest_income": str(latest["record"].income) if latest else None,
        "points": len(m["points"]),
        "placeholders": sum(1 for r in m["records"] if r.placeholder),
    }


def _returns(env):
    m = env.returns
    return {"n": len(m["records"]), "recent": len(m["recent"]),
            "older": len(m["older"]), "undated": len(m["undated"]),
            "chart": m["chart"]}


def _identity(env):
    def split(pair):
        return "%d current / %d prior" % (len(pair[0]), len(pair[1]))
    return {
        "emirates_id": split(env.ids("EmiratesId")),
        "passport": split(env.ids("Passport")),
        "mobile": split(env.contacts("Mobile Number")),
        "landline": split(env.contacts("Phone Number")),
        "email": split(env.contacts("E-mail")),
        "address": split(d_id.addresses(env.ctx)),
    }


def _heatmap(env):
    out = {}
    for block, _cat, row in pagetext.heatmap_rows(env.blob):
        out.setdefault(block, []).append(str(row.get("id")))
    return dict((k, sorted(v)) for k, v in sorted(out.items()))


def _applications(env):
    t = env.timeline
    return {
        "rows": len(env.rows("applications")),
        "events": len(t.get("events") or []),
        "in_90d": len(d_app.in_window(env.ctx, env.rows("applications"))),
        "lanes": t.get("lanes"),
        "split": t.get("split"),
    }


# --- diff -------------------------------------------------------------------

def _flatten(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out.update(_flatten(v, "%s.%s" % (prefix, k) if prefix else str(k)))
        return out
    return {prefix: value}


def _short(value, limit=70):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def diff(old, new):
    """['path: old -> new', ...] for every fact that changed."""
    a, b = _flatten(old or {}), _flatten(new or {})
    out = []
    for key in sorted(set(a) | set(b)):
        if a.get(key, "<absent>") != b.get(key, "<absent>"):
            out.append("%s: %s -> %s" % (key, _short(a.get(key, "<absent>")),
                                         _short(b.get(key, "<absent>"))))
    return out
