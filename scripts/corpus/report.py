"""Writes the corpus report: summary.md for reading, results.json for tools.

summary.md is written to be triaged from -- by you, or by Claude Code working
through scripts/corpus/TRIAGE.md. It leads with the checks that failed (one
root cause usually fails many payloads, so fix by check, not by file), then
every finding per payload with the rerun command, then the corpus-wide views
no single payload shows: config gaps, schema drift, variant coverage and the
baseline.

Python 3.9 compatible.
"""

from __future__ import annotations

import collections
import json
import os

from . import profile, registry

_ORDER = registry.RANK


def status_of(result):
    """ERROR / FAIL / WARN, or 'ok' when only INFO (or nothing) was found."""
    worst = "ok"
    for f in result["findings"]:
        if f["severity"] == registry.INFO:
            continue
        if worst == "ok" or _ORDER[f["severity"]] < _ORDER[worst]:
            worst = f["severity"]
    return worst


def _md(text):
    """Escape a value for a markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _rel(path, repo):
    try:
        rel = os.path.relpath(path, repo)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel


def write(run, out_dir, repo):
    os.makedirs(out_dir, exist_ok=True)
    results = run["results"]
    for r in results:
        r["status"] = status_of(r)

    clean = []
    for r in results:
        r2 = dict(r)
        r2.pop("html", None)
        r2.pop("delivered", None)
        clean.append(r2)
    payload = dict(run)
    payload["results"] = clean
    payload["checks"] = [c.as_dict() for c in registry.CHECKS.values()]
    payload["features"] = profile.catalogue()
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False, default=str)

    md = _summary(run, results, out_dir, repo)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    return os.path.join(out_dir, "summary.md")


def _summary(run, results, out_dir, repo):
    meta = run["meta"]
    counts = collections.Counter(r["status"] for r in results)
    verdict = ("FAIL" if counts["ERROR"] or counts["FAIL"] else
               "WARN" if counts["WARN"] else "PASS")
    L = []
    L.append("# Corpus test report — %s" % meta["app"])
    L.append("")
    L.append("- **Run**: %s · git `%s`%s" % (
        meta["started"], meta["git"], " (with uncommitted changes)"
        if meta.get("dirty") else ""))
    L.append("- **Payloads**: %d file(s) in `%s`%s" % (
        len(results), _rel(meta["dir"], repo),
        (" (filtered by `--only %s`)" % meta["only"]) if meta.get("only") else ""))
    b = run["browser"]
    L.append("- **Browser pass**: %s" % (
        "on — %s%s" % (b.get("chrome"), (", %d page(s) could not be probed"
                                          % b["failures"]) if b.get("failures")
                       else "") if b["status"] == "on" else
        "off (%s)" % b.get("reason", "--browser off")))
    base = run["baseline"]
    L.append("- **Baseline**: %s" % base["summary"])
    L.append("- **Verdict**: **%s** — %d ERROR · %d FAIL · %d WARN · %d clean"
             % (verdict, counts["ERROR"], counts["FAIL"], counts["WARN"],
                counts["ok"]))
    L.append("")
    # The link is relative to summary.md itself, so it opens from the editor.
    triage = os.path.relpath(os.path.join(repo, "scripts", "corpus", "TRIAGE.md"),
                             out_dir)
    L.append("Triage playbook: [`scripts/corpus/TRIAGE.md`](%s). Rerun one "
             "payload: `python3 scripts/check_corpus.py --dir %s --only <file>`."
             % (triage, _rel(meta["dir"], repo)))
    L.append("")

    # 1. by check -------------------------------------------------------------
    by_check = collections.OrderedDict()
    for r in results:
        for f in r["findings"]:
            by_check.setdefault(f["check"], []).append((r, f))
    L.append("## 1. Findings by check")
    L.append("")
    problem_checks = [c for c in by_check
                      if registry.get(c).severity != registry.INFO]
    if not problem_checks:
        L.append("No ERROR, FAIL or WARN findings.")
    else:
        L.append("Fix by check, not by file: one root cause usually fails many "
                 "payloads. Most severe first.")
        L.append("")
        L.append("| Sev | Check | Payloads | What it means | Start at |")
        L.append("|---|---|---|---|---|")
        for cid in sorted(problem_checks, key=lambda c: (
                _ORDER[registry.get(c).severity],
                -len(set(r["file"] for r, _f in by_check[c])), c)):
            chk = registry.get(cid)
            n = len(set(r["file"] for r, _f in by_check[cid]))
            L.append("| %s | `%s` | %d | %s | %s |" % (
                chk.severity, cid, n, _md(chk.title), _md(chk.hint)))
    L.append("")

    # 2. by payload -------------------------------------------------------------
    L.append("## 2. Findings by payload")
    L.append("")
    flagged = [r for r in results if r["status"] != "ok"]
    flagged.sort(key=lambda r: (_ORDER[r["status"]], r["file"]))
    if not flagged:
        L.append("Every payload is clean.")
    for r in flagged:
        L.append("### `%s` — %s" % (r["file"], r["status"]))
        L.append("")
        extra = []
        if r.get("page_file"):
            extra.append("page: `%s`" % _rel(r["page_file"], repo))
        if r.get("render_ms") is not None:
            extra.append("render %.0f ms" % r["render_ms"])
        extra.append("rerun: `--only %s`" % r["file"])
        L.append(" · ".join(extra))
        L.append("")
        for f in sorted(r["findings"], key=lambda f: (_ORDER[f["severity"]],
                                                      f["check"])):
            if f["severity"] == registry.INFO:
                continue
            where = " [%s]" % f["section"] if f.get("section") else ""
            L.append("- **%s** `%s`%s — %s" % (f["severity"], f["check"], where,
                                               f["message"]))
            if f.get("details"):
                if f["check"].startswith(("render.", "load.context")):
                    L.append("  ```")
                    L.extend("  " + d for d in f["details"])
                    L.append("  ```")
                else:
                    L.extend("  - %s" % d for d in f["details"])
        for err in r.get("harness_errors") or []:
            L.append("- **HARNESS** — %s" % err.splitlines()[0])
        L.append("")
    ok = sorted(r["file"] for r in results if r["status"] == "ok")
    if ok:
        L.append("**Clean (%d):** %s" % (len(ok), ", ".join("`%s`" % f for f in ok)))
        L.append("")

    # 3. vocabulary across the corpus -------------------------------------------
    L.append("## 3. Config and vocabulary gaps across the corpus")
    L.append("")
    vocab = collections.OrderedDict()
    providers = collections.defaultdict(set)
    for r in results:
        for f in r["findings"]:
            for v in ((f.get("data") or {}).get("values") or []):
                if f["check"] == "vocab.provider":
                    providers[str(v["value"])].add(r["file"])
                    continue
                key = (f["check"], v["field"], str(v["value"]))
                slot = vocab.setdefault(key, {"count": 0, "files": set()})
                slot["count"] += v["count"]
                slot["files"].add(r["file"])
    if providers:
        L.append("Provider codes not in `config/providers.json` (a stub by "
                 "decision, so these show as codes): %s." % ", ".join(
                     "%s (%d)" % (code, len(files)) for code, files in
                     sorted(providers.items(), key=lambda kv: -len(kv[1]))))
        L.append("")
    if not vocab:
        L.append("No other gaps — every other delivered value the config maps "
                 "was recognised.")
    else:
        L.append("One row per distinct value: add it to the config, or record "
                 "why not.")
        L.append("")
        L.append("| Check | Field | Value | Occurrences | Payloads | Example |")
        L.append("|---|---|---|---|---|---|")
        for (cid, field, value), slot in sorted(
                vocab.items(), key=lambda kv: (kv[0][0], -len(kv[1]["files"]))):
            L.append("| `%s` | `%s` | %s | %d | %d | `%s` |" % (
                cid, field, _md(value), slot["count"], len(slot["files"]),
                sorted(slot["files"])[0]))
    L.append("")

    # 4. schema drift --------------------------------------------------------------
    L.append("## 4. Schema drift")
    L.append("")
    drift = run.get("schema_drift") or []
    if not drift:
        L.append("No field appears that the committed fixtures or the code do "
                 "not already know.")
    else:
        L.append("Fields in these payloads that neither the committed fixtures "
                 "nor any string in `aecb/` mention. The page never reads them — "
                 "decide whether it should.")
        L.append("")
        L.append("| Field | Payloads | Example |")
        L.append("|---|---|---|")
        for d in drift:
            L.append("| `%s` | %d | `%s` |" % (d["field"], d["payloads"], d["example"]))
    L.append("")

    # 5. coverage ----------------------------------------------------------------
    L.append("## 5. Variant coverage")
    L.append("")
    have = collections.defaultdict(list)
    for r in results:
        for key in r.get("features") or []:
            have[key].append(r["file"])
    L.append("How many payloads exercise each path the report can take. Rows "
             "with 0 are paths no real payload has hit — still covered only by "
             "the synthetic fixtures and `scripts/measure/synthetic.py`.")
    L.append("")
    L.append("| Section | Variant | Payloads | Examples |")
    L.append("|---|---|---|---|")
    unseen = []
    for feat in profile.catalogue():
        files = have.get(feat["key"], [])
        if not files:
            unseen.append(feat)
        L.append("| %s | %s <br>`%s` | %d | %s |" % (
            feat["section"], _md(feat["label"]), feat["key"], len(files),
            ", ".join("`%s`" % f for f in sorted(files)[:3]) +
            (" …" if len(files) > 3 else "")))
    L.append("")
    if unseen:
        L.append("**Not exercised by any payload (%d):** %s" % (
            len(unseen), "; ".join(f["label"] for f in unseen)))
        L.append("")

    # 6. baseline ------------------------------------------------------------------
    L.append("## 6. Baseline")
    L.append("")
    L.append(base["summary"] + ".")
    if base.get("path"):
        L.append("")
        L.append("File: `%s`. Approve the current output with `--approve` (all "
                 "payloads, or combine with `--only`)." % _rel(base["path"], repo))
    if base.get("gone"):
        L.append("")
        L.append("In the baseline but no longer in the folder: %s"
                 % ", ".join("`%s`" % g for g in base["gone"]))
    L.append("")

    # 7. harness notes --------------------------------------------------------------
    L.append("## 7. Harness notes")
    L.append("")
    harness = [(r["file"], e) for r in results for e in r.get("harness_errors") or []]
    if harness:
        L.append("A check itself raised on these payloads — a harness bug or a "
                 "payload shape it did not expect. The product was not judged "
                 "on that check:")
        L.append("")
        for name, err in harness:
            L.append("- `%s`:" % name)
            L.append("  ```")
            L.extend("  " + line for line in err.splitlines())
            L.append("  ```")
    else:
        L.append("No check raised.")
    L.append("")
    timed = sorted((r for r in results if r.get("render_ms") is not None),
                   key=lambda r: -r["render_ms"])[:5]
    if timed:
        L.append("Slowest renders: " + ", ".join(
            "`%s` %.0f ms" % (r["file"], r["render_ms"]) for r in timed))
        L.append("")
    return "\n".join(L)
