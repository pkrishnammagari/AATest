"""Corpus harness: run every archived API payload through the report and check it.

scripts/check_corpus.py is the entry point; this package holds its parts.

    registry   the catalogue of checks -- id, severity, what it means, where to look
    pagetext   reading the rendered page: sections, pills, visible text, the blob
    checks     the per-payload checks (load, render, no-drop, recompute, hygiene,
               vocabulary, dates)
    browser    the optional headless-Chrome pass for what report.js draws
    profile    which payload variants each file exercises (the coverage matrix)
    snapshot   derived facts per payload, diffed against an approved baseline
    report     summary.md and results.json
    selftest   proves each check can fire, on mutated copies of the fixtures

Python 3.9 compatible, like the rest of the repo.
"""
